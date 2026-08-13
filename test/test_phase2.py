import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import is_action_request, summarize_results


# =========================================================
# FASE 2: Acties herkennen (betere toolkeuze)
# =========================================================

action_phrases = [
    "Open Discord, Spotify en Steam",
    "Open Steam en open Spotify",
    "Sluit hem",
    "Beëindig Discord",
    "Sluit Spotify en open Steam",
    "Onthoud dat mijn favoriete game Spider-Man is",
    "Wat is mijn favoriete game",
]

knowledge_phrases = [
    "Wat is de hoofdstad van Frankrijk",
    "Hoe laat is het",
    "Wat heb ik net geopend",
    "Wat is mijn laatste programma",
]


print("=== ACTIEZINNEN (moeten True zijn) ===")

for phrase in action_phrases:
    result = is_action_request(phrase)
    print(f"{'✅' if result else '❌'} {phrase}")

print()
print("=== KENNISVRAGEN (moeten False zijn) ===")

for phrase in knowledge_phrases:
    result = is_action_request(phrase)
    print(f"{'✅' if not result else '❌'} {phrase}")

# =========================================================
# FASE 2: Samenvatting van meerdere acties
# =========================================================

print()
print("=== SAMENVATTING (verwacht een korte Nederlandse zin) ===")

print(summarize_results(
    "Open Discord en Spotify",
    ["Ik open Discord.", "Ik open Spotify."]
))
