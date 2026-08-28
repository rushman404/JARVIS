import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.home_assistant import (
    has_ha_reference,
    is_ha_device_action,
    apply_context_copilot,
    apply_color_copilot,
)
from core.ai import execute_tool, current_context

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


LAST_HA = {
    "entity_id": "light.bed_lamp",
    "domain": "light",
    "name": "bedlamp",
}

print("\n=== VERWIJZING-DETECTIE: has_ha_reference ===\n")

ok("'maak hem groen' is een verwijzing", has_ha_reference("maak hem groen"))
ok("'zet haar uit' is een verwijzing", has_ha_reference("zet haar uit"))
ok("'zet het op 50%' is een verwijzing", has_ha_reference("zet het op 50%"))
ok("'deze lamp' is een verwijzing", has_ha_reference("maak deze lamp rood"))
ok("'die lamp' is een verwijzing", has_ha_reference("zet die lamp aan"))
ok("'dat apparaat' is een verwijzing", has_ha_reference("doe dat apparaat uit"))
ok("'de woonkamerlamp' is GEEN verwijzing", not has_ha_reference("maak de woonkamerlamp groen"))
ok("'bedlamp' alleen is GEEN verwijzing", not has_ha_reference("zet mijn bedlamp aan"))

print("\n=== VERWIJZING-DETECTIE: is_ha_device_action ===\n")

ok("kleurnaam is HA-actie", is_ha_device_action("maak hem groen"))
ok("helderheid is HA-actie", is_ha_device_action("zet hem op 50%"))
ok("uit is HA-actie", is_ha_device_action("doe hem uit"))
ok("aan is HA-actie", is_ha_device_action("zet hem aan"))
ok("procent is HA-actie", is_ha_device_action("zet haar op 30 procent"))
ok("'sluit hem' is GEEN open/uit/kleur HA-actie", not is_ha_device_action("sluit het programma"))

print("\n=== VERWIJZING-COPILOOT: apply_context_copilot ===\n")

# AI geeft een vaag/leeg entity_id bij een verwijzing -> copiloot zet last_ha
args = apply_context_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
    "maak hem groen",
    LAST_HA,
)
ok("'hem groen' -> entity light.bed_lamp",
   args.get("entity_id") == "light.bed_lamp" and args.get("domain") == "light")

args = apply_context_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
    "zet haar op 50%",
    LAST_HA,
)
ok("'haar op 50%' -> entity light.bed_lamp", args.get("entity_id") == "light.bed_lamp")

args = apply_context_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_off"},
    "doe dat apparaat uit",
    LAST_HA,
)
ok("'dat apparaat uit' -> entity light.bed_lamp", args.get("entity_id") == "light.bed_lamp")

# Expliciet ander apparaat -> NIET overschrijven
args = apply_context_copilot(
    {"domain": "light", "entity_id": "light.woonkamer", "service": "turn_on"},
    "maak de woonkamerlamp groen",
    LAST_HA,
)
ok("expliciete woonkamerlamp wordt niet overschreven",
   args.get("entity_id") == "light.woonkamer")

# Geen verwijzing -> ongewijzigd
args = apply_context_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
    "zet mijn bedlamp op 50%",
    LAST_HA,
)
ok("expliciete bedlamp-opdracht wordt niet overschreven",
   args.get("entity_id") == "light.bed_lamp")

