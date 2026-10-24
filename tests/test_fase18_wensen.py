"""Fase 18 — wensen na de iPad-test (versie 18.5).

Dekt:
  - auditlog-blok: de onderste regel loopt niet meer over de rand
  - media: alleen Spotify, met een volumeschuif (vaste app, via de bewaakte
    poort, herkomst "dashboard"); duidelijke tekst als Spotify niet speelt
  - audio: een app die zijn procesnaam niet prijsgeeft (Store-app) wordt
    toch gevonden via de sessie-ID van Windows
  - slim huis: "+"-tegel en zelf kiezen welke apparaten erop staan;
    bedienen blijft beperkt tot lampen die echt op het dashboard staan
  - de testsuite schrijft niet in het echte auditlog
"""

import json
import re
from pathlib import Path

import pytest

from core.timers import TimerStore
from dashboard import auth
from dashboard import bronnen as mod
from dashboard.api import DashboardAPI
from dashboard.bronnen import Bronnen, valideer_slim_huis
from dashboard.server import STATIC_DIR, DashboardServer, standaard_hosts, standaard_origins
from remote.server import RateLimiter

STATIC = Path(STATIC_DIR)
VIEW = "kijk-token-0123456789abcdef"
CONTROL = "bedien-token-0123456789abcdef"
HOST = "192.168.1.5:8780"
ORIGIN = "https://192.168.1.5:8780"


class TR:
    def __init__(self, ok, data=None, message=""):
        self.ok, self.data, self.message = ok, data, message


STATES = [
    {"entity_id": "light.woonkamer_lamp", "state": "on", "attributes": {"friendly_name": "Woonkamer"}},
    {"entity_id": "light.bed_lamp", "state": "off", "attributes": {"friendly_name": "Bedlamp"}},
    {"entity_id": "light.keuken", "state": "off", "attributes": {"friendly_name": "Keuken"}},
    {"entity_id": "switch.tv_switch", "state": "on", "attributes": {"friendly_name": "TV-stekker"}},
    {"entity_id": "sensor.temperatuur", "state": "21.5", "attributes": {"friendly_name": "Temperatuur", "unit_of_measurement": "°C"}},
    {"entity_id": "lock.voordeur", "state": "locked", "attributes": {"friendly_name": "Voordeur"}},
    {"entity_id": "weather.thuis", "state": "sunny", "attributes": {"temperature": 15}},
]


@pytest.fixture
def aanroepen():
    return []


@pytest.fixture
def bronnen(aanroepen):
    def tool(naam, args, vraag):
        aanroepen.append((naam, args))
        return TR(True, message="ok")

    return Bronnen(
        tool_fn=tool,
        lees_fn=lambda naam, args, vraag: TR(True, {"volume": 40}),
        app_volume_fn=lambda app, volume: aanroepen.append(("app_volume", app, volume)) or TR(True, message="gezet"),
        ha_get_fn=lambda pad: (True, STATES),
        scenes_fn=lambda: {"avondmodus": {}},
        apparaten_fn=lambda: {"light.woonkamer_lamp": ["woonkamerlamp"], "switch.tv_switch": ["tv"]},
        pc_target_fn=lambda: "game-pc",
    )


@pytest.fixture
def api(tmp_path, bronnen):
    return DashboardAPI(timer_store=TimerStore(pad=str(tmp_path / "t.json")),
                        widgets_pad=str(tmp_path / "dashboard.json"),
                        audit_fn=lambda **v: None, bronnen=bronnen)


# ----- auditlog-blok -----

def test_auditlog_blok_loopt_niet_over():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"\.panel\.audit \{ height: 2\d\dpx; display: flex; flex-direction: column; overflow: hidden; \}", css)
    assert "#audit { flex: 1; min-height: 0; overflow: hidden; }" in css


# ----- media: alleen Spotify met een schuif -----

