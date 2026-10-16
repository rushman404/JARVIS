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
    "game_pc_create_folder": (_RAW, None, None),
    "game_pc_create_file": (_RAW, None, None),
    "game_pc_copy_file": (_RAW, None, None),
    "game_pc_move_file": (_RAW, None, None),
    "game_pc_rename_file": (_RAW, None, None),
    # Fase 15B - UI tools met meerdere params -> via _RAW
    "game_pc_ui_list_windows": (_RAW, None, None),
    "game_pc_ui_find_window": (_RAW, None, None),
    "game_pc_ui_activate_window": (_RAW, None, None),
    "game_pc_ui_list_elements": (_RAW, None, None),
    "game_pc_ui_find_element": (_RAW, None, None),
    "game_pc_ui_click_element": (_RAW, None, None),
    "game_pc_ui_type_text": (_RAW, None, None),
    "game_pc_ui_get_value": (_RAW, None, None),
    "game_pc_ui_set_value": (_RAW, None, None),
    "game_pc_ui_launch_app": (_RAW, None, None),
    # Fase 15B - verwijderen + power
    "game_pc_recycle_file": (_COMMAND, "recycle_file", "filename"),
    "game_pc_empty_recycle_bin": (_COMMAND, "empty_recycle_bin", None),
    "game_pc_power": (_COMMAND, "power", "action"),
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


def _command_resultaat(client, remote_tool, remote_args, jarvis_tool):
    resultaat = client.send_command(remote_tool, remote_args)
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
