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

        # =============================================
        # WACHT OP WAKE WORD
        # =============================================

        wait_for_wake_word()

        speak("Ja, Rushil?")

        # =============================================
        # OPDRACHTEN LUISTEREN
        # =============================================

        while True:

            command = listen()

            # -----------------------------------------
            # JARVIS HEEFT 15 SECONDEN NIETS GEHOORD
            # -----------------------------------------

            if command == "":
                break

            # -----------------------------------------
            # GEEN GELDIGE DATA
            # -----------------------------------------

            if command is None:

                print("⚠️ Geen opdracht ontvangen.")
                continue

            if not isinstance(command, str):

                print("⚠️ JARVIS kreeg geen tekst terug.")
                continue

            command = command.strip()

            if not command:
                print("⚠️ Lege opdracht.")
                continue

            command = command.lower().strip()

            # =========================================
            # HANDMATIG SLAPEN
            # =========================================

            if any(word in command for word in [
                "ga slapen",
                "slaap",
                "stop jarvis",
                "rust",
                "tot ziens"
            ]):

                speak("Natuurlijk. Ik ga slapen.")
                break

            # =========================================
            # COMMANDO VERWERKEN
            # =========================================

            response = process_command(command)

            if response:
                speak(response)


if __name__ == "__main__":
    start_jarvis()