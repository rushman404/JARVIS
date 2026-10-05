import json
import math
import os
import re
import time

from datetime import datetime
from functools import lru_cache

from memory import store


MEMORY_FILE = os.path.join(
    os.path.dirname(__file__),
    "memory.json"
)

# =============================================================
# USAGE TRACKING (Fase 14, Stap 2)
#
# _touched_keys houdt bij welke sleutels binnen het huidige
# commando al geteld zijn. Zo worden dubbele aanroepen van
# bijv. get_context_answer() niet dubbel geteld. De set wordt
# aan het begin van elk process_command() ge-reset.
# =============================================================

_touched_keys = set()


def reset_touch_usage():
    """Wis de dedup-set — aanroepen aan het begin van elk commando."""

    _touched_keys.clear()



DEFAULT_CATEGORIES = [
    "voorkeuren",
    "pc",
    "projecten",
    "muziek",
    "algemeen",
    "apparaten",
]

# =============================================================
# CATEGORIE- EN SLEUTELBELEID (Stabilisatie vóór Stap 7)
#
# Categorieën
# -----------
# Memory 2.0 ondersteunt uitsluitend DEFAULT_CATEGORIES. Een expliciete
# categorie die daar niet in staat, wordt naar "algemeen" gebracht in
# plaats van ergens half-leesbaar op te slagen: recall(), get_entry(),
# get_all_memory(), get_relevant_memory() en memory_summary() itereren
# allemaal uitsluitend over DEFAULT_CATEGORIES, dus een entry in een
# onbekende categorie zou onzichtbaar zijn terwijl hij wél bestaat.
# Het beleid staat op precies één plek (_canonical_category) zodat elk
# opslagpad (remember, resolve_conflict, de vault-import) hetzelfde
# gedrag krijgt.
#
# Sleutels
# --------
# Op het opslagniveau is een memory-sleutel een IDENTITEIT: exact, of
# genormaliseerd op hoofdletters en spaties/underscores/koppeltekens.
# Substring-matching hoort daar NIET bij. "fav band" en "fav band2"
# zijn twee verschillende feiten, en "vergeet band" mag "fav band"
# niet weggooien.
# =============================================================


def _canonical_category(category):
    """
    Het categoriebeleid op één plek.

    Zonder categorie -> None (laat get_category() de detectie doen).
    Een standaardcategorie (hoofdletterongevoelig) -> zichzelf.
    Alles anders -> "algemeen".

    Bewust NIET keyword-detectie: "sfeer" is een categorie die de
    gebruiker noemde, niet een woord dat ergens in valt.
    """

    if category is None:
        return None

    tekst = str(category).strip().lower()

    if not tekst:
        return None

    if tekst in DEFAULT_CATEGORIES:
        return tekst

    return "algemeen"


def _normalize_key(key):
    """
    Genormaliseerde vorm van een memory-sleutel voor identiteits-
    vergelijking.

    Hoofdletters zijn gelijk, en spatie, underscore en koppelteken zijn
    onderling verwisselbaar. Dat is BEWUST iets anders dan
    substring-matching: "fav band" en "fav band2" normaliseren naar
    twee verschillende strings en blijven dus verschillende sleutels.
    """

    if not isinstance(key, str):
        return ""

    tekst = re.sub(r"[\s_\-]+", " ", key.lower().strip())

    return tekst.strip()


def _values_equal(old, new):
    """
    Centrale waardevergelijking voor Memory 2.0.

    Twee waarden zijn gelijk als ze van hetzelfde type zijn en gelijk
    zijn. Dat is bewust strenger dan str(old) == str(new): een bool
    mag NOOIT gelijk zijn aan de tekst "ja", ook al is dat precies hoe
    Obsidian de waarde leesbaar maakt. De vault-import zet een waarde
    terug met het juiste type (value_type in de frontmatter), dus er
    hoeft geen tekstuele gelijkstelling te zijn.

    Uitzondering: int en float zijn hetzelfde getal als ze
    numeriek gelijk zijn (42 == 42.0). bool is uitdrukkelijk niet
    gelijk aan int, want True == 1 in Python maar niet in Memory 2.0.
    """

    if type(old) is type(new):
        return old == new

    if isinstance(old, bool) or isinstance(new, bool):
        return False

    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return old == new

    return False


CATEGORY_KEYWORDS = {
    "pc": [
        "gpu", "grafische kaart", "videokaart", "ram", "geheugen", "cpu",
        "processor", "moederbord", "ssd", "opslag", "scherm", "monitor",
        "toetsenbord", "muis", "pc", "computer", "laptop", "headset",
        "koeling", "voeding", "behuizing",
    ],
    "muziek": [
        "muziek", "nummer", "artiest", "band", "liedje", "lied", "genre",
        "playlist", "album", "song", "zanger", "favoriete band",
    ],
    "projecten": [
        "project", "school", "werk", "baan", "studie", "opdracht",
        "cursus", "stage", "vereniging",
    ],
    "voorkeuren": [
        "favoriet", "lievelings", "leuk", "lekker", "voorkeur", "graag",
        "houd van", "mijn game", "mijn kleur", "mijn sport", "mijn team",
        "mijn club",

        # Fase 5: licht/sfeer-voorkeuren ("warm wit licht", "gezellig")
        "licht", "verlichting", "lamp", "lampen", "kleur", "gezellig",
        "sfeer", "warm", "koel", "helder", "fel", "zacht", "temperatuur",
        "wit", "dimmen", "gedimd", "modus", "stand",
    ],
    "apparaten": [
        "apparaat", "apparaten", "lamp", "licht", "voordeur", "deurbel",
        "thermostaat", "gordijn", "stekker", "sensor", "camera",
        "schakelaar", "tv", "verwarming", "bedlamp", "gang",
        "kachel", "ventilator", "alarmsysteem", "rookmelder",
    ],
}

# =============================================================
# ENTRY-MODEL (Fase 5, aangevuld in Stap 7)
#
# Memory wordt opgeslagen als entry met metadata:
#   { "categorie": { "sleutel": {
#        "value": "warm wit",
#        "source": "conversation",
#        "created": "2026-10-03T19:00:00+02:00",
#        "updated": "2026-10-03T19:10:00+02:00",
#        "previous_value": None,
#        "corrected": False,
#        "conflict": False,
#        "usage_count": 0,
#        "last_used": None,
#        "priority": 1.0,
#        "related": ["gaming_pc", "monitor"],
#   } } }
#
# Oud (plat) formaat {categorie: {sleutel: waarde}} wordt bij het
# laden automatisch geconverteerd; alle functies blijven compatibel.
# =============================================================

# Het metadata-contract van één memory-entry (Stap 7).
#
# Vóór Stap 7 stond hier een dode verzameling sleutels die nergens
# werd gebruikt. Nu is het de ENNE definitie: _normalize_entry()
# vult ontbrekende velden in, _wrap() maakt een nieuwe entry
# conform, en is_entry_meta() wordt gebruikt om het onderscheid
# tussen een kale waarde en een entry te bepalen.
#
# `value` is het enige verplichte veld: het onderscheidt een entry
# van een kale waarde (_is_entry()). `category` staat NIET in de
# entry, maar in de map eromheen — zo blijft de bestaande
# categorie-architectuur ongemoeid.
#
# Per veld de veilige default bij ontbreken, en wie hem zet:
#
#   veld             default   gezet door
#   ---------------  --------  ------------------------------------
#   value            --        verplicht; _is_entry() herkent hieraan
#   source           "conversation"  remember()
#   created          None      _wrap() (nieuw) / blijft bij update
#   updated          None      remember() bij een waardewijziging
#                     (NIET touch_usage(): gebruik tellen is geen
#                     waardewijziging, dus updated blijft staan)
#   previous_value   None      remember() bij een waardewijziging
#   corrected        False     remember(explicit=True)
#   conflict         False     remember(), resolve_conflict()
#   usage_count      0         touch_usage()
#   last_used        None      touch_usage()
#   priority         1.0       remember(), resolve_conflict()
#   related          []        add_related(), remove_related()
#
# `created` en `related` staan bewust DEFAULT op None/[] en NIET op
# een verzonnen waarde: bij een oude memory zonder deze velden is
# er geen betrouwbare bron, dus we gokken geen datum. None betekent
# "onbekend", niet "nul".
ENTRY_META_KEYS = {
    "value", "source", "updated", "created",
    "previous_value", "corrected", "conflict",
    "usage_count", "last_used", "priority", "related",
}

