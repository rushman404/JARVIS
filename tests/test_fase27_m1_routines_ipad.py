"""Fase 27, M1 — routines maken en aanpassen op de iPad (⚙ → Routines).

Werkt altijd op een tijdelijk routines.json; het echte bestand blijft staan.
"""

import json
from pathlib import Path

import pytest

from core import routine_bewerken, routines
from core.routine_bewerken import RoutineFout

STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"

BESTAAND = {
    "gaming": {
        "name": "gaming",
        "vertrouwd": True,
        "triggers": ["\\bgamen\\b"],
        "aliases": ["game modus"],
        "steps": [
            {"tool_name": "open_program", "arguments": {"program": "Discord"}},
            {"tool_name": "set_volume", "arguments": {"percent": 40}},
            {"tool_name": "control_home_assistant", "arguments": {
                "domain": "light", "service": "turn_on", "entity_id": "light.bed_lamp",
                "service_data": {"brightness_pct": 30}}},
        ],
        "description": "Gaming mode.",
        "usage_count": 186,
        "protocollen": ["gamen"],
        "start_zin": "Gamemodus wordt geactiveerd.",
        "eind_zin": "Veel plezier, sir.",
        "muziek_voorstel": "gaming",
    },
    "movie": {"name": "movie", "soort": "film", "steps": [], "description": "Film."},
}


@pytest.fixture(autouse=True)
def tijdelijk(tmp_path, monkeypatch):
    pad = tmp_path / "routines.json"
    pad.write_text(json.dumps(BESTAAND), encoding="utf-8")
    monkeypatch.setattr(routines, "ROUTINES_FILE", str(pad))
    routines._manager.reload()
    yield pad
    monkeypatch.undo()
    routines._manager.reload()


def _lees(pad):
    return json.loads(pad.read_text(encoding="utf-8"))


def _gaming():
    return next(r for r in routine_bewerken.lijst() if r["naam"] == "gaming")


# ---------------------------------------------------------------------
# Lezen
# ---------------------------------------------------------------------

def test_lijst_in_editorvorm():
    r = _gaming()
    assert r["protocollen"] == ["gamen"] and r["vertrouwd"] is True and r["bewerkbaar"] is True
    assert r["stappen"][0] == {"soort": "open", "programma": "Discord"}
    assert r["stappen"][1] == {"soort": "volume", "procent": 40}
    assert r["stappen"][2]["soort"] == "bestaand"
    assert r["stappen"][2]["tool_name"] == "control_home_assistant"
    film = next(r for r in routine_bewerken.lijst() if r["naam"] == "movie")
    assert film["bewerkbaar"] is False


# ---------------------------------------------------------------------
# Opslaan
# ---------------------------------------------------------------------

def test_nieuwe_routine(tijdelijk):
    r = routine_bewerken.opslaan({
        "naam": "Studeren", "protocollen": ["Studie", "leren"], "start_zin": "Tijd om te leren.",
        "eind_zin": "Succes, sir.", "vertrouwd": False,
        "stappen": [
            {"soort": "sluit", "programma": "Discord"},
            {"soort": "opdracht", "tekst": "zet de bedlamp op 80%"},
            {"soort": "volume", "procent": 20},
            {"soort": "opdracht", "tekst": "focusmodus voor 2 uur"},
        ],
    })
    assert r["naam"] == "studeren"
    opgeslagen = _lees(tijdelijk)["studeren"]
    assert opgeslagen["protocollen"] == ["studie", "leren"]
    assert opgeslagen["steps"] == [
        {"tool_name": "close_program", "arguments": {"program": "Discord"}},
        {"tool_name": "jarvis_opdracht", "arguments": {"tekst": "zet de bedlamp op 80%"}},
        {"tool_name": "set_volume", "arguments": {"percent": 20}},
        {"tool_name": "jarvis_opdracht", "arguments": {"tekst": "focusmodus voor 2 uur"}},
    ]
    assert opgeslagen["description"] == "Routine studeren (4 stappen)."
    assert "gaming" in _lees(tijdelijk)  # de rest blijft staan
    assert Path(str(tijdelijk) + ".bak").exists()


