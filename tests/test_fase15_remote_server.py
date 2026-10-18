"""Fase 15 — tests voor remote/server.py.

Dekt:
    - server start met geldige configuratie en weigert ongeldige configuratie;
    - geldige en ongeldige authenticatie (HMAC, tijdstempel, nonce);
    - replay-aanvallen, te grote requests en time-outs;
    - onbekende routes, acties en parameters worden geweigerd;
    - gelijktijdige requests leiden niet tot dubbele uitvoering;
    - audit-logs bevatten geen tokens of geheimen;
    - TLS: geldige aanvraag, onbekende CA en platte HTTP op de TLS-poort;
    - trage, stille of halfhandshake-verbindingen blokkeren de server niet.
"""

import datetime
import http.client
import importlib.util
import ipaddress
import json
import os
import shutil
import socket
import ssl
import tempfile
import threading
import time

import pytest

import core.audit as core_audit
from remote import protocol, server

TOKEN = "s" * 32


# ---------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def audit_bestand(monkeypatch):
    """Zorgt dat audit-schrijfsels in een tijdelijke map belanden."""

    map_ = tempfile.mkdtemp(prefix="jarvis_audit_")
    pad = os.path.join(map_, "audit.jsonl")
    monkeypatch.setattr(core_audit, "AUDIT_FILE", pad)
    yield pad
    shutil.rmtree(map_, ignore_errors=True)


def _agent(dispatch=None, **kwargs):
    kwargs.setdefault("rate_limiter", server.RateLimiter(max_requests=0))
    kwargs.setdefault("audit", False)
    kwargs.setdefault("dispatch", dispatch)
    return server.RemoteAgent(TOKEN, **kwargs)


def _dispatch_tekst(resultaat="gedaan", teller=None):
    def dispatch(tool, argumenten, question):
        if teller is not None:
            teller.append((tool, argumenten, question))
        return resultaat

    return dispatch


def _commando(tool, arguments=None, token=TOKEN, timestamp=None, nonce=None, question=None):
    bericht = {"tool": tool}
    if arguments is not None:
        bericht["arguments"] = arguments
    if question is not None:
        bericht["question"] = question

    body = protocol.encode_body(bericht)
    headers = protocol.signed_headers(
        token, "POST", server.ROUTE_COMMAND, body, timestamp=timestamp, nonce=nonce
    )
    return headers, body


def _health(token=TOKEN, timestamp=None, nonce=None):
    body = b""
    headers = protocol.signed_headers(
        token, "GET", server.ROUTE_HEALTH, body, timestamp=timestamp, nonce=nonce
    )
    return headers, body


# ---------------------------------------------------------------
# Configuratie — fail-closed
# ---------------------------------------------------------------

def test_agent_vereist_token():
    with pytest.raises(ValueError):
        server.RemoteAgent("")
    with pytest.raises(ValueError):
        server.RemoteAgent("    ")


def test_create_server_weigert_zonder_token():
    with pytest.raises(RuntimeError):
        server.create_server(host="127.0.0.1", port=0, token="", cert_file="a", key_file="b")


def test_create_server_weigert_zonder_certificaat():
    with pytest.raises(RuntimeError):
        server.create_server(
            host="127.0.0.1", port=0, token=TOKEN, cert_file="", key_file=""
        )


def test_create_server_weigert_ontbrekende_bestanden():
    with pytest.raises(RuntimeError):
        server.create_server(
            host="127.0.0.1",
            port=0,
            token=TOKEN,
            cert_file="C:\\bestaat-niet.crt",
            key_file="C:\\bestaat-niet.key",
        )


