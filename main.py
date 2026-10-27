import atexit
import logging
import os
import re
import sys
import threading
import time

import status
import taal
from config import (
    AI_MODEL,
    BARGE_IN_ENABLED,
    JARVIS_NAME,
    MIC_DEVICE,
    NIET_BEGREPEN_DREMPEL,
    NIET_BEGREPEN_MELDING,
    SESSIE_TIMEOUT_SECONDEN,
    STREAM_ANTWOORD,
    USER_NAME,
)
from core import llm
from core import pc_target
from core.logging_config import setup_logging
from core import proactive
from core import timers as timers_module
from core.opdrachten import BREIN_LOCK
from beheer.verbinding import maak_checks as maak_verbinding_checks
from voice.audio_stream import AudioSource, set_audio_source
from voice.barge_in import BargeInMonitor
from voice.listen import listen
from voice.notify import toon_melding
from voice.speak import speak
from voice.stream_bridge import TekstStroom
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

# Slaapstand (Fase 19, M4). Exacte zinnen, zodat "ik ga slapen" (de
# slaaproutine) en "zet de pc in slaapstand" (power) er niet onder vallen.
SLAAP_PATTERNS = [
    r"^ga slapen$",
    r"^ga maar slapen$",
    r"^ga lekker slapen$",
    r"^welterusten$",
    r"^welterusten jarvis$",
    r"^slaap lekker$",
]
SLAAP_MELDING = "Goed, sir. Ik ga slapen. Zeg 'Hey JARVIS' als u me nodig heeft."
WAKKER_MELDING = "Tot uw dienst, sir."

# Exitcodes voor de waakhond (Fase 19, M2): bij 0 en GEEN_WAKE_WORD heeft
# herstarten geen zin; bij TE_VEEL_CRASHES (en elke andere code) wel.
EXIT_GESTOPT = 0
EXIT_TE_VEEL_CRASHES = 3
EXIT_GEEN_WAKE_WORD = 4
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


def _spreek_niet_begrepen(teller):
    """Vraagt om herhaling, of meldt vriendelijk dat het genoeg is geweest.

    Gebruikt de teller (Fase 17): na ``NIET_BEGREPEN_DREMPEL`` mislukkingen
    achter elkaar zegt JARVIS een vriendelijk woord in plaats van eindeloos
    door te vragen. De sessie blijft daarna gewoon open — hij blijft dus
    luisteren, maar zeurt niet aan één stuk door.
    """

    if teller.registreer():
        if NIET_BEGREPEN_MELDING:
            speak(NIET_BEGREPEN_MELDING)
        teller.reset()
        return

    if get_pending():
        speak(
            "Ik hoorde het niet goed. Zeg duidelijk ja of nee, "
            "of noem de plek nog eens."
        )
    else:
        speak("Sorry, ik verstond je niet. Kun je het herhalen?")


class NietBegrepenTeller:
    """Telt hoe vaak JARVIS de vraag achter elkaar niet verstond.

    ``registreer()`` geeft True terug zodra de drempel is bereikt; de
    aanroeper zegt dan een vriendelijk woord in plaats van eindeloos om
    herhaling te vragen. Een geslaagde herkenning wist de teller via
    ``reset()``.
    """

    def __init__(self, drempel=NIET_BEGREPEN_DREMPEL):
        self.drempel = max(1, int(drempel))
        self.aantal = 0

    def registreer(self):
        self.aantal += 1
        return self.aantal >= self.drempel

    def reset(self):
        self.aantal = 0


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


def _pas_volume(waarde):
    """Past het spreekvolume aan (wordt door de engine gebruikt voor de
    nachtmodus: zachter 's nachts, vol volume overdag)."""

    from voice.speak import set_volume
    set_volume(waarde)


