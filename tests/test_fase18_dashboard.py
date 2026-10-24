"""Tests voor Fase 18 M2: de dashboard-server over echte TLS-sockets.

Dekt:
  - scripts/make_dashboard_cert.py: eigen CA + servercertificaat (SAN,
    serverAuth, max. 825 dagen) + .mobileconfig met alleen de CA
  - create_server weigert te starten zonder tokens of certificaat
  - HTTPS met verificatie tegen de eigen CA; security-headers op de lijn
  - SSE: een abonnee krijgt meteen de status en daarna wijzigingen
  - de Waarnemer publiceert alleen bij een wijziging

Bewust ``tempfile.mkdtemp`` in plaats van ``tmp_path`` (Windows-kwestie met
de ``pytest-current``-koppeling, zie test_fase15_remote_cert.py).
"""

import http.client
import importlib.util
import json
import plistlib
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from core.confirmation import clear_pending, set_pending
from core.timers import TimerStore
from dashboard import auth
from dashboard.api import DashboardAPI
from dashboard.events import EventBus, Waarnemer
from dashboard.server import (
    DashboardServer,
    create_server,
    standaard_hosts,
    standaard_origins,
)

cryptography = pytest.importorskip("cryptography")
from cryptography import x509  # noqa: E402
from cryptography.x509.oid import ExtendedKeyUsageOID  # noqa: E402

