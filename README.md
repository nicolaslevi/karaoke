# Karaoké — paroles synchronisées mot à mot

Chaîne complète : à partir d'un **audio** et d'un **SRT** de paroles, produit une
**vidéo karaoké** où le texte se remplit mot à mot, calé sur le chant.

## Arborescence

```
karaoke/
├── run.py              ← orchestrateur : lance tout le pipeline
├── requirements.txt
├── input/              ← déposez ici l'audio (.wav/.mp3) et le .srt
├── work/               ← fichiers intermédiaires (voix isolée, words.json)
├── scripts/
│   ├── align_words.py      alignement mot à mot (WhisperX)
│   ├── render_karaoke.py   conversion + rendu vidéo (tout intégré)
│   └── _compat.py          rustines NumPy 2 / torchaudio 2.9
└── karaoke.mp4         ← vidéo finale (générée à la racine)
```

## Installation

Dans un environnement virtuel (Python 3.12 conseillé ; 3.14 fonctionne aussi) :

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate     macOS/Linux : source .venv/bin/activate
pip install -U -r requirements.txt
```

`ffmpeg` **et** `ffprobe` doivent être installés et dans le PATH :
- Windows : `winget install Gyan.FFmpeg` puis **rouvrir le terminal**
- macOS : `brew install ffmpeg`   •   Linux : `apt install ffmpeg`

`demucs` n'est nécessaire que si vous utilisez l'option `--demucs`.

## Utilisation

Placez votre audio et votre `.srt` dans `input/`, puis :

```bash
python run.py
```

C'est tout : le fichier `karaoke.mp4` apparaît à la racine.

### Options

| Option              | Effet                                                            |
|---------------------|------------------------------------------------------------------|
| `--demucs`          | Isole la voix (Demucs) avant l'alignement → calage plus précis   |
| `--start 0 --end 30`| Ne rend qu'un extrait de 30 s (test rapide)                      |
| `--bg fond.png`     | Image de fond 1920×1080 (sinon un dégradé est généré)            |
| `--font chemin.ttf` | Police du texte (sinon Arial/Segoe sous Windows, auto ailleurs)  |
| `--audio` / `--srt` | Fichiers explicites si non déposés dans `input/`                 |
| `--out nom.mp4`     | Nom de la vidéo finale                                            |
| `--language fr`     | Langue des paroles                                               |
| `--skip-align`      | Réutilise `work/words.json` (ne relance pas WhisperX)            |

### Exemples

```bash
python run.py --demucs                       # qualité maximale
python run.py --start 0 --end 30             # aperçu de 30 s
python run.py --demucs --bg input/fond.jpg --out clip.mp4
```

## Fonctionnement

1. **Demucs** (option) : sépare voix / instrumental. La voix isolée sert **à
   l'alignement seulement** — la vidéo garde toujours le mix complet en bande-son.
2. **WhisperX** (`align_words.py`) : alignement forcé des paroles du SRT sur
   l'audio → `work/words.json` (timing début/fin par mot, `mm:ss:xx`).
3. **Rendu** (`render_karaoke.py`) : regroupe les mots en lignes d'après le SRT
   (ponctuation conservée) et fabrique la vidéo image par image via ffmpeg.

## Lancer les scripts séparément

```bash
python scripts/align_words.py input/song.wav --srt input/lyrics.srt -o work/words.json
python scripts/render_karaoke.py --audio input/song.wav --words work/words.json \
    --srt input/lyrics.srt --out karaoke.mp4
```

## Personnalisation

Couleurs, taille, position du texte : en tête de `scripts/render_karaoke.py`
(`FILLED`, `UNFILLED`, `SIZE`, `BASE_Y`, `LEAD`, `TAIL`, `FADE`…).

## Conseils

- Timings imprécis sur un morceau très instrumental ? Utilisez `--demucs`.
- Mots à `score` bas dans `words.json` = alignement peu sûr, à vérifier.
- Pour itérer sur le style, travaillez avec `--start/--end` sur un court extrait.
