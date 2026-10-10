"""Centrale risico- en goedkeuringslaag voor alle toolaanroepen.

Bevat:
    - TOOL_RISK: vaste tabel toolnaam -> (risico, idempotent).
    - get_tool_risk(): risico van een tool, gebaseerd op de VASTE tabel.
      Een risico dat de LLM zelf in een plan zet (step["risk"]) wordt
      hier bewust genegeerd.
    - run_tool_guarded(): één centrale toegangspoort die ALLE
      toolaanroepen moeten doorlopen (executor, agent én ai.execute_tool).

Risiconiveaus:
    low    -> direct uitvoeren.
    medium -> eerst om bevestiging vragen.
    high   -> eerst om bevestiging vragen (zelfde pad als medium).
    Onbekende tools zijn fail-safe "medium".
"""

import re

from core.confirmation import set_pending, clear_pending
from core.audit import log_audit

# =========================================================
# VASTE RISICOTABEL
# =========================================================

TOOL_RISK = {
    # ---- Hoog risico: starten van willekeurige apps ----
    "ui_launch_app": ("high", False),

    # ---- Medium risico: tekst typen / waarden aanpassen ----
    "ui_type_text": ("medium", False),
    "ui_set_value": ("medium", False),
    "ui_click_element": ("medium", False),

    # ---- Medium risico: bestanden wijzigen / verplaatsen ----
    "move_file": ("medium", True),
    "copy_file": ("medium", True),
    "rename_file": ("medium", True),
    "create_folder": ("medium", True),
    "create_file": ("medium", True),
    "delete_file": ("high", False),
    "restart_program": ("medium", False),

    # ---- Home Assistant (risico hangt af van het domein) ----
    #  light -> low,  cover/switch -> medium  (in get_tool_risk)
    "control_home_assistant": ("medium", False),

    # ---- Leggedige/leestools: low ----
    "open_file": ("low", True),
    "open_website": ("low", True),
    "open_program": ("low", True),
    "close_program": ("low", True),
    "remember": ("low", True),
    "recall": ("low", True),
    "forget": ("low", True),
    "media_play_pause": ("low", False),
    "media_next": ("low", True),
    "media_previous": ("low", True),
    "media_stop": ("low", True),
    "media_volume_up": ("low", True),
    "media_volume_down": ("low", True),
    "media_set_volume": ("low", True),
    "media_mute": ("low", True),
    "system_info": ("low", True),
    "screenshot": ("low", True),
    "minimize_window": ("low", True),
    "maximize_window": ("low", True),
    "restore_window": ("low", True),
    "list_files": ("low", True),
    "open_folder": ("low", True),
    "search_files": ("low", True),
    "recent_files": ("low", True),
    "program_status": ("low", True),
    "find_program_location": ("low", True),
    "browser_search": ("low", True),
    "browser_back": ("low", True),
    "browser_forward": ("low", True),
    "browser_refresh": ("low", True),
    "browser_new_tab": ("low", True),
    "browser_close_tab": ("low", True),
    "web_fetch": ("low", True),
    "web_search": ("low", True),
    "web_search_and_fetch": ("low", True),
    "weather": ("low", True),
    "wikipedia": ("low", True),
    "ui_list_windows": ("low", True),
    "ui_find_window": ("low", True),
    "ui_activate_window": ("low", True),
    "ui_list_elements": ("low", True),
    "ui_find_element": ("low", True),
    "ui_get_value": ("low", True),
    "audio_list_sessions": ("low", True),
    "audio_get_session_volume": ("low", True),
    "audio_set_session_volume": ("medium", True),
    "audio_set_session_mute": ("medium", True),
    "audio_toggle_session_mute": ("medium", True),
    "audio_list_outputs": ("low", True),
    "audio_get_default_output": ("low", True),
    "audio_set_default_output": ("medium", True),
    "calculate": ("low", True),
    "get_information": ("low", True),
}

# Risico van een onbekende tool (fail-safe)
DEFAULT_RISK = "medium"

RISK_LEVELS = ("low", "medium", "high")

# Medium en hoog vereisen goedkeuring
APPROVAL_REQUIRED_RISKS = ("medium", "high")


def get_tool_risk(tool_name, arguments=None):
    """Risico van een tool uit de VASTE tabel.

    argumenten-notatie wordt alleen gebruikt voor tools waarbij het
    risico afhangt van het doel (Home Assistant-domein).
    """

    if not tool_name:
        return DEFAULT_RISK

    tool_name = tool_name.strip()

    entry = TOOL_RISK.get(tool_name)

    if entry is None:
        return DEFAULT_RISK

    risk = entry[0]

    # Home Assistant: risico hangt af van het domein (cover/switch
    # medium, light low). Verder zo ver mogelijk terugvallen op de
    # tabelwaarde, zodat een onbekend domein niet "low" wordt.
    if tool_name == "control_home_assistant":
        domain = None

        if isinstance(arguments, dict):
            domain = arguments.get("domain") or arguments.get("domein")
            if not domain and arguments.get("entity"):
                domain = re.split(r"\s|\.", str(arguments.get("entity")))[0]

        if domain in ("cover", "switch"):
            return "medium"

        if domain == "light":
            return "low"

        return "medium"

    return risk


