"""Tests voor Fase 17 — Piper-TTS en streaming-spraak.

Dekt:

1. ``voice.piper_tts``: het vinden van een stemmodel, ``is_available`` en
   het omzetten van Piper-chunks naar int16-audio.
2. ``voice.speak``: de keuze tussen Piper en de pyttsx3-terugval.
3. ``voice.speak_stream``: per zin uitspreken terwijl de tekst binnenkomt,
   inclusief stop_event (barge-in) en het afmaken van de rest.

De tests raken nooit echte audio aan: de afspeel- en spreekfuncties worden
vervangen door lijstjes.
"""

import threading

import numpy as np
import pytest

from voice import piper_tts


@pytest.fixture(autouse=True)
def schone_spraakstaat():
    """Zet de globale spraakstaat na elke test terug."""

    from voice import speak as speak_mod

    yield
    speak_mod._volume = 1.0
    speak_mod._STOP.clear()
    speak_mod._spreek_actief.clear()
    piper_tts.reset()


# =============================================================
# 1. voice.piper_tts
# =============================================================

def test_is_available_false_als_uit(monkeypatch, tmp_path):
    import config

    (tmp_path / "stem.onnx").write_bytes(b"x")
    monkeypatch.setattr(config, "PIPER_ENABLED", False)
    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "")

    assert piper_tts.is_available() is False


def test_is_available_true_met_model(monkeypatch, tmp_path):
    import config

    (tmp_path / "stem.onnx").write_bytes(b"x")
    monkeypatch.setattr(config, "PIPER_ENABLED", True)
    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "")

    assert piper_tts.is_available() is True


def test_is_available_false_zonder_model(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "PIPER_ENABLED", True)
    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path / "leeg"))
    monkeypatch.setattr(config, "PIPER_VOICE", "")

    assert piper_tts.is_available() is False


def test_resolve_model_path_kiest_eerste_onnx(monkeypatch, tmp_path):
    import config

    (tmp_path / "b.onnx").write_bytes(b"x")
    (tmp_path / "a.onnx").write_bytes(b"x")
    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "")

    pad = piper_tts._resolve_model_path()

    assert pad is not None
    assert pad.name == "a.onnx"


def test_resolve_model_path_met_expliciete_stem(monkeypatch, tmp_path):
    import config

    (tmp_path / "nl_NL-pim-medium.onnx").write_bytes(b"x")
    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "nl_NL-pim-medium.onnx")

    pad = piper_tts._resolve_model_path()

    assert pad is not None
    assert pad.name == "nl_NL-pim-medium.onnx"


def test_resolve_model_path_none_zonder_map(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path / "leeg"))
    monkeypatch.setattr(config, "PIPER_VOICE", "")

    assert piper_tts._resolve_model_path() is None


def test_get_voice_zonder_model_gooit_fout(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path / "leeg"))
    monkeypatch.setattr(config, "PIPER_VOICE", "")
    piper_tts.reset()

    with pytest.raises(RuntimeError):
        piper_tts.get_voice()


def test_synthesize_levert_int16_arrays(monkeypatch):
    class FakeChunk:
        sample_rate = 22050
        audio_int16_array = np.array([1, 2, 3], dtype=np.int16)

    class FakeVoice:
        def synthesize(self, text, syn_config=None):
            assert syn_config is not None
            yield FakeChunk()

    monkeypatch.setattr(piper_tts, "get_voice", lambda: FakeVoice())

    uit = list(piper_tts.synthesize("Hallo", volume=0.5))

    assert len(uit) == 1
    samples, rate = uit[0]
    assert rate == 22050
    assert samples.dtype == np.int16


def test_reset_vergeet_stem():
    piper_tts._voice = object()

    piper_tts.reset()

    assert piper_tts._voice is None


# =============================================================
# 2. voice.speak — backendkeuze
# =============================================================

def test_speak_gebruikt_piper_als_beschikbaar(monkeypatch):
    from voice import speak as speak_mod

    monkeypatch.setattr(piper_tts, "is_available", lambda: True)
    afgespeeld = []
    monkeypatch.setattr(
        speak_mod, "_play", lambda samples, rate: afgespeeld.append((samples, rate))
    )
    monkeypatch.setattr(
        piper_tts,
        "synthesize",
        lambda text, volume=1.0: iter([("A", 22050), ("B", 22050)]),
    )
    monkeypatch.setattr(
        speak_mod, "_say_pyttsx3", lambda text: pytest.fail("pyttsx3 toch gebruikt")
    )

    speak_mod.speak("Hallo Rushil.")

    assert afgespeeld == [("A", 22050), ("B", 22050)]


def test_speak_gebruikt_pyttsx3_zonder_piper(monkeypatch):
    from voice import speak as speak_mod

    monkeypatch.setattr(piper_tts, "is_available", lambda: False)
    geroepen = []
    monkeypatch.setattr(speak_mod, "_say_pyttsx3", lambda text: geroepen.append(text))

    speak_mod.speak("Hallo")

    assert geroepen == ["Hallo"]


