"""
Home Assistant client (dynamische smart-home integratie).

Generieke clientlaag voor communicatie met Home Assistant via de
REST API. Nieuwe apparaten die aan Home Assistant worden toegevoegd,
zijn automatisch beschikbaar zonder Python-wijzigingen.

Gebruikt requests (reeds beschikbaar in dit project).

Fouten worden als nette NL-strings teruggegeven die voldoen aan
de bestaande FAILED_PATTERNS in core/result_validation.py
(zodat ze correct als "failed" worden geclassificeerd).
"""

import json
import re
import time

import requests

from config import HOME_ASSISTANT_URL, HOME_ASSISTANT_TOKEN

from core.ha_registry import (
    get_snapshot,
    resolve_entity,
    is_control_allowed,
    _domain_supports_service,
)


# =============================================================
# Apparaatwoorden (gedeeld met brain/ai)
# =============================================================
# De lijst die brain en de AI gebruiken om te herkennen dat een
# opdracht over een slim apparaat gaat. Bevat ook veelvoorkomende
# spraak-varianten / slecht uitgesproken woorden ("bedlam",
# "steker", "thermostad", "gordinie") zodat die óók de actie-route
# nemen in plaats van als "normale chat"-vraag te verdwijnen.

HA_DEVICE_WORDS = (
    "lamp", "lampen", "licht", "lichten", "stekker", "stekkers",
    "sensor", "sensors", "schakelaar", "schakelaars", "shutter",
    "shutters", "thermostaat", "thermostad", "klimaat",
    "temperatuur", "verwarming", "graden",
    "fan", "ventilator", "humidifier", "vacuum", "stofzuiger",
    "speaker", "speakers", "media player", "camera", "deurbel",
    "lampje", "ledstrip", "led strip", "spot", "spots", "rolluik",
    "rolluiken", "gordijn", "gordijnen", "gordyn", "gordinie",
    "scène", "scene", "scenes", "scènemodus", "filmmodus", "sfeer",
    "ambiance", "tv", "televisie", "soundbar", "versterker",
    "home cinema", "mediabox", "chromecast",
    # Veelvoorkomende spraak-varianten (slecht uitgesproken)
    "bedlam", "steker",
)


# =============================================================
# Configuratie-check
# =============================================================

def _config_ok():

    """Returnt True als de basisconfiguratie aanwezig is."""

    return bool(HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN)


def _base_url():

    return HOME_ASSISTANT_URL.rstrip("/")


def _headers():

    return {
        "Authorization": f"Bearer {HOME_ASSISTANT_TOKEN}",
        "Content-Type": "application/json",
    }


def _missing_config_msg():

    return (
        "Home Assistant niet beschikbaar: niet geconfigureerd. "
        "Stel HOME_ASSISTANT_URL en HOME_ASSISTANT_TOKEN in via "
        "de omgevingsvariabelen."
    )


# =============================================================
# Basiscommunicatie
# =============================================================

def _ha_get(path):

    """
    Voert een GET-request uit op de HA REST API.

    Geeft (True, json-data) bij succes, (False, foutmelding-tekst)
    bij falen. Foutmeldingen voldoen aan bestaande FAILED_PATTERNS.
    """

    if not _config_ok():
        return False, _missing_config_msg()

    try:
        response = requests.get(
            f"{_base_url()}{path}",
            headers=_headers(),
            timeout=8,
        )

    except requests.ConnectionError:
        return False, "Kan Home Assistant niet bereiken: verbinding mislukt."
    except requests.Timeout:
        return False, "Kan Home Assistant niet bereiken: timeout (mislukt)."
    except requests.RequestException as error:
        return False, f"Kan Home Assistant niet bereiken: {error}"

    if response.status_code == 401:
        return False, "Kan Home Assistant niet autoriseren (HTTP 401): geen toegang."
    if response.status_code == 404:
        return False, "Kan Home Assistant niet vinden (HTTP 404)."
    if response.status_code >= 500:
        return False, f"Kan Home Assistant niet bereiken (HTTP {response.status_code} serverfout mislukt)."
    if response.status_code != 200:
        return False, f"Kan Home Assistant niet bereiken (HTTP {response.status_code})."

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        return False, "Kan antwoord van Home Assistant niet lezen (ongeldige JSON)."

    return True, data


def _ha_post(path, payload=None):

    """
    Voert een POST-request uit op de HA REST API.

    Geeft (True, json-data) bij succes, (False, foutmelding-tekst)
    bij falen.
    """

    if not _config_ok():
        return False, _missing_config_msg()

    try:
        response = requests.post(
            f"{_base_url()}{path}",
            headers=_headers(),
            json=payload or {},
            timeout=8,
        )

    except requests.ConnectionError:
        return False, "Kan Home Assistant niet bereiken: verbinding mislukt."
    except requests.Timeout:
        return False, "Kan Home Assistant niet bereiken: timeout (mislukt)."
    except requests.RequestException as error:
        return False, f"Kan Home Assistant niet bereiken: {error}"

    if response.status_code == 401:
        return False, "Kan Home Assistant niet autoriseren (HTTP 401): geen toegang."
    if response.status_code == 404:
        return False, "Kan Home Assistant niet vinden (HTTP 404)."
    if response.status_code >= 500:
        return False, f"Kan Home Assistant niet bereiken (HTTP {response.status_code} serverfout mislukt)."
    if response.status_code not in (200, 201):
        return False, f"Kan Home Assistant niet bereiken (HTTP {response.status_code})."

    if response.text.strip():
        try:
            return True, response.json()
        except (json.JSONDecodeError, ValueError):
            pass

    return True, {"ok": True}


