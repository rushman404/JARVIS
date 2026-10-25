"""Proef: de iPad als microfoon en speaker (Fase 20, M3).

Een haalbaarheidsproef vóór M4/M5. De proefpagina (``spraak-proef.html``,
in Safari) neemt een paar seconden op, zet het om naar 16 kHz mono en
stuurt het in stukjes van ±0,25 s naar het brein. Het brein meet:

* of alles aankwam (geen ontbrekende stukjes) en hoe regelmatig;
* het geluidsniveau (gemiddeld en piek, in dBFS) en of het oversteurt;
* of het wake word ("Hey JARVIS") te herkennen is (openWakeWord);
* wat de spraakherkenning ervan maakt (dezelfde als bij de microfoon).

Daarnaast maakt het brein een testzin met de echte JARVIS-stem
(``testzin_wav``), zodat de pagina kan proberen of afspelen op de iPad werkt.

Veiligheid: alleen met de bedien-rol, één proef tegelijk, maximaal
``MAX_SECONDEN`` audio, en de opname blijft alleen in het geheugen tot de
proef klaar is. Er wordt niets opgeslagen.
"""

import base64
import io
import logging
import math
import secrets
import threading
import time
import wave

logger = logging.getLogger("jarvis.dashboard.spraakproef")

RATE = 16000
MAX_SECONDEN = 10
MAX_STUK_SAMPLES = RATE  # hoogstens 1 s per stukje
MAX_STUKKEN = 80
VERLOOPT_NA = 120  # een vergeten proef ruimt zichzelf op
WAKE_FRAME = 1280  # 80 ms, zoals voice/wakeword.py
TESTZIN = "Goedenavond, sir. Dit is de stem van JARVIS, nu via de iPad."


def _dbfs(waarde):
    return round(20 * math.log10(waarde), 1) if waarde > 0 else -120.0


def meet(samples):
    """Niveau en oversturing van int16-samples (een ``array`` of lijst)."""

    import numpy as np

    x = np.asarray(samples, dtype=np.int16).astype(np.float64)
    if x.size == 0:
        return {"rms_dbfs": -120.0, "piek_dbfs": -120.0, "oversturing": 0.0}
    norm = x / 32768.0
    rms = float(np.sqrt(np.mean(norm ** 2)))
    piek = float(np.max(np.abs(norm)))
    oversturing = float(np.mean(np.abs(x) >= 32000))
    return {
        "rms_dbfs": _dbfs(rms),
        "piek_dbfs": _dbfs(piek),
        "oversturing": round(oversturing * 100, 2),
    }


def _std_wake_score(samples):
    """Hoogste 'hey_jarvis'-score over de opname, of None zonder model."""

    import numpy as np

    try:
        from openwakeword.model import Model
    except Exception:
        return None
    try:
        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception:
        return None
    x = np.asarray(samples, dtype=np.int16)
    beste = 0.0
    for start in range(0, x.size - WAKE_FRAME + 1, WAKE_FRAME):
        uitkomst = model.predict(x[start:start + WAKE_FRAME])
        beste = max(beste, max((float(v) for v in uitkomst.values()), default=0.0))
    return round(beste, 3)


def _std_herken(samples):
    """De spraakherkenning van JARVIS op de opname, of None."""

    try:
        import speech_recognition as sr

        import taal
    except Exception:
        return None
    import numpy as np

    data = np.asarray(samples, dtype=np.int16).tobytes()
    try:
        tekst = sr.Recognizer().recognize_google(sr.AudioData(data, RATE, 2), language=taal.spraak_code())
    except Exception:
        return None
    return str(tekst)[:200] if tekst else None


def _std_testzin():
    """De testzin als WAV (16-bit mono) met de Piper-stem van JARVIS."""

    from voice import piper_tts

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        rate = None
        for audio, sample_rate in piper_tts.synthesize(TESTZIN, volume=1.0):
            if rate is None:
                rate = sample_rate
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
            wav.writeframes(audio.tobytes())
        if rate is None:
            raise RuntimeError("Piper gaf geen geluid.")
    return buf.getvalue()


