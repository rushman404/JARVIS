"""Korte tussentijdse melding bij trage acties of research (Fase 17, E).

De roadmap wil dat JARVIS "acties meteen" doet en dat research "langer mag
duren". In beide gevallen mag er geen onnatuurlijke stilte vallen. Daarom
start deze module, als een commando langer duurt dan
``MELDING_MIN_SECONDEN``, een timer die één korte melding uitspreekt:

* actie    → bijvoorbeeld "Moment, ik doe het even."
* research → bijvoorbeeld "Even opzoeken, een moment."

De melding wordt alleen gegeven als JARVIS nog niet zelf begonnen is met
praten (bij een streamend antwoord hoeft het niet meer) en er geen
onderbreking (barge-in) gaande is. Zodra het antwoord klaar is, stopt de
timer en wordt er niets meer gezegd.

De teksten staan in ``config.py`` (``MELDING_ACTIE`` en ``MELDING_RESEARCH``);
een lege tekst zet de melding uit.
"""

import logging
import threading

import status
from config import MELDING_MIN_SECONDEN

logger = logging.getLogger(__name__)

#: Huidige melding-timer (of None). Eén tegelijk: JARVIS werkt taken
#: sequentieel af (Fase 17, "meerdere taken: sequentieel verwerken").
_timer = None
_lock = threading.Lock()


def _spreek(tekst):
    """Spreekt de melding uit via voice.speak (lazy import: geen cirkel)."""
    try:
        from voice.speak import speak

        # Alleen als JARVIS de melding nog nodig heeft: niet als hij al
        # zelf begonnen is met antwoorden (streaming) of onderbroken is.
        if not status.is_gestart():
            return
        if status.heeft_gepraat():
            return
        speak(tekst)
    except Exception:
        logger.exception("Kon de tussentijdse melding niet uitspreken")


def start(commando, soort):
    """Start (indien nodig) de korte melding voor deze taaksoort.

    Geeft niets terug; de timer loopt op de achtergrond en stopt bij
    :func:`stop`.
    """
    global _timer

    if not soort or soort == status.TAAK_GESPREK:
        return None

    try:
        tekst = status.meld_taak(soort)
    except Exception:
        logger.exception("Kon de meldingstekst niet bepalen")
        return None

    if not tekst:
        return None

    stop()

    with _lock:
        timer = threading.Timer(
            max(0.0, float(MELDING_MIN_SECONDEN)), _spreek, args=(tekst,)
        )
        timer.daemon = True
        _timer = timer
        timer.start()

    logger.info("⏳ Tussentijdse melding gepland (%s): %s", soort, tekst)
    return timer


def stop():
    """Stopt een lopende melding-timer (idempotent)."""
    global _timer

    with _lock:
        timer = _timer
        _timer = None

    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            logger.exception("Kon de melding-timer niet stoppen")
