"""Privacy-poort (Fase 25, M3): wat mag naar Gemini, en wat blijft lokaal.

Besluit 2026-10-28/30: Gemini doet het meeste werk, maar persoonlijke data
gaat nooit naar de cloud. Gemini krijgt alleen de vraag zelf, de naam en de
aanspreekvorm. Nooit: mail, agenda, DM's, het geheugen over u, bestanden,
het scherm, eerdere (lokale) gesprekken, locatie en reistijden.

Twee lagen:

1. :func:`beslis` kijkt vóóraf naar de vraag. Gaat die over iets
   persoonlijks (mail, agenda, bestanden, "wat is mijn …", uw woonplaats),
   dan doet Ollama het lokaal. Bij twijfel ook.
2. :func:`controleer` kijkt vlak vóór verzending naar het hele verzoek: geen
   geheugenblok, geen e-mailadres of bestandspad, geen gevoelige
   geheugenwaarde (woonplaats, adres, school, …), geen toolresultaat en
   alleen bedien-tools. Faalt dat, dan gaat er niets weg (``core/llm.py``).

Verder bewaart deze module de enige geschiedenis die Gemini krijgt: eerdere
beurten die zelf al via de poort naar Gemini gingen.
"""

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Besluit:
    cloud: bool
    reden: str = ""


# ---------------------------------------------------------------------
# 1. Vooraf: gaat de vraag over iets persoonlijks?
# ---------------------------------------------------------------------

_PERSOONLIJK = (
    (r"\b(e-?mails?|mailtje|inbox|gmail|postvak|mail)\b", "mail"),
    (r"\b(agenda|afspraak|afspraken|kalender|deadlines?|planning)\b", "agenda"),
    (r"\b(dm|dms|discord-?berichten?|berichtje|berichten|whatsapp|appje|stuurde)\b", "berichten"),
    (r"\b(bestand|bestanden|mapje|map|mappen|document|documenten|downloads|bureaublad|"
     r"foto|foto's|fotos|prullenbak|screenshot|schermafbeelding)\b", "bestanden"),
    (r"[a-z]:\\|\.(pdf|docx?|xlsx?|pptx?|txt|csv|jpe?g|png|mp4|zip)\b", "bestanden"),
    (r"\b(scherm|wat zie je|wat staat er op)\b", "scherm"),
    (r"\b(onthoud|onthouden|vergeet|vergeten|weet je nog|herinner je|geheugen|over mij|van mij)\b", "geheugen"),
    (r"\bwat (is|zijn|was|waren) mijn\b", "geheugen"),
    (r"\b(wie ben ik|hoe heet ik|hoe oud ben ik|waar woon ik|wat doe ik|wat weet je)\b", "geheugen"),
    (r"\bik (woon|werk|studeer|heet|ben geboren|ben \d+|zit op)\b", "persoonlijk feit"),
    # Vragen over uzelf ("waar werk ik", "welke opleiding doe ik"): het
    # antwoord staat alleen in het lokale geheugen.
    (r"\b(ben|heb|woon|werk|studeer|doe|speel|hou|houd|heet|zit) ik\b", "geheugen"),
    (r"\b(jarig|verjaardag|geboren)\b", "geheugen"),
    (r"\b(wat zei ik|wat vroeg ik|vorige keer|eerder vandaag|ons gesprek|vorige vraag)\b", "geschiedenis"),
    (r"\b(waar ben ik|in de buurt|bij mij in de buurt|naar huis|thuis|reistijd|moet ik weg|"
     r"vertrekken|route naar|mijn locatie|hier in de buurt)\b", "locatie"),
)
_PERSOONLIJK = tuple((re.compile(p), reden) for p, reden in _PERSOONLIJK)

# "mijn …" is persoonlijk, behalve bij iets dat JARVIS gewoon bedient.
_MIJN = re.compile(r"\bmijn\s+(\w+)")
_BEDIENBAAR = frozenset([
    "lamp", "lampen", "lampje", "licht", "lichten", "tv", "televisie", "pc",
    "computer", "laptop", "game-pc", "gamepc", "muziek", "volume", "geluid",
    "spotify", "discord", "steam", "speaker", "speakers", "koptelefoon",
    "headset", "game", "games", "browser", "chrome", "woonkamer",
    "slaapkamer", "kamer", "ledstrip", "gordijnen", "stekker",
])

