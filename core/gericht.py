"""Tegen wie praat u? (Fase 31, M1)

Binnen de minuut doorluisteren (Fase 28) hoort JARVIS ook wat u tegen een
ander in de kamer zegt. :func:`beoordeel` beslist per zin of hij voor JARVIS
is. Alleen voor zinnen zónder "JARVIS" ná de eerste in een sessie: met
"JARVIS" erbij is het altijd voor hem.

1. Vaste regels (snel): staat er een vraag van JARVIS open of een ja/nee,
   begint de zin met een commando ("zet", "open", "kun je …"), of is het een
   korte vervolgvraag ("en morgen?") → voor JARVIS. Lachen, groeten, "kom je
   …", "mam" → voor iemand anders.
2. Twijfel → Ollama op deze pc (nooit de cloud), met een korte tijdslimiet.
3. Nog steeds onduidelijk → niet voor JARVIS: liever een keer "JARVIS"
   opnieuw zeggen dan een actie die niet bedoeld was.
"""

import logging
import re
import threading

logger = logging.getLogger("jarvis.gericht")

VOOR_JARVIS = "jarvis"
ANDERS = "anders"
TWIJFEL = "twijfel"

AI_TIMEOUT = 3.0  # seconden

_WERKWOORDEN = frozenset("""
zet doe open start sluit speel pauzeer stop maak dim demp schakel draai vergrendel herstart
toon zoek onthoud vergeet stuur lees herinner wek geef noem verbeter installeer weiger
volgende vorige skip annuleer activeer deactiveer verplaats plan voeg verwijder wis
""".split())

# Na deze werkwoorden een persoonlijk voornaamwoord = een vraag aan iemand
# ("ga je mee?", "kom je eten?"), geen bevel aan JARVIS.
_PERSOON = frozenset(["je", "jij", "jullie", "we", "wij", "ik", "ze", "hij", "zij"])

_BELEEFD_COMMANDO = re.compile(r"^(kun|kan|wil|zou|kunt|wilt)\s+(je|jij|u)\s+(\w+\s+){0,6}\w*"
                               r"(aan|uit|open|dicht|zetten|doen|openen|sluiten|starten|spelen|"
                               r"zoeken|opzoeken|herinneren|onthouden|maken|dimmen|harder|zachter|"
                               r"vertellen|noemen|geven|sturen|lezen|voorlezen|afspelen|pauzeren|"
                               r"stoppen|herstarten|installeren|vergrendelen)$")

_VERVOLG = re.compile(r"^(en|of|maar|ook)\s+\w+(\s+\w+){0,3}$")

_JARVIS_VRAAG = re.compile(
    r"^(hoe\s+laat|hoeveel|hoe\s+ver|hoe\s+lang|hoe\s+warm|hoe\s+koud|welke\s+dag|welke\s+datum|"
    r"wat\s+voor\s+weer|wat\s+is\s+het\s+weer|wat\s+is\s+de\s+(temperatuur|datum)|"
    r"wat\s+staat\s+er|wat\s+heb\s+ik|heb\s+ik\s+(nog\s+)?(nieuwe\s+)?(mail|mails|dm|dms|afspraken|deadlines)|"
    r"wat\s+speelt\s+er|welk\s+nummer|wie\s+zingt|is\s+de\s+game[\s-]?pc)\b")

_LACHEN = re.compile(r"^(ha){2,}h?\b|^(he){2,}\b|^hihi|^lol\b|^xd\b")
_GROET = re.compile(r"^(hoi|hey|hallo|doei|dag|later|tot\s+(straks|zo|morgen|later)|"
                    r"welterusten|slaap\s+lekker|goedemorgen|goedenavond)\b")
_JOH = re.compile(r"\b(joh|man|bro|gast|gozer|jongens|meid|schat)$")
_AANSPREKEN = re.compile(r"^(mam|mama|pap|papa|ma|pa|oma|opa|bro|jongens|schat)\b|\b(mam|mama|pap|papa)$")
_GESPREK_VRAAG = re.compile(r"^(kom|ben|heb|ga|zie|weet|hoor|snap|wil|moet|kan|kun|mag|zal|doe|eet|lust|"
                            r"zit|lig|sta|loop|werk|speel|wacht)\s+(je|jij|jullie)\b")


