"""Gegevensbronnen voor de dashboard-tegels (Fase 18, M4).

Hier staat alles wat het dashboard uit de rest van JARVIS haalt of daar
aanstuurt: auditlog, gesprek, media, slim huis, weer en pc-meters.

Ontwerpregels
-------------
* **Dezelfde weg als de stem.** Bediening (media, lampen) loopt via
  ``core.ai.execute_tool``: dezelfde bewaakte poort, hetzelfde risico,
  dezelfde PC_TARGET-routering naar de game-pc. Een medium/high-actie
  wordt dus nooit stil uitgevoerd maar krijgt een goedkeuring (overlay).
* **Vaste lijsten.** Alleen lampen uit ``config/ha_aliases.json`` en
  scènes uit ``config/ha_scenes.json`` zijn tikbaar; een entity_id of
  scènenaam van buiten die lijsten wordt geweigerd.
* **Niet hameren.** Trage bronnen (HA, telemetrie, weer, media op de
  game-pc) hebben een korte cache.
* **Nooit crashen.** Een kapotte bron geeft ``beschikbaar: False`` en een
  korte melding, geen exception.
* **Testbaar.** Elke aanroep naar buiten is injecteerbaar.
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime

logger = logging.getLogger("jarvis.dashboard.bronnen")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIASES_FILE = os.path.join(PROJECT, "config", "ha_aliases.json")
SCENES_FILE = os.path.join(PROJECT, "config", "ha_scenes.json")

# Apps waarvan het dashboard het volume toont (zoals in de wireframe).
# Apps waarvan het dashboard het volume toont en met een schuif bedient.
MEDIA_APPS = ("Spotify",)

# Media-acties van het dashboard -> tools van JARVIS.
MEDIA_ACTIES = {
    "play_pauze": "media_play_pause",
    "volgende": "media_next",
    "vorige": "media_previous",
    "stop": "media_stop",
    "dempen": "media_mute",
}

# Cachetijden (seconden). Media en meters van de game-pc gaan via de
# game-pc-agent, die 60 verzoeken per minuut per IP toestaat; het dashboard
# mag die ruimte niet opsouperen, anders worden gesproken opdrachten naar de
# game-pc geweigerd (429). Media = 2 verzoeken per 15 s, meters 1 per 10 s.
TTL_MEDIA = 15
TTL_HA = 5
TTL_PC = 10
TTL_WEER = 600

# Auditlog: zoveel regels tonen en zoveel bytes van het einde lezen.
AUDIT_REGELS = 6
AUDIT_LEES_BYTES = 64 * 1024

# Gesprek: zoveel beurten tonen.
GESPREK_BEURTEN = 6

# Drempels voor de meters (design §7.4): balk oranje erboven.
DREMPEL_CPU = 80
DREMPEL_RAM = 80
DREMPEL_GPU_TEMP = 75

DOEL_LOKAAL = "local"
DOEL_GAME_PC = "game-pc"

# Weer: HA-condities -> Nederlands.
HA_WEER = {
    "clear-night": "Helder", "cloudy": "Bewolkt", "exceptional": "Uitzonderlijk",
    "fog": "Mist", "hail": "Hagel", "lightning": "Onweer", "lightning-rainy": "Onweer en regen",
    "partlycloudy": "Half bewolkt", "pouring": "Stortregen", "rainy": "Regen",
    "snowy": "Sneeuw", "snowy-rainy": "Natte sneeuw", "sunny": "Zonnig",
    "windy": "Winderig", "windy-variant": "Winderig en bewolkt",
}

# Slim huis: staat -> label (zoals de wireframe: AAN/UIT, OPEN/DICHT).
_DOMEIN_LABEL = {
    "light": ("AAN", "UIT"),
    "switch": ("AAN", "UIT"),
    "media_player": ("AAN", "UIT"),
    "climate": ("AAN", "UIT"),
    "cover": ("OPEN", "DICHT"),
}
# Welke HA-domeinen u als tegel kunt kiezen (alleen tonen; bedienen kan
# alleen bij lampen). Max. aantal gekozen apparaten.
SLIM_HUIS_DOMEINEN = ("light", "switch", "button", "cover", "climate", "media_player", "fan", "sensor",
                      "binary_sensor")

# Wat een tik op een tegel doet. Lampen: aan/uit (laag risico, direct).
# Schakelaars, mediaspelers (bijv. de tv) en knoppen (bijv. Wake-on-LAN)
# zijn "medium": de bewaakte poort vraagt dan eerst om goedkeuring.
TIK_DOMEINEN = ("light", "switch", "media_player", "button")

# Lampen instellen vanaf het dashboard (Fase 20, M2): vaste keuzes, zodat er
# nooit willekeurige waarden naar Home Assistant gaan.
LAMP_KLEUREN = {
    "rood": (255, 0, 0),
    "oranje": (255, 120, 0),
    "geel": (255, 210, 0),
    "groen": (0, 200, 60),
    "cyaan": (0, 200, 255),
    "blauw": (30, 60, 255),
    "paars": (150, 40, 255),
    "roze": (255, 60, 160),
}
LAMP_WARMTES = {"warm": 2700, "neutraal": 4000, "koel": 6000}
_DIM_MODI = frozenset(["brightness", "color_temp", "hs", "rgb", "rgbw", "rgbww", "xy", "white"])
_KLEUR_MODI = frozenset(["hs", "rgb", "rgbw", "rgbww", "xy"])


def lamp_mogelijkheden(attrs):
    """Wat een lamp kan, uit de HA-attributen: dimmen, warmte, kleur."""

    modi = attrs.get("supported_color_modes") or []
    if not isinstance(modi, (list, tuple)):
        modi = []
    modi = {str(m) for m in modi}
    helderheid = attrs.get("brightness")
    try:
        procent = None if helderheid is None else max(1, min(100, round(int(helderheid) * 100 / 255)))
    except (TypeError, ValueError):
        procent = None
    return {
        "dimbaar": bool(modi & _DIM_MODI),
        "warmte": "color_temp" in modi,
        "kleur": bool(modi & _KLEUR_MODI),
        "helderheid": procent,
    }
MAX_SLIM_HUIS = 24
_ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def valideer_slim_huis(lijst):
    """Foutmelding (str) of None voor een lijst gekozen entity_id's."""

    if not isinstance(lijst, list):
        return "apparaten moet een lijst zijn."
    if len(lijst) > MAX_SLIM_HUIS:
        return f"Hooguit {MAX_SLIM_HUIS} apparaten."
    if len(set(lijst)) != len(lijst):
        return "Een apparaat mag maar één keer voorkomen."
    for e in lijst:
        if not isinstance(e, str) or len(e) > 100 or not _ENTITY_ID.match(e):
            return "Ongeldige entity_id."
        if e.split(".", 1)[0] not in SLIM_HUIS_DOMEINEN:
            return "Dit soort apparaat kan niet op het dashboard."
    return None