# De velden die een memory over zijn waarde beschrijven. Alles
# buiten `value` en `related` is metadata die je programmatisch mag
# lezen en overschrijven zonder de waarde aan te raken.
ENTRY_META_DEFAULTS = {
    "source": "conversation",
    "created": None,
    "updated": None,
    "previous_value": None,
    "corrected": False,
    "conflict": False,
    "usage_count": 0,
    "last_used": None,
    "priority": 1.0,
    "related": [],
}


def _now():
    """
    Huidig tijdstip als ISO 8601, inclusief tijdzone.

        2026-10-03T19:00:00+02:00

    Met tijdzone is bewust gekozen boven een naief tijdstip: een
    memory die je over de grens verhuist moet geen uren lijken te
    oud of jong zijn, en een `created` zonder zone is niet
    eenduidig te lezen. Zie _parse_timestamp(): beide formaten
    worden geaccepteerd, dus oude data blijft leesbaar.
    """

    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _parse_timestamp(text):
    """
    Leest een ISO 8601-tijdstip, met of zonder tijdzone.

    Geeft een epoch in seconden terug, of None als het onleesbaar is.
    Bewust tolerant: bestaande memories kunnen nog het oude naieve
    formaat ("2026-09-07T21:00:00") hebben en die moeten blijven
    werken. Een naief tijdstip wordt gelezen als lokale tijd.
    """

    if not text or not isinstance(text, str):
        return None

    try:
        return datetime.fromisoformat(text).timestamp()

    except ValueError:
        return None

    except (TypeError, OverflowError):
        return None


def _is_entry(value):

    return isinstance(value, dict) and "value" in value


def is_entry_meta(value):
    """
    Geeft de metadata van een memory-entry terug, of None als de
    waarde geen entry is.

    Dit is de lezende kant van het metadata-contract: de caller krijgt
    een kopie, dus wie hem wijzigt raakt het geheugen niet zonder
    save_memory() te doen.

        >>> is_entry_meta({"value": 1})["priority"]
        1.0
        >>> is_entry_meta("warm") is None
        True
    """

    if not _is_entry(value):
        return None

    meta = {veld: value[veld] for veld in ENTRY_META_KEYS if veld in value}

    meta["related"] = _clean_related(meta.get("related"))

    return meta


def _wrap(value):
    """
    Maakt een volledige entry van een kale waarde.

    Alle velden komen uit ENTRY_META_DEFAULTS, dus een nieuwe entry
    is per definitie contract-conform. Priority is standaard 1.0
    (neutraal). Bestaande memories zonder priority worden bij het
    laden automatisch opgevuld.
    """

    entry = {"value": value}

    for veld, standaard in ENTRY_META_DEFAULTS.items():
        entry[veld] = list(standaard) if isinstance(standaard, list) else standaard

    entry["source"] = "conversation"
    entry["created"] = _now()
    entry["updated"] = entry["created"]

    return entry


def _normalize_entry(entry):
    """
    Maakt één bestaande entry contract-conform, zonder hem te overschrijven.

    Bestaande waarden blijven staan; alleen ontbrekende velden worden
    ingevuld. Dat geldt ook voor `created` en `related`: een oude
    memory krijgt created=None en related=[], want er is geen
    betrouwbare bron om een datum op te verzinnen.
    """

    for veld, standaard in ENTRY_META_DEFAULTS.items():

        if veld not in entry:
            entry[veld] = list(standaard) if isinstance(standaard, list) else standaard

    # Een handmatig bewerkte memory.json kan hier van alles invullen.
    # Wat geen bruikbare lijst is, wordt een lege lijst.
    entry["related"] = _clean_related(entry.get("related"))

    return entry


# Velden die remember() ZELF bepaalt in plaats van over te nemen van de
# bestaande entry. Alles anders in ENTRY_META_DEFAULTS hoort bij het
# FEIT en wordt bewaard, ook als de waarde verandert.
#
#   source          : komt van de aanroeper ("conversation", "user", ...)
#   updated         : is altijd het moment van deze opslag
#   previous_value  : wordt door remember() zelf vastgesteld bij een
#                     conflicterende nieuwe waarde; bij een gelijke
#                     waarde blijft de eerdere historie staan
#   corrected       : staat aan bij een expliciete correctie
#   conflict        : staat uit zodra de waarde is opgeslagen
#
# Priority hoort hier NIET bij: die wordt eerst overgenomen en kan
# daarna alsnog expliciet worden overschreven (met de bestaande clamp
# op 0.0-10.0).
#
# Bewust in ÉN plek, zodat er geen tweede metadata-implementatie
# naast ENTRY_META_DEFAULTS kan ontstaan.
_REMEMBER_SETTLED = {
    "source",
    "updated",
    "previous_value",
    "corrected",
    "conflict",
}


def _carry_metadata(entry, existing):
    """
    Neemt de bestaande contract-metadata over op een nieuwe entry.

    Dit is de kern van "een bestaande memory behoudt haar metadata".
    Bij een gewone waardewijziging blijven usage_count, last_used,
    created, related en de rest dus staan; alleen de waarde en de
    door remember() bepaalde velden veranderen.

    Zonder een bestaande entry is er niets om over te nemen en blijft
    de nieuwe entry op zijn defaults staan.
    """

    if not _is_entry(existing):
        return entry

    for veld in ENTRY_META_DEFAULTS:

        if veld in _REMEMBER_SETTLED:
            continue

        if veld == "related":
            continue

        entry[veld] = existing.get(veld, entry[veld])

    entry["related"] = _clean_related(existing.get("related"))

    return entry


def _unwrap(value):

    if _is_entry(value):
        return value["value"]

    return value


def _normalize(memory):
    """Zorgt dat elk geheugenbestand een geldige structuur heeft."""

    for category in DEFAULT_CATEGORIES:

        if category not in memory or not isinstance(memory[category], dict):
            memory[category] = {}

        for key, value in list(memory[category].items()):

            if not _is_entry(value):
                memory[category][key] = _wrap(value)

            # Bestaande entries worden aangevuld volgens het
            # metadata-contract; wat er al staat blijft staan.
            _normalize_entry(memory[category][key])

    # Beleid (zie _canonical_category): alleen DEFAULT_CATEGORIES zijn
    # toegestaan. Een entry die nog in een onbekende categorie staat,
    # wordt naar "algemeen" gebracht zodat hij ook echt leesbaar is.
    # Er wordt nooit overschreven: bij een naambotsing wint de
    # bestaande entry in "algemeen".
    for category in list(memory.keys()):

        if category in DEFAULT_CATEGORIES:
            continue

        if not isinstance(memory[category], dict):
            del memory[category]
            continue

        for key, value in list(memory[category].items()):

            if not _is_entry(value):
                value = _wrap(value)

            if "priority" not in value:
                value["priority"] = 1.0

            if key not in memory["algemeen"]:
                memory["algemeen"][key] = value

        del memory[category]

    return memory


def empty_memory():

    return {category: {} for category in DEFAULT_CATEGORIES}


