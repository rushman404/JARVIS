"""Fase 18 — fixes na de eerste test op de iPad (iPad Air 1e gen, iOS 12).

Dekt:
  - de orb bleef op "spreekt" staan: na het spreken gaat de fase terug
    (naar "luistert" in een gesprek, anders naar "rust")
  - Game-PC-meters waren leeg: de client gaf de telemetrie als None door.
    Getest door de hele echte keten (agent-server -> client over TLS ->
    remote/tools.py -> dashboard-meters), niet met een nagebootste vorm.
  - het dashboard vraagt de game-pc niet vaker dan de agent toestaat
  - iOS 12: elke flexbox met `gap` heeft een vervanger via marges
    (.geen-flex-gap), icoon voor het beginscherm, netwerk-eerst service
    worker, geen doorschijnende statusbalk
"""

import importlib.util
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

import status as status_mod
from dashboard import bronnen as bronnen_mod
from dashboard.api import DashboardAPI
from dashboard.bronnen import Bronnen
from dashboard.server import STATIC_DIR

STATIC = Path(STATIC_DIR)
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(autouse=True)
def schone_status():
    status_mod.reset()
    yield
    status_mod.reset()


# ----- orb: "spreekt" vervalt na het spreken -----

@pytest.mark.parametrize("voor, na", [
    ("rust", "rust"),        # melding of "JARVIS is online" buiten een gesprek
    ("luistert", "luistert"),
    ("denkt", "rust"),       # antwoord op een vraag; listen() zet daarna zelf "luistert"
])
def test_fase_na_het_spreken(voor, na):
    {"rust": status_mod.wacht, "luistert": status_mod.luistert, "denkt": status_mod.omzetten}[voor]()
    status_mod.spreekt("Hallo, Sir.")
    status_mod.spreekt("Tweede zin.")
    assert status_mod.fase() == "spreekt"
    status_mod.klaar_met_spreken()
    assert status_mod.fase() == na


def test_klaar_met_spreken_doet_niets_buiten_spreken():
    status_mod.luistert()
    status_mod.klaar_met_spreken()
    assert status_mod.fase() == "luistert"


def test_speak_zet_de_fase_terug(monkeypatch):
    speak = pytest.importorskip("voice.speak")
    for naam in ("_say", "_mute_microphone", "_unmute_microphone", "_duck", "_herstel_volume"):
        monkeypatch.setattr(speak, naam, lambda *a, **k: None)
    status_mod.wacht()
    speak.speak("Uw timer is afgegaan.")
    assert status_mod.fase() == "rust"


def test_speak_zet_de_fase_ook_terug_bij_een_fout(monkeypatch):
    speak = pytest.importorskip("voice.speak")
    for naam in ("_mute_microphone", "_unmute_microphone", "_duck", "_herstel_volume"):
        monkeypatch.setattr(speak, naam, lambda *a, **k: None)

    def kapot(_tekst):
        raise RuntimeError("geluidskaart weg")

    monkeypatch.setattr(speak, "_say", kapot)
    with pytest.raises(RuntimeError):
        speak.speak("test")
    assert status_mod.fase() == "rust"


def test_dashboard_toont_spreekt_alleen_als_hij_echt_praat(tmp_path):
    from core.timers import TimerStore

    api = DashboardAPI(timer_store=TimerStore(pad=str(tmp_path / "t.json")),
                       fase_fn=lambda: "spreekt", spreekt_fn=lambda: False, pc_target_fn=lambda: "local")
    assert api.status()[1]["fase"] == "rust"
    api.spreekt_fn = lambda: True
    assert api.status()[1]["fase"] == "spreekt"


# ----- Game-PC-meters: de echte keten -----

