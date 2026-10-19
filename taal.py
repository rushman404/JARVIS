"""Taal van het gesprek: Nederlands standaard, Engels opvraagbaar (Fase 17, F).

JARVIS is Nederlandstalig, maar u kunt hem vragen om Engels te spreken
(bijvoorbeeld "switch to English", "praat Engels" of "in het Engels"). De
keuze geldt voor de rest van de sessie en wordt onthouden in
``taal.json``, zodat JARVIS bij een volgende start dezelfde taal gebruikt.

Wisselen kan ook met een commando:

* naar Engels  → "switch to English", "speak English", "praat Engels"
* naar Nederlands → "switch to Dutch", "praat Nederlands", "schakel terug"

Deze module houdt alleen de taal bij; de spraakherkenning
(``voice.listen``) en de stem vragen de taal op via :func:`taal` en
:func:`spraak_code`.
"""

import json
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)

NEDERLANDS = "nl"
ENGELS = "en"

#: Map van de taal naar de herkenningscode voor spraakherkenning.
_SPRAAK_CODES = {NEDERLANDS: "nl-NL", ENGELS: "en-US"}

#: Map van de taal naar de naam die JARVIS in gesprekken gebruikt.
_TAAL_NAMEN = {NEDERLANDS: "Nederlands", ENGELS: "Engels"}

# Bestand waarin de taalkeuze bewaard wordt (naast de andere JARVIS-bestanden).
TAAL_BESTAND = "taal.json"

_taal = NEDERLANDS
_lock = threading.Lock()

# --- Herkenning van de taalwissel -------------------------------------

# "switch to English", "speak english", "in het engels", "praat engels"
_NAAR_ENGELS = re.compile(
    r"(switch\s+to\s+english|speak\s+english|talk\s+english|"
    r"in\s+english|english\s+please|praat\s+engels|spreek\s+engels|"
    r"in\s+het\s+engels|engels\s+praten|schakel\s+naar\s+engels|"
    r"ga\s+over\s+op\s+engels)"
)

# "switch to Dutch", "speak dutch", "in het nederlands", "praat nederlands"
_NAAR_NEDERLANDS = re.compile(
    r"(switch\s+to\s+dutch|speak\s+dutch|talk\s+dutch|"
    r"in\s+dutch|dutch\s+please|praat\s+nederlands|spreek\s+nederlands|"
    r"in\s+het\s+nederlands|nederlands\s+praten|"
    r"schakel\s+(terug\s+)?naar\s+nederlands|terug\s+naar\s+nederlands)"
)


def _taal_bestand_pad():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), TAAL_BESTAND)


def taal():
    """De taal die nu gebruikt wordt: ``"nl"`` (standaard) of ``"en"``."""
    return _taal


def taal_naam(code=None):
    """De leesbare naam van de taal ("Nederlands" / "Engels")."""
    return _TAAL_NAMEN.get(code or _taal, "Nederlands")


def spraak_code(code=None):
    """De code voor spraakherkenning bij de huidige taal (bijv. "en-US")."""
    return _SPRAAK_CODES.get(code or _taal, "nl-NL")


def is_engels():
    """True als JARVIS nu Engels spreekt."""
    return _taal == ENGELS


def detecteer_wissel(commando):
    """Bepaalt of dit commando om een taalwissel vraagt.

    Geeft ``"en"``, ``"nl"`` of ``None`` terug (geen wissel).
    """
    if not commando or not isinstance(commando, str):
        return None

    tekst = commando.strip().lower()
    if not tekst:
        return None

    if _NAAR_NEDERLANDS.search(tekst):
        return NEDERLANDS
    if _NAAR_ENGELS.search(tekst):
        return ENGELS
    return None


def zet(code):
    """Zet de taal en bewaar die. Geeft True terug als het gewijzigd is."""
    global _taal

    if code not in (NEDERLANDS, ENGELS):
        return False

    with _lock:
        gewijzigd = _taal != code
        _taal = code

    if gewijzigd:
        logger.info("🌍 Taal gewijzigd naar %s.", taal_naam(code))
        _bewaar(code)

    return gewijzigd


def wissel(commando):
    """Verwerkt een taalwissel-commando.

    Geeft de bevestigingszin terug, of ``None`` als het commando geen
    taalwissel is.
    """
    code = detecteer_wissel(commando)
    if code is None:
        return None

    zet(code)

    if code == ENGELS:
        return "Understood, I'll speak English from now on."
    return "Prima, ik praat weer Nederlands."


def _bewaar(code):
    """Schrijft de taalkeuze weg (best-effort; fouten zijn niet fataal)."""
    try:
        with open(_taal_bestand_pad(), "w", encoding="utf-8") as bestand:
            json.dump({"taal": code}, bestand)
    except Exception:
        logger.exception("Kon de taalkeuze niet opslaan")


def laad():
    """Leest de bewaarde taalkeuze (best-effort)."""
    global _taal

    try:
        with open(_taal_bestand_pad(), "r", encoding="utf-8") as bestand:
            data = json.load(bestand)
    except FileNotFoundError:
        return _taal
    except Exception:
        logger.exception("Kon de bewaarde taalkeuze niet lezen")
        return _taal

    code = data.get("taal")
    if code in (NEDERLANDS, ENGELS):
        with _lock:
            _taal = code

    return _taal


def reset(code=NEDERLANDS):
    """Zet de taal terug (voor tests) zonder het bestand te wijzigen."""
    global _taal

    with _lock:
        _taal = code