# =============================================================
# Capabilities afleiden uit HA entity attributes
# =============================================================

# Home Assistant light supported_features bits (officieel)
_LIGHT_BRIGHTNESS = 1
_LIGHT_COLOR_TEMP = 2
_LIGHT_EFFECT = 4
_LIGHT_FLASH = 128
_LIGHT_TRANSITION = 64

# Nieuwere HA versies: supported_color_modes die ECHTE kleur geven.
# 'onoff', 'brightness' en 'white' zijn géén kleurmodi en maken een
# lamp dus niet kleur-capabel.
_COLOR_MODES_WITH_COLOR = {
    "rgb", "rgbw", "rgbww", "hs", "xy", "color_temp",
}


def _extract_capabilities(attrs, domain):

    """
    Leidt uit HA entity-attributes en het domain af welke
    services/capabilities redelijkerwijs beschikbaar zijn.

    Geeft een compacte lijst van strings terug.
    """

    caps = []

    if domain in ("light", "switch", "fan", "media_player", "cover", "climate", "scene"):
        caps.extend(["turn_on", "turn_off", "toggle"])

    if domain == "light":

        features = attrs.get("supported_features", 0)
        color_modes = attrs.get("supported_color_modes") or []

        dimmable_modes = ("brightness", "hs", "rgb", "rgbw", "rgbww", "xy", "color_temp")

        if features & _LIGHT_BRIGHTNESS or any(
            mode in dimmable_modes for mode in color_modes
        ):
            caps.append("brightness")

        if features & _LIGHT_COLOR_TEMP or "color_temp" in color_modes:
            caps.append("color_temperature")

        color_capable = any(
            mode in _COLOR_MODES_WITH_COLOR for mode in color_modes
        )

        if features & 16 or color_capable:
            caps.append("color")

        if features & _LIGHT_EFFECT or attrs.get("effect_list"):
            caps.append("effect")

    elif domain == "cover":
        if attrs.get("supported_features", 0) & 1:
            caps.append("set_position")

    elif domain == "scene":
        caps.append("activate_scene")

    elif domain == "media_player":
        features = attrs.get("supported_features", 0)
        media_caps = [
            (1, "pause"), (1, "play"), (2, "stop"), (4, "previous"),
            (8, "next"), (128, "volume_set"), (256, "volume_up"),
            (512, "volume_down"), (1024, "select_source"),
        ]
        for bit, cap in media_caps:
            if features & bit:
                caps.append(cap)

    elif domain == "climate":
        caps.extend(["set_temperature", "set_hvac_mode"])

    return caps


# =============================================================
# Entity parsing (compact)
# =============================================================

def _parse_entity(state):

    """
    Parsest een HA state-object tot een compacte dict
    die door de AI bruikbaar is.
    """

    entity_id = state.get("entity_id", "")
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    # HA kan "attributes": null retourneren; behandel dat als lege dict
    attrs = state.get("attributes") or {}
    friendly_name = attrs.get("friendly_name", entity_id)
    ha_state = state.get("state", "unknown")

    capabilities = _extract_capabilities(attrs, domain)

    entity = {
        "entity_id": entity_id,
        "domain": domain,
        "name": friendly_name,
        "state": ha_state,
    }

    if capabilities:
        entity["capabilities"] = capabilities

    if domain == "light" and "brightness" in (state.get("attributes") or {}):
        brightness_val = attrs["brightness"]
        if brightness_val is not None:
            entity["brightness_pct"] = round(
                (brightness_val / 255) * 100
            )

    return entity


def _entity_fits_service(entity, domain, service):

    """
    Controleert of een service geldig is voor de gegeven entity.

    Geeft (True, "") bij geldigheid, (False, fouttekst) bij een
    duidelijke mismatch.
    """

    entity_domain = entity.get("domain", "")

    if entity_domain != domain:
        return False, (
            f"De entity {entity.get('entity_id', '?')} hoort bij "
            f"domain '{entity_domain}', niet '{domain}'."
        )

    caps = entity.get("capabilities", [])
    read_only_domains = ("sensor", "binary_sensor", "weather", "zone", "person", "device_tracker")

    if entity_domain in read_only_domains and service in (
        "turn_on", "turn_off", "toggle",
    ):
        return False, (
            f"Entity {entity.get('name', entity.get('entity_id'))} is "
            f"een {entity_domain}-sensor en kan niet bediend worden "
            f"met '{service}'."
        )

    if caps and service in ("turn_on", "turn_off", "toggle") and "turn_on" not in caps:
        return False, (
            f"Entity {entity.get('name', entity.get('entity_id'))} "
            f"ondersteunt service '{service}' niet."
        )

    return True, ""


