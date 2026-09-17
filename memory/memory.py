import json
import os
import re
import time


MEMORY_FILE = os.path.join(
    os.path.dirname(__file__),
    "memory.json"
)

DEFAULT_CATEGORIES = [
    "voorkeuren",
    "pc",
    "projecten",
    "muziek",
    "algemeen",
    "apparaten",
]

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
# ENTRY-MODEL (Fase 5)
#
# Memory wordt opgeslagen als entry met metadata:
#   { "categorie": { "sleutel": {
#        "value": "warm wit",
#        "source": "conversation",
#        "updated": "2026-09-07T21:00:00",
#        "previous_value": None,
#        "corrected": False,
#        "conflict": False,
#        "usage_count": 0,
#        "last_used": None,
#   } } }
#
# Oud (plat) formaat {categorie: {sleutel: waarde}} wordt bij het
# laden automatisch geconverteerd; alle functies blijven compatibel.
# =============================================================

ENTRY_META_KEYS = {
    "value", "source", "updated", "previous_value",
    "corrected", "conflict", "usage_count", "last_used",
}


def _now():

    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _is_entry(value):

    return isinstance(value, dict) and "value" in value


def _wrap(value):

    return {
        "value": value,
        "source": "conversation",
        "updated": _now(),
        "previous_value": None,
        "corrected": False,
        "conflict": False,
        "usage_count": 0,
        "last_used": None,
    }


def _unwrap(value):

    if _is_entry(value):
        return value["value"]

    return value


def _normalize(memory):

    for category in DEFAULT_CATEGORIES:

        if category not in memory or not isinstance(memory[category], dict):
            memory[category] = {}

        for key, value in list(memory[category].items()):

            if not _is_entry(value):
                memory[category][key] = _wrap(value)

    return memory


def empty_memory():

    return {category: {} for category in DEFAULT_CATEGORIES}