# Geen last_ha -> ongewijzigd
args = apply_context_copilot(
    {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
    "maak hem groen",
    {},
)
ok("zonder last_ha geen overschrijving", args.get("entity_id") == "light.bed_lamp")

print("\n=== VERWIJZING + KLEUR: copiloten werken samen ===\n")

combined = apply_color_copilot(
    apply_context_copilot(
        {"entity_id": "light.x", "service": "turn_on"},
        "maak hem groen",
        LAST_HA,
    ),
    "maak hem groen",
)
ok("referentie + kleur -> entity bedlamp en hs_color groen",
   combined.get("entity_id") == "light.bed_lamp"
   and combined.get("service") == "turn_on"
   and combined.get("service_data", {}).get("hs_color") == [120, 100])

print("\n=== VERWIJZING-COPILOOT: execute_tool full flow (mocked HA, last_ha gezet) ===\n")

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


# Zet last_ha in de context (zoals na "zet mijn bedlamp aan")
update_ctx = {}
current_context["last_ha_entity"] = "light.bed_lamp"
current_context["last_ha_domain"] = "light"
current_context["last_ha_name"] = "bedlamp"

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

    # "maak hem groen" -> AI geeft zelfs een fout entity_id; copiloot fixt naar bedlamp + groen
    result = execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.bedroom_lamp",
         "service": "turn_on", "service_data": {"hs_color": [0, 100]}},
        "maak hem groen",
    )
    data = payload_json_data(mock_post)
    ok("'hem groen' -> POST op light.bed_lamp met hs_color [120,100]",
       (data or {}).get("entity_id") == "light.bed_lamp"
       and data.get("hs_color") == [120, 100])

    mock_post.reset_mock()

    # "zet hem op 30%" -> helderheid, entity uit context, geen kleur
    execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on",
         "service_data": {"brightness_pct": 30}},
        "zet hem op 30%",
    )
    data = payload_json_data(mock_post)
    ok("'hem op 30%' -> brightness_pct 30 op light.bed_lamp",
       (data or {}).get("entity_id") == "light.bed_lamp"
       and data.get("brightness_pct") == 30
       and "hs_color" not in (data or {}))

    mock_post.reset_mock()

    # "doe hem uit" -> turn_off op light.bed_lamp
    execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_off"},
        "doe hem uit",
    )
    data = payload_json_data(mock_post)
    ok("'hem uit' -> turn_off op light.bed_lamp",
       (data or {}).get("entity_id") == "light.bed_lamp")

    mock_post.reset_mock()

    # "zet hem aan" -> turn_on op light.bed_lamp
    execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on"},
        "zet hem aan",
    )
    data = payload_json_data(mock_post)
    ok("'hem aan' -> turn_on op light.bed_lamp",
       (data or {}).get("entity_id") == "light.bed_lamp")

print("\n=== VERWIJZING-COPILOOT: deterministische route in brain (try_ha_reference) ===\n")

from core.brain import try_ha_reference
from unittest.mock import patch as _patch

import core.brain as brain_mod

current_context["last_ha_entity"] = "light.bed_lamp"
current_context["last_ha_domain"] = "light"

with _patch.object(sys.modules["core.home_assistant"], "HOME_ASSISTANT_URL", "http://ha:8123"), \
     _patch.object(sys.modules["core.home_assistant"], "HOME_ASSISTANT_TOKEN", "tok123"), \
     _patch("core.home_assistant.requests.get") as mock_get, \
     _patch("core.home_assistant.requests.post") as mock_post:

    mock_get.return_value = fake_response(200, LIGHT_ENTITY)
    mock_post.return_value = fake_response(200, {})

    out = try_ha_reference("maak hem groen")
    ok("'maak hem groen' -> deterministisch resultaat", out is not None and "hs_color" in out)
    data = payload_json_data(mock_post)
    ok("'maak hem groen' -> POST light.bed_lamp + hs_color [120,100]",
       (data or {}).get("entity_id") == "light.bed_lamp" and data.get("hs_color") == [120, 100])

    mock_post.reset_mock()
    out = try_ha_reference("zet hem op 30%")
    data = payload_json_data(mock_post)
    ok("'zet hem op 30%' -> brightness_pct 30",
       (data or {}).get("brightness_pct") == 30)

    mock_post.reset_mock()
    out = try_ha_reference("doe hem uit")
    data = payload_json_data(mock_post)
    ok("'doe hem uit' -> turn_off", out is not None and "uit" in out)
    ok("'doe hem uit' -> POST entity light.bed_lamp",
       (data or {}).get("entity_id") == "light.bed_lamp")

    # Zonder last_ha (context leeg) -> None
    current_context["last_ha_entity"] = ""
    current_context["last_ha_domain"] = ""
    out = try_ha_reference("doe hem uit")
    ok("zonder last_ha -> None", out is None)
    current_context["last_ha_entity"] = "light.bed_lamp"
    current_context["last_ha_domain"] = "light"

print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===\n")
sys.exit(1 if failed else 0)
