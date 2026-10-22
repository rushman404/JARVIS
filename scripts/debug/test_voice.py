import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from voice.listen import listen
from core.brain import process_command


print("JARVIS spraakbesturing gestart.")
print()

command = listen()

print()

if isinstance(command, str) and command.strip():
    print(f"Jij: {command}")
    response = process_command(command)
    print(f"JARVIS: {response}")

elif command is None:
    print("JARVIS kon je niet verstaan.")

else:
    print("Er werd niets gezegd.")