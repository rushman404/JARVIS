"""Fase 17 (D) — console-indicator: luistert / denkt na / praat.

JARVIS meldt in één vaste stijl wat hij doet én hoe lang het model deed
over het eerste woord en het hele antwoord:

    🎙️ Luistert naar u...
    🧠 Denkt na: <vraag>
    🗣️ JARVIS: <zin>
    💬 Reactie: eerste woord na 0.84s, klaar na 3.21s.
"""

import pytest

import status
from core import ai
from core import brain
from core import context_memory
from voice import listen as listen_mod


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _FakeResponse:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _StilleBron:
    """AudioSource die geen frames heeft (geen echte microfoon nodig)."""

    def __init__(self):
        self.aantal = 0

    def read_frame(self, after_ts=None, timeout=None):
        self.aantal += 1
        return None

    def get_cursor(self):
        return 0.0

    def latest_timestamp(self):
        return 0.0


@pytest.fixture(autouse=True)
def _schone_status(monkeypatch):
    """Elke test begint zonder lopende meting en zonder schijf- of LLM-pad."""
    status.reset()

    monkeypatch.setattr(ai, "_save_conversation", lambda *a, **k: None)
    monkeypatch.setattr(ai, "_load_conversation", lambda *a, **k: None)
    monkeypatch.setattr(ai, "extract_personal_info", lambda vraag, antwoord: "")
    monkeypatch.setattr(ai, "memory_summary", lambda: "")
    monkeypatch.setattr(context_memory, "_memory_items", lambda *a, **k: [])
    monkeypatch.setattr(brain, "ask_ai", lambda command, **kw: "antwoord")

    ai.conversation_history.clear()
    for sleutel in ai.current_context:
        ai.current_context[sleutel] = None if sleutel == "pending_choice" else ""

    yield

    status.reset()


# ---------------------------------------------------------------
# status.py op zichzelf
# ---------------------------------------------------------------

def test_beurt_begint_meldt_dat_hij_denkt(caplog):
    with caplog.at_level("INFO"):
        status.beurt_begint("wat is de hoofdstad van frankrijk?")

    assert "🧠 Denkt na: wat is de hoofdstad van frankrijk?" in caplog.text
    assert status.is_gestart() is True


def test_beurt_begint_zonder_melden_logt_niets(caplog):
    with caplog.at_level("INFO"):
        status.beurt_begint("doe iets", melden=False)

    assert "Denkt na" not in caplog.text
    assert status.is_gestart() is True


def test_beurt_klaar_zonder_start_logt_niets(caplog):
    status.reset()
    with caplog.at_level("INFO"):
        status.beurt_klaar()

    assert "Reactie" not in caplog.text


def test_beurt_klaar_zonder_eerste_woord_logt_only_totaal(caplog):
    status.beurt_begint("vraag")
    with caplog.at_level("INFO"):
        status.beurt_klaar()

    assert "Reactie klaar na" in caplog.text
    assert "eerste woord" not in caplog.text


def test_eerste_woord_en_beurt_klaar_loggen_beide_tijden(caplog):
    status.beurt_begint("vraag")
    status.eerste_woord()
    with caplog.at_level("INFO"):
        status.beurt_klaar()

    assert "eerste woord na" in caplog.text
    assert "klaar na" in caplog.text


def test_luistert_omzetten_en_spreekt_emoji(caplog):
    with caplog.at_level("INFO"):
        status.luistert()
        status.omzetten()
        status.spreekt("De hoofdstad is Parijs.")

    assert "🎙️ Luistert naar u..." in caplog.text
    assert "🔁 Zet spraak om naar tekst..." in caplog.text
    assert "🗣️ JARVIS: De hoofdstad is Parijs." in caplog.text


def test_reset_wist_de_metings(caplog):
    status.beurt_begint("vraag")
    status.eerste_woord()

    status.reset()

    assert status.is_gestart() is False

    with caplog.at_level("INFO"):
        status.beurt_klaar()

    assert "Reactie" not in caplog.text


# ---------------------------------------------------------------
# koppeling aan het pad
# ---------------------------------------------------------------

def test_brain_meldt_denken_en_print_niet(caplog, capsys, monkeypatch):
    with caplog.at_level("INFO"):
        brain.process_command("hoe laat is het")

    assert "🧠 Denkt na: hoe laat is het" in caplog.text
    uitvoer = capsys.readouterr().out
    assert "Brain kreeg" not in uitvoer


def test_listen_meldt_luisteren_en_niet_zeg_iets(caplog, monkeypatch):
    bron = _StilleBron()
    monkeypatch.setattr(listen_mod, "get_audio_source", lambda: bron)

    with caplog.at_level("INFO"):
        uitkomst = listen_mod.listen(start_ts=0.0, wacht_seconden=0.0)

    assert uitkomst == ""
    assert "🎙️ Luistert naar u..." in caplog.text
    assert "Zeg iets" not in caplog.text


# ---------------------------------------------------------------
# reactietijd in de antwoordroute
# ---------------------------------------------------------------

def test_ask_ai_logt_reactietijd_zonder_stream(monkeypatch, caplog):
    monkeypatch.setattr(
        ai.llm, "chat",
        lambda messages=None, **kw: _FakeResponse("Parijs."),
    )

    with caplog.at_level("INFO"):
        antwoord = ai.ask_ai("wat is de hoofdstad van frankrijk?")

    assert antwoord == "Parijs."
    assert "🧠 Denkt na: wat is de hoofdstad van frankrijk?" in caplog.text
    assert "💬 Reactie klaar na" in caplog.text
    assert "eerste woord" not in caplog.text


def test_ask_ai_stream_markeert_eerste_woord(monkeypatch, caplog):
    stukken = ["De hoofdstad ", "van Frankrijk ", "is Parijs."]
    monkeypatch.setattr(
        ai.llm, "chat_stream",
        lambda messages=None, **kw: iter(stukken),
    )

    gezien = []

    with caplog.at_level("INFO"):
        antwoord = ai.ask_ai(
            "wat is de hoofdstad van frankrijk?",
            on_tekst=gezien.append,
        )

    assert gezien == stukken
    assert antwoord == "".join(stukken)
    assert "eerste woord na" in caplog.text
    assert "💬 Reactie: eerste woord na" in caplog.text
