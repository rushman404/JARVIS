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

import logging
import re

from core.confirmation import set_pending, clear_pending
from core.audit import log_audit

logger = logging.getLogger(__name__)

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
    "restart_program": ("medium", False),

    # ---- Home Assistant (risico hangt af van het domein) ----
    #  light -> low,  cover/switch -> medium  (in get_tool_risk)
    "control_home_assistant": ("medium", False),
    "get_home_assistant_entities": ("low", True),

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
    "set_volume": ("low", True),
    "volume_up": ("low", False),
    "volume_down": ("low", False),
    "media_mute": ("low", True),
    "system_info": ("low", True),
    "pc_status": ("low", True),
    "screenshot": ("low", True),
    "show_notification": ("low", True),
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
    "browser_get_url": ("low", True),
    "browser_get_title": ("low", True),
    "browser_get_content": ("low", True),
    "web_fetch": ("low", True),
    "web_search": ("low", True),
    "web_search_and_fetch": ("low", True),
    "ui_list_windows": ("low", True),
    "ui_find_window": ("low", True),
    "ui_activate_window": ("low", True),
    "ui_list_elements": ("low", True),
    "ui_find_element": ("low", True),
    "ui_get_value": ("low", True),
    "audio_list_sessions": ("low", True),
    "audio_get_session_volume": ("low", True),
    # Volume per app is net zo onschuldig als het systeemvolume (low): geen
    # ja/nee-vraag bij "zet Spotify op 30" (Fase 20, wens na de iPad-test).
    "audio_set_session_volume": ("low", True),
    "audio_set_session_mute": ("low", True),
    "audio_toggle_session_mute": ("low", True),
    # Fase 21: één app pauzeren als die speelt (film-modus, "pc stil").
    "media_pause_app": ("low", True),
    # Fase 21, M5: een Spotify-link openen (alleen spotify:<soort>:<id>).
    "spotify_open": ("low", True),
    "audio_list_outputs": ("low", True),
    "audio_get_default_output": ("low", True),
    "audio_set_default_output": ("medium", True),

    # ---- Game-PC Agent (remote, Fase 15) ----
    #  Alles low behalve de generieke fallback; die vraagt goedkeuring.
    #  game_pc_media is niet-idempotent: geen automatische herhaling.
    "game_pc_open_program": ("low", True),
    "game_pc_close_program": ("low", True),
    "game_pc_restart_program": ("low", True),
    "game_pc_program_status": ("low", True),
    "game_pc_status": ("low", True),
    "game_pc_telemetry": ("low", True),
    "game_pc_screenshot": ("low", True),
    "game_pc_media": ("low", False),
    "game_pc_set_volume": ("low", True),

    # ---- Game-PC Agent: bestanden + scherm (remote, Fase 15B) ----
    #  Het risico spiegelt de lokale tool: lezen is laag, wijzigen en
    #  UI-acties vragen goedkeuring (net als lokaal).
    "game_pc_list_files": ("low", True),
    "game_pc_open_folder": ("low", True),
    "game_pc_open_file": ("low", True),
    "game_pc_search_files": ("low", True),
    "game_pc_recent_files": ("low", True),
    "game_pc_create_folder": ("medium", True),
    "game_pc_create_file": ("medium", True),
    "game_pc_copy_file": ("medium", True),
    "game_pc_move_file": ("medium", True),
    "game_pc_rename_file": ("medium", True),
    "game_pc_ui_list_windows": ("low", True),
    "game_pc_ui_find_window": ("low", True),
    "game_pc_ui_activate_window": ("low", True),
    "game_pc_ui_list_elements": ("low", True),
    "game_pc_ui_find_element": ("low", True),
    "game_pc_ui_get_value": ("low", True),
    "game_pc_ui_click_element": ("medium", False),
    "game_pc_ui_type_text": ("medium", False),
    "game_pc_ui_set_value": ("medium", False),
    "game_pc_ui_launch_app": ("high", False),

    # ---- Game-PC Agent: verwijderen + power (remote, Fase 15B) ----
    #  De gevaarlijkste acties: altijd langs de goedkeuringspoort.
    "game_pc_recycle_file": ("medium", True),
    "game_pc_empty_recycle_bin": ("high", True),
    "game_pc_power": ("high", False),

    # ---- Game-PC Agent: vensters, systeeminfo, audio, browser (Taak F) ----
    #  Het risico spiegelt de lokale tool, zodat de goedkeuringspoort op
    #  de game-pc precies hetzelfde werkt als lokaal.
    "game_pc_find_program_location": ("low", True),
    "game_pc_minimize_window": ("low", True),
    "game_pc_maximize_window": ("low", True),
    "game_pc_restore_window": ("low", True),
    "game_pc_system_info": ("low", True),
    "game_pc_audio_list_sessions": ("low", True),
    "game_pc_audio_get_session_volume": ("low", True),
    "game_pc_audio_set_session_volume": ("low", True),
    "game_pc_audio_set_session_mute": ("low", True),
    "game_pc_audio_toggle_session_mute": ("low", True),
    "game_pc_audio_list_outputs": ("low", True),
    "game_pc_audio_get_default_output": ("low", True),
    "game_pc_audio_set_default_output": ("medium", True),
    "game_pc_open_website": ("low", True),
    "game_pc_browser_search": ("low", True),
    "game_pc_browser_back": ("low", True),
    "game_pc_browser_forward": ("low", True),
    "game_pc_browser_refresh": ("low", True),
    "game_pc_browser_new_tab": ("low", True),
    "game_pc_browser_close_tab": ("low", True),
    "game_pc_show_notification": ("low", True),
    "game_pc_media_pause_app": ("low", True),
    "game_pc_spotify_open": ("low", True),

    # ---- Verwijderen + power (lokaal, Fase 15B) ----
    #  Bewust NIET "delete_file" (die naam is verboden): bestanden gaan
    #  altijd naar de prullenbak, nooit definitief weg.
    "recycle_file": ("medium", True),
    "empty_recycle_bin": ("high", True),
    "power": ("high", False),
}

