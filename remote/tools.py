"""Brug tussen het JARVIS-brein en de Game-PC Agent (Fase 15, stap 5).

Dit is de dunne laag tussen de JARVIS-tools en de beveiligde remote-client.
De JARVIS-tools (``game_pc_*`` en ``remote_command``) worden hier omgezet
naar **expliciet toegestane** acties van de agent en via
:class:`remote.client.RemoteClient` verstuurd.

Uitgangspunten
--------------
* **Alleen de allowlist** (:mod:`remote.allowlist`) bepaalt wat er op de
  game-pc mag draaien; ``remote_command`` is een gecontroleerde fallback
  naar diezelfde allowlist — nooit vrije shell-uitvoering.
* **Goedkeuring gebeurt op het brein** (via ``core.tool_registry``) vóór
  verzending; de server valideert daarna nog een keer.
* **Duidelijk onderscheid** tussen geslaagd, mislukt en onzeker:
  - ``geslaagd`` : de game-pc bevestigde de actie (``ok=True``).
  - ``mislukt``  : de actie is aantoonbaar niet uitgevoerd
    (niet bereikbaar, niet toegestaan, fout op de server).
  - ``onzeker``  : het verzoek kan de game-pc bereikt hebben, maar we
    kregen geen bevestiging (time-out, verbroken verbinding). We doen
    dan **niet** alsof het gelukt is.
"""

import logging

from core.result_validation import ToolResult

logger = logging.getLogger("jarvis.remote.tools")

# Alle JARVIS-toolnamen die via de game-pc-agent lopen.
REMOTE_TOOL_NAMES = frozenset(
    {
        # Bestaand (Fase 15)
        "game_pc_open_program",
        "game_pc_close_program",
        "game_pc_restart_program",
        "game_pc_program_status",
        "game_pc_status",
        "game_pc_telemetry",
        "game_pc_screenshot",
        "game_pc_media",
        "game_pc_set_volume",
        "remote_command",
        # Fase 15B - bestanden lezen
        "game_pc_list_files",
        "game_pc_open_folder",
        "game_pc_open_file",
        "game_pc_search_files",
        "game_pc_recent_files",
        # Fase 15B - bestanden wijzigen
        "game_pc_create_folder",
        "game_pc_create_file",
        "game_pc_copy_file",
        "game_pc_move_file",
        "game_pc_rename_file",
        # Fase 15B - UI
        "game_pc_ui_list_windows",
        "game_pc_ui_find_window",
        "game_pc_ui_activate_window",
        "game_pc_ui_list_elements",
        "game_pc_ui_find_element",
        "game_pc_ui_click_element",
        "game_pc_ui_type_text",
        "game_pc_ui_get_value",
        "game_pc_ui_set_value",
        "game_pc_ui_launch_app",
        # Fase 15B - verwijderen + power
        "game_pc_recycle_file",
        "game_pc_empty_recycle_bin",
        "game_pc_power",
        # Taak F - vensters, systeeminfo, audio per app, browser & websites
        "game_pc_find_program_location",
        "game_pc_minimize_window",
        "game_pc_maximize_window",
        "game_pc_restore_window",
        "game_pc_system_info",
        "game_pc_audio_list_sessions",
        "game_pc_audio_get_session_volume",
        "game_pc_audio_set_session_volume",
        "game_pc_audio_set_session_mute",
        "game_pc_audio_toggle_session_mute",
        "game_pc_audio_list_outputs",
        "game_pc_audio_get_default_output",
        "game_pc_audio_set_default_output",
        "game_pc_open_website",
        "game_pc_browser_search",
        "game_pc_browser_back",
        "game_pc_browser_forward",
        "game_pc_browser_refresh",
        "game_pc_browser_new_tab",
        "game_pc_browser_close_tab",
        # Fase 18 - meldingen van het brein op de game-pc tonen
        "game_pc_show_notification",
        # Fase 21 - film-modus: één app pauzeren
        "game_pc_media_pause_app",
        "game_pc_spotify_open",
        "game_pc_game_lijst",
        "game_pc_game_start",
        # Fase 23, M6 - Discord-DM's
        "game_pc_discord_dms",
        "game_pc_discord_antwoord",
        # Fase 28, M1 - klaar met updaten of downloaden?
        "game_pc_achtergrond_status",
    }
)

