import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory import remember, recall, forget


print("🧠 Geheugen test gestart.")

remember("test", "Hallo vanuit het geheugen.")

print("📥 Opgeslagen.")

value = recall("test")

print("📤 Teruggelezen:", value)

forget("test")

print("🗑️ Testgeheugen verwijderd.")

print("🧠 Geheugen test klaar.")