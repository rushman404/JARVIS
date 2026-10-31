"""Fase 32 — storingslog voor verstaan en het wake word (alleen aantallen)."""

import json
from datetime import date, datetime, timedelta

import numpy as np
import pytest
import speech_recognition as sr

import main
from core import storingen
from voice import listen as listen_mod
from voice import wakeword


def _data():
    return storingen._lees()


# ---------------------------------------------------------------------
# M1 — tellen
# ---------------------------------------------------------------------

def test_tel_per_dag_alleen_aantallen():
    nu = datetime(2026, 11, 2, 10, 0)
    storingen.tel("beurt", nu=nu)
    storingen.tel("verstaan", duur=1.25, nu=nu)
    storingen.tel("verstaan", duur=0.75, nu=nu)
    storingen.tel("onzin", nu=nu)
    data = _data()
    assert data == {"2026-11-02": {"beurt": 1, "verstaan": 2, "duur_verstaan": 2.0}}
    tekst = json.dumps(data)
    assert all(t not in tekst for t in ("zet", "lamp", "audio"))


def test_oude_dagen_verdwijnen():
    storingen.tel("beurt", nu=datetime(2026, 8, 1, 10, 0))
    storingen.tel("beurt", nu=datetime(2026, 11, 2, 10, 0))
    assert list(_data()) == ["2026-11-02"]


def test_tellen_breekt_nooit(monkeypatch):
    monkeypatch.setattr(storingen, "_schrijf", lambda *a, **k: 1 / 0)
    assert storingen.tel("beurt") is None  # geen fout


def test_overzicht_deze_en_vorige_week():
    vandaag = date(2026, 11, 8)
    for i in range(10):
        storingen.tel("beurt", nu=datetime(2026, 11, 8, 9) - timedelta(days=i % 9))
    for _ in range(2):
        storingen.tel("niet_verstaan", nu=datetime(2026, 11, 7, 9))
    storingen.tel("verstaan", duur=2.0, nu=datetime(2026, 11, 7, 9))
    storingen.tel("verstaan", duur=1.0, nu=datetime(2026, 11, 6, 9))
    for _ in range(4):
        storingen.tel("wakker", nu=datetime(2026, 11, 7, 9))
    storingen.tel("vals_alarm", nu=datetime(2026, 11, 7, 9))
    storingen.tel("niet_verstaan", nu=datetime(2026, 10, 30, 9))
    o = storingen.overzicht(vandaag=vandaag)
    nu = o["deze_week"]
    assert nu["beurten"] == 8 and nu["niet_verstaan"] == 2 and nu["niet_verstaan_pct"] == 25
    assert nu["verstaan_gem"] == 1.5
    assert nu["vals_alarm_pct"] == 25
    assert o["vorige_week"]["beurten"] == 2 and o["vorige_week"]["niet_verstaan"] == 1
    assert len(o["dagen"]) == 7 and o["dagen"][-1]["dag"] == "2026-11-08"


def test_overzicht_leeg():
    o = storingen.overzicht(vandaag=date(2026, 11, 8))
    assert o["deze_week"]["niet_verstaan_pct"] is None and o["deze_week"]["verstaan_gem"] is None


# ---------------------------------------------------------------------
# M1 — aangesloten op verstaan
# ---------------------------------------------------------------------

@pytest.fixture
def opname(monkeypatch):
    bron = type("Bron", (), {"latest_timestamp": lambda self: 9.0})()
    monkeypatch.setattr(listen_mod, "get_audio_source", lambda: bron)
    opnames = {"lijst": []}

    def capture(start_ts=None, audio_source=None, wacht_seconden=None):
        return opnames["lijst"].pop(0) if opnames["lijst"] else None

    monkeypatch.setattr(listen_mod, "_capture", capture)
    return opnames


def _som():
    totaal = {}
    for regel in _data().values():
        for k, v in regel.items():
            totaal[k] = totaal.get(k, 0) + v
    return totaal


def test_listen_verstaan_in_een_keer(monkeypatch, opname):
    opname["lijst"] = [np.zeros(10)]
    monkeypatch.setattr(listen_mod, "_recognize", lambda r: "zet de lamp aan")
    assert listen_mod.listen() == "zet de lamp aan"
    s = _som()
    assert s["beurt"] == 1 and s["verstaan"] == 1 and "duur_verstaan" in s
    assert "tweede_poging" not in s


