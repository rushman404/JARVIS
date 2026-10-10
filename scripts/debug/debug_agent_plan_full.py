import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import ollama
from core.agent import PLANNING_SYSTEM_PROMPT, TOOL_LIST_TEXT
from core.ai import get_context
from memory.memory import memory_summary
from core.home_assistant import get_home_assistant_entities_tool

goal = "maak mijn pc klaar om te gamen"

messages = [
    {
        "role": "system",
        "content": PLANNING_SYSTEM_PROMPT.format(
            tools=TOOL_LIST_TEXT,
            ha_devices=get_home_assistant_entities_tool(domain=None),
        ),
    },
    {"role": "system", "content": f"ACTUELE JARVIS-CONTEXT:\n{get_context()}"},
    {"role": "system", "content": f"JARVIS-GEHEUGEN:\n{memory_summary()}"},
    {"role": "user", "content": goal},
]

response = ollama.chat(model="qwen2.5:3b", messages=messages, format="json")

print("=== RUWE LLM-OUTPUT (volledige Agent-context) ===")
print(repr(response.message.content))
print()

try:
    data = json.loads(response.message.content)
except json.JSONDecodeError:
    import re
    m = re.search(r"\{.*\}", response.message.content, re.DOTALL)
    data = json.loads(m.group(0)) if m else {}

print("=== GEPARSE PLAN ===")
print(json.dumps(data, indent=2, ensure_ascii=False))