import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import ollama
from core.agent import REPLANNING_SYSTEM_PROMPT, TOOL_LIST_TEXT

# Reproduceer de mislukte HA-stap van de gebruiker (zonder geslaagde stappen)
failed = [
    {
        "tool_name": "control_home_assistant",
        "arguments": {
            "domain": "media_player",
            "service": "turn_off",
            "entity_id": "media_player.chromecast",
        },
        "result": (
            "Actie niet uitgevoerd: Kon 'media_player.chromecast' niet aan "
            "een bestaand Home Assistant apparaat koppelen."
        ),
    }
]

failed_lines = "\n".join(
    f"- {r.get('used_tool_name') or r.get('tool_name')} met {r.get('arguments')}\n"
    f"  Reden: {str(r.get('result'))[:200]}"
    for r in failed
)

content = REPLANNING_SYSTEM_PROMPT.format(
    tools=TOOL_LIST_TEXT,
    succeeded="- (geen)",
    failed=failed_lines,
)

response = ollama.chat(
    model="qwen2.5:3b",
    messages=[
        {"role": "system", "content": content},
        {"role": "user", "content": "Doel: maak mijn pc klaar om te gamen"},
    ],
    format="json",
)

print("=== RUWE REPLAN OUTPUT ===")
print(repr(response.message.content))