# Media-acties van de JARVIS-tool -> toegestane agent-tool.
MEDIA_ACTIES = {
    "play_pause": "media_play_pause",
    "next": "media_next",
    "previous": "media_previous",
    "stop": "media_stop",
    "mute": "media_mute",
    "volume_up": "volume_up",
    "volume_down": "volume_down",
}

# Interne soorten.
_COMMAND = "command"
_MEDIA = "media"
_TELEMETRY = "telemetry"
_RAW = "raw"

# JARVIS-toolnaam -> (soort, agent-tool, verplicht argument)
# Sommige tools hebben meerdere parameters; die worden via _RAW afgehandeld
# zodat de wrapper ze zonder de simpele spec-vorm aan te passen doorgeeft.
_SPECS = {
    # Bestaand
    "game_pc_open_program": (_COMMAND, "open_program", "program"),
    "game_pc_close_program": (_COMMAND, "close_program", "program"),
    "game_pc_restart_program": (_COMMAND, "restart_program", "program"),
    "game_pc_program_status": (_COMMAND, "program_status", "program"),
    "game_pc_status": (_COMMAND, "pc_status", None),
    "game_pc_screenshot": (_COMMAND, "screenshot", None),
    "game_pc_set_volume": (_COMMAND, "set_volume", "percent"),
    "game_pc_media": (_MEDIA, None, None),
    "game_pc_telemetry": (_TELEMETRY, None, None),
    # Fase 15B - enkele-parameter tools
    "game_pc_list_files": (_COMMAND, "list_files", "location"),
    "game_pc_open_folder": (_COMMAND, "open_folder", "location"),
    "game_pc_open_file": (_COMMAND, "open_file", "filename"),
    "game_pc_search_files": (_COMMAND, "search_files", "query"),
    "game_pc_recent_files": (_COMMAND, "recent_files", None),  # optioneel
    # Fase 15B - tools met meerdere parameters -> via _RAW (wrapper doet check)
    "game_pc_create_folder": (_RAW, "create_folder", None),
    "game_pc_create_file": (_RAW, "create_file", None),
    "game_pc_copy_file": (_RAW, "copy_file", None),
    "game_pc_move_file": (_RAW, "move_file", None),
    "game_pc_rename_file": (_RAW, "rename_file", None),
    # Fase 15B - UI tools met meerdere params -> via _RAW
    "game_pc_ui_list_windows": (_RAW, "ui_list_windows", None),
    "game_pc_ui_find_window": (_RAW, "ui_find_window", None),
    "game_pc_ui_activate_window": (_RAW, "ui_activate_window", None),
    "game_pc_ui_list_elements": (_RAW, "ui_list_elements", None),
    "game_pc_ui_find_element": (_RAW, "ui_find_element", None),
    "game_pc_ui_click_element": (_RAW, "ui_click_element", None),
    "game_pc_ui_type_text": (_RAW, "ui_type_text", None),
    "game_pc_ui_get_value": (_RAW, "ui_get_value", None),
    "game_pc_ui_set_value": (_RAW, "ui_set_value", None),
    "game_pc_ui_launch_app": (_RAW, "ui_launch_app", None),
    # Fase 15B - verwijderen + power
    "game_pc_recycle_file": (_COMMAND, "recycle_file", "filename"),
    "game_pc_empty_recycle_bin": (_COMMAND, "empty_recycle_bin", None),
    "game_pc_power": (_COMMAND, "power", "action"),
    # Taak F - vensters + zoek programma + systeeminfo
    "game_pc_find_program_location": (_COMMAND, "find_program_location", "program"),
    "game_pc_minimize_window": (_COMMAND, "minimize_window", "program"),
    "game_pc_maximize_window": (_COMMAND, "maximize_window", "program"),
    "game_pc_restore_window": (_COMMAND, "restore_window", "program"),
    "game_pc_system_info": (_COMMAND, "system_info", None),
    # Taak F - audio per app
    "game_pc_audio_list_sessions": (_COMMAND, "audio_list_sessions", None),
    "game_pc_audio_get_session_volume": (_COMMAND, "audio_get_session_volume", "app_name"),
    "game_pc_audio_toggle_session_mute": (_COMMAND, "audio_toggle_session_mute", "app_name"),
    "game_pc_audio_list_outputs": (_COMMAND, "audio_list_outputs", None),
    "game_pc_audio_get_default_output": (_COMMAND, "audio_get_default_output", None),
    "game_pc_audio_set_default_output": (_COMMAND, "audio_set_default_output", "device_name"),
    # Taak F - audio met meerdere parameters -> via _RAW
    "game_pc_audio_set_session_volume": (_RAW, "audio_set_session_volume", None),
    "game_pc_audio_set_session_mute": (_RAW, "audio_set_session_mute", None),
    # Taak F - browser & websites
    "game_pc_open_website": (_COMMAND, "open_website", "url"),
    "game_pc_browser_back": (_COMMAND, "browser_back", None),
    "game_pc_browser_forward": (_COMMAND, "browser_forward", None),
    "game_pc_browser_refresh": (_COMMAND, "browser_refresh", None),
    "game_pc_browser_new_tab": (_COMMAND, "browser_new_tab", None),
    "game_pc_browser_close_tab": (_COMMAND, "browser_close_tab", None),
    "game_pc_browser_search": (_RAW, "browser_search", None),
    # Fase 18 - melding (titel + tekst) -> via _RAW
    "game_pc_show_notification": (_RAW, "show_notification", None),
    "game_pc_media_pause_app": (_COMMAND, "media_pause_app", "app_name"),
    "game_pc_spotify_open": (_COMMAND, "spotify_open", "uri"),
    "game_pc_game_lijst": (_COMMAND, "game_lijst", None),
    "game_pc_game_start": (_COMMAND, "game_start", "game_id"),
    "game_pc_discord_dms": (_COMMAND, "discord_dms", None),
    "game_pc_achtergrond_status": (_COMMAND, "achtergrond_status", None),
    "game_pc_discord_antwoord": (_RAW, "discord_antwoord", None),
    "remote_command": (_RAW, None, None),
}