# Risico van een onbekende tool (fail-safe)
DEFAULT_RISK = "medium"

RISK_LEVELS = ("low", "medium", "high")

# Medium en hoog vereisen goedkeuring
APPROVAL_REQUIRED_RISKS = ("medium", "high")


def get_schema_tool_names():
    """De echte toolnamen uit het schema in core/ai.py.

    Dit is de bron van waarheid: de LLM mag alleen deze tools kennen.
    De schemalijst staat lokaal in een functie, dus we lezen de namen
    statisch uit de broncode (de dicts met "type": "function" en een
    "function"-dict met een "name"). Zo blijft de risicotabel
    controleerbaar tegen het echte schema, ook als dat verandert.
    """

    import ast
    import os

    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai.py")

    with open(schema_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=schema_path)

    names = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue

        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]

        if "type" not in keys or "function" not in keys:
            continue

        functie = node.values[keys.index("function")]

        if not isinstance(functie, ast.Dict):
            continue

        fkeys = [k.value for k in functie.keys if isinstance(k, ast.Constant)]

        if "name" not in fkeys:
            continue

        naam = functie.values[fkeys.index("name")]

        if isinstance(naam, ast.Constant) and isinstance(naam.value, str):
            names.add(naam.value)

    return names


def get_tool_risk(tool_name, arguments=None):
    """Risico van een tool uit de VASTE tabel.

    argumenten-notatie wordt alleen gebruikt voor tools waarbij het
    risico afhangt van het doel (Home Assistant-domein).
    """

    if not tool_name:
        return DEFAULT_RISK

    tool_name = tool_name.strip()

    # remote_command: risico wordt bepaald door de binnenste tool.
    # Een onbekende of ongeldige binnenste tool is fail-safe "high".
    if tool_name == "remote_command":
        inner = None
        inner_args = None
        if isinstance(arguments, dict):
            inner = arguments.get("tool")
            inner_args = arguments.get("arguments")
        if not isinstance(inner, str) or not inner.strip():
            return "high"
        inner = inner.strip()
        if inner not in TOOL_RISK:
            return "high"
        return get_tool_risk(inner, inner_args)

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

# Korte Nederlandse omschrijving van veelgebruikte (meestal lage-risico)
# tools, voor "wat JARVIS nu doet" onder de orb (Fase 20, M1).
_TAAK_OMSCHRIJVING = {
    "set_volume": lambda a: f"het volume op {a.get('percent', '?')}% zetten",
    "volume_up": lambda a: "het volume harder zetten",
    "volume_down": lambda a: "het volume zachter zetten",
    "media_play_pause": lambda a: "afspelen of pauzeren",
    "media_next": lambda a: "naar het volgende nummer",
    "media_previous": lambda a: "naar het vorige nummer",
    "media_stop": lambda a: "de media stoppen",
    "media_mute": lambda a: "het geluid dempen",
    "audio_set_session_volume": lambda a: f"{a.get('app_name', 'een app')} op {a.get('volume', '?')}% zetten",
    "audio_toggle_session_mute": lambda a: f"{a.get('app_name', 'een app')} dempen of ontdempen",
    "open_program": lambda a: f"{a.get('program', 'een programma')} openen",
    "close_program": lambda a: f"{a.get('program', 'een programma')} sluiten",
    "open_website": lambda a: "een website openen",
    "browser_search": lambda a: "op internet zoeken",
    "system_info": lambda a: "de systeeminformatie ophalen",
    "pc_status": lambda a: "de pc-status ophalen",
    "screenshot": lambda a: "een schermafbeelding maken",
    "remember": lambda a: "iets onthouden",
    "recall": lambda a: "in het geheugen zoeken",
    "show_notification": lambda a: "een melding tonen",
}


