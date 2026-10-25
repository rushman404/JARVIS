import os
import re
import time

import logging

import status
import taal
from core import melding
from core.agent import Agent, is_goal as is_agent_goal, is_multi_step_goal
from core.calculator import calculate
from core.information import get_information
from core.ai import ask_ai, update_context, current_context, format_results, remember_from_question, execute_tool
from core import pc_target
from core.spraak_normaliseer import normaliseer_spraak
from core.routines import _manager as routine_manager
from core.proactive_commands import try_barge_in_command, try_proactive_command
from core.externe_bronnen import try_externe_bron_command
from core.scenes import get_scene_manager
from core.executor import execute_action_plan, get_last_done_actions, resume_approved_plan
from core.home_assistant import (
    has_ha_reference,
    is_ha_device_action,
    extract_color_hs,
    control_home_assistant_tool,
    HA_DEVICE_WORDS,
)
from core.ha_registry import resolve_entity, resolve_entities
from core.tools import open_program_tool, close_program_tool
from actions.file_finder import open_confirmed, open_path
from config import USER_NAME
from actions.program_finder import find_program
from actions.media import (
    play_pause,
    next_track,
    previous_track,
    volume_up,
    volume_down,
    set_volume,
    toggle_mute,
)
from actions.audio import (
    list_sessions as audio_list_sessions,
    get_session_volume as audio_get_session_volume,
    set_session_volume as audio_set_session_volume,
    set_session_mute as audio_set_session_mute,
    toggle_session_mute as audio_toggle_session_mute,
    list_output_devices as audio_list_outputs,
    get_default_output as audio_get_default_output,
    set_default_output as audio_set_default_output,
)
from actions.pc import minimize_program, maximize_program, restore_window, get_program_status, restart_program, find_program_location
from actions.system import (
    cpu_info,
    ram_info,
    disk_info,
    gpu_names,
    battery_info,
    os_info,
    uptime,
    system_summary,
    screen_info,
)
from core.tools import pc_status_tool
from actions.screenshot import take_screenshot
from actions.power import (
    lock_pc,
    sleep_pc,
    shutdown_pc,
    restart_pc,
    logoff_pc,
    cancel_shutdown,
)
from actions.file_manager import (
    create_folder,
    create_file,
    list_folder,
    list_folder_by_path,
    copy_path,
    move_path,
    find_item,
    resolve_location,
    send_to_recycle,
    empty_recycle_bin,
    open_folder,
    search_files,
    rename_file,
    get_recent_files,
)
from actions.browser import (
    browser_search,
    browser_back,
    browser_forward,
    browser_refresh,
    browser_new_tab,
    browser_close_tab,
)
from actions.web import fetch_url, format_fetch_result, search_and_fetch, format_search_and_fetch
from actions.pc import open_website
from actions.ui_automation import list_windows as ui_list_windows, find_window as ui_find_window, activate_window as ui_activate_window, type_text as ui_type_text
from memory.memory import remember, forget, clear_memory, get_all_memory, get_category_memory, beautify, find_entry, update_memory, touch_usage, reset_touch_usage, has_conflict, resolve_conflict, resolve_existing_key, _values_equal
from memory import obsidian as obsidian_vault
from memory import vault_import as vault_sync
from memory import vault_export as vault_out


from core.confirmation import (
    set_pending,
    get_pending,
    clear_pending,
    claim_pending,
    JA_NEE_KINDS,
    evaluate_answer,
    get_reask_prompt,
    is_dangerous_kind,
)

agent = Agent()

# =========================================================
# HULPFUNCTIES / ROUTERS
# =========================================================

SKIP_PARSE_WORDS = {
    "sluit", "sluiten", "stop", "stoppen", "zet", "doe", "maak", "uit",
    "dicht", "afsluiten", "af", "beëindig", "beëindigen", "uitzetten",
    "open", "openen", "start", "starten", "lanceer", "ga",
    "graag", "even", "aub", "alsjeblieft", "svp", "nu",
    "het", "de", "een", "en", "of", "dan", "me", "mij", "je", "jou",
    "jij", "jouw", "mijn", "u", "uw", "kan", "kun", "kunnen", "zou",
    "eens", "maar", "weer", "alle", "allemaal", "alles", "beide",
    "allebei", "apps", "app", "applicatie", "toepassing", "programma",
    "hem", "die", "dat", "deze", "dit", "muziek",
    "opnieuw", "nogmaals", "nog", "opent", "gestart",
}

CLOSE_PATTERNS = [
    r"\bsluit",
    r"sluiten",
    r"\bstop",
    r"\buit\b",
    r"\bdicht\b",
    r"afsluit",
    r"beëindig",
    r"beindig",
    r"uitzet",
]

CLOSE_EXCLUDE_PATTERNS = [
    r"\buit\s+komt\b",     # "wanneer komt X uit"
    r"\buit\s+gaat\b",     # "hoe laat gaat X uit"
    r"\buit\s+werkt\b",    # "hoe werkt X uit"
    r"\buit\s+voeren\b",   # "hoe voer X uit"
    r"\buit\s*$",          # "wanneer komt de iPhone uit" (einde zin)
    r"\buitkomt\b",
    r"uitkomen",           # "wanneer komt de iPhone uit"
    r"uitgang",            # "zoek uitgang"
    r"uitleggen",          # "leg X uit"
    r"uitdrukking",        # "betekenis van uitdrukking"
]

OPEN_PATTERNS = [
    r"\bopen",
    r"openen",
    r"\bstart",
    r"lanceer",
]

OTHER_ACTION_PATTERNS = [
    r"\bopen",
    r"openen",
    r"\bstart",
    r"lanceer",
    r"ga naar",
    r"\bbezoek",
    r"\btoon",
    r"\bzoek",
    r"onthoud",
    r"bewaar",
    r"herinner",
]


def has_intent(command, patterns):
    return any(re.search(pattern, command) for pattern in patterns)


def is_multi_command(command):
    return " en " in command or "," in command


def extract_program_names(command):

    cleaned = command.replace(",", " ")

    tokens = [token.strip(".,!?") for token in cleaned.split() if token.strip(".,!?")]

    return [token.lower() for token in tokens if token.lower() not in SKIP_PARSE_WORDS]


def extract_program_name(command):

    if is_multi_command(command):
        return None

    names = extract_program_names(command)

    if len(names) == 1:
        return names[0]

    if len(names) == 2:
        return " ".join(names)

    return None


def close_programs_in_command(command):

    names = extract_program_names(command)

    results = []

    if not names:
        return results

    for name in names:
        try:
            results.append(close_program_tool(name))
        except Exception as error:
            print(f"Fout bij sluiten {name}: {error}")
            results.append(f"Ik kon {name} niet sluiten.")

    return results


SMART_HOME_WORDS = HA_DEVICE_WORDS

logger = logging.getLogger(__name__)


def has_ha_word(question):
    # Word-boundary matching in plaats van substring: voorkomt dat
    # "spot" in "spotify" of "fan" in "fantastisch" als HA-match telt.
    return any(re.search(rf"\b{re.escape(word)}\b", question) for word in HA_DEVICE_WORDS)


def try_home_assistant(command):

    """
    Detecteert of een opdracht over een Home Assistant smart-home
    apparaat gaat (lamp, licht, stekker, sensor, thermostaat, enz.).

    Geeft een opdracht NIET anderszins afhandelbaar door de
    deterministische bestaande routes (media, PC-programma's, ...),
    dan stuurt hij hem door naar de beste bestaande AI-tool-call route
    (ask_ai). De AI kiest dan de juiste HA-tool (control_home_assistant)
    via de bestaande Planner -> Executor-keten.

    Retourneert een antwoord-string, of None als de opdracht niet over
    een smart-home apparaat gaat.
    """

    question = command.lower().strip()

    # =====================================================
    # VOORKEURS- / GEHEUGENZINNEN zijn géén HA-bediening.
    #
    # "ik hou meestal van warm wit licht" bevat 'licht'/'wit',
    # maar is een voorkeur die bij het geheugen hoort
    # (auto_remember), niet bij de smart-home-route. Zonder
    # deze guard zou de zin naar de AI-route gaan i.p.v. te
    # worden onthouden. (Fase 5)
    # =====================================================

    if re.search(
        r"\b(ik hou|ik houd|ik vind|ik heb graag|ik heb het liefst|"
        r"mijn favoriete|mijn lievelings|mijn voorkeur|voorkeur)\b",
        question,
    ):
        return None

    # =====================================================
    # CONTEXTUELE VERWIJZING naar een eerder HA-apparaat.
    #
    # Na "zet mijn bedlamp aan" verwijst "maak hem groen",
    # "zet hem op 30%", "doe hem uit", "die lamp", enz. naar
    # datzelfde apparaat. Zulke opdrachten bevatten vaak géén
    # device-naam ("lamp"), maar wél een verwijzing (hem/het/
    # deze/die) mét een HA-actie (kleur/helderheid/aan-uit).
    # Dit wordt deterministisch afgehandeld met de entity uit
    # de context (geen AI-gedoe en geen hardcoded entity_id).
    # =====================================================
    if not any(word in question for word in SMART_HOME_WORDS):

        if has_ha_reference(question) and is_ha_device_action(question):
            return try_ha_reference(command)

        return None

    # =====================================================
    # APPNAMEN zijn géén smart-home-apparaten, ook al bevatten
    # sommigen een apparaatwoord als SUBSTRING ("Spotify" bevat
    # "spot", "Word" bevat "word"). Telt alleen een apparaatwoord
    # dat als ZELFSTANDIG woord in de zin staat, dan is het HA.
    # =====================================================

    _app_tokens = (
        "spotify", "netflix", "steam", "discord", "chrome", "whatsapp",
        "youtube", "twitch", "gmail", "dropbox", "onedrive", "word",
        "excel", "powerpoint", "notepad", "teamviewer", "microsoft edge",
    )

    if any(token in question for token in _app_tokens):

        has_full_device_token = any(
            re.search(rf"\b{re.escape(w)}\b", question)
            for w in SMART_HOME_WORDS
        )

        if not has_full_device_token:
            return None

    # "speel muziek" hoort bij de PC-mediaspeler, niet bij HA.
    # Behalve als er expliciet een HA-media-apparaat genoemd wordt
    # (tv, soundbar, speaker, chromecast, versterker, ...).
    if "muziek" in question or "film" in question:
        media_device_tokens = (
            "speaker", "speakers", "tv", "televisie", "soundbar",
            "versterker", "chromecast", "mediabox", "home cinema",
            "media player",
        )
        if not any(full_token in question for full_token in media_device_tokens):
            return None

    # Een opdracht die duidelijk om een PC-actie vraagt (bijv. "open
    # lamp.exe", "toon mijn map lamp") moet niet naar HA worden gestuurd
    # en blijft bij de bestaande PC-routes terechtkomen. Let op: woorden
    # als "spot" matchten vroeger "Spotify" als substring; daarom wordt
    # voor open/start/... vereist dat het apparaatwoord een ECHT
    # zelfstandig woord is ("open de gordijnen" = HA, "open Spotify" = PC).
    if has_intent(question, OTHER_ACTION_PATTERNS):
        program_context = any(x in question for x in (
            ".exe", ".lnk", ".bat", "programma", "app",
            "applicatie", "bestand", "map", "toon", "zoek",
        ))
        if program_context:
            return None

        full_token_device = any(
            re.search(rf"\b{re.escape(word)}\b", question)
            for word in SMART_HOME_WORDS
        )

        if not full_token_device:
            return None

    # Zonder expliciete aan/uit/status-actie is het een HA-vraag naar
    # beschikbare apparaten of status -> probeer eerst deterministisch,
    # dan naar de AI-route.

    # Deterministische route (Option A): apparaatnaam + expliciete actie
    direct_result = try_ha_direct(command)
    if direct_result is not None:
        return direct_result

    return ask_ai(command)


# Kleurtemperatuur in kelvin voor "warmer" (lagere kelvin = warmer licht)
# en "koeler" (hogere kelvin = koeler licht).
_WARMER_COLOR_TEMP = 3000
_KOELER_COLOR_TEMP = 5000

# Stopwoorden die uit een HA-zin moeten worden verwijderd om de
# apparaatnaam te vinden (lidwoorden, voegwoorden, werkwoorden).
_HA_STOPWORDS = {
    "zet", "maak", "doe", "geef", "stel", "schakel", "draai",
    "mijn", "je", "jouw", "de", "het", "een", "van", "in",
    "op", "aan", "uit", "naar", "voor", "en", "of", "dan",
    "met", "graag", "even", "alsjeblieft", "aub", "svp",
    "als", "bij", "tot", "om", "nog", "weer", "nu", "dan",
    "die", "dit", "dat", "hem", "haar", "ze",
    "hem", "op", "half", "procent",
    "activeer", "activeer", "activeren", "start", "scène", "scene",
    "modus", "kleur", "kleuren",
    # Media-woorden die geen apparaatnaam zijn
    "nummer", "track", "liedje", "song", "muziek",
    "volgende", "volgend", "vorige",
    "pauzeer", "pauze", "pauseren", "stoppen", "stop",
    "harder", "luider", "louder", "zachter", "stiller",
    "omhoog", "omlaag", "verder", "doorgaan", "afspelen",
    "speel", "skip", "overslaan",
}


def _extract_device_name(question):
    """
    Extraheert een mogelijke apparaatnaam uit een HA-vraag door
    stopwoorden en actie-woorden te verwijderen.

    Geeft de apparaatnaam terug als string, of None als er
    niets bruikbaars overblijft.
    """

    question = question.lower().strip()

    # Verwijder patronen die een actie beschrijven (aan/uit/%/kleur)
    # zodat alleen de apparaatnaam overblijft.
    cleaned = re.sub(r"\b\d{1,3}\s*(?:%|procent)\b", "", question)
    cleaned = re.sub(r"\d{1,3}\s*%", "", cleaned)
    cleaned = re.sub(r"\b(?:aan|uit)\b", "", cleaned)
    cleaned = re.sub(r"\b(?:groen|rood|blauw|geel|oranje|paars|wit|warm|koel)\b", "", cleaned)
    cleaned = re.sub(
        r"\b(?:harder|luider|louder|zachter|stiller|omhoog|omlaag|"
        r"pauze|pauzeer|pauzeren|afspelen|stoppen|verder|doorgaan|"
        r"volgende|volgend|skip|overslaan|vorige)\b",
        "", cleaned,
    )

    # Verwijder woorden uit de HA woordenlijst die ook stopwoorden zijn
    words = cleaned.split()
    name_words = [
        w.strip(".,!?")
        for w in words
        if w.strip(".,!?") and w.strip(".,!?") not in _HA_STOPWORDS
    ]

    if not name_words:
        return None

    name = " ".join(name_words).strip()

    # Minimaal 1 teken, maximaal 4 woorden
    if len(name) < 2 or len(name_words) > 4:
        return None

    return name


def _resolve_with_action(device_name, is_media_action, is_power_action):
    """
    Resolved een apparaatnaam actie-bewust naar één entity.

    Bij meerdere gelijkwaardige matches (bv. "tv" matcht zowel
    switch.tv_switch als media_player.tv) kiezen we het domein dat
    bij de actie past:
      - media-actie (volume/pauze/next): media_player
      - power-actie (aan/uit): switch (echte power i.p.v. standby)

    Geeft (entity_info, status, message) zoals resolve_entity.
    """
    candidates = resolve_entities(device_name)

    if not candidates:
        return None, "none", (
            f"Geen Home Assistant apparaat gevonden voor '{device_name}'."
        )

    # Media-actie: media_player heeft voorrang (volume, pauze, next).
    if is_media_action:
        for c in candidates:
            if c.get("domain") == "media_player":
                return c, ("exact" if c.get("match") == "exact" else "resolved"), ""

    # Power-actie (aan/uit) met zowel een switch als media_player als
    # kandidaat: de switch regelt de échte power (webOS 'uit' = standby).
    if is_power_action:
        has_mp = any(c.get("domain") == "media_player" for c in candidates)
        if has_mp:
            for c in candidates:
                if c.get("domain") == "switch":
                    return c, ("exact" if c.get("match") == "exact" else "resolved"), ""

    # Fallback: standaard resolutie (hoogste score wint).
    return resolve_entity(device_name)


def try_ha_direct(command):
    """
    Deterministische HA-route voor directe commando's met een
    expliciete apparaatnaam: "zet bedlamp aan", "doe keukenlamp uit",
    "maak bedlamp op 50%", "maak bedlamp rood".

    Parst een apparaatnaam uit de zin, resolved die via de HA-registry
    (actie-bewust: bij aan/uit prefereren we een switch boven een
    media_player, want een webOS 'uit' betekent alleen standby), en voert
    de actie uit met control_home_assistant_tool.

    Geeft een antwoord-string, of None als de vraag niet deterministisch
    kan worden afgehandeld.
    """

    question = command.lower().strip()

    # Stap 1: actie-klasse bepalen vóór resolutie, zodat "tv uit/aan"
    # naar de switch (echte power) gestuurd wordt i.p.v. naar de
    # media_player (webOS standby).
    is_power_action = bool(
        re.search(r"\b(aan|uit)\b", question)
    )
    is_media_action = bool(
        re.search(r"\b(harder|luider|louder|omhoog|zachter|stil|omlaag|"
                  r"pauze|pauzeer|pauzeren|afspelen|verder|doorgaan|stoppen|"
                  r"volgende|volgend|skip|overslaan|vorige|terug)\b", question)
    )

    # Stap 2: apparaatnaam extraheren
    device_name = _extract_device_name(question)

    if not device_name:
        return None

    # Stap 3: probeer de entity te vinden. Bij meerdere matches kiezen
    # we het domein dat bij de actie past:
    #   - power (aan/uit/dim): switch > light > media_player
    #   - media (volume/pauze/next): media_player
    entity_info, entity_status, entity_msg = _resolve_with_action(
        device_name, is_media_action, is_power_action,
    )

    if entity_info is None or entity_status not in ("exact", "resolved"):
        return None

    entity_id = entity_info.get("entity_id", "")
    domain = entity_info.get("domain", entity_id.split(".")[0] if "." in entity_id else "")

    if not entity_id or not domain:
        return None

    # Stap 4: actie bepalen
    service = None
    service_data = {}

    # Scène: "activeer filmmodus" / "zet scene film aan" -> turn_on.
    # Scenes hebben alleen turn_on/toggle; "uit" activeren betekent
    # een scene die alles uitzet, via turn_on.
    if domain == "scene":
        if re.search(r"\b(uit|off)\b", question) and not re.search(r"\b(aan)\b", question):
            service = "toggle"
        else:
            service = "turn_on"

    # Media: "zet tv harder/zachter" -> volume op de media_player
    if service is None and domain == "media_player":
        if re.search(r"\b(harder|luider|louder|omhoog)\b", question):
            service = "volume_up"
        elif re.search(r"\b(zachter|stillen|stiller|omlaag)\b", question):
            service = "volume_down"
        elif re.search(r"\b(pauze|pauzeer|pauzeren|stoppen|stop)\b", question):
            service = "media_pause"
        elif re.search(r"\b(verder|doorgaan|afspelen|play|speel)\b", question):
            service = "media_play"
        elif re.search(r"\b(volgende|volgend|skip|overslaan)\b", question):
            service = "media_next_track"
        elif re.search(r"\b(vorige|terug)\b", question):
            service = "media_previous_track"
        elif re.search(r"\b(\d{1,3})\s*(?:%|procent)\b", question):
            match = re.search(r"\b(\d{1,3})\s*(?:%|procent)\b", question)
            pct = int(match.group(1))
            service = "volume_set"
            service_data["volume_level"] = round(min(max(pct, 0), 100) / 100, 2)

    # Kleur heeft voorrang (bv. "maak bedlamp rood")
    hs, _color_name = extract_color_hs(question)

    if hs is not None:
        service = "turn_on"
        service_data["hs_color"] = hs

    # Helderheid: "zet bedlamp op 50%" / "bedlamp op 50 procent"
    if service is None:
        match = re.search(r"(?:op|naar)\s+(\d{1,3})\s*(?:%|procent)", question)
        if match:
            pct = int(match.group(1))
            if 0 <= pct <= 100:
                service = "turn_on"
                service_data["brightness_pct"] = pct

    # Aan / uit
    if service is None:
        if re.search(r"\b(aan)\b", question):
            service = "turn_on"
        elif re.search(r"\b(uit)\b", question):
            service = "turn_off"

    # Kleurtemperatuur
    if service is None:
        if re.search(r"\bwarmer\b", question):
            service = "turn_on"
            service_data["color_temp"] = _WARMER_COLOR_TEMP
        elif re.search(r"\bkoeler|kouder\b", question):
            service = "turn_on"
            service_data["color_temp"] = _KOELER_COLOR_TEMP
        elif re.search(r"\bwarm\b", question) and "wit" not in question:
            service = "turn_on"
            service_data["color_temp"] = _WARMER_COLOR_TEMP
        elif re.search(r"\bkoel\b", question) and "wit" not in question:
            service = "turn_on"
            service_data["color_temp"] = _KOELER_COLOR_TEMP

    if service is None:
        return None

    # Stap 4: uitvoeren
    result = control_home_assistant_tool(domain, service, entity_id, service_data)

    update_context(
        last_command=command,
        last_result=str(result),
        last_action="apparaat bediend",
        last_ha_entity=entity_id,
        last_ha_domain=domain,
        last_ha_name=entity_info.get("name", entity_id),
    )

    return format_results([result])


def try_ha_reference(command):

    """
    Handelt een contextuele verwijzing naar het laatst gebruikte
    HA-apparaat deterministisch af. Bijv. na 'zet mijn bedlamp aan':
      - 'maak hem groen'    -> turn_on + hs_color
      - 'zet hem op 30%'    -> turn_on + brightness_pct
      - 'doe hem uit'       -> turn_off
      - 'zet hem aan'       -> turn_on

    Gebruikt de laatste entity uit de context. Geeft een
    antwoord-string, of None als het géén verwijzing betreft.
    """

    entity_id = current_context.get("last_ha_entity")
    domain = current_context.get("last_ha_domain")

    if not entity_id or not domain:
        return None

    if not has_ha_reference(command) or not is_ha_device_action(command):
        return None

    service = None
    service_data = {}

    # Kleur heeft voorrang (bv. "maak hem groen").
    hs, _color_name = extract_color_hs(command)

    if hs is not None:
        service = "turn_on"
        service_data["hs_color"] = hs

    # Helderheid: "zet hem op 30%" / "op 50 procent".
    if service is None:

        match = re.search(r"(?:op|naar)\s+(\d{1,3})\s*(?:%|procent)", command)

        if match:

            pct = int(match.group(1))

            if 0 <= pct <= 100:
                service = "turn_on"
                service_data["brightness_pct"] = pct

    # Aan / uit.
    if service is None:

        if re.search(r"\b(aan)\b", command):
            service = "turn_on"
        elif re.search(r"\b(uit)\b", command):
            service = "turn_off"

    # Kleurtemperatuur: "maak hem warmer" / "maak die koeler" /
    # "maak hem warm" / "maak hem koel".
    if service is None:

        if re.search(r"\bwarmer\b", command):
            service = "turn_on"
            service_data["color_temp"] = _WARMER_COLOR_TEMP
        elif re.search(r"\bkoeler|kouder\b", command):
            service = "turn_on"
            service_data["color_temp"] = _KOELER_COLOR_TEMP
        elif re.search(r"\bwarm\b", command) and "wit" not in command:
            service = "turn_on"
            service_data["color_temp"] = _WARMER_COLOR_TEMP
        elif re.search(r"\bkoel\b", command) and "wit" not in command:
            service = "turn_on"
            service_data["color_temp"] = _KOELER_COLOR_TEMP

    if service is None:
        return None

    result = control_home_assistant_tool(domain, service, entity_id, service_data)

    update_context(
        last_command=command,
        last_result=str(result),
        last_action="apparaat bediend",
    )

    return format_results([result])


def try_close_program(command):

    if not has_intent(command, CLOSE_PATTERNS):
        return None

    # "uit" is ambigu: "sluit discord" vs "wanneer komt de iPhone uit"
    # Bij uitzonderingspatronen NIET als sluiting zien
    if has_intent(command, CLOSE_EXCLUDE_PATTERNS):
        return None

    # Bij remote doel: dezelfde parserregels, maar direct naar de
    # game-pc-tool (zonder LLM). Meerdere namen laten we aan het
    # agent-/LLM-pad over.
    if pc_target.is_remote(command):

        if is_multi_command(command):
            return None

        naam = extract_program_name(command)

        if not naam:
            return None

        return execute_tool("game_pc_close_program", {"program": naam}, command)

    # Meerdere programma's tegelijk sluiten
    # (bijv. "sluit Discord en Spotify")
    if is_multi_command(command) and not has_intent(command, OTHER_ACTION_PATTERNS):

        results = close_programs_in_command(command)

        if results:
            update_context(
                last_command=command,
                last_result="; ".join(results),
                last_action="programma's gesloten"
            )
            return format_results(results)

        return None

    if is_multi_command(command):
        return None

    name = extract_program_name(command)

    if name:
        result = close_program_tool(name)
        update_context(
            last_command=command,
            last_result=str(result),
            last_action="programma gesloten",
            last_program=name
        )
        return format_results([result])

    if current_context["last_program"]:
        result = close_program_tool(current_context["last_program"])
        update_context(
            last_command=command,
            last_result=str(result),
            last_action="programma gesloten",
            last_program=current_context["last_program"]
        )
        return format_results([result])

    return "Welk programma wil je sluiten?"


def try_open_program(command):

    if not has_intent(command, OPEN_PATTERNS):
        return None

    # Gemengde of sluit-opdrachten (bijv. "sluit X en open Y")
    # gaan naar de AI, niet deterministisch openen.
    if has_intent(command, CLOSE_PATTERNS):
        return None

    # Bij remote doel: dezelfde parserregels, maar direct naar de
    # game-pc-tool (zonder LLM). Meerdere namen laten we aan het
    # agent-/LLM-pad over.
    if pc_target.is_remote(command):

        # Meerdere programma's ("open spotify en discord"): elk programma
        # als eigen game-pc-opdracht. Zonder dit belandde de hele zin bij
        # de LLM-planner, en dat kostte tientallen seconden.
        if is_multi_command(command):

            # Alleen een pure openlijst ("open spotify en discord"); een
            # gemengde zin blijft bij de Agent.
            if not is_multi_open_program(command):
                return None

            namen = extract_program_names(command)

            if len(namen) < 2:
                return None

            # Eerst controleren of ELKE naam bestaat; anders nooit openen
            # en de rest van de keten laten afhandelen.
            if not all(_programma_bestaat(naam, command) for naam in namen):
                return None

            resultaten = [
                execute_tool("game_pc_open_program", {"program": naam}, command)
                for naam in namen
            ]

            return format_results(resultaten)

        naam = extract_program_name(command)

        if not naam:
            return None

        return execute_tool("game_pc_open_program", {"program": naam}, command)

    # Meerdere programma's tegelijk openen (bijv. "Open Discord en Spotify")
    if is_multi_command(command):

        names = extract_program_names(command)

        # Alleen deterministisch als ALLE genoemde namen exacte
        # programma's zijn; anders laat de AI het afhandelen. Mappen,
        # bestanden en huisapparaten zijn nooit programma's.
        if (names
                and not any(naam in GEEN_PROGRAMMA_WOORDEN for naam in names)
                and all(_programma_bestaat(naam, command) for naam in names)):

            results = []

            for name in names:
                results.append(open_program_tool(name))

            update_context(
                last_command=command,
                last_result="; ".join(results),
                last_action="programma's geopend",
                last_program=names[-1]
            )

            return format_results(results)

        return None

    name = extract_program_name(command)

    if not name:
        return None

    # Alleen deterministisch openen als het een écht geïnstalleerd
    # programma is (exacte match); anders laat de AI het afhandelen
    # (bijv. een bestand of website).
    if not find_program(name, exact_only=True):
        return None

    result = open_program_tool(name)

    update_context(
        last_command=command,
        last_result=str(result),
        last_action="programma geopend",
        last_program=name
    )

    return format_results([result])


