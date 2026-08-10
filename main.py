from config import JARVIS_NAME, USER_NAME
from voice.listen import listen
from voice.transcribe import transcribe
from voice.speak import speak
from voice.wakeword import wait_for_wake_word
from core.brain import process_command


def start_jarvis():

    print("🚀 JARVIS gestart")

    speak("JARVIS is online.")

    while True:

        wait_for_wake_word()

        speak("Ja, Rushil?")

        while True:

            command = listen()

            if command is None:
                continue

            if not isinstance(command, str):
                print("⚠️ JARVIS kreeg geen tekst terug.")
                continue

            command = command.strip()

            if not command:
                continue

            command = command.lower().strip()

            # Stop met luisteren naar opdrachten
            if any(word in command for word in [
                "ga slapen",
                "slaap",
                "stop jarvis",
                "rust",
                "tot ziens"
            ]):

                speak("Natuurlijk. Ik ga slapen.")
                break

            response = process_command(command)

            if response:
                speak(response)


if __name__ == "__main__":
    start_jarvis()