def beschrijf_taak(tool_name, arguments=None):
    """Wat JARVIS nu doet, in gewone woorden (voor het dashboard)."""

    arguments = arguments or {}
    naam = (tool_name or "").strip()
    op_game_pc = naam.startswith("game_pc_")
    basis = naam[len("game_pc_"):] if op_game_pc else naam
    omschrijving = _TAAK_OMSCHRIJVING.get(basis)
    if omschrijving is not None:
        try:
            tekst = omschrijving(arguments)
        except Exception:
            tekst = None
        if tekst:
            return tekst + (" op de game-pc" if op_game_pc else "")
    return describe_tool_action(naam, arguments)


def describe_tool_action(tool_name, arguments=None):
    """Leesbare actiebeschrijving voor de goedkeuringsvraag."""

    arguments = arguments or {}

    if tool_name == "remote_command":
        inner = None
        inner_args = None
        if isinstance(arguments, dict):
            inner = arguments.get("tool")
            inner_args = arguments.get("arguments")
        if not isinstance(inner, str) or not inner.strip() or inner.strip() not in TOOL_RISK:
            return "een onbekende actie uitvoeren"
        return describe_tool_action(inner.strip(), inner_args)

    if tool_name == "ui_launch_app":
        path = arguments.get("path") or arguments.get("app_path") or ""
        import os

        naam = os.path.basename(str(path).replace("\\\\", "/")) if path else ""
        if naam:
            return f"het programma '{naam}' starten"
        return "een programma starten"

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

    # Nieuwe tools (Fase 15B) voor helderere goedkeuringsvragen
    if tool_name == "recycle_file":
        naam = arguments.get("filename") or arguments.get("name") or "een item"
        return f"{naam} naar de prullenbak verplaatsen"
    if tool_name == "empty_recycle_bin":
        return "de prullenbak leegmaken"
    if tool_name == "power":
        actie = (arguments.get("action") or "").lower()
        labels = {
            "lock": "de pc vergrendelen",
            "sleep": "de pc in slaapstand zetten",
            "hibernate": "de pc in sluimerstand zetten",
            "shutdown": "de pc afsluiten",
            "restart": "de pc herstarten",
            "logoff": "je afmelden",
            "cancel": "een lopende afsluiting of herstart annuleren",
        }
        return labels.get(actie, "een stroomactie uitvoeren")

    if tool_name.startswith("game_pc_"):
        return _describe_game_pc_tool(tool_name, arguments)

    if tool_name == "control_home_assistant":
        domain = arguments.get("domain") or arguments.get("domein") or ""
        entity = arguments.get("entity") or arguments.get("apparaat") or ""
        return f"een {domain or 'smart home'}-apparaat bedienen" + (f" ({entity})" if entity else "")

    return tool_name.replace("_", " ") if tool_name else "deze actie"


