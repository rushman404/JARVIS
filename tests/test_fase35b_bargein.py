"""Fase 35B, M1 — barge-in gerepareerd: "JARVIS" of "stop" tijdens het praten."""

import threading

import numpy as np
import pytest

from voice import barge_in

SR = 16000


@pytest.fixture(autouse=True)
def _schoon():
    barge_in._modus = None
    barge_in._sneltoets_event.clear()
    yield
    barge_in._modus = None
    barge_in._sneltoets_event.clear()


class NepBron:
    """Levert blokken van 80 ms; gedempt komt er niets door, tenzij barge-in aan staat."""

    def __init__(self, blokken, gedempt=True):
        self.blokken = list(blokken)
        self.gedempt = gedempt
        self.barge = False
        self.ts = 10.0
        self.cursor = None

    def latest_timestamp(self):
        return self.ts

    def set_barge_in(self, actief):
        self.barge = actief

    def advance_cursor(self, ts):
        self.cursor = ts

    def read_frame(self, after_ts=None, timeout=None):
        if not self.blokken or (self.gedempt and not self.barge):
            threading.Event().wait(0.005)
            return None
        self.ts += 0.08
        return self.ts, self.blokken.pop(0)


def _ruis(rms, n=1280, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) * rms).astype(np.int16)


def _monitor(bron, modus=barge_in.MODUS_WOORD, **kw):
    return barge_in.BargeInMonitor(stop_event=threading.Event(), source=bron, modus=modus,
                                   is_speaking=lambda: True, grace_seconds=0.2, **kw)


def _wacht(monitor, seconden=2.0):
    monitor._thread.join(seconden)


# ---------------------------------------------------------------------
# De twee fouten
# ---------------------------------------------------------------------

@pytest.mark.parametrize("modus", [barge_in.MODUS_WOORD, barge_in.MODUS_STEM])
def test_start_zet_de_bron_meteen_in_barge_in_stand(modus):
    bron = NepBron([], gedempt=True)
    m = _monitor(bron, modus=modus)
    m.start()
    try:
        assert bron.barge is True  # vroeger pas na een frame: gedempt kwam dat nooit
    finally:
        m.stop()
    assert bron.barge is False and bron.cursor is not None


def test_sneltoets_tijdens_het_uitspreken_van_een_gewoon_antwoord(monkeypatch):
    import main

    monkeypatch.setattr(main, "wait_for_wake_word", lambda *a, **k: {"detected_at": 1.0})
    monkeypatch.setattr(main, "process_command", lambda cmd, on_tekst=None: "Een lang antwoord.")
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    zinnen = iter(["vertel eens wat", ""])
    monkeypatch.setattr(main, "listen", lambda **k: next(zinnen))
    volgorde = []

    class Monitor:
        def __init__(self, stop_event=None, **k):
            self.triggered, self.trigger_ts, self.reden = False, None, None

        def start(self):
            volgorde.append("start")

        def stop(self):
            volgorde.append("stop")

    monkeypatch.setattr(main, "BargeInMonitor", Monitor)
    monkeypatch.setattr(main, "spreek_antwoord", lambda r, s=None: volgorde.append("spreek") or True)
    main.run_wake_cycle()
    # De monitor loopt tot ná het uitspreken.
    assert volgorde[:3] == ["start", "spreek", "stop"]


def test_stop_beeindigt_de_sessie(monkeypatch):
    import main

    monkeypatch.setattr(main, "wait_for_wake_word", lambda *a, **k: {"detected_at": 1.0})
    monkeypatch.setattr(main, "process_command", lambda cmd, on_tekst=None: "Een lang antwoord.")
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    gehoord = []
    monkeypatch.setattr(main, "listen", lambda **k: gehoord.append(k) or "vertel eens wat")

    class Monitor:
        def __init__(self, stop_event=None, **k):
            self.triggered, self.trigger_ts, self.reden = False, None, None

        def start(self):
            self.triggered, self.trigger_ts, self.reden = True, 5.0, barge_in.REDEN_STOP

        def stop(self):
            pass

    monkeypatch.setattr(main, "BargeInMonitor", Monitor)
    monkeypatch.setattr(main, "spreek_antwoord", lambda r, s=None: pytest.fail("niet uitspreken"))
    main.run_wake_cycle()
    assert len(gehoord) == 1  # niet verder luisteren na "stop"


