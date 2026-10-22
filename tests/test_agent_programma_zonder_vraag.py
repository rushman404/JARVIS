"""De game-pc-agent krijgt geen oorspronkelijke vraag mee.

Daardoor faalde ``open_program`` altijd: de controle ``has_program_hint``
zag een lege vraag en antwoordde "Welk programma wil je openen?" terwijl de
programmanaam (bijv. "discord") gewoon bekend was.

Deze test controleert dat een concrete naam zonder vraag gewoon opengaat.
"""

import sys

import pytest

sys.path.insert(0, 'C:\\JARVIS')

import core.ai as ai


@pytest.fixture
def laatste_program(monkeypatch):
    """Houd de globale context schoon en herstel hem daarna."""

    bewaard = ai.current_context.get("last_program")
    ai.current_context["last_program"] = None

    yield

    ai.current_context["last_program"] = bewaard


def test_open_program_zonder_vraag(monkeypatch, laatste_program):
    geopend = []
    monkeypatch.setattr(
        ai, "open_program_tool", lambda naam: geopend.append(naam) or f"Ik open {naam}."
    )

    resultaat = ai._dispatch_local_tool("open_program", {"program": "discord"}, "")

    assert geopend == ["discord"], "de agent moet de concrete naam gewoon openen"
    assert "Welk programma" not in str(resultaat)
    assert ai.current_context["last_program"] == "discord"


def test_close_program_zonder_vraag(monkeypatch, laatste_program):
    gesloten = []
    monkeypatch.setattr(
        ai, "close_program_tool", lambda naam: gesloten.append(naam) or f"Ik sluit {naam}."
    )

    resultaat = ai._dispatch_local_tool("close_program", {"program": "discord"}, "")

    assert gesloten == ["discord"]
    assert "Welk programma" not in str(resultaat)


def test_vage_naam_blijft_om_vraag_vragen(monkeypatch, laatste_program):
    """Zonder concrete naam én zonder vraag blijft de tegenvraag staan."""

    geopend = []
    monkeypatch.setattr(ai, "open_program_tool", lambda naam: geopend.append(naam) or "ok")

    resultaat = ai._dispatch_local_tool("open_program", {"program": "programma"}, "")

    assert geopend == []
    assert "Welk programma" in str(resultaat)


def test_met_vraag_zonder_hint_vraagt_om_programma(monkeypatch, laatste_program):
    """Lokale LLM-route: een vraag zonder programmawens vraagt om een naam."""

    geopend = []
    monkeypatch.setattr(ai, "open_program_tool", lambda naam: geopend.append(naam) or "ok")

    resultaat = ai._dispatch_local_tool(
        "open_program", {"program": "discord"}, "open het programma"
    )

    assert geopend == []
    assert "Welk programma" in str(resultaat)
