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


def remote_client_configuratie_fout():
    """Eén melding als het doel game-pc is maar de client onbruikbaar is.

    Geeft een leesbare melding terug als ``PC_TARGET`` op ``game-pc``
    staat terwijl de client uit staat of onvolledig geconfigureerd is
    (geen of te kort token, geen vertrouwd certificaat). Geeft ``None``
    terug als het doel local is of als de client compleet lijkt.
    """

    if get_pc_target() != GAME_PC:
        return None

    cfg = __import__("config")

    if not getattr(cfg, "REMOTE_CLIENT_ENABLED", False):
        return (
            "PC_TARGET staat op 'game-pc', maar de game-pc-agent staat uit "
            "(REMOTE_CLIENT_ENABLED staat niet aan). Commando's voor de "
            "game-pc werken niet; deze pc wordt niet lokaal bediend."
        )

    token = str(getattr(cfg, "REMOTE_CLIENT_TOKEN", "") or "")
    minimaal = int(getattr(cfg, "REMOTE_MIN_TOKEN_LENGTH", 16))
    ca_file = str(getattr(cfg, "REMOTE_CLIENT_CA_FILE", "") or "")

    ontbrekend = []

    if len(token) < minimaal:
        ontbrekend.append(f"REMOTE_CLIENT_TOKEN is leeg of korter dan {minimaal} tekens")

    if not ca_file:
        ontbrekend.append("REMOTE_CLIENT_CA_FILE ontbreekt")

    if not ontbrekend:
        return None

    return (
        "PC_TARGET staat op 'game-pc', maar de game-pc-client is niet compleet "
        "geconfigureerd (" + "; ".join(ontbrekend) + "). Commando's voor de "
        "game-pc werken niet; deze pc wordt niet lokaal bediend."
    )


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
    "restart_program": "game_pc_restart_program",
    "program_status": "game_pc_program_status",
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
    # vensters (native)
    "minimize_window": "game_pc_minimize_window",
    "maximize_window": "game_pc_maximize_window",
    "restore_window": "game_pc_restore_window",
    # programma's zoeken
    "find_program_location": "game_pc_find_program_location",
    # audio per app
    "audio_list_sessions": "game_pc_audio_list_sessions",
    "audio_get_session_volume": "game_pc_audio_get_session_volume",
    "audio_set_session_volume": "game_pc_audio_set_session_volume",
    "audio_set_session_mute": "game_pc_audio_set_session_mute",
    "audio_toggle_session_mute": "game_pc_audio_toggle_session_mute",
    "audio_list_outputs": "game_pc_audio_list_outputs",
    "audio_get_default_output": "game_pc_audio_get_default_output",
    "audio_set_default_output": "game_pc_audio_set_default_output",
    # systeeminfo
    "system_info": "game_pc_system_info",
    # meldingen (toast)
    "show_notification": "game_pc_show_notification",
    "media_pause_app": "game_pc_media_pause_app",
    "spotify_open": "game_pc_spotify_open",
    "game_lijst": "game_pc_game_lijst",
    "game_start": "game_pc_game_start",
    "discord_dms": "game_pc_discord_dms",
    "achtergrond_status": "game_pc_achtergrond_status",
    "discord_antwoord": "game_pc_discord_antwoord",
    # browser / websites
    "open_website": "game_pc_open_website",
    "browser_search": "game_pc_browser_search",
    "browser_back": "game_pc_browser_back",
    "browser_forward": "game_pc_browser_forward",
    "browser_refresh": "game_pc_browser_refresh",
    "browser_new_tab": "game_pc_browser_new_tab",
    "browser_close_tab": "game_pc_browser_close_tab",
}


def remote_variant(tool_name):
    """De game_pc_*-twin van een lokale PC-tool, of None."""

    return LOCAL_TO_REMOTE.get((tool_name or "").strip())


# Media-tools hebben geen één-op-één-twin: op de game-pc gaan ze allemaal
# via game_pc_media met een "action". Zonder deze tabel draaiden
# media_play_pause, media_next enz. op het brein zelf terwijl het doel de
# game-pc was (het auditlog zei "gelukt", maar er gebeurde niets).
MEDIA_NAAR_REMOTE = {
    "media_play_pause": "play_pause",
    "media_next": "next",
    "media_previous": "previous",
    "media_stop": "stop",
    "media_mute": "mute",
    "volume_up": "volume_up",
    "volume_down": "volume_down",
}


