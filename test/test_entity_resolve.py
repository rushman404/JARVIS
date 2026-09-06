import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.home_assistant import resolve_entity_id

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


# Realistische, gecontroleerde set (vergelijkbaar met live HA-data).
ENTITIES = [
    {"entity_id": "light.bed_lamp", "domain": "light", "name": "Bed lamp"},
    {"entity_id": "light.woonkamer", "domain": "light", "name": "Woonkamer"},
    {"entity_id": "light.kitchen_kitchen", "domain": "light", "name": "Kitchen"},
    {"entity_id": "light.eethoek_eethoek", "domain": "light", "name": "Eethoek"},
    {"entity_id": "light.bar_bar", "domain": "light", "name": "Bar"},
    {"entity_id": "light.eethoek_hue_ambiance_spot_6", "domain": "light",
     "name": "Eethoek Hue ambiance spot 6"},
    {"entity_id": "light.bank_hue_ambiance_spot_1", "domain": "light",
     "name": "Bank Hue ambiance spot 1"},
    {"entity_id": "light.kleine_spotjes", "domain": "light", "name": "Kleine spotjes"},
]

print("\n=== ENTITY-RESOLUTIE: exact geldige entity_ids worden behouden ===\n")

r = resolve_entity_id("light.bed_lamp", None, ENTITIES)
ok("light.bed_lamp -> exact, ongewijzigd", r[0] == "light.bed_lamp" and r[1] == "exact")

r = resolve_entity_id("light.kleine_spotjes", None, ENTITIES)
ok("light.kleine_spotjes -> exact, ongewijzigd", r[0] == "light.kleine_spotjes" and r[1] == "exact")

print("\n=== ENTITY-RESOLUTIE: duidelijke fuzzy matches ===\n")

r = resolve_entity_id("light.woonkamer_lamp", None, ENTITIES)
ok("light.woonkamer_lamp -> light.woonkamer",
   r[0] == "light.woonkamer" and r[1] == "resolved")

r = resolve_entity_id("light.bar_light", None, ENTITIES)
ok("light.bar_light -> light.bar_bar",
   r[0] == "light.bar_bar" and r[1] == "resolved")

r = resolve_entity_id("light.bar_lamp", None, ENTITIES)
ok("light.bar_lamp -> light.bar_bar",
   r[0] == "light.bar_bar" and r[1] == "resolved")

r = resolve_entity_id("light.kitchen_lamp", None, ENTITIES)
ok("light.kitchen_lamp -> light.kitchen_kitchen",
   r[0] == "light.kitchen_kitchen" and r[1] == "resolved")

print("\n=== ENTITY-RESOLUTIE: twijfelachtige matches (geen uitvoering) ===\n")

r = resolve_entity_id("light.eethoek_lamp", None, ENTITIES)
ok("light.eethoek_lamp -> ambiguous (meerdere eethoek-lampen)",
   r[0] is None and r[1] == "ambiguous")

print("\n=== ENTITY-RESOLUTIE: geen match ===\n")

r = resolve_entity_id("light.living_room_lamp", None, ENTITIES)
ok("light.living_room_lamp -> none", r[0] is None and r[1] == "none")

r = resolve_entity_id("light.slaapkamerlamp", None, ENTITIES)
ok("light.slaapkamerlamp -> none", r[0] is None and r[1] == "none")

r = resolve_entity_id("light.lamp", None, ENTITIES)
ok("'light.lamp' (enkel generiek) -> none", r[0] is None and r[1] == "none")

print("\n=== ENTITY-RESOLUTIE: domein-scoping en edge cases ===\n")

# domeinpri-refix in het opgegeven id bepaalt de scope
r = resolve_entity_id("woonkamer_lamp", None, ENTITIES)
ok("zonder domeinprefix maar met unieke kern -> resolved",
   r[0] == "light.woonkamer" and r[1] == "resolved")

r = resolve_entity_id("", None, ENTITIES)
ok("leeg entity_id -> none", r[0] is None and r[1] == "none")

r = resolve_entity_id("light.bed_lamp", None, [])
ok("geen bekende entities -> none met duidelijke melding",
   r[0] is None and r[1] == "none" and r[2].lower().find("geen") != -1)

# alleen onderscheidende kern telt; een enkel generiek token lost NIET op
r = resolve_entity_id("light.lamp", None, ENTITIES)
ok("enkel generiek token 'lamp' lost niet op", r[1] == "none")

print("\n=== ENTITY-RESOLUTIE: integratie in execute_tool (mocked HA) ===\n")

import json
from unittest.mock import patch, MagicMock
from core.ai import execute_tool
import sys as _sys

def fake_response(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else json.dumps(json_data) if json_data is not None else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    return resp

def states_response():
    return json.dumps([
        {"entity_id": "light.bed_lamp", "state": "on",
         "attributes": {"friendly_name": "Bed lamp",
                        "supported_color_modes": ["color_temp", "hs"]}},
        {"entity_id": "light.woonkamer", "state": "off",
         "attributes": {"friendly_name": "Woonkamer",
                        "supported_color_modes": ["color_temp"]}},
    ])

with patch.object(_sys.modules["core.home_assistant"], "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(_sys.modules["core.home_assistant"], "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    # /api/states levert de echte entities (dubbel gebruik: discovery + resolve)
    def fake_get(url, *a, **kw):
        if "/api/config/entity_registry" in str(url) or "/api/config/device_registry" in str(url) or "/api/config/area_registry" in str(url):
            return fake_response(404, [])
        if "/api/states/" in str(url):
            entity_id = str(url).split("/api/states/")[-1]
            for ent in [{"entity_id": "light.bed_lamp", "state": "on",
                         "attributes": {"friendly_name": "Bed lamp",
                                        "supported_color_modes": ["color_temp", "hs"]}},
                        {"entity_id": "light.woonkamer", "state": "off",
                         "attributes": {"friendly_name": "Woonkamer",
                                        "supported_color_modes": ["color_temp"]}}]:
                if ent["entity_id"] == entity_id:
                    return fake_response(200, ent)
            return fake_response(404, None, "Not Found")
        return fake_response(200, json.loads(states_response()))

    mock_get.side_effect = fake_get
    mock_post.return_value = fake_response(200, {})

    # AI verzint 'light.woonkamer_lamp' -> copiloot corrigeert naar light.woonkamer
    out = execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.woonkamer_lamp", "service": "turn_off"},
        "zet de woonkamerlamp uit",
    )
    data_ok = mock_post.call_args is not None
    post_payload = None
    if data_ok:
        post_payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[0]
    ok("verzonnen entity omgezet (POST op light.woonkamer)",
       data_ok and (post_payload or {}).get("entity_id") == "light.woonkamer")
    ok("geen 404-melding", out.strip() != "Kan Home Assistant niet vinden (HTTP 404).")

    mock_post.reset_mock()

    # AI verzint een niet-bestaande entity -> actie NIET uitgevoerd, duidelijke melding
    out = execute_tool(
        "control_home_assistant",
        {"domain": "light", "entity_id": "light.slaapkamerlamp", "service": "turn_off"},
        "zet de slaapkamerlamp uit",
    )
    ok("niet-bestaande entity -> actie niet uitgevoerd met melding",
       mock_post.call_args is None and "niet uitgevoerd" in out)

print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===\n")
sys.exit(1 if failed else 0)
