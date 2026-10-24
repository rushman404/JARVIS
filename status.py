"""Consistente statusmeldingen en reactietijd in de console (Fase 17, D).

JARVIS laat per fase zien wat hij doet, in dezelfde stijl:

    💤 JARVIS wacht op wake word...
    🎙️ Luistert naar u...
    Jij: wat is de hoofdstad van frankrijk?
    🧠 Denkt na: wat is de hoofdstad van frankrijk?
    🗣️ JARVIS: De hoofdstad van Frankrijk is Parijs.
    💬 Reactie: eerste woord na 0.84s, klaar na 3.21s.

De module meet de reactietijd vanaf het moment dat JARVIS het commando
heeft gekregen, zodat de latency-doelen van Fase 17 direct zichtbaar zijn.

Er zitten géén projectimports in deze module, zodat zowel ``core`` als
``voice`` hem kan gebruiken zonder een cirkelvormige afhankelijkheid te
maken (die twee lagen importeren elkaar namelijk niet).
"""

import collections
import itertools
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

# Tijd van het begin van de huidige beurt en van het eerste woord van het
# model. None zodat duidelijk is of er al een meting loopt.
_start = None
_eerste = None

# Huidige fase voor de spraakstatus-orb op het dashboard (Fase 18):
# "rust" (wacht op het wake word), "luistert", "denkt" of "spreekt".
# Of JARVIS op dit moment echt praat, komt live uit voice.speak; deze
# waarde is de laatst gemelde fase.
FASE_RUST = "rust"
FASE_LUISTERT = "luistert"
FASE_DENKT = "denkt"
FASE_SPREEKT = "spreekt"
_fase = FASE_RUST
# De fase vóór het spreken; daar gaat de orb na het spreken naar terug
# (zie ``klaar_met_spreken``).
_fase_voor_spreken = FASE_RUST

# De laatste beurten van het gesprek, voor het Gesprek-paneel op het
# dashboard (Fase 18). Alleen in het geheugen; nooit naar schijf.
MAX_GESPREK = 12
MAX_GESPREK_TEKST = 500
_gesprek = collections.deque(maxlen=MAX_GESPREK)
_gesprek_lock = threading.Lock()
_gesprek_id = itertools.count(1)


# --- Taaksoort (Fase 17, E — reactiesnelheid per taaksoort) ---
# JARVIS onderscheidt drie soorten opdrachten:
#   * "actie"    — een concrete handeling: meteen melden dat hij bezig is.
#   * "research" — zoeken/lezen: mag langer duren, dus kort melden dat hij
#                  gaat opzoeken.
#   * "gesprek"  — een gewone vraag of praatje: geen extra melding.
TAAK_ACTIE = "actie"
TAAK_RESEARCH = "research"
TAAK_GESPREK = "gesprek"

# Woorden die op een concrete handeling wijzen (Pc-besturing en media).
_ACTIE_WOORDEN = (
    "open", "openen", "start", "starten", "lanceer", "lancering",
    "sluit", "sluiten", "beeindig", "beëindig", "afsluiten", "stop",
    "speel", "speel af", "pauzeer", "pauze", "volgende", "vorige",
    "volume", "harder", "zachter", "dempen", "mute",
    "verklein", "minimaliseer", "maximaliseer", "vergroot", "herstel",
    "maak een schermafbeelding", "screenshot", "maak een map",
    "hernoem", "verplaats", "verwijder", "zet uit", "zet aan",
    "doe uit", "doe aan", "schakel",
)

# Woorden die op research wijzen (zoeken, lezen, actuele info).
_RESEARCH_WOORDEN = (
    "zoek", "zoeken", "zoek op", "zoek eens", "zoek uit",
    "google", "research", "onderzoek", "kijk eens naar",
    "nieuws", "weer", "weersverwachting",
    "wat is het laatste", "laatste nieuws",
    "lees de pagina", "lees deze pagina", "lees de website",
    "prijzen", "reis", "vakantie",
)

_ACTIE_PATROON = re.compile(
    r"^(open|start|lanceer|sluit|beeindig|beëindig|speel|pauzeer|"
    r"verklein|maximaliseer|vergroot|herstel|volume)\b"
)
_RESEARCH_PATROON = re.compile(
    r"^(zoek|google|research|onderzoek|nieuws|weer)\b"
)


def taaksoort(commando):
    """Bepaalt wat voor soort opdracht dit is (Fase 17, E).

    Geeft ``"actie"`` bij een concrete handeling, ``"research"`` bij zoeken
    of actuele informatie, en anders ``"gesprek"``. Zo kan JARVIS bij een
    actie meteen iets zeggen en bij research melden dat het even duurt.
    """
    if not commando or not isinstance(commando, str):
        return TAAK_GESPREK

    tekst = commando.strip().lower()
    if not tekst:
        return TAAK_GESPREK

    if _RESEARCH_PATROON.match(tekst) or _RESEARCH_WOORDEN[0] in tekst:
        # "zoek"/"google" aan het begin is sterk; losse woorden alleen als
        # ze echt op een zoekopdracht wijzen.
        if _RESEARCH_PATROON.match(tekst):
            return TAAK_RESEARCH

    if _ACTIE_PATROON.match(tekst):
        return TAAK_ACTIE

    for woord in _RESEARCH_WOORDEN:
        if woord in tekst:
            return TAAK_RESEARCH

    for woord in _ACTIE_WOORDEN:
        if f" {woord} " in f" {tekst} ":
            return TAAK_ACTIE

    return TAAK_GESPREK