def load_memory():
    """
    Laadt het geheugen via de opslaglaag (memory/store.py).

    De store regelt de cache, het herstel van een corrupt bestand
    en het terugvallen op de backup. Geeft nooit een crash: bij
    onleesbare data (en geen bruikbare backup) krijg je een lege
    memory terug, net als toen er alleen try/except stond.
    """

    data = store.read(MEMORY_FILE)

    if data is None:
        return empty_memory()

    if not isinstance(data, dict):
        return empty_memory()

    # Oud (plat) formaat automatisch omzetten naar categorieën
    if not any(isinstance(value, dict) for value in data.values()):

        structured = empty_memory()

        for key, value in data.items():
            category = get_category(key, str(value))
            structured[category][key] = _wrap(value)

        return _normalize(structured)

    return _normalize(data)


def save_memory(memory):
    """
    Bewaart het geheugen atomair via de opslaglaag.

    Schrijft nooit rechtstreeks over memory.json: eerst naar een
    tijdelijk bestand, daarna atomair omwisselen. Een crash
    tijdens het schrijven laat dus geen halfgeschreven geheugen
    achter.
    """

    store.write(MEMORY_FILE, memory)



def beautify(value):

    return str(value).replace("_", " ")


def get_category(key, value=""):

    text = f"{key} {value}".lower()

    # Specifiekere categorieën eerst, zodat "favoriete band"
    # naar muziek gaat en "favoriete game" naar voorkeuren.
    check_order = ["pc", "muziek", "projecten", "voorkeuren", "apparaten"]

    for category in check_order:

        if any(word in text for word in CATEGORY_KEYWORDS[category]):
            return category

    return "algemeen"

def get_entry(key, category=None):
    """
    Geeft de volledige entry (met metadata) terug, of None als de
    sleutel niet bestaat. Zoekt exact én genormaliseerd, zoals
    recall(). Geen substring-matching: "kleur" vindt "favoriete_kleur"
    niet.
    """

    _, entry = find_entry(key, category)

    return entry



def find_entry(key, category=None):
    """
    Zoekt een entry op opslag-identiteit: exact, of genormaliseerd op
    hoofdletters en spaties/underscores/koppeltekens.

    Geeft (categorie, entry) terug, of (None, None) als er niets is.

    Geen substring-matching: die hoort niet bij het opslagniveau. Een
    gebruiker die "licht" zegt terwijl er "lichtvoorkeur" staat, krijgt
    via resolve_existing_key() een expliciete vraag, niet een stille
    gok.
    """

    memory = load_memory()

    key_norm = _normalize_key(key)

    if not key_norm:
        return None, None

    categories = [category] if category else DEFAULT_CATEGORIES

    # 1. Exact (hoofdletterongevoelig)
    for c in categories:

        for stored_key, entry in memory.get(c, {}).items():

            if stored_key.lower().strip() == key.lower().strip():
                return c, entry

    # 2. Genormaliseerd: spatie / underscore / koppelteken onderling gelijk
    for c in categories:

        for stored_key, entry in memory.get(c, {}).items():

            if _normalize_key(stored_key) == key_norm:
                return c, entry

    return None, None


def _find_existing(key, category=None):
    """
    Zoekt een bestaande entry op opslag-identiteit.

    Geeft (found_category, actual_stored_key, existing_entry) terug,
    of (None, None, None) als er niets is gevonden.

    Identiteit = exact, of genormaliseerd (_ ≡ - ≡ spatie). Geen
    substring-matching: die bepaalt niet meer welke memory-entry wordt
    aangemaakt, gewijzigd, verwijderd of als conflict beschouwd. De
    enige overgebleven substring-pass is resolve_existing_key(), die
    uitsluitend een conversatiehulp is en niets wegschrijft.
    """

    memory = load_memory()

    key_norm = _normalize_key(key)

    if not key_norm:
        return None, None, None

    categories = [category] if category else DEFAULT_CATEGORIES

    # 1. Exact (onderliggende key identiek)
    for c in categories:
        for stored_key, entry in memory.get(c, {}).items():
            if stored_key.lower().strip() == str(key).lower().strip():
                return c, stored_key, entry

    # 2. Genormaliseerd: spaties/underscores/koppeltekens onderling gelijk
    for c in categories:
        for stored_key, entry in memory.get(c, {}).items():
            if _normalize_key(stored_key) == key_norm:
                return c, stored_key, entry

    return None, None, None


def resolve_existing_key(key, category=None):
    """
    Gesprekshulp (NIET de opslag): koppelt een vrij geformuleerde
    uiting aan een opgeslagen memory-sleutel.

    Dit is de enige plek waar nog substring-matching mag voorkomen, en
    dat bewust: "wijzig licht naar warm" moet "lichtvoorkeur" kunnen
    raken zonder dat er een tweede entry ontstaat. Deze functie
    wijzigt NIETS — wie bevestigt, beslist zelf.

    Geeft een dict terug met:

        status     : "exact"  de sleutel bestaat (exact of genorm.)
                     "fuzzy"  een of meer losse kandidaten
                     "none"   geen kandidaat
        key        : de opgeslagen sleutel ("exact") of de
                     oorspronkelijke query ("none"), anders None
        category   : de categorie waarin de sleutel staat ("exact"),
                     anders None
        candidates : alle kandidaten (bij "exact" alleen de match,
                     bij "none" een lege lijst)
        exact      : of er een exacte match is
    """

    oplossing = {
        "status": "none",
        "key": key if isinstance(key, str) else None,
        "category": None,
        "candidates": [],
        "exact": False,
    }

    if not isinstance(key, str) or not key.strip():
        return oplossing

    # 1. Exact of genormaliseerd — dezelfde regel als de opslag
    found_category, stored_key, _ = _find_existing(key, category)

    if stored_key is not None:
        return {
            "status": "exact",
            "key": stored_key,
            "category": found_category,
            "candidates": [stored_key],
            "exact": True,
        }

    # 2. Substring — uitsluitend voor conversatie
    memory = load_memory()

    norm = _normalize_key(key)

    kandidaat_categories = [category] if category else DEFAULT_CATEGORIES

    kandidaten = []

    for c in kandidaat_categories:

        for stored_key in memory.get(c, {}):

            opgeslagen = _normalize_key(stored_key)

            if norm and opgeslagen and (norm in opgeslagen
                                         or opgeslagen in norm):
                kandidaten.append(stored_key)

    if not kandidaten:
        return oplossing

    oplossing["status"] = "fuzzy"
    oplossing["key"] = kandidaten[0] if len(kandidaten) == 1 else None
    oplossing["candidates"] = kandidaten

    return oplossing