def get_tool_idempotent(tool_name):
    """Of de tool veilig meerdere keren kan draaien (idempotent)."""

    if not tool_name:
        return False

    entry = TOOL_RISK.get(tool_name.strip())

    if entry is None:
        return False

    return bool(entry[1])


def needs_approval(tool_name, arguments=None):
    """True als de tool voor het eerst bevestigd moet worden."""

    return get_tool_risk(tool_name, arguments) in APPROVAL_REQUIRED_RISKS


# =========================================================
# BESCHRIJVING & CENTRALE POORT
# =========================================================

def describe_tool_action(tool_name, arguments=None):
    """Leesbare actiebeschrijving voor de goedkeuringsvraag."""

    arguments = arguments or {}

    if tool_name == "ui_launch_app":
        path = arguments.get("path") or arguments.get("app_path") or ""
        return f"het programma vanaf '{path}' starten" if path else "een programma starten"

    if tool_name == "ui_type_text":
        tekst = str(arguments.get("text") or "")[:40]
        return f"tekst typen in een venster" + (f" ('{tekst}')" if tekst else "")

    if tool_name == "ui_set_value":
        naam = arguments.get("name") or arguments.get("element_name") or ""
        return f"de waarde van een element aanpassen" + (f" ({naam})" if naam else "")

    if tool_name == "ui_click_element":
        naam = arguments.get("name") or ""
        return f"op een knop klikken" + (f" ({naam})" if naam else "")

    if tool_name == "move_file":
        return f"{arguments.get('filename', 'een bestand')} verplaatsen"

    if tool_name == "copy_file":
        return f"{arguments.get('filename', 'een bestand')} kopiëren"

    if tool_name == "rename_file":
        return f"{arguments.get('filename', 'een bestand')} hernoemen"

    if tool_name == "control_home_assistant":
        domain = arguments.get("domain") or arguments.get("domein") or ""
        entity = arguments.get("entity") or arguments.get("apparaat") or ""
        return f"een {domain or 'smart home'}-apparaat bedienen" + (f" ({entity})" if entity else "")

    return tool_name.replace("_", " ") if tool_name else "deze actie"


def run_tool_guarded(tool_name, arguments=None, source="", question="", dispatch=None, approved=False):
    """Centrale poort voor élke toolaanroep (executor, agent, execute_tool).

    - low : direct uitvoeren via dispatch.
    - medium/high : vooraf een goedkeuringsvraag via core/confirmation.py
      stellen; de bevestigings-flow kan daarna run_tool_guarded(...,
      approved=True) aanroepen om de actie alsnog uit te voeren.
    - approved=True : overslaat de goedkeuringsvraag en voert direct uit.

    dispatch is een callable (tool_name, arguments, question) die de
    ÉCHTE actie uitvoert (bijv. _dispatch_tool uit core/ai.py). Bij
    audio/browser/ui_automation is dat al een ToolResult; de rest blijft
    een tekst. De beoordelingslaag (retry/executor) gebruikt
    to_tool_result() om beide betrouwbaar te interpreteren.
    """

    arguments = arguments or {}

    risk = get_tool_risk(tool_name, arguments)

    # Geheim-zonder-blootstelling: audit-log wordt al gesaneerd.
    def _voer_uit():
        if dispatch is None:
            return f"Ik kon {tool_name} niet uitvoeren omdat er geen uitvoerder is."

        resultaat = dispatch(tool_name, arguments, question)
        log_audit(
            gehoord=question,
            handler=source or "onbekend",
            tool=tool_name,
            argumenten=arguments,
            risico=risk,
            resultaat=resultaat,
            goedgekeurd=True,
        )
        return resultaat

    # Alleen uitvoeren als geldig goedgekeurd (vaak na "ja" via pending).
    if approved:
        return _voer_uit()

    # Laag risico: gewoon uitvoeren.
    if risk == "low":
        return _voer_uit()

    # Medium/high: eerst om bevestiging vragen.
    set_pending("tool_approval", {
        "tool_name": tool_name,
        "arguments": arguments,
        "question": question,
        "source": source or "onbekend",
        "risk": risk,
        "remaining_steps": [],
    })

    actie = describe_tool_action(tool_name, arguments)

    return f"Ik ga {actie} uitvoeren. Ga je akkoord? Zeg 'ja' of 'nee'."