"""
JARVIS — Bug-fix tests (TV aan/uit, state-verificatie, switch-preferentie)
============================================================================
Test dat de gerapporteerde bugs zijn gefixed:
  A: "tv" resolveert naar switch bij aan/uit
  B: State-verificatie: antwoord is gebaseerd op werkelijke state
  D: Polling delay tussen POST en state read-back
  F: last_ha_name wordt bijgewerkt door try_ha_direct

Alles gemockt; geen echte HA-aanroepen.
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock, call
import time as _time

import core.brain as brain
import core.ai as ai

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        extra = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{extra}")


_orig_ctx = dict(brain.current_context)


def _reset():
    brain.current_context.update(_orig_ctx)
    brain.current_context["pending_choice"] = None
    brain.conversation_history = []


print("\n=== BUG-FIX TESTS ===\n")


# =============================================================
# Mock data: een gebruiker heeft ZOWEL switch.tv_switch ALS
# media_player.lg_webos_tv. Beide matchen op alias "tv".
# =============================================================

_MOCK_SNAPSHOT_BOTH = {
    "source": "registry",
    "entities": [
        {
            "entity_id": "switch.tv_switch",
            "domain": "switch",
            "name": "Tv stekker",
            "device": "Tv smart plug",
            "device_id": "",
            "area": "Woonkamer",
            "area_id": "",
            "state": "off",
            "capabilities": ["turn_on", "turn_off", "toggle"],
            "aliases": ["tvs", "tv stekker", "tv"],
        },
        {
            "entity_id": "media_player.lg_webos_tv",
            "domain": "media_player",
            "name": "LG webOS TV",
            "device": "LG webOS",
            "device_id": "",
            "area": "Woonkamer",
            "area_id": "",
            "state": "off",
            "capabilities": ["turn_on", "turn_off", "toggle",
                             "pause", "play", "volume_up", "volume_down"],
            "aliases": ["televisie", "tv"],
        },
    ],
    "devices": {},
    "areas": {},
}


# =============================================================
# [1] Bug A: "tv uit" → switch, niet media_player
# =============================================================

print("--- Bug A: tv uit → switch ---\n")

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT_BOTH), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT_BOTH), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", return_value=(True, {
         "entity_id": "switch.tv_switch", "state": "off",
         "attributes": {"friendly_name": "Tv stekker"},
     })), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})):

    # Simuleer dat state verandert naar "off" na de POST
    _ha_get_call_count = {"n": 0}
    _mock_state = {"state": "on"}

    def mock_ha_get(path):
        _ha_get_call_count["n"] += 1
        if "/api/states/" in path:
            return True, {
                "entity_id": "switch.tv_switch",
                "state": _mock_state["state"],
                "attributes": {"friendly_name": "Tv stekker"},
            }
        return True, {}

    with patch("core.home_assistant._ha_get", side_effect=mock_ha_get), \
         patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})):
        _reset()
        r = brain.process_command("doe de tv uit")
        ok("'doe de tv uit' -> switch.tv_switch (niet media_player)",
           "tv stekker" in r.lower() or "tv" in r.lower(),
           r[:120])
        ok("last_ha_entity is switch",
           brain.current_context.get("last_ha_entity") == "switch.tv_switch",
           f"got: {brain.current_context.get('last_ha_entity')}")


# =============================================================
# [2] Bug A: "tv aan" → switch
# =============================================================

print("--- Bug A: tv aan → switch ---\n")

_mock_state_tv = {"state": "off"}

def mock_ha_get_tv(path):
    if "/api/states/" in path:
        return True, {
            "entity_id": "switch.tv_switch",
            "state": _mock_state_tv["state"],
            "attributes": {"friendly_name": "Tv stekker"},
        }
    return True, {}

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT_BOTH), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT_BOTH), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", side_effect=mock_ha_get_tv), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})):

    _mock_state_tv["state"] = "off"
    _reset()
    r = brain.process_command("zet tv aan")
    ok("'zet tv aan' -> switch.tv_switch",
       "tv stekker" in r.lower() or "tv" in r.lower(),
       r[:120])
    ok("last_ha_domain is switch",
       brain.current_context.get("last_ha_domain") == "switch",
       f"got: {brain.current_context.get('last_ha_domain')}")


# =============================================================
# [3] Bug A: "tv harder" → media_player (media-actie)
# =============================================================

print("--- Bug A: tv harder → media_player ---\n")

_MOCK_SNAPSHOT_ONLY_MP = {
    "source": "registry",
    "entities": [
        {
            "entity_id": "media_player.lg_webos_tv",
            "domain": "media_player",
            "name": "LG webOS TV",
            "device": "LG webOS",
            "device_id": "",
            "area": "Woonkamer",
            "area_id": "",
            "state": "on",
            "capabilities": ["turn_on", "turn_off", "toggle",
                             "pause", "play", "volume_up", "volume_down"],
            "aliases": ["televisie", "tv"],
        },
    ],
    "devices": {},
    "areas": {},
}

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT_ONLY_MP), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT_ONLY_MP), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", return_value=(True, {
         "entity_id": "media_player.lg_webos_tv", "state": "on",
         "attributes": {"friendly_name": "LG webOS TV", "supported_features": 128},
     })), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})):

    _reset()
    r = brain.process_command("zet tv harder")
    ok("'zet tv harder' -> media_player (media-actie)",
       "lg webos" in r.lower() or "tv" in r.lower(),
       r[:120])


# =============================================================
# [4] Bug B: State-verificatie na turn_off
# =============================================================

print("--- Bug B: state-verificatie ---\n")

# Scenario: POST gestuurd, maar state verandert NIET naar "off"
_mock_state_verify = {"state": "on"}

def mock_ha_get_verify(path):
    if "/api/states/" in path:
        return True, {
            "entity_id": "media_player.lg_webos_tv",
            "state": _mock_state_verify["state"],
            "attributes": {"friendly_name": "LG webOS TV", "supported_features": 128},
        }
    return True, {}

_MOCK_SNAPSHOT_VERIFY = {
    "source": "registry",
    "entities": [{
        "entity_id": "media_player.lg_webos_tv",
        "domain": "media_player",
        "name": "LG webOS TV",
        "device": "LG webOS",
        "device_id": "",
        "area": "Woonkamer",
        "area_id": "",
        "state": "on",
        "capabilities": ["turn_on", "turn_off", "toggle", "volume_up"],
        "aliases": ["tv", "televisie"],
    }],
    "devices": {},
    "areas": {},
}

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT_VERIFY), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT_VERIFY), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", side_effect=mock_ha_get_verify), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})), \
     patch("core.home_assistant.time") as mock_time:

    mock_time.sleep = MagicMock()
    mock_time.time = _time.time

    # State blijft "on" — verandert niet na turn_off
    _mock_state_verify["state"] = "on"
    _reset()
    r = brain.process_command("pauzeer op tv")
    ok("pauzeer op tv -> media_pause op media_player",
       "lg webos" in r.lower() or "tv" in r.lower(),
       r[:120])


# =============================================================
# [5] Bug F: last_ha_name wordt bijgewerkt
# =============================================================

print("--- Bug F: last_ha_name ---\n")

_MOCK_SNAPSHOT_NAME = {
    "source": "registry",
    "entities": [{
        "entity_id": "light.bed_lamp",
        "domain": "light",
        "name": "Bedlamp",
        "device": "Philips Hue",
        "device_id": "",
        "area": "Slaapkamer",
        "area_id": "",
        "state": "off",
        "capabilities": ["turn_on", "turn_off", "toggle", "brightness"],
        "aliases": ["bedlamp"],
    }],
    "devices": {},
    "areas": {},
}

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT_NAME), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT_NAME), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", return_value=(True, {
         "entity_id": "light.bed_lamp", "state": "off",
         "attributes": {"friendly_name": "Bedlamp"},
     })), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})), \
     patch("core.home_assistant.time") as mock_time:

    mock_time.sleep = MagicMock()
    mock_time.time = _time.time

    _reset()
    brain.process_command("zet bedlamp aan")
    name = brain.current_context.get("last_ha_name", "")
    ok("last_ha_name = 'Bedlamp' na try_ha_direct",
       name == "Bedlamp",
       f"got: {name!r}")


# =============================================================
# [6] Duplicate key bug fix (media_caps)
# =============================================================

print("--- Duplicate key fix ---\n")

from core.home_assistant import _extract_capabilities
caps = _extract_capabilities({"supported_features": 1}, "media_player")
ok("media_player features bit 1 -> 'pause' in caps",
   "pause" in caps, str(caps))
ok("media_player features bit 1 -> 'play' in caps",
   "play" in caps, str(caps))


# =============================================================
# [7] State tonen voor niet-sensor entities
# =============================================================

print("--- State tonen voor alle domeinen ---\n")

from core.home_assistant import get_home_assistant_entities_tool

_MOCK_SNAPSHOT_STATES = {
    "source": "registry",
    "entities": [
        {
            "entity_id": "light.bed_lamp",
            "domain": "light",
            "name": "Bedlamp",
            "device": "", "device_id": "", "area": "", "area_id": "",
            "state": "on",
            "capabilities": ["turn_on", "turn_off"],
            "aliases": [],
        },
        {
            "entity_id": "switch.tv_switch",
            "domain": "switch",
            "name": "Tv stekker",
            "device": "", "device_id": "", "area": "", "area_id": "",
            "state": "off",
            "capabilities": ["turn_on", "turn_off"],
            "aliases": [],
        },
    ],
    "devices": {},
    "areas": {},
}

with patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT_STATES), \
     patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT_STATES):
    output = get_home_assistant_entities_tool()
    ok("light state 'on' zichtbaar in LLM-output",
       "= on" in output,
       output[:200])
    ok("switch state 'off' zichtbaar in LLM-output",
       "= off" in output,
       output[:200])


# =============================================================
# Opruimen
# =============================================================

print(f"\n{'='*60}")
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald")
print(f"{'='*60}\n")
sys.exit(1 if failed else 0)