# Vulwoorden die in een pure openlijst mogen staan ("open graag spotify en
# discord"). Alles wat hier niet in staat én geen programmanaam is, maakt
# de zin te complex voor de deterministische route.
MULTI_OPEN_VULWOORDEN = {
    "graag", "even", "aub", "alsjeblieft", "svp", "nu", "ook", "maar",
    "eens", "wil", "wilt", "zou", "kan", "kun", "kunnen", "je", "jij",
    "mijn", "de", "het", "een", "dat", "die", "dit", "voor", "mij",
    "en", "of", "beide", "allebei", "tegelijk", "samen",
    "app", "apps", "applicatie", "applicaties", "programma",
    "programma's", "programmas", "toepassing", "toepassingen",
}

MULTI_OPEN_WERKWOORDEN = {
    "open", "opent", "openen", "start", "starten", "lanceer", "lanceert",
}

# Woorden die bij mappen, bestanden of huisapparaten horen. Ze mogen nooit
# als programmanaam naar de game-pc: "open de map downloads en documenten"
# hoort bij de map-handler, niet bij de programma-router.
GEEN_PROGRAMMA_WOORDEN = frozenset([
    "map", "mappen", "bestand", "bestanden", "downloads", "documenten",
    "bureaublad", "deur", "deuren", "raam", "ramen", "wasmachine",
    "droger", "lamp", "lampen", "tv",
])


def is_multi_open_program(command):
    """True voor een pure openlijst: "open spotify en discord".

    Alleen als elk woord een openingswerkwoord, een vulwoord of een
    programmanaam is. Zodra er een andere actie in staat ("open discord en
    zet muziek aan") of een smart-home-apparaat ("open discord en de lamp"),
    blijft de Agent aan de beurt.
    """

    tekst = command.strip().lower().rstrip(".!?")

    if not tekst or "," in tekst or " en " not in tekst:
        return False

    if not has_intent(tekst, OPEN_PATTERNS):
        return False

    if has_intent(tekst, CLOSE_PATTERNS) or has_ha_word(tekst):
        return False

    for woord in tekst.split():
        woord = woord.strip(".,!?")
        if not woord:
            continue
        if woord in MULTI_OPEN_WERKWOORDEN or woord in MULTI_OPEN_VULWOORDEN:
            continue
        # Mappen, bestanden en huisapparaten zijn geen programma's.
        if woord in GEEN_PROGRAMMA_WOORDEN:
            return False
        # Actiewoorden als "zet", "doe", "muziek" en "aan" horen niet in
        # een pure openlijst.
        if woord in SKIP_PARSE_WORDS:
            return False
        if any(teken.isdigit() for teken in woord):
            return False

    return len(extract_program_names(tekst)) >= 2


def _programma_bestaat(naam, command):
    """True als dit programma bestaat (lokaal of op de game-pc).

    Dezelfde bestaanscontrole als de enkelvoudige route: lokaal via
    ``find_program`` (exacte match), op de game-pc via
    ``game_pc_find_program_location``. Zo worden onzinnamen als "de deur"
    of "documenten" nooit geopend.
    """

    if not naam:
        return False

    if pc_target.is_remote(command):
        try:
            resultaat = execute_tool(
                "game_pc_find_program_location", {"program": naam}, command
            )
        except Exception:
            return False

        tekst = str(resultaat or "").lower()
        if not tekst:
            return False
        return "niet gevonden" not in tekst and "not found" not in tekst

    return bool(find_program(naam, exact_only=True))


def try_multi_open_program(command):
    """Opent meerdere programma's zonder LLM.

    "open spotify en discord" kostte via de Agent-planner tientallen
    seconden op een langzame laptop; dit is een paar honderd milliseconden.
    Geeft None als de zin niet eenduidig is of als een naam niet bestaat.
    """

    if not is_multi_open_program(command):
        return None

    return try_open_program(command)


def try_program_status(command):

    question = command.lower().strip()

    status_trigger = (
        any(word in question for word in ["draait", "loopt"])
        or re.search(r"(?:is|staat)\s+.+?\s+(?:geopend|open)\b", question)
    )

    if status_trigger:
        if has_ha_word(question):
            return None

        # "draait spotify?", "is discord geopend?", "loopt de game?"
        name = None

        match = re.match(r"^(?:draait|loopt)\s*(.+?)\??$", question)
        if match:
            name = clean_file_name(match.group(1))

        if not name:
            match = re.search(r"^(?:is|staat)\s+(.+?)\s+(?:geopend|open)\??$", question)
            if match:
                name = clean_file_name(match.group(1))

        if not name:
            name = extract_program_name(question)

        if not name or len(name.split()) > 3:
            return None

        # Bij remote doel: de agent controleert daar of het programma draait.
        if pc_target.is_remote(command):
            return execute_tool("game_pc_program_status", {"program": name}, command)

        if not find_program(name, exact_only=True):
            return None

        result = get_program_status(name)

        update_context(
            last_command=command,
            last_result=str(result),
            last_action="programma-status gecontroleerd",
            last_program=name
        )

        return result

    if any(word in question for word in [
        "welke programma's draaien", "welke programma draait", "welke programma s draaien",
        "welke apps draaien", "welke applicaties draaien", "wat draait er",
    ]):
        # Lopende processen opvragen is lokale informatie.
        if pc_target.is_remote(command):
            return None

        import psutil

        running = sorted({
            p.name().replace(".exe", "").lower()
            for p in psutil.process_iter(["name"])
            if p.info["name"]
        })

        if not running:
            return "Er draaien momenteel geen programma's."

        known = [n for n in running if find_program(n)]

        shown = known or running[:15]

        update_context(last_command=command, last_action="lopende programma's getoond")

        return "Momenteel draaien onder andere: " + ", ".join(shown[:15]) + "."

    return None


def try_restart_program(command):

    question = command.lower().strip()

    match = re.search(
        r"(?:herstart|restart)\s+(.+)",
        question
    )

    if not match:
        match = re.search(r"(?:start|open)\s+(.+?)\s+opnieuw\b", question)

    if not match:
        return None

    target = match.group(1).strip().strip(".,!?")

    if target in (
        "de pc", "pc", "de computer", "computer", "de laptop", "laptop",
        "het systeem", "systeem", "windows",
        # De game-pc zelf is geen programma: die gaat via de power-route.
        "de game-pc", "game-pc", "game pc", "gamepc", "gaming-pc", "gaming pc",
    ):
        return None

    if has_ha_word(question):
        return None

    name = clean_file_name(target)

    if not name:
        return None

    # Bij remote doel: direct naar de game-pc-tool (zonder LLM).
    if pc_target.is_remote(command):
        return execute_tool("game_pc_restart_program", {"program": name}, command)

    if not find_program(name, exact_only=True):
        return None

    result = restart_program(name)

    update_context(
        last_command=command,
        last_result=str(result),
        last_action="programma herstart",
        last_program=name
    )

    return result


def try_find_program(command):

    question = command.lower().strip()

    match = re.search(r"(?:vind(?: het)?(?: programma)?|waar staat|waar zit)\s+(.+)", question)

    if not match:
        return None

    target = match.group(1).strip().strip(".,!?")

    name = clean_file_name(target)

    if not name:
        return None

    # Bij remote doel: zoek het programma op de game-pc (zonder LLM).
    if pc_target.is_remote(command):
        return execute_tool(
            pc_target.remote_twin("find_program_location"),
            {"program": name},
            command,
        )

    location = find_program_location(name)

    update_context(
        last_command=command,
        last_result=str(location),
        last_action="programma-locatie gevonden",
        last_program=name
    )

    return location


def try_browser_search(command):

    question = command.lower().strip()

    def zoek(query, site):
        # Bij remote doel: zoek in de browser van de game-pc.
        if pc_target.is_remote(command):
            return execute_tool(
                pc_target.remote_twin("browser_search"),
                {"query": query, "site": site},
                command,
            )
        return browser_search(query, site)

    # "zoek op <site> naar <query>"
    match = re.search(r"zoek\s+op\s+([a-z]+)\s+naar\s+(.+)", question)

    if match:
        site = match.group(1).strip()
        query = match.group(2).strip().strip(".,!?")

        if query:
            return zoek(query, site)

    # "zoek <query> op <site>"
    match = re.search(r"zoek\s+(.+?)\s+op\s+([a-z]+)\s*$", question)

    if match:
        query = match.group(1).strip()
        site = match.group(2).strip()

        if query and query not in ("google", "youtube", "wikipedia", "bing"):
            return zoek(query, site)

    # "google naar <query>", "youtube <query>"
    match = re.search(r"(google|youtube|wikipedia|bing)\s+naar\s+(.+)", question)

    if match:
        site = match.group(1).strip()
        query = match.group(2).strip().strip(".,!?")

        if query and site in ("google", "youtube", "wikipedia", "bing"):
            return zoek(query, site)

    return None


def try_open_known_site(command):

    question = command.lower().strip()

    known_sites = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "wikipedia": "https://www.wikipedia.org",
        "bing": "https://www.bing.com",
        "github": "https://www.github.com",
        "reddit": "https://www.reddit.com",
        "duckduckgo": "https://duckduckgo.com",
    }

    match = re.search(r"(?:open|bezoek|ga naar)\s+(?:de\s+)?(\w+)\s*$", question)

    if match:
        site = match.group(1).strip().lower()

        if site in known_sites:
            # Bij remote doel: open de website op de game-pc.
            if pc_target.is_remote(command):
                return execute_tool(
                    pc_target.remote_twin("open_website"),
                    {"url": known_sites[site]},
                    command,
                )

            open_website(known_sites[site])

            update_context(
                last_command=command,
                last_result="website geopend",
                last_action="website geopend",
                last_website=site
            )

            return f"Ik open {site}."

    return None


def try_browser_command(command):

    question = command.lower().strip()

    def remote_of_lokaal(twin, lokaal):
        # Bij remote doel: bedien de browser van de game-pc.
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin(twin), {}, command)
        return lokaal()

    if has_ha_word(question):
        return None

    if any(phrase in question for phrase in [
        "ververs", "verversen", "refresh", "vernieuw", "herlaad", "pagina opnieuw laden",
    ]):
        return remote_of_lokaal("browser_refresh", browser_refresh)

    if (
        any(phrase in question for phrase in [
            "vorige pagina", "ga terug", "pagina terug",
        ])
        or re.fullmatch(r"(ga\s+)?terug", question)
    ) and "vooruit" not in question:
        return remote_of_lokaal("browser_back", browser_back)

    if any(phrase in question for phrase in [
        "vooruit", "volgende pagina",
    ]):
        return remote_of_lokaal("browser_forward", browser_forward)

    if any(phrase in question for phrase in [
        "nieuw tabblad", "extra tabblad", "open een tabblad",
    ]):
        return remote_of_lokaal("browser_new_tab", browser_new_tab)

    if any(phrase in question for phrase in [
        "sluit tabblad", "tabblad sluiten", "tabblad dicht", "dicht tabblad",
    ]):
        return remote_of_lokaal("browser_close_tab", browser_close_tab)

    return None


def try_browser_read(command):

    """Lees de huidige browserinhoud via UIA (Fase 12)."""

    question = command.lower().strip()

    # "wat staat er op mijn browser?"
    if re.search(r"wat\s+(?:staat|staan)\s+er\s+(?:op|in)\s+(?:mijn\s+)?(?:browser|pagina|scherm)", question):
        # Het uitlezen van de browser kan alleen lokaal: op de game-pc
        # bestaat hiervoor geen remote-actie.
        if pc_target.is_remote(command):
            return pc_target.blokkade_bericht("get_browser_content")
        from actions.browser import get_browser_content
        return get_browser_content()

    # "welke pagina heb ik open?" / "welke site is dit?"
    if re.search(r"(?:welke|welk)\s+(?:pagina|site|url|website|link)\s+(?:heb\s+ik|is\s+dit|heb\s+jij)", question):
        if pc_target.is_remote(command):
            return pc_target.blokkade_bericht("get_browser_content")
        from actions.browser import get_browser_url
        return get_browser_url()

    # "wat is de titel van mijn browser?"
    if re.search(r"titel\s+(?:van|mijn|van\s+mijn)\s+(?:browser|pagina)", question) \
       or re.search(r"(?:wat|hoe)\s+(?:heet|is)\s+(?:deze|dit|mijn)\s+(?:pagina|site|browser)", question):
        if pc_target.is_remote(command):
            return pc_target.blokkade_bericht("get_browser_content")
        from actions.browser import get_browser_title
        return get_browser_title()

    return None


def try_web_fetch(command):

    """Haal de inhoud van een webpagina op als de gebruiker vraagt om te lezen."""

    question = command.lower().strip()

    # Alleen een URL als antwoord ("https://www.nu.nl") -> direct ophalen
    # (bijv. als reactie op de vervolgvraag "welke pagina bedoel je?")
    bare_url = re.fullmatch(r"(?:oké |oke |ok |ja |die |dit |gebruik )?(https?://\S+)\.?", question)
    if bare_url:
        return format_fetch_result(fetch_url(bare_url.group(1)))

    # URLs direct herkennen (https://...) met lees-intentie
    url_match = re.search(r"(https?://\S+)", question)
    if url_match and any(phrase in question for phrase in [
        "lees", "vertel", "haal op", "bekijk de inhoud",
        "wat staat er", "wat staat erop",
    ]):
        return format_fetch_result(fetch_url(url_match.group(1)))

    # "lees <url>" / "open de pagina <url>" / "haal de pagina op <url>"
    if any(phrase in question for phrase in [
        "lees deze pagina", "lees de pagina", "lees de site",
        "haal de pagina op", "haal de site op",
        "bekijk de pagina", "bekijk de site",
        "wat staat er op", "wat staat erop",
    ]):
        # URL in de vraag zoeken
        if url_match:
            return format_fetch_result(fetch_url(url_match.group(1)))
        # Anders: als er een bekende site-naam is, probeer een URL te bouwen
        known_sites = {
            "wikipedia": "https://nl.wikipedia.org/wiki/Hoofdpagina",
            "youtube": "https://www.youtube.com",
            "github": "https://github.com",
            "google": "https://www.google.com",
        }
        for site, url in known_sites.items():
            if site in question:
                return format_fetch_result(fetch_url(url))

        return "Geef me een URL om te lezen, bijvoorbeeld https://www.example.com."

    return None


def try_web_search(command):

    """Zoek op het internet als de gebruiker iets wil opzoeken.

    Herkent: "zoek X op", "google naar X", "wat is het weer", enz.
    Gebruikt de instructie-route via deterministic extraction zodat de
    zoekterm letterlijk uit de opdracht komt (niet verzonnen door AI).
    """

    question = command.lower().strip()

    # LET OP: als de gebruiker op een SPECIFIEKE site wil zoeken
    # ("zoek op youtube naar hond", "zoek hond op youtube", "youtube naar hond"),
    # dan moet de BROWSER dat afhandelen, niet internet-zoeken.
    # "google naar X" wil juist WEL de web-agent (JARVIS zoekt en antwoordt).
    if re.search(r"zoek\s+op\s+(google|youtube|wikipedia|bing|duckduckgo)\s+naar", question):
        return None
    if re.search(r"zoek\s+(.+?)\s+op\s+(google|youtube|wikipedia|bing|duckduckgo)\s*$", question):
        return None
    if re.search(r"^(youtube|wikipedia|bing|duckduckgo)\s+naar\s+", question):
        return None
    if re.search(r"^duckduckgo\s+", question):
        return None

    intent = web_search_intent(question)

    if intent is None:
        return None

    query, max_pages = intent

    # DIRECTE WEER-VRAAG: ga naar Open-Meteo (geen DDG nodig, altijd beschikbaar)
    if "weer" in question and max_pages == 1:
        place = query.replace("weer", "").replace("vandaag", "").strip()
        # Zonder stad: standaard naar Nederland
        if not place:
            place = ""
        from actions.web import get_weather, format_weather
        print(f"🌤️ Weer-vraag: haal weer op.")
        weather = get_weather(place or "Amsterdam")
        return format_weather(weather)

    print(f"🔎 Web Agent: zoek '{query}' (lees top {max_pages} bron{'' if max_pages == 1 else 'en'}).")

    result = search_and_fetch(query, max_pages=max_pages)
    formatted = format_search_and_fetch(result)

    # VERGELIJKING: extra AI-samenvatting met oordeel
    if max_pages >= 2:
        verdict = _comparison_verdict(query, result)
        if verdict:
            formatted += f"\n\n---\n\n{verdict}"

    return formatted


def _comparison_verdict(query, result):
    """Gebruik AI om uit de twee bronnen een duidelijk oordeel te geven."""

    pages = result.get("pages", [])
    if len(pages) < 2:
        return ""

    # Bouw context van de twee bronnen
    b1 = f"[Bron 1: {pages[0].get('search_title','')}]\n{pages[0].get('text','')[:800]}"
    b2 = f"[Bron 2: {pages[1].get('search_title','')}]\n{pages[1].get('text','')[:800]}"
    context = f"\n{b1}\n\n{b2}"

    prompt = f"""Je analyseert een vergelijking tussen twee dingen. Geef een DUOELIJK eindoordeel.

Beantwoord in dit EXACTE formaat, in het Nederlands:

🏆 WINNAAR: <welke van de twee is beter, of "gelijk spel">
🤔 WAAROM: <in 2-3 zinnen de belangrijkste redenen, met concrete getallen>
💡 TIPS:
  - <belangrijkste verschil 1>
  - <belangrijkste verschil 2>
  - <belangrijkste verschil 3>

Wees eerlijk: als het van de situatie afhangt (budget, gebruik), zeg dat dan.
Gebruik geen Markdown-headers (#) en geen codeblokken. Maximaal 12 regels.

VERGELIJKING: {query}"""

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": context},
    ]

    try:
        from core import llm
        response = llm.chat(messages=messages)
        return response.get("message", {}).get("content", "").strip()
    except Exception:
        return ""


def try_ui_automation(command):

    """UI-automatisering (Fase 10): bepaal uit een opdracht of de gebruiker
    hulp nodig heeft bij het BEDIENEN van een app-venster.

    Deze router is bewust MINIMAAL: alleen duidelijke, veilige commando's
    worden hier afgehandeld ("welke vensters zijn open", "minimaliseer
    venster X naar voorgrond"). Complexe bediening gaat via de LLM-tools
    (ui_find_element / ui_click_element / ui_set_value).

    Geeft None terug als het geen UI-commando is.
    """

    question = command.lower().strip()

    # Smart-home-vragen ("is het licht aan", "staat de verwarming aan")
    # mogen NEVER door deze venster-router worden opgepikt -> HA-route.
    if any(hw in question for hw in (
        "home assistant", "smart home", "smart-home", "hass",
        "lamp", "licht", "verwarming", "thermostaat", "schakelaar",
        "stekker", "zonwering", "rolgordijn", "shutter", "sensor",
        "tv", "radio", "muziek",
    )):
        return None

    # =========================
    # VENSTERS OPSOMMEN
    # "welke vensters zijn open", "welke programma's draaien", "toon vensters"
    # =========================
    if re.search(r"(welke|welke)\s+vensters?(?:\s+zijn)?\s+open", question) or \
       re.search(r"(toon|laat)\s+(mij\s+)?(de\s+)?vensters?", question) or \
       re.search(r"welke\s+programma\w*\s+(draaien|lopen)", question) or \
       re.search(r"vensters?\s+(?:bevat|heeft|zijn\s+er|met|waarin)", question) or \
       re.search(r"(welke|alle)\s+vensters?\s+met\s+", question):
        if pc_target.is_remote(command):
            return None
        result = ui_list_windows()
        if not result.ok:
            return f"Het lukte niet om de vensters te lezen: {result.message}"
        windows = (result.data or {}).get("windows", [])
        if not windows:
            return "Er zijn geen zichtbare vensters."
        lines = [f"- {w['title']}" for w in windows]
        return "Open vensters:\n" + "\n".join(lines)

    # =========================
    # VENSTER(BEDRIJFS)STATUS VAN EEN APP
    # "is discord open", "draait spotify", "staat sonar aan"
    # =========================
    status_match = re.match(r"(?:is|draait|staat|wordt|lopen)\s+([a-zA-Z0-9_ .]+?)\s*(?:open|aan|geopend|\?)?$", question)
    if status_match:
        app_name = status_match.group(1).strip()
        if pc_target.is_remote(command):
            return None
        result = ui_find_window(title_substring=app_name)
        if result.ok:
            return f"Ja, {app_name} is open."
        return f"Nee, ik zie geen venster van {app_name}."

    # =========================
    # VENSTER NAAR VOORGROND
    # "breng discord naar voren", "activeer spotify", "open het venster van X"
    # =========================
    focus_match = re.match(r"(?:breng|activeer|open)\s+(?:het\s+venster\s+van\s+|de\s+)?([a-zA-Z0-9_ .]+?)\s+(?:naar\s+(?:de\s+|het\s+)?(?:voorgrond|voren|creen|boven))", question)
    if focus_match:
        app_name = focus_match.group(1).strip()
        if pc_target.is_remote(command):
            return None
        result = ui_find_window(title_substring=app_name)
        if not result.ok:
            return f"Ik zie geen venster van {app_name}."
        act = ui_activate_window((result.data or {}).get("handle"))
        if act.ok:
            return f"{app_name} is naar de voorgrond gebracht."
        return f"Het lukte niet om {app_name} naar de voorgrond te brengen."

    # =========================
    # TEKST TYPEN IN EEN VENSTER
    # "typ test in kladblok" -> direct ui_type_text, zonder LLM-plan.
    # Zonder deze route koos de LLM soms geen tool en gaf hij een lijstje
    # in plaats van te typen.
    # =========================
    typ_match = re.match(
        r"^(?:typ|type|schrijf|voer)\s+(?:de\s+tekst\s+|dit\s+)?[\"']?"
        r"(?P<tekst>.+?)[\"']?\s+(?:in|in\s+het|in\s+de|in\s+een)\s+"
        r"(?P<venster>[\w .\-]+?)\s*[.!?]?$",
        question,
    )
    if typ_match:
        if pc_target.is_remote(command):
            return None
        tekst = (typ_match.group("tekst") or "").strip().strip("\"'")
        venster = (typ_match.group("venster") or "").strip()
        venster = re.sub(r"^(?:het|de|een)\s+", "", venster).strip()
        if tekst and venster:
            gevonden = ui_find_window(title_substring=venster)
            if gevonden.ok:
                handle = (gevonden.data or {}).get("handle")
                ui_activate_window(handle)
                resultaat = ui_type_text(handle, tekst)
                if resultaat.ok:
                    return f'Ik heb "{tekst}" in {venster} getypt.'
                return f"Ik kon niet typen in {venster}: {resultaat.message}"
            # Geen venster gevonden: laat de LLM-tools het proberen (die
            # kunnen ook een programma starten of een ander venster kiezen).
            return None

    return None


def web_search_intent(question, defaults=None):

    """Bepaal uit een opdracht of er gezocht moet worden, en geef
    (query, max_pages) terug. max_pages=2 bij 'vergelijk'.

    Gebeurtenissen, niet blokkerend; AndersNone als het geen zoek-opdracht is.
    """

    patterns = [
        # "vergelijk ..." -> twee bronnen oplossen
        # "vergelijk de ps5 en xbox": houd BOTH binnen + ' vs '
        (r"vergelijk\s+(?:de\s+|het\s+)?(.+?)\s+(?:met|en|tegen|versus|vs)\s+(?:de\s+|het\s+)?(.+)", 2),
        (r"vergelijk\s+(.+)", 2),
        # "zoek X op"
        (r"zoek\s+(.+?)\s+op\b", 1),
        (r"zoek\s+op\s+(.+)", 1),
        # "google naar X"
        (r"google\s+naar\s+(.+)", 1),
        (r"googlen\s+op\s+(.+)", 1),
        # "zoek X op het internet"
        (r"zoek\s+(.+?)\s+op\s+(het\s+)?internet", 1),
        # "waar vind ik X" / "hoe laat is X open" etc.
        # "wat is het weer" / "wat is het weer in X"
        (r"wat\s+is\s+(?:het\s+)?weer\b\s*(?:vandaag\s*)?(?:in\s+(.+))?", 1),
        (r"weer\s+op\s+(.+?)\.?$", 1),
        # "hoe laat is X open" / "hoe laat gaat X open"
        (r"hoe\s+laat\s+(?:is|gaat|staat|wordt|huidt)\s+(.+?)\s+open\b(?: in\s+(.+))?", 1),
        # "hoe laat X open gaat/is" (omgekeerde volgorde) + eventuele plaats
        (r"hoe\s+laat\s+(.+?)\s+(?:open\s+gaat|open\s+is|open\s+weer|opent)\b(?: in\s+(.+))?", 1),
        # "hoe laat sluit X" / "hoe laat gaat X dicht"
        (r"hoe\s+laat\s+(?:sluit|gaat\s+dicht)\s+(.+?)(?:\s+in\s+(.+))?$", 1),
        (r"wanneer\s+(?:gaat|is)\s+(.+?)\s+open\b(?: in\s+(.+))?", 1),
        (r"openingstijden\s+van\s+(.+)", 1),
        (r"hoe\s+laat\s+(?:sluit|gaat)\s+(.+)\s+dicht\b", 1),
        # "wanneer kwam X uit" / "wanneer verscheen X"
        (r"wanneer\s+(?:kwam|verscheen|werd)\s+(.+?)\s+uit\b", 1),
        (r"wanneer\s+(?:kwam|verscheen)\s+(.+)", 1),
        # "wat staat er op het internet over X" -> zoek
        (r"zoek\s+(.+)\s+op\s+het\s+internet", 1),
    ]

    for pattern, pages in patterns:
        m = re.search(pattern, question)
        if m:
            # "wat is het weer" (zonder plaats) -> generiek weer-zoektype
            if pattern.startswith(r"wat\s+is\s+(?:het\s+)?weer"):
                place = m.group(1).strip().strip(".,!? ") if m.groups() and m.group(1) else ""
                return (f"weer {place}".strip() if place else "weer vandaag", pages)

            groups = [g for g in m.groups() if g]
            query = " ".join(groups).strip(".,!? ")

            if not query:
                continue

            # opruimen van leidende werkwoorden die in de query zijn beland
            query = _clean_search_query(query)

            if not query:
                continue

            # "hoe laat X open" -> betere zoekquery met "openingstijden"
            if "open" in pattern and "openingstijden" not in query:
                query = f"{query} openingstijden"

            return (query, pages)

    return None


def _clean_search_query(query):

    """Verwijder woorden die in de zoekterm terechtkomen maar er niet horen."""

    leading = re.match(r"^(op|voor|naar|met|en|een|de|het|via|door)\b", query)
    if leading:
        query = query[leading.end():].strip()

    return query


