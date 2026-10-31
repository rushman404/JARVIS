"""Whisper: lokaal verstaan, Google als terugval (Fase 33).

* **Motor per pc** (:func:`motor` / :func:`zet_motor`): ``google`` of
  ``whisper``, bewaard in ``memory/spraakherkenning.json`` (de schakelaar op
  de iPad); zonder keuze geldt ``SPRAAK_HERKENNING`` uit ``.env``.
* **Model automatisch** (:func:`kies_model`): met een NVIDIA-videokaart
  ``large-v3-turbo`` (float16), anders ``small`` op de processor (int8).
  ``WHISPER_MODEL`` in ``.env`` gaat voor.
* **Terugval** (:func:`herken`): laadt het model nog, is het kapot, al bezig
  of duurt het langer dan ``WHISPER_MAX_SECONDEN``, dan :class:`WhisperFout`
  en verstaat Google het. Een leeg resultaat is gewoon "niet verstaan".

Alles blijft op deze pc: het geluid gaat bij Whisper nergens heen. Alleen
het model wordt de eerste keer gedownload (Hugging Face).
"""

import glob
import json
import logging
import os
import sys
import threading
import time

logger = logging.getLogger("jarvis.whisper")

MOTOR_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "memory", "spraakherkenning.json")
MOTOREN = ("google", "whisper")

MODEL_GPU = "large-v3-turbo"
MODEL_CPU = "small"

# Woorden die Whisper anders vaak verkeerd spelt.
HINT = "JARVIS, Spotify, Discord, Steam, Valorant."

# Whisper verzint bij stilte of ruis soms ondertitel-zinnen.
VERZONNEN = ("ondertiteling", "ondertiteld door", "ondertitels", "bedankt voor het kijken",
             "bedankt voor het luisteren", "amara.org", "tv gelderland", "abonneer")

_lock = threading.Lock()
_bezig = threading.Lock()
_staat = {"model": None, "naam": None, "apparaat": None, "laden": False,
          "fout": None, "laatst_duur": None}


class WhisperFout(Exception):
    """Whisper kan nu niet: Google neemt het over."""


# ---------------------------------------------------------------------
# Motor (schakelaar)
# ---------------------------------------------------------------------

def _standaard_motor():
    try:
        from config import SPRAAK_HERKENNING

        return SPRAAK_HERKENNING if SPRAAK_HERKENNING in MOTOREN else "google"
    except Exception:
        return "google"


def motor(pad=None):
    """``google`` of ``whisper`` voor deze pc."""

    try:
        with open(pad or MOTOR_FILE, encoding="utf-8") as f:
            keuze = json.load(f).get("motor")
    except (OSError, ValueError, AttributeError):
        keuze = None
    return keuze if keuze in MOTOREN else _standaard_motor()


def zet_motor(keuze, pad=None, laden=True):
    """Bewaart de keuze; bij ``whisper`` begint het model alvast te laden."""

    if keuze not in MOTOREN:
        raise ValueError(keuze)
    pad = pad or MOTOR_FILE
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    tijdelijk = pad + ".tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump({"motor": keuze}, f)
    os.replace(tijdelijk, pad)
    logger.info("Verstaan via %s", keuze)
    if keuze == "whisper" and laden:
        laad_op_achtergrond()
    return status(pad)


# ---------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------

