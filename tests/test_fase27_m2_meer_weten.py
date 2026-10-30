"""Fase 27, M2 — "Wilt u meer weten?" na een kort antwoord.

Gemini (nep) zet het aanbod alleen achter een antwoord als er meer te
vertellen is; een "ja" geeft de uitgebreide uitleg.
"""

import types

import pytest

import config
from core import ai, gemini, llm, privacy_poort, vervolg


@pytest.fixture
def nep(monkeypatch):
    verzoeken = []
    antwoorden = []

    def chat(messages, **kw):
        verzoeken.append(list(messages))
        return gemini.Antwoord(antwoorden.pop(0) if antwoorden else "Prima, sir.")

    monkeypatch.setattr(config, "GEMINI_API_KEY", "nep")
    monkeypatch.setattr(gemini, "chat", chat)
    monkeypatch.setattr(ai, "extract_personal_info", lambda *a, **k: None)
    monkeypatch.setattr(ai, "build_memory_context", lambda *a, **k: "")
    monkeypatch.setattr(ai, "memory_summary", lambda *a, **k: "")
    llm._reset_brein()
    privacy_poort._reset()
    yield types.SimpleNamespace(verzoeken=verzoeken, antwoorden=antwoorden)
    llm._reset_brein()
    privacy_poort._reset()


KORT = "Door Rayleigh-verstrooiing: blauw licht verstrooit het meest, sir. Wilt u meer weten?"


def test_instructie_gaat_mee_naar_gemini(nep):
    nep.antwoorden.append("Parijs, sir.")
    ai.ask_ai("wat is de hoofdstad van frankrijk?")
    systeem = nep.verzoeken[0][0]["content"]
    assert "MEER WETEN" in systeem and ai.MEER_WETEN_AANBOD in systeem


def test_zonder_aanbod_geen_vervolg(nep):
    nep.antwoorden.append("Parijs, sir.")
    ai.ask_ai("wat is de hoofdstad van frankrijk?")
    assert vervolg.open_vraag() is None


def test_ja_geeft_uitgebreide_uitleg(nep):
    nep.antwoorden += [KORT, "Zonlicht bevat alle kleuren. Blauw heeft een korte golflengte. Wilt u meer weten?"]
    assert ai.ask_ai("waarom is de lucht blauw?") == KORT
    assert vervolg.open_vraag()["vraag"] == ai.MEER_WETEN_AANBOD

    uitgevoerd = []
    uitleg = vervolg.beantwoord("ja graag", lambda c: uitgevoerd.append(c))
    assert uitleg == "Zonlicht bevat alle kleuren. Blauw heeft een korte golflengte."  # geen nieuw aanbod
    tweede = nep.verzoeken[1]
    assert "uitgebreidere uitleg" in tweede[0]["content"]
    inhoud = [b["content"] for b in tweede[1:]]
    assert inhoud[-3:] == ["waarom is de lucht blauw?", KORT, "Vertel me er meer over."]
    assert uitgevoerd == []


@pytest.mark.parametrize("ja", ["ja", "ja graag", "graag", "vertel maar", "vertel meer", "leg het maar uit", "zeker", "ok"])
def test_varianten_van_ja(nep, ja):
    nep.antwoorden += [KORT, "Meer uitleg."]
    ai.ask_ai("waarom is de lucht blauw?")
    assert vervolg.beantwoord(ja, lambda c: None) == "Meer uitleg."


def test_nee(nep):
    nep.antwoorden.append(KORT)
    ai.ask_ai("waarom is de lucht blauw?")
    assert vervolg.beantwoord("nee", lambda c: None) == vervolg.ANNULEER_ANTWOORD


def test_andere_vraag_laat_aanbod_vervallen(nep):
    nep.antwoorden.append(KORT)
    ai.ask_ai("waarom is de lucht blauw?")
    assert vervolg.beantwoord("hoe laat is het", lambda c: None) is None
    assert vervolg.open_vraag() is None


def test_via_het_brein(nep, monkeypatch):
    import core.brain as brain

    nep.antwoorden += [KORT, "Uitgebreide uitleg."]
    assert brain.process_command("waarom is de lucht blauw?") == KORT
    assert brain.process_command("ja") == "Uitgebreide uitleg."


def test_lokaal_als_de_vraag_niet_naar_gemini_mag(nep, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    gezien = []
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: gezien.append(kw["messages"]) or types.SimpleNamespace(
        message=types.SimpleNamespace(content="Lokale uitleg.", tool_calls=None)))
    assert ai.vertel_meer("waar woon ik", "In Badhoevedorp. Wilt u meer weten?") == "Lokale uitleg."
    assert nep.verzoeken == []
    assert [m["content"] for m in gezien[0][1:]] == ["waar woon ik", "In Badhoevedorp. Wilt u meer weten?",
                                                    "Vertel me er meer over."]


def test_fout_bij_uitleg(nep, monkeypatch):
    def kapot(*a, **k):
        raise RuntimeError("stuk")

    monkeypatch.setattr(llm, "chat", kapot)
    assert ai.vertel_meer("waarom is de lucht blauw?", KORT).startswith("Dat lukte even niet")


@pytest.mark.parametrize("tekst, aanbod", [
    ("Blauw licht verstrooit. Wilt u meer weten?", True),
    ("Blauw licht verstrooit. Wil je meer weten?", True),
    ("Blauw licht verstrooit. Wilt u er meer over weten?", True),
    ("Wilt u meer weten over de zon, dan kan dat.", False),
    ("Parijs, sir.", False),
])
def test_aanbod_herkennen(tekst, aanbod):
    assert bool(ai._MEER_AANBOD.search(tekst)) is aanbod


def test_alleen_in_de_gemini_instructie(nep, monkeypatch):
    # Het kleine lokale model krijgt de instructie niet (zou het te vaak doen).
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    gezien = []
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: gezien.append(kw["messages"]) or types.SimpleNamespace(
        message=types.SimpleNamespace(content="Parijs.", tool_calls=None)))
    ai.ask_ai("wat is de hoofdstad van frankrijk?")
    assert all("MEER WETEN" not in str(m.get("content")) for m in gezien[0])
