"""Routering van negatieve zinnen: niets mag een routine starten.

Elke regel uit tests/data/negative_utterances.txt wordt apart door de
volledige router (process_command) gehaald. De LLM is gemockt zodat de
test deterministisch is.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import process_command
from core import confirmation
from core.routines import RoutineManager

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_negative():
    pad = os.path.join(DATA_DIR, "negative_utterances.txt")
    with open(pad, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


NEGATIEVE_ZINNEN = load_negative()


@pytest.mark.parametrize("utt", NEGATIEVE_ZINNEN)
def test_negative_utterances_routing(utt):
    routines = RoutineManager()
    confirmation.clear_pending()
    with patch("core.brain.ask_ai", return_value="AI-STUB"):
        result = process_command(utt)
    assert result is None or isinstance(result, str), f"rare return voor {utt!r}"
    naam, _ = routines.resolve(utt)
    assert naam is None, f"{utt!r} startte routine {naam!r}"


def test_confirmation_regressions():
    from core import confirmation as c
    assert "niet" in c.DENIAL_WORDS
    assert c.contains_denial("ja maar niet nu")
