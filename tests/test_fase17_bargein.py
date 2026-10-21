"""Tests voor Fase 17 — barge-in (B1): JARVIS onderbreken terwijl hij praat.

Dekt:

1. ``voice.audio_stream.AudioSource``: frames bewaren tijdens demping als
   barge-in aanstaat (zodat de monitor u kan horen onderbreken).
2. ``voice.speak``: het globale stop-signaal (``stop_speaking``/``_gestopt``)
   en het meteen afbreken van ``speak_stream``.
3. ``voice.barge_in.BargeInMonitor``: onderbreken via uw stem en via de
   sneltoets, zonder valse meldingen bij stilte of als JARVIS niet praat.
4. ``main.run_wake_cycle``: na een onderbreking gaat JARVIS meteen verder
   luisteren vanaf het moment van onderbreken.

Er wordt nooit echte audio afgespeeld of opgenomen: alle bronnen zijn nep
en de VAD is een stub.
"""

import threading
import time

import numpy as np
import pytest

from voice import barge_in


@pytest.fixture(autouse=True)
def schone_bargein_staat():
    """Zet de globale barge-in- en spraakstaat na elke test terug."""
    from voice import speak as speak_mod

    barge_in._sneltoets_event.clear()
    barge_in._modus = None
    yield
    barge_in._sneltoets_event.clear()
    barge_in._modus = None
    speak_mod._STOP.clear()
    speak_mod._spreek_actief.clear()


def _wacht(conditie, timeout=2.0):
    einde = time.time() + timeout
    while time.time() < einde:
        if conditie():
            return True
        time.sleep(0.01)
    return conditie()


def _blok(ts, amplitude, n=1280):
    """Eén audioblok (80 ms) met een vaste amplitude."""
    return (ts, np.full(n, amplitude, dtype=np.int16))


class _FakeVad:
    def __init__(self, antwoord=True):
        self._antwoord = antwoord

    def is_speech(self, frame, rate):
        return self._antwoord


class _FakeSource:
    """Doorloopt een vaste lijst frames; daarna stil."""

    def __init__(self, frames):
        self._frames = list(frames)
        self._i = 0
        self.barge = False
        self.cursor = 0.0
        self.barge_calls = []
        self.read_calls = 0

    def read_frame(self, after_ts=None, timeout=None):
        self.read_calls += 1
        if self._i >= len(self._frames):
            time.sleep(0.005)
            return None
        ts, frame = self._frames[self._i]
        self._i += 1
        return ts, frame

    def latest_timestamp(self):
        return self._frames[-1][0] if self._frames else None

    def advance_cursor(self, ts):
        if ts is not None:
            self.cursor = max(self.cursor, ts)

    def set_barge_in(self, actief):
        self.barge = bool(actief)
        self.barge_calls.append(bool(actief))


# =============================================================
# 1. voice.audio_stream — frames tijdens barge-in
# =============================================================

def test_barge_in_bewaart_frames_ondanks_demping():
    from voice.audio_stream import AudioSource

    bron = AudioSource()
    frame = np.zeros(1280, dtype=np.int16)

    bron.mute()
    bron.feed(frame, ts=1.0)
    assert bron.latest_timestamp() is None  # gedempt: niets bewaard

    bron.set_barge_in(True)
    assert bron.is_barge_in() is True
    bron.feed(frame, ts=2.0)
    assert bron.latest_timestamp() == 2.0  # barge-in: wel bewaard

    bron.set_barge_in(False)
    bron.feed(frame, ts=3.0)
    assert bron.latest_timestamp() == 2.0  # weer gedempt

    bron.unmute()
    bron.feed(frame, ts=4.0)
    assert bron.latest_timestamp() == 4.0


# =============================================================
# 2. voice.speak — stop-signaal
# =============================================================

def test_stop_speaking_zet_stop_event(monkeypatch):
    from voice import speak as speak_mod

    monkeypatch.setattr(speak_mod, "sd", type("SD", (), {"stop": lambda: None})())
    speak_mod._STOP.clear()
    assert speak_mod._gestopt() is False

    speak_mod.stop_speaking()
    assert speak_mod._STOP.is_set()
    assert speak_mod._gestopt() is True


def test_gestopt_reageert_op_meegegeven_event():
    from voice import speak as speak_mod

    speak_mod._STOP.clear()
    event = threading.Event()
    assert speak_mod._gestopt(event) is False
    event.set()
    assert speak_mod._gestopt(event) is True


