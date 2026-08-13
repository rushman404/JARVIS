import re
import ollama

from core.tools import open_file_tool
from core.tools import open_website_tool
from core.tools import open_program_tool
from core.tools import remember_tool
from core.tools import recall_tool
from core.tools import close_program_tool


MODEL = "qwen2.5:3b"

# =========================================================
# TIJDELIJK GESPREKSGEHEUGEN
# =========================================================

conversation_history = []

# Hoeveel berichten JARVIS maximaal onthoudt
MAX_HISTORY = 10

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
    "last_website": ""
}


def update_context(**kwargs):

    for key, value in kwargs.items():

        if key in current_context:
            current_context[key] = value


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

        else:

            return f"Ik weet niet hoe ik de tool {tool_name} moet uitvoeren."

    except KeyError as error:

        print(f"⚠️ Tool {tool_name} miste een argument: {error}")

        return f"Ik kon {tool_name} niet uitvoeren omdat een argument ontbrak."

    except Exception as error:

        print(f"⚠️ Fout bij tool {tool_name}: {error}")

        return f"Ik kon {tool_name} niet uitvoeren."


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
    ]

    # =========================================================
    # AI VOOR ACTIES
    # =========================================================

    messages = [
        {
            "role": "system",
            "content": """
Je bent JARVIS, een Nederlandse Windows-assistent.

## KIES ALTIJD DE JUISTE TOOL (één tool-call per actie)

- Programma openen   → open_program("naam")      bijv. Discord, Spotify, Steam, Chrome
- Programma sluiten  → close_program("naam")
- Bestand openen     → open_file("naam")          bijv. een foto of document
- Website bezoeken   → open_website("volledige url")   bijv. https://www.youtube.com
- Iets onthouden     → remember("korte naam", "informatie")
- Eerder opgeslagen info ophalen → recall("naam")

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

## ALGEMENE REGELS

- Kennisvragen beantwoord je zelf, zonder tool.
- Gebruik nooit open_website voor een kennisvraag.
- Gebruik nooit open_file voor een programma en nooit open_program voor een bestand.
- Verzin nooit een programma; gebruik alleen een naam uit de opdracht of de context.
- Zegt de gebruiker "onthoud" of "bewaar"? Dan ALLEEN remember, nooit een andere tool."""
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
    """
    })

    # =========================================================
    # NIEUWE OPDRACHT
    # =========================================================

    messages.append({
        "role": "user",
        "content": question
    })

    response = ollama.chat(
        model=MODEL,
        messages=messages,
        tools=tools,
    )

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
        # TOOLS UITVOEREN
        # =====================================================

        for call in response.message.tool_calls:

            tool_name = call.function.name

            corrected = correct_opposite_tool(tool_name, question)

            if corrected:
                print(f"⚠️ AI koos {tool_name}, maar gebruiker wil het tegenovergestelde. Gebruik {corrected}.")
                tool_name = corrected

            print(f"🔧 AI kiest tool: {tool_name}")
            print(f"📦 Argumenten: {call.function.arguments}")

            result = execute_tool(tool_name, call.function.arguments, question)

            print(f"📤 Resultaat {call.function.name}: {result}")

            results.append(str(result))

            messages.append({
                "role": "tool",
                "content": result,
                "tool_name": call.function.name,
            })

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


def summarize_results(question, results):

    result_text = "\n".join(results)

    messages = [
        {
            "role": "system",
            "content": (
                "Je bent JARVIS. Je hebt net zelf acties uitgevoerd op de computer. "
                "Vertel nu kort en natuurlijk tegen de gebruiker wat je hebt gedaan. "
                "Zeg duidelijk wat gelukt is en wat niet. "
                "Blijf kort. Antwoord altijd in het Nederlands."
            )
        },
        {
            "role": "user",
            "content": (
                "Dit heb ik zojuist gedaan:\n"
                f"{result_text}\n\n"
                "Vertel dit kort terug aan de gebruiker."
            )
        }
    ]

    try:
        response = ollama.chat(model=MODEL, messages=messages)
        answer = response.message.content.strip()

        if answer:
            return answer

    except Exception as error:
        print(f"⚠️ Fout bij samenvatten: {error}")

    return result_text