def remember(key, value, category=None, source="conversation", explicit=False,
             priority=None, force=False):
    """
    Slaat een feit op als entry met metadata.

    Geeft een dict terug met de uitkomst:
        changed     : er stond een andere waarde
        conflict    : er stond een andere waarde én er is geen expliciete
                      correctie ("onthoud", "wijzig")
        previous    : de oude waarde (of None)
        category    : waarin de waarde is opgeslagen
        corrected   : expliciete correctie (update_memory)
        needs_confirm : True als het feit een conflict heeft met een
                      bestaande waarde en er om bevestiging gevraagd
                      moet worden. De nieuwe waarde is NIET opgeslagen.

    Bij een conflict wordt de nieuwe waarde NIET automatisch
    opgeslagen als `force=False` en `explicit=False`. De aanroeper
    kan dan om bevestiging vragen via het pending_choice-mechanisme.
    Na bevestiging moet `resolve_conflict()` worden aangeroepen.

    Optioneel:
        priority  : een getal (0.0–10.0) dat aangeeft hoe belangrijk
                    dit feit is. Standaard 1.0 (neutraal). Een hoge
                    priority versterkt de eindscore, een lage verzwakt
                    die. Zonder prioriteit wordt de bestaande waarde
                    behouden bij updates.
force     : overschrijf ook bij een conflict. Alleen gebruiken
                na expliciete bevestiging van de gebruiker.

    Een bestaande memory wordt bij een gewone waardewijziging bijgewerkt
    op zijn EIGEN plek: zelfde category, zelfde key, en de metadata
    (created, usage_count, last_used, priority, related) blijft staan
    (zie _carry_metadata()). Alleen source, updated, previous_value,
    corrected en conflict zijn waarde-afhankelijk. De category die de
    aanroeper meegeeft geldt daarom alleen voor een nieuw feit; de
    identiteit van een bestaand feit ligt bij wat er al in de database
    staat. De lookup loopt daarom over alle categorieen, zodat er nooit
    een tweede entry met dezelfde genormaliseerde sleutel ontstaat.
    """

    # --- EERST CONFLICT DETECTEREN, DAN PAS OPSLAAN ---

    # Categoriebeleid vóór de lookup, zodat een expliciete onbekende
    # categorie niet buiten het zicht van de conflictdetectie valt.
    if category:
        category = _canonical_category(category)

    # De lookup gaat bewust over ALLE categorieen, niet alleen over de
    # meegegeven categorie. Opslag-identiteit hoort niet af te hangen van
    # de categorie die de aanroeper gokt: anders zou remember() hetzelfde
    # feit een tweede keer opslaan (zelfde normalisatie, andere sleutel of
    # categorie) en blijft de eerste, nu verouderde entry de waarde geven
    # die recall() terugstuurt. Zie _find_existing(): exact + genormaliseerd,
    # nooit substring.
    found_category, stored_key, existing = _find_existing(key)

    old = _unwrap(existing) if existing is not None else None

    conflict = old is not None and not _values_equal(old, value)

    if conflict and not force and not explicit:
        return {
            "changed": True,
            "conflict": True,
            "previous": str(old) if old is not None else None,
            "category": found_category or (category or get_category(key, str(value))),
            "corrected": False,
            "needs_confirm": True,
            "memory_key": stored_key or key,
            "memory_value": value,
            "old_value": old,
        }

    # --- NIET OF WEL CONFLICT: OPSLAAN ---

    memory = load_memory()

    # Een bestaande entry blijft waar hij staat. De identiteit is hierboven
    # al gevonden, dus de schrijfplek is found_category/stored_key; de
    # (auto- of expliciet) gevraagde categorie geldt alleen voor een NIEUW
    # feit. Een waardewijziging verhuist geen feit en maakt geen tweede
    # entry: dat zou de metadata over twee plaatsen verdelen en de oude
    # waarde laten winnen bij recall().
    category = found_category or category or get_category(key, str(value))

    if category not in memory:
        memory[category] = {}

    memory.setdefault(category, {})

    # --- De nieuwe waarde, en de metadata die erbij hoort ---
    #
    # De metadata hoort bij het FEIT, niet bij de waarde. Een gewone
    # waardewijziging is dus geen nieuw feit: de gebruiksgeschiedenis,
    # de oorspronkelijke datum en de relaties blijven staan. Zie
    # _carry_metadata() en _REMEMBER_SETTLED voor wat wél en niet
    # wordt overgenomen.
    entry = _wrap(value)

    entry["source"] = source
    entry["updated"] = _now()

    _carry_metadata(entry, existing)

    # Een conflicterende nieuwe waarde schuift de historie op: wat er
    # nu staat verdringt de vorige waarde, en die gaat naar
    # previous_value. Bij een gelijke waarde blijft de eerdere
    # historie staan.
    if conflict:
        entry["previous_value"] = old
    elif _is_entry(existing):
        entry["previous_value"] = existing.get("previous_value")

    # Correctie-markeerder: alleen bij een expliciete correctie.
    entry["corrected"] = bool(explicit)

    # Een opgeslagen waarde nooit in conflict laten staan.
    entry["conflict"] = False

    # Priority: expliciet gezet (met clamp), of de bestaande waarde die
    # _carry_metadata al heeft overgenomen.
    if priority is not None:
        try:
            entry["priority"] = max(_MIN_PRIORITY, min(_MAX_PRIORITY, float(priority)))
        except (TypeError, ValueError):
            entry["priority"] = _DEFAULT_PRIORITY

    # Onder de gevonden sleutel, zodat een normaliserende variant
    # ("fav-band" bij een opgeslagen "fav band") dezelfde entry bijwerkt
    # in plaats van een tweede, bijna-identieke entry ernaast te zetten.
    memory[category][stored_key or key] = entry

    save_memory(memory)

    return {
        "changed": conflict,
        "conflict": False,
        "previous": str(old) if conflict else None,
        "category": category,
        "corrected": bool(explicit),
        "related": list(entry["related"]),
    }


def update_memory(key, value, category=None, source="user"):
    """
    Expliciete correctie van een onthouden feit.
    "wijzig mijn favoriete kleur naar blauw" → wordt bijgewerkt en
    gemarkeerd als corrected, met de oude waarde bewaard.
    """

    return remember(key, value, category=category, source=source, explicit=True)


def has_conflict(key, value, category=None):
    """
    Geeft (bool, huidige_waarde, categorie) terug voor een sleutel.

    bool is True als er al een ANDERE waarde staat voor deze sleutel,
    gemeten met _values_equal(): een bool is dus nooit gelijk aan de
    tekst "ja", ook al is dat precies hoe Obsidian die waarde maakt.
    De waarde is nog niet opgeslagen; gebruik resolve_conflict() om
    de wijziging definitief te maken.
    """

    found_category, stored_key, existing = _find_existing(key, category)

    if existing is None:
        return False, None, None

    old = _unwrap(existing)

    return (not _values_equal(old, value)), old, found_category


def resolve_conflict(key, value, keep_old=False, category=None, priority=None):
    """
    Werkt een eerder gemeld conflict af nadat de gebruiker heeft
    gekozen.

    keep_old=False : de nieuwe waarde wordt de actuele waarde
    keep_old=True  : de oude waarde blijft staan (het conflict wordt
                     alleen in de metadata vastgelegd)

    Geeft een dict terug met de uitkomst:
        applied   : of er iets is opgeslagen
        kept_old  : of de oude waarde behouden is
        value     : de waarde die nu als actueel geldt
        previous  : de waarde die hiervoor gold
        category  : de categorie
        corrected : True als dit een gecorrigeerd feit is
    """

    found_category, stored_key, existing = _find_existing(key, category)

    if stored_key is None:
        # Er was geen conflict; sla de waarde gewoon op.
        remember(key, value, category=category, priority=priority)

        return {
            "applied": True,
            "kept_old": False,
            "value": value,
            "previous": None,
            "category": category or get_category(key, str(value)),
            "corrected": False,
        }

    old = _unwrap(existing)

    category = category or found_category

    if keep_old:
        # Oude waarde blijft actueel; leg het conflict alleen vast.
        memory = load_memory()

        entry = memory[found_category][stored_key]

        entry["conflict"] = True
        entry["conflict_resolved"] = _now()
        entry["conflict_kept_old"] = True
        entry["conflict_rejected_value"] = value

        save_memory(memory)

        return {
            "applied": False,
            "kept_old": True,
            "value": old,
            "previous": None,
            "category": found_category,
            "corrected": False,
        }

    # Nieuwe waarde wordt actueel; oude waarde blijft bewaard.
    remember(
        stored_key, value,
        category=category,
        source="user",
        explicit=True,
        priority=priority,
        force=True,
    )

    memory = load_memory()

    entry = memory[category].get(stored_key)

    if entry is not None:
        entry["conflict"] = False
        entry["conflict_resolved"] = _now()
        entry["conflict_kept_old"] = False
        save_memory(memory)

    return {
        "applied": True,
        "kept_old": False,
        "value": value,
        "previous": str(old),
        "category": category,
        "corrected": True,
    }


