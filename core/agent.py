"""
Agent (Fase 10 — Agent V1)

De Agent ligt BOVENOP de bestaande Planner/Executor. Hij vervangt niets:

    Planner  : "Wat moet er gebeuren?"
    Executor : "Voer het plan uit."
    Agent    : "Breek een doel op in een plan en bepaal of het doel gehaald is."

Dataflow:
    1. Live smart-home apparaatlijst + context + geheugen worden klaargezet.
    2. Het doel wordt via de LLM opgebroken in concrete stappen (JSON-plan).
       Verboden ruis-stappen (screenshot/system_info/...) worden geweerd.
    3. Het plan wordt door de BESTAANDE Executor uitgevoerd (
       parallel waar mogelijk).
    4. Bij mislukte stappen krijgt de LLM maximaal EEN herplanting. Die kent
       de geslaagde stappen (mag die nooit herhalen) en mag een plan leeg
       teruggeven (= "overslaan") voor stappen die niet kunnen.
    5. Het eindantwoord wordt deterministisch samengevat uit de resultaten
       (nooit "succes" claimen zonder bevestigd resultaat — Fase 9-principe).
"""

import json
import re

import ollama

from core.ai import MODEL, get_context, add_to_history, update_context, current_context, conversation_history
from core.context_memory import build_memory_context
from memory.memory import memory_summary, relevant_memory_prompt, get_relevant_memory, touch_usage, reset_touch_usage
from core.executor import execute_action_plan
from core.home_assistant import get_home_assistant_entities_tool


# =========================================================
# BESTAANDE TOOLS (alleen namen, géén volledige schema's)
# =========================================================

VALID_TOOL_NAMES = {
    "open_file",
    "open_website",
    "open_program",
    "close_program",
    "remember",
    "recall",
    "forget",
    "media_play_pause",
    "media_next",
    "media_previous",
    "media_stop",
    "volume_up",
    "volume_down",
    "set_volume",
    "media_mute",
    "system_info",
    "screenshot",
    "create_folder",
    "create_file",
    "list_files",
    "copy_file",
    "move_file",
    "minimize_window",
    "maximize_window",
    "restore_window",
    "get_home_assistant_entities",
    "control_home_assistant",
    "restart_program",
    "program_status",
    "find_program_location",
    "rename_file",
    "open_folder",
    "search_files",
    "recent_files",
    "browser_search",
    "browser_back",
    "browser_forward",
    "browser_refresh",
    "browser_new_tab",
    "browser_close_tab",
    "browser_get_url",
    "browser_get_title",
    "browser_get_content",
    "pc_status",
    "web_fetch",
    "web_search",
    "web_search_and_fetch",
    "ui_find_window",
    "ui_list_elements",
    "ui_click_element",
    "ui_find_element",
    "ui_type_text",
    "ui_set_value",
    "ui_get_value",
    "ui_activate_window",
    "ui_launch_app",
    "ui_list_windows",
    "audio_list_sessions",
    "audio_get_session_volume",
    "audio_set_session_volume",
    "audio_set_session_mute",
    "audio_toggle_session_mute",
    "audio_list_outputs",
    "audio_get_default_output",
    "audio_set_default_output",
}

# Tools die een plan zelden hoeven te bevatten: alleen opnemen als de
# gebruiker er expliciet om vraagt (paste bij het Fase 9-principe).
NOISE_TOOLS = {
    "screenshot",
    "system_info",
    "create_folder",
    "create_file",
    "list_files",
    "copy_file",
    "move_file",
    "remember",
    "recall",
    "forget",
    "get_home_assistant_entities",
    "search_files",
    "recent_files",
    "program_status",
    "find_program_location",
}

TOOL_LIST_TEXT = "\n".join([
    "open_file(filename)            - een bestand of foto openen",
    "open_website(url)              - een website openen",
    "open_program(program)          - een programma openen",
    "close_program(program)         - een programma sluiten",
    "remember(key, value)           - iets onthouden",
    "recall(key)                    - eerder onthouden info ophalen",
    "forget(key)                    - iets vergeten",
    "media_play_pause()             - muziek/media afspelen of pauzeren",
    "media_next()                   - volgend nummer",
    "media_previous()               - vorig nummer",
    "media_stop()                   - muziek volledig stoppen (niet pauzeren)",
    "volume_up()                    - volume omhoog",
    "volume_down()                  - volume omlaag",
    "set_volume(percent)            - volume op percentage (0-100)",
    "media_mute()                   - geluid dempen",
    "system_info()                  - systeeminformatie (CPU/RAM/GPU/...)",
    "screenshot()                   - screenshot maken",
    "create_folder(name, location)  - map maken",
    "create_file(name, location)    - bestand maken",
    "list_files(location)           - bestanden in een map tonen",
    "copy_file(filename, location)  - bestand kopiëren",
    "move_file(filename, location)  - bestand verplaatsen",
    "minimize_window(program)       - venster minimaliseren",
    "maximize_window(program)       - venster vergroten",
    "restore_window(program)        - venster herstellen",
    "restart_program(program)      - programma herstarten",
    "program_status(program)       - controleren of programma draait",
    "find_program_location(program) - locatie van programma opzoeken",
    "rename_file(old, new)         - bestand hernoemen",
    "open_folder(location)         - map openen in Verkenner",
    "search_files(query)           - bestanden zoeken",
    "recent_files()                - recent geopende bestanden tonen",
    "browser_search(query, site)   - zoeken op een website (bijv. youtube, google)",
    "browser_back()                - terug naar vorige pagina",
    "browser_forward()             - vooruit naar volgende pagina",
    "browser_refresh()             - pagina verversen",
    "browser_new_tab()             - nieuw tabblad openen",
    "browser_close_tab()           - tabblad sluiten",
    "browser_get_url()             - lees de URL van de huidige browser",
    "browser_get_title()           - lees de titel van de huidige browser",
    "browser_get_content(max)      - lees alle zichtbare tekst van de huidige pagina",
    "web_fetch(url)                - inhoud van een webpagina ophalen en lezen",
    "web_search(query)             - zoeken op internet (DuckDuckGo)",
    "web_search_and_fetch(query, max_pages) - zoeken én beste resultaten lezen (max_pages=2 bij vergelijken)",
    "ui_find_window(title)         - vind een app-venster (titel-deel) en geef de handle",
    "ui_list_elements(handle)      - lees de knoppen/velden/sliders van een venster",
    "ui_click_element(handle, name) - klik op een knop in een app-venster",
    "ui_type_text(handle, text)    - type tekst in het actieve venster/veld",
    "ui_set_value(handle, value, name) - stel een waarde in (bijv. slider)",
    "ui_get_value(handle, name)    - lees de waarde van een element",
    "ui_activate_window(handle)    - breng venster naar de voorgrond",
    "ui_launch_app(path)           - start een app via een eigen pad",
    "get_home_assistant_entities(domain) - HA-apparaten opvragen",
    "control_home_assistant(domain, service, entity_id, service_data) - HA-apparaat bedienen",
])

