"""Fase 18 M7: end-to-end over echte TLS-sockets.

Eén doorlopend scenario zoals op de iPad: koppelen met de code, de
sessiecookie gebruiken, bedienen, een live-stream openen en het apparaat
weer ontkoppelen. Daarna de "grep-controle" uit het beveiligingstestplan
(design §12.1): geen token, geen apparaattoken en geen koppelcode in het
auditlog of in welke logregel dan ook.

Bewust ``tempfile.mkdtemp`` (Windows-kwestie met ``tmp_path``).
"""

import http.client
import importlib.util
import json
import logging
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

import core.audit as audit
from core import proactive
from core.confirmation import clear_pending
from core.timers import TimerStore
from dashboard import auth
from dashboard.api import DashboardAPI
from dashboard.bronnen import Bronnen
from dashboard.events import Waarnemer
from dashboard.server import DashboardServer, create_server, standaard_hosts, standaard_origins

pytest.importorskip("cryptography")

VIEW = "kijk-token-e2e-0123456789abcdef"
CONTROL = "bedien-token-e2e-0123456789abcdef"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(scope="module")
def certs():
    spec = importlib.util.spec_from_file_location("make_dashboard_cert_e2e", SCRIPTS / "make_dashboard_cert.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_dashboard_cert_e2e"] = module
    spec.loader.exec_module(module)
    map_ = tempfile.mkdtemp(prefix="jarvis_e2e_cert_")
    try:
        yield module.maak_certificaten(map_)
    finally:
        shutil.rmtree(map_, ignore_errors=True)


