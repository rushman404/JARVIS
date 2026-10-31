"""Fase 33 — Whisper: lokaal verstaan, Google als terugval."""

import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import speech_recognition as sr

from core import storingen
from voice import listen as listen_mod
from voice import whisper_stt

ROOT = Path(__file__).resolve().parent.parent


def _seg(tekst, no_speech=0.0, logprob=-0.2):
    return SimpleNamespace(text=tekst, no_speech_prob=no_speech, avg_logprob=logprob)


class NepModel:
    def __init__(self, segmenten=(), wacht=None, fout=None):
        self.segmenten = list(segmenten)
        self.wacht = wacht
        self.fout = fout
        self.aanroepen = []

    def transcribe(self, audio, **kw):
        self.aanroepen.append(kw)
        if self.wacht is not None:
            self.wacht.wait(5)
        if self.fout:
            raise self.fout
        return iter(self.segmenten), None


def _geladen(model):
    whisper_stt._staat.update(model=model, naam="large-v3-turbo", apparaat="cuda")


def _som():
    totaal = {}
    for regel in storingen._lees().values():
        for k, v in regel.items():
            totaal[k] = totaal.get(k, 0) + v
    return totaal


# ---------------------------------------------------------------------
# M1 — motor, model en laden
# ---------------------------------------------------------------------

def test_motor_standaard_google_en_schakelaar_bewaart():
    assert whisper_stt.motor() == "google"
    stand = whisper_stt.zet_motor("whisper")
    assert stand["motor"] == "whisper" and whisper_stt.motor() == "whisper"
    whisper_stt.zet_motor("google")
    assert whisper_stt.motor() == "google"


def test_motor_ongeldig_en_standaard_uit_env(monkeypatch):
    with pytest.raises(ValueError):
        whisper_stt.zet_motor("siri")
    import config

    monkeypatch.setattr(config, "SPRAAK_HERKENNING", "whisper")
    assert whisper_stt.motor() == "whisper"
    monkeypatch.setattr(config, "SPRAAK_HERKENNING", "onzin")
    assert whisper_stt.motor() == "google"


def test_kies_model_automatisch_en_override(monkeypatch):
    import config

    monkeypatch.setattr(config, "WHISPER_MODEL", "")
    assert whisper_stt.kies_model(gpu=True) == ("large-v3-turbo", "cuda", "float16")
    assert whisper_stt.kies_model(gpu=False) == ("small", "cpu", "int8")
    monkeypatch.setattr(config, "WHISPER_MODEL", "medium")
    assert whisper_stt.kies_model(gpu=False)[0] == "medium"


def test_laden_valt_terug_op_de_processor(monkeypatch):
    gemaakt = []

    def maak(naam, apparaat, rekentype):
        gemaakt.append((naam, apparaat, rekentype))
        if apparaat == "cuda":
            raise RuntimeError("cublas64_12.dll niet gevonden")
        return NepModel()

    monkeypatch.setattr(whisper_stt, "heeft_gpu", lambda: True)
    monkeypatch.setattr(whisper_stt, "_maak_model", maak)
    monkeypatch.setattr(whisper_stt, "_proef", lambda m: None)
    assert whisper_stt.laad() is True
    assert gemaakt == [("large-v3-turbo", "cuda", "float16"), ("small", "cpu", "int8")]
    s = whisper_stt.status()
    assert s["stand"] == "klaar" and s["apparaat"] == "cpu" and s["model"] == "small"


def test_laden_mislukt_geeft_fout_stand(monkeypatch):
    monkeypatch.setattr(whisper_stt, "heeft_gpu", lambda: False)
    assert whisper_stt.laad() is False  # conftest blokkeert _maak_model
    s = whisper_stt.status()
    assert s["stand"] == "fout" and "geblokkeerd" in s["fout"]


# ---------------------------------------------------------------------
# M1 — verstaan en terugval
# ---------------------------------------------------------------------

def test_herken_tekst_taal_en_filter():
    model = NepModel([_seg(" Zet de lamp aan."), _seg("Ondertiteld door de Amara.org gemeenschap"),
                      _seg(" ruis", no_speech=0.9, logprob=-1.5)])
    _geladen(model)
    assert whisper_stt.herken(np.zeros(1600, dtype=np.int16), "en-US") == "Zet de lamp aan."
    assert model.aanroepen[0]["language"] == "en"
    assert whisper_stt.status()["laatst_duur"] is not None


