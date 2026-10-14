"""Tests voor core/tool_select.select_tools.

select_tools kiest per vraag een kleine set tools: altijd de basisset
plus maximaal twee passende categorieën, en nooit alle ~65 tools.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_registry import get_schema_tool_names
from core.tool_select import BASE_TOOLS, MAX_TOOLS, select_tools


def _all_tools():
    """Alle echte toolschema-namen als minimale tool-dicts."""
    return [
        {"type": "function", "function": {"name": name}}
        for name in sorted(get_schema_tool_names())
    ]


def _names(tools):
    return {tool["function"]["name"] for tool in tools}


def test_nooit_meer_dan_max_en_altijd_basisset():
    tools = _all_tools()
    vragen = [
        "zet de lamp aan",
        "zet het volume op 30",
        "open Discord",
        "open het bestand notities.txt",
        "open de website youtube.com",
        "zoek op youtube naar katten",
        "onthoud dat mijn favoriete game Elden Ring is",
        "klik op de knop verzenden",
        "hallo daar",
        "",
    ]
    for vraag in vragen:
        selectie = select_tools(vraag, tools)
        namen = _names(selectie)
        assert len(selectie) <= MAX_TOOLS, vraag
        for basis in BASE_TOOLS:
            assert basis in namen, (vraag, basis)


def test_ha_vraag_krijgt_ha_set():
    namen = _names(select_tools("zet de lamp aan", _all_tools()))
    assert "control_home_assistant" in namen
    assert "get_home_assistant_entities" in namen


def test_volume_vraag_krijgt_media_set():
    namen = _names(select_tools("zet het volume op 30", _all_tools()))
    assert "set_volume" in namen
    assert "media_play_pause" in namen
    # Geen Home Assistant-tools nodig bij een pure volume-vraag.
    assert "control_home_assistant" not in namen


def test_web_vraag_krijgt_web_tools():
    namen = _names(select_tools("open de website youtube.com", _all_tools()))
    assert "open_website" in namen


def test_vraag_zonder_categorie_krijgt_basisset_plus_fallback():
    namen = _names(select_tools("hallo daar allemaal", _all_tools()))
    # Basisset
    for basis in BASE_TOOLS:
        assert basis in namen
    # Fallback-categorieën: pc + bestanden
    assert "open_program" in namen
    assert "open_file" in namen
    # Nooit alles: geen Home Assistant-tools in de fallback.
    assert "control_home_assistant" not in namen


def test_select_tools_negeert_onbekende_namen():
    tools = [{"type": "function", "function": {"name": "onbekende_tool"}}]
    selectie = select_tools("zet de lamp aan", tools)
    assert selectie == []