@pytest.fixture
def omgeving(certs, monkeypatch, caplog):
    werk = Path(tempfile.mkdtemp(prefix="jarvis_e2e_"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(werk / "audit.jsonl"))
    caplog.set_level(logging.DEBUG)
    clear_pending()
    proactive.set_nachtmodus("auto")

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    poort = s.getsockname()[1]
    s.close()

    api = DashboardAPI(
        timer_store=TimerStore(pad=str(werk / "timers.json")),
        widgets_pad=str(werk / "dashboard.json"),
        spreekt_fn=lambda: False,
        fase_fn=lambda: "rust",
        pc_target_fn=lambda: "local",
        bronnen=Bronnen(audit_pad_fn=lambda: str(werk / "audit.jsonl")),
        gesprek_fn=lambda: [],
    )
    hosts = standaard_hosts(poort)
    dashboard = DashboardServer(
        api=api,
        authenticator=auth.Authenticator(VIEW, CONTROL, auth.ApparaatRegister(str(werk / "devices.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts,
        allowed_origins=standaard_origins(hosts),
        static_dir=str(werk),
    )
    httpd = create_server(dashboard, host="127.0.0.1", port=poort,
                          cert_file=str(certs.server_cert), key_file=str(certs.server_key))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    context = ssl.create_default_context(cafile=str(certs.ca_cert))
    try:
        yield dashboard, poort, context, werk, caplog
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        clear_pending()
        proactive.set_nachtmodus("auto")
        shutil.rmtree(werk, ignore_errors=True)


def _verzoek(poort, context, methode, pad, cookie=None, body=None):
    c = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    data = None
    if methode != "GET":
        headers["Origin"] = f"https://127.0.0.1:{poort}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body)
    c.request(methode, pad, body=data, headers=headers)
    a = c.getresponse()
    inhoud = a.read()
    c.close()
    return a.status, (json.loads(inhoud) if inhoud else None), a.getheader("Set-Cookie")


def test_volledig_scenario_en_geen_geheimen_in_logs(omgeving):
    dashboard, poort, context, werk, caplog = omgeving

    # 1. Koppelen met de code (zoals op de iPad).
    code = dashboard.koppelcode.nieuw()
    status, data, set_cookie = _verzoek(poort, context, "POST", "/api/pair", body={"code": code, "rol": "bedien"})
    assert status == 201
    apparaattoken = data["token"]
    cookie = set_cookie.split(";")[0]
    assert "HttpOnly" in set_cookie and "Secure" in set_cookie

    # 2. Lezen en bedienen met alleen de cookie.
    assert _verzoek(poort, context, "GET", "/api/sessie", cookie=cookie)[1]["rol"] == "bedien"
    assert _verzoek(poort, context, "GET", "/api/status", cookie=cookie)[0] == 200
    assert _verzoek(poort, context, "POST", "/api/timers", cookie=cookie, body={"naam": "pasta", "seconden": 600})[0] == 201
    assert _verzoek(poort, context, "POST", "/api/nachtmodus", cookie=cookie, body={"stand": "aan"})[0] == 200
    status, _, _ = _verzoek(poort, context, "POST", "/api/power", cookie=cookie, body={"actie": "slaap"})
    assert status == 202
    pending = _verzoek(poort, context, "GET", "/api/pending", cookie=cookie)[1]
    assert pending["soort"] == "power_confirm"
    assert _verzoek(poort, context, "POST", "/api/goedkeuring", cookie=cookie,
                    body={"id": pending["id"], "nonce": pending["nonce"], "besluit": "nee"})[0] == 200

    # 3. Een live-stream openen...
    Waarnemer(dashboard.api, dashboard.bus).stap()
    stream = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
    stream.request("GET", "/api/events", headers={"Cookie": cookie})
    antwoord = stream.getresponse()
    assert antwoord.status == 200
    assert b"event: status" in antwoord.fp.readline() + antwoord.fp.readline() + antwoord.fp.readline()

    # 4. ...en het apparaat ontkoppelen: de open stream moet stoppen.
    assert _verzoek(poort, context, "POST", "/api/afmelden", cookie=cookie, body={})[0] == 200
    dashboard.bus.publiceer("status", {"test": True}, onthoud=False)
    eind = time.time() + 5
    gesloten = False
    while time.time() < eind:
        regel = antwoord.fp.readline()
        if regel == b"":
            gesloten = True
            break
        if b'"test"' in regel:
            pytest.fail("een ontkoppeld apparaat kreeg nog live-gegevens")
    stream.close()
    assert gesloten
    assert _verzoek(poort, context, "GET", "/api/status", cookie=cookie)[0] == 401

    # 5. Een paar foute pogingen (die moeten in de audit, zonder het token).
    for _ in range(2):
        c = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
        c.request("GET", "/api/status", headers={"Authorization": "Bearer fout-token-dat-niet-mag-lekken"})
        assert c.getresponse().status == 401
        c.close()

    # 6. Grep-controle: geen enkel geheim in het auditlog of in de logregels.
    auditlog = (werk / "audit.jsonl").read_text(encoding="utf-8")
    logtekst = "\n".join(r.getMessage() for r in caplog.records)
    assert "dashboard_koppelen" in auditlog and "dashboard_auth" in auditlog
    for geheim in (apparaattoken, code, VIEW, CONTROL, "fout-token-dat-niet-mag-lekken", cookie.split("=", 1)[1]):
        assert geheim not in auditlog, "geheim in het auditlog"
        assert geheim not in logtekst, "geheim in een logregel"
    # Ook de koppelcode-hash of het apparatenbestand bevat het token niet.
    assert apparaattoken not in (werk / "devices.json").read_text(encoding="utf-8")


def test_token_vernieuwen_stopt_de_oude_stream(omgeving):
    dashboard, poort, context, werk, _ = omgeving
    code = dashboard.koppelcode.nieuw()
    _, _, set_cookie = _verzoek(poort, context, "POST", "/api/pair", body={"code": code, "rol": "kijk"})
    oud = set_cookie.split(";")[0]

    stream = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
    stream.request("GET", "/api/events", headers={"Cookie": oud})
    antwoord = stream.getresponse()
    assert antwoord.status == 200
    antwoord.fp.readline()

    status, data, nieuw_cookie = _verzoek(poort, context, "POST", "/api/tokens/rotatie", cookie=oud, body={"sessie": True})
    assert status == 200 and "token" not in data
    dashboard.bus.publiceer("status", {"na_rotatie": True}, onthoud=False)
    eind = time.time() + 5
    while time.time() < eind:
        regel = antwoord.fp.readline()
        if regel == b"":
            break
        assert b"na_rotatie" not in regel
    stream.close()
    nieuw = nieuw_cookie.split(";")[0]
    assert _verzoek(poort, context, "GET", "/api/status", cookie=nieuw)[0] == 200
    assert _verzoek(poort, context, "GET", "/api/status", cookie=oud)[0] == 401