PLANNING_SYSTEM_PROMPT = """
Je bent JARVIS, een Nederlandse assistent. De gebruiker geeft je een DOEL.
Breek dat doel op in concrete, uitvoerbare stappen.

REGELS:
- Gebruik ALLEEN tools uit de lijst hieronder. Verzin GEEN andere tools.
- Elke stap is exact één tool-call met de juiste argumenten.
- Maximaal 6 stappen. Liever minder: alleen stappen die écht bijdragen aan het doel.
- Open eerst programma's/websites, daarna instellingen (volume, lampen).
- Gebruik het GEHEUGEN (voorkeuren, favoriete programma's) waar relevant.
- Wil je in een bestaand app-venster iets BEDIENEN (knop klikken, veld invullen,
  slider zetten)? Gebruik dan ui_find_window om de handle te krijgen, daarna
  ui_list_elements om de echte knoppen te zien, daarna ui_click_element/
  ui_set_value/ui_type_text. Verzin NOOIT knopnamen; lees ze eerst.
- Eén venster-actie = eerst handle vinden (ui_find_window), daarna pas de actie.

WAT BEPAALDE DOELEN BETEKENEN:
- "pc klaar maken om te gamen": openen van de game-programma's van de gebruiker
  (bijv. Steam, Discord, Spotify) en het volume instellen. Geen systeeminformatie,
  geen screenshots, geen bestandsbeheer, geen geheugen-acties.
- "ik ga slapen": smart-home apparaten uitzetten (lampen, media) en media pauzeren.
  Geen programma's openen, geen volume instellen.
- "filmavond / filmmodus": media aanzetten, verlichting op stemming, muziek uit of stil.
- Gebruik deze richting alleen als het doel er duidelijk over gaat.

KIJS DE BESTE METHODE (Fase 12) — lees de intentie, kies dan de tool:
- De gebruiker wil weten wat er OP ZIJN SCHEEM / in zijn openstaande browser
  staat ("wat staat er op mijn browser", "wat is er zichtbaar")?
      → browser_get_content()  (leest de geopende pagina)
  Wil hij de URL/titel van de openstaande pagina?
      → browser_get_url()  /  browser_get_title()
  Wil hij iets OP HET INTERNET zoeken (een antwoord vinden op een vraag)?
      → web_search(query) of web_search_and_fetch(query)
- Wil hij EEN NIEUWE WEBSITE in zijn browser openen, met zoekopdracht?
      → browser_search(query, site)
- Wil hij het totaaloverzicht van de pc (systeem + audio + browser)?
      → pc_status()
- Per-app volume ("zet Spotify op 50", "maak Discord zachter")?
      → audio_set_session_volume / audio_get_session_volume
- Output-apparaat wisselen ("zet geluid naar headset")?
      → audio_set_default_output
- In een app-venster klikken/typen/slider zetten?
      → ui_find_window → ui_list_elements → ui_click_element/ui_set_value/ui_type_text
- Verwar browser_search (openen + zoeken) NIET met web_search (internetzoeken
  zonder browser te bedienen). Lees de intentie: wil de gebruiker MIJ een
  antwoord, of wil hij een BEZOEK in zijn browser?

GEBRUIK NOOIT een ui_*-tool of browser_get_*-tool om een bestand te openen of
een programma te starten; dat doet open_file / open_program.

PLAN NOOIT DEZE TOOLS (tenzij de gebruiker er ÉXPLICIET om vraagt):
- screenshot, system_info (CPU/RAM/GPU), create_file, create_folder, list_files,
  copy_file, move_file, remember, recall, forget,
  of get_home_assistant_entities als losse plan-stap.

BIJ "PC KLAAR MAKEN OM TE GAMEN":
- Gebruik ALTIJD open_program voor Spotify (de app), NOOIT open_website.
- Geen remember/recall/forget stappen — dit is geen geheugen-opdracht.

MULTI-ACTIE ZINNEN (Fase 2):
- De gebruiker kan in ÉÉN zin meerdere acties geven, bijv.:
  "Doe mijn lamp aan, zet hem op 40% en open Spotify."
  → 1) control_home_assistant(light, turn_on, ...)  2) set_volume(40)  3) open_program(Spotify)
  "Open Discord, zet mijn muziek aan en maak Discord kleiner."
  → 1) open_program(Discord)  2) media_play_pause()  3) minimize_window(Discord)
- Elke actie wordt een aparte stap. Gebruik GEEN losse "(en)" tussen acties.
- Zet een actie die volgt op het GEVOLG van een andere actie NEIET voor de
  eerste actie: bijv. "maak Discord kleiner" moet na "open Discord" komen.
- OPTIONEEL: geef een "depends_on" mee met de 1-based nummers van stappen
  die eerst MÓETEN slagen. Bijv. "maak Discord kleiner" ná "open Discord":
    {{"tool_name": "minimize_window", "arguments": {{"program": "Discord"}},
      "depends_on": [1], "description": "Discord kleiner maken"}}
- Stappen ZONDER depends_on zijn onafhankelijk en mogen parallel.

VEILIGHEID (Fase 2):
- Onveilige/onmogelijke acties mogen NIET in het plan: verwijder ze.
  Bijv. een HA-apparaat dat niet in de lijst staat, of een niet-bestaande
  tool. Vertel dat NIET als succes.

SMART-HOME (Home Assistant):
- Hieronder staat de ECHTE lijst van beschikbare apparaten (SMART-HOME APPARATEN).
- Gebruik een HA-apparaat ALLEEN als het in die lijst staat, met het EXACTE
  entity_id eruit. Verzin NOOIT een entity_id.
- Neem alleen de apparaten op die passen bij het doel.
- Staat er "SMART-HOME: niet beschikbaar" of een lege lijst, plan dan GEEN
  home-assistant stappen.
- Bij twijfel tussen lampen: gebruik altijd light.bed_lamp.

BESCHIKBARE TOOLS:
{tools}

SMART-HOME APPARATEN:
{ha_devices}

VOORBEELD voor "maak mijn pc klaar om te gamen":
{{"steps": [
  {{"tool_name": "open_program", "arguments": {{"program": "Steam"}}, "description": "Steam openen"}},
  {{"tool_name": "open_program", "arguments": {{"program": "Discord"}}, "description": "Discord openen"}},
  {{"tool_name": "open_program", "arguments": {{"program": "Spotify"}}, "description": "Spotify openen"}},
  {{"tool_name": "set_volume", "arguments": {{"percent": 40}}, "description": "Volume op 40%"}}
]}}

VOORBEELD voor "Doe mijn lamp aan, zet hem op 40% en open Spotify":
{{"steps": [
  {{"tool_name": "control_home_assistant", "arguments": {{"domain": "light", "service": "turn_on", "entity_id": "light.bed_lamp", "service_data": {{}}}}, "description": "Lamp aanzetten"}},
  {{"tool_name": "set_volume", "arguments": {{"percent": 40}}, "description": "Volume op 40%"}},
  {{"tool_name": "open_program", "arguments": {{"program": "Spotify"}}, "description": "Spotify openen"}}
]}}

VOORBEELD voor "Open Discord, zet mijn muziek aan en maak Discord kleiner":
{{"steps": [
  {{"tool_name": "open_program", "arguments": {{"program": "Discord"}}, "description": "Discord openen"}},
  {{"tool_name": "media_play_pause", "arguments": {{}}, "description": "Muziek aanzetten"}},
  {{"tool_name": "minimize_window", "arguments": {{"program": "Discord"}}, "depends_on": [1], "description": "Discord kleiner maken"}}
]}}

GEEF ALLEEN JSON terug in dit formaat (geen andere tekst):
{{"steps": [{{"tool_name": "...", "arguments": {{...}}, "description": "korte uitleg", "depends_on"?: [1, 2]}}]}}
"""

