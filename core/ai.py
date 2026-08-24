import re
import json
import os
import ollama

from core.tools import open_file_tool
from core.tools import open_website_tool
from core.tools import open_program_tool
from core.tools import remember_tool
from core.tools import recall_tool
from core.tools import forget_tool
from core.tools import close_program_tool
from core.tools import (
    media_play_pause_tool,
    media_next_tool,
    media_previous_tool,
    media_volume_up_tool,
    media_volume_down_tool,
    media_set_volume_tool,
    media_mute_tool,
)
from core.tools import system_info_tool
from core.tools import screenshot_tool
from core.tools import (
    minimize_window_tool,
    maximize_window_tool,
    restore_window_tool,
)
from core.tools import (
    create_folder_tool,
    create_file_tool,
    list_files_tool,
    copy_file_tool,
    move_file_tool,
)
from memory.memory import memory_summary, remember, recall, beautify
from core.planner import make_action_plan, describe_plan
from core.executor import execute_action_plan


MODEL = "qwen2.5:3b"

# =========================================================
# GESPREKSGEHEUGEN (bewaard ná herstart, Fase 4)
# =========================================================

CONVERSATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memory",
    "conversation.json"
)

# Hoeveel berichten JARVIS maximaal onthoudt
MAX_HISTORY = 10


def _load_conversation():

    try:
        with open(CONVERSATION_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        history = data.get("history", [])[-MAX_HISTORY:]
        context = data.get("context", {})

        return history, context

    except (json.JSONDecodeError, OSError, AttributeError):
        return [], {}


def _save_conversation():

    try:
        with open(CONVERSATION_FILE, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "history": conversation_history,
                    "context": current_context,
                },
                file,
                indent=4,
                ensure_ascii=False
            )

    except OSError as error:
        print(f"⚠️ Kon het gesprek niet opslaan: {error}")


# =========================================================
# TIJDELIJK GESPREKSGEHEUGEN (geladen uit bestand)
# =========================================================

conversation_history, _saved_context = _load_conversation()

# =========================================================
# LAATSTE CONTEXT
# =========================================================

current_context = {
    "last_command": "",
    "last_result": "",
    "last_action": "",
    "last_calculation": "",
    "last_program": "",
    "last_file": "",
    "last_website": "",
    "pending_choice": None
}

current_context.update(_saved_context)


def update_context(**kwargs):

    for key, value in kwargs.items():

        if key in current_context:
            current_context[key] = value

    _save_conversation()


def get_context():

    context = []

    if current_context["last_command"]:
        context.append(
            f"Laatste opdracht: {current_context['last_command']}"
        )

    if current_context["last_result"]:
        context.append(
            f"Laatste resultaat: {current_context['last_result']}"
        )

    if current_context["last_action"]:
        context.append(
            f"Laatste actie: {current_context['last_action']}"
        )

    if current_context["last_calculation"]:
        context.append(
            f"Laatste berekening: {current_context['last_calculation']}"
        )

    if current_context["last_program"]:
        context.append(
            f"Laatste programma: {current_context['last_program']}"
        )

    if current_context["last_file"]:
        context.append(
            f"Laatste bestand: {current_context['last_file']}"
        )

    if current_context["last_website"]:
        context.append(
            f"Laatste website: {current_context['last_website']}"
        )

    return "\n".join(context)


def add_to_history(role, content):

    conversation_history.append({
        "role": role,
        "content": content
    })

    # Houd alleen de laatste berichten
    if len(conversation_history) > MAX_HISTORY:
        del conversation_history[0]

    _save_conversation()


def is_action_request(question):

    question = question.lower().strip()

     # Vragen over de huidige sessie zijn normale contextvragen
    context_words = [
        "laatste programma",
        "laatst geopende programma",
        "laatste geopende programma",
        "wat heb ik net geopend",
        "wat heb ik zojuist geopend",
        "wat heb ik net gestart",
        "wat heb ik zojuist gestart"
    ]

    if any(word in question for word in context_words):
        return False

    action_words = [
        "open",
        "start",
        "lanceer",
        "ga naar",

        # Venster-acties via verwijzingen ("maak hem kleiner")
        "kleiner",
        "verklein",
        "groter",
        "herstel",
        "bezoek",
        "toon",
        "zoek mijn",
        "zoek het bestand",
        "speel",

        "sluit",
        "beëindig",
        "stop het programma",
        "afsluiten",

        "onthoud",
        "bewaar",
        "vergeet",

        "wat weet je",
        "wat heb ik je verteld",
        "wat is mijn",
        "wat zijn mijn",
        "wat was mijn",
        "herinner je",
        "herinner jij",
        "weet je nog",

        # Media (Fase 5)
        "volume",
        "pauzeer",
        "pauze",
        "pause",
        "pauseren",
        "hervat",
        "speel verder",
        "harder",
        "luider",
        "zachter",
        "stiller",
        "mute",
        "demp",
        "muteer",
        "skip",
        "volgende",
        "vorige nummer",
        "vorige track",
        "muziek",

        # Systeeminformatie (Fase 6)
        "cpu",
        "processor",
        "ram",
        "geheugen",
        "gpu",
        "videokaart",
        "grafische kaart",
        "schijfruimte",
        "opslag",
        "batterij",
        "systeeminformatie",
        "systeeminfo",
        "systeem",
        "uptime",

        # Vensters (Fase 6)
        "minimaliseer",
        "minimalizeer",
        "minimaliseren",
        "verklein",
        "verkleinen",
        "maximaliseer",
        "maximalizeer",
        "maximaliseren",
        "vergroot",
        "vergroten",
        "herstel venster",

        # Screenshot (Fase 6)
        "screenshot",
        "schermafbeelding",
        "schermfoto",

        # Bestandsbeheer (Fase 6)
        "maak een map",
        "nieuwe map",
        "map maken",
        "map genaamd",
        "maak een bestand",
        "bestand maken",
        "map",
        "bestand",
        "kopieer",
        "kopieren",
        "verplaats",
        "welke bestanden",
        "wat zit er in",
        "laat mijn bestanden",
        "toon mijn bestanden",
    ]

    if any(word in question for word in action_words):
        return True

    # =====================================================
    # EXTRA: sluiten in verschillende formuleringen
    # (stop X, zet X uit, X uit, X dicht, X afsluiten)
    # =====================================================

    close_patterns = [
        r"\bstop(pen)?\b",
        r"\buit\b",
        r"uitzet",
        r"\bdicht\b",
        r"afsluit",
        r"\bdoe?\b.*\buit\b",
    ]

    if any(re.search(pattern, question) for pattern in close_patterns):
        return True

    return False