# Altijd persoonlijk, waar het ook staat.
_GEGEVENS = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                 # e-mailadres
    re.compile(r"\b\d{4}\s?[a-z]{2}\b"),                    # postcode
    re.compile(r"(\+31|\b0)[\s-]?6[\s-]?\d{8}\b"),          # mobiel nummer
    re.compile(r"\bnl\d{2}[a-z]{4}\d{10}\b"),               # IBAN
)

# Geheugensleutels waarvan de waarde nooit naar de cloud mag (woonplaats,
# adres, school, ...). Een favoriete game of muziekstijl is niet gevoelig.
_GEVOELIGE_SLEUTEL = re.compile(
    r"woon|adres|postcode|plaats|stad|straat|telefoon|nummer|mail|school|"
    r"opleiding|stage|werk|baan|geboort|verjaardag|leeftijd|familie|moeder|"
    r"vader|broer|zus|vriend|partner|wachtwoord|locatie|thuis"
)

_waarden_cache = {"tijd": 0.0, "waarden": ()}
_WAARDEN_TTL = 60.0


def _norm(tekst):
    return " ".join(str(tekst or "").lower().split())


def gevoelige_waarden():
    """Gevoelige waarden uit het geheugen en de instellingen (genormaliseerd)."""

    nu = time.monotonic()
    if nu - _waarden_cache["tijd"] < _WAARDEN_TTL:
        return _waarden_cache["waarden"]
    waarden = set()
    try:
        from memory.memory import get_all_memory

        for sleutel, waarde in (get_all_memory() or {}).items():
            sleutel = str(sleutel).lower()
            if _GEVOELIGE_SLEUTEL.search(sleutel):
                waarden.update(_waarde_delen(waarde, woorden=bool(_PLAATS_SLEUTEL.search(sleutel))))
    except Exception:
        logger.debug("Geheugen lezen voor de privacy-poort mislukt", exc_info=True)
    try:
        from config import THUIS_ADRES

        waarden.update(_waarde_delen(THUIS_ADRES, woorden=True))
    except Exception:
        pass
    # De naam mag mee (besluit 2026-10-28), ook als hij in een e-mailadres
    # of andere waarde staat.
    waarden -= _naam_woorden()
    _waarden_cache.update(tijd=nu, waarden=tuple(sorted(waarden)))
    return _waarden_cache["waarden"]


# Alleen bij een plaats of straat telt ook elk los woord ("Badhoevedorp" uit
# "Pruimenlaan 17, Badhoevedorp"). Bij school, werk, e-mail of verjaardag
# alleen de hele waarde: anders blokkeren woorden als "niveau", "maart" of
# de eigen naam (uit een e-mailadres) alles (bewijstest M4, 2026-10-30).
_PLAATS_SLEUTEL = re.compile(r"woon|adres|plaats|stad|straat|postcode|thuis|locatie")


def _naam_woorden():
    try:
        from config import USER_NAME
    except Exception:
        return set()
    return {w for w in re.findall(r"[\w'-]+", _norm(USER_NAME)) if w}


def _waarde_delen(waarde, woorden=False):
    """De waarde zelf, en bij ``woorden`` ook de losse woorden (vanaf 4 letters)."""

    if isinstance(waarde, dict):
        waarde = waarde.get("value", "")
    if isinstance(waarde, (list, tuple)):
        delen = set()
        for w in waarde:
            delen.update(_waarde_delen(w, woorden))
        return delen
    tekst = _norm(waarde)
    if len(tekst) < 4:
        return set()
    delen = {tekst}
    if woorden:
        delen.update(w for w in re.findall(r"[\w'-]+", tekst) if len(w) >= 4 and not w.isdigit())
    return delen


def _bevat_waarde(tekst, waarden):
    t = _norm(tekst)
    for waarde in waarden:
        if re.search(rf"(?<!\w){re.escape(waarde)}(?!\w)", t):
            return waarde
    return None


def naar_cloud(vraag):
    """True als deze vraag nu naar Gemini gaat: Gemini is beschikbaar
    (sleutel, geen pauze) én de poort laat de vraag toe. Zonder Gemini
    loopt alles precies zoals vóór Fase 25."""

    from core import llm

    return llm.gemini_beschikbaar() and beslis(vraag).cloud


