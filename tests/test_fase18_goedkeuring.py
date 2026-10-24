"""Tests voor Fase 18 M1: goedkeuring met id + nonce (core/confirmation.py).

Dekt (zie docs/fase18_dashboard_design.md §10.6 en §12.1 "Goedkeuring"):
  - elke pending krijgt een unieke id en een geheime nonce
  - claim_voor_besluit werkt alleen met de id + nonce van de actie die nu
    openstaat; verkeerde nonce 403, verlopen 410, al afgehandeld 409
  - een tweede goedkeuring van dezelfde actie doet niets
  - stem en dashboard kunnen dezelfde actie nooit allebei uitvoeren
  - de auditregel noemt de herkomst ("stem" of "dashboard")
  - DashboardAPI.goedkeuring accepteert alleen exact "ja" of "nee"

Windows-acties worden gemockt via een nep-_dispatch_tool.
"""

import json
import threading
import time

import pytest

import core.ai as ai
import core.audit as audit
import core.brain as brain
from core import confirmation
from core.confirmation import (
    CLAIM_AFGEHANDELD,
    CLAIM_GEEN,
    CLAIM_NONCE,
    CLAIM_OK,
    CLAIM_SOORT,
    CLAIM_VERLOPEN,
    ID_KEY,
    NONCE_KEY,
    beschrijf_pending,
    claim_pending,
    claim_voor_besluit,
    clear_pending,
    get_pending,
    set_pending,
)
from dashboard.api import DashboardAPI


@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONVERSATION_FILE", str(tmp_path / "conversation.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    clear_pending()
    yield
    clear_pending()


@pytest.fixture
def nep_dispatch(monkeypatch):
    aangeroepen = []

    def fake(tool_name, arguments, question):
        aangeroepen.append((tool_name, dict(arguments)))
        return "uitgevoerd"

    monkeypatch.setattr(ai, "_dispatch_tool", fake)
    return aangeroepen


def _auditregels():
    try:
        with open(audit.AUDIT_FILE, encoding="utf-8") as f:
            return [json.loads(r) for r in f if r.strip()]
    except FileNotFoundError:
        return []


def _vraag_goedkeuring():
    """Zet een echte tool-goedkeuring klaar (high-risico tool)."""

    ai.execute_tool("ui_launch_app", {"path": "C:/test/app.exe"}, "start app")
    pending = get_pending()
    assert pending["kind"] == "tool_approval"
    return pending


# ----- id en nonce -----

def test_pending_krijgt_unieke_id_en_nonce():
    a = set_pending("power_confirm", {"action": "shutdown"})
    b = set_pending("power_confirm", {"action": "shutdown"})
    assert a[ID_KEY] and b[ID_KEY] and a[ID_KEY] != b[ID_KEY]
    assert len(a[NONCE_KEY]) >= 16
    assert a[NONCE_KEY] != b[NONCE_KEY]


def test_id_en_nonce_uit_payload_worden_niet_overgenomen():
    data = set_pending("power_confirm", {"_id": "p1", "_nonce": "geraden"})
    assert data[NONCE_KEY] != "geraden"


def test_pending_zonder_id_krijgt_er_alsnog_een():
    """Pendings die direct via update_context gezet worden (oude code)."""

    ai.current_context["pending_choice"] = {"kind": "delete_confirm", "matches": ["x"]}
    pending = get_pending()
    assert pending[ID_KEY] and pending[NONCE_KEY]


# ----- claim_voor_besluit -----

def test_claim_met_juiste_id_en_nonce():
    p = set_pending("power_confirm", {"action": "shutdown"})
    uitkomst, pending = claim_voor_besluit(p[ID_KEY], p[NONCE_KEY], "dashboard")
    assert uitkomst == CLAIM_OK
    assert pending is p
    assert pending["herkomst"] == "dashboard"
    assert get_pending() is None


def test_claim_met_verkeerde_nonce_verandert_niets():
    p = set_pending("power_confirm", {"action": "shutdown"})
    uitkomst, pending = claim_voor_besluit(p[ID_KEY], "fout", "dashboard")
    assert uitkomst == CLAIM_NONCE
    assert pending is None
    assert get_pending() is p


def test_claim_van_onbekende_id():
    p = set_pending("power_confirm", {"action": "shutdown"})
    assert claim_voor_besluit("p999999", p[NONCE_KEY], "dashboard")[0] == CLAIM_GEEN
    assert get_pending() is p


def test_claim_van_een_oude_actie_na_een_nieuwe_vraag():
    oud = set_pending("power_confirm", {"action": "shutdown"})
    nieuw = set_pending("power_confirm", {"action": "restart"})
    uitkomst, _ = claim_voor_besluit(oud[ID_KEY], oud[NONCE_KEY], "dashboard")
    assert uitkomst == CLAIM_AFGEHANDELD
    assert get_pending() is nieuw


