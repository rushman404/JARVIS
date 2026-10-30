"""Tests voor Fase 18 M4: de tegels met echte gegevens (dashboard/bronnen.py).

Dekt:
  - auditlog lezen (nieuwste eerst, geen inlogregels, geen geheimen)
  - media: volumes (lokaal en via de game-pc-agent), acties via de
    bewaakte poort met herkomst "dashboard"
  - slim huis: alleen lampen en scènes uit de vaste lijsten zijn tikbaar
  - weer: eerst Home Assistant, anders Open-Meteo
  - pc-meters: drempels (80% / 80% / 75 °C), game-pc niet verbonden
  - nachtmodus en slaapstand (die NOOIT direct uitvoert: alleen een
    goedkeuring met id + nonce)
  - het gesprek-geheugen in status.py
  - rollen op de nieuwe endpoints (kijk mag lezen, niet bedienen)

Alles wat naar buiten gaat (HA, tools, telemetrie) is nep.
"""

import json

import pytest

import status as status_mod
from core import proactive
from core.confirmation import ID_KEY, clear_pending, get_pending
from core.timers import TimerStore
from dashboard import auth
from dashboard.api import DashboardAPI
from dashboard.bronnen import Bronnen, Cache, _ontpak, lees_audit
from dashboard.server import DashboardServer, standaard_hosts, standaard_origins
from remote.server import RateLimiter

VIEW = "kijk-token-0123456789abcdef"
CONTROL = "bedien-token-0123456789abcdef"
HOST = "192.168.1.5:8780"
ORIGIN = "https://192.168.1.5:8780"
IPAD = "192.168.1.20"


class TR:
    def __init__(self, ok, data=None, message=""):
        self.ok, self.data, self.message = ok, data, message


APPARATEN = {
    "light.woonkamer_lamp": ["woonkamerlamp"],
    "light.bed_lamp": ["bedlamp"],
    "switch.tv_switch": ["tv"],
    "cover.woonkamer_gordijn": ["gordijn"],
}


def _states(woonkamer="on", weer=True):
    lijst = [
        {"entity_id": "light.woonkamer_lamp", "state": woonkamer, "attributes": {"friendly_name": "Woonkamer", "brightness": 128}},
        {"entity_id": "light.bed_lamp", "state": "off", "attributes": {"friendly_name": "Bedlamp"}},
        {"entity_id": "switch.tv_switch", "state": "on", "attributes": {}},
        {"entity_id": "cover.woonkamer_gordijn", "state": "open", "attributes": {"current_position": 80}},
    ]
    if weer:
        lijst.append({"entity_id": "weather.forecast_thuis", "state": "rainy",
                      "attributes": {"friendly_name": "Thuis", "temperature": 12.6}})
    return lijst


@pytest.fixture
def aanroepen():
    return []


@pytest.fixture
def bronnen(tmp_path, aanroepen):
    def tool(naam, args, vraag):
        aanroepen.append((naam, args, vraag))
        return TR(True, message="ok")

    return Bronnen(
        tool_fn=tool,
        lees_fn=lambda naam, args, vraag: TR(True, {"volume": {"Spotify": 50, "Discord": 30}[args["app_name"]]}),
        ha_get_fn=lambda pad: (True, _states()),
        weer_fn=lambda plaats: {"ok": True, "plaats": f"{plaats}, Nederland", "temperatuur": 14.4,
                                "beschrijving": "Bewolkt", "vandaag_max": 16.2, "vandaag_min": 8.6},
        telemetrie_lokaal_fn=lambda: {"cpu": {"ok": True, "gebruik_percent": 23.4}, "ram": {"ok": True, "percentage": 81},
                                      "gpu": {"ok": True, "gpus": [{"temperatuur_c": 52}]}},
        telemetrie_game_pc_fn=lambda: None,
        scene_fn=lambda naam, scene: aanroepen.append(("scene", naam, None)) or "Scène gestart.",
        scenes_fn=lambda: {"avondmodus": {"steps": []}},
        apparaten_fn=lambda: dict(APPARATEN),
        weer_plaats_fn=lambda: "Badhoevedorp",
        pc_target_fn=lambda: "game-pc",
        audit_pad_fn=lambda: str(tmp_path / "audit.jsonl"),
        vandaag_fn=lambda: {"datum": "2026-10-28", "agenda": {"status": "niet_ingesteld"},
                            "mail": {"status": "niet_gekoppeld"}, "discord": {"status": "niet_gebruikt"}},
    )