REPLANNING_SYSTEM_PROMPT = """
Je bent JARVIS. Enkele stappen van een doel zijn MISLUKT.
Bedenk voor ALLEEN de mislukte stappen een correcte afhandeling.

REGELS:
- Voer NOOIT een stap opnieuw uit die al GESLAAGD is (zie GESLAAGDE STAPPEN).
- Een retry is: dezelfde tool met betere argumenten óf een andere passende tool.
- "Kon '...' niet aan een bestaand Home Assistant apparaat koppelen" betekent:
  het apparaat bestaat niet -> sla die stap over en geef er GEEN nieuwe stap voor.
- Een programma/bestand "niet gevonden": probeer één duidelijke variant, anders
  overslaan.
- Maximaal 4 stappen. Een lege lijst is óók goed (= alles overgeslagen).

KIJS BIJ EEN MISLUKTE STAP EEN ANDERE METHODE (Fase 12):
- Een website "niet gevonden" in de browser: gebruik web_search / web_fetch
  in plaats van browser_search -> misschien staat het antwoord op een andere site.
- Een browser_get_* leest niets (browser niet gevonden): probeer web_fetch(url)
  als het doel een INHOUD-vraag is, óf open eerst het programma met open_program.
- Een open_program mislukking: probeer ui_launch_app met hetzelfde pad.
- Een ui_click_element/ui_type_text mislukking (element niet gevonden): lees eerst
  opnieuw ui_list_elements om de ECHTE naam te zien, verzin NOOIT een knopnaam.
- Opnieuw de ZELFDE tool met dezelfde argumenten is zinloos: kies iets anders.

BESCHIKBARE TOOLS:
{tools}

GESLAAGDE STAPPEN (niet herhalen!):
{succeeded}

MISLUKTE STAPPEN:
{failed}

GEEF ALLEEN JSON terug in dit formaat:
{{"steps": [{{"tool_name": "...", "arguments": {{...}}, "description": "..."}}]}}
Leeg plan wanneer alles zinloos is om opnieuw te proberen:
{{"steps": []}}
"""

# Harde limieten zodat de Agent nooit eindeloos blijft proberen
MAX_PLAN_ITERATIONS = 2        # initiële planning + maximaal 1 herplanning
MAX_PLAN_STEPS = 6
MAX_REPLAN_STEPS = 4


def is_goal(command):
    """
    Detecteert doel-gebaseerde opdrachten (modes/routines) die vragen om
    meerdere acties tegelijk. Bewust conservatief: simpele enkelvoudige
    opdrachten ("open Discord") moeten gewoon door de bestaande
    handlers / ask_ai() blijven gaan.
    """

    text = (command or "").lower().strip()

    goal_patterns = [
        r"^zet mijn pc klaar (om te gamen|voor)\b",
        r"^maak (mijn )?pc klaar (om te gamen|voor)\b",
        r"^activeer\s+(game|film|slaap)\s*modus\b",
        r"^(game|film|slaap)\s*modus\s+aan\b",
    ]

    for pattern in goal_patterns:
        if re.search(pattern, text):
            return True

    return False


