import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import (
    tool_matches_question,
    _smart_home_domain,
)

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


print("\n=== FIX B: tool_matches_question() accepteert HA helderheid/kleur ===\n")

ok(
    "helderheid-call wordt geaccepteerd",
    match("zet mijn bedlamp op 50% helderheid",
          {"domain": "light", "entity_id": "light.bed_lamp",
           "service": "turn_on", "service_data": {"brightness_pct": 50}}),
)
ok(
    "kleur-call (rood) wordt geaccepteerd",
    match("maak mijn bedlamp rood",
          {"domain": "light", "entity_id": "light.bed_lamp",
           "service": "turn_on", "service_data": {"hs_color": [0, 100]}}),
)
ok(
    "willekeurige kleurnaam (paars) wordt geaccepteerd",
    match("maak mijn bedlamp paars",
          {"domain": "light", "entity_id": "light.bed_lamp",
           "service": "turn_on", "service_data": {"hs_color": [270, 100]}}),
)
ok(
    "warmer wordt geaccepteerd",
    match("maak het licht warmer",
          {"domain": "light", "entity_id": "light.bed_lamp",
           "service": "turn_on", "service_data": {"color_temp": 3000}}),
)
ok(
    "koeler wordt geaccepteerd",
    match("maak het licht koeler",
          {"domain": "light", "entity_id": "light.woonkamer",
           "service": "turn_on", "service_data": {"color_temp": 6000}}),
)
ok(
    "aan blijft geaccepteerd",
    match("zet mijn bedlamp aan",
          {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"}),
)
ok(
    "uit blijft geaccepteerd",
    match("doe mijn bedlamp uit",
          {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_off"}),
)


print("\n=== FIX B: _smart_home_domain() generieke domeinen ===\n")

ok("light is smart-home domein", _smart_home_domain("light"))
ok("switch is smart-home domein", _smart_home_domain("switch"))
ok("cover is smart-home domein", _smart_home_domain("cover"))
ok("climate is smart-home domein", _smart_home_domain("climate"))
ok("media_player is smart-home domein", _smart_home_domain("media_player"))
ok("open_program is GEEN smart-home domein", not _smart_home_domain("open_program"))
ok("lege string is GEEN smart-home domein", not _smart_home_domain(""))
ok("None is GEEN smart-home domein", not _smart_home_domain(None))


print("\n=== FIX B: mismatching entity/domain wordt NIET geforceerd ===\n")

# entity_id-domein verschilt van domain -> geen voorrang, valt terug op overlap
# (hier geen overlap -> False). Dit voorkomt dat een foute call wordt doorgelaten.
ok(
    "domain 'light' vs entity 'switch.x' geeft geen HA-voorrang",
    not match("zet mijn bedlamp aan",
              {"domain": "light", "entity_id": "switch.bed_lamp", "service": "turn_on"}),
)


print("\n=== E: home_assistant.py geeft service_data correct door (geen wijziging nodig) ===\n")

from unittest.mock import patch, MagicMock
import json
import core.home_assistant as ha


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
    """Haal de json-payload uit de laatste requests.post-aanroep."""
    call = mock_post.call_args
    if not call:
        return None
    return call.kwargs.get("json")


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


with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    mock_get.return_value = fake_response(200, LIGHT_ENTITY)
    mock_post.return_value = fake_response(200, {})

    ha.control_home_assistant_tool(
        "light", "turn_on", "light.bed_lamp",
        {"brightness_pct": 50},
    )
    data = payload_json_data(mock_post)
    ok("brightness_pct=50 in POST-payload",
       (data or {}).get("entity_id") == "light.bed_lamp" and data.get("brightness_pct") == 50)

    mock_post.reset_mock()
    ha.control_home_assistant_tool(
        "light", "turn_on", "light.bed_lamp",
        {"hs_color": [0, 100]},
    )
    data = payload_json_data(mock_post)
    ok("hs_color in POST-payload", (data or {}).get("hs_color") == [0, 100])

    mock_post.reset_mock()
    ha.control_home_assistant_tool(
        "light", "turn_on", "light.bed_lamp",
        {"rgb_color": [255, 0, 0]},
    )
    data = payload_json_data(mock_post)
    ok("rgb_color in POST-payload", (data or {}).get("rgb_color") == [255, 0, 0])

    mock_post.reset_mock()
    ha.control_home_assistant_tool(
        "light", "turn_on", "light.bed_lamp",
        {"color_temp": 3000},
    )
    data = payload_json_data(mock_post)
    ok("color_temp in POST-payload", (data or {}).get("color_temp") == 3000)


print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===\n")
sys.exit(1 if failed else 0)