def test_create_server_weigert_ongeldig_certificaat():
    map_ = tempfile.mkdtemp(prefix="jarvis_badcert_")
    cert = os.path.join(map_, "cert.pem")
    key = os.path.join(map_, "key.pem")
    try:
        with open(cert, "w", encoding="utf-8") as f:
            f.write("dit is geen certificaat")
        with open(key, "w", encoding="utf-8") as f:
            f.write("dit is geen sleutel")

        with pytest.raises(RuntimeError):
            server.create_server(
                host="127.0.0.1", port=0, token=TOKEN, cert_file=cert, key_file=key
            )
    finally:
        shutil.rmtree(map_, ignore_errors=True)


# ---------------------------------------------------------------
# Authenticatie
# ---------------------------------------------------------------

def test_gezondheid_met_geldige_handtekening():
    agent = _agent()
    headers, body = _health()

    status, payload = agent.process("GET", server.ROUTE_HEALTH, headers, body, client_ip="192.168.1.10")

    assert status == 200
    assert payload["ok"] is True
    assert payload["status"] == "online"


def test_gezondheid_zonder_handtekening():
    agent = _agent()

    status, payload = agent.process("GET", server.ROUTE_HEALTH, {}, b"", client_ip="192.168.1.10")

    assert status == 401
    assert payload["ok"] is False
    assert payload["fout"]["code"] == "niet_geautoriseerd"


def test_gezondheid_ongeldig_token():
    agent = _agent()
    headers, body = _health(token="r" * 32)

    status, payload = agent.process("GET", server.ROUTE_HEALTH, headers, body, client_ip="192.168.1.10")

    assert status == 401


def test_commando_geldig():
    teller = []
    agent = _agent(dispatch=_dispatch_tekst("gedaan", teller))
    headers, body = _commando("pc_status", {})

    status, payload = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 200
    assert payload["ok"] is True
    assert payload["resultaat"] == "gedaan"
    assert teller == [("pc_status", {}, "")]