def is_vague_program_name(name):

    vague_names = (
        "hem",
        "het",
        "die",
        "dat",
        "deze",
        "dit",
        "programma",
        "app",
        "naam",
        "ding",
        "sluiten",
        "sluit",
        "stop",
        "stoppen",
        "uit",
        "afsluiten",
        "beëindig",
        "beëindigen",
        "uitzetten",
        "open",
        "openen",
        "start",
        "starten",
        "dit programma",
        "dat programma",
        "de app",
    )

    name_lower = (name or "").strip().lower()

    return name_lower in vague_names


def claims_pc_action(text):

    """
    Betrouwbaarheidscontrole (Fase 9, stap 1).

    Detecteert of een AI-tekst beweert dat een PC-actie is of wordt
    uitgevoerd. Dit pad is alleen relevant wanneer de AI GEEN echte
    tool-call heeft gemaakt: dan is er ook niets uitgevoerd en mag
    JARVIS zo'n bewering niet klakkeloos herhalen.
    """

    text = (text or "").lower().strip()

    claim_patterns = (
        "ik open", "ik start", "ik sluit", "ik lanceer",
        "ik zet", "ik pauzeer", "ik hervat", "ik demp", "ik mute",
        "ik minimaliseer", "ik vergroot", "ik herstel",
        "ik maak", "ik kopieer", "ik verplaats", "ik verwijder",
        "ik speel", "ik ga naar", "bezoek ik",
        "ik neem een screenshot", "maak een screenshot",
        "ik vergrendel", "ik herstart", "ik log af",
        "wordt geopend", "wordt gestart", "wordt gesloten",
        "wordt gedempt", "wordt gepauzeerd", "wordt afgesloten",
        "wordt geminimaliseerd", "wordt vergroot",
        "al geopend", "wordt getoond", "staat open", "is gestart",
    )

    return any(pattern in text for pattern in claim_patterns)


def decision_text_usable(text):

    """
    Error-feedback (Fase 9, stap 5): alleen gewone eerlijke tekst
    is bruikbaar als antwoord op een mislukte actie. Ruwe tool-call
    JSON (het model echoot soms zijn eigen tool-call) of een nieuwe
    actieclaim zonder uitvoering is NIET bruikbaar.
    """

    cleaned = str(text or "").strip()

    if not cleaned:
        return False

    if cleaned.startswith("{") and (
        '"arguments"' in cleaned or '"name"' in cleaned or "'arguments'" in cleaned
    ):
        return False

    if claims_pc_action(cleaned):
        return False

    return True


# =============================================================
# TOOL SELECTION VALIDATION (Fase 9, stap 3)
#
# Controleert of een gekozen tool waarschijnlijk past bij de
# gebruikersvraag, puur op basis van BESTAANDE informatie:
# de tool-metadata (naam, description, parameternamen) en de
# tool-tabel in de systeemprompt. Geen hardcoded per-tool regels.
# =============================================================

_VALIDATION_STOPWORDS = frozenset({
    "de", "het", "een", "en", "of", "maar", "wat", "is", "zijn",
    "mijn", "mij", "ik", "je", "jij", "jou", "naar", "voor",
    "met", "van", "dat", "die", "dit", "dan", "als", "ook",
    "even", "graag", "aub", "nu", "kan", "kun", "wil", "moet",
    "hem", "haar", "hier", "daar", "niet", "maak", "doe", "bij",
})

_TOOL_PROMPT_TOKENS_CACHE = None

# De actie-systeemprompt staat lokaal in ask_ai(); deze holder maakt
# hem leesbaar voor de tool-validatie zonder de prompt te verplaatsen.
_ACTION_PROMPT_HOLDER = {"text": None}


def register_action_prompt(text):

    _ACTION_PROMPT_HOLDER["text"] = text


def _content_tokens(text):

    cleaned = "".join(ch if ch.isalnum() else " " for ch in (text or "").lower())

    return {
        token
        for token in cleaned.split()
        if len(token) >= 3 and token not in _VALIDATION_STOPWORDS
    }


def _tokens_overlap(question_tokens, reference_tokens):

    """
    True zodra een vraagtoken bij een referentietoken hoort.
    Korte stammen (4 tekens) mogen ook matchen, zodat bv.
    "sluit" bij "sluiten" en "open" bij "openen" hoort.
    """

    for q in question_tokens:

        for r in reference_tokens:

            if q == r:
                return True

            if len(q) >= 4 and len(r) >= 4 and (
                q.startswith(r[:4]) or r.startswith(q[:4])
            ):
                return True

    return False


def _prompt_tool_tokens():

    """
    Leidt per toolnaam extra herkenningswoorden af uit de bestaande
    tool-tabel in de systeemprompt (regels met "-> tool_naam"),
    zodat bv. "cpu" bij system_info hoort via de promptregel over
    CPU/RAM/GPU-uitvraging.
    """

    global _TOOL_PROMPT_TOKENS_CACHE

    prompt_text = _ACTION_PROMPT_HOLDER.get("text")

    if _TOOL_PROMPT_TOKENS_CACHE is not None or not prompt_text:
        return _TOOL_PROMPT_TOKENS_CACHE or {}

    mapping = {}

    for line in prompt_text.splitlines():

        if "\u2192" not in line:
            continue

        after_arrow = line.split("\u2192", 1)[1]

        name_match = re.match(r"\s*([a-z_][a-z_0-9]*)", after_arrow)

        if not name_match:
            continue

        tool_name = name_match.group(1)

        mapping.setdefault(tool_name, set())
        mapping[tool_name] |= _content_tokens(line)

    _TOOL_PROMPT_TOKENS_CACHE = mapping
    return mapping


def tool_matches_question(tool_name, arguments, question, tools):

    """
    Geeft True als de gekozen tool waarschijnlijk past bij de vraag.

    Onbekende tools (hallucinaties) gelden als mismatch zodat de
    recovery-poging uit stap 2 een kans krijgt.
    """

    question_tokens = _content_tokens(question)

    if not question_tokens:
        return True   # niets zinnigs te toetsen: niet blokkeren

    meta = None

    for item in tools or []:

        info = item.get("function", {}) if isinstance(item, dict) else {}

        if info.get("name") == tool_name:
            meta = info
            break

    if meta is None:
        return False

    parameter_names = " ".join(
        str(key)
        for key in (meta.get("parameters") or {}).get("properties", {}).keys()
    )

    meta_text = " ".join([
        str(meta.get("name") or ""),
        str(meta.get("description") or ""),
        parameter_names,
    ])

    reference_tokens = _content_tokens(meta_text)
    reference_tokens |= _prompt_tool_tokens().get(tool_name, set())

    return _tokens_overlap(question_tokens, reference_tokens)