def spreek_antwoord(response, stroom=None):
    """Spreekt het antwoord van een commando uit (Fase 17, A3).

    Heeft de :class:`~voice.stream_bridge.TekstStroom` het antwoord al
    streamend uitgesproken, dan wordt de volledige tekst niet nog eens
    herhaald. Geeft True terug als er iets met het antwoord is gedaan.
    """

    if not isinstance(response, str) or not response:
        return False

    if stroom is not None and stroom.gestreamd:
        return True

    speak(response)
    return True


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

    proactive.set_in_gesprek(True)
    try:
        # Een eventueel openstaande bevestiging hoort bij de vorige
        # luistersessie: bij een nieuwe wake word wist JARVIS hem, zodat
        # een "ja" later nooit alsnog een afsluiting uitvoert.
        clear_pending()

        # Sliep JARVIS (Fase 19, M4)? Dan maakt het wake word hem wakker.
        # Na "ga slapen" groet hij; na de auto-slaap volstaat de piep.
        slaap_reden = proactive.slaap_reden()
        if slaap_reden is not None:
            proactive.word_wakker()

        if slaap_reden == proactive.SLAAP_COMMANDO:
            speak(WAKKER_MELDING)
        else:
            # Replace "Ja, ..." with short beep (configurable; speech optional)
            try:
                speak(beep_only=True)
            except Exception:
                speak(f"Ja, {USER_NAME}?")

        # Sessie-modus (Fase 17, B2): één wake word houdt het gesprek open.
        # Binnen de sessie hoeft u geen "JARVIS" te zeggen; de lange wachttijd
        # hieronder bepaalt wanneer de sessie eindigt. De eerste opdracht
        # begint bij het detectiemoment; elke volgende opdracht begint waar de
        # vorige opname stopte (start_ts=None gebruikt de lees-cursor). Zo
        # wordt dezelfde audio nooit opnieuw herkend.
        next_ts = detected_at

        # Fase 17: houdt bij hoe vaak JARVIS de vraag achter elkaar niet
        # verstond, zodat hij na de drempel vriendelijk ophoudt met zeuren.
        niet_begrepen = NietBegrepenTeller(NIET_BEGREPEN_DREMPEL)

        while True:

            command = listen(start_ts=next_ts, wacht_seconden=SESSIE_TIMEOUT_SECONDEN)
            next_ts = None

            # -----------------------------------------
            # SESSIE VERLOPEN: TE LANG NIETS GEHOORD
            # -----------------------------------------

            if command == "":
                logger.info(
                    "💤 Sessie verlopen: %s seconden geen spraak. "
                    "Het wake word is weer nodig.",
                    SESSIE_TIMEOUT_SECONDEN,
                )
                break

            # -----------------------------------------
            # JARVIS HEERDE WEL IETS, MAAR VERSTOND HET NIET
            # (blijft hierdoor wakker, gaat niet slapen)
            # -----------------------------------------

            if command is None:

                logger.warning("JARVIS kon je niet verstaan.")
                _spreek_niet_begrepen(niet_begrepen)

                continue

            # Handle specific error states
            if command == "NO_CONNECTION":
                speak("Ik heb geen verbinding met de spraakherkenning")
                break  # Exit to wake word

            if command == "NOT_UNDERSTOOD":
                logger.warning("JARVIS kon je niet verstaan.")
                _spreek_niet_begrepen(niet_begrepen)
                continue

            if not isinstance(command, str):

                logger.warning("JARVIS kreeg geen tekst terug.")
                continue

            command = strip_wake_phrase(command).strip()

            if not command:
                logger.warning("Lege opdracht.")
                continue

            command = command.lower().strip()

            # Een verstaanbare opdracht wist de niet-begrepen-teller.
            niet_begrepen.reset()

            # =========================================
            # STANDBY / STOP LUISTEREN (terug naar wake word)
            # Gebruik word-boundary regex zodat "ik ga slapen"
            # NIET matcht op "ga slapen".
            # =========================================

            # Slaapstand (Fase 19, M4): alleen het wake word maakt hem
            # weer wakker. "ik ga slapen" blijft de slaaproutine.
            if any(re.match(p, command) for p in SLAAP_PATTERNS):
                clear_pending()
                proactive.ga_slapen(proactive.SLAAP_COMMANDO)
                speak(SLAAP_MELDING)
                break

            STANDBY_PATTERNS = [
                r"^stop jarvis$",
                r"^stop maar$",
                r"^tot ziens$",
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

            # Barge-in (Fase 17, B1): terwijl JARVIS denkt en praat, let de
            # monitor op een onderbreking (uw stem of de sneltoets). Zonder
            # audiobron (test/opstart) stopt de monitor vanzelf.
            stop_event = threading.Event()
            barge = None
            if BARGE_IN_ENABLED:
                barge = BargeInMonitor(stop_event=stop_event)
                barge.start()

            status.noteer_gesprek("me", command)
            try:
                stroom = TekstStroom(stop_event=stop_event) if STREAM_ANTWOORD else None
                try:
                    # Eén opdracht tegelijk door het brein: een getypte
                    # opdracht van de iPad (Fase 20) wacht hier op zijn beurt.
                    with BREIN_LOCK:
                        response = process_command(
                            command,
                            on_tekst=(stroom.schrijf if stroom is not None else None),
                        )
                finally:
                    if stroom is not None:
                        stroom.sluit_af()
            finally:
                if barge is not None:
                    barge.stop()

            # Onderbroken? Dan het antwoord niet afmaken, maar meteen weer
            # luisteren naar wat u zegt (vanaf het moment van onderbreken).
            if barge is not None and barge.triggered:
                logger.info("Onderbroken; ik luister verder.")
                next_ts = barge.trigger_ts
                continue

            if isinstance(response, str):
                status.noteer_gesprek("ai", response)

            if spreek_antwoord(response, stroom):

                if "slaapmodus is ingesteld" in response.lower():
                    speak("Welterusten.")
                    break
            elif response is not None and not isinstance(response, str):
                logger.warning("Onverwacht antwoordtype: %s", type(response))

    finally:
        proactive.set_in_gesprek(False)
        # De automatische taalwissel geldt alleen voor het lopende antwoord:
        # aan het einde van de sessie staat JARVIS weer in de vaste taal.
        taal.sessie_einde()
    return "ok"


def _start_dashboard(engine):
    """Start het iPad-dashboard (Fase 18) als DASHBOARD_ENABLED aan staat.

    Een onveilige of kapotte configuratie stopt JARVIS niet: het dashboard
    start dan gewoon niet en de reden komt in de log.
    """

    import config

    if not config.DASHBOARD_ENABLED:
        return None

    try:
        from dashboard.server import start_dashboard

        dienst = start_dashboard(engine=engine)
    except RuntimeError as fout:
        logger.error("Dashboard niet gestart: %s", fout)
        return None
    except OSError:
        logger.exception("Dashboard niet gestart (poort bezet of netwerkfout).")
        return None
    except Exception:
        logger.exception("Dashboard niet gestart door een onverwachte fout.")
        return None

    atexit.register(dienst.stop)
    return dienst


def start_jarvis():
    setup_logging()
    logger.info("🚀 JARVIS gestart")

    # Onthouden taalkeuze terugzetten (Fase 17, F): sprak u de vorige keer
    # Engels met JARVIS, dan pakt hij die taal nu weer op.
    try:
        taal.laad()
        logger.info("🌍 Taal: %s", taal.taal_naam())
    except Exception:
        logger.exception("Kon de taalkeuze niet laden")

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

    # Eén duidelijke melding als het doel game-pc is maar de client onbruikbaar is.
    remote_melding = pc_target.remote_client_configuratie_fout()
    if remote_melding:
        logger.error(remote_melding)
        try:
            speak(remote_melding)
        except Exception:
            logger.exception("Kon de remote-melding niet uitspreken")

    # Fase 20 (M4): met MIC_BRON=ipad blijft de pc-microfoon dicht; dan komt
    # al het geluid van het spraakpaneel op de iPad.
    from config import MIC_BRON

    audio_source = AudioSource(device=MIC_DEVICE, lokaal=(MIC_BRON != "ipad"))
    set_audio_source(audio_source)
    audio_source.start()
    atexit.register(audio_source.stop)

    # --- Proactieve engine (Fase 16A) ---
    def _lever_melding(melding):
        """Stopt een proactieve melding naar stem + Windows-toast (op PC_TARGET)."""

        tekst = getattr(melding, "tekst", None) or str(melding)
        try:
            toon_melding(JARVIS_NAME, tekst)
        except Exception:
            logger.exception("Kon de Windows-toast niet tonen.")
        speak(tekst)

    def _ha_bereikbaar():
        """True/False als HA bereikbaar/onbereikbaar, None als niet geconfigureerd."""

        from core.home_assistant import _config_ok, _ha_get

        if not _config_ok():
            return None
        ok, _data = _ha_get("/api/")
        return bool(ok)

    def _schijf_vrij_percent():
        """Geeft het vrije schijf-percentage terug (of None bij een fout)."""

        from remote.telemetry import schijf_telemetry

        resultaat = schijf_telemetry()
        if not resultaat.get("ok"):
            return None
        percentage = resultaat.get("percentage")
        if percentage is None:
            return None
        try:
            return 100.0 - float(percentage)
        except (TypeError, ValueError):
            return None

    def _pc_is_actief():
        """True als de pc recent is gebruikt (voor auto-slaap en zorg)."""

        from core.pc_activiteit import is_actief
        return is_actief()

    engine = proactive.get_engine(
        store=timers_module.get_store(),
        lever_fn=_lever_melding,
        ha_check_fn=_ha_bereikbaar,
        schijf_check_fn=_schijf_vrij_percent,
        volume_fn=_pas_volume,
        actief_check_fn=_pc_is_actief,
        in_gesprek_fn=proactive.is_in_gesprek,
        status_checks=maak_verbinding_checks(),
    )
    engine.start()
    atexit.register(engine.stop)

    _start_dashboard(engine)

    # Onder de waakhond (Fase 19, M2): hartslag bijhouden, en na een
    # herstart melden dat JARVIS weer terug is.
    if os.environ.get("JARVIS_WAAKHOND") == "1":
        from beheer.hartslag import HartslagSchrijver

        HartslagSchrijver(fase_fn=status.fase, teken_fn=status.laatste_teken).start()
    herstart_reden = os.environ.get("JARVIS_HERSTART_REDEN", "").strip()
    if herstart_reden:
        logger.warning("Herstart door de waakhond: %s", herstart_reden)
        try:
            engine.meld(
                f"Sir, ik ben om {time.strftime('%H:%M')} opnieuw opgestart "
                f"na een storing ({herstart_reden}).",
                bron="herstart",
            )
        except Exception:
            logger.exception("Kon de herstartmelding niet versturen.")

    # Slaapstand (Fase 19, M4): het AI-model gaat uit het geheugen als JARVIS
    # slaapt en wordt alvast geladen zodra hij wakker wordt.
    proactive.bij_slaap(lambda: llm.op_achtergrond(llm.ontlaad_model, "jarvis-model-uit"))
    proactive.bij_wakker(lambda: llm.op_achtergrond(llm.laad_model, "jarvis-model-aan"))

    # Updates (Fase 19, M6): dagelijks kijken en melden; installeren alleen
    # na uw "ja".
    from config import UPDATES_ENABLED

    if UPDATES_ENABLED:
        from beheer.updates import UpdatePlanner

        UpdatePlanner(meld_fn=engine.meld).start()

    # Dagelijkse backup (Fase 19, M3); een fout komt als melding binnen.
    from config import BACKUP_ENABLED

    if BACKUP_ENABLED:
        from beheer.backup import BackupPlanner

        BackupPlanner(meld_fn=engine.meld).start()

    # Gmail (Fase 23, M2): nieuwe belangrijke mail melden. Doet niets zolang
    # Gmail niet gekoppeld is.
    from config import GMAIL_MELDEN

    if GMAIL_MELDEN:
        from core.gmail import GmailPlanner

        GmailPlanner(meld_fn=engine.meld).start()

    limiter = CrashLimiter()
    exitcode = EXIT_GESTOPT
    wake_failures = 0
    wake_status = "ok"

    def _cycle():
        nonlocal wake_status
        # Een nieuwe wake-word-sessie is activiteit: dit zet een
        # eventuele auto-slaap weer uit. De "in gesprek"-vlag wordt in
        # run_wake_cycle() gezet zodra het wake word is gedetecteerd.
        engine.meld_activiteit()
        wake_status = run_wake_cycle()

    try:
        speak("JARVIS is weer online." if herstart_reden else "JARVIS is online.")

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
                exitcode = EXIT_TE_VEEL_CRASHES
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
                    exitcode = EXIT_GEEN_WAKE_WORD
                    break

                time.sleep(WAKE_RETRY_SECONDS)
                continue

            wake_failures = 0

    except KeyboardInterrupt:
        logger.info("JARVIS gestopt door de gebruiker (Ctrl+C).")
        speak("Tot ziens.")
    finally:
        audio_source.stop()

    return exitcode


if __name__ == "__main__":
    sys.exit(start_jarvis())
