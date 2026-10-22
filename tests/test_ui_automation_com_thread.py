"""Tests dat UI-elementaanroepen via de COM-thread lopen.

Aanleiding: `ui_find_element` en `ui_get_value` riepen pywinauto rechtstreeks
aan vanuit de HTTP-workerthread van de agent. Daardoor hing de agent
(geen antwoord meer, ook geen gezondheidscheck) tot de client afbrak.
`list_elements` gebruikte als enige wél `run_on_com_thread`.
"""

import pytest

from actions import ui_automation
from core.result_validation import ToolResult


@pytest.fixture
def geen_pywinauto(monkeypatch):
    monkeypatch.setattr(ui_automation, "_import_pywinauto", lambda: (object, object))


def _maak_recorder(monkeypatch, resultaat=None):
    oproepen = []

    def nep(fn, *argumenten, **sleutels):
        oproepen.append(fn.__name__)
        return resultaat

    monkeypatch.setattr(ui_automation, "run_on_com_thread", nep)

    return oproepen


def _gevonden_element(handle=4242):
    return ToolResult(
        ok=True,
        message="Element gevonden.",
        data={
            "found": True,
            "matches": [{"type": "", "name": "Volume", "automation_id": "", "handle": handle}],
            "count": 1,
            "first": {"type": "", "name": "Volume", "automation_id": "", "handle": handle},
        },
    )


def test_find_element_haalt_de_boom_op_de_com_thread(monkeypatch, geen_pywinauto):
    oproepen = _maak_recorder(monkeypatch, resultaat=[])

    resultaat = ui_automation.find_element(12345, name="Volume")

    assert oproepen == ["_descendants"]
    assert resultaat.ok is False
    assert resultaat.data["count"] == 0


def test_get_value_leest_de_waarde_op_de_com_thread(monkeypatch, geen_pywinauto):
    oproepen = _maak_recorder(monkeypatch, resultaat="50")
    monkeypatch.setattr(ui_automation, "find_element", lambda *a, **k: _gevonden_element())

    resultaat = ui_automation.get_value(12345, name="Volume")

    assert oproepen == ["_lees"]
    assert resultaat.ok is True
    assert resultaat.data["value"] == "50"


def test_type_text_typt_op_de_com_thread(monkeypatch, geen_pywinauto):
    oproepen = _maak_recorder(monkeypatch, resultaat=None)
    monkeypatch.setattr(ui_automation, "find_element", lambda *a, **k: _gevonden_element())

    resultaat = ui_automation.type_text(12345, "hallo", element_name="Volume")

    assert oproepen == ["_type_element"]
    assert resultaat.ok is True


def test_type_text_zonder_element_gebruikt_het_venster(monkeypatch, geen_pywinauto):
    oproepen = _maak_recorder(monkeypatch, resultaat=None)

    resultaat = ui_automation.type_text(12345, "hallo")

    assert oproepen == ["_type_window"]
    assert resultaat.ok is True


def test_set_value_stelt_in_op_de_com_thread(monkeypatch, geen_pywinauto):
    oproepen = _maak_recorder(monkeypatch, resultaat=None)
    monkeypatch.setattr(ui_automation, "find_element", lambda *a, **k: _gevonden_element())

    resultaat = ui_automation.set_value(12345, "75", name="Volume")

    assert oproepen == ["_set"]
    assert resultaat.ok is True
