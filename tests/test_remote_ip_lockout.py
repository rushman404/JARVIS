"""Fase 15 — IP-allowlist en lockout voor de remote-agent.

De server weigert verbindingen vanaf adressen die niet zijn toegestaan
(standaard alleen privé-adressen), en blokkeert een IP dat te vaak een
verkeerde handtekening stuurt.
"""

import pytest

import config
from remote import protocol
from remote.server import RemoteAgent, AuthLockout


TOKEN = "x" * 32


def _agent(**kwargs):
    """Een test-agent zonder echte dispatch (er wordt niets uitgevoerd)."""

    return RemoteAgent(TOKEN, audit=False, **kwargs)


def _onderteken(method, path, body=b"", now=None, token=TOKEN):
    """Bouwt ondertekende headers voor een request."""

    return protocol.signed_headers(
        token, method, path, body, timestamp=int(now if now is not None else 0)
    )


# ------------------------------------------------------------------
# IP-allowlist
# ------------------------------------------------------------------


@pytest.mark.parametrize("ip", ["192.168.1.10", "10.0.0.5", "172.16.0.9", "127.0.0.1"])
def test_privé_adres_is_toegestaan_zonder_lijst(ip):
    agent = _agent()
    headers = _onderteken("GET", "/health", b"", now=0)
    status, _ = agent.process("GET", "/health", headers, b"", client_ip=ip, now=0)
    assert status == 200


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_publiek_adres_wordt_altijd_geweigerd(ip):
    agent = _agent()
    headers = _onderteken("GET", "/health", b"", now=0)
    status, _ = agent.process("GET", "/health", headers, b"", client_ip=ip, now=0)
    assert status == 403


def test_lijst_van_ip_adressen_wordt_gehonoreerd():
    agent = _agent()
    # allowlist injecteren zoals create_server dat doet
    agent._allowed_ips = ("192.168.1.50",)
    headers = _onderteken("GET", "/health", b"", now=0)
    ok, _ = agent.process("GET", "/health", headers, b"", client_ip="192.168.1.50", now=0)
    assert ok == 200
    nee, _ = agent.process("GET", "/health", headers, b"", client_ip="192.168.1.51", now=0)
    assert nee == 403


def test_config_parseert_allowed_ips(monkeypatch):
    assert config._parse_ips("192.168.1.50, 10.0.0.9") == ("192.168.1.50", "10.0.0.9")
    assert config._parse_ips("") == ()
    assert config._parse_ips(None) == ()


# ------------------------------------------------------------------
# Lockout
# ------------------------------------------------------------------


def test_lockout_blokkeert_na_vijf_mislukte_authenticaties():
    lockout = AuthLockout(max_failures=5, window_seconds=60, lockout_seconds=300)
    for _ in range(4):
        lockout.record_failure("192.168.1.7", now=1000.0)
    assert not lockout.is_blocked("192.168.1.7", now=1000.0)

    lockout.record_failure("192.168.1.7", now=1000.0)
    assert lockout.is_blocked("192.168.1.7", now=1000.0)


def test_lockout_verloopt_na_de_blokketijd():
    lockout = AuthLockout(max_failures=5, window_seconds=60, lockout_seconds=300)
    for _ in range(5):
        lockout.record_failure("192.168.1.7", now=1000.0)
    assert lockout.is_blocked("192.168.1.7", now=1100.0)
    assert not lockout.is_blocked("192.168.1.7", now=1000.0 + 301)


def test_lockout_telt_per_ip():
    lockout = AuthLockout(max_failures=5, window_seconds=60, lockout_seconds=300)
    for _ in range(5):
        lockout.record_failure("192.168.1.7", now=1000.0)
    assert not lockout.is_blocked("192.168.1.8", now=1000.0)


def test_lockout_wordt_gereset_na_geslaagde_authenticatie():
    agent = _agent()
    lockout = agent._lockout
    ip = "192.168.1.9"
    for _ in range(4):
        lockout.record_failure(ip, now=1000.0)

    # een geldig verzoek
    headers = _onderteken("GET", "/health", b"", now=1000.0)
    status, _ = agent.process("GET", "/health", headers, b"", client_ip=ip, now=1000.0)
    assert status == 200
    assert not lockout.is_blocked(ip, now=1000.0)


def test_foute_handtekening_blokkeert_ip_na_vijf_keer():
    agent = _agent()
    ip = "192.168.1.11"
    for i in range(5):
        headers = _onderteken("GET", "/health", b"", now=1000.0 + i)
        # verkeerde handtekening
        headers[protocol.HEADER_SIGNATURE] = "foute_handtekening"
        status, _ = agent.process("GET", "/health", headers, b"", client_ip=ip, now=1000.0 + i)
        assert status == 401

    # nu is het IP geblokkeerd: volgend verzoek wordt geweigerd
    headers = _onderteken("GET", "/health", b"", now=1010.0)
    status, _ = agent.process("GET", "/health", headers, b"", client_ip=ip, now=1010.0)
    assert status == 403
