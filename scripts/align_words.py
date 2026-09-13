#!/usr/bin/env python3
"""
Alignement mot par mot de paroles (SRT) sur un fichier audio avec WhisperX.

Deux modes :
  - Avec un SRT (recommandé) : on ne transcrit pas, on aligne directement les
    paroles connues sur l'audio (alignement forcé wav2vec2 de WhisperX).
  - Sans SRT : WhisperX transcrit puis aligne.

Sortie : JSON [{"word": ..., "start": "mm:ss:xx", "end": "mm:ss:xx"}, ...]
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Rustines de compatibilité NumPy 2.0 / torchaudio 2.9 : DOIT précéder whisperx.
import _compat  # noqa: F401

import whisperx

SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(path: Path) -> list[dict]:
    """Retourne une liste de segments {"start": s, "end": s, "text": str}."""
    text = path.read_text(encoding="utf-8")
    segments = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.findall(SRT_TIME, lines[1])
        if len(m) != 2:
            continue
        (h1, m1, s1, ms1), (h2, m2, s2, ms2) = m
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000
        segments.append({"start": start, "end": end, "text": " ".join(lines[2:])})
    return segments


def fmt(t: float) -> str:
    """Secondes -> mm:ss:xx (xx = centièmes)."""
    cs_total = int(round(t * 100))
    m, rest = divmod(cs_total, 6000)
    s, cs = divmod(rest, 100)
    return f"{m:02d}:{s:02d}:{cs:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="Fichier audio (wav, mp3, ...)")
    ap.add_argument("-s", "--srt", type=Path, help="Paroles au format SRT (timings de phrase indicatifs)")
    ap.add_argument("-o", "--output", type=Path, default=Path("words.json"))
    ap.add_argument("-l", "--language", default="fr")
    ap.add_argument("--device", default=None, help="cuda ou cpu (auto par défaut)")
    ap.add_argument("--model", default="large-v3", help="Modèle Whisper (utilisé uniquement sans SRT)")
    ap.add_argument("--pad", type=float, default=0.5,
                    help="Marge (s) ajoutée autour de chaque ligne SRT avant alignement")
    args = ap.parse_args()

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[device] {device}", file=sys.stderr)

    print("[audio] chargement…", file=sys.stderr)
    audio = whisperx.load_audio(str(args.audio))
    duration = len(audio) / 16000

    if args.srt:
        # Mode alignement forcé : les timings SRT servent de fenêtre de recherche.
        segments = parse_srt(args.srt)
        for i, seg in enumerate(segments):
            seg["start"] = max(0.0, seg["start"] - args.pad)
            nxt = segments[i + 1]["start"] + args.pad if i + 1 < len(segments) else duration
            seg["end"] = min(duration, max(seg["end"] + args.pad, nxt))
        print(f"[srt] {len(segments)} lignes chargées", file=sys.stderr)
    else:
        print(f"[whisper] transcription avec {args.model}…", file=sys.stderr)
        compute = "float16" if device == "cuda" else "int8"
        model = whisperx.load_model(args.model, device, compute_type=compute, language=args.language)
        segments = model.transcribe(audio, batch_size=8)["segments"]

    print("[align] chargement du modèle d'alignement…", file=sys.stderr)
    align_model, metadata = whisperx.load_align_model(language_code=args.language, device=device)
    print("[align] alignement…", file=sys.stderr)
    result = whisperx.align(segments, align_model, metadata, audio, device, return_char_alignments=False)

    # On collecte d'abord les mots bruts (certains, comme les chiffres ou les
    # symboles, n'ont pas de timing renvoyé par WhisperX : start/end = None).
    raw = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            token = re.sub(r"^[^\w]+|[^\w]+$", "", w["word"])
            if token:
                raw.append({"word": token,
                            "start": w.get("start"),
                            "end": w.get("end"),
                            "score": round(w.get("score", 0.0), 3)})

    _fill_missing_timings(raw, duration)

    words = [{"word": w["word"], "start": fmt(w["start"]),
              "end": fmt(w["end"]), "score": w["score"]} for w in raw]

    n_interp = sum(1 for w in raw if w["score"] == 0.0)
    args.output.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {len(words)} mots -> {args.output}"
          + (f" ({n_interp} timing(s) interpolé(s))" if n_interp else ""), file=sys.stderr)


def _fill_missing_timings(raw: list[dict], duration: float) -> None:
    """Comble start/end manquants en interpolant entre les mots voisins datés.

    Une suite de mots sans timing entre deux mots datés se voit répartir
    l'intervalle de façon égale. Modifie `raw` en place.
    """
    n = len(raw)
    for i, w in enumerate(raw):
        if w["start"] is not None and w["end"] is not None:
            continue
        # borne gauche : fin du dernier mot daté avant i
        left = next((raw[j]["end"] for j in range(i - 1, -1, -1)
                     if raw[j]["end"] is not None), 0.0)
        # borne droite : début du prochain mot daté après i
        right = next((raw[j]["start"] for j in range(i + 1, n)
                      if raw[j]["start"] is not None), duration)
        # nombre de mots consécutifs sans timing dans ce trou (i compris)
        k = i
        while k < n and raw[k]["start"] is None:
            k += 1
        gap = raw[i:k]
        span = (right - left) / max(len(gap), 1)
        for m, g in enumerate(gap):
            g["start"] = left + m * span
            g["end"] = left + (m + 1) * span


if __name__ == "__main__":
    main()
