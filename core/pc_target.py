"""Fase 15B — standaarddoel van PC-bediening.

Sinds Fase 15B is de game-pc het werkstation: **alle** PC-bediening
gaat standaard naar de game-pc (via de remote-agent uit Fase 15). Deze
machine (de mini-pc) is het brein/de server en doet alleen mee als de
gebruiker hem expliciet noemt ("mini-pc", "server", "thuisserver").

* ``PC_TARGET`` (config.py, stap 6) bepaalt het standaarddoel. Zolang die
  instelling ontbreekt of niet ``game-pc`` is, blijft alles lokaal.
* "hier" / "deze pc" betekent de game-pc: de gebruiker zit achter het
  werkstation, niet achter de mini-pc die JARVIS draait.
* Expliciet "mini-pc"/"server" is de ENIGE uitzondering die lokaal
  uitvoert.

De module is bewust klein en zonder afhankelijkheden behalve ``config``,
zodat zowel de brein-routing (core/brain.py) als de tool-routering
(core/ai.py) dezelfde regel gebruiken.
"""

import os
import re

GAME_PC = "game-pc"
LOCAL = "local"

# Expliciete woorden waarmee de gebruiker de machine KAN bedoelen waarop
# JARVIS zelf draait. Alleen dan voeren we lokaal uit.
LOCAL_PATROON = re.compile(
    r"\b(?:mini[\s-]?pc|minipc|thuis[\s-]?server|thuisserver|server)\b"
)

# Aliasen voor de instelling die het standaarddoel op "game-pc" zet.
_GAME_PC_WAARDEN = frozenset(
    {"game-pc", "gamepc", "game pc", "game", "gaming-pc", "gamingpc", "remote"}
)


def mentions_local_pc(tekst):
    """True als de tekst expliciet de mini-pc/de server noemt."""

    return bool(LOCAL_PATROON.search((tekst or "").lower()))


def get_pc_target():
    """Het ingestelde standaarddoel: ``game-pc`` of ``local``.

    Leest ``config.PC_TARGET`` (of de omgevingsvariabele ``PC_TARGET``).
    Ontbreekt de instelling, dan is het doel **``local``** in stap 5.
    (Stap 6 zet dit naar ``game-pc`` als default.)
    """

    cfg = __import__("config")
    waarde = getattr(cfg, "PC_TARGET", None)

    if waarde is None:
        waarde = os.getenv("PC_TARGET")

    waarde = str(waarde or "").strip().lower()

    if waarde in _GAME_PC_WAARDEN:
        return GAME_PC

    return LOCAL


def resolve_target(command):
    """Het effectieve doel voor dit commando.

    Een expliciete "mini-pc"/"server" wint altijd van de instelling.
    """

    if mentions_local_pc(command):
        return LOCAL

    return get_pc_target()


def is_remote(command):
    """True als dit commando op de game-pc uitgevoerd moet worden."""

    if mentions_local_pc(command):
        return False
    return get_pc_target() == GAME_PC


# Lokale PC-tool -> de game-pc-twin. De risico's van beide zijn in stap 4
# bewust gelijkgetrokken, dus de goedkeuringspoort blijft kloppen.
LOCAL_TO_REMOTE = {
    # bestanden (lezen)
    "list_files": "game_pc_list_files",
    "open_folder": "game_pc_open_folder",
    "open_file": "game_pc_open_file",
    "search_files": "game_pc_search_files",
    "recent_files": "game_pc_recent_files",
    # bestanden (wijzigen)
    "create_folder": "game_pc_create_folder",
    "create_file": "game_pc_create_file",
    "copy_file": "game_pc_copy_file",
    "move_file": "game_pc_move_file",
    "rename_file": "game_pc_rename_file",
    "recycle_file": "game_pc_recycle_file",
    "empty_recycle_bin": "game_pc_empty_recycle_bin",
    # scherm / systeem
    "screenshot": "game_pc_screenshot",
    "pc_status": "game_pc_status",
    "set_volume": "game_pc_set_volume",
    "music_control": "game_pc_media",
    "open_program": "game_pc_open_program",
    "close_program": "game_pc_close_program",
    # vensters (UI)
    "ui_list_windows": "game_pc_ui_list_windows",
    "ui_find_window": "game_pc_ui_find_window",
    "ui_activate_window": "game_pc_ui_activate_window",
    "ui_list_elements": "game_pc_ui_list_elements",
    "ui_find_element": "game_pc_ui_find_element",
    "ui_get_value": "game_pc_ui_get_value",
    "ui_click_element": "game_pc_ui_click_element",
    "ui_type_text": "game_pc_ui_type_text",
    "ui_set_value": "game_pc_ui_set_value",
    "ui_launch_app": "game_pc_ui_launch_app",
    # power
    "power": "game_pc_power",
}


def remote_variant(tool_name):
    """De game_pc_*-twin van een lokale PC-tool, of None."""

    return LOCAL_TO_REMOTE.get((tool_name or "").strip())