def beslis(vraag):
    """Mag deze vraag naar Gemini? :class:`Besluit` met de reden."""

    t = _norm(vraag)
    if not t:
        return Besluit(False, "lege vraag")
    for patroon, reden in _PERSOONLIJK:
        if patroon.search(t):
            return Besluit(False, reden)
    for match in _MIJN.finditer(t):
        if match.group(1) not in _BEDIENBAAR:
            return Besluit(False, f"persoonlijk ('mijn {match.group(1)}')")
    for patroon in _GEGEVENS:
        if patroon.search(t):
            return Besluit(False, "persoonsgegevens")
    if _bevat_waarde(t, gevoelige_waarden()):
        return Besluit(False, "gevoelige geheugenwaarde")
    return Besluit(True)


# ---------------------------------------------------------------------
# 2. Vlak voor verzending: het hele verzoek nakijken
# ---------------------------------------------------------------------

# Alleen bedien-tools: de keuze komt uit de vraag, het resultaat blijft
# lokaal. Lees-tools (bestanden, scherm, geheugen, mail, DM's) nooit.
CLOUD_TOOLS = frozenset([
    "open_program", "close_program", "restart_program", "program_status",
    "find_program_location", "open_website", "browser_back", "browser_forward",
    "browser_refresh", "browser_new_tab", "browser_close_tab", "browser_search",
    "media_play_pause", "media_next", "media_previous", "media_stop", "media_mute",
    "media_pause_app", "set_volume", "volume_up", "volume_down",
    "audio_get_default_output", "audio_list_outputs", "audio_list_sessions",
    "audio_get_session_volume", "audio_set_session_volume", "audio_set_session_mute",
    "audio_toggle_session_mute", "audio_set_default_output",
    "control_home_assistant", "get_home_assistant_entities",
    "maximize_window", "minimize_window", "restore_window", "ui_launch_app",
    "game_start", "game_lijst", "spotify_open", "power", "pc_status", "system_info",
    "show_notification", "web_search", "web_fetch", "web_search_and_fetch",
])
CLOUD_TOOLS = CLOUD_TOOLS | frozenset(
    "game_pc_" + naam for naam in CLOUD_TOOLS
) | frozenset(["game_pc_media", "game_pc_status", "game_pc_telemetry", "game_pc_game_start", "game_pc_game_lijst"])

# Kopregels van het lokale context- en geheugenblok: staat er zo'n kop aan
# het begin van een regel, dan is er per ongeluk iets lokaals meegegaan. Een
# vermelding in een instructie ('uit het blok "JARVIS-CONTEXT EN GEHEUGEN"')
# telt niet: dat is geen data.
_VERBODEN_KOP = re.compile(
    r"^\s*(JARVIS-CONTEXT EN GEHEUGEN|ACTUELE JARVIS-CONTEXT|JARVIS-GEHEUGEN \(|"
    r"\d\. DIT GESPREK \(|\d\. RECENTE GESPREK|PERMANENT GEHEUGEN|LANGETERMIJNGEHEUGEN)",
    re.MULTILINE,
)
_PAD = re.compile(r"\b[a-z]:\\|\\users\\", re.IGNORECASE)


def _tool_naam(tool):
    if not isinstance(tool, dict):
        return ""
    return str((tool.get("function") or tool).get("name") or "")


def cloud_tools(tools):
    """Alleen de tools die Gemini mag kiezen."""

    return [t for t in tools or [] if _tool_naam(t) in CLOUD_TOOLS]


def _inhoud(bericht):
    if isinstance(bericht, dict):
        return bericht.get("role"), str(bericht.get("content") or "")
    return getattr(bericht, "role", None), str(getattr(bericht, "content", "") or "")


def controleer(messages, tools=None):
    """(True, "") als dit verzoek naar Gemini mag, anders (False, reden)."""

    waarden = gevoelige_waarden()
    for bericht in messages or []:
        rol, inhoud = _inhoud(bericht)
        if rol not in ("system", "user", "assistant"):
            return False, f"rol {rol!r}"
        kop = _VERBODEN_KOP.search(inhoud)
        if kop:
            return False, f"lokaal contextblok ({kop.group(1).strip()})"
        if _PAD.search(inhoud):
            return False, "bestandspad"
        for patroon in _GEGEVENS[:1]:  # e-mailadres (de rest kan in gewone tekst staan)
            if patroon.search(inhoud):
                return False, "e-mailadres"
        waarde = _bevat_waarde(inhoud, waarden)
        if waarde:
            return False, "gevoelige geheugenwaarde"
    for tool in tools or []:
        naam = _tool_naam(tool)
        if naam not in CLOUD_TOOLS:
            return False, f"tool {naam!r} mag niet naar de cloud"
        # Ook de beschrijving: een tool met live gegevens erin (namen,
        # paden) mag niet ongemerkt meegaan.
        beschrijving = repr(tool)
        if _PAD.search(beschrijving) or _bevat_waarde(beschrijving, waarden):
            return False, f"tool {naam!r} bevat persoonlijke gegevens"
    return True, ""


