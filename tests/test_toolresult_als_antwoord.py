"""Een ToolResult van een game-pc-tool is een normaal antwoord.

De remote-tools geven een ToolResult terug in plaats van tekst. Dat
leverde per opdracht "Onverwacht antwoordtype: ToolResult" in het log op,
terwijl het antwoord gewoon bruikbaar was.
"""

import logging

import core.brain as brain
from core.result_validation import ToolResult


def test_toolresult_wordt_tekst(monkeypatch, caplog):
    monkeypatch.setattr(
        brain,
        "_process_command_intern",
        lambda command, on_tekst=None: ToolResult(
            True, "discord draait momenteel."
        ),
    )

    with caplog.at_level(logging.WARNING, logger="core.brain"):
        antwoord = brain.process_command("is discord open")

    assert antwoord == "discord draait momenteel."
    assert "Onverwacht antwoordtype" not in caplog.text


def test_toolresult_zonder_tekst_geeft_altijd_een_zin(monkeypatch):
    monkeypatch.setattr(
        brain,
        "_process_command_intern",
        lambda command, on_tekst=None: ToolResult(False, ""),
    )

    antwoord = brain.process_command("iets onduidelijks")

    assert isinstance(antwoord, str)
    assert antwoord.strip()
