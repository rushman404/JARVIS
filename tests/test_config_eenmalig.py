"""Elke constante in config.py hoort maar één keer gedefinieerd te worden.

Een tweede definitie overschrijft de eerste stil: een aanpassing in het
bovenste blok doet dan niets. Zo stonden de BARGE_IN_*-waarden er dubbel in.
"""

import ast
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config.py"


def _top_level_names(boom):
    """Alle namen die op moduleniveau een waarde krijgen, met hun regelnummers."""
    namen = {}

    for knoop in boom.body:
        if isinstance(knoop, ast.Assign):
            doelen = knoop.targets
        elif isinstance(knoop, ast.AnnAssign):
            doelen = [knoop.target]
        else:
            continue

        for doel in doelen:
            if isinstance(doel, ast.Name):
                namen.setdefault(doel.id, []).append(knoop.lineno)

    return namen


def test_config_definieert_elke_constante_een_keer():
    boom = ast.parse(CONFIG.read_text(encoding="utf-8"))

    dubbel = {
        naam: regels
        for naam, regels in _top_level_names(boom).items()
        if len(regels) > 1
    }

    assert not dubbel, f"Dubbel gedefinieerd in config.py: {dubbel}"


def test_de_controle_vindt_een_dubbele_constante():
    """De controle zelf werkt: twee keer dezelfde naam valt op."""
    boom = ast.parse("A = 1\nA = 2\n")

    assert _top_level_names(boom)["A"] == [1, 2]