def test_listen_tweede_poging_en_niet_verstaan(monkeypatch, opname):
    opname["lijst"] = [np.zeros(10), np.zeros(10)]

    def nooit(r):
        raise sr.UnknownValueError()

    monkeypatch.setattr(listen_mod, "_recognize", nooit)
    assert listen_mod.listen() == "NOT_UNDERSTOOD"
    s = _som()
    assert s == {"beurt": 2, "tweede_poging": 1, "niet_verstaan": 1}


def test_listen_tweede_poging_zonder_spraak(monkeypatch, opname):
    opname["lijst"] = [np.zeros(10)]
    monkeypatch.setattr(listen_mod, "_recognize", lambda r: "")
    assert listen_mod.listen() is None
    assert _som() == {"beurt": 1, "tweede_poging": 1, "niet_verstaan": 1}


def test_listen_google_fout(monkeypatch, opname):
    opname["lijst"] = [np.zeros(10)]

    def weg(r):
        raise sr.RequestError("geen internet")

    monkeypatch.setattr(listen_mod, "_recognize", weg)
    assert listen_mod.listen() == "NO_CONNECTION"
    assert _som() == {"beurt": 1, "google_fout": 1}


def test_listen_geen_spraak_telt_niet(opname):
    assert listen_mod.listen() == ""
    assert _data() == {}


# ---------------------------------------------------------------------
# M1 — wake word en vals alarm
# ---------------------------------------------------------------------

class NepModel:
    def __init__(self, scores):
        self.scores = list(scores)

    def predict(self, frame):
        return {"hey_jarvis": self.scores.pop(0)}

    def reset(self):
        pass


class NepBron:
    def __init__(self, n):
        self.ts = [10.0 + i * 0.08 * 10 for i in range(n)]  # 0,8 s per frame

    def get_cursor(self):
        return None

    def read_frame(self, after_ts=None, timeout=None):
        return (self.ts.pop(0), np.ones(1280, dtype=np.int16)) if self.ts else None

    def is_running(self):
        return bool(self.ts)


def test_wake_word_telt_wakker_en_bijna_een_keer_per_poging(monkeypatch):
    # 0.35, 0.4 (zelfde poging), 0.1, 0.1, 0.1, 0.1, 0.45 (nieuwe poging, >3 s later), 0.9 (wakker)
    scores = [0.35, 0.4, 0.1, 0.1, 0.1, 0.1, 0.45, 0.9]
    monkeypatch.setattr(wakeword, "get_model", lambda: NepModel(scores))
    monkeypatch.setattr(wakeword, "model", NepModel(scores), raising=False)
    monkeypatch.setattr(wakeword, "last_detection", -100.0, raising=False)
    uit = wakeword.wait_for_wake_word(audio_source=NepBron(len(scores)))
    assert uit["detected_at"] is not None
    assert _som() == {"bijna_wakker": 2, "wakker": 1}


def test_vals_alarm_in_de_sessie(monkeypatch):
    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 3.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    monkeypatch.setattr(main, "listen", lambda **kw: "")
    main.run_wake_cycle()
    assert _som() == {"vals_alarm": 1}


def test_na_een_antwoord_stilte_is_geen_vals_alarm(monkeypatch):
    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 3.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    monkeypatch.setattr(main, "process_command", lambda c, on_tekst=None: "Prima, sir.")
    monkeypatch.setattr(main, "spreek_antwoord", lambda *a, **k: True)
    reeks = iter(["zet de lamp aan", ""])
    monkeypatch.setattr(main, "listen", lambda **kw: next(reeks))
    main.run_wake_cycle()
    assert "vals_alarm" not in _som()


# ---------------------------------------------------------------------
# M2 — de iPad
# ---------------------------------------------------------------------

def test_dashboard_api():
    from dashboard.api import DashboardAPI

    storingen.tel("beurt")
    status, data = DashboardAPI(audit_fn=lambda **k: None).storingen()
    assert status == 200 and data["deze_week"]["beurten"] == 1


def test_dashboard_aansluiting():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert '("GET", "/api/storingen"): (k,' in (root / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert 'id="instStoringen"' in (root / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    assert "memory/storingen.json" in (root / ".gitignore").read_text(encoding="utf-8")