def _check_service_data(entity, service_data):

    """
    Controleert of de gevraagde service_data (brightness, color, etc.)
    door de entity worden ondersteund.

    Geeft (True, "") of (False, fouttekst).
    """

    if not service_data:
        return True, ""

    caps = entity.get("capabilities", [])

    if "rgb_color" in service_data and "color" not in caps:
        return False, (
            f"Entity {entity.get('name', '?')} ondersteunt "
            f"geen kleur (rgb_color)."
        )

    if "hs_color" in service_data and "color" not in caps:
        return False, (
            f"Entity {entity.get('name', '?')} ondersteunt "
            f"geen kleur (hs_color)."
        )

    if "brightness_pct" in service_data and "brightness" not in caps:
        return False, (
            f"Entity {entity.get('name', '?')} ondersteunt "
            f"geen helderheidsregeling (brightness)."
        )

    if "color_temp" in service_data and "color_temperature" not in caps:
        return False, (
            f"Entity {entity.get('name', '?')} ondersteunt "
            f"geen kleurtemperatuur (color_temp)."
        )

    return True, ""


# =============================================================
# Tool: Entity Discovery
# =============================================================

# De 6 domeinen die JARVIS ondersteunt (Fase 3: bewust beperkt).
# Discovery mag alles uitlezen; bediening wordt beperkt tot deze
# domeinen via _domain_supports_service in de tool-laag.
SUPPORTED_DOMAINS = frozenset({
    "light", "switch", "cover", "media_player", "climate", "sensor",
    "scene",
})

SMART_HOME_DOMAINS = set(SUPPORTED_DOMAINS)

DOMAIN_PRIORITY = {
    "light": 0, "switch": 1, "cover": 2,
    "media_player": 3, "climate": 4, "sensor": 5,
}


def get_home_assistant_entities_tool(domain=None):

    """
    Vraagt Home Assistant entities op.

    Bron: registry (als beschikbaar) of states-fallback.
    Geeft compacte LLM-context met device, ruimte, capabilities
    en de gebruikte bron.

    Zonder domein-filter: toont slechts de 6 ondersteunde domeinen
    (light, switch, cover, media_player, climate, sensor).
    """

    snapshot = get_snapshot(force=False)
    source = snapshot.get("source", "unknown")
    entities = snapshot.get("entities") or []

    # Domeinen die we aan de LLM tonen: de ondersteunde domeinen + sensor
    if domain:
        entities = [e for e in entities if e.get("domain") == domain]
    else:
        control_domains = {"light", "switch", "cover", "media_player", "climate", "sensor", "scene"}
        entities = [e for e in entities if e.get("domain") in control_domains]

    if not entities:
        domein = f" in domein '{domain}'" if domain else ""
        return f"Geen Home Assistant entities gevonden{domein}. (bron: {source})"

    # Sorteer op domein + naam
    DOMAIN_PRIORITY = {"light": 0, "switch": 1, "cover": 2, "media_player": 3, "climate": 4, "sensor": 5, "scene": 6}
    entities.sort(key=lambda e: (DOMAIN_PRIORITY.get(e.get("domain"), 99), e.get("name", "")))

    if not domain and len(entities) > 40:
        entities = entities[:40]

    lines = []

    for e in entities:
        entity_id = e["entity_id"]
        name = e["name"]
        device = e.get("device") or ""
        area = e.get("area") or ""
        state = e.get("state", "?")

        # Compacte beschrijving: entity_id : naam [device/ruimte]
        extras = []
        if device:
            extras.append(device)
        if area:
            extras.append(area)
        suffix = f" ({', '.join(extras)})" if extras else ""

        # State tonen: voor sensors (read-only) ALTIJD, en voor andere
        # domeinen wanneer relevant (light/switch/media_player/cover).
        state_str = ""
        if state and state not in ("unknown", "unavailable"):
            state_str = f" = {state}"

        line = f"{entity_id}: {name}{suffix}{state_str}"
        lines.append(line)

    return (
        f"Home Assistant entities ({len(lines)}, bron: {source}):\n"
        + "\n".join(lines)
    )


# =============================================================
# ENTITY-RESOLUTIE-COPILOOT (deterministisch)
#
# qwen2.5:3b verzint bij multi-HA-opdrachten regelmatig entity_ids
# die niet bestaan ('light.woonkamer_lamp', 'light.kitchen_lamp',
# ...), wat leidt tot HTTP 404. Deze copiloot matcht een ongeldig
# AI-entity_id deterministisch tegen de échte, live HA-entities.
#
# Regels:
#   - Een exact geldig entity_id wordt ALTIJD behouden.
#   - Alleen aanvullen/corrigeren bij een duidelijke match.
#   - Bij twijfel (meerdere gelijkwaardige matches) NIET uitvoeren,
#     maar een duidelijke melding teruggeven.
#   - Geen hardcoded apparaatnamen: matching is puur op token-IDF
#     en generieke NL-apparaat-suffixen (lamp/licht/...).
# =============================================================