def remote_aanroep(tool_name, arguments=None):
    """``(twin, argumenten)`` voor de game-pc, of ``None`` als er geen twin is.

    Gewone tools houden hun argumenten; media-tools worden
    ``game_pc_media`` met de bijbehorende ``action``.
    """

    naam = (tool_name or "").strip()
    actie = MEDIA_NAAR_REMOTE.get(naam)
    if actie is not None:
        return "game_pc_media", {"action": actie}
    twin = LOCAL_TO_REMOTE.get(naam)
    if twin is None:
        return None
    return twin, arguments or {}


# ------------------------------------------------------------------
# Classificatie van elke pc-bedienende functie die core/brain.py
# direct aanroept (Fase 15B, stap F).
# ------------------------------------------------------------------
#
# Drie soorten:
#   * ``remote``        — hoort op de game-pc: het brein stuurt de twin
#     (via core.ai.execute_tool) en raakt de lokale functie nooit aan.
#   * ``geblokkeerd``   — kan (nog) niet op de game-pc en mag dus NOOIT
#     stil lokaal draaien; de gebruiker krijgt een duidelijke melding.
#   * ``onafhankelijk`` — geen PC-bediening (opzoeken, web, pad-omzetting):
#     die mag gewoon lokaal blijven werken.
#
# De sleutels zijn exact de namen zoals core/brain.py ze importeert
# (inclusief aliassen), zodat de pariteitstest ze kan controleren.

ACTIE_REMOTE = "remote"
ACTIE_GEBLOKKEERD = "geblokkeerd"
ACTIE_ONAFHANKELIJK = "onafhankelijk"

