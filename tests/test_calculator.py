import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.calculator import calculate


def test_procent_van_geheel():
    r = calculate("wat is 20 procent van 50")
    assert r is not None, "procent-van wordt herkend"
    assert r["result"] == 10, "20 procent van 50 = 10"


def test_procent_van_met_komma():
    r = calculate("wat is 1,5 procent van 200")
    assert r is not None, "procent-van met komma wordt herkend"
    assert r["result"] == 3, "1,5 procent van 200 = 3"


def test_procent_van_met_voorrang():
    r = calculate("wat is 20 procent van 50 plus 10")
    assert r is not None, "procent-van met vervolg wordt herkend"
    assert r["result"] == 20, "procent gaat voor optellen (10 + 10)"


def test_gewone_berekening_blijft_werken():
    assert calculate("wat is 2 plus 3")["result"] == 5
    assert calculate("bereken 100 gedeeld door 4")["result"] == 25


def test_geen_rekenintentie_geeft_none():
    assert calculate("zet de lamp op 50 procent") is None
    assert calculate("wat is het weer") is None