_AAN_STATEN = frozenset(["on", "open", "opening", "playing", "paused", "idle", "heat", "cool", "auto", "heat_cool"])


def _kort(waarde, maximaal=28):
    tekst = str(waarde)
    return tekst if len(tekst) <= maximaal else tekst[: maximaal - 1] + "…"


# =============================================================
# Cache
# =============================================================

class Cache:
    """Kleine thread-safe cache met een ttl per sleutel."""

    def __init__(self, clock=None):
        self.clock = clock or time.time
        self._lock = threading.Lock()
        self._data = {}

    def haal(self, sleutel, ttl, maak):
        nu = self.clock()
        with self._lock:
            item = self._data.get(sleutel)
            if item and nu - item[0] < ttl:
                return item[1]
        waarde = maak()
        with self._lock:
            self._data[sleutel] = (self.clock(), waarde)
        return waarde

    def vergeet(self, sleutel):
        with self._lock:
            self._data.pop(sleutel, None)


# =============================================================
# Auditlog
# =============================================================

def lees_audit(pad, aantal=AUDIT_REGELS):
    """De laatste ``aantal`` auditregels, nieuwste eerst, klaar voor de tegel.

    Inlogpogingen (``dashboard_auth``) worden overgeslagen; die zijn voor
    het auditbestand, niet voor het scherm.
    """

    try:
        with open(pad, "rb") as f:
            f.seek(0, os.SEEK_END)
            grootte = f.tell()
            f.seek(max(0, grootte - AUDIT_LEES_BYTES))
            ruw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    regels = ruw.splitlines()
    if len(ruw.encode("utf-8")) >= AUDIT_LEES_BYTES and regels:
        regels = regels[1:]  # eerste regel kan half zijn

    uit = []
    for regel in reversed(regels):
        try:
            item = json.loads(regel)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("tool") == "dashboard_auth":
            continue
        uit.append(_audit_tegel(item))
        if len(uit) >= aantal:
            break
    return uit


def _audit_tegel(item):
    tijd = str(item.get("tijd") or "")
    args = item.get("argumenten") if isinstance(item.get("argumenten"), dict) else {}
    delen = [str(item.get("tool") or "?")]
    for waarde in list(args.values())[:2]:
        if isinstance(waarde, (str, int, float)) and str(waarde) != "***":
            delen.append(_kort(waarde, 20))
    goedgekeurd = bool(item.get("goedgekeurd"))
    if goedgekeurd:
        resultaat = "gelukt"
    else:
        resultaat = _kort(item.get("reden") or "niet uitgevoerd", 24)
    return {
        "tijd": tijd[11:19] if len(tijd) >= 19 else tijd,
        "actie": " · ".join(delen),
        "risico": str(item.get("risico") or "low").upper(),
        "resultaat": resultaat,
        "goedgekeurd": goedgekeurd,
        "herkomst": str(item.get("herkomst") or ""),
    }