# Foutcodes waarbij we niet zeker weten of de actie is uitgevoerd.
_ONZEKER_CODES = frozenset({"timeout", "verbinding_verbroken"})

_CLIENT = None


def is_remote_tool(tool_name):
    """True als dit een game-pc-tool is."""

    return str(tool_name or "").strip() in REMOTE_TOOL_NAMES


def _get_client():
    """Maakt (eenmalig) de remote-client.

    Fail-closed: ontbreekt de beveiligingsconfiguratie of staat de client
    uit, dan geeft dit een ``ValueError`` en versturen we niets.
    """

    global _CLIENT

    if _CLIENT is not None:
        return _CLIENT

    from remote.client import RemoteClient

    client = RemoteClient()

    if not getattr(client, "enabled", False):
        raise ValueError(
            "de game-pc-agent staat uit (REMOTE_CLIENT_ENABLED staat niet aan)."
        )

    _CLIENT = client
    return client


def _reset_client():
    """Vergeet de gecachte client (voor tests en herconfiguratie)."""

    global _CLIENT
    _CLIENT = None


def execute_remote_tool(tool_name, arguments=None, question=None):
    """Voert één game-pc-tool uit en geeft een :class:`ToolResult` terug."""

    naam = str(tool_name or "").strip()
    spec = _SPECS.get(naam)

    if spec is None:
        return _mislukt(
            f"Onbekende game-pc-actie: {naam or 'leeg'}.", "remote_onbekend"
        )

    arguments = arguments if isinstance(arguments, dict) else {}

    try:
        client = _get_client()
    except ValueError as fout:
        return _mislukt(f"De game-pc-agent is niet beschikbaar: {fout}", "remote_config")

    soort = spec[0]

    if soort == _TELEMETRY:
        return _telemetrie_resultaat(client)

    if soort == _MEDIA:
        return _media_resultaat(client, arguments)

    if soort == _RAW:
        # Voor multi-parameter wrappers mappen we game_pc_* naar agent-tool
        wrapper_to_agent = {
            "game_pc_create_folder": "create_folder",
            "game_pc_create_file": "create_file",
            "game_pc_copy_file": "copy_file",
            "game_pc_move_file": "move_file",
            "game_pc_rename_file": "rename_file",
            "game_pc_ui_list_windows": "ui_list_windows",
            "game_pc_ui_find_window": "ui_find_window",
            "game_pc_ui_activate_window": "ui_activate_window",
            "game_pc_ui_list_elements": "ui_list_elements",
            "game_pc_ui_find_element": "ui_find_element",
            "game_pc_ui_click_element": "ui_click_element",
            "game_pc_ui_type_text": "ui_type_text",
            "game_pc_ui_get_value": "ui_get_value",
            "game_pc_ui_set_value": "ui_set_value",
            "game_pc_ui_launch_app": "ui_launch_app",
            # Taak F - multi-parameter twins
            "game_pc_audio_set_session_volume": "audio_set_session_volume",
            "game_pc_audio_set_session_mute": "audio_set_session_mute",
            "game_pc_browser_search": "browser_search",
            "game_pc_show_notification": "show_notification",
            "game_pc_discord_antwoord": "discord_antwoord",
        }
        if naam in wrapper_to_agent:
            agent_tool = wrapper_to_agent[naam]
            # validate via allowlist
            from remote import allowlist

            schoon, reden = allowlist.validate_call(agent_tool, arguments)
            if schoon is None:
                return _mislukt(reden, "remote_niet_toegestaan")
            return _command_resultaat(client, agent_tool, schoon, naam)
        return _raw_resultaat(client, arguments)

    remote_tool = spec[1]
    arg_naam = spec[2]

    if arg_naam:
        waarde = arguments.get(arg_naam)
        if waarde is None or (isinstance(waarde, str) and not waarde.strip()):
            return _mislukt(
                f"Voor '{naam}' is het argument '{arg_naam}' verplicht.",
                "remote_argumenten",
            )
        remote_args = {arg_naam: waarde}
    else:
        remote_args = {}

    # Dezelfde strikte controle als bij de multi-parameter wrappers: nooit
    # iets naar de game-pc sturen dat de allowlist zou weigeren.
    from remote import allowlist

    schoon, reden = allowlist.validate_call(remote_tool, remote_args)
    if schoon is None:
        return _mislukt(reden, "remote_niet_toegestaan")

    return _command_resultaat(client, remote_tool, schoon, naam)


