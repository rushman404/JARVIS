import json
import os


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
    ],
}


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
            structured[category][key] = value

        return structured

    # Zorg dat alle categorieën bestaan
    for category in DEFAULT_CATEGORIES:
        if category not in data or not isinstance(data[category], dict):
            data[category] = {}

    return data


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
    check_order = ["pc", "muziek", "projecten", "voorkeuren"]

    for category in check_order:

        if any(word in text for word in CATEGORY_KEYWORDS[category]):
            return category

    return "algemeen"


def remember(key, value, category=None):

    memory = load_memory()

    category = category or get_category(key, value)

    if category not in memory:
        memory[category] = {}

    memory[category][key] = value

    save_memory(memory)

    return True


def recall(key):

    memory = load_memory()

    key_lower = key.lower().strip()

    # Eerst exact zoeken in alle categorieën
    for category in DEFAULT_CATEGORIES:

        for stored_key, value in memory.get(category, {}).items():

            if stored_key.lower() == key_lower:
                return value

    # Daarna gedeeltelijke match
    for category in DEFAULT_CATEGORIES:

        for stored_key, value in memory.get(category, {}).items():

            stored = stored_key.lower()

            if key_lower in stored or stored in key_lower:
                return value

    return None


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

        for key, value in memory.get(category, {}).items():
            result[key] = value

    return result


def get_category_memory(category):

    memory = load_memory()

    return dict(memory.get(category, {}))


def get_categories_with_content():

    memory = load_memory()

    return {
        category: dict(items)
        for category in DEFAULT_CATEGORIES
        for items in [memory.get(category, {})]
        if items
    }


def memory_summary():

    memory = load_memory()

    parts = []

    for category in DEFAULT_CATEGORIES:

        items = memory.get(category, {})

        if not items:
            continue

        lines = [f"{key.replace('_', ' ')} is {beautify(value)}" for key, value in items.items()]

        parts.append(f"{category}: {', '.join(lines)}")

    if not parts:
        return "Ik heb nog niets onthouden."

    return "; ".join(parts)
