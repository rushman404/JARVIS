import ollama


tools = [
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": "Zoek een bestand op de computer en open het.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "De naam van het bestand dat geopend moet worden."
                    }
                },
                "required": ["filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Open een website in de standaard webbrowser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "De URL van de website, bijvoorbeeld https://www.youtube.com/"
                    }
                },
                "required": ["url"]
            }
        }
    }
]


response = ollama.chat(
    model="llama3.2:3b",
    messages=[
        {
            "role": "system",
            "content": (
                "Je bent JARVIS. "
                "Als de gebruiker een bestand wil openen, gebruik open_file. "
                "Als de gebruiker een website wil openen, gebruik open_website. "
                "Gebruik nooit open_file voor websites."
            )
        },
        {
            "role": "user",
            "content": "Open YouTube"
        }
    ],
    tools=tools
)


print(response)