# Generieke apparaat-suffixen/werkwoorden die géén onderscheidende
# identiteit vormen. Hiermee wordt bijv. 'woonkamer_lamp' gereduceerd
# tot de kern 'woonkamer'. Dit is géén lijst van apparaatnamen.
_GENERIC_DEVICE_TOKENS = frozenset({
    "lamp", "lampen", "licht", "lichten", "light", "lights",
    "apparaat", "apparaten", "aard", "onderdeel",
    "schakelaar", "schakelaars", "switch", "switches",
    "stekker", "stekkers", "plug",
})


def _norm_for_match(text):

    """Normaliseert tekst voor token-matching (kleine letters, spaties)."""

    s = str(text or "").lower().replace("_", " ").replace("-", " ")

    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)

    return " ".join(s.split())


def _candidate_tokens(entity):

    """Tokens van een entity: uit de vriendelijke naam en het id-deel."""

    tokens = set(_norm_for_match(entity.get("name") or "").split())

    id_part = str(entity.get("entity_id") or "")

    if "." in id_part:
        tokens |= set(_norm_for_match(id_part.split(".", 1)[1]).split())

    return tokens


def _key_tokens(tokens):

    """Houdt alleen de onderscheidende (niet-generieke) tokens over."""

    return tokens - _GENERIC_DEVICE_TOKENS


def resolve_entity_id(entity_id, domain, known_entities):

    """
    Matcht een (mogelijk door de AI verzonnen) entity_id tegen de
    bekende HA-entities.

    parameters:
        entity_id         het door de AI aangeleverde entity_id
        domain            het (optionele) HA-domein van de actie
        known_entities    lijst van dicts met minimaal 'entity_id',
                          'domain' en 'name' (zoals _parse_entity)

    Geeft terug: (resolved_entity_id, status, message)
        - status 'exact'    : de opgegeven entity is geldig (ongewijzigd)
        - status 'resolved' : een duidelijke fuzzy-match; geretourneerde id
        - status 'ambiguous': meerdere even goede matches -> resolved is None
        - status 'none'     : geen match -> resolved is None
    """

    entity_id = str(entity_id or "").strip()

    if not entity_id:
        return None, "none", "Geen entity_id opgegeven."

    if not known_entities:
        return None, "none", "Geen Home Assistant entities bekend om te matchen."

    known_ids = {e.get("entity_id") for e in known_entities}

    # 1) Exact geldig entity_id -> altijd behouden.
    if entity_id in known_ids:
        return entity_id, "exact", entity_id

    # 2) Domeinfilter op de opgave, als die een domeinprefix heeft.
    given_domain = entity_id.split(".", 1)[0].lower()

    scope_domain = given_domain if "." in entity_id else (domain or "")

    candidates = known_entities

    if scope_domain:
        candidates = [
            e for e in candidates
            if str(e.get("domain") or "").lower() == str(scope_domain).lower()
        ]

    if not candidates:
        return None, "none", (
            f"Kon '{entity_id}' niet koppelen: geen apparaat in domein "
            f"'{scope_domain}' gevonden."
        )

    # 3) Kern tokens uit het opgegeven id halen en per kandidaat scoren.
    fragment_tokens = set(_norm_for_match(
        entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    ).split())

    if not fragment_tokens:
        return None, "none", f"Kon '{entity_id}' niet koppelen: geen naam om te matchen."

    key_tokens = _key_tokens(fragment_tokens)

    if not key_tokens:
        return None, "none", (
            f"'{entity_id}' is te vaag: het bevat niets onderscheidends "
            f"om aan een Home Assistant apparaat te koppelen."
        )

    # Alleen kandidaten die een ONDERSCHEIDEND (niet-generiek) token
    # uit de opgave delen, komen in aanmerking. Zo voorkom je dat
    # 'living_room_lamp' op 'Bed lamp' valt via het generieke 'lamp'.
    eligible = [
        e for e in candidates
        if key_tokens & _candidate_tokens(e)
    ]

    if not eligible:
        return None, "none", (
            f"Kon '{entity_id}' niet aan een bestaand Home Assistant "
            f"apparaat koppelen."
        )

    # Gewicht per token: een token dat in weinig apparaten voorkomt is
    # onderscheidender dan een token dat overal zit (bv. 'lamp').
    def token_weight(token):

        df = min(10, sum(1 for e in eligible if token in _candidate_tokens(e)))

        return 2.0 if df <= 1 else (1.0 if df <= 3 else 0.0)

    scores = []

    for e in eligible:

        cand_tokens = _candidate_tokens(e)

        device_overlap = len(key_tokens & cand_tokens)

        score = (
            10.0 * device_overlap
            + sum(token_weight(t) for t in (fragment_tokens & cand_tokens))
        )

        scores.append((score, e))

    scores.sort(key=lambda item: item[0], reverse=True)

    best_score, best_entity = scores[0]

    second_score = scores[1][0] if len(scores) > 1 else -1.0

    if best_score == second_score:
        return None, "ambiguous", (
            f"'{entity_id}' is onduidelijk: meerdere apparaten matchen "
            f"even goed. Noem het apparaat preciezer."
        )

    resolved = best_entity.get("entity_id")

    return resolved, "resolved", (
        f"Gecorrigeerd van '{entity_id}' naar '{resolved}'."
    )


