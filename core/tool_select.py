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

# Vraag zonder duidelijke categorie -> deze categorieën (max. MAX_TOOLS).
FALLBACK_CATEGORIES = ("pc", "ui", "systeem")

# Als categorieën even goed passen, wint de eerste uit deze lijst.
PRIORITY = ("remote", "ha", "media", "web", "pc", "bestanden", "ui", "geheugen", "systeem")

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
        "media_pause_app",
        "spotify_open",
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
        "recycle_file",
        "empty_recycle_bin",
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
    "remote": (
        "game_pc_open_program",
        "game_pc_close_program",
        "game_pc_restart_program",
        "game_pc_program_status",
        "game_pc_status",
        "game_pc_telemetry",
        "game_pc_screenshot",
        "game_pc_media",
        "game_pc_set_volume",
        # Fase 15B - bestanden op de game-pc
        "game_pc_list_files",
        "game_pc_open_folder",
        "game_pc_open_file",
        "game_pc_search_files",
        "game_pc_recent_files",
        "game_pc_create_folder",
        "game_pc_create_file",
        "game_pc_copy_file",
        "game_pc_move_file",
        "game_pc_rename_file",
        # Fase 15B - scherm op de game-pc
        "game_pc_ui_list_windows",
        "game_pc_ui_find_window",
        "game_pc_ui_activate_window",
        "game_pc_ui_list_elements",
        "game_pc_ui_find_element",
        "game_pc_ui_click_element",
        "game_pc_ui_type_text",
        "game_pc_ui_get_value",
        "game_pc_ui_set_value",
        "game_pc_ui_launch_app",
        # Fase 15B - verwijderen + power op de game-pc
        "game_pc_recycle_file",
        "game_pc_empty_recycle_bin",
        "game_pc_power",
        # Taak F - vensters, systeeminfo, audio per app, browser & websites
        "game_pc_find_program_location",
        "game_pc_minimize_window",
        "game_pc_maximize_window",
        "game_pc_restore_window",
        "game_pc_system_info",
        "game_pc_audio_list_sessions",
        "game_pc_audio_get_session_volume",
        "game_pc_audio_set_session_volume",
        "game_pc_audio_set_session_mute",
        "game_pc_audio_toggle_session_mute",
        "game_pc_media_pause_app",
        "game_pc_spotify_open",
        "game_pc_audio_list_outputs",
        "game_pc_audio_get_default_output",
        "game_pc_audio_set_default_output",
        "game_pc_open_website",
        "game_pc_browser_search",
        "game_pc_browser_back",
        "game_pc_browser_forward",
        "game_pc_browser_refresh",
        "game_pc_browser_new_tab",
        "game_pc_browser_close_tab",
        "game_pc_show_notification",
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
        "power",
        "show_notification",
    ),
}

# Woorden die een categorie activeren. Alles wordt in kleine letters
# vergeleken; match op woordgrens (behalve Home Assistant, zie boven).
CATEGORY_WORDS = {
    "remote": (
        "game-pc", "gamepc", "game pc",
        "gaming-pc", "gamingpc", "gaming pc",
        "spelcomputer", "spel-pc", "spel pc",
        "gamecomputer", "game computer",
    ),
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
        "klik", "klikken", "klikt", "tik", "typ", "typen", "type",
        "selecteer", "kladblok", "notepad", "invoeren", "formulier",
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
        "verwijder",
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
        "status", "pc status", "prestaties", "belasting",
        # stroomacties (Fase 15B)
        "afsluiten", "afsluit", "sluimerstand", "slaapstand",
        "hibernatie", "vergrendelen", "vergrendel", "uitloggen", "stroom",
        # Telemetrie & power-nabijheid (Fase 15)
        "uit", "warm", "warmte", "vram", "belast", "belasting",
    ),
}

# Woorden die alleen meetellen in combinatie met een ander woord.
# "temperatuur" hoort bij Home Assistant, behalve bij een pc/cpu-vraag;
# dan is het een systeemvraag.
CONDITIONAL_WORDS = {
    "systeem": (
        ("temperatuur", ("pc", "cpu")),
    ),
}

# Een paar tools krijgen voorrang in de selectie, zodat ze niet door de
# MAX_TOOLS-cap worden afgekapt. Zonder dit zou "verwijder bestand oud"
# recycle_file nooit bereiken: die staat als 11e in de bestandenlijst.
VOORRANG_TOOLS = (
    ("verwijder", "recycle_file"),
    ("prullenbak", "empty_recycle_bin"),
    ("leeg", "empty_recycle_bin"),
)


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

    # Woorden die alleen tellen samen met een ander woord (bijv. temperatuur).
    for name, rules in CONDITIONAL_WORDS.items():
        strong, weak = scores[name]
        for word, requires in rules:
            word_present = re.search(rf"\b{re.escape(word)}\b", question_lower)
            if word_present and any(
                re.search(rf"\b{re.escape(req)}\b", question_lower)
                for req in requires
            ):
                strong += 1
        scores[name] = (strong, weak)

    return scores


def _chosen_categories(question_lower):
    """De passende categorieën (max. twee; bij twijfel de fallback)."""
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

    # Voorrangstools eerst, zodat ze niet buiten MAX_TOOLS vallen.
    for woord, tool in VOORRANG_TOOLS:
        if re.search(rf"\b{re.escape(woord)}\b", question_lower):
            wanted.append(tool)

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