# =============================================================
# Standaardaanroepen naar de rest van JARVIS (late imports)
# =============================================================

def _std_tool(tool_name, arguments, question):
    """Schrijfacties: dezelfde bewaakte poort als de stem (risico, goedkeuring,
    PC_TARGET-routering), met herkomst "dashboard" in de auditregel."""

    from core.ai import _dispatch_tool
    from core.tool_registry import run_tool_guarded

    return run_tool_guarded(
        tool_name, arguments, source="dashboard", question=question,
        dispatch=_dispatch_tool, herkomst="dashboard",
    )


def _std_app_volume(app, volume):
    """Zet het volume van één app (uit MEDIA_APPS) via de bewaakte poort.

    audio_set_session_volume is "medium": via de stem volgt dan een
    goedkeuringsvraag. Een schuif op het dashboard is zelf al een expliciete
    handeling van een bedien-apparaat, voor één vaste app; daarom hier
    approved=True. De auditregel (herkomst "dashboard") blijft.
    """

    from core.ai import _dispatch_tool
    from core.tool_registry import run_tool_guarded

    return run_tool_guarded(
        "audio_set_session_volume", {"app_name": app, "volume": volume},
        source="dashboard", question=f"dashboard: {app} op {volume}%",
        dispatch=_dispatch_tool, approved=True, herkomst="dashboard",
    )


def _std_lees(tool_name, arguments, question):
    """Alleen-lezen tools (bijv. een app-volume): wel de PC_TARGET-routering,
    maar geen auditregel elke paar seconden."""

    from core.ai import _dispatch_tool

    return _dispatch_tool(tool_name, arguments, question)


def _std_ha_get(pad):
    from core.home_assistant import _ha_get

    return _ha_get(pad)


def _std_weer(plaats):
    from actions.web import get_weather

    return get_weather(plaats)


def _std_telemetrie_lokaal():
    from remote.telemetry import collect_telemetry

    return collect_telemetry()


def _std_telemetrie_game_pc():
    import config

    if not config.REMOTE_CLIENT_ENABLED:
        return None
    from core.ai import _dispatch_local_tool

    return _dispatch_local_tool("game_pc_telemetry", {}, "dashboard: pc-status")


def _std_scene(naam, scene):
    from core.brain import _execute_scene

    return _execute_scene(naam, scene, f"dashboard: scène {naam}")


def _std_scenes():
    try:
        with open(SCENES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _std_lampen():
    """Entity-id's uit de HA-aliassen (de apparaten die JARVIS kent)."""

    try:
        with open(ALIASES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: (v if isinstance(v, list) else []) for k, v in data.items() if isinstance(k, str) and "." in k}


def _std_weer_plaats():
    import config

    return config.WEER_PLAATS


def _std_audit_pad():
    import core.audit

    return core.audit.AUDIT_FILE


def _std_pc_target():
    from core import pc_target

    return pc_target.get_pc_target()


def _ontpak(data):
    """Haalt de echte gegevens uit een (eventueel remote) ToolResult-data.

    Lokaal: ``{"volume": 40, ...}``. Via de game-pc-agent zit dat in
    ``data["resultaat"]`` en bij een tool-resultaat nog in ``["data"]``.
    """

    # Telemetrie van de game-pc: remote/tools.py zet die al uitgepakt in
    # data["telemetrie"] (de agent stuurt {"ok": true, "telemetrie": {...}}).
    if isinstance(data, dict) and isinstance(data.get("telemetrie"), dict):
        return data["telemetrie"]
    if isinstance(data, dict) and "resultaat" in data and "remote_tool" in data:
        data = data.get("resultaat")
        if isinstance(data, dict) and isinstance(data.get("data"), dict) and "ok" in data:
            data = data["data"]
    return data


def _resultaat_ok(resultaat):
    """(ok, data, melding) uit een ToolResult of tekst."""

    if resultaat is None:
        return False, None, ""
    ok = getattr(resultaat, "ok", None)
    if ok is not None:
        data = _ontpak(getattr(resultaat, "data", None))
        return bool(ok), data, str(getattr(resultaat, "message", "") or "")
    tekst = str(resultaat)
    mislukt = any(w in tekst.lower() for w in ("mislukt", "fout", "kan niet", "kon niet", "niet bereiken"))
    return not mislukt, None, tekst



# =============================================================
# Overzichten (M6): logboek, geheugen, routines — alleen lezen
# =============================================================

LOG_FILE = os.path.join(PROJECT, "logs", "jarvis.log")
ROUTINES_FILE = os.path.join(PROJECT, "config", "routines.json")

LOG_REGELS = 100
LOG_LEES_BYTES = 96 * 1024
GEHEUGEN_ITEMS = 60
MAX_TEKST = 160

_LOG_REGEL = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})[,.]\d+\s+([A-Z]+)\s+([\w.\-]+):\s?(.*)$"
)
# Extra vangnet: tokens horen nooit in de log, maar mocht er iets op lijken,
# dan komt het niet op het scherm.
_GEHEIM = re.compile(
    r"(?i)\b(token|bearer|authorization|password|wachtwoord|api[_-]?key)\b(\s*[:=]?\s*)(?:bearer\s+)?(\S+)"
)