# ---------------------------------------------------------------------
# Modus "woord"
# ---------------------------------------------------------------------

@pytest.mark.parametrize("tekst,verwacht", [
    ("stop", True), ("Stop!", True), ("hou op", True), ("jarvis stop", True), ("stil maar", True),
    ("laat maar", True), ("stop de muziek", False), ("ik stop ermee vandaag", False), ("", False),
])
def test_is_stopwoord(tekst, verwacht):
    assert barge_in.is_stopwoord(tekst) is verwacht


class NepWake:
    def __init__(self, raak_bij):
        self.n = 0
        self.raak_bij = raak_bij

    def predict(self, stuk):
        self.n += 1
        return {"hey_jarvis": 0.9 if self.n == self.raak_bij else 0.0}

    def reset(self):
        pass


def test_woord_jarvis_onderbreekt(monkeypatch):
    bron = NepBron([_ruis(300, seed=i) for i in range(10)])
    m = _monitor(bron)
    monkeypatch.setattr(m, "_wake_model", lambda: (NepWake(raak_bij=6), 0.5))
    m.start()
    _wacht(m)
    m.stop()
    assert m.triggered and m.reden == barge_in.REDEN_JARVIS
    assert m.trigger_ts == pytest.approx(10.0 + 6 * 0.08 + 0.08)


def test_woord_echo_onderbreekt_niet(monkeypatch):
    bron = NepBron([_ruis(800, seed=i) for i in range(25)])
    m = _monitor(bron, min_rms=200)
    gevraagd = []
    monkeypatch.setattr(m, "_wake_model", lambda: (None, None))
    monkeypatch.setattr(m, "_herken_kort", lambda audio: gevraagd.append(audio) or "stop")
    m.start()
    _wacht(m, 1.0)
    m.stop()
    assert not m.triggered and gevraagd == []


def _met_stop(monkeypatch, verstaan):
    # Echo (rustig), dan uw "stop" (veel luider), dan weer echo.
    blokken = [_ruis(500, seed=i) for i in range(6)] + [_ruis(6000, seed=50 + i) for i in range(4)] + \
        [_ruis(500, seed=90 + i) for i in range(6)]
    bron = NepBron(blokken)
    m = _monitor(bron, min_rms=200, echo_ratio=1.8)
    gevraagd = []
    monkeypatch.setattr(m, "_wake_model", lambda: (None, None))
    monkeypatch.setattr(barge_in.webrtcvad, "Vad", lambda *_: type("V", (), {"is_speech": lambda s, f, r: True})())
    monkeypatch.setattr(m, "_herken_kort", lambda audio: gevraagd.append(audio.size) or verstaan)
    m.start()
    _wacht(m)
    m.stop()
    return m, gevraagd


def test_woord_stop_onderbreekt(monkeypatch):
    m, gevraagd = _met_stop(monkeypatch, "stop")
    assert m.triggered and m.reden == barge_in.REDEN_STOP and len(gevraagd) == 1


def test_woord_ander_woord_onderbreekt_niet(monkeypatch):
    m, gevraagd = _met_stop(monkeypatch, "wat leuk")
    assert not m.triggered and len(gevraagd) == 1


def test_woord_sneltoets_werkt_ook():
    bron = NepBron([_ruis(300, seed=i) for i in range(40)])
    m = _monitor(bron)
    m._wake_model = lambda: (None, None)
    m.start()
    barge_in._sneltoets_event.set()
    _wacht(m)
    m.stop()
    assert m.triggered and m.reden == barge_in.REDEN_SNELTOETS


def test_standaardmodus_is_woord():
    import config

    assert config.BARGE_IN_MODE in barge_in.MODI
    assert barge_in.zet_modus("woord") == barge_in.MODUS_WOORD
