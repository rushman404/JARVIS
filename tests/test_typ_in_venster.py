"""Tests voor de directe route "typ <tekst> in <venster>".

Zonder deze route koos de LLM soms geen ui_type_text-tool en antwoordde hij
met een opsomming in plaats van te typen. De route is deterministisch en
valt terug op de LLM-tools als het venster niet gevonden wordt.
"""

from unittest.mock import patch

from actions.ui_automation import ToolResult
from core.brain import try_ui_automation


def test_typ_in_venster_typt_direct():
    gevonden = ToolResult(
        ok=True,
        message="Venster gevonden.",
        data={"handle": 123, "title": "Naamloos - Kladblok"},
    )

    with patch("core.brain.ui_find_window", return_value=gevonden) as zoek, patch(
        "core.brain.ui_activate_window", return_value=ToolResult(ok=True)
    ) as activeer, patch(
        "core.brain.ui_type_text", return_value=ToolResult(ok=True)
    ) as typ, patch("core.pc_target.is_remote", return_value=False):
        antwoord = try_ui_automation("typ test in kladblok")

    zoek.assert_called_once_with(title_substring="kladblok")
    activeer.assert_called_once_with(123)
    typ.assert_called_once_with(123, "test")
    assert "getypt" in antwoord


def test_typen_zonder_venster_gaat_naar_de_llm():
    mislukt = ToolResult(
        ok=False, message="Geen venster gevonden.", data={"handle": None}
    )

    with patch("core.brain.ui_find_window", return_value=mislukt), patch(
        "core.pc_target.is_remote", return_value=False
    ), patch("core.brain.ui_type_text") as typ:
        antwoord = try_ui_automation("typ test in kladblok")

    assert antwoord is None
    assert not typ.called


def test_typen_op_de_game_pc_blijft_bij_de_llm():
    with patch("core.pc_target.is_remote", return_value=True), patch(
        "core.brain.ui_find_window"
    ) as zoek:
        antwoord = try_ui_automation("typ test in kladblok")

    assert antwoord is None
    assert not zoek.called