def touch_usage(key, category=None):
    """
    Verhoogt usage_count en zet last_used (voor relevante-feiten-score).

    Matcht op opslag-identiteit: exact, of genormaliseerd op
    spaties/underscores/koppeltekens. Geen substring-matching —
    touch_usage("band") mag "fav band" niet tellen.

    Slaat over als de sleutel binnen dit commando al geteld is
    (dedup via _touched_keys).
    """

    key_norm = _normalize_key(key)

    if not key_norm:
        return False

    # Dedup: niet twee keer tellen voor hetzelfde commando
    if key_norm in _touched_keys:
        return False

    memory = load_memory()

    categories = [category] if category else DEFAULT_CATEGORIES

    for c in categories:

        for stored_key, entry in memory.get(c, {}).items():

            if _normalize_key(stored_key) != key_norm:
                continue

            if isinstance(entry, dict):
                entry["usage_count"] = int(entry.get("usage_count") or 0) + 1
                entry["last_used"] = _now()
                save_memory(memory)

                _touched_keys.add(key_norm)

                return True

    return False


def recall(key, category=None):

    entry = get_entry(key, category)

    return _unwrap(entry) if entry is not None else None


# =============================================================
# RELATIES (Fase 14, Stap 7)
#
# `related` is een ECHTE relatie: een lijst met memory-keys die
# inhoudelijk bij dit feit horen. Het is nadrukkelijk NIET de lijst
# met alle andere sleutels in dezelfde categorie. Zo'n sibling-graaf
# is geen relatie: "pc" en "muziek" delen wel een map, maar niet een
# betekenis.
#
# Ontwerpkeuzes, en waarom:
#
# * BIDIRECTIONEEL. add_related("A", "B") schrijft beide kanten.
#   Een eenzijdig verband is in de praktijk altijd een vergissing,
#   en A->B zonder B->A leidt tot een graf die je half kan
#   verwijderen zonder het te merken.
#
# * KEY GEBASEERD, NIET CATEGORIE GEBASEERD. Het enige wat een
#   sleutel identificeert is de sleutel. Dat is bewust dezelfde
#   regel als elders in dit bestand: _normalize_key() voor de
#   normalisatie, GEEN substring, GEEN fuzzy. add_related()
#   raakt resolve_existing_key() niet aan.
#
# * STRIKT BIJ SCHRIJVEN. Een relatie naar een sleutel die niet
#   bestaat wordt niet opgeslagen. We gokken geen "misschien komt
#   hij nog"-relatie: die zou een dode verwijzing worden zodra het
#   om het andere feit gaat.
#
# * ONDERHOUD BIJ VERWIJDEREN. forget() haalt de weggehaalde
#   sleutel uit alle andere entries, zodat er geen dode verwijzing
#   overblijft. Dat gebeurt in dezelfde save_memory()-schrijfactie
#   als het verwijderen zelf, dus het is atomair.
# =============================================================


def _clean_related(related):
    """
    Maakt van wat dan ook een bruikbare related-lijst.

    Accepteert None, een string of een lijst; negeert onbruikbare
    elementen, verwijdert duplicaten en houdt de volgorde. Geeft altijd
    een nieuwe lijst terug, zodat de oorspronkelijke entry nooit via
    een gedeelde lijst kan worden gewijzigd.
    """

    if isinstance(related, str):
        related = [related]

    if not isinstance(related, (list, tuple, set)):
        return []

    schoon = []

    for item in related:

        if not isinstance(item, str):
            continue

        item = item.strip()

        if item and item not in schoon:
            schoon.append(item)

    return schoon


def _stored_keys(memory):
    """Alle memory-keys in het geheugen, ongeordend."""

    keys = set()

    for category in DEFAULT_CATEGORIES:

        for key in memory.get(category, {}):
            keys.add(_normalize_key(key))

    return keys


def _resolve_stored_key(memory, key):
    """
    Zoekt de exact/genormaliseerde sleutel op in het geheugen.

    Geeft de opgeslagen sleutel terug (met de originele spelling), of
    None. GEEN fuzzy, GEEN substring: dit is dezelfde opslag-identiteit
    als find_entry() gebruikt.
    """

    key_norm = _normalize_key(key)

    if not key_norm:
        return None

    for category in DEFAULT_CATEGORIES:

        for stored_key in memory.get(category, {}):

            if _normalize_key(stored_key) == key_norm:
                return stored_key

    return None


def _relations_of(memory, key):
    """
    Geeft de opgeslagen related-lijst van één memory-entry.

    Let op: dit is de ECHTE lijst uit de entry. Er worden geen
    siblings bijgerekend.
    """

    stored_key = _resolve_stored_key(memory, key)

    if stored_key is None:
        return []

    for category in DEFAULT_CATEGORIES:

        entry = memory.get(category, {}).get(stored_key)

        if isinstance(entry, dict):
            return _clean_related(entry.get("related"))

    return []


def _entry_related_set(memory):
    """
    Alle relaties uit het geheugen als dict: sleutel -> set van
    genormaliseerde doelsleutels.

    Met genormaliseerde sleutels, want een relatie moet één feit
    zijn, geen spellingvariant.
    """

    relaties = {}

    for category in DEFAULT_CATEGORIES:

        for key, entry in memory.get(category, {}).items():

            if not isinstance(entry, dict):
                continue

            doelen = set()

            for item in _clean_related(entry.get("related")):

                norm = _normalize_key(item)

                if norm and norm != _normalize_key(key):
                    doelen.add(norm)

            if doelen:
                relaties[_normalize_key(key)] = doelen

    return relaties


def _target_of(norm_key, memory):
    """De opgeslagen sleutel + entry voor een genormaliseerde sleutel."""

    for category in DEFAULT_CATEGORIES:

        for stored_key, entry in memory.get(category, {}).items():

            if _normalize_key(stored_key) == norm_key:
                return stored_key, entry

    return None, None


def _drop_relations(memory, norm_key):
    """
    Haalt `norm_key` uit de related-lijst van alle andere entries.

    Geeft het aantal entries terug dat is aangepast. De wijzigingen
    zitten in `memory`; de caller beslist over save_memory().
    """

    geraakt = 0

    for category in DEFAULT_CATEGORIES:

        for key, entry in memory.get(category, {}).items():

            if not isinstance(entry, dict):
                continue

            if _normalize_key(key) == norm_key:
                continue

            huidig = _clean_related(entry.get("related"))

            if not huidig:
                continue

            schoon = [item for item in huidig
                      if _normalize_key(item) != norm_key]

            if len(schoon) != len(huidig):
                entry["related"] = schoon
                geraakt += 1

    return geraakt


