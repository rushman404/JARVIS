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
    assert bronnen.lamp_wissel("sensor.temperatuur", gekozen + ["sensor.temperatuur"])[0] is False  # alleen status
    assert [a[1]["entity_id"] for a in aanroepen] == ["light.keuken"]


def test_schakelaar_en_wake_on_lan_knop(bronnen, aanroepen):
    gekozen = ["switch.tv_switch", "button.game_pc_wol"]
    assert bronnen.lamp_wissel("switch.tv_switch", gekozen)[0] is True
    assert aanroepen[-1] == ("control_home_assistant",
                             {"domain": "switch", "service": "turn_off", "entity_id": "switch.tv_switch"})
    assert bronnen.lamp_wissel("button.game_pc_wol", gekozen)[0] is True
    assert aanroepen[-1] == ("control_home_assistant",
                             {"domain": "button", "service": "press", "entity_id": "button.game_pc_wol"})
    # Niet gekozen: geweigerd.
    assert bronnen.lamp_wissel("button.ander", gekozen)[0] is False


def test_knop_tegel_en_kiesbaar(bronnen):
    tegels = {t["id"]: t for t in bronnen.slim_huis(["button.game_pc_wol"])["tegels"]}
    assert tegels["button.game_pc_wol"]["tikbaar"] is True
    assert tegels["button.game_pc_wol"]["label"] == "DRUK"
    assert valideer_slim_huis(["button.game_pc_wol"]) is None


def test_ha_laag_kent_button_alleen_met_press():
    from core.ha_registry import _DOMAIN_SERVICE_DEFAULTS, _domain_supports_service
    from core.home_assistant import SUPPORTED_DOMAINS
    from core.tool_registry import get_tool_risk

    assert "button" in SUPPORTED_DOMAINS
    assert _DOMAIN_SERVICE_DEFAULTS["button"] == {"press"}
    knop = {"domain": "button", "entity_id": "button.game_pc_wol", "capabilities": []}
    assert _domain_supports_service(knop, "button", "press")[0] is True
    assert _domain_supports_service(knop, "button", "turn_on")[0] is False
    # Een knop indrukken vraagt (net als een schakelaar) om goedkeuring.
    assert get_tool_risk("control_home_assistant", {"domain": "button"}) == "medium"
    assert get_tool_risk("control_home_assistant", {"domain": "light"}) == "low"


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


# ----- Windows-toast met app-ID -----

def test_toast_gebruikt_een_app_id(monkeypatch):
    import subprocess

    import voice.notify as notify

    gezien = {}

    class Klaar:
        returncode = 0
        stderr = b""

    def nep_run(args, env=None, **kw):
        gezien["script"] = args[-1]
        gezien["env"] = env
        return Klaar()

    monkeypatch.setattr(notify, "windows_beschikbaar", lambda: True)
    monkeypatch.setattr(subprocess, "run", nep_run)
    assert notify.toon_toast("JARVIS", "Uw timer is afgegaan.") is True
    # Zonder app-ID faalde dit met 0x80070490 ("Kan element niet vinden").
    assert "CreateToastNotifier($env:JARVIS_TOAST_APP_ID)" in gezien["script"]
    assert gezien["env"]["JARVIS_TOAST_APP_ID"].endswith(r"WindowsPowerShell\v1.0\powershell.exe")
    # De tekst gaat via de omgeving, nooit in het script.
    assert "Uw timer" not in gezien["script"]


# ----- audio: alle uitvoerapparaten (Sonar Aux, headset, ...) -----

class _Ctl:
    def __init__(self, naam):
        self.naam = naam

    def QueryInterface(self, _iface):
        return self


class _Lijst:
    def __init__(self, namen):
        self.namen = namen

    def GetCount(self):
        return len(self.namen)

    def GetSession(self, i):
        return _Ctl(self.namen[i])


class _Apparaat:
    def __init__(self, ident, naam, sessies):
        self.id = ident
        self.FriendlyName = naam
        self._sessies = sessies

    @property
    def AudioSessionManager(self):
        apparaat = self

        class _Mgr:
            def GetSessionEnumerator(self):
                return _Lijst(apparaat._sessies)

        return _Mgr()


def test_sessies_van_alle_apparaten_standaard_eerst(monkeypatch):
    import sys
    import types

    from actions import audio

    # In de tests is pycaw een nepmodule; bied de twee gebruikte delen aan.
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", types.SimpleNamespace(IAudioSessionControl2=object))
    monkeypatch.setitem(sys.modules, "pycaw.utils", types.SimpleNamespace(AudioSession=lambda ctl2: ctl2.naam))

    class _Utils:
        @staticmethod
        def GetAllDevices(flow, state):
            return [_Apparaat("aux", "Sonar - Aux", ["Spotify.exe"]),
                    _Apparaat("gaming", "Sonar - Gaming", ["Discord.exe"])]

        @staticmethod
        def GetSpeakers():
            class _S:
                def GetId(self):
                    return "gaming"
            return _S()

    class _Enum:
        class eRender:
            value = 0

    class _State:
        class ACTIVE:
            value = 1

    gevonden = audio._sessies_van_alle_apparaten(_Utils, _Enum, _State)
    assert gevonden == [("Discord.exe", "Sonar - Gaming"), ("Spotify.exe", "Sonar - Aux")]


def test_terugval_als_apparaten_niet_lukken():
    from actions import audio

    class _Utils:
        @staticmethod
        def GetAllDevices(flow, state):
            raise OSError("COM weg")

        @staticmethod
        def GetAllSessions():
            return ["oude-manier"]

    class _X:
        class eRender:
            value = 0

        class ACTIVE:
            value = 1

    assert audio._sessies_van_alle_apparaten(_Utils, _X, _X) == [("oude-manier", None)]


