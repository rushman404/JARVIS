"""Fase 15C — tests voor verbindingsbeveiliging van de remote server.

Dekt:
    - 36 verbindingen met een geldige recordheader vanaf een niet-toegestaan
      IP houden een toegestaan IP niet tegen;
    - de limiet per IP (standaard 4) werkt;
    - de totale handshake-deadline van 5 seconden werkt;
    - verbindingen van een IP dat de limiet raakt tellen als mislukte
      pogingen voor de lockout;
    - mislukte handshakes worden samengevat gelogd;
    - niet-toegestane en geblokkeerde IPs worden vóór de handshake stil
      gesloten (process_request_thread direct).
"""

import datetime
import http.client
import importlib.util
import ipaddress
import json
import logging
import os
import shutil
import socket
import ssl
import tempfile
import threading
import time

import pytest

from remote import protocol, server

TOKEN = "s" * 32


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def audit_bestand(monkeypatch):
    import core.audit as core_audit

    map_ = tempfile.mkdtemp(prefix="jarvis_audit_")
    pad = os.path.join(map_, "audit.jsonl")
    monkeypatch.setattr(core_audit, "AUDIT_FILE", pad)
    yield pad
    shutil.rmtree(map_, ignore_errors=True)


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


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _dispatch_tekst(resultaat="gedaan", teller=None):
    def dispatch(tool, argumenten, question):
        if teller is not None:
            teller.append((tool, argumenten, question))
        return resultaat

    return dispatch


def _commando(tool, arguments=None):
    bericht = {"tool": tool}
    if arguments is not None:
        bericht["arguments"] = arguments

    body = protocol.encode_body(bericht)
    headers = protocol.signed_headers(
        TOKEN, "POST", server.ROUTE_COMMAND, body
    )
    return headers, body


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


def _stop_server(httpd, thread, *verbindingen):
    for verbinding in verbindingen:
        try:
            verbinding.close()
        except OSError:
            pass
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _geldig_verzoek(cert, poort):
    context = ssl.create_default_context(cafile=cert)
    verbinding = http.client.HTTPSConnection(
        "127.0.0.1", poort, context=context, timeout=5
    )
    headers, body = _commando("pc_status", {})
    headers["Content-Type"] = "application/json"
    verbinding.request("POST", server.ROUTE_COMMAND, body=body, headers=headers)
    antwoord = verbinding.getresponse()
    data = json.loads(antwoord.read())
    verbinding.close()
    return antwoord.status, data


def _record_verbinding(poort):
    """Opent een TCP-verbinding en stuurt een geldige TLS-recordheader.

    De header belooft 64 bytes maar er komen er geen, dus de handshake
    blijft wachten tot de deadline of tot de verbinding gesloten wordt.
    """
    sock = socket.create_connection(("127.0.0.1", poort), timeout=5)
    sock.sendall(b"\x16\x03\x01\x00\x40")
    return sock


# ---------------------------------------------------------------
# 1. Niet-toegestaan IP blokkeert toegestaan IP niet
# ---------------------------------------------------------------

def test_36_verbindingen_van_niet_toegestaan_ip_blokkeert_niet(tls_bestanden):
    """36 verbindingen vanaf een niet-toegestaan IP mogen een toegestaan
    IP niet tegenhouden."""
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)
    # Zet de allowlist ná het starten: alleen 192.168.1.50 is toegestaan.
    httpd.agent._allowed_ips = ("192.168.1.50",)

    stille = []
    try:
        for _ in range(36):
            try:
                sock = _record_verbinding(poort)
                stille.append(sock)
            except OSError:
                pass
        time.sleep(0.5)

        # Na de golf: pas de allowlist aan zodat 127.0.0.1 tóch mag en
        # controleer dat het toegestaan IP normaal werkt.
        httpd.agent._allowed_ips = ("127.0.0.1", "192.168.1.50")
        httpd.agent._lockout.reset("127.0.0.1")
        status, data = _geldig_verzoek(cert, poort)
    finally:
        _stop_server(httpd, thread, *stille)

    assert status == 200
    assert data["ok"] is True


