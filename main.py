import re

from config import JARVIS_NAME, USER_NAME
from voice.listen import listen
from voice.speak import speak
from voice.wakeword import wait_for_wake_word
from core.brain import process_command
from core.confirmation import clear_pending, get_pending


def start_jarvis():

    print("🚀 JARVIS gestart")

    speak("JARVIS is online.")

    while True:

        # =============================================
        # WACHT OP WAKE WORD
        # =============================================

        wake_result = wait_for_wake_word()
        preamble = None
        if isinstance(wake_result, dict) and "audio" in wake_result:
            preamble = wake_result["audio"]
        elif wake_result is True:
            preamble = None

        # Een eventueel openstaande bevestiging hoort bij de vorige
        # luistersessie: bij een nieuwe wake word wist JARVIS hem, zodat
        # een "ja" later nooit alsnog een afsluiting uitvoert.
        clear_pending()

        # Replace "Ja, ..." with short beep (configurable; speech optional)
        try:
            speak(beep_only=True)
        except Exception:
            speak(f"Ja, {USER_NAME}?")

        # =============================================
        # OPDRACHTEN LUISTEREN
        # =============================================

        while True:

            command = listen(preamble_audio=preamble)

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

                if get_pending():
                    speak("Ik hoorde het niet goed. Zeg duidelijk ja of nee, of noem de plek nog eens.")
                else:
                    speak("Sorry, ik verstond je niet. Kun je het herhalen?")

                continue

            # Handle specific error states
            if command == "NO_CONNECTION":
                speak("Ik heb geen verbinding met de spraakherkenning")
                break  # Exit to wake word

            if command == "NOT_UNDERSTOOD":
                print("⚠️ JARVIS kon je niet verstaan.")
                if get_pending():
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
                # Bij standby wist JARVIS elke openstaande bevestiging:
                # een "ja" tijdens het slapen mag niets meer uitvoeren.
                clear_pending()
                speak("Oke, ik luister niet meer. Roep me als je me nodig hebt.")
                break

            # =========================================
            # COMMANDO VERWERKEN (via Brain/Agent)
            # =========================================

            response = process_command(command)

            if isinstance(response, str) and response:
                speak(response)

                if "slaapmodus is ingesteld" in response.lower():
                    speak("Welterusten.")
                    break
            elif response is not None and not isinstance(response, str):
                print(f"⚠️ Onverwacht antwoordtype: {type(response)}")


if __name__ == "__main__":
    start_jarvis()