def test_client_geeft_telemetrie_door_zonder_resultaatveld(certs):
    from remote.client import RemoteClient

    client = RemoteClient(host="127.0.0.1", port=1, token="x" * 20, ca_file=str(certs.ca_cert), enabled=True)
    r = client._parse_antwoord(200, b'{"ok": true, "telemetrie": {"cpu": {"ok": true, "gebruik_percent": 12}}}', 1)
    assert r.ok
    assert r.resultaat["telemetrie"]["cpu"]["gebruik_percent"] == 12
    # Opdrachten (met "resultaat") blijven zoals ze waren.
    r = client._parse_antwoord(200, b'{"ok": true, "resultaat": "gedaan"}', 1)
    assert r.resultaat == "gedaan"


@pytest.fixture(scope="module")
def certs():
    pytest.importorskip("cryptography")
    spec = importlib.util.spec_from_file_location("make_dashboard_cert_fix", SCRIPTS / "make_dashboard_cert.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_dashboard_cert_fix"] = module
    spec.loader.exec_module(module)
    map_ = tempfile.mkdtemp(prefix="jarvis_fix_cert_")
    try:
        yield module.maak_certificaten(map_)
    finally:
        shutil.rmtree(map_, ignore_errors=True)


def test_game_pc_meters_door_de_hele_echte_keten(certs, monkeypatch):
    import remote.server as remote_server
    import remote.telemetry as telemetrie
    from remote import tools as remote_tools
    from remote.client import RemoteClient

    nep = {
        "ok": True,
        "cpu": {"ok": True, "gebruik_percent": 61.2},
        "ram": {"ok": True, "percentage": 88.0},
        "gpu": {"ok": True, "gpus": [{"temperatuur_c": 78}]},
    }
    monkeypatch.setattr(telemetrie, "collect_telemetry", lambda *a, **k: nep)
    token = "remote-token-0123456789abcdef"
    httpd = remote_server.create_server(
        host="127.0.0.1", port=0, token=token,
        cert_file=str(certs.server_cert), key_file=str(certs.server_key),
        rate_limiter=remote_server.RateLimiter(max_requests=0), audit=False,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = RemoteClient(host="127.0.0.1", port=httpd.server_address[1], token=token,
                              ca_file=str(certs.ca_cert), enabled=True)
        resultaat = remote_tools._telemetrie_resultaat(client)
        assert resultaat.ok
        assert resultaat.data["telemetrie"]["cpu"]["gebruik_percent"] == 61.2

        b = Bronnen(telemetrie_game_pc_fn=lambda: resultaat)
        pc = b.pc_status("game-pc")
        meters = {m["naam"]: m for m in pc["meters"]}
        assert pc["beschikbaar"] is True
        assert meters["Processor"]["waarde"] == 61
        assert meters["Geheugen"]["waarde"] == 88 and meters["Geheugen"]["hoog"]
        assert meters["GPU-temperatuur"]["waarde"] == 78 and meters["GPU-temperatuur"]["hoog"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_dashboard_blijft_ruim_onder_de_limiet_van_de_agent():
    # 2 media-verzoeken per TTL_MEDIA + 1 telemetrie per TTL_PC, per minuut.
    per_minuut = 2 * 60 / bronnen_mod.TTL_MEDIA + 60 / bronnen_mod.TTL_PC
    assert per_minuut <= 20, "het dashboard zou de 60/min van de game-pc-agent te veel gebruiken"


# ----- iOS 12 (iPad Air 1e generatie) -----

CSS = (STATIC / "styles.css").read_text(encoding="utf-8")


def _flex_gap_selectors():
    zonder_commentaar = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    selectors = set()
    for selector, inhoud in re.findall(r"([^{}]+)\{([^{}]*)\}", zonder_commentaar):
        if "display: flex" in inhoud and re.search(r"(?<![-\w])gap\s*:", inhoud):
            for s in selector.split(","):
                selectors.add(s.strip())
    return selectors


def test_elke_flexbox_met_gap_heeft_een_ios12_vervanger():
    selectors = _flex_gap_selectors()
    assert len(selectors) > 15
    ontbreekt = [s for s in sorted(selectors) if f".geen-flex-gap {s} >" not in CSS]
    assert ontbreekt == [], f"geen marge-vervanger voor: {ontbreekt}"


def test_app_herkent_ontbrekende_flex_gap():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function controleerFlexGap" in app
    assert "controleerFlexGap();" in app
    assert "geen-flex-gap" in app


def test_icoon_voor_het_beginscherm():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"' in html
    for naam in ("apple-touch-icon.png", "apple-touch-icon-precomposed.png"):
        data = (STATIC / naam).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_geen_doorschijnende_statusbalk():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'name="apple-mobile-web-app-status-bar-style" content="black"' in html


def test_service_worker_eerst_netwerk():
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    fetch_deel = sw[sw.index("addEventListener('fetch'"):]
    # Eerst het netwerk; de cache pas in de catch (offline).
    assert fetch_deel.index("fetch(e.request)") < fetch_deel.index("caches.match(e.request)")
    assert ".catch(function ()" in fetch_deel


def test_stage_vult_een_4_3_ipad():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "stage.style.height = hoogte + 'px'" in app
    # 1024x768 (iPad Air 1): breedte 1180 -> hoogte ~885, boven het minimum.
    assert 768 / (1024 / 1180) >= 760


# ----- een oude sessiecookie blokkeert het apparaat niet -----

def _server(tmp_path):
    from core.timers import TimerStore
    from dashboard import auth
    from dashboard.server import DashboardServer, standaard_hosts, standaard_origins
    from remote.server import RateLimiter

    hosts = standaard_hosts(8780, "192.168.1.5")
    return DashboardServer(
        api=DashboardAPI(timer_store=TimerStore(pad=str(tmp_path / "t.json")), audit_fn=lambda **v: None),
        authenticator=auth.Authenticator("k" * 20, "b" * 20, auth.ApparaatRegister(str(tmp_path / "d.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts,
        allowed_origins=standaard_origins(hosts),
        rate_limiter=RateLimiter(1000, 60),
        audit_fn=lambda **v: None,
    )


def test_oude_cookie_telt_niet_voor_de_blokkade(tmp_path):
    from dashboard.auth import COOKIE_NAAM

    srv = _server(tmp_path)
    oud = {"Host": "192.168.1.5:8780", "Cookie": f"{COOKIE_NAAM}=verlopen-token"}
    # De PWA opent met veel verzoeken tegelijk, allemaal met de oude cookie.
    for pad in ["/api/sessie"] + ["/api/status", "/api/events", "/api/timers", "/api/media"] * 3:
        a = srv.process("GET", pad, oud, b"", client_ip="192.168.1.20")
        assert a.status in (200, 401)
        assert "Max-Age=0" in a.header("Set-Cookie")
    assert srv._lockout.is_blocked("192.168.1.20") is False
    # Koppelen blijft gewoon mogelijk.
    code = srv.koppelcode.nieuw()
    h = {"Host": "192.168.1.5:8780", "Content-Type": "application/json"}
    assert srv.process("POST", "/api/pair", h, ('{"code": "%s", "rol": "kijk"}' % code).encode(),
                       client_ip="192.168.1.20").status == 201


def test_fout_bearer_token_telt_wel_voor_de_blokkade(tmp_path):
    srv = _server(tmp_path)
    h = {"Host": "192.168.1.5:8780", "Authorization": "Bearer geraden"}
    for _ in range(5):
        srv.process("GET", "/api/status", h, b"", client_ip="192.168.1.20")
    assert srv._lockout.is_blocked("192.168.1.20") is True


# ----- versie: een oude app op het beginscherm ververst zichzelf -----

def test_versie_is_overal_gelijk():
    from dashboard.api import API_VERSIE

    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert f"var VERSIE = '{API_VERSIE}';" in app
    for html in ("index.html", "koppel.html"):
        tekst = (STATIC / html).read_text(encoding="utf-8")
        refs = re.findall(r'(?:href|src)="(/(?:styles\.css|app\.js|koppel\.js)[^"]*)"', tekst)
        assert refs, html
        assert all(r.endswith(f"?v={API_VERSIE}") for r in refs), (html, refs)
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert f"var CACHE = 'jarvis-shell-{API_VERSIE}';" in sw
    assert f"'/app.js?v={API_VERSIE}'" in sw


def test_server_serveert_bestanden_met_versie_in_het_adres(tmp_path):
    srv = _server(tmp_path)
    h = {"Host": "192.168.1.5:8780"}
    for pad in ("/app.js?v=18.2", "/styles.css?v=oud", "/koppel.js?v=1"):
        a = srv.process("GET", pad, h, b"", client_ip="192.168.1.20")
        assert a.status == 200, pad


def test_app_ververst_zichzelf_bij_een_andere_versie():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function controleerVersie" in app and "controleerVersie();" in app
    assert "getRegistrations" in app and "unregister()" in app
    assert "caches.delete" in app and "location.reload()" in app
    # Hooguit één keer per sessie herladen (geen lus).
    assert "sessionStorage.getItem(sleutel)" in app
    # Ook bij terugkeren naar de app (iOS herlaadt die dan niet).
    assert "visibilitychange" in app


# ----- media-knoppen gingen naar de laptop i.p.v. de game-pc -----

@pytest.mark.parametrize("tool, actie", [
    ("media_play_pause", "play_pause"),
    ("media_next", "next"),
    ("media_previous", "previous"),
    ("media_stop", "stop"),
    ("media_mute", "mute"),
    ("volume_up", "volume_up"),
    ("volume_down", "volume_down"),
])
def test_media_tools_gaan_naar_de_game_pc(monkeypatch, tool, actie):
    import core.ai as ai
    from core import pc_target

    verstuurd = []
    monkeypatch.setattr(pc_target, "get_pc_target", lambda: pc_target.GAME_PC)
    monkeypatch.setattr(ai.remote_tools, "execute_remote_tool",
                        lambda naam, args, vraag: verstuurd.append((naam, args)) or "ok")
    ai._dispatch_tool(tool, {}, "dashboard: media")
    assert verstuurd == [("game_pc_media", {"action": actie})]


def test_media_tools_blijven_lokaal_als_het_doel_lokaal_is(monkeypatch):
    import core.ai as ai
    from core import pc_target

    verstuurd = []
    monkeypatch.setattr(pc_target, "get_pc_target", lambda: pc_target.LOCAL)
    monkeypatch.setattr(ai.remote_tools, "execute_remote_tool",
                        lambda naam, args, vraag: verstuurd.append(naam) or "ok")
    monkeypatch.setattr(ai, "media_play_pause_tool", lambda: "lokaal gepauzeerd")
    assert ai._dispatch_tool("media_play_pause", {}, "pauzeer") == "lokaal gepauzeerd"
    assert verstuurd == []


def test_andere_twins_houden_hun_argumenten():
    from core import pc_target

    assert pc_target.remote_aanroep("set_volume", {"percent": 30}) == ("game_pc_set_volume", {"percent": 30})
    assert pc_target.remote_aanroep("bestaat_niet", {}) is None
    # Elke media-actie bestaat ook echt op de game-pc-agent.
    from remote.tools import MEDIA_ACTIES

    assert set(pc_target.MEDIA_NAAR_REMOTE.values()) <= set(MEDIA_ACTIES)


# ----- koppelcode invoeren op de iPad -----

def test_koppelscherm_heeft_een_eigen_cijfertoetsenbord():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    cijfers = re.findall(r'data-cijfer="(\w+)"', html)
    assert sorted(cijfers) == sorted(list("0123456789") + ["wis", "terug"])
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function toets(cijfer)" in app
    # Op een touchscreen geen systeemtoetsenbord (verschoof de pagina op iOS 12).
    assert "setAttribute('readonly', 'readonly')" in app


def test_invoervelden_zijn_niet_geblokkeerd_door_user_select():
    css = CSS + (STATIC / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"input, textarea \{ -webkit-user-select: text; user-select: text; \}", css)


def test_schalen_wacht_tijdens_typen():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "actief.tagName === 'INPUT' && window.innerWidth === laatsteBreedte" in app


# ----- beginscherm-app zonder verbinding (certificaat niet vertrouwd) -----

def test_geen_verbinding_venster_bestaat_en_wordt_gebruikt():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="geenVerbinding"' in html and "certificaatvertrouwen" in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # Netwerkfout (geen antwoord) -> venster; elk antwoord -> weg.
    assert ".catch(netwerkFout)" in app
    assert app.count("netwerkOk();") >= 3
    assert "staat.mislukt >= (staat.rol ? 3 : 1)" in app


def test_certificaat_past_bij_het_lan_ip(certs):
    from dashboard.server import controleer_certificaat

    pad = str(certs.server_cert)
    # Het testcertificaat is gemaakt voor 127.0.0.1 en localhost.
    assert controleer_certificaat(pad, "127.0.0.1") == []
    w = controleer_certificaat(pad, "192.168.1.77")
    assert len(w) == 1 and "192.168.1.77" in w[0] and "--force --ip 192.168.1.77" in w[0]


def test_certificaat_verlopen_of_bijna(certs):
    import datetime as dt

    from dashboard.server import controleer_certificaat

    pad = str(certs.server_cert)
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=900)
    assert any("verlopen" in w for w in controleer_certificaat(pad, "127.0.0.1", nu=later))
    bijna = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=810)
    assert any("verloopt over" in w for w in controleer_certificaat(pad, "127.0.0.1", nu=bijna))


def test_onleesbaar_certificaat(tmp_path):
    pytest.importorskip("cryptography")
    from dashboard.server import controleer_certificaat

    kapot = tmp_path / "kapot.pem"
    kapot.write_text("geen certificaat", encoding="utf-8")
    assert controleer_certificaat(str(kapot), "1.2.3.4") == ["Het certificaat kon niet gelezen worden."]


# ----- dode live-verbindingen houden geen plekken meer bezet -----

def test_nieuwe_stream_van_hetzelfde_apparaat_sluit_de_oudste():
    from dashboard.events import MAX_PER_IP, EventBus

    bus = EventBus()
    oud = [bus.abonneer(ip="192.168.1.20") for _ in range(MAX_PER_IP)]
    nieuw = bus.abonneer(ip="192.168.1.20")
    assert nieuw is not None
    assert oud[0].overgelopen is True
    assert oud[0].wachtrij.get_nowait() is None  # de handler stopt meteen
    assert bus.aantal() == MAX_PER_IP
    # Een ander apparaat merkt er niets van.
    ander = bus.abonneer(ip="192.168.1.21")
    assert ander is not None and not ander.overgelopen


def test_veel_keer_openen_loopt_nooit_vol():
    from dashboard.events import MAX_PER_IP, EventBus

    bus = EventBus()
    for _ in range(50):  # app 50 keer geopend, oude verbindingen half open
        assert bus.abonneer(ip="192.168.1.20") is not None
    assert bus.aantal() == MAX_PER_IP


def test_stream_heeft_een_maximale_duur_en_keepalive():
    import inspect

    from dashboard import server as server_mod
    from dashboard.events import MAX_STREAM_SECONDEN

    assert 60 <= MAX_STREAM_SECONDEN <= 600
    bron = inspect.getsource(server_mod._DashboardHandler._stream)
    assert "zet_keepalive(self.connection)" in bron
    assert "MAX_STREAM_SECONDEN" in bron


def test_keepalive_op_een_echte_socket():
    import socket

    from dashboard.server import zet_keepalive

    s = socket.socket()
    try:
        zet_keepalive(s)
        assert s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
    finally:
        s.close()
    zet_keepalive(object())  # gooit nooit een fout
