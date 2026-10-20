"""Tests voor Fase 17, punt 2 — voorbehoud bij onzekere informatie (A + C).

JARVIS brengt een feit, getal of recente gebeurtenis niet als harde waarheid
als hij er niet zeker van is. Dat gebeurt via een korte systeem-instructie; is
die uit, dan verandert er niets. Kwam het antwoord uit een webpagina, dan
noemt hij de bron.
"""

import pytest

import taal
from core import ai


@pytest.fixture(autouse=True)
def schone_taalstaat(monkeypatch, tmp_path):
    """Zet de taal per test terug (net als in test_fase17_taal.py)."""

    bestand = tmp_path / "taal.json"
    monkeypatch.setattr(taal, "TAAL_BESTAND", str(bestand))
    taal.reset()
    yield
    taal.reset()


# =============================================================
# _zekerheid_instructie: aan/uit en taal
# =============================================================

def test_instructie_bevat_voorbehoud_in_het_nederlands():
    tekst = ai._zekerheid_instructie()

    assert tekst, "met ZEKERHEID_ENABLED hoort er een instructie te zijn"
    assert "ZEKERHEID" in tekst
    assert "twijfel" in tekst.lower()
    assert "verzin nooit" in tekst.lower()


def test_instructie_noemt_de_vaste_onbekend_zin(monkeypatch):
    import config

    monkeypatch.setattr(config, "ZEKERHEID_ONBEKEND", "Dat weet ik niet, sorry.")

    tekst = ai._zekerheid_instructie()

    assert "Dat weet ik niet, sorry." in tekst


def test_instructie_is_leeg_als_zekerheid_uitstaat(monkeypatch):
    import config

    monkeypatch.setattr(config, "ZEKERHEID_ENABLED", False)

    assert ai._zekerheid_instructie() == ""


def test_instructie_is_engels_als_taal_engels_is(monkeypatch):
    import config

    monkeypatch.setattr(config, "ZEKERHEID_ONBEKEND_EN", "I'm not sure, sorry.")

    taal.zet(taal.ENGELS)
    tekst = ai._zekerheid_instructie()

    assert "CERTAINTY" in tekst
    assert "I'm not sure, sorry." in tekst
    assert "ZEKERHEID" not in tekst


def test_taal_instructie_en_zekerheid_staan_naast_elkaar(monkeypatch):
    """De gewone-vraag-prompt bevat beide extra regels als ze aanstaan."""
    import config

    monkeypatch.setattr(config, "ZEKERHEID_ENABLED", True)
    taal.zet(taal.ENGELS)

    inhoud = ai._taal_instructie() + ai._zekerheid_instructie()

    assert "LANGUAGE" in inhoud
    assert "CERTAINTY" in inhoud


# =============================================================
# De instructie komt echt in de systeem-prompt van ask_ai
# =============================================================

def _vraag_met_gevangen_prompt(monkeypatch):
    """Roept ask_ai aan en geeft de meegestuurde systeem-prompt terug."""
    import types

    gevangen = {}

    def nep_chat(messages=None, tools=None):
        gevangen["messages"] = messages
        return types.SimpleNamespace(
            message=types.SimpleNamespace(content="Parijs.")
        )

    monkeypatch.setattr(ai.llm, "chat", nep_chat)
    monkeypatch.setattr(ai, "is_action_request", lambda q: False)
    monkeypatch.setattr(ai, "_chat_history", lambda: [])
    monkeypatch.setattr(ai, "build_memory_context", lambda *a, **k: "")
    monkeypatch.setattr(ai, "memory_summary", lambda: "")
    monkeypatch.setattr(ai, "extract_personal_info", lambda *a, **k: "")
    monkeypatch.setattr(ai, "update_context", lambda **k: None)
    monkeypatch.setattr(ai, "add_to_history", lambda *a, **k: None)

    ai.ask_ai("wat is de hoofdstad van frankrijk?")
    return gevangen["messages"]


def test_ask_ai_prompt_bevat_zekerheid_instructie(monkeypatch):
    import config

    monkeypatch.setattr(config, "ZEKERHEID_ENABLED", True)

    messages = _vraag_met_gevangen_prompt(monkeypatch)

    systeem = messages[0]["content"]
    assert "ZEKERHEID" in systeem


def test_ask_ai_prompt_zonder_zekerheid_als_uit(monkeypatch):
    import config

    monkeypatch.setattr(config, "ZEKERHEID_ENABLED", False)

    messages = _vraag_met_gevangen_prompt(monkeypatch)

    systeem = messages[0]["content"]
    assert "ZEKERHEID" not in systeem


# =============================================================
# C: bron noemen in de tools-route
# =============================================================

def _ai_bron():
    from pathlib import Path

    return Path(ai.__file__).read_text(encoding="utf-8")


def test_tools_prompt_vraagt_om_bron_bij_webresultaat():
    bron = _ai_bron()

    assert "Bron noemen" in bron
    assert "webpagina of zoekresultaat" in bron


def test_tools_prompt_bevat_zekerheid_instructie():
    """De tools-route (waar webresultaten binnenkomen) krijgt dezelfde regel."""
    bron = _ai_bron()

    # De tools-prompt begint met _taal_instructie() + _zekerheid_instructie().
    assert "system_prompt_content = _taal_instructie() + _zekerheid_instructie()" in bron
