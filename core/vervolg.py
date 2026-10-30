"""Vervolgvragen (Fase 27, M4): het antwoord op JARVIS' eigen wedervraag.

Probleem (melding 2026-10-30): "zet een deadline verslag" → JARVIS vraagt
"Wanneer moet dit af?" → u zegt "morgen om 10 uur" → JARVIS behandelde dat
als een losse zin en snapte niet meer waar het over ging.

Nu zet elke plek die iets terugvraagt een *open wedervraag* klaar met wat
er met uw antwoord moet gebeuren:

* een ``sjabloon`` ("zet een deadline: Verslag {antwoord}") dat met uw
  antwoord een volledig commando wordt, of
* een functie ``verwerk(antwoord)`` die het zelf afhandelt.

De wedervraag geldt voor precies één beurt (en hooguit een minuut). Past uw
antwoord er niet bij (bijv. u zegt iets heel anders), dan vervalt hij en
gaat uw zin gewoon door de normale keten. "Laat maar" annuleert hem.

Daarnaast onthoudt deze module de vorige beurt (vraag + antwoord), zodat een
vervolgvraag op een antwoord van een vaste route ("hoe is het weer
morgen?" … "en overmorgen?") die context ook krijgt; naar Gemini alleen als
de privacy-poort het niet persoonlijk vindt.
"""

import re
import threading
import time

TTL = 60.0                 # zo lang wacht een wedervraag op antwoord (seconden)
BEURT_TTL = 180.0          # zo lang telt de vorige beurt als context
MAX_NAAM_WOORDEN = 5
MAX_MOMENT_REST = 4        # woorden naast de datum/tijd ("morgen om 10 uur graag")

# Soorten controle: past het antwoord bij de vraag?
MOMENT = "moment"   # moet een datum of tijd bevatten
NAAM = "naam"       # kort, geen nieuw commando
TEKST = "tekst"     # alles mag (bijv. de tekst van een DM)
ZIN = "zin"         # een korte zin die geen nieuw commando is ("verslag op vrijdag")
JA = "ja"           # een ja op een aanbod ("ja", "graag", "vertel maar")
MAX_ZIN_WOORDEN = 15

ANNULEER_ANTWOORD = "Oké, laat maar."

# Zo begint een nieuw commando of een vraag: dan is het geen naam.
_COMMANDO_START = frozenset([
    "zet", "doe", "open", "sluit", "start", "stop", "speel", "pauzeer", "maak", "verwijder",
    "wat", "wie", "hoe", "waarom", "welke", "welk", "wanneer", "waar", "hoeveel", "is", "zijn",
    "kun", "kan", "wil", "heb", "geef", "vertel", "zoek", "herstart", "draai", "dim", "demp",
])
_ANNULEER = re.compile(
    r"^(?:nee|nee hoor|laat maar|laat maar zitten|annuleer|stop|niks|niets|toch niet|vergeet het|"
    r"hoeft niet|maakt niet uit)$"
)

_JA_EXTRA = re.compile(
    r"^(?:graag|zeker|vertel(?:\s+(?:maar|het|eens|verder))?(?:\s+meer)?|meer|leg(?:\s+het)?\s+(?:maar\s+)?uit"
    r"|ja\s+graag|ga\s+(?:maar\s+)?(?:door|verder))$"
)

_lock = threading.Lock()
_open = {"vraag": None}
_beurt = {"vraag": None, "antwoord": None, "tijd": 0.0}


def _norm(tekst):
    return " ".join(str(tekst or "").strip().rstrip(" ?!.").split())


def zet(vraag, sjabloon=None, verwerk=None, controle=NAAM, ttl=TTL, inhoud=False):
    """Zet een wedervraag klaar en geeft ``vraag`` terug (handig als return).

    Precies één van ``sjabloon`` (met ``{antwoord}``) of ``verwerk``.
    ``inhoud=True``: het antwoord is iets om te noteren (agenda, deadline);
    een "zet"/"noteer" ervoor valt dan weg ("zet uit eten" -> "uit eten"),
    behalve als het duidelijk een bedienopdracht is ("zet de lamp aan").
    """

    if (sjabloon is None) == (verwerk is None):
        raise ValueError("geef sjabloon óf verwerk")
    with _lock:
        _open["vraag"] = {
            "vraag": vraag,
            "sjabloon": sjabloon,
            "verwerk": verwerk,
            "controle": controle,
            "inhoud": inhoud,
            "tot": time.monotonic() + ttl,
        }
    return vraag


def wis():
    with _lock:
        _open["vraag"] = None