VIEW = "kijk-token-0123456789abcdef"
CONTROL = "bedien-token-0123456789abcdef"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(scope="module")
def certscript():
    spec = importlib.util.spec_from_file_location("make_dashboard_cert", SCRIPTS / "make_dashboard_cert.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_dashboard_cert"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def certs(certscript):
    map_ = tempfile.mkdtemp(prefix="jarvis_dash_cert_")
    try:
        yield certscript.maak_certificaten(map_, ips=["192.168.1.5"]), map_
    finally:
        shutil.rmtree(map_, ignore_errors=True)


@pytest.fixture
def werkmap():
    map_ = tempfile.mkdtemp(prefix="jarvis_dash_")
    try:
        yield Path(map_)
    finally:
        shutil.rmtree(map_, ignore_errors=True)


@pytest.fixture(autouse=True)
def schoon():
    clear_pending()
    yield
    clear_pending()


# ----- certificaatscript -----

def test_servercertificaat_voldoet_aan_de_eisen_van_ios(certs):
    r, _ = certs
    keten = x509.load_pem_x509_certificates(r.server_cert.read_bytes())
    server, ca = keten[0], keten[1]

    san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    ips = [str(i) for i in san.get_values_for_type(x509.IPAddress)]
    assert "192.168.1.5" in ips and "127.0.0.1" in ips

    eku = server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert server.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    assert server.not_valid_after_utc - server.not_valid_before_utc <= timedelta(days=826)
    assert server.issuer == ca.subject

    bc = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True and bc.path_length == 0


def test_profiel_bevat_alleen_het_ca_certificaat(certs):
    r, _ = certs
    profiel = plistlib.loads(r.profiel.read_bytes())
    assert profiel["PayloadType"] == "Configuration"
    inhoud = profiel["PayloadContent"]
    assert len(inhoud) == 1
    assert inhoud[0]["PayloadType"] == "com.apple.security.root"
    ca = x509.load_der_x509_certificate(inhoud[0]["PayloadContent"])
    assert ca.subject.rfc4514_string().endswith("JARVIS Dashboard CA")
    assert b"PRIVATE KEY" not in r.profiel.read_bytes()


def test_opnieuw_maken_hergebruikt_de_ca(certscript, certs):
    r, map_ = certs
    with pytest.raises(certscript.BestandBestaat):
        certscript.maak_certificaten(map_, ips=["192.168.1.6"])
    tweede = certscript.maak_certificaten(map_, ips=["192.168.1.6"], force=True)
    assert tweede.ca_hergebruikt is True
    assert tweede.vingerafdruk_ca == r.vingerafdruk_ca
    # Terugzetten voor de andere tests in deze module.
    certscript.maak_certificaten(map_, ips=["192.168.1.5"], force=True)


@pytest.mark.parametrize("ip", ["999.1.1.1", "abc"])
def test_ongeldig_ip_wordt_geweigerd(certscript, ip):
    map_ = tempfile.mkdtemp(prefix="jarvis_dash_cert_")
    try:
        with pytest.raises(certscript.ValidatieFout):
            certscript.maak_certificaten(map_, ips=[ip])
    finally:
        shutil.rmtree(map_, ignore_errors=True)


# ----- server starten -----

def _dashboard(werkmap, poort, view=VIEW, control=CONTROL):
    api = DashboardAPI(
        timer_store=TimerStore(pad=str(werkmap / "timers.json")),
        widgets_pad=str(werkmap / "dashboard.json"),
        spreekt_fn=lambda: False,
        fase_fn=lambda: "rust",
        pc_target_fn=lambda: "local",
        audit_fn=lambda **v: None,
    )
    hosts = standaard_hosts(poort)
    return DashboardServer(
        api=api,
        authenticator=auth.Authenticator(view, control, auth.ApparaatRegister(str(werkmap / "dev.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts,
        allowed_origins=standaard_origins(hosts),
        static_dir=str(werkmap),
        audit_fn=lambda **v: None,
    )


def _vrije_poort():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    poort = s.getsockname()[1]
    s.close()
    return poort


@pytest.mark.parametrize("view, control, cert", [
    ("", CONTROL, True),
    (VIEW, "", True),
    ("kort", CONTROL, True),
    (VIEW, VIEW, True),
    (VIEW, CONTROL, False),
])
def test_server_start_niet_zonder_beveiliging(werkmap, certs, view, control, cert):
    r, _ = certs
    dashboard = _dashboard(werkmap, 8780, view=view, control=control)
    with pytest.raises(RuntimeError):
        create_server(
            dashboard, host="127.0.0.1", port=0,
            cert_file=str(r.server_cert) if cert else "",
            key_file=str(r.server_key) if cert else "",
        )


@pytest.fixture
def draaiend(werkmap, certs):
    r, _ = certs
    poort = _vrije_poort()
    dashboard = _dashboard(werkmap, poort)
    httpd = create_server(dashboard, host="127.0.0.1", port=poort,
                          cert_file=str(r.server_cert), key_file=str(r.server_key))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    context = ssl.create_default_context(cafile=str(r.ca_cert))
    try:
        yield dashboard, poort, context
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _verbind(poort, context):
    return http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)


def test_https_met_verificatie_tegen_de_eigen_ca(draaiend):
    _, poort, context = draaiend
    c = _verbind(poort, context)
    c.request("GET", "/api/status", headers={"Authorization": f"Bearer {VIEW}"})
    a = c.getresponse()
    data = json.loads(a.read())
    assert a.status == 200
    assert data["fase"] == "rust"
    assert "unsafe-inline" not in a.getheader("Content-Security-Policy")
    assert a.getheader("Referrer-Policy") == "no-referrer"
    assert a.getheader("X-Content-Type-Options") == "nosniff"
    assert a.getheader("Cache-Control") == "no-store"
    assert a.getheader("Access-Control-Allow-Origin") is None
    c.close()


def test_zonder_vertrouwde_ca_mislukt_de_verbinding(draaiend):
    _, poort, _ = draaiend
    c = http.client.HTTPSConnection("127.0.0.1", poort, context=ssl.create_default_context(), timeout=5)
    with pytest.raises(ssl.SSLError):
        c.request("GET", "/api/health")
    c.close()


def test_plat_http_krijgt_geen_antwoord(draaiend):
    _, poort, _ = draaiend
    c = http.client.HTTPConnection("127.0.0.1", poort, timeout=5)
    with pytest.raises((http.client.HTTPException, OSError)):
        c.request("GET", "/api/health")
        c.getresponse().read()
    c.close()


def test_verkeerde_host_over_tls_403(draaiend):
    _, poort, context = draaiend
    c = _verbind(poort, context)
    c.request("GET", "/api/health", headers={"Host": "evil.example"})
    assert c.getresponse().status == 403
    c.close()


def _lees_events(antwoord, aantal, timeout=5):
    """Leest ``aantal`` SSE-events (soort, data) van een open stream."""

    events, soort, eind = [], None, time.time() + timeout
    while len(events) < aantal and time.time() < eind:
        regel = antwoord.fp.readline().decode("utf-8").rstrip("\n")
        if regel.startswith("event: "):
            soort = regel[7:]
        elif regel.startswith("data: ") and soort:
            events.append((soort, json.loads(regel[6:])))
            soort = None
    return events


def test_sse_stuurt_status_en_wijzigingen(draaiend):
    dashboard, poort, context = draaiend
    waarnemer = Waarnemer(dashboard.api, dashboard.bus, interval=0.1)
    waarnemer.stap()

    c = _verbind(poort, context)
    c.request("GET", "/api/events", headers={"Authorization": f"Bearer {VIEW}"})
    a = c.getresponse()
    assert a.status == 200
    assert a.getheader("Content-Type").startswith("text/event-stream")

    eerste = dict(_lees_events(a, 3))
    assert eerste["status"]["fase"] == "rust"
    assert eerste["timer"] == []
    assert eerste["pending"] is None

    set_pending("power_confirm", {"action": "shutdown", "question": "sluit af"})
    waarnemer.stap()
    soort, data = _lees_events(a, 1)[0]
    assert soort == "pending"
    assert data["soort"] == "power_confirm"
    c.close()


# ----- waarnemer en bus -----

def test_waarnemer_publiceert_alleen_wijzigingen(werkmap):
    api = _dashboard(werkmap, 8780).api
    bus = EventBus()
    w = Waarnemer(api, bus)
    assert sorted(w.stap()) == ["pending", "status", "timer"]
    assert w.stap() == []
    api.timer_store.zet("thee", 60)
    assert w.stap() == ["timer"]


def test_melding_gaat_direct_naar_de_bus(werkmap):
    from core.proactive import Melding

    api = _dashboard(werkmap, 8780).api
    bus = EventBus()
    Waarnemer(api, bus)
    ab = bus.abonneer()
    api._nieuwe_melding(Melding("Pauze", nu=1.0))
    soort, data = ab.wachtrij.get_nowait()
    assert soort == "melding" and data["tekst"] == "Pauze"


def test_trage_abonnee_wordt_losgekoppeld():
    bus = EventBus()
    ab = bus.abonneer()
    for i in range(300):
        bus.publiceer("status", {"i": i}, onthoud=False)
    assert ab.overgelopen is True
    assert bus.aantal() == 0


def test_sse_bericht_kan_het_formaat_niet_breken():
    from dashboard.events import sse_bericht

    bericht = sse_bericht("melding", {"tekst": "regel1\nevent: nep\ndata: x"})
    assert bericht.count(b"\n\n") == 1
    assert bericht.startswith(b"event: melding\ndata: ")
    assert bericht.count(b"\nevent:") == 0


# ----- starten vanuit main.py -----

@pytest.fixture
def dash_config(monkeypatch, werkmap, certs):
    import config
    import core.audit as audit
    import dashboard.api as dapi
    from core import timers

    r, _ = certs
    monkeypatch.setattr(config, "DASHBOARD_ENABLED", True)
    monkeypatch.setattr(config, "DASHBOARD_VIEW_TOKEN", VIEW)
    monkeypatch.setattr(config, "DASHBOARD_CONTROL_TOKEN", CONTROL)
    monkeypatch.setattr(config, "DASHBOARD_CERT_FILE", str(r.server_cert))
    monkeypatch.setattr(config, "DASHBOARD_KEY_FILE", str(r.server_key))
    monkeypatch.setattr(config, "DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "DASHBOARD_PORT", _vrije_poort())
    monkeypatch.setattr(config, "DASHBOARD_LAN_IP", "192.168.1.5")
    monkeypatch.setattr(config, "DASHBOARD_DEVICES_FILE", str(werkmap / "dev.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(werkmap / "audit.jsonl"))
    monkeypatch.setattr(dapi, "WIDGETS_FILE", str(werkmap / "dashboard.json"))
    timers.reset_store(timers.TimerStore(pad=str(werkmap / "timers.json")))
    yield config
    timers.reset_store(None)


def test_start_dashboard_overleeft_een_console_zonder_utf8(dash_config):
    from dashboard.server import start_dashboard

    def cp1252_console(tekst):
        tekst.encode("cp1252")
        print(tekst)

    def kapotte_console(tekst):
        raise UnicodeEncodeError("charmap", "x", 0, 1, "kan niet")

    for toon in (cp1252_console, kapotte_console):
        dienst = start_dashboard(toon=toon)
        try:
            assert dienst.poort == dash_config.DASHBOARD_PORT
            # De koppelcode is aangemaakt, ook als de console hem niet kon tonen.
            assert dienst.dashboard.koppelcode.resterend() > 0
        finally:
            dienst.stop()


def test_main_start_dashboard_alleen_als_aan(monkeypatch, dash_config):
    import main

    monkeypatch.setattr(dash_config, "DASHBOARD_ENABLED", False)
    assert main._start_dashboard(engine=None) is None


def test_main_start_dashboard_onveilig_stopt_jarvis_niet(monkeypatch, dash_config):
    import main

    monkeypatch.setattr(dash_config, "DASHBOARD_CONTROL_TOKEN", "")
    assert main._start_dashboard(engine=None) is None


def test_startmelding_noemt_koppelpagina_en_profiel(dash_config):
    from dashboard.server import start_dashboard

    uitvoer = []
    dienst = start_dashboard(toon=uitvoer.append)
    try:
        tekst = uitvoer[0]
        assert "/koppel.html" in tekst
        # Het profiel staat naast het certificaat (zelfde map als het script).
        assert "/profiel.mobileconfig" in tekst
        assert "LET OP" not in tekst
    finally:
        dienst.stop()


def test_startmelding_waarschuwt_als_profiel_ontbreekt(monkeypatch, dash_config, werkmap):
    from dashboard.server import start_dashboard

    import dashboard.server as server_mod

    origineel = server_mod.bouw_dashboard

    def zonder_profiel(**kwargs):
        kwargs["profiel_file"] = [str(werkmap / "bestaat-niet.mobileconfig")]
        return origineel(**kwargs)

    monkeypatch.setattr(server_mod, "bouw_dashboard", zonder_profiel)
    uitvoer = []
    dienst = start_dashboard(toon=uitvoer.append)
    try:
        assert "LET OP: iPad-profiel niet gevonden" in uitvoer[0]
        assert "make_dashboard_cert.py" in uitvoer[0]
    finally:
        dienst.stop()