def resolve_live_entity_id(entity_id, domain):

    """
    Bepaalt de juiste entity op basis van een door de AI gegeven
    entity_id of apparaat-naam.

    Bronnen (in volgorde):
      1. Registry-resolutie (exact/alias/device/area) op de snapshot.
      2. Fallback: bestaande token-IDF-resolver over de
         states-entities (voor het geval iemand uit de context
         een alternatieve naam gebruikt, of de registry-score
         onbeslist is maar de token-IDF wél een duidelijke
         winnaar kent).

    Geeft (resolved_id, status, message) — status 'none' met een
    heldere melding als HA niet beschikbaar is.
    """

    if not _config_ok():
        return None, "none", (
            "Home Assistant niet beschikbaar: niet geconfigureerd. "
            "Stel HOME_ASSISTANT_URL en HOME_ASSISTANT_TOKEN in via "
            "de omgevingsvariabelen."
        )

    # 1. Registry-resolutie (rijk: alias/device/area)
    hit, status, message = resolve_entity(entity_id, domain=domain)

    if hit is not None:
        resolved = hit.get("entity_id")
        return resolved, status, ""

    # 2. Fallback via de bestaande token-IDF-resolver. Die geeft ook
    #    bij een registry-"twijfel" het eindoordeel: alleen een
    #    duidelijke winnaar leidt tot uitvoering; echte twijfel blijft
    #    geblokkeerd (Fase 9-principe).
    parsed = [e for e in (get_snapshot().get("entities") or [])]
    parsed = [_entity_record_to_parse_entity(e) for e in parsed]

    if not parsed:
        if status == "ambiguous":
            return None, "ambiguous", message
        return None, "none", (
            "Home Assistant lijkt geen apparaten te hebben die passen. "
            "Geen entities gevonden."
        )

    resolved_id, fb_status, fb_message = resolve_entity_id(entity_id, domain, parsed)

    if fb_status in ("exact", "resolved"):
        return resolved_id, fb_status, fb_message

    if fb_status == "ambiguous":
        return None, "ambiguous", fb_message

    # Fallback geeft 'none'; behoud een mogelijke registry-twijfel.
    if status == "ambiguous":
        return None, "ambiguous", message

    return None, "none", fb_message


def _entity_record_to_parse_entity(record):
    """Zet een registry-record om naar het formaat van _parse_entity."""

    return {
        "entity_id": record.get("entity_id", ""),
        "domain": record.get("domain", ""),
        "name": record.get("name", record.get("entity_id", "")),
        "state": record.get("state", "unknown"),
        "capabilities": record.get("capabilities", []),
        "brightness_pct": record.get("brightness_pct"),
    }


# =============================================================
# Tool: Control
# =============================================================

# Hoe vaak en hoe lang we wachten op een state-update na een service.
# Dit voorkomt dat JARVIS "aan/uit" teruggeeft terwijl de state nog
# oud is (Fase 13 bugfix: eerlijke state-verificatie).
HA_STATE_SETTLE_ATTEMPTS = 4
HA_STATE_SETTLE_DELAY = 0.6


def _POWERED_ON_STATES(domain):
    """States die 'aan' betekenen, per domein."""
    if domain == "media_player":
        return {"on", "playing", "buffering", "idle", "paused"}
    if domain == "cover":
        return {"open", "opening"}
    if domain == "climate":
        return {"heat", "cool", "auto", "heat_cool", "dry", "fan_only"}
    if domain == "scene":
        # Scenes hebben geen vaste 'on'-state: hun state is de naam
        # van de laatst geactiveerde scene. Elk niet-onbekend resultaat
        # betekent activering.
        return {"any_non_empty"}
    return {"on", "open"}


def _POWERED_OFF_STATES(domain):
    """States die 'uit' betekenen, per domein."""
    if domain == "media_player":
        return {"off", "standby"}
    if domain == "cover":
        return {"closed", "stopped"}
    if domain == "scene":
        return {"any_non_empty"}
    return {"off", "closed", "unavailable", "unknown"}


def _state_matches_expected(state_str, expected):
    """
    Controleert of de huidige state overeenkomt met de verwachte set.
    "any_non_empty" matcht elk niet-leeg, niet-onbekend resultaat
    (voor domeinen zoals scene die geen vaste 'on'-state hebben).
    """
    if "any_non_empty" in expected:
        return bool(state_str) and state_str not in ("unknown", "unavailable")
    return state_str in expected


