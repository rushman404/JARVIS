"""Tests voor Fase 18 M1: DashboardAPI zonder HTTP (dashboard/api.py).

Dekt:
  - status samenstellen (fase voor de orb, nachtmodus, stille modus)
  - meldingen: id + aangemaakt_op, observer-hook zonder de wachtrij te legen,
    hub met gelezen/legen
  - timers zetten, tonen en annuleren op id (met invoercontrole)
  - widget-config lezen en schrijven (tmp-bestand), ongeldige config weigeren
  - tekst met HTML komt ongewijzigd terug (de PWA rendert alleen textContent)

Alle tijd komt van een vaste klok; er wordt niet geslapen.
"""

import json

import pytest

import status as status_mod
from core import proactive
from core.proactive import Melding, ProactiveEngine
from core.timers import TimerStore
from dashboard import api as api_mod
from dashboard.api import DashboardAPI, MeldingenHub

EPOCH = 1_000_000.0


class Klok:
    def __init__(self, nu=EPOCH):
        self.nu = nu

    def __call__(self):
        return self.nu


@pytest.fixture
def klok():
    return Klok()


@pytest.fixture
def store(tmp_path, klok):
    return TimerStore(pad=str(tmp_path / "timers.json"), clock=klok)


@pytest.fixture
def audit_regels():
    return []


@pytest.fixture
def api(tmp_path, store, klok, audit_regels):
    return DashboardAPI(
        timer_store=store,
        widgets_pad=str(tmp_path / "dashboard.json"),
        clock=klok,
        spreekt_fn=lambda: False,
        fase_fn=lambda: "rust",
        pc_target_fn=lambda: "local",
        audit_fn=lambda **v: audit_regels.append(v),
    )


@pytest.fixture(autouse=True)
def schone_modi():
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    yield
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    status_mod.reset()


# ----- health & status -----

def test_health(api):
    assert api.health() == (200, {"ok": True, "versie": api_mod.API_VERSIE})


def test_status_velden(api):
    code, s = api.status()
    assert code == 200
    for veld in ("tijd", "actief", "fase", "luistert", "denkt", "spreekt", "in_gesprek",
                 "nachtmodus", "nachtmodus_stand", "auto_slaap", "quiet", "pc_target"):
        assert veld in s
    assert s["fase"] == "rust"
    assert s["pc_target"] == "local"


def test_status_spreekt_wint_van_fase(api):
    api.spreekt_fn = lambda: True
    api.fase_fn = lambda: "denkt"
    _, s = api.status()
    assert s["fase"] == "spreekt" and s["spreekt"] and not s["denkt"]


def test_status_onbekende_fase_wordt_rust(api):
    api.fase_fn = lambda: "iets anders"
    assert api.status()[1]["fase"] == "rust"


def test_status_volgt_stille_modus_en_gesprek(api):
    proactive.set_quiet(True)
    proactive.set_in_gesprek(True)
    _, s = api.status()
    assert s["quiet"] is True and s["in_gesprek"] is True


def test_status_nachtmodus_handmatig_aan(api):
    proactive.set_nachtmodus("aan", nu=EPOCH)
    _, s = api.status()
    assert s["nachtmodus"] is True
    assert s["nachtmodus_stand"] == "aan"


def test_statusmodule_fases():
    status_mod.reset()
    assert status_mod.fase() == "rust"
    status_mod.luistert()
    assert status_mod.fase() == "luistert"
    status_mod.omzetten()
    assert status_mod.fase() == "denkt"
    status_mod.spreekt("hallo")
    assert status_mod.fase() == "spreekt"
    status_mod.beurt_begint("vraag")
    assert status_mod.fase() == "denkt"
    status_mod.wacht()
    assert status_mod.fase() == "rust"


# ----- meldingen -----

def test_melding_heeft_id_en_aanmaaktijd():
    a = Melding("een", nu=EPOCH)
    b = Melding("twee", nu=EPOCH + 5)
    assert a.id != b.id
    assert a.aangemaakt_op == EPOCH
    assert b.aangemaakt_op == EPOCH + 5
    assert a.verloopt_op == EPOCH + proactive.DEFAULT_MELDING_TTL


def _engine(tmp_path, klok):
    return ProactiveEngine(
        rules_pad=str(tmp_path / "geen_regels.json"),
        time_fn=klok,
        in_gesprek_fn=lambda: False,
    )


