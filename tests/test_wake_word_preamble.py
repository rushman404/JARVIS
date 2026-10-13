"""Tests voor de noodfix tegen wake-word-audio als commando.

Dekt:
  - strip_wake_phrase verwijdert een aanhef ALLEEN aan het begin
  - wait_for_wake_word geeft nooit audio van vóór de detectie terug
  - listen() negeert de (compatibiliteits)parameter preamble_audio
  - de cooldown in wakeword.py gebruikt een module-variabele

Windows-audio (sounddevice) wordt gemockt; frames worden gelabeld.
"""
import numpy as np
import pytest

import main
import voice.wakeword as ww
import voice.listen as listen_mod
from voice.audio_stream import AudioSource


# ---------------------------------------------------------------
# strip_wake_phrase
# ---------------------------------------------------------------

@pytest.mark.parametrize("tekst,verwacht", [
    ("hey jarvis zet de lamp aan", "zet de lamp aan"),
    ("jarvis, ja", "ja"),
    ("ja", "ja"),
    ("jarvis", ""),
    ("zet jarvis aan", "zet jarvis aan"),
    ("hé jarvis doe het licht aan", "doe het licht aan"),
    ("hee jarvis, wat is het weer", "wat is het weer"),
    ("hoi jarvis stop", "stop"),
])
def test_strip_wake_phrase(tekst, verwacht):
    """Alleen een aanhef aan het begin wordt verwijderd, nergens anders."""
    assert main.strip_wake_phrase(tekst) == verwacht


# ---------------------------------------------------------------
# wait_for_wake_word: nooit pre-detectie audio
# ---------------------------------------------------------------

def _vul_met_labels(source, labels, start=10.0, stap=0.5):
    """Zet gelabelde frames in de bron; geeft (label -> tijdstip) terug."""
    tijden = {}
    ts = start
    for label in labels:
        frame = np.full(ww.FRAME_SAMPLES, label, dtype=np.int16)
        source.feed(frame, ts=ts)
        tijden.setdefault(label, ts)
        ts += stap
    return tijden


def test_wait_for_wake_word_geeft_geen_predetectie_audio(monkeypatch):
    """Bij detectie mag NOOIT audio terugkomen, alleen het detectietijdstip."""
    ww.last_detection = 0.0
    source = AudioSource()

    # stilte (0), wake word (1), stilte (0)
    tijden = _vul_met_labels(source, [0, 0, 1, 0, 0])
    wake_ts = tijden[1]

    monkeypatch.setattr(ww.model, "reset", lambda: None)
    monkeypatch.setattr(
        ww.model, "predict",
        lambda frame: {"hey_jarvis": 0.9 if int(np.max(frame)) == 1 else 0.0},
    )

    resultaat = ww.wait_for_wake_word(audio_source=source)

    assert isinstance(resultaat, dict)
    assert resultaat.get("audio") is None
    assert resultaat.get("detected_at") == wake_ts


def test_last_detection_is_module_variabele(monkeypatch):
    """De cooldown moet een module-variabele gebruiken, geen lokale."""
    ww.last_detection = 0.0
    source = AudioSource()
    tijden = _vul_met_labels(source, [0, 1, 0])
    wake_ts = tijden[1]

    monkeypatch.setattr(ww.model, "reset", lambda: None)
    monkeypatch.setattr(
        ww.model, "predict",
        lambda frame: {"hey_jarvis": 0.9 if int(np.max(frame)) == 1 else 0.0},
    )

    ww.wait_for_wake_word(audio_source=source)

    # Detectie moet de module-variabele hebben bijgewerkt (niet lokaal).
    assert ww.last_detection == wake_ts


# ---------------------------------------------------------------
# listen(): preamble wordt genegeerd
# ---------------------------------------------------------------

def test_listen_negeert_preamble(monkeypatch):
    """De meegegeven preamble mag niet vóór de opname worden geplakt."""
    opgenomen = np.ones(1000, dtype=np.int16)
    monkeypatch.setattr(listen_mod, "_capture", lambda *a, **k: opgenomen)

    gezien = {}

    def fake_recognize(recording):
        gezien["recording"] = recording
        return "ja"

    monkeypatch.setattr(listen_mod, "_recognize", fake_recognize)

    preamble = np.full(500, 999, dtype=np.int16)
    resultaat = listen_mod.listen(preamble_audio=preamble)

    assert resultaat == "ja"
    assert len(gezien["recording"]) == len(opgenomen)
    assert not np.any(gezien["recording"] == 999)