def test_bewerken_houdt_andere_velden(tijdelijk):
    r = _gaming()
    stappen = list(reversed(r["stappen"]))  # volgorde omdraaien, bestaande stap blijft
    routine_bewerken.opslaan({**r, "oude_naam": "gaming", "eind_zin": "Succes!", "stappen": stappen})
    opgeslagen = _lees(tijdelijk)["gaming"]
    assert opgeslagen["eind_zin"] == "Succes!"
    assert opgeslagen["steps"][0]["tool_name"] == "control_home_assistant"
    assert opgeslagen["usage_count"] == 186 and opgeslagen["muziek_voorstel"] == "gaming"
    assert opgeslagen["triggers"] == ["\\bgamen\\b"]


def test_hernoemen(tijdelijk):
    r = _gaming()
    routine_bewerken.opslaan({**r, "oude_naam": "gaming", "naam": "game avond"})
    data = _lees(tijdelijk)
    assert "gaming" not in data and data["game avond"]["usage_count"] == 186


def test_bestaande_stap_kan_niet_gewijzigd_worden():
    r = _gaming()
    r["stappen"][2]["arguments"] = {"domain": "lock", "service": "unlock", "entity_id": "lock.voordeur"}
    with pytest.raises(RoutineFout, match="bestaande stap"):
        routine_bewerken.opslaan({**r, "oude_naam": "gaming"})


def test_willekeurige_tool_kan_niet_via_dashboard():
    with pytest.raises(RoutineFout):
        routine_bewerken.opslaan({"naam": "x", "stappen": [
            {"soort": "bestaand", "tool_name": "power", "arguments": {"action": "shutdown"}}]})


