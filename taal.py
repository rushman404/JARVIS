"""Taal van het gesprek: Nederlands standaard, Engels opvraagbaar (Fase 17, F).

JARVIS is Nederlandstalig, maar u kunt hem vragen om Engels te spreken
(bijvoorbeeld "switch to English", "praat Engels" of "in het Engels"). De
keuze geldt voor de rest van de sessie en wordt onthouden in
``taal.json``, zodat JARVIS bij een volgende start dezelfde taal gebruikt.

Wisselen kan ook met een commando:

* naar Engels  → "switch to English", "speak English", "praat Engels"
* naar Nederlands → "switch to Dutch", "praat Nederlands", "schakel terug"

Daarnaast volgt JARVIS de taal van uw vraag (Fase 17, taal volgt uw vraag):
een overduidelijk Engelse vraag krijgt een Engels antwoord, een Nederlandse
vraag een Nederlands antwoord. Losse Engelse woorden in een Nederlandse zin
veranderen niets. Een expliciete keuze ("switch to English") wordt
vastgezet en wint altijd; met "taal mag automatisch" geeft u die weer vrij.

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

#: True als de gebruiker de taal expliciet heeft vastgezet ("switch to
#: English"). Zolang dit True is, neemt JARVIS de taal van de vraag niet
#: automatisch over; hij wacht op "taal mag automatisch".
_vastgezet = False

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

# "taal mag automatisch", "mag automatisch wisselen", "automatisch wisselen aan"
# → geeft een vaste taalkeuze weer vrij, zodat JARVIS de taal van uw vraag
#   weer mag volgen.
_VRIJGAVE = re.compile(
    r"(taal\s+mag\s+automatisch|mag\s+(weer\s+)?automatisch|"
    r"automatisch(e)?\s+(taal)?wissel(en)?\s+(aan|weer\s+aan)|"
    r"schakel\s+automatisch(e)?\s+(taal)?wissel(en)?\s+in|"
    r"volg\s+(weer\s+)?mijn\s+taal)"
)

# --- Herkenning van de taal van een vraag (Fase 17, taal volgt uw vraag) ---
# Bewust streng: alleen als de vraag OVERDUIDELIJK Engels of Nederlands is.
# Nederlandse signaalwoorden: alleen woorden die GEEN Engelse betekenis
# hebben, zodat "open", "in" of "over" geen valse Nederlandse treffer geven.
_NL_SIGNALEN = re.compile(
    r"\b(de|het|een|ik|je|jij|wij|kan|kun|kunt|wil|wilt|zal|zet|zetten|"
    r"sluit|maak|doe|geef|laat|wat|waar|waarom|hoe|welke|wanneer|"
    r"wie|als|dan|maar|ook|niet|geen|met|voor|naar|van|bij|"
    r"graag|even|misschien|alstublieft|alsjeblieft|morgen|vandaag|straks)\b"
)

_EN_SIGNALEN = re.compile(
    r"\b(the|a|an|i|you|we|can|could|would|will|please|set|open|close|make|"
    r"what|where|why|how|which|when|who|and|but|not|no|with|for|to|of|on|"
    r"at|about|my|your|is|are|was|were|do|does|did|should|turn|play|start|"
    r"stop|tell|show|find|give|let|maybe|today|tomorrow|later|again)\b"
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


def is_vastgezet():
    """True als de taal expliciet is vastgezet en niet automatisch mag wisselen."""
    return _vastgezet


def detecteer_vraagtaal(tekst):
    """Bepaalt de taal van een vraag: ``"en"``, ``"nl"`` of ``None``.

    Bewust streng (Fase 17, taal volgt uw vraag): alleen bij een vraag die
    OVERDUIDELIJK in één taal is geeft dit een oordeel. Losse Engelse woorden
    in een Nederlandse zin ("zet even Spotify op") geven ``None``: dan
    verandert er niets. Bij twijfel ook ``None``.
    """
    if not tekst or not isinstance(tekst, str):
        return None

    tekst = tekst.strip().lower()
    if not tekst or not re.search(r"[a-z]", tekst):
        return None

    woorden = re.findall(r"[a-z']+", tekst)
    if len(woorden) < 3:
        # Te kort om de taal betrouwbaar te bepalen ("oké", "spotify open").
        return None

    heeft_nl = bool(_NL_SIGNALEN.search(tekst))
    nl_aantal = len(_NL_SIGNALEN.findall(tekst))
    en_aantal = len(_EN_SIGNALEN.findall(tekst))

    # Nederlandse signaalwoorden aanwezig → geen Engelse vraag.
    if heeft_nl:
        return None

    # Engelse vraag: genoeg duidelijke Engelse signaalwoorden, en geen
    # Nederlandse. Bij twijfel (te weinig signalen) geen oordeel.
    try:
        from config import TAAL_AUTOMATISCH_DREMPEL
        drempel = max(1, int(TAAL_AUTOMATISCH_DREMPEL))
    except Exception:  # pragma: no cover - config hoort altijd te laden
        drempel = 2

    if en_aantal >= drempel:
        return ENGELS

    return None


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


def zet(code, vastgezet=True):
    """Zet de taal en bewaar die. Geeft True terug als het gewijzigd is.

    ``vastgezet=True`` (standaard) betekent: de gebruiker koos deze taal
    expliciet, dus de automaat mag hem niet meer overrulen. Bij een
    automatische wissel geeft u ``vastgezet=False`` mee.
    """
    global _taal, _vastgezet

    if code not in (NEDERLANDS, ENGELS):
        return False

    with _lock:
        gewijzigd = _taal != code or _vastgezet != bool(vastgezet)
        _taal = code
        _vastgezet = bool(vastgezet)

    if gewijzigd:
        logger.info("🌍 Taal gewijzigd naar %s.", taal_naam(code))
        _bewaar(code, _vastgezet)

    return gewijzigd


def vrijgeven():
    """Geeft een vaste taalkeuze vrij: de automaat mag weer volgen.

    Geeft True terug als er iets veranderd is.
    """
    global _vastgezet

    with _lock:
        if not _vastgezet:
            return False
        _vastgezet = False

    logger.info("🌍 Taal mag weer automatisch volgen.")
    _bewaar(_taal, False)
    return True


def volgt_vraag(tekst):
    """Past de taal aan op de taal van de vraag (Fase 17, taal volgt uw vraag).

    Doet niets als de taal vastgezet is, als de automaat uit staat, of als de
    vraag geen duidelijk oordeel geeft. Geeft de nieuwe taal terug als er
    gewisseld is, anders ``None``.
    """
    if _vastgezet:
        return None

    try:
        from config import TAAL_AUTOMATISCH
        if not TAAL_AUTOMATISCH:
            return None
    except Exception:  # pragma: no cover - config hoort altijd te laden
        pass

    doel = detecteer_vraagtaal(tekst)
    if doel is None or doel == _taal:
        return None

    zet(doel, vastgezet=False)
    return doel


def wissel(commando):
    """Verwerkt een taalwissel-commando.

    Geeft de bevestigingszin terug, of ``None`` als het commando geen
    taalwissel (of vrijgave) is.
    """
    if not commando or not isinstance(commando, str):
        return None

    tekst = commando.strip().lower()

    if _VRIJGAVE.search(tekst):
        vrijgeven()
        return ("Prima, ik volg weer de taal van je vraag."
                if not is_engels() else
                "Fine, I'll follow the language of your question again.")

    code = detecteer_wissel(commando)
    if code is None:
        return None

    zet(code, vastgezet=True)

    if code == ENGELS:
        return "Understood, I'll speak English from now on."
    return "Prima, ik praat weer Nederlands."


def _bewaar(code, vastgezet=None):
    """Schrijft de taalkeuze weg (best-effort; fouten zijn niet fataal)."""
    if vastgezet is None:
        vastgezet = _vastgezet
    try:
        with open(_taal_bestand_pad(), "w", encoding="utf-8") as bestand:
            json.dump({"taal": code, "vastgezet": bool(vastgezet)}, bestand)
    except Exception:
        logger.exception("Kon de taalkeuze niet opslaan")


def laad():
    """Leest de bewaarde taalkeuze (best-effort)."""
    global _taal, _vastgezet

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
            # Oud bestand zonder dit veld: behandel als vastgezet, zodat de
            # automaat een eerdere expliciete keuze niet stil overruled.
            _vastgezet = bool(data.get("vastgezet", True))

    return _taal


def reset(code=NEDERLANDS):
    """Zet de taal terug (voor tests) zonder het bestand te wijzigen."""
    global _taal, _vastgezet

    with _lock:
        _taal = code
        _vastgezet = False
