"""Lokale tekst-naar-spraak met Piper (Fase 17).

Piper is een neurale TTS die volledig lokaal draait. Voordelen boven
pyttsx3 voor JARVIS:

- **Sneller**: de synthese loopt sneller dan realtime.
- **Per zin**: ``synthesize()`` levert één audiostuk per zin, waardoor
  JARVIS kan beginnen met praten terwijl het taalmodel nog genereert.

Deze module is een dunne laag rond de ``piper``-bibliotheek. Het afspelen
van de audio, het dempen van de microfoon en het vergrendelen van
gelijktijdige spraak gebeuren in ``voice.speak``; hier gaat het alleen om
het vinden en aansturen van de stem.

De ``piper``-import gebeurt pas binnen de functies, zodat JARVIS ook
zonder Piper blijft werken (hij valt dan terug op pyttsx3).
"""

import logging
import threading
from pathlib import Path

import taal

logger = logging.getLogger(__name__)

# <projectmap>/voice/models
DEFAULT_MODELS_DIR = Path(__file__).resolve().parent / "models"

# Eenmalig geladen stem (lazy) en een lock zodat twee threads niet
# tegelijk een (zwaar) model inladen.
_voice = None
_voice_lock = threading.Lock()

# Pad van het nu geladen model, zodat een taalwissel (Fase 17, F) de stem
# opnieuw laadt.
_voice_model_pad = None


def _voice_pad():
    return _voice_model_pad


def _onthou_pad(pad):
    global _voice_model_pad

    _voice_model_pad = pad


def _models_dir():
    """Geeft de map met stemmodellen (uit config, anders de standaardmap)."""
    from config import PIPER_MODELS_DIR

    if PIPER_MODELS_DIR:
        return Path(PIPER_MODELS_DIR)
    return DEFAULT_MODELS_DIR


def _resolve_model_path():
    """Bepaalt welk .onnx-stemmodel gebruikt wordt, of None als er geen is.

    Met ``PIPER_VOICE`` in de config wordt dat model gekozen (als los pad,
    of als bestandsnaam binnen de modellenmap). Zonder die instelling wordt
    het eerste .onnx-bestand in de modellenmap gebruikt.

    Staat het gesprek op Engels en is er een Engelse stem ingesteld
    (``PIPER_VOICE_EN``), dan krijgt die voorrang (Fase 17, F).
    """
    from config import PIPER_VOICE

    if taal.is_engels():
        from config import PIPER_VOICE_EN

        if PIPER_VOICE_EN:
            pad = Path(PIPER_VOICE_EN)
            if not pad.is_absolute():
                naast_map = _models_dir() / PIPER_VOICE_EN
                if naast_map.is_file():
                    pad = naast_map
            if pad.is_file():
                return pad

    if PIPER_VOICE:
        pad = Path(PIPER_VOICE)
        if not pad.is_absolute():
            naast_map = _models_dir() / PIPER_VOICE
            if naast_map.is_file():
                pad = naast_map
        return pad if pad.is_file() else None

    map_ = _models_dir()
    if not map_.is_dir():
        return None
    modellen = sorted(map_.glob("*.onnx"))
    return modellen[0] if modellen else None


def is_available():
    """True als Piper aanstaat én er een bruikbaar stemmodel is."""
    from config import PIPER_ENABLED

    if not PIPER_ENABLED:
        return False
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return _resolve_model_path() is not None


def get_voice():
    """Laadt de Piper-stem eenmalig en geeft hem terug.

    Gooit een ``RuntimeError`` als er geen model te vinden is of als de
    ``piper``-bibliotheek ontbreekt; ``voice.speak`` vangt dat op en valt
    dan terug op pyttsx3.
    """
    global _voice
    with _voice_lock:
        model_path = _resolve_model_path()

        # Bij een taalwissel (Fase 17, F) moet een andere stem geladen
        # worden. We onthouden daarom ook welk model nu geladen is.
        if _voice is not None and _voice_pad() == model_path:
            return _voice

        from piper import PiperVoice

        if model_path is None:
            raise RuntimeError("Geen Piper-stemmodel gevonden.")
        logger.info("Piper-stem laden: %s", model_path.name)
        _voice = PiperVoice.load(str(model_path))
        _onthou_pad(model_path)
        return _voice


def synthesize(text, volume=1.0):
    """Genereert audio voor ``text``, per zin.

    Levert een iterator van ``(int16-array, sample_rate)``. Het volume
    (0.0 - 1.0) wordt tijdens de synthese toegepast.
    """
    from config import PIPER_LENGTH_SCALE, PIPER_NOISE_SCALE, PIPER_NOISE_W, PIPER_SPEAKER

    stem = get_voice()
    spreker = PIPER_SPEAKER if _aantal_sprekers(stem) > 1 else None
    config = stem_instellingen(volume, PIPER_LENGTH_SCALE, PIPER_NOISE_SCALE, PIPER_NOISE_W, spreker)
    for chunk in stem.synthesize(text, syn_config=config):
        yield chunk.audio_int16_array, chunk.sample_rate


def _aantal_sprekers(stem):
    try:
        return int(getattr(getattr(stem, "config", None), "num_speakers", 1) or 1)
    except (TypeError, ValueError):
        return 1


def stem_instellingen(volume=1.0, length_scale=None, noise_scale=None, noise_w=None, speaker_id=None):
    """De ``SynthesisConfig`` voor Piper; ``None`` = de waarde van het model.

    Gedeeld met ``scripts/stem_proef.py``, zodat de proef precies klinkt
    zoals JARVIS straks.
    """
    from piper import SynthesisConfig

    return SynthesisConfig(
        speaker_id=speaker_id,
        volume=volume,
        length_scale=length_scale,
        noise_scale=noise_scale,
        noise_w_scale=noise_w,
    )


def reset():
    """Vergeet de geladen stem (voor tests of bij wisselen van stem)."""
    global _voice, _voice_model_pad
    with _voice_lock:
        _voice = None
        _voice_model_pad = None
