import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import has_program_hint, request_intent, update_context, current_context
from core.brain import get_context_answer


print("=== FASE 3: Verwijzingen herkennen ===")

reference_phrases = [
    ("open het opnieuw", False),   # verwijzing, geen programmanaam
    ("sluit hem", False),
    ("open die app", False),
    ("sluit het programma", False),
]

for phrase, expected in reference_phrases:
    result = has_program_hint(phrase)
    ok = "✅" if result == expected else "❌"
    print(f"{ok} has_program_hint({phrase!r}) = {result} (verwacht {expected})")


print()
print("=== FASE 3: Intentie herkennen ===")

for phrase, expected in [
    ("open het opnieuw", "open"),
    ("sluit hem", "close"),
    ("zet spotify uit", "close"),
    ("start steam", "open"),
    ("wat is de hoofdstad van frankrijk", None),
]:
    result = request_intent(phrase)
    ok = "✅" if result == expected else "❌"
    print(f"{ok} request_intent({phrase!r}) = {result!r} (verwacht {expected!r})")


print()
print("=== FASE 3: Contextantwoorden (deterministisch) ===")

update_context(
    last_command="Open Spotify",
    last_result="Ik open Spotify.",
    last_action="programma geopend",
    last_program="Spotify",
    last_calculation="15 + 6",
)

for phrase in [
    "wat is mijn laatste programma",
    "wat heb ik net geopend",
    "wat was mijn laatste berekening",
    "wat heb je net gedaan?",
]:
    print(f"✅ {phrase} -> {get_context_answer(phrase)}")

print()
print("=== FASE 3: Help-antwoord ===")

help_answer = get_context_answer("wat kun je?")
print(f"✅ wat kun je? -> {help_answer[:60]}...")
print(f"✅ help bestaat: {'programma' in help_answer}")