def add_related(key, related, category=None):
    """
    Legt een relatie tussen twee memories vast (Stap 7).

    Bidirectioneel: beide entries worden bijgewerkt. Geeft een dict
    terug:

        added     : True als er iets is toegevoegd
        key       : de opgeslagen sleutel van het eerste feit
        related   : de opgeslagen sleutel van het tweede feit
        skipped   : lijst met redenen per overgeslagen key
        changed   : True als er iets geschreven moest worden

    Veiligheidsregels, allemaal expliciet getest:
        - beide sleutels moeten bestaan; anders wordt de relatie
          NIET opgeslagen (een relatie naar niets is een lege
          verwijzing, geen "misschien"-hint);
        - geen fuzzy matching: "fav band" wordt nooit gevonden door
          "band" te zoeken. Gebruik resolve_existing_key() als je
          een verkorte formulering wilt laten bevestigen;
        - een relatie naar zichzelf wordt geweigerd;
        - een bestaande relatie wordt niet dubbel toegevoegd;
        - normalisatie geldt: "Fav Band" en "fav_band" zijn hetzelfde
          feit, dus de relatie bestaat dan al.
    """

    resultaat = {
        "added": False,
        "key": None,
        "related": None,
        "skipped": [],
        "changed": False,
    }

    memory = load_memory()

    stored_a = _resolve_stored_key(memory, key)
    stored_b = _resolve_stored_key(memory, related)

    if stored_a is None:
        resultaat["skipped"].append("onbekend feit: %s" % key)
        return resultaat

    if stored_b is None:
        resultaat["skipped"].append("onbekend feit: %s" % related)
        return resultaat

    resultaat["key"] = stored_a
    resultaat["related"] = stored_b

    norm_a = _normalize_key(stored_a)
    norm_b = _normalize_key(stored_b)

    if norm_a == norm_b:
        resultaat["skipped"].append("een feit kan niet aan zichzelf gerelateerd zijn")
        return resultaat

    _, entry_a = _target_of(norm_a, memory)
    _, entry_b = _target_of(norm_b, memory)

    if entry_a is None or entry_b is None:
        resultaat["skipped"].append("feit niet meer aanwezig")
        return resultaat

    veranderd = False

    # Een bestaande relatie blijft op zijn plek staan; alleen de spelling
    # wordt genormaliseerd naar zoals de sleutel in het geheugen heet.
    # Zo blijft de lijst stabiel: twee exports van dezelfde memory
    # leveren dezelfde notitie, en een identieke add_related() raakt
    # de schijf niet aan.
    for doel_norm, entry, doel_sleutel in ((norm_b, entry_a, stored_b),
                                           (norm_a, entry_b, stored_a)):

        huidig = _clean_related(entry.get("related"))

        positie = None

        for index, item in enumerate(huidig):

            if _normalize_key(item) == doel_norm:
                positie = index
                break

        if positie is None:

            entry["related"] = huidig + [doel_sleutel]

            veranderd = True

            continue

        if huidig[positie] != doel_sleutel:

            huidig[positie] = doel_sleutel

            entry["related"] = huidig

            veranderd = True

    if not veranderd:
        resultaat["added"] = True
        return resultaat

    save_memory(memory)

    resultaat["added"] = True
    resultaat["changed"] = True

    return resultaat


def remove_related(key, related, category=None):
    """
    Haalt een relatie tussen twee memories weg (Stap 7).

    Bidirectioneel: de relatie verdwijnt aan beide kanten. Geeft een
    dict terug:

        removed   : True als er ergens iets is verwijderd
        key       : de opgeslagen sleutel van het eerste feit
        related   : de opgeslagen sleutel van het tweede feit
        skipped   : lijst met redenen per overgeslagen key

    Een relatie die er niet is geeft removed=False en is geen fout:
    weghalen wat er niet staat hoeft niet te crashen.
    """

    resultaat = {
        "removed": False,
        "key": None,
        "related": None,
        "skipped": [],
    }

    memory = load_memory()

    stored_a = _resolve_stored_key(memory, key)
    stored_b = _resolve_stored_key(memory, related)

    if stored_a is None:
        resultaat["skipped"].append("onbekend feit: %s" % key)
        return resultaat

    if stored_b is None:
        resultaat["skipped"].append("onbekend feit: %s" % related)
        return resultaat

    resultaat["key"] = stored_a
    resultaat["related"] = stored_b

    norm_b = _normalize_key(stored_b)
    norm_a = _normalize_key(stored_a)

    _, entry_a = _target_of(norm_a, memory)
    _, entry_b = _target_of(norm_b, memory)

    for doel_norm, entry in ((norm_b, entry_a), (norm_a, entry_b)):

        if not isinstance(entry, dict):
            continue

        huidig = _clean_related(entry.get("related"))

        schoon = [item for item in huidig if _normalize_key(item) != doel_norm]

        if len(schoon) != len(huidig):
            entry["related"] = schoon
            resultaat["removed"] = True

    if resultaat["removed"]:
        save_memory(memory)

    return resultaat


def get_related(key, category=None):
    """
    Geeft de ECHTE relaties van één memory terug (Stap 7).

    Alleen wat er echt in de entry staat. Er worden GEEN siblings
    toegevoegd: een memory in dezelfde categorie is geen relatie.

        >>> add_related("fav_game", "gaming_pc")["added"]
        True
        >>> get_related("fav_game")
        ['gaming_pc']

    De lijst is gesorteerd, zodat twee exports van dezelfde memory
    dezelfde notitie opleveren. Geeft [] voor een onbekende sleutel.
    """

    return sorted(_relations_of(load_memory(), key))


def has_related(key, related, category=None):
    """
    Staat key inderdaad gerelateerd aan related? Geeft bool.

    Vergelijkt op genormaliseerde sleutels, zodat "Fav Game" en
    "fav_game" hetzelfde feit zijn.
    """

    norm_a = _normalize_key(key)
    norm_b = _normalize_key(related)

    if not norm_a or not norm_b or norm_a == norm_b:
        return False

    return norm_b in _entry_related_set(load_memory()).get(norm_a, set())


def clear_related(key):
    """
    Leegt de relaties van één memory (beide kanten blijven bestaan).

    Geeft True als er iets is gewijzigd. Werkt volledig in het
    geheugen en schrijft één keer, zodat de entry die wordt geleegd
    niet door een tussenliggende save() wordt overschreven.
    """

    memory = load_memory()

    stored_key = _resolve_stored_key(memory, key)

    if stored_key is None:
        return False

    norm_key = _normalize_key(stored_key)

    doelen = set(_entry_related_set(memory).get(norm_key, set()))

    if not doelen:
        return False

    _, entry = _target_of(norm_key, memory)

    entry["related"] = []

    for doel in doelen:

        _, doel_entry = _target_of(doel, memory)

        if not isinstance(doel_entry, dict):
            continue

        doel_entry["related"] = [
            item for item in _clean_related(doel_entry.get("related"))
            if _normalize_key(item) != norm_key
        ]

    save_memory(memory)

    return True


def forget(key):
    """
    Verwijdert één geheugenfeit. Geeft True als er iets verwijderd is.

    Matcht op opslag-identiteit: exact, of genormaliseerd op
    spaties/underscores/koppeltekens. Geen substring-matching —
    forget("band") mag nooit "fav band" verwijderen.

    Wil je een verkorte of andere formulering gebruiken ("vergeet
    licht" voor "lichtvoorkeur"), laat dat dan eerst oplossen via
    resolve_existing_key() zodat de gebruiker kan bevestigen.

    Stap 7: de weggehaalde sleutel wordt meteen uit de related-lijst
    van alle andere memories gehaald. Er blijft dus geen dode
    verwijzing achter. Dat gebeurt in dezelfde save_memory()-schrijfactie
    als het verwijderen zelf, dus het is atomair: na de schrijfactie is
    het geheugen óf helemaal zonder deze sleutel, óf nog helemaal
    onaangeroerd.
    """

    key_norm = _normalize_key(key)

    if not key_norm:
        return False

    memory = load_memory()

    for category in DEFAULT_CATEGORIES:

        for stored_key in list(memory.get(category, {}).keys()):

            if _normalize_key(stored_key) != key_norm:
                continue

            del memory[category][stored_key]

            _drop_relations(memory, key_norm)

            save_memory(memory)

            return True

    return False


def clear_memory():

    save_memory(empty_memory())

    return True


def get_all_memory():

    memory = load_memory()

    result = {}

    for category in DEFAULT_CATEGORIES:

        for key, entry in memory.get(category, {}).items():

            result[key] = _unwrap(entry)

    return result


def get_category_memory(category):

    memory = load_memory()

    return {
        key: _unwrap(entry)
        for key, entry in memory.get(category, {}).items()
    }


def memory_summary():

    memory = load_memory()

    parts = []

    for category in DEFAULT_CATEGORIES:

        items = memory.get(category, {})

        if not items:
            continue

        lines = [
            f"{key.replace('_', ' ')} is {beautify(_unwrap(value))}"
            for key, value in items.items()
        ]

        parts.append(f"{category}: {', '.join(lines)}")

    if not parts:
        return "Ik heb nog niets onthouden."

    return "; ".join(parts)