@pytest.fixture(autouse=True)
def schoon():
    clear_pending()
    proactive.set_nachtmodus("auto")
    yield
    clear_pending()
    proactive.set_nachtmodus("auto")


# ----- auditlog -----

def _schrijf_audit(pad, regels):
    pad.write_text("\n".join(json.dumps(r) for r in regels) + "\n", encoding="utf-8")


def test_audit_nieuwste_eerst_zonder_inlogregels(tmp_path):
    pad = tmp_path / "audit.jsonl"
    _schrijf_audit(pad, [
        {"tijd": "2026-10-24T10:41:12", "tool": "open_program", "argumenten": {"name": "discord"}, "risico": "low", "goedgekeurd": True},
        {"tijd": "2026-10-24T10:41:13", "tool": "dashboard_auth", "argumenten": {}, "goedgekeurd": False, "reden": "x"},
        {"tijd": "2026-10-24T10:42:40", "tool": "game_pc_power", "argumenten": {"action": "shutdown"}, "risico": "high",
         "goedgekeurd": False, "reden": "goedkeuring geweigerd", "herkomst": "dashboard"},
    ])
    regels = lees_audit(str(pad))
    assert [r["actie"] for r in regels] == ["game_pc_power · shutdown", "open_program · discord"]
    assert regels[0] == {"tijd": "10:42:40", "actie": "game_pc_power · shutdown", "risico": "HIGH",
                         "resultaat": "goedkeuring geweigerd", "goedgekeurd": False, "herkomst": "dashboard"}
    assert regels[1]["resultaat"] == "gelukt"


def test_audit_toont_geen_geheimen_en_overleeft_kapotte_regels(tmp_path):
    pad = tmp_path / "audit.jsonl"
    pad.write_text(
        "{kapot\n" + json.dumps({"tijd": "2026-10-24T10:00:00", "tool": "x", "argumenten": {"token": "***", "naam": "a"},
                                  "goedgekeurd": True}) + "\n", encoding="utf-8")
    regels = lees_audit(str(pad))
    assert regels[0]["actie"] == "x · a"
    assert lees_audit(str(tmp_path / "bestaat-niet.jsonl")) == []


def test_audit_leest_alleen_opnieuw_na_een_wijziging(bronnen, tmp_path):
    pad = tmp_path / "audit.jsonl"
    _schrijf_audit(pad, [{"tijd": "2026-10-24T10:00:00", "tool": "a", "goedgekeurd": True}])
    assert [r["actie"] for r in bronnen.audit()] == ["a"]
    _schrijf_audit(pad, [{"tijd": "2026-10-24T10:00:00", "tool": "a", "goedgekeurd": True},
                         {"tijd": "2026-10-24T10:00:01", "tool": "bb", "goedgekeurd": True}])
    assert [r["actie"] for r in bronnen.audit()] == ["bb", "a"]


# ----- media -----

def test_media_volumes(bronnen):
    m = bronnen.media()
    assert m["doel"] == "game-pc"
    # Alleen Spotify (Discord is op verzoek uit het media-blok gehaald).
    assert m["apps"] == [{"naam": "Spotify", "volume": 50, "actief": True}]


def test_media_volume_via_de_game_pc_agent_wordt_uitgepakt():
    remote = {"remote_tool": "audio_get_session_volume", "status": "geslaagd",
              "resultaat": {"ok": True, "message": "", "data": {"volume": 42}}}
    assert _ontpak(remote) == {"volume": 42}
    assert _ontpak({"volume": 1}) == {"volume": 1}


def test_media_app_niet_actief(bronnen):
    bronnen.lees_fn = lambda *a: TR(False, None, "geen sessie")
    assert all(not a["actief"] and a["volume"] is None for a in bronnen.media()["apps"])


