"""Fase 35B, M2–M4 — instellingen-tabs, "zet het terug" en de iPad-knop."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import verbeteren

ROOT = Path(__file__).resolve().parent.parent


def _beurt(zin, *acties):
    verbeteren.begin_beurt(zin)
    for actie in acties:
        verbeteren.noteer_actie(*actie)
    verbeteren.einde_beurt()


# ---------------------------------------------------------------------
# M3 — herkennen en terugzetten
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin", [
    "zet het terug", "Zet dat maar weer terug.", "draai dat terug", "maak dat ongedaan",
    "maak het even ongedaan", "ongedaan maken", "doe maar weer zoals het was", "zet het zoals het was",
    "kun je het terugzetten", "zet het terug alsjeblieft", "undo",
])
def test_is_terug(zin):
    assert verbeteren.is_terug(zin) or verbeteren.is_terug(zin.replace("kun je het ", ""))


@pytest.mark.parametrize("zin", ["zet de lamp aan", "zet het volume terug naar 30", "terug naar huis", "nee"])
def test_is_geen_terug(zin):
    assert not verbeteren.is_terug(zin)


def test_zet_terug_alleen_de_laatste():
    gedaan = []
    _beurt("dim de lamp", ("lamp", "Woonkamer", lambda: gedaan.append("lamp"), "de woonkamerlamp weer op 40% gezet"))
    assert verbeteren.kan_terug()
    assert verbeteren.zet_terug() == "Ik heb de woonkamerlamp weer op 40% gezet."
    assert gedaan == ["lamp"]
    assert verbeteren.zet_terug() == verbeteren.NIETS_TERUG  # nog een keer: niets
    assert not verbeteren.kan_terug()


def test_zet_terug_meerdere_acties_in_een_beurt():
    gedaan = []
    _beurt("protocol film",
           ("lamp", "Bank", lambda: gedaan.append("bank"), "de banklamp weer aangezet"),
           ("modus", "film", lambda: gedaan.append("film"), "de film-modus weer gestopt"))
    assert verbeteren.zet_terug() == "Ik heb de film-modus weer gestopt en de banklamp weer aangezet."
    assert gedaan == ["film", "bank"]


def test_na_de_minuut_niets(monkeypatch):
    verbeteren.begin_beurt("dim de lamp", nu=0.0)
    verbeteren.noteer_actie("lamp", "x", lambda: None, "x")
    verbeteren.einde_beurt(nu=0.0)
    assert verbeteren.zet_terug() == verbeteren.NIETS_TERUG


def test_tijdens_terugzetten_wordt_niets_genoteerd():
    def terug():
        verbeteren.noteer_actie("lamp", "y", lambda: None, "y")  # zoals de HA-tool zelf doet

    _beurt("dim de lamp", ("lamp", "x", terug, "x teruggezet"))
    verbeteren.begin_beurt("zet het terug")
    assert verbeteren.probeer_terug("zet het terug") == "Ik heb x teruggezet."
    assert verbeteren._beurt["huidig"]["acties"] == []
    verbeteren.einde_beurt()
    assert verbeteren.zet_terug() == verbeteren.NIETS_TERUG


def test_mislukt_terugzetten():
    def kapot():
        raise RuntimeError("weg")

    _beurt("dim", ("lamp", "x", kapot, "x"))
    assert verbeteren.zet_terug().startswith("Dat lukte niet")


def test_in_process_command(monkeypatch):
    from core import brain

    gedaan = []
    monkeypatch.setattr(brain, "try_open_program", lambda c: (
        verbeteren.noteer_actie("app", "discord", lambda: gedaan.append("dicht"), "discord weer gesloten")
        or "Ik open discord.") if c == "open discord" else None)
    assert brain.process_command("open discord") == "Ik open discord."
    assert brain.process_command("zet het terug") == "Ik heb discord weer gesloten."
    assert gedaan == ["dicht"]


def test_gericht_ziet_terug_als_voor_jarvis():
    from core import gericht

    _beurt("dim", ("lamp", "x", lambda: None, "x"))
    assert gericht.regels("maak dat ongedaan") == gericht.VOOR_JARVIS


# ---------------------------------------------------------------------
# M3 — wat er genoteerd wordt
# ---------------------------------------------------------------------

def _acties_van(fn):
    verbeteren.begin_beurt("test")
    try:
        fn()
        return list(verbeteren._beurt["huidig"]["acties"])
    finally:
        verbeteren.einde_beurt()


@pytest.mark.parametrize("pre,service,data,verwacht_service,verwacht_data,tekst", [
    ({"state": "off"}, "turn_on", None, "turn_off", None, "Lamp weer uitgezet"),
    ({"state": "on", "attributes": {"brightness": 102, "color_mode": "color_temp", "color_temp_kelvin": 2700}},
     "turn_on", {"brightness_pct": 100}, "turn_on", {"brightness_pct": 40, "color_temp_kelvin": 2700},
     "Lamp weer op 40% gezet"),
    ({"state": "on", "attributes": {"brightness": 255, "color_mode": "hs", "hs_color": [30, 80]}},
     "turn_off", None, "turn_on", {"brightness_pct": 100, "hs_color": [30, 80]}, "Lamp weer aangezet"),
])
def test_lamp_onthoudt_stand(pre, service, data, verwacht_service, verwacht_data, tekst):
    from core import home_assistant as ha

    acties = _acties_van(lambda: ha._noteer_verbeteren("light", "light.l", "Lamp", service, data, pre))
    assert len(acties) == 1
    argumenten = acties[0]["terug"][1]
    assert argumenten["service"] == verwacht_service and argumenten.get("service_data") == verwacht_data
    assert acties[0]["beschrijving"] == tekst


def test_lamp_niets_veranderd_niets_genoteerd():
    from core import home_assistant as ha

    assert _acties_van(lambda: ha._noteer_verbeteren("light", "l", "L", "turn_off", None, {"state": "off"})) == []
    assert _acties_van(lambda: ha._noteer_verbeteren("light", "l", "L", "turn_on", None, {"state": "on"})) == []
    assert _acties_van(lambda: ha._noteer_verbeteren("light", "l", "L", "turn_on", None, None)) == []


def test_volume_lokaal(monkeypatch):
    from actions import media

    monkeypatch.setattr(media, "get_volume", lambda: 30)
    monkeypatch.setattr(media, "run_on_com_thread", lambda fn: None)
    acties = _acties_van(lambda: media.set_volume(70))
    assert acties[0]["beschrijving"] == "het volume weer op 30% gezet"
    gezet = []
    monkeypatch.setattr(media, "set_volume", lambda p: gezet.append(p))
    acties[0]["terug"]()
    assert gezet == [30]


def test_muziek_lokaal(monkeypatch):
    from actions import media

    monkeypatch.setattr(media, "_press_media_key", lambda vk: True)
    acties = _acties_van(media.next_track)
    assert acties[0]["terug"] is media.previous_track
    assert _acties_van(media.play_pause)[0]["terug"] is media.play_pause


def test_game_pc_media_en_volume(monkeypatch):
    from core import tool_registry

    ok = SimpleNamespace(ok=True, data={"resultaat": {"ok": True}})
    acties = _acties_van(lambda: tool_registry._noteer_voor_verbeteren("game_pc_media", {"action": "next"}, ok))
    assert acties[0]["terug"] == ("game_pc_media", {"action": "previous"})
    acties = _acties_van(lambda: tool_registry._noteer_voor_verbeteren(
        "game_pc_set_volume", {"percent": 80}, ok, voor=25))
    assert acties[0]["terug"] == ("game_pc_set_volume", {"percent": 25})
    mislukt = SimpleNamespace(ok=True, data={"resultaat": {"ok": False}})
    assert _acties_van(lambda: tool_registry._noteer_voor_verbeteren(
        "game_pc_media", {"action": "next"}, mislukt)) == []


def test_game_pc_volume_uitlezen(monkeypatch):
    from core import tool_registry
    from remote import tools as remote_tools

    monkeypatch.setattr(remote_tools, "execute_remote_tool", lambda *a, **k: SimpleNamespace(
        ok=True, data={"resultaat": {"ok": True, "data": {"volume": 42}}}))
    assert tool_registry._game_pc_volume() == 42


def test_standaard_uitvoer_kent_game_pc_tools(monkeypatch):
    from core import ai

    gebruikt = []
    monkeypatch.setattr(ai, "execute_tool", lambda t, a, q: gebruikt.append((t, a)))
    verbeteren._standaard_uitvoer("game_pc_set_volume", {"percent": 25})
    assert gebruikt == [("game_pc_set_volume", {"percent": 25})]


def test_modi(tmp_path):
    from core import gespreksmodus, proactive

    pad = str(tmp_path / "g.json")
    acties = _acties_van(lambda: gespreksmodus.zet(True, pad=pad))
    assert acties[0]["beschrijving"] == "'In gesprek' weer uitgezet"
    acties[0]["terug"]()
    assert gespreksmodus.knop_aan(pad) is False

    oud = proactive._nachtmodstand
    try:
        proactive.set_nachtmodus("auto")
        acties = _acties_van(lambda: proactive.set_nachtmodus("aan"))
        acties[0]["terug"]()
        assert proactive._nachtmodstand == "auto"
    finally:
        proactive.set_nachtmodus(oud)


def test_spotify_onthoudt_wat_er_speelde():
    from core import spotify_smaak

    class Klant:
        def __init__(self, speler):
            self.speler, self.puts = speler, []

        def get(self, pad):
            return self.speler

        def put(self, pad, params=None, body=None):
            self.puts.append((pad, body))

    k = Klant({"is_playing": False})
    acties = _acties_van(lambda: spotify_smaak._noteer_terug(k))
    acties[0]["terug"]()
    assert k.puts == [("/me/player/pause", None)]

    k = Klant({"is_playing": True, "progress_ms": 5000, "context": {"uri": "spotify:playlist:x"},
               "item": {"uri": "spotify:track:y"}})
    acties = _acties_van(lambda: spotify_smaak._noteer_terug(k))
    acties[0]["terug"]()
    assert k.puts == [("/me/player/play", {"position_ms": 5000, "context_uri": "spotify:playlist:x",
                                           "offset": {"uri": "spotify:track:y"}})]


def test_volume_status_tool_geregistreerd():
    from core import pc_target, tool_registry, tool_select
    from remote import allowlist
    from remote import tools as remote_tools

    assert "volume_status" in allowlist.ALLOWED_TOOLS and "volume_status" in allowlist.BASIS_TOOLS
    assert "game_pc_volume_status" in remote_tools.REMOTE_TOOL_NAMES
    assert pc_target.LOCAL_TO_REMOTE["volume_status"] == "game_pc_volume_status"
    assert tool_registry.get_tool_risk("volume_status", {}) == "low"
    assert "volume_status" in tool_select.ALLEEN_INTERN


# ---------------------------------------------------------------------
# M2 + M4 — de iPad
# ---------------------------------------------------------------------

def test_dashboard_terug():
    from dashboard.api import DashboardAPI

    api = DashboardAPI(audit_fn=lambda **k: None)
    status, data = api.zet_terug()
    assert status == 200 and data["ok"] is False and data["tekst"] == verbeteren.NIETS_TERUG
    _beurt("dim", ("lamp", "x", lambda: None, "de lamp teruggezet"))
    status, data = api.zet_terug()
    assert data == {"ok": True, "tekst": "Ik heb de lamp teruggezet.", "kan_terug": False}


def test_dashboard_aansluiting():
    server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("POST", "/api/terug"): (b,' in server
    api = (ROOT / "dashboard" / "api.py").read_text(encoding="utf-8")
    assert '"kan_terug": _kan_terug()' in api
    html = (ROOT / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="terugKnop"' in html


def test_instellingen_in_vier_tabs():
    html = (ROOT / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    inst = html[html.index('id="instellingen"'):html.index('id="instFout"')]
    tabs = re.findall(r'<div class="inst-tab" data-instab="(\w+)"', inst)
    assert tabs == ["algemeen", "gewoontes", "leren", "spraak"]

    def koppen(tab):
        deel = inst[inst.index(f'<div class="inst-tab" data-instab="{tab}"') + 1:]
        volgende = re.search(r'<div class="inst-tab" data-instab="', deel)
        deel = deel[:volgende.start()] if volgende else deel
        return re.findall(r'<div class="inst-kop">([^<]+)</div>', deel)

    assert koppen("algemeen") == ["Deze iPad", "JARVIS", "Panelen", "Meldingen"]
    assert koppen("gewoontes") == ["Routines", "Geleerde gewoontes"]
    assert koppen("leren") == ["Verbeteringen", "Kon ik niet", "Zelfverbetering"]
    assert koppen("spraak") == ["Verstaan", "Storingen"]
    app = (ROOT / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function kiesInstTab(" in app and "localStorage" not in app