def _describe_game_pc_tool(tool_name, arguments):
    """Nederlandse beschrijvingen voor game_pc_*-tools."""

    arguments = arguments or {}
    naam = tool_name[8:]  # zonder "game_pc_"

    mapping = {
        "create_folder": _beschrijf_map,
        "create_file": _beschrijf_bestand,
        "copy_file": lambda a: f"{a.get('filename', 'een bestand')} op de game-pc kopiëren",
        "move_file": lambda a: f"{a.get('filename', 'een bestand')} op de game-pc verplaatsen",
        "rename_file": lambda a: f"{a.get('old_name', 'een bestand')} op de game-pc hernoemen",
        "recycle_file": lambda a: f"{a.get('filename', 'een item')} op de game-pc naar de prullenbak verplaatsen",
        "empty_recycle_bin": lambda a: "de prullenbak op de game-pc leegmaken",
        "list_files": lambda a: f"de inhoud van {a.get('location', 'een map')} op de game-pc tonen",
        "open_folder": lambda a: f"map {a.get('location', '')} op de game-pc openen".strip(),
        "open_file": lambda a: f"bestand {a.get('filename', '')} op de game-pc openen".strip(),
        "search_files": lambda a: f"op de game-pc zoeken naar {a.get('query', 'iets')}".strip(),
        "recent_files": lambda a: "recente bestanden op de game-pc tonen",
        "screenshot": lambda a: "een screenshot op de game-pc maken",
        "pc_status": lambda a: "de status van de game-pc opvragen",
        "set_volume": lambda a: f"het volume op de game-pc op {a.get('percent', 50)}% zetten",
        "media": lambda a: f"media op de game-pc ({a.get('action', 'actie')}) bedienen",
        "open_program": lambda a: f"{a.get('program', 'een programma')} op de game-pc openen",
        "close_program": lambda a: f"{a.get('program', 'een programma')} op de game-pc sluiten",
        "restart_program": lambda a: f"{a.get('program', 'een programma')} op de game-pc herstarten",
        "program_status": lambda a: f"of {a.get('program', 'een programma')} op de game-pc draait",
        "power": lambda a: _beschrijf_power(a) + " op de game-pc",
        "ui_list_windows": lambda a: "vensters op de game-pc tonen",
        "ui_find_window": lambda a: f"venster '{a.get('title', a.get('title_substring', ''))}' op de game-pc vinden",
        "ui_activate_window": lambda a: "venster op de game-pc naar voren halen",
        "ui_list_elements": lambda a: "UI-elementen op de game-pc tonen",
        "ui_find_element": lambda a: f"UI-element '{a.get('name', '')}' op de game-pc vinden",
        "ui_get_value": lambda a: "waarde van een UI-element op de game-pc ophalen",
        "ui_click_element": lambda a: "op een UI-element op de game-pc klikken",
        "ui_type_text": lambda a: (
            "tekst typen op de game-pc ('" + str((a or {}).get("text", ""))[:40] + "')"
            if (a or {}).get("text")
            else "tekst typen op de game-pc"
        ),
        "ui_set_value": lambda a: "waarde op de game-pc instellen",
        "ui_launch_app": lambda a: (
            "het programma '"
            + __import__("os").path.basename(
                str((a or {}).get("path", "")).replace("\\\\", "/")
            )
            + "' op de game-pc starten"
            if (a or {}).get("path")
            else "een programma op de game-pc starten"
        ),
        "telemetry": lambda a: "telemetrie van de game-pc opvragen",
    }
    fn = mapping.get(naam)
    if fn:
        try:
            return fn(arguments)
        except Exception:
            pass
    return tool_name.replace("_", " ")


def _beschrijf_map(a):
    loc = a.get("location") or ""
    if loc:
        return f"een map maken op de game-pc in {loc}"
    return "een map maken op de game-pc"


def _beschrijf_bestand(a):
    loc = a.get("location") or ""
    if loc:
        return f"een bestand maken op de game-pc in {loc}"
    return "een bestand maken op de game-pc"


def _beschrijf_power(a):
    actie = (a.get("action") or "").lower()
    labels = {
        "lock": "de pc vergrendelen",
        "sleep": "de pc in slaapstand zetten",
        "hibernate": "de pc in sluimerstand zetten",
        "shutdown": "de pc afsluiten",
        "restart": "de pc herstarten",
        "logoff": "je afmelden",
        "cancel": "een lopende afsluiting of herstart annuleren",
    }
    return labels.get(actie, "een stroomactie uitvoeren")


def run_tool_guarded(tool_name, arguments=None, source="", question="", dispatch=None, approved=False,
                     herkomst=None):
    """Centrale poort voor élke toolaanroep (executor, agent, execute_tool).

    - low : direct uitvoeren via dispatch.
    - medium/high : vooraf een goedkeuringsvraag via core/confirmation.py
      stellen; de bevestigings-flow kan daarna run_tool_guarded(...,
      approved=True) aanroepen om de actie alsnog uit te voeren.
    - approved=True : overslaat de goedkeuringsvraag en voert direct uit.
    - herkomst : wie de goedkeuring gaf ("stem" of "dashboard"); komt in
      de auditregel.

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

        # Het dashboard toont zo wat JARVIS nu doet (Fase 20, M1).
        import status

        try:
            status.zet_taak(beschrijf_taak(tool_name, arguments))
        except Exception:
            status.zet_taak(None)
        try:
            resultaat = dispatch(tool_name, arguments, question)
        finally:
            status.zet_taak(None)
        log_audit(
            gehoord=question,
            handler=source or "onbekend",
            tool=tool_name,
            argumenten=arguments,
            risico=risk,
            resultaat=resultaat,
            goedgekeurd=True,
            herkomst=herkomst,
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