@pytest.mark.parametrize("actie, tool, args", [
    ("play_pauze", "media_play_pause", {}),
    ("volgende", "media_next", {}),
    ("vorige", "media_previous", {}),
    ("stop", "media_stop", {}),
])
def test_media_acties_gaan_naar_de_juiste_tool(bronnen, aanroepen, actie, tool, args):
    ok, _ = bronnen.media_actie(actie)
    assert ok
    assert aanroepen[-1][:2] == (tool, args)
    assert aanroepen[-1][2].startswith("dashboard:")


@pytest.mark.parametrize("actie, waarde", [("volume", 101), ("volume", -1), ("volume", "50"), ("volume", True), ("rm -rf", None)])
def test_media_ongeldige_acties(bronnen, aanroepen, actie, waarde):
    ok, _ = bronnen.media_actie(actie, waarde)
    assert not ok
    assert aanroepen == []


def test_schrijfacties_gaan_door_de_bewaakte_poort_met_herkomst(monkeypatch):
    import core.ai
    import core.tool_registry
    from dashboard import bronnen as mod

    gezien = {}

    def nep_poort(tool, args, **kw):
        gezien.update(kw, tool=tool, args=args)
        return "ok"

    monkeypatch.setattr(core.tool_registry, "run_tool_guarded", nep_poort)
    monkeypatch.setattr(core.ai, "_dispatch_tool", lambda *a: "lokaal")
    mod._std_tool("media_next", {}, "dashboard: media volgende")
    assert gezien["tool"] == "media_next"
    assert gezien["herkomst"] == "dashboard"
    assert gezien["source"] == "dashboard"
    assert gezien["dispatch"] is core.ai._dispatch_tool


# ----- slim huis -----

def test_slim_huis_tegels(bronnen):
    sh = bronnen.slim_huis()
    assert sh["beschikbaar"] is True
    tegels = {t["id"]: t for t in sh["tegels"]}
    assert tegels["light.woonkamer_lamp"]["aan"] is True
    assert tegels["light.woonkamer_lamp"]["detail"] == "Lamp · 50%"
    assert tegels["cover.woonkamer_gordijn"]["label"] == "OPEN"
    assert tegels["cover.woonkamer_gordijn"]["detail"] == "Positie 80%"
    # Alleen lampen en scènes zijn tikbaar.
    # Lampen, schakelaars en scènes zijn tikbaar; rolluiken e.d. alleen status.
    assert {i for i, t in tegels.items() if t["tikbaar"]} == {
        "light.woonkamer_lamp", "light.bed_lamp", "switch.tv_switch", "scene:avondmodus"}


def test_slim_huis_zonder_home_assistant(bronnen):
    bronnen.ha_get_fn = lambda pad: (False, "Kan Home Assistant niet bereiken")
    sh = bronnen.slim_huis()
    assert sh["beschikbaar"] is False
    assert all(t["label"] in ("?", "ACTIVEER") for t in sh["tegels"])


def test_lamp_wisselen_kiest_aan_of_uit(bronnen, aanroepen):
    assert bronnen.lamp_wissel("light.woonkamer_lamp")[0]
    assert aanroepen[-1][1] == {"domain": "light", "service": "turn_off", "entity_id": "light.woonkamer_lamp"}
    assert bronnen.lamp_wissel("light.bed_lamp")[0]
    assert aanroepen[-1][1]["service"] == "turn_on"


@pytest.mark.parametrize("entity", ["cover.woonkamer_gordijn", "light.onbekend", "lock.voordeur", None, 5])
def test_alleen_bekende_lampen_zijn_te_bedienen(bronnen, aanroepen, entity):
    ok, _ = bronnen.lamp_wissel(entity)
    assert not ok
    assert aanroepen == []


def test_scene_starten(bronnen, aanroepen):
    assert bronnen.scene_start("avondmodus") == (True, "Scène gestart.")
    assert aanroepen[-1] == ("scene", "avondmodus", None)
    assert bronnen.scene_start("bestaat_niet")[0] is False


# ----- weer -----

def test_weer_eerst_uit_home_assistant(bronnen):
    w = bronnen.weer()
    assert w == {"beschikbaar": True, "bron": "home_assistant", "plaats": "Thuis", "temperatuur": 13,
                 "beschrijving": "Regen", "max": None, "min": None}


