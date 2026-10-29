"""Fase 24, M5 — leren van een "ja" en het logboek met missers."""

import json
import time

import pytest

import core.ai as ai
import core.audit as audit
import core.brain as brain
from core import commando_correctie as cc
from core.confirmation import CORRECTIE_KIND, ID_KEY, NONCE_KEY, clear_pending, get_pending, set_pending
from dashboard.api import DashboardAPI

NAMEN = frozenset(["spotify", "steam", "lamp", "lampen", "tv", "brave", "grave"])


@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONVERSATION_FILE", str(tmp_path / "conversation.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(cc, "_namen", NAMEN)
    monkeypatch.setattr(cc, "_namen_tijd", time.monotonic())
    # Geen AI-vangnet: alleen de lokale match.
    monkeypatch.setattr(cc, "_standaard_llm", lambda berichten: "")
    clear_pending()
    yield
    clear_pending()


@pytest.fixture
def keten(monkeypatch):
    log = {"ai": [], "geopend": []}

    def ask_ai(command, **_kw):
        log["ai"].append(command)
        return "AI-antwoord"

    def open_program(command):
        delen = command.split()
        if len(delen) == 2 and delen[0] == "open" and delen[1] in ("steam", "brave", "grave", "spotify"):
            log["geopend"].append(delen[1])
            return f"Ik open {delen[1]}."
        return None

    monkeypatch.setattr(brain, "ask_ai", ask_ai)
    monkeypatch.setattr(brain, "try_open_program", open_program)
    return log