def control_home_assistant_tool(domain, service, entity_id, service_data=None):

    """
    Voert een generieke Home Assistant service-aanroep uit.

    parameters:
        domain      bv. 'light', 'switch', 'cover'
        service     bv. 'turn_on', 'turn_off', 'toggle'
        entity_id   bv. 'light.my_rgb_strip'
        service_data optionele dict met extra parameters
                      (brightness_pct, rgb_color, etc.)
    """

    if not domain:
        return "Kan actie niet uitvoeren: mist een argument: domain."
    if not service:
        return "Kan actie niet uitvoeren: mist een argument: service."
    if not entity_id:
        return "Kan actie niet uitvoeren: mist een argument: entity_id."

    # Fase 3 veiligheidsregel: JARVIS bestuurt alleen de 6
    # ondersteunde domeinen. Discovery mag alles uitlezen, maar
    # bediening van andere domeinen (fan, vacuum, camera, lock, ...)
    # wordt hier geweigerd — vóór elke netwerkcall.
    if domain not in SUPPORTED_DOMAINS:
        return (
            f"Actie niet uitgevoerd: domein '{domain}' wordt door "
            f"JARVIS niet ondersteund (alleen light, switch, cover, "
            f"media_player, climate en sensor)."
        )

    # Fase 3 veiligheidsregel: bij live tests mag alleen de
    # bedoelde bedlamp daadwerkelijk bestuurd worden. Discovery
    # blijft alles uitlezen; bediening loopt via deze tool-laag.
    allowed, msg = is_control_allowed(entity_id)

    if not allowed:
        return f"Actie niet uitgevoerd: {msg}"

    ok, data = _ha_get(f"/api/states/{entity_id}")

    if not ok:
        return data

    entity = _parse_entity(data)

    # Extra laag op de registry-whitelist (domein + read-only +
    # service-ondersteuning). Geeft heldere NL-meldingen.
    ok, msg = _domain_supports_service(entity, domain, service)

    if not ok:
        return msg

    ok, msg = _entity_fits_service(entity, domain, service)

    if not ok:
        return msg

    ok, msg = _check_service_data(entity, service_data or {})

    if not ok:
        return msg

    payload = {
        "entity_id": entity_id,
    }

    if service_data:
        payload.update(service_data)

    ok, result = _ha_post(
        f"/api/services/{domain}/{service}",
        payload,
    )

    if not ok:
        return result

    name = entity.get("name", entity_id)

    # Verwachtte state na de service bepalen (domain-bewust).
    expected_on = _POWERED_ON_STATES(domain)
    expected_off = _POWERED_OFF_STATES(domain)

    # Enkel voor turn_on/turn_off/toggle pollen we op state-verandering.
    # Andere services (volume_up, media_pause, enz.) blokkeren niet.
    needs_state_verify = service in ("turn_on", "turn_off", "toggle")
    new_state_str = "onbekend"
    state_ok = False
    new_state = None

    # State vóór de actie opslaan zodat we VERANDERING kunnen detecteren.
    # Sommige apparaten (bv. webOS TV) zijn langzaam: de state is na
    # 1.8s nog niet "off" maar wél veranderd t.o.v. "on".
    pre_state_str = "onbekend"
    pre_state_ok, pre_state = _ha_get(f"/api/states/{entity_id}")
    if pre_state_ok and pre_state:
        pre_state_str = pre_state.get("state", "onbekend")

    if needs_state_verify:
        for attempt in range(HA_STATE_SETTLE_ATTEMPTS):
            if attempt > 0:
                time.sleep(HA_STATE_SETTLE_DELAY)
            state_ok, new_state = _ha_get(f"/api/states/{entity_id}")
            if not state_ok:
                break
            new_state_str = new_state.get("state", "onbekend")
            if service == "turn_on" and _state_matches_expected(new_state_str, expected_on):
                break
            if service == "turn_off" and _state_matches_expected(new_state_str, expected_off):
                break
            # Toggle: eerste lezing overslaan (is de PRE-toggle state).
            if service == "toggle" and attempt > 0:
                break
    else:
        # Niet-power services: een snelle lezing voor het antwoord,
        # maar geen blokkerende polling.
        state_ok, new_state = _ha_get(f"/api/states/{entity_id}")
        if state_ok:
            new_state_str = new_state.get("state", "onbekend")

    if service == "turn_on":
        brightness_str = ""

        if service_data and "brightness_pct" in service_data:
            brightness_str = f" (brightness {service_data['brightness_pct']}%)"
        elif state_ok and new_state:
            attrs = new_state.get("attributes", {})
            brightness_val = attrs.get("brightness")
            if brightness_val is not None:
                brightness_str = f" (brightness {round((brightness_val / 255) * 100)}%)"

        if service_data and "hs_color" in service_data:
            hs = service_data["hs_color"]
            if isinstance(hs, (list, tuple)) and len(hs) == 2:
                brightness_str += f" (kleur: hs_color {int(hs[0])}, {int(hs[1])})"
        elif service_data and "rgb_color" in service_data:
            rgb = service_data["rgb_color"]
            if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
                brightness_str += f" (kleur: rgb_color {int(rgb[0])}, {int(rgb[1])}, {int(rgb[2])})"

        # Eerlijke melding: alleen "aan" als HA dat bevestigt ÓF de
        # state is veranderd (sommige apparaten zijn langzaam).
        state_changed = (state_ok and new_state_str != pre_state_str)
        state_ok_now = (state_ok and _state_matches_expected(new_state_str, expected_on))
        if not state_ok_now and not state_changed:
            return (
                f"{name}: ik stuurde 'aan', maar de status is nog "
                f"'{new_state_str}'. Het apparaat reageert mogelijk niet "
                f"op het commando."
            )

        return f"{name} is nu aan.{brightness_str}"

    if service == "turn_off":
        # Eerlijke melding: alleen "uit" als de state veranderd is
        # (ook niet als die nog niet de verwachte eindstate heeft bereikt).
        state_changed = (state_ok and new_state_str != pre_state_str)
        state_ok_now = (state_ok and _state_matches_expected(new_state_str, expected_off))
        if not state_ok_now and not state_changed:
            return (
                f"{name}: ik stuurde 'uit', maar de status is nog "
                f"'{new_state_str}'. Het apparaat reageert mogelijk niet "
                f"op het commando."
            )

        return f"{name} is nu uit."

    if service == "toggle":
        return f"{name} is nu {new_state_str}."

    return f"{name}: service '{service}' uitgevoerd (state: {new_state_str})."


