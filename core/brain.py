import os
import re
import time

from core.calculator import calculate
from core.information import get_information
from core.ai import ask_ai, update_context, current_context, format_results, remember_from_question
from core.home_assistant import (
    has_ha_reference,
    is_ha_device_action,
    extract_color_hs,
    control_home_assistant_tool,
)
from core.tools import open_program_tool, close_program_tool
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
from actions.pc import minimize_program, maximize_program, restore_window
from actions.system import (
    cpu_info,
    ram_info,
    disk_info,
    gpu_names,
    battery_info,
    os_info,
    uptime,
    system_summary,
)
from actions.screenshot import take_screenshot
from actions.power import (
    lock_pc,
    sleep_pc,
    shutdown_pc,
    restart_pc,
    logoff_pc,
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
)
from memory.memory import remember, forget, clear_memory, get_all_memory, get_category_memory, beautify


SKIP_PARSE_WORDS = {
    "sluit", "sluiten", "stop", "stoppen", "zet", "doe", "maak", "uit",
    "dicht", "afsluiten", "af", "beëindig", "beëindigen", "uitzetten",
    "open", "openen", "start", "starten", "lanceer", "ga",
    "graag", "even", "aub", "alsjeblieft", "svp", "nu",
    "het", "de", "een", "en", "of", "dan", "me", "mij", "je", "jou",
    "jij", "jouw", "mijn", "u", "uw", "kan", "kun", "kunnen", "zou",
    "eens", "maar", "weer", "nog", "alle", "allemaal", "alles", "beide",
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


SMART_HOME_WORDS = (
    "lamp", "lampen", "licht", "lichten", "stekker", "stekkers",
    "sensor", "sensors", "schakelaar", "schakelaars", "shutter",
    "shutters", "thermostaat", "klimaat", "fan", "ventilator",
    "humidifier", "vacuum", "stofzuiger", "speaker", "speakers",
    "media player", "camera", "deurbel", "lampje", "ledstrip",
    "led strip", "spot", "spots", "rolluik", "rolluiken",
)


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

    # "speel muziek" hoort bij de PC-mediaspeler, niet bij HA.
    if "muziek" in question and "speaker" not in question and "speakers" not in question:
        return None

    # Een opdracht die duidelijk om een PC-actie vraagt (bijv. "open
    # lamp.exe", "toon mijn map lamp") moet niet naar HA worden gestuurd
    # en blijft bij de bestaande PC-routes terechtkomen.
    if has_intent(question, OTHER_ACTION_PATTERNS):
        if any(word in question for word in (
            "open", "start", "lanceer", "toon", "zoek", "bestand",
            "map", "programma",
        )):
            return None

    # Zonder expliciete aan/uit/status-actie is het een HA-vraag naar
    # beschikbare apparaten of status -> ook naar de AI-route.
    return ask_ai(command)


# Kleurtemperatuur in kelvin voor "warmer" (lagere kelvin = warmer licht)
# en "koeler" (hogere kelvin = koeler licht).
_WARMER_COLOR_TEMP = 3000
_KOELER_COLOR_TEMP = 5000


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

    # Kleurtemperatuur: "maak hem warmer" / "maak die koeler".
    if service is None:

        if re.search(r"\b(warmer)\b", command):
            service = "turn_on"
            service_data["color_temp"] = _WARMER_COLOR_TEMP
        elif re.search(r"\b(koeler|kouder)\b", command):
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

    # Meerdere programma's tegelijk openen (bijv. "Open Discord en Spotify")
    if is_multi_command(command):

        names = extract_program_names(command)

        # Alleen deterministisch als ALLE genoemde namen exacte
        # programma's zijn; anders laat de AI het afhandelen.
        if names and all(find_program(name, exact_only=True) for name in names):

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


def try_media_command(command):

    question = command.lower().strip()

    # Volume op een exact percentage: "zet volume op 30"
    match = re.search(r"\bvolume\s+(?:op|naar)\s+(\d{1,3})\s*(?:%|procent)?", question)

    if match:
        percent = int(match.group(1))

        if 0 <= percent <= 100:
            return set_volume(percent)

    # Volume omhoog
    if any(word in question for word in [
        "volume omhoog", "volume hoger", "volume hard", "harder", "luider",
    ]):
        return volume_up()

    # Volume omlaag
    if any(word in question for word in [
        "volume omlaag", "volume lager", "volume zacht", "zachter",
        "stiller", "still",
    ]):
        return volume_down()

    # Dempen / geluid aan
    if any(word in question for word in [
        "demp", "demp het geluid", "mute", "muteer", "geluid uit",
        "geluid aan", "zet het geluid uit", "zet het geluid aan",
    ]):
        return toggle_mute()

    # Pauzeren
    if any(word in question for word in [
        "pauzeer", "pauze", "pauseren", "pause",
        "zet muziek uit", "stop de muziek", "muziek stop",
    ]):
        return play_pause()

    # Afspelen / hervatten
    if any(word in question for word in [
        "speel verder", "speel weer", "speel door", "hervat",
        "play", "speel muziek", "speel de muziek", "zet muziek aan",
        "muziek aan", "start de muziek",
    ]):
        return play_pause()

    # Volgend nummer
    if any(word in question for word in [
        "volgende", "volgende nummer", "volgende track", "volgende song",
        "volgende liedje", "skip", "naar het volgende",
    ]):
        return next_track()

    # Vorig nummer
    if any(word in question for word in [
        "vorige", "vorige nummer", "vorige track", "vorige song",
        "vorige liedje", "terug naar het vorige",
    ]):
        return previous_track()

    return None


def try_system_info(command):

    question = command.lower().strip()

    # Volledige systeeminformatie
    if any(word in question for word in [
        "systeeminformatie", "systeeminfo",
        "wat voor pc heb ik", "wat voor computer heb ik",
    ]) or (
        "overzicht" in question
        and any(word in question for word in ["pc", "computer", "systeem"])
    ):
        return system_summary()

    # Processor
    if any(word in question for word in [
        "wat is mijn cpu", "welke cpu", "welke processor",
        "wat voor processor", "wat is mijn processor",
    ]):
        info = cpu_info()
        return (
            f"Je hebt een {info['naam']} met {info['cores']} cores "
            f"en {info['threads']} threads."
        )

    # RAM / geheugen
    if re.search(r"(hoeveel|wat).*\bram\b", question) or "geheugen" in question:
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
        gpus = gpu_names()
        if len(gpus) == 1:
            return f"Je videokaart is een {gpus[0]}."
        return f"Je videokaarten zijn: {', '.join(gpus)}."

    # Schijfruimte
    if any(word in question for word in [
        "schijfruimte", "hoeveel ruimte", "hoeveel vrije ruimte",
        "hoeveel vrij", "hoeveel opslag",
    ]):
        info = disk_info()
        return (
            f"Op je C-schijf is {info['vrij']} GB vrij van de "
            f"{info['totaal']} GB."
        )

    # Batterij
    if "batterij" in question:
        battery = battery_info()

        if not battery:
            return "Deze computer heeft geen batterij."

        if battery["stekker"]:
            return f"Je batterij staat op {battery['percentage']}% en de pc hangt aan de stroom."

        return f"Je batterij staat op {battery['percentage']}% en de pc draait op de accu."

    # Windows-versie
    if "windows" in question or "besturingssysteem" in question:
        info = os_info()
        return f"Je draait {info['systeem']} {info['release']}."

    # Uptime
    if any(word in question for word in [
        "hoe lang staat", "hoelang staat", "hoe lang staat hij",
        "uptime", "hoe lang is de pc aan",
    ]):
        duration = uptime()
        return (
            f"Je pc staat al {duration['dagen']} dagen, {duration['uren']} "
            f"uur en {duration['minuten']} minuten aan."
        )

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


def _apply_window_action(action, target):

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

    open_result = open_program_tool(program)

    window_result = _apply_window_action(action, target)

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

    path = take_screenshot()

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

        update_context(
            pending_choice={
                "kind": "delete_confirm",
                "name": delete_name,
                "matches": found,
            }
        )

        return (
            f"Zal ik '{os.path.basename(found[0])}' naar de prullenbak sturen? "
            "Zeg 'ja' of 'nee'."
        )

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

    if state == "minimize":
        return minimize_program(program)

    if state == "maximize":
        return maximize_program(program)

    return restore_window(program)


def try_remember(command):

    if not any(word in command for word in ["onthoud", "bewaar"]):
        return None

    return remember_from_question(command)


def auto_remember(command):

    question = command.lower()

    # "mijn favoriete X is Y"
    match = re.search(r"mijn favoriete ([a-z]+) is (.+)", question)
    if match:
        name = match.group(1).strip()
        value = match.group(2).strip(" .!?")
        remember(f"favoriete_{name}", value)
        return f"Ik onthoud dat je favoriete {name} {value} is."

    # "mijn lievelings X is Y"
    match = re.search(r"mijn lievelings ([a-z]+) is (.+)", question)
    if match:
        name = match.group(1).strip()
        value = match.group(2).strip(" .!?")
        remember(f"lievelings_{name}", value)
        return f"Ik onthoud dat je lievelings-{name} {value} is."

    # PC-specificaties: "mijn gpu is X"
    match = re.search(
        r"mijn (gpu|grafische kaart|videokaart|ram|geheugen|cpu|processor|ssd|scherm|monitor) is (.+)",
        question
    )
    if match:
        name = match.group(1).strip()
        value = match.group(2).strip(" .!?")
        remember(name, value)
        return f"Ik onthoud dat je {name} {value} is."

    # "mijn naam is X" / "ik heet X"
    match = re.search(r"(?:mijn naam is|ik heet) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        remember("naam", value)
        return f"Ik onthoud dat je naam {value} is."

    # "mijn leeftijd is X" / "ik ben X jaar"
    match = re.search(r"(?:mijn leeftijd is|ik ben) (\d+) jaar", question)
    if match:
        value = match.group(1)
        remember("leeftijd", value)
        return f"Ik onthoud dat je leeftijd {value} jaar is."

    # "mijn woonplaats is X" / "ik woon in X"
    match = re.search(r"(?:mijn woonplaats is|ik woon in|ik woon te) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        remember("woonplaats", value)
        return f"Ik onthoud dat je woonplaats {value} is."

    # "mijn project is X" / "ik werk aan X"
    match = re.search(r"(?:mijn project is|ik werk aan) (.+)", question)
    if match:
        value = match.group(1).strip(" .!?")
        remember("project", value)
        return f"Ik onthoud dat je project {value} is."

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
            return f"Je favoriete game is {beautify(favorite_game)}. Zal ik die voor je openen?"

        return None

    # "speel muziek" / "zet muziek aan"
    if "muziek" in question:
        music = get_category_memory("muziek")

        if music:
            first_key, first_value = next(iter(music.items()))
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

    memory = get_all_memory()

    topic_norm = topic.replace(" ", "_")

    for key in memory:

        stored = key.lower()

        if stored == topic_norm or stored == topic or topic_norm in stored or stored in topic_norm:

            forget(key)
            return f"Ik heb {key.replace('_', ' ')} vergeten."

    # Nog een poging: losse woorden van het onderwerp
    words = topic.split()

    if len(words) > 1:

        for word in words:

            if len(word) < 3:
                continue

            for key in memory:

                if word in key.lower():

                    forget(key)
                    return f"Ik heb {key.replace('_', ' ')} vergeten."

    return None


def _resolve_pending_choice(pending, chosen):

    kind = pending.get("kind", "list")

    if kind == "copy":
        return copy_path(chosen, pending["destination"])

    if kind == "move":
        return move_path(chosen, pending["destination"])

    if kind == "delete_choose":
        update_context(
            pending_choice={
                "kind": "delete_confirm",
                "name": pending["name"],
                "matches": [chosen],
            }
        )
        return (
            f"Zal ik '{os.path.basename(chosen)}' naar de prullenbak sturen? "
            "Zeg 'ja' of 'nee'."
        )

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


def _is_yes(question):

    question = question.strip().strip(" .!?")

    if question in YES_WORDS:
        return True

    return bool(re.match(
        r"^(ja|jazeker|jawel|jep|jup|yep|yes|tuurlijk|natuurlijk|prima|goed|oke|ok)\b",
        question
    ))


def _is_no(question):

    question = question.strip().strip(" .!?")

    if question in NO_WORDS:
        return True

    return bool(re.match(r"^(nee|nope|niet)\b", question))


POWER_ACTIONS = {
    "lock": lock_pc,
    "sleep": sleep_pc,
    "shutdown": shutdown_pc,
    "restart": restart_pc,
    "logoff": logoff_pc,
}


def handle_pending_choice(command):

    pending = current_context.get("pending_choice")

    if not pending:
        return None

    question = command.lower().strip()

    kind = pending.get("kind")

    # Bevestiging: "ja" / "nee"
    if kind in ("delete_confirm", "empty_confirm", "power_confirm"):

        if _is_yes(question):

            update_context(pending_choice=None)

            if kind == "delete_confirm":
                return send_to_recycle(pending["matches"][0])

            if kind == "empty_confirm":
                return empty_recycle_bin()

            return POWER_ACTIONS[pending["action"]]()

        if _is_no(question):

            update_context(pending_choice=None)
            return "Oké, ik doe het niet."

        return "Zeg 'ja' als ik het moet doen, of 'nee' om te stoppen."

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

    has_pc_word = any(word in question for word in PC_WORDS)

    action = None

    # Vergrendelen
    if any(word in question for word in [
        "vergrendel", "vergrendelen", "op slot", "lock de pc", "lock pc",
    ]):
        action = "lock"

    # Slaapstand
    elif any(word in question for word in [
        "slaapstand", "in slaap zetten", "naar de slaap",
    ]) or ("slaap" in question and has_pc_word):
        action = "sleep"

    # Afmelden / uitloggen
    elif any(word in question for word in ["log uit", "afmelden", "uitloggen", "logoff"]):
        action = "logoff"

    # Herstarten
    elif any(word in question for word in ["herstart", "herstarten", "reboot", "opnieuw opstarten"]):
        action = "restart"

    # Afsluiten: alleen met een pc-woord erbij, zodat "sluit spotify af"
    # gewoon het programma-sluiten blijft
    elif has_pc_word and (
        any(word in question for word in ["afsluiten", "shutdown", "uitzetten", "uit zetten"])
        or re.search(r"(?:sluit|zet)\s+(?:de\s+|mijn\s+|je\s+)?(?:pc|computer|laptop|systeem)\s+(?:af|uit)\b", question)
        or re.search(r"(?:pc|computer|laptop|systeem)\s+(?:uit|af)\b", question)
    ):
        action = "shutdown"

    if not action:
        return None

    labels = {
        "lock": "de pc vergrendelen",
        "sleep": "de pc in slaapstand zetten",
        "shutdown": "de pc afsluiten",
        "restart": "de pc herstarten",
        "logoff": "je afmelden",
    }

    update_context(
        pending_choice={
            "kind": "power_confirm",
            "action": action,
        }
    )

    return f"Zal ik {labels[action]}? Zeg 'ja' of 'nee'."


def process_command(command):

    command = command.lower().strip()

    print(f"🧠 Brain kreeg: {command}")

    # =========================
    # WACHTENDE KEUZE (Fase 6)
    # =========================

    pending_answer = handle_pending_choice(command)

    if pending_answer:
        return pending_answer


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
    # SYSTEEMINFO (Fase 6)
    # =========================

    system_result = try_system_info(command)

    if system_result is not None:
        return system_result


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
    # PC-ACTIES (Fase 6)
    # =========================

    power_result = try_power_command(command)

    if power_result is not None:
        return power_result


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

    if any(word in command for word in [
        "hallo",
        "hoi",
        "goedemorgen",
        "goedemiddag",
        "goedenavond"
    ]):
        return "Hallo Rushil. Waarmee kan ik je helpen?"

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
        return ask_ai(command)

    except Exception as error:

        print(f"⚠️ AI-fout: {error}")

        return "Er ging iets mis bij het verwerken van je opdracht."
