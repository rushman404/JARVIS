"""Fase 15 — tests voor de remote-configuratie in config.py.

Dekt:
    - gescheiden server- en clientinstellingen;
    - veilige standaardwaarden (uit / lokaal);
    - fail-closed beveiligingscontrole: ontbrekende configuratie mag
      nooit tot een onbeschermde server leiden;
    - robuuste omgevingsvariabelen (onzin valt terug op de standaard).

Let op: bewust GEEN pytest `tmp_path` (die lokt op Windows een
permissie-fout bij het opruimen van de pytest-temp-symlink); we
beheren onze eigen tijdelijke map.
"""

import os
import shutil
import tempfile

import pytest

import config


@pytest.fixture
def cert_key():
    """Tijdelijke certificaat- en sleutelbestanden die echt bestaan."""

    map_ = tempfile.mkdtemp(prefix="jarvis_fase15_")
    cert = os.path.join(map_, "cert.pem")
    key = os.path.join(map_, "key.pem")

    with open(cert, "w", encoding="utf-8") as f:
        f.write("dummy-cert")
    with open(key, "w", encoding="utf-8") as f:
        f.write("dummy-key")

    yield cert, key

    shutil.rmtree(map_, ignore_errors=True)


# ---------------------------------------------------------------
# Gescheiden server- en clientinstellingen
# ---------------------------------------------------------------

def test_server_en_client_hebben_eigen_instellingen():
    assert hasattr(config, "REMOTE_SERVER_HOST")
    assert hasattr(config, "REMOTE_CLIENT_HOST")
    assert hasattr(config, "REMOTE_SERVER_TOKEN")
    assert hasattr(config, "REMOTE_CLIENT_TOKEN")

    # Het zijn echt aparte namen, niet per ongeluk hetzelfde attribuut.
    assert config.REMOTE_SERVER_HOST != config.REMOTE_CLIENT_HOST


def test_veilige_standaardwaarden():
    assert config.REMOTE_SERVER_ENABLED is False
    assert config.REMOTE_CLIENT_ENABLED is False

    # Client verbindt standaard alleen lokaal.
    assert config.REMOTE_CLIENT_HOST == "127.0.0.1"

    assert isinstance(config.REMOTE_SERVER_PORT, int)
    assert isinstance(config.REMOTE_CLIENT_PORT, int)
    assert isinstance(config.REMOTE_CLIENT_TIMEOUT, (int, float))


def test_replay_venster_is_gedeeld_met_protocol():
    from remote import protocol

    assert config.REMOTE_REPLAY_WINDOW_SECONDS == protocol.DEFAULT_REPLAY_WINDOW_SECONDS


# ---------------------------------------------------------------
# Omgevingsvariabelen: veilige parsers
# ---------------------------------------------------------------

def test_env_bool_herkent_ware_waarden(monkeypatch):
    for waarde in ("1", "true", "TRUE", "yes", "on", "On"):
        monkeypatch.setenv("JARVIS_TEST_VLAG", waarde)
        assert config._env_bool("JARVIS_TEST_VLAG") is True, waarde


def test_env_bool_herkent_onware_waarden(monkeypatch):
    for waarde in ("0", "false", "nee", "off", ""):
        monkeypatch.setenv("JARVIS_TEST_VLAG", waarde)
        assert config._env_bool("JARVIS_TEST_VLAG") is False, waarde


def test_env_bool_ontbrekend_gebruikt_default(monkeypatch):
    monkeypatch.delenv("JARVIS_TEST_VLAG", raising=False)
    assert config._env_bool("JARVIS_TEST_VLAG", default=True) is True


def test_env_int_valt_terug_op_default(monkeypatch):
    monkeypatch.setenv("JARVIS_TEST_GETAL", "geen-getal")
    assert config._env_int("JARVIS_TEST_GETAL", 99) == 99

    monkeypatch.setenv("JARVIS_TEST_GETAL", "42")
    assert config._env_int("JARVIS_TEST_GETAL", 99) == 42


def test_env_float_valt_terug_op_default(monkeypatch):
    monkeypatch.setenv("JARVIS_TEST_GETAL", "abc")
    assert config._env_float("JARVIS_TEST_GETAL", 1.5) == 1.5

    monkeypatch.setenv("JARVIS_TEST_GETAL", "2.5")
    assert config._env_float("JARVIS_TEST_GETAL", 1.5) == 2.5


# ---------------------------------------------------------------
# Fail-closed beveiligingscontrole
# ---------------------------------------------------------------

def test_uitgeschakelde_server_heeft_geen_fouten():
    assert config.remote_server_security_errors(enabled=False) == []


def test_ingeschakelde_server_zonder_beveiliging_is_fout():
    fouten = config.remote_server_security_errors(
        enabled=True, token="", cert_file="", key_file=""
    )

    assert fouten, "een onbeschermde server moet fouten opleveren"
    tekst = " ".join(fouten)
    assert "TOKEN" in tekst
    assert "CERT" in tekst
    assert "KEY" in tekst


def test_kort_token_wordt_geweigerd():
    fouten = config.remote_server_security_errors(
        enabled=True,
        token="kort",
        cert_file="c",
        key_file="k",
    )

    tekst = " ".join(fouten)
    assert "te kort" in tekst


def test_volledige_beveiliging_geeft_geen_fouten(cert_key):
    cert, key = cert_key

    fouten = config.remote_server_security_errors(
        enabled=True,
        token="x" * config.REMOTE_MIN_TOKEN_LENGTH,
        cert_file=cert,
        key_file=key,
    )

    assert fouten == []


def test_ontbrekend_certificaatbestand_is_fout(cert_key):
    _, key = cert_key
    ontbrekend = os.path.join(os.path.dirname(key), "bestaat-niet.pem")

    fouten = config.remote_server_security_errors(
        enabled=True,
        token="x" * config.REMOTE_MIN_TOKEN_LENGTH,
        cert_file=ontbrekend,
        key_file=key,
    )

    tekst = " ".join(fouten)
    assert "niet gevonden" in tekst


def test_token_grens_net_te_kort_en_net_goed_genoeg(cert_key):
    cert, key = cert_key

    te_kort = config.remote_server_security_errors(
        enabled=True,
        token="x" * (config.REMOTE_MIN_TOKEN_LENGTH - 1),
        cert_file=cert,
        key_file=key,
    )
    net_goed = config.remote_server_security_errors(
        enabled=True,
        token="x" * config.REMOTE_MIN_TOKEN_LENGTH,
        cert_file=cert,
        key_file=key,
    )

    assert te_kort, "net te kort token moet een fout geven"
    assert net_goed == []