def test_handtekening_body_gemanipuleerd():
    agent = _agent(dispatch=_dispatch_tekst())
    headers, _ = _commando("pc_status", {})
    gemanipuleerd = protocol.encode_body({"tool": "screenshot"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, gemanipuleerd, client_ip="192.168.1.10"
    )

    assert status == 401


def test_handtekening_verkeerd_pad():
    agent = _agent(dispatch=_dispatch_tekst())
    # Ondertekend voor /command, maar naar /health gestuurd.
    headers, body = _commando("pc_status", {})

    status, _ = agent.process("GET", server.ROUTE_HEALTH, headers, body, client_ip="192.168.1.10")

    assert status == 401


def test_te_oude_tijdstempel():
    agent = _agent(dispatch=_dispatch_tekst())
    oud = time.time() - agent._replay_window - 30
    headers, body = _commando("pc_status", {}, timestamp=oud)

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 401


def test_tijdstempel_in_toekomst():
    agent = _agent(dispatch=_dispatch_tekst())
    toekomst = time.time() + agent._replay_window + 30
    headers, body = _commando("pc_status", {}, timestamp=toekomst)

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 401


def test_replay_wordt_geweigerd():
    teller = []
    agent = _agent(dispatch=_dispatch_tekst("gedaan", teller))
    headers, body = _commando("pc_status", {}, nonce="abc123")

    eerste, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")
    tweede, tweede_payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert eerste == 200
    assert tweede == 401
    assert len(teller) == 1, "de replay mag de actie niet nogmaals uitvoeren"


def test_nonce_niet_verbruikt_bij_slechte_handtekening():
    agent = _agent(dispatch=_dispatch_tekst())

    # Eerst een aanvraag met een FOUT token, maar dezelfde nonce.
    fout_headers, body = _commando("pc_status", {}, token="r" * 32, nonce="dezelfde")
    status_fout, _ = agent.process(
        "POST", server.ROUTE_COMMAND, fout_headers, body, client_ip="192.168.1.10"
    )
    assert status_fout == 401

    # Daarna de GELDIGE aanvraag met diezelfde nonce mag nog steeds.
    goede_headers, body = _commando("pc_status", {}, nonce="dezelfde")
    status_goed, _ = agent.process(
        "POST", server.ROUTE_COMMAND, goede_headers, body, client_ip="192.168.1.10"
    )
    assert status_goed == 200


# ---------------------------------------------------------------
# Routes en methodes
# ---------------------------------------------------------------

def test_onbekende_route():
    agent = _agent()
    headers, body = _health()

    status, payload = agent.process("GET", "/geheim", headers, body, client_ip="192.168.1.10")

    assert status == 404
    assert payload["fout"]["code"] == "onbekende_route"


def test_query_string_is_onbekende_route():
    agent = _agent()
    headers, body = _health()

    status, _ = agent.process(
        "GET", server.ROUTE_HEALTH + "?x=1", headers, body, client_ip="192.168.1.10"
    )

    assert status == 404


def test_verkeerde_methode_op_command():
    agent = _agent()
    headers, body = _health()

    status, payload = agent.process("GET", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 405
    assert payload["fout"]["code"] == "verkeerde_methode"


def test_verkeerde_methode_op_health():
    agent = _agent()
    headers, body = _commando("pc_status", {})

    status, payload = agent.process("POST", server.ROUTE_HEALTH, headers, body, client_ip="192.168.1.10")

    assert status == 405


# ---------------------------------------------------------------
# Acties en parameters
# ---------------------------------------------------------------

@pytest.mark.parametrize(
    "tool",
    [
        "open_file",
        "create_file",
        "create_folder",
        "copy_file",
        "move_file",
        "rename_file",
        "ui_launch_app",
        "ui_type_text",
        "ui_set_value",
        "shutdown_pc",
        "restart_pc",
    ],
)
def test_niet_toegestane_acties(tool):
    teller = []
    agent = _agent(dispatch=_dispatch_tekst("gedaan", teller))
    headers, body = _commando(tool, {})

    status, payload = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 403
    assert payload["fout"]["code"] == "niet_toegestaan"
    assert teller == [], "een geweigerde actie mag nooit worden uitgevoerd"


def test_ontbrekende_parameter():
    teller = []
    agent = _agent(dispatch=_dispatch_tekst("gedaan", teller))
    headers, body = _commando("open_program", {})

    status, payload = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 403
    assert teller == []


def test_extra_parameter():
    agent = _agent(dispatch=_dispatch_tekst())
    headers, body = _commando(
        "open_program", {"program": "Notepad", "extra": "kwaad"}
    )

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 403


def test_ongeldig_parametertype():
    agent = _agent(dispatch=_dispatch_tekst())
    headers, body = _commando("set_volume", {"percent": "hard"})

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 403


def test_ongeldige_naam_tekens():
    agent = _agent(dispatch=_dispatch_tekst())
    headers, body = _commando("open_program", {"program": "notepad; rm -rf /"})

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 403


def test_ongeldige_json_wordt_geweigerd():
    agent = _agent(dispatch=_dispatch_tekst())
    body = b"{dit is geen json"
    headers = protocol.signed_headers(TOKEN, "POST", server.ROUTE_COMMAND, body)

    status, payload = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 400
    assert payload["fout"]["code"] == "ongeldig_bericht"


def test_bericht_moet_object_zijn():
    agent = _agent(dispatch=_dispatch_tekst())
    body = b"[1, 2, 3]"
    headers = protocol.signed_headers(TOKEN, "POST", server.ROUTE_COMMAND, body)

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 400


def test_onbekende_velden_in_bericht():
    agent = _agent(dispatch=_dispatch_tekst())
    body = protocol.encode_body({"tool": "pc_status", "arguments": {}, "hack": 1})
    headers = protocol.signed_headers(TOKEN, "POST", server.ROUTE_COMMAND, body)

    status, payload = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 400
    assert payload["fout"]["code"] == "ongeldig_bericht"


def test_query_parameter_in_tool_wordt_geweigerd():
    # "&" mag inmiddels in een programmanaam (Fase 15C: geen shell),
    # maar andere metacharacters blijven geweigerd.
    agent = _agent(dispatch=_dispatch_tekst())
    headers, body = _commando("open_program", {"program": "calc | whoami"})

    status, _ = agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    assert status == 403


# ---------------------------------------------------------------
# Limieten
# ---------------------------------------------------------------

def test_body_te_groot():
    agent = _agent(max_body_bytes=10)
    groot = b"x" * 50
    headers = protocol.signed_headers(TOKEN, "POST", server.ROUTE_COMMAND, groot)

    status, payload = agent.process("POST", server.ROUTE_COMMAND, headers, groot, client_ip="192.168.1.10")

    assert status == 413
    assert payload["fout"]["code"] == "te_groot"


def test_snelheidslimiet():
    agent = server.RemoteAgent(
        TOKEN,
        dispatch=_dispatch_tekst(),
        rate_limiter=server.RateLimiter(max_requests=2, window_seconds=60),
        audit=False,
    )

    statussen = []
    for _ in range(3):
        headers, body = _health()
        status, _ = agent.process("GET", server.ROUTE_HEALTH, headers, body, client_ip="192.168.1.99")
        statussen.append(status)

    assert statussen == [200, 200, 429]


def test_stille_verbinding_wordt_na_timeout_gesloten(monkeypatch):
    monkeypatch.setattr(server._RemoteHandler, "timeout", 0.5)

    agent = _agent(dispatch=_dispatch_tekst())
    httpd = server.RemoteAgentServer(("127.0.0.1", 0), agent)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        poort = httpd.server_address[1]
        verbinding = socket.create_connection(("127.0.0.1", poort), timeout=5)
        verbinding.settimeout(5)
        begin = time.time()
        data = verbinding.recv(1024)
        duur = time.time() - begin
        verbinding.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert data == b"", "de server moet de stille verbinding sluiten"
    assert duur < 4, "de time-out moet snel afgaan"


# ---------------------------------------------------------------
# Gelijktijdigheid — geen dubbele uitvoering door replay
# ---------------------------------------------------------------

def test_gelijktijdige_replay_maakt_een_uitvoering():
    teller = {"n": 0}
    slot = threading.Lock()

    def dispatch(tool, argumenten, question):
        with slot:
            teller["n"] += 1
        time.sleep(0.05)
        return "gedaan"

    agent = _agent(dispatch=dispatch)
    headers, body = _commando("pc_status", {}, nonce="eenmalig")
    resultaten = []
    slot_resultaat = threading.Lock()

    def worker(index):
        status, _ = agent.process(
            "POST", server.ROUTE_COMMAND, headers, body, client_ip=f"10.0.0.{index}"
        )
        with slot_resultaat:
            resultaten.append(status)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert resultaten.count(200) == 1, "exact één aanvraag mag slagen"
    assert resultaten.count(401) == 9, "de rest is een replay"
    assert teller["n"] == 1, "de actie mag maar één keer worden uitgevoerd"


# ---------------------------------------------------------------
# Audit — geen geheimen
# ---------------------------------------------------------------

def test_audit_bevat_geen_geheimen(audit_bestand):
    agent = _agent(dispatch=_dispatch_tekst("gedaan"))
    agent._audit_enabled = True
    headers, body = _commando("pc_status", {}, nonce="nonce-xyz")

    agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    with open(audit_bestand, "r", encoding="utf-8") as f:
        inhoud = f.read()

    assert TOKEN not in inhoud
    assert "X-JARVIS" not in inhoud
    assert headers[protocol.HEADER_SIGNATURE] not in inhoud
    assert "nonce-xyz" not in inhoud
    # Het toegestane resultaat mag wél zichtbaar zijn.
    assert "pc_status" in json.dumps(json.loads(inhoud.splitlines()[-1]))


def test_audit_bij_geweigerde_authenticatie(audit_bestand):
    agent = _agent()
    agent._audit_enabled = True

    agent.process("GET", server.ROUTE_HEALTH, {}, b"", client_ip="192.168.1.10")

    with open(audit_bestand, "r", encoding="utf-8") as f:
        regels = [json.loads(regel) for regel in f if regel.strip()]

    assert regels, "een geweigerde aanvraag moet worden gelogd"
    laatste = regels[-1]
    assert laatste["goedgekeurd"] is False
    assert laatste["reden"]
    assert TOKEN not in json.dumps(laatste)


def test_audit_bij_geweigerde_actie(audit_bestand):
    agent = _agent(dispatch=_dispatch_tekst())
    agent._audit_enabled = True
    headers, body = _commando("open_file", {"filename": "C:\\geheim.txt"})

    agent.process("POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10")

    with open(audit_bestand, "r", encoding="utf-8") as f:
        regels = [json.loads(regel) for regel in f if regel.strip()]

    assert regels[-1]["tool"] == "open_file"
    assert regels[-1]["goedgekeurd"] is False


# ---------------------------------------------------------------
# TLS-integratie (vereist 'cryptography')
# ---------------------------------------------------------------

def _maak_selfsigned_cert(cert_pad, key_pad):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    sleutel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    naam = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    nu = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(naam)
        .issuer_name(naam)
        .public_key(sleutel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nu - datetime.timedelta(days=1))
        .not_valid_after(nu + datetime.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(sleutel, hashes.SHA256())
    )

    with open(cert_pad, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_pad, "wb") as f:
        f.write(
            sleutel.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )


@pytest.fixture
def tls_bestanden():
    if importlib.util.find_spec("cryptography") is None:
        pytest.skip("cryptography niet beschikbaar voor TLS-tests")

    map_ = tempfile.mkdtemp(prefix="jarvis_cert_")
    cert = os.path.join(map_, "cert.pem")
    key = os.path.join(map_, "key.pem")
    _maak_selfsigned_cert(cert, key)
    try:
        yield cert, key
    finally:
        shutil.rmtree(map_, ignore_errors=True)


def _start_tls_server(cert, key, dispatch=None, **kwargs):
    httpd = server.create_server(
        host="127.0.0.1",
        port=0,
        token=TOKEN,
        cert_file=cert,
        key_file=key,
        dispatch=dispatch or _dispatch_tekst("gedaan"),
        rate_limiter=server.RateLimiter(max_requests=0),
        audit=False,
        **kwargs,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, httpd.server_address[1]


def test_tls_geldige_aanvraag(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)

    try:
        context = ssl.create_default_context(cafile=cert)
        verbinding = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
        headers, body = _commando("pc_status", {})
        headers["Content-Type"] = "application/json"
        verbinding.request("POST", server.ROUTE_COMMAND, body=body, headers=headers)
        antwoord = verbinding.getresponse()
        data = json.loads(antwoord.read())
        verbinding.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert antwoord.status == 200
    assert data["ok"] is True


def test_tls_onbekende_ca_wordt_geweigerd(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)

    try:
        # Vertrouwt het zelfondertekende certificaat NIET.
        context = ssl.create_default_context()
        verbinding = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
        with pytest.raises(ssl.SSLError):
            verbinding.request("GET", server.ROUTE_HEALTH)
            verbinding.getresponse()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_platte_http_op_tls_poort_wordt_geweigerd(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)

    try:
        verbinding = http.client.HTTPConnection("127.0.0.1", poort, timeout=5)
        with pytest.raises(Exception):
            verbinding.request("GET", server.ROUTE_HEALTH)
            verbinding.getresponse()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------
# Trage of stille verbindingen mogen de server niet blokkeren
# ---------------------------------------------------------------

def _stille_verbinding(poort):
    """Opent een kaal TCP-verbinding die nooit iets stuurt."""

    return socket.create_connection(("127.0.0.1", poort), timeout=5)


def _geldig_verzoek(cert, poort):
    """Doet één geldig ondertekend verzoek via TLS.

    Geeft ``(status, payload, duur_in_seconden)`` terug.
    """

    context = ssl.create_default_context(cafile=cert)
    verbinding = http.client.HTTPSConnection(
        "127.0.0.1", poort, context=context, timeout=5
    )
    headers, body = _commando("pc_status", {})
    headers["Content-Type"] = "application/json"
    begin = time.time()
    verbinding.request("POST", server.ROUTE_COMMAND, body=body, headers=headers)
    antwoord = verbinding.getresponse()
    data = json.loads(antwoord.read())
    verbinding.close()
    return antwoord.status, data, time.time() - begin


def _stop_server(httpd, thread, *verbindingen):
    """Sluit eerst open verbindingen en daarna de server."""

    for verbinding in verbindingen:
        try:
            verbinding.close()
        except OSError:
            pass
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def test_stille_verbinding_blokkeert_normaal_verzoek_niet(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)
    stille = _stille_verbinding(poort)
    time.sleep(0.3)  # de server moet de stille verbinding al hebben geaccepteerd

    try:
        status, data, duur = _geldig_verzoek(cert, poort)
    finally:
        _stop_server(httpd, thread, stille)

    assert status == 200
    assert data["ok"] is True
    assert duur < 1.0, "een stille verbinding mag een normaal verzoek niet vertragen"


def test_tien_stille_verbindingen_blokkeren_niet(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key, max_connections_per_ip=0)
    stille = [_stille_verbinding(poort) for _ in range(10)]
    time.sleep(0.5)

    try:
        status, data, duur = _geldig_verzoek(cert, poort)
    finally:
        _stop_server(httpd, thread, *stille)

    assert status == 200
    assert data["ok"] is True
    assert duur < 1.0, "tien stille verbindingen mogen een normaal verzoek niet vertragen"


def test_halve_handshake_blokkeert_niet(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)
    # Een onafgemaakte ClientHello: het record belooft 64 bytes maar
    # er komen er maar enkeel, dus de handshake blijft hierop wachten.
    half = socket.create_connection(("127.0.0.1", poort), timeout=5)
    half.sendall(b"\x16\x03\x01\x00\x40" + b"\x01\x00\x00\x3c\x03\x03" + b"x" * 16)
    time.sleep(0.3)

    try:
        status, data, duur = _geldig_verzoek(cert, poort)
    finally:
        _stop_server(httpd, thread, half)

    assert status == 200
    assert data["ok"] is True
    assert duur < 1.0, "een halve handshake mag een normaal verzoek niet vertragen"


def test_verbindingslimiet_sluit_extra_verbindingen(tls_bestanden):
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key, max_connections=2)
    bezet = [_stille_verbinding(poort) for _ in range(2)]
    time.sleep(0.3)  # beide verbindingen bezetten nu een plek

    extra = socket.create_connection(("127.0.0.1", poort), timeout=5)
    try:
        begin = time.time()
        try:
            data = extra.recv(1024)
        except (socket.timeout, TimeoutError):
            data = None
        sluiten = time.time() - begin
    finally:
        extra.close()

    assert data == b"", "de derde verbinding moet direct worden gesloten"
    assert sluiten < 2.0, "de derde verbinding moet snel worden gesloten"

    # De bezette verbindingen dicht: de plekken komen dan weer vrij.
    for verbinding in bezet:
        verbinding.close()

    # Zodra de plekken vrij zijn, moet een geldig verzoek weer doorkomen.
    try:
        status = None
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                status, _data, _duur = _geldig_verzoek(cert, poort)
            except Exception:
                status = None
            if status == 200:
                break
            time.sleep(0.1)
    finally:
        _stop_server(httpd, thread, *bezet)

    assert status == 200, "na het vrijkomen van de plekken moet een geldig verzoek slagen"