# functienaam (zoals in brain.py) -> (soort, twin-toolnaam of None)
PC_ACTIES = {
    # programma's (core.tools)
    "open_program_tool": (ACTIE_REMOTE, "game_pc_open_program"),
    "close_program_tool": (ACTIE_REMOTE, "game_pc_close_program"),
    "pc_status_tool": (ACTIE_REMOTE, "game_pc_status"),
    # programma's (actions.pc)
    "minimize_program": (ACTIE_REMOTE, "game_pc_minimize_window"),
    "maximize_program": (ACTIE_REMOTE, "game_pc_maximize_window"),
    "restore_window": (ACTIE_REMOTE, "game_pc_restore_window"),
    "get_program_status": (ACTIE_REMOTE, "game_pc_program_status"),
    "restart_program": (ACTIE_REMOTE, "game_pc_restart_program"),
    "find_program_location": (ACTIE_REMOTE, "game_pc_find_program_location"),
    "open_website": (ACTIE_REMOTE, "game_pc_open_website"),
    # media / volume (actions.media)
    "play_pause": (ACTIE_REMOTE, "game_pc_media"),
    "next_track": (ACTIE_REMOTE, "game_pc_media"),
    "previous_track": (ACTIE_REMOTE, "game_pc_media"),
    "volume_up": (ACTIE_REMOTE, "game_pc_media"),
    "volume_down": (ACTIE_REMOTE, "game_pc_media"),
    "toggle_mute": (ACTIE_REMOTE, "game_pc_media"),
    "set_volume": (ACTIE_REMOTE, "game_pc_set_volume"),
    # audio per app (actions.audio)
    "audio_list_sessions": (ACTIE_REMOTE, "game_pc_audio_list_sessions"),
    "audio_get_session_volume": (ACTIE_REMOTE, "game_pc_audio_get_session_volume"),
    "audio_set_session_volume": (ACTIE_REMOTE, "game_pc_audio_set_session_volume"),
    "audio_set_session_mute": (ACTIE_REMOTE, "game_pc_audio_set_session_mute"),
    "audio_toggle_session_mute": (ACTIE_REMOTE, "game_pc_audio_toggle_session_mute"),
    "audio_list_outputs": (ACTIE_REMOTE, "game_pc_audio_list_outputs"),
    "audio_get_default_output": (ACTIE_REMOTE, "game_pc_audio_get_default_output"),
    "audio_set_default_output": (ACTIE_REMOTE, "game_pc_audio_set_default_output"),
    # systeeminfo (actions.system)
    "cpu_info": (ACTIE_REMOTE, "game_pc_system_info"),
    "ram_info": (ACTIE_REMOTE, "game_pc_system_info"),
    "disk_info": (ACTIE_REMOTE, "game_pc_system_info"),
    "gpu_names": (ACTIE_REMOTE, "game_pc_system_info"),
    "os_info": (ACTIE_REMOTE, "game_pc_system_info"),
    "uptime": (ACTIE_REMOTE, "game_pc_system_info"),
    "system_summary": (ACTIE_REMOTE, "game_pc_system_info"),
    "screen_info": (ACTIE_GEBLOKKEERD, None),
    "battery_info": (ACTIE_GEBLOKKEERD, None),
    # scherm (actions.screenshot)
    "take_screenshot": (ACTIE_REMOTE, "game_pc_screenshot"),
    # power (actions.power)
    "lock_pc": (ACTIE_REMOTE, "game_pc_power"),
    "sleep_pc": (ACTIE_REMOTE, "game_pc_power"),
    "shutdown_pc": (ACTIE_REMOTE, "game_pc_power"),
    "restart_pc": (ACTIE_REMOTE, "game_pc_power"),
    "logoff_pc": (ACTIE_REMOTE, "game_pc_power"),
    "cancel_shutdown": (ACTIE_REMOTE, "game_pc_power"),
    # bestanden (actions.file_manager)
    "create_folder": (ACTIE_REMOTE, "game_pc_create_folder"),
    "create_file": (ACTIE_REMOTE, "game_pc_create_file"),
    "rename_file": (ACTIE_REMOTE, "game_pc_rename_file"),
    "list_folder": (ACTIE_REMOTE, "game_pc_list_files"),
    "get_recent_files": (ACTIE_REMOTE, "game_pc_recent_files"),
    "copy_path": (ACTIE_REMOTE, "game_pc_copy_file"),
    "move_path": (ACTIE_REMOTE, "game_pc_move_file"),
    "send_to_recycle": (ACTIE_REMOTE, "game_pc_recycle_file"),
    "empty_recycle_bin": (ACTIE_REMOTE, "game_pc_empty_recycle_bin"),
    "open_folder": (ACTIE_REMOTE, "game_pc_open_folder"),
    "search_files": (ACTIE_REMOTE, "game_pc_search_files"),
    # bestand kiezen/openen zonder remote-twin: fail-closed blokkeren
    "open_confirmed": (ACTIE_GEBLOKKEERD, None),
    "open_path": (ACTIE_GEBLOKKEERD, None),
    # browser / websites (actions.browser)
    "browser_search": (ACTIE_REMOTE, "game_pc_browser_search"),
    "browser_back": (ACTIE_REMOTE, "game_pc_browser_back"),
    "browser_forward": (ACTIE_REMOTE, "game_pc_browser_forward"),
    "browser_refresh": (ACTIE_REMOTE, "game_pc_browser_refresh"),
    "browser_new_tab": (ACTIE_REMOTE, "game_pc_browser_new_tab"),
    "browser_close_tab": (ACTIE_REMOTE, "game_pc_browser_close_tab"),
    # browser uitlezen: geen remote-twin, dus fail-closed
    "get_browser_content": (ACTIE_GEBLOKKEERD, None),
    "get_browser_title": (ACTIE_GEBLOKKEERD, None),
    "get_browser_url": (ACTIE_GEBLOKKEERD, None),
    # vensters (UI-automatisering)
    "ui_list_windows": (ACTIE_REMOTE, "game_pc_ui_list_windows"),
    "ui_find_window": (ACTIE_REMOTE, "game_pc_ui_find_window"),
    "ui_activate_window": (ACTIE_REMOTE, "game_pc_ui_activate_window"),
    # tekst typen in een venster ("typ test in kladblok"); voor de game-pc
    # laat de brain het aan de LLM-tool game_pc_ui_type_text over.
    "ui_type_text": (ACTIE_REMOTE, "game_pc_ui_type_text"),
    # opzoeken / hulpfuncties (geen PC-bediening)
    "find_program": (ACTIE_ONAFHANKELIJK, None),
    "find_item": (ACTIE_ONAFHANKELIJK, None),
    "list_folder_by_path": (ACTIE_ONAFHANKELIJK, None),
    "resolve_location": (ACTIE_ONAFHANKELIJK, None),
    # web (geen PC-bediening)
    "fetch_url": (ACTIE_ONAFHANKELIJK, None),
    "format_fetch_result": (ACTIE_ONAFHANKELIJK, None),
    "search_and_fetch": (ACTIE_ONAFHANKELIJK, None),
    "format_search_and_fetch": (ACTIE_ONAFHANKELIJK, None),
    "get_weather": (ACTIE_ONAFHANKELIJK, None),
    "format_weather": (ACTIE_ONAFHANKELIJK, None),
}


def actie_classificatie(functienaam):
    """(soort, twin) van een pc-functie; onbekend = onafhankelijk."""

    return PC_ACTIES.get(
        (functienaam or "").strip(), (ACTIE_ONAFHANKELIJK, None)
    )


def remote_twin(functienaam):
    """De game_pc_*-twin van een pc-functie, of None."""

    return actie_classificatie(functienaam)[1]


def blokkade_bericht(functienaam=None):
    """Duidelijke melding voor een actie die niet remote kan."""

    return "Dat kan ik nog niet op de game-pc."
