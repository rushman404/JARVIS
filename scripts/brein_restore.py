#!/usr/bin/env python3
"""Zet een backup van het JARVIS-brein terug (Fase 19, M3).

Stop JARVIS eerst (``Stop-ScheduledTask -TaskName 'JARVIS Brein'``)::

    python scripts/brein_restore.py --laatste                  # de nieuwste backup
    python scripts/brein_restore.py jarvis-backup-20261025-040000.zip
    python scripts/brein_restore.py --laatste --alleen-controle

Een naam zonder map wordt in ``BACKUP_MAP`` gezocht. Het terugzetten zelf
is de veilige import van ``brein_import.py``: controlegetallen, alleen
brein-bestanden, en eerst een veiligheidszip van wat overschreven wordt.
"""

import argparse
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beheer import backup  # noqa: E402


def _brein_import():
    pad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brein_import.py")
    spec = importlib.util.spec_from_file_location("brein_import", pad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    p = argparse.ArgumentParser(prog="brein_restore.py", description="Zet een backup van het brein terug.")
    p.add_argument("backup", nargs="?", help="naam of pad van de backup")
    p.add_argument("--laatste", action="store_true", help="de nieuwste backup nemen.")
    p.add_argument("--ja", action="store_true", help="niet vragen, meteen terugzetten.")
    p.add_argument("--alleen-controle", action="store_true", help="alleen tonen wat er zou gebeuren.")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if bool(args.backup) == bool(args.laatste):
        print("Geef een backup op, of gebruik --laatste.", file=sys.stderr)
        return 2

    if args.laatste:
        backups = backup.lijst()
        if not backups:
            print(f"Geen backups gevonden in {backup.backup_map()}.", file=sys.stderr)
            return 1
        pad = backups[0][2]
    else:
        pad = args.backup
        if not os.path.dirname(pad):
            pad = os.path.join(backup.backup_map(), pad)
    if not os.path.isfile(pad):
        print(f"Backup niet gevonden: {pad}", file=sys.stderr)
        return 1

    print(f"Backup: {pad}\n")
    extra = []
    if args.ja:
        extra.append("--ja")
    if args.alleen_controle:
        extra.append("--alleen-controle")
    return _brein_import().main([pad, *extra])


if __name__ == "__main__":
    sys.exit(main())
