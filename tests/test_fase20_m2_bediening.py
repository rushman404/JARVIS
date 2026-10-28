"""Fase 20, M2 — routines starten en lampen dimmen of kleuren."""

import inspect
import os
import time

import pytest

import status
from core import opdrachten
from dashboard import api as api_mod
from dashboard.bronnen import LAMP_KLEUREN, LAMP_WARMTES, Bronnen, lamp_mogelijkheden

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------
# Wat een lamp kan
# ---------------------------------------------------------------

@pytest.mark.parametrize("modi, verwacht", [
    (["onoff"], (False, False, False)),
    (["brightness"], (True, False, False)),
    (["color_temp"], (True, True, False)),
    (["color_temp", "hs"], (True, True, True)),
    (["rgbww"], (True, False, True)),
    ([], (False, False, False)),
    ("onzin", (False, False, False)),
])
def test_lamp_mogelijkheden(modi, verwacht):
    kan = lamp_mogelijkheden({"supported_color_modes": modi, "brightness": 128})
    assert (kan["dimbaar"], kan["warmte"], kan["kleur"]) == verwacht
    assert kan["helderheid"] == 50


# ---------------------------------------------------------------
# Lamp instellen (via de bewaakte poort)
# ---------------------------------------------------------------

STATES = {
    "light.bed": {"state": "on", "attributes": {
        "friendly_name": "Bedlamp", "brightness": 255, "supported_color_modes": ["color_temp", "hs"],
        "min_color_temp_kelvin": 2200, "max_color_temp_kelvin": 5500}},
    "light.plafond": {"state": "off", "attributes": {"friendly_name": "Plafond", "supported_color_modes": ["onoff"]}},
    "switch.tv": {"state": "off", "attributes": {}},
}


def _bronnen(aanroepen):
    def tool(naam, args, vraag):
        aanroepen.append((naam, args))
        return "gelukt"

    b = Bronnen(tool_fn=tool, ha_get_fn=lambda pad: (True, [dict(v, entity_id=k) for k, v in STATES.items()]),
                scenes_fn=lambda: {})
    b._ha_states = lambda: STATES
    return b


GEKOZEN = ["light.bed", "light.plafond", "switch.tv"]


def test_helderheid_kleur_en_warmte():
    aanroepen = []
    b = _bronnen(aanroepen)
    assert b.lamp_instellen("light.bed", GEKOZEN, helderheid=40)[0]
    assert b.lamp_instellen("light.bed", GEKOZEN, kleur="blauw")[0]
    assert b.lamp_instellen("light.bed", GEKOZEN, warmte="koel")[0]
    data = [a[1]["service_data"] for a in aanroepen]
    assert data == [{"brightness_pct": 40}, {"rgb_color": list(LAMP_KLEUREN["blauw"])},
                    {"color_temp_kelvin": 5500}]  # koel = 6000 K, begrensd op wat de lamp kan
    assert all(a[0] == "control_home_assistant" and a[1]["service"] == "turn_on" for a in aanroepen)


@pytest.mark.parametrize("kwargs, fout", [
    ({"helderheid": 0}, "tussen 1 en 100"),
    ({"helderheid": 101}, "tussen 1 en 100"),
    ({"helderheid": True}, "tussen 1 en 100"),
    ({"helderheid": "50"}, "tussen 1 en 100"),
    ({"kleur": "zwart"}, "Onbekende kleur"),
    ({"warmte": "heet"}, "Onbekende warmte"),
    ({}, "Kies één ding"),
    ({"helderheid": 50, "kleur": "rood"}, "Kies één ding"),
])
def test_ongeldige_invoer(kwargs, fout):
    aanroepen = []
    ok, melding = _bronnen(aanroepen).lamp_instellen("light.bed", GEKOZEN, **kwargs)
    assert not ok and fout in melding and aanroepen == []


def test_alleen_wat_de_lamp_kan():
    aanroepen = []
    b = _bronnen(aanroepen)
    assert "kan niet dimmen" in b.lamp_instellen("light.plafond", GEKOZEN, helderheid=50)[1]
    assert "geen kleur" in b.lamp_instellen("light.plafond", GEKOZEN, kleur="rood")[1]
    assert aanroepen == []


def test_alleen_lampen_op_het_dashboard():
    aanroepen = []
    b = _bronnen(aanroepen)
    assert not b.lamp_instellen("light.bed", ["light.plafond"], helderheid=50)[0]
    assert not b.lamp_instellen("switch.tv", GEKOZEN, helderheid=50)[0]
    assert aanroepen == []


def test_tegel_bevat_lampmogelijkheden():
    b = _bronnen([])
    tegels = {t["id"]: t for t in b.slim_huis(GEKOZEN)["tegels"]}
    assert tegels["light.bed"]["lamp"] == {"dimbaar": True, "warmte": True, "kleur": True, "helderheid": 100}
    assert "lamp" not in tegels["switch.tv"]