# Actiewerkwoorden waarmee multi-actie zinnen starten of delen met elkaar
# worden verbonden ("zet", "doe", "maak", "open", "sluit", "start", "paald", ...).
ACTION_VERBS = (
    "open", "openen", "sluit", "sluiten", "start", "starten", "zet", "zetten",
    "doe", "maak", "maken", "stop", "stoppen", "verplaats", "kopieer",
    "minimaliseer", "vergroot", "herstel", "pauzeer", "demp", "mute",
    "onthoud", "vergeet", "roep", "haal", "schakel", "draai", "zoek",
)

# Structuurwoorden die scheidingen/volgorde in een zin aangeven.
CONNECTOR_WORDS = (
    " en ", " en dan ", " daarna ", " eerst ", " vervolgens ", " dan ",
    " daarna ", " uiteindelijk ", " tenslotte ", " en vervolgens ",
    " en daarna ", " daarnaast ", " tegelijk ", " samen ", ", ",
)

# HA-familienamen zodat gemengde PC + HA zinnen herkend worden.
# Gedeeld met brain/ai (incl. spraak-varianten zoals "bedlam").
from core.home_assistant import HA_DEVICE_WORDS

HA_WORDS = HA_DEVICE_WORDS


def is_multi_step_goal(command):
    """
    Detecteert multi-actie opdrachten met (mogelijk) gemengde PC + HA:
    "Doe mijn lamp aan, zet hem op 40% en open Spotify."
    "Open Discord, zet mijn muziek aan en maak Discord kleiner."

    Bewust conservatief: een enkele actie ("open discord") of een algemene
    vraag ("wat is de hoofdstad") wordt NIET als multi-step doel gezien.
    """

    text = (command or "").strip().lower()
    text = re.sub(r"\s+", " ", text)

    if not text:
        return False

    words = text.split()

    # --- Detail: heeft de zin een komma-scheiding? ---
    has_comma = "," in text

    # --- Telt het aantal actiewerkwoorden ---
    verb_count = sum(1 for v in ACTION_VERBS if f" {v} " in f" {text} ")

    # --- Aantal "objecten" na een werkwoord:
    #     "open discord en spotify" -> 2 objecten (discord, spotify) met 1 werkwoord
    #     We tellen het aantal woorden die GEEN verb/connector/stopwoord zijn.
    #     Simpel: aantal zelfstandige woorden buiten werkwoorden en kleine woorden. ---
    SMALL = set("de het een mijn jouw onze jullie dan en met naar op aan uit in voor om te op het hem haar ze zij die dat zo dan als nadat daarna eerst vervolgens daarnaast ook nu".split())

    meaningful = [w for w in words if w.strip(".,!?") not in SMALL]
    object_units = 0
    # een actie-eenheid = minstens één naamwoord ná een werkwoord of verbindingswoord
    # benaderen: het aantal woorden dat niet-werkwoord en niet-stopwoord is, gedeeld grof
    # is juist voor onze doeleinden een ruwe drempel.

    has_ha_word = any(hw in text for hw in HA_WORDS)
    has_en = " en " in text

    # ====== Regels ======
    # Regel E: één HA-actie met resultaatwoord ("zet de gordijnen open",
    # "doe het licht uit", "maak de lamp zachter") is GEEN multi-doel,
    # zolang er geen "en"/komma (connector) in de zin zit.
    if has_ha_word and not has_en and not has_comma:
        if re.search(r"\b(zet|doe|maak)\b", text) and re.search(
            r"\b(open|dicht|aan|uit|warmer|koeler|koel|warm|zachter|"
            r"helderder|helder|dim|rood|groen|blauw|geel|fel)\b",
            text,
        ):
            return False

    # Regel A: meerdere actiewerkwoorden = multi (open X en sluit Y, etc.)
    if verb_count >= 2:
        return True

    # Regel B: komma met ≥2 zelfstandige eenheden = multi
    if has_comma and len(meaningful) >= 4:
        return True

    # Regel C: één werkwoord met ≥2 duidelijke objecten ("open discord en spotify")
    #          TRUE als er een " en " is en minimaal 2 zelfstandige objecten eromheen.
    if has_en and verb_count >= 1 and len(meaningful) >= 3 and len(words) >= 4:
        return True

    # Regel D: mixed PC + HA met actie, alleen als er écht twee delen in
    # de zin zitten (connector of komma). "open de lamp" is enkelvoudig.
    if has_ha_word and (has_en or has_comma) and verb_count >= 1 and (any(v in text for v in ("open ", "sluit ", "start ", " zet "))):
        return True

    return False


# =========================================================
# PROGRAMMA-ACTIE INTENTIES (algemeen, geen hardcoded zinnen)
# Gebruikt woord-detectie zoals brain.py dat al doet, en vult
# het LLM-plan aan als de LLM een duidelijke actie vergeet.
# =========================================================

# Werkwoorden die een PROGRAMA-actie aangeven. De kaart staat op
# toolnaam -> (werkwoorden, argumenten-key).
PROGRAM_ACTION_INTENTS = {
    "close_program": (
        {"sluit", "sluiten", "afsluiten", "beëindig", "beeindig", "uitzet", "stop"},
        "program",
    ),
    "minimize_window": (
        {"minimaliseer", "minimalizeer", "minimaliseren", "verklein", "verkleinen", "kleiner"},
        "program",
    ),
    "maximize_window": (
        {"maximaliseer", "maximalizeer", "maximaliseren", "vergroot", "vergroten", "groter"},
        "program",
    ),
    "restore_window": (
        {"herstel", "herstellen", "terugzet", "normaal", "uit het klein"},
        "program",
    ),
}

# Woorden die NIET als programma-object mogen worden gezien
# (lidwoorden, voegwoorden, algemene woorden over vensters/apps).
PROGRAM_FILLER = {
    "de", "het", "een", "en", "dan", "daarna", "vervolgens", "met", "naar",
    "op", "aan", "in", "voor", "ook", "dan", "maar", "graag", "even",
    "venster", "vensters", "scherm", "schermen", "programma", "programma's",
    "programmas", "applicatie", "applicaties", "app", "apps", "toepassing",
    "die", "dat", "dit", "hem", "haar", "ze",
    "kun", "kan", "je", "jij", "jou", "jouw", "mijn", "mij", "van", "alle",
    "allemaal", "iedereen", "wat", "zou", "wil", "wilt", "alsjeblieft",
    "svp", "aub", "even", "misschien", "nu", "gelieve", "eerst",
}

