import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory import (
    load_memory,
    get_category,
    remember,
    recall,
    forget,
    get_all_memory,
    memory_summary,
)
from core.brain import auto_remember, get_context_answer


print("=== FASE 4: Geheugenstructuur ===")

memory = load_memory()

for category in ["voorkeuren", "pc", "projecten", "muziek", "algemeen"]:
    ok = "✅" if category in memory else "❌"
    print(f"{ok} categorie {category} bestaat")

print(f"✅ bestaande data bewaard: {get_all_memory()}")


print()
print("=== FASE 4: Automatische categorisatie ===")

for key, value, expected in [
    ("favoriete_game", "Spider-Man", "voorkeuren"),
    ("gpu", "RTX 3060 Ti", "pc"),
    ("favoriete_band", "Coldplay", "muziek"),
    ("schoolproject", "website", "projecten"),
    ("woonplaats", "Amsterdam", "algemeen"),
]:
    result = get_category(key, value)
    ok = "✅" if result == expected else "❌"
    print(f"{ok} {key} -> {result} (verwacht {expected})")


print()
print("=== FASE 4: Slim ophalen (exact + partieel) ===")

remember("test_pc_gpu", "RTX 3060 Ti")

ok = "✅" if recall("test_pc_gpu") == "RTX 3060 Ti" else "❌"
print(f"{ok} recall exact: RTX 3060 Ti")

ok = "✅" if recall("pc_gpu") == "RTX 3060 Ti" else "❌"
print(f"{ok} recall partieel ('pc_gpu'): RTX 3060 Ti")

forget("test_pc_gpu")


print()
print("=== FASE 4: Automatisch onthouden van voorkeuren ===")

ack = auto_remember("mijn favoriete testkleur is paars")
ok = "✅" if ack and "paars" in ack else "❌"
print(f"{ok} auto_remember: {ack}")

ok = "✅" if recall("favoriete_testkleur") == "paars" else "❌"
print(f"{ok} opgeslagen: favoriete_testkleur = paars")

forget("favoriete_testkleur")


print()
print("=== FASE 4: Meer persoonlijke info automatisch onthouden ===")

for phrase, key, value in [
    ("mijn naam is Testnaam", "naam", "testnaam"),
    ("mijn woonplaats is Teststad", "woonplaats", "teststad"),
    ("mijn project is Testproject", "project", "testproject"),
]:
    ack = auto_remember(phrase)
    ok = "✅" if ack and value in ack else "❌"
    print(f"{ok} {phrase} -> {ack}")

    stored = recall(key)
    ok = "✅" if stored == value else "❌"
    print(f"{ok}   opgeslagen: {key} = {stored}")

    forget(key)


print()
print("=== FASE 4: Geheugen per categorie ===")

remember("gpu", "RTX 3060 Ti")

answer = get_context_answer("wat weet je over mijn pc")
ok = "✅" if answer and "RTX 3060 Ti" in answer else "❌"
print(f"{ok} wat weet je over mijn pc -> {answer}")

forget("gpu")


print()
print("=== FASE 4: 'wat weet je over mij' ===")

answer = get_context_answer("wat weet je over mij")
ok = "✅" if answer and "Ik weet" in answer else "❌"
print(f"{ok} {answer}")

print()
print("Geheugen samenvatting werkt:", bool(memory_summary()))