def test_api_lamp(tmp_path):
    api = api_mod.DashboardAPI(widgets_pad=str(tmp_path / "d.json"), fase_fn=lambda: "rust",
                               spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    gezien = []

    class NepBronnen:
        def lamp_instellen(self, entity_id, gekozen, **kw):
            gezien.append((entity_id, kw))
            return True, "ok"

    api._bronnen = NepBronnen()
    assert api.lamp({"id": "light.bed", "helderheid": 30})[0] == 200
    assert gezien[0] == ("light.bed", {"helderheid": 30, "kleur": None, "warmte": None})
    assert api.lamp({"id": "light.bed", "brightness": 30})[0] == 400  # onbekend veld
    assert api.lamp(["x"])[0] == 400

    class Fout:
        def __init__(self, melding):
            self.melding = melding

        def lamp_instellen(self, *a, **k):
            return False, self.melding

    api._bronnen = Fout("Deze lamp staat niet in de lijst van het dashboard.")
    assert api.lamp({"id": "light.x", "helderheid": 30})[0] == 404
    api._bronnen = Fout("Onbekende kleur.")
    assert api.lamp({"id": "light.bed", "kleur": "zwart"})[0] == 400
    api._bronnen = Fout("HA gaf een fout")
    assert api.lamp({"id": "light.bed", "kleur": "rood"})[0] == 502


def test_kleurnamen_in_pwa_en_server_gelijk():
    js = open(os.path.join(PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    blok = js.split("var LAMP_KLEUREN = [")[1].split("];")[0]
    for naam in LAMP_KLEUREN:
        assert f"['{naam}'," in blok, naam
    html = open(os.path.join(PROJECT, "dashboard", "static", "index.html"), encoding="utf-8").read()
    for warmte in LAMP_WARMTES:
        assert f'data-warmte="{warmte}"' in html


# ---------------------------------------------------------------
# Routines
# ---------------------------------------------------------------

def _wacht(runner):
    eind = time.time() + 3
    while runner.bezig() and time.time() < eind:
        time.sleep(0.01)
    assert not runner.bezig()


def test_routine_starten_via_het_brein(monkeypatch):
    from core import brain

    gestart = []
    monkeypatch.setattr(brain, "_execute_routine",
                        lambda naam, routine, cmd: gestart.append((naam, cmd)) or "Routine 'gaming' klaar.")
    monkeypatch.setattr(opdrachten.OpdrachtRunner, "_routine", staticmethod(lambda naam: {"name": naam}))
    runner = opdrachten.OpdrachtRunner(audit_fn=lambda **k: None)
    assert runner.start_routine("gaming") == (True, None)
    _wacht(runner)
    assert gestart == [("gaming", "routine gaming")]
    assert [b["tekst"] for b in status.gesprek()[-2:]] == ["Routine 'gaming' starten", "Routine 'gaming' klaar."]


def test_onbekende_routine():
    runner = opdrachten.OpdrachtRunner(audit_fn=lambda **k: None)
    assert runner.start_routine("bestaat-niet-xyz") == (False, "onbekend")
    assert runner.start_routine("") == (False, "onbekend")


def test_api_routine_start(tmp_path):
    api = api_mod.DashboardAPI(widgets_pad=str(tmp_path / "d.json"), fase_fn=lambda: "rust",
                               spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    api.bronnen.routines_fn = lambda: {"gaming": {"name": "gaming"}}

    class NepRunner:
        def __init__(self, uitkomst):
            self.uitkomst = uitkomst

        def start_routine(self, naam, hardop=False):
            return self.uitkomst

    api.opdrachten = NepRunner((True, None))
    assert api.routine_start({"naam": "gaming"}) == (202, {"ok": True})
    assert api.routine_start({"naam": "film"})[0] == 404
    assert api.routine_start({})[0] == 400
    api.opdrachten = NepRunner((False, "bezig"))
    assert api.routine_start({"naam": "gaming"})[0] == 409


def test_routines_overzicht_geeft_sleutel():
    from dashboard.bronnen import routines_overzicht

    uit = routines_overzicht({"gaming": {"name": "Gamen!", "steps": []}})
    assert uit[0]["id"] == "gaming" and uit[0]["naam"] == "Gamen!"


# ---------------------------------------------------------------
# Indeling: het routinepaneel komt er vanzelf bij
# ---------------------------------------------------------------

def test_oude_indeling_krijgt_routines(tmp_path):
    import json

    pad = tmp_path / "dashboard.json"
    pad.write_text(json.dumps({
        "versie": 1,
        "kolommen": {"links": ["spraakstatus"], "midden": ["gesprek", "auditlog"], "rechts": ["systeem"]},
        "instellingen": {"meldingen": True},
        "slim_huis": ["light.bed"],
    }), encoding="utf-8")
    data = api_mod.lees_widgets(str(pad))
    # Versie 2 voegt routines toe, versie 3 (Fase 23) zet Vandaag op de plek van de auditlog.
    assert data["versie"] == 3
    assert data["kolommen"]["midden"] == ["gesprek", "routines", "vandaag"]
    assert data["slim_huis"] == ["light.bed"]


def test_verborgen_routines_blijft_verborgen(tmp_path):
    import json

    pad = tmp_path / "dashboard.json"
    pad.write_text(json.dumps({"versie": 2, "kolommen": {"midden": ["gesprek", "auditlog"]}}), encoding="utf-8")
    assert api_mod.lees_widgets(str(pad))["kolommen"]["midden"] == ["gesprek", "vandaag"]


def test_standaard_indeling():
    assert api_mod.STANDAARD_WIDGETS["kolommen"]["midden"] == ["gesprek", "routines", "vandaag"]
    assert api_mod._valideer_widgets(api_mod.STANDAARD_WIDGETS) is None


# ---------------------------------------------------------------
# Routes en PWA
# ---------------------------------------------------------------

def test_routes_alleen_bedienen():
    from dashboard.server import DashboardServer

    bron = inspect.getsource(DashboardServer)
    assert '("POST", "/api/ha/lamp"): (b,' in bron
    assert '("POST", "/api/routines/start"): (b,' in bron


def test_pwa():
    js = open(os.path.join(PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    html = open(os.path.join(PROJECT, "dashboard", "static", "index.html"), encoding="utf-8").read()
    assert "['routines', 'Routines']" in js and "function laadRoutines(" in js and "function openLamp(" in js
    assert 'data-widget="routines"' in html and 'id="lampVenster"' in html
    assert ".innerHTML" not in js
