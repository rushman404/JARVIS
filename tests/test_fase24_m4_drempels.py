"""Fase 24, M4 — drempels en veiligheid bij commando-correctie.

Bijna zeker + onschuldig → meteen doen ("Ik nam aan dat u … bedoelde");
twijfel → "Bedoelde u…?"; gevaarlijk → altijd één samengevoegde, strikte vraag.
"""

import time

import pytest

import core.ai as ai
import core.audit as audit
import core.brain as brain
from core import commando_correctie as cc
from core.confirmation import CORRECTIE_KIND, clear_pending, get_pending

NAMEN = frozenset(["spotify", "steam", "lamp", "lampen", "tv", "brave", "grave", "discord"])


def _k(commando, score=95, wijzigingen=(("x", "y"),)):
    return cc.Kandidaat(commando, score, "test", list(wijzigingen))


@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONVERSATION_FILE", str(tmp_path / "conversation.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(cc, "_namen", NAMEN)
    monkeypatch.setattr(cc, "_namen_tijd", time.monotonic())
    clear_pending()
    yield
    clear_pending()


@pytest.fixture
def keten(monkeypatch):
    log = {"ai": [], "geopend": [], "power": [], "gesloten": []}

    def ask_ai(command, **_kw):
        log["ai"].append(command)
        return "AI-antwoord"

    def open_program(command):
        delen = command.split()
        if len(delen) == 2 and delen[0] == "open" and delen[1] in ("spotify", "steam"):
            log["geopend"].append(delen[1])
            return f"Ik open {delen[1]}."
        return None

    def close_program_tool(name):
        log["gesloten"].append(name)
        return f"Ik sluit {name}."

    monkeypatch.setattr(brain, "ask_ai", ask_ai)
    monkeypatch.setattr(brain, "try_open_program", open_program)
    monkeypatch.setattr(brain, "close_program_tool", close_program_tool)
    for actie in list(brain.POWER_ACTIONS):
        monkeypatch.setitem(brain.POWER_ACTIONS, actie, lambda *a, _a=actie, **k: log["power"].append(_a) or f"{_a} gedaan")
    return log


# ---------------------------------------------------------------------
# Risico en beslissing (zonder brein)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("commando, verwacht", [
    ("open spotify", cc.VEILIG),
    ("zet de lampen aan", cc.VEILIG),
    ("pauzeer de muziek", cc.VEILIG),
    ("zet de muziek harder", cc.VEILIG),
    ("sluit discord", cc.GEVOELIG),
    ("vergeet mijn favoriete game", cc.GEVOELIG),
    ("sluit de pc af", cc.GEVAARLIJK),
    ("zet de computer uit", cc.GEVAARLIJK),
    ("herstart de pc", cc.GEVAARLIJK),
    ("vergrendel de pc", cc.GEVAARLIJK),
    ("zet de pc in slaapstand", cc.GEVAARLIJK),
    ("verwijder rapport.docx", cc.GEVAARLIJK),
    ("leeg de prullenbak", cc.GEVAARLIJK),
    ("beantwoord de mail van school met ok", cc.GEVAARLIJK),
    ("antwoord sem ik kom zo", cc.GEVAARLIJK),
    ("verplaats de tandarts naar vrijdag", cc.GEVAARLIJK),
    ("zet tandarts in mijn agenda", cc.GEVAARLIJK),
])
def test_risico(commando, verwacht):
    assert cc.risico(commando) == verwacht


def test_bijna_zeker_en_onschuldig_is_direct():
    assert cc.beslis([_k("open spotify", score=92)]) == cc.DIRECT


def test_alleen_opvulwoorden_is_direct():
    assert cc.beslis([_k("doe tv uit", score=100, wijzigingen=())]) == cc.DIRECT


@pytest.mark.parametrize("kandidaten", [
    [_k("open spotify", score=cc.DREMPEL_DIRECT - 1)],                       # twijfel
    [_k("open brave"), _k("open grave")],                                     # meerdere
    [_k("zet de lampen aan", wijzigingen=(("a", "b"), ("c", "d")))],          # te veel gegok
    [_k("sluit discord", score=100)],                                         # gevoelig
])
def test_vragen(kandidaten):
    assert cc.beslis(kandidaten) == cc.VRAGEN


