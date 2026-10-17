"""Tests voor core/tool_select.select_tools.

select_tools kiest per vraag een kleine set tools: altijd de basisset
plus maximaal twee passende categorieën, en nooit alle ~65 tools.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_registry import get_schema_tool_names
from core.tool_select import BASE_TOOLS, CATEGORIES, MAX_TOOLS, select_tools


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
    # Fallback-categorieën: pc + ui + systeem
    assert "open_program" in namen
    assert "ui_launch_app" in namen
    # Nooit alles: geen Home Assistant-tools in de fallback.
    assert "control_home_assistant" not in namen


def test_select_tools_negeert_onbekende_namen():
    tools = [{"type": "function", "function": {"name": "onbekende_tool"}}]
    selectie = select_tools("zet de lamp aan", tools)
    assert selectie == []


def test_elke_tool_zit_in_minstens_een_categorie():
    """Geen enkele tool mag buiten alle categorieën vallen."""
    schema = set(get_schema_tool_names())
    in_categorie = set(BASE_TOOLS)
    for tools in CATEGORIES.values():
        in_categorie.update(tools)
    ontbreekt = schema - in_categorie
    assert ontbreekt == set(), f"tools zonder categorie: {sorted(ontbreekt)}"


# Minimaal 30 gewone Nederlandse zinnen met de tool die erin moet zitten.
ZINNEN = [
    ("zet de lamp aan", "control_home_assistant"),
    ("zet het volume op 30", "set_volume"),
    ("open spotify", "open_program"),
    ("sluit chrome", "close_program"),
    ("wat is het weer in rotterdam", "web_search"),
    ("onthoud dat ik van koffie hou", "remember"),
    ("wat weet je over mij", "recall"),
    ("maak een screenshot", "screenshot"),
    ("hoeveel geheugen heb ik", "pc_status"),
    ("maak een map aan", "create_folder"),
    ("verplaats het bestand naar documenten", "move_file"),
    ("lees de pagina voor", "browser_get_content"),
    ("ga terug in de browser", "browser_back"),
    ("klik op opslaan", "ui_click_element"),
    ("type hallo in kladblok", "ui_type_text"),
    ("volgende nummer", "media_next"),
    ("pauzeer de muziek", "media_play_pause"),
    ("haal de pagina op", "web_fetch"),
    ("minimaliseer het venster", "minimize_window"),
    ("wat is de pc status", "pc_status"),
    ("zet de verwarming op 20 graden", "control_home_assistant"),
    ("vertel een mop", "system_info"),
    ("start discord", "open_program"),
    ("herstart spotify", "restart_program"),
    ("vergroot het venster", "maximize_window"),
    ("maak een nieuw bestand", "create_file"),
    ("kopieer het rapport naar downloads", "copy_file"),
    ("toon recente bestanden", "recent_files"),
    ("vergeet mijn adres", "forget"),
    ("stop de muziek", "media_stop"),
    ("zet het geluid harder", "volume_up"),
    ("open de website nu.nl", "open_website"),
    ("zoek op google naar katten", "web_search"),
    ("doe de lamp uit", "control_home_assistant"),
    ("wat is de temperatuur van mijn pc", "pc_status"),
    ("wat is de status van mijn pc", "pc_status"),
    ("zet de pc uit", "power"),
    ("verwijder bestand oud", "recycle_file"),
    ("leeg de prullenbak", "empty_recycle_bin"),
    ("hoe warm is mijn gpu", "pc_status"),
]


@pytest.mark.parametrize("zin,tool", ZINNEN)
def test_gewone_zin_krijgt_juiste_tool(zin, tool):
    selectie = select_tools(zin, _all_tools())
    namen = _names(selectie)
    assert tool in namen, (zin, tool)
    assert len(selectie) <= MAX_TOOLS, zin