def test_observer_ziet_melding_zonder_wachtrij_te_legen(tmp_path, klok, api):
    engine = _engine(tmp_path, klok)
    api.koppel_engine(engine)
    engine._verstuur("Tijd voor pauze", bron="pauze", nu_ts=EPOCH)

    _, hub = api.notificaties()
    assert hub["aantal"] == 1 and hub["ongelezen"] == 1
    m = hub["meldingen"][0]
    assert m["tekst"] == "Tijd voor pauze"
    assert m["bron"] == "pauze"
    assert m["aangemaakt_op"] == EPOCH
    assert m["gelezen"] is False

    # De wachtrij van de engine is niet geleegd.
    assert [x.tekst for x in engine.neem_meldingen()] == ["Tijd voor pauze"]


def test_dubbele_melding_komt_niet_twee_keer_in_de_hub(tmp_path, klok, api):
    engine = _engine(tmp_path, klok)
    api.koppel_engine(engine)
    engine._verstuur("zelfde", nu_ts=EPOCH)
    engine._verstuur("zelfde", nu_ts=EPOCH)
    assert api.notificaties()[1]["aantal"] == 1


def test_kapotte_observer_stopt_de_engine_niet(tmp_path, klok):
    engine = _engine(tmp_path, klok)

    def kapot(melding):
        raise RuntimeError("stuk")

    engine.set_melding_observer(kapot)
    engine._verstuur("gaat door", nu_ts=EPOCH)
    assert engine.wachtrij.lengte() == 1


def test_ontkoppel_zet_observer_uit(tmp_path, klok, api):
    engine = _engine(tmp_path, klok)
    api.koppel_engine(engine)
    api.ontkoppel()
    engine._verstuur("niet zien", nu_ts=EPOCH)
    assert api.notificaties()[1]["aantal"] == 0


def test_hub_lezen_en_legen(api):
    for tekst in ("a", "b", "c"):
        api.hub.voeg_toe(Melding(tekst, nu=EPOCH))
    meldingen = api.notificaties()[1]["meldingen"]
    assert [m["tekst"] for m in meldingen] == ["c", "b", "a"]

    eerste_id = meldingen[-1]["id"]
    assert api.notificaties_lees({"ids": [eerste_id]}) == (200, {"ok": True, "gelezen": 1})
    assert api.notificaties()[1]["ongelezen"] == 2

    assert api.notificaties_lees({})[1]["gelezen"] == 2
    assert api.notificaties()[1]["ongelezen"] == 0

    assert api.notificaties_legen() == (200, {"ok": True, "gewist": 3})
    assert api.notificaties()[1]["aantal"] == 0


@pytest.mark.parametrize("ids", ["1", [1, "2"], [True], {"a": 1}])
def test_hub_lezen_weigert_ongeldige_ids(api, ids):
    assert api.notificaties_lees({"ids": ids})[0] == 400


def test_hub_onthoudt_maximaal(api):
    hub = MeldingenHub(max_meldingen=3)
    for i in range(5):
        hub.voeg_toe(Melding(f"m{i}", nu=EPOCH))
    assert [m["tekst"] for m in hub.lijst()] == ["m4", "m3", "m2"]


def test_html_in_melding_blijft_tekst(api):
    kwaad = '"><img src=x onerror=alert(1)>'
    api.hub.voeg_toe(Melding(kwaad, nu=EPOCH))
    assert api.notificaties()[1]["meldingen"][0]["tekst"] == kwaad


# ----- timers -----

def test_timer_zetten_en_tonen(api, klok, audit_regels):
    code, timer = api.timer_zet({"naam": "thee", "seconden": 180})
    assert code == 201
    assert timer["naam"] == "thee"
    assert timer["resterend_seconden"] == 180
    assert timer["af_loopt_op"] == EPOCH + 180

    klok.nu += 60
    code, lijst = api.timers()
    assert code == 200
    assert lijst == [{"id": timer["id"], "naam": "thee", "resterend_seconden": 120,
                      "af_loopt_op": EPOCH + 180}]
    assert audit_regels[-1]["tool"] == "timer_zet"
    assert audit_regels[-1]["herkomst"] == "dashboard"


def test_timer_annuleren_op_id(api):
    _, a = api.timer_zet({"naam": "a", "seconden": 60})
    _, b = api.timer_zet({"naam": "b", "seconden": 60})
    assert api.timer_annuleer(a["id"]) == (200, {"ok": True})
    assert [t["naam"] for t in api.timers()[1]] == ["b"]
    assert api.timer_annuleer(a["id"])[0] == 404
    assert b["id"]


