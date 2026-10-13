"""Meta-test: elke testfunctie moet echt kunnen falen.

We lopen met ast alle testbestanden in tests/ langs en eisen dat elke
functie die met "test" begint minstens één assert, pytest.raises,
pytest.fail, pytest.warns, pytest.xfail of pytest.skip bevat. Zo kan een
test niet stilletjes groen blijven terwijl hij alleen maar print.
"""
import ast
import os

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

_ASSERTION_CALLS = {"raises", "fail", "warns", "xfail", "skip"}


def _heeft_assertion(functie):
    for node in ast.walk(functie):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "pytest"
                and func.attr in _ASSERTION_CALLS
            ):
                return True
    return False


def _testfuncties():
    for bestand in sorted(os.listdir(TESTS_DIR)):
        if not bestand.endswith(".py") or not bestand.startswith("test_"):
            continue
        pad = os.path.join(TESTS_DIR, bestand)
        with open(pad, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=pad)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                yield bestand, node


def test_elke_testfunctie_heeft_een_assertion():
    overtreders = [
        f"{bestand}::{node.name} (regel {node.lineno})"
        for bestand, node in _testfuncties()
        if not _heeft_assertion(node)
    ]
    assert not overtreders, "Testfuncties zonder assertion:\n" + "\n".join(overtreders)


def test_meta_test_ziet_overtreders():
    """Zelfcontrole: een testfunctie zonder assert wordt herkend."""
    boom = ast.parse("def test_x():\n    print('hoi')\n")
    functie = boom.body[0]
    assert _heeft_assertion(functie) is False