def test_speak_stream_onderbroken_stopt_meteen(monkeypatch):
    from voice import speak as speak_mod

    gespeeld = []
    chunks = [(np.zeros(10, dtype=np.int16), 16000) for _ in range(5)]

    def fake_synth(text, volume=1.0):
        return iter(chunks)

    def fake_play(samples, rate):
        gespeeld.append(samples)
        if len(gespeeld) == 1:
            speak_mod.stop_speaking()

    monkeypatch.setattr(speak_mod.piper_tts, "synthesize", fake_synth)
    monkeypatch.setattr(speak_mod, "_play", fake_play)
    monkeypatch.setattr(speak_mod, "_use_piper", lambda: True)
    monkeypatch.setattr(speak_mod, "_mute_microphone", lambda: None)
    monkeypatch.setattr(speak_mod, "_unmute_microphone", lambda: None)

    speak_mod.speak_stream(iter(["Dit is een langere zin om uit te spreken. "]))

    assert len(gespeeld) == 1  # meteen gestopt na de onderbreking
    assert speak_mod._STOP.is_set()


# =============================================================
# 3. voice.barge_in — de monitor
# =============================================================

def test_monitor_trigger_op_stem(monkeypatch):
    monkeypatch.setattr(barge_in.webrtcvad, "Vad", lambda *a, **k: _FakeVad(True))
    bron = _FakeSource([_blok(i * 0.08, 6000) for i in range(6)])
    stop = threading.Event()

    monitor = barge_in.BargeInMonitor(
        stop_event=stop, source=bron, is_speaking=lambda: True,
        frames_needed=3, min_rms=1000.0, echo_ratio=2.0, grace_seconds=0.0,
        modus=barge_in.MODUS_STEM,
    )
    monitor.start()
    try:
        assert _wacht(lambda: monitor.triggered)
    finally:
        monitor.stop()

    assert monitor.triggered is True
    assert stop.is_set()
    assert monitor.trigger_ts is not None


def test_monitor_geen_trigger_bij_stilte(monkeypatch):
    monkeypatch.setattr(barge_in.webrtcvad, "Vad", lambda *a, **k: _FakeVad(True))
    bron = _FakeSource([_blok(i * 0.08, 0) for i in range(6)])
    stop = threading.Event()

    monitor = barge_in.BargeInMonitor(
        stop_event=stop, source=bron, is_speaking=lambda: True,
        frames_needed=3, min_rms=1000.0, grace_seconds=0.0,
        modus=barge_in.MODUS_STEM,
    )
    monitor.start()
    try:
        _wacht(lambda: False, timeout=0.3)
    finally:
        monitor.stop()

    assert monitor.triggered is False
    assert not stop.is_set()


def test_monitor_geen_trigger_als_jarvis_niet_praat(monkeypatch):
    monkeypatch.setattr(barge_in.webrtcvad, "Vad", lambda *a, **k: _FakeVad(True))
    bron = _FakeSource([_blok(i * 0.08, 9000) for i in range(6)])
    stop = threading.Event()

    monitor = barge_in.BargeInMonitor(
        stop_event=stop, source=bron, is_speaking=lambda: False,
        frames_needed=3, min_rms=1000.0, grace_seconds=0.0,
    )
    monitor.start()
    try:
        _wacht(lambda: False, timeout=0.3)
    finally:
        monitor.stop()

    assert monitor.triggered is False
    assert not stop.is_set()


def test_monitor_trigger_op_sneltoets(monkeypatch):
    bron = _FakeSource([_blok(0.0, 0)])
    stop = threading.Event()

    monitor = barge_in.BargeInMonitor(
        stop_event=stop, source=bron, is_speaking=lambda: False,
    )
    monitor.start()
    try:
        barge_in._sneltoets_event.set()
        assert _wacht(lambda: monitor.triggered)
    finally:
        monitor.stop()

    assert monitor.triggered is True
    assert stop.is_set()
    assert monitor.trigger_ts is None


def test_monitor_zet_barge_in_weer_uit_bij_stop():
    bron = _FakeSource([_blok(0.0, 0)])
    monitor = barge_in.BargeInMonitor(
        source=bron, is_speaking=lambda: True, frames_needed=99,
        min_rms=1e9, grace_seconds=0.0, modus=barge_in.MODUS_STEM,
    )
    monitor.start()
    assert _wacht(lambda: bron.barge is True)
    monitor.stop()
    assert bron.barge is False


def test_monitor_zonder_bron_stopt_met_warning(caplog):
    monitor = barge_in.BargeInMonitor(
        source=None, is_speaking=lambda: True, modus=barge_in.MODUS_STEM,
    )
    monitor._source_obj = lambda: None  # geen audiobron
    monitor.start()
    try:
        assert _wacht(lambda: not monitor._thread.is_alive())
    finally:
        monitor.stop()
    assert monitor.triggered is False


# =============================================================
# 3b. Modus: stem / sneltoets / uit
# =============================================================

def _eigen_stem_frames(amplitude_later, blokken_later=45):
    """JARVIS' eigen stem: 0,32 s op 2000, daarna ``blokken_later`` blokken."""
    frames = [_blok(i * 0.08, 2000) for i in range(4)]
    frames.extend(
        _blok(0.32 + i * 0.08, amplitude_later) for i in range(blokken_later)
    )
    return frames


