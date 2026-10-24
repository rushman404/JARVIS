"""
HA Registry (Fase 3 — Home Assistant 2.0)

Dynamische snapshot van Home Assistant: entities → devices → areas.

Bronnen (in volgorde):
  1. /api/config/entity_registry + /api/config/device_registry + /api/config/area_registry
     (rijke metadata: device, naam, area)
  2. Terugval: /api/states (alleen entity_id + friendly_name + state + attrs)

De snapshot wordt gecached met TTL en opnieuw gebouwd bij verandering.
De gebruikte bron wordt bijgehouden zodat JARVIS weet waarmee hij werkt.

Veiligheidsregel:
  - ALLEEN ontdekken mag alles.
  - Bediening loopt altijid via de bestaande tool/validatielaag
    (control_home_assistant_tool).
  - Voor live tests kan een optionele allowlist beperken welke
    entities mogen worden bestuurd (bv. alleen light.bed_lamp).
"""

import json
import os
import time
import threading


# =========================================================
# Configuratie
# =========================================================

REGISTRY_TTL = 60  # seconden cache-refresh

# Optionele veiligheidsmodus voor live tests. Alleen wanneer
# HA_CONTROL_SAFETY_ON=1, wordt bediening extra beperkt tot de
# entiteiten in _CONTROLLED_ENTITY_ALLOWED (waaronder light.bed_lamp).
# Standaard (zonder env-var) is de modus uit: dan mag JARVIS alle
# ontdekte entities bedienen, maar altijd via de tool-/validatielaag
# (domein-whitelist + capability-checks in home_assistant.py).
_CONTROL_SAFETY_ON = os.environ.get("HA_CONTROL_SAFETY_ON", "").lower() in ("1", "true", "yes")

_CONTROLLED_ENTITY_ALLOWED = frozenset({
    "light.bed_lamp",
})


# =========================================================
# Basiscommunicatie (runtime-delegatie naar home_assistant
# zodat tests met één mock volstaan — geen circulaire import).
# =========================================================

def _config_ok():
    from core.home_assistant import _config_ok as _impl
    return _impl()


def _base_url():
    from core.home_assistant import _base_url as _impl
    return _impl()


def _headers():
    from core.home_assistant import _headers as _impl
    return _impl()


def _missing_config_msg():
    return "Home Assistant niet beschikbaar: niet geconfigureerd."


def _ha_get(path):
    from core.home_assistant import _ha_get as _impl
    return _impl(path)


# =========================================================
# Aliassen (JSON-bestand, editabel)
# =========================================================

ALIASES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ha_aliases.json",
)