def web_lookup_tool_if_available():
    """Helper zodat andere modules eenvoudig kunnen testen of internet zoeken kan."""
    return True


def try_open_folder(command):

    question = command.lower().strip()

    match = re.search(r"open\s+(?:de\s+|mijn\s+)?map\s+(.+)", question)

    if match:
        location = find_location_word(match.group(1))

        if not location:
            location = clean_file_name(match.group(1))

        if not location:
            return None

        if pc_target.is_remote(command):
            return execute_tool("game_pc_open_folder", {"location": location}, command)
        return open_folder(location)

    # "open downloads", "open documenten" (directe locatie)
    if re.search(r"^(?:open|toon)\s+(bureaublad|desktop|downloads|documenten|afbeeldingen|muziek|video)s?$", question):
        location = find_location_word(question)
        if location:
            if pc_target.is_remote(command):
                return execute_tool("game_pc_open_folder", {"location": location}, command)
            return open_folder(location)

    return None


def try_recent_files(command):

    question = command.lower().strip()

    if any(word in question for word in [
        "recente bestanden", "recente documenten", "recente",
        "laatst geopende bestanden", "laatst geopende documenten",
        "recent geopende", "laatst gebruikte bestanden",
    ]):
        if pc_target.is_remote(command):
            return execute_tool("game_pc_recent_files", {}, command)
        return get_recent_files()

    return None


def show_number(number):
    return int(number) if number.is_integer() else number


def try_calculate_followup(command):

    match = re.fullmatch(
        r"(plus|min|keer|gedeeld door|\+|-|\*|/)\s*(\d+(?:\.\d+)?)",
        command.strip().lower()
    )

    if not match:
        return None

    operator = match.group(1)
    number = float(match.group(2))

    try:
        base = float(current_context["last_result"])
    except (TypeError, ValueError):
        return None

    if operator in ("plus", "+"):
        result = base + number
        operation = f"{show_number(base)} + {show_number(number)}"

    elif operator in ("min", "-"):
        result = base - number
        operation = f"{show_number(base)} - {show_number(number)}"

    elif operator in ("keer", "*"):
        result = base * number
        operation = f"{show_number(base)} × {show_number(number)}"

    else:
        if number == 0:
            return "Delen door nul is niet mogelijk."
        result = base / number
        operation = f"{show_number(base)} ÷ {show_number(number)}"

    if result.is_integer():
        result = int(result)

    update_context(
        last_command=command,
        last_result=str(result),
        last_action="berekening",
        last_calculation=operation
    )

    return f"Het antwoord is {result}."


def _looks_like_app_volume(question):

    """Bepaalt of een volume/percentage-opdracht APP-SPECIFIEK is
    ("zet Spotify op 100", "zet het volume van Sonar op 50") in plaats
    van een systeemvolume-actie ("zet het volume op 50").

    Het app-woord moet een ECHT programma zijn (via find_program).
    Alleen dan is het veilig om de Agent/UI (i.p.v. Windows-volume)
    in te schakelen. Geeft True terug bij een app-specifieke actie.
    """

    text = question.lower().strip()

    # Zonder getal/percentage is er niets te verifiëren
    if not re.search(r"\d{1,3}\s*(?:%|procent)?", text):
        return False

    # Smart-home-woorden uitsluiten ("zet de lamp op 100" is HA, géén app)
    if any(hw in text for hw in SMART_HOME_WORDS) and not any(
        mw in text for mw in (
            "muziek", "volume", "liedje", "nummer", "muziekje", "radio",
            "spotify", "nummers", "afspelen",
        )
    ):
        return False

    candidates = []

    # Patroon A: "zet Spotify op 100" / "zet het volume van Spotify op 50"
    m = re.search(r"(?:zet|doe|maak|regel)\s+(?:het\s+|de\s+)?(?:volume\s+)?(?:(?:van|in|binnen)\s+)?([a-zA-Z0-9_ .-]+?)\s+(?:op|naar)\s+\d", text)
    if m:
        candidates.append(m.group(1).strip())

    # Patroon B: "zet Spotify volume op 100" (app vóór 'volume')
    m = re.search(r"(?:zet|doe|maak|regel)\s+([a-zA-Z0-9_ .-]+?)\s+volume\s+(?:op|naar)\s+\d", text)
    if m:
        candidates.append(m.group(1).strip())

    # Patroon C: "volume harder in Spotify" / "volume van Spotify omhoog"
    m = re.search(r"volume\s+(?:van|in|binnen)\s+([a-zA-Z0-9_ .-]+?)\s+(?:op|naar|harder|lager|zachter|luider|omhoog|omlaag)", text)
    if m:
        candidates.append(m.group(1).strip())

    # Algemeen: eerste pakkende 'zet ... op' met percentage
    if not candidates:
        m = re.search(r"(?:zet|doe|maak|regel)\s+([a-zA-Z0-9_ .-]{2,})\s+(?:op|naar)\s+\d", text)
        if m:
            candidates.append(m.group(1).strip())

    for candidate in candidates:
        # Zuiver stoppenlaag-woorden eruit
        app = re.sub(r"\b(het|de|een|van|in|binnen)\b", "", candidate).strip()
        if not app or len(app) < 2:
            continue
        if app in ("volume", "geluid", "muziek", "pc", "computer", "systeem", "windows"):
            continue
        # EXACTE match op HA-woorden (niet substring! "spot" vs "spotify")
        app_words = set(app.lower().split())
        if app_words & set(SMART_HOME_WORDS):
            continue
        # Bij een game-pc-doel is er geen lokale opzoeking nodig:
        # de programmanaam gaat ongewijzigd naar de game-pc.
        if pc_target.get_pc_target() == pc_target.GAME_PC:
            return True
        try:
            if find_program(app):
                return True
        except Exception:
            pass

    return False


def try_audio_command(command):

    """Audio-router (Fase 11) — per-app volume/mute + output-apparaten.

    Onderscheid met try_media_command (Fase 5):
      - "zet het volume op 50"      → systeemvolume (media)
      - "zet Spotify op 50"         → alleen Spotify (audio, per-app)
      - "maak Discord zachter"      → alleen Discord (audio)
      - "zet output naar headset"   → default audio-apparaat (audio)

    Geeft None als de opdracht geen audio-actie is, zodat de volgende
    routers (media/agent/AI) de kans krijgen.
    """

    question = command.lower().strip()

    # Smart-home / HA-queries mogen NOOIT door de audio-router worden opgepikt
    # ("welke apparaten heb je in home assistant" -> HA, niet audio-apparaten).
    if any(hw in question for hw in (
        "home assistant", "smart home", "smart-home", "hass",
        "apparaten ken je", "apparaten heb je onthouden",
        "apparaten weet je", "apparaten weet jij",
        "apparaatnamen", "welke namen heb je voor apparaten",
        "welke apparaten heb je",
    )):
        return None

    # --- Hulp: app-naam extraheren uit "zet <app> op 80" / "maak <app> zachter"
    def _app_in(patterns):
        for pat in patterns:
            m = re.search(pat, question)
            if m:
                return m.group(1).strip()
        return None

    def _real_app(app):
        # Alleen behandelen als het een ECHT programma is (niet HA-woord,
        # niet algemene term). Zo voorkomen we dat "zet de lamp op 50"
        # per-app audio wordt.
        if not app or len(app) < 2:
            return False
        app2 = re.sub(r"\b(het|de|een|van|in|binnen|mijn|naar|op)\b", "", app).strip()
        if not app2:
            return False
        if app2 in ("volume", "geluid", "muziek", "pc", "computer", "systeem",
                    "windows", "tv", "lamp", "licht", "schakelaar"):
            return False
        # Bij een game-pc-doel is er geen lokale opzoeking nodig.
        if pc_target.get_pc_target() == pc_target.GAME_PC:
            return True
        try:
            return bool(find_program(app2))
        except Exception:
            return False

    remote = pc_target.is_remote(command)

    def _remote_volume(app):
        # Best-effort: lees het per-app-volume van de game-pc. Lukt dat
        # niet, dan vallen de aanroepers terug op hun eigen default (50).
        res = execute_tool(
            pc_target.remote_twin("audio_get_session_volume"),
            {"app_name": app},
            command,
        )
        data = getattr(res, "data", None) or {}
        for bron in (data.get("resultaat"), data):
            if isinstance(bron, dict) and bron.get("volume") is not None:
                return bron.get("volume")
        return None

    # -------------------------------------------------------------
    # 1. Welke apps maken geluid? / welke sessies zijn er?
    # -------------------------------------------------------------
    if re.search(
        r"(?:welke|wat|toon)\s+(?:apps|sessions?|programma's|programmas|"
        r"toepassingen|softwares?)?\s*(?:maken|spelen|speelt|draait|doen)?"
        r"?\s*(?:geluid|audio|muziek)\s*(?:af|maken)?\??$",
        question,
    ) or re.search(r"(?:wat|welke)\s+apps\s+spelen\s+audio", question) or \
    re.search(r"(?:welke|wat)\s+apps?\s+(?:maken)\s+geluid", question) or \
    re.search(r"(?:welke|wat)\s+apps?\s+maken\s+(?:er\s+)?geluid", question) or \
    re.search(r"(?:wat|welke|toon)\s+(?:apps|programma['\u2019]?s)\s+(?:maken|spelen|draaien)\s+(?:er\s+)?(?:geluid|audio)", question) or \
    re.search(r"^(?:wat|welke)\s+maken\s+(?:er\s+)?(?:geluid|audio)", question) or \
    question.rstrip().endswith(("geluid af", "audio af", "maken geluid",
                                "spelen geluid", "geluid afspelen", "geluid af?",
                                "maken er geluid", "geluid maakt")):
        if remote:
            return execute_tool(pc_target.remote_twin("audio_list_sessions"), {}, command)
        result = audio_list_sessions()
        if not result.ok:
            return "Het lukte niet om de audio-sessies te lezen."
        sessions = (result.data or {}).get("sessions", [])
        if not sessions:
            return "Er zijn geen apps die op dit moment geluid maken."
        lines = []
        for s in sessions:
            vol = s.get("volume")
            vol_str = f"{vol}%" if vol is not None else "?"
            muted = " (gedempt)" if s.get("muted") else ""
            name = s.get("name", "Onbekend")
            lines.append(f"- {name}: volume {vol_str}{muted}")
        return "Apps die geluid maken:\n" + "\n".join(lines)

    # -------------------------------------------------------------
    # 2. Welke audio-apparaten zijn er? / wat is de output?
    #    Alleen LIJSTEN als de vraag dat vraagt ("welke", "wat", "toon").
    #    "zet ... naar ..." hoort bij sectie 3.
    # -------------------------------------------------------------
    if re.search(
        r"(?:welke|wat|toon|noem)\s+(?:mijn\s+)?(?:audio-)?"
        r"(?:apparaten|devices|uitvoer|uitgangen|outputs?)",
        question,
    ) or re.search(r"(?:welke|wat|toon|noem)\s+(?:zijn\s+)?(?:er\s+)?.*?(?:headsets?|koptelefoons?|speakers?)", question):
        if remote:
            return execute_tool(pc_target.remote_twin("audio_list_outputs"), {}, command)
        result = audio_list_outputs()
        if not result.ok:
            return "Het lukte niet om de audio-apparaten te lezen."
        devices = (result.data or {}).get("devices", [])
        if not devices:
            return "Ik kon geen actieve audio-apparaten vinden."
        default = (result.data or {}).get("default") or ""
        lines = []
        for d in devices:
            name = d.get("name", "?")
            marker = " (standaard)" if name == default else ""
            lines.append(f"- {name}{marker}")
        return "Audio-outputapparaten:\n" + "\n".join(lines)

    # Huidige output?
    if re.search(r"waar(?:heen)?\s+gaat\s+(?:mijn\s+)?(?:geluid|audio)\s+(?:nu\s+)?(?:heen|naartoe|naar\s*toe)?\s*\??$", question) \
       or re.search(r"welke\s+(?:audio-)?output\s+(?:is\s+)?(?:actief|standaard|default)?", question) \
       or re.search(r"welk\s+(?:audio-)?apparaat\s+is\s+(?:actief|standaard|default)?", question) \
       or question.strip() in ("welke output heb ik", "wat is mijn output",
                               "wat is de output", "welke output is actief"):
        if remote:
            return execute_tool(pc_target.remote_twin("audio_get_default_output"), {}, command)
        return audio_get_default_output()

    # -------------------------------------------------------------
    # 3. Output wisselen: "zet (al het geluid) naar headset"
    # -------------------------------------------------------------
    m_out = re.search(
        r"(?:zet|verander|wissel|switch)\s+(?:al\s+het\s+|het\s+|mijn\s+)?"
        r"(?:geluid|audio|output|uitgang)?\s*(?:naar|op)\s+(?:de\s+|mijn\s+|"
        r"mijn\s+hoofdtelefoon\s+)?(.+?)\.?$",
        question,
    )
    if m_out:
        target = m_out.group(1).strip()
        # Vermijd "zet naar 50%" en microfoon/aangeboden
        if re.fullmatch(r"\d{1,3}\s*(?:%|procent)?", target):
            m_out = None
        elif re.search(r"(microfoon|microfoonmix|playback|systeem)?volume|eq|bass|treble", question):
            m_out = None
        elif not re.search(r"(headset|koptelefoon|hoofdtelefoon|speaker|speler|"
                           r"luidspreker|sonar|apparaat|device|nvidia|hdmi|usb|"
                           r"dual|realtek|arag|hyperx|fifine)", target, re.I):
            m_out = None  # geen herkenbaar apparaat → niet wisselen
    if m_out:
        target = m_out.group(1).strip()
        if remote:
            return execute_tool(pc_target.remote_twin("audio_set_default_output"), {"device_name": target}, command)
        return audio_set_default_output(target)

    # Accentloze aliassen: "speakers" → "Luidsprekers", "headset" → "Hoofdtelefoon"
    m_out2 = re.search(
        r"(?:zet|verander|wissel|switch)\s+(?:al\s+het\s+|het\s+|mijn\s+)?"
        r"(?:geluid|audio|output|uitgang)?\s*(?:naar|op)\s+(?:de\s+|mijn\s+)?(.+?)\.?$",
        question,
    )
    if m_out2:
        t2 = m_out2.group(1).strip().lower()
        if t2 in ("speakers", "speaker", "luidspreker", "luidsprekers"):
            if remote:
                return execute_tool(pc_target.remote_twin("audio_set_default_output"), {"device_name": "Luidsprekers"}, command)
            return audio_set_default_output("Luidsprekers")
        if t2 in ("headset", "koptelefoon", "hoofdtelefoon"):
            if remote:
                return execute_tool(pc_target.remote_twin("audio_set_default_output"), {"device_name": "Hoofdtelefoon"}, command)
            # Zoek het actieve device dat "Hoofdtelefoon" heet
            devs = audio_list_outputs()
            if devs.ok:
                for d in (devs.data or {}).get("devices", []):
                    if d["name"].startswith("Hoofdtelefoon"):
                        return audio_set_default_output(d["name"])
            return audio_set_default_output("Hoofdtelefoon")

    # -------------------------------------------------------------
    # 4. Per-app volume op een getal: "zet Spotify op 50",
    #    "zet het volume van Discord op 70", "Spotify volume naar 30"
    # -------------------------------------------------------------
    if _looks_like_app_volume(question):
        # Extraheer het getal
        mval = re.search(r"(?:op|naar)\s+(\d{1,3})\s*(?:%|procent)?", question)
        if mval and 0 <= int(mval.group(1)) <= 100:
            app = _app_in([
                r"(?:zet|doe|maak)\s+(\w+)\s+(?:op|naar)\s+\d",
                r"(?:zet|doe|maak)\s+(\w+)\s+volume\s+(?:op|naar)\s+\d",
                r"(?:zet|doe|maak)\s+(?:het\s+)?volume\s+(?:van|in)\s+(\w+)\s+(?:op|naar)\s+\d",
            ])
            if app and _real_app(app):
                if remote:
                    return execute_tool(pc_target.remote_twin("audio_set_session_volume"), {"app_name": app, "volume": int(mval.group(1))}, command)
                return audio_set_session_volume(app, int(mval.group(1)))

    # -------------------------------------------------------------
    # 5. Per-app volume zachter/harder: "maak Discord zachter"
    # -------------------------------------------------------------
    m_zachter = re.search(r"(?:maak|zet|doe)\s+(.+?)\s+(?:zachter|stiller|still|lager|harder|luider|hoger|omhoog|omlaag)", question)
    if m_zachter:
        app = m_zachter.group(1).strip()
        app = re.sub(r"^(het|de|een|mijn|van|het volume van|volume van)\s+", "", app).strip()
        if _real_app(app):
            tone = m_zachter.group(0)
            zachter = bool(re.search(r"zachter|stiller|still|lager|omlaag", tone))
            harder = bool(re.search(r"harder|luider|hoger|omhoog", tone))
            if remote:
                huidig = _remote_volume(app)
                basis = huidig if huidig is not None else 50
                if zachter:
                    return execute_tool(pc_target.remote_twin("audio_set_session_volume"), {"app_name": app, "volume": max(0, basis - 10)}, command)
                if harder:
                    return execute_tool(pc_target.remote_twin("audio_set_session_volume"), {"app_name": app, "volume": min(100, basis + 10)}, command)
            if zachter:
                current = audio_get_session_volume(app)
                if current.ok:
                    target = max(0, ((current.data or {}).get("volume") or 50) - 10)
                    return audio_set_session_volume(app, target)
            elif harder:
                current = audio_get_session_volume(app)
                if current.ok:
                    target = min(100, ((current.data or {}).get("volume") or 50) + 10)
                    return audio_set_session_volume(app, target)

    # -------------------------------------------------------------
    # 6. Per-app dempen: "demp Discord", "zet Discord geluid uit/aan"
    # -------------------------------------------------------------
    m_demp = re.search(
        r"(?:demp|mute|muteer|dempen|muten)\s+(.+?)\s*$", question,
    ) or re.search(r"zet\s+(.+?)(?:\s+geluid)?\s+(uit|aan)\s*$", question)
    if m_demp:
        if re.search(r"(?:demp|mute|muteer|dempen|muten)", m_demp.group(0)):
            muted_intent = True
        else:
            muted_intent = "aan" not in m_demp.group(0)
        app = m_demp.group(1).strip()
        app = re.sub(r"^(het|de|een|mijn|van)\s+", "", app).strip()
        if "geluid" in app:
            app = app.replace("geluid", "").strip()
        if app and _real_app(app):
            if remote:
                return execute_tool(pc_target.remote_twin("audio_set_session_mute"), {"app_name": app, "muted": muted_intent}, command)
            return audio_set_session_mute(app, muted_intent)

    return None


def try_media_command(command):

    question = command.lower().strip()

    remote = pc_target.is_remote(command)

    # Guard: woorden als "zachter"/"harder" kunnen zowel op media
    # (volume) als op smart-home (helderheid/lamp) slaan. Bevat de
    # opdracht een apparaatwoord en GEEN muziek-gerelateerd woord?
    # Dan is het een licht-actie (dimmen/helderheid), geen volume.
    if any(hw in question for hw in SMART_HOME_WORDS) and not any(
        mw in question for mw in (
            "muziek", "volume", "liedje", "nummer", "muziekje", "radio",
            "spotify", "nummers", "afspelen",
        )
    ):
        return None

    # APP-SPECIFIEKE VOLUME-ACTIE: "zet het volume van Spotify op 50",
    # "zet Spotify volume op 50", "zet Spotify op 50"
    # Bevat de zin een app-naam die een ECHT programma is?
    # Dan is het GEEN systeemvolume maar een actie IN die app.
    # Stuur naar de Agent (die ui_* tools kan gebruiken om de juiste
    # slider te vinden).
    if _looks_like_app_volume(question):
        return None  # overlaten aan Agent (ui_automation)

    # Volume op een exact percentage: "zet volume op 30", "zet het geluid op
    # 100". Zonder "geluid" viel "geluid op 100" door naar "geluid op"
    # (= harder) hieronder en ging het volume maar 5 stappen omhoog.
    match = re.search(
        r"\b(?:volume|geluid|geluidsvolume|systeemvolume)\s+(?:op|naar)\s+(\d{1,4})\s*(?:%|procent)?",
        question,
    )

    if match:
        percent = int(match.group(1))

        if 0 <= percent <= 100:
            if remote:
                return execute_tool("game_pc_set_volume", {"percent": percent}, command)
            return set_volume(percent)
        return "Het volume kan van 0 tot 100 procent, sir."

    # Volume omhoog
    if any(word in question for word in [
        "volume omhoog", "volume hoger", "volume hard", "harder", "luider",
        # extra Nederlandse formuleringen: "zet geluid op", "geluid harder",
        # "volume opzetten", "maak het geluid luid" enz.
        "geluid op", "geluid omhoog", "geluid hoger", "geluid harder",
        "geluid opzetten", "geluid luid", "volume op", "volume opzetten",
        "volume luid", "volume omhoog zetten", "volume hoger zetten",
        "maak het geluid luid", "maak geluid luid",
    ]):
        if remote:
            return execute_tool("game_pc_media", {"action": "volume_up"}, command)
        return volume_up()

    # Volume omlaag
    if any(word in question for word in [
        "volume omlaag", "volume lager", "volume zacht", "zachter",
        "stiller", "still",
        # extra Nederlandse formuleringen: "zet geluid omlaag", "geluid zachter" enz.
        "geluid omlaag", "geluid lager", "geluid zachter", "geluid zacht",
        "geluid stil", "volume stil", "maak het geluid zacht",
        "maak geluid zacht",
    ]):
        if remote:
            return execute_tool("game_pc_media", {"action": "volume_down"}, command)
        return volume_down()

    # Dempen / geluid aan
    if any(word in question for word in [
        "demp", "demp het geluid", "mute", "muteer", "geluid uit",
        "geluid aan", "zet het geluid uit", "zet het geluid aan",
    ]):
        if remote:
            return execute_tool("game_pc_media", {"action": "mute"}, command)
        return toggle_mute()

    # Pauzeren
    if any(word in question for word in [
        "pauzeer", "pauze", "pauseren", "pause",
        "zet muziek uit", "stop de muziek", "muziek stop",
    ]):
        if remote:
            return execute_tool("game_pc_media", {"action": "play_pause"}, command)
        return play_pause()

    # Afspelen / hervatten
    if any(word in question for word in [
        "speel verder", "speel weer", "speel door", "hervat",
        "play", "speel muziek", "speel de muziek", "zet muziek aan",
        "muziek aan", "start de muziek",
    ]):
        if remote:
            return execute_tool("game_pc_media", {"action": "play_pause"}, command)
        return play_pause()

    # Volgend nummer
    if any(word in question for word in [
        "volgende", "volgende nummer", "volgende track", "volgende song",
        "volgende liedje", "skip", "naar het volgende",
    ]):
        # Bij een genoemd smart-home apparaat (bijv. "op tv") hoort dit
        # bij HA, niet bij de lokale mediatoets.
        if any(hw in question for hw in SMART_HOME_WORDS):
            return None
        if remote:
            return execute_tool("game_pc_media", {"action": "next"}, command)
        return next_track()

    # Vorig nummer
    if any(word in question for word in [
        "vorige", "vorige nummer", "vorige track", "vorige song",
        "vorige liedje", "terug naar het vorige",
    ]):
        if any(hw in question for hw in SMART_HOME_WORDS):
            return None
        if remote:
            return execute_tool("game_pc_media", {"action": "previous"}, command)
        return previous_track()

    return None


# Telemetrievragen over temperatuur/gebruik (Fase 15). Deze zijn bewust
# losgetrokken van de andere systeemvragen zodat ze ook zonder het woord
# "game-pc" de juiste (lokale of remote) telemetrie bereiken.
_TELEMETRIE_VRAAG_PATRONEN = (
    re.compile(r"\bhoe\s+warm\b.*\b(cpu|processor|gpu|videokaart|grafische)\b"),
    re.compile(r"\b(cpu|processor|gpu|videokaart|grafische)\b.*\btemperatuur\b"),
    re.compile(r"\btemperatuur\b.*\b(cpu|processor|gpu|videokaart|grafische)\b"),
    re.compile(r"\bhoe\s+zwaar\b.*\bbelast"),
    re.compile(r"\bhoeveel\s+vram\b"),
    re.compile(r"\bhoeveel\s+gebruik"),
)


def _is_telemetrie_vraag(question):
    """True bij een vraag over temperatuur of gebruik van de pc."""

    return any(patroon.search(question) for patroon in _TELEMETRIE_VRAAG_PATRONEN)


def _pc_status_zin(status):
    """Zet het pc_status-dict om in één Nederlandse gesproken zin."""

    systeem = status.get("systeem") if isinstance(status, dict) else None

    if not isinstance(systeem, dict):
        return "Ik kon de status van je pc niet ophalen."

    delen = []

    if systeem.get("cpu"):
        delen.append(f"CPU: {systeem['cpu']}")

    if systeem.get("ram_totaal") is not None:
        delen.append(
            f"geheugen {systeem.get('ram_vrij')} van "
            f"{systeem.get('ram_totaal')} gigabyte vrij"
        )

    if systeem.get("disk_vrij") is not None:
        delen.append(f"schijf C {systeem['disk_vrij']} gigabyte vrij")

    if not delen:
        return "Ik kon de status van je pc niet ophalen."

    return "Je pc-status: " + ", ".join(delen) + "."


def try_system_info(command):

    question = command.lower().strip()

    # Volledige systeeminformatie
    if any(word in question for word in [
        "systeeminformatie", "systeeminfo",
        "wat voor pc heb ik", "wat voor computer heb ik",
    ]):
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("system_summary"), {}, command)
        return system_summary()

    # Unified PC-status (Fase 12): "geef me een overzicht"
    if any(phrase in question for phrase in [
        "pc status", "status van mijn pc", "geef me een overzicht",
        "geef mij een overzicht", "alles over mijn systeem",
        "hoe is het met mijn pc", "wat gebeurt er allemaal",
        "overzicht van mijn pc", "pc overzicht",
    ]):
        if pc_target.is_remote(command):
            return execute_tool("game_pc_status", {}, command)
        return _pc_status_zin(pc_status_tool())

    # Scherminformatie (Fase 6)
    if any(word in question for word in [
        "scherminformatie", "scherminfo",
        "welke resolutie", "wat is mijn resolutie",
        "schermresolutie", "hoe groot is mijn scherm",
        "welk scherm heb ik",
    ]):
        if pc_target.is_remote(command):
            return pc_target.blokkade_bericht("screen_info")
        return screen_info()

    # Processor
    if any(word in question for word in [
        "wat is mijn cpu", "welke cpu", "welke processor",
        "wat voor processor", "wat is mijn processor",
    ]):
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("cpu_info"), {}, command)
        info = cpu_info()
        return (
            f"Je hebt een {info['naam']} met {info['cores']} cores "
            f"en {info['threads']} threads."
        )

    # RAM / geheugen
    if re.search(r"(hoeveel|wat).*\bram\b", question) or "geheugen" in question:
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("ram_info"), {}, command)
        info = ram_info()
        return (
            f"Je hebt {info['totaal']} GB RAM, waarvan {info['gebruikt']} GB "
            f"in gebruik en {info['vrij']} GB nog vrij."
        )

    # GPU / videokaart
    if any(word in question for word in [
        "welke gpu", "wat is mijn gpu", "welke videokaart",
        "wat voor videokaart", "welke grafische kaart",
    ]):
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("gpu_names"), {}, command)
        gpus = gpu_names()
        if len(gpus) == 1:
            return f"Je videokaart is een {gpus[0]}."
        return f"Je videokaarten zijn: {', '.join(gpus)}."

    # Schijfruimte
    if any(word in question for word in [
        "schijfruimte", "hoeveel ruimte", "hoeveel vrije ruimte",
        "hoeveel vrij", "hoeveel opslag",
    ]):
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("disk_info"), {}, command)
        info = disk_info()
        return (
            f"Op je C-schijf is {info['vrij']} GB vrij van de "
            f"{info['totaal']} GB."
        )

    # Batterij
    if "batterij" in question:
        if pc_target.is_remote(command):
            return pc_target.blokkade_bericht("battery_info")
        battery = battery_info()

        if not battery:
            return "Deze computer heeft geen batterij."

        if battery["stekker"]:
            return f"Je batterij staat op {battery['percentage']}% en de pc hangt aan de stroom."

        return f"Je batterij staat op {battery['percentage']}% en de pc draait op de accu."

    # Windows-versie
    if "windows" in question or "besturingssysteem" in question:
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("os_info"), {}, command)
        info = os_info()
        return f"Je draait {info['systeem']} {info['release']}."

    # Uptime
    if any(word in question for word in [
        "hoe lang staat", "hoelang staat", "hoe lang staat hij",
        "uptime", "hoe lang is de pc aan",
    ]):
        if pc_target.is_remote(command):
            return execute_tool(pc_target.remote_twin("uptime"), {}, command)
        duration = uptime()
        return (
            f"Je pc staat al {duration['dagen']} dagen, {duration['uren']} "
            f"uur en {duration['minuten']} minuten aan."
        )

    # Telemetrie: temperatuur en gebruik (Fase 15). Werkt ook zonder dat de
    # zin "game-pc" bevat; bij doel game-pc gaat de vraag naar de agent.
    if _is_telemetrie_vraag(question):
        if pc_target.is_remote(command):
            return execute_tool("game_pc_telemetry", {}, command)
        return _pc_status_zin(pc_status_tool())

    return None


