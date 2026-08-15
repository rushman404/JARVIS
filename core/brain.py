import re

from core.calculator import calculate
from core.information import get_information
from core.ai import ask_ai, update_context, current_context, format_results, remember_from_question
from core.tools import open_program_tool, close_program_tool
from actions.program_finder import find_program
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
            "de tijd en datum vertellen, en gewoon een gesprek met je voeren."
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


def process_command(command):

    command = command.lower().strip()

    print(f"🧠 Brain kreeg: {command}")

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
    # INFO VERGETEN (Fase 4)
    # =========================

    forget_result = try_forget(command)

    if forget_result is not None:
        return forget_result


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