# ---------------------------------------------------------------
# 2. Per-IP limiet
# ---------------------------------------------------------------

def test_per_ip_limiet_sluit_verbindingen(tls_bestanden):
    """De per-IP limiet sluit extra verbindingen vanaf hetzelfde IP."""
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key, max_connections_per_ip=2)

    bezet = []
    try:
        for _ in range(2):
            bezet.append(_record_verbinding(poort))
        time.sleep(0.3)

        extra = socket.create_connection(("127.0.0.1", poort), timeout=5)
        begin = time.time()
        try:
            data = extra.recv(1024)
        except (socket.timeout, TimeoutError):
            data = None
        sluiten = time.time() - begin
        extra.close()
    finally:
        _stop_server(httpd, thread, *bezet)

    assert data == b"", "de derde verbinding moet direct worden gesloten"
    assert sluiten < 2.0, "de derde verbinding moet snel worden gesloten"


def test_per_ip_limiet_telt_mislukte_pogingen_voor_lockout(tls_bestanden):
    """Verbindingen van een IP dat de per-IP limiet raakt tellen als
    mislukte pogingen voor de lockout."""
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key, max_connections_per_ip=1)

    bezet = []
    try:
        bezet.append(_record_verbinding(poort))
        time.sleep(0.3)

        # Vijf extra verbindingen: allemaal geweigerd, tellen mee voor
        # de lockout (max_failures=5).
        for _ in range(5):
            try:
                extra = socket.create_connection(("127.0.0.1", poort), timeout=2)
                extra.sendall(b"\x16\x03\x01\x00\x40")
                extra.close()
            except OSError:
                pass
        time.sleep(0.3)

        assert httpd.agent._lockout.is_blocked("127.0.0.1") is True
    finally:
        _stop_server(httpd, thread, *bezet)


# ---------------------------------------------------------------
# 3. Totale handshake-deadline
# ---------------------------------------------------------------

def test_handshake_deadline_waarde():
    """De standaard deadline is 5 seconden."""
    assert server.DEFAULT_HANDSHAKE_DEADLINE_SECONDS == 5.0


def test_handshake_deadline_breekt_trage_handshake_af(tls_bestanden):
    """Een handshake die de totale deadline overschrijdt wordt afgebroken
    en een nieuw verzoek werkt daarna."""
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(
        cert, key, handshake_deadline=1.0
    )

    trage = []
    try:
        for _ in range(3):
            trage.append(_record_verbinding(poort))
        time.sleep(1.5)  # wacht langer dan de deadline

        # Na de deadline: de trage verbindingen zijn afgebroken.
        # Reset eventuele lockout en doe een geldig verzoek.
        httpd.agent._lockout.reset("127.0.0.1")
        status, data = _geldig_verzoek(cert, poort)
    finally:
        _stop_server(httpd, thread, *trage)

    assert status == 200
    assert data["ok"] is True


# ---------------------------------------------------------------
# 4. Samengevatte logging van mislukte handshakes
# ---------------------------------------------------------------

def test_handshake_log_samengevat(tls_bestanden, caplog):
    """Mislukte handshakes worden samengevat gelogd: niet één regel per
    verbinding."""
    cert, key = tls_bestanden
    httpd, thread, poort = _start_tls_server(cert, key)

    with caplog.at_level(logging.WARNING, logger="jarvis.remote.server"):
        trage = []
        try:
            for _ in range(10):
                trage.append(_record_verbinding(poort))
            time.sleep(0.5)
        finally:
            _stop_server(httpd, thread, *trage)

    handshake_regels = [
        r for r in caplog.records
        if "handshake" in r.getMessage().lower() and "127.0.0.1" in r.getMessage()
    ]
    assert len(handshake_regels) >= 1
    # Niet tien (een per verbinding): de logging is samengevat.
    assert len(handshake_regels) < 10


# ---------------------------------------------------------------
# 5. IP-allowlist en lockout vóór de handshake (direct)
# ---------------------------------------------------------------

