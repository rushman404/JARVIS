"""Commando-correctie (Fase 24, M1): de lokale fuzzy-match.

Een verkeerd gezegd of getypt commando ("zet de lampe in de wonkamer an")
herkent geen enkele herkenner in het brein, dus belandt het als chatvraag
bij de AI. Deze module zoekt wat u waarschijnlijk bedoelde, snel en gratis:

1. Alleen als de zin op een commando lijkt (begint met zet, doe, open,
   speel, ... of eindigt op aan/uit). Gewone vragen krijgen nooit een
   "bedoelde u".
2. Opvulwoorden weg ("doe die tv toch uit" → "doe tv uit") en korte
   spraakvormen herstellen ("an" → "aan").
3. Elk onbekend woord vergelijken met de woordenlijst: woorden uit de
   voorbeeldcommando's plus bekende namen (programma's, apparaten, games,
   sites) via ``rapidfuzz``.
4. De verbeterde zin vergelijken met de voorbeeldcommando's per herkenner
   (``config/commando_voorbeelden.json``) voor een zekerheidsscore.

Deze module beslist niets en voert niets uit: hij geeft alleen kandidaten
met een score terug. Vragen ("Bedoelde u…?") en de drempels komen in M2/M4.
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VOORBEELDEN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "commando_voorbeelden.json",
)

# Bekende namen (HA, startmenu) worden zo lang hergebruikt: ophalen kost
# netwerk- en schijfwerk, en een commando moet snel blijven.
NAMEN_TTL_SECONDEN = 300

# Minimale gelijkenis (0-100) om een woord te vervangen. Korte woorden
# (≤ 3 letters) worden nooit vaag vervangen, alleen via de korte vormen:
# anders wordt "sem" al snel "steam".
DREMPEL_KORT = 75   # 4 letters ("stem" → "steam", "opne" → "open")
DREMPEL_LANG = 80   # 5+ letters ("lampe" → "lampen")

# Twee woordkeuzes die zo dicht bij elkaar liggen gelden als twijfel: dan
# komen er meerdere kandidaten ("Bedoelde u 1 … of 2 …?").
TWIJFEL_MARGE = 3

# Beleefde voorloop: hoort niet bij het commando zelf.
_BELEEFD = re.compile(
    r"^(?:jarvis\s+)?(?:(?:kun|kan|wil|zou)\s+(?:je|jij|u)\s+|kunt\s+u\s+|"
    r"wilt\s+u\s+|zoudt\s+u\s+)?(?:alsjeblieft\s+|alstublieft\s+)?"
)
_BELEEFDE_WOORDEN = frozenset([
    "jarvis", "kun", "kan", "kunt", "wil", "wilt", "zou", "zoudt",
    "jij", "alsjeblieft", "alstublieft", "aub",
])

# Een zin die hiermee begint is een vraag, geen commando.
_VRAAGWOORDEN = frozenset([
    "wat", "waarom", "hoe", "wie", "wanneer", "welke", "welk", "waar",
    "hoeveel", "is", "zijn", "ben", "heb", "heeft", "hebben", "weet",
    "ken", "vind", "mag", "moet", "kan", "kun", "kunt", "wil",
])

# Woorden aan het eind die een bedienopdracht maken ("tv uit").
_EIND_ACTIE = frozenset(["aan", "uit", "af", "dicht"])

# Na een beleefde voorloop staat het werkwoord achteraan ("kun je de
# lamp aan doen").
_EIND_WERKWOORDEN = frozenset([
    "doen", "zetten", "openen", "starten", "sluiten", "spelen", "pauzeren",
    "aandoen", "uitdoen", "aanzetten", "uitzetten", "dimmen", "dempen",
    "afsluiten", "vergrendelen", "herstarten",
])

_NAAM = "{naam}"


@dataclass
class Kandidaat:
    """Eén mogelijk bedoeld commando."""

    commando: str
    score: int                      # 0-100, hoger = zekerder
    herkenner: str                  # groep uit de voorbeelden, bv. "slim_huis"
    wijzigingen: list = field(default_factory=list)  # [(oud, nieuw), ...]
    bron: str = "lokaal"            # "lokaal" (M1) of "ai" (M3)


# ---------------------------------------------------------------------
# Voorbeelden en namen laden
# ---------------------------------------------------------------------

_LOCK = threading.Lock()
_voorbeelden = None
_namen = None
_namen_tijd = 0.0


def _norm(tekst):
    """Kleine letters, leestekens weg (behalve %), enkele spaties."""

    t = str(tekst or "").lower().replace("_", " ").replace("-", " ")
    t = re.sub(r"[^\w%\s]", " ", t)
    return " ".join(t.split())


def laad_voorbeelden(vernieuw=False):
    """De inhoud van ``config/commando_voorbeelden.json`` (gecachet)."""

    global _voorbeelden

    with _LOCK:
        if _voorbeelden is not None and not vernieuw:
            return _voorbeelden
        try:
            with open(VOORBEELDEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("Commando-voorbeelden niet te lezen: %s", VOORBEELDEN_FILE)
            data = {}
        if not isinstance(data, dict):
            data = {}
        _voorbeelden = data
        return data


def _startmenu_namen():
    """Namen van snelkoppelingen in het startmenu (zonder de-installeerders)."""

    mappen = (
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
    )
    namen = set()
    for map_ in mappen:
        if not os.path.isdir(map_):
            continue
        for _root, _dirs, bestanden in os.walk(map_):
            for bestand in bestanden:
                if not bestand.lower().endswith(".lnk"):
                    continue
                naam = _norm(os.path.splitext(bestand)[0])
                if re.search(r"\b(uninstall|verwijder|readme|help|documentation)\b", naam):
                    continue
                namen.add(naam)
    return namen


def _ha_namen():
    """Apparaat-, kamer- en aliasnamen uit Home Assistant (als gekoppeld)."""

    from core import ha_registry
    from core.home_assistant import HA_DEVICE_WORDS

    namen = {_norm(w) for w in HA_DEVICE_WORDS}

    for aliassen in ha_registry._load_aliases().values():
        if isinstance(aliassen, list):
            namen.update(_norm(a) for a in aliassen)

    if ha_registry._config_ok():
        snapshot = ha_registry.get_snapshot() or {}
        for entity in snapshot.get("entities") or []:
            for sleutel in ("name", "device", "area"):
                namen.add(_norm(entity.get(sleutel)))
            namen.update(_norm(a) for a in entity.get("aliases") or [])
        namen.update(_norm(a) for a in (snapshot.get("areas") or {}).values())

    return namen


def bekende_namen(vernieuw=False):
    """Alle bekende namen (programma's, apparaten, games, sites), genormaliseerd.

    Elke bron mag mislukken zonder de rest te raken. Gecachet voor
    ``NAMEN_TTL_SECONDEN``.
    """

    global _namen, _namen_tijd

    with _LOCK:
        if (not vernieuw and _namen is not None
                and time.monotonic() - _namen_tijd < NAMEN_TTL_SECONDEN):
            return _namen

    namen = {_norm(n) for n in laad_voorbeelden().get("namen") or []}
    for bron in (_ha_namen, _startmenu_namen):
        try:
            namen.update(bron())
        except Exception:
            logger.debug("Namenbron %s mislukt", bron.__name__, exc_info=True)

    namen = frozenset(n for n in namen if len(n) >= 2)

    with _LOCK:
        _namen = namen
        _namen_tijd = time.monotonic()
    return namen


# ---------------------------------------------------------------------
# Herkennen en opschonen
# ---------------------------------------------------------------------

def _splits_beleefd(tekst):
    """(beleefde voorloop, rest) — "kun je zet ..." → ("kun je ", "zet ...")."""

    match = _BELEEFD.match(tekst)
    voorloop = match.group(0) if match else ""
    return voorloop, tekst[len(voorloop):]


def _gelijkenis(a, b, **_kwargs):
    from rapidfuzz import fuzz
    from rapidfuzz.distance import DamerauLevenshtein

    # Damerau telt een omgedraaide letter ("opne") als één fout.
    return max(fuzz.ratio(a, b), 100 * DamerauLevenshtein.normalized_similarity(a, b))


def lijkt_op_commando(tekst):
    """True als de zin een opdracht lijkt, geen vraag of praatje."""

    t = _norm(tekst)
    if not t:
        return False
    voorloop, rest = _splits_beleefd(t)
    woorden = rest.split()
    if not woorden:
        return False

    # Een vraagteken of vraagwoord vooraan is een vraag, tenzij hij
    # beleefd begon ("kun je de lamp aandoen?").
    if str(tekst).strip().endswith("?") and not voorloop:
        return False
    if woorden[0] in _VRAAGWOORDEN:
        return False

    data = laad_voorbeelden()
    werkwoorden = set(data.get("werkwoorden") or [])
    eerste = woorden[0]
    if eerste in werkwoorden:
        return True
    if len(eerste) >= 4 and any(_gelijkenis(eerste, w) >= DREMPEL_KORT for w in werkwoorden if len(w) >= 3):
        return True

    # "tv uit", "lampen woonkamer an": kort en eindigt op een actie.
    korte_vormen = data.get("korte_vormen") or {}
    laatste = korte_vormen.get(woorden[-1], woorden[-1])
    if voorloop and laatste in _EIND_WERKWOORDEN:
        return True
    return len(woorden) <= 6 and laatste in _EIND_ACTIE


def verwijder_opvulwoorden(tekst):
    """Haalt opvulwoorden weg; laat de zin nooit leeg achter."""

    t = _norm(tekst)
    opvul = set(laad_voorbeelden().get("opvulwoorden") or [])
    over = [w for w in t.split() if w not in opvul]
    return " ".join(over) if over else t


# ---------------------------------------------------------------------
# Kandidaten zoeken
# ---------------------------------------------------------------------

def _woordenlijst(data, namen):
    woorden = set(data.get("basiswoorden") or [])
    woorden.update(data.get("werkwoorden") or [])
    woorden.update(data.get("opvulwoorden") or [])
    woorden.update((data.get("korte_vormen") or {}).values())
    woorden.update(_BELEEFDE_WOORDEN)
    woorden.update(_EIND_WERKWOORDEN)
    for lijst in (data.get("herkenners") or {}).values():
        for voorbeeld in lijst:
            woorden.update(w for w in _norm(voorbeeld.replace(_NAAM, " ")).split())
    for naam in namen:
        woorden.update(naam.split())
    return frozenset(w for w in woorden if w)


def _zelfde_stam(a, b):
    """"lamp", "lampen" en "lampje" zijn geen echte twijfel."""

    return len(os.path.commonprefix([a, b])) >= 4 or a.startswith(b) or b.startswith(a)


# Direct na deze werkwoorden staat een programma, game of site: daar gaat
# een naam als "spotify" voor een apparaatwoord als "spot" ("open spotie").
_PROGRAMMA_WERKWOORDEN = frozenset(["open", "start", "sluit", "speel", "stop", "herstart", "bezoek"])
DREMPEL_PROGRAMMA = 75


def _apparaatwoorden():
    """De algemene slim-huis-woorden (lamp, spot, tv, ...), genormaliseerd."""

    try:
        from core.home_assistant import HA_DEVICE_WORDS
    except Exception:
        return frozenset()
    return frozenset(w for woord in HA_DEVICE_WORDS for w in _norm(woord).split())


def _verbeter_programmanaam(woord, woordenlijst, apparaatwoorden):
    """Als ``_verbeter_woord``, maar zonder apparaatwoorden en iets ruimer:
    "spotie" lijkt meer op "spot" (80) dan op "spotify" (77)."""

    if woord in woordenlijst:
        return []
    keuzes = [w for w in woordenlijst if w not in apparaatwoorden]
    return _verbeter_woord(woord, keuzes, drempel=DREMPEL_PROGRAMMA)


def _verbeter_woord(woord, woordenlijst, drempel=None):
    """Lijst [(nieuw woord, score)]: leeg = laten staan; >1 = twijfel."""

    if len(woord) <= 3 or woord.isdigit() or woord in woordenlijst:
        return []
    from rapidfuzz import process

    if drempel is None:
        drempel = DREMPEL_KORT if len(woord) == 4 else DREMPEL_LANG
    treffers = process.extract(woord, woordenlijst, scorer=_gelijkenis, limit=5)
    treffers = [(w, s) for w, s, _ in treffers if s >= drempel]
    if not treffers:
        return []

    beste, beste_score = treffers[0]
    keuzes = [(beste, beste_score)]
    for w, s in treffers[1:]:
        if beste_score - s <= TWIJFEL_MARGE and not any(_zelfde_stam(w, k) for k, _ in keuzes):
            keuzes.append((w, s))
    return keuzes


def _skelet(tekst, namen_op_lengte):
    """Vervangt bekende namen door {naam} (langste eerst)."""

    resultaat = f" {tekst} "
    for naam in namen_op_lengte:
        resultaat = resultaat.replace(f" {naam} ", f" {_NAAM} ")
    return " ".join(resultaat.split())


def _structuur(zin, data, namen_op_lengte):
    """(beste herkenner, score 0-100) van de zin tegen de voorbeelden."""

    from rapidfuzz import fuzz

    _voorloop, rest = _splits_beleefd(zin)
    skelet = _skelet(rest, namen_op_lengte)
    beste = ("", 0.0)
    for herkenner, lijst in (data.get("herkenners") or {}).items():
        for voorbeeld in lijst:
            doel = _skelet(_norm(voorbeeld.replace(_NAAM, " naamplek ")), namen_op_lengte)
            doel = doel.replace("naamplek", _NAAM)
            score = fuzz.token_sort_ratio(skelet, doel)
            if score > beste[1]:
                beste = (herkenner, score)
    return beste


def zoek_kandidaten(tekst, namen=None, max_kandidaten=3):
    """Mogelijk bedoelde commando's voor ``tekst``, beste eerst.

    Leeg als de zin geen commando lijkt of er niets te verbeteren valt.
    ``namen`` kan worden meegegeven (tests); anders ``bekende_namen()``.
    """

    if not lijkt_op_commando(tekst):
        return []

    data = laad_voorbeelden()
    namen = frozenset(_norm(n) for n in namen) if namen is not None else bekende_namen()
    woordenlijst = _woordenlijst(data, namen)
    korte_vormen = data.get("korte_vormen") or {}

    origineel = _norm(tekst)
    voorloop, rest = _splits_beleefd(origineel)
    schoon = verwijder_opvulwoorden(rest)

    # Per woord: vaste korte vorm, vage verbetering of laten staan. Bij
    # twijfel tussen twee woorden ontstaan meerdere varianten.
    varianten = [([], [], 100.0)]  # (woorden, wijzigingen, laagste score)
    werkwoorden = frozenset(data.get("werkwoorden") or [])
    apparaatwoorden = _apparaatwoorden()
    vorige = None
    for positie, woord in enumerate(schoon.split()):
        if woord in korte_vormen:
            keuzes = [(korte_vormen[woord], 100.0)]
        elif positie == 0 and woord not in woordenlijst:
            # Vooraan staat de gebiedende wijs: "opne" → "open", niet "openen".
            keuzes = (_verbeter_woord(woord, werkwoorden)
                      or _verbeter_woord(woord, woordenlijst) or [(woord, 100.0)])
        elif vorige in _PROGRAMMA_WERKWOORDEN:
            keuzes = (_verbeter_programmanaam(woord, woordenlijst, apparaatwoorden)
                      or _verbeter_woord(woord, woordenlijst) or [(woord, 100.0)])
        else:
            keuzes = _verbeter_woord(woord, woordenlijst) or [(woord, 100.0)]
        vorige = keuzes[0][0]
        nieuw = []
        for woorden, wijzigingen, laagste in varianten:
            for keuze, score in keuzes:
                extra = [(woord, keuze)] if keuze != woord else []
                nieuw.append((woorden + [keuze], wijzigingen + extra, min(laagste, score)))
        varianten = nieuw[:max_kandidaten]

    namen_op_lengte = sorted(namen, key=len, reverse=True)
    kandidaten = []
    gezien = set()
    for woorden, wijzigingen, laagste in varianten:
        zin = (voorloop + " ".join(woorden)).strip()
        if zin == origineel or zin in gezien:
            continue
        gezien.add(zin)
        herkenner, structuur = _structuur(zin, data, namen_op_lengte)
        score = int(round(min(laagste, structuur)))
        kandidaten.append(Kandidaat(zin, score, herkenner, wijzigingen))

    kandidaten.sort(key=lambda k: -k.score)
    return kandidaten[:max_kandidaten]


# ---------------------------------------------------------------------
# "Bedoelde u…?" (M2)
# ---------------------------------------------------------------------

# Onder deze score is de gok te wild: dan blijft het een gewone chatvraag.
DREMPEL_VRAGEN = 70

_RANGTELWOORDEN = ("eerste", "tweede", "derde")

# Een verbeterd commando wordt opnieuw door de keten gestuurd. Tijdens dat
# herhalen mag er geen nieuwe "bedoelde u" komen, anders kan het rondjes
# draaien. Per thread: stem en dashboard lopen elk in hun eigen thread.
_herhaling = threading.local()


class herhaling:
    """Context: het verbeterde commando wordt nu uitgevoerd."""

    def __enter__(self):
        _herhaling.actief = getattr(_herhaling, "actief", 0) + 1
        return self

    def __exit__(self, *_fout):
        _herhaling.actief -= 1
        return False


def is_herhaling():
    return getattr(_herhaling, "actief", 0) > 0


def te_vragen(tekst, alleen_echte_fouten=False, namen=None, met_ai=False):
    """De kandidaten die goed genoeg zijn om na te vragen (kan leeg zijn).

    Met ``alleen_echte_fouten`` telt een zin waar alleen opvulwoorden uit
    gingen niet mee: in de slim-huis-route begrijpt de AI "zet die lamp
    even op rood" prima zonder vraag. Met ``met_ai`` probeert het
    AI-vangnet (M3) het nog als de lokale match niets vond.
    """

    if is_herhaling():
        return []
    # Eerder met "ja" bevestigd (M5): dan weet JARVIS het al.
    geleerd = geleerd_commando(tekst)
    if geleerd is not None:
        return [geleerd]
    kandidaten = [k for k in zoek_kandidaten(tekst, namen=namen) if k.score >= DREMPEL_VRAGEN]
    if alleen_echte_fouten:
        kandidaten = [k for k in kandidaten if k.wijzigingen]
    if not kandidaten and met_ai:
        kandidaat = ai_kandidaat(tekst, namen=namen)
        if kandidaat is not None and kandidaat.score >= DREMPEL_VRAGEN:
            kandidaten = [kandidaat]
    return kandidaten


# ---------------------------------------------------------------------
# AI-vangnet (M3)
# ---------------------------------------------------------------------

# Een klein model raakt de weg kwijt in een lange lijst: alleen de namen die
# het meest op de zin lijken gaan mee.
AI_MAX_NAMEN = 40

# Het AI-antwoord moet echt op een voorbeeldcommando lijken; anders heeft
# het model iets verzonnen.
AI_MIN_STRUCTUUR = 85

AI_SYSTEEM = (
    "Je bent de commando-herkenner van JARVIS, een Nederlandse assistent. "
    "De gebruiker gaf een opdracht die niet letterlijk herkend werd. Kies uit "
    "de voorbeeldcommando's het commando dat hij bedoelde en schrijf het "
    "volledig uit. Vul {naam} alleen in met een naam uit de namenlijst. Verzin "
    "geen nieuwe commando's of namen. Past er geen enkel commando, antwoord "
    "dan met commando \"geen\". Antwoord alleen met JSON: "
    "{\"commando\": \"...\", \"zekerheid\": 0-100}."
)


def _ai_berichten(tekst, data, namen):
    from rapidfuzz import fuzz, process

    voorbeelden = []
    for lijst in (data.get("herkenners") or {}).values():
        for voorbeeld in lijst:
            if voorbeeld not in voorbeelden:
                voorbeelden.append(voorbeeld)
    dichtbij = [n for n, _s, _i in process.extract(
        tekst, sorted(namen), scorer=fuzz.partial_ratio, limit=AI_MAX_NAMEN)]
    inhoud = (
        "Voorbeeldcommando's:\n- " + "\n- ".join(voorbeelden)
        + "\n\nNamen: " + ", ".join(sorted(dichtbij))
        + f"\n\nOpdracht van de gebruiker: \"{tekst}\""
    )
    return [
        {"role": "system", "content": AI_SYSTEEM},
        {"role": "user", "content": inhoud},
    ]


# Mag de zin van deze aanroep naar Gemini (Fase 25)? Gezet door ai_kandidaat
# na de privacy-poort; per thread, want stem en dashboard lopen apart.
_cloud = threading.local()


def _standaard_llm(berichten):
    from core import llm

    if getattr(_cloud, "mag", False):
        antwoord = llm.chat(messages=berichten, json_mode=True, cloud=True)
    else:
        antwoord = llm.chat(messages=berichten, json_mode=True)
    return str(getattr(antwoord.message, "content", "") or "")


def _met_tijdslimiet(fn, timeout):
    """``fn()`` met een tijdslimiet; None bij een fout of te laat."""

    uitkomst = []

    def _draai():
        try:
            uitkomst.append(fn())
        except Exception:
            logger.debug("AI-vangnet: aanroep mislukt", exc_info=True)

    thread = threading.Thread(target=_draai, name="jarvis-correctie-ai", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.info("AI-vangnet: geen antwoord binnen %.1fs", timeout)
        return None
    return uitkomst[0] if uitkomst else None


def _lees_ai_antwoord(inhoud):
    """(commando, zekerheid) uit het JSON-antwoord, of None."""

    try:
        data = json.loads(inhoud)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    commando = data.get("commando")
    zekerheid = data.get("zekerheid")
    if not isinstance(commando, str) or isinstance(zekerheid, bool):
        return None
    try:
        zekerheid = float(zekerheid)
    except (TypeError, ValueError):
        return None
    commando = _norm(commando)
    # Een niet-ingevulde {naam} wordt na normaliseren het woord "naam".
    if not commando or commando == "geen" or "naam" in commando.split():
        return None
    return commando, max(0.0, min(100.0, zekerheid))


def ai_kandidaat(tekst, namen=None, llm_fn=None, timeout=None):
    """Laat het taalmodel het bedoelde commando kiezen; Kandidaat of None.

    Alleen bij een zin die op een commando lijkt. Het antwoord telt alleen
    als het op een voorbeeldcommando lijkt en uitsluitend bekende woorden en
    namen bevat: een verzonnen commando valt zo altijd af.

    Privacy (Fase 25): het verzoek bevat alleen de zin, de voorbeeldcommando's
    en bekende namen van programma's en apparaten, geen persoonlijke data.
    """

    from config import COMMANDO_CORRECTIE_AI, COMMANDO_CORRECTIE_AI_TIMEOUT

    if not COMMANDO_CORRECTIE_AI or is_herhaling() or not lijkt_op_commando(tekst):
        return None

    data = laad_voorbeelden()
    namen = frozenset(_norm(n) for n in namen) if namen is not None else bekende_namen()
    origineel = _norm(tekst)
    berichten = _ai_berichten(origineel, data, namen)
    llm_fn = llm_fn or _standaard_llm
    timeout = COMMANDO_CORRECTIE_AI_TIMEOUT if timeout is None else timeout

    # Fase 25: Gemini kiest als de zin niets persoonlijks bevat (de lijst
    # met voorbeelden en namen van programma's en apparaten mag mee).
    from core import privacy_poort

    mag = privacy_poort.naar_cloud(origineel)

    def _vraag():
        _cloud.mag = mag
        return llm_fn(berichten)

    gelezen = _lees_ai_antwoord(_met_tijdslimiet(_vraag, timeout))
    if gelezen is None:
        return None
    commando, zekerheid = gelezen

    _voorloop, rest = _splits_beleefd(origineel)
    if commando in (origineel, rest):
        return None
    woordenlijst = _woordenlijst(data, namen)
    if any(w not in woordenlijst and not w.isdigit() for w in commando.split()):
        logger.info("AI-vangnet: onbekend woord in %r, genegeerd", commando)
        return None
    herkenner, structuur = _structuur(commando, data, sorted(namen, key=len, reverse=True))
    if structuur < AI_MIN_STRUCTUUR:
        logger.info("AI-vangnet: %r lijkt niet op een voorbeeld (%d)", commando, structuur)
        return None

    score = int(round(min(zekerheid, structuur)))
    logger.info("AI-vangnet: %r → %r (%d)", origineel, commando, score)
    return Kandidaat(commando, score, herkenner, [(rest, commando)], bron="ai")


def maak_vraag(kandidaten):
    """ "Bedoelde u: zet de lampen aan?" of een genummerd lijstje."""

    if len(kandidaten) == 1:
        return f"Bedoelde u: {kandidaten[0].commando}?"
    delen = [f"{i}. {k.commando}" for i, k in enumerate(kandidaten, 1)]
    return "Bedoelde u " + ", of ".join(delen) + "? Zeg het nummer, of nee."


def stel_vraag(origineel, kandidaten):
    """Zet de "bedoelde u"-vraag klaar (ja/nee, ook op het dashboard)."""

    from core.confirmation import CORRECTIE_KIND, set_pending

    vraag = maak_vraag(kandidaten)
    set_pending(CORRECTIE_KIND, {
        "question": origineel,
        "action": "commando_correctie",
        "bedoelde_vraag": vraag,
        "kandidaten": [k.commando for k in kandidaten],
        "scores": [k.score for k in kandidaten],
        "wijzigingen": [k.wijzigingen for k in kandidaten],
    })
    logger.info("Bedoelde u: %r → %s", origineel, [k.commando for k in kandidaten])
    return vraag


# ---------------------------------------------------------------------
# Drempels en veiligheid (M4)
# ---------------------------------------------------------------------

# Bijna zeker + onschuldig → meteen doen. Bij meer dan één verbeterd woord
# vraagt JARVIS toch: "zet de lampe in de wonkamer an" is te veel gegok.
DREMPEL_DIRECT = 90
MAX_WIJZIGINGEN_DIRECT = 1

# Risico van een verbeterd commando.
VEILIG = "veilig"
GEVOELIG = "gevoelig"      # altijd eerst "Bedoelde u…?" (programma sluiten, ...)
GEVAARLIJK = "gevaarlijk"  # afsluiten, verwijderen, mail/DM, agenda

# Deze routes vragen zelf altijd een strikte ja (power_confirm,
# delete_confirm, mail_versturen, discord_versturen, agenda_*). Daardoor kan
# hun vraag de enige vraag zijn: "Bedoelde u …? Zal ik de pc afsluiten?"
_GEVAARLIJK = (
    re.compile(
        r"\b(?:afsluiten|herstart\w*|vergrendel\w*|slaapstand|sluimerstand|"
        r"afmelden|uitloggen|log uit|verwijder\w*|wis|prullenbak|leeg|"
        r"mail\w*|beantwoord|antwoord|stuur|verstuur|dm|dms|agenda|"
        r"verplaats|afspraak)\b"
    ),
    re.compile(r"\b(?:pc|computer|laptop|systeem)\b.*\b(?:uit|af)\b"),
)
_GEVOELIG = re.compile(r"\b(?:sluit|beëindig|beeindig|typ|type|installeer|update|vergeet|koop|bestel)\b")

# Uitkomsten van beslis().
DIRECT = "direct"
VRAGEN = "vragen"


def risico(commando):
    """VEILIG, GEVOELIG of GEVAARLIJK voor een (verbeterd) commando."""

    t = _norm(commando)
    if any(p.search(t) for p in _GEVAARLIJK):
        return GEVAARLIJK
    if _GEVOELIG.search(t):
        return GEVOELIG
    return VEILIG


def beslis(kandidaten):
    """DIRECT, VRAGEN of GEVAARLIJK (= één samengevoegde vraag).

    * één kandidaat, gevaarlijk → GEVAARLIJK: de route stelt zijn eigen
      strikte vraag, met "Bedoelde u …?" ervoor;
    * één kandidaat, onschuldig, score ≥ ``DREMPEL_DIRECT`` en hooguit
      ``MAX_WIJZIGINGEN_DIRECT`` verbeterd woord → DIRECT;
    * de rest (twijfel, meerdere kandidaten, gevoelig) → VRAGEN.
    """

    if len(kandidaten) != 1:
        return VRAGEN
    kandidaat = kandidaten[0]
    soort = risico(kandidaat.commando)
    if soort == GEVAARLIJK:
        return GEVAARLIJK
    # Een gok van het taalmodel (M3) is nooit "bijna zeker": qwen2.5:3b
    # noemt "open dat chat programma" → "open chrome" 100% zeker.
    if kandidaat.bron == "ai":
        return VRAGEN
    if (soort == VEILIG and kandidaat.score >= DREMPEL_DIRECT
            and len(kandidaat.wijzigingen) <= MAX_WIJZIGINGEN_DIRECT):
        return DIRECT
    return VRAGEN


def aanname(kandidaat):
    """ "Ik nam aan dat u 'open spotify' bedoelde. " — leeg als er alleen
    opvulwoorden uit gingen (dan valt er niets te melden)."""

    if not kandidaat.wijzigingen:
        return ""
    return f"Ik nam aan dat u '{kandidaat.commando}' bedoelde. "


# Uitkomsten van beoordeel_antwoord().
KIES = "kies"
NEE = "nee"
ONDUIDELIJK = "onduidelijk"
NIEUW = "nieuw"


def beoordeel_antwoord(tekst, aantal):
    """(uitkomst, index) voor een antwoord op de "bedoelde u"-vraag.

    ``KIES`` met de index van de kandidaat, ``NEE``, ``ONDUIDELIJK`` (bijv.
    "ja" terwijl er meerdere kandidaten zijn) of ``NIEUW``: het antwoord
    is een nieuw commando en de vraag vervalt.
    """

    from core.confirmation import is_loose_no, is_loose_yes, is_strict_yes

    t = _norm(tekst)
    nummer = re.fullmatch(r"(?:nummer\s+)?(\d{1,2})", t)
    if nummer:
        index = int(nummer.group(1)) - 1
        return (KIES, index) if 0 <= index < aantal else (ONDUIDELIJK, None)
    for index, woord in enumerate(_RANGTELWOORDEN):
        if re.fullmatch(rf"(?:de\s+)?{woord}", t):
            return (KIES, index) if index < aantal else (ONDUIDELIJK, None)
    if is_loose_no(t) or t.startswith("geen van"):
        return NEE, None
    if is_strict_yes(t) or is_loose_yes(t):
        return (KIES, 0) if aantal == 1 else (ONDUIDELIJK, None)
    return NIEUW, None


# ---------------------------------------------------------------------
# Leren en logboek (M5)
# ---------------------------------------------------------------------

# Persoonlijke data (wat u zei): staat buiten git, zie .gitignore.
LEER_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memory", "commando_correcties.json",
)

# Het logboek blijft klein: de oudste missers vallen eraf.
MAX_MISSERS = 300

# Uitkomsten in het logboek.
UIT_DIRECT = "direct"        # meteen verbeterd en uitgevoerd
UIT_GELEERD = "geleerd"      # direct, omdat het eerder bevestigd was
UIT_GEVRAAGD = "gevraagd"    # "Bedoelde u…?" gesteld
UIT_JA = "ja"
UIT_NEE = "nee"
UIT_ONBEKEND = "onbekend"    # lijkt een commando, maar niets gevonden

_LEER_LOCK = threading.Lock()


def _sleutel(tekst):
    """Wat u zei, zonder beleefde voorloop en opvulwoorden."""

    _voorloop, rest = _splits_beleefd(_norm(tekst))
    return verwijder_opvulwoorden(rest)


def _lees():
    try:
        with open(LEER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for deel in ("geleerd", "missers"):
        if not isinstance(data.get(deel), dict):
            data[deel] = {}
    return data


def _schrijf(data):
    os.makedirs(os.path.dirname(LEER_FILE), exist_ok=True)
    tijdelijk = LEER_FILE + ".tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tijdelijk, LEER_FILE)


def _nu():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def geleerd_commando(tekst):
    """De eerder bevestigde verbetering voor deze zin, als Kandidaat."""

    sleutel = _sleutel(tekst)
    if not sleutel:
        return None
    with _LEER_LOCK:
        regel = _lees()["geleerd"].get(sleutel)
    if not isinstance(regel, dict) or not isinstance(regel.get("commando"), str):
        return None
    commando = regel["commando"]
    return Kandidaat(commando, 100, "geleerd", [(sleutel, commando)], bron="geleerd")


def leer(origineel, commando):
    """Na een "ja": deze fout betekent voortaan dit commando."""

    sleutel = _sleutel(origineel)
    commando = _norm(commando)
    if not sleutel or not commando or sleutel == commando:
        return
    with _LEER_LOCK:
        data = _lees()
        vorige = data["geleerd"].get(sleutel) or {}
        keer = vorige.get("keer", 0) if vorige.get("commando") == commando else 0
        data["geleerd"][sleutel] = {"commando": commando, "keer": keer + 1, "laatst": _nu()}
        _schrijf(data)
    logger.info("Commando-correctie geleerd: %r → %r", sleutel, commando)


def noteer(origineel, uitkomst, commando=None):
    """Houdt bij welke zinnen niet meteen herkend werden (logboek)."""

    sleutel = _sleutel(origineel)
    if not sleutel:
        return
    with _LEER_LOCK:
        data = _lees()
        missers = data["missers"]
        regel = missers.get(sleutel)
        if not isinstance(regel, dict):
            regel = {"keer": 0, "uitkomsten": {}}
        if uitkomst != UIT_JA and uitkomst != UIT_NEE:
            # Een ja of nee hoort bij dezelfde misser als de vraag ervoor.
            regel["keer"] = int(regel.get("keer", 0)) + 1
        uitkomsten = regel.setdefault("uitkomsten", {})
        uitkomsten[uitkomst] = int(uitkomsten.get(uitkomst, 0)) + 1
        if commando and uitkomst != UIT_NEE:
            regel["bedoeld"] = _norm(commando)
        regel["laatst"] = _nu()
        missers[sleutel] = regel
        if len(missers) > MAX_MISSERS:
            oudste = sorted(missers, key=lambda s: str(missers[s].get("laatst", "")))
            for s in oudste[:len(missers) - MAX_MISSERS]:
                del missers[s]
        _schrijf(data)


def vaak_fout(aantal=5):
    """[(zin, regel), ...] van de missers die het vaakst voorkwamen."""

    with _LEER_LOCK:
        missers = _lees()["missers"]
    rijen = [(s, r) for s, r in missers.items() if isinstance(r, dict) and r.get("keer")]
    rijen.sort(key=lambda sr: (-int(sr[1].get("keer", 0)), sr[0]))
    return rijen[:aantal]


def beschrijf_vaak_fout(aantal=5):
    """Antwoord op "welke commando's gaan vaak fout?"."""

    rijen = vaak_fout(aantal)
    if not rijen:
        return "Er gaan nog geen commando's fout, sir."
    delen = []
    for zin, regel in rijen:
        keer = int(regel.get("keer", 0))
        deel = f"'{zin}' ({keer} keer"
        if regel.get("bedoeld"):
            deel += f", bedoeld: {regel['bedoeld']}"
        delen.append(deel + ")")
    return "Deze commando's gaan het vaakst fout: " + "; ".join(delen) + "."


def vergeet_geleerd():
    """Wist alle geleerde verbeteringen; geeft het aantal terug."""

    with _LEER_LOCK:
        data = _lees()
        aantal = len(data["geleerd"])
        data["geleerd"] = {}
        _schrijf(data)
    return aantal