def _bestand():
    with open(cc.LEER_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------
# Leren
# ---------------------------------------------------------------------

def test_na_ja_werkt_het_de_volgende_keer_direct(keten):
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"
    brain.process_command("ja")
    assert keten["geopend"] == ["steam"]

    antwoord = brain.process_command("open stem")
    assert antwoord == "Ik nam aan dat u 'open steam' bedoelde. Ik open steam."
    assert keten["geopend"] == ["steam", "steam"]
    assert get_pending() is None


def test_geleerd_ook_met_opvulwoorden_en_beleefd(keten):
    brain.process_command("open stem")
    brain.process_command("ja")
    antwoord = brain.process_command("kun je ff open stem")
    assert antwoord.startswith("Ik nam aan dat u 'open steam' bedoelde.")


def test_keuze_uit_lijst_wordt_geleerd(keten):
    brain.process_command("open crave")
    gekozen = get_pending()["kandidaten"][1]
    brain.process_command("2")
    assert cc.geleerd_commando("open crave").commando == gekozen
    assert brain.process_command("open crave").startswith(f"Ik nam aan dat u '{gekozen}' bedoelde.")


def test_dashboard_keuze_wordt_geleerd(keten):
    brain.process_command("open crave")
    p = get_pending()
    gekozen = p["kandidaten"][0]
    status, _ = DashboardAPI(uitvoerder=brain.voer_besluit_uit, audit_fn=lambda **v: None).goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja", "keuze": 0})
    assert status == 200
    assert cc.geleerd_commando("open crave").commando == gekozen


def test_nee_leert_niets(keten):
    brain.process_command("open stem")
    brain.process_command("nee")
    assert cc.geleerd_commando("open stem") is None
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"


def test_geleerd_gevaarlijk_vraagt_nog_steeds(keten, monkeypatch):
    for actie in list(brain.POWER_ACTIONS):
        monkeypatch.setitem(brain.POWER_ACTIONS, actie, lambda *a, **k: "gedaan")
    cc.leer("herstrat de pc", "herstart de pc")
    vraag = brain.process_command("herstrat de pc")
    assert vraag.startswith("Bedoelde u: herstart de pc? Zal ik de pc herstarten?")
    assert get_pending()["kind"] == "power_confirm"


def test_geleerd_gevoelig_vraagt_nog_steeds(keten):
    cc.leer("sluit discrod", "sluit discord")
    assert brain.try_commando_correctie("sluit discrod") == "Bedoelde u: sluit discord?"


def test_leer_negeert_onzin():
    cc.leer("", "open steam")
    cc.leer("open steam", "open steam")
    cc.leer("open stem", "")
    assert cc.geleerd_commando("open stem") is None


def test_leer_telt_en_overschrijft():
    cc.leer("open stem", "open steam")
    cc.leer("open stem", "open steam")
    assert _bestand()["geleerd"]["open stem"]["keer"] == 2
    cc.leer("open stem", "open spotify")
    assert _bestand()["geleerd"]["open stem"] == {
        "commando": "open spotify", "keer": 1, "laatst": _bestand()["geleerd"]["open stem"]["laatst"]}


def test_kapot_bestand_breekt_niets(keten):
    with open(cc.LEER_FILE, "w", encoding="utf-8") as f:
        f.write("{ geen json")
    assert cc.geleerd_commando("open stem") is None
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"


def test_fout_bij_schrijven_breekt_niets(keten, monkeypatch):
    def kapot(_data):
        raise OSError("schijf vol")

    monkeypatch.setattr(cc, "_schrijf", kapot)
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"
    assert brain.process_command("ja") == "Ik open steam."


def test_vergeet_geleerd(keten):
    cc.leer("open stem", "open steam")
    cc.leer("open crave", "open brave")
    assert brain.process_command("vergeet de geleerde commando's") == "Gedaan, sir. Ik ben 2 geleerde commando's vergeten."
    assert cc.geleerd_commando("open stem") is None
    assert brain.process_command("wis alle geleerde commando's") == "Ik had nog geen commando's geleerd, sir."


# ---------------------------------------------------------------------
# Logboek
# ---------------------------------------------------------------------

def test_logboek_vraag_ja_en_direct(keten):
    brain.process_command("open stem")
    brain.process_command("ja")
    brain.process_command("open stem")
    regel = _bestand()["missers"]["open stem"]
    assert regel["keer"] == 2
    assert regel["uitkomsten"] == {"gevraagd": 1, "ja": 1, "geleerd": 1}
    assert regel["bedoeld"] == "open steam"


def test_logboek_direct_en_nee(keten):
    brain.process_command("open spotfy")
    brain.process_command("open stem")
    brain.process_command("nee")
    missers = _bestand()["missers"]
    assert missers["open spotfy"]["uitkomsten"] == {"direct": 1}
    assert missers["open stem"]["uitkomsten"] == {"gevraagd": 1, "nee": 1}


def test_logboek_onbekend_commando(keten):
    assert brain.process_command("zet de wekker om 7 uur") == "AI-antwoord"
    assert _bestand()["missers"]["zet de wekker om 7 uur"]["uitkomsten"] == {"onbekend": 1}


def test_gewone_vraag_komt_niet_in_logboek(keten):
    brain.process_command("waarom is de lucht blauw")
    assert cc.vaak_fout() == []


def test_herhaling_komt_niet_in_logboek(keten):
    set_pending(CORRECTIE_KIND, {"kandidaten": ["zet de wekker om 7 uur"], "question": "zet de wekkr om 7 uur"})
    brain.process_command("ja")
    assert "zet de wekker om 7 uur" not in _bestand()["missers"]


def test_logboek_blijft_klein(monkeypatch):
    monkeypatch.setattr(cc, "MAX_MISSERS", 3)
    for i in range(5):
        monkeypatch.setattr(cc, "_nu", lambda i=i: f"2026-10-29T10:00:0{i}")
        cc.noteer(f"open ding{i}", cc.UIT_ONBEKEND)
    assert sorted(_bestand()["missers"]) == ["open ding2", "open ding3", "open ding4"]


def test_vaak_fout_volgorde():
    for _ in range(3):
        cc.noteer("open stem", cc.UIT_GEVRAAGD, "open steam")
    cc.noteer("zet de wekker", cc.UIT_ONBEKEND)
    assert [zin for zin, _r in cc.vaak_fout()] == ["open stem", "zet de wekker"]


@pytest.mark.parametrize("vraag", [
    "welke commando's gaan vaak fout?",
    "welke commandos gaan het vaakst fout",
    "welke commando's gaan er mis",
    "welke commando's begrijp je vaak niet",
])
def test_spraak_vaak_fout(keten, vraag):
    for _ in range(2):
        cc.noteer("open stem", cc.UIT_GEVRAAGD, "open steam")
    cc.noteer("zet de wekker", cc.UIT_ONBEKEND)
    assert brain.process_command(vraag) == (
        "Deze commando's gaan het vaakst fout: 'open stem' (2 keer, bedoeld: open steam); "
        "'zet de wekker' (1 keer)."
    )


def test_spraak_vaak_fout_leeg(keten):
    assert brain.process_command("welke commando's gaan vaak fout") == "Er gaan nog geen commando's fout, sir."


def test_bestand_staat_buiten_git():
    from pathlib import Path

    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "memory/commando_correcties.json" in gitignore.splitlines()
