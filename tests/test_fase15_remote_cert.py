"""Tests voor scripts/gen_remote_cert.py (Fase 15, stap 6).

We laden het script als losse module (het is geen onderdeel van een
pakket) en testen het genereren van het zelfondertekende certificaat,
de validatie en de foutafhandeling.

Let op: we gebruiken bewust ``tempfile.mkdtemp`` in plaats van de
``tmp_path``-fixture, vanwege een bekende Windows-kwestie met de
``pytest-current``-symbolische koppeling.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

try:  # pragma: no cover - afhankelijk van de omgeving
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(
    not HAS_CRYPTO, reason="cryptography is niet geïnstalleerd"
)


@pytest.fixture(scope="module")
def gencert():
    """Laadt scripts/gen_remote_cert.py als module."""

    pad = SCRIPTS / "gen_remote_cert.py"
    spec = importlib.util.spec_from_file_location("gen_remote_cert", pad)
    module = importlib.util.module_from_spec(spec)
    # Registreer de module, anders kan dataclasses de modulenaamruimte
    # niet vinden bij het verwerken van de dataclass-annotaties.
    sys.modules["gen_remote_cert"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def werkmap():
    """Tijdelijke map die na de test netjes wordt opgeruimd."""

    pad = tempfile.mkdtemp(prefix="jarvis_cert_")
    try:
        yield Path(pad)
    finally:
        shutil.rmtree(pad, ignore_errors=True)


def _main(module, argumenten):
    """Roept main() aan en vertaalt SystemExit naar een exitcode."""

    try:
        return module.main(argumenten)
    except SystemExit as afsluiting:  # argparse-fouten
        return afsluiting.code if isinstance(afsluiting.code, int) else 1


# ------------------------------------------------------------------
# Genereren
# ------------------------------------------------------------------


@requires_crypto
def test_genereert_certificaat_en_sleutel(gencert, werkmap):
    code = _main(gencert, ["--out-dir", str(werkmap)])

    assert code == gencert.EXIT_OK

    cert_pad = werkmap / gencert.DEFAULT_CERT_NAME
    key_pad = werkmap / gencert.DEFAULT_KEY_NAME

    assert cert_pad.is_file()
    assert key_pad.is_file()
    assert cert_pad.stat().st_size > 0
    assert key_pad.stat().st_size > 0


@requires_crypto
def test_certificaat_heeft_juiste_common_name_en_san(gencert, werkmap):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID, NameOID

    cert = x509.load_pem_x509_certificate(
        (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes()
    )

    naam = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert naam == gencert.DEFAULT_COMMON_NAME

    san = cert.extensions.get_extension_for_oid(
        ExtensionOID.SUBJECT_ALTERNATIVE_NAME
    ).value

    dns_namen = san.get_values_for_type(x509.DNSName)
    ip_adressen = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]

    assert "localhost" in dns_namen
    assert "127.0.0.1" in ip_adressen


@requires_crypto
def test_extra_host_en_ip_komen_in_de_san(gencert, werkmap):
    code = _main(
        gencert,
        [
            "--out-dir",
            str(werkmap),
            "--host",
            "game-pc.local",
            "--ip",
            "192.168.2.79",
        ],
    )
    assert code == gencert.EXIT_OK

    from cryptography import x509

    cert = x509.load_pem_x509_certificate(
        (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes()
    )
    san = cert.extensions.get_extension_for_oid(
        x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME
    ).value

    assert "game-pc.local" in san.get_values_for_type(x509.DNSName)
    assert "192.168.2.79" in [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]


@requires_crypto
def test_certificaat_is_zelfondertekend(gencert, werkmap):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    from cryptography import x509

    cert = x509.load_pem_x509_certificate(
        (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes()
    )

    assert cert.issuer == cert.subject
    assert cert.version == x509.Version.v3


@requires_crypto
def test_sleutel_is_een_geldige_privrsleutel(gencert, werkmap):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    from cryptography.hazmat.primitives import serialization

    sleutel = serialization.load_pem_private_key(
        (werkmap / gencert.DEFAULT_KEY_NAME).read_bytes(), password=None
    )
    assert sleutel.key_size == gencert.DEFAULT_BITS


# ------------------------------------------------------------------
# Overschrijven
# ------------------------------------------------------------------


@requires_crypto
def test_weigert_te_overschrijven_zonder_force(gencert, werkmap):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    voor = (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes()
    code = _main(gencert, ["--out-dir", str(werkmap)])

    assert code == gencert.EXIT_EXISTS
    assert (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes() == voor


@requires_crypto
def test_force_overschrijft_bestaande_bestanden(gencert, werkmap):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK
    voor = (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes()

    code = _main(gencert, ["--out-dir", str(werkmap), "--force"])

    assert code == gencert.EXIT_OK
    na = (werkmap / gencert.DEFAULT_CERT_NAME).read_bytes()
    assert na != voor  # nieuwe sleutel -> nieuw certificaat


# ------------------------------------------------------------------
# Validatie / foutafhandeling
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "argumenten",
    [
        ["--days", "0"],
        ["--days", "-5"],
        ["--bits", "1024"],
        ["--host", "foute host!"],
        ["--host", ""],
        ["--ip", "geen-ip"],
        ["--name", "  "],
    ],
)
def test_ongeldige_argumenten_geven_een_foutcode(gencert, werkmap, argumenten):
    code = _main(gencert, ["--out-dir", str(werkmap)] + argumenten)

    # 1 = EXIT_USAGE (validatiefout), 2 = argparse-fout
    assert code in (gencert.EXIT_USAGE, 2)
    assert not (werkmap / gencert.DEFAULT_CERT_NAME).exists()


def test_validate_functies_bestaan(gencert):
    assert gencert.validate_days(30) == 30
    assert gencert.validate_bits(2048) == 2048
    assert gencert.validate_common_name("agent") == "agent"
    assert gencert.validate_host("localhost") == "localhost"
    assert gencert.validate_ip("127.0.0.1") == "127.0.0.1"

    with pytest.raises(gencert.ValidatieFout):
        gencert.validate_days(0)
    with pytest.raises(gencert.ValidatieFout):
        gencert.validate_days(99999)
    with pytest.raises(gencert.ValidatieFout):
        gencert.validate_bits(1024)
    with pytest.raises(gencert.ValidatieFout):
        gencert.validate_common_name("")
    with pytest.raises(gencert.ValidatieFout):
        gencert.validate_host("heeft spaties")
    with pytest.raises(gencert.ValidatieFout):
        gencert.validate_ip("niet-een-ip")


# ------------------------------------------------------------------
# Geheimen
# ------------------------------------------------------------------


@requires_crypto
def test_uitvoer_bevat_geen_sleutelmateriaal(gencert, werkmap, capsys):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    uitgevoerd = capsys.readouterr()
    alles = uitgevoerd.out + uitgevoerd.err

    assert "PRIVATE KEY" not in alles
    assert "BEGIN" not in alles


@requires_crypto
def test_uitvoer_noemt_het_juiste_bestandspad(gencert, werkmap, capsys):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    uitgevoerd = capsys.readouterr()
    assert gencert.DEFAULT_CERT_NAME in uitgevoerd.out


@pytest.mark.skipif(os.name == "nt", reason="POSIX-rechten gelden niet op Windows")
@requires_crypto
def test_privrsleutel_is_alleen_voor_de_gebruiker(gencert, werkmap):
    assert _main(gencert, ["--out-dir", str(werkmap)]) == gencert.EXIT_OK

    rechten = os.stat(werkmap / gencert.DEFAULT_KEY_NAME).st_mode & 0o777
    assert rechten == 0o600


def test_ontbrekende_cryptography_geeft_duidelijke_fout(gencert, werkmap, monkeypatch):
    # sys.modules op None zetten laat een 'import cryptography' mislukken.
    monkeypatch.setitem(sys.modules, "cryptography", None)

    code = _main(gencert, ["--out-dir", str(werkmap)])

    assert code == gencert.EXIT_MISSING_DEP


def test_ontbrekende_cryptography_noemt_openssl_alternatief(
    gencert, werkmap, monkeypatch, capsys
):
    monkeypatch.setitem(sys.modules, "cryptography", None)

    _main(gencert, ["--out-dir", str(werkmap)])

    # De gebruiker krijgt een alternatief aangereikt.
    uitgevoerd = capsys.readouterr()
    assert "openssl" in (uitgevoerd.out + uitgevoerd.err).lower()


def test_help_werkt(gencert, capsys):
    code = _main(gencert, ["--help"])

    # argparse print de help en sluit af met 0
    assert code in (gencert.EXIT_OK, 0)
    uitgevoerd = capsys.readouterr()
    assert "--out-dir" in uitgevoerd.out
    assert "--force" in uitgevoerd.out