# ------------------------------------------------------------------
# Interne helpers
# ------------------------------------------------------------------


def _mislukt(melding, code):
    return ToolResult(False, melding, data={"status": "mislukt"}, error_kind=code)


# Acties die op de game-pc langer duren dan de gewone time-out.
LANGE_ACTIES = {"discord_antwoord": 50.0}


def _command_resultaat(client, remote_tool, remote_args, jarvis_tool):
    extra = LANGE_ACTIES.get(remote_tool)
    if extra is None:
        resultaat = client.send_command(remote_tool, remote_args)
    else:
        oud = client.timeout
        client.timeout = max(float(oud), extra)
        try:
            resultaat = client.send_command(remote_tool, remote_args)
        finally:
            client.timeout = oud
    return _naar_toolresult(resultaat, jarvis_tool, remote_tool)


def _naar_toolresult(resultaat, jarvis_tool, remote_tool):
    data = {
        "remote_tool": remote_tool,
        "pogingen": getattr(resultaat, "pogingen", 1),
        "status_code": getattr(resultaat, "status", 0),
    }

    if resultaat.ok:
        melding = _bericht(resultaat.resultaat) or (
            f"De game-pc heeft '{remote_tool}' uitgevoerd."
        )
        data["status"] = "geslaagd"
        data["resultaat"] = resultaat.resultaat
        return ToolResult(True, melding, data=data)

    code = getattr(resultaat, "fout_code", "")
    data["fout_code"] = code

    if code in _ONZEKER_CODES:
        data["status"] = "onzeker"
        detail = getattr(resultaat, "fout_melding", "") or "de verbinding viel weg."
        return ToolResult(
            False,
            f"Ik weet niet zeker of de game-pc '{remote_tool}' heeft uitgevoerd: {detail}",
            data=data,
            error_kind="remote_onzeker",
        )

    data["status"] = "mislukt"
    melding = getattr(resultaat, "fout_melding", "") or (
        f"De opdracht '{remote_tool}' op de game-pc is mislukt."
    )
    return ToolResult(False, melding, data=data, error_kind="remote_mislukt")