WINDOW_FILLER_WORDS = {
    "minimaliseer", "minimalizeer", "minimaliseren", "verklein", "verkleinen",
    "maximaliseer", "maximalizeer", "maximaliseren", "maximale", "maximaal",
    "vergroot", "vergroten", "groter", "groot", "grote", "klein", "kleiner",
    "maak", "vouw", "klap", "in", "weer", "normaal", "vorige",
    "grootte", "herstel", "herstellen", "naar", "de", "taakbalk",
    "venster", "vensters", "programma", "applicatie", "toepassing",
    "app", "apps", "ook", "bijv", "en",
}

WINDOW_ACTION_WORDS = {
    "minimize": [
        "minimaliseer", "minimalizeer", "minimaliseren",
        "verklein", "verkleinen", "klein",
    ],
    "maximize": [
        "maximaliseer", "maximalizeer", "maximaliseren",
        "maximale", "maximaal", "vergroot", "vergroten",
        "groot", "groter",
    ],
    "restore": [
        "herstel", "herstellen", "normaal",
    ],
}


def _detect_window_action(text):

    for action, words in WINDOW_ACTION_WORDS.items():

        if any(word in text for word in words):
            return action

    return None


def _apply_window_action(action, target, command=None):

    # Bij een remote doel gaat de vensteractie naar de game-pc-twin.
    if command is not None and pc_target.is_remote(command):
        lokaal = "minimize_program" if action == "minimize" else (
            "maximize_program" if action == "maximize" else "restore_window"
        )
        return execute_tool(pc_target.remote_twin(lokaal), {"program": target}, command)

    result = ""

    # Venster is er misschien nog niet als we net een programma
    # hebben geopend; een paar keer opnieuw proberen.
    for _ in range(3):

        if action == "minimize":
            result = minimize_program(target)
        elif action == "maximize":
            result = maximize_program(target)
        else:
            result = restore_window(target)

        if "kon geen venster" not in result:
            return result

        time.sleep(1.0)

    return result


def try_combined_open_window(command):

    question = command.lower().strip()

    match = re.search(r"^open\s+(.+?)\s+en\s+(.+)$", question)

    if not match:
        return None

    program = match.group(1).strip()
    rest = match.group(2).strip()

    # Alleen afhandelen als het tweede deel een venster-actie is
    action = _detect_window_action(rest)

    if not action:
        return None

    # "open discord en spotify en vergroot" → te ingewikkeld, laat AI het doen
    if "en" in program:
        return None

    program = program.replace("-venster", "").replace(" venster", "").strip()

    tokens = [t.strip(".,!?") for t in rest.replace(",", " ").split() if t.strip(".,!?")]
    names = [
        t for t in tokens
        if t not in WINDOW_FILLER_WORDS and t not in SKIP_PARSE_WORDS
    ]
    target = " ".join(names).replace("-venster", "").replace(" venster", "").strip() or program

    if pc_target.is_remote(command):
        open_result = execute_tool(
            pc_target.remote_twin("open_program_tool"), {"program": program}, command
        )
    else:
        open_result = open_program_tool(program)

    window_result = _apply_window_action(action, target, command)

    update_context(
        last_command=command,
        last_result=f"{open_result} {window_result}",
        last_action="gecombineerd",
        last_program=target
    )

    return format_results([open_result, window_result])


def try_screenshot(command):

    question = command.lower().strip()

    if not any(word in question for word in [
        "screenshot", "schermafbeelding", "schermfoto", "scherm foto",
        "foto van mijn scherm",
    ]):
        return None

    if pc_target.is_remote(command):
        return execute_tool("game_pc_screenshot", {}, command)

    path = take_screenshot()

    if pc_target.is_remote(command):
        return execute_tool("game_pc_screenshot", {}, command)

    if not path:
        return "Ik kon geen screenshot maken."

    filename = os.path.basename(path)

    update_context(
        last_command=command,
        last_result=f"screenshot {filename}",
        last_action="screenshot gemaakt"
    )

    return f"Ik heb een screenshot gemaakt en geopend: {filename}."


LOCATION_WORDS = [
    "bureaublad", "desktop", "downloads", "documenten", "afbeeldingen",
    "pictures", "foto's", "fotos", "muziek", "video's", "videos", "movies",
]

LIST_HEADER_WORDS = {
    "wat", "zit", "zitten", "sta", "staat", "staan", "er", "erin", "is",
    "zijn", "in", "een", "mijn", "de", "het", "laat", "toon", "lijst",
    "welke", "bestanden", "bestand", "map", "mappen", "even", "zien",
    "toon", "aan", "mij", "me", "graag",
}


def extract_question_name(question):

    tokens = question.lower().split()

    index = 0

    while index < len(tokens) and tokens[index] in LIST_HEADER_WORDS:
        index += 1

    name = " ".join(tokens[index:]).strip()

    # "laat mijn testmap zien" → "testmap"
    name = re.sub(
        r"\s+(zien|toon|even|aan mij|voor mij|aan|me|graag)\s*$",
        "",
        name
    ).strip()

    return name.strip(" .,!?")


def find_location_word(text):

    lower = text.lower()

    for word in sorted(LOCATION_WORDS, key=len, reverse=True):

        if word in lower:
            return word

    return None


def clean_file_name(text):

    name = text.strip().strip(" .,!?")

    # "de map test" → "test", "het bestand cv" → "cv", "map test" → "test"
    name = re.sub(
        r"^(?:de|het|een|mijn|die)\s+(?:map|mappen|bestand|bestanden)\s+",
        "",
        name
    )
    name = re.sub(
        r"^(?:map|mappen|bestand|bestanden)\s+",
        "",
        name
    )

    return name.strip()


def extract_create_name(rest):

    location_word = find_location_word(rest)

    name = rest

    if location_word:

        index = rest.lower().find(location_word)

        name = re.sub(
            r"\s*(?:op\s+(?:het\s+|mijn\s+|de\s+)?|in\s+(?:mijn\s+|de\s+|het\s+)?)$",
            "",
            rest[:index]
        ).strip()

    name = name.strip(" .,!?")

    # "op mijn bureaublad genaamd auditai3" → "auditai3"
    if not name:

        match = re.search(r"(?:genaamd|met de naam)\s+(.+)", rest)

        if match:
            name = match.group(1).strip(" .,!?")

    return name, location_word


def try_file_command(command):

    question = command.lower().strip()

    if pc_target.is_remote(command):
        return _remote_file_command(command)

    # -------------------------------------------------
    # BESTANDEN/ZOEKEN: "zoek naar X", "zoek mijn X"
    # -------------------------------------------------

    search_match = re.search(r"zoek\s+(?:naar|mijn)\s+(.+)", question)

    if search_match:
        query = search_match.group(1).strip().strip(".,!?")

        if query and len(query) > 1:
            return search_files(query)

    # -------------------------------------------------
    # HERNOEMEN: "hernoem X naar Y", "noem X om naar Y"
    # -------------------------------------------------

    rename_match = re.search(r"(?:hernoem|noem\s+(.+)\s+om\s+naar|hernoemen?)\s+(.+?)\s+naar\s+(.+)", question)

    if not rename_match:
        rename_match = re.search(r"hernoem\s+(.+?)\s+naar\s+(.+)", question)

    if rename_match:
        if rename_match.lastindex and rename_match.lastindex >= 3:
            old_name = clean_file_name(rename_match.group(2))
            new_name = clean_file_name(rename_match.group(3))
        else:
            old_name = clean_file_name(rename_match.group(1))
            new_name = clean_file_name(rename_match.group(2))

        if old_name and new_name:
            return rename_file(old_name, new_name)

    # -------------------------------------------------
    # MAP MAKEN: "maak een map (genaamd) X op/in <locatie>"
    # -------------------------------------------------

    map_match = re.search(
        r"(?:maak\s+(?:een\s+)?(?:nieuwe\s+)?map(?:\s+genaamd\s+)?"
        r"|maak er een map(?:\s+genaamd\s+)?"
        r"|maak voor mij een map(?:\s+genaamd\s+)?"
        r"|een map maken(?:\s+genaamd\s+)?"
        r"|een map voor mij maken(?:\s+genaamd\s+)?"
        r"|map maken(?:\s+genaamd\s+)?"
        r"|map voor mij maken(?:\s+genaamd\s+)?)\s*(.+)",
        question
    )

    if map_match:

        rest = map_match.group(1).strip()

        name, location_word = extract_create_name(rest)

        if not name:
            return "Welke naam moet de map krijgen?"

        return create_folder(name, location_word or "")

    # -------------------------------------------------
    # BESTAND MAKEN: "maak een bestand (genaamd) X op/in <locatie>"
    # -------------------------------------------------

    file_match = re.search(
        r"(?:maak\s+(?:een\s+)?(?:nieuw\s+)?bestand(?:\s+genaamd\s+)?"
        r"|maak voor mij een bestand(?:\s+genaamd\s+)?"
        r"|een bestand maken(?:\s+genaamd\s+)?"
        r"|een bestand voor mij maken(?:\s+genaamd\s+)?"
        r"|bestand maken(?:\s+genaamd\s+)?)\s*(.+)",
        question
    )

    if file_match:

        rest = file_match.group(1).strip()

        name, location_word = extract_create_name(rest)

        if not name:
            return "Welke naam moet het bestand krijgen?"

        return create_file(name, location_word or "")

    # -------------------------------------------------
    # BESTANDEN LIJKS/TONEN: "welke bestanden zitten in X"
    # -------------------------------------------------

    if any(word in question for word in [
        "welke bestanden", "wat zit er", "wat zit erin",
        "laat mijn", "toon mijn", "laat de", "toon de",
        "lijst mijn", "wat staat er in",
    ]):

        location_word = find_location_word(question)

        if location_word:
            return list_folder(location_word)

        # Geen bekende locatie? Dan een map op naam zoeken,
        # bijv. "wat zit er in test123" of "wat zit er een test".
        folder_name = extract_question_name(question)

        if not folder_name or folder_name in ("bestanden", "bestand"):
            return None

        folder_name = clean_file_name(folder_name)

        if not folder_name:
            return None

        folder_matches = [
            item for item in find_item(folder_name)
            if os.path.isdir(item)
        ]

        if not folder_matches:
            return f"Ik kan de map '{folder_name}' niet vinden."

        if len(folder_matches) > 1:

            locations = [
                os.path.basename(os.path.dirname(item))
                for item in folder_matches[:5]
            ]

            update_context(
                pending_choice={
                    "kind": "list",
                    "name": folder_name,
                    "matches": folder_matches,
                }
            )

            return (
                f"Ik heb meerdere mappen '{folder_name}' gevonden, "
                f"bijvoorbeeld in: {', '.join(locations)}. "
                "Zeg de plek, zoals 'desktop' of 'pictures', of geef een nummer."
            )

        return list_folder_by_path(folder_matches[0])

    # -------------------------------------------------
    # KOPIËREN: "kopieer X naar <locatie>"
    # -------------------------------------------------

    copy_match = re.search(r"kopi[ée]er\s+(.+?)\s+naar\s+(.+)", question)

    if copy_match:

        filename = clean_file_name(copy_match.group(1))

        location = find_location_word(copy_match.group(2))

        if not filename or not location:
            return "Ik weet niet wat ik moet kopiëren of waarheen."

        found = find_item(filename)

        if not found:
            return f"Ik kan {filename} niet vinden."

        if len(found) > 1:

            parents = [os.path.basename(os.path.dirname(item)) for item in found[:5]]

            update_context(
                pending_choice={
                    "kind": "copy",
                    "name": filename,
                    "matches": found,
                    "destination": location,
                }
            )

            return (
                f"Ik heb meerdere bestanden of mappen met de naam '{filename}' "
                f"gevonden, bijvoorbeeld in: {', '.join(parents)}. "
                "Welke wil je kopiëren? Zeg de plek of geef een nummer."
            )

        return copy_path(found[0], location)

    # -------------------------------------------------
    # VERPLAATSEN: "verplaats X naar <locatie>"
    # -------------------------------------------------

    move_match = re.search(r"verplaats\s+(.+?)\s+naar\s+(.+)", question)

    if move_match:

        filename = clean_file_name(move_match.group(1))

        location = find_location_word(move_match.group(2))

        if not filename or not location:
            return "Ik weet niet wat ik moet verplaatsen of waarheen."

        found = find_item(filename)

        if not found:
            return f"Ik kan {filename} niet vinden."

        if len(found) > 1:

            parents = [os.path.basename(os.path.dirname(item)) for item in found[:5]]

            update_context(
                pending_choice={
                    "kind": "move",
                    "name": filename,
                    "matches": found,
                    "destination": location,
                }
            )

            return (
                f"Ik heb meerdere bestanden of mappen met de naam '{filename}' "
                f"gevonden, bijvoorbeeld in: {', '.join(parents)}. "
                "Welke wil je verplaatsen? Zeg de plek of geef een nummer."
            )

        return move_path(found[0], location)

    # -------------------------------------------------
    # PRULLENBAK LEGEN: "leeg de prullenbak"
    # -------------------------------------------------

    if re.search(r"(?:leeg(?:maken)?\s+(?:de\s+)?prullenbak|prullenbak\s+leegmaken|maak de prullenbak leeg)", question):

        update_context(
            pending_choice={
                "kind": "empty_confirm",
            }
        )

        return "Wil je dat ik de prullenbak echt leegmaak? Zeg 'ja' of 'nee'."

    # -------------------------------------------------
    # VERWIJDEREN: "verwijder X", "gooi X weg",
    #               "gooi X in de prullenbak"
    # -------------------------------------------------

    delete_name = None

    if any(word in question for word in ["prullenbak", "weggooien", "wegdoen", "gooi", "gooien"]):

        # "gooi X weg"
        match = re.search(r"gooi\s+(.+?)\s+weg\b", question)
        if match:
            delete_name = clean_file_name(match.group(1))

        # "gooi/zet X in de prullenbak"
        match = re.search(
            r"(?:gooi|zet|doe)\s+(.+?)\s+(?:in|naar)\s+de prullenbak",
            question
        )
        if match and not delete_name:
            delete_name = clean_file_name(match.group(1))

        if not delete_name:
            return None

    elif "verwijder" in question:

        match = re.search(r"verwijder\s+(.+)", question)

        if not match:
            match = re.search(r"verwijderen?\s+(.+)", question)

        if not match:
            match = re.search(r"(.+?)\s+verwijderen?\s*$", question)

        if match:
            candidate = clean_file_name(match.group(1))

            # Alleen bestandsverwijdering als er een bestand/map hint is
            # óf er écht iets gevonden wordt. Anders laat het geheugenvergeten
            # de vrije hand ("verwijder mijn favoriete game").
            has_hint = any(word in question for word in [
                "bestand", "bestanden", "map", "mappen", "file",
                "foto", "foto's", "fotos", "document", "download", "video",
            ])

            if has_hint or find_item(candidate):
                delete_name = candidate

    if delete_name:

        found = find_item(delete_name)

        if not found:
            return f"Ik kan {delete_name} niet vinden."

        if len(found) > 1:

            parents = [os.path.basename(os.path.dirname(item)) for item in found[:5]]

            update_context(
                pending_choice={
                    "kind": "delete_choose",
                    "name": delete_name,
                    "matches": found,
                }
            )

            return (
                f"Ik heb meerdere bestanden of mappen met de naam '{delete_name}' "
                f"gevonden, bijvoorbeeld in: {', '.join(parents)}. "
                "Welke wil je verwijderen? Zeg de plek of geef een nummer."
            )

        # Altijd direct naar de prullenbak (geen bevestiging)
        return send_to_recycle(found[0])

    return None


def _remote_file_command(command):
    """Remote-parsing voor bestandsbeheer als standaarddoel game-pc is."""

    if not pc_target.is_remote(command):
        return None

    question = command.lower().strip()

    # 1. Zoeken
    search_match = re.search(r"zoek\s+(?:naar|mijn)\s+(.+)", question)
    if search_match:
        query = search_match.group(1).strip().strip(".,!?")
        if query and len(query) > 1:
            # Alleen als query duidelijke bestandshints heeft, anders niet remote sturen
            query_l = query.lower()
            hints = (
                "bestand", "bestanden", "map", "mappen", "file",
                "foto", "foto's", "fotos", "document", "documenten", "download", "downloads",
                "video", "video's", "afbeelding", "afbeeldingen", "muziek", "audio",
                ".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".mp3", ".mp4", ".wav", ".avi", ".mkv",
            )
            if any(h in query_l for h in hints):
                return execute_tool("game_pc_search_files", {"query": query}, command)

    # 2. Hernoemen
    rename_match = re.search(
        r"(?:hernoem|noem\s+(.+)\s+om\s+naar|hernoemen?)\s+(.+?)\s+naar\s+(.+)",
        question,
    )
    if not rename_match:
        rename_match = re.search(r"hernoem\s+(.+?)\s+naar\s+(.+)", question)
    if rename_match:
        if rename_match.lastindex and rename_match.lastindex >= 3:
            old_name = clean_file_name(rename_match.group(2))
            new_name = clean_file_name(rename_match.group(3))
        else:
            old_name = clean_file_name(rename_match.group(1))
            new_name = clean_file_name(rename_match.group(2))
        if old_name and new_name:
            return execute_tool(
                "game_pc_rename_file",
                {"old_name": old_name, "new_name": new_name},
                command,
            )

    # 3. Map maken
    map_match = re.search(
        r"(?:maak\s+(?:een\s+)?(?:nieuwe\s+)?map(?:\s+genaamd\s+)?"
        r"|maak er een map(?:\s+genaamd\s+)?"
        r"|maak voor mij een map(?:\s+genaamd\s+)?"
        r"|een map maken(?:\s+genaamd\s+)?"
        r"|een map voor mij maken(?:\s+genaamd\s+)?"
        r"|map maken(?:\s+genaamd\s+)?"
        r"|map voor mij maken(?:\s+genaamd\s+)?)\s*(.+)",
        question,
    )
    if map_match:
        rest = map_match.group(1).strip()
        name, location_word = extract_create_name(rest)
        if not name:
            return "Welke naam moet de map krijgen?"
        args = {"name": name}
        if location_word:
            args["location"] = location_word
        return execute_tool("game_pc_create_folder", args, command)

    # 4. Bestand maken
    file_match = re.search(
        r"(?:maak\s+(?:een\s+)?(?:nieuw\s+)?bestand(?:\s+genaamd\s+)?"
        r"|maak voor mij een bestand(?:\s+genaamd\s+)?"
        r"|een bestand maken(?:\s+genaamd\s+)?"
        r"|een bestand voor mij maken(?:\s+genaamd\s+)?"
        r"|bestand maken(?:\s+genaamd\s+)?)\s*(.+)",
        question,
    )
    if file_match:
        rest = file_match.group(1).strip()
        name, location_word = extract_create_name(rest)
        if not name:
            return "Welke naam moet het bestand krijgen?"
        args = {"name": name}
        if location_word:
            args["location"] = location_word
        return execute_tool("game_pc_create_file", args, command)

    # 5. Lijst (alleen op locatie)
    if any(word in question for word in [
        "welke bestanden", "wat zit er", "wat zit erin",
        "laat mijn", "toon mijn", "laat de", "toon de",
        "lijst mijn", "wat staat er in",
    ]):
        location_word = find_location_word(question)
        if location_word:
            return execute_tool("game_pc_list_files", {"location": location_word}, command)
        # geen locatie-label → niet deterministisch remote; laat LLM het oppakken

    # 6. Kopiëren
    copy_match = re.search(r"kopi[ée]er\s+(.+?)\s+naar\s+(.+)", question)
    if copy_match:
        filename = clean_file_name(copy_match.group(1))
        location = find_location_word(copy_match.group(2))
        if filename and location:
            return execute_tool(
                "game_pc_copy_file",
                {"filename": filename, "location": location},
                command,
            )

    # 7. Verplaatsen
    move_match = re.search(r"verplaats\s+(.+?)\s+naar\s+(.+)", question)
    if move_match:
        filename = clean_file_name(move_match.group(1))
        location = find_location_word(move_match.group(2))
        if filename and location:
            return execute_tool(
                "game_pc_move_file",
                {"filename": filename, "location": location},
                command,
            )

    # 8. Prullenbak legen
    if re.search(r"(?:leeg(?:maken)?\s+(?:de\s+)?prullenbak|prullenbak\s+leegmaken|maak de prullenbak leeg)", question):
        return execute_tool("game_pc_empty_recycle_bin", {}, command)

    # 9. Verwijderen
    delete_name = None
    if any(word in question for word in ["prullenbak", "weggooien", "wegdoen", "gooi", "gooien"]):
        match = re.search(r"gooi\s+(.+?)\s+weg\b", question)
        if match:
            delete_name = clean_file_name(match.group(1))
        match = re.search(
            r"(?:gooi|zet|doe)\s+(.+?)\s+(?:in|naar)\s+de prullenbak",
            question,
        )
        if match and not delete_name:
            delete_name = clean_file_name(match.group(1))
        if not delete_name:
            return None
    elif "verwijder" in question:
        match = re.search(r"verwijder\s+(.+)", question)
        if not match:
            match = re.search(r"verwijderen?\s+(.+)", question)
        if not match:
            match = re.search(r"(.+?)\s+verwijderen?\s*$", question)
        if match:
            candidate = clean_file_name(match.group(1))
            has_hint = any(word in question for word in [
                "bestand", "bestanden", "map", "mappen", "file",
                "foto", "foto's", "fotos", "document", "download", "video",
            ])
            if has_hint:
                delete_name = candidate

    if delete_name:
        return execute_tool("game_pc_recycle_file", {"filename": delete_name}, command)

    return None


def _extract_window_program(command):

    tokens = [t.strip(".,!?") for t in command.replace(",", " ").split() if t.strip(".,!?")]

    names = [
        token.lower()
        for token in tokens
        if token.lower() not in WINDOW_FILLER_WORDS and token.lower() not in SKIP_PARSE_WORDS
    ]

    if not names:
        return None

    program = " ".join(names)

    # "spotify-venster" of "spotify venster" opschonen
    program = program.replace("-venster", "").replace("-vensters", "")
    program = program.replace(" venster", "").replace(" vensters", "")

    return program.strip() or None


def try_window_command(command):

    question = command.lower().strip()

    state = None

    if any(word in question for word in [
        "minimaliseer", "minimalizeer", "minimaliseren", "klap in",
        "vouw in", "verklein", "verkleinen", "naar de taakbalk",
    ]) or ("maak" in question and "klein" in question):
        state = "minimize"

    elif any(word in question for word in [
        "maximaliseer", "maximalizeer", "maximaliseren", "vergroot",
        "vergroten",
    ]) or ("maak" in question and "groot" in question):
        state = "maximize"

    elif any(word in question for word in [
        "herstel", "herstel het venster", "weer normaal",
        "vorige grootte",
    ]):
        state = "restore"

    if not state:
        return None

    # Meerdere vensters in één zin: laat de AI dat doen
    if "," in question or " en " in question:
        return None

    program = _extract_window_program(question)

    if not program:
        if current_context["last_program"]:
            program = current_context["last_program"]
        else:
            return "Welk programma wil je dat ik aanpas?"

    if pc_target.is_remote(command):
        lokaal = "minimize_program" if state == "minimize" else (
            "maximize_program" if state == "maximize" else "restore_window"
        )
        return execute_tool(pc_target.remote_twin(lokaal), {"program": program}, command)

    if state == "minimize":
        return minimize_program(program)

    if state == "maximize":
        return maximize_program(program)

    return restore_window(program)


# =============================================================
# Fase 5 — VOORKEUREN HERKENNEN + BIJWERKEN
# =============================================================

def _preference_key(phrase):
    """
    Bepaalt een mooie geheugensleutel + categorie uit een voorkeurszin.
    "warm wit licht" -> ("lichtvoorkeur", "warm wit", "voorkeuren")
    """

    p = phrase.lower()

    if any(word in p for word in [
        "licht", "verlichting", "lamp", "lampen", "kleur", "warm",
        "koel", "fel", "zacht", "helder", "gedimd", "sfeer", "wit",
        "dim", "schemer", "lichtkleur",
    ]):
        value = phrase.strip()
        value = re.sub(r"\s*(licht|verlichting)$", "", value).strip(" .!?")
        return "lichtvoorkeur", value, "voorkeuren"

    if any(word in p for word in [
        "muziek", "nummer", "band", "artiest", "genre", "song",
        "track", "album", "playlist", "zanger",
    ]):
        return "muziekvoorkeur", phrase.strip(" .!?"), "muziek"

    if any(word in p for word in [
        "temperatuur", "graden", "koud", "kou", "warmte", "klimaat",
    ]):
        return "temperatuurvoorkeur", phrase.strip(" .!?"), "voorkeuren"

    return "voorkeur", phrase.strip(" .!?"), "voorkeuren"


def extract_preference(command):
    """
    Haalt een voorkeur uit een losse mededeling (zonder 'onthoud'):
      "ik hou meestal van warm wit licht"
      "ik vind zacht licht fijn"
      "mijn voorkeur voor licht is warm wit"

    Geeft (key, value, category) of None.
    """

    question = command.lower().strip()

    # "ik hou (meestal/altijd/graag) van X"
    match = re.search(
        r"ik (?:hou|houd|heb)\s+"
        r"(?:meestal\s+|altijd\s+|graag\s+|wel\s+|weleens\s+|eigenlijk\s+)?"
        r"van\s+(.+)",
        question,
    )

    if match:
        return _preference_key(match.group(1))

    # "ik vind X fijn/prettig"
    match = re.search(
        r"ik vind\s+(.+?)\s+(fijn|prettig|aangenaam|lekker|gezellig)\b",
        question,
    )

    if match:
        return _preference_key(match.group(1))

    # "mijn voorkeur voor X is Y"
    match = re.search(r"mijn voorkeur voor (.+?) is (.+)", question)

    if match:
        key, _, category = _preference_key(match.group(2).strip())
        return key, match.group(2).strip(" .!?"), category

    # "mijn voorkeur is X"
    match = re.search(r"mijn voorkeur is (.+)", question)

    if match:
        return _preference_key(match.group(1))

    return None