def _load_aliases():
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def add_user_alias(entity_ref, aliases):
    """
    Voegt door de gebruiker bedachte namen toe aan de HA-aliassen
    voor een entity (Fase 5: "de voordeur heet deurbel").

    Schrijft ALLEEN als Home Assistant geconfigureerd is (anders staat
    er geen echte entity achter) en retourneert True als er iets
    toegevoegd is.
    """

    entity_ref = (entity_ref or "").strip()

    names = [
        str(a).strip().lower()
        for a in (aliases or [])
        if str(a).strip()
    ]

    if not entity_ref or not names:
        return False

    if not _config_ok():
        return False

    data = _load_aliases()

    existing = data.setdefault(entity_ref, [])

    added = False

    for name in names:

        if name not in existing and not any(
            existing_name.split() == name.split() for existing_name in existing
        ):
            existing.append(name)
            added = True

    if added:
        try:
            with open(ALIASES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            return False

    return added


# =========================================================
# Bron-gebaseerde snapshot
# =========================================================

# Spectrum van capabilities die per domein kunnen voorkomen
_DOMAIN_SERVICE_DEFAULTS = {
    "light": {
        "turn_on", "turn_off", "toggle",
    },
    "switch": {
        "turn_on", "turn_off", "toggle",
    },
    "cover": {
        "turn_on", "turn_off", "toggle",
        "open_cover", "close_cover", "stop_cover",
        "set_cover_position",
    },
    "media_player": {
        "turn_on", "turn_off", "toggle",
        "media_play", "media_pause", "media_stop",
        "media_next_track", "media_previous_track",
        "volume_set", "volume_up", "volume_down", "select_source",
    },
    "climate": {
        "turn_on", "turn_off", "toggle",
        "set_temperature", "set_hvac_mode", "set_fan_mode",
    },
    "scene": {
        "turn_on", "toggle",
    },
    "sensor": set(),
    # Een knop (bijv. Wake-on-LAN) kan alleen worden ingedrukt.
    "button": {
        "press",
    },
}

# Domains die niet mogen worden bestuurd (read-only)
_READ_ONLY_DOMAINS = {
    "sensor", "binary_sensor", "weather", "zone",
    "person", "device_tracker", "sun",
}


class HARegistry:
    """
    In-memory snapshot van HA met TTL-cache.
    Alle methoden zijn thread-safe.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = None
        self._last_refresh = 0.0

    def get_snapshot(self, force=False):
        with self._lock:
            now = time.time()
            if not force and self._snapshot and (now - self._last_refresh) < REGISTRY_TTL:
                return self._snapshot
            self._snapshot = self._build_snapshot()
            self._last_refresh = time.time()
            return self._snapshot

    def _build_snapshot(self):
        entities = []
        devices = {}
        areas = {}
        source = "states"

        # Stap 1: Probeer registries (entity + device + area)
        reg_ok, entity_reg = _ha_get("/api/config/entity_registry")
        dev_ok, device_reg = _ha_get("/api/config/device_registry")
        area_ok, area_reg = _ha_get("/api/config/area_registry")
        state_ok, state_data = _ha_get("/api/states")

        if reg_ok and dev_ok and area_ok and isinstance(entity_reg, list) and isinstance(device_reg, list) and isinstance(area_reg, list):
            source = "registry"
            area_map = {a["area_id"]: a.get("name", a["area_id"]) for a in area_reg if isinstance(a, dict) and a.get("area_id")}
            areas = area_map

            device_map = {}
            for d in device_reg:
                if not isinstance(d, dict):
                    continue
                did = d.get("device_id", "")
                device_map[did] = {
                    "name": d.get("name") or d.get("name_by_user") or did,
                    "manufacturer": d.get("manufacturer", ""),
                    "model": d.get("model", ""),
                    "area_id": d.get("area_id"),
                    "area": area_map.get(d.get("area_id"), ""),
                }
            devices = device_map

            state_map = {}
            if state_ok and isinstance(state_data, list):
                for s in state_data:
                    if isinstance(s, dict):
                        state_map[s.get("entity_id")] = s

            user_aliases = _load_aliases()

            for er in entity_reg:
                if not isinstance(er, dict):
                    continue
                eid = er.get("entity_id")
                if not eid:
                    continue
                domain = eid.split(".")[0] if "." in eid else ""
                state_data_entity = state_map.get(eid, {})
                attrs = state_data_entity.get("attributes") or {}
                friendly_name = attrs.get("friendly_name", eid)
                device_id = er.get("device_id")
                device = device_map.get(device_id, {}) if device_id else {}
                area = device.get("area", "")

                extra_aliases = user_aliases.get(eid, [])
                if not isinstance(extra_aliases, list):
                    extra_aliases = []

                caps = _extract_capabilities(attrs, domain)

                entity_record = {
                    "entity_id": eid,
                    "domain": domain,
                    "name": friendly_name,
                    "device": device.get("name", ""),
                    "device_id": device_id,
                    "area": area,
                    "area_id": device.get("area_id") or "",
                    "state": state_data_entity.get("state", "unknown"),
                    "capabilities": sorted(caps),
                    "aliases": sorted(extra_aliases),
                }

                # Brightness
                brightness_val = attrs.get("brightness")
                if domain == "light" and isinstance(brightness_val, (int, float)):
                    entity_record["brightness_pct"] = round((brightness_val / 255) * 100)

                entities.append(entity_record)
        else:
            # Stap 2: Terugval op states (alleen entity_id + friendly_name + state + attrs)
            source = "states_fallback"
            if state_ok and isinstance(state_data, list):
                user_aliases = _load_aliases()
                for s in state_data:
                    if not isinstance(s, dict):
                        continue
                    eid = s.get("entity_id", "")
                    domain = eid.split(".")[0] if "." in eid else ""
                    attrs = s.get("attributes") or {}
                    friendly_name = attrs.get("friendly_name", eid)
                    caps = _extract_capabilities(attrs, domain)
                    entity_record = {
                        "entity_id": eid,
                        "domain": domain,
                        "name": friendly_name,
                        "device": "",
                        "device_id": "",
                        "area": "",
                        "area_id": "",
                        "state": s.get("state", "unknown"),
                        "capabilities": sorted(caps),
                        "aliases": sorted(user_aliases.get(eid, [])),
                    }
                    brightness_val = attrs.get("brightness")
                    if domain == "light" and isinstance(brightness_val, (int, float)):
                        entity_record["brightness_pct"] = round((brightness_val / 255) * 100)
                    entities.append(entity_record)

        return {
            "source": source,
            "generated_at": time.time(),
            "entity_count": len(entities),
            "entities": entities,
            "devices": devices,
            "areas": areas,
        }


def _extract_capabilities(attrs, domain):
    caps = set(_DOMAIN_SERVICE_DEFAULTS.get(domain, set()))

    if domain == "light":
        features = attrs.get("supported_features", 0) or 0
        color_modes = attrs.get("supported_color_modes") or []

        # Brightness
        if features & 1 or any(
            m in ("brightness", "hs", "rgb", "rgbw", "rgbww", "xy", "color_temp")
            for m in color_modes
        ):
            caps.add("brightness")

        # Kleurtemperatuur
        if features & 2 or "color_temp" in color_modes:
            caps.add("color_temperature")

        # Kleur
        color_modes_with_color = {"hs", "rgb", "rgbw", "rgbww", "xy"}
        if features & 16 or any(m in color_modes_with_color for m in color_modes):
            caps.add("color")

        # Effect
        if features & 4 or attrs.get("effect_list"):
            caps.add("effect")

    elif domain == "cover":
        if (attrs.get("supported_features") or 0) & 1:
            caps.add("set_position")
        if (attrs.get("supported_features") or 0) & 2:
            caps.add("tilt")
        if (attrs.get("supported_features") or 0) & 8:
            caps.add("stop_cover")

    elif domain == "media_player":
        features = attrs.get("supported_features") or 0
        if features & 1:
            caps.add("pause")
            caps.add("play")
        if features & 2:
            caps.add("stop")
        if features & 4:
            caps.add("previous")
        if features & 8:
            caps.add("next")
        if features & 16:
            caps.add("seek")
        if features & 128:
            caps.add("volume_set")
        if features & 256:
            caps.add("volume_up")
        if features & 512:
            caps.add("volume_down")
        if features & 1024:
            caps.add("select_source")

    elif domain == "climate":
        features = attrs.get("supported_features") or 0
        if features & 1:
            caps.add("set_temperature")
        if features & 2:
            caps.add("set_fan_mode")
        if features & 4:
            caps.add("set_hvac_mode")
        if features & 16:
            caps.add("set_swing_mode")

    elif domain in ("sensor", "binary_sensor"):
        caps.clear()  # read-only, geen services

    return caps


def _domain_supports_service(entity, domain, service):
    """
    Controleert of het domein/entity de service ondersteunt.
    Geeft (True, "") bij geldig, (False, fouttekst) bij mismatch.
    """

    entity_domain = entity.get("domain", "")

    if entity_domain not in _DOMAIN_SERVICE_DEFAULTS and entity_domain not in _READ_ONLY_DOMAINS:
        return False, (
            f"Domein '{entity_domain}' wordt door JARVIS niet ondersteund."
        )

    if entity_domain in _READ_ONLY_DOMAINS:
        return False, (
            f"Entity '{entity.get('name', entity.get('entity_id', '?'))}' is "
            f"een {entity_domain} en kan niet bediend worden."
        )

    caps = entity.get("capabilities", [])

    if service not in caps and service not in _DOMAIN_SERVICE_DEFAULTS.get(entity_domain, set()):
        return False, (
            f"Entity '{entity.get('name', entity.get('entity_id', '?'))}' "
            f"ondersteunt service '{service}' niet."
        )

    return True, ""


# =========================================================
# Resolutie (op de snapshot)
# =========================================================

def _norm_token(text):
    """Normaliseert voor matching: kleine letters, spaties i.p.v. _-."""

    if not text:
        return ""

    s = str(text).lower().replace("_", " ").replace("-", " ")

    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)

    return " ".join(s.split())


def _fuzzy_overlap(query_tokens, candidate_tokens):
    """Fractie van query-tokens die in de candidate zitten (0..1)."""

    if not query_tokens or not candidate_tokens:
        return 0.0

    overlap = sum(1 for t in query_tokens if t in candidate_tokens)

    return overlap / len(query_tokens)


def resolve_entities(query, domain=None, snapshot=None):
    """
    Zoekt entities op basis van naam, alias, device-naam of area.

    Geeft een gesorteerde lijst van kandidaten:
    [
      {
        "entity_id": .., "name": .., "device": .., "area": ..,
        "domain": .., "state": .., "capabilities": [], "score": 0..1,
        "match": "alias" | "device" | "area" | "name",
      }, ...
    ]
    Leeg bij niets.
    """

    snapshot = snapshot or get_snapshot()
    query_norm = _norm_token(query.strip().lower())

    if not query_norm:
        return []

    query_tokens = set(query_norm.split())
    entities = snapshot.get("entities") or []
    domain = (domain or "").strip()

    if domain:
        entities = [e for e in entities if e.get("domain") == domain]

    results = []

    for entity in entities:
        similar_names = [
            entity.get("name", ""),
            entity.get("entity_id", ""),
            entity.get("device", ""),
            entity.get("area", ""),
        ]
        similar_names += entity.get("aliases") or []

        best = 0.0
        best_match = ""
        added_exact = False

        for candidate in similar_names:
            cand_norm = _norm_token(candidate)

            if not cand_norm:
                continue

            if cand_norm == query_norm:
                results.append({
                    **entity, "score": 1.0, "match": "exact"
                })
                # Niet returnen: er kunnen MEERDELE exacte matches zijn
                # (bv. switch.tv_switch én media_player.tv voor "tv").
                # Ambiguïteit moet worden opgemerkt i.p.v. de eerste te
                # stoppen.
                added_exact = True
                break

            # Alias: bijna-exact (ontbrekende spaties/tekens)
            cand_tokens = set(cand_norm.split())
            overlap = _fuzzy_overlap(query_tokens, cand_tokens)

            # Alias-variant: "slaapkamerlamp" ~ "slaapkamerlamp" al gecheckt,
            # maar "lamp in de slaapkamer" zit in aliases -> token-fraction
            if overlap > 0:
                # Verhoog score als query en candidate veel gemeenschappelijk hebben
                fraction = overlap
                if fraction > best:
                    best = fraction
                    best_match = "alias" if candidate in similar_names[3:] else ("device" if candidate == entity.get("device") else "area" if candidate == entity.get("area") else "name")

        if added_exact:
            continue

        if best > 0:
            score = min(1.0, best + 0.2)  # kleine bonus: meerdere tokens
            result = {**entity, "score": score, "match": best_match or "name"}
            results.append(result)

    results.sort(key=lambda r: (-r.get("score", 0.0), r.get("entity_id", "")))

    return results


def resolve_entity(query, domain=None, snapshot=None):
    """
    Eenduidige resolutie: exacte match, of één duidelijke winnaar.
    Geeft (dict|None, status, message):
      - status 'exact' / 'resolved' / 'ambiguous' / 'none'
    """

    candidates = resolve_entities(query, domain=domain, snapshot=snapshot)

    if not candidates:
        return None, "none", (
            f"Geen Home Assistant apparaat gevonden voor '{query}'."
        )

    top = candidates[0]

    exact = [c for c in candidates if c.get("match") == "exact"]

    if exact:
        return exact[0], "exact", ""

    # Ambigu: eerste twee kandidaten even sterk
    if len(candidates) >= 2:
        s1 = round(candidates[0].get("score", 0), 3)
        s2 = round(candidates[1].get("score", 0), 3)

        if abs(s1 - s2) < 0.05:
            names = ", ".join(c.get("name", c.get("entity_id", "")) for c in candidates[:2])
            return None, "ambiguous", (
                f"Twijfel tussen '{names}'. Bedoel je die, of kun je "
                f"het apparaat anders omschrijven?"
            )

    return top, "resolved", ""
# =========================================================

# Globaal exemplaar (thread-safe singleton via lock in klasse)
_registry = HARegistry()


def get_snapshot(force=False):
    return _registry.get_snapshot(force=force)


def is_control_allowed(entity_id):
    """
    Bepaalt of het gegeven entity mag worden bestuurd.
    Als HA_CONTROL_SAFETY_ON=1 (live test), dan alleen een
    vaste allowlist; anders alles (standaard gedrag).
    """
    if not _CONTROL_SAFETY_ON:
        return True, ""

    if entity_id in _CONTROLLED_ENTITY_ALLOWED:
        return True, ""

    return (
        False,
        f"Live test beveiliging: entity '{entity_id}' staat niet in de "
        f"allowlist. Ontdekking is wel mogelijk, maar bediening is geblokkeerd."
    )
