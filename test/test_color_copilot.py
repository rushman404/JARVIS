import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.home_assistant import (
    extract_color_hs,
    apply_color_copilot,
    _COLOR_NAMES,
)
from core.ai import execute_tool, tool_matches_question

passed = 0
failed = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}")


CONTROL_TOOL = {
    "type": "function",
    "function": {
        "name": "control_home_assistant",
        "description": "Bedien een willekeurig Home Assistant apparaat.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "service": {"type": "string"},
                "entity_id": {"type": "string"},
                "service_data": {"type": "object"},
            },
            "required": ["domain", "service", "entity_id"],
        },
    },
}


def match(q, args):
    return tool_matches_question("control_home_assistant", args, q, [CONTROL_TOOL])


print("\n=== KLEUR-COPILOOT: deterministische kleurnamen -> hs_color ===\n")

ok("rood -> hue 0", extract_color_hs("maak mijn bedlamp rood") == ([0, 100], "rood"))
ok("groen -> hue 120", extract_color_hs("maak mijn bedlamp groen") == ([120, 100], "groen"))
ok("blauw -> hue 240", extract_color_hs("maak mijn bedlamp blauw") == ([240, 100], "blauw"))
ok("geel -> hue 60", extract_color_hs("maak mijn bedlamp geel") == ([60, 100], "geel"))
ok("paars -> hue 270", extract_color_hs("maak mijn bedlamp paars") == ([270, 100], "paars"))
ok("roze -> hue 330", extract_color_hs("maak mijn bedlamp roze") == ([330, 100], "roze"))
ok("oranje -> hue 30", extract_color_hs("maak mijn bedlamp oranje") == ([30, 100], "oranje"))
ok("lichtblauw heeft voorrang op blauw", extract_color_hs("lichtblauw") == ([200, 100], "lichtblauw"))
ok("geen kleurnaam -> None", extract_color_hs("zet mijn bedlamp op 50%") == (None, None))
ok("geen kleurnaam (aan) -> None", extract_color_hs("zet mijn bedlamp aan") == (None, None))
ok("geen kleurnaam (uit) -> None", extract_color_hs("doe mijn bedlamp uit") == (None, None))
ok("onbekende kleur -> None", extract_color_hs("maak mijn bedlamp neongeelgroen") == (None, None))
ok("minimaal 10 kleuren bekend", len(_COLOR_NAMES) >= 10)

print("\n=== KLEUR-COPILOOT: apply_color_copilot normaliseert arguments ===\n")

# AI levert een kleur-call ZONDER service_data (bekend model-gedrag)
args = apply_color_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
    "maak mijn bedlamp rood",
)
ok("zonder service_data krijgt alsnog hs_color",
   args.get("service_data", {}).get("hs_color") == [0, 100])
ok("service blijft turn_on", args.get("service") == "turn_on")

# AI gaf een VERKEERDE hs_color (bv. 'groen' -> [0,100]): copiloot corrigeert deterministisch
args = apply_color_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp",
     "service": "turn_on", "service_data": {"hs_color": [0, 100]}},
    "maak mijn bedlamp groen",
)
ok("verkeerde AI hs_color wordt gecorrigeerd naar groen",
   args.get("service_data", {}).get("hs_color") == [120, 100])

# AI gaf rgb_color in plaats van hs_color: copiloot vervangt door hs_color
args = apply_color_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp",
     "service": "turn_on", "service_data": {"rgb_color": [255, 0, 0]}},
    "maak mijn bedlamp blauw",
)
ok("rgb_color vervangen door hs_color (blauw)",
   args.get("service_data", {}).get("hs_color") == [240, 100]
   and "rgb_color" not in args.get("service_data", {}))

print("\n=== KLEUR-COPILOOT: bestaande functies blijven intact ===\n")

args = apply_color_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp",
     "service": "turn_on", "service_data": {"brightness_pct": 50}},
    "zet mijn bedlamp op 50% helderheid",
)
ok("helderheid-call ongewijzigd",
   args.get("service") == "turn_on"
   and args.get("service_data", {}).get("brightness_pct") == 50
   and "hs_color" not in args.get("service_data", {}))

args = apply_color_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
    "zet mijn bedlamp aan",
)
ok("aan-call ongewijzigd",
   args.get("service") == "turn_on"
   and args.get("service_data", {}) == {})

args = apply_color_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_off"},
    "doe mijn bedlamp uit",
)
ok("uit-call ongewijzigd",
   args.get("service") == "turn_off"
   and args.get("service_data", {}) == {})

print("\n=== KLEUR-COPILOOT: routing blijft acceptabel (FASE 9) ===\n")

ok("rood-call wordt geaccepteerd door tool_matches_question",
   match("maak mijn bedlamp rood",
         {"domain": "light", "entity_id": "light.bed_lamp",
          "service": "turn_on", "service_data": {"hs_color": [0, 100]}}))
ok("groen-call (met copiloot resultaat) wordt geaccepteerd",
   match("maak mijn bedlamp groen",
         {"domain": "light", "entity_id": "light.bed_lamp",
          "service": "turn_on", "service_data": {"hs_color": [120, 100]}}))
ok("paars-call wordt geaccepteerd",
   match("maak mijn bedlamp paars",
         {"domain": "light", "entity_id": "light.bed_lamp",
          "service": "turn_on", "service_data": {"hs_color": [270, 100]}}))

print("\n=== KLEUR-COPILOOT: execute_tool doorloopt de copiloot (mocked HA) ===\n")

from unittest.mock import patch, MagicMock

LIGHT_ENTITY = {
    "entity_id": "light.bed_lamp",
    "state": "on",
    "attributes": {
        "friendly_name": "Bed lamp",
        "supported_color_modes": ["color_temp", "hs"],
        "supported_features": 0,
        "brightness": 128,
    },
}


def fake_response(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else json.dumps(json_data) if json_data is not None else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    return resp


def payload_json_data(mock_post):
    call = mock_post.call_args
    if not call:
        return None
    return call.kwargs.get("json")


with patch.object(sys.modules["core.home_assistant"], "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(sys.modules["core.home_assistant"], "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    def _collect_get(url, *a, **kw):
        if "/api/states/" in str(url):
            entity_id = str(url).split("/api/states/")[-1]
            return fake_response(200, LIGHT_ENTITY) if entity_id == "light.bed_lamp" else fake_response(404, None, "Not Found")
        return fake_response(200, [LIGHT_ENTITY])

    mock_get.side_effect = _collect_get
    mock_post.return_value = fake_response(200, {})

    # AI geeft een rood-call ZONDER service_data -> copiloot vult hs_color in
    msg = execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
        "maak mijn bedlamp rood",
    )
    data = payload_json_data(mock_post)
    ok("rood zonder service_data -> hs_color [0,100] in POST",
       (data or {}).get("hs_color") == [0, 100])
    ok("rood-call bevestigd in resultaat", "hs_color 0, 100" in msg)

    mock_post.reset_mock()

    # Groen-call -> copiloot corrigeert naar hue 120
    execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.bed_lamp",
         "service": "turn_on", "service_data": {"hs_color": [0, 100]}},
        "maak mijn bedlamp groen",
    )
    data = payload_json_data(mock_post)
    ok("groen -> hs_color [120,100] in POST", (data or {}).get("hs_color") == [120, 100])

print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===\n")
sys.exit(1 if failed else 0)