def test_claim_na_verlopen_ttl():
    p = set_pending("power_confirm", {"action": "shutdown"}, ttl=0.05)
    time.sleep(0.1)
    uitkomst, _ = claim_voor_besluit(p[ID_KEY], p[NONCE_KEY], "dashboard")
    assert uitkomst == CLAIM_VERLOPEN


def test_tweede_claim_doet_niets():
    p = set_pending("power_confirm", {"action": "shutdown"})
    assert claim_voor_besluit(p[ID_KEY], p[NONCE_KEY], "dashboard")[0] == CLAIM_OK
    assert claim_voor_besluit(p[ID_KEY], p[NONCE_KEY], "dashboard")[0] == CLAIM_AFGEHANDELD


def test_claim_van_een_lijstkeuze_kan_niet():
    p = set_pending("open_choice", {"matches": ["a", "b"]})
    assert claim_voor_besluit(p[ID_KEY], p[NONCE_KEY], "dashboard")[0] == CLAIM_SOORT
    assert get_pending() is p


@pytest.mark.parametrize("pid, nonce", [(None, "x"), ("p1", None), (1, "x"), ("p1", 5)])
def test_claim_met_ongeldige_typen(pid, nonce):
    set_pending("power_confirm", {"action": "shutdown"})
    assert claim_voor_besluit(pid, nonce, "dashboard")[0] == CLAIM_GEEN


def test_claim_pending_alleen_voor_de_huidige():
    oud = set_pending("power_confirm", {"action": "shutdown"})
    set_pending("power_confirm", {"action": "restart"})
    assert claim_pending(oud) is False
    assert get_pending() is not None


def test_gelijktijdige_claims_slechts_een_wint():
    p = set_pending("power_confirm", {"action": "shutdown"})
    winnaars = []
    start = threading.Barrier(8)

    def poging():
        start.wait()
        if claim_voor_besluit(p[ID_KEY], p[NONCE_KEY], "dashboard")[0] == CLAIM_OK:
            winnaars.append(1)

    threads = [threading.Thread(target=poging) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winnaars) == 1


# ----- beschrijf_pending -----

def test_beschrijving_bevat_de_volledige_actie(nep_dispatch):
    _vraag_goedkeuring()
    view = beschrijf_pending()
    assert view["soort"] == "tool_approval"
    assert view["tool"] == "ui_launch_app"
    assert view["argumenten"] == {"path": "C:/test/app.exe"}
    assert view["risico"] == "high"
    assert view["vraag"] == "start app"
    assert view["actie"]
    assert view["id"] and view["nonce"]
    assert 0 < view["resterende_seconden"] <= confirmation.CONFIRM_TTL_SECONDS


def test_beschrijving_van_power_confirm():
    set_pending("power_confirm", {"action": "shutdown", "target": "game-pc", "question": "sluit de game-pc af"})
    view = beschrijf_pending()
    assert view["actie"] == "shutdown"
    assert view["argumenten"] == {"action": "shutdown", "target": "game-pc"}
    assert view["risico"] == "high"


def test_geen_beschrijving_zonder_ja_nee_vraag():
    assert beschrijf_pending() is None
    set_pending("open_choice", {"matches": ["a"]})
    assert beschrijf_pending() is None


# ----- stem-pad (handle_pending_choice) -----

def test_stem_goedkeuring_noemt_herkomst_stem(nep_dispatch):
    _vraag_goedkeuring()
    assert brain.handle_pending_choice("ja") == "uitgevoerd"
    assert nep_dispatch == [("ui_launch_app", {"path": "C:/test/app.exe"})]
    regel = _auditregels()[-1]
    assert regel["goedgekeurd"] is True
    assert regel["herkomst"] == "stem"


def test_stem_afwijzing_noemt_herkomst_stem(nep_dispatch):
    _vraag_goedkeuring()
    brain.handle_pending_choice("nee")
    assert nep_dispatch == []
    regel = _auditregels()[-1]
    assert regel["goedgekeurd"] is False
    assert regel["herkomst"] == "stem"