def _remember_or_ask(key, value, category=None, source="conversation"):
    """
    Slaat een feit op via remember() en vangt een conflict af.

    Geeft None terug als het feit gewoon opgeslagen kon worden.
    Geeft een bevestigingsvraag terug als er een conflict was: de
    nieuwe waarde is dan NIET opgeslagen en er wordt een
    pending_choice klaargezet zodat "ja"/"nee" het conflict afhandelt.

    Zo wordt een tegenstrijdige waarde nooit stilzwijgend
    overschreven, maar ook niet zomaar weggegooid.
    """

    result = remember(key, value, category=category, source=source)

    if not result.get("needs_confirm"):
        return None

    update_context(pending_choice={
        "kind": "memory_update",
        "memory_key": result["memory_key"],
        "memory_value": result["memory_value"],
        "memory_category": result.get("category"),
        "old_value": result.get("old_value"),
    })

    return (
        f"Ik wist al dat je {result['memory_key'].replace('_', ' ')} "
        f"{result['old_value']} is, nu zeg je {value}. "
        f"Zal ik dat wijzigen? Zeg 'ja' of 'nee'."
    )


def _store_preference(key, value, category=None):
    """
    Slaat een voorkeur op. Staat er al een ANDERE waarde, dan wordt
    eerst om bevestiging gevraagd via pending_choice (geen stille
    overschrijving).

    Geeft de spoken reply terug.
    """

    found_category, existing = find_entry(key, category)

    if existing is not None and not _values_equal(existing.get("value"), value):

        old = existing.get("value")

        update_context(pending_choice={
            "kind": "memory_update",
            "memory_key": key,
            "memory_value": value,
            "memory_category": found_category,
            "old_value": old,
        })

        return (
            f"Ik wist dat je {beautify(key)} {old} is, "
            f"nu zeg je {value}. Zal ik dat wijzigen? Zeg 'ja' of 'nee'."
        )

    remember(key, value, category=category, source="conversation")

    return f"Ik onthoud dat je {beautify(key)} {value} is."


def _sleutelbevestiging(oplossing, actie):
    """
    Stelt een fuzzy-sleutelvraag aan de gebruiker.

    Bij precies één kandidaat gaat er een pending_choice klaarstaan
    ("Bedoelde je 'lichtvoorkeur'?"): "ja" voert de actie op die sleutel
    uit, "nee" op de oorspronkelijke. Bij MEERDERE kandidaten wordt er
    niets automatisch gekozen — de gebruiker krijgt de lijst en moet
    opnieuw formuleren, want een stilzwijgende gok kan hier een ander
    feit wijzigen of verwijderen.
    """

    kandidaten = oplossing.get("candidates") or []

    if len(kandidaten) == 1:

        bedoelde = kandidaten[0]

        update_context(pending_choice={
            "kind": "memory_key_confirm",
            "query": oplossing.get("query") or oplossing.get("key"),
            "resolved": bedoelde,
            "operation": actie,
        })

        return (
            f"Bedoelde je '{bedoelde.replace('_', ' ')}'? "
            "Zeg 'ja' of 'nee'."
        )

    zichtbaar = [k.replace("_", " ") for k in kandidaten[:6]]

    lijst = ", ".join(f"'{k}'" for k in zichtbaar)

    if len(kandidaten) > len(zichtbaar):
        lijst += f" (en nog {len(kandidaten) - len(zichtbaar)})"

    return (
        f"Ik vind meerdere geheugenfeiten die daarbij passen: {lijst}. "
        "Noem er één zo dat ik precies weet welk je bedoelt."
    )


def _hervat_sleutelbevestiging(pending, bevestigd):
    """
    Voert de opgeslagen memory-actie uit nadat de gebruiker heeft
    gezegd welke sleutel hij bedoelde.
    """

    actie = pending.get("operation") or {}

    if actie.get("operation") == "update":
        return _memory_update_onderwerp(
            actie.get("query") or pending.get("query") or "",
            actie.get("new_value") or "",
            category=actie.get("category"),
            opgeloste_sleutel=pending.get("resolved") if bevestigd else None,
        )

    if actie.get("operation") == "forget":
        return _memory_forget_onderwerp(
            pending.get("resolved") if bevestigd else pending.get("query"),
            category=actie.get("category"),
            opgeloste_sleutel=True,
        )

    return "Ik heb geen wijziging om door te zetten."


def _memory_update_onderwerp(subject, new_value, category=None,
                             opgeloste_sleutel=None):
    """
    Voert de memory-wijziging uit op één onderwerp.

    De sleutel wordt eerst opgesloten via resolve_existing_key(): een
    verkorte of andere formulering ("licht") kan naar een bestaande
    sleutel ("lichtvoorkeur") verwijzen. Eén fuzzy kandidaat betekent
    een vraag; meerdere betekenen geen automatische keuze.
    """

    if opgeloste_sleutel is None:

        key = subject.replace(" ", "_")

        oplossing = resolve_existing_key(key, category)

        if oplossing["status"] == "fuzzy":
            oplossing = dict(oplossing)
            oplossing["query"] = subject

            return _sleutelbevestiging(oplossing, {
                "operation": "update",
                "query": subject,
                "new_value": new_value,
                "category": category,
            })

        key = oplossing["key"]

    else:
        key = opgeloste_sleutel

    found_category, existing = find_entry(key, category)

    old = existing.get("value") if existing is not None else None

    update_memory(key, new_value,
                  category=found_category or category, source="user")

    if old is not None:
        return f"Oké, ik heb je {subject} aangepast van '{old}' naar '{new_value}'."

    return f"Oké, ik onthoud dat je {subject} {new_value} is."


def try_memory_update(command):
    """
    Expliciet bijwerken van onthouden info (Fase 5):
      "wijzig mijn favoriete kleur naar blauw"
      "verander X in Y", "corrigeer X naar Y", "pas X aan naar Y"
    """

    question = command.lower().strip()

    match = re.search(
        r"(?:wijzig|verander|corrigeer|pas aan)\s+"
        r"(?:mijn\s+)?(.+?)\s+(?:naar|in)\s+(.+)",
        question,
    )

    if not match:
        return None

    subject = match.group(1).strip(" .!?")
    new_value = match.group(2).strip(" .!?")

    if not subject or not new_value:
        return None

    return _memory_update_onderwerp(subject, new_value)


def _link_ha_alias(entity_ref, names):

    try:
        from core.ha_registry import add_user_alias
        return add_user_alias(entity_ref, names)
    except Exception:
        return False


_PRONOUNS = {"ik", "hij", "zij", "het", "we", "wij", "je", "jij", "u", "dat", "die"}

# Woorden waarmee een vraag begint. Zo'n zin is nooit een onthoud- of
# naamgeving-statement en mag dus nooit in het geheugen belanden.
_VRAAGWOORDEN = (
    "hoe", "wat", "welke", "welk", "wie", "waar", "wanneer", "hoeveel", "is",
)


def _is_vraagzin(tekst):
    """True als de zin een vraag is (vraagwoord vooraan of eindigt op '?')."""

    schoon = tekst.strip().lower()

    if schoon.endswith("?"):
        return True

    woorden = schoon.split()

    if not woorden:
        return False

    return woorden[0] in _VRAAGWOORDEN


def _is_bekend_apparaat(tekst):
    """True als de tekst een bestaand apparaat is (HA, geheugen of register)."""

    schoon = tekst.strip().lower().strip(" .!?")

    if not schoon:
        return False

    for woord in HA_DEVICE_WORDS:
        if re.search(rf"\b{re.escape(woord)}\b", schoon):
            return True

    try:
        from memory.memory import CATEGORY_KEYWORDS, get_category_memory

        for woord in CATEGORY_KEYWORDS.get("apparaten", ()):
            if re.search(rf"\b{re.escape(woord)}\b", schoon):
                return True

        for entry in get_category_memory("apparaten") or []:
            key = str(entry.get("key", "")).replace("_", " ").strip().lower()
            if key and re.search(rf"\b{re.escape(key)}\b", schoon):
                return True
    except Exception:
        pass

    try:
        for kandidaat in resolve_entities(schoon):
            # Alleen een echte naam/alias-match telt. Een los woord als "pc"
            # mag niet als bekend apparaat gelden puur omdat het fuzzy op
            # "Game-Pc" lijkt (token-overlap). Anders slaat een zin als
            # "mijn bureaubladachtergrond is mijn pc" onterecht iets op.
            if kandidaat.get("match") == "exact":
                return True
    except Exception:
        pass

    return False


def try_remember_device(command):
    """
    Herkent uitspraken waarin de gebruiker een slim apparaat een
    (bij)naam geeft (Fase 5):
      "de voordeur heet deurbel"
      "noem de ganglamp vanaf nu ganglicht"
      "deurbel is mijn voordeur"

    Slaat de naam op in het geheugen (categorie 'apparaten') en, als
    het achterliggende apparaat een HA-entity is, ook als HA-alias.
    """

    question = command.lower().strip().strip(" .!?")

    # Een vraag ("hoe warm is mijn cpu") is nooit een naamgeving-statement.
    if _is_vraagzin(question):
        return None

    nick = None
    ref = None
    wording = None

    # 1. "<apparaat> heet <naam>"  (hoek: label 'heet')
    match = re.search(r"(.+?)\s+heet\s+(.+)", question)

    if match:
        candidate = match.group(1).strip()

        if candidate.lower() not in _PRONOUNS and len(candidate) >= 3:
            ref = candidate
            nick = match.group(2).strip(" .!?")
            wording = "heet"

    # 2. "<naam> is mijn <apparaat>" (de korte naam voorop)
    if nick is None:
        match = re.search(r"^(.+?)\s+is\s+mijn\s+(.+)$", question)

        if match:
            nick = match.group(1).strip(" .!?")
            ref = match.group(2).strip(" .!?")
            wording = "is mijn"

    # 3. "noem <apparaat> (vanaf nu|voortaan) <naam>"
    if nick is None:
        match = re.search(
            r"noem\s+(.+?)\s+(?:vanaf nu|voortaan|van nu af aan|voortaan gewoon)\s+(.+)",
            question,
        )

        if match:
            ref = match.group(1).strip(" .!?")
            nick = match.group(2).strip(" .!?")
            wording = "heet"

    # 4. "vanaf nu noem ik <apparaat> <naam>" (naam = laatste woord)
    if nick is None:
        match = re.search(r"vanaf nu noem ik (?:de |mijn )?(.+?)\s+(\S+)$", question)

        if match:
            ref = match.group(1).strip(" .!?")
            nick = match.group(2).strip(" .!?")
            wording = "heet"

    if not nick or not ref:
        return None

    if nick.lower() in _PRONOUNS or ref.lower() in _PRONOUNS:
        return None

    # "<naam> is mijn <apparaat>": alleen opslaan als het tweede deel een
    # bestaand apparaat is. Anders zou een vraag als "hoe warm is mijn cpu"
    # als geheugen belanden.
    if wording == "is mijn" and not _is_bekend_apparaat(ref):
        return None

    remember(nick, ref, category="apparaten", source="conversation")

    ha_note = ""

    # Als het achterliggende apparaat een HA-entity is, koppel de naam.
    domain, _, _tail = ref.partition(".")

    if domain.isalnum() and "." in ref:
        ha_note = " en gekoppeld aan Home Assistant" if _link_ha_alias(ref, [nick]) else ""

    if wording == "heet":
        return f"Oké, ik onthoud dat {ref} '{nick}' heet{ha_note}."

    if wording == "is mijn":
        return f"Oké, ik onthoud dat '{nick}' jouw {ref} is{ha_note}."

    return f"Oké, ik onthoud dat {ref} '{nick}' heet{ha_note}."


def try_list_devices(command):
    """
    "welke apparaten ken je" / "welke apparaatnamen heb je onthouden"
    -> lijst van onthouden apparaatnamen.
    """

    question = command.lower()

    if not any(phrase in question for phrase in [
        "welke apparaten ken je",
        "welke apparaatnamen",
        "welke apparaten weet je",
        "welke namen heb je voor apparaten",
        "welke apparaten heb je onthouden",
        "welke apparaten weet jij",
    ]):
        return None

    items = get_category_memory("apparaten")

    if not items:
        return "Ik heb nog geen apparaatnamen onthouden. Zeg bijvoorbeeld 'de voordeur heet deurbel'."

    lines = [f"- {beautify(nick)} = {beautify(ref)}" for nick, ref in items.items()]

    return "Onthouden apparaatnamen:\n" + "\n".join(lines)


def try_project_query(command):
    """
    "wat is de deadline van project X" / "hoe gaat het met project X"
    gecombineerde status + deadline uit het geheugen halen (Fase 5).
    """

    question = command.lower()

    if not any(word in question for word in ["deadline", "project"]):
        return None

    match = re.search(r"(?:wat is|wat was|wanneer is)\s+(?:de\s+)?deadline\s+(?:van\s+|voor\s+)?(.+?)[?]?$", question)

    if not match:
        match = re.search(r"(?:hoe gaat het met|hoe gaat het met project|wat is de status van)\s+(?:project\s+)?(.+?)[?]?$", question)

    if not match:
        return None

    name = match.group(1).strip().strip(" .!?")

    if name.lower() in ("mijn projecten", "je projecten", "alle"):
        return None

    memory = get_all_memory()

    deadline = memory.get(f"project_deadline_{name}")
    status = memory.get(f"project_status_{name}")

    base = memory.get("project")

    parts = []

    pretty = beauty_proper_noun(name)

    if deadline:
        touch_usage(f"project_deadline_{name}")
        parts.append(f"de deadline van '{pretty}' is {beautify(deadline)}")

    if status:
        touch_usage(f"project_status_{name}")
        parts.append(f"het project is {beautify(status)}")

    if not parts and base and (name.lower() in str(base).lower() or str(base).lower() in name.lower()):
        touch_usage("project")
        return f"Je project is {beautify(base)}, maar ik ken er geen deadline of status van."

    if not parts:
        return None

    return (" en ".join(parts)) + "."


def beauty_proper_noun(name):

    return name.replace("_", " ").strip()


def try_remember(command):

    if not any(word in command for word in ["onthoud", "bewaar"]):
        return None

    return remember_from_question(command)