def test_alleen_spotify(bronnen):
    m = bronnen.media()
    assert [a["naam"] for a in m["apps"]] == ["Spotify"]
    assert m["apps"][0] == {"naam": "Spotify", "volume": 40, "actief": True}
    assert m["uitleg"] == "Speelt nu niet op de game-pc"


def test_spotify_volume_zetten(bronnen, aanroepen):
    assert bronnen.app_volume("Spotify", 35) == (True, "gezet")
    assert aanroepen == [("app_volume", "Spotify", 35)]


@pytest.mark.parametrize("app, volume", [("Discord", 30), ("Spotify", 101), ("Spotify", -1), ("Spotify", "30"), ("Spotify", True)])
def test_spotify_volume_ongeldig(bronnen, aanroepen, app, volume):
    assert bronnen.app_volume(app, volume)[0] is False
    assert aanroepen == []


def test_app_volume_via_bewaakte_poort_met_herkomst(monkeypatch):
    import core.ai
    import core.tool_registry

    gezien = {}
    monkeypatch.setattr(core.tool_registry, "run_tool_guarded",
                        lambda tool, args, **kw: gezien.update(kw, tool=tool, args=args) or "ok")
    monkeypatch.setattr(core.ai, "_dispatch_tool", lambda *a: "lokaal")
    mod._std_app_volume("Spotify", 25)
    assert gezien["tool"] == "audio_set_session_volume"
    assert gezien["args"] == {"app_name": "Spotify", "volume": 25}
    assert gezien["approved"] is True and gezien["herkomst"] == "dashboard"


def test_app_volume_via_api(api):
    assert api.media_actie({"actie": "app_volume", "app": "Spotify", "waarde": 50})[0] == 200
    assert api.media_actie({"actie": "app_volume", "app": "Discord", "waarde": 50})[0] == 400
    assert api.media_actie({"actie": "app_volume", "app": "Spotify", "waarde": 500})[0] == 400


def test_volumeschuif_in_de_app():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "schuif.type = 'range'" in app
    assert "actie: 'app_volume'" in app
    # Tijdens het schuiven niet opnieuw tekenen (schuif springt anders terug).
    assert "if (staat.schuift) { return; }" in app


# ----- audio: Store-apps -----

def test_appnaam_uit_sessie_id():
    from actions.audio import _naam_uit_sessie_id

    class Spotify:
        Identifier = r"{0.0.0.00000000}.{x}|\Device\HarddiskVolume3\Program Files\WindowsApps\Spotify\Spotify.exe%b{0}"

    class Systeem:
        Identifier = r"{0.0.0.00000000}.{x}|#%b{A9EF3FD9-4240-455E-A4D5-F2B3301887B2}"

    class Kapot:
        @property
        def Identifier(self):
            raise OSError("geen toegang")

    assert _naam_uit_sessie_id(Spotify()) == "Spotify.exe"
    assert _naam_uit_sessie_id(Systeem()) is None
    assert _naam_uit_sessie_id(Kapot()) is None


# ----- slim huis zelf kiezen -----

@pytest.mark.parametrize("lijst, goed", [
    (["light.keuken", "sensor.temperatuur"], True),
    ([], True),
    (["lock.voordeur"], False),          # dit soort apparaat niet
    (["light.keuken", "light.keuken"], False),
    (["Light.Keuken"], False),
    (["light.keuken; rm"], False),
    ("light.keuken", False),
    ([f"light.l{i}" for i in range(25)], False),
])
def test_valideer_slim_huis(lijst, goed):
    assert (valideer_slim_huis(lijst) is None) is goed


def test_zonder_keuze_blijven_de_aliassen(bronnen):
    ids = [t["id"] for t in bronnen.slim_huis()["tegels"]]
    assert ids == ["light.woonkamer_lamp", "switch.tv_switch", "scene:avondmodus"]


def test_eigen_keuze_met_sensor(bronnen):
    tegels = {t["id"]: t for t in bronnen.slim_huis(["light.keuken", "sensor.temperatuur"])["tegels"]}
    assert list(tegels) == ["light.keuken", "sensor.temperatuur", "scene:avondmodus"]
    assert tegels["sensor.temperatuur"]["label"] == "21.5 °C"
    assert tegels["sensor.temperatuur"]["tikbaar"] is False
    assert tegels["light.keuken"]["naam"] == "Keuken"


