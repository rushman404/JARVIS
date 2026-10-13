"""Negatieve zinnen mogen helemaal niets starten.

Elke regel uit tests/data/negative_utterances.txt wordt APART getest
(geparametriseerd), met echte asserts:
  - calculate() geeft None (geen rekenintentie)
  - is_goal() geeft False (geen agent-doel)
  - routine-resolve() geeft (None, None)

Positieve routine-triggers (tests/data/routine_positives.txt) starten
juist WEL de verwachte routine, en beheercommando's
(tests/data/management_commands.txt) bereiken de beheerhandler.
"""
import os
from unittest.mock import patch

import pytest

import core.brain as brain
from core.calculator import calculate
from core.agent import is_goal
from core.routines import RoutineManager

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
NEGATIVES = os.path.join(DATA_DIR, "negative_utterances.txt")
POSITIVES = os.path.join(DATA_DIR, "routine_positives.txt")
MANAGEMENT = os.path.join(DATA_DIR, "management_commands.txt")


def _lees(pad):
    with open(pad, encoding="utf-8") as f:
        return [r.strip() for r in f if r.strip() and not r.strip().startswith("#")]


NEGATIEVE_ZINNEN = _lees(NEGATIVES)
POSITIEVE_TRIGGERS = [tuple(r.rsplit("|", 1)) for r in _lees(POSITIVES)]
BEHEER_COMMANDOS = _lees(MANAGEMENT)


@pytest.fixture(scope="module")
def routines():
    return RoutineManager()


def test_databestand_is_gevuld():
    assert len(NEGATIEVE_ZINNEN) >= 100, "te weinig negatieve zinnen"
    assert POSITIEVE_TRIGGERS, "geen positieve triggers"
    assert BEHEER_COMMANDOS, "geen beheercommando's"


@pytest.mark.parametrize("zin", NEGATIEVE_ZINNEN)
def test_negatieve_zin_start_geen_calculator(zin):
    assert calculate(zin) is None, f"calculator reageerde op {zin!r}"


@pytest.mark.parametrize("zin", NEGATIEVE_ZINNEN)
def test_negatieve_zin_is_geen_goal(zin):
    assert is_goal(zin) is False, f"agent-doel gezien in {zin!r}"


@pytest.mark.parametrize("zin", NEGATIEVE_ZINNEN)
def test_negatieve_zin_start_geen_routine(routines, zin):
    naam, routine = routines.resolve(zin)
    assert naam is None and routine is None, f"{zin!r} startte routine {naam!r}"


@pytest.mark.parametrize("zin,verwacht", POSITIEVE_TRIGGERS)
def test_positieve_trigger_start_routine(routines, zin, verwacht):
    naam, _ = routines.resolve(zin)
    assert naam == verwacht, f"{zin!r} -> {naam!r}, verwacht {verwacht!r}"


@pytest.mark.parametrize("cmd", BEHEER_COMMANDOS)
def test_beheercommando_bereikt_de_handler(cmd):
    with patch("core.brain._handle_routine_management", return_value="HANDLER") as mock:
        result = brain.try_routine(cmd)
    assert result == "HANDLER", f"{cmd!r} bereikte de beheerhandler niet (got {result!r})"
    assert mock.called