@pytest.mark.parametrize("gegevens, melding", [
    ({"naam": "", "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "naam ontbreekt"),
    ({"naam": "gaming", "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "al een routine"),
    ({"naam": "a/b", "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "alleen letters"),
    ({"naam": "x", "stappen": []}, "minstens één stap"),
    ({"naam": "x", "stappen": [{"soort": "volume", "procent": 120}]}, "0 tot 100"),
    ({"naam": "x", "stappen": [{"soort": "volume", "procent": "40"}]}, "0 tot 100"),
    ({"naam": "x", "stappen": [{"soort": "open", "programma": ""}]}, "programma ontbreekt"),
    ({"naam": "x", "stappen": [{"soort": "opdracht", "tekst": "x" * 200}]}, "te lang"),
    ({"naam": "x", "stappen": [{"soort": "hack"}]}, "Onbekende soort"),
    ({"naam": "x", "stappen": [{"soort": "opdracht", "tekst": "x"}] * 21}, "Hooguit 20"),
    ({"naam": "x", "protocollen": ["a"] * 6, "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "Hooguit 5"),
    ({"naam": "x", "vertrouwd": "ja", "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "ja of nee"),
    ({"naam": "x", "oude_naam": "bestaatniet", "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "bestaat niet"),
    ({"naam": "movie", "oude_naam": "movie", "stappen": [{"soort": "opdracht", "tekst": "x"}]}, "film-routine"),
    ("geen object", "Stuur een routine"),
])
def test_ongeldig(gegevens, melding):
    with pytest.raises(RoutineFout, match=melding):
        routine_bewerken.opslaan(gegevens)


def test_verwijderen(tijdelijk):
    assert routine_bewerken.verwijder("gaming") is True
    assert "gaming" not in _lees(tijdelijk)
    assert routine_bewerken.verwijder("gaming") is False
    with pytest.raises(RoutineFout):
        routine_bewerken.verwijder("")


# ---------------------------------------------------------------------
# De stap "zeg tegen JARVIS"
# ---------------------------------------------------------------------

def test_jarvis_opdracht_tool(monkeypatch):
    import core.ai as ai
    import core.brain as brain
    from core.tool_registry import TOOL_RISK, _TAAK_OMSCHRIJVING

    assert TOOL_RISK["jarvis_opdracht"][0] == "low"
    assert _TAAK_OMSCHRIJVING["jarvis_opdracht"]({"tekst": "zet de tv aan"}) == '"zet de tv aan"'
    gezegd = []
    monkeypatch.setattr(brain, "process_command", lambda t: gezegd.append(t) or f"gedaan: {t}")
    assert ai._dispatch_local_tool("jarvis_opdracht", {"tekst": "zet de tv aan"}, "") == "gedaan: zet de tv aan"
    assert gezegd == ["zet de tv aan"]
    assert "geen opdracht" in ai._dispatch_local_tool("jarvis_opdracht", {"tekst": ""}, "")


def test_jarvis_opdracht_geen_eindeloze_lus(monkeypatch):
    import core.ai as ai
    import core.brain as brain

    def zelf(tekst):
        # Een routinestap die weer een routinestap start.
        return ai._dispatch_local_tool("jarvis_opdracht", {"tekst": "nog eens"}, "")

    monkeypatch.setattr(brain, "process_command", zelf)
    assert ai._dispatch_local_tool("jarvis_opdracht", {"tekst": "protocol x"}, "").startswith("Overgeslagen")


def test_jarvis_opdracht_niet_voor_gemini():
    from core import privacy_poort

    assert "jarvis_opdracht" not in privacy_poort.CLOUD_TOOLS


def test_routine_met_opdracht_stap_draait(monkeypatch, tijdelijk):
    import core.brain as brain
    from core import executor

    routine_bewerken.opslaan({"naam": "proef", "vertrouwd": True,
                              "stappen": [{"soort": "opdracht", "tekst": "zet de tv aan"}]})
    gezegd = []
    echte = brain.process_command

    def nep(tekst, *a, **k):
        if tekst == "zet de tv aan":
            gezegd.append(tekst)
            return "De tv gaat aan."
        return echte(tekst, *a, **k)

    monkeypatch.setattr(brain, "process_command", nep)
    stappen = routines._manager.steps_for_agent("proef")
    resultaten = executor.execute_action_plan(stappen, "routine: proef", trusted=True)
    assert gezegd == ["zet de tv aan"]
    assert resultaten[0]["status"] == "done"


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------

@pytest.fixture
def api(tmp_path):
    from dashboard.api import DashboardAPI

    regels = []
    return DashboardAPI(audit_fn=lambda **v: regels.append(v), widgets_pad=str(tmp_path / "d.json")), regels


def test_api_lijst_opslaan_verwijderen(api, tijdelijk):
    a, regels = api
    status, data = a.routines_bewerken()
    assert status == 200 and {r["naam"] for r in data["routines"]} == {"gaming", "movie"}
    status, data = a.routine_opslaan({"naam": "proef", "stappen": [{"soort": "opdracht", "tekst": "zet de tv aan"}]})
    assert status == 200 and data["routine"]["naam"] == "proef"
    assert regels[-1]["tool"] == "routine_opslaan"
    status, data = a.routine_opslaan({"naam": "proef", "stappen": [{"soort": "opdracht", "tekst": "x"}]})
    assert status == 400 and "al een routine" in data["fout"]["melding"]
    assert a.routine_verwijder({"naam": "proef"})[0] == 200
    assert a.routine_verwijder({"naam": "proef"})[0] == 404
    assert a.routine_verwijder(None)[0] == 400


def test_routes_alleen_bedienen_voor_wijzigen():
    tekst = (Path(__file__).resolve().parent.parent / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("POST", "/api/routines/opslaan"): (b,' in tekst
    assert '("POST", "/api/routines/verwijder"): (b,' in tekst
    assert '("GET", "/api/routines/bewerken"): (k,' in tekst


def test_editor_in_het_dashboard():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for id_ in ("instRoutines", "instNieuweRoutine", "routineEditor", "reNaam", "reProtocollen",
                "reStart", "reEind", "reVertrouwd", "reStappen", "reSoort", "reWaarde", "reVerwijder"):
        assert f'id="{id_}"' in html, id_
    for functie in ("function openRoutineEditor", "function opslaanRoutine", "function verwijderRoutine",
                    "function verplaatsStap", "/api/routines/opslaan", "Zeker verwijderen?"):
        assert functie in js
    deel = js[js.index("var RE_SOORT"):js.index("function openInstellingen")]
    assert "innerHTML" not in deel and "=>" not in deel


def test_lange_vensters_scrollen_met_knoppen_zichtbaar():
    # Fix 2026-10-30: met Routines erbij liep Instellingen van het scherm en
    # waren Opslaan/Annuleren onbereikbaar.
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".dialoog { max-height: calc(100% - 24px); overflow-y: auto; -webkit-overflow-scrolling: touch; }" in css
    assert ".dialoog > .dialoog-knoppen { position: -webkit-sticky; position: sticky;" in css