def test_weer_valt_terug_op_open_meteo(bronnen):
    bronnen.ha_get_fn = lambda pad: (True, _states(weer=False))
    w = bronnen.weer()
    assert w["bron"] == "open_meteo"
    assert w["plaats"] == "Badhoevedorp"
    assert (w["temperatuur"], w["max"], w["min"]) == (14, 16, 9)


def test_weer_niet_beschikbaar(bronnen):
    bronnen.ha_get_fn = lambda pad: (False, "uit")
    bronnen.weer_fn = lambda plaats: {"ok": False}
    assert bronnen.weer()["beschikbaar"] is False


# ----- pc-meters -----

def test_meters_met_drempels(bronnen):
    pc = bronnen.pc_status("local")
    meters = {m["naam"]: m for m in pc["meters"]}
    assert meters["Processor"]["waarde"] == 23 and not meters["Processor"]["hoog"]
    assert meters["Geheugen"]["waarde"] == 81 and meters["Geheugen"]["hoog"]
    assert meters["GPU-temperatuur"]["waarde"] == 52 and not meters["GPU-temperatuur"]["hoog"]


def test_game_pc_niet_verbonden_en_remote_telemetrie(bronnen):
    assert bronnen.pc_status("game-pc")["beschikbaar"] is False
    bronnen.cache = Cache()
    bronnen.telemetrie_game_pc_fn = lambda: TR(True, {
        "remote_tool": "telemetry", "status": "geslaagd",
        "resultaat": {"cpu": {"ok": True, "gebruik_percent": 90}, "ram": {"ok": True, "percentage": 10},
                      "gpu": {"ok": True, "gpus": [{"temperatuur_c": 80}]}}})
    meters = {m["naam"]: m for m in bronnen.pc_status("game-pc")["meters"]}
    assert meters["Processor"]["hoog"] and meters["GPU-temperatuur"]["hoog"]
    assert bronnen.pc_status("server") is None


def test_cache_voorkomt_hameren(bronnen):
    teller = []
    bronnen.telemetrie_lokaal_fn = lambda: teller.append(1) or {}
    bronnen.pc_status("local")
    bronnen.pc_status("local")
    assert len(teller) == 1


# ----- API: nachtmodus, slaapstand, gesprek -----

@pytest.fixture
def api(tmp_path, bronnen):
    regels = []
    a = DashboardAPI(
        timer_store=TimerStore(pad=str(tmp_path / "timers.json")),
        widgets_pad=str(tmp_path / "dashboard.json"),
        audit_fn=lambda **v: regels.append(v),
        bronnen=bronnen,
        gesprek_fn=lambda: [{"id": i, "wie": "me" if i % 2 else "ai", "tekst": f"beurt {i}"} for i in range(1, 9)],
        power_doel_fn=lambda: "game-pc",
        uitvoerder=lambda p, ok: pytest.fail("power mag nooit direct uitgevoerd worden"),
    )
    a.audit_regels = regels
    return a


@pytest.mark.parametrize("stand", ["aan", "uit", "auto"])
def test_nachtmodus_zetten(api, stand):
    code, data = api.nachtmodus({"stand": stand})
    assert code == 200 and data["stand"] == stand
    assert api.audit_regels[-1]["tool"] == "nachtmodus"


@pytest.mark.parametrize("body", [{"stand": "AAN"}, {"stand": "nacht"}, {}, None, []])
def test_nachtmodus_ongeldig(api, body):
    assert api.nachtmodus(body)[0] == 400
    assert proactive.get_nachtmodus_stand() == "auto"


def test_slaapstand_maakt_alleen_een_goedkeuring(api):
    code, data = api.power({"actie": "slaap"})
    assert code == 202
    pending = get_pending()
    assert pending["kind"] == "power_confirm"
    assert pending["action"] == "sleep"
    assert pending["target"] == "game-pc"
    assert data["id"] == pending[ID_KEY]
    assert "nonce" not in data
    assert api.audit_regels[-1]["goedgekeurd"] is False


@pytest.mark.parametrize("actie", ["afsluiten", "shutdown", "lock", "logoff", None])
def test_onbekende_power_actie_kan_niet_vanaf_het_dashboard(api, actie):
    assert api.power({"actie": actie})[0] == 400
    assert get_pending() is None


