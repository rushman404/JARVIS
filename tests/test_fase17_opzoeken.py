"""Tests voor Fase 17: het aanbod "Wil je dat ik het opzoek?".

Twijfelt JARVIS, dan biedt hij aan om het op te zoeken. Een "ja" daarop moest
eerder nog ergens landen: nu zet het aanbod een korte pending en voert alleen
een expliciet "ja" de zoekopdracht uit, met de oorspronkelijke vraag en met
bronvermelding. Bij "nee", bij een verlopen pending of zonder pending gebeurt
er niets.
"""

import pytest

from core import brain, confirmation, opzoeken

ZIN = "Dat weet ik niet zeker. Wil je dat ik het opzoek?"
VRAAG = "wat is de hoofdstad van frankrijk?"


@pytest.fixture(autouse=True)
def schone_pending():
    """Zet de pending-state van dit proces voor en na elke test terug."""
    from core import ai

    vorige = ai.current_context.get("pending_choice")
    ai.current_context["pending_choice"] = None
    yield
    ai.current_context["pending_choice"] = vorige


@pytest.fixture
def nep_zoekfunctie(monkeypatch):
    """Vervangt de echte webopzoeking en houdt de vragen bij."""
    import actions.web as web

    vragen = []

    def nep_search_and_fetch(query, max_pages=1):
        vragen.append((query, max_pages))
        return {
            "ok": True,
            "query": query,
            "pages": [{
                "search_title": "Wikipedia",
                "title": "Parijs",
                "url": "https://nl.wikipedia.org/wiki/Parijs",
                "text": "Parijs is de hoofdstad van Frankrijk.",
            }],
        }

    monkeypatch.setattr(web, "search_and_fetch", nep_search_and_fetch)
    return vragen


# =============================================================
# Het aanbod zet een pending
# =============================================================

def test_aanbod_zet_een_korte_pending():
    from config import OPZOEK_CONFIRM_TTL_SECONDS

    pending = opzoeken.onthoud_aanbod(VRAAG, ZIN)

    assert pending is not None
    assert pending["kind"] == opzoeken.KIND
    assert pending["vraag"] == VRAAG
    assert OPZOEK_CONFIRM_TTL_SECONDS <= 60


def test_gewone_zin_zet_geen_pending():
    assert opzoeken.onthoud_aanbod(VRAAG, "Ik kan dat opzoeken.") is None


def test_process_command_onthoudt_de_vraag_bij_een_aanbod(monkeypatch):
    monkeypatch.setattr(
        brain, "_process_command_intern", lambda command, on_tekst=None: ZIN
    )

    antwoord = brain.process_command(VRAAG)

    assert antwoord == ZIN
    pending = confirmation.get_pending()
    assert pending is not None
    assert pending["kind"] == opzoeken.KIND
    assert pending["vraag"] == VRAAG


# =============================================================
# "ja" voert de opzoeking uit
# =============================================================

def test_ja_na_aanbod_start_de_opzoeking(nep_zoekfunctie):
    opzoeken.onthoud_aanbod(VRAAG, ZIN)

    antwoord = brain.handle_pending_choice("ja")

    assert nep_zoekfunctie == [(VRAAG, 1)]
    assert "Bron 1" in antwoord
    assert "https://nl.wikipedia.org/wiki/Parijs" in antwoord
    assert "Parijs is de hoofdstad van Frankrijk." in antwoord
    assert confirmation.get_pending() is None


def test_ja_zonder_pending_zoekt_niets_op(nep_zoekfunctie):
    assert brain.handle_pending_choice("ja") is None
    assert nep_zoekfunctie == []


# =============================================================
# "nee", verlopen en geen pending: niets opzoeken
# =============================================================

def test_nee_na_aanbod_zoekt_niets_op(nep_zoekfunctie):
    opzoeken.onthoud_aanbod(VRAAG, ZIN)

    antwoord = brain.handle_pending_choice("nee")

    assert antwoord == "Oké, dan laat ik het."
    assert nep_zoekfunctie == []
    assert confirmation.get_pending() is None


def test_verlopen_aanbod_zoekt_niets_op(nep_zoekfunctie):
    confirmation.set_pending(
        opzoeken.KIND, payload={"vraag": VRAAG}, ttl=-1
    )

    assert brain.handle_pending_choice("ja") is None
    assert nep_zoekfunctie == []
    assert confirmation.get_pending() is None
