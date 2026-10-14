"""Kies per vraag een kleine, passende set tools voor het LLM.

De volledige toollijst van JARVIS is ~65 tools (ongeveer 8.000-10.000
tokens aan toolbeschrijvingen). Dat past niet in de context
(``AI_NUM_CTX``) en qwen2.5:3b kiest bij zo'n lange lijst vaak de
verkeerde tool of ziet de tools helemaal niet meer.

Daarom sturen we het model per vraag alleen:

- een kleine **basisset** (``remember``, ``recall``, ``system_info``), en
- maximaal **twee** categorieën die bij de vraag passen.

Zo blijft het aantal tools beperkt tot ``MAX_TOOLS`` (12) en houdt het
model de beschrijvingen echt binnen de context. Dit vervangt de oude
HA-subset in ``core/ai.py`` en werkt voor álle vragen, niet alleen
Home Assistant-vragen.

Woorden worden op woordgrens gematcht. Home Assistant is een uitzondering:
daar telt een HA-woord ook als het ín een langer woord zit (zoals
"bedlamp"), zodat spraakvarianten blijven werken — maar zo'n match weegt
lichter dan een echte woord-match, zodat "spotify" niet per ongeluk als
HA-"spot" wordt gezien.
"""
import re

from core.home_assistant import HA_DEVICE_WORDS

# Altijd meegestuurd: geheugen + systeeminformatie.
BASE_TOOLS = ("remember", "recall", "system_info")

# Harde bovengrens: nooit meer dan zoveel tools naar het model.
MAX_TOOLS = 12

# Vraag zonder duidelijke categorie -> deze twee categorieën.
FALLBACK_CATEGORIES = ("pc", "bestanden")

# Als categorieën even goed passen, wint de eerste uit deze lijst.
PRIORITY = ("ha", "media", "web", "pc", "bestanden", "ui", "geheugen", "systeem")

# Per categorie de tools, op volgorde van belangrijkheid. De volgorde
# bepaalt welke tools als eerste in de set komen (en dus overblijven als
# de set de grens van MAX_TOOLS raakt).
CATEGORIES = {
    "pc": (
        "open_program",
        "close_program",
        "restart_program",
        "program_status",
        "find_program_location",
        "minimize_window",
        "maximize_window",
        "restore_window",
    ),
    "ui": (
        "ui_launch_app",
        "ui_find_window",
        "ui_find_element",
        "ui_list_elements",
        "ui_click_element",
        "ui_type_text",
        "ui_set_value",
        "ui_get_value",
        "ui_activate_window",
        "ui_list_windows",
    ),
    "media": (
        "media_play_pause",
        "media_stop",
        "media_next",
        "media_previous",
        "set_volume",
        "volume_up",
        "volume_down",
        "media_mute",
        "audio_set_session_volume",
        "audio_set_session_mute",
        "audio_toggle_session_mute",
        "audio_list_sessions",
        "audio_get_session_volume",
        "audio_set_default_output",
        "audio_list_outputs",
        "audio_get_default_output",
    ),
    "bestanden": (
        "open_file",
        "open_folder",
        "list_files",
        "search_files",
        "recent_files",
        "create_folder",
        "create_file",
        "copy_file",
        "move_file",
        "rename_file",
    ),
    "web": (
        "open_website",
        "web_fetch",
        "web_search_and_fetch",
        "web_search",
        "browser_search",
        "browser_get_content",
        "browser_get_url",
        "browser_get_title",
        "browser_back",
        "browser_forward",
        "browser_refresh",
        "browser_new_tab",
        "browser_close_tab",
    ),
    "ha": (
        "control_home_assistant",
        "get_home_assistant_entities",
    ),
    "geheugen": (
        "remember",
        "recall",
        "forget",
    ),
    "systeem": (
        "system_info",
        "pc_status",
        "screenshot",
    ),
}