# Volume-intentie: "zet het volume op 30".
VOLUME_INTENT_PATTERN = re.compile(
    r"\bvolume\s+(?:op|naar|tot)\s+(?:een\s+)?(\d{1,3})\s*(?:procent|%)?",
    re.IGNORECASE,
)


def _extract_program_action_intents(text):
    """
    Haalt programma-acties uit de zin: bijv. "sluit chrome" -> close_program,
    "vergroot spotify" -> maximize_window, "maak discord kleiner" ->
    minimize_window(discord), "discord sluiten" -> close_program.

    Gebruikt segment-gebaseerde parsing (splitsen op verbindingswoorden)
    i.p.v. broze regex over de hele zin. Geeft een lijst van
    (tool_name, programnaam).
    """

    text = (text or "").strip().lower()

    if not text:
        return []

    # Splits de zin op verbindingswoorden en komma's.
    # Let op: geen \b rond "en" — dat faalt bij spaties aan beide kanten.
    segments = re.split(
        r"\s*(?:(?<=\s)en(?=\s)|,|en dan|en daarna|daarna|vervolgens|dan|eerst|ten slotte|tenslotte)\s*",
        text,
        flags=re.IGNORECASE,
    )

    segments = [s.strip() for s in segments if s.strip()]
    intents = []

    for segment in segments:

        found = _extract_intent_from_segment(segment)

        if found is not None:
            intents.append(found)

    return intents


def _extract_intent_from_segment(segment):
    """Probeert een programma-actie in één segment te herkennen."""

    words = segment.split()

    if not words:
        return None

    # ---- Vorm 1: "werkwoord + programma" ("sluit chrome", "vergroot spotify")
    first = words[0].strip(".,!?")

    for tool_name, (verbs, _arg_key) in PROGRAM_ACTION_INTENTS.items():
        if first in verbs:
            # "vergroot het venster van spotify" -> programma staat na "van"
            if "van" in words:
                van_index = words.index("van")
                program = _clean_program_words(words[van_index + 1:])
            else:
                program = _clean_program_words(words[1:])

            if program:
                return (tool_name, program)

    # ---- Vorm 2: "maak X kleiner/groter/normaal"
    if first == "maak" and len(words) >= 3:
        action = words[-1].strip(".,!?")

        tool_by_word = {
            "kleiner": "minimize_window", "klein": "minimize_window",
            "groter": "maximize_window", "groot": "maximize_window",
            "normaal": "restore_window", "weer": "restore_window",
            "maximaal": "maximize_window",
        }

        if action in tool_by_word:
            program = _clean_program_words(words[1:-1])
            if program:
                return (tool_by_word[action], program)

    # ---- Vorm 3: "programma + werkwoord" ("discord sluiten", "spotify verkleinen")
    last = words[-1].strip(".,!?")

    infinitive_map = {
        "sluiten": "close_program", "afsluiten": "close_program",
        "minimaliseren": "minimize_window", "verkleinen": "minimize_window",
        "maximaliseren": "maximize_window", "vergroten": "maximize_window",
        "herstellen": "restore_window",
    }

    if last in infinitive_map and len(words) >= 2:
        program = _clean_program_words(words[:-1])
        if program:
            return (infinitive_map[last], program)

    return None


def _clean_program_words(words):
    """Filtert stopwoorden/filler uit en geeft 1-2 woorden terug, of None."""

    cleaned = []

    for word in words:
        clean = word.strip(".,!?()") 

        if not clean or clean in PROGRAM_FILLER:
            continue

        cleaned.append(clean)

    if not cleaned:
        return None

    if len(cleaned) >= 2:
        return " ".join(cleaned[:2])

    return cleaned[0]


def _extract_volume_intent(text):
    """Haalt een volume-percentage uit de zin, of None."""

    if not text:
        return None

    match = VOLUME_INTENT_PATTERN.search(text)

    if not match:
        return None

    percent = int(match.group(1))

    if 0 <= percent <= 100:
        return percent

    return None


def augment_plan_with_program_intents(goal, plan):
    """
    Vult een LLM-plan aan met programma-acties die duidelijk in het DOEL
    staan maar ontbreken in het plan (bijv. "sluit chrome", "vergroot
    spotify", "zet het volume op 30").

    Algemeen principe, geen vaste zinnen: elke "werkwoord + programma"
    combinatie uit de intent-tabellen wordt gecontroleerd en toegevoegd.

    Geeft het aangevulde plan terug (nieuwe lijst; wijzigt niets aan input).
    """

    plan = list(plan or [])

    # 1. Reeds aanwezige tools + programma's verzamelen
    covered_close = set()
    covered_windows = set()
    covered_volume = False

    for step in plan:
        tool = step.get("tool_name") or step.get("used_tool_name") or ""
        arguments = step.get("arguments") or {}

        if tool == "close_program":
            covered_close.add((arguments.get("program") or "").lower())

        if tool in ("minimize_window", "maximize_window", "restore_window"):
            covered_windows.add((arguments.get("program") or "").lower())

        if tool in ("set_volume", "volume_up", "volume_down"):
            covered_volume = True

    # 2. Intenties ophalen uit het doel
    intents = _extract_program_action_intents(goal)

    for tool_name, program in intents:
        key = program.lower()

        if tool_name == "close_program":
            if key not in covered_close:
                plan.append({
                    "tool_name": "close_program",
                    "arguments": {"program": program},
                    "status": "pending",
                    "goal": goal,
                })
                covered_close.add(key)

        elif tool_name in ("minimize_window", "maximize_window", "restore_window"):
            if key not in covered_windows:
                # Indien verwijzing stabiel: na een open-programma stap.
                depends_on = _find_open_step_number(plan, key)
                step = {
                    "tool_name": tool_name,
                    "arguments": {"program": program},
                    "status": "pending",
                    "goal": goal,
                }
                if depends_on is not None:
                    step["depends_on"] = [depends_on]

                plan.append(step)
                covered_windows.add(key)

    # 3. Volume-intentie toevoegen als die ontbreekt
    volume = _extract_volume_intent(goal)

    if volume is not None and not covered_volume:
        plan.append({
            "tool_name": "set_volume",
            "arguments": {"percent": volume},
            "status": "pending",
            "goal": goal,
        })

    return plan