def test_eigen_stem_onderbreekt_zichzelf_niet(monkeypatch):
    """Een luidere zinsdeel van JARVIS (2x) mag hem niet onderbreken."""
    monkeypatch.setattr(barge_in.webrtcvad, "Vad", lambda *a, **k: _FakeVad(True))
    bron = _FakeSource(_eigen_stem_frames(4000))
    stop = threading.Event()
    monitor = barge_in.BargeInMonitor(
        stop_event=stop, source=bron, is_speaking=lambda: True,
        frames_needed=8, min_rms=1000.0, echo_ratio=1.8,
        grace_seconds=0.3, modus=barge_in.MODUS_STEM,
    )
    monitor.start()
    try:
        time.sleep(0.3)
        assert monitor.triggered is False
        assert not stop.is_set()
    finally:
        monitor.stop()


def test_gebruiker_op_3x_onderbreekt_wel(monkeypatch):
    """Een gebruiker die 3x boven de echo uitkomt, onderbreekt wél."""
    monkeypatch.setattr(barge_in.webrtcvad, "Vad", lambda *a, **k: _FakeVad(True))
    bron = _FakeSource(_eigen_stem_frames(6000))
    stop = threading.Event()
    monitor = barge_in.BargeInMonitor(
        stop_event=stop, source=bron, is_speaking=lambda: True,
        frames_needed=8, min_rms=1000.0, echo_ratio=1.8,
        grace_seconds=0.3, modus=barge_in.MODUS_STEM,
    )
    monitor.start()
    try:
        assert _wacht(lambda: monitor.triggered)
        assert stop.is_set()
    finally:
        monitor.stop()


def test_modus_sneltoets_luistert_niet_naar_de_stem():
    """In de sneltoets-modus wordt de microfoon niet afgeluisterd."""
    bron = _FakeSource(_eigen_stem_frames(6000))
    monitor = barge_in.BargeInMonitor(
        stop_event=threading.Event(), source=bron, is_speaking=lambda: True,
        frames_needed=3, min_rms=1000.0, modus=barge_in.MODUS_SNELTOETS,
    )
    monitor.start()
    try:
        time.sleep(0.2)
        assert bron.read_calls == 0
        assert monitor.triggered is False
    finally:
        monitor.stop()


def test_modus_uit_start_geen_monitor():
    """In de modus "uit" start er geen monitor-thread."""
    monitor = barge_in.BargeInMonitor(
        stop_event=threading.Event(), is_speaking=lambda: True,
        modus=barge_in.MODUS_UIT,
    )
    monitor.start()
    try:
        assert monitor._thread is None
        assert monitor.triggered is False
    finally:
        monitor.stop()


def test_commando_onderbreken_met_stem_uit_en_aan():
    from core.proactive_commands import try_barge_in_command

    antwoord = try_barge_in_command("zet onderbreken met stem uit")
    assert antwoord is not None
    assert "sneltoets" in antwoord
    assert barge_in.huidige_modus() == barge_in.MODUS_SNELTOETS

    antwoord = try_barge_in_command("zet onderbreken met stem aan")
    assert antwoord is not None
    assert barge_in.huidige_modus() == barge_in.MODUS_STEM


# =============================================================
# 4. main.run_wake_cycle — meteen verder na onderbreking
# =============================================================

def test_run_wake_cycle_gaat_verder_na_onderbreking(monkeypatch):
    import main

    monkeypatch.setattr(
        main, "wait_for_wake_word", lambda *a, **k: {"detected_at": 1.0}
    )
    monkeypatch.setattr(
        main, "process_command", lambda cmd, on_tekst=None: "Een lang antwoord."
    )
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)

    start_ts_waarden = []

    def fake_listen(start_ts=None, **k):
        start_ts_waarden.append(start_ts)
        if len(start_ts_waarden) >= 2:
            return ""  # geen spraak meer -> sessie klaar
        return "jarvis vertel eens wat"

    monkeypatch.setattr(main, "listen", fake_listen)

    gebeurtenissen = []

    class FakeMonitor:
        def __init__(self, stop_event=None, **k):
            self.stop_event = stop_event
            self.triggered = False
            self.trigger_ts = None

        def start(self):
            self.triggered = True
            self.trigger_ts = 7.5

        def stop(self):
            gebeurtenissen.append("gestopt")

    monkeypatch.setattr(main, "BargeInMonitor", FakeMonitor)
    monkeypatch.setattr(
        main, "spreek_antwoord",
        lambda response, stroom=None: gebeurtenissen.append("spreek") or True,
    )

    main.run_wake_cycle()

    assert start_ts_waarden[0] == 1.0
    assert start_ts_waarden[1] == 7.5
    assert "spreek" not in gebeurtenissen
    assert "gestopt" in gebeurtenissen
