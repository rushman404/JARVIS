#!/usr/bin/env python3
"""Maak het TLS-certificaat en het iPad-profiel voor het dashboard (Fase 18).

Waarom een eigen CA (en niet één zelfondertekend certificaat)?
iOS laat bij *Instellingen → Algemeen → Info → Instellingen voor
certificaatvertrouwen* alleen **root-certificaten** op "Volledig vertrouwen"
zetten. Daarom maakt dit script:

* een kleine eigen CA (``dashboard-ca.pem`` + ``dashboard-ca-key.pem``),
  alleen geldig voor het ondertekenen van certificaten;
* een servercertificaat (``dashboard-cert.pem`` + ``dashboard-key.pem``),
  ondertekend door die CA, met de LAN-IP's en ``localhost`` in de SAN,
  ``serverAuth``, RSA 2048 en 397 dagen geldig (ruim binnen de eisen van Apple);
* het profiel ``jarvis-dashboard.mobileconfig`` met **alleen het publieke
  CA-certificaat**. Dat installeert u op de iPad.

Gebruik
-------
::

    python scripts/make_dashboard_cert.py --ip 192.168.2.10

Zonder ``--ip`` neemt het script het LAN-adres dat het zelf vindt.
Verandert het IP van de pc, draai het script dan opnieuw met ``--force``:
de bestaande CA wordt hergebruikt, dus de iPad hoeft het profiel niet
opnieuw te installeren.

Daarna in ``.env``::

    DASHBOARD_CERT_FILE=certs/dashboard-cert.pem
    DASHBOARD_KEY_FILE=certs/dashboard-key.pem

Op de iPad
----------
1. Open ``https://<pc-ip>:8780/profiel.mobileconfig`` in Safari (of stuur
   het bestand via AirDrop) en installeer het bij *Instellingen → Profiel
   gedownload*.
2. *Instellingen → Algemeen → Info → Instellingen voor certificaatvertrouwen*
   → zet **JARVIS Dashboard CA** op **Volledig vertrouwen**.

Beveiliging
-----------
* De privésleutels worden nooit naar het scherm geschreven en staan in
  ``certs/`` (in ``.gitignore``). Het profiel bevat geen sleutel.
* De CA mag alleen certificaten ondertekenen (``path_length=0``); bewaar
  ``dashboard-ca-key.pem`` goed: wie die heeft, kan certificaten maken die
  de iPad vertrouwt.
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import plistlib
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

HIER = Path(__file__).resolve().parent

DEFAULT_OUT_DIR = "certs"
CA_CERT = "dashboard-ca.pem"
CA_KEY = "dashboard-ca-key.pem"
SERVER_CERT = "dashboard-cert.pem"
SERVER_KEY = "dashboard-key.pem"
PROFIEL = "jarvis-dashboard.mobileconfig"

CA_NAAM = "JARVIS Dashboard CA"
SERVER_NAAM = "jarvis-dashboard"
CA_DAGEN = 3650
# 397 dagen: ruim binnen alle Apple-grenzen (825 voor iOS 13+, 398 voor
# nieuwere Safari). Vernieuwen is één commando (--force); de CA blijft.
SERVER_DAGEN = 397

PROFIEL_ID = "nl.jarvis.dashboard"

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_MISSING_DEP = 2
EXIT_EXISTS = 3


def _laad_basis():
    """Hergebruikt de validatie en het veilig wegschrijven van gen_remote_cert.py."""

    if "gen_remote_cert" in sys.modules:
        return sys.modules["gen_remote_cert"]
    spec = importlib.util.spec_from_file_location("gen_remote_cert", HIER / "gen_remote_cert.py")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses (met uitgestelde annotaties) zoeken hun module op in sys.modules.
    sys.modules["gen_remote_cert"] = module
    spec.loader.exec_module(module)
    return module


basis = _laad_basis()
ValidatieFout = basis.ValidatieFout
BestandBestaat = basis.BestandBestaat
OntbrekendeAfhankelijkheid = basis.OntbrekendeAfhankelijkheid


@dataclass
class Resultaat:
    ca_cert: Path
    server_cert: Path
    server_key: Path
    profiel: Path
    ca_hergebruikt: bool
    vingerafdruk_ca: str


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as fout:  # pragma: no cover - afhankelijk van omgeving
        raise OntbrekendeAfhankelijkheid(str(fout)) from fout
    return x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID


def detecteer_lan_ip():
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    adres = ipaddress.ip_address(ip)
    return ip if adres.is_private and not adres.is_loopback else None


def _sleutel_pem(sleutel, serialization):
    return sleutel.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _maak_ca(x509, hashes, ec, NameOID, nu):
    sleutel = ec.generate_private_key(ec.SECP256R1())
    naam = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAAM)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(naam)
        .issuer_name(naam)
        .public_key(sleutel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nu - timedelta(minutes=5))
        .not_valid_after(nu + timedelta(days=CA_DAGEN))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(sleutel.public_key()), critical=False)
        .sign(sleutel, hashes.SHA256())
    )
    return sleutel, cert


def bouw_profiel(ca_der, profiel_uuid=None, inhoud_uuid=None):
    """Het .mobileconfig-profiel (plist) met alleen het CA-certificaat."""

    profiel_uuid = profiel_uuid or str(uuid.uuid4()).upper()
    inhoud_uuid = inhoud_uuid or str(uuid.uuid4()).upper()
    return plistlib.dumps({
        "PayloadContent": [{
            "PayloadCertificateFileName": "jarvis-dashboard-ca.cer",
            "PayloadContent": ca_der,
            "PayloadDescription": "Vertrouw het JARVIS-dashboard op uw eigen netwerk.",
            "PayloadDisplayName": CA_NAAM,
            "PayloadIdentifier": f"{PROFIEL_ID}.ca",
            "PayloadType": "com.apple.security.root",
            "PayloadUUID": inhoud_uuid,
            "PayloadVersion": 1,
        }],
        "PayloadDescription": "Certificaat voor het JARVIS-dashboard (alleen thuis).",
        "PayloadDisplayName": "JARVIS Dashboard",
        "PayloadIdentifier": PROFIEL_ID,
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": profiel_uuid,
        "PayloadVersion": 1,
    })


def maak_certificaten(out_dir=DEFAULT_OUT_DIR, ips=(), hosts=(), force=False, nu=None):
    """Maakt (of hergebruikt) de CA, het servercertificaat en het profiel."""

    x509, hashes, serialization, ec, ExtendedKeyUsageOID, NameOID = _crypto()
    nu = nu or datetime.now(timezone.utc)

    ip_lijst = basis._ontdubbel([basis.validate_ip(i) for i in ["127.0.0.1", *ips]])
    host_lijst = basis._ontdubbel([basis.validate_host(h) for h in ["localhost", *hosts]])

    out = Path(out_dir)
    paden = {n: out / n for n in (CA_CERT, CA_KEY, SERVER_CERT, SERVER_KEY, PROFIEL)}

    server_bestaand = [p for n, p in paden.items() if n in (SERVER_CERT, SERVER_KEY) and p.exists()]
    if server_bestaand and not force:
        raise BestandBestaat(
            "Deze bestanden bestaan al: " + ", ".join(str(p) for p in server_bestaand)
            + ". Gebruik --force om ze opnieuw te maken (de CA blijft dan behouden)."
        )

    # Bestaande CA hergebruiken: dan hoeft de iPad niets opnieuw te doen.
    ca_hergebruikt = paden[CA_CERT].exists() and paden[CA_KEY].exists()
    if ca_hergebruikt:
        ca_cert = x509.load_pem_x509_certificate(paden[CA_CERT].read_bytes())
        ca_sleutel = serialization.load_pem_private_key(paden[CA_KEY].read_bytes(), password=None)
    else:
        ca_sleutel, ca_cert = _maak_ca(x509, hashes, ec, NameOID, nu)
        basis._schrijf_bestand(paden[CA_KEY], _sleutel_pem(ca_sleutel, serialization), geheim=True)
        basis._schrijf_bestand(paden[CA_CERT], ca_cert.public_bytes(serialization.Encoding.PEM))

    # Servercertificaat zo behoudend mogelijk voor (oudere) iOS-versies:
    # RSA 2048 met digitalSignature + keyEncipherment, serverAuth, SAN met de
    # IP-adressen, en een geldigheid die ruim binnen de Apple-grens blijft
    # (inclusief de terugdatering; eerder was het 825 dagen + 5 minuten).
    from cryptography.hazmat.primitives.asymmetric import rsa

    sleutel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san = [x509.DNSName(h) for h in host_lijst]
    san += [x509.IPAddress(ipaddress.ip_address(i)) for i in ip_lijst]
    lan_ips = [i for i in ip_lijst if not ipaddress.ip_address(i).is_loopback]
    naam = lan_ips[0] if lan_ips else SERVER_NAAM
    begin = nu - timedelta(hours=1)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, naam)]))
        .issuer_name(ca_cert.subject)
        .public_key(sleutel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(begin)
        .not_valid_after(begin + timedelta(days=SERVER_DAGEN))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(sleutel.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_sleutel.public_key()), critical=False
        )
        .sign(ca_sleutel, hashes.SHA256())
    )

    basis._schrijf_bestand(paden[SERVER_KEY], _sleutel_pem(sleutel, serialization), geheim=True)
    # De keten (server + CA) zodat clients de CA ook meekrijgen.
    keten = cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM)
    basis._schrijf_bestand(paden[SERVER_CERT], keten)

    basis._schrijf_bestand(paden[PROFIEL], bouw_profiel(ca_cert.public_bytes(serialization.Encoding.DER)))

    return Resultaat(
        ca_cert=paden[CA_CERT],
        server_cert=paden[SERVER_CERT],
        server_key=paden[SERVER_KEY],
        profiel=paden[PROFIEL],
        ca_hergebruikt=ca_hergebruikt,
        vingerafdruk_ca=ca_cert.fingerprint(hashes.SHA256()).hex(),
    )


def _parser():
    p = argparse.ArgumentParser(
        prog="make_dashboard_cert.py",
        description="Maak het TLS-certificaat en het iPad-profiel voor het JARVIS-dashboard.",
    )
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"doelmap (standaard: {DEFAULT_OUT_DIR}).")
    p.add_argument("--ip", action="append", default=[], metavar="IP",
                   help="LAN-adres van deze pc (herhaalbaar). Standaard: automatisch.")
    p.add_argument("--host", action="append", default=[], metavar="NAAM", help="extra DNS-naam (herhaalbaar).")
    p.add_argument("--force", action="store_true", help="servercertificaat opnieuw maken (CA blijft).")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    ips = list(args.ip)
    if not ips:
        gevonden = detecteer_lan_ip()
        if gevonden:
            ips.append(gevonden)
            print(f"LAN-adres gevonden: {gevonden}")
        else:
            print("Geen LAN-adres gevonden; alleen localhost. Geef het IP met --ip.")

    try:
        r = maak_certificaten(args.out_dir, ips=ips, hosts=args.host, force=args.force)
    except OntbrekendeAfhankelijkheid:
        print("De module 'cryptography' ontbreekt: pip install -r requirements-dev.txt", file=sys.stderr)
        return EXIT_MISSING_DEP
    except ValidatieFout as fout:
        print(f"Ongeldige invoer: {fout}", file=sys.stderr)
        return EXIT_USAGE
    except BestandBestaat as fout:
        print(str(fout), file=sys.stderr)
        return EXIT_EXISTS

    print(("Bestaande CA hergebruikt: " if r.ca_hergebruikt else "Nieuwe CA: ") + str(r.ca_cert))
    print(f"Servercertificaat: {r.server_cert}")
    print(f"Serversleutel:     {r.server_key}")
    print(f"iPad-profiel:      {r.profiel}")
    print(f"SHA-256 van de CA: {r.vingerafdruk_ca}")
    print()
    print("Zet in .env:")
    print(f"  DASHBOARD_CERT_FILE={r.server_cert.as_posix()}")
    print(f"  DASHBOARD_KEY_FILE={r.server_key.as_posix()}")
    print()
    print("Op de iPad: installeer het profiel en zet daarna bij Instellingen → Algemeen →")
    print("Info → Instellingen voor certificaatvertrouwen 'JARVIS Dashboard CA' op Volledig vertrouwen.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
