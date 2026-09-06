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
            # STANDBY / STOP LUISTEREN (terug naar wake word)
            # Gebruik word-boundary regex zodat "ik ga slapen"
            # NIET matcht op "ga slapen".
            # =========================================

            import re

            STANDBY_PATTERNS = [
                r"^ga slapen$",
                r"^ga maar slapen$",
                r"^stop jarvis$",
                r"^stop maar$",
                r"^tot ziens$",
                r"^welterusten$",
                r"^rustig aan$",
                r"^doe rustig$",
                r"^ga weg$",
            ]

            if any(re.match(p, command) for p in STANDBY_PATTERNS):
                speak("Oke, ik luister niet meer. Roep me als je me nodig hebt.")
                break

            # =========================================
            # COMMANDO VERWERKEN (via Brain/Agent)
            # =========================================

            response = process_command(command)

            if response:
                speak(response)

            # =========================================
            # SLAPEN NA AGENT ROUTINE (slaapmodus)
            # =========================================

            if "slaapmodus is ingesteld" in response.lower():
                speak("Welterusten.")
                break


if __name__ == "__main__":
    start_jarvis()