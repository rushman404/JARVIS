"""Tests voor Fase 17, stap F — meertalig (Nederlands standaard, Engels opvraagbaar)."""

import json

import pytest

import taal


@pytest.fixture(autouse=True)
def schone_taalstaat(monkeypatch, tmp_path):
    """Zet de taal en het taalbestand per test terug."""

    bestand = tmp_path / "taal.json"
    monkeypatch.setattr(taal, "TAAL_BESTAND", str(bestand))
    taal.reset()
    yield
    taal.reset()


# --- basis -------------------------------------------------------------


def test_standaard_taal_is_nederlands():
    assert taal.taal() == taal.NEDERLANDS
    assert not taal.is_engels()
    assert taal.spraak_code() == "nl-NL"
    assert taal.taal_naam() == "Nederlands"


def test_spraak_code_per_taal():
    assert taal.spraak_code(taal.ENGELS) == "en-US"
    assert taal.spraak_code(taal.NEDERLANDS) == "nl-NL"
    assert taal.taal_naam(taal.ENGELS) == "Engels"


# --- wissel herkennen --------------------------------------------------


@pytest.mark.parametrize(
    "commando",
    [
        "switch to english",
        "Switch to English",
        "speak english",
        "in english please",
        "praat engels",
        "in het engels graag",
        "schakel naar engels",
    ],
)
def test_detecteer_wissel_naar_engels(commando):
    assert taal.detecteer_wissel(commando) == taal.ENGELS


@pytest.mark.parametrize(
    "commando",
    [
        "switch to dutch",
        "speak dutch",
        "praat nederlands",
        "in het nederlands",
        "terug naar nederlands",
    ],
)
def test_detecteer_wissel_naar_nederlands(commando):
    assert taal.detecteer_wissel(commando) == taal.NEDERLANDS


@pytest.mark.parametrize("commando", ["wat is de hoofdstad van frankrijk?", "", None, 42])
def test_detecteer_wissel_geen_wissel(commando):
    assert taal.detecteer_wissel(commando) is None


def test_nederlands_patroon_gaat_voor_engels():
    # "terug naar nederlands" bevat geen Engels patroon, maar bij twijfel
    # wint het Nederlands-patroon.
    assert taal.detecteer_wissel("schakel terug naar nederlands") == taal.NEDERLANDS


# --- taal per onderwerp: bewust NIET (Fase 17, punt 3) -----------------
# Losse Engelse woorden in een Nederlandse zin mogen NOOIT een taalwissel
# veroorzaken. JARVIS blijft Nederlands tot u het expliciet vraagt.


@pytest.mark.parametrize(
    "commando",
    [
        "zet even Spotify op, dan kijken we de film",
        "speel mijn favorite playlist af",
        "open de game Steam en zet Discord klaar",
        "wat is de release date van die film?",
        "zet de volume op 50 en speel wat music",
        "app, laptop, wifi en internet doen het niet meer",
        "start een youtube video over python",
        "kan je mijn password manager openen?",
    ],
)
def test_engelse_woorden_in_nederlandse_zin_geven_geen_wissel(commando):
    assert taal.detecteer_wissel(commando) is None
    assert taal.taal() == taal.NEDERLANDS


def test_losse_engelse_woorden_laten_taal_nederlands():
    """Ook als de taal al eens op Engels stond en u zet hem terug: hij blijft
    daarna Nederlands, ook bij Engelse woorden in de zin."""
    taal.zet(taal.ENGELS)
    taal.wissel("praat nederlands")
    assert not taal.is_engels()

    taal.wissel("zet even Spotify op, dan kijken we de film")

    assert taal.taal() == taal.NEDERLANDS
    assert not taal.is_engels()


# --- zetten en wisselen ------------------------------------------------


def test_wissel_naar_engels_geeft_bevestiging():
    antwoord = taal.wissel("switch to English")

    assert taal.is_engels()
    assert "English" in antwoord


def test_wissel_naar_nederlands_geeft_bevestiging():
    taal.zet(taal.ENGELS)
    antwoord = taal.wissel("praat nederlands")

    assert not taal.is_engels()
    assert "Nederlands" in antwoord


def test_wissel_zonder_verzoek_geeft_niets():
    assert taal.wissel("open spotify") is None


def test_zet_ongeldige_taal_negeert():
    assert taal.zet("fr") is False
    assert not taal.is_engels()


def test_zet_bewaart_de_keuze(tmp_path):
    bestand = tmp_path / "taal.json"
    taal.zet(taal.ENGELS)

    data = json.loads(bestand.read_text(encoding="utf-8"))
    assert data == {"taal": "en", "vastgezet": True}


def test_laad_leest_de_bewaarde_keuze(tmp_path):
    bestand = tmp_path / "taal.json"
    bestand.write_text('{"taal": "en"}', encoding="utf-8")

    taal.reset()
    assert taal.laad() == taal.ENGELS
    assert taal.is_engels()


def test_laad_zonder_bestand_houdt_huidige_taal(tmp_path):
    assert taal.laad() == taal.NEDERLANDS


