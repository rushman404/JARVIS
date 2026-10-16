"""Fase 15 — tests voor remote/protocol.py (HMAC + replay-bescherming).

Dekt:
    - geldige en ongeldige handtekeningen;
    - ontbrekende tokens;
    - ongeldige tijdstempels (te oud, in de toekomst, niet-numeriek);
    - hergebruikte nonces (replay);
    - dat pad en methode echt meetellen in de handtekening.
"""

import time

import pytest

from remote import protocol

TOKEN = "geheim-token-0000000000000000"  # 32 tekens


def _maak_headers(body=b"", ts=None, nonce="nonce-vast", method="POST", path="/command"):
    return protocol.signed_headers(
        TOKEN, method, path, body, timestamp=ts, nonce=nonce
    )


def test_geldige_handtekening_verifieert():
    ts = int(time.time())
    headers = _maak_headers(body=b'{"tool":"pc_status"}', ts=ts)

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b'{"tool":"pc_status"}',
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
    )

    assert ok is True
    assert reden == ""


def test_aangepaste_body_geeft_bad_signature():
    ts = int(time.time())
    headers = _maak_headers(body=b'{"tool":"pc_status"}', ts=ts)

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b'{"tool":"shutdown_pc"}',  # body stiekem gewijzigd
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
    )

    assert ok is False
    assert reden == "bad_signature"


def test_verkeerd_token_faalt():
    ts = int(time.time())
    headers = _maak_headers(ts=ts)

    ok, reden = protocol.verify_request(
        "ander-token-00000000000000000000",
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
    )

    assert ok is False
    assert reden == "bad_signature"


def test_ontbrekend_token_wordt_geweigerd():
    tools = [None, "", "   "]

    for token in tools:
        ok, reden = protocol.verify_request(
            token, "POST", "/command", "123", "n", b"", "sig"
        )
        assert ok is False
        assert reden == "no_token"


def test_ontbrekende_handtekening():
    ts = int(time.time())

    ok, reden = protocol.verify_request(
        TOKEN, "POST", "/command", str(ts), "nonce", b"", ""
    )

    assert ok is False
    assert reden == "missing_signature"


def test_ontbrekende_timestamp_of_nonce():
    ts = int(time.time())

    ok, reden = protocol.verify_request(
        TOKEN, "POST", "/command", None, "nonce", b"", "sig"
    )
    assert ok is False
    assert reden == "missing_headers"

    ok, reden = protocol.verify_request(
        TOKEN, "POST", "/command", str(ts), "", b"", "sig"
    )
    assert ok is False
    assert reden == "missing_headers"


def test_niet_numerieke_timestamp():
    ok, reden = protocol.verify_request(
        TOKEN, "POST", "/command", "geen-getal", "nonce", b"", "sig"
    )

    assert ok is False
    assert reden == "bad_timestamp"


def test_timestamp_te_oud_is_stale():
    now = int(time.time())
    oud = now - 3600
    headers = _maak_headers(ts=oud)

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=now,
        window=30,
    )

    assert ok is False
    assert reden == "stale_timestamp"


def test_timestamp_in_de_toekomst():
    now = int(time.time())
    toekomst = now + 3600
    headers = _maak_headers(ts=toekomst)

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=now,
        window=30,
    )

    assert ok is False
    assert reden == "future_timestamp"


def test_hergebruikte_nonce_wordt_geweigerd():
    ts = int(time.time())
    store = protocol.NonceStore(window_seconds=30)
    headers = _maak_headers(ts=ts)

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
        nonce_store=store,
    )
    assert (ok, reden) == (True, "")

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
        nonce_store=store,
    )
    assert ok is False
    assert reden == "replayed_nonce"


def test_nonce_wordt_niet_verbruikt_bij_slechte_handtekening():
    """Een aanvaller mag de nonce-store niet volproppen met ongeldige handtekeningen."""

    ts = int(time.time())
    store = protocol.NonceStore(window_seconds=30)
    headers = _maak_headers(ts=ts)

    # Eerst een poging met een ongeldige handtekening.
    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        "doodbeest",
        now=ts,
        nonce_store=store,
    )
    assert ok is False
    assert reden == "bad_signature"
    assert len(store) == 0

    # Dezelfde nonce met een geldige handtekening moet nog steeds werken.
    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
        nonce_store=store,
    )
    assert (ok, reden) == (True, "")


def test_handtekening_is_aan_pad_gebonden():
    ts = int(time.time())
    headers = _maak_headers(path="/command", ts=ts)

    ok, reden = protocol.verify_request(
        TOKEN,
        "POST",
        "/status",  # ander pad
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
    )

    assert ok is False
    assert reden == "bad_signature"


def test_handtekening_is_aan_methode_gebonden():
    ts = int(time.time())
    headers = _maak_headers(method="POST", ts=ts)

    ok, reden = protocol.verify_request(
        TOKEN,
        "GET",  # andere methode
        "/command",
        headers[protocol.HEADER_TIMESTAMP],
        headers[protocol.HEADER_NONCE],
        b"",
        headers[protocol.HEADER_SIGNATURE],
        now=ts,
    )

    assert ok is False
    assert reden == "bad_signature"


def test_nonce_store_ruimt_verlopen_nonces_op():
    store = protocol.NonceStore(window_seconds=10)

    assert store.check_and_store("a", now=1000) is True
    assert store.check_and_store("b", now=1000) is True
    assert len(store) == 2

    # Ver vooruit: beide nonces zijn verlopen.
    assert store.check_and_store("c", now=2000) is True
    assert len(store) == 1


def test_canonieke_string_bevat_alle_velden():
    tekst = protocol.build_canonical_string(
        "post", "/command", "1700000000", "nonce1", b"x"
    )
    velden = tekst.split("\n")

    assert velden[0] == "POST"
    assert velden[1] == "/command"
    assert velden[2] == "1700000000"
    assert velden[3] == "nonce1"
    assert velden[4] == protocol.body_digest(b"x")


def test_ondertekenen_zonder_token_is_fout():
    with pytest.raises(ValueError):
        protocol.sign("", "POST", "/command", "1", "n", b"")


def test_body_codec_roundtrip():
    payload = {"tool": "set_volume", "arguments": {"percent": 40}}
    raw = protocol.encode_body(payload)

    assert isinstance(raw, bytes)
    assert protocol.decode_body(raw) == payload


def test_body_codec_weigert_niet_object():
    with pytest.raises(ValueError):
        protocol.decode_body(b"[1, 2, 3]")


def test_lege_body_decodeert_naar_lege_dict():
    assert protocol.decode_body(b"") == {}
    assert protocol.decode_body(None) == {}
