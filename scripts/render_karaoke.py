#!/usr/bin/env python3
"""
Rendu d'une vidéo karaoké : le texte se « remplit » mot à mot en suivant les
timings produits par align_words.py.

Ce script intègre la conversion : il lit directement le JSON de mots
(align_words.py) + le SRT (pour le regroupement en lignes et la ponctuation),
puis produit la vidéo. Plus besoin d'étape aligned.json séparée.

Multiplateforme (Windows / macOS / Linux). Police et fond ont des valeurs par
défaut ; un fond dégradé est généré si aucune image n'est fournie.

Exemple :
    python render_karaoke.py --audio input/song.wav --words work/words.json \
        --srt input/lyrics.srt --out karaoke.mp4

Dépendances : pillow, numpy, et ffmpeg + ffprobe dans le PATH.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --- Paramètres visuels (surchargeables en ligne de commande) ------------------
W, H, FPS = 1920, 1080, 25
SIZE = 52
MAXW = 1650          # largeur max d'une ligne avant passage sur 2 rangées
BASE_Y = 903         # position verticale du bloc de texte
ROW_GAP = 78
PAD = 20
FILLED = (255, 204, 60)      # texte déjà chanté
UNFILLED = (185, 185, 208)   # texte à venir
SHADOW = (5, 8, 25)
LEAD = 0.6           # apparition de la ligne avant le 1er mot (s)
TAIL = 1.2           # maintien après le dernier mot (s)
FADE = 5             # durée du fondu (frames)

SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


# =============================== Conversion ===================================
# (anciennement to_karaoke_json.py, désormais intégré)

def _clean(token: str) -> str:
    """Retire la ponctuation de bord (même règle que align_words.py)."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", token, flags=re.UNICODE)


def _parse_mmssxx(s: str) -> float:
    """'mm:ss:xx' (xx = centièmes) -> secondes."""
    mm, ss, xx = s.split(":")
    return int(mm) * 60 + int(ss) + int(xx) / 100


def _srt_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = block.strip().splitlines()
        if len(rows) >= 3 and len(re.findall(SRT_TIME, rows[1])) == 2:
            out.append(" ".join(rows[2:]))
    return out


def words_to_lines(words_json: Path, srt: Path) -> list[list]:
    """Transforme la liste plate de mots (align_words.py) en lignes de segments
    [texte, debut_sec, fin_sec, espace_bool], en récupérant le découpage en
    lignes et la ponctuation d'origine depuis le SRT."""
    words = json.loads(words_json.read_text(encoding="utf-8"))
    lines = _srt_lines(srt)
    idx = 0
    result = []
    warnings = 0
    for line in lines:
        raw_tokens = line.split()
        segs = []
        for j, raw in enumerate(raw_tokens):
            has_space = j < len(raw_tokens) - 1
            c = _clean(raw)
            if not c:
                # ponctuation seule : pas de timing (rempli au rendu depuis le mot précédent)
                segs.append([raw, None, None, has_space])
                continue
            if idx >= len(words):
                segs.append([raw, None, None, has_space])
                continue
            w = words[idx]
            idx += 1
            if _clean(w["word"]).lower() != c.lower():
                warnings += 1
                if warnings <= 5:
                    print(f"[!] décalage mot : SRT « {c} » vs JSON « {w['word']} »", file=sys.stderr)
            segs.append([raw, _parse_mmssxx(w["start"]), _parse_mmssxx(w["end"]), has_space])
        result.append(segs)
    if idx != len(words):
        print(f"[!] {len(words) - idx} mot(s) du JSON non utilisé(s)", file=sys.stderr)
    if warnings:
        print(f"[!] {warnings} décalage(s) SRT/JSON détecté(s)", file=sys.stderr)
    return result


# ================================ Rendu =======================================

def find_font(user_font: str | None) -> str:
    candidates = []
    if user_font:
        candidates.append(user_font)
    if sys.platform.startswith("win"):
        win = os.environ.get("WINDIR", r"C:\Windows")
        candidates += [os.path.join(win, "Fonts", f)
                       for f in ("arialbd.ttf", "segoeuib.ttf", "arial.ttf", "calibrib.ttf")]
    elif sys.platform == "darwin":
        candidates += ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                       "/Library/Fonts/Arial Bold.ttf",
                       "/System/Library/Fonts/Helvetica.ttc"]
    candidates += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise FileNotFoundError(
        'Aucune police trouvée. Passe-en une avec --font, '
        'p. ex. --font "C:\\Windows\\Fonts\\arialbd.ttf".')