@pytest.mark.parametrize("timer_id", ["", None, 5, "x" * 65, "bestaat-niet"])
def test_timer_annuleren_onbekend(api, timer_id):
    assert api.timer_annuleer(timer_id)[0] == 404


@pytest.mark.parametrize("body", [
    None,
    [],
    {"naam": "x"},
    {"naam": "x", "seconden": 0},
    {"naam": "x", "seconden": -5},
    {"naam": "x", "seconden": 1.5},
    {"naam": "x", "seconden": "60"},
    {"naam": "x", "seconden": True},
    {"naam": "x", "seconden": 8 * 24 * 3600},
    {"naam": "", "seconden": 60},
    {"naam": "   ", "seconden": 60},
    {"naam": 5, "seconden": 60},
    {"naam": "x" * 61, "seconden": 60},
])
def test_timer_zetten_weigert_ongeldige_invoer(api, body):
    code, antwoord = api.timer_zet(body)
    assert code == 400
    assert antwoord["ok"] is False
    assert api.timers()[1] == []


def test_timernaam_met_html_blijft_tekst(api):
    kwaad = '<img src=x onerror="alert(1)">'
    _, timer = api.timer_zet({"naam": kwaad, "seconden": 60})
    assert timer["naam"] == kwaad
    assert api.timers()[1][0]["naam"] == kwaad


# ----- widgets -----

def test_widgets_standaard_zonder_bestand(api):
    code, data = api.widgets()
    assert code == 200
    assert data == api_mod.STANDAARD_WIDGETS
    # Een kopie: wijzigen raakt de standaard niet.
    data["kolommen"]["links"].clear()
    assert api_mod.STANDAARD_WIDGETS["kolommen"]["links"]


def test_widgets_opslaan_en_lezen(api, tmp_path, audit_regels):
    nieuw = {
        "versie": 3,  # de huidige indeling; oudere versies worden bij het lezen bijgewerkt
        "kolommen": {"links": ["timers", "spraakstatus"], "midden": ["auditlog"], "rechts": []},
        "instellingen": {"thema": "donker", "taal": "nl", "meldingen": False},
    }
    assert api.widgets_opslaan(nieuw) == (200, {"ok": True})
    assert api.widgets()[1] == nieuw
    op_schijf = json.loads((tmp_path / "dashboard.json").read_text(encoding="utf-8"))
    assert op_schijf == nieuw
    assert audit_regels[-1]["tool"] == "widgets_opslaan"


@pytest.mark.parametrize("body", [
    None,
    [],
    {"kolommen": {"links": ["bestaat_niet"]}},
    {"kolommen": {"boven": ["timers"]}},
    {"kolommen": {"links": ["timers"], "rechts": ["timers"]}},
    {"kolommen": {"links": "timers"}},
    {"kolommen": {}, "extra": 1},
    {"kolommen": {}, "instellingen": {"thema": 5}},
    {"kolommen": {}, "instellingen": {"onbekend": "x"}},
    {"kolommen": {}, "instellingen": {"meldingen": "ja"}},
    {"kolommen": {}, "versie": "1"},
])
def test_widgets_opslaan_weigert_ongeldig(api, tmp_path, body):
    code, _ = api.widgets_opslaan(body)
    assert code == 400
    assert not (tmp_path / "dashboard.json").exists()


def test_widgets_te_groot(api):
    body = {"kolommen": {}, "instellingen": {"thema": "x" * 20000}}
    assert api.widgets_opslaan(body)[0] == 413


def test_kapotte_widgetconfig_valt_terug_op_standaard(api, tmp_path):
    (tmp_path / "dashboard.json").write_text("{kapot", encoding="utf-8")
    assert api.widgets()[1] == api_mod.STANDAARD_WIDGETS
    (tmp_path / "dashboard.json").write_text('{"kolommen": {"links": ["virus"]}}', encoding="utf-8")
    assert api.widgets()[1] == api_mod.STANDAARD_WIDGETS


def test_meegeleverde_config_is_geldig():
    assert api_mod._valideer_widgets(api_mod.lees_widgets()) is None
    # Het meegeleverde bestand blijft bewust versie 1 (het dashboard schrijft
    # erin, dus een wijziging in git zou een "git pull" op de laptop laten
    # botsen). Na het inlezen is het precies de standaard van nu.
    with open(api_mod.WIDGETS_SJABLOON, encoding="utf-8") as f:
        assert api_mod._werk_widgets_bij(json.load(f)) == api_mod.STANDAARD_WIDGETS
