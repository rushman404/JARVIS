"""Controleert welke Nederlandse formuleringen de brain-router herkent.

Handmatig script (geen unittest): rapporteert per formulering welke
tak van brain.py het commando afhandelt.

Gebruik::

    python -m scripts.debug.debug_frase_dekking
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import core.brain as brain

OMHOOG = [
    "zet geluid op",
    "zet het geluid op",
    "volume omhoog",
    "maak het geluid harder",
    "geluid harder",
    "zet volume hoger",
    "harder",
    "volume opzetten",
    "geluid opzetten",
    "zet geluid omhoog",
    "maak het geluid luid",
    "volume omhoog doen",
    "luider",
]

OMLAAG = [
    "zet geluid omlaag",
    "volume omlaag",
    "maak het geluid zachter",
    "geluid zachter",
    "zet volume lager",
    "zachter",
    "geluid stil",
    "stiller",
]

DEMPEN = [
    "demp het geluid",
    "mute",
    "zet het geluid uit",
    "zet het geluid aan",
    "geluid uit",
]

PROCENT = [
    "zet het volume op 30",
    "zet volume op 30 procent",
    "volume naar 70",
]

VERKEERD = [
    "wat is de tijd",
    "vertel een mop",
    "wie was Einstein",
]


def _label(resultaat):
    """Kort label: welke tak pakte het commando?"""

    if resultaat is None:
        return "GEEN MATCH"

    tekst = str(resultaat)

    if "omhoog" in tekst:
        return "volume omhoog"

    if "omlaag" in tekst:
        return "volume omlaag"

    if "gedempt" in tekst or "weer aan" in tekst:
        return "demp/mute"

    if "%" in tekst:
        return "volume op procent"

    return "match: " + tekst[:40]


def main():
    print(f"PC_TARGET = {os.environ.get('PC_TARGET', '(niet gezet)')}")

    groepen = {
        "OMHOOG": OMHOOG,
        "OMLAAG": OMLAAG,
        "DEMPEN": DEMPEN,
        "PROCENT": PROCENT,
        "NIET-PC": VERKEERD,
    }

    for naam, zinnen in groepen.items():
        print(f"\n=== {naam} ===")

        for zin in zinnen:
            resultaat = brain.try_media_command(zin)
            print(f"  {zin!r:42} -> {_label(resultaat)}")


if __name__ == "__main__":
    main()
