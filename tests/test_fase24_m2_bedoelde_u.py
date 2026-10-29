"""Fase 24, M2 — "Bedoelde u…?" via ja/nee, een nummer of het dashboard."""

import time
from pathlib import Path

import pytest

import core.ai as ai
import core.audit as audit
import core.brain as brain
from core import commando_correctie as cc
from core.confirmation import (
    CORRECTIE_KIND,
    ID_KEY,
    JA_NEE_KINDS,
    NONCE_KEY,
    beschrijf_pending,
    clear_pending,
    get_pending,
    set_pending,
)
from dashboard.api import DashboardAPI

STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"
NAMEN = frozenset(["spotify", "steam", "lamp", "lampen", "tv", "brave", "grave"])


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
    """Nep-AI en nep-programma's: alleen "open steam/brave/grave" bestaat."""

    log = {"ai": [], "geopend": []}

    def ask_ai(command, **_kw):
        log["ai"].append(command)
        return "AI-antwoord"

    def open_program(command):
        delen = command.split()
        if len(delen) == 2 and delen[0] == "open" and delen[1] in ("steam", "brave", "grave"):
            log["geopend"].append(delen[1])
            return f"Ik open {delen[1]}."
        return None

    monkeypatch.setattr(brain, "ask_ai", ask_ai)
    monkeypatch.setattr(brain, "try_open_program", open_program)
    return log


# ---------------------------------------------------------------------
# Stem
# ---------------------------------------------------------------------

def test_een_kandidaat_ja_voert_uit(keten):
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"
    pending = get_pending()
    assert pending["kind"] == CORRECTIE_KIND
    assert pending["kandidaten"] == ["open steam"]
    assert pending["question"] == "open stem"

    assert brain.process_command("ja") == "Ik open steam."
    assert keten["geopend"] == ["steam"]
    assert get_pending() is None
    assert keten["ai"] == []


def test_nee_vraagt_wat_dan(keten):
    brain.process_command("open stem")
    assert brain.process_command("nee") == "Wat bedoelde u dan?"
    assert keten["geopend"] == []
    assert get_pending() is None


def test_meerdere_kandidaten_genummerd(keten):
    vraag = brain.process_command("open crave")
    assert vraag.startswith("Bedoelde u 1. open ")
    assert ", of 2. open " in vraag
    assert vraag.endswith("Zeg het nummer, of nee.")

    # "ja" is hier niet genoeg: welke?
    assert "Welke bedoelt u?" in brain.process_command("ja")
    assert get_pending() is not None

    tweede = get_pending()["kandidaten"][1].split()[1]
    assert brain.process_command("2") == f"Ik open {tweede}."
    assert keten["geopend"] == [tweede]


@pytest.mark.parametrize("antwoord, index", [("1", 0), ("de eerste", 0), ("tweede", 1), ("nummer 2", 1)])
def test_keuze_met_woorden(keten, antwoord, index):
    brain.process_command("open crave")
    bedoeld = get_pending()["kandidaten"][index].split()[1]
    brain.process_command(antwoord)
    assert keten["geopend"] == [bedoeld]


def test_ongeldig_nummer_vraagt_opnieuw(keten):
    brain.process_command("open crave")
    assert "Welke bedoelt u?" in brain.process_command("5")
    assert get_pending() is not None


def test_geen_van_deze(keten):
    brain.process_command("open crave")
    assert brain.process_command("geen van deze") == "Wat bedoelde u dan?"
    assert keten["geopend"] == []


def test_nieuw_commando_laat_vraag_vervallen(keten):
    brain.process_command("open stem")
    assert brain.process_command("wat is de hoofdstad van frankrijk") == "AI-antwoord"
    assert get_pending() is None
    assert keten["geopend"] == []


def test_gewone_vraag_krijgt_geen_bedoelde_u(keten):
    assert brain.process_command("waarom is de lucht blauw") == "AI-antwoord"
    assert get_pending() is None


def test_verlopen_vraag_doet_niets(keten, monkeypatch):
    brain.process_command("open stem")
    get_pending()["_expires_at"] = time.time() - 1
    assert brain.process_command("ja") != "Ik open steam."
    assert keten["geopend"] == []


def test_geen_rondjes_bij_herhaling(keten):
    # Het verbeterde commando is zelf weer onbekend: geen tweede vraag,
    # maar gewoon de AI.
    set_pending(CORRECTIE_KIND, {"kandidaten": ["open stem"], "question": "opne stem"})
    assert brain.process_command("ja") == "AI-antwoord"
    assert keten["ai"] == ["open stem"]
    assert get_pending() is None


def test_herhaling_is_per_context():
    assert not cc.is_herhaling()
    with cc.herhaling():
        assert cc.is_herhaling()
        assert cc.te_vragen("open stem", namen=NAMEN) == []
        with cc.herhaling():
            assert cc.is_herhaling()
        assert cc.is_herhaling()
    assert not cc.is_herhaling()


def test_slim_huis_route_vraagt_bij_typfout(keten, monkeypatch):
    monkeypatch.setattr(brain, "try_ha_direct", lambda c: None)
    vraag = brain.process_command("zet de lampe in de wonkamer an")
    assert vraag == "Bedoelde u: zet de lampen in de woonkamer aan?"
    assert keten["ai"] == []


