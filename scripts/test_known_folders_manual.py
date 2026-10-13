"""Handmatige Windows-test voor de bekende mappen (get_known_folder).

Prints alle zes mappen met hun echt pad (ook als OneDrive ze heeft
omgeleid) en of het pad bestaat.

Gebruik (Windows):
    python scripts/test_known_folders_manual.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.paths import get_known_folder

MAPPEN = [
    ("Bureaublad", "Desktop"),
    ("Documenten", "Documents"),
    ("Downloads", "Downloads"),
    ("Afbeeldingen", "Pictures"),
    ("Muziek", "Music"),
    ("Video's", "Videos"),
]


def main():
    print("Bekende Windows-mappen via get_known_folder():\n")
    totaal = 0
    bestaand = 0
    for label, naam in MAPPEN:
        pad = get_known_folder(naam)
        bestaat = os.path.isdir(pad)
        totaal += 1
        bestaand += bestaat
        status = "BESTAAT" if bestaat else "BESTAAT NIET"
        print(f"  {label:<16} -> {pad}")
        print(f"                     [{status}]")

    print(f"\n{bestaand}/{totaal} mappen bestaan.")


if __name__ == "__main__":
    main()