# =============================================================
# KLEUR-COPILOOT (deterministisch)
#
# Qwen2.5:3b genereert bij een kleuropdracht ("maak mijn bedlamp
# rood") soms GEEN service_data, of een verkeerde hs_color (bijv.
# "groen" -> hue 0 = rood). Deze copiloot lost dat deterministisch
# op: het vertaalt bekende kleurnamen naar een vaste hs_color en
# garandeert dat de call altijd service='turn_on' wordt met die
# service_data. Geen hardcoded apparaat: de entity komt uit de
# normale HA-discovery.
# =============================================================

# Naam -> hs_color ([hue 0-360, saturation 0-100])
_COLOR_NAMES = {
    "rood": [0, 100], "rode": [0, 100], "felrood": [0, 100],
    "scharlaken": [8, 100], "karmijn": [350, 100],
    "oranje": [30, 100], "oranjegeel": [45, 100],
    "geel": [60, 100], "gele": [60, 100], "citroen": [60, 100],
    "goud": [45, 100], "gouden": [45, 100],
    "groen": [120, 100], "groene": [120, 100], "felgroen": [120, 100],
    "limoen": [90, 100], "smaragd": [150, 100],
    "olijfgroen": [70, 100], "olijfgroene": [70, 100],
    "turkoois": [175, 100], "turquoise": [175, 100],
    "cyaan": [180, 100], "turkooizen": [175, 100],
    "lichtblauw": [200, 100], "lichtblauwe": [200, 100],
    "hemelsblauw": [200, 100],
    "blauw": [240, 100], "blauwe": [240, 100], "felblauw": [240, 100],
    "donkerblauw": [240, 100], "nachtblauw": [240, 100],
    "zeeblauw": [220, 100], "azuurblauw": [210, 100],
    "paars": [270, 100], "paarse": [270, 100], "donkerpaars": [270, 100],
    "violet": [280, 100],
    "lila": [290, 100], "lavendel": [250, 60],
    "magenta": [300, 100],
    "roze": [330, 100], "rozeachtig": [330, 100], "felroze": [330, 100],
    "lichroze": [330, 100], "roos": [330, 100],
    "wit": [0, 0], "witte": [0, 0], "koelwit": [210, 0],
    "crème": [45, 30], "creme": [45, 30],
    "bruin": [30, 60], "bruine": [30, 60],
    # Engelse fallbacks (voor het geval de gebruiker Engels gebruikt)
    "red": [0, 100], "orange": [30, 100], "yellow": [60, 100],
    "green": [120, 100], "cyan": [180, 100], "blue": [240, 100],
    "purple": [270, 100],
    "pink": [330, 100], "white": [0, 0],
}


