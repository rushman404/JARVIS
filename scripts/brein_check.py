#!/usr/bin/env python3
"""Controleer of het JARVIS-brein klaar is (Fase 19, M1).

Gebruik::

    python scripts/brein_check.py          # overzicht
    python scripts/brein_check.py --json   # voor scripts

Exitcode 0 als er geen enkele ❌ is, anders 1. Het script verandert niets.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beheer import dokter  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(prog="brein_check.py", description="Controleer het JARVIS-brein.")
    p.add_argument("--json", action="store_true", help="uitvoer als JSON.")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    uitkomsten = dokter.voer_uit()
    if args.json:
        print(json.dumps([asdict(u) for u in uitkomsten], ensure_ascii=False, indent=2))
    else:
        print("JARVIS-brein — controle\n")
        print(dokter.als_tekst(uitkomsten))
    return 0 if dokter.is_gezond(uitkomsten) else 1


if __name__ == "__main__":
    sys.exit(main())
