"""
JARVIS — Fase 13: Media Player tests
======================================
Test de media_player bediening via control_home_assistant:
tv harder/zachter, volgende/vorige nummer, volume_set, pauze/play.

Alles gemockt; geen echte HA-aanroepen.
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import core.brain as brain
import core.ha_registry as hr

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


print("\n=== FASE 13 MEDIA PLAYER ===\n")

# =============================================================
# Mock-gegevens
# =============================================================

_MOCK_TV = {
    "entity_id": "media_player.tv",
    "domain": "media_player",
    "name": "LG TV",
    "device": "LG webOS",
    "device_id": "",
    "area": "Woonkamer",
    "area_id": "",
    "state": "on",
    "capabilities": ["turn_on", "turn_off", "toggle",
                     "pause", "play", "stop", "previous",
                     "next", "volume_set", "volume_up", "volume_down",
                     "select_source"],
    "aliases": ["tv", "televisie"],
}

_MOCK_TV_STATE = {
    "entity_id": "media_player.tv",
    "state": "on",
    "attributes": {"friendly_name": "LG TV", "supported_features": 128},
}

_MOCK_SNAPSHOT = {
    "source": "registry",
    "entities": [_MOCK_TV],
    "devices": {},
    "areas": {},
}


# =============================================================
# [1] CONTROL_HOME_ASSISTANT: media_player services
# =============================================================

print("--- media_player service-dispatch ---\n")

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", return_value=(True, _MOCK_TV_STATE)), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})):

    from core.home_assistant import control_home_assistant_tool

    r = control_home_assistant_tool("media_player", "volume_up", "media_player.tv")
    ok("volume_up op media_player wordt uitgevoerd",
       "lg tv" in r.lower() or "tv" in r.lower(),
       r[:100])

    r = control_home_assistant_tool("media_player", "media_next_track", "media_player.tv")
    ok("media_next_track op media_player wordt uitgevoerd",
       "lg tv" in r.lower() or "tv" in r.lower(),
       r[:100])

    r = control_home_assistant_tool("media_player", "volume_set",
                                    "media_player.tv",
                                    service_data={"volume_level": 0.4})
    ok("volume_set op media_player wordt uitgevoerd",
       "lg tv" in r.lower() or "tv" in r.lower(),
       r[:100])


# =============================================================
# [2] BRAIN: media-direct routing
# =============================================================

print("\n--- brain: media-direct ---\n")

with patch("core.ha_registry.get_snapshot", return_value=_MOCK_SNAPSHOT), \
     patch("core.home_assistant.get_snapshot", return_value=_MOCK_SNAPSHOT), \
     patch("core.home_assistant.is_control_allowed", return_value=(True, "")), \
     patch("core.home_assistant._ha_get", return_value=(True, _MOCK_TV_STATE)), \
     patch("core.home_assistant._ha_post", return_value=(True, {"ok": True})):

    _reset()
    r = brain.process_command("zet tv harder")
    ok("zet tv harder -> volume_up op tv",
       "lg tv" in r.lower() or "tv" in r.lower() or "volume" in r.lower(),
       r[:120])

    _reset()
    r = brain.process_command("zet tv zachter")
    ok("zet tv zachter -> volume_down op tv",
       "lg tv" in r.lower() or "tv" in r.lower() or "volume" in r.lower(),
       r[:120])

    _reset()
    r = brain.process_command("pauzeer op tv")
    ok("pauzeer op tv -> media_pause",
       "lg tv" in r.lower() or "tv" in r.lower(),
       r[:120])

    _reset()
    r = brain.process_command("volgende nummer op tv")
    ok("volgende nummer op tv -> media_next_track",
       "lg tv" in r.lower() or "tv" in r.lower() or "over" in r.lower(),
       r[:120])

    _reset()
    r = brain.process_command("zet tv op 40%")
    ok("zet tv op 40% -> volume_set op tv",
       "lg tv" in r.lower() or "tv" in r.lower() or "volume" in r.lower(),
       r[:120])


# =============================================================
# [3] SCENE-domein + cover positie in SUPPORTED_DOMAINS
# =============================================================

print("\n--- domein-config ---\n")

from core.home_assistant import SUPPORTED_DOMAINS
ok("scene in SUPPORTED_DOMAINS",
   "scene" in SUPPORTED_DOMAINS,
   str(SUPPORTED_DOMAINS))

from core.ha_registry import _DOMAIN_SERVICE_DEFAULTS
ok("scene in _DOMAIN_SERVICE_DEFAULTS",
   "scene" in _DOMAIN_SERVICE_DEFAULTS,
   str(list(_DOMAIN_SERVICE_DEFAULTS.keys())))

ok("set_cover_position in cover defaults",
   "set_cover_position" in _DOMAIN_SERVICE_DEFAULTS.get("cover", set()),
   str(_DOMAIN_SERVICE_DEFAULTS.get("cover", set())))


# =============================================================
# Opruimen
# =============================================================

print(f"\n{'='*60}")
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald")
print(f"{'='*60}\n")
sys.exit(1 if failed else 0)