def has_program_hint(question):

    command_words = {
        "sluit", "sluiten", "stop", "stoppen", "uit", "dicht", "afsluiten",
        "beëindig", "beëindigen", "uitzetten", "zet", "doe", "maak",
        "open", "openen", "start", "starten", "lanceer",
        "hem", "het", "die", "dat", "deze", "dit", "programma", "app",
        "graag", "aub", "alsjeblieft", "even", "nu", "svp",
        "wil", "je", "jou", "jij", "u", "uw", "kan", "kun", "kunnen",
        "zou", "eens", "maar", "en", "de", "een", "van", "op", "naar",
        "mij", "me", "moeten", "dan", "weer", "alsjeblieft", "svp",
        "opnieuw", "nogmaals", "nog", "opent", "gestart",
    }

    for word in question.lower().split():
        if word not in command_words:
            return True

    return False


def request_intent(question):

    question = question.lower()

    close_patterns = [
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

    open_patterns = [
        r"\bopen",
        r"openen",
        r"\bstart",
        r"lanceer",
    ]

    if any(re.search(pattern, question) for pattern in close_patterns):
        return "close"

    if any(re.search(pattern, question) for pattern in open_patterns):
        return "open"

    return None


def correct_opposite_tool(tool_name, question):

    question = question.lower()

    wants_open = any(re.search(pattern, question) for pattern in [
        r"\bopen", r"openen", r"\bstart", r"lanceer",
    ])

    wants_close = any(re.search(pattern, question) for pattern in [
        r"\bsluit", r"sluiten", r"\bstop", r"\buit\b", r"\bdicht\b",
        r"afsluit", r"beëindig", r"beindig", r"uitzet",
    ])

    if tool_name == "close_program" and wants_open and not wants_close:
        return "open_program"

    if tool_name == "open_program" and wants_close and not wants_open:
        return "close_program"

    return None


def execute_tool(tool_name, arguments, question):

    arguments = arguments or {}

    try:

        if tool_name == "open_file":

            filename = arguments["filename"]

            result = open_file_tool(filename)

            update_context(
                last_command=question,
                last_result=str(result),
                last_action="bestand geopend",
                last_file=filename
            )

            return str(result)

        elif tool_name == "open_website":

            url = arguments["url"]

            result = open_website_tool(url)

            update_context(
                last_command=question,
                last_result=str(result),
                last_action="website geopend",
                last_website=url
            )

            return str(result)

        elif tool_name == "open_program":

            program = arguments["program"]

            if is_vague_program_name(program) or not has_program_hint(question):
                if current_context["last_program"]:
                    program = current_context["last_program"]
                else:
                    return "Welk programma wil je openen?"

            result = open_program_tool(program)

            update_context(
                last_command=question,
                last_result=str(result),
                last_action="programma geopend",
                last_program=program
            )

            return str(result)

        elif tool_name == "close_program":

            program = arguments["program"]

            if is_vague_program_name(program) or not has_program_hint(question):
                if current_context["last_program"]:
                    program = current_context["last_program"]
                else:
                    return "Welk programma wil je sluiten?"

            result = close_program_tool(program)

            update_context(
                last_command=question,
                last_result=str(result),
                last_action="programma gesloten",
                last_program=program
            )

            return str(result)

        elif tool_name == "remember":

            key = arguments["key"]
            value = arguments["value"]

            return str(remember_tool(key, value))

        elif tool_name == "recall":

            key = arguments["key"]

            return str(recall_tool(key))

        elif tool_name == "forget":

            key = arguments["key"]

            return str(forget_tool(key))

        elif tool_name == "media_play_pause":

            return str(media_play_pause_tool())

        elif tool_name == "media_next":

            return str(media_next_tool())

        elif tool_name == "media_previous":

            return str(media_previous_tool())

        elif tool_name == "volume_up":

            return str(media_volume_up_tool())

        elif tool_name == "volume_down":

            return str(media_volume_down_tool())

        elif tool_name == "set_volume":

            percent = arguments["percent"]

            return str(media_set_volume_tool(percent))

        elif tool_name == "media_mute":

            return str(media_mute_tool())

        elif tool_name == "system_info":

            return str(system_info_tool())

        elif tool_name == "screenshot":

            return str(screenshot_tool())

        elif tool_name == "create_folder":

            name = arguments["name"]
            location = arguments.get("location", "")

            return str(create_folder_tool(name, location))

        elif tool_name == "create_file":

            name = arguments["name"]
            location = arguments.get("location", "")

            return str(create_file_tool(name, location))

        elif tool_name == "list_files":

            location = arguments["location"]

            return str(list_files_tool(location))

        elif tool_name == "copy_file":

            filename = arguments["filename"]
            location = arguments["location"]

            return str(copy_file_tool(filename, location))

        elif tool_name == "move_file":

            filename = arguments["filename"]
            location = arguments["location"]

            return str(move_file_tool(filename, location))

        elif tool_name in ("minimize_window", "maximize_window", "restore_window"):

            program = arguments["program"]

            if is_vague_program_name(program) or not has_program_hint(question):
                if current_context["last_program"]:
                    program = current_context["last_program"]
                else:
                    return "Welk programma wil je dat ik aanpas?"

            if tool_name == "minimize_window":
                result = minimize_window_tool(program)
            elif tool_name == "maximize_window":
                result = maximize_window_tool(program)
            else:
                result = restore_window_tool(program)

            update_context(
                last_command=question,
                last_result=str(result),
                last_action=f"venster {tool_name.split('_')[0]}gezet",
                last_program=program
            )

            return str(result)

        else:

            return f"Ik weet niet hoe ik de tool {tool_name} moet uitvoeren."

    except KeyError as error:

        print(f"⚠️ Tool {tool_name} miste een argument: {error}")

        return f"Ik kon {tool_name} niet uitvoeren omdat een argument ontbrak."

    except Exception as error:

        print(f"⚠️ Fout bij tool {tool_name}: {error}")

        return f"Ik kon {tool_name} niet uitvoeren."


def remember_from_question(question):

    try:

        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Je bent JARVIS. De gebruiker wil iets onthouden. "
                        "Geef alleen antwoord in het formaat "
                        "'sleutel: waarde' (kleine letters, geen spaties in "
                        "de sleutel, bijv. 'favoriete_game: valorant' of "
                        "'naam: rushil'). De waarde mag gewoon spaties en "
                        "hoofdletters bevatten, bijv. "
                        "'favoriete_band: The Jacksons 5'. "
                        "Bedenk een korte, duidelijke sleutel. "
                        "Als de opdracht onduidelijk is, geef alleen 'geen'."
                    )
                },
                {
                    "role": "user",
                    "content": question
                }
            ]
        )

        text = response.message.content.strip().lower()

        if text == "geen" or ":" not in text:
            return None

        key, value = text.split(":", 1)

        key = key.strip()
        value = beautify(value).strip()

        if not key or not value or len(key) > 40 or len(value) > 80:
            return None

        remember(key, value)

        return f"Ik onthoud dat {key.replace('_', ' ')} {value} is."

    except Exception as error:
        print(f"⚠️ Fout bij onthouden: {error}")
        return None