def test_bedienen_alleen_voor_lampen_op_het_dashboard(bronnen, aanroepen):
    gekozen = ["light.keuken", "switch.tv_switch"]
    assert bronnen.lamp_wissel("light.keuken", gekozen)[0] is True
    assert bronnen.lamp_wissel("light.bed_lamp", gekozen)[0] is False   # niet gekozen
    assert bronnen.lamp_wissel("switch.tv_switch", gekozen)[0] is False  # geen lamp
    assert [a[1]["entity_id"] for a in aanroepen] == ["light.keuken"]


def test_ha_apparaten_overzicht(bronnen):
    o = bronnen.ha_apparaten(["light.keuken"])
    assert [g["id"] for g in o["gekozen"]] == ["light.keuken"]
    beschikbaar = [a["id"] for a in o["beschikbaar"]]
    assert "light.keuken" not in beschikbaar
    assert "lock.voordeur" not in beschikbaar and "weather.thuis" not in beschikbaar
    assert beschikbaar[:2] == ["light.bed_lamp", "light.woonkamer_lamp"]  # lampen eerst, op naam


def test_opslaan_en_toepassen_via_api(api, tmp_path, aanroepen):
    assert api.ha_apparaten_opslaan({"apparaten": ["light.keuken"]})[0] == 200
    config = json.loads((tmp_path / "dashboard.json").read_text(encoding="utf-8"))
    assert config["slim_huis"] == ["light.keuken"]
    assert [t["id"] for t in api.slim_huis()[1]["tegels"]] == ["light.keuken", "scene:avondmodus"]
    assert api.slim_huis_actie({"id": "light.keuken"})[0] == 200
    assert api.slim_huis_actie({"id": "light.woonkamer_lamp"})[0] == 404
    assert api.ha_apparaten_opslaan({"apparaten": ["lock.voordeur"]})[0] == 400
    # Panelen-instellingen opslaan wist de apparatenlijst niet.
    code, widgets = api.widgets()
    assert widgets["slim_huis"] == ["light.keuken"]
    assert api.widgets_opslaan(widgets)[0] == 200


@pytest.fixture
def srv(tmp_path, api):
    hosts = standaard_hosts(8780, "192.168.1.5")
    return DashboardServer(
        api=api,
        authenticator=auth.Authenticator(VIEW, CONTROL, auth.ApparaatRegister(str(tmp_path / "d.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts, allowed_origins=standaard_origins(hosts),
        rate_limiter=RateLimiter(1000, 60), audit_fn=lambda **v: None,
    )


def test_rollen_op_apparaten_endpoint(srv):
    h = {"Host": HOST, "Authorization": f"Bearer {VIEW}"}
    assert srv.process("GET", "/api/ha/apparaten", h, b"", client_ip="192.168.1.20").status == 200
    body = json.dumps({"apparaten": ["light.keuken"]}).encode()
    hs = dict(h, Origin=ORIGIN, **{"Content-Type": "application/json"})
    assert srv.process("PUT", "/api/ha/apparaten", hs, body, client_ip="192.168.1.20").status == 403
    hs["Authorization"] = f"Bearer {CONTROL}"
    assert srv.process("PUT", "/api/ha/apparaten", hs, body, client_ip="192.168.1.20").status == 200


def test_plus_tegel_en_editor_in_de_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="shEditor"' in html and 'data-filter="light"' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "doos.appendChild(plusTegel());" in app
    assert "api('/api/ha/apparaten', { method: 'PUT'" in app


# ----- de testsuite raakt het echte auditlog niet -----

def test_auditlog_van_de_tests_staat_niet_in_het_project():
    import core.audit as audit

    project = Path(__file__).resolve().parent.parent
    assert project not in Path(audit.AUDIT_FILE).resolve().parents
