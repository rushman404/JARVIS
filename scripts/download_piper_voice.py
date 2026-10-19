"""Download een Piper-stemmodel naar voice/models (Fase 17).

Gebruik:

    python scripts/download_piper_voice.py                 # standaardstem
    python scripts/download_piper_voice.py nl_NL-pim-medium
    python scripts/download_piper_voice.py --list          # toon alle stemmen

Beschikbare Nederlandse stemmen zijn o.a. nl_NL-pim-medium,
nl_NL-ronnie-medium, nl_NL-alex-medium, nl_NL-mls_5809-low en
nl_BE-nathalie-medium. De bestanden komen van Hugging Face
(rhasspy/piper-voices) en staan in voice/models (niet in git).
"""

import argparse
import logging
import sys
from pathlib import Path

STANDAARD_STEM = "nl_NL-pim-medium"
MODELS_DIR = Path(__file__).resolve().parent.parent / "voice" / "models"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download een Piper-stemmodel.")
    parser.add_argument(
        "voice",
        nargs="?",
        default=STANDAARD_STEM,
        help=f"Naam van de stem, bijv. {STANDAARD_STEM} (standaard)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Toon alle beschikbare stemmen en stop.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overschrijf een bestaand model opnieuw.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from piper.download_voices import download_voice, list_voices

    if args.list:
        list_voices()
        return 0

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    download_voice(args.voice, MODELS_DIR, force_redownload=args.force)
    print(f"Stem '{args.voice}' staat in {MODELS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
