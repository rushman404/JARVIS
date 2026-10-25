#!/usr/bin/env python3
"""Backups van het JARVIS-brein (Fase 19, M3).

JARVIS maakt elke nacht zelf een backup (``BACKUP_TIJD``). Met dit script
kunt u er ook direct een maken of ze bekijken::

    python scripts/brein_backup.py           # nu een backup maken
    python scripts/brein_backup.py --lijst   # bestaande backups tonen

Terugzetten: ``python scripts/brein_restore.py --laatste``.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beheer import backup  # noqa: E402


def _mb(grootte):
    return f"{grootte / 1024 / 1024:.1f} MB"


def main(argv=None):
    p = argparse.ArgumentParser(prog="brein_backup.py", description="Backups van het JARVIS-brein.")
    p.add_argument("--lijst", action="store_true", help="toon de bestaande backups.")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        map_ = backup.controleer_map(backup.backup_map())
    except backup.BackupFout as fout:
        print(f"Backupmap ongeldig: {fout}", file=sys.stderr)
        return 1

    if args.lijst:
        backups = backup.lijst(map_)
        print(f"Backups in {map_}:")
        if not backups:
            print("  (nog geen)")
        for naam, moment, pad in backups:
            try:
                grootte = _mb(os.path.getsize(pad))
            except OSError:
                grootte = "?"
            print(f"  {moment:%d-%m-%Y %H:%M}  {grootte:>8}  {naam}")
        return 0

    ok, info = backup.voer_uit()
    if not ok:
        print(f"Backup mislukt: {info}", file=sys.stderr)
        return 1
    print(f"Backup gemaakt: {info['naam']} ({info['aantal']} bestanden, {_mb(info['grootte'])})")
    print(f"  in {map_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
