#!/usr/bin/env python3
"""Pak het JARVIS-brein in voor de verhuizing naar een andere pc (Fase 19, M1).

Gebruik (op de oude pc, bijv. de laptop)::

    python scripts/brein_export.py
    python scripts/brein_export.py --naar E:\\

Het pakket bevat het geheugen, gesprek, timers, routines, gekoppelde
iPads, het auditlog, de Obsidian-vault **en de geheimen** (.env en
certs/). Zet het over met een usb-stick; mail het niet en zet het niet
in de cloud. Op de nieuwe pc: ``python scripts/brein_import.py <pakket>``.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beheer import migratie  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(prog="brein_export.py", description="Pak het JARVIS-brein in.")
    p.add_argument("--naar", default=None, metavar="MAP",
                   help=f"doelmap (standaard: {migratie.standaard_exportmap()}).")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        pad, aantal = migratie.exporteer(args.naar)
    except (migratie.MigratieFout, OSError) as fout:
        print(f"Export mislukt: {fout}", file=sys.stderr)
        return 1

    print(f"Klaar: {aantal} bestanden in")
    print(f"  {pad}")
    print()
    print("LET OP: dit pakket bevat uw tokens en sleutels. Zet het over met een")
    print("usb-stick (niet mailen, niet in de cloud) en verwijder het daarna.")
    print("Op de nieuwe pc:  python scripts/brein_import.py \"<pakket>\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
