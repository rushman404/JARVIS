"""Tests voor de gedeelde audiostream (AudioSource) en de opname daaruit.

Er wordt gewerkt met een gemockte stream van GELABELDE frames:
stilte (0), wake word (1) en commando (2000/3000). Elk frame is
gevuld met zijn label, zodat we exact kunnen zien welke frames in de
opname terechtkomen.

Windows-audio (sounddevice) en webrtcvad worden gemockt.
"""
import numpy as np
import pytest
from unittest.mock import MagicMock

import voice.wakeword as ww
import voice.listen as listen_mod
from voice.audio_stream import AudioSource


FRAME = ww.FRAME_SAMPLES  # 1280 samples


class _FakeVad:
    """webrtcvad-vervanger: spraak als de amplitude hoog genoeg is."""

    def __init__(self, level):
        self.level = level

    def is_speech(self, frame_bytes, rate):
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        return samples.size > 0 and int(np.max(np.abs(samples))) >= 1000


def _feed(source, labels, start):
    """Zet frames met oplopende tijdstempels in de bron."""
    ts = start
    for label in labels:
        source.feed(np.full(FRAME, label, dtype=np.int16), ts=ts)
        ts += 0.1
    return ts


# ---------------------------------------------------------------
# AudioSource zelf
# ---------------------------------------------------------------

def test_feed_en_read_frame_geeft_bron_oudste_eerst():
    source = AudioSource()
    source.feed(np.full(FRAME, 1, dtype=np.int16), ts=5.0)
    source.feed(np.full(FRAME, 2, dtype=np.int16), ts=6.0)

    ts1, frame1 = source.read_frame(after_ts=None)
    assert ts1 == 5.0
    assert int(frame1[0]) == 1

    ts2, frame2 = source.read_frame(after_ts=ts1)
    assert ts2 == 6.0
    assert int(frame2[0]) == 2


def test_mute_gooit_frames_weg():
    source = AudioSource()
    source.mute()
    source.feed(np.full(FRAME, 5, dtype=np.int16), ts=1.0)
    source.unmute()
    source.feed(np.full(FRAME, 6, dtype=np.int16), ts=2.0)

    assert source.latest_timestamp() == 2.0
    _, frame = source.read_frame(after_ts=None)
    assert int(frame[0]) == 6


def test_latest_timestamp_leeg_is_none():
    assert AudioSource().latest_timestamp() is None


# ---------------------------------------------------------------
# Opname vanaf het detectiemoment
# ---------------------------------------------------------------

def _wake_mock(monkeypatch):
    fake_model = MagicMock()
    fake_model.predict.side_effect = (
        lambda frame: {"hey_jarvis": 0.9 if int(np.max(frame)) == 1 else 0.0}
    )
    monkeypatch.setattr(ww, "get_model", lambda: fake_model)


def test_opname_begint_bij_eerste_commando_en_bevat_geen_wake(monkeypatch):
    ww.last_detection = 0.0
    source = AudioSource()
    _wake_mock(monkeypatch)
    monkeypatch.setattr(listen_mod.webrtcvad, "Vad", _FakeVad)

    # wake word (1), dan meteen het commando (2000), dan stilte (0)
    _feed(source, [1] + [2000] * 6 + [0] * 30, start=10.0)

    resultaat = ww.wait_for_wake_word(audio_source=source)
    assert resultaat["audio"] is None

    opname = listen_mod._capture(start_ts=resultaat["detected_at"], audio_source=source)

    assert opname is not None
    assert opname.size > 0
    # De opname begint met het eerste commando-frame...
    assert int(opname[0]) == 2000
    # ...en bevat nooit een wake-word-frame.
    assert not np.any(opname == 1)


def test_twee_rondes_hergebruiken_geen_audio(monkeypatch):
    ww.last_detection = 0.0
    source = AudioSource()
    _wake_mock(monkeypatch)
    monkeypatch.setattr(listen_mod.webrtcvad, "Vad", _FakeVad)

    # ronde 1: commando-label 2000
    _feed(source, [1] + [2000] * 6 + [0] * 30, start=10.0)
    det1 = ww.wait_for_wake_word(audio_source=source)["detected_at"]
    opname1 = listen_mod._capture(start_ts=det1, audio_source=source)
    assert opname1 is not None
    assert np.any(opname1 == 2000)

    # ronde 2: ruim na de cooldown, commando-label 3000
    _feed(source, [1] + [3000] * 6 + [0] * 30, start=20.0)
    det2 = ww.wait_for_wake_word(audio_source=source)["detected_at"]
    opname2 = listen_mod._capture(start_ts=det2, audio_source=source)
    assert opname2 is not None

    # Nooit audio van de vorige ronde in de nieuwe opname.
    assert np.any(opname2 == 3000)
    assert not np.any(opname2 == 2000)


# ---------------------------------------------------------------
# Lees-cursor: geen replay binnen één wake-sessie
# ---------------------------------------------------------------

def test_cursor_gaat_nooit_terug():
    source = AudioSource()
    assert source.get_cursor() is None

    source.advance_cursor(5.0)
    assert source.get_cursor() == 5.0

    source.advance_cursor(3.0)
    assert source.get_cursor() == 5.0

    source.advance_cursor(None)
    assert source.get_cursor() == 5.0

    source.reset_cursor(1.0)
    assert source.get_cursor() == 1.0


def test_cursor_volgt_gelezen_audio(monkeypatch):
    source = AudioSource()
    monkeypatch.setattr(listen_mod.webrtcvad, "Vad", _FakeVad)

    _feed(source, [2000] * 6 + [0] * 30, start=10.0)
    listen_mod._capture(start_ts=None, audio_source=source)

    # Na de opname staat de cursor voorbij het commando in de buffer.
    assert source.get_cursor() is not None


def test_opeenvolgende_opdrachten_in_een_sessie_hergebruiken_geen_audio(monkeypatch):
    """Twee opdrachten binnen één wake-sessie: de tweede mag de audio van de
    eerste niet opnieuw inlezen en uitvoeren (de replay-bug)."""
    ww.last_detection = 0.0
    source = AudioSource()
    _wake_mock(monkeypatch)
    monkeypatch.setattr(listen_mod.webrtcvad, "Vad", _FakeVad)

    # Fase 1: wake (1), opdracht A (2000), stilte.
    _feed(source, [1] + [2000] * 6 + [0] * 30, start=10.0)

    det = ww.wait_for_wake_word(audio_source=source)["detected_at"]

    # Eerste opdracht begint bij het detectiemoment.
    opname_a = listen_mod._capture(start_ts=det, audio_source=source)
    assert opname_a is not None
    assert np.any(opname_a == 2000)

    # Fase 2: de tweede opdracht komt binnen (zónder nieuw wake word).
    _feed(source, [3000] * 6 + [0] * 30, start=20.0)

    # Tweede opdracht: geen start_ts -> lees-cursor, dus na opdracht A.
    opname_b = listen_mod._capture(audio_source=source)
    assert opname_b is not None
    assert np.any(opname_b == 3000)
    assert not np.any(opname_b == 2000)
