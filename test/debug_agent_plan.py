import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import ollama
from core.agent import PLANNING_SYSTEM_PROMPT, REPLANNING_SYSTEM_PROMPT, VALID_TOOL_NAMES

goal = sys.argv[1] if len(sys.argv) > 1 else "maak mijn pc klaar om te gamen"

response = ollama.chat(
    model="qwen2.5:3b",
    messages=[
        {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
        {"role": "user", "content": goal},
    ],
    format="json",
)

print("=== RUWE LLM-OUTPUT ===")
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

steps = data.get("steps", [])
print()
print(f"=== TOOL-VALIDATIE ({len(steps)} stappen) ===")
for i, s in enumerate(steps):
    name = str(s.get("tool_name", ""))
    valid = "BEKEND" if name in VALID_TOOL_NAMES else "HALLUCINATIE"
    print(f"  {i+1}. [{valid}] {name}({s.get('arguments', {})})")