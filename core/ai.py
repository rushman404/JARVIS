import ollama

from core.tools import open_file_tool
from core.tools import open_website_tool
from core.tools import open_program_tool
from core.tools import remember_tool
from core.tools import recall_tool


MODEL = "llama3.2:3b"

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

    return any(word in question for word in action_words)


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

Antwoord altijd in het Nederlands.

Je voert een natuurlijk gesprek met de gebruiker.

Je krijgt naast de huidige vraag ook de recente conversatie.

Gebruik die conversatie om vervolgvragen te begrijpen.

Bijvoorbeeld:

Gebruiker:
Wat is de hoofdstad van Frankrijk?

JARVIS:
De hoofdstad van Frankrijk is Parijs.

Gebruiker:
En van Duitsland?

JARVIS:
De hoofdstad van Duitsland is Berlijn.

Als de gebruiker woorden gebruikt zoals:
"het", "hem", "haar", "daar", "die", "dat", "de vorige"
of "en van ...", probeer dan uit de recente conversatie
te begrijpen waarnaar de gebruiker verwijst.

Gebruik GEEN tools voor normale kennisvragen.

Open GEEN bestanden.
Open GEEN programma's.
Open GEEN websites.

Geef korte, duidelijke en natuurlijke antwoorden.
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

De gebruiker kan meerdere acties in één opdracht geven.

BELANGRIJK:
Voer ALLE gevraagde acties uit.

Gebruik ook de recente conversatie om vervolgopdrachten
te begrijpen.

Als de gebruiker bijvoorbeeld zegt:

"Open Discord."

en daarna:

"Sluit hem."

dan verwijst "hem" naar Discord.

Voorbeeld:

"Open Steam en ga naar Spotify."

Dit betekent:

1. open_program("Steam")
2. open_program("Spotify")

Gebruik de juiste tool voor iedere afzonderlijke actie.

Gebruik nooit open_file voor een programma.

Gebruik nooit open_program voor een bestand.

Gebruik nooit open_website om informatie op te zoeken.

Bij meerdere acties moet je voor iedere actie
een aparte tool-call maken.

Gebruik remember wanneer de gebruiker expliciet
vraagt om iets te onthouden.

Gebruik recall wanneer de gebruiker vraagt naar
iets dat JARVIS eerder heeft onthouden.

Voer algemene kennisvragen niet uit via tools.

Geef korte, natuurlijke antwoorden.
"""
        }
    ]

    # Recente conversatie toevoegen
    messages.extend(conversation_history)

    # Nieuwe opdracht toevoegen
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
    # TOOL RESULTATEN
    # =========================================================

    results = []

    if response.message.tool_calls:

        for call in response.message.tool_calls:

            tool_name = call.function.name
            arguments = call.function.arguments

            print(f"🔧 AI kiest tool: {tool_name}")
            print(f"📦 Argumenten: {arguments}")

            if tool_name == "open_file":

                filename = arguments["filename"]

                result = open_file_tool(filename)

                results.append(result)

            elif tool_name == "open_website":

                url = arguments["url"]

                result = open_website_tool(url)

                results.append(result)

            elif tool_name == "open_program":

                program = arguments["program"]

                result = open_program_tool(program)

                results.append(result)

            elif tool_name == "remember":

                key = arguments["key"]
                value = arguments["value"]

                result = remember_tool(key, value)

                results.append(result)

            elif tool_name == "recall":

                key = arguments["key"]

                result = recall_tool(key)

                results.append(result)

        # =====================================================
        # GESPREK OPSLAAN
        # =====================================================

        add_to_history("user", question)

        if results:

            answer = "\n".join(str(result) for result in results)

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