# ---------------------------------------------------------------------
# Wat Gemini over de gebruiker en het gesprek krijgt
# ---------------------------------------------------------------------

def persona():
    """Het enige over de gebruiker: naam en aanspreekvorm."""

    try:
        from config import USER_NAME
    except Exception:
        USER_NAME = "de gebruiker"
    return (
        f"Je bent JARVIS, de persoonlijke assistent van {USER_NAME}. Spreek hem "
        "formeel aan met 'u' en af en toe 'sir', droog en kalm zoals de JARVIS "
        "uit de film. Antwoord in gewone Nederlandse spreektaal (tenzij hij om "
        "een andere taal vraagt) en houd het kort: één of twee zinnen, want je "
        "antwoord wordt uitgesproken. Gebruik geen Markdown, opsommingstekens of "
        "emoji. Je weet verder niets persoonlijks over hem en verzint dat ook niet."
    )


# Alleen beurten die zelf al naar Gemini gingen (besluit 2026-10-30).
MAX_CLOUD_BEURTEN = 6
CLOUD_GESCHIEDENIS_TTL = 15 * 60

_geschiedenis_lock = threading.Lock()
_geschiedenis = deque(maxlen=MAX_CLOUD_BEURTEN)
_laatst = {"tijd": 0.0}


def onthoud_cloud_beurt(vraag, antwoord):
    """Bewaar een beurt die via Gemini ging, voor vervolgvragen."""

    vraag, antwoord = str(vraag or "").strip(), str(antwoord or "").strip()
    if not vraag or not antwoord:
        return
    with _geschiedenis_lock:
        _geschiedenis.append((vraag, antwoord))
        _laatst["tijd"] = time.monotonic()


def cloud_geschiedenis():
    """De eerdere Gemini-beurten als berichten (leeg na 15 min stilte)."""

    with _geschiedenis_lock:
        if time.monotonic() - _laatst["tijd"] > CLOUD_GESCHIEDENIS_TTL:
            _geschiedenis.clear()
        beurten = list(_geschiedenis)
    berichten = []
    for vraag, antwoord in beurten:
        berichten.append({"role": "user", "content": vraag})
        berichten.append({"role": "assistant", "content": antwoord})
    return berichten


def wis_cloud_geschiedenis():
    with _geschiedenis_lock:
        _geschiedenis.clear()
        _laatst["tijd"] = 0.0


def laatste_programma_regel(vraag, laatste_programma):
    """Bij "sluit hem": alleen de programmanaam, verder niets uit de context."""

    if not laatste_programma:
        return None
    if not re.search(r"\b(hem|het|die|dat|opnieuw|nog een keer|hetzelfde)\b", _norm(vraag)):
        return None
    naam = str(laatste_programma).strip()
    if not naam or _PAD.search(naam) or len(naam) > 60:
        return None
    return {"role": "system", "content": f"Laatste programma in dit gesprek: {naam}"}


def cloud_berichten(vraag, instructies="", extra_systeem=None, laatste_programma=None):
    """Het complete Gemini-verzoek: persona (+ instructies), eerdere
    Gemini-beurten, eventueel de laatste programmanaam, en de vraag."""

    systeem = (instructies or "") + persona()
    if extra_systeem:
        systeem += "\n\n" + extra_systeem
    berichten = [{"role": "system", "content": systeem}]
    berichten.extend(cloud_geschiedenis())
    regel = laatste_programma_regel(vraag, laatste_programma)
    if regel:
        berichten.append(regel)
    berichten.append({"role": "user", "content": str(vraag)})
    return berichten


def _reset():
    """Voor tests."""

    wis_cloud_geschiedenis()
    _waarden_cache.update(tijd=0.0, waarden=())
