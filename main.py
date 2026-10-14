import atexit
import logging
import re
import time

from config import AI_MODEL, JARVIS_NAME, USER_NAME, MIC_DEVICE
from core import llm
from core.logging_config import setup_logging
from voice.audio_stream import AudioSource, set_audio_source
from voice.listen import listen
from voice.speak import speak
from voice.wakeword import wait_for_wake_word
from core.brain import process_command
from core.confirmation import clear_pending, get_pending

logger = logging.getLogger(__name__)

# Crash-bescherming van de hoofdlus: meer dan MAX_CRASHES onverwachte
# fouten binnen CRASH_WINDOW_SECONDS seconden => JARVIS stopt netjes.
MAX_CRASHES = 5
CRASH_WINDOW_SECONDS = 60

# Fail-closed wake-word: zonder geldig wake word verwerkt JARVIS nooit
# audio. Na dit aantal mislukte pogingen achter elkaar stopt hij met een
# duidelijke melding in plaats van eindeloos door te proberen.
MAX_WAKE_FAILURES = 3
WAKE_RETRY_SECONDS = 5
MISSING_WAKE_MODEL_MESSAGE = (
    "Het wake word-model ontbreekt, ik kan niet luisteren. Zie de README."
)
STOP_MISSING_WAKE_MODEL_MESSAGE = (
    "Het wake word-model ontbreekt nog steeds. Ik kan niet luisteren en stop er mee."
)

# Aanheffen die aan het BEGIN van een herkende tekst mogen worden verwijderd.
WAKE_PHRASES = (
    "hey jarvis",
    "hé jarvis",
    "hee jarvis",
    "hoi jarvis",
    "jarvis",
)


def strip_wake_phrase(text):
    """Verwijdert een wake-word-aanhef aan het BEGIN van de tekst.

    Herkent 'hey jarvis', 'hé jarvis', 'hee jarvis', 'hoi jarvis' en
    'jarvis', eventueel gevolgd door een komma. Alleen aan het begin;
    voorkomens elders (bijv. 'zet jarvis aan') blijven ongewijzigd.
    """
    if not text:
        return text

    lowered = text.lower()

    for phrase in WAKE_PHRASES:
        if lowered.startswith(phrase):
            rest = text[len(phrase):].lstrip(" \t")
            if rest.startswith(","):
                rest = rest[1:].lstrip(" \t")
            return rest.strip()

    return text


class CrashLimiter:
    """Telt onverwachte crashes binnen een tijdsvenster.

    ``register_crash()`` geeft True zolang het aantal crashes in het
    venster de limiet niet overschrijdt; daarna False (stop de lus).
    """

    def __init__(self, max_crashes=MAX_CRASHES,
                 window_seconds=CRASH_WINDOW_SECONDS, clock=time.monotonic):
        self.max_crashes = max_crashes
        self.window_seconds = window_seconds
        self.clock = clock
        self.crashes = []

    def register_crash(self):
        now = self.clock()
        self.crashes = [t for t in self.crashes if now - t <= self.window_seconds]
        self.crashes.append(now)
        return len(self.crashes) <= self.max_crashes


def run_protected(action, limiter, on_continue=None):
    """Voer ``action`` uit en houd de lus in leven bij een onverwachte fout.

    Geeft "ok", "continue" of "stop" terug. KeyboardInterrupt wordt
    doorgegeven aan de aanroeper (die hem netjes afhandelt).
    """
    try:
        action()
        return "ok"
    except KeyboardInterrupt:
        raise
    except Exception:
        logger.exception("Onverwachte fout in de hoofdlus")
        if not limiter.register_crash():
            return "stop"
        if on_continue is not None:
            try:
                on_continue()
            except Exception:
                logger.exception("Kon de herstelmelding niet uitspreken")
        return "continue"