def test_speak_valt_terug_op_pyttsx3_bij_piper_fout(monkeypatch):
    from voice import speak as speak_mod

    monkeypatch.setattr(piper_tts, "is_available", lambda: True)

    def kapot(text, volume=1.0):
        raise RuntimeError("geen audio")

    monkeypatch.setattr(piper_tts, "synthesize", kapot)
    geroepen = []
    monkeypatch.setattr(speak_mod, "_say_pyttsx3", lambda text: geroepen.append(text))

    speak_mod.speak("Hallo")

    assert geroepen == ["Hallo"]


def test_set_volume_onthoudt_waarde_voor_piper(monkeypatch):
    from voice import speak as speak_mod

    class FakeEngine:
        def __init__(self):
            self.volume = None

        def setProperty(self, naam, waarde):
            if naam == "volume":
                self.volume = waarde

    engine = FakeEngine()
    monkeypatch.setattr(speak_mod, "engine", engine)

    speak_mod.set_volume(0.3)
    assert speak_mod._volume == pytest.approx(0.3)
    assert engine.volume == pytest.approx(0.3)

    speak_mod.set_volume("onzin")
    assert speak_mod._volume == pytest.approx(0.3)

    speak_mod.set_volume(5)
    assert speak_mod._volume == pytest.approx(1.0)


# =============================================================
# 3. voice.speak_stream — per zin uitspreken
# =============================================================

def test_take_sentence_wacht_op_minimale_lengte(monkeypatch):
    from voice import speak as speak_mod

    monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 40)

    zin, rest = speak_mod._take_sentence("Hallo.")

    assert zin is None
    assert rest == "Hallo."


def test_take_sentence_knipt_lange_tekst_zonder_zinseinde(monkeypatch):
    from voice import speak as speak_mod

    monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 10)

    zin, rest = speak_mod._take_sentence("a" * 250)

    assert len(zin) == 200
    assert rest == "a" * 50


def test_speak_stream_spreekt_per_zin(monkeypatch):
    from voice import speak as speak_mod

    gesproken = []
    monkeypatch.setattr(speak_mod, "_say", lambda tekst, stop_event=None: gesproken.append(tekst))
    monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 5)

    def deltas():
        yield "Goedemorgen Rushil."
        yield " Ik heb het weer voor"
        yield " u opgezocht. Vandaag wordt het zonnig."

    speak_mod.speak_stream(deltas())

    assert gesproken == [
        "Goedemorgen Rushil.",
        "Ik heb het weer voor u opgezocht.",
        "Vandaag wordt het zonnig.",
    ]


def test_speak_stream_flusht_rest_zonder_punt(monkeypatch):
    from voice import speak as speak_mod

    gesproken = []
    monkeypatch.setattr(speak_mod, "_say", lambda tekst, stop_event=None: gesproken.append(tekst))
    monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 5)

    speak_mod.speak_stream(iter(["Dit is een langere zin zonder punt"]))

    assert gesproken == ["Dit is een langere zin zonder punt"]


def test_speak_stream_stopt_meteen_bij_stop_event(monkeypatch):
    from voice import speak as speak_mod

    gesproken = []
    monkeypatch.setattr(speak_mod, "_say", lambda tekst, stop_event=None: gesproken.append(tekst))
    monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 5)

    stop = threading.Event()
    stop.set()

    speak_mod.speak_stream(iter(["Hallo allemaal. Nog meer tekst."]), stop_event=stop)

    assert gesproken == []


def test_speak_stream_stopt_na_eerste_zin(monkeypatch):
    from voice import speak as speak_mod

    gesproken = []
    stop = threading.Event()

    def zeg(tekst, stop_event=None):
        gesproken.append(tekst)
        stop.set()

    monkeypatch.setattr(speak_mod, "_say", zeg)
    monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 5)

    speak_mod.speak_stream(
        iter(["Eerste zin. Tweede zin. Derde zin."]), stop_event=stop
    )

    assert gesproken == ["Eerste zin."]


def test_speak_stream_dempt_en_ontdempt_de_microfoon(monkeypatch):
    from voice import speak as speak_mod
    from voice.audio_stream import AudioSource, set_audio_source

    bron = AudioSource()
    set_audio_source(bron)
    try:
        gezien = {}

        def zeg(tekst, stop_event=None):
            gezien["tijdens"] = bron.is_muted()

        monkeypatch.setattr(speak_mod, "_say", zeg)
        monkeypatch.setattr(speak_mod, "PIPER_STREAM_MIN_CHARS", 5)

        speak_mod.speak_stream(iter(["Een zin. Nog een zin."]))

        assert gezien["tijdens"] is True, "tijdens het spreken is de mic dicht"
        assert bron.is_muted() is False, "na het spreken gaat de mic weer open"
    finally:
        set_audio_source(None)
