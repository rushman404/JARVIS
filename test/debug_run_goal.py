import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from core.agent import Agent

agent = Agent()

goal = "Doe mijn lamp aan, zet hem op 40% en open Spotify."

print("=" * 70)
print("LIVE RUN:", goal)
answer = agent.run_goal(goal)
print("=" * 70)
print("JARVIS:", answer)