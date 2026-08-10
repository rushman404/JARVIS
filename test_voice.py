from voice.listen import listen
from voice.transcribe import transcribe
from main import handle_command


print("JARVIS spraakbesturing gestart.")
print()

audio = listen()

print()
print("🧠 JARVIS verwerkt je stem...")

text = transcribe(audio)

print()
print(f"Jij: {text}")

response = handle_command(text)

print(f"JARVIS: {response}")