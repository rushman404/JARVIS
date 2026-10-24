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
import threading
import time
from datetime import datetime

logger = logging.getLogger("jarvis.dashboard.bronnen")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIASES_FILE = os.path.join(PROJECT, "config", "ha_aliases.json")
SCENES_FILE = os.path.join(PROJECT, "config", "ha_scenes.json")

# Apps waarvan het dashboard het volume toont (zoals in de wireframe).
MEDIA_APPS = ("Spotify", "Discord")

# Media-acties van het dashboard -> tools van JARVIS.
MEDIA_ACTIES = {
    "play_pauze": "media_play_pause",
    "volgende": "media_next",
    "vorige": "media_previous",
    "stop": "media_stop",
    "dempen": "media_mute",
}

# Cachetijden (seconden).
TTL_MEDIA = 3
TTL_HA = 5
TTL_PC = 5
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
# Bronnen
# =============================================================

class Bronnen:
    """Alle tegelgegevens en -acties, met cache en injecteerbare aanroepen."""

    def __init__(self, tool_fn=None, lees_fn=None, ha_get_fn=None, weer_fn=None, telemetrie_lokaal_fn=None,
                 telemetrie_game_pc_fn=None, scene_fn=None, scenes_fn=None, apparaten_fn=None,
                 weer_plaats_fn=None, pc_target_fn=None, audit_pad_fn=None, clock=None):
        self.tool_fn = tool_fn or _std_tool
        self.lees_fn = lees_fn or _std_lees
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
        return {"doel": self.pc_target_fn(), "apps": apps}

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

    def slim_huis(self):
        states = self._ha_states()
        apparaten = self.apparaten_fn()
        tegels = []
        for entity_id, aliassen in apparaten.items():
            domein = entity_id.split(".", 1)[0]
            state = (states or {}).get(entity_id) or {}
            attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
            staat = state.get("state")
            aan = staat in _AAN_STATEN
            labels = _DOMEIN_LABEL.get(domein, ("AAN", "UIT"))
            naam = attrs.get("friendly_name") or (aliassen[0].capitalize() if aliassen else entity_id)
            tegels.append({
                "id": entity_id,
                "naam": _kort(naam, 22),
                "domein": domein,
                "aan": aan,
                "label": "?" if staat in (None, "unavailable", "unknown") else labels[0 if aan else 1],
                "detail": _ha_detail(domein, staat, attrs),
                "tikbaar": domein == "light",
            })
        for naam in self.scenes_fn():
            tegels.append({
                "id": f"scene:{naam}", "naam": _kort(str(naam).capitalize(), 22), "domein": "scene",
                "aan": False, "label": "ACTIVEER", "detail": "Scène", "tikbaar": True,
            })
        return {"beschikbaar": states is not None, "tegels": tegels}

    def lamp_wissel(self, entity_id):
        """Zet een bekende lamp aan of uit (via de bewaakte poort)."""

        apparaten = self.apparaten_fn()
        if not isinstance(entity_id, str) or entity_id not in apparaten or not entity_id.startswith("light."):
            return False, "Deze lamp staat niet in de lijst van het dashboard."
        state = (self._ha_states() or {}).get(entity_id) or {}
        service = "turn_off" if state.get("state") == "on" else "turn_on"
        try:
            ok, _, melding = _resultaat_ok(self.tool_fn(
                "control_home_assistant",
                {"domain": "light", "service": service, "entity_id": entity_id},
                f"dashboard: {entity_id} {service}",
            ))
        except Exception:
            logger.exception("Lamp wisselen vanaf het dashboard mislukt.")
            return False, "De lamp kon niet worden bediend."
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
        return self.cache.haal(f"pc:{doel}", TTL_PC, lambda: self._pc_status(doel))

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
        return "Stekker"
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
