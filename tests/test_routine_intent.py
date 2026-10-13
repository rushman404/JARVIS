"""Tests voor routine-intentieherkenning (RoutineManager.resolve).

De kern: een routine start alleen bij een echte opdracht. Vragen,
beschrijvingen en woorden die toevallig in een ander woord zitten
starten geen routine.
"""
import os

import pytest

from core.routines import (
    RoutineManager,
    is_question,
    matches_routine_command,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
NEGATIVES_FILE = os.path.join(DATA_DIR, "routine_negatives.txt")

POSITIEVE_ZINNEN = [
    ("ik ga slapen", "sleep"),
    ("ik ga gamen", "gaming"),
    ("gaming modus", "gaming"),
    ("game modus aan", "gaming"),
    ("zet de game modus aan", "gaming"),
    ("filmavond", "movie"),
    ("start de film", "movie"),
    ("ik wil een film kijken", "movie"),
    ("slaap modus", "sleep"),
]


@pytest.fixture()
def manager():
    return RoutineManager()


def _lees_negatieven():
    with open(NEGATIVES_FILE, "r", encoding="utf-8") as f:
        return [
            regel.strip()
            for regel in f
            if regel.strip() and not regel.strip().startswith("#")
        ]


def test_bestand_heeft_minimaal_25_negatieve_zinnen():
    assert len(_lees_negatieven()) >= 25


@pytest.mark.parametrize("zin,verwacht", POSITIEVE_ZINNEN)
def test_positieve_zinnen_starten_de_juiste_routine(manager, zin, verwacht):
    naam, routine = manager.resolve(zin)
    assert naam == verwacht, f"{zin!r} moet {verwacht!r} starten, kreeg {naam!r}"
    assert routine is not None


@pytest.mark.parametrize("zin", _lees_negatieven())
def test_negatieve_zinnen_starten_geen_routine(manager, zin):
    naam, routine = manager.resolve(zin)
    assert naam is None, f"{zin!r} mag geen routine starten, kreeg {naam!r}"
    assert routine is None


def test_is_question_herkent_vraagwoorden_en_vraagtekens():
    for zin in ("hoe lang moet ik slapen", "wat is de slaap modus", "is de film al begonnen", "waar is de game modus"):
        assert is_question(zin) is True, zin
    for zin in ("ik ga slapen", "filmavond", "start de film"):
        assert is_question(zin) is False, zin
    assert is_question("filmavond?") is True


def test_vraag_start_nooit_een_routine(manager):
    for zin in ("hoe lang moet ik slapen", "filmavond?", "wat is slaap modus"):
        naam, _ = manager.resolve(zin)
        assert naam is None, zin


def test_alias_matcht_alleen_als_heel_woord():
    routine = {"name": "sleep", "aliases": ["slapen"], "triggers": []}
    assert matches_routine_command("ik ga slapen", routine) is True
    assert matches_routine_command("lekker geslapen", routine) is False
    assert matches_routine_command("tijd om te slapen", routine) is False


def test_opdrachtvormen_voor_naam_en_alias():
    routine = {"name": "gaming", "aliases": ["game modus"], "triggers": []}
    for zin in ("gaming", "ik ga gaming", "start gaming", "zet gaming aan", "gaming modus"):
        assert matches_routine_command(zin, routine) is True, zin
    for zin in ("game modus", "game modus aan", "ik ga game modus"):
        assert matches_routine_command(zin, routine) is True, zin
    for zin in ("game modus is saai", "om te gamen is leuk", "gaming is duur"):
        assert matches_routine_command(zin, routine) is False, zin
