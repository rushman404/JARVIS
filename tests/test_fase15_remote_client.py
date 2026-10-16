"""Fase 15 — tests voor remote/client.py.

Dekt:
    - succesvolle communicatie met een testserver (TLS);
    - verkeerd certificaat, verkeerde token en ongeldige response;
    - server niet bereikbaar, time-out en verbroken verbinding;
    - correcte requestondertekening en verwerking van resultaten;
    - geen onveilige retry van niet-idempotente acties.
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

import pytest

import core.audit as core_audit
from remote import client as client_module, protocol, server

TOKEN = "s" * 32


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def audit_bestand(monkeypatch):
    """Houd audit-schrijfsels buiten het echte logbestand."""

    map_ = tempfile.mkdtemp(prefix="jarvis_audit_c_")
    monkeypatch.setattr(core_audit, "AUDIT_FILE", os.path.join(map_, "audit.jsonl"))
    yield
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
def certs():
    """Levert twee onafhankelijke zelfondertekende certificaten."""

    if importlib.util.find_spec("cryptography") is None:
        pytest.skip("cryptography niet beschikbaar voor TLS-tests")

    map_ = tempfile.mkdtemp(prefix="jarvis_certs_")
    paden = {}
    for naam in ("a", "b"):
        cert = os.path.join(map_, f"{naam}.pem")
        key = os.path.join(map_, f"{naam}.key")
        _maak_selfsigned_cert(cert, key)
        paden[naam] = (cert, key)
    try:
        yield paden
    finally:
        shutil.rmtree(map_, ignore_errors=True)


@pytest.fixture
def start_server():
    gestart = []

    def _start(cert, key, dispatch=None):
        httpd = server.create_server(
            host="127.0.0.1",
            port=0,
            token=TOKEN,
            cert_file=cert,
            key_file=key,
            dispatch=dispatch or (lambda tool, argumenten, question: "gedaan"),
            rate_limiter=server.RateLimiter(max_requests=0),
            audit=False,
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        gestart.append((httpd, thread))
        return httpd.server_address[1]

    yield _start

    for httpd, thread in gestart:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _client(cert, poort, **kwargs):
    kwargs.setdefault("host", "127.0.0.1")
    kwargs.setdefault("token", TOKEN)
    kwargs.setdefault("ca_file", cert)
    kwargs.setdefault("backoff", 0)
    return client_module.RemoteClient(port=poort, **kwargs)


def _vrije_poort():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    poort = sock.getsockname()[1]
    sock.close()
    return poort


# ---------------------------------------------------------------
# Configuratie — fail-closed
# ---------------------------------------------------------------

def test_client_weigert_zonder_vertrouwd_certificaat():
    with pytest.raises(ValueError):
        client_module.RemoteClient(host="127.0.0.1", token=TOKEN, ca_file="")


def test_client_weigert_zonder_token(certs):
    cert, _ = certs["a"]
    with pytest.raises(ValueError):
        client_module.RemoteClient(host="127.0.0.1", token="", ca_file=cert)


def test_client_weigert_te_kort_token(certs):
    cert, _ = certs["a"]
    with pytest.raises(ValueError):
        client_module.RemoteClient(host="127.0.0.1", token="kort", ca_file=cert)


def test_client_weigert_ongeldig_certificaatbestand():
    map_ = tempfile.mkdtemp(prefix="jarvis_badca_")
    bestand = os.path.join(map_, "ca.pem")
    try:
        with open(bestand, "w", encoding="utf-8") as f:
            f.write("geen certificaat")

        with pytest.raises(ValueError):
            client_module.RemoteClient(host="127.0.0.1", token=TOKEN, ca_file=bestand)
    finally:
        shutil.rmtree(map_, ignore_errors=True)


def test_loopback_wordt_gemarkeerd(certs):
    cert, _ = certs["a"]
    lokaal = client_module.RemoteClient(host="127.0.0.1", token=TOKEN, ca_file=cert)
    extern = client_module.RemoteClient(host="192.168.1.50", token=TOKEN, ca_file=cert)

    assert lokaal.is_loopback() is True
    assert extern.is_loopback() is False


def test_certificaatcontrole_staat_aan(certs):
    cert, _ = certs["a"]
    client_ = client_module.RemoteClient(host="127.0.0.1", token=TOKEN, ca_file=cert)
    context = client_._ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


# ---------------------------------------------------------------
# Succesvolle communicatie
# ---------------------------------------------------------------

def test_health_succes(certs, start_server):
    cert, key = certs["a"]
    poort = start_server(cert, key)
    client_ = _client(cert, poort)

    resultaat = client_.health()

    assert resultaat.ok is True
    assert resultaat.status == 200
    assert bool(resultaat) is True


def test_is_online(certs, start_server):
    cert, key = certs["a"]
    poort = start_server(cert, key)

    assert _client(cert, poort).is_online() is True


def test_send_command_geldig(certs, start_server):
    cert, key = certs["a"]
    gezien = []

    def dispatch(tool, argumenten, question):
        gezien.append((tool, argumenten, question))
        return "Cyberpunk 2077 gestart"

    poort = start_server(cert, key, dispatch=dispatch)
    client_ = _client(cert, poort)

    resultaat = client_.send_command("open_program", {"program": "Cyberpunk 2077"}, question="start cyberpunk")

    assert resultaat.ok is True
    assert resultaat.status == 200
    assert resultaat.resultaat == "Cyberpunk 2077 gestart"
    assert gezien == [("open_program", {"program": "Cyberpunk 2077"}, "start cyberpunk")]


def test_gestructureerd_resultaat(certs, start_server):
    cert, key = certs["a"]

    class NepResultaat:
        ok = True
        message = "klaar"
        data = {"temperatuur": 45}

    poort = start_server(cert, key, dispatch=lambda tool, argumenten, question: NepResultaat())
    client_ = _client(cert, poort)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is True
    assert resultaat.resultaat == {"ok": True, "message": "klaar", "data": {"temperatuur": 45}}


# ---------------------------------------------------------------
# Fouten van de server
# ---------------------------------------------------------------

def test_verkeerd_token(certs, start_server):
    cert, key = certs["a"]
    poort = start_server(cert, key)
    client_ = _client(cert, poort, token="w" * 32)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert resultaat.status == 401
    assert resultaat.fout_code == "niet_geautoriseerd"


def test_verkeerd_certificaat_wordt_geweigerd(certs, start_server):
    cert_a, key_a = certs["a"]
    cert_b, _ = certs["b"]
    poort = start_server(cert_a, key_a)
    # Client vertrouwt certificaat B, server presenteert A.
    client_ = _client(cert_b, poort, max_retries=3)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_TLS
    assert resultaat.pogingen == 1, "een TLS-fout mag nooit opnieuw geprobeerd worden"


def test_niet_bereikbare_server(certs):
    cert, _ = certs["a"]
    client_ = _client(cert, _vrije_poort(), max_retries=1)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_NIET_BEREIKBAAR
    assert resultaat.lokaal is True
    assert resultaat.pogingen == 2  # idempotent: 1 herhaling


def test_time_out(certs):
    cert, _ = certs["a"]

    luister = socket.socket()
    luister.bind(("127.0.0.1", 0))
    luister.listen(5)
    poort = luister.getsockname()[1]
    stop = threading.Event()
    open_verbindingen = []

    def loop():
        luister.settimeout(0.2)
        while not stop.is_set():
            try:
                verbinding, _ = luister.accept()
                # Accepteer, maar antwoord nooit: houd de verbinding open
                # zodat de client in een time-out loopt.
                open_verbindingen.append(verbinding)
            except (socket.timeout, OSError):
                continue

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    try:
        client_ = _client(cert, poort, timeout=0.3, max_retries=1)
        resultaat = client_.send_command("pc_status", {})
    finally:
        stop.set()
        luister.close()
        for verbinding in open_verbindingen:
            try:
                verbinding.close()
            except OSError:
                pass
        thread.join(timeout=2)

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_TIMEOUT


def test_verbroken_verbinding(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)

    def kapot(method, path, body=b""):
        raise http.client.RemoteDisconnected("verbinding weg")

    monkeypatch.setattr(client_, "_do_request", kapot)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_VERBROKEN


@pytest.mark.parametrize(
    "ruwe_body",
    [b"", b"<html>geen json</html>", b'{"ok": "ja"}', b"[1, 2, 3]", b"{kapot"],
)
def test_ongeldig_antwoord(certs, monkeypatch, ruwe_body):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)
    monkeypatch.setattr(client_, "_do_request", lambda method, path, body=b"": (200, ruwe_body))

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_ONGELDIG_ANTWOORD


def test_fout_envelope_van_server(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)
    body = json.dumps(
        {"ok": False, "fout": {"code": "niet_toegestaan", "melding": "mag niet"}}
    ).encode("utf-8")
    monkeypatch.setattr(
        client_,
        "_do_request",
        lambda method, path, body=b"", antwoord=body: (403, antwoord),
    )

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert resultaat.status == 403
    assert resultaat.fout_code == "niet_toegestaan"
    assert resultaat.fout_melding == "mag niet"


# ---------------------------------------------------------------
# Ondertekening en validatie
# ---------------------------------------------------------------

def test_ondertekening_verifieert(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)
    vastgelegd = {}

    def tussenstap(method, path, body=b""):
        headers = protocol.signed_headers(client_.token, method, path, body)
        ok, reden = protocol.verify_request(
            TOKEN, method, path,
            headers[protocol.HEADER_TIMESTAMP],
            headers[protocol.HEADER_NONCE],
            body,
            headers[protocol.HEADER_SIGNATURE],
        )
        vastgelegd["ok"] = ok
        vastgelegd["reden"] = reden
        return 200, b'{"ok": true}'

    monkeypatch.setattr(client_, "_do_request", tussenstap)
    client_.send_command("pc_status", {})

    assert vastgelegd["ok"] is True, vastgelegd["reden"]


def test_actie_lokaal_gevalideerd(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)
    geraakt = []
    monkeypatch.setattr(
        client_, "_do_request", lambda method, path, body=b"": geraakt.append(1) or (200, b'{"ok": true}')
    )

    resultaat = client_.send_command("open_file", {"filename": "C:\\geheim.txt"})

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_NIET_TOEGESTAAN
    assert resultaat.pogingen == 0
    assert geraakt == [], "een niet-toegestane actie mag de server niet bereiken"


def test_vereiste_parameter_ontbreekt_lokaal(certs):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)

    resultaat = client_.send_command("open_program", {})

    assert resultaat.ok is False
    assert resultaat.fout_code == client_module.FOUT_NIET_TOEGESTAAN


# ---------------------------------------------------------------
# Retry-gedrag
# ---------------------------------------------------------------

def test_idempotente_actie_wordt_herhaald(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765, max_retries=1)
    pogingen = {"n": 0}

    def eerste_keer_fout(method, path, body=b""):
        pogingen["n"] += 1
        if pogingen["n"] == 1:
            raise ConnectionRefusedError("nog niet bereikbaar")
        return 200, b'{"ok": true, "resultaat": "gelukt"}'

    monkeypatch.setattr(client_, "_do_request", eerste_keer_fout)

    resultaat = client_.send_command("pc_status", {})  # idempotent

    assert resultaat.ok is True
    assert resultaat.pogingen == 2


def test_niet_idempotente_actie_wordt_niet_herhaald(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765, max_retries=3)
    pogingen = {"n": 0}

    def altijd_fout(method, path, body=b""):
        pogingen["n"] += 1
        raise ConnectionRefusedError("weg")

    monkeypatch.setattr(client_, "_do_request", altijd_fout)

    resultaat = client_.send_command("media_play_pause", {})  # NIET idempotent

    assert resultaat.ok is False
    assert resultaat.pogingen == 1
    assert pogingen["n"] == 1, "een niet-idempotente actie mag nooit herhaald worden"


def test_niet_idempotent_bij_retrybare_status(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765, max_retries=2)
    pogingen = {"n": 0}

    def altijd_503(method, path, body=b""):
        pogingen["n"] += 1
        return 503, b'{"ok": false, "fout": {"code": "interne_fout", "melding": "bezet"}}'

    monkeypatch.setattr(client_, "_do_request", altijd_503)

    resultaat = client_.send_command("media_play_pause", {})

    assert resultaat.ok is False
    assert pogingen["n"] == 1, "geen retry voor niet-idempotente actie, ook niet bij 503"


def test_idempotent_bij_retrybare_status_wel_herhaald(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765, max_retries=2)
    pogingen = {"n": 0}

    def altijd_503(method, path, body=b""):
        pogingen["n"] += 1
        return 503, b'{"ok": false, "fout": {"code": "interne_fout", "melding": "bezet"}}'

    monkeypatch.setattr(client_, "_do_request", altijd_503)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.ok is False
    assert pogingen["n"] == 3  # 1 + 2 retries


def test_tls_fout_nooit_herhaald(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765, max_retries=3)
    pogingen = {"n": 0}

    def tls_fout(method, path, body=b""):
        pogingen["n"] += 1
        raise ssl.SSLError("certificaat klopt niet")

    monkeypatch.setattr(client_, "_do_request", tls_fout)

    resultaat = client_.send_command("pc_status", {})

    assert resultaat.fout_code == client_module.FOUT_TLS
    assert pogingen["n"] == 1


# ---------------------------------------------------------------
# Samenvatting
# ---------------------------------------------------------------

def test_samenvatting_bij_succes(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765)
    monkeypatch.setattr(client_, "_do_request", lambda method, path, body=b"": (200, b'{"ok": true, "resultaat": "Hallo daar"}'))

    assert client_.send_command("pc_status", {}).samenvatting() == "Hallo daar"


def test_samenvatting_bij_fout(certs, monkeypatch):
    cert, _ = certs["a"]
    client_ = _client(cert, 8765, max_retries=0)

    def weg(method, path, body=b""):
        raise ConnectionRefusedError("weg")

    monkeypatch.setattr(client_, "_do_request", weg)

    tekst = client_.send_command("pc_status", {}).samenvatting()

    assert "niet bereikbaar" in tekst.lower()
