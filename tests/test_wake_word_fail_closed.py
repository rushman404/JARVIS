"""Tests voor fail-closed wake word (JARVIS luistert nooit zonder wake word).

Dekt:
  - wait_for_wake_word geeft een duidelijke status (geen stil None) als het
    model ontbreekt of er geen audiobron is
  - een gestopte AudioSource laat wait_for_wake_word direct terugkeren
  - run_wake_cycle verwerkt géén audio zonder wake word
  - de hoofdlus stopt na 3 mislukte wake-pogingen achter elkaar
  - tijdstempels in de audiostream komen van de monotone klok

Windows-audio (sounddevice) en het ONNX-model worden gemockt.
"""
import time

import numpy as np

import main
import voice.wakeword as ww
from voice.audio_stream import AudioSource


def _fake_model(monkeypatch):
    """Vervangt get_model() door een nep-model (geen ONNX-bestand nodig)."""
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.predict.side_effect = lambda frame: {"hey_jarvis": 0.0}
    monkeypatch.setattr(ww, "get_model", lambda: fake)


# ---------------------------------------------------------------
# wait_for_wake_word: duidelijke status i.p.v. stil None
# ---------------------------------------------------------------

def test_wait_for_wake_word_geeft_status_zonder_model(monkeypatch):
    """Ontbrekend model => duidelijke status, niet stil None."""
    bron = AudioSource()
    monkeypatch.setattr(ww, "get_model", lambda: None)

    resultaat = ww.wait_for_wake_word(audio_source=bron)

    assert isinstance(resultaat, dict)
    assert resultaat.get("detected_at") is None
    assert resultaat.get("status") == "geen_model"
    assert resultaat.get("error")


def test_wait_for_wake_word_geeft_status_zonder_bron(monkeypatch):
    """Geen audiobron => duidelijke status, niet stil None."""
    monkeypatch.setattr(ww, "get_audio_source", lambda: None)

    resultaat = ww.wait_for_wake_word()

    assert isinstance(resultaat, dict)
    assert resultaat.get("detected_at") is None
    assert resultaat.get("status") == "geen_bron"


def test_wait_for_wake_word_keert_terug_bij_gestopte_bron(monkeypatch):
    """Een gestopte AudioSource mag niet in een strakke lus blijven draaien."""
    _fake_model(monkeypatch)

    bron = AudioSource()
    bron._running = True   # net gestart geweest...
    bron.stop()            # ...en nu gestopt
    assert bron.is_running() is False

    begin = time.monotonic()
    resultaat = ww.wait_for_wake_word(audio_source=bron)
    duur = time.monotonic() - begin

    assert resultaat.get("detected_at") is None
    assert resultaat.get("status") == "bron_gestopt"
    assert duur < 1.0, "moet direct terugkeren, niet blijven wachten"


def test_is_running_is_initieel_false():
    assert AudioSource().is_running() is False


# ---------------------------------------------------------------
# Tijdstempels: monotone klok
# ---------------------------------------------------------------

def test_feed_tijdstempel_gebruikt_monotone_klok():
    """feed() zonder ts moet de monotone klok gebruiken, niet de wandklok."""
    bron = AudioSource()

    voor = time.monotonic()
    bron.feed(np.ones(ww.FRAME_SAMPLES, dtype=np.int16))
    ts = bron.latest_timestamp()
    na = time.monotonic()

    assert voor <= ts <= na


# ---------------------------------------------------------------
# run_wake_cycle: fail-closed
# ---------------------------------------------------------------

def test_run_wake_cycle_zonder_model_verwerkt_niets(monkeypatch):
    """Zonder wake word wordt process_command NOOIT aangeroepen."""
    bron = AudioSource()
    monkeypatch.setattr(ww, "get_audio_source", lambda: bron)
    monkeypatch.setattr(ww, "get_model", lambda: None)

    verwerkt = []
    monkeypatch.setattr(main, "process_command", lambda cmd: verwerkt.append(cmd))

    gesproken = []
    monkeypatch.setattr(main, "speak", lambda *a, **k: gesproken.append(a))

    resultaat = main.run_wake_cycle()

    assert resultaat == "geen_wake_word"
    assert verwerkt == [], "er mag geen commando verwerkt worden zonder wake word"
    assert gesproken == [], "zonder wake word geen piep en geen spraak"


# ---------------------------------------------------------------
# Hoofdlus: stoppen na 3 mislukte pogingen
# ---------------------------------------------------------------

def test_hoofdlus_stopt_na_drie_mislukte_wake_pogingen(monkeypatch):
    """Na 3 keer 'geen_wake_word' stopt start_jarvis met een duidelijke melding."""
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.llm, "check_model_available", lambda: True)

    class _FakeAudio:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(main, "AudioSource", _FakeAudio)
    monkeypatch.setattr(main, "set_audio_source", lambda source: None)
    monkeypatch.setattr(main.atexit, "register", lambda *a, **k: None)

    said = []
    monkeypatch.setattr(main, "speak", lambda *a, **k: said.append(a[0] if a else ""))

    pogingen = {"n": 0}

    def fake_cycle():
        pogingen["n"] += 1
        return "geen_wake_word"

    monkeypatch.setattr(main, "run_wake_cycle", fake_cycle)

    geslapen = []
    monkeypatch.setattr(main.time, "sleep", lambda s: geslapen.append(s))

    main.start_jarvis()

    assert pogingen["n"] == 3, "de lus moet na 3 pogingen stoppen"
    assert said.count(main.MISSING_WAKE_MODEL_MESSAGE) == 1
    assert main.STOP_MISSING_WAKE_MODEL_MESSAGE in said
    assert geslapen == [main.WAKE_RETRY_SECONDS, main.WAKE_RETRY_SECONDS]