class SpraakProef:
    """Eén proef tegelijk; alle functies zijn vervangbaar voor de tests."""

    def __init__(self, klok=time.time, wake_fn=None, herken_fn=None, testzin_fn=None):
        self.klok = klok
        self.wake_fn = wake_fn or _std_wake_score
        self.herken_fn = herken_fn or _std_herken
        self.testzin_fn = testzin_fn or _std_testzin
        self._lock = threading.Lock()
        self._proef = None
        self._testzin = None

    # ----- opnemen -----

    def start(self):
        with self._lock:
            self._proef = {
                "id": secrets.token_hex(8),
                "gestart": self.klok(),
                "stukken": {},
                "aankomst": [],
                "client": [],
            }
            return 200, {"ok": True, "id": self._proef["id"], "rate": RATE, "max_seconden": MAX_SECONDEN}

    def _actief(self, proef_id):
        p = self._proef
        if p is None or not isinstance(proef_id, str) or proef_id != p["id"]:
            return None
        if self.klok() - p["gestart"] > VERLOOPT_NA:
            self._proef = None
            return None
        return p

    def stuk(self, body):
        import numpy as np

        if not isinstance(body, dict):
            return 400, _fout("ongeldige_invoer", "Verwacht een JSON-object.")
        seq = body.get("seq")
        pcm = body.get("pcm")
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < MAX_STUKKEN:
            return 400, _fout("ongeldige_invoer", "seq ontbreekt of is ongeldig.")
        if not isinstance(pcm, str) or not pcm:
            return 400, _fout("ongeldige_invoer", "pcm ontbreekt.")
        try:
            data = base64.b64decode(pcm, validate=True)
        except (ValueError, TypeError):
            return 400, _fout("ongeldige_invoer", "pcm is geen geldige base64.")
        if len(data) % 2 or len(data) // 2 > MAX_STUK_SAMPLES:
            return 400, _fout("ongeldige_invoer", "Een stukje moet 16-bit audio van hoogstens 1 s zijn.")
        with self._lock:
            p = self._actief(body.get("id"))
            if p is None:
                return 404, _fout("niet_gevonden", "Deze proef bestaat niet (meer). Start opnieuw.")
            totaal = sum(len(s) for s in p["stukken"].values()) + len(data) // 2
            if totaal > MAX_SECONDEN * RATE:
                return 413, _fout("te_lang", f"Een proef duurt hoogstens {MAX_SECONDEN} seconden.")
            p["stukken"][seq] = np.frombuffer(data, dtype=np.int16).copy()
            p["aankomst"].append(self.klok())
            t = body.get("t")
            if isinstance(t, (int, float)) and not isinstance(t, bool):
                p["client"].append(float(t))
        return 200, {"ok": True}

    def klaar(self, body):
        import numpy as np

        proef_id = body.get("id") if isinstance(body, dict) else None
        with self._lock:
            p = self._actief(proef_id)
            if p is None:
                return 404, _fout("niet_gevonden", "Deze proef bestaat niet (meer). Start opnieuw.")
            self._proef = None
        if not p["stukken"]:
            return 400, _fout("leeg", "Er kwam geen geluid binnen.")

        volgorde = sorted(p["stukken"])
        ontbrekend = [i for i in range(volgorde[-1] + 1) if i not in p["stukken"]]
        samples = np.concatenate([p["stukken"][i] for i in volgorde])
        aankomst = p["aankomst"]
        gaten = [b - a for a, b in zip(aankomst, aankomst[1:])]

        uitslag = {
            "ok": True,
            "seconden": round(samples.size / RATE, 2),
            "stukken": len(volgorde),
            "ontbrekend": len(ontbrekend),
            "grootste_gat_ms": round(max(gaten) * 1000) if gaten else 0,
            **meet(samples),
        }
        try:
            uitslag["wake_word_score"] = self.wake_fn(samples)
        except Exception:
            logger.debug("Wake word op de proef mislukt.", exc_info=True)
            uitslag["wake_word_score"] = None
        try:
            uitslag["herkend"] = self.herken_fn(samples)
        except Exception:
            logger.debug("Spraakherkenning op de proef mislukt.", exc_info=True)
            uitslag["herkend"] = None
        uitslag["oordeel"] = oordeel(uitslag)
        return 200, uitslag

    # ----- afspelen -----

    def testzin(self):
        """``(wav_bytes, None)`` of ``(None, foutmelding)``; eenmalig gemaakt."""

        if self._testzin is None:
            try:
                self._testzin = self.testzin_fn()
            except Exception:
                logger.exception("Testzin maken mislukt.")
                return None, "De testzin kon niet gemaakt worden (staat Piper aan?)."
        return self._testzin, None


def oordeel(u):
    """Korte conclusie in gewone woorden, voor op de iPad."""

    punten = []
    if u["ontbrekend"]:
        punten.append(f"{u['ontbrekend']} stukje(s) kwamen niet aan")
    if u["grootste_gat_ms"] > 1500:
        punten.append("het geluid kwam met grote haperingen binnen")
    if u["rms_dbfs"] < -50:
        punten.append("het geluid is erg zacht (microfoon geblokkeerd of te ver weg?)")
    if u["oversturing"] > 1:
        punten.append("het geluid stuurt over (te dichtbij of te hard)")
    score = u.get("wake_word_score")
    if score is not None and score < 0.5:
        punten.append("'Hey JARVIS' werd niet duidelijk herkend")
    if not punten:
        return "Goed: het geluid komt heel en duidelijk aan."
    return "Let op: " + "; ".join(punten) + "."


def _fout(code, melding):
    return {"ok": False, "fout": {"code": code, "melding": melding}}