def open_vraag():
    """De openstaande wedervraag (of None), zonder hem weg te nemen."""

    with _lock:
        open_ = _open["vraag"]
        if open_ and time.monotonic() > open_["tot"]:
            _open["vraag"] = open_ = None
        return open_


def _neem():
    with _lock:
        open_ = _open["vraag"]
        _open["vraag"] = None
    if open_ and time.monotonic() > open_["tot"]:
        return None
    return open_


def past(antwoord, controle):
    """True als ``antwoord`` bij een wedervraag van deze soort past."""

    tekst = _norm(antwoord).lower()
    if not tekst:
        return False
    woorden = tekst.split()
    if controle == TEKST:
        return True
    if controle == MOMENT:
        from core import agenda_tijd

        moment = agenda_tijd.lees_moment(tekst)
        if moment.leeg():
            return False
        return len(moment.rest(tekst).split()) <= MAX_MOMENT_REST
    if controle == JA:
        from core.confirmation import is_loose_yes

        return is_loose_yes(tekst) or bool(_JA_EXTRA.match(tekst))
    if controle == ZIN:
        return len(woorden) <= MAX_ZIN_WOORDEN and woorden[0] not in _COMMANDO_START
    # NAAM: kort en geen nieuw commando of vraag.
    return len(woorden) <= MAX_NAAM_WOORDEN and woorden[0] not in _COMMANDO_START


_NOTITIE_WERKWOORD = re.compile(
    r"^(?:zet|noteer|plan|schrijf)\s+(?:er\s+)?(?:maar\s+)?(?:een\s+)?(?:afspraak\s+|deadline\s*:?\s*)?",
    re.IGNORECASE,
)
_BEDIENING = re.compile(r"\b(?:aan|uit|af|dicht|open|harder|zachter|hoger|lager)$|%$", re.IGNORECASE)


def _zonder_notitie_werkwoord(tekst):
    """"zet uit eten" -> "uit eten"; "zet de lamp aan" blijft zoals hij is."""

    rest = _NOTITIE_WERKWOORD.sub("", tekst, count=1).strip()
    if not rest or rest == tekst or _BEDIENING.search(rest):
        return tekst
    return rest


def beantwoord(antwoord, verwerk_commando):
    """Probeert ``antwoord`` als antwoord op de open wedervraag.

    ``verwerk_commando(tekst)`` voert een aangevuld commando uit (de normale
    keten). Geeft het antwoord terug, of None als er geen wedervraag was of
    het antwoord er niet bij past (dan gaat de zin gewoon verder).
    """

    open_ = _neem()
    if open_ is None:
        return None
    tekst = _norm(antwoord)
    if _ANNULEER.match(tekst.lower()):
        return ANNULEER_ANTWOORD
    if open_.get("inhoud"):
        tekst = _zonder_notitie_werkwoord(tekst)
    if not past(tekst, open_["controle"]):
        return None
    if open_["verwerk"] is not None:
        return open_["verwerk"](tekst)
    commando = open_["sjabloon"].replace("{antwoord}", tekst)
    return verwerk_commando(" ".join(commando.split()))


# -----------------------------------------------------------------
# De vorige beurt
# -----------------------------------------------------------------

def onthoud_beurt(vraag, antwoord):
    """Na elk commando: de vraag en het antwoord (alleen tekst)."""

    if not isinstance(antwoord, str) or not str(vraag or "").strip():
        return
    with _lock:
        _beurt.update(vraag=str(vraag).strip(), antwoord=antwoord.strip(), tijd=time.monotonic())


def vorige_beurt(binnen=BEURT_TTL):
    """``(vraag, antwoord)`` van de vorige beurt als die recent is, anders None."""

    with _lock:
        if not _beurt["vraag"] or time.monotonic() - _beurt["tijd"] > binnen:
            return None
        return _beurt["vraag"], _beurt["antwoord"]


def mag_naar_cloud(beurt):
    """True als deze vorige beurt mee mag naar Gemini (niets persoonlijks)."""

    if not beurt:
        return False
    from core import privacy_poort

    vraag, antwoord = beurt
    if not privacy_poort.beslis(vraag).cloud or not privacy_poort.beslis(antwoord).cloud:
        return False
    veilig, _ = privacy_poort.controleer([
        {"role": "user", "content": vraag},
        {"role": "assistant", "content": antwoord},
    ])
    return veilig


def _reset():
    """Voor tests."""

    with _lock:
        _open["vraag"] = None
        _beurt.update(vraag=None, antwoord=None, tijd=0.0)