def test_stem_na_dashboard_doet_niets(nep_dispatch):
    p = _vraag_goedkeuring()
    api = DashboardAPI()
    status, _ = api.goedkeuring({"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert status == 200
    # Daarna nog "ja" via de stem: er staat niets meer open.
    assert brain.handle_pending_choice("ja") is None
    assert len(nep_dispatch) == 1


# ----- dashboard-pad (DashboardAPI.goedkeuring) -----

def test_dashboard_ja_voert_uit_met_herkomst_dashboard(nep_dispatch):
    p = _vraag_goedkeuring()
    api = DashboardAPI()
    status, antwoord = api.goedkeuring({"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert status == 200
    assert antwoord["uitgevoerd"] is True
    assert antwoord["resultaat"] == "uitgevoerd"
    assert nep_dispatch == [("ui_launch_app", {"path": "C:/test/app.exe"})]
    regels = _auditregels()
    assert len(regels) == 1
    assert regels[0]["herkomst"] == "dashboard"
    assert regels[0]["goedgekeurd"] is True


def test_dashboard_nee_annuleert(nep_dispatch):
    p = _vraag_goedkeuring()
    status, antwoord = DashboardAPI().goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "nee"}
    )
    assert status == 200
    assert antwoord["uitgevoerd"] is False
    assert nep_dispatch == []
    regel = _auditregels()[-1]
    assert regel["goedgekeurd"] is False
    assert regel["herkomst"] == "dashboard"
    assert get_pending() is None


@pytest.mark.parametrize("besluit", ["misschien", "ja, misschien", "Ja", "ok", "ja doe maar", "", None, True])
def test_dashboard_accepteert_alleen_exact_ja_of_nee(nep_dispatch, besluit):
    p = _vraag_goedkeuring()
    status, antwoord = DashboardAPI().goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": besluit}
    )
    assert status == 400
    assert antwoord["ok"] is False
    assert nep_dispatch == []
    assert get_pending() is p


def test_dashboard_verkeerde_nonce_403(nep_dispatch):
    p = _vraag_goedkeuring()
    status, antwoord = DashboardAPI().goedkeuring({"id": p[ID_KEY], "nonce": "oud", "besluit": "ja"})
    assert status == 403
    assert antwoord["fout"]["code"] == "ongeldige_nonce"
    assert nep_dispatch == []
    assert get_pending() is p


def test_dashboard_onbekende_actie_409(nep_dispatch):
    _vraag_goedkeuring()
    status, _ = DashboardAPI().goedkeuring({"id": "p0", "nonce": "x", "besluit": "ja"})
    assert status == 409
    assert nep_dispatch == []


def test_dashboard_tweede_goedkeuring_409(nep_dispatch):
    p = _vraag_goedkeuring()
    api = DashboardAPI()
    body = {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"}
    assert api.goedkeuring(body)[0] == 200
    status, antwoord = api.goedkeuring(body)
    assert status == 409
    assert antwoord["fout"]["code"] == "al_afgehandeld"
    assert len(nep_dispatch) == 1


def test_dashboard_na_verlopen_ttl_410(nep_dispatch):
    p = set_pending("tool_approval", {
        "tool_name": "ui_launch_app", "arguments": {}, "question": "",
        "source": "test", "risk": "high", "remaining_steps": [],
    }, ttl=0.05)
    time.sleep(0.1)
    status, _ = DashboardAPI().goedkeuring({"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert status == 410
    assert nep_dispatch == []


def test_dashboard_power_confirm_schrijft_auditregel():
    uitgevoerd = []
    audit_regels = []
    p = set_pending("power_confirm", {"action": "shutdown", "question": "sluit de pc af"})
    api = DashboardAPI(
        uitvoerder=lambda pending, ok: uitgevoerd.append((pending["action"], ok)) or "Afsluiten...",
        audit_fn=lambda **v: audit_regels.append(v),
    )
    status, _ = api.goedkeuring({"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert status == 200
    assert uitgevoerd == [("shutdown", True)]
    assert audit_regels[0]["handler"] == "dashboard"
    assert audit_regels[0]["herkomst"] == "dashboard"
    assert audit_regels[0]["tool"] == "power_confirm"
    assert audit_regels[0]["risico"] == "high"
    assert audit_regels[0]["goedgekeurd"] is True


def test_dashboard_fout_bij_uitvoeren_geeft_500_zonder_details():
    def kapot(pending, ok):
        raise RuntimeError("geheim pad C:/x")

    p = set_pending("power_confirm", {"action": "shutdown"})
    status, antwoord = DashboardAPI(uitvoerder=kapot, audit_fn=lambda **v: None).goedkeuring(
        {"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"}
    )
    assert status == 500
    assert "geheim" not in json.dumps(antwoord)
    assert get_pending() is None


def test_dashboard_pending_endpoint(nep_dispatch):
    api = DashboardAPI()
    assert api.pending() == (200, None)
    p = _vraag_goedkeuring()
    status, view = api.pending()
    assert status == 200
    assert view["id"] == p[ID_KEY]
    assert view["nonce"] == p[NONCE_KEY]
