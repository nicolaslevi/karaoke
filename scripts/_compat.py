"""
Rustines de compatibilité pour faire tourner WhisperX / pyannote.audio avec les
DERNIÈRES versions de NumPy (>= 2.0) et torchaudio (>= 2.9), sans rien rétrograder.

À importer TOUT EN HAUT de align_words.py, avant whisperx :

    import _compat  # noqa: F401  (doit précéder l'import de whisperx)

Chaque rustine ne s'applique que si l'attribut manque réellement : sur des versions
plus anciennes de NumPy/torchaudio, ce module est un no-op total.
"""

# --- NumPy >= 2.0 : alias supprimés encore utilisés par d'anciennes libs --------
import numpy as _np

for _name, _val in {
    "NaN": _np.nan, "NAN": _np.nan,
    "Inf": _np.inf, "Infinity": _np.inf, "PINF": _np.inf, "NINF": -_np.inf,
    "float_": _np.float64, "complex_": _np.complex128,
    "int_": _np.int64, "uint": _np.uint64, "bool_": _np.bool_,
    "str_": _np.str_, "unicode_": _np.str_, "object_": _np.object_,
}.items():
    if not hasattr(_np, _name):
        setattr(_np, _name, _val)

# --- torchaudio >= 2.9 : API d'I/O supprimées mais encore appelées par pyannote -
import sys as _sys
import types as _types
import torchaudio as _ta

if not hasattr(_ta, "set_audio_backend"):
    _ta.set_audio_backend = lambda *a, **k: None
if not hasattr(_ta, "get_audio_backend"):
    _ta.get_audio_backend = lambda *a, **k: None
if not hasattr(_ta, "list_audio_backends"):
    _ta.list_audio_backends = lambda *a, **k: ["soundfile"]


class _AudioMetaData:  # simple porteur de métadonnées / annotation de type
    def __init__(self, sample_rate=0, num_frames=0, num_channels=0,
                 bits_per_sample=0, encoding="UNKNOWN"):
        self.sample_rate = sample_rate
        self.num_frames = num_frames
        self.num_channels = num_channels
        self.bits_per_sample = bits_per_sample
        self.encoding = encoding


if not hasattr(_ta, "AudioMetaData"):
    _ta.AudioMetaData = _AudioMetaData

# torchaudio.backend (et .backend.common) ont été supprimés : on recrée des
# sous-modules factices pour que `from torchaudio.backend.common import AudioMetaData`
# continue de fonctionner.
if "torchaudio.backend" not in _sys.modules:
    _backend = _types.ModuleType("torchaudio.backend")
    _common = _types.ModuleType("torchaudio.backend.common")
    _common.AudioMetaData = getattr(_ta, "AudioMetaData", _AudioMetaData)
    _backend.common = _common
    _ta.backend = _backend
    _sys.modules["torchaudio.backend"] = _backend
    _sys.modules["torchaudio.backend.common"] = _common