def make_gradient_bg(w: int, h: int) -> Image.Image:
    top = np.array([18, 22, 46], np.float32)
    bottom = np.array([6, 8, 20], np.float32)
    ramp = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    col = top[None, :] * (1 - ramp) + bottom[None, :] * ramp
    arr = np.repeat(col[:, None, :], w, axis=1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([w * 0.15, h * 0.45, w * 0.85, h * 1.15], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    tint = Image.new("RGB", (w, h), (60, 70, 130))
    return Image.composite(tint, img, glow)


def load_background(path: str | None) -> np.ndarray:
    if path:
        img = Image.open(path).convert("RGB")
        if img.size != (W, H):
            img = img.resize((W, H), Image.LANCZOS)
    else:
        img = make_gradient_bg(W, H)
    return np.asarray(img).astype(np.float32)


def probe_duration(audio: str) -> float | None:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", audio])
        return float(out.strip())
    except Exception:
        return None


class Line:
    pass


def build(lines: list[list], font: ImageFont.FreeTypeFont) -> list[Line]:
    space_w = font.getlength(" ")

    for segs in lines:
        for i, seg in enumerate(segs):
            t, s, e, sp = seg
            if s is None:
                prev = [x for x in segs[:i] if x[1] is not None]
                pe = prev[-1][2] if prev else next(x[1] for x in segs if x[1] is not None)
                segs[i] = [t, pe, pe + 0.04, sp]

    def seg_w(segs):
        return sum(font.getlength(t) + (space_w if sp else 0) for t, _, _, sp in segs)

    def rows_for(segs):
        if seg_w(segs) <= MAXW:
            return [segs]
        best = None
        for i in range(1, len(segs)):
            w1, w2 = seg_w(segs[:i]), seg_w(segs[i:])
            if w1 > MAXW or w2 > MAXW or not segs[i - 1][3]:
                continue
            score = abs(w1 - w2) - (400 if segs[i - 1][0][-1] in ",.;:!?…" else 0)
            if best is None or score < best[0]:
                best = (score, i)
        i = best[1] if best else max(1, len(segs) // 2)
        return [segs[:i], segs[i:]]

    def render_strip(rows):
        nrows = len(rows)
        strip_h = ROW_GAP * nrows + 2 * PAD
        img_u = Image.new("RGBA", (W, strip_h), (0, 0, 0, 0))
        img_f = Image.new("RGBA", (W, strip_h), (0, 0, 0, 0))
        sh = Image.new("L", (W, strip_h), 0)
        du, df, ds = ImageDraw.Draw(img_u), ImageDraw.Draw(img_f), ImageDraw.Draw(sh)
        ranges = []
        for r, segs in enumerate(rows):
            width = seg_w(segs) - (space_w if segs[-1][3] else 0)
            x = (W - width) / 2
            y = PAD + r * ROW_GAP
            for t, s, e, sp in segs:
                w = font.getlength(t)
                du.text((x, y), t, font=font, fill=UNFILLED)
                df.text((x, y), t, font=font, fill=FILLED)
                ds.text((x + 3, y + 3), t, font=font, fill=255)
                ranges.append((r, x, x + w, s, e))
                x += w + (space_w if sp else 0)
        sh = sh.filter(ImageFilter.GaussianBlur(3))
        shadow = np.asarray(sh).astype(np.float32) / 255.0 * 0.85
        top = BASE_Y - 40 - PAD - (nrows - 1) * ROW_GAP // 2
        return dict(u=np.asarray(img_u).astype(np.float32),
                    f=np.asarray(img_f).astype(np.float32),
                    shadow=shadow, top=top, h=strip_h, ranges=ranges, nrows=nrows)

    L = []
    for segs in lines:
        ln = Line()
        ln.rows = rows_for(segs)
        ln.first = min(s for _, s, _, _ in segs)
        ln.last = max(e for _, _, e, _ in segs)
        L.append(ln)
    for i, ln in enumerate(L):
        ln.show = ln.first - LEAD
        if i > 0:
            ln.show = max(ln.show, L[i - 1].last + 0.08)
        ln.hide = ln.last + TAIL
    for i, ln in enumerate(L):
        if i + 1 < len(L):
            ln.hide = min(ln.hide, L[i + 1].show - 0.001)
        ln.hide = max(ln.hide, ln.last + 0.1)
    for ln in L:
        ln.st = render_strip(ln.rows)
    return L


def cursor(ln, t):
    rng = ln.st["ranges"]
    row, x = rng[0][0], rng[0][1]
    for r, x0, x1, s, e in rng:
        if t >= e:
            row, x = r, x1
        elif t >= s:
            return r, x0 + (x1 - x0) * (t - s) / max(e - s, 1e-6)
        else:
            break
    return row, x


def compose(frame, bg, ln, t, alpha):
    st = ln.st
    row, cx = cursor(ln, t)
    h = st["h"]
    mask = np.zeros((h, W, 1), np.float32)
    for r in range(st["nrows"]):
        y0 = max(0, PAD + r * ROW_GAP - 12)
        y1 = (min(h, PAD + (r + 1) * ROW_GAP + 12) if r == st["nrows"] - 1
              else PAD + (r + 1) * ROW_GAP - 12)
        if r < row:
            mask[y0:y1, :, 0] = 1.0
        elif r == row:
            ci = int(math.floor(cx))
            mask[y0:y1, :ci, 0] = 1.0
            if 0 <= ci < W:
                mask[y0:y1, ci, 0] = cx - ci
    rgba = st["u"] * (1 - mask) + st["f"] * mask
    a = rgba[..., 3:4] / 255.0 * alpha
    sh = st["shadow"][..., None] * alpha
    top = st["top"]
    reg = bg[top:top + h]
    reg = reg * (1 - sh) + np.array(SHADOW, np.float32) * sh
    reg = reg * (1 - a) + rgba[..., :3] * a
    frame[top:top + h] = np.clip(reg, 0, 255).astype(np.uint8)


def main():
    global FPS, SIZE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", required=True, help="Bande-son de la vidéo (mix complet)")
    ap.add_argument("--words", required=True, help="JSON de mots (align_words.py)")
    ap.add_argument("--srt", required=True, help="SRT des paroles (lignes + ponctuation)")
    ap.add_argument("--out", default="karaoke.mp4", help="Vidéo de sortie")
    ap.add_argument("--bg", default=None, help="Image de fond 1920x1080 (sinon dégradé auto)")
    ap.add_argument("--font", default=None, help="Chemin d'une police .ttf")
    ap.add_argument("--start", type=float, default=0.0, help="Début de l'extrait (s)")
    ap.add_argument("--end", type=float, default=None, help="Fin de l'extrait (s)")
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--size", type=int, default=SIZE)
    ap.add_argument("--dump-json", default=None,
                    help="(debug) écrit aussi les lignes converties dans ce fichier")
    args = ap.parse_args()

    FPS, SIZE = args.fps, args.size

    lines = words_to_lines(Path(args.words), Path(args.srt))
    if args.dump_json:
        Path(args.dump_json).write_text(json.dumps(lines, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
        print(f"[debug] lignes converties -> {args.dump_json}", file=sys.stderr)

    font_path = find_font(args.font)
    print(f"[police] {font_path}", file=sys.stderr)
    font = ImageFont.truetype(font_path, SIZE)

    L = build(lines, font)
    bg = load_background(args.bg)
    bg_u8 = bg.astype(np.uint8)
    bg8 = bg_u8.tobytes()

    duration = probe_duration(args.audio)
    if duration is None:
        duration = max(ln.hide for ln in L) + 1.0
        print(f"[!] ffprobe indisponible, durée estimée = {duration:.1f}s", file=sys.stderr)
    t0 = args.start
    t1 = args.end if args.end is not None else duration
    n0, n1 = int(t0 * FPS), int(math.ceil(t1 * FPS))

    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-ss", str(t0), "-i", args.audio,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", args.out]
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit("[erreur] ffmpeg introuvable dans le PATH. Installe-le "
                 "(winget install Gyan.FFmpeg) puis rouvre le terminal.")

    li = 0
    for n in range(n0, n1):
        t = n / FPS
        while li < len(L) and t > L[li].hide:
            li += 1
        if li < len(L) and L[li].show <= t <= L[li].hide:
            ln = L[li]
            alpha = min(1.0, (t - ln.show) * FPS / FADE + 0.2, (ln.hide - t) * FPS / FADE + 0.2)
            frame = bg_u8.copy()
            compose(frame, bg, ln, t, alpha)
            p.stdin.write(frame.tobytes())
        else:
            p.stdin.write(bg8)
        if n % 250 == 0:
            print(f"{n}/{n1}", flush=True)
    p.stdin.close()
    p.wait()
    print("terminé ->", args.out)


if __name__ == "__main__":
    main()