def auto_remember(command):

    question = command.lower()

    # Een vraag is nooit een onthoud-opdracht.
    if _is_vraagzin(question):
        return None

    # "mijn favoriete X is Y"
    match = re.search(r"mijn favoriete ([a-z]+) is (.+)", question)
    if match:
        name = match.group(1).strip()
        value = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(f"favoriete_{name}", value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je favoriete {name} {value} is."

    # "mijn lievelings X is Y"
    match = re.search(r"mijn lievelings ([a-z]+) is (.+)", question)
    if match:
        name = match.group(1).strip()
        value = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(f"lievelings_{name}", value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je lievelings-{name} {value} is."

    # PC-specificaties: "mijn gpu is X"
    match = re.search(
        r"mijn (gpu|grafische kaart|videokaart|ram|geheugen|cpu|processor|ssd|scherm|monitor) is (.+)",
        question
    )
    if match:
        name = match.group(1).strip()
        value = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(name, value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je {name} {value} is."

    # "mijn naam is X" / "ik heet X"
    match = re.search(r"(?:mijn naam is|ik heet) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        conflict = _remember_or_ask("naam", value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je naam {value} is."

    # "mijn leeftijd is X" / "ik ben X jaar"
    match = re.search(r"(?:mijn leeftijd is|ik ben) (\d+) jaar", question)
    if match:
        value = match.group(1)
        conflict = _remember_or_ask("leeftijd", value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je leeftijd {value} jaar is."

    # "mijn woonplaats is X" / "ik woon in X"
    match = re.search(r"(?:mijn woonplaats is|ik woon in|ik woon te) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        conflict = _remember_or_ask("woonplaats", value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je woonplaats {value} is."

    # "mijn project is X" / "ik werk aan X"
    match = re.search(r"(?:mijn project is|ik werk aan) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        conflict = _remember_or_ask("project", value)
        if conflict:
            return conflict
        return f"Ik onthoud dat je project {value} is."

    # Fase 5: project-deadline  ("deadline van X is Y")
    match = re.search(
        r"deadline (?:van|voor|voor mijn) (?:mijn )?(?:project )?(.+?)(?: is|:)\s+(.+)",
        question,
    )
    if match:
        name = match.group(1).strip(" .!?")
        deadline = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(f"project_deadline_{name}", deadline, category="projecten")
        if conflict:
            return conflict
        return f"Ik onthoud dat de deadline van project {name} {deadline} is."

    # "project X heeft deadline Y"
    match = re.search(r"project (.+?) heeft (?:een )?deadline (?:van )?(.+)", question)
    if match:
        name = match.group(1).strip(" .!?")
        deadline = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(f"project_deadline_{name}", deadline, category="projecten")
        if conflict:
            return conflict
        return f"Ik onthoud dat de deadline van project {name} {deadline} is."

    # "project X is (bijna) klaar / afgerond / in uitvoering"
    match = re.search(r"project (.+?) is (bijna klaar|klaar|afgerond|af|in uitvoering)", question)
    if match:
        name = match.group(1).strip(" .!?")
        status = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(f"project_status_{name}", status, category="projecten")
        if conflict:
            return conflict
        return f"Ik onthoud dat project {name} {status} is."

    # "het project is bijna klaar" -> status van het hoofdproject
    match = re.search(r"het project is (bijna klaar|klaar|afgerond|af|in uitvoering)", question)
    if match:
        status = match.group(1).strip(" .!?")
        conflict = _remember_or_ask("project_status_project", status, category="projecten")
        if conflict:
            return conflict
        return f"Ik onthoud dat je project {status} is."

    # "'X' is bijna klaar / afgerond" met één woord als naam
    match = re.search(r"^(\w+)\s+is\s+(bijna klaar|afgerond|in uitvoering)\s*\.?$", question)
    if match:
        name = match.group(1).strip()
        status = match.group(2).strip()
        conflict = _remember_or_ask(f"project_status_{name}", status, category="projecten")
        if conflict:
            return conflict
        return f"Ik onthoud dat project {name} {status} is."

    # "ik moet X af hebben voor/op Y" → deadline
    match = re.search(r"moet (.+?) af (?:hebben )?(?:voor|op) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        deadline = match.group(2).strip(" .!?")
        conflict = _remember_or_ask(f"project_deadline_{value}", deadline, category="projecten")
        if conflict:
            return conflict
        return f"Ik onthoud dat je {value} af moet hebben voor {deadline}."

    # Fase 5: voorkeuren uit losse zinnen
    #   "ik hou meestal van warm wit licht" -> lichtvoorkeur
    preference = extract_preference(question)

    if preference:
        key, value, category = preference
        return _store_preference(key, value, category)

    return None


def get_context_answer(command):

    question = command.lower()

    # -------------------------------------------------
    # GEHEUGEN: "wat is mijn <onderwerp>?" (Fase 4)
    # -------------------------------------------------

    memory_match = re.search(r"wat (?:is|zijn) mijn ([a-z ]+?)[?]?$", question)

    if memory_match:

        topic = memory_match.group(1).strip()
        topic_key = topic.replace(" ", "_")

        memory = get_all_memory()

        for key, value in memory.items():
            if key == topic_key or topic_key in key or key in topic_key:
                touch_usage(key)
                return f"Je {topic} is {beautify(value)}."

    # -------------------------------------------------
    # GEHEUGEN PER CATEGORIE: "wat weet je over mijn pc?"
    # -------------------------------------------------

    category_match = re.search(r"over mijn (pc|computer|voorkeuren|projecten|muziek)", question)

    if category_match:

        category_map = {
            "pc": "pc",
            "computer": "pc",
            "voorkeuren": "voorkeuren",
            "projecten": "projecten",
            "muziek": "muziek",
        }

        category = category_map[category_match.group(1)]
        items = get_category_memory(category)

        if items:

            parts = [f"je {key.replace('_', ' ')} is {beautify(value)}" for key, value in items.items()]

            if len(parts) == 1:
                return f"Ik weet dat {parts[0]}."

            return "Ik weet dat " + ", ".join(parts[:-1]) + " en " + parts[-1] + "."

        return f"Ik weet nog niets over je {category_match.group(1)}."

    # -------------------------------------------------
    # WAT WEET JARVIS OVER DE GEBRUIKER? (Fase 4)
    # -------------------------------------------------

    if any(word in question for word in [
        "wat weet je over mij",
        "wat ken je van mij",
        "wat weet je van mij",
        "wat staat er in je geheugen",
        "wat heb je onthouden",
    ]):
        memory = get_all_memory()

        if memory:

            parts = [f"je {key.replace('_', ' ')} is {beautify(value)}" for key, value in memory.items()]

            if len(parts) == 1:
                return f"Ik weet dat {parts[0]}."

            return "Ik weet dat " + ", ".join(parts[:-1]) + " en " + parts[-1] + "."

        return "Ik weet nog niets over je."

    # -------------------------------------------------
    # HELP: wat kan JARVIS?
    # -------------------------------------------------

    if any(word in question for word in [
        "wat kun je",
        "wat kan je",
        "wat kan ik vragen",
        "wat kun jij",
        "help",
        "help mij",
    ]):
        return (
            "Ik kan programma's openen en sluiten (bijvoorbeeld "
            "'open Discord' of 'sluit Spotify'), websites openen, "
            "bestanden openen, dingen onthouden ('onthoud dat mijn "
            "favoriete game Spider-Man is') en later ophalen, rekenen, "
            "de tijd en datum vertellen, en gewoon een gesprek met je voeren. "
            "Ook muziek kan ik bedienen: 'pauzeer', 'volgende', 'zet "
            "volume op 30' of 'harder'. En ik kan je pc uitlezen: "
            "'wat is mijn cpu', 'hoeveel ram heb ik', 'welke videokaart', "
            "'hoeveel ruimte' of 'systeeminformatie'. Vensters kan ik "
            "ook aanpassen: 'minimaliseer Discord' of 'vergroot Spotify'. "
            "En ik kan een screenshot van je scherm maken. Ook met je "
            "bestanden kan ik helpen: 'maak een map', 'welke bestanden "
            "zitten in downloads', 'kopieer' of 'verplaats'. En ik kan je "
            "pc bedienen: 'vergrendel de pc', 'slaapstand', 'herstart' "
            "of 'sluit de pc af' (altijd met bevestiging)."
        )

    if any(word in question for word in [
        "laatste programma",
        "laatst geopende programma",
        "laatst gestart",
        "welk programma",
        "wat heb ik net geopend",
        "wat heb ik zojuist geopend",
        "wat heb ik net gestart",
        "wat heb ik zojuist gestart",
    ]):
        if current_context["last_program"]:
            return f"Je laatst geopende programma is {current_context['last_program'].strip().capitalize()}."

        if current_context["last_file"]:
            return f"Het laatste bestand dat je hebt geopend is {current_context['last_file']}."

        if current_context["last_website"]:
            return f"De laatste website die je hebt geopend is {current_context['last_website']}."

        return "Ik heb nog niets geopend."

    if any(word in question for word in [
        "wat heb je net gedaan",
        "wat heb je zojuist gedaan",
        "wat deed je net",
        "wat was je laatste actie",
        "wat was de laatste actie",
    ]):
        if current_context["last_program"] and "geopend" in current_context["last_action"]:
            return f"Je hebt {current_context['last_program'].strip().capitalize()} geopend."

        if current_context["last_program"] and "gesloten" in current_context["last_action"]:
            return f"Je hebt {current_context['last_program'].strip().capitalize()} gesloten."

        if current_context["last_file"]:
            return f"Je hebt {current_context['last_file']} geopend."

        if current_context["last_website"]:
            return f"Je hebt {current_context['last_website']} geopend."

        if current_context["last_calculation"]:
            return f"Je laatste opdracht was een berekening: {current_context['last_calculation']}."

        if current_context["last_result"]:
            return f"Dat was: {current_context['last_result']}."

        return "Ik heb nog niets gedaan."

    if any(word in question for word in [
        "laatste berekening",
        "de berekening was",
        "vorige berekening",
    ]):
        if current_context["last_calculation"]:
            return f"De laatste berekening was {current_context['last_calculation']}."

        return "Er is nog geen berekening geweest."

    return None


def memory_suggestion(command):

    question = command.lower()

    # "open een game" / "ik wil gamen" / "wat moet ik spelen"
    if any(word in question for word in [
        "een game",
        "een spel",
        "wil gamen",
        "zin in een game",
        "zin in een spel",
        "wat moet ik spelen",
    ]):
        favorite_game = get_all_memory().get("favoriete_game")

        if favorite_game:
            touch_usage("favoriete_game")
            return f"Je favoriete game is {beautify(favorite_game)}. Zal ik die voor je openen?"

        return None

    # "speel muziek" / "zet muziek aan"
    if "muziek" in question:
        music = get_category_memory("muziek")

        if music:
            first_key, first_value = next(iter(music.items()))
            touch_usage(first_key)
            return f"Je favoriete {first_key.replace('_', ' ')} is {beautify(first_value)}. Zal ik die voor je afspelen?"

        return None

    return None


def try_forget(command):

    question = command.lower()

    if not any(word in question for word in [
        "vergeet", "verwijder", "gooi weg", "haal weg", "wis"
    ]):
        return None

    forget_words = {
        "vergeet", "verwijder", "vergeet", "gooi", "weg", "haal",
        "mijn", "over", "uit", "het", "de", "dat", "van", "even",
        "graag", "alsjeblieft", "aub", "nu",
    }

    tokens = [token.strip(".,!?") for token in question.split() if token.strip(".,!?")]

    topic = " ".join(token for token in tokens if token not in forget_words).strip()

    if not topic:
        return None

    # "vergeet alles" → geheugen leegmaken
    if topic in ("alles", "mijn geheugen", "al mijn info", "al mijn gegevens"):
        clear_memory()
        return "Ik heb mijn geheugen gewist."

    return _memory_forget_onderwerp(topic)


def _memory_forget_onderwerp(subject, category=None, opgeloste_sleutel=False):
    """
    Verwijdert één geheugenfeit, met dezelfde sleutelresolutie als een
    update.

    Nooit stilzwijgend op een gok: "vergeet band" verwijdert niet
    "fav band". Bij één fuzzy kandidaat wordt eerst bevestigd, bij
    meerdere wordt de keuze aan de gebruiker gelaten.
    """

    if not subject:
        return None

    if opgeloste_sleutel:
        return (f"Ik heb {str(subject).replace('_', ' ')} vergeten."
                if forget(subject)
                else None)

    key = str(subject).replace(" ", "_")

    oplossing = resolve_existing_key(key, category)

    if oplossing["status"] == "fuzzy":
        oplossing = dict(oplossing)
        oplossing["query"] = subject

        return _sleutelbevestiging(oplossing, {
            "operation": "forget",
            "query": subject,
            "category": category,
        })

    stored = oplossing["key"]

    if forget(stored):
        return f"Ik heb {str(stored).replace('_', ' ')} vergeten."

    return None


def _resolve_pending_choice(pending, chosen):

    kind = pending.get("kind", "list")

    if kind == "copy":
        return copy_path(chosen, pending["destination"])

    if kind == "move":
        return move_path(chosen, pending["destination"])

    if kind == "delete_choose":
        return send_to_recycle(chosen)

    if kind == "file_choice":
        return open_path(chosen)

    return list_folder_by_path(chosen)


YES_WORDS = [
    "ja", "jep", "jup", "jawel", "ja hoor", "ja doe maar", "ja doe het",
    "doe maar", "doe het", "doe maar hoor", "ga door", "ga je gang",
    "prima", "goed", "oke", "ok", "oké", "okee", "klopt",
    "bevestig", "bevestigen", "tuurlijk", "natuurlijk", "jazeker",
    "yep", "yes", "ja graag", "doen", "doe het maar",
]


NO_WORDS = [
    "nee", "nope", "niet doen", "doe maar niet", "laat maar",
    "laat maar zitten", "niet", "stop", "annuleer", "cancel",
    "nee hoor", "geen prullenbak", "liever niet", "stoppen",
]


POWER_ACTIONS = {
    "lock": lock_pc,
    "sleep": sleep_pc,
    "shutdown": shutdown_pc,
    "restart": restart_pc,
    "logoff": logoff_pc,
}


def detect_power_action(question):
    """Detecteer een power-actie uit de vraag (zonder pending)."""

    vraag = (question or "").lower().strip()

    has_pc_word = any(word in vraag for word in PC_WORDS)

    # Vergrendelen
    if any(word in vraag for word in [
        "vergrendel", "vergrendelen", "op slot", "lock de pc", "lock pc",
    ]):
        return "lock"

    # Slaapstand
    if any(word in vraag for word in [
        "slaapstand", "in slaap zetten", "naar de slaap", "sluimerstand", "hibernate", "hiberneer",
    ]) or ("slaap" in vraag and has_pc_word):
        return "sleep"

    # Afmelden / uitloggen
    if any(word in vraag for word in ["log uit", "afmelden", "uitloggen", "logoff"]):
        return "logoff"

    # Herstarten
    if has_pc_word and any(word in vraag for word in ["herstart", "herstarten", "reboot", "opnieuw opstarten"]):
        return "restart"

    # Afsluiten
    if has_pc_word and (
        any(word in vraag for word in ["afsluiten", "shutdown", "uitzetten", "uit zetten"])
        or re.search(r"(?:sluit|zet)\s+(?:de\s+|mijn\s+|je\s+)?(?:pc|computer|laptop|systeem)\s+(?:af|uit)\b", vraag)
        or re.search(r"(?:pc|computer|laptop|systeem)\s+(?:uit|af)\b", vraag)
    ):
        return "shutdown"

    return None


def _log_approval_uitkomst(pending, reden, goedgekeurd=False):
    """Logt een goedkeuring die NIET tot uitvoering leidde.

    Dekt geweigerde en geannuleerde tool-goedkeuringen zodat het
    auditlog ook de afgebroken acties laat zien (goedgekeurd=False met
    een reden).
    """
    if not pending or pending.get("kind") != "tool_approval":
        return
    try:
        from core.audit import log_audit

        log_audit(
            gehoord=pending.get("question", ""),
            handler=pending.get("source") or "onbekend",
            tool=pending.get("tool_name") or "",
            argumenten=pending.get("arguments") or {},
            risico=pending.get("risk") or "medium",
            resultaat=reden,
            goedgekeurd=goedgekeurd,
            reden=reden,
            herkomst=pending.get("herkomst"),
        )
    except Exception:
        pass


AL_AFGEHANDELD = "Die vraag is al afgehandeld."


def voer_besluit_uit(pending, goedgekeurd):
    """Voert een ja/nee-besluit uit op een al overgenomen pending.

    De aanroeper heeft de pending eerst met ``claim_pending()`` (stem) of
    ``claim_voor_besluit()`` (dashboard) overgenomen; daardoor kan
    dezelfde actie nooit twee keer worden uitgevoerd. De herkomst staat
    in ``pending["herkomst"]`` en komt zo in de auditregel.
    """

    kind = pending.get("kind")

    if goedgekeurd:

        if kind == "tool_approval":
            # Een bewaakte tool-aanroep (medium/high) is goedgekeurd:
            # voer hem uit en hervat een eventueel gepauzeerd plan.
            return resume_approved_plan(pending, approved=True)

        if kind == "file_open_confirm":
            # De gebruiker bevestigt een gevaarlijk bestandstype.
            # De pending-payload heeft het pad al vastgelegd.
            payload = pending.get("payload") or pending
            return open_confirmed(payload.get("path"))

        if kind == "prijs_confirm":
            # 'ja' op "Wil je dat ik de prijs van X opzoek?": nu pas
            # gaat de zoekopdracht naar DuckDuckGo.
            payload = pending.get("payload") or pending
            product = payload.get("product") or ""
            if not product:
                return "Ik weet niet meer welk product je bedoelde. Vraag het me nog eens."
            from core.externe_bronnen import zoek_product_prijs

            vraag = pending.get("question") or f"wat kost {product}"
            return zoek_product_prijs(product, vraag)

        if kind == "opzoeken_confirm":
            # 'ja' op "Wil je dat ik het opzoek?": nu pas gaat de
            # zoekopdracht naar buiten, met de oorspronkelijke vraag.
            # Het antwoord noemt de bron (titel en URL).
            from core import opzoeken

            payload = pending.get("payload") or pending
            return opzoeken.zoek_op(payload.get("vraag") or "")

        if kind == "memory_key_confirm":
            # 'ja' op "Bedoelde je X?" — de voorgestelde sleutel is
            # degene die de gebruiker bedoelde.
            payload = pending.get("payload") or pending
            return _hervat_sleutelbevestiging(payload, bevestigd=True)
        if kind == "delete_confirm":
            payload = pending.get("payload") or pending
            try:
                doel = pending.get("target") or payload.get("target")
                if doel == pc_target.GAME_PC:
                    return execute_tool("game_pc_recycle_file", {"filename": payload.get("name") or ""}, pending.get("question") or "")
            except Exception:
                pass
            return send_to_recycle(payload["matches"][0])

        if kind == "empty_confirm":
            payload = pending.get("payload") or pending
            try:
                doel = pending.get("target") or payload.get("target")
                if doel == pc_target.GAME_PC:
                    return execute_tool("game_pc_empty_recycle_bin", {}, pending.get("question") or "")
            except Exception:
                pass
            return empty_recycle_bin()

        if kind == "memory_update":
            payload = pending.get("payload") or pending
            memory_category = payload.get("memory_category") or None

            # Een batch-import handelt zijn eigen conflict af (via
            # de bestaande resolve_conflict) en gaat daarna door
            # met de volgende notities. Ik los het conflict dus
            # NIET twee keer op: precies één plek doet het werk.
            if payload.get("vault_batch"):
                return _hervat_vault_batch(payload, keep_old=False)

            # Een export-afspraak raakt het GEHEUGEN niet. 'ja'
            # herschrijft alleen de notitie; daarom wordt
            # resolve_conflict() hier bewust overgeslagen.
            if payload.get("vault_export"):
                return _hervat_vault_export(payload, overwrite=True)

            # Bevestigd: de nieuwe waarde wordt de actuele waarde.
            # resolve_conflict() zet de oude waarde in previous_value
            # en wist de conflict-markering.
            resolve_conflict(
                payload["memory_key"],
                payload["memory_value"],
                keep_old=False,
                category=memory_category,
            )

            # Komt de waarde uit de vault, dan zeg ik dat erbij: dan is
            # duidelijk waarom dit feit ineens veranderd is.
            if payload.get("from_vault"):
                return (
                    f"Oké, ik heb je "
                    f"{payload['memory_key'].replace('_', ' ')} uit je "
                    f"vault aangepast naar '{payload['memory_value']}'. "
                    "Je oude waarde heb ik bewaard."
                )

            return (
                f"Oké, ik heb je {payload['memory_key'].replace('_', ' ')} "
                f"aangepast naar '{payload['memory_value']}'."
            )

        if kind == "scene_save_suggest":
            payload = pending.get("payload") or pending
            steps = payload.get("steps") or []
            cmd = payload.get("last_command", "")
            # Genereer automatische naam
            name = _generate_scene_name(cmd)
            get_scene_manager().save_scene(
                name, steps,
                description=f"Aangemaakt na multi-actie ({len(steps)} stappen).",
            )
            return f"Scene '{name}' is opgeslagen ({len(steps)} acties)."

        if kind == "update_confirm":
            # Fase 19, M6: JARVIS bijwerken (backup, fast-forward, herstart).
            from beheer import updates

            return updates.voer_uit_na_goedkeuring()

        payload = pending.get("payload") or pending
        actie = payload.get("action")
        doel = pending.get("target") or payload.get("target")
        if actie and doel == pc_target.GAME_PC:
            try:
                from core.ai import _dispatch_tool
                vraag = pending.get("question") or ""
                return _dispatch_tool("game_pc_power", {"action": actie}, vraag)
            except Exception:
                pass
        if actie:
            return POWER_ACTIONS[actie]()
        return "Oké, ik doe het niet."

    else:

        if kind == "tool_approval":
            # Afgewezen: de actie wordt overgeslagen en gemeld.
            _log_approval_uitkomst(pending, "goedkeuring geweigerd door de gebruiker")
            return resume_approved_plan(pending, approved=False)

        if kind == "file_open_confirm":
            return "Oké, ik open dat bestand niet."

        if kind == "update_confirm":
            return "Oké, ik installeer de update niet. Zeg het maar als het wel mag."

        if kind == "prijs_confirm":
            return "Oké, ik zoek geen prijs op."

        if kind == "memory_key_confirm":
            # 'nee' op "Bedoelde je X?" — dan geldt de sleutel die
            # de gebruiker zelf zei.
            payload = pending.get("payload") or pending
            return _hervat_sleutelbevestiging(payload, bevestigd=False)

        if kind == "memory_update":
            payload = pending.get("payload") or pending
            # Een batch-import handelt zijn eigen conflict af en
            # hervat daarna; zie hierboven.
            if payload.get("vault_batch"):
                return _hervat_vault_batch(payload, keep_old=True)

            # Een export-afspraak: 'nee' betekent dat de notitie
            # precies blijft zoals hij is. Ook hier geen
            # resolve_conflict(): het geheugen verandert niet.
            if payload.get("vault_export"):
                return _hervat_vault_export(payload, overwrite=False)

            # Afgewezen: de oude waarde blijft actueel. Het conflict
            # wordt als afgehandeld vastgelegd, met de afgewezen
            # waarde ernaast, zodat je niet steeds opnieuw gevraagd
            # wordt om exact hetzelfde feit.
            resolve_conflict(
                payload["memory_key"],
                payload["memory_value"],
                keep_old=True,
                category=payload.get("memory_category") or None,
            )

            if payload.get("from_vault"):
                return (
                    "Oké, ik laat je geheugen zoals het is; de notitie "
                    "in je vault heb ik niet overgenomen."
                )

            return "Oké, ik laat je geheugen zoals het is."

        if kind == "scene_save_suggest":
            return "Oké, ik sla niets op."

        if kind == "opzoeken_confirm":
            return "Oké, dan laat ik het."

        return "Oké, ik doe het niet."


def handle_pending_choice(command):

    pending = get_pending()

    if not pending:
        return None

    question = command.lower().strip()

    kind = pending.get("kind")

    # Bevestiging: "ja" / "nee"
    if kind in JA_NEE_KINDS:

        result = evaluate_answer(question, kind)

        if result in ("yes", "no"):

            # In één stap overnemen: heeft het dashboard (of een eerdere
            # beurt) de vraag al afgehandeld, dan gebeurt er niets meer.
            if not claim_pending(pending, herkomst="stem"):
                return AL_AFGEHANDELD

            return voer_besluit_uit(pending, goedgekeurd=(result == "yes"))

        if result == "unclear":
            return get_reask_prompt(kind)

        if result == "cancel":
            if kind == "tool_approval":
                _log_approval_uitkomst(pending, "goedkeuring geannuleerd")
            clear_pending()
            return None

    matches = pending.get("matches", [])

    chosen = None

    # Nummer: "1", "2", "3"
    number_match = re.fullmatch(r"(\d{1,2})", question)

    if number_match:

        index = int(number_match.group(1)) - 1

        if 0 <= index < len(matches):
            chosen = matches[index]

    # Woorden: "de eerste", "tweede"
    if chosen is None:

        for index, word in enumerate(["eerste", "tweede", "derde", "vierde", "vijfde"]):

            if word in question:

                if index < len(matches):
                    chosen = matches[index]
                break

    # Locatie: "desktop", "bureaublad", "pictures", "downloads", "documenten"
    if chosen is None:

        location = resolve_location(question)

        if location:

            for path in matches:

                if path.lower().startswith(location.lower()):
                    chosen = path
                    break

    if chosen is not None:
        update_context(pending_choice=None)
        return _resolve_pending_choice(pending, chosen)

    # Het antwoord leek een keuze te zijn maar was ongeldig?
    if number_match:
        return f"Die keuze ken ik niet. Geef een nummer van 1 tot {len(matches)}."

    if find_location_word(question):
        return "Die plek zit er niet bij. Probeer een andere plek of geef een nummer."

    if any(word in question for word in ["eerste", "tweede", "derde", "vierde", "vijfde"]):
        return "Die keuze ken ik niet."

    # Helemaal geen keuze: gewoon doorlopen met de normale verwerking
    return None


PC_WORDS = ["pc", "computer", "laptop", "systeem"]


def try_power_command(command):

    question = command.lower().strip()

    # Annuleren van lopende shutdown/restart (shutdown /a)
    if "annuleer" in question and any(word in question for word in ["afsluiten", "herstart", "herstarten", "shutdown"]):
        if pc_target.is_remote(command):
            return execute_tool(
                pc_target.remote_twin("cancel_shutdown"),
                {"action": "cancel"},
                command,
            )
        return cancel_shutdown()

    action = detect_power_action(question)
    if not action:
        return None

    if pc_target.is_remote(command):
        return execute_tool("game_pc_power", {"action": action}, command)

    labels = {
        "lock": "de pc vergrendelen",
        "sleep": "de pc in slaapstand zetten",
        "shutdown": "de pc afsluiten",
        "restart": "de pc herstarten",
        "logoff": "je afmelden",
    }

    set_pending("power_confirm", {"action": action, "target": pc_target.resolve_target(command), "question": command})

    annuleren_toevoeging = ""
    if action in ("shutdown", "restart"):
        annuleren_toevoeging = " Je kunt dit eventueel nog annuleren met 'annuleer afsluiten' of 'annuleer herstart'."

    return f"Zal ik {labels[action]}? Zeg 'ja' of 'nee'.{annuleren_toevoeging}"


# =========================================================
# ROUTINES (Fase 4 — JARVIS Routines / Modes)
#
# Herkent opgeslagen routines (bijv. "ik ga gamen") en voert
# de bijbehorende stappen uit via de Executor. Beheer-commando's
# voor het aanmaken, verwijderen en tonen van routines.
# =========================================================

ROUTINE_MANAGE_PATTERNS = [
    (r"(welke routine gebruik ik (het meest|vaakst|vaak)|meest gebruik\w*\s*routine)", "mostused"),
    (r"(welke|welk)\s+routin", "list"),
    (r"routines?\s*(tonen|lijst|overzicht|laten zien)", "list"),
    (r"wat\s*(zijn|heb je|kan je)\s*(mijn\s+|je\s+)?routin", "list"),
    (r"verwijder\s+routine\s+(\w+)", "delete"),
    (r"wis\s+routine\s+(\w+)", "delete"),
    (r"vergeet\s+routine\s+(\w+)", "delete"),
    # Opslaan — flexibel: "dit/deze/dat/deze acties" + optioneel
    # "een" en "genaamd"/"met de naam". De routinenaam is de laatste
    # regex-groep.
    (r"bewaar\s+(dit|deze|dat|deze acties|al deze acties)\s+als\s+(een\s+)?routine\s+(genaamd\s+|met de naam\s+)?(\w+)", "save"),
    (r"sla\s+(dit|deze|dat|deze acties)\s+op\s+als\s+(een\s+)?routine\s+(genaamd\s+|met de naam\s+)?(\w+)", "save"),
    (r"sla\s+op\s+als\s+(een\s+)?routine\s+(genaamd\s+|met de naam\s+)?(\w+)", "save"),
    (r"bewaar\s+als\s+(een\s+)?routine\s+(genaamd\s+|met de naam\s+)?(\w+)", "save"),
    (r"onthoud\s+dit\s+als\s+(een\s+)?routine\s+(genaamd\s+)?(\w+)", "save"),
    (r"maak\s+er\s+een\s+routine\s+van\s+(genaamd\s+)?(\w+)", "save"),
    (r"maak\s+hier\s+een\s+routine\s+van\s+(genaamd\s+)?(\w+)", "save"),
    (r"maak\s+een\s+routine\s+(genaamd\s+|met de naam\s+)?(\w+)", "save"),
]

# Vangnet: een zin die duidelijk om het opslaan van een routine
# vraagt, maar door geen specifiek patroon gevat wordt ("sla deze
# handelingen op als routine X"). Zonder vangnet zou de AI gaan raden.
# Het vangnet telt alleen als het woord "routine" in de zin voorkomt.
SAVE_INTENT_GUARD = re.compile(
    r"(opslaan\b|sla\b.*\bop\b|bewaar\b.*routine)",
    re.IGNORECASE,
)


def try_routine(command):
    """
    Verwerkt routine-gerelateerde opdrachten:
      - Routine-uitvoering: "ik ga gamen", "slapen", ...
      - Beheer: "welke routines", "verwijder routine gamen"

    Geeft een antwoord-string, of None als de opdracht niet over
    een routine gaat.
    """

    # --- Beheer-commando's ---
    for pattern, action in ROUTINE_MANAGE_PATTERNS:
        match = re.search(pattern, command)
        if match:
            return _handle_routine_management(command, action, match)

    # --- Routine-uitvoering ---
    name, routine = routine_manager.resolve(command)

    if routine:
        return _execute_routine(name, routine, command)

    # --- Vangnet voor opslaan-intentie ---
    # De zin vraagt duidelijk om iets als routine op te slaan, maar
    # geen patroon matchte. Zeg duidelijk wat JARVIS wel kan in plaats
    # van de AI te laten gokken. Alleen bij woorden die
    # opslaan-intentie combineren met "routine".
    if "routine" in command and SAVE_INTENT_GUARD.search(command):
        return (
            "Ik kon die zin niet omzetten naar een routine. "
            "Zeg bijvoorbeeld 'bewaar dit als routine gamen' "
            "of 'sla dit op als een routine genaamd gamen'."
        )

    return None


def _generate_scene_name(question):
    """Genereert een automatische scene-naam uit een opdracht."""

    question = question.lower().strip()

    # Verwijder actie-woorden
    cleaned = re.sub(
        r"\b(open|sluit|start|maak|doe|zet|schakel|activeer|"
        r"geef|stel|pauzeer|stop|vergroot|minimaliseer|"
        r"volume|harder|zachter|groen|rood|blauw|wit|warm|koel|"
        r"aan|uit|op)\b",
        "", question,
    )

    # Verwijder lidwoorden en stopwoorden
    cleaned = re.sub(r"\b(de|het|een|mijn|je|jouw|van|in|op|naar|voor|"
                     r"met|en|of|dan|dan|graag|even|alsjeblieft)\b", "", cleaned)

    cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
    words = [w.strip() for w in cleaned.split() if len(w.strip()) >= 2]

    if not words:
        return "multi_actie"

    name = "_".join(words[:3])

    # Zorg dat naam uniek is
    manager = get_scene_manager()
    base = name
    i = 2
    while manager.get_scene(name) is not None:
        name = f"{base}_{i}"
        i += 1

    return name


SCENE_MANAGE_PATTERNS = [
    (r"(welke|welk)\s+scene", "list"),
    (r"scene\w*s?\s*(tonen|lijst|overzicht|laten zien)", "list"),
    (r"wat\s*(zijn|heb je|kan je)\s*(mijn\s+|je\s+)?scene", "list"),
    (r"verwijder\s+scene\s+([a-z0-9_\- ]+)", "delete"),
    (r"wis\s+scene\s+([a-z0-9_\- ]+)", "delete"),
    (r"vergeet\s+scene\s+([a-z0-9_\- ]+)", "delete"),
]

# Vangnet: een zin die duidelijk om het opslaan van een scene vraagt,
# maar door geen specifiek patroon gevat wordt.
SCENE_SAVE_PATTERNS = [
    r"sla\s+(dit|deze|dat|deze acties|deze handelingen)\s+op\s+als\s+(een\s+)?scene",
    r"bewaar\s+(dit|deze|dat|deze acties)\s+als\s+(een\s+)?scene",
    r"maak\s+(er\s+|hier\s+)?(een\s+)?scene\s+van",
    r"onthoud\s+(dit|deze|dat)\s+als\s+(een\s+)?scene",
]


def try_scene(command):
    """
    Verwerkt scene-gerelateerde opdrachten:
      - Scene-activering: "zet filmmodus aan", "activeer scene filmmodus"
      - Beheer: "welke scenes", "verwijder scene filmmodus"
      - Opslaan: "sla dit op als scene filmmodus"

    Geeft een antwoord-string, of None als de opdracht niet over
    een scene gaat.
    """
    manager = get_scene_manager()

    # --- Beheer-commando's ---
    for pattern, action in SCENE_MANAGE_PATTERNS:
        match = re.search(pattern, command)
        if match:
            return _handle_scene_management(command, action, match)

    # --- Opslaan-intentie (vóór activering: "sla dit op als scene X") ---
    if any(re.search(p, command, re.IGNORECASE) for p in SCENE_SAVE_PATTERNS):
        return _save_last_run_as_scene(command)

    # --- Activering ("activeer scene", "zet <scene> aan") ---
    # Voorbeelden: "zet filmmodus aan", "activeer scene filmmodus",
    # "start scene avond", "doe filmmodus aan".
    if re.search(r"scene|scène", command) or re.search(
        r"\b(activeer|activ|start)\b", command
    ):
        name, scene = manager.resolve(command)
        if scene:
            return _execute_scene(name, scene, command)

    return None


def _handle_scene_management(command, action, match):
    """Verwerkt scene-beheercommando's (lijst, verwijderen, opslaan)."""
    manager = get_scene_manager()

    if action == "list":
        scenes = manager.list_scenes()
        if not scenes:
            return (
                "Er zijn nog geen scenes opgeslagen. Ik kan er een "
                "voorstellen na een actie, of je zegt bijvoorbeeld "
                "'sla dit op als scene filmmodus'."
            )
        lines = []
        for name, scene in sorted(scenes.items()):
            desc = scene.get("description", "")
            n = len(scene.get("steps", []) or [])
            lines.append(f"- {name} ({n} acties){': ' + desc if desc else ''}")
        return "Je scenes:\n" + "\n".join(lines)

    if action == "delete":
        name = None
        # Pak de laatst gevangen naamgroep (na evt. spaties)
        named = [g for g in match.groups() if g]
        if named:
            name = named[-1].strip().lower()

        if not name:
            return "Welke scene wil je verwijderen?"

        existed = manager.delete_scene(name)
        if existed:
            return f"Scene '{name}' is verwijderd."
        return f"Ik ken geen scene '{name}'."

    return None


def _save_last_run_as_scene(command):
    """
    Slaat de laatst uitgevoerde acties op als scene.

    Voorbeeld: "sla dit op als scene filmmodus" → de stappen van de
    laatste run worden opgeslagen als scene 'filmmodus'.
    """
    m = re.search(r"scene\s+(?:genaamd\s+|met de naam\s+)?([a-z0-9_\- ]+)", command)
    target = m.group(1).strip().lower() if m else ""

    # Laatste woord-optie: "sla dit op als scene" zonder naam
    if not target:
        return (
            "Geef de scene een naam, bijvoorbeeld "
            "'sla dit op als scene filmmodus'."
        )

    steps = list(get_last_done_actions())

    if not steps:
        return (
            "Ik heb geen recente acties om als scene op te slaan. "
            "Voer eerst een opdracht uit, bijvoorbeeld "
            "'zet de lamp aan en open de film'."
        )

    existed = get_scene_manager().get_scene(target) is not None

    if not any(
        s.get("tool_name") == "control_home_assistant"
        for s in steps
    ):
        return (
            f"Ik heb '{target}' niet als scene opgeslagen: de recente "
            "acties bevatten geen smart-home-stappen. Scenes zijn "
            "bedoeld voor HA-combinaties (bijv. licht + tv)."
        )

    get_scene_manager().save_scene(
        target,
        steps,
        description=f"Aangemaakt via stem ({len(steps)} acties).",
    )

    if existed:
        return f"Scene '{target}' is bijgewerkt ({len(steps)} acties)."
    return f"Scene '{target}' is opgeslagen ({len(steps)} acties)."


def _execute_scene(name, scene, command):
    """Voert een opgeslagen scene uit via de Executor."""
    steps = scene.get("steps") or []
    description = scene.get("description", "")

    # Een scene met "vertrouwd": true in ha_scenes.json slaat de
    # goedkeuringsvragen per stap over (net als bij routines).
    vertrouwd = bool(scene.get("vertrouwd", False))

    print(f"🎬 Scene '{name}' gestart ({len(steps)} stappen).")

    try:
        results = execute_action_plan(steps, f"scene: {name}", trusted=vertrouwd)
    except Exception as error:
        print(f"⚠️ Scene-fout: {error}")
        return f"Er ging iets mis bij het uitvoeren van scene '{name}'."

    done = [r for r in results if r.get("status") == "done"]
    failed = [r for r in results if r.get("status") == "failed"]

    answer = _summarize_scene(name, description, done, failed)

    update_context(
        last_command=command,
        last_result=answer,
        last_action=f"scene {name}",
    )

    return answer


def _summarize_scene(name, description, done, failed):
    """Bouwt een kort, eerlijk Nederlands antwoord voor een scene."""

    if not failed:
        return description if description else f"Scene '{name}' is uitgevoerd."

    failed_names = []
    for record in failed:
        tool = record.get("used_tool_name") or record.get("tool_name", "")
        arguments = record.get("arguments") or {}
        label = arguments.get("entity_id") or arguments.get("program") or tool
        failed_names.append(label)

    joined = ", ".join(failed_names) if failed_names else "een paar stappen"

    if done:
        return (
            f"Scene '{name}' gedeeltelijk uitgevoerd. "
            f"Mislukt: {joined}."
        )

    return f"Scene '{name}' mislukt: {joined}."


def _handle_routine_management(command, action, match):
    """Verwerkt beheer-commando's (lijst, verwijderen, opslaan)."""

    name_group = match.group(len(match.groups())) if match.groups() else ""

    if action == "list":
        routines = routine_manager.list_routines()
        if not routines:
            return "Er zijn nog geen routines opgeslagen."

        lines = []
        for name, routine in routines.items():
            desc = routine.get("description", "")
            n_steps = len(routine.get("steps", []))
            lines.append(f"- {name}: {desc} ({n_steps} stappen)")

        return "Je opgeslagen routines:\n" + "\n".join(lines)

    if action == "delete":
        target = name_group.strip().lower()
        if routine_manager.delete_routine(target):
            return f"Routine '{target}' is verwijderd."
        return f"Routine '{target}' bestaat niet. Zeg 'welke routines' om een overzicht te zien."

    if action == "mostused":
        ranking = routine_manager.most_used_routines()
        if not ranking:
            return "Er zijn nog geen routines opgeslagen."
        lines = []
        for count, last_used, name, description in ranking:
            when = f" (laatst op {last_used})" if last_used else ""
            lines.append(f"- {name}: {count}× gebruikt{when}")
        return "Je routines, van meest naar minst gebruikt:\n" + "\n".join(lines)

    if action == "save":
        return _save_last_run_as_routine(name_group)

    return None


def _save_last_run_as_routine(target):
    """
    Slaat de laatst uitgevoerde Agent-acties op als routine.

    Voorbeeld: "JARVIS, bewaar dit als routine gaming" → de stappen
    van de laatste run_goal() worden opgeslagen als routine 'gaming'.
    """

    target = target.strip().lower()

    if not target:
        return "Ik kon geen routinenaam horen. Zeg bijvoorbeeld 'bewaar dit als routine gamen'."

    # De laatst geslaagde acties komen in de eerste plaats uit het
    # Executor-journaal (dekt Agent-plannen, routines én LLM-toolcalls).
    steps = list(get_last_done_actions())

    if not steps:
        steps = list(getattr(agent, "last_executed_steps", None) or [])

    if not steps:
        return (
            "Ik heb geen recente acties om op te slaan. "
            "Voer eerst een opdracht uit, bijvoorbeeld "
            "'open spotify en zet het volume op 40'."
        )

    triggers = [
        f"\\b{target}\\b",
        f"ik ga {target}",
        f"start {target}",
        f"ik wil {target}",
    ]
    aliases = [target]
    description = f"Aangemaakt via stem ({len(steps)} acties)."

    existed = routine_manager.get_routine(target) is not None
    routine_manager.save_routine(target, triggers, steps, description, aliases)

    if existed:
        return f"Routine '{target}' is bijgewerkt met {len(steps)} acties."

    return (
        f"Routine '{target}' is opgeslagen met {len(steps)} acties. "
        f"Zeg 'ik ga {target}' om hem uit te voeren."
    )


def _execute_routine(name, routine, command):
    """
    Voert een opgeslagen routine uit via de Executor.
    Geeft een deterministisch antwoord terug.
    """

    steps = routine_manager.steps_for_agent(name)

    if not steps:
        return f"Routine '{name}' heeft geen stappen om uit te voeren."

    description = routine.get("description", name)
    print(f"🔄 Routine '{name}' gestart ({len(steps)} stappen).")

    # Een routine met "vertrouwd": true in routines.json slaat de
    # goedkeuringsvragen per stap over (de gebruiker vertrouwt hem).
    vertrouwd = bool(routine.get("vertrouwd", False))

    try:
        results = execute_action_plan(steps, f"routine: {name}", trusted=vertrouwd)
    except Exception as error:
        print(f"⚠️ Routine-fout: {error}")
        return f"Er ging iets mis bij het uitvoeren van routine '{name}'."

    try:
        routine_manager.track_usage(name)
    except Exception:
        pass

    done = [r for r in results if r.get("status") == "done"]
    failed = [r for r in results if r.get("status") == "failed"]

    answer = _summarize_routine(name, description, done, failed)

    update_context(
        last_command=command,
        last_result=answer,
        last_action=f"routine {name}",
    )

    return answer


# =========================================================
# OBSIDIAN-VAULT (Fase 14, Stap 4)
#
# Twee expliciete commando's, meer niet:
#
#   1. "wat heb ik in mijn vault staan"
#   2. "zet <notitie> in mijn geheugen"
#
# VOLLEDIG OP VRAAG. Er is geen watcher, geen timer en geen
# achtergrondproces. Onthouden in een gesprek schrijft NIET naar de
# vault, en een notitie die je in Obsidian maakt komt NIET vanzelf in
# het geheugen. De bestaande remember()-logica is niet aangeraakt.
#
# Conflicten lopen door de bestaande pending_choice-flow: het is
# letterlijk dezelfde 'memory_update'-bevestiging als bij onthouden in
# een gesprek, zodat een tegenstrijdige waarde nooit stilzwijgend
# wordt overschreven. 'Ja' past de vault-waarde toe (de oude blijft
# in previous_value bewaard), 'nee' laat het geheugen zoals het is.
#
# Wat dit bestand WEL doet: het leest de bestaande lagen,
#   memory/obsidian.py    -> Markdown op schijf
#   memory/vault_import.py -> de geheugenkant + conflictplan
# Er staat hier geen nieuwe geheugenlogica.
# =========================================================

# Woorden waarmee de gebruiker expliciet naar de vault vraagt.
VAULT_WORDS = [
    "vault", "obsidian",
]

# Werkwoorden voor het importeren van een notitie.
VAULT_IMPORT_WORDS = [
    "naar mijn geheugen", "in mijn geheugen", "in het geheugen",
    "naar het geheugen", "importeer", "zet over",
]

# Werkwoorden voor het EXPORTEREN van geheugen naar de vault. Deze
# lijst bewust anders opgebouwd dan de import-woorden: de
# richtingswoorden 'naar de vault' en 'in obsidian' kunnen niet
# samenvallen met 'naar mijn geheugen', dus er is geen kans dat een
# export-word een import-commando opstuikt.
VAULT_EXPORT_WORDS = [
    "exporteer", "migreer",
    "naar de vault", "naar obsidian",
    "naar mijn vault", "naar mijn obsidian",
    "in obsidian", "in de vault",
    "zet mijn geheugen", "schrijf mijn geheugen",
]

# Uitdrukkingen die de RICHTING van een vergelijking aangeven. Zonder
# deze regels zou "vergelijk mijn geheugen met de vault" (export) en
# "vergelijk mijn vault met mijn geheugen" (import) door elkaar
# worden gehaald: beide noemen een vault én een geheugen.
#
# De regel is bewust: komt de geheugen-uitdrukking VOOR de
# vault-uitdrukking, dan is de export de onderwerp.
VAULT_EXPORT_COMPARE_PHRASES = [
    "geheugen met de vault",
    "geheugen met obsidian",
    "geheugen met mijn vault",
    "geheugen met mijn obsidian",
]


def _vault_is_configured():
    """True als er een vault-pad bekend is (best hoeft nog niet te)."""

    return bool(obsidian_vault.get_vault_path())


def try_vault_info(command):
    """
    "Wat heb ik in mijn vault staan?" — alleen op expliciete vraag.

    Geeft None terug als de vraag niets met de vault te maken heeft,
    zodat de normale verwerking gewoon doorgaat.
    """

    question = command.lower()

    if not any(word in question for word in VAULT_WORDS):
        return None

    # Het import-commando is specifieker; die hoort bij try_vault_import.
    if any(word in question for word in VAULT_IMPORT_WORDS):
        return None

    # Er moet ook een vraagvorm zijn, anders is dit geen verzoek.
    if not any(word in question for word in [
        "wat", "welke", "welk", "hoeveel", "toon", "laat zien", "geef",
        "informatie", "status", "notities", "notitie", "inhoud",
    ]):
        return None

    vault = obsidian_vault.get_vault_path()

    if not obsidian_vault.vault_exists():
        return (
            f"Ik kan je vault niet vinden op '{vault}'. "
            "Kun je controleren of die map er nog is?"
        )

    notes = obsidian_vault.list_notes()

    if not notes:
        return (
            "Je vault is nog leeg. Ik vind nog geen notities. "
            "Maak er zelf een met Obsidian, dan kan ik ze voor je lezen."
        )

    memory_notes = vault_sync.plan_import_all()

    if not memory_notes:
        return (
            f"Ik zie {len(notes)} notitie(s) in je vault, maar geen daarvan "
            "is een memory-notitie. Ik kan ze wel voor je lezen."
        )

    nieuw = sum(1 for p in memory_notes if p["action"] == "new")
    onveranderd = sum(1 for p in memory_notes if p["action"] == "unchanged")
    conflict = sum(1 for p in memory_notes if p["action"] == "conflict")

    regels = [f"Je vault bevat {len(memory_notes)} memory-notitie(s):"]

    for plan in memory_notes[:8]:
        regels.append(f"- {plan['key']}: {plan['value']}")

    if len(memory_notes) > 8:
        regels.append(f"- en nog {len(memory_notes) - 8} andere")

    if conflict:
        regels.append(
            f"Let op: {conflict} daarvan wijken af van wat ik in je geheugen "
            "heb staan. Zeg bijvoorbeeld 'zet die notitie in mijn geheugen' "
            "en ik leg het verschil aan je voor."
        )
    else:
        regels.append(f"{nieuw} nieuw, {onveranderd} gelijk aan je geheugen.")

    return "\n".join(regels)


def _find_vault_note_by_name(zoekterm):
    """
    Zoekt de best passende vault-notitie bij een zoekterm.

    Vergelijkt de notitienaam en de memory-sleutel, zodat zowel
    'favoriete-kleur' als 'favoriete kleur' iets vinden.

    Geeft de notitienaam terug, of None als er geen notitie past of er
    er meer dan één even goed past (dan geven we niets zomaar gokken).
    """

    zoekterm = zoekterm.strip().lower()

    if not zoekterm:
        return None

    if not obsidian_vault.vault_exists():
        return None

    kandidaten = []

    for notitie in obsidian_vault.list_notes():
        stam = notitie.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        pad = notitie.rsplit("/", 1)[0] if "/" in notitie else ""
        volledig = notitie.rsplit(".", 1)[0]

        for vorm in (volledig, stam, pad):
            if zoekterm == vorm or zoekterm == vorm.replace("-", " "):
                kandidaten.append(notitie)
                break

        if notitie in kandidaten:
            continue

        for vorm in (stam, volledig):
            if zoekterm and zoekterm in vorm:
                kandidaten.append(notitie)
                break

    uniek = []
    for notitie in kandidaten:
        if notitie not in uniek:
            uniek.append(notitie)

    if len(uniek) == 1:
        return uniek[0]

    return None


def try_vault_import(command):
    """
    "Zet <notitie> in mijn geheugen" — alleen op expliciete vraag.

    Geeft None terug als de vraag geen import-verzoek is, zodat de
    normale verwerking gewoon doorgaat. Bij een conflict wordt de
    bestaande pending_choice-flow gebruikt; de waarde wordt pas na
    'ja' opgeslagen.
    """

    question = command.lower()

    if not any(word in question for word in VAULT_WORDS + ["geheugen", "notitie"]):
        return None

    if not any(word in question for word in VAULT_IMPORT_WORDS):
        return None

    vault = obsidian_vault.get_vault_path()

    if not obsidian_vault.vault_exists():
        return (
            f"Ik kan je vault niet vinden op '{vault}', dus ik kan niets "
            "importeren."
        )

    # Strips het verzoek eruit, zodat alleen de notitienaam overblijft.
    zoekterm = question

    for word in VAULT_IMPORT_WORDS:
        zoekterm = zoekterm.replace(word, " ")

    # Ook het kale werkwoord 'zet'. Zonder deze regel bleef 'zet' aan het
    # begin van de zoekterm plakken, waardoor de notitienaam nooit
    # meer volledig overkwam en het commando niets vond.
    for word in VAULT_WORDS + ["notitie", "notities", "mijn", "het",
                               "zet", "in"]:
        zoekterm = zoekterm.replace(word, " ")

    notitie = _find_vault_note_by_name(zoekterm)

    if notitie is None:
        return (
            "Ik kan geen notitie vinden die daarbij past. "
            "Geef de naam van de notitie, zoals 'zet voorkeuren/licht "
            "in mijn geheugen'."
        )

    uitkomst = vault_sync.import_note(notitie)

    if uitkomst["needs_confirm"]:
        token = uitkomst["confirm_token"]

        # Precies dezelfde bevestigingsvorm als bij onthouden in een
        # gesprek: memory_key/memory_value/memory_category.
        update_context(pending_choice={
            "kind": "memory_update",
            "memory_key": token["stored_key"],
            "memory_value": token["vault_value"],
            "memory_category": token.get("category"),
            "old_value": uitkomst.get("memory_value"),
            "from_vault": notitie,
        })

        return (
            f"Ik wist al dat je {token['stored_key'].replace('_', ' ')} "
            f"{uitkomst.get('memory_value')} is, in je vault staat "
            f"{uitkomst['value']}. Zal ik dat wijzigen? Zeg 'ja' of 'nee'."
        )

    if uitkomst["applied"]:
        return (
            f"Oké, ik heb '{uitkomst['key']}' uit je vault onthouden "
            f"als {uitkomst['value']}."
        )

    if uitkomst["action"] == "unchanged":
        return (
            f"Dat staat er al in je geheugen: '{uitkomst['key']}' "
            f"is {uitkomst['value']}."
        )

    return (
        f"Ik kon die notitie niet importeren: {uitkomst['reason'] or 'onbekend'}."
    )


def _describe_batch(state):
    """
    Vat de batch samen in gewone taal.

    Er is hier geen geheugenlogica: dit leest alleen de statusvelden
    die vault_import al heeft gevuld.
    """

    telling = state.get("count") or {}

    if state.get("error"):
        return (
            f"Ik ben gestopt: {state['error']}. "
            "Ik heb verder niets gedaan, dus je geheugen is niet "
            "halverwege in een raar standje achtergelaten."
        )

    if state.get("paused"):
        confirm = state.get("confirm") or {}

        return (
            f"Ik ben bij een tegenstrijdigheid gestopt: "
            f"{confirm.get('vault_value')} in de vault, maar "
            f"{confirm.get('memory_value')} in je geheugen."
        )

    if state.get("dry_run"):
        return (
            f"Dit zou ik doen met {telling.get('total', 0)} notitie(s): "
            f"{telling.get('new', 0)} nieuw, "
            f"{telling.get('conflict_planned', 0)} met een verschil, "
            f"{telling.get('unchanged', 0)} onveranderd. "
            "Ik heb nog niets weggeschreven."
        )

    stukjes = []

    for sleutel, label in [
        ("imported", "geïmporteerd"),
        ("new", "nieuw"),
        ("accepted", "gewijzigd met jouw 'ja'"),
        ("kept", "behouden na jouw 'nee'"),
        ("unchanged", "onveranderd"),
        ("planned", "gepland"),
        ("conflict_planned", "zou een conflict geven"),
        ("error", "mislukt"),
        ("duplicate", "al verwerkt"),
    ]:
        aantal = telling.get(sleutel, 0)

        if aantal:
            stukjes.append(f"{aantal} {label}")

    if not stukjes:
        return "Er was niets te doen."

    return f"{', '.join(stukjes)}."


def _describe_export(state):
    """
    Vat de export-batch samen in gewone taal.

    Er is hier geen geheugenlogica: dit leest alleen de statusvelden
    die vault_export al heeft gevuld.
    """

    telling = state.get("counts") or {}

    if state.get("error"):
        return (
            f"Ik ben gestopt: {state['error']}. "
            "Ik heb niets half afgemaakt; je geheugen is ongewijzigd "
            "en de resterende notities staan nog op de wachtrij."
        )

    if state.get("paused"):
        confirm = state.get("confirm") or {}

        return (
            f"Er is een verschil bij '{confirm.get('key')}': "
            f"je geheugen zegt '{confirm.get('memory_value')}', "
            f"de notitie in je vault zegt '{confirm.get('vault_value')}'."
        )

    if state.get("dry_run"):
        return (
            f"Dit zou ik doen met {telling.get('total', 0)} notitie(s): "
            f"{telling.get('planned', 0)} nieuw, "
            f"{telling.get('drift_planned', 0)} met een verschil, "
            f"{telling.get('unchanged', 0)} onveranderd, "
            f"{telling.get('blocked', 0)} geblokkeerd. "
            "Ik heb nog niets weggeschreven."
        )

    stukjes = []

    for sleutel, label in [
        ("written", "geschreven"),
        ("overwritten", "herschreven met jouw 'ja'"),
        ("kept", "laten staan na jouw 'nee'"),
        ("unchanged", "onveranderd"),
        ("blocked", "geblokkeerd, niet aangeraakt"),
        ("planned", "gepland"),
        ("drift_planned", "zou een verschil geven"),
        ("error", "mislukt"),
        ("duplicate", "al verwerkt"),
    ]:
        aantal = telling.get(sleutel, 0)

        if aantal:
            stukjes.append(f"{aantal} {label}")

    if not stukjes:
        return "Er was niets te doen."

    return f"{', '.join(stukjes)}."


def try_vault_export(command):
    """
    "Zet mijn geheugen in Obsidian" — alleen op expliciete vraag.

    Doet precies twee dingen, en nooit iets anders:

      * "vergelijk mijn geheugen met de vault" -> lezen en rapporteren
      * "exporteer / migreer ..."              -> de export, tot de
                                                   eerste drift

    In beide richtingen is memory.json de bron van waarheid: er wordt
    door de hele exportflow niets aan het geheugen geschreven. Bij een
    verschil wordt gevraagd, en 'ja' wijzigt uitsluitend de notitie.
    """

    question = command.lower()

    # Een export-commando mag nooit een import-commando opstrikken.
    if any(word in question for word in VAULT_IMPORT_WORDS):
        return None

    # Richting-bepalende uitdrukking komt eerst: "vergelijk mijn
    # geheugen met de vault" is een export-vraag, "vergelijk mijn
    # vault met mijn geheugen" niet.
    is_vergelijking = any(woord in question for woord in
                          ["vergelijk", "vergelijken", "verschil"])

    if is_vergelijking and any(
            frase in question for frase in VAULT_EXPORT_COMPARE_PHRASES):
        return _vergelijk_geheugen_met_vault()

    if not any(woord in question for woord in VAULT_EXPORT_WORDS):
        return None

    if not any(woord in question for woord in VAULT_WORDS):
        return None

    return _start_vault_export()


def _vergelijk_geheugen_met_vault():
    """Leest de stand en rapporteert. Schrijft niets."""

    vault = obsidian_vault.get_vault_path()

    if not obsidian_vault.vault_exists():
        return (
            f"Ik kan je vault niet vinden op '{vault}', dus ik kan je "
            "geheugen er niet naast leggen."
        )

    rapport = vault_out.compare_memory_to_vault()

    if not rapport["ok"]:
        return f"Ik kon de vergelijking niet maken: {rapport['reason']}."

    telling = rapport["counts"]

    if not telling["total"]:
        return (
            "Je geheugen is nog leeg, dus er valt niets te vergelijken "
            "met de notities in je vault."
        )

    regels = [
        f"Je geheugen bevat {telling['total']} notitie(s) voor de vault:",
        "",
        f"- {telling['create']} nog niet in je vault",
        f"- {telling['unchanged']} al gelijk",
        f"- {telling['drift']} met een verschil",
        f"- {telling['blocked']} die ik niet overschrijf",
    ]

    if rapport["drift"]:
        regels.extend(["", "De verschillen zijn:"])

        for record in rapport["drift"][:6]:
            regels.append(
                f"- {record['key']}: geheugen zegt '{record['value']}', "
                "maar de notitie zegt iets anders"
            )

        if len(rapport["drift"]) > 6:
            regels.append(f"- en nog {len(rapport['drift']) - 6} andere")

    if rapport["blocked"]:
        regels.extend(["", "Deze schrijf ik niet weg:"])

        for record in rapport["blocked"][:6]:
            regels.append(f"- {record['key']}: {record['reason']}")

    regels.extend([
        "",
        "Ik heb niets weggeschreven. Zeg bijvoorbeeld "
        "'exporteer mijn geheugen naar de vault' als je ze wilt "
        "bijwerken.",
    ])

    return "\n".join(regels)


def _start_vault_export():
    """Start de export en zet de uitkomst om in een antwoord."""

    state = vault_out.start_export(dry_run=False)

    return _verwerk_export(state)


def _verwerk_export(state):
    """
    Zet de export-uitkomst om in een antwoord.

    Stopt de export bij een verschil, dan wordt de bestaande
    pending_choice-architectuur gebruikt. Bij 'ja' of 'nee' gaat de
    export daarna verder met de wachtrij. De state is JSON-geschikt
    en bewust zó gezet dat er geen notitie-inhoud in het
    context-bestand belandt.
    """

    if state.get("paused") and state.get("confirm"):
        confirm = state["confirm"]

        update_context(pending_choice={
            "kind": "memory_update",
            "memory_key": confirm["key"],
            "memory_value": confirm["memory_value"],
            "memory_category": confirm.get("category"),
            "old_value": confirm.get("vault_value"),
            "from_vault": confirm["note_name"],
            # Dit merkt het aan als een EXPORT-pending is, zodat
            # handle_pending_choice() de gewone conflictlogica NIET
            # gebruikt: een export mag het geheugen nooit wijzigen.
            "vault_export": vault_out.export_state_for_storage(state),
        })

        return (
            f"Je geheugen zegt dat je {confirm['key'].replace('_', ' ')} "
            f"{confirm['memory_value']} is, maar de notitie in je vault "
            f"zegt {confirm['vault_value']}. Zal ik de notitie "
            "bijwerken? Zeg 'ja' of 'nee'."
        )

    return _describe_export(state)


def _hervat_vault_export(pending, overwrite):
    """
    Hervat de export na een 'ja' of 'nee' op een verschil.

    'ja' (overwrite=True) herschrijft uitsluitend de Obsidian-notitie.
    'nee' (overwrite=False) laat notitie én geheugen precies zoals
    ze zijn. Het geheugen wordt in beide gevallen niet aangeraakt.

    Geeft een antwoord-string terug, of None als er geen export was
    om te hervatten.
    """

    bewaard = pending.get("vault_export")

    if not isinstance(bewaard, dict):
        return None

    state = vault_out.export_state_from_storage(bewaard)

    try:
        nieuwe_state = vault_out.resolve_paused_export(state, overwrite)
    except Exception as exc:
        return (
            f"Ik kon de export niet hervatten: {type(exc).__name__}: {exc}. "
            "Ik doe verder niets; je geheugen is ongewijzigd."
        )

    if nieuwe_state.get("paused") and nieuwe_state.get("confirm"):
        return _verwerk_export(nieuwe_state)

    return _describe_export(nieuwe_state)


def try_vault_compare(command):
    """
    "Vergelijk mijn vault met mijn geheugen" — alleen op expliciete vraag.

    Volledig read-only: er wordt niets in memory.json of in de vault
    geschreven. De vergelijking zelf doet niets dan lezen; ook de
    conflictstatus wordt alleen berekend, niet opgelost.
    """

    question = command.lower()

    if not any(word in question for word in ["vergelijk", "verschil", "vergelijken"]):
        return None

    if not any(word in question for word in ["vault", "obsidian"]):
        return None

    vault = obsidian_vault.get_vault_path()

    if not obsidian_vault.vault_exists():
        return (
            f"Ik kan je vault niet vinden op '{vault}', dus ik kan niets "
            "vergelijken."
        )

    rapport = vault_sync.compare_vault_to_memory()

    if not rapport["ok"]:
        return f"Ik kon de vergelijking niet maken: {rapport['reason']}."

    telling = rapport["counts"]

    if not telling["total"]:
        return (
            "Ik zie geen memory-notities in je vault, dus er valt niets "
            "te vergelijken met je geheugen."
        )

    regels = [
        f"Ik zie {telling['total']} memory-notitie(s) in je vault:",
        "",
        f"- {telling['new']} nieuw (nog niet in je geheugen)",
        f"- {telling['conflict']} met een verschil",
        f"- {telling['unchanged']} hetzelfde als wat ik al heb",
    ]

    if rapport["conflicts"]:
        regels.extend(["", "De verschillen zijn:"])

        for record in rapport["conflicts"][:6]:
            regels.append(
                f"- {record['key']}: geheugen zegt "
                f"'{record['memory_value']}', je vault zegt '{record['value']}'"
            )

        if len(rapport["conflicts"]) > 6:
            regels.append(f"- en nog {len(rapport['conflicts']) - 6} andere")

        regels.extend([
            "",
            "Ik heb er niets mee gedaan. Zeg bijvoorbeeld "
            "'importeer alles uit mijn vault' als je ze wilt overnemen.",
        ])

    return "\n".join(regels)


def try_vault_batch(command):
    """
    "Importeer alles uit mijn vault" — alleen op expliciete vraag.

    De batch wordt door de gebruiker gestart. Bij de eerste
    tegenstrijdigheid stopt hij en wordt de bestaande
    pending_choice-flow gebruikt; pas na 'ja' of 'nee' gaat hij
    verder met de volgende notities.
    """

    question = command.lower()

    if not any(word in question for word in VAULT_IMPORT_WORDS):
        return None

    if not any(word in question for word in VAULT_WORDS + ["geheugen"]):
        return None

    # Alleen als er expliciet om ALLES wordt gevraagd; een enkele
    # notitie hoort bij try_vault_import.
    if not any(word in question for word in ["alles", "alle", "volledige", "batch"]):
        return None

    vault = obsidian_vault.get_vault_path()

    if not obsidian_vault.vault_exists():
        return (
            f"Ik kan je vault niet vinden op '{vault}', dus ik kan niets "
            "importeren."
        )

    state = vault_sync.start_batch(dry_run=False)

    return _verwerk_batch(state)


def _verwerk_batch(state):
    """
    Zet de batch-uitkomst om in een antwoord.

    Stopt de batch bij een conflict, dan wordt meteen de bestaande
    pending_choice-vorm gebruikt (memory_key/memory_value/
    memory_category), plus de batch-state zelf zodat we na 'ja' of
    'nee' kunnen hervatten. De state gaat mee in het context-bestand en
    is daarom bewust JSON-geschikt.
    """

    if state.get("paused") and state.get("confirm"):
        confirm = state["confirm"]

        update_context(pending_choice={
            "kind": "memory_update",
            "memory_key": confirm["stored_key"],
            "memory_value": confirm["vault_value"],
            "memory_category": confirm.get("category"),
            "old_value": confirm.get("memory_value"),
            "from_vault": confirm["note_name"],
            "vault_batch": state,
        })

        return (
            f"Ik wist dat je {confirm['stored_key'].replace('_', ' ')} "
            f"{confirm['memory_value']} is, in je vault staat "
            f"{confirm['vault_value']}. Zal ik dat wijzigen? "
            "Zeg 'ja' of 'nee'."
        )

    return _describe_batch(state)


def _hervat_vault_batch(pending, keep_old):
    """
    Hervat de batch na een 'ja' of 'nee' op een conflict.

    Wordt aangeroepen vanuit handle_pending_choice(), nadat het
    conflict zelf al is afgehandeld met resolve_conflict(). Hier gaat
    de batch verder met de notities die nog op de wachtrij staan.

    Geeft een antwoord-string terug, of None als er geen batch was om
    te hervatten (dan is het gewone geheugen-confict afgehandeld).
    """

    state = pending.get("vault_batch")

    if not isinstance(state, dict):
        return None

    try:
        nieuwe_state = vault_sync.resolve_paused_batch(state, keep_old)
    except Exception as exc:
        return (
            f"Ik kon de batch niet hervatten: {type(exc).__name__}: {exc}. "
            "Ik doe verder niets, zodat je geheugen niet half afgemaakt "
            "achterblijft."
        )

    if nieuwe_state.get("paused") and nieuwe_state.get("confirm"):
        return _verwerk_batch(nieuwe_state)

    return _describe_batch(nieuwe_state)


def _summarize_routine(name, description, done, failed):
    """Bouwt een kort, eerlijk Nederlands antwoord voor een routine."""

    if not failed:
        return description if description else f"Routine '{name}' is uitgevoerd."

    failed_names = []
    for record in failed:
        tool = record.get("used_tool_name") or record.get("tool_name", "")
        arguments = record.get("arguments") or {}
        label = arguments.get("program") or arguments.get("entity_id") or tool
        failed_names.append(label)

    joined = ", ".join(failed_names) if failed_names else "een paar stappen"

    if done:
        return (
            f"Routine '{name}' gedeeltelijk uitgevoerd. "
            f"Mislukt: {joined}."
        )

    return f"Routine '{name}' mislukt: {joined}."


# =========================================================
# GAME-PC AGENT (Fase 15)
#
# Expliciete routing voor opdrachten die de gaming-pc bedoelen
# ("open Discord op de game-pc"). Dit staat bewust VÓÓR de
# PC-ACTIES/power-tools: een opdracht voor de game-pc mag NOOIT
# op deze pc (de mini-pc) worden uitgevoerd.
# =========================================================

# Frases waarmee de gebruiker de gaming-pc bedoelt. "game" alleen is
# te breed ("mijn favoriete game"), dus we eisen een expliciete
# game-pc-variant.
_GAME_PC_PATROON = re.compile(
    r"\b(?:game[\s-]?pc|gaming[\s-]?pc|spel[\s-]?pc|gamecomputer|spelcomputer"
    r"|game\s+computer)\b"
)

# Tussenwoorden die na/rond de game-pc-frase mogen staan ("op de game-pc").
_GAME_PC_TUSSENWOORDEN = frozenset(
    {
        "op", "de", "het", "een", "via", "van", "bij", "naar", "in", "aan",
        "voor", "met", "en", "dan", "ook", "even", "eens", "gauw", "snel",
        "graag", "alsjeblieft", "aub", "nou", "maar", "mijn",
    }
)

_GAME_PC_POWER_WOORDEN = (
    "uitzetten", "uitschakelen", "shutdown", "slaapstand", "slapen",
    "herstart", "herstarten", "reboot", "afsluiten", "poweroff",
    "opnieuw opstarten", "in slaap", "naar slaap",
)

_GAME_PC_OPEN_WOORDEN = (
    "open", "opent", "openen", "start", "starten", "lanceer", "lanceren",
    "opstarten", "beginnen", "begin",
)

_GAME_PC_SLUIT_WOORDEN = (
    "sluit", "sluiten", "beëindig", "beeindig", "beëindigen", "beeindigen",
    "stopzetten",
)

_GAME_PC_TELEMETRIE_WOORDEN = (
    "telemetrie", "temperatuur", "warmte", "gpu", "videokaart", "grafische",
    "geheugen", "ram", "cpu", "processor", "schijf", "disk", "uptime",
    "specs", "specificaties", "belasting", "prestaties", "hardware",
    "systeeminformatie",
)

_GAME_PC_SCREENSHOT_WOORDEN = (
    "screenshot", "schermafbeelding", "screen", "vastleggen",
)

_GAME_PC_STATUS_WOORDEN = (
    "status", "online", "offline", "bereikbaar", "draait", "hoe staat",
)

_GAME_PC_MEDIA_ACTIES = (
    ("volgend nummer", "next"),
    ("volgende", "next"),
    ("vorig nummer", "previous"),
    ("vorige", "previous"),
    ("pauzeer", "play_pause"),
    ("pauze", "play_pause"),
    ("afspelen", "play_pause"),
    ("speel", "play_pause"),
    ("speelt", "play_pause"),
    ("play", "play_pause"),
    ("stop", "stop"),
    ("stoppen", "stop"),
    ("dempen", "mute"),
    ("mute", "mute"),
    ("volume omhoog", "volume_up"),
    ("harder", "volume_up"),
    ("luider", "volume_up"),
    ("volume omlaag", "volume_down"),
    ("zachter", "volume_down"),
)


def mentions_game_pc(text):
    """True als de tekst expliciet de game-pc/gaming-pc noemt."""

    return bool(_GAME_PC_PATROON.search(text or ""))


def _strip_game_pc_phrase(text):
    """Haalt de game-pc-frase plus losse tussenwoorden uit de tekst."""

    tekst = _GAME_PC_PATROON.sub(" ", text or "")
    woorden = [w for w in tekst.split() if w not in _GAME_PC_TUSSENWOORDEN]
    return " ".join(woorden).strip()


def _game_pc_bevat(tekst, woorden):
    """Woordgrens-match: True als één van ``woorden`` in de tekst staat."""

    for woord in woorden:
        if re.search(rf"\b{re.escape(woord)}\b", tekst):
            return True
    return False


def _game_pc_power_verzoek(tekst):
    """True als de gebruiker de game-pc uit/uit/herstart wil."""

    if _game_pc_bevat(tekst, _GAME_PC_POWER_WOORDEN):
        return True
    return bool(
        re.search(
            r"\b(?:zet|doe|zetten|doen|laat|leg|schakel|schakelen|haal)\b.*\buit\b",
            tekst,
        )
    )


def _game_pc_programma(tekst, werkwoorden):
    """De programma-/gamennaam, zonder tussen- en werkwoorden."""

    woorden = []
    for woord in tekst.split():
        if woord in _GAME_PC_TUSSENWOORDEN or woord in werkwoorden:
            continue
        woorden.append(woord)
    return " ".join(woorden).strip(" .,!?")


def _game_pc_volume(tekst):
    """Percentage als de tekst 'volume'/'geluid' + een getal bevat."""

    if not _game_pc_bevat(tekst, ("volume", "geluid")):
        return None

    match = re.search(r"\b(\d{1,3})\b", tekst)

    if not match:
        return None

    return max(0, min(100, int(match.group(1))))


def _game_pc_bepaal_actie(tekst):
    """Kies de juiste game-pc-tool bij de overgebleven tekst."""

    if not tekst:
        return ("game_pc_status", {})

    if _game_pc_bevat(tekst, _GAME_PC_TELEMETRIE_WOORDEN):
        return ("game_pc_telemetry", {})

    if _game_pc_bevat(tekst, _GAME_PC_SCREENSHOT_WOORDEN):
        return ("game_pc_screenshot", {})

    percent = _game_pc_volume(tekst)
    if percent is not None:
        return ("game_pc_set_volume", {"percent": percent})

    if _game_pc_bevat(tekst, _GAME_PC_SLUIT_WOORDEN):
        programma = _game_pc_programma(tekst, _GAME_PC_SLUIT_WOORDEN)
        if programma:
            return ("game_pc_close_program", {"program": programma})

    if _game_pc_bevat(tekst, _GAME_PC_OPEN_WOORDEN):
        programma = _game_pc_programma(tekst, _GAME_PC_OPEN_WOORDEN)
        if programma:
            return ("game_pc_open_program", {"program": programma})

    for woord, media_actie in _GAME_PC_MEDIA_ACTIES:
        if _game_pc_bevat(tekst, (woord,)):
            return ("game_pc_media", {"action": media_actie})

    if _game_pc_bevat(tekst, _GAME_PC_STATUS_WOORDEN):
        return ("game_pc_status", {})

    return None


def try_game_pc_command(command):
    """Routeert een expliciete game-pc-opdracht naar de remote-agent.

    Geeft ``None`` terug als het commando niet (veilig) bij de game-pc
    hoort, zodat de gewone JARVIS-routing het kan afhandelen.
    """

    if not mentions_game_pc(command):
        return None

    tekst = _strip_game_pc_phrase(command)
    actie = _game_pc_bepaal_actie(tekst)

    if actie is not None:
        tool, argumenten = actie
        return execute_tool(tool, argumenten, command)

    # Expliciet de game-pc genoemd, maar geen veilige remote-actie
    # herkend. Vraagt de gebruiker om uit/uitzetten/herstarten? Dan
    # weigeren we -- we laten dit NOOIT doorvallen naar de lokale
    # power-tools van deze pc.
    if _game_pc_power_verzoek(tekst):
        return (
            "Ik kan de game-pc niet op afstand uitzetten, herstarten of in "
            "slaapstand zetten; dat is om veiligheidsredenen niet toegestaan."
        )

    return None


def _process_command_intern(command, on_tekst=None):

    command = command.lower().strip()

    # =====================================================
    # USAGE TRACKING: reset dedup-set voor dit commando
    # =====================================================

    reset_touch_usage()

    # =====================================================
    # INPUT-GUARD (Fase 6 — randgeval-afhandeling)
    # =====================================================
    # Lege of whitespace-alleen input is nooit een geldige
    # opdracht of keuze. Direct een veilig antwoord.

    if not command:
        return "Ik verstond je niet. Kun je dat nog eens zeggen?"

    status.beurt_begint(command)

    # =========================
    # TAALWISSEL (Fase 17, F)
    # =========================

    taal_antwoord = taal.wissel(command)

    if taal_antwoord:
        status.taalwissel()
        return taal_antwoord

    # =========================
    # TAAL VOLGT UW VRAAG (Fase 17)
    # =========================
    # Geen expliciete wissel: volgt JARVIS de taal van de vraag, maar alleen
    # als die overduidelijk Engels is en de taal niet vastgezet is. Anders
    # gaat de antwoordtaal terug naar de vaste taal (spraakherkenning blijft
    # altijd op de vaste taal).
    # Dit mag nooit een opdracht laten mislukken.
    try:
        taal.volgt_vraag(command)
    except Exception:
        logger.debug("Automatische taaldetectie mislukt", exc_info=True)

    # =========================
    # WACHTENDE KEUZE (Fase 6)
    # =========================

    pending_answer = handle_pending_choice(command)

    if pending_answer:
        return pending_answer

    # -----------------------------------------------------
    # Nonsens-guard: puur interpunctie / alleen tekens zonder
    # letters (bv. "???", "!!", "...") is geen geldige
    # opdracht. (Numerieke keuzes zoals "1" worden hierboven
    # al door handle_pending_choice afgehandeld.)
    # -----------------------------------------------------

    if not re.search(r"[a-z]", command):
        return "Ik verstond je niet. Kun je dat nog eens zeggen?"


    # =========================================================
    # OBSIDIAN-VAULT (Fase 14, Stap 4 + 5)
    #
    # Opdrachtig: alleen als de gebruiker er expliciet om vraagt.
    #
    # Dit blok staat bewust VROEG. "geheugen" betekent in het
    # systeeminfo-gedeelte RAM, en try_system_info() pakt elk
    # commando met het woord 'geheugen' aan. Zonder deze positie
    # zou "zet voorkeuren/licht in mijn geheugen" dus een
    # RAM-rapportage opleveren in plaats van een import.
    #
    # De handlers zijn streng genoeg om geen woorden te stelen: ze
    # geven None terug zodra het commando niet duidelijk over de
    # vault gaat.
    #
    # Volgorde: vergelijken, dan de batch, dan één notitie, dan
    # de algemene vraag.
    # =========================================================

    # Volgorde: de export komt VÓÓR de import-vergelijking, want die
    # noemen beide een vault én een geheugen.
    vault_export_result = try_vault_export(command)

    if vault_export_result is not None:
        return vault_export_result


    vault_compare_result = try_vault_compare(command)

    if vault_compare_result is not None:
        return vault_compare_result


    vault_batch_result = try_vault_batch(command)

    if vault_batch_result is not None:
        return vault_batch_result


    vault_import_result = try_vault_import(command)

    if vault_import_result is not None:
        return vault_import_result


    vault_info_result = try_vault_info(command)

    if vault_info_result is not None:
        return vault_info_result


    # =========================
    # GAME-PC AGENT (Fase 15)
    #
    # Expliciete routing voor opdrachten die de gaming-pc bedoelen.
    # Dit staat bewust VÓÓR de PC-ACTIES/power-tools: een opdracht
    # voor de game-pc mag NOOIT op deze pc (de mini-pc) worden
    # uitgevoerd.
    # =========================

    game_pc_result = try_game_pc_command(command)

    if game_pc_result is not None:
        return game_pc_result


    # =========================
    # PC-ACTIES (Fase 6)
    # (Moet vóór scenes/routines staan zodat "zet de pc in slaapstand"
    # niet door een "slaap" routine wordt gekaapt)
    # =========================

    power_result = try_power_command(command)

    if power_result is not None:
        return power_result


    # =========================
    # SCENES (Fase 13): opgeslagen scènes ("zet filmmodus aan") plus
    # beheer ("welke scenes", "verwijder scene filmmodus") en opslaan
    # ("sla dit op als scene filmmodus"). Scenes krijgen voorrang op
    # routines bij expliciete scene-woorden.
    # =========================

    scene_result = try_scene(command)

    if scene_result is not None:
        return scene_result

    # =========================
    # ROUTINES (Fase 4): opgeslagen modes ("ik ga gamen") plus
    # beheer ("welke routines", "verwijder routine gamen"). Deze
    # check komt VÓÓR het Agent/LLM-pad, zodat routines 100%
    # deterministisch worden uitgevoerd zonder AI-hallucinaties.
    # =========================

    routine_result = try_routine(command)

    if routine_result is not None:
        return routine_result

    # =========================
    # PROACTIEF (Fase 16A): timers/herinneringen, nachtmodus en stille
    # modus. Deterministisch pad vóór de Agent/LLM, zelfde patroon als
    # routines.
    # =========================

    proactive_result = try_proactive_command(command)

    if proactive_result is not None:
        return proactive_result

    # =========================
    # UPDATES (Fase 19, M6): "zijn er updates", "installeer de update".
    # Installeren vraagt altijd eerst om een ja.
    # =========================

    from beheer import updates as _updates

    update_result = _updates.probeer_commando(command)

    if update_result is not None:
        return update_result

    # =========================
    # BARGE-IN (Fase 17, B1): onderbreken met de stem aan of uit.
    # Deterministisch pad, net als de proactieve commando's.
    # =========================

    barge_in_result = try_barge_in_command(command)

    if barge_in_result is not None:
        return barge_in_result

    # =========================
    # EXTERNE BRONNEN (Fase 16C): nieuws, reistijden en prijzen —
    # alleen op aanvraag. Deterministisch pad vóór de Agent/LLM, zelfde
    # patroon als routines en proactieve commando's.
    # =========================

    bron_result = try_externe_bron_command(command)

    if bron_result is not None:
        return bron_result


    # =========================
    # AGENT (Fase 10 + Fase 2): doel-gebaseerde EN multi-actie opdrachten
    # "maak mijn pc klaar om te gamen" (mode) en "open discord en zet het
    # volume op 30" (multi-step) gaan naar de Agent. Enkelvoudige
    # opdrachten ("open Discord") blijven bij de handlers.
    # =========================

    # =========================
    # PROGRAMMA-STATUS & VINDEN (Fase 6 PC Control 2.0)
    # (moet VÓÓR Agent komen zodat eenvoudige vragen niet
    # onnodig naar de LLM gaan)
    # =========================

    status_result = try_program_status(command)

    if status_result is not None:
        return status_result

    find_prog_result = try_find_program(command)

    if find_prog_result is not None:
        return find_prog_result

    # =========================
    # HERSTART PROGRAMMA (Fase 6)
    # (moet VÓÓR power komen zodat "herstart spotify" niet als
    # PC-herstart wordt geïnterpreteerd)
    # =========================

    restart_result = try_restart_program(command)

    if restart_result is not None:
        return restart_result

    # =========================
    # SYSTEEMINFO & SCHERMINFO (Fase 6)
    # (moet VÓÓR Agent komen zodat "scherminformatie" niet door de
    # LLM wordt gekaapt)
    # =========================

    sys_result = try_system_info(command)

    if sys_result is not None:
        return sys_result


    # =========================
    # WEB ZOEKEN (Fase 9) — internet-zoek + beste bron lezen
    # "zoek X op", "google naar X", "weer", "vergelijk X en Y"
    # Moet VÓÓR de Agent-check komen zodat zoekvragen deterministisch
    # worden afgehandeld en de LLM geen 'web_search (alleen resultaten)'
    # stap plant die geen antwoord geeft.
    # =========================

    web_search_result = try_web_search(command)

    if web_search_result is not None:
        return web_search_result


    # =========================
    # UI AUTOMATISERING (Fase 10) — vensters vinden, naar voorgrond brengen
    # "welke vensters zijn open", "is Discord open", "breng Spotify naar voren"
    # Complexe bediening (klikken/typen/sliders) gaat via de LLM-tools.
    # =========================

    ui_result = try_ui_automation(command)

    if ui_result is not None:
        return ui_result


    # =========================
    # AUDIO (Fase 11): per-app volume/mute + output-apparaten
    # Moet vóór de app-specifieke agent-routing staan, zodat
    # "zet Spotify op 50" direct de per-app audio-session instelt
    # i.p.v. via de LLM-agent te gaan (sneller, deterministisch).
    # =========================

    audio_result = try_audio_command(command)

    if audio_result is not None:
        return audio_result


    # =========================
    # APP-SPECIFIEKE BEDIENING (Fase 10/11): "zet het volume van Spotify
    # op 50", "zet de helderheid in Discord harder"
    # Bevat de zin een app-NAAM tussen de actie en het resultaatwoord?
    # Dan moet de Agent met ui_* tools de juiste slider vinden — NOOIT
    # het Windows-systeemvolume aanpassen.
    # =========================

    if re.search(
        r"volume\s+(?:van|in|binnen)\s+\S+",
        command.lower(),
    ) or re.search(
        r"(?:zet|doe|maak|regel)\s+(?:het\s+)?volume\s+(?:van|in)\s+",
        command.lower(),
    ) or re.search(
        r"(?:harder|lager|zachter|luider)\s+(?:in|van|voor)\s+\S+",
        command.lower(),
    ) or _looks_like_app_volume(command.lower()):
        try:
            return agent.run_goal(command)
        except Exception as error:
            print(f"⚠️ Agent-fout (app-bediening): {error}")
            return "Er ging iets mis bij het bedienen van die app."


    # =========================
    # MEERDERE PROGRAMMA'S OPENEN ("open spotify en discord")
    # Deterministisch en zonder LLM: elk programma als eigen open-opdracht.
    # Zonder deze route belandde de zin bij de Agent-planner, en dat kostte
    # tientallen seconden op een langzame laptop.
    # =========================

    multi_open_result = try_multi_open_program(command)

    if multi_open_result is not None:
        return multi_open_result


    if is_agent_goal(command) or is_multi_step_goal(command):
        try:
            answer = agent.run_goal(command)
        except Exception as error:
            print(f"⚠️ Agent-fout: {error}")
            return "Er ging iets mis bij het uitvoeren van die opdracht."

        # --- Automations-voorstel (Fase 13) ---
        # Na een succesvolle multi-actie met ≥2 HA-stappen stelt JARVIS
        # automatisch voor om een scene op te slaan. Gebruiker keurt
        # goed met "ja" (pending_choice) of met "sla op als scene <naam>".
        executed_steps = list(getattr(agent, "last_executed_steps", []) or [])
        ha_steps = [
            s for s in executed_steps
            if (s.get("tool_name") == "control_home_assistant")
        ]
        if len(executed_steps) >= 2 and ha_steps:
            # Suggestie toevoegen aan het antwoord
            update_context(
                pending_choice={
                    "kind": "scene_save_suggest",
                    "steps": executed_steps,
                    "last_command": command,
                }
            )
            answer += (
                "\n\n💡 Wil je dit opslaan als scene? "
                "Zeg 'sla op als scene <naam>' of 'ja' om een "
                "automatische naam te kiezen."
            )

        return answer


    # =========================
    # TIJD EN DATUM
    # =========================

    info = get_information(command)

    if info:
        return info


    # =========================
    # REKENEN
    # =========================

    result = calculate(command)

    if result is not None:

        update_context(
            last_command=command,
            last_result=str(result["result"]),
            last_action="berekening",
            last_calculation=result["operation"]
        )

        return f"Het antwoord is {result['result']}."


    # =========================
    # REKEN-VERVOLG (bijv. "plus 10" na een berekening)
    # =========================

    followup = try_calculate_followup(command)

    if followup:
        return followup


    # =========================
    # CONTEXTVRAGEN (Fase 3)
    # =========================

    context_answer = get_context_answer(command)

    if context_answer:
        return context_answer


    # =========================
    # MEDIA (Fase 5)
    # =========================

    media_result = try_media_command(command)

    if media_result is not None:
        return media_result


    # =========================
    # VENSTERS (Fase 6)
    # =========================

    window_result = try_window_command(command)

    if window_result is not None:
        return window_result


    # =========================
    # GEOPENDE ACTIES COMBINEREN (Fase 6)
    # "open X en vergroot/minimaliseer/herstel X"
    # =========================

    combined_result = try_combined_open_window(command)

    if combined_result is not None:
        return combined_result


    # =========================
    # SCREENSHOT (Fase 6)
    # =========================

    screenshot_result = try_screenshot(command)

    if screenshot_result is not None:
        return screenshot_result


# =========================
    # BROWSER READING (Fase 12)
    # =========================

    browser_read_result = try_browser_read(command)

    if browser_read_result is not None:
        return browser_read_result

    # =========================
    # BROWSER SEARCH (Fase 6)
    # =========================

    browser_search_result = try_browser_search(command)

    if browser_search_result is not None:
        return browser_search_result

    known_site_result = try_open_known_site(command)

    if known_site_result is not None:
        return known_site_result

    browser_nav_result = try_browser_command(command)

    if browser_nav_result is not None:
        return browser_nav_result

    # =========================
    # WEB FETCH (Fase 8)
    # =========================

    web_fetch_result = try_web_fetch(command)

    if web_fetch_result is not None:
        return web_fetch_result


    # =========================
    # OPEN FOLDER (Fase 6)
    # (moet VÓÓR open_program komen zodat "open downloads" als map
    # wordt geïnterpreteerd en niet als programma)
    # =========================

    folder_result = try_open_folder(command)

    if folder_result is not None:
        return folder_result


    # =========================
    # RECENTE BESTANDEN (Fase 6)
    # =========================

    recent_result = try_recent_files(command)

    if recent_result is not None:
        return recent_result


    # =========================
    # BESTANDSBEHEER (Fase 6)
    # =========================

    file_result = try_file_command(command)

    if file_result is not None:
        return file_result


    # =========================
    # INFO VERGETEN (Fase 4)
    # =========================

    forget_result = try_forget(command)

    if forget_result is not None:
        return forget_result


    # =========================
    # INFO BIJWERKEN (Fase 5)
    # =========================

    update_result = try_memory_update(command)

    if update_result is not None:
        return update_result


    # =========================
    # APPARAATNAMEN ONTHOUDEN / OPSOMMEN (Fase 5)
    # =========================

    device_result = try_remember_device(command)

    if device_result is not None:
        return device_result

    device_list_result = try_list_devices(command)

    if device_list_result is not None:
        return device_list_result

    project_query_result = try_project_query(command)

    if project_query_result is not None:
        return project_query_result


    # =========================
    # HOME ASSISTANT (SMART HOME)
    #
    # Smart-home opdrachten (lampen, licht, stekkers, sensoren, ...)
    # gaan naar de bestaande AI-route zodat de AI de juiste HA-tool
    # (control_home_assistant) kan aanroepen. Deze check komt VÓÓR de
    # generieke PC-programma-routing, zodat "doe bedlamp uit" niet als
    # "sluit programma bedlamp" wordt geïnterpreteerd.
    # =========================

    ha_result = try_home_assistant(command)

    if ha_result is not None:
        return ha_result


    # =========================
    # PROGRAMMA SLUITEN / OPENEN
    # =========================

    close_result = try_close_program(command)

    if close_result is not None:
        return close_result

    open_result = try_open_program(command)

    if open_result is not None:
        return open_result


    # =========================
    # GEHEUGEN-SUGGESTIES (Fase 4)
    # =========================

    suggestion = memory_suggestion(command)

    if suggestion:
        return suggestion


    # =========================
    # BEGROETING
    # =========================

    if re.search(r"\b(hallo|hoi|goedemorgen|goedemiddag|goedenavond)\b", command):
        return f"Hallo {USER_NAME}. Waarmee kan ik je helpen?"

    # =========================
    # AUTOMATISCH ONTHOUDEN (Fase 4)
    # =========================

    remember_result = try_remember(command)

    if remember_result is not None:
        return remember_result

    saved = auto_remember(command)

    if saved:
        return saved

    # =========================
    # AI OPDRACHT
    # =========================

    try:
        if on_tekst is None:
            return ask_ai(command)
        return ask_ai(command, on_tekst=on_tekst)

    except Exception as error:

        print(f"⚠️ AI-fout: {error}")

        return "Er ging iets mis bij het verwerken van je opdracht."


def _antwoord_naar_zin(antwoord):
    """Maakt van een niet-tekst antwoord toch een Nederlandse zin."""

    if isinstance(antwoord, dict):
        # Een pc_status-achtig dict wordt een nette statuszin.
        if isinstance(antwoord.get("systeem"), dict):
            return _pc_status_zin(antwoord)

        for sleutel in ("message", "melding", "tekst", "antwoord"):
            waarde = antwoord.get(sleutel)
            if isinstance(waarde, str) and waarde.strip():
                return waarde

        return (
            "Ik heb je opdracht uitgevoerd, maar kan het resultaat "
            "niet uitspreken."
        )

    return str(antwoord)


def process_command(command, on_tekst=None):
    """Verwerkt één commando en garandeert altijd een gesproken antwoord.

    Handlers horen een string terug te geven. Geeft een handler toch iets
    anders terug (bijvoorbeeld een dict), dan zeggen we nooit niets: het
    antwoord wordt omgezet in een nette Nederlandse zin, met een
    logwaarschuwing zodat de oorzaak vindbaar blijft.

    Met ``on_tekst`` (Fase 17, A3) worden bij een gewone AI-vraag de
    tekststukjes direct doorgegeven zodra ze binnenkomen, zodat JARVIS al
    kan beginnen met praten (streaming). Zonder ``on_tekst`` gebeurt alles
    zoals voorheen.

    Bij een trage actie of research geeft JARVIS na ``MELDING_MIN_SECONDEN``
    een korte melding zodat er geen stille wachttijd valt (Fase 17, E).
    """

    # Spraakruis eerst repareren ("laag streepje" -> "_", "en download"
    # -> "in downloads"), zodat alle routers hieronder de juiste tekst zien.
    command = normaliseer_spraak(command)

    soort = status.taaksoort(command)
    melding.start(command, soort)
    try:
        antwoord = _process_command_intern(command, on_tekst=on_tekst)
    finally:
        melding.stop()

    if isinstance(antwoord, str):
        # Bevat het antwoord het aanbod "Wil je dat ik het opzoek?", dan
        # onthoudt JARVIS de oorspronkelijke vraag voor een "ja" (Fase 17).
        # Dit mag een antwoord nooit laten mislukken.
        try:
            from core import opzoeken

            opzoeken.onthoud_aanbod(command, antwoord)
        except Exception:
            logger.debug("Aanbod opzoeken onthouden mislukt", exc_info=True)
        return antwoord

    if antwoord is None:
        return "Sorry, daar heb ik geen antwoord op."

    # Sommige tools (met name game-pc-tools) geven een ToolResult terug in
    # plaats van tekst. Dat is een normaal antwoord, geen fout: gebruik de
    # melding zonder waarschuwing in het log.
    if hasattr(antwoord, "message") and hasattr(antwoord, "ok"):

        tekst = str(getattr(antwoord, "message", "") or "").strip()

        if tekst:
            return tekst

    logger.warning("Onverwacht antwoordtype: %s", type(antwoord).__name__)

    return _antwoord_naar_zin(antwoord)
