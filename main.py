from config import JARVIS_NAME, USER_NAME
from voice.listen import listen
from voice.speak import speak
from voice.wakeword import wait_for_wake_word
from core.brain import process_command
from core.ai import current_context


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
            # JARVIS HEERDE WEL IETS, MAAR VERSTOND HET NIET
            # (blijft hierdoor wakker, gaat niet slapen)
            # -----------------------------------------

            if command is None:

                print("⚠️ JARVIS kon je niet verstaan.")

                if current_context.get("pending_choice"):
                    speak("Ik hoorde het niet goed. Zeg duidelijk ja of nee, of noem de plek nog eens.")
                else:
                    speak("Sorry, ik verstond je niet. Kun je het herhalen?")

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
                "ga maar slapen",
                "slaap lekker",
                "slaap maar",
                "welterusten",
                "stop jarvis",
                "stop maar",
                "tot ziens",
                "ga rusten",
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