def test_laad_negeert_ongeldige_inhoud(tmp_path):
    bestand = tmp_path / "taal.json"
    bestand.write_text('{"taal": "de"}', encoding="utf-8")

    assert taal.laad() == taal.NEDERLANDS


# --- koppeling met de rest --------------------------------------------


def test_status_meld_taak_volgt_de_taal(monkeypatch):
    import status
    import config

    monkeypatch.setattr(config, "MELDING_ACTIE", "Moment, ik doe het even.")
    monkeypatch.setattr(config, "MELDING_ACTIE_EN", "One moment, doing it now.")

    assert status.meld_taak(status.TAAK_ACTIE) == "Moment, ik doe het even."

    taal.zet(taal.ENGELS)
    assert status.meld_taak(status.TAAK_ACTIE) == "One moment, doing it now."


def test_status_meld_taak_research_volgt_de_taal(monkeypatch):
    import status
    import config

    monkeypatch.setattr(config, "MELDING_RESEARCH", "Even opzoeken.")
    monkeypatch.setattr(config, "MELDING_RESEARCH_EN", "Let me look that up.")

    assert status.meld_taak(status.TAAK_RESEARCH) == "Even opzoeken."

    taal.zet(taal.ENGELS)
    assert status.meld_taak(status.TAAK_RESEARCH) == "Let me look that up."


def test_brain_verwerkt_taalwissel(monkeypatch):
    import core.brain as brain

    monkeypatch.setattr(brain.status, "beurt_begint", lambda *a, **k: None)
    monkeypatch.setattr(brain.status, "taalwissel", lambda: None)

    antwoord = brain._process_command_intern("switch to English")

    assert taal.is_engels()
    assert "English" in antwoord


def test_taal_instructie_alleen_bij_engels():
    from core import ai

    assert ai._taal_instructie() == ""

    taal.zet(taal.ENGELS)
    assert "English" in ai._taal_instructie()


def test_ai_systeem_prompt_bevat_taalinstructie(monkeypatch):
    from core import ai

    gevangen = {}

    class NepBericht:
        content = "ok"
        tool_calls = None

    class NepAntwoord:
        message = NepBericht()

    def nep_chat(messages=None, **kwargs):
        gevangen["messages"] = messages
        return NepAntwoord()

    monkeypatch.setattr(ai.llm, "chat", nep_chat)
    monkeypatch.setattr(ai, "_chat_history", lambda: [])
    monkeypatch.setattr(ai, "memory_summary", lambda: "")
    monkeypatch.setattr(ai, "build_memory_context", lambda *a, **k: "")
    monkeypatch.setattr(ai, "is_action_request", lambda q: False)
    monkeypatch.setattr(ai, "extract_personal_info", lambda q, a: "")
    monkeypatch.setattr(ai, "add_to_history", lambda *a, **k: None)
    monkeypatch.setattr(ai, "update_context", lambda **k: None)

    ai.ask_ai("what is the capital of france?")
    assert "LANGUAGE" not in gevangen["messages"][0]["content"]

    taal.zet(taal.ENGELS)
    ai.ask_ai("what is the capital of france?")
    assert "LANGUAGE" in gevangen["messages"][0]["content"]


def test_listen_gebruikt_taal_code(monkeypatch):
    import numpy as np
    from voice import listen as listen_mod

    gebruikt = {}

    class NepRecognizer:
        def record(self, source):
            return object()

        def recognize_google(self, audio, language=None):
            gebruikt["language"] = language
            return "hello there"

    class NepAudioFile:
        def __init__(self, buf):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(listen_mod.sr, "Recognizer", lambda: NepRecognizer())
    monkeypatch.setattr(listen_mod.sr, "AudioFile", NepAudioFile)
    monkeypatch.setattr(listen_mod, "_normalize", lambda opname: np.zeros(10, dtype=np.int16))

    listen_mod._recognize(np.zeros(10, dtype=np.int16))
    assert gebruikt["language"] == "nl-NL"

    taal.zet(taal.ENGELS)
    listen_mod._recognize(np.zeros(10, dtype=np.int16))
    assert gebruikt["language"] == "en-US"


def test_piper_kiest_engelse_stem(monkeypatch, tmp_path):
    from voice import piper_tts

    (tmp_path / "nl.onnx").write_bytes(b"x")
    (tmp_path / "en.onnx").write_bytes(b"x")

    import config

    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "nl.onnx")
    monkeypatch.setattr(config, "PIPER_VOICE_EN", "en.onnx")

    assert piper_tts._resolve_model_path().name == "nl.onnx"

    taal.zet(taal.ENGELS)
    assert piper_tts._resolve_model_path().name == "en.onnx"


def test_piper_valt_terug_op_nederlands_zonder_engelse_stem(monkeypatch, tmp_path):
    from voice import piper_tts

    (tmp_path / "nl.onnx").write_bytes(b"x")

    import config

    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "nl.onnx")
    monkeypatch.setattr(config, "PIPER_VOICE_EN", "")

    taal.zet(taal.ENGELS)
    assert piper_tts._resolve_model_path().name == "nl.onnx"
