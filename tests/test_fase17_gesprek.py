"""Fase 17 (C) — gespreksflow: multi-beurt context.

Deze tests dekken de twee gaten die in stap 6 zijn gedicht:

1. Bij een verwijzing zonder woordoverlap ("en dat dan?", "sluit hem")
   bleef het blok "1. DIT GESPREK" leeg, terwijl de regels zeggen dat het
   gesprek dan zwaarder weegt. Nu vult JARVIS dat blok met de meest
   recente context, zodat de AI iets heeft om naar te verwijzen.
2. De gewone-vraag-tak gaf het recente gesprek dubbel mee: één keer als
   echte berichten en nog een keer in blok "2. RECENTE GESPREK". Nu niet
   meer (history=None), net als de tools-tak.
"""

import pytest

from core import ai
from core import context_memory


CTX = {
    "last_action": "normale vraag",
    "last_command": "open spotify",
    "last_program": "spotify",
    "last_result": "Spotify is geopend",
}


def _lege_context():
    return {
        "last_action": None,
        "last_command": None,
        "last_program": None,
        "last_file": None,
        "last_website": None,
        "last_ha_entity": None,
        "last_result": None,
        "last_calculation": None,
        "last_ha_domain": None,
        "last_ha_name": None,
        "pending_choice": None,
    }


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _FakeResponse:
    def __init__(self, content):
        self.message = _FakeMessage(content)


@pytest.fixture(autouse=True)
def _schone_omgeving(monkeypatch):
    """Isoleer de test: geen echt geheugen, geen bestanden op schijf."""
    monkeypatch.setattr(context_memory, "_memory_items", lambda *a, **k: [])
    monkeypatch.setattr(ai, "memory_summary", lambda: "(geen geheugen)")
    monkeypatch.setattr(ai, "_save_conversation", lambda *a, **k: None)
    monkeypatch.setattr(ai, "_load_conversation", lambda *a, **k: None)
    monkeypatch.setattr(ai, "extract_personal_info", lambda vraag, antwoord: "")
    ai.conversation_history.clear()
    # Let op: niet clear()en. update_context() zet alleen waarden voor
    # sleutels die al bestaan, dus de sleutels moeten blijven staan.
    for sleutel in ai.current_context:
        ai.current_context[sleutel] = None if sleutel == "pending_choice" else ""
    yield


# ---------------------------------------------------------------
# build_memory_context: blok 1 vult zich bij een verwijzing
# ---------------------------------------------------------------

def test_verwijzing_zonder_overlap_vult_dit_gesprek():
    blok = context_memory.build_memory_context("en dat dan?", context=dict(CTX), history=[])
    assert "1. DIT GESPREK" in blok
    assert "spotify" in blok


def test_zonder_verwijzing_en_zonder_overlap_geen_blok():
    blok = context_memory.build_memory_context(
        "wat is de hoofdstad van frankrijk?", context=dict(CTX), history=[]
    )
    assert blok == ""


def test_lege_context_leeg_blok_bij_verwijzing():
    blok = context_memory.build_memory_context(
        "en dat dan?", context=_lege_context(), history=[]
    )
    assert blok == ""


def test_rank_context_items_blijft_leeg_bij_lege_velden():
    assert context_memory.rank_context_items("en dat dan?", _lege_context()) == []


def test_has_conversation_reference():
    assert context_memory.has_conversation_reference("en dat dan?", dict(CTX)) is True
    assert context_memory.has_conversation_reference("open spotify", dict(CTX)) is False


# ---------------------------------------------------------------
# de hulpfunctie voor de terugval
# ---------------------------------------------------------------

def test_recent_context_items_in_gewichtsorde():
    items = context_memory._recent_context_items(dict(CTX))
    velden = [i["field"] for i in items]
    assert velden[0] == "last_action"
    assert items[0]["score"] == 1.4
    assert "last_command" in velden
    assert "last_program" in velden
    assert all(i["score"] > 0 for i in items)


def test_recent_context_items_max():
    items = context_memory._recent_context_items(dict(CTX), max_items=2)
    assert len(items) == 2


def test_recent_context_items_ha_domein():
    ctx = _lege_context()
    ctx["last_ha_entity"] = "lamp"
    ctx["last_ha_domain"] = "light"
    items = context_memory._recent_context_items(ctx)
    assert items[0]["value"] == "lamp (light)"


# ---------------------------------------------------------------
# ai.ask_ai: gesprek niet dubbel + multi-beurt
# ---------------------------------------------------------------

def _vraag_aan_ai(monkeypatch, antwoord="Ok."):
    calls = []

    def fake_chat(messages=None, **kwargs):
        calls.append(messages)
        return _FakeResponse(antwoord)

    monkeypatch.setattr(ai.llm, "chat", fake_chat)
    return calls


def _systeemtekst(messages):
    return "\n".join(m["content"] for m in messages if m["role"] == "system")


def test_gewone_vraag_geeft_gesprek_niet_dubbel(monkeypatch):
    calls = _vraag_aan_ai(monkeypatch, "Parijs.")
    ai.add_to_history("user", "open kladblok")
    ai.add_to_history("assistant", "Kladblok geopend.")
    ai.current_context.update(dict(CTX))

    ai.ask_ai("wat is de hoofdstad van frankrijk?")

    messages = calls[0]
    systeem = _systeemtekst(messages)
    assert "RECENTE GESPREK" not in systeem

    rollen = [(m["role"], m["content"]) for m in messages]
    assert ("user", "open kladblok") in rollen
    assert ("assistant", "Kladblok geopend.") in rollen
    assert rollen[-1] == ("user", "wat is de hoofdstad van frankrijk?")


def test_vervolgvraag_ziet_context_van_vorige_beurt(monkeypatch):
    calls = _vraag_aan_ai(monkeypatch, "Parijs.")

    ai.ask_ai("wat is de hoofdstad van frankrijk?")
    ai.ask_ai("en dat dan?")

    tweede = calls[1]
    systeem = _systeemtekst(tweede)

    # De context van beurt 1 is zichtbaar in blok "1. DIT GESPREK".
    assert "1. DIT GESPREK" in systeem
    assert "wat is de hoofdstad van frankrijk?" in systeem

    # Beurt 1 staat als echte berichten in de prompt (multi-beurt).
    rollen = [(m["role"], m["content"]) for m in tweede]
    assert ("user", "wat is de hoofdstad van frankrijk?") in rollen
    assert rollen[-1] == ("user", "en dat dan?")