def _find_open_step_number(plan, program_key):
    """Zoekt het 1-based stapnummer van een open_program stap voor het
   zelfde programma, zodat een window-actie erafhankelijk kan wachten."""

    for index, step in enumerate(plan, start=1):
        tool = step.get("tool_name") or ""
        arguments = step.get("arguments") or {}

        if tool == "open_program" and (arguments.get("program") or "").lower() == program_key:
            return index

    return None


def _parse_json_object(content):
    """
    Haalt het eerste complete JSON-object uit een LLM-antwoord.
    qwen2.5:3b levert af en toe tekst rond de JSON op, dus fallbacks.

    Geeft dict of None.
    """

    if not content:
        return None

    content = content.strip()

    # Fallback 1: tekst tussen de eerste { en de laatste }
    match = re.search(r"\{.*\}", content, re.DOTALL)

    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback 2: ieder object/array los proberen
    for chunk in re.findall(r"\{[^{}]*\}", content):
        try:
            return json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def _live_ha_devices():
    """
    Haalt de échte smart-home apparaatlijst op voor de plan-context.

    Geeft een compacte tekst of een vervangende regel, nooit een exception.
    """

    try:
        text = get_home_assistant_entities_tool(domain=None)

        if not isinstance(text, str) or not text.strip():
            return "SMART-HOME: geen apparaten gevonden."

        if "niet geconfigureerd" in text.lower() or "geen" in text.lower():
            return "SMART-HOME: niet beschikbaar (geen Home Assistant of geen apparaten)."

        return text

    except Exception as error:
        print(f"⚠️ Agent: HA-lijst ophalen mislukt ({error}).")
        return "SMART-HOME: niet beschikbaar."


def _join_names(names):
    """'Discord, Spotify en Steam' in natuurlijk Nederlands."""

    names = [str(name).strip() for name in names if str(name).strip()]

    if not names:
        return ""

    if len(names) == 1:
        return names[0]

    if len(names) == 2:
        return f"{names[0]} en {names[1]}"

    return ", ".join(names[:-1]) + " en " + names[-1]