def extract_personal_info(question, answer):

    question_lower = question.lower()

    # Alleen als de gebruiker iets persoonlijks lijkt te delen
    signals = [
        "mijn", "ik heb", "ik vind", "ik hou", "ik speel", "ik game",
        "ik ben", "favoriet", "lievelings", "graag", "ik woon",
        "ik houd",
    ]

    if not any(signal in question_lower for signal in signals):
        return None

    # Neem de laatste paar gespreksberichten mee als context
    # (de huidige beurt staat hier nog niet in, die wordt apart meegegeven)
    recent = conversation_history[-3:]
    context_lines = "\n".join(
        f"{'Gebruiker' if m['role'] == 'user' else 'JARVIS'}: {m['content']}"
        for m in recent
    )

    try:

        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Je bent JARVIS. De gebruiker deelt soms een "
                        "persoonlijke voorkeur of een feit over zichzelf, "
                        "ook midden in een gesprek. Voorbeelden: 'ik hou "
                        "van iron man', 'ik vind sporten leuk', 'mijn "
                        "favoriete film is de avengers', 'iron man is mijn "
                        "lievelingsheld'. Herken zulke uitspraken en geef "
                        "alleen antwoord in het formaat 'sleutel: waarde' "
                        "(kleine letters, geen spaties in de sleutel, de "
                        "waarde mag spaties en hoofdletters bevatten, bijv. "
                        "'favoriete_film: Iron Man'). Bedenk een korte, "
                        "duidelijke sleutel (bijv. favoriete_film, "
                        "favoriete_held, favoriete_hobby, favoriete_band). "
                        "Heeft de gebruiker geen persoonlijke info gedeeld? "
                        "Geef dan alleen het woord 'geen'."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Recente conversatie:\n{context_lines}\n\n"
                        f"Gebruiker zei: {question}\n"
                        f"JARVIS antwoordde: {answer}\n"
                        "Wat moet ik onthouden?"
                    )
                }
            ]
        )

        text = response.message.content.strip().lower()

        if text == "geen" or ":" not in text:
            return None

        key, value = text.split(":", 1)

        key = key.strip()
        value = beautify(value).strip()

        if not key or not value or len(key) > 40 or len(value) > 80:
            return None

        if recall(key) == value:
            return None

        remember(key, value)

        return f"Ik heb genoteerd dat je {key.replace('_', ' ')} {value} is."

    except Exception as error:
        print(f"⚠️ Geheugenextractie fout: {error}")
        return None