def load_memory():

    if not os.path.exists(MEMORY_FILE):
        return empty_memory()

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

    except (json.JSONDecodeError, OSError):
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

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(
            memory,
            file,
            indent=4,
            ensure_ascii=False
        )


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
    sleutel niet bestaat. Zoekt exact én partieel, zoals recall().
    """

    _, entry = find_entry(key, category)

    return entry


def find_entry(key, category=None):
    """
    Geeft (categorie, entry) terug voor een sleutel. Zoekt exact én
    partieel in alle categorieën (of één specifieke categorie).
    """

    memory = load_memory()

    key_lower = key.lower().strip()

    categories = [category] if category else DEFAULT_CATEGORIES

    # Eerst exact zoeken in alle categorieën
    for c in categories:

        for stored_key, entry in memory.get(c, {}).items():

            if stored_key.lower() == key_lower:
                return c, entry

    # Daarna gedeeltelijke match
    for c in categories:

        for stored_key, entry in memory.get(c, {}).items():

            stored = stored_key.lower()

            if key_lower in stored or stored in key_lower:
                return c, entry

    return None, None


def remember(key, value, category=None, source="conversation", explicit=False):
    """
    Slaat een feit op als entry met metadata.

    Geeft een dict terug met de uitkomst:
        changed   : er stond een andere waarde
        conflict  : er stond een andere waarde én er is geen expliciete
                    correctie ("onthoud", "wijzig")
        previous  : de oude waarde (of None)
        category  : waarin de waarde is opgeslagen
        corrected : expliciete correctie (update_memory)

    Voor niet-expliciete wijzigingen die een conflict opleveren kan de
    aanroeper (brain) ervoor kiezen om eerst bevestiging te vragen.
    """

    memory = load_memory()

    category = category or get_category(key, str(value))

    if category not in memory:
        memory[category] = {}

    memory.setdefault(category, {})

    existing = memory[category].get(key)

    old = _unwrap(existing) if existing is not None else None

    conflict = old is not None and str(old) != str(value)

    previous_value = old if conflict else None

    entry = _wrap(value)
    entry["source"] = source
    entry["updated"] = _now()

    if previous_value is not None:
        entry["previous_value"] = previous_value

    if explicit:
        entry["corrected"] = True
        entry["conflict"] = False
    else:
        entry["conflict"] = conflict

    memory[category][key] = entry

    save_memory(memory)

    return {
        "changed": conflict,
        "conflict": conflict and not explicit,
        "previous": str(previous_value) if previous_value is not None else None,
        "category": category,
        "corrected": bool(explicit),
    }


def update_memory(key, value, category=None, source="user"):
    """
    Expliciete correctie van een onthouden feit.
    "wijzig mijn favoriete kleur naar blauw" → wordt bijgewerkt en
    gemarkeerd als corrected, met de oude waarde bewaard.
    """

    return remember(key, value, category=category, source=source, explicit=True)


def touch_usage(key, category=None):
    """
    Verhoogt usage_count en zet last_used (voor relevante-feiten-score).
    """

    memory = load_memory()

    key_lower = key.lower().strip()

    categories = [category] if category else DEFAULT_CATEGORIES

    for c in categories:

        for stored_key, entry in memory.get(c, {}).items():

            stored = stored_key.lower()

            if stored == key_lower or key_lower in stored or stored in key_lower:

                if isinstance(entry, dict):
                    entry["usage_count"] = int(entry.get("usage_count") or 0) + 1
                    entry["last_used"] = _now()
                    save_memory(memory)
                    return True

    return False


def recall(key, category=None):

    entry = get_entry(key, category)

    return _unwrap(entry) if entry is not None else None


def forget(key):

    memory = load_memory()

    key_lower = key.lower().strip()

    # Zowel "favoriete game" als "favoriete_game" als "game" laten matchen
    candidates = [key_lower, key_lower.replace(" ", "_")]

    for candidate in candidates:

        for category in DEFAULT_CATEGORIES:

            for stored_key in list(memory.get(category, {}).keys()):

                stored = stored_key.lower()

                if stored == candidate or candidate in stored or stored in candidate:

                    del memory[category][stored_key]
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


def _tokens(text):

    return set(re.findall(r"[a-z0-9]+", text.lower()))


def relevance_score(question, category, key, value):
    """
    Bepaalt hoe relevant een opgeslagen feit is voor een vraag,
    zonder LLM (deterministisch):

      - exacte sleutel in de vraag      (+5)
      - sleutelwoord-overlap            (+2 per woord)
      - waarde-overlap                  (+1,5 per woord)
      - categorie-trefwoorden in vraag  (+1 per trefwoord)
    """

    q = question.lower()

    tokens_q = _tokens(q)
    tokens_k = _tokens(key)
    tokens_v = _tokens(str(value))

    score = 0

    if key.lower() in q:
        score += 5

    score += 2 * len(tokens_k & tokens_q)
    score += int(1.5 * len(tokens_v & tokens_q))

    for word in CATEGORY_KEYWORDS.get(category, []):
        if word in q:
            score += 1

    return score


def get_relevant_memory(question, max_items=6):
    """
    Geeft de meest relevante geheugenfeiten voor een vraag terug.

    Elke entry: {'category', 'key', 'value', 'score'}, aflopend op
    score. Alleen feiten met score > 0.
    """

    memory = load_memory()

    candidates = []

    for category in DEFAULT_CATEGORIES:

        for key, entry in memory.get(category, {}).items():

            value = _unwrap(entry)

            score = relevance_score(question, category, key, value)

            if score > 0:
                candidates.append({
                    "category": category,
                    "key": key,
                    "value": value,
                    "score": score,
                    "usage_count": entry.get("usage_count", 0) if _is_entry(entry) else 0,
                })

    candidates.sort(key=lambda item: (item["score"], item["usage_count"]), reverse=True)

    return candidates[:max_items]


def relevant_memory_prompt(question, max_items=6):
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