def test_slim_huis_route_alleen_opvulwoorden_naar_ai(keten, monkeypatch):
    monkeypatch.setattr(brain, "try_ha_direct", lambda c: None)
    assert brain.process_command("zet die lamp even op rood") == "AI-antwoord"
    assert get_pending() is None


def test_fout_in_correctie_breekt_niets(keten, monkeypatch):
    def kapot(*_a, **_kw):
        raise RuntimeError("stuk")

    monkeypatch.setattr(cc, "zoek_kandidaten", kapot)
    assert brain.process_command("open stem") == "AI-antwoord"


@pytest.mark.parametrize("tekst, aantal, verwacht", [
    ("ja", 1, (cc.KIES, 0)),
    ("ja graag", 1, (cc.KIES, 0)),
    ("ok", 1, (cc.KIES, 0)),
    ("ja", 2, (cc.ONDUIDELIJK, None)),
    ("nee", 2, (cc.NEE, None)),
    ("nee hoor", 1, (cc.NEE, None)),
    ("3", 3, (cc.KIES, 2)),
    ("3", 2, (cc.ONDUIDELIJK, None)),
    ("de derde", 2, (cc.ONDUIDELIJK, None)),
    ("zet de tv aan", 1, (cc.NIEUW, None)),
])
def test_beoordeel_antwoord(tekst, aantal, verwacht):
    assert cc.beoordeel_antwoord(tekst, aantal) == verwacht


def test_maak_vraag():
    een = [cc.Kandidaat("open steam", 90, "programma_openen")]
    twee = een + [cc.Kandidaat("open spotify", 88, "programma_openen")]
    assert cc.maak_vraag(een) == "Bedoelde u: open steam?"
    assert cc.maak_vraag(twee) == "Bedoelde u 1. open steam, of 2. open spotify? Zeg het nummer, of nee."


def test_lage_score_wordt_niet_gevraagd(monkeypatch):
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [
        cc.Kandidaat("open steam", cc.DREMPEL_VRAGEN - 1, "programma_openen", [("stem", "steam")]),
    ])
    assert cc.te_vragen("open stem") == []


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------

def test_soort_is_ja_nee_en_niet_gevaarlijk():
    from core.confirmation import is_dangerous_kind

    assert CORRECTIE_KIND in JA_NEE_KINDS
    assert not is_dangerous_kind(CORRECTIE_KIND)


def test_beschrijf_pending_geeft_keuzes(keten):
    brain.process_command("open crave")
    beschrijving = beschrijf_pending()
    assert beschrijving["soort"] == CORRECTIE_KIND
    assert len(beschrijving["keuzes"]) == 2
    assert beschrijving["actie"].startswith("Bedoelde u 1.")
    assert beschrijving["vraag"] == "open crave"
    assert beschrijving["risico"] == "low"


def test_andere_pending_heeft_lege_keuzes():
    set_pending("power_confirm", {"action": "shutdown"})
    assert beschrijf_pending()["keuzes"] == []


def _api(audit_regels):
    return DashboardAPI(uitvoerder=brain.voer_besluit_uit, audit_fn=lambda **v: audit_regels.append(v))


def test_dashboard_kiest_knop(keten):
    brain.process_command("open crave")
    p = get_pending()
    tweede = p["kandidaten"][1].split()[1]
    regels = []
    status, antwoord = _api(regels).goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja", "keuze": 1})
    assert status == 200
    assert antwoord["resultaat"] == f"Ik open {tweede}."
    assert keten["geopend"] == [tweede]
    assert regels[0]["tool"] == CORRECTIE_KIND
    assert regels[0]["gehoord"] == "open crave"


def test_dashboard_ja_bij_een_kandidaat(keten):
    brain.process_command("open stem")
    p = get_pending()
    status, antwoord = _api([]).goedkeuring({"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert status == 200
    assert keten["geopend"] == ["steam"]


def test_dashboard_geen_van_deze(keten):
    brain.process_command("open crave")
    p = get_pending()
    status, antwoord = _api([]).goedkeuring({"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "nee"})
    assert status == 200
    assert antwoord["resultaat"] == "Wat bedoelde u dan?"
    assert keten["geopend"] == []


@pytest.mark.parametrize("keuze", [-1, 10, "1", 1.0, True, None])
def test_dashboard_ongeldige_keuze(keten, keuze):
    brain.process_command("open crave")
    p = get_pending()
    status, _ = _api([]).goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja", "keuze": keuze})
    assert status == 400
    assert get_pending() is p  # niets overgenomen
    assert keten["geopend"] == []


def test_dashboard_keuze_buiten_lijst(keten):
    brain.process_command("open stem")
    p = get_pending()
    status, antwoord = _api([]).goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja", "keuze": 3})
    assert status == 200
    assert "weet niet meer" in antwoord["resultaat"]
    assert keten["geopend"] == []


def test_dashboard_tekent_knoppen_per_keuze():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="gkKeuzes"' in html
    assert "function tekenKeuzes" in js
    assert "body.keuze = keuze" in js
    assert "Geen van deze" in js