@pytest.mark.parametrize("score", [70, 100])
def test_gevaarlijk_altijd_gevaarlijk(score):
    assert cc.beslis([_k("sluit de pc af", score=score)]) == cc.GEVAARLIJK


def test_gevaarlijk_tussen_meerdere_wordt_gewoon_vragen():
    assert cc.beslis([_k("herstart de pc"), _k("herstart steam")]) == cc.VRAGEN


def test_aanname():
    assert cc.aanname(_k("open spotify")) == "Ik nam aan dat u 'open spotify' bedoelde. "
    assert cc.aanname(_k("doe tv uit", wijzigingen=())) == ""


# ---------------------------------------------------------------------
# In het brein
# ---------------------------------------------------------------------

def test_direct_uitvoeren_met_aanname(keten):
    antwoord = brain.process_command("open spotfy")
    assert antwoord == "Ik nam aan dat u 'open spotify' bedoelde. Ik open spotify."
    assert keten["geopend"] == ["spotify"]
    assert get_pending() is None
    assert keten["ai"] == []


def test_twijfel_vraagt(keten):
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"
    assert keten["geopend"] == []


def test_meerdere_woorden_verbeterd_vraagt(keten, monkeypatch):
    monkeypatch.setattr(brain, "try_ha_direct", lambda c: None)
    assert brain.process_command("zet de lampe in de wonkamer an").startswith("Bedoelde u:")


def test_gevaarlijk_een_samengevoegde_vraag(keten):
    vraag = brain.process_command("herstrat de pc")
    assert vraag.startswith("Bedoelde u: herstart de pc? Zal ik de pc herstarten?")
    pending = get_pending()
    assert pending["kind"] == "power_confirm"  # strikte ja, met alle details
    assert keten["power"] == []

    # Eén ja is genoeg: geen tweede vraag.
    assert brain.process_command("ja") == "restart gedaan"
    assert keten["power"] == ["restart"]
    assert get_pending() is None


def test_gevaarlijk_nee_doet_niets(keten):
    brain.process_command("vergrendl de pc")
    assert get_pending()["kind"] == "power_confirm"
    brain.process_command("nee")
    assert keten["power"] == []
    assert get_pending() is None


@pytest.mark.parametrize("los", ["ok", "prima", "ja maar niet nu"])
def test_gevaarlijk_geen_losse_ja(keten, los):
    brain.process_command("herstrat de pc")
    brain.process_command(los)
    assert keten["power"] == []


def test_gevaarlijk_zonder_bevestiging_van_route(keten, monkeypatch):
    # Blijkt de route niets te vragen (bijv. niets gevonden), dan gewoon
    # het antwoord met de aanname, en geen hangende vraag.
    monkeypatch.setattr(brain, "try_ha_direct", lambda c: None)
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [
        cc.Kandidaat("verwijder bestaatniet.txt", 95, "test", [("verwijdr", "verwijder")])])
    monkeypatch.setattr(brain, "try_file_command", lambda c: "Ik kan bestaatniet.txt niet vinden.")
    antwoord = brain.try_commando_correctie("verwijdr bestaatniet.txt")
    assert antwoord == "Ik nam aan dat u 'verwijder bestaatniet.txt' bedoelde. Ik kan bestaatniet.txt niet vinden."
    assert get_pending() is None


def test_gevoelig_vraagt_eerst(keten, monkeypatch):
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [
        cc.Kandidaat("sluit discord", 98, "programma_sluiten", [("discrod", "discord")])])
    assert brain.try_commando_correctie("sluit discrod") == "Bedoelde u: sluit discord?"
    assert keten["gesloten"] == []
    assert get_pending()["kind"] == CORRECTIE_KIND


def test_direct_herhaalt_niet_opnieuw(keten, monkeypatch):
    # Het verbeterde commando is zelf onbekend: geen tweede correctie,
    # gewoon de AI.
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda tekst, **_kw: [
        cc.Kandidaat("open spotfy", 95, "programma_openen", [("x", "y")])])
    antwoord = brain.try_commando_correctie("opn spotfy")
    assert antwoord.endswith("AI-antwoord")
    assert keten["ai"] == ["open spotfy"]