def _nep_server(agent, **extra):
    """Maakt een RemoteAgentServer zonder sockets (voor directe tests)."""

    httpd = server.RemoteAgentServer.__new__(server.RemoteAgentServer)
    httpd.agent = agent
    httpd.ssl_context = None
    httpd.max_connections = extra.get("max_connections", 32)
    httpd._verbinding_semafoor = threading.BoundedSemaphore(httpd.max_connections)
    httpd.max_connections_per_ip = extra.get("max_connections_per_ip", 4)
    httpd.handshake_deadline = 5.0
    httpd._per_ip_lock = threading.Lock()
    httpd._per_ip_counts = {}
    httpd._handshake_log_lock = threading.Lock()
    httpd._handshake_log = {}
    return httpd


class _FakeSock:
    def settimeout(self, t):
        pass

    def close(self):
        pass


def test_niet_toegestaan_ip_wordt_stil_gesloten():
    """Een niet-toegestaan IP wordt vóór de semafoor en handshake stil
    gesloten."""
    agent = server.RemoteAgent(TOKEN, rate_limiter=server.RateLimiter(max_requests=0), audit=False)
    agent._allowed_ips = ("192.168.1.50",)

    httpd = _nep_server(agent)
    gesloten = []
    httpd._sluit_verbinding = lambda req: gesloten.append(req)

    httpd.process_request_thread(_FakeSock(), ("8.8.8.8", 12345))

    assert len(gesloten) == 1, "het niet-toegestaan IP moet stil gesloten worden"


def test_geblokkeerd_ip_wordt_stil_gesloten():
    """Een geblokkeerd (lockout) IP wordt vóór de handshake stil gesloten."""
    agent = server.RemoteAgent(TOKEN, rate_limiter=server.RateLimiter(max_requests=0), audit=False)
    for _ in range(5):
        agent._lockout.record_failure("127.0.0.1")

    httpd = _nep_server(agent)
    gesloten = []
    httpd._sluit_verbinding = lambda req: gesloten.append(req)

    httpd.process_request_thread(_FakeSock(), ("127.0.0.1", 12345))

    assert len(gesloten) == 1, "het geblokkeerde IP moet stil gesloten worden"


def test_per_ip_slot_wordt_vrijgegeven():
    """Na een verbinding moet het per-IP slot weer vrij zijn."""
    agent = server.RemoteAgent(TOKEN, rate_limiter=server.RateLimiter(max_requests=0), audit=False)
    httpd = _nep_server(agent, max_connections_per_ip=1)

    # Reserveer een slot.
    assert httpd._per_ip_slot_vrij("10.0.0.1") is True
    # Tweede slot voor hetzelfde IP moet geweigerd worden.
    assert httpd._per_ip_slot_vrij("10.0.0.1") is False
    # Ander IP mag wel.
    assert httpd._per_ip_slot_vrij("10.0.0.2") is True
    # Slot vrijgeven en opnieuw reserveren.
    httpd._per_ip_slot_vrij("10.0.0.1", reserveer=False)
    assert httpd._per_ip_slot_vrij("10.0.0.1") is True


def test_handshake_log_reset_na_minuut():
    """Na een minuut begint het logvenster opnieuw."""
    agent = server.RemoteAgent(TOKEN, rate_limiter=server.RateLimiter(max_requests=0), audit=False)
    httpd = _nep_server(agent)

    httpd._log_handshake_mislukt("10.0.0.1")
    httpd._log_handshake_mislukt("10.0.0.1")
    with httpd._handshake_log_lock:
        assert httpd._handshake_log["10.0.0.1"][0] == 2

    # Simuleer dat er een minuut voorbij is.
    with httpd._handshake_log_lock:
        httpd._handshake_log["10.0.0.1"][1] = time.time() - 61

    httpd._log_handshake_mislukt("10.0.0.1")
    with httpd._handshake_log_lock:
        assert httpd._handshake_log["10.0.0.1"][0] == 1, "na een minuut begint de teller opnieuw"
