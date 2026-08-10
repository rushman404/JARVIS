import ollama

from core.tools import open_file_tool
from core.tools import open_website_tool
from core.tools import open_program_tool
from core.tools import remember_tool
from core.tools import recall_tool


MODEL = "llama3.2:3b"


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

        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """
Je bent JARVIS, een slimme Nederlandse persoonlijke AI-assistent.

Antwoord altijd in het Nederlands.

Dit is een normale kennis-, informatie- of conversatievraag.

Gebruik GEEN tools.
Open GEEN bestanden.
Open GEEN programma's.
Open GEEN websites.

Beantwoord de vraag zelf met je eigen kennis.

Geef korte, duidelijke en natuurlijke antwoorden.
""",
                },
                {
                    "role": "user",
                    "content": question,
                },
            ],
        )

        return response.message.content


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

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": """
Je bent JARVIS, een Nederlandse Windows-assistent.

De gebruiker kan meerdere acties in één opdracht geven.

BELANGRIJK:
Voer ALLE gevraagde acties uit.

Voorbeeld:

"Open Steam en ga naar Spotify."

Dit betekent:

1. open_program("Steam")
2. open_program("Spotify")

Een ander voorbeeld:

"Open Discord en daarna YouTube."

Dit betekent:

1. open_program("Discord")
2. open_website("https://www.youtube.com/")

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
""",
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        tools=tools,
    )


    # =========================================================
    # MEERDERE TOOL CALLS UITVOEREN
    # =========================================================

    results = []

    if response.message.tool_calls:

        for call in response.message.tool_calls:

            tool_name = call.function.name
            arguments = call.function.arguments

            print(f"🔧 AI kiest tool: {tool_name}")
            print(f"📦 Argumenten: {arguments}")

            # -------------------------------------------------
            # BESTAND
            # -------------------------------------------------

            if tool_name == "open_file":

                filename = arguments["filename"]

                result = open_file_tool(filename)

                results.append(result)

            # -------------------------------------------------
            # WEBSITE
            # -------------------------------------------------

            elif tool_name == "open_website":

                url = arguments["url"]

                result = open_website_tool(url)

                results.append(result)

            # -------------------------------------------------
            # PROGRAMMA
            # -------------------------------------------------

            elif tool_name == "open_program":

                program = arguments["program"]

                result = open_program_tool(program)

                results.append(result)

            # -------------------------------------------------
            # GEHEUGEN OPSLAAN
            # -------------------------------------------------

            elif tool_name == "remember":

                key = arguments["key"]
                value = arguments["value"]

                result = remember_tool(key, value)

                results.append(result)

            # -------------------------------------------------
            # GEHEUGEN OPHALEN
            # -------------------------------------------------

            elif tool_name == "recall":

                key = arguments["key"]

                result = recall_tool(key)

                results.append(result)


        # =====================================================
        # ALLE RESULTATEN SAMENVOEGEN
        # =====================================================

        if results:

            return "\n".join(str(result) for result in results)


    # =========================================================
    # GEEN TOOL
    # =========================================================

    if response.message.content:

        return response.message.content

    return "Ik weet niet hoe ik die opdracht moet uitvoeren."