def test_gesprek_geeft_alle_recente_beurten(api):
    code, beurten = api.gesprek()
    assert code == 200
    assert [b["tekst"] for b in beurten] == [f"beurt {i}" for i in range(1, 9)]


def test_slim_huis_actie_via_api(api, aanroepen):
    assert api.slim_huis_actie({"id": "light.bed_lamp"})[0] == 200
    assert api.slim_huis_actie({"id": "scene:avondmodus"})[0] == 200
    assert api.slim_huis_actie({"id": "cover.woonkamer_gordijn"})[0] == 404
    assert api.slim_huis_actie({"id": "scene:onbekend"})[0] == 404
    assert api.slim_huis_actie({})[0] == 400


def test_media_actie_via_api(api):
    assert api.media_actie({"actie": "volgende"})[0] == 200
    assert api.media_actie({"actie": "volume", "waarde": 500})[0] == 400
    api.bronnen.tool_fn = lambda *a: TR(False, None, "game-pc niet bereikbaar")
    assert api.media_actie({"actie": "volgende"})[0] == 502


def test_statusmodule_gesprek():
    for i in range(status_mod.MAX_GESPREK + 3):
        status_mod.noteer_gesprek("me" if i % 2 else "ai", f"zin {i}")
    status_mod.noteer_gesprek("hacker", "nee")
    status_mod.noteer_gesprek("me", "   ")
    status_mod.noteer_gesprek("me", "x" * 1000)
    beurten = status_mod.gesprek()
    assert len(beurten) == status_mod.MAX_GESPREK
    assert beurten[-1]["tekst"] == "x" * status_mod.MAX_GESPREK_TEKST
    assert all(b["wie"] in ("me", "ai") for b in beurten)


# ----- server: rollen op de nieuwe endpoints -----

@pytest.fixture
def srv(tmp_path, api):
    hosts = standaard_hosts(8780, "192.168.1.5")
    return DashboardServer(
        api=api,
        authenticator=auth.Authenticator(VIEW, CONTROL, auth.ApparaatRegister(str(tmp_path / "d.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts,
        allowed_origins=standaard_origins(hosts),
        rate_limiter=RateLimiter(1000, 60),
        audit_fn=lambda **v: None,
    )


def _req(srv, method, pad, token, body=None):
    h = {"Host": HOST, "Authorization": f"Bearer {token}"}
    data = b""
    if method != "GET":
        h["Origin"] = ORIGIN
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
    return srv.process(method, pad, h, data, client_ip=IPAD)


@pytest.mark.parametrize("pad", ["/api/audit", "/api/gesprek", "/api/media", "/api/ha/status", "/api/weer",
                                 "/api/vandaag", "/api/pc-status/local", "/api/pc-status/game-pc"])
def test_kijk_mag_tegels_lezen(srv, pad):
    assert _req(srv, "GET", pad, VIEW).status == 200
    assert srv.process("GET", pad, {"Host": HOST}, b"", client_ip=IPAD).status == 401


@pytest.mark.parametrize("pad, body", [
    ("/api/media", {"actie": "volgende"}),
    ("/api/ha/actie", {"id": "light.bed_lamp"}),
    ("/api/nachtmodus", {"stand": "aan"}),
    ("/api/power", {"actie": "slaap"}),
])
def test_kijk_mag_niet_bedienen_bedien_wel(srv, aanroepen, pad, body):
    assert _req(srv, "POST", pad, VIEW, body).status == 403
    assert aanroepen == [] and get_pending() is None
    assert _req(srv, "POST", pad, CONTROL, body).status in (200, 202)


def test_onbekende_pc_404(srv):
    assert _req(srv, "GET", "/api/pc-status/server", VIEW).status == 404


def test_html_in_gesprek_blijft_tekst(srv, api):
    api.gesprek_fn = lambda: [{"id": 1, "wie": "me", "tekst": '<img src=x onerror="alert(1)">'}]
    assert _req(srv, "GET", "/api/gesprek", VIEW).json()[0]["tekst"] == '<img src=x onerror="alert(1)">'