def _media_resultaat(client, arguments):
    actie = str(arguments.get("action", "")).strip().lower()
    remote_tool = MEDIA_ACTIES.get(actie)

    if remote_tool is None:
        return _mislukt(
            f"Onbekende media-actie '{actie or 'leeg'}' voor de game-pc.",
            "remote_onbekend",
        )

    return _command_resultaat(client, remote_tool, {}, "game_pc_media")


def _raw_resultaat(client, arguments):
    from remote import allowlist

    remote_tool = str(arguments.get("tool", "")).strip()
    remote_args = arguments.get("arguments") or {}

    if not isinstance(remote_args, dict):
        return _mislukt(
            "De 'arguments' van remote_command moeten een object zijn.",
            "remote_argumenten",
        )

    if not allowlist.is_allowed(remote_tool):
        return _mislukt(
            f"'{remote_tool or 'deze actie'}' is niet toegestaan op de game-pc.",
            "remote_niet_toegestaan",
        )

    return _command_resultaat(client, remote_tool, remote_args, "remote_command")


def _telemetrie_resultaat(client):
    resultaat = client.telemetry()
    tool_result = _naar_toolresult(resultaat, "game_pc_telemetry", "telemetry")

    if tool_result.ok:
        telemetrie = resultaat.resultaat
        if isinstance(telemetrie, dict) and isinstance(telemetrie.get("telemetrie"), dict):
            telemetrie = telemetrie["telemetrie"]
        tool_result.data["telemetrie"] = telemetrie
        tool_result.message = _telemetrie_samenvatting(telemetrie)

    return tool_result


def _bericht(resultaat):
    if isinstance(resultaat, str):
        return resultaat.strip()

    if isinstance(resultaat, dict):
        for sleutel in ("message", "melding", "resultaat", "result"):
            waarde = resultaat.get(sleutel)
            if isinstance(waarde, str) and waarde.strip():
                return waarde.strip()

    return ""


def _telemetrie_samenvatting(telemetrie):
    """Korte Nederlandse samenvatting van de telemetrie."""

    try:
        if not isinstance(telemetrie, dict):
            return "Ik heb de status van de game-pc opgehaald."

        delen = []

        cpu = telemetrie.get("cpu")
        if isinstance(cpu, dict) and cpu.get("gebruik_percent") is not None:
            delen.append(f"CPU {cpu['gebruik_percent']}%")

        ram = telemetrie.get("ram")
        if isinstance(ram, dict) and ram.get("percentage") is not None:
            delen.append(f"geheugen {ram['percentage']}%")

        gpu = telemetrie.get("gpu")
        if isinstance(gpu, dict):
            gpus = gpu.get("gpus")
            if isinstance(gpus, list) and gpus and isinstance(gpus[0], dict):
                kaart = gpus[0]
                onderdelen = [str(kaart.get("naam") or "GPU")]
                if kaart.get("gebruik_percent") is not None:
                    onderdelen.append(f"{kaart['gebruik_percent']}%")
                if kaart.get("temperatuur_c") is not None:
                    onderdelen.append(f"{kaart['temperatuur_c']}°C")
                delen.append("GPU " + " ".join(onderdelen))

        if not delen:
            return "Ik heb de status van de game-pc opgehaald."

        return "De game-pc: " + ", ".join(delen) + "."

    except Exception:  # telemetrie mag nooit een crash veroorzaken
        return "Ik heb de status van de game-pc opgehaald."