def _cuda_dlls():
    """Maakt de CUDA-DLL's uit de pip-pakketten (nvidia-*) vindbaar op Windows."""

    if sys.platform != "win32":
        return
    for basis in sys.path:
        for map_ in glob.glob(os.path.join(basis, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(map_)
            except OSError:
                continue
            if map_ not in os.environ.get("PATH", ""):
                os.environ["PATH"] = map_ + os.pathsep + os.environ.get("PATH", "")


def heeft_gpu():
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def kies_model(gpu=None):
    """(model, apparaat, rekentype)."""

    gpu = heeft_gpu() if gpu is None else gpu
    try:
        from config import WHISPER_MODEL
    except Exception:
        WHISPER_MODEL = ""
    if gpu:
        return (WHISPER_MODEL or MODEL_GPU), "cuda", "float16"
    return (WHISPER_MODEL or MODEL_CPU), "cpu", "int8"


def _maak_model(naam, apparaat, rekentype):
    from faster_whisper import WhisperModel

    return WhisperModel(naam, device=apparaat, compute_type=rekentype)


def _proef(model):
    """Een halve seconde stilte: laadt ook de CUDA-bibliotheken echt."""

    import numpy as np

    segmenten, _ = model.transcribe(np.zeros(8000, dtype=np.float32), language="nl", beam_size=1)
    list(segmenten)


def laad():
    """Laadt het model (blokkeert); videokaart eerst, anders de processor."""

    with _lock:
        if _staat["model"] is not None:
            return True
        _staat.update(laden=True, fout=None)
    return _laad()


def _laad():
    _cuda_dlls()
    naam, apparaat, rekentype = kies_model()
    pogingen = [(naam, apparaat, rekentype)]
    if apparaat == "cuda":
        pogingen.append((kies_model(gpu=False)[0], "cpu", "int8"))
    fout = None
    for naam, apparaat, rekentype in pogingen:
        try:
            begin = time.monotonic()
            model = _maak_model(naam, apparaat, rekentype)
            _proef(model)
        except Exception as e:
            fout = e
            logger.warning("Whisper %s op %s laden lukte niet: %s", naam, apparaat, e)
            continue
        with _lock:
            _staat.update(model=model, naam=naam, apparaat=apparaat, laden=False, fout=None)
        logger.info("🎙️ Whisper %s klaar op %s (%.1f s)", naam, apparaat, time.monotonic() - begin)
        return True
    with _lock:
        _staat.update(laden=False, fout=str(fout) or type(fout).__name__)
    return False


def laad_op_achtergrond():
    with _lock:
        if _staat["model"] is not None or _staat["laden"]:
            return
        _staat["laden"] = True
    threading.Thread(target=_laad_veilig, name="whisper-laden", daemon=True).start()


def _laad_veilig():
    try:
        _laad()
    except Exception:
        logger.exception("Whisper laden mislukte.")
        with _lock:
            _staat.update(laden=False, fout="onverwachte fout")


def ontlaad():
    with _lock:
        _staat.update(model=None, naam=None, apparaat=None, laden=False, fout=None)


# ---------------------------------------------------------------------
# Verstaan
# ---------------------------------------------------------------------

def _taal(spraak_code):
    return (spraak_code or "nl").split("-")[0].lower() or "nl"


def _verzonnen(tekst):
    t = tekst.lower()
    return any(v in t for v in VERZONNEN)


def _schrijf_uit(model, audio, taal):
    segmenten, _ = model.transcribe(
        audio, language=taal, beam_size=5, vad_filter=False,
        condition_on_previous_text=False, without_timestamps=True,
        initial_prompt=HINT,
    )
    delen = []
    for s in segmenten:
        if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
            continue
        tekst = s.text.strip()
        if tekst and not _verzonnen(tekst):
            delen.append(tekst)
    tekst = " ".join(delen).strip()
    # De hint zelf terug = niets gehoord.
    return "" if tekst.strip(" .,") == HINT.strip(" .,") else tekst


def herken(recording, spraak_code="nl-NL", max_seconden=None):
    """Tekst uit een int16-opname (16 kHz); :class:`WhisperFout` = terugvallen."""

    import numpy as np

    if max_seconden is None:
        try:
            from config import WHISPER_MAX_SECONDEN as max_seconden
        except Exception:
            max_seconden = 5.0
    with _lock:
        model = _staat["model"]
    if model is None:
        laad_op_achtergrond()
        raise WhisperFout("het model is nog niet geladen")
    if not _bezig.acquire(blocking=False):
        raise WhisperFout("Whisper is nog bezig met de vorige zin")

    audio = np.asarray(recording, dtype=np.float32) / 32768.0
    uit = {}

    def werk():
        try:
            uit["tekst"] = _schrijf_uit(model, audio, _taal(spraak_code))
        except Exception as e:
            uit["fout"] = e
        finally:
            _bezig.release()

    begin = time.monotonic()
    draad = threading.Thread(target=werk, name="whisper-verstaan", daemon=True)
    draad.start()
    draad.join(max_seconden)
    if draad.is_alive():
        raise WhisperFout(f"te traag (meer dan {max_seconden:g} s)")
    if "fout" in uit:
        raise WhisperFout(str(uit["fout"]) or type(uit["fout"]).__name__)
    with _lock:
        _staat["laatst_duur"] = round(time.monotonic() - begin, 2)
    return uit.get("tekst", "")


def status(pad=None):
    """Voor de iPad: motor, model, apparaat en of hij klaar is."""

    with _lock:
        s = dict(_staat)
    gekozen = motor(pad)
    if s["model"] is not None:
        stand = "klaar"
    elif s["laden"]:
        stand = "laden"
    elif s["fout"]:
        stand = "fout"
    else:
        stand = "uit"
    verwacht = kies_model()
    return {
        "motor": gekozen,
        "stand": stand,
        "model": s["naam"] or verwacht[0],
        "apparaat": s["apparaat"] or verwacht[1],
        "fout": s["fout"],
        "laatst_duur": s["laatst_duur"],
    }
