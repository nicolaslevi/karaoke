#!/usr/bin/env python3
"""
Orchestrateur du pipeline karaoké, de bout en bout.

Étapes :
  1. (option --demucs) Extraction des voix avec Demucs      -> work/vocals.wav
  2. Alignement mot à mot (WhisperX)                        -> work/words.json
  3. Rendu de la vidéo (conversion intégrée)                -> karaoke.mp4 (racine)

L'alignement se fait sur la voix isolée si --demucs est utilisé (meilleure
précision sur un morceau chanté), mais la vidéo garde TOUJOURS le mix complet
comme bande-son.

Arborescence attendue :
  input/   audio + .srt (détectés automatiquement, ou passés en option)
  work/    fichiers intermédiaires
  scripts/ align_words.py, render_karaoke.py, _compat.py
  <racine> run.py + la vidéo finale

Exemples :
  python run.py                          # tout auto depuis input/
  python run.py --demucs                 # avec isolation des voix
  python run.py --start 0 --end 30       # extrait de test de 30 s
  python run.py --demucs --bg fond.png --out mavideo.mp4
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
INPUT = ROOT / "input"
WORK = ROOT / "work"

AUDIO_EXT = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus")


def find_one(folder: Path, exts) -> Path | None:
    hits = [p for p in sorted(folder.glob("*")) if p.suffix.lower() in exts]
    return hits[0] if hits else None


def run(cmd, **kw):
    """Lance une commande en affichant ce qui est exécuté ; stoppe si échec."""
    print("»", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        sys.exit(f"[échec] étape interrompue (code {r.returncode}).")
    return r


def step_demucs(audio: Path) -> Path:
    """Isole la voix. Retourne le chemin de vocals.wav."""
    outdir = WORK / "demucs"
    print("\n=== 1/3  Extraction des voix (Demucs) ===")
    run([sys.executable, "-m", "demucs", "--two-stems", "vocals",
         "-o", str(outdir), str(audio)])
    hits = sorted(outdir.glob("**/vocals.wav"), key=lambda p: p.stat().st_mtime)
    if not hits:
        sys.exit("[échec] vocals.wav introuvable après Demucs.")
    vocals = WORK / "vocals.wav"
    vocals.write_bytes(hits[-1].read_bytes())
    print(f"[ok] voix isolée -> {vocals}")
    return vocals


def step_align(align_audio: Path, srt: Path, language: str, demucs_used: bool) -> Path:
    words = WORK / "words.json"
    print(f"\n=== 2/3  Alignement mot à mot (WhisperX) ===")
    cmd = [sys.executable, str(SCRIPTS / "align_words.py"), str(align_audio),
           "--srt", str(srt), "-o", str(words), "--language", language]
    run(cmd)
    return words


def step_render(soundtrack: Path, words: Path, srt: Path, out: Path, args) -> None:
    print(f"\n=== 3/3  Rendu de la vidéo ===")
    cmd = [sys.executable, str(SCRIPTS / "render_karaoke.py"),
           "--audio", str(soundtrack), "--words", str(words), "--srt", str(srt),
           "--out", str(out), "--fps", str(args.fps), "--size", str(args.size)]
    if args.bg:
        cmd += ["--bg", args.bg]
    if args.font:
        cmd += ["--font", args.font]
    if args.start:
        cmd += ["--start", str(args.start)]
    if args.end is not None:
        cmd += ["--end", str(args.end)]
    run(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", help="Audio d'entrée (défaut : auto dans input/)")
    ap.add_argument("--srt", help="Paroles SRT (défaut : auto dans input/)")
    ap.add_argument("--out", default=str(ROOT / "karaoke.mp4"), help="Vidéo finale (racine)")
    ap.add_argument("--demucs", action="store_true",
                    help="Isoler la voix avant l'alignement (recommandé si instrumental fort)")
    ap.add_argument("--language", default="fr", help="Langue des paroles (défaut fr)")
    ap.add_argument("--bg", default=None, help="Image de fond 1920x1080")
    ap.add_argument("--font", default=None, help="Police .ttf")
    ap.add_argument("--start", type=float, default=0.0, help="Début extrait (s)")
    ap.add_argument("--end", type=float, default=None, help="Fin extrait (s)")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--size", type=int, default=52)
    ap.add_argument("--skip-align", action="store_true",
                    help="Réutiliser work/words.json s'il existe déjà")
    args = ap.parse_args()

    WORK.mkdir(exist_ok=True)

    audio = Path(args.audio) if args.audio else find_one(INPUT, AUDIO_EXT)
    srt = Path(args.srt) if args.srt else find_one(INPUT, (".srt",))
    if not audio or not audio.is_file():
        sys.exit(f"[erreur] aucun audio trouvé (place un fichier dans {INPUT} ou passe --audio).")
    if not srt or not srt.is_file():
        sys.exit(f"[erreur] aucun .srt trouvé (place un fichier dans {INPUT} ou passe --srt).")
    print(f"[audio] {audio}\n[srt]   {srt}")

    # 1. Demucs (optionnel) : la voix isolée sert à l'alignement uniquement.
    align_audio = audio
    if args.demucs:
        align_audio = step_demucs(audio)

    # 2. Alignement
    words = WORK / "words.json"
    if args.skip_align and words.is_file():
        print(f"\n=== 2/3  Alignement ignoré (réutilise {words}) ===")
    else:
        words = step_align(align_audio, srt, args.language, args.demucs)

    # 3. Rendu : bande-son = mix complet d'origine (pas la voix isolée)
    step_render(audio, words, srt, Path(args.out), args)

    print(f"\n✓ Terminé : {args.out}")


if __name__ == "__main__":
    main()