# Woorden die een categorie activeren. Alles wordt in kleine letters
# vergeleken; match op woordgrens (behalve Home Assistant, zie boven).
CATEGORY_WORDS = {
    "pc": (
        "programma", "programma's", "applicatie", "applicaties", "app", "apps",
        "open", "opent", "sluit", "sluiten", "start", "starten",
        "herstart", "herstarten",
        "venster", "vensters", "window", "minimaliseer", "maximaliseer",
        "vergroot", "verklein", "kleiner", "groter", "herstel",
        "draait", "draaien",
        "spotify", "discord", "steam", "chrome", "firefox", "edge",
        "netflix", "obs", "excel", "word", "vlc",
    ),
    "ui": (
        "knop", "knoppen", "veld", "velden", "slider", "schuifbalk",
        "invullen", "aanklikken", "aanvinken", "vakje", "venster",
        "interface", "uia", "automatisering",
    ),
    "media": (
        "muziek", "nummer", "nummers", "liedje", "liedjes", "playlist",
        "afspelen", "speel", "speelt", "pauzeer", "pauze", "play",
        "stop", "stoppen", "volgende", "vorige",
        "volume", "geluid", "audio", "dempen", "mute", "harder",
        "zachter", "luider",
        "speaker", "speakers", "hoofdtelefoon", "koptelefoon", "headset",
        "output", "sonar",
        "spotify", "discord", "steam", "chrome", "firefox", "edge",
        "netflix", "vlc",
    ),
    "bestanden": (
        "bestand", "bestanden", "document", "documenten", "foto", "foto's",
        "map", "mappen", "folder", "folders", "mapje",
        "verplaats", "kopieer", "kopiëren", "hernoem", "hernoemen",
        "zoek", "zoeken", "recent", "recente",
        "prullenbak", "download", "downloads", "bureaublad",
    ),
    "web": (
        "website", "websites", "site", "url", "browser", "internet", "web",
        "google", "youtube", "pagina", "tabblad", "tabbladen",
        "link", "links", "opzoeken", "opzoek",
        "wikipedia", "nieuws", "weer",
    ),
    "ha": tuple(HA_DEVICE_WORDS),
    "geheugen": (
        "onthoud", "onthouden", "vergeet", "vergeten",
        "herinner", "herinneren", "weet je nog",
    ),
    "systeem": (
        "cpu", "ram", "gpu", "geheugen", "schijf", "disk",
        "systeem", "systeeminformatie", "besturingssysteem",
        "screenshot", "schermafbeelding", "screen", "proces", "processen",
    ),
}


def _scores(question_lower):
    """Per categorie (sterke, zwakke) treffers.

    Sterk = het woord staat als los woord in de vraag. Zwak = het woord
    zit ín een langer woord; dat geldt alleen voor Home Assistant, zodat
    "bedlamp" en "lampa" meetellen maar "spotify" niet als HA-"spot".
    """
    scores = {}
    for name, words in CATEGORY_WORDS.items():
        strong = 0
        weak = 0
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", question_lower):
                strong += 1
            elif name == "ha" and word in question_lower:
                weak += 1
        scores[name] = (strong, weak)
    return scores


def _chosen_categories(question_lower):
    """De (maximaal twee) categorieën die het beste bij de vraag passen."""
    scores = _scores(question_lower)
    order = list(PRIORITY)
    matched = [
        name
        for name in order
        if scores.get(name, (0, 0))[0] > 0 or scores.get(name, (0, 0))[1] > 0
    ]

    if not matched:
        return list(FALLBACK_CATEGORIES)

    matched.sort(
        key=lambda name: (
            -scores[name][0],
            -scores[name][1],
            order.index(name),
        )
    )
    return matched[:2]


def select_tools(question, all_tools):
    """Kies de tools die bij ``question`` horen (max. ``MAX_TOOLS``).

    ``all_tools`` is de volledige lijst toolschema's. Geeft een subset
    terug: altijd de basisset plus de tools van maximaal twee passende
    categorieën. Nooit alle 65 tools.
    """
    available = {}
    for tool in all_tools or []:
        name = tool.get("function", {}).get("name")
        if name:
            available[name] = tool

    question_lower = (question or "").lower()

    wanted = list(BASE_TOOLS)
    for category in _chosen_categories(question_lower):
        wanted.extend(CATEGORIES.get(category, ()))

    selected = []
    seen = set()
    for name in wanted:
        if name in seen or name not in available:
            continue
        seen.add(name)
        selected.append(available[name])
        if len(selected) >= MAX_TOOLS:
            break

    return selected