def run_wake_cycle():
    """Eén wake-word-sessie: wachten, luisteren en opdrachten verwerken.

    Geeft "geen_wake_word" terug als er geen geldige wake-word-detectie is
    (bijv. het model ontbreekt of de audiobron is gestopt). Er wordt dan
    GEEN audio verwerkt: JARVIS luistert nooit zonder wake word.
    """

    wake_result = wait_for_wake_word()
    detected_at = None
    if isinstance(wake_result, dict):
        detected_at = wake_result.get("detected_at")

    if detected_at is None:
        # Fail-closed: zonder wake word geen piep, geen opname, geen commando.
        reden = "onbekend"
        if isinstance(wake_result, dict):
            reden = wake_result.get("status") or "onbekend"
        logger.warning(
            "Geen wake word gedetecteerd (status: %s); ik verwerk geen audio.",
            reden,
        )
        return "geen_wake_word"

    # Een eventueel openstaande bevestiging hoort bij de vorige
    # luistersessie: bij een nieuwe wake word wist JARVIS hem, zodat
    # een "ja" later nooit alsnog een afsluiting uitvoert.
    clear_pending()

    # Replace "Ja, ..." with short beep (configurable; speech optional)
    try:
        speak(beep_only=True)
    except Exception:
        speak(f"Ja, {USER_NAME}?")

    # De eerste opdracht begint bij het detectiemoment; elke volgende
    # opdracht begint waar de vorige opname stopte (start_ts=None gebruikt
    # de lees-cursor). Zo wordt dezelfde audio nooit opnieuw herkend.
    next_ts = detected_at

    while True:

        command = listen(start_ts=next_ts)
        next_ts = None

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

            logger.warning("JARVIS kon je niet verstaan.")

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
            logger.warning("JARVIS kon je niet verstaan.")
            if get_pending():
                speak("Ik hoorde het niet goed. Zeg duidelijk ja of nee, of noem de plek nog eens.")
            else:
                speak("Sorry, ik verstond je niet. Kun je het herhalen?")
            continue

        if not isinstance(command, str):

            logger.warning("JARVIS kreeg geen tekst terug.")
            continue

        command = strip_wake_phrase(command).strip()

        if not command:
            logger.warning("Lege opdracht.")
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
            logger.warning("Onverwacht antwoordtype: %s", type(response))

    return "ok"


def start_jarvis():
    setup_logging()
    logger.info("🚀 JARVIS gestart")

    # Controleer één keer of het geconfigureerde model in Ollama staat.
    if not llm.check_model_available():
        message = (
            f"Let op: het model {AI_MODEL} is niet gevonden. "
            f"Draai: ollama pull {AI_MODEL}"
        )
        logger.error(message)
        try:
            speak(message)
        except Exception:
            logger.exception("Kon de modelwaarschuwing niet uitspreken")

    audio_source = AudioSource(device=MIC_DEVICE)
    set_audio_source(audio_source)
    audio_source.start()
    atexit.register(audio_source.stop)

    limiter = CrashLimiter()
    wake_failures = 0
    wake_status = "ok"

    def _cycle():
        nonlocal wake_status
        wake_status = run_wake_cycle()

    try:
        speak("JARVIS is online.")

        while True:

            wake_status = "ok"

            outcome = run_protected(
                _cycle,
                limiter,
                on_continue=lambda: speak("Er ging iets mis, ik ga door."),
            )

            if outcome == "stop":
                logger.error(
                    "Meer dan %d crashes binnen %d seconden: JARVIS stopt.",
                    limiter.max_crashes,
                    limiter.window_seconds,
                )
                speak("Er ging meerdere keren iets mis, ik stop er mee.")
                break

            if wake_status == "geen_wake_word":
                wake_failures += 1
                logger.warning(
                    "Geen geldig wake word (poging %d/%d); ik verwerk geen audio.",
                    wake_failures,
                    MAX_WAKE_FAILURES,
                )

                # De melding maar één keer uitspreken; daarna stil opnieuw
                # proberen, zodat JARVIS niet elke 5 seconden blijft praten.
                if wake_failures == 1:
                    speak(MISSING_WAKE_MODEL_MESSAGE)

                if wake_failures >= MAX_WAKE_FAILURES:
                    logger.error(
                        "Wake word-model ontbreekt na %d pogingen: JARVIS stopt.",
                        wake_failures,
                    )
                    speak(STOP_MISSING_WAKE_MODEL_MESSAGE)
                    break

                time.sleep(WAKE_RETRY_SECONDS)
                continue

            wake_failures = 0

    except KeyboardInterrupt:
        logger.info("JARVIS gestopt door de gebruiker (Ctrl+C).")
        speak("Tot ziens.")
    finally:
        audio_source.stop()


if __name__ == "__main__":
    start_jarvis()