def test_herken_alleen_de_hint_is_niets():
    _geladen(NepModel([_seg(whisper_stt.HINT)]))
    assert whisper_stt.herken(np.zeros(1600, dtype=np.int16)) == ""


def test_herken_zonder_model_valt_terug(monkeypatch):
    gestart = []
    monkeypatch.setattr(whisper_stt, "laad_op_achtergrond", lambda: gestart.append(1))
    with pytest.raises(whisper_stt.WhisperFout):
        whisper_stt.herken(np.zeros(1600, dtype=np.int16))
    assert gestart == [1]


def test_herken_te_traag_en_bezig_vallen_terug():
    los = threading.Event()
    _geladen(NepModel([_seg("hoi")], wacht=los))
    with pytest.raises(whisper_stt.WhisperFout, match="te traag"):
        whisper_stt.herken(np.zeros(1600, dtype=np.int16), max_seconden=0.05)
    with pytest.raises(whisper_stt.WhisperFout, match="bezig"):
        whisper_stt.herken(np.zeros(1600, dtype=np.int16), max_seconden=0.05)
    los.set()
    assert whisper_stt._bezig.acquire(timeout=2)
    whisper_stt._bezig.release()


def test_herken_fout_in_model_valt_terug():
    _geladen(NepModel(fout=RuntimeError("CUDA out of memory")))
    with pytest.raises(whisper_stt.WhisperFout, match="CUDA"):
        whisper_stt.herken(np.zeros(1600, dtype=np.int16))


@pytest.fixture
def google(monkeypatch):
    gebruikt = []

    def herken(self, audio, language=None):
        gebruikt.append(language)
        return "via google"

    monkeypatch.setattr(sr.Recognizer, "recognize_google", herken)
    return gebruikt


def test_recognize_met_whisper(google):
    whisper_stt.zet_motor("whisper")
    _geladen(NepModel([_seg("zet de lamp aan")]))
    assert listen_mod._recognize(np.zeros(1600, dtype=np.int16)) == "zet de lamp aan"
    assert google == [] and _som() == {"whisper": 1}


def test_recognize_whisper_leeg_is_niet_verstaan(google):
    whisper_stt.zet_motor("whisper")
    _geladen(NepModel([]))
    with pytest.raises(sr.UnknownValueError):
        listen_mod._recognize(np.zeros(1600, dtype=np.int16))
    assert google == []


def test_recognize_terugval_naar_google(google):
    whisper_stt.zet_motor("whisper")  # model niet geladen
    assert listen_mod._recognize(np.zeros(1600, dtype=np.int16)) == "via google"
    assert google == ["nl-NL"] and _som() == {"whisper_terugval": 1}


def test_recognize_google_raakt_whisper_niet(google, monkeypatch):
    monkeypatch.setattr(whisper_stt, "herken", lambda *a, **k: pytest.fail("Whisper gebruikt"))
    assert listen_mod._recognize(np.zeros(1600, dtype=np.int16)) == "via google"
    assert _som() == {}


# ---------------------------------------------------------------------
# M2 — iPad en storingslog
# ---------------------------------------------------------------------

def test_dashboard_verstaan():
    from dashboard.api import DashboardAPI

    audit = []
    api = DashboardAPI(audit_fn=lambda **k: audit.append(k))
    status, data = api.verstaan()
    assert status == 200 and data["motor"] == "google"
    status, data = api.verstaan_zet({"motor": "whisper"})
    assert status == 200 and data["motor"] == "whisper" and whisper_stt.motor() == "whisper"
    assert api.verstaan_zet({"motor": "siri"})[0] == 400
    assert api.verstaan_zet(None)[0] == 400


def test_dashboard_aansluiting():
    server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("GET", "/api/verstaan"): (k,' in server
    assert '("POST", "/api/verstaan"): (b,' in server
    assert 'id="verstaanKnop"' in (ROOT / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function zetVerstaan(" in app and "Verstaan via Whisper" in app
    assert "memory/spraakherkenning.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_storingslog_telt_whisper():
    storingen.tel("whisper")
    storingen.tel("whisper_terugval")
    week = storingen.overzicht()["deze_week"]
    assert week["whisper"] == 1 and week["whisper_terugval"] == 1


def test_opstarten_laadt_alvast():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'whisper_stt.motor() == "whisper"' in main and "whisper_stt.laad_op_achtergrond()" in main
