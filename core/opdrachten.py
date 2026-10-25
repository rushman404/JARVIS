"""Opdrachten van buiten de spraaklus (Fase 20, M1): typen op de iPad.

Het brein (``core.brain``) is niet gemaakt voor twee opdrachten tegelijk:
het gesprek, de context en een openstaande goedkeuring zijn gedeeld. Daarom:

* **Eén slot** (:data:`BREIN_LOCK`) voor élke opdracht, gesproken of
  getypt. ``main.py`` neemt hetzelfde slot rond ``process_command``.
* **Eén getypte opdracht tegelijk.** Een tweede, terwijl de eerste nog
  loopt, wordt geweigerd (geen wachtrij die ongemerkt vol loopt).
* Het antwoord komt in het gesprek-paneel (``status.noteer_gesprek``); met
  ``hardop=True`` zegt JARVIS het ook.

Een getypte opdracht telt als activiteit en maakt JARVIS ook wakker uit de
slaapstand: typen is net zo bewust als "Hey JARVIS" zeggen.
"""

import logging
import re
import threading

import status

logger = logging.getLogger("jarvis.opdrachten")

BREIN_LOCK = threading.RLock()

MAX_LENGTE = 300
# Geen stuurtekens (regeleinden, tabs, escape-reeksen): één regel tekst.
_STUURTEKENS = re.compile(r"[\x00-\x1f\x7f]")


def schoon(tekst):
    """De opdracht als nette tekst, of ``None`` als hij ongeldig is."""

    if not isinstance(tekst, str):
        return None
    tekst = " ".join(_STUURTEKENS.sub(" ", tekst).split())
    if not tekst or len(tekst) > MAX_LENGTE:
        return None
    return tekst


def _vervang_open_vraag(opdracht):
    """Staat er nog een ja/nee-vraag open en typt u iets anders dan een
    antwoord, dan vervalt die vraag en wordt de tekst een nieuwe opdracht.

    Anders slikte de vraag de opdracht in ("Zeg duidelijk 'ja' ...").
    Een getypt "ja" of "nee" blijft gewoon het antwoord op de vraag.
    """

    from core import confirmation

    pending = confirmation.get_pending()
    if not pending:
        return
    try:
        antwoord = confirmation.evaluate_answer(opdracht.lower(), pending.get("kind"))
    except Exception:
        antwoord = "unclear"
    if antwoord in ("yes", "no", "cancel"):
        return
    logger.info("Nieuwe getypte opdracht; de openstaande vraag vervalt.")
    confirmation.clear_pending()


def _maak_dashboardvriendelijk(antwoord):
    """De ja/nee-vraag zegt bij typen ook waar u hem kunt beantwoorden."""

    from core import confirmation

    if confirmation.get_pending() and "'ja' of 'nee'" in antwoord:
        return antwoord.replace(
            "Zeg 'ja' of 'nee'.",
            "Keur het goed in het oranje venster, of typ 'ja' of 'nee'.",
        )
    return antwoord


def _antwoord_als_tekst(antwoord):
    if isinstance(antwoord, str):
        return antwoord
    if antwoord is None:
        return "Dat is gelukt."
    return str(antwoord)


class OpdrachtRunner:
    """Voert getypte opdrachten één voor één uit op de achtergrond."""

    def __init__(self, verwerk_fn=None, spreek_fn=None, audit_fn=None):
        self.verwerk_fn = verwerk_fn
        self.spreek_fn = spreek_fn
        self.audit_fn = audit_fn
        self._bezig = threading.Event()
        self._thread = None

    def bezig(self):
        return self._bezig.is_set()

    def start(self, tekst, hardop=False, herkomst="dashboard"):
        """Start de opdracht. Geeft ``(True, None)`` of ``(False, reden)``."""

        opdracht = schoon(tekst)
        if opdracht is None:
            return False, "ongeldig"
        return self._begin(opdracht, hardop, herkomst, None)

    def start_routine(self, naam, hardop=False, herkomst="dashboard"):
        """Start een routine bij naam (Fase 20, M2), via de normale
        routine-uitvoering van het brein (goedkeuring per stap blijft)."""

        routine = self._routine(naam)
        if routine is None:
            return False, "onbekend"
        tekst = f"Routine '{naam}' starten"

        def verwerk(_opdracht):
            from core.brain import _execute_routine

            return _execute_routine(naam, routine, f"routine {naam}")

        return self._begin(tekst, hardop, herkomst, verwerk)

    @staticmethod
    def _routine(naam):
        if not isinstance(naam, str) or not naam:
            return None
        from core.brain import routine_manager

        try:
            return routine_manager.get_routine(naam)
        except Exception:
            return None

    def _begin(self, opdracht, hardop, herkomst, verwerk):
        if self._bezig.is_set():
            return False, "bezig"
        self._bezig.set()
        self._thread = threading.Thread(
            target=self._draai, args=(opdracht, bool(hardop), herkomst, verwerk),
            name="jarvis-opdracht", daemon=True,
        )
        self._thread.start()
        return True, None

    def _verwerk(self, opdracht):
        if self.verwerk_fn is not None:
            return self.verwerk_fn(opdracht)
        from core.brain import process_command

        return process_command(opdracht)

    def _spreek(self, tekst):
        if self.spreek_fn is not None:
            return self.spreek_fn(tekst)
        from voice.speak import speak

        return speak(tekst)

    def _draai(self, opdracht, hardop, herkomst, verwerk=None):
        from core import proactive

        try:
            with BREIN_LOCK:
                status.noteer_gesprek("me", opdracht)
                if proactive.slaapt():
                    proactive.word_wakker()
                proactive.markeer_activiteit()
                status.beurt_begint(opdracht)
                _vervang_open_vraag(opdracht)
                try:
                    if verwerk is not None:
                        antwoord = _antwoord_als_tekst(verwerk(opdracht))
                    else:
                        antwoord = _antwoord_als_tekst(self._verwerk(opdracht.lower()))
                except Exception:
                    logger.exception("Getypte opdracht mislukt.")
                    antwoord = "Er ging iets mis bij die opdracht, sir."
                antwoord = _maak_dashboardvriendelijk(antwoord)
                status.beurt_klaar()
                status.noteer_gesprek("ai", antwoord)
                self._audit(opdracht, antwoord, hardop, herkomst)
                if hardop:
                    try:
                        self._spreek(antwoord)
                    except Exception:
                        logger.exception("Kon het antwoord niet uitspreken.")
        finally:
            if not proactive.is_in_gesprek():
                status.wacht()
            self._bezig.clear()

    def _audit(self, opdracht, antwoord, hardop, herkomst):
        try:
            if self.audit_fn is not None:
                fn = self.audit_fn
            else:
                from core.audit import log_audit as fn
            fn(
                gehoord=opdracht,
                handler=herkomst,
                tool="opdracht",
                argumenten={"hardop": hardop},
                risico="low",
                resultaat=antwoord[:200],
                goedgekeurd=True,
                herkomst=herkomst,
            )
        except Exception:
            logger.debug("Audit van de opdracht mislukt.", exc_info=True)