# =============================================================
# Fase 5 — RELEVANTE MEMORY AUTOMATISCH OPHALEN
#
# In plaats van de volledige geheugendump in het AI-prompt te
# stoppen, selecteren we alleen de feiten die bij de huidige
# opdracht horen. Zo kan "maak de kamer gezellig" de voorkeur
# "warm wit licht" meenemen zonder ruis.
# =============================================================


# =============================================================
# FASE 14 STAP 3 — RELEVANTE MEMORY OPHALEN (verbeterd)
#
# Bepaalt welke opgeslagen feiten bij een vraag relevant zijn.
# Volledig deterministisch: geen AI, geen embeddings, net als
# toen. De verbetering zit in vier dingen:
#
#   1. WOORDGRENZEN in plaats van kale substring.
#      Vroeger goldt `key in vraag`, waardoor "ram" matchte in
#      "programma" en "licht" in "misschien". Nu zoekt een regex
#      met woordgrenzen, zodat toevallige substrings niets scoren.
#
#   2. STOPWOORDEN + lichte meervoudsvorm.
#      "wat is mijn kleur" scoort niet meer op "mijn"/"is", en
#      "lampen" matcht hierdoor "lamp".
#
#   3. MEERDERE SOORTEN OVEREENKOMST, apart geteld.
#      Sleutel, waarde en categorie tellen elk mee, en een sleutel
#      waarvan álle woorden terugkomen scoort extra hoog.
#
#   4. GEBRUIKSDATA als kleine extra factor.
#      usage_count en last_used tellen mee, maar alleen op een feit
#      dat de tekstcheck al haalde. Zonder tekstovereenkomst blijft
#      de score 0. Zo kan gebruik nooit een irrelevant feit naar
#      voren duwen, en zit er bewust nog geen decay/veroudering in.
# =============================================================

# Maximaal aantal memories dat get_relevant_memory teruggeeft.
DEFAULT_RELEVANT_ITEMS = 6

# Woorden die over het onderwerp niets zeggen. Zelfde opzet als
# _VALIDATION_STOPWORDS in core/ai.py.
_STOPWORDS = frozenset({
    "de", "het", "een", "en", "of", "maar", "wat", "is", "zijn",
    "mijn", "mij", "ik", "je", "jij", "jou", "jouw", "uw", "haar",
    "naar", "voor", "met", "van", "dat", "die", "dit", "dan", "als",
    "ook", "even", "graag", "aub", "nu", "kan", "kun", "kunt", "wil",
    "wilt", "moet", "moeten", "mag", "hem", "hier", "daar", "niet",
    "geen", "wel", "bij", "tot", "uit", "was", "waren", "bent",
    "heb", "hebt", "hebben", "heeft", "wordt", "worden", "werd",
    "hoe", "wie", "waar", "wanneer", "welke", "welk", "waarom",
    "toch", "nog", "al", "zo", "echt", "gewoon", "veel", "weinig",
    "the", "and", "you", "your", "for", "with", "this", "that",
})

# Werkwoorden uit een opdracht ("open de lamp", "zet het volume").
# Die zeggen iets over de ACTIE, niet over het onderwerp, en zouden
# anders elke memory met zo'n woord in de sleutel naar voren duwen.
_ACTION_WORDS = frozenset({
    "open", "openen", "sluit", "sluiten", "zet", "zetten", "maak",
    "maken", "start", "starten", "stop", "stoppen", "pauzeer",
    "pauzeren", "dempen", "versterken", "houd", "geven", "geef",
    "vertel", "zeg", "doen", "gaan", "ga", "kom", "help", "weten",
    "verander", "veranderen", "wijzig", "wijzigen", "onthoud",
    "vergeet", "verwijder", "zoek", "vind", "download", "update",
    "check", "laat", "zorg", "kies", "selecteer", "activeer",
    "deactiveer", "schakel", "terug", "vooruit", "omhoog", "omlaag",
    "harder", "zachter", "luider", "volgende", "vorige",
    "minimaliseer", "maximaliseer", "versterk",
})


def _tokens(text):
    """Alle woorden uit een tekst, voor vergelijking."""

    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _stem(token):
    """
    Zeer lichte meervoudsvorm: "lampen" -> "lamp", "kleuren" ->
    "kleur". Bewust conservatief; een echte stammer (difflib) komt
    in een latere stap.
    """

    if len(token) >= 5 and token.endswith("en"):
        return token[:-2]

    if len(token) >= 5 and token.endswith("s") \
            and not token.endswith(("ss", "us", "is")):
        return token[:-1]

    return token


def _content_tokens(text):
    """
    Inhoudswoorden uit een tekst: zonder stopwoorden, zonder
    werkwoorden, met lichte meervoudsvorm.

    Zelfde aanpak als _content_tokens() in core/ai.py, zodat beide
    lagen consistent met elkaar werken.
    """

    result = set()

    for token in _tokens(text):

        if len(token) < 3:
            continue

        if token in _STOPWORDS or token in _ACTION_WORDS:
            continue

        result.add(_stem(token))

    return result


@lru_cache(maxsize=2048)
def _phrase_pattern(phrase):
    """
    Regex voor een phrase met woordgrenzen.

    Spaties, underscores en koppeltekens tussen woorden zijn
    onderling uitwisselbaar, zodat de sleutel "favoriete_kleur"
    ook matcht op de vraag "mijn favoriete kleur" en andersom.

    (?<!\\w) en (?!\\w) zorgen ervoor dat een korte sleutel als
    "ram" NIET in "programma" matcht, en "licht" niet in
    "misschien".
    """

    words = [re.escape(w) for w in re.split(r"[\s_\-]+", phrase.lower()) if w]

    if not words:
        return None

    return r"(?<!\w)" + r"[\s_\-]+".join(words) + r"(?!\w)"


def _phrase_in(phrase, text):
    """True als de hele phrase met woordgrenzen in de tekst staat."""

    pattern = _phrase_pattern(phrase)

    if not pattern:
        return False

    return re.search(pattern, text) is not None


# Hoeveel de "vaak gebruikt"-factor maximaal waard is. Bewust klein:
# het is een extraatje, geen prioriteitsysteem.
_USAGE_BONUS_CAP = 1.5

# Binnen hoeveel dagen "recent gebruikt" nog iets oplevert.
_RECENCY_BONUS_CAP = 1.0
_RECENCY_WINDOW_DAYS = 30

# =============================================================
# PRIORITY + AGING (Fase 14, Stap 4)
#
# Priority is een getal bovenop de tekstuele relevantie:
#   0.0 … 10.0  (standaard 1.0)
#
# Een priority van 2.0 verdubbelt de eindscore, 0.5 halveert hem.
# Dit is een vermenigvuldiging, geen optelling — zo kan een hoge
# priority nooit een IRRELEVANT feit naar voren duwen (want die
# heeft al een score van 0, en 0 × 2.0 = 0).
#
# Aging is een factor op basis van hoe oud een memory is (gemeten
# aan de `updated`-tijdstempel):
#   ≤ 7 dagen     → +10% bonus
#   7 … 90 dagen  → neutraal (×1,0)
#   90 … 365 dagen→ milde veroudering (×0,90)
#   > 365 dagen   → sterkere veroudering (×0,75)
#
# Beide factoren worden toegepast NA de tekstcheck, dus zonder
# tekstovereenkomst is de score sowieso 0.
# =============================================================

_DEFAULT_PRIORITY = 1.0

# Priority-range
_MIN_PRIORITY = 0.0
_MAX_PRIORITY = 10.0