def reset():
    "Zet de lopende reactietijd-meting weer leeg (ook handig in tests)."
    global _start, _eerste, _fase

    _start = None
    _eerste = None
    _fase = FASE_RUST


def noteer_gesprek(wie, tekst):
    """Onthoudt één beurt: ``wie`` is "me" (u) of "ai" (JARVIS)."""
    if wie not in ("me", "ai") or not isinstance(tekst, str):
        return
    tekst = tekst.strip()
    if not tekst:
        return
    with _gesprek_lock:
        _gesprek.append({
            "id": next(_gesprek_id),
            "wie": wie,
            "tekst": tekst[:MAX_GESPREK_TEKST],
            "tijd": time.time(),
        })


def gesprek():
    """De laatste beurten, oudste eerst (kopieën)."""
    with _gesprek_lock:
        return [dict(b) for b in _gesprek]


def fase():
    """De laatst gemelde fase: "rust", "luistert", "denkt" of "spreekt"."""
    return _fase


def klaar_met_spreken():
    """JARVIS is klaar met praten: de fase "spreekt" vervalt weer.

    Luisterde hij vóór het praten (sessie), dan terug naar "luistert";
    anders naar "rust". Zonder deze stap bleef de orb op "spreekt" staan
    na een melding of antwoord buiten een gesprek om (Fase 18).
    """
    global _fase

    if _fase == FASE_SPREEKT:
        _fase = FASE_LUISTERT if _fase_voor_spreken == FASE_LUISTERT else FASE_RUST


def wacht():
    """Meldt dat JARVIS weer op het wake word wacht (fase "rust")."""
    global _fase

    _fase = FASE_RUST


def is_gestart():
    """Of er al een meting voor de huidige beurt loopt."""
    return _start is not None


def heeft_gepraat():
    """Of JARVIS deze beurt al begonnen is met praten (streaming)."""
    return _eerste is not None


def meld_taak(soort):
    """Geeft een korte gesproken melding passend bij de taaksoort.

    Wordt alleen gebruikt als een actie of research echt even duurt; zie
    ``core/melding.py``. Lege tekst in de config betekent: niets zeggen.
    De tekst volgt de taal van het gesprek (Fase 17, F).
    """
    import taal
    from config import (
        MELDING_ACTIE,
        MELDING_ACTIE_EN,
        MELDING_RESEARCH,
        MELDING_RESEARCH_EN,
    )

    engels = taal.is_engels()

    if soort == TAAK_ACTIE:
        return (MELDING_ACTIE_EN if engels else MELDING_ACTIE) or ""
    if soort == TAAK_RESEARCH:
        return (MELDING_RESEARCH_EN if engels else MELDING_RESEARCH) or ""
    return ""


def beurt_begint(vraag=None, melden=True):
    """Start de meting voor de huidige beurt.

    Met ``vraag`` meldt JARVIS meteen dat hij aan het nadenken is, zodat u
    nooit in een stil gat zit terwijl het model aan het opwarmen is
    ("altijd direct melden dat hij denkt"). Met ``melden=False`` wordt alleen
    de meting gestart — handig als een andere plek het al heeft gemeld.
    """
    global _start, _eerste, _fase

    _start = time.monotonic()
    _eerste = None
    _fase = FASE_DENKT

    if melden and vraag:
        logger.info("🧠 Denkt na: %s", vraag)


def eerste_woord():
    """Noteert het moment waarop het eerste woord van het model binnen is.

    Bij streaming is dat het eerste tekststukje; bij een geblokkeerd
    antwoord blijft het None en loggen we alleen de totale tijd.
    """
    global _eerste

    if _eerste is None and _start is not None:
        _eerste = time.monotonic()


def beurt_klaar():
    """Logt de reactietijd zodra de antwoordtekst compleet is."""
    if _start is None:
        return

    totaal = time.monotonic() - _start

    if _eerste is None:
        logger.info("💬 Reactie klaar na %.2fs.", totaal)
        return

    logger.info(
        "💬 Reactie: eerste woord na %.2fs, klaar na %.2fs.",
        _eerste - _start,
        totaal,
    )


def luistert():
    """Meldt dat JARVIS naar u luistert."""
    global _fase

    _fase = FASE_LUISTERT
    logger.info("🎙️ Luistert naar u...")


def omzetten():
    """Meldt dat de opname wordt omgezet naar tekst (spraakherkenning)."""
    global _fase

    _fase = FASE_DENKT
    logger.info("🔁 Zet spraak om naar tekst...")


def spreekt(tekst):
    """Meldt wat JARVIS zegt (één regel per zin of antwoord)."""
    global _fase, _fase_voor_spreken

    if _fase != FASE_SPREEKT:
        _fase_voor_spreken = _fase
    _fase = FASE_SPREEKT
    logger.info("🗣️ JARVIS: %s", tekst)


def taalwissel():
    """Meldt in de console welke taal JARVIS nu spreekt (Fase 17, F)."""
    import taal

    logger.info("🌍 Taal: %s", taal.taal_naam())
