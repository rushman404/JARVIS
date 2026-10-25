#!/usr/bin/env python3
"""Zet een JARVIS-breinpakket terug op deze pc (Fase 19, M1).

Gebruik (op de nieuwe pc, met JARVIS gestopt)::

    python scripts/brein_import.py "E:\\jarvis-brein-LAPTOP-20261025-120000.zip"
    python scripts/brein_import.py <pakket> --ja   # zonder vraag

Eerst ziet u wat er nieuw is en wat overschreven wordt. Bestaande
bestanden gaan vóór het overschrijven in een veiligheidszip.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beheer import migratie  # noqa: E402


def _toon_plan(plan):
    print(f"Pakket van {plan.bron_pc or 'onbekende pc'}, gemaakt op {plan.gemaakt_op or '?'}")
    print(f"  nieuw:          {len(plan.nieuw)}")
    print(f"  overschrijven:  {len(plan.overschrijven)}")
    print(f"  al gelijk:      {len(plan.gelijk)}")
    for rel in plan.overschrijven:
        print(f"    ~ {rel}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="brein_import.py", description="Zet een JARVIS-breinpakket terug.")
    p.add_argument("pakket", help="het .zip-pakket van brein_export.py")
    p.add_argument("--ja", action="store_true", help="niet vragen, meteen terugzetten.")
    p.add_argument("--alleen-controle", action="store_true", help="alleen tonen wat er zou gebeuren.")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        manifest, inhoud = migratie.lees_pakket(args.pakket)
    except migratie.MigratieFout as fout:
        print(f"Import geweigerd: {fout}", file=sys.stderr)
        return 1

    plan = migratie.maak_plan(manifest, inhoud)
    _toon_plan(plan)

    if args.alleen_controle:
        return 0
    if not plan.nieuw and not plan.overschrijven:
        print("\nNiets te doen: alles is al gelijk.")
        return 0
    if not args.ja:
        antwoord = input("\nDoorgaan? Typ 'ja': ").strip().lower()
        if antwoord != "ja":
            print("Afgebroken, er is niets veranderd.")
            return 1

    try:
        plan, veiligheid = migratie.importeer(args.pakket)
    except (migratie.MigratieFout, OSError) as fout:
        print(f"Import mislukt: {fout}", file=sys.stderr)
        return 1

    print(f"\nKlaar: {len(plan.nieuw) + len(plan.overschrijven)} bestanden teruggezet.")
    if veiligheid:
        print(f"De oude versies staan in: {veiligheid}")

    if ".env" in inhoud:
        nakijken = migratie.env_nakijken(inhoud[".env"])
        if nakijken:
            print("\nKijk deze instellingen in .env na (ze kunnen op deze pc anders zijn):")
            for sleutel, reden in nakijken:
                print(f"  - {sleutel}  ({reden})")

    print("\nVolgende stappen:")
    print("  1. python scripts/brein_check.py")
    print("  2. Nieuw IP-adres? python scripts/make_dashboard_cert.py --force")
    print("     (de CA blijft gelijk, de iPad hoeft niets opnieuw te doen)")
    print("  3. Pakket verwijderen: het bevat uw tokens en sleutels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