def _verberg_geheimen(tekst):
    return _GEHEIM.sub(lambda m: m.group(1) + m.group(2) + "***", tekst)


def lees_log(pad, aantal=LOG_REGELS):
    """De laatste ``aantal`` logregels, nieuwste eerst."""

    try:
        with open(pad, "rb") as f:
            f.seek(0, os.SEEK_END)
            grootte = f.tell()
            f.seek(max(0, grootte - LOG_LEES_BYTES))
            ruw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    regels = ruw.splitlines()
    if grootte > LOG_LEES_BYTES and regels:
        regels = regels[1:]  # eerste regel kan half zijn

    uit = []
    for regel in reversed(regels):
        m = _LOG_REGEL.match(regel)
        if m:
            datum, tijd, niveau, bron, tekst = m.groups()
        elif regel.strip():
            datum, tijd, niveau, bron, tekst = "", "", "", "", regel.strip()
        else:
            continue
        uit.append({
            "datum": datum,
            "tijd": tijd,
            "niveau": niveau,
            "bron": _kort(bron, 32),
            "tekst": _kort(_verberg_geheimen(tekst), MAX_TEKST),
        })
        if len(uit) >= aantal:
            break
    return uit


def _tekst(waarde):
    if isinstance(waarde, str):
        return waarde
    try:
        return json.dumps(waarde, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(waarde)


def geheugen_overzicht(geheugen, aantal=GEHEUGEN_ITEMS):
    """Categorieën met aantallen en de recentst bijgewerkte feiten."""

    categorieen = []
    items = []
    if not isinstance(geheugen, dict):
        return {"categorieen": [], "items": [], "totaal": 0}
    for categorie, inhoud in sorted(geheugen.items()):
        if not isinstance(inhoud, dict):
            continue
        categorieen.append({"naam": str(categorie), "aantal": len(inhoud)})
        for sleutel, entry in inhoud.items():
            if isinstance(entry, dict) and "value" in entry:
                waarde = entry.get("value")
                bijgewerkt = entry.get("updated") or entry.get("created") or ""
                gebruikt = entry.get("usage_count") or 0
            else:
                waarde, bijgewerkt, gebruikt = entry, "", 0
            items.append({
                "categorie": str(categorie),
                "sleutel": _kort(str(sleutel).replace("_", " "), 40),
                "waarde": _kort(_tekst(waarde), MAX_TEKST),
                "bijgewerkt": str(bijgewerkt)[:16].replace("T", " "),
                "gebruikt": gebruikt if isinstance(gebruikt, int) else 0,
            })
    items.sort(key=lambda i: i["bijgewerkt"], reverse=True)
    return {
        "categorieen": [c for c in categorieen if c["aantal"]],
        "items": items[:aantal],
        "totaal": len(items),
    }


_STAP_SLEUTELS = ("entity_id", "program", "name", "app_name", "percent", "volume", "service")


def routines_overzicht(routines):
    """Naam, beschrijving, stappen en gebruik per routine (alleen tonen)."""

    uit = []
    if not isinstance(routines, dict):
        return uit
    for naam, r in sorted(routines.items()):
        if not isinstance(r, dict):
            continue
        stappen = []
        for stap in r.get("steps") or []:
            if not isinstance(stap, dict):
                continue
            args = stap.get("arguments") if isinstance(stap.get("arguments"), dict) else {}
            # Eerst wát er bediend wordt (lamp, programma), dan hoe.
            belangrijk = [args[k] for k in _STAP_SLEUTELS if k in args]
            waarden = belangrijk or list(args.values())
            delen = [str(stap.get("tool_name") or "?")]
            delen += [_kort(v, 24) for v in waarden[:2] if isinstance(v, (str, int, float))]
            stappen.append(" · ".join(delen))
        uit.append({
            "id": naam,  # de sleutel in routines.json (om te starten)
            "naam": _kort(str(r.get("name") or naam), 30),
            "beschrijving": _kort(str(r.get("description") or ""), MAX_TEKST),
            "stappen": stappen[:12],
            "gebruikt": r.get("usage_count") if isinstance(r.get("usage_count"), int) else 0,
            "laatst_gebruikt": str(r.get("last_used") or "")[:16].replace("T", " "),
            "vertrouwd": bool(r.get("vertrouwd")),
        })
    return uit


def _std_log_pad():
    return LOG_FILE


def _std_geheugen():
    from memory.memory import load_memory

    return load_memory()


def _std_routines():
    try:
        with open(ROUTINES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _std_brein():
    from beheer import backup
    from beheer.waakhond import brein_status

    status = brein_status()
    try:
        status["backup"] = backup.samenvatting()
    except Exception:
        logger.debug("Backupstatus lezen mislukt.", exc_info=True)
    try:
        from beheer import updates

        status["updates"] = updates.samenvatting()
    except Exception:
        logger.debug("Updatestatus lezen mislukt.", exc_info=True)
    try:
        from core import koppelingen

        status["koppelingen"] = koppelingen.overzicht()
    except Exception:
        logger.debug("Koppelingen lezen mislukt.", exc_info=True)
    return status

# =============================================================
# Bronnen
# =============================================================

class Bronnen:
    """Alle tegelgegevens en -acties, met cache en injecteerbare aanroepen."""

    def __init__(self, tool_fn=None, lees_fn=None, app_volume_fn=None, ha_get_fn=None, weer_fn=None, telemetrie_lokaal_fn=None,
                 telemetrie_game_pc_fn=None, scene_fn=None, scenes_fn=None, apparaten_fn=None,
                 weer_plaats_fn=None, pc_target_fn=None, audit_pad_fn=None, log_pad_fn=None,
                 geheugen_fn=None, routines_fn=None, brein_fn=None, clock=None):
        self.tool_fn = tool_fn or _std_tool
        self.lees_fn = lees_fn or _std_lees
        self.app_volume_fn = app_volume_fn or _std_app_volume
        self.ha_get_fn = ha_get_fn or _std_ha_get
        self.weer_fn = weer_fn or _std_weer
        self.telemetrie_lokaal_fn = telemetrie_lokaal_fn or _std_telemetrie_lokaal
        self.telemetrie_game_pc_fn = telemetrie_game_pc_fn or _std_telemetrie_game_pc
        self.scene_fn = scene_fn or _std_scene
        self.scenes_fn = scenes_fn or _std_scenes
        self.apparaten_fn = apparaten_fn or _std_lampen
        self.weer_plaats_fn = weer_plaats_fn or _std_weer_plaats
        self.pc_target_fn = pc_target_fn or _std_pc_target
        self.audit_pad_fn = audit_pad_fn or _std_audit_pad
        self.log_pad_fn = log_pad_fn or _std_log_pad
        self.geheugen_fn = geheugen_fn or _std_geheugen
        self.routines_fn = routines_fn or _std_routines
        self.brein_fn = brein_fn or _std_brein
        self.cache = Cache(clock)
        self._audit_lock = threading.Lock()
        self._audit_sleutel = None
        self._audit_regels = []

    # ----- auditlog -----

    def audit(self):
        """De laatste auditregels; leest het bestand alleen opnieuw als het
        veranderd is (de waarnemer vraagt dit elke seconde)."""

        pad = self.audit_pad_fn()
        try:
            st = os.stat(pad)
        except OSError:
            return []
        sleutel = (pad, st.st_size, st.st_mtime_ns)
        with self._audit_lock:
            if sleutel != self._audit_sleutel:
                self._audit_regels = lees_audit(pad)
                self._audit_sleutel = sleutel
            return [dict(r) for r in self._audit_regels]

    # ----- overzichten (M6) -----

    def logboek(self):
        return self.cache.haal("logboek", 2, lambda: lees_log(self.log_pad_fn()))

    def geheugen(self):
        def maak():
            try:
                return geheugen_overzicht(self.geheugen_fn())
            except Exception:
                logger.debug("Geheugen lezen mislukt.", exc_info=True)
                return {"categorieen": [], "items": [], "totaal": 0}
        return self.cache.haal("geheugen", 5, maak)

    def routines(self):
        return self.cache.haal("routines", 5, lambda: routines_overzicht(self.routines_fn()))

    # ----- media -----

    def media(self):
        return self.cache.haal("media", TTL_MEDIA, self._media)

    def _media(self):
        apps = []
        for naam in MEDIA_APPS:
            try:
                ok, data, _ = _resultaat_ok(
                    self.lees_fn("audio_get_session_volume", {"app_name": naam}, "dashboard: media")
                )
            except Exception:
                ok, data = False, None
            volume = data.get("volume") if ok and isinstance(data, dict) else None
            try:
                volume = None if volume is None else max(0, min(100, int(volume)))
            except (TypeError, ValueError):
                volume = None
            apps.append({"naam": naam, "volume": volume, "actief": volume is not None})
        doel = self.pc_target_fn()
        return {
            "doel": doel,
            "apps": apps,
            # Windows kent pas een audio-sessie als de app geluid afspeelt.
            "uitleg": "Speelt nu niet op de " + ("game-pc" if doel == "game-pc" else "laptop"),
        }

    def app_volume(self, app, volume):
        """Volume van één app zetten (alleen apps uit MEDIA_APPS)."""

        if app not in MEDIA_APPS:
            return False, "Deze app kan niet vanaf het dashboard."
        if type(volume) is not int or not 0 <= volume <= 100:
            return False, "volume moet een geheel getal van 0 tot 100 zijn."
        try:
            ok, _, melding = _resultaat_ok(self.app_volume_fn(app, volume))
        except Exception:
            logger.exception("App-volume vanaf het dashboard mislukt.")
            return False, "Het volume kon niet worden gezet."
        self.cache.vergeet("media")
        return ok, melding

    def media_actie(self, actie, waarde=None):
        if actie == "volume":
            if type(waarde) is not int or not 0 <= waarde <= 100:
                return False, "volume moet een geheel getal van 0 tot 100 zijn."
            tool, args = "set_volume", {"percent": waarde}
        elif actie in MEDIA_ACTIES:
            tool, args = MEDIA_ACTIES[actie], {}
        else:
            return False, "Onbekende media-actie."
        try:
            ok, _, melding = _resultaat_ok(self.tool_fn(tool, args, f"dashboard: media {actie}"))
        except Exception:
            logger.exception("Media-actie vanaf het dashboard mislukt.")
            return False, "De media-actie is mislukt."
        self.cache.vergeet("media")
        return ok, melding

    # ----- slim huis -----

    def _states(self):
        ok, data = self.ha_get_fn("/api/states")
        if not ok or not isinstance(data, list):
            return None
        return {s.get("entity_id"): s for s in data if isinstance(s, dict) and s.get("entity_id")}

    def _ha_states(self):
        return self.cache.haal("ha_states", TTL_HA, self._states_veilig)

    def _states_veilig(self):
        try:
            return self._states()
        except Exception:
            logger.debug("HA-states ophalen mislukt.", exc_info=True)
            return None

    def _gekozen_ids(self, gekozen=None):
        """De apparaten op het dashboard: uw keuze, of anders de HA-aliassen."""

        if isinstance(gekozen, list):
            return list(gekozen)
        return list(self.apparaten_fn())

    def slim_huis(self, gekozen=None):
        states = self._ha_states()
        aliassen_van = self.apparaten_fn()
        tegels = []
        for entity_id in self._gekozen_ids(gekozen):
            aliassen = aliassen_van.get(entity_id) or []
            domein = entity_id.split(".", 1)[0]
            state = (states or {}).get(entity_id) or {}
            attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
            staat = state.get("state")
            aan = staat in _AAN_STATEN
            labels = _DOMEIN_LABEL.get(domein, ("AAN", "UIT"))
            naam = attrs.get("friendly_name") or (aliassen[0].capitalize() if aliassen else entity_id)
            tegel = {
                "id": entity_id,
                "naam": _kort(naam, 22),
                "domein": domein,
                "aan": aan,
                "label": _ha_label(domein, staat, attrs, aan, labels),
                "detail": _ha_detail(domein, staat, attrs),
                "tikbaar": domein in TIK_DOMEINEN,
            }
            if domein == "light":
                tegel["lamp"] = lamp_mogelijkheden(attrs)
            tegels.append(tegel)
        for naam in self.scenes_fn():
            tegels.append({
                "id": f"scene:{naam}", "naam": _kort(str(naam).capitalize(), 22), "domein": "scene",
                "aan": False, "label": "ACTIVEER", "detail": "Scène", "tikbaar": True,
            })
        return {"beschikbaar": states is not None, "tegels": tegels}

    def ha_apparaten(self, gekozen=None):
        """Voor het aanpassen: wat er nu staat en wat HA verder kent."""

        states = self._ha_states() or {}
        ids = self._gekozen_ids(gekozen)
        beschikbaar = []
        for entity_id, state in states.items():
            domein = entity_id.split(".", 1)[0]
            if domein not in SLIM_HUIS_DOMEINEN or not _ENTITY_ID.match(entity_id):
                continue
            attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
            beschikbaar.append({
                "id": entity_id,
                "naam": _kort(attrs.get("friendly_name") or entity_id, 40),
                "domein": domein,
            })
        beschikbaar.sort(key=lambda a: (SLIM_HUIS_DOMEINEN.index(a["domein"]), a["naam"].lower()))
        namen = {a["id"]: a["naam"] for a in beschikbaar}
        return {
            "beschikbaar_ha": bool(states),
            "gekozen": [{"id": i, "naam": namen.get(i, i), "domein": i.split(".", 1)[0]} for i in ids],
            "beschikbaar": [a for a in beschikbaar if a["id"] not in ids],
        }

    def lamp_wissel(self, entity_id, gekozen=None):
        """Een tik op een tegel van het dashboard (via de bewaakte poort).

        Lamp of schakelaar: aan/uit. Knop (bijv. Wake-on-LAN): indrukken.
        Alleen apparaten die echt op het dashboard staan.
        """

        apparaten = self._gekozen_ids(gekozen)
        domein = entity_id.split(".", 1)[0] if isinstance(entity_id, str) else ""
        if not isinstance(entity_id, str) or entity_id not in apparaten or domein not in TIK_DOMEINEN:
            return False, "Deze lamp staat niet in de lijst van het dashboard."
        if domein == "button":
            service = "press"
        else:
            # Aan is meer dan "on": een tv kan ook "playing", "paused" of
            # "idle" zijn. Dan zet een tik hem uit, anders aan.
            state = (self._ha_states() or {}).get(entity_id) or {}
            service = "turn_off" if state.get("state") in _AAN_STATEN else "turn_on"
        try:
            ok, _, melding = _resultaat_ok(self.tool_fn(
                "control_home_assistant",
                {"domain": domein, "service": service, "entity_id": entity_id},
                f"dashboard: {entity_id} {service}",
            ))
        except Exception:
            logger.exception("Lamp wisselen vanaf het dashboard mislukt.")
            return False, "De lamp kon niet worden bediend."
        self.cache.vergeet("ha_states")
        return ok, melding

    def lamp_instellen(self, entity_id, gekozen=None, helderheid=None, kleur=None, warmte=None):
        """Helderheid, kleur of warmte van een lamp (Fase 20, M2).

        Alleen lampen die op het dashboard staan en alleen wat de lamp echt
        kan; kleur en warmte komen uit een vaste lijst. Via de bewaakte
        poort (``control_home_assistant``), net als aan/uit.
        """

        apparaten = self._gekozen_ids(gekozen)
        if not isinstance(entity_id, str) or entity_id not in apparaten or not entity_id.startswith("light."):
            return False, "Deze lamp staat niet in de lijst van het dashboard."
        if sum(x is not None for x in (helderheid, kleur, warmte)) != 1:
            return False, "Kies één ding: helderheid, kleur of warmte."

        state = (self._ha_states() or {}).get(entity_id) or {}
        attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        kan = lamp_mogelijkheden(attrs)

        if helderheid is not None:
            if isinstance(helderheid, bool) or not isinstance(helderheid, int) or not 1 <= helderheid <= 100:
                return False, "Helderheid moet tussen 1 en 100 procent liggen."
            if not kan["dimbaar"]:
                return False, "Deze lamp kan niet dimmen."
            data = {"brightness_pct": helderheid}
        elif kleur is not None:
            if kleur not in LAMP_KLEUREN:
                return False, "Onbekende kleur."
            if not kan["kleur"]:
                return False, "Deze lamp kan geen kleur."
            data = {"rgb_color": list(LAMP_KLEUREN[kleur])}
        else:
            if warmte not in LAMP_WARMTES:
                return False, "Onbekende warmte."
            if not kan["warmte"]:
                return False, "Deze lamp kan geen warm of koel wit."
            kelvin = LAMP_WARMTES[warmte]
            try:
                laag = int(attrs.get("min_color_temp_kelvin") or kelvin)
                hoog = int(attrs.get("max_color_temp_kelvin") or kelvin)
                kelvin = max(laag, min(hoog, kelvin))
            except (TypeError, ValueError):
                pass
            data = {"color_temp_kelvin": kelvin}

        try:
            ok, _, melding = _resultaat_ok(self.tool_fn(
                "control_home_assistant",
                {"domain": "light", "service": "turn_on", "entity_id": entity_id, "service_data": data},
                f"dashboard: {entity_id} instellen",
            ))
        except Exception:
            logger.exception("Lamp instellen vanaf het dashboard mislukt.")
            return False, "De lamp kon niet worden ingesteld."
        self.cache.vergeet("ha_states")
        return ok, melding

    def scene_start(self, naam):
        scenes = self.scenes_fn()
        if not isinstance(naam, str) or naam not in scenes:
            return False, "Deze scène bestaat niet."
        try:
            antwoord = self.scene_fn(naam, scenes[naam])
        except Exception:
            logger.exception("Scène starten vanaf het dashboard mislukt.")
            return False, "De scène kon niet worden gestart."
        self.cache.vergeet("ha_states")
        return True, str(antwoord or "")

    # ----- weer -----

    def weer(self):
        return self.cache.haal("weer", TTL_WEER, self._weer)

    def _weer(self):
        # Eerst Home Assistant (een weather.*-entiteit), anders Open-Meteo.
        states = self._ha_states() or {}
        for entity_id, state in sorted(states.items()):
            if not entity_id.startswith("weather."):
                continue
            attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
            temp = attrs.get("temperature")
            if temp is None:
                continue
            return {
                "beschikbaar": True,
                "bron": "home_assistant",
                "plaats": _kort(attrs.get("friendly_name") or "Thuis", 24),
                "temperatuur": _rond(temp),
                "beschrijving": HA_WEER.get(state.get("state"), str(state.get("state") or "")),
                "max": None,
                "min": None,
            }
        plaats = self.weer_plaats_fn()
        try:
            w = self.weer_fn(plaats)
        except Exception:
            w = None
        if not isinstance(w, dict) or not w.get("ok"):
            return {"beschikbaar": False, "bron": "open_meteo", "plaats": plaats}
        return {
            "beschikbaar": True,
            "bron": "open_meteo",
            "plaats": _kort(str(w.get("plaats") or plaats).split(",")[0], 24),
            "temperatuur": _rond(w.get("temperatuur")),
            "beschrijving": str(w.get("beschrijving") or ""),
            "max": _rond(w.get("vandaag_max")),
            "min": _rond(w.get("vandaag_min")),
        }

    # ----- pc-meters -----

    def pc_status(self, doel):
        if doel not in (DOEL_LOKAAL, DOEL_GAME_PC):
            return None
        data = self.cache.haal(f"pc:{doel}", TTL_PC, lambda: self._pc_status(doel))
        if doel == DOEL_LOKAAL:
            # De brein-status (Fase 19, M2) is goedkoop en mag niet uit de
            # cache komen: na een herstart wilt u het meteen zien.
            try:
                data = dict(data, brein=self.brein_fn())
            except Exception:
                logger.debug("Brein-status ophalen mislukt.", exc_info=True)
        return data

    def _pc_status(self, doel):
        try:
            if doel == DOEL_LOKAAL:
                telemetrie = self.telemetrie_lokaal_fn()
            else:
                resultaat = self.telemetrie_game_pc_fn()
                if resultaat is None:
                    return {"doel": doel, "beschikbaar": False, "melding": "Game-PC-agent staat niet aan."}
                ok, data, melding = _resultaat_ok(resultaat)
                if not ok or not isinstance(data, dict):
                    return {"doel": doel, "beschikbaar": False, "melding": "Game-PC niet bereikbaar."}
                telemetrie = data
        except Exception:
            logger.debug("Telemetrie ophalen mislukt.", exc_info=True)
            return {"doel": doel, "beschikbaar": False, "melding": "Meters niet beschikbaar."}
        return {"doel": doel, "beschikbaar": True, "meters": _meters(telemetrie)}


def _rond(waarde):
    try:
        return round(float(waarde))
    except (TypeError, ValueError):
        return None


def _ha_label(domein, staat, attrs, aan, labels):
    """Het kleine label rechtsboven op een tegel."""

    if domein == "button":
        return "DRUK"
    if staat in (None, "unavailable", "unknown"):
        return "?"
    if domein == "sensor":
        # Een sensor heeft een waarde (bijv. 21.5 °C), geen aan/uit.
        return _kort(f"{staat} {attrs.get('unit_of_measurement') or ''}".strip(), 10)
    return labels[0 if aan else 1]


def _ha_detail(domein, staat, attrs):
    if staat in (None, "unavailable", "unknown"):
        return "Niet bereikbaar"
    if domein == "light" and staat == "on" and attrs.get("brightness") is not None:
        try:
            return f"Lamp · {round(int(attrs['brightness']) / 255 * 100)}%"
        except (TypeError, ValueError):
            return "Lamp"
    if domein == "light":
        return "Lamp"
    if domein == "cover" and attrs.get("current_position") is not None:
        return f"Positie {attrs.get('current_position')}%"
    if domein == "climate" and attrs.get("temperature") is not None:
        return f"{attrs.get('temperature')}° ingesteld"
    if domein == "media_player":
        return "Mediaspeler"
    if domein == "switch":
        return "Schakelaar"
    if domein == "button":
        return "Tik om in te drukken"
    if domein == "fan":
        return "Ventilator"
    if domein == "sensor":
        return "Sensor"
    if domein == "binary_sensor":
        return "Melder"
    return ""


def _meters(t):
    """Processor, geheugen en GPU-temperatuur (design §7.4) uit telemetrie."""

    def deel(naam):
        d = t.get(naam) if isinstance(t, dict) else None
        return d if isinstance(d, dict) and d.get("ok", True) else {}

    cpu = _rond(deel("cpu").get("gebruik_percent"))
    ram = _rond(deel("ram").get("percentage"))
    gpu = deel("gpu")
    gpu_lijst = gpu.get("gpus") if isinstance(gpu.get("gpus"), list) else []
    eerste = gpu_lijst[0] if gpu_lijst and isinstance(gpu_lijst[0], dict) else gpu
    gpu_temp = _rond(eerste.get("temperatuur_c"))
    return [
        {"naam": "Processor", "waarde": cpu, "eenheid": "%", "procent": cpu, "hoog": cpu is not None and cpu >= DREMPEL_CPU},
        {"naam": "Geheugen", "waarde": ram, "eenheid": "%", "procent": ram, "hoog": ram is not None and ram >= DREMPEL_RAM},
        {"naam": "GPU-temperatuur", "waarde": gpu_temp, "eenheid": "°C",
         "procent": None if gpu_temp is None else min(100, gpu_temp),
         "hoog": gpu_temp is not None and gpu_temp >= DREMPEL_GPU_TEMP},
    ]


def nu_tijd():
    return datetime.now().strftime("%H:%M:%S")