def _normalize_text(text):

    if not text:
        return ""

    lower = str(text).lower().strip()

    return (
        lower.replace("é", "e")
        .replace("è", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("ç", "c")
    )


def extract_color_hs(text):

    """
    Zoekt een bekende kleurnaam in een tekst.

    Geeft (hs_color, kleurnaam) terug, of (None, None) als er geen
    bekende kleur in staat. Langste namen krijgen voorrang zodat
    'lichtblauw' niet als 'blauw' wordt geparsed.
    """

    normalized = _normalize_text(text)

    if not normalized:
        return None, None

    for name in sorted(_COLOR_NAMES, key=len, reverse=True):

        if re.search(rf"\b{re.escape(name)}\b", normalized):
            return _COLOR_NAMES[name], name

    return None, None


def apply_color_copilot(arguments, question):

    """
    Normaliseert een control_home_assistant-opdracht voor kleuren.

    Wanneer de opdracht een bekende kleurnaam bevat (in de vraag),
    zorgt dit dát:
      - service altijd 'turn_on' is (kleur = turn_on + service_data);
      - service_data een deterministische hs_color bevat;
      - evt. foutieve rgb_color/color_temp van de AI worden vervangen
        door de vertrouwde hs_color.

    Heeft de opdracht GEEN kleurnaam (bijv. "aan", "uit", "50%"),
    dan blijft de call ongewijzigd zodat bestaande functies intact
    blijven.
    """

    arguments = dict(arguments or {})

    hs, color_name = extract_color_hs(question)

    if hs is None:
        return arguments

    arguments["service"] = "turn_on"

    service_data = dict(arguments.get("service_data") or {})

    service_data.pop("rgb_color", None)
    service_data.pop("color_temp", None)
    service_data["hs_color"] = hs

    arguments["service_data"] = service_data

    return arguments


# =============================================================
# CONTEXTUELE VERWIJZING-COPILOOT
#
# Na een geslaagde HA-bediening wordt de laatst gebruikte entity
# in de context onthouden (last_ha_entity/domain). Een opvolgende
# opdracht die met "hem", "haar", "het", "deze lamp", "die lamp",
# "dat apparaat", enz. verwijst, wordt hier deterministisch aan die
#zelfde entity gekoppeld. Dit werkt voor álle HA-apparaten (niet
# alleen lampen) en gebruikt geen hardcoded entity_ids: alles komt
# uit de bestaande context/memory.
# =============================================================

_HA_REF_TOKENS = frozenset({
    "hem", "haar", "het", "deze", "die", "dat",
    # informele samentrekkingen van "zet/doe/maak + hem"
    "zetum", "doeum", "makum", "maakum",
    "zet'um", "doe'um", "maak'um",
    "zet'em", "doe'em", "maak'em", "ze'um",
})

_HA_REF_PHRASES = (
    "deze lamp", "die lamp", "die lampen", "deze lampen",
    "dat apparaat", "het apparaat", "dat ding", "het ding",
    "die stekker", "die sensor", "die thermostaat", "die ventilator",
    "deze stekker", "deze sensor", "deze thermostaat",
    "dat rolluik", "dat licht", "dat lampje",
)


def has_ha_reference(text):

    """
    Geeft True als de opdracht verwijst naar een eerder HA-apparaat
    ("hem", "haar", "het", "deze lamp", "die lamp", "dat apparaat",
    enz.).
    """

    lower = _normalize_text(text)

    if not lower:
        return False

    for phrase in _HA_REF_PHRASES:
        if phrase in lower:
            return True

    tokens = set(re.findall(r"\b\w+\b", lower))

    return bool(tokens & _HA_REF_TOKENS)


def is_ha_device_action(text):

    """
    Geeft True als de opdracht een HA-apparaat-actie beschrijft:
    een kleurnaam, dimmen (helderheid/%), aan/uit, of
    kleurtemperatuur ("warmer"/"koeler"). Gebruikt om verwijzingen
    ("maak hem groen", "zet hem op 30%", "doe hem uit", "maak hem
    warmer") naar de HA-route te sturen in plaats van naar PC-programma's.
    """

    lower = _normalize_text(text)

    if not lower:
        return False

    if extract_color_hs(lower)[0] is not None:
        return True

    if "%" in lower or "procent" in lower or "helderheid" in lower:
        return True

    if re.search(r"\b(aan|uit)\b", lower):
        return True

    if re.search(r"\b(warmer|koeler|kouder|warm|koel)\b", lower):
        return True

    return False


def apply_context_copilot(arguments, question, last_ha):

    """
    Koppelt een contextuele verwijzing aan de laatst gebruikte
    HA-entity.

    Alleen als:
      - er een laatst gebruikte HA-entity bekend is (last_ha), én
      - de opdracht een verwijzing bevat ("hem", "die lamp", ...),
    wordt entity_id en domain ingesteld op die bekende entity.
    Een expliciete, anders genoemde device wordt nooit overschreven.
    """

    if not last_ha:
        return arguments

    entity = last_ha.get("entity_id")
    domain = last_ha.get("domain")

    if not entity or not domain:
        return arguments

    if not has_ha_reference(question):
        return arguments

    arguments = dict(arguments or {})

    arguments["entity_id"] = entity
    arguments["domain"] = domain

    return arguments


# =============================================================
# Health check
# =============================================================

def ha_health_check():

    """
    Controeft of Home Assistant bereikbaar is.

    Geeft een korte NL-tekst terug.
    """

    if not _config_ok():
        return "Home Assistant is niet geconfigureerd (HOME_ASSISTANT_URL/TOKEN ontbreekt)."

    ok, data = _ha_get("/api/")

    if not ok:
        return data

    return "Home Assistant is bereikbaar."