def test_volume_zetten_op_alle_sessies_van_een_app(monkeypatch):
    from actions import audio

    gezet = []

    class _Control:
        def __init__(self, naam):
            self.naam = naam

        def SetMasterVolume(self, waarde, _ctx):
            gezet.append((self.naam, round(waarde, 2)))

    sessies = [
        {"name": "Spotify.exe", "control": _Control("aux")},
        {"name": "Discord.exe", "control": _Control("chat")},
        {"name": "Spotify.exe", "control": _Control("headset")},
    ]
    monkeypatch.setattr(audio, "_build_sessions", lambda: sessies)
    monkeypatch.setattr(audio, "run_on_com_thread", lambda fn: fn())
    r = audio.set_session_volume("Spotify", 30)
    assert r.ok
    assert gezet == [("aux", 0.3), ("headset", 0.3)]


# ----- timers: precies op tijd melden -----

class _Klok:
    def __init__(self, nu=1_000_000.0):
        self.nu = nu

    def __call__(self):
        return self.nu


def _engine(tmp_path, klok, store, geleverd):
    from core.proactive import ProactiveEngine

    return ProactiveEngine(store=store, rules_pad=str(tmp_path / "geen.json"), tick_seconden=30,
                           time_fn=klok, lever_fn=lambda m: geleverd.append(m.tekst),
                           in_gesprek_fn=lambda: False)


def test_engine_slaapt_nooit_voorbij_een_timer(tmp_path):
    klok = _Klok()
    store = TimerStore(pad=str(tmp_path / "t.json"), clock=klok)
    engine = _engine(tmp_path, klok, store, [])
    assert engine.wachttijd() == 30                     # geen timers: gewone tick
    store.zet("thee", 20)
    assert 20 <= engine.wachttijd() <= 20.1             # eerder: tot 30 s te laat
    store.zet("ei", 5)
    assert 5 <= engine.wachttijd() <= 5.1
    store.zet("lang", 3600)
    assert engine.wachttijd() <= 5.1


def test_nieuwe_timer_wekt_de_engine(tmp_path):
    klok = _Klok()
    store = TimerStore(pad=str(tmp_path / "t.json"), clock=klok)
    engine = _engine(tmp_path, klok, store, [])
    engine._wek.clear()
    store.zet("thee", 20)
    assert engine._wek.is_set()


def test_tekst_op_tijd_en_te_laat(tmp_path):
    klok = _Klok()
    store = TimerStore(pad=str(tmp_path / "t.json"), clock=klok)
    geleverd = []
    engine = _engine(tmp_path, klok, store, geleverd)
    store.zet("thee", 20)
    klok.nu += 20.2
    engine.tick()
    assert len(geleverd) == 1
    assert geleverd[0].startswith("Sir, het is ") and geleverd[0].endswith(": uw timer 'thee' is afgelopen.")
    store.zet("ei", 10)
    klok.nu += 10 + 600   # JARVIS stond uit: 10 minuten te laat
    engine.tick()
    assert geleverd[-1].startswith("Sir, uw timer 'ei' is om ") and geleverd[-1].endswith(" afgegaan.")


def test_echte_thread_meldt_binnen_een_halve_seconde(tmp_path):
    import time

    from core.proactive import ProactiveEngine

    store = TimerStore(pad=str(tmp_path / "t.json"))
    geleverd = []
    start = time.time()
    engine = ProactiveEngine(store=store, rules_pad=str(tmp_path / "geen.json"), tick_seconden=30,
                             lever_fn=lambda m: geleverd.append(time.time() - start),
                             in_gesprek_fn=lambda: False)
    engine.start()
    try:
        time.sleep(0.3)   # de engine slaapt nu 30 s
        store.zet("kort", 1)
        eind = time.time() + 5
        while not geleverd and time.time() < eind:
            time.sleep(0.05)
    finally:
        engine.stop()
    assert geleverd, "de timer werd niet gemeld"
    assert geleverd[0] < 1.3 + 0.5


# ----- slim huis: tv (mediaspeler) aan/uit -----

@pytest.mark.parametrize("staat, service", [
    ("playing", "turn_off"), ("paused", "turn_off"), ("idle", "turn_off"), ("on", "turn_off"),
    ("off", "turn_on"), ("standby", "turn_on"),
])
def test_tv_aan_en_uit(aanroepen, staat, service):
    b = Bronnen(
        tool_fn=lambda naam, args, vraag: aanroepen.append((naam, args)) or TR(True),
        ha_get_fn=lambda pad: (True, [{"entity_id": "media_player.tv", "state": staat, "attributes": {}}]),
        apparaten_fn=lambda: {"media_player.tv": ["tv"]},
        scenes_fn=lambda: {},
    )
    assert b.slim_huis()["tegels"][0]["tikbaar"] is True
    assert b.lamp_wissel("media_player.tv")[0] is True
    assert aanroepen[-1] == ("control_home_assistant",
                             {"domain": "media_player", "service": service, "entity_id": "media_player.tv"})


def test_tv_bedienen_vraagt_goedkeuring():
    """Herzien in Fase 21 (wens 2026-10-26): de tv aan/uit/volume is laag
    risico, net als een lamp. Stekkers blijven medium."""
    from core.tool_registry import get_tool_risk

    assert get_tool_risk("control_home_assistant", {"domain": "media_player"}) == "low"
    assert get_tool_risk("control_home_assistant", {"domain": "switch"}) == "medium"