def ask_ai(question):

    question = question.strip()

    print(f"🤖 AI verwerkt: {question}")

    # =========================================================
    # NORMALE VRAAG
    # =========================================================

    if not is_action_request(question):

        messages = [
            {
                "role": "system",
                "content": """
Je bent JARVIS, een slimme Nederlandse persoonlijke AI-assistent.

Antwoord altijd in het Nederlands, in gewone spreektaal.
Gebruik geen formele, ouderwetse of vreemde woorden
(zoals "laatstelijk", "derhalve", "bijgevolg").

Blijf kort: antwoord in één of twee zinnen.
Als iets onduidelijk is, stel dan een korte vervolgvraag.

Je voert een natuurlijk gesprek met de gebruiker.
Je krijgt naast de huidige vraag ook de recente conversatie.

Gebruik die conversatie om vervolgvragen te begrijpen.

Bijvoorbeeld:

Gebruiker:
Wat is de hoofdstad van Frankrijk?

JARVIS:
Parijs.

Gebruiker:
En van Duitsland?

JARVIS:
Berlijn.

Als de gebruiker woorden gebruikt zoals:
"het", "hem", "haar", "daar", "die", "dat", "de vorige"
of "en van ...", probeer dan uit de recente conversatie
te begrijpen waarnaar de gebruiker verwijst.

Gebruik GEEN tools voor normale kennisvragen.
Open GEEN bestanden, programma's of websites.

Gebruik de actuele JARVIS-CONTEXT wanneer de gebruiker
verwijst naar iets uit de vorige opdracht.

Als:
Laatste programma: Discord

en de gebruiker zegt:
"sluit hem"

dan betekent "hem" → Discord.

Als:
Laatste programma: Spotify

en de gebruiker zegt:
"open het opnieuw"

dan betekent "het" → Spotify.

Als er geen relevant programma in de context staat,
raad dan niet welk programma de gebruiker bedoelt.
"""
            }
        ]

        # Recente conversatie toevoegen
        messages.extend(conversation_history)

        messages.append({
            "role": "system",
            "content": f"""
        ACTUELE JARVIS-CONTEXT:

        {get_context()}

        Gebruik deze context om vervolgvragen te begrijpen.

        Als de gebruiker bijvoorbeeld zegt:
        "plus 10"

        en de laatste berekening was:
        10 + 5 = 15

        dan betekent "plus 10":
        15 + 10

        Gebruik de context alleen wanneer deze relevant is.
        """
        })

        # =====================================================
        # PERMANENT GEHEUGEN (Fase 4)
        # =====================================================

        messages.append({
            "role": "system",
            "content": f"""
        JARVIS-GEHEUGEN (wat ik over de gebruiker weet):

        {memory_summary()}

        Gebruik dit geheugen wanneer de gebruiker vraagt naar
        zichzelf, zijn voorkeuren, zijn pc of zijn projecten.
        Als er iets in het geheugen staat, gebruik dat als
        het antwoord. Verzin geen dingen die er niet staan.
        """
        })
        
        # Nieuwe vraag toevoegen
        messages.append({
            "role": "user",
            "content": question
        })

        response = ollama.chat(
            model=MODEL,
            messages=messages
        )

        answer = response.message.content

        update_context(
            last_command=question,
            last_result=answer,
            last_action="normale vraag"
        )

        # =============================================
        # BELANGRIJKE INFO AUTOMATISCH OPSLAAN (Fase 4)
        # =============================================

        note = extract_personal_info(question, answer)

        if note:
            answer = f"{answer} {note}"

        add_to_history("user", question)
        add_to_history("assistant", answer)

        return answer

    # =========================================================
    # TOOLS
    # =========================================================

    tools = [

        {
            "type": "function",
            "function": {
                "name": "open_file",
                "description": """
                    Zoek een bestand op de Windows-computer en open het.

                    Gebruik deze tool wanneer de gebruiker daadwerkelijk
                    een bestand of foto wil openen.

                    Voorbeelden:
                    Open kamerfoto
                    Open mijn document
                    Open foto van mijn kamer
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "De naam van het bestand dat geopend moet worden.",
                        }
                    },
                    "required": ["filename"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "open_website",
                "description": """
                    Open een website in de standaardbrowser.

                    Gebruik deze tool ALLEEN wanneer de gebruiker expliciet
                    vraagt om een website te openen of ernaartoe te gaan.

                    Voorbeelden:
                    Open YouTube
                    Ga naar Google
                    Open Wikipedia

                    Gebruik deze tool NIET voor algemene kennisvragen.
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "De volledige URL van de website.",
                        }
                    },
                    "required": ["url"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "open_program",
                "description": """
                    Zoek een programma op de Windows-computer en open het.

                    Gebruik deze tool wanneer de gebruiker een programma
                    of applicatie wil starten.

                    Voorbeelden:
                    Open Discord
                    Start Steam
                    Open Chrome
                    Start Spotify
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {
                            "type": "string",
                            "description": "De naam van het programma.",
                        }
                    },
                    "required": ["program"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "close_program",
                "description": """
                Sluit een programma dat momenteel geopend is.

                Gebruik deze tool wanneer de gebruiker vraagt
                om een programma te sluiten.

                Als de gebruiker bijvoorbeeld zegt:
                "Sluit hem"

                en de context zegt:
                Laatste programma: Spotify

                dan moet je close_program gebruiken met:
                Spotify
                """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {
                            "type": "string",
                            "description": "De naam van het programma dat gesloten moet worden."
                        }
                    },
                    "required": ["program"]
                }
            }
        },

        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": """
Sla informatie op in het permanente geheugen van JARVIS.

Gebruik deze tool wanneer de gebruiker expliciet vraagt
om iets te onthouden.
""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Een korte naam voor de informatie.",
                        },
                        "value": {
                            "type": "string",
                            "description": "De informatie die onthouden moet worden.",
                        },
                    },
                    "required": ["key", "value"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": """
Haal informatie uit het permanente geheugen van JARVIS.

Gebruik deze tool wanneer de gebruiker vraagt naar
informatie die eerder is opgeslagen.
""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "De naam van de informatie.",
                        }
                    },
                    "required": ["key"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "forget",
                "description": """
Verwijder informatie uit het permanente geheugen van JARVIS.

Gebruik deze tool wanneer de gebruiker vraagt om
iets te vergeten of te verwijderen.
""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "De naam van de informatie die verwijderd moet worden.",
                        }
                    },
                    "required": ["key"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "media_play_pause",
                "description": """
                    Muziek pauzeren of afspelen (wisselt tussen pauze en play).
                    Gebruik deze tool bij "pauzeer", "speel verder", "hervat".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "media_next",
                "description": """
                    Naar het volgende nummer gaan.
                    Gebruik deze tool bij "volgende", "volgende nummer", "skip".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "media_previous",
                "description": """
                    Terug naar het vorige nummer gaan.
                    Gebruik deze tool bij "vorige", "vorige nummer".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "volume_up",
                "description": """
                    Het volume iets omhoog zetten.
                    Gebruik deze tool bij "harder", "volume omhoog", "luider".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "volume_down",
                "description": """
                    Het volume iets omlaag zetten.
                    Gebruik deze tool bij "zachter", "volume omlaag", "stiller".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "set_volume",
                "description": """
                    Het volume op een exact percentage zetten.
                    Gebruik deze tool bij "zet volume op 30", "volume naar 50".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "percent": {
                            "type": "integer",
                            "description": "Het gewenste volume van 0 tot 100.",
                        }
                    },
                    "required": ["percent"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "media_mute",
                "description": """
                    Het geluid dempen of het dempen opheffen (wisselt).
                    Gebruik deze tool bij "demp", "mute", "geluid uit".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "system_info",
                "description": """
                    Lees de systeeminformatie van de pc uit: processor, GPU,
                    RAM, schijfruimte, batterij, Windows-versie en uptime.
                    Gebruik deze tool bij "wat voor pc heb ik",
                    "systeeminformatie", "geef een overzicht van je pc".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "minimize_window",
                "description": """
                    Minimaliseer het venster van een programma (vouw in).
                    Gebruik deze tool bij "minimaliseer Discord",
                    "maak Spotify klein", "vouw het venster in".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {
                            "type": "string",
                            "description": "De naam van het programma.",
                        }
                    },
                    "required": ["program"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "maximize_window",
                "description": """
                    Vergroot/gemaximaliseerd zetten van een programma-venster.
                    Gebruik deze tool bij "vergroot Discord",
                    "maak Spotify groot", "maximaliseer het venster".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {
                            "type": "string",
                            "description": "De naam van het programma.",
                        }
                    },
                    "required": ["program"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "restore_window",
                "description": """
                    Herstel het vorige formaat van een programma-venster
                    (uit minimaliseer/vergroot terug naar normaal).
                    Gebruik deze tool bij "herstel Discord",
                    "maak het venster weer normaal".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "program": {
                            "type": "string",
                            "description": "De naam van het programma.",
                        }
                    },
                    "required": ["program"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "screenshot",
                "description": """
                    Maak een screenshot van het volledige scherm, sla het
                    op en open het voor de gebruiker.
                    Gebruik deze tool bij "maak een screenshot",
                    "schermafbeelding", "neem een foto van mijn scherm".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "create_folder",
                "description": """
                    Maak een nieuwe map aan.
                    Gebruik deze tool bij "maak een map genaamd project",
                    "nieuwe map op het bureaublad".
                    Locatie mag leeg blijven (dan bureaublad): bureaublad,
                    downloads, documenten, afbeeldingen, muziek, video's.
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "De naam van de nieuwe map.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Waar de map moet komen, bijv. 'documenten'. Mag ook leeg.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "create_file",
                "description": """
                    Maak een nieuw (leeg) bestand aan.
                    Gebruik deze tool bij "maak een bestand genaamd
                    notities in documenten", "maak bestand lijstje op het
                    bureaublad". Zonder extensie wordt .txt gebruikt.
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "De naam van het bestand.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Waar het bestand moet komen, bijv. 'documenten'. Mag ook leeg.",
                        },
                    },
                    "required": ["name"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": """
                    Toon welke bestanden en mappen er in een locatie staan.
                    Gebruik deze tool bij "welke bestanden zitten in
                    downloads", "wat zit er in documenten". Locaties:
                    bureaublad, downloads, documenten, afbeeldingen,
                    muziek, video's.
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "De locatie, bijv. 'downloads'.",
                        }
                    },
                    "required": ["location"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "copy_file",
                "description": """
                    Kopieer een bestand naar een locatie.
                    Gebruik deze tool bij "kopieer kamerfoto naar
                    documenten", "kopieer cv naar downloads".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "De naam van het bestand.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Naar welke locatie, bijv. 'documenten'.",
                        },
                    },
                    "required": ["filename", "location"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": """
                    Verplaats een bestand naar een locatie.
                    Gebruik deze tool bij "verplaats rapport naar
                    documenten", "verplaats foto naar downloads".
                    """,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "De naam van het bestand.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Naar welke locatie, bijv. 'documenten'.",
                        },
                    },
                    "required": ["filename", "location"],
                },
            },
        },
    ]

    # =========================================================
    # AI VOOR ACTIES
    # =========================================================

    system_prompt_content = """
Je bent JARVIS, een Nederlandse Windows-assistent.

## KIES ALTIJD DE JUISTE TOOL (één tool-call per actie)

- Programma openen   → open_program("naam")      bijv. Discord, Spotify, Steam, Chrome
- Programma sluiten  → close_program("naam")
- Bestand openen     → open_file("naam")          bijv. een foto of document
- Website bezoeken   → open_website("volledige url")   bijv. https://www.youtube.com
- Iets onthouden     → remember("korte naam", "informatie")
- Eerder opgeslagen info ophalen → recall("naam")
- Iets vergeten       → forget("naam")
- Muziek pauzeren/afspelen → media_play_pause
- Volgend nummer      → media_next
- Vorig nummer        → media_previous
- Volume omhoog       → volume_up
- Volume omlaag       → volume_down
- Volume op een percentage → set_volume(percent)   bijv. set_volume(30)
- Geluid dempen       → media_mute
- Systeeminformatie   → system_info   bijv. "wat voor pc heb ik", "systeeminformatie"
- CPU/RAM/GPU/etc. los uitvragen → system_info écht aanroepen, niet zelf verzinnen
- Venster minimaliseren → minimize_window("naam")   bijv. "minimaliseer Discord"
- Venster vergroten     → maximize_window("naam")   bijv. "vergroot Spotify"
- Venster herstellen    → restore_window("naam")    bijv. "herstel Discord"
- Screenshot maken      → screenshot   bijv. "maak een screenshot", "schermafbeelding"
- Map maken             → create_folder("naam", "locatie")   bijv. "maak een map project op het bureaublad"
- Bestand maken         → create_file("naam", "locatie")   bijv. "maak een bestand notities in documenten"
- Bestanden tonen       → list_files("locatie")   bijv. "welke bestanden zitten in documenten"
- Bestand kopiëren      → copy_file("naam", "locatie")   bijv. "kopieer cv naar downloads"
- Bestand verplaatsen   → move_file("naam", "locatie")   bijv. "verplaats rapport naar documenten"
- Locaties: bureaublad, downloads, documenten, afbeeldingen, muziek, video's

## OPEN IS NIET SLUITEN (belangrijk!)

- Zegt de gebruiker "open" of "start"? Dan betekent dat ÓPENEN.
  Gebruik bij "open" NOOIT close_program.
- Zegt de gebruiker "sluit", "stop", "uit", "dicht" of "beëindig"?
  Dan betekent dat SLUITEN. Gebruik bij "sluit" NOOIT open_program.

Voorbeelden:
- "Open Discord"      → open_program("Discord")
- "Sluit Discord"     → close_program("Discord")
- "Open YouTube"      → open_website("https://www.youtube.com")
- "Open mijn kamerfoto" → open_file("kamerfoto")

## MEERDERE ACTIES IN ÉÉN ZIN

Maak voor ELKE actie een aparte tool-call, in de volgorde van de zin.

Voorbeelden:
- "Open Discord en open Spotify"        → open_program("Discord") EN open_program("Spotify")
- "Open Discord, Spotify en Steam"      → drie open_program-calls
- "Sluit Discord en open Spotify"       → close_program("Discord") EN open_program("Spotify")
- "Open YouTube en open Spotify"        → open_website(...) EN open_program("Spotify")

Zeg nooit dat je iets doet zonder de tool daadwerkelijk aan te roepen.

## VERWIJZINGEN EN CONTEXT

- Zegt de gebruiker "sluit hem", "open het opnieuw" of "zet hem uit"?
  Kies dan het programma dat de gebruiker noemt, anders het programma
  uit de ACTUELE JARVIS-CONTEXT. Staat er geen programma in de context?
  Gebruik dan GEEN tool en vraag: "Welk programma bedoel je?"
- Vraag als "wat heb ik net geopend?" of "wat is mijn laatste programma?":
  beantwoord uit de ACTUELE JARVIS-CONTEXT, zonder tool.

## BELANGRIJK: ECHTE TOOL-CALLS

- Wil de gebruiker dat je iets DOET op de pc (openen, sluiten,
  volume, media, screenshot, bestanden, afsluiten, ...)?
  Maak DAN ALTIJD een echte tool-call. Eén tool-call per actie.
- Antwoord NOOIT alleen met tekst zoals "Ik open ..." of
  "Ik zet ... op 30" zonder tool-call: daarmee gebeurt er niets.
- Noem een actie nooit afgerond tenzij je er echt een tool voor
  hebt aangeroepen.

## ALGEMENE REGELS

- Kennisvragen beantwoord je zelf, zonder tool.
- Gebruik nooit open_website voor een kennisvraag.
- Gebruik nooit open_file voor een programma en nooit open_program voor een bestand.
- Verzin nooit een programma; gebruik alleen een naam uit de opdracht of de context.
- Zegt de gebruiker "onthoud" of "bewaar"? Dan ALLEEN remember, nooit een andere tool."""

    # Beschikbaar maken voor de tool-validatie (Fase 9, stap 3)
    register_action_prompt(system_prompt_content)

    messages = [
        {
            "role": "system",
            "content": system_prompt_content,
        }
    ]

    # Recente conversatie toevoegen
    messages.extend(conversation_history)

    # =========================================================
    # ACTUELE JARVIS-CONTEXT
    # =========================================================

    messages.append({
        "role": "system",
        "content": f"""
    ACTUELE JARVIS-CONTEXT:

    {get_context()}

    Gebruik deze context wanneer de gebruiker verwijst
    naar iets uit een vorige opdracht.

    Bijvoorbeeld:

    Laatste programma: Discord

    Gebruiker:
    "Sluit hem."

    Dan betekent "hem" → Discord.

    Als:
    Laatste programma: Spotify

    Gebruiker:
    "Open het opnieuw."

    Dan betekent "het" → Spotify.

    Als er geen relevant programma in de context staat,
    raad dan niet wat de gebruiker bedoelt.

    VERWIJZINGEN zoals "hem", "haar", "het", "die", "daar",
    "opnieuw", "nog een keer", "hetzelfde", "maak hem kleiner",
    "sluit hem", "open hem opnieuw":
    verwijzen normaal naar LAST_PROGRAM uit de ACTUELE
    JARVIS-CONTEXT hierboven.
    - Staat daar duidelijk één programma? Gebruik dát programma
      als argument voor de juiste bestaande tool (bijv.
      minimize_window, maximize_window, restore_window,
      close_program, open_program).
    - Is het onduidelijk of staat er niets in de context?
      Raad dan NIET en vraag kort om verduidelijking.
    """
    })

    # =========================================================
    # PERMANENT GEHEUGEN (Fase 4)
    # =========================================================

    messages.append({
        "role": "system",
        "content": f"""
    JARVIS-GEHEUGEN (wat ik over de gebruiker weet):

    {memory_summary()}

    Gebruik dit geheugen wanneer de gebruiker vraagt naar
    zichzelf, zijn voorkeuren, zijn pc of zijn projecten.
    Als er iets in het geheugen staat, gebruik dat als
    het antwoord. Verzin geen dingen die er niet staan.
    """
    })

    # =========================================================
    # NIEUWE OPDRACHT
    # =========================================================

    messages.append({
        "role": "user",
        "content": question
    })

    # =========================================================
    # AI-CALL MET RECOVERY (Fase 9, stap 2)
    #
    # Geeft de AI bij een actievraag alleen een tekstuele actieclaim
    # ("Ik open ...") zonder echte tool-call, dan volgt maximaal EEN
    # extra aanroep met een expliciete recovery-instructie.
    #
    # Oneindige loops zijn onmogelijk: de lus draait maximaal 2x en
    # stopt direct bij een echte tool-call of bij een antwoord ZONDER
    # actieclaim.
    # =========================================================

    MAX_AI_ATTEMPTS = 2

    attempt = 0
    validation_failed = False

    # =========================================================
    # CONTEXT-VERRIJKING (Fase 9, stap 6): bevat de vraag een
    # verwijzing ("hem", "opnieuw", ...), dan mag de tool-validatie
    # ook het laatste programma uit de context meerekenen. Dit is
    # alleen matching-tolerantie; JARVIS raadt nooit zelf argumenten.
    # =========================================================

    validation_question = question

    reference_words = (
        "hem", "haar", "die", "daar", "opnieuw",
        "nog een keer", "hetzelfde", "kleiner", "groter", "herstel",
    )

    last_program = current_context.get("last_program")

    if last_program and any(word in question.lower() for word in reference_words):
        validation_question = f"{question} {last_program}"

    while True:

        attempt += 1

        response = ollama.chat(
            model=MODEL,
            messages=messages,
            tools=tools,
        )

        # =====================================================
        # ECHTE TOOL-CALLS: eerst valideren of ze passen bij de
        # vraag (Fase 9, stap 3) vóórdat er iets uitgevoerd wordt.
        # =====================================================

        if response.message.tool_calls:

            wrong_calls = [
                call for call in response.message.tool_calls
                if not tool_matches_question(
                    call.function.name,
                    dict(call.function.arguments or {}),
                    validation_question,
                    tools,
                )
            ]

            if not wrong_calls:
                break   # alle tools passen -> normale Planner/Executor flow

            if attempt >= MAX_AI_ATTEMPTS:
                # Ook na recovery nog een niet-passende tool:
                # NIET uitvoeren, eerlijk stoppen
                validation_failed = True
                break

            wrong_names = ", ".join(
                sorted({call.function.name for call in wrong_calls})
            )

            messages.append({
                "role": "user",
                "content": (
                    f"De tool '{wrong_names}' past niet bij de opdracht "
                    f"van de gebruiker. Kies de JUISTE beschikbare tool "
                    f"voor deze opdracht en maak een echte tool call."
                ),
            })

            continue

        if not claims_pc_action(response.message.content or ""):
            break

        if attempt >= MAX_AI_ATTEMPTS:
            break

        # Recovery: vorige claim + expliciete instructie toevoegen
        messages.append({
            "role": "assistant",
            "content": response.message.content or "",
        })

        messages.append({
            "role": "user",
            "content": (
                "De vorige reactie bevatte geen echte tool call. "
                "Voer de gevraagde actie uit met de juiste beschikbare tool. "
                "Geef geen tekstuele bevestiging; gebruik daadwerkelijk een tool."
            ),
        })

    # =========================================================
    # VALIDATIE MISLUKT (Fase 9, stap 3): na recovery nog steeds
    # een tool die niet bij de vraag past -> niets uitvoeren en
    # eerlijk melden.
    # =========================================================

    if validation_failed:

        answer = (
            "Ik heb die actie NIET uitgevoerd: ik kon geen passende "
            "tool kiezen voor deze opdracht. Probeer het anders te formuleren."
        )

        add_to_history("user", question)
        add_to_history("assistant", answer)

        return answer

    # =========================================================
    # DETERMINISTISCHE AFHANDELING: duidelijke open/sluit-opdracht
    # ZONDER programmanaam en zonder tool-call van de AI
    # =========================================================

    if not response.message.tool_calls and not has_program_hint(question):

        intent = request_intent(question)

        if intent in ("open", "close"):

            if current_context["last_program"]:

                program = current_context["last_program"]

                if intent == "close":
                    result = close_program_tool(program)
                    update_context(
                        last_command=question,
                        last_result=str(result),
                        last_action="programma gesloten",
                        last_program=program
                    )
                else:
                    result = open_program_tool(program)
                    update_context(
                        last_command=question,
                        last_result=str(result),
                        last_action="programma geopend",
                        last_program=program
                    )

                answer = format_results([result])

                add_to_history("user", question)
                add_to_history("assistant", answer)

                return answer

            verb = "sluiten" if intent == "close" else "openen"

            return f"Welk programma wil je {verb}?"

    # =========================================================
    # TOOL RESULTATEN
    # =========================================================

    results = []

    if response.message.tool_calls:

        # =====================================================
        # PLANNER (Fase 8): maakt een Action Plan van de
        # toolcalls. Plannen alleen — uitvoeren blijft bij
        # de bestaande execute_tool() hieronder.
        # =====================================================

        action_plan = make_action_plan(response.message.tool_calls)

        print(describe_plan(action_plan))

        print(f"🛠️ JARVIS voert {len(response.message.tool_calls)} actie(s) uit...")

        # =====================================================
        # ASSISTANT-BERICHT MET TOOL-CALLS TOEVOEGEN
        # =====================================================

        messages.append({
            "role": "assistant",
            "content": response.message.content or "",
            "tool_calls": [
                {
                    "function": {
                        "name": call.function.name,
                        "arguments": dict(call.function.arguments or {}),
                    },
                }
                for call in response.message.tool_calls
            ],
        })

        # =====================================================
        # EXECUTOR (Fase 8): voert het Action Plan uit via de
        # bestaande execute_tool() en houdt per stap de status
        # bij (pending -> running -> done/failed).
        # =====================================================

        executed_steps = execute_action_plan(action_plan, question)

        # =====================================================
        # TOOL-MESSAGES (Ollama-protocol) + RESULTATEN
        # =====================================================

        for step_record in executed_steps:

            if step_record["status"] in ("skipped", "approval_required"):
                continue

            results.append(str(step_record["result"]))

            messages.append({
                "role": "tool",
                "content": step_record["result"],
                "tool_name": step_record["tool_name"],
            })

        # =====================================================
        # AI ERROR FEEDBACK (Fase 9, stap 5): als een plan volledig
        # mislukte (geen enkele geslaagde stap), krijgt de AI
        # maximaal ÉÉN extra beslissingsronde: opnieuw proberen,
        # alternatieve passende tool, of eerlijk opgeven.
        #
        # - Plannen mét minstens één geslaagde stap krijgen GEEN
        #   recovery -> succesvolle acties worden nooit herhaald.
        # - Deze beslissing is los van core/retry.py (retry binnen
        #   één actie) en van de Fase 9.2 claim-recovery ervoor.
        # - Maximaal één keer; daarna nooit meer.
        # =====================================================

        done_steps = [r for r in executed_steps if r["status"] == "done"]
        failed_steps = [r for r in executed_steps if r["status"] == "failed"]

        if failed_steps and not done_steps:

            failure_lines = "\n".join(
                f"- {r['tool_name']} met {r.get('arguments')}\n"
                f"  Reden: {str(r['result'])[:200]}"
                for r in failed_steps
            )

            messages.append({
                "role": "user",
                "content": (
                    "De volgende acties zijn MISLUKT:\n"
                    f"{failure_lines}\n\n"
                    "Beslis nu:\n"
                    "- probeer dezelfde actie EEN keer opnieuw met een nieuwe "
                    "tool-call, OF\n"
                    "- kies een ANDERE passende bestaande tool, OF\n"
                    "- geef zonder tool-call kort en eerlijk toe dat het niet "
                    "gelukt is.\n"
                    "Voer NOOIT een actie uit die al geslaagd is."
                ),
            })

            error_decision = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=tools,
            )

            decision_calls = getattr(error_decision.message, "tool_calls", None)

            recovery_ran = False

            if decision_calls:

                decision_matches = all(
                    tool_matches_question(
                        call.function.name,
                        dict(call.function.arguments or {}),
                        validation_question,
                        tools,
                    )
                    for call in decision_calls
                )

                if decision_matches:

                    print("🛠️ JARVIS probeert het nog één keer na de fout...")

                    recovery_plan = make_action_plan(decision_calls)

                    print(describe_plan(recovery_plan))

                    messages.append({
                        "role": "assistant",
                        "content": error_decision.message.content or "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": call.function.name,
                                    "arguments": dict(call.function.arguments or {}),
                                },
                            }
                            for call in decision_calls
                        ],
                    })

                    recovery_steps = execute_action_plan(recovery_plan, question)

                    recovery_results = []

                    for step_record in recovery_steps:

                        if step_record["status"] in ("skipped", "approval_required"):
                            continue

                        recovery_results.append(str(step_record["result"]))

                        messages.append({
                            "role": "tool",
                            "content": step_record["result"],
                            "tool_name": step_record["tool_name"],
                        })

                    if any(r["status"] == "done" for r in recovery_steps):
                        results = recovery_results

                    recovery_ran = True

                else:

                    # Recovery kiest opnieuw een niet-passende tool:
                    # NIET uitvoeren
                    print("⚠️ AI-herstelpoging koos een niet-passende tool; overgeslagen.")

            elif decision_text_usable(error_decision.message.content):

                # De AI geeft eerlijk toe dat het niet lukte: gebruik
                # die tekst als antwoord
                answer = error_decision.message.content.strip()

                add_to_history("user", question)
                add_to_history("assistant", answer)

                return answer

        # =====================================================
        # NETTE, DETERMINISTISCHE EINDREACTIE (samengesteld uit
        # de resultaten van de tools, niet door de AI herschreven)
        # =====================================================

        answer = format_results(results)

        # =====================================================
        # GESPREK OPSLAAN
        # =====================================================

        add_to_history("user", question)
        add_to_history("assistant", answer)

        return answer

    # =========================================================
    # GEEN TOOL
    # =========================================================

    if response.message.content:

        answer = response.message.content

        # =====================================================
        # BETROUWBAARHEIDSCONTROLE (Fase 9, stap 1): de AI heeft
        # hier GEEN tool-call gemaakt, dus er is niets uitgevoerd.
        # Beweert de tekst wél dat een PC-actie gebeurt, dan
        # vervangen door een eerlijk antwoord.
        # =====================================================

        if claims_pc_action(answer):

            answer = (
                "Ik heb die actie NIET uitgevoerd: ik kreeg geen "
                "geldige tool-opdracht. Probeer het nog een keer."
            )

        add_to_history("user", question)
        add_to_history("assistant", answer)

        return answer

    return "Ik weet niet hoe ik die opdracht moet uitvoeren."


def format_results(results):

    cleaned = [
        str(result).strip().rstrip(".")
        for result in results
        if str(result).strip()
    ]

    if not cleaned:
        return "Ik kon de opdracht niet uitvoeren."

    if len(cleaned) == 1:
        answer = cleaned[0] + "."

    elif all(item.startswith("Ik open ") for item in cleaned):
        names = [item[len("Ik open "):] for item in cleaned]
        answer = "Ik open " + join_names(names) + "."

    elif all(item.endswith(" wordt gesloten") for item in cleaned):
        names = [item[: -len(" wordt gesloten")] for item in cleaned]
        answer = join_names(names) + " worden gesloten."

    else:
        answer = ". ".join(cleaned) + "."

    return answer[:1].upper() + answer[1:]


def join_names(names):

    if len(names) == 1:
        return names[0]

    if len(names) == 2:
        return f"{names[0]} en {names[1]}"

    return ", ".join(names[:-1]) + " en " + names[-1]