# Aging-vensters (in dagen)
_AGING_FRESH_DAYS = 7
_AGING_FRESH_FACTOR = 1.1
_AGING_OLD_DAYS = 90
_AGING_OLD_FACTOR = 0.9
_AGING_STALE_DAYS = 365
_AGING_STALE_FACTOR = 0.75


def _age_days(updated):
    """
    Hoeveel dagen geleden is het `updated`-tijdstip verlopen?
    Geeft een niet-negatief getal, of None als het tijdstip
    ongeldig of ontbrekend is.
    """

    if not updated or not isinstance(updated, str):
        return None

    stamp = _parse_timestamp(updated)

    if stamp is None:
        return None

    seconds = time.time() - stamp

    if seconds < 0:
        return 0.0

    return round(seconds / 86400, 1)


def _priority_factor(priority):
    """
    Verandert de priority-score (0.0–10.0) in een vermenigvuldigende
    factor. Standaard is de factor 1.0 (geen invloed).

    Onwaarschijnlijke waarden worden afgekapt.
    """

    try:
        p = float(priority)
    except (TypeError, ValueError):
        return 1.0

    p = max(_MIN_PRIORITY, min(_MAX_PRIORITY, p))

    # 1.0 is de neutrale waarde; elke afwijking is een factor
    return round(p, 2)


def _aging_factor(updated):
    """
    Geeft een vermenigvuldigende factor op basis van de ouderdom
    van een memory. Recente feiten krijgen een kleine bonus;
    oude feiten worden mild afgezwakt. Nooit zo sterk dat een
    relevant feit wegvalt.
    """

    days = _age_days(updated)

    if days is None:
        return 1.0

    if days <= _AGING_FRESH_DAYS:
        return _AGING_FRESH_FACTOR

    if days <= _AGING_OLD_DAYS:
        return 1.0

    if days <= _AGING_STALE_DAYS:
        return _AGING_OLD_FACTOR

    return _AGING_STALE_FACTOR


def _usage_bonus(usage_count):
    """
    Kleine, begrensde bonus voor vaak gebruikte feiten.
    Logaritmisch, zodat 500 gebruikingen niet alles overheersen.
    """

    try:
        count = int(usage_count or 0)
    except (TypeError, ValueError):
        return 0.0

    if count <= 0:
        return 0.0

    return round(min(_USAGE_BONUS_CAP, math.log1p(count) * 0.5), 2)


def _recency_bonus(last_used):
    """
    Kleine bonus voor feiten die je recent gebruikt hebt.
    Tijdstipformaat is hetzelfde als _now() schrijft.
    """

    if not last_used or not isinstance(last_used, str):
        return 0.0

    stamp = _parse_timestamp(last_used)

    if stamp is None:
        return 0.0

    age = time.time() - stamp

    window = _RECENCY_WINDOW_DAYS * 24 * 3600

    if age < 0 or age > window:
        return 0.0

    return round(_RECENCY_BONUS_CAP * (1.0 - (age / window)), 2)


def relevance_score(question, category, key, value, usage_count=0, last_used=None,
                    priority=1.0, updated=None):
    """
    Bepaalt hoe relevant een opgeslagen feit is voor een vraag,
    zonder LLM (deterministisch):

      KEY       hele sleutel als phrase                (+6,0)
                woord-overeenkomst per sleutelwoord    (+2,5 elk)
                álle sleutelwoorden aanwezig           (+2,0)
      WAARDE    hele waarde als phrase                (+4,0)
                woord-overeenkomst per waardewoord    (+1,5 elk)
      CATEGORIE categorie-trefwoord met woordgrens    (+1,5, max 3)
      GEBRUIK   usage_count                       0 … +1,5
                last_used (recency)               0 … +1,0

    Daarna wordt de tekstuele score vermenigvuldigd met:
      - priority  (0.0–10.0, standaard 1.0)
      - aging     (hoe ouder hoe lager, maar nooit onder 0.75)

    Belangrijk: de factor wordt pas NA de tekstcheck toegepast,
    dus een score van 0 × 2.0 = 0. Irrelevante feiten worden
    dus nooit door priority of aging naar voren geduwd.

    Extra parameters hebben defaultwaarden zodat bestaande aanroepen
    met vier of zes argumenten blijven werken.
    """

    question = (question or "").lower()

    tokens_q = _content_tokens(question)
    tokens_k = _content_tokens(key)
    tokens_v = _content_tokens(str(value))

    score = 0.0

    # ---- KEY ----
    if _phrase_in(key, question):
        score += 6.0

    score += 2.5 * len(tokens_k & tokens_q)

    if tokens_k and tokens_k.issubset(tokens_q):
        score += 2.0

    # ---- WAARDE ----
    if _phrase_in(str(value), question):
        score += 4.0

    score += 1.5 * len(tokens_v & tokens_q)

    # ---- CATEGORIE (met woordgrenzen, maximaal 3 treffers) ----
    hits = 0

    for word in CATEGORY_KEYWORDS.get(category, []):
        if _phrase_in(word, question):
            hits += 1

            if hits >= 3:
                break

    score += 1.5 * hits

    # Zonder tekstovereenkomst geen punten, ongeacht gebruik of priority.
    if score <= 0:
        return 0.0

    # ---- GEBRUIK ----
    score += _usage_bonus(usage_count)
    score += _recency_bonus(last_used)

    # ---- PRIORITY + AGING ----
    # Beide factoren worden pas hier toegepast, dus een score van 0
    # zou hier nooit meer kunnen worden. Irrelevante feiten worden
    # dus nooit door priority of aging naar voren geduwd.
    score *= _priority_factor(priority)
    score *= _aging_factor(updated)

    return round(score, 2)


def get_relevant_memory(question, max_items=DEFAULT_RELEVANT_ITEMS):
    """
    Geeft de meest relevante geheugenfeiten voor een vraag terug.

    Elke entry: {'category', 'key', 'value', 'score', 'usage_count',
                 'priority', 'updated'}, aflopend op score.
    Alleen feiten met score > 0.

    De 'max_items'-limiet blijft gelijk (standaard 6) zodat de
    prompt niet vol loopt met ruis.
    """

    memory = load_memory()

    candidates = []

    for category in DEFAULT_CATEGORIES:

        for key, entry in memory.get(category, {}).items():

            value = _unwrap(entry)

            usage_count = entry.get("usage_count", 0) if _is_entry(entry) else 0
            last_used = entry.get("last_used") if _is_entry(entry) else None
            priority = entry.get("priority", _DEFAULT_PRIORITY) if _is_entry(entry) else _DEFAULT_PRIORITY
            updated = entry.get("updated") if _is_entry(entry) else None

            score = relevance_score(
                question, category, key, value,
                usage_count=usage_count,
                last_used=last_used,
                priority=priority,
                updated=updated,
            )

            if score > 0:
                candidates.append({
                    "category": category,
                    "key": key,
                    "value": value,
                    "score": score,
                    "usage_count": usage_count,
                    "priority": priority,
                    "updated": updated,
                })

    # Hoogste score eerst; bij gelijke score het meest gebruikte
    # feit, en bij volledige gelijksstand een stabiele volgorde.
    candidates.sort(key=lambda item: (item["score"], item["usage_count"]), reverse=True)

    return candidates[:max_items]


def relevant_memory_prompt(question, max_items=DEFAULT_RELEVANT_ITEMS):
    """
    Bouwt een korte NL-tekst met de relevante geheugenfeiten voor
    een opdracht. Lege string als er niets relevant is.
    """

    items = get_relevant_memory(question, max_items=max_items)

    if not items:
        return ""

    lines = [
        "Relevante geheugenfeiten over de gebruiker "
        "(alleen gebruiken als ze echt relevant zijn):"
    ]

    for item in items:
        lines.append(
            f"- {item['key'].replace('_', ' ')}: {item['value']}"
        )

    return "\n".join(lines)