def _norm(tekst):
    t = str(tekst or "").lower()
    t = re.sub(r"[^\w\s%-]", " ", t)
    return " ".join(t.split())


def regels(zin, open_vraag=False):
    """VOOR_JARVIS, ANDERS of TWIJFEL, alleen met vaste regels."""

    t = _norm(zin)
    if not t:
        return ANDERS
    woorden = t.split()
    if "jarvis" in woorden or open_vraag:
        return VOOR_JARVIS
    if _LACHEN.search(t) or _GROET.search(t) or _AANSPREKEN.search(t):
        return ANDERS
    if _BELEEFD_COMMANDO.match(t):
        return VOOR_JARVIS
    if _GESPREK_VRAAG.match(t):
        return ANDERS
    if woorden[0] in _WERKWOORDEN and (len(woorden) == 1 or woorden[1] not in _PERSOON):
        return VOOR_JARVIS
    if _JARVIS_VRAAG.match(t) or _VERVOLG.match(t):
        return VOOR_JARVIS
    if _JOH.search(t):
        return ANDERS
    return TWIJFEL


INSTRUCTIE = (
    "Je bepaalt of een gesproken zin bedoeld is voor JARVIS, een Nederlandse spraakassistent "
    "die lampen, muziek, de pc en vragen afhandelt, of voor een ander persoon in de kamer. "
    "Een opdracht, een vraag aan de assistent of een vervolg op zijn vorige antwoord is voor JARVIS. "
    "Een praatje, een reactie op iemand anders of een vraag aan een huisgenoot of vriend is dat niet. "
    "Antwoord met precies één woord: JARVIS of ANDERS."
)


def _std_ai(berichten):
    from core import llm

    antwoord = llm.chat(messages=berichten)  # nooit cloud=True: dit blijft lokaal
    return str(getattr(antwoord.message, "content", "") or "")


def _met_tijdslimiet(fn, timeout):
    uitkomst = []

    def _draai():
        try:
            uitkomst.append(fn())
        except Exception:
            logger.debug("Gericht: AI-aanroep mislukt", exc_info=True)

    thread = threading.Thread(target=_draai, name="jarvis-gericht", daemon=True)
    thread.start()
    thread.join(timeout)
    return uitkomst[0] if uitkomst else None


def vraag_ai(zin, vorige_antwoord="", ai_fn=None, timeout=AI_TIMEOUT):
    """VOOR_JARVIS of ANDERS volgens Ollama; TWIJFEL als die niets zegt."""

    gebruiker = f'JARVIS zei net: "{vorige_antwoord[:300]}"\n' if vorige_antwoord else ""
    gebruiker += f'Daarna hoorde hij: "{str(zin)[:300]}"\nVoor wie is deze zin?'
    berichten = [{"role": "system", "content": INSTRUCTIE}, {"role": "user", "content": gebruiker}]
    antwoord = _met_tijdslimiet(lambda: (ai_fn or _std_ai)(berichten), timeout)
    if not antwoord:
        return TWIJFEL
    a = antwoord.strip().upper()
    if a.startswith("JARVIS"):
        return VOOR_JARVIS
    if a.startswith("ANDERS"):
        return ANDERS
    return TWIJFEL


def _open_vraag():
    """Wacht JARVIS op een antwoord (wedervraag of ja/nee)?"""

    try:
        from core import confirmation, vervolg

        return bool(confirmation.get_pending()) or vervolg.open_vraag() is not None
    except Exception:
        return False


def beoordeel(zin, vorige_antwoord="", open_vraag=None, ai_fn=None):
    """True als de zin voor JARVIS is. Bij twijfel False (niets doen)."""

    if open_vraag is None:
        open_vraag = _open_vraag()
    uitkomst = regels(zin, open_vraag)
    if uitkomst == TWIJFEL:
        uitkomst = vraag_ai(zin, vorige_antwoord, ai_fn)
    logger.info("Gericht aan JARVIS? %s", uitkomst)
    return uitkomst == VOOR_JARVIS
