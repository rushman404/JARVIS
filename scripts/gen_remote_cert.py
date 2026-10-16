#!/usr/bin/env python3
"""Genereer een zelfondertekend TLS-certificaat + sleutel voor de Game-PC Agent.

De agent (``remote/server.py``) weigert te starten zonder een geldig
certificaat en een gedeeld geheim (token). Dit script maakt dat paar één
keer aan met de **dev-dependency** ``cryptography``.

Gebruik
-------
::

    python scripts/gen_remote_cert.py --host <ip-of-naam-van-de-game-pc>

Standaard komt het paar in ``certs/`` terecht (dat in ``.gitignore`` staat)
onder de namen ``agent-cert.pem`` en ``agent-key.pem``.

Beveiliging
-----------
* De **privésleutel** wordt nooit naar het scherm of naar een log geschreven;
  het script print alleen de paden en de SHA-256-vingerafdruk.
* Bestaande bestanden worden **niet** overschreven tenzij je ``--force`` geeft.
* Commit ``certs/`` nooit: ``.gitignore`` blokkeert het al.

Alternatief met OpenSSL (zie ``docs/remote_agent.md``)
------------------------------------------------------
::

    openssl req -x509 -newkey rsa:2048 -nodes \\
        -keyout agent-key.pem -out agent-cert.pem -days 825 \\
        -subj "/CN=jarvis-game-pc-agent" \\
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:<game-pc-ip>"
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ------------------------------------------------------------------
# Constanten
# ------------------------------------------------------------------

DEFAULT_OUT_DIR = "certs"
DEFAULT_CERT_NAME = "agent-cert.pem"
DEFAULT_KEY_NAME = "agent-key.pem"
DEFAULT_COMMON_NAME = "jarvis-game-pc-agent"
DEFAULT_DAYS = 825
DEFAULT_BITS = 2048
MIN_DAYS = 1
MAX_DAYS = 3650
ALLOWED_BITS = (2048, 3072, 4096)

# Altijd meenemen in de SAN, zodat lokale (loopback-)tests blijven werken.
STANDAARD_HOSTS = ("localhost",)
STANDAARD_IPS = ("127.0.0.1", "::1")

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_MISSING_DEP = 2
EXIT_EXISTS = 3

_GELDIGE_HOST_TEKENS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-."
)


class ValidatieFout(ValueError):
    """Ongeldige invoer (verkeerde dagen/naam/host/ip)."""


class BestandBestaat(Exception):
    """Doelbestand(en) bestaan al en ``--force`` is niet gegeven."""


class OntbrekendeAfhankelijkheid(Exception):
    """De module ``cryptography`` is niet geïnstalleerd."""


@dataclass
class Certificaat:
    cert_path: Path
    key_path: Path
    fingerprint: str


# ------------------------------------------------------------------
# Validatie
# ------------------------------------------------------------------


def validate_days(days):
    """Controleert het aantal geldigheidsdagen."""

    try:
        dagen = int(days)
    except (TypeError, ValueError) as fout:
        raise ValidatieFout(f"--days moet een geheel getal zijn, kreeg {days!r}.") from fout

    if dagen < MIN_DAYS or dagen > MAX_DAYS:
        raise ValidatieFout(
            f"--days moet tussen {MIN_DAYS} en {MAX_DAYS} liggen, kreeg {dagen}."
        )

    return dagen


def validate_bits(bits):
    """Controleert de RSA-sleutellengte."""

    try:
        waarde = int(bits)
    except (TypeError, ValueError) as fout:
        raise ValidatieFout(f"--bits moet een geheel getal zijn, kreeg {bits!r}.") from fout

    if waarde not in ALLOWED_BITS:
        toegestaan = ", ".join(str(b) for b in ALLOWED_BITS)
        raise ValidatieFout(
            f"--bits moet één van {toegestaan} zijn, kreeg {waarde}."
        )

    return waarde


def validate_common_name(naam):
    """Controleert de Common Name van het certificaat."""

    tekst = str(naam or "").strip()
    if not tekst:
        raise ValidatieFout("--name mag niet leeg zijn.")
    if len(tekst) > 64:
        raise ValidatieFout("--name mag maximaal 64 tekens zijn.")
    return tekst


def validate_host(host):
    """Controleert een DNS-naam voor de SAN."""

    tekst = str(host or "").strip()
    if not tekst:
        raise ValidatieFout("Een hostnaam mag niet leeg zijn.")
    if len(tekst) > 253:
        raise ValidatieFout(f"Hostnaam te lang: {tekst!r}.")
    if any(teken not in _GELDIGE_HOST_TEKENS for teken in tekst):
        raise ValidatieFout(
            f"Ongeldige hostnaam {tekst!r}: gebruik alleen letters, cijfers, '-' en '.'."
        )
    if tekst.startswith("-") or tekst.endswith("-") or tekst.startswith("."):
        raise ValidatieFout(f"Ongeldige hostnaam {tekst!r}.")
    return tekst


def validate_ip(waarde):
    """Controleert een IP-adres voor de SAN."""

    tekst = str(waarde or "").strip()
    if not tekst:
        raise ValidatieFout("Een IP-adres mag niet leeg zijn.")
    try:
        ipaddress.ip_address(tekst)
    except ValueError as fout:
        raise ValidatieFout(f"Ongeldig IP-adres {tekst!r}.") from fout
    return tekst


# ------------------------------------------------------------------
# Certificaatgeneratie
# ------------------------------------------------------------------


def _laad_cryptography():
    """Importeert ``cryptography`` lui, met een duidelijke foutmelding."""

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as fout:  # pragma: no cover - afhankelijk van omgeving
        raise OntbrekendeAfhankelijkheid(str(fout)) from fout

    return {
        "x509": x509,
        "hashes": hashes,
        "serialization": serialization,
        "rsa": rsa,
        "NameOID": NameOID,
    }


def _ontdubbel(waarden):
    gezien = []
    for waarde in waarden:
        if waarde not in gezien:
            gezien.append(waarde)
    return gezien


def _schrijf_bestand(pad: Path, inhoud: bytes, geheim: bool = False):
    """Schrijft een bestand; een privésleutel krijgt beperkte rechten."""

    pad.parent.mkdir(parents=True, exist_ok=True)

    if geheim and os.name != "nt":
        # Maak de sleutel direct aan met alleen lees/schrijf voor de eigenaar.
        descriptor = os.open(pad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as bestand:
            bestand.write(inhoud)
    else:
        with open(pad, "wb") as bestand:
            bestand.write(inhoud)

    if geheim:
        try:
            os.chmod(pad, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def generate_certificate(
    out_dir=DEFAULT_OUT_DIR,
    cert_name=DEFAULT_CERT_NAME,
    key_name=DEFAULT_KEY_NAME,
    common_name=DEFAULT_COMMON_NAME,
    hosts=(),
    ips=(),
    days=DEFAULT_DAYS,
    bits=DEFAULT_BITS,
    force=False,
):
    """Maakt een zelfondertekend certificaat + sleutel en geeft de paden terug."""

    crypt = _laad_cryptography()
    x509 = crypt["x509"]
    hashes = crypt["hashes"]
    serialization = crypt["serialization"]
    rsa = crypt["rsa"]
    NameOID = crypt["NameOID"]

    dagen = validate_days(days)
    sleutel_bits = validate_bits(bits)
    naam = validate_common_name(common_name)

    dns_namen = _ontdubbel(
        [validate_host(h) for h in list(STANDAARD_HOSTS) + list(hosts)]
    )
    ip_adressen = _ontdubbel(
        [validate_ip(i) for i in list(STANDAARD_IPS) + list(ips)]
    )

    out_dir = Path(out_dir)
    cert_pad = out_dir / cert_name
    key_pad = out_dir / key_name

    if not force:
        bestaand = [p for p in (cert_pad, key_pad) if p.exists()]
        if bestaand:
            namen = ", ".join(str(p) for p in bestaand)
            raise BestandBestaat(
                f"Deze bestanden bestaan al: {namen}. Gebruik --force om te overschrijven."
            )

    privésleutel = rsa.generate_private_key(public_exponent=65537, key_size=sleutel_bits)

    onderwerp = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, naam)])

    nu = datetime.now(timezone.utc)
    bouwer = (
        x509.CertificateBuilder()
        .subject_name(onderwerp)
        .issuer_name(onderwerp)
        .public_key(privésleutel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nu - timedelta(minutes=5))
        .not_valid_after(nu + timedelta(days=dagen))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
    )

    san_waarden = [x509.DNSName(dns) for dns in dns_namen]
    san_waarden += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ip_adressen]
    if san_waarden:
        bouwer = bouwer.add_extension(
            x509.SubjectAlternativeName(san_waarden), critical=False
        )

    certificaat = bouwer.sign(privésleutel, hashes.SHA256())

    sleutel_pem = privésleutel.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = certificaat.public_bytes(serialization.Encoding.PEM)

    _schrijf_bestand(key_pad, sleutel_pem, geheim=True)
    _schrijf_bestand(cert_pad, cert_pem, geheim=False)

    return Certificaat(
        cert_path=cert_pad,
        key_path=key_pad,
        fingerprint=certificaat.fingerprint(hashes.SHA256()).hex(),
    )


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def _bouw_parser():
    parser = argparse.ArgumentParser(
        prog="gen_remote_cert.py",
        description=(
            "Genereer een zelfondertekend TLS-certificaat + sleutel voor de "
            "JARVIS Game-PC Agent."
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"map voor het certificaat en de sleutel (standaard: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--cert-name", default=DEFAULT_CERT_NAME, help="bestandsnaam van het certificaat."
    )
    parser.add_argument(
        "--key-name", default=DEFAULT_KEY_NAME, help="bestandsnaam van de sleutel."
    )
    parser.add_argument(
        "--name", dest="common_name", default=DEFAULT_COMMON_NAME, help="Common Name (CN)."
    )
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        metavar="HOSTNAAM",
        help="extra DNS-naam in de SAN (herhaalbaar).",
    )
    parser.add_argument(
        "--ip",
        action="append",
        default=[],
        metavar="IP",
        help="extra IP-adres in de SAN (herhaalbaar).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"geldigheidsduur in dagen (standaard: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--bits",
        type=int,
        default=DEFAULT_BITS,
        help=f"RSA-sleutellengte (standaard: {DEFAULT_BITS}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overschrijf bestaande certificaat-/sleutelbestanden.",
    )
    return parser


def _print_openssl_alternatief():
    print(
        "Alternatief met OpenSSL:\n"
        "  openssl req -x509 -newkey rsa:2048 -nodes ^\n"
        "      -keyout agent-key.pem -out agent-cert.pem -days 825 ^\n"
        '      -subj "/CN=jarvis-game-pc-agent" ^\n'
        '      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:<game-pc-ip>"'
    )


def main(argv=None):
    parser = _bouw_parser()
    args = parser.parse_args(argv)

    try:
        resultaat = generate_certificate(
            out_dir=args.out_dir,
            cert_name=args.cert_name,
            key_name=args.key_name,
            common_name=args.common_name,
            hosts=args.host,
            ips=args.ip,
            days=args.days,
            bits=args.bits,
            force=args.force,
        )
    except OntbrekendeAfhankelijkheid:
        print(
            "FOUT: de module 'cryptography' is niet geïnstalleerd.\n"
            "Installeer de ontwikkel-afhankelijkheden:\n"
            "  pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        _print_openssl_alternatief()
        return EXIT_MISSING_DEP
    except BestandBestaat as fout:
        print(f"FOUT: {fout}", file=sys.stderr)
        return EXIT_EXISTS
    except ValidatieFout as fout:
        print(f"FOUT: {fout}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as fout:
        print(f"FOUT: kon het certificaat niet wegschrijven: {fout}", file=sys.stderr)
        return EXIT_USAGE

    print("Certificaat en sleutel aangemaakt:")
    print(f"  Certificaat : {resultaat.cert_path}")
    print(f"  Sleutel     : {resultaat.key_path}")
    print(f"  Vingerafdruk (SHA-256): {resultaat.fingerprint}")
    print()
    print("Zet dit in het .env-bestand van de GAME-PC (server):")
    print(f"  REMOTE_SERVER_CERT_FILE={resultaat.cert_path}")
    print(f"  REMOTE_SERVER_KEY_FILE={resultaat.key_path}")
    print()
    print(
        "Deel ALLEEN het certificaat (niet de sleutel) met het brein en zet het "
        "daar als REMOTE_CLIENT_CA_FILE.\n"
        "Bewaar de sleutel geheim en commit 'certs/' nooit (staat in .gitignore)."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