class Agent:
    """Taak-gebaseerde assistent bovenop de bestaande Planner/Executor."""

    def __init__(self):
        # Fase 4: onthoud de laatst geslaagde acties, zodat de
        # gebruiker ze als routine kan opslaan ("bewaar dit als routine x").
        self.last_executed_steps = []

    def run_goal(self, goal):
        """
        Hoofdloop: plan -> uitvoeren -> (max 1 herplanting) -> eindantwoord.

        Resultaten worden over de iteraties heen bijgehouden, zodat een
        geslaagde stap na een herplanting nooit verloren gaat.
        """

        reset_touch_usage()
        goal = goal.strip().lower()
        print(f"🤖 Agent start voor doel: {goal}")

        plan = self._generate_plan(goal)

        if plan is None:
            return "Ik kon geen plan maken voor die opdracht. Probeer het anders te formuleren."

        if not plan:
            return "Ik begrijp het doel, maar ik zie geen concreet haalbare stappen. Kun je het anders formuleren?"

        print(f"🛠️ Agent maakt een plan met {len(plan)} stappen.")

        all_done = []
        last_failed = []
        all_skipped = []

        for iteration in range(MAX_PLAN_ITERATIONS):

            results = self._execute_plan(plan, goal)

            all_done.extend(r for r in results if r["status"] == "done")
            last_failed = [r for r in results if r["status"] == "failed"]
            all_skipped.extend(r for r in results if r["status"] == "skipped")

            if not last_failed:
                print("✅ Agent: alle stappen geslaagd.")
                break

            if iteration >= MAX_PLAN_ITERATIONS - 1:
                print(f"⚠️ Agent: {len(last_failed)} stap(pen) blijft mislukken; stop.")
                break

            plan = self._replan(goal, last_failed, all_done)

            if not plan:
                print("ℹ️ Agent: herplanning gaf geen nieuwe stappen; klaar.")
                break

        all_done = self._dedupe_done(all_done)

        # Fase 4: bewaar de geslaagde stappen zodat de gebruiker ze
        # als routine kan opslaan.
        self.last_executed_steps = [
            {
                "tool_name": tool,
                "arguments": r.get("arguments") or {},
            }
            for r in all_done
            if (tool := (r.get("used_tool_name") or r.get("tool_name")))
        ]

        # Verificatie-slag (Fase 2): deterministisch controleren of het doel
        # werkelijk bereikt is. Geen LLM: alleen feitelijke status van stappen.
        detected_gap_summary = self._verify_goal(all_done, last_failed, all_skipped)

        answer = self._generate_response(goal, all_done, last_failed, detected_gap_summary)

        self._finish_goal(goal, answer)

        return answer

    def _dedupe_done(self, records):
        """Verwijdert dubbele geslaagde stappen (zelfde tool + argumenten)."""

        seen = set()
        unique = []

        for record in records:
            tool = record.get("used_tool_name") or record.get("tool_name")
            arguments = record.get("arguments") or {}
            key = (tool, json.dumps(arguments, sort_keys=True, default=str))

            if key in seen:
                continue

            seen.add(key)
            unique.append(record)

        return unique

    # -----------------------------------------------------
    # PLANNEN (LLM + live HA-data)
    # -----------------------------------------------------

    def _generate_plan(self, goal):
        """Breekt het doel op in een structuro plan via de LLM."""

        # Context + langetermijngeheugen in één blok (Fase 14, Stap 6).
        combined = build_memory_context(
            goal,
            context=current_context,
            history=conversation_history,
        ) or memory_summary()

        messages = [
            {
                "role": "system",
                "content": PLANNING_SYSTEM_PROMPT.format(
                    tools=TOOL_LIST_TEXT,
                    ha_devices=_live_ha_devices(),
                ),
            },
            {"role": "system", "content": combined},
            {"role": "user", "content": goal},
        ]

        try:
            response = ollama.chat(model=MODEL, messages=messages, format="json")
        except Exception as error:
            print(f"⚠️ Agent plan-fout: {error}")
            return None

        data = _parse_json_object(response.message.content or "")

        if not isinstance(data, dict):
            print("⚠️ Agent: plan-antwoord was geen JSON-object.")
            return None

        plan = self._normalize_steps(
            data.get("steps"), goal, max_steps=MAX_PLAN_STEPS
        )

        # Fase 2: duidelijke programma-acties ("sluit chrome", "vergroot
        # spotify") aanvullen als het kleine LLM de stap vergeet.
        plan = augment_plan_with_program_intents(goal, plan)

        return plan

    def _normalize_steps(self, raw_steps, goal, max_steps=MAX_PLAN_STEPS):
        """
        Zet de LLM-stappen om naar het planformaat van de Executor.
        Onbekende tools (hallucinaties) worden overgeslagen (Fase 9-principe).
        """

        plan = []

        if not isinstance(raw_steps, list):
            return plan

        for step in raw_steps[:max_steps]:

            if not isinstance(step, dict):
                continue

            tool_name = str(step.get("tool_name") or "").strip()

            if tool_name not in VALID_TOOL_NAMES:
                print(f"⚠️ Agent: onbekende tool '{tool_name}' overgeslagen.")
                continue

            arguments = step.get("arguments")
            arguments = dict(arguments) if isinstance(arguments, dict) else {}

            # Optionele metadata voor de Executor (Fase 2):
            # - depends_on   : lijst van 1-based stapnummers die eerst moeten slagen
            # - wait_seconds : wachttijd vóór uitvoering
            # - condition    : simpele voorwaarde op een eerdere stap
            step_meta = {}
            depends_on = step.get("depends_on")

            if isinstance(depends_on, int) and depends_on > 0:
                step_meta["depends_on"] = [depends_on]

            elif isinstance(depends_on, (list, tuple)):
                valid = [d for d in depends_on if isinstance(d, int) and d > 0]
                if valid:
                    step_meta["depends_on"] = valid

            wait = step.get("wait_seconds")
            if isinstance(wait, (int, float)) and wait > 0:
                step_meta["wait_seconds"] = float(wait)

            condition = step.get("condition")
            if isinstance(condition, dict):
                step_meta["condition"] = condition

            plan.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "pending",
                "goal": goal,
                **step_meta,
            })

        return plan

    # -----------------------------------------------------
    # UITVOEREN (bestaande Executor)
    # -----------------------------------------------------

    def _execute_plan(self, plan, goal):
        """Voert het plan uit via de bestaande Executor."""

        try:
            return execute_action_plan(plan, goal)
        except Exception as error:
            print(f"⚠️ Agent uitvoerfout: {error}")

            return [
                {
                    "tool_name": step.get("tool_name"),
                    "arguments": step.get("arguments"),
                    "status": "failed",
                    "result": f"Uitvoerfout: {error}",
                    "verdict": "failed",
                    "attempts": 0,
                    "errors": [str(error)],
                    "results": [],
                    "needs_approval": False,
                    "risk": "low",
                    "used_tool_name": step.get("tool_name"),
                }
                for step in plan
            ]

    # -----------------------------------------------------
    # HERPLANNEN (LLM) — één keer bij mislukking
    # -----------------------------------------------------

    def _replan(self, goal, failed_steps, succeeded_steps):
        """
        Vraagt de LLM een correcte afhandeling voor de mislukte stappen.

        succeeded_steps wordt meegegeven zodat nooit iets herhaald wordt.
        Een leeg plan uit de LLM betekent: overslaan.
        """

        succeeded_lines = "\n".join(
            f"- {r.get('used_tool_name') or r.get('tool_name')} met "
            f"{r.get('arguments')}"
            for r in succeeded_steps
        ) or "- (geen)"

        failure_lines = "\n".join(
            f"- {r.get('used_tool_name') or r.get('tool_name')} met "
            f"{r.get('arguments')}\n"
            f"  Reden: {str(r.get('result'))[:200]}"
            + (f"\n  AL GEPROBEERD via fallback: {r.get('fallback_used')}" if r.get("fallback_used") else "")
            for r in failed_steps
        )

        messages = [
            {
                "role": "system",
                "content": REPLANNING_SYSTEM_PROMPT.format(
                    tools=TOOL_LIST_TEXT,
                    succeeded=succeeded_lines,
                    failed=failure_lines,
                ),
            },
            {"role": "user", "content": f"Doel: {goal}"},
        ]

        try:
            response = ollama.chat(model=MODEL, messages=messages, format="json")
        except Exception as error:
            print(f"⚠️ Agent herplan-fout: {error}")
            return None

        data = _parse_json_object(response.message.content or "")

        if not isinstance(data, dict):
            print("⚠️ Agent: herplan-antwoord was geen JSON-object.")
            return None

        replan = self._normalize_steps(
            data.get("steps"), goal, max_steps=MAX_REPLAN_STEPS
        )

        # Fase 2: ook bij herplanning duidelijke programma-acties aanvullen.
        return augment_plan_with_program_intents(goal, replan)

    # -----------------------------------------------------
    # EINDRESULTAAT (deterministisch, geen succes zonder bewijs)
    # -----------------------------------------------------

    def _verify_goal(self, succeeded, failed, skipped):
        """
        Fase 2 verificatie-slag (deterministisch, geen LLM).

        Controleert aan de hand van de FEITELIJKE stapstatussen of het doel
        volledig bereikt is:
        - alles geslaagd en niets overgeslagen  -> None (doel bereikt)
        - stappen overgeslagen (dependency failure) -> eerlijke melding
        - mislukte stappen -> None (die worden al in de samenvatting gemeld)

        Geeft None of een korte, feitelijke Nederlandse zin.
        """

        skipped_names = []
        for record in skipped:
            tool = record.get("tool_name") or record.get("used_tool_name") or ""
            arguments = record.get("arguments") or {}
            label = arguments.get("program") or arguments.get("filename") or arguments.get("url") or ""

            if tool == "control_home_assistant":
                label = arguments.get("entity_id") or arguments.get("domain") or ""

            skipped_names.append(label or tool.replace("_", " "))

        if skipped_names:
            unique = list(dict.fromkeys(skipped_names))
            if len(unique) == 1:
                return f"Let op: {unique[0]} is niet uitgevoerd omdat een eerdere stap mislukte."
            return f"Let op: {', '.join(unique[:-1])} en {unique[-1]} zijn niet uitgevoerd omdat een eerdere stap mislukte."

        # Alles geslaagd en niets overgeslagen = doel bereikt.
        return None

    def _generate_response(self, goal, succeeded, failed, gap=None):
        """Bouwt een kort, eerlijk Nederlands eindantwoord."""

        lead = self._lead_phrase(goal)
        parts = [lead]

        done_text = self._summarize_done(succeeded)

        if done_text:
            parts.append(done_text)

        failed_text = self._summarize_failed(failed)

        if failed_text:
            parts.append(failed_text)

        if gap:
            parts.append(gap)

        return " ".join(parts).rstrip()

    def _summarize_done(self, records):
        """Vat geslaagde stappen samen op basis van tool + argumenten."""

        opened = []
        closed = []
        volumes = []
        media = []
        ha_actions = []
        other = []

        for record in records:
            tool = record.get("used_tool_name") or record.get("tool_name")
            arguments = record.get("arguments") or {}

            if tool == "open_program":
                if arguments.get("program"):
                    opened.append(arguments["program"])
            elif tool == "close_program":
                if arguments.get("program"):
                    closed.append(arguments["program"])
            elif tool == "set_volume":
                volumes.append(arguments.get("percent"))
            elif tool == "volume_up":
                volumes.append("omhoog")
            elif tool == "volume_down":
                volumes.append("omlaag")
            elif tool == "media_mute":
                media.append("muziek gedempt")
            elif tool == "media_stop":
                media.append("muziek gestopt")
            elif tool == "media_play_pause":
                media.append("media afgespeeld of gepauzeerd")
            elif tool == "media_next":
                media.append("volgend nummer afgespeeld")
            elif tool == "media_previous":
                media.append("vorig nummer afgespeeld")
            elif tool == "control_home_assistant":
                ha_actions.append(arguments.get("entity_id") or "een apparaat")
            elif tool in NOISE_TOOLS:
                continue          # ruis niet vermelden (screenshot/system_info/...)
            elif tool == "open_website":
                other.append(f"website {arguments.get('url')} geopend")
            elif tool == "open_file":
                other.append(f"bestand {arguments.get('filename')} geopend")
            elif tool in ("minimize_window", "maximize_window", "restore_window"):
                if arguments.get("program"):
                    other.append(f"{arguments['program']} aangepast")
            else:
                if tool:
                    other.append(tool.replace("_", " "))

        sentences = []

        if opened:
            sentences.append(f"Ik heb {_join_names(opened)} geopend.")

        if closed:
            sentences.append(f"{_join_names(closed)} zijn gesloten.")

        if volumes:
            unique_volumes = list(dict.fromkeys(str(v) for v in volumes))
            if len(unique_volumes) == 1:
                value = unique_volumes[0]
                sentences.append(
                    f"Volume is {value} gezet." if value in ("omhoog", "omlaag")
                    else f"Volume staat op {value}%."
                )
            else:
                raw = ", ".join(unique_volumes)
                sentences.append(f"Volume is aangepast ({raw}).")

        if media:
            sentences.append(", ".join(media) + ".")

        if ha_actions:
            sentences.append("Je smart-home apparaten zijn bijgewerkt.")

        if other:
            sentences.append(_join_names(other) + ".")

        return " ".join(sentences) if sentences else ""

    def _summarize_failed(self, records):
        """Bouwt een korte, eerlijke zin over mislukte stappen."""

        if not records:
            return ""

        failed_names = []
        reasons = []

        for record in records:
            tool = record.get("used_tool_name") or record.get("tool_name")
            arguments = record.get("arguments") or {}
            name = None

            if tool == "open_program":
                name = arguments.get("program")
            elif tool == "close_program":
                name = arguments.get("program")
            elif tool == "control_home_assistant":
                suffix = " aan" if arguments.get("service") in ("turn_on", "toggle") else ""
                name = f"het apparaat {arguments.get('entity_id')}"
            elif tool == "open_website":
                name = f"de website {arguments.get('url')}"

            failed_names.append(name if name else (tool or "onbekende stap").replace("_", " "))

            result = str(record.get("result") or "").strip()
            if result and len(result) < 140:
                reasons.append(result)

        base = f"Dit lukte niet: {_join_names(failed_names)}."

        if reasons:
            first_reason = reasons[0]
            base += f" ({first_reason})" if len(base) + len(first_reason) < 200 else ""

        return base

    def _lead_phrase(self, goal):
        """Opent het antwoord met een passende, korte slotzin."""

        text = goal.lower()

        if "film" in text:
            return "Alles staat klaar voor de film."
        if "slaap" in text or "slapen" in text:
            return "Slaapmodus is ingesteld."
        if "gamen" in text or "gaming" in text or "game" in text:
            return "Je pc staat klaar om te gamen."
        if "muziek" in text:
            return "Alles staat klaar voor de muziek."
        if "werk" in text:
            return "Alles staat klaar voor je werk."

        return "Klaar."

    def _finish_goal(self, goal, answer):
        """Zet context bij en slaat het gesprek op (hooks in ai.py)."""

        update_context(
            last_command=goal,
            last_result=answer,
            last_action="doel uitgevoerd",
        )

        add_to_history("user", goal)
        add_to_history("assistant", answer)