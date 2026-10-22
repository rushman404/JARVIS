import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import ollama
from core.agent import PLANNING_SYSTEM_PROMPT, TOOL_LIST_TEXT
from core.ai import get_context
from memory.memory import memory_summary
from core.home_assistant import get_home_assistant_entities_tool
from core.agent import Agent

goals = [
    "Doe mijn lamp aan, zet hem op 40% en open Spotify.",
    "Open Discord, zet mijn muziek aan en maak Discord kleiner.",
    "Open discord en zet het volume op 30.",
]

for goal in goals:
    print("=" * 70)
    print("GOAL:", goal)
    agent = Agent()
    plan = agent._generate_plan(goal)
    if plan is None:
        print("  => GEEN PLAN")
        continue
    for i, p in enumerate(plan, 1):
        deps = p.get("depends_on")
        print(f"  {i}. {p['tool_name']}({p['arguments']})" + (f"  depends_on={deps}" if deps else ""))
    print()