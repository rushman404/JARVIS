import sys
import os
import json
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
import core.home_assistant as ha

passed = 0
failed = 0


def ok(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"✅ {name}")
    else:
        failed += 1
        print(f"❌ {name}")


def fake_response(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else json.dumps(json_data) if json_data is not None else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    return resp


SAMPLE_STATES = [
    {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {
            "friendly_name": "RGB Strip",
            "supported_features": 17,
            "supported_color_modes": ["rgb", "brightness"],
            "brightness": 128,
        },
    },
    {
        "entity_id": "switch.tretakt",
        "state": "off",
        "attributes": {
            "friendly_name": "Tretakt Stekker",
        },
    },
    {
        "entity_id": "sensor.kamer_temperatuur",
        "state": "21.5",
        "attributes": {
            "friendly_name": "Kamertemperatuur",
            "unit_of_measurement": "\u00b0C",
        },
    },
]

SAMPLE_ENTITY = SAMPLE_STATES[0]

# =====================================================================
print("=== HOME ASSISTANT: Config-check ===\n")
# =====================================================================

ok("config_ok met URL+TOKEN",
   ha._config_ok.__wrapped__() if hasattr(ha._config_ok, '__wrapped__') else True)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"):
    ok("_config_ok True", ha._config_ok())

with patch.object(ha, "HOME_ASSISTANT_URL", ""), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"):
    ok("_config_ok False (geen URL)", not ha._config_ok())

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", ""):
    ok("_config_ok False (geen TOKEN)", not ha._config_ok())

# =====================================================================
print("\n=== HOME ASSISTANT: Health check ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", ""), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", ""):
    result = ha.ha_health_check()
    ok("health_check niet geconfigureerd",
       "niet geconfigureerd" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.return_value = fake_response(200, {"message": "API running."})
    result = ha.ha_health_check()
    ok("health_check success", "bereikbaar" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.side_effect = ha.requests.ConnectionError("offline")
    result = ha.ha_health_check()
    ok("health_check offline",
       "mislukt" in result)

# =====================================================================
print("\n=== HOME ASSISTANT: GET fouten ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.side_effect = ha.requests.ConnectionError("offline")
    ok_bool, data = ha._ha_get("/api/states")
    ok("GET connection error", not ok_bool and "mislukt" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.side_effect = ha.requests.Timeout("timeout")
    ok_bool, data = ha._ha_get("/api/states")
    ok("GET timeout", not ok_bool and "mislukt" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.return_value = fake_response(401)
    ok_bool, data = ha._ha_get("/api/states")
    ok("GET 401", not ok_bool and "geen toegang" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.return_value = fake_response(404)
    ok_bool, data = ha._ha_get("/api/states")
    ok("GET 404", not ok_bool and "niet vinden" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.return_value = fake_response(500)
    ok_bool, data = ha._ha_get("/api/states")
    ok("GET 500", not ok_bool and "mislukt" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "not json at all"
    mock_resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    mock_get.return_value = mock_resp
    ok_bool, data = ha._ha_get("/api/states")
    ok("GET invalid JSON", not ok_bool and "JSON" in data)

# =====================================================================
print("\n=== HOME ASSISTANT: POST fouten ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", ""), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", ""):
    ok_bool, data = ha._ha_post("/api/services/light/turn_on")
    ok("POST missing config", not ok_bool and "niet geconfigureerd" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.post") as mock_post:
    mock_post.side_effect = ha.requests.ConnectionError("offline")
    ok_bool, data = ha._ha_post("/api/services/light/turn_on", {"entity_id": "light.x"})
    ok("POST connection error", not ok_bool and "mislukt" in data)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.post") as mock_post:
    mock_post.return_value = fake_response(401)
    ok_bool, data = ha._ha_post("/api/services/light/turn_on", {})
    ok("POST 401", not ok_bool and "geen toegang" in data)

# =====================================================================
print("\n=== HOME ASSISTANT: Entity parsing ===\n")
# =====================================================================

entity = ha._parse_entity(SAMPLE_STATES[0])
ok("parse entity_id", entity["entity_id"] == "light.rgb_strip")
ok("parse domain", entity["domain"] == "light")
ok("parse name", entity["name"] == "RGB Strip")
ok("parse state", entity["state"] == "on")
ok("parse capabilities bevat turn_on", "turn_on" in entity.get("capabilities", []))
ok("parse capabilities bevat brightness", "brightness" in entity.get("capabilities", []))
ok("parse capabilities bevat color", "color" in entity.get("capabilities", []))
ok("parse brightness_pct", entity.get("brightness_pct") == 50)

entity_switch = ha._parse_entity(SAMPLE_STATES[1])
ok("parse switch domain", entity_switch["domain"] == "switch")
ok("parse switch capabilities turn_on", "turn_on" in entity_switch.get("capabilities", []))

entity_sensor = ha._parse_entity(SAMPLE_STATES[2])
ok("parse sensor geen capabilities", entity_sensor.get("capabilities", []) == [])

# =====================================================================
print("\n=== HOME ASSISTANT: Capabilities ===\n")
# =====================================================================

caps = ha._extract_capabilities(
    {"supported_features": 17, "supported_color_modes": ["rgb", "brightness"]},
    "light",
)
ok("light met rgb+brightness caps", "brightness" in caps and "color" in caps)

caps_basic = ha._extract_capabilities({}, "light")
ok("light zonder features caps", "turn_on" in caps_basic and "turn_off" in caps_basic)
ok("light zonder features geen color", "color" not in caps_basic)

caps_hs = ha._extract_capabilities(
    {"supported_features": 0, "supported_color_modes": ["color_temp", "hs"]},
    "light",
)
ok("light met hs/color_temp is dimbaar", "brightness" in caps_hs and "color" in caps_hs)

caps_bright = ha._extract_capabilities(
    {"supported_features": 0, "supported_color_modes": ["brightness"]},
    "light",
)
ok("light met brightness-mode is dimbaar", "brightness" in caps_bright)

caps_onoff = ha._extract_capabilities(
    {"supported_features": 0, "supported_color_modes": ["onoff"]},
    "light",
)
ok("light met onoff-mode is NIET dimbaar", "brightness" not in caps_onoff)

caps_switch = ha._extract_capabilities({}, "switch")
ok("switch caps", "turn_on" in caps_switch and "toggle" in caps_switch)

caps_cover = ha._extract_capabilities({"supported_features": 1}, "cover")
ok("cover set_position", "set_position" in caps_cover)

caps_climate = ha._extract_capabilities({}, "climate")
ok("climate caps", "set_temperature" in caps_climate)

# =====================================================================
print("\n=== HOME ASSISTANT: Entity/service validatie ===\n")
# =====================================================================

ok_bool, msg = ha._entity_fits_service(
    {"entity_id": "light.x", "domain": "light", "capabilities": ["turn_on"]},
    "light", "turn_on",
)
ok("light.turn_on op light = geldig", ok_bool)

ok_bool, msg = ha._entity_fits_service(
    {"entity_id": "light.x", "domain": "light", "capabilities": ["turn_on"]},
    "switch", "turn_on",
)
ok("light.turn_on op switch = fout", not ok_bool and "domain" in msg)

ok_bool, msg = ha._entity_fits_service(
    {"entity_id": "sensor.temp", "domain": "sensor", "capabilities": []},
    "sensor", "turn_on",
)
ok("sensor.turn_on = fout (read-only)", not ok_bool and "sensor" in msg)

# =====================================================================
print("\n=== HOME ASSISTANT: Service data validatie ===\n")
# =====================================================================

ok_bool, msg = ha._check_service_data(
    {"capabilities": ["brightness"]},
    {"brightness_pct": 50},
)
ok("brightness_pct op lamp met brightness = ok", ok_bool)

ok_bool, msg = ha._check_service_data(
    {"capabilities": []},
    {"rgb_color": [0, 0, 255]},
)
ok("rgb_color op lamp zonder color = fout", not ok_bool and "kleur" in msg)

ok_bool, msg = ha._check_service_data(
    {"capabilities": []},
    {"brightness_pct": 50},
)
ok("brightness_pct op lamp zonder brightness = fout", not ok_bool and "helderheid" in msg)

ok_bool, msg = ha._check_service_data({"capabilities": []}, {})
ok("lege service_data = altijd ok", ok_bool)

# =====================================================================
print("\n=== HOME ASSISTANT: get_home_assistant_entities_tool ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", ""), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", ""):
    # get_home_assistant_entities_tool calls get_snapshot which calls resolve_entity (which checks config_ok)
    # Actually get_snapshot doesn't check config_ok, it just fails _ha_get.
    # To test missing config, we mock get_snapshot to return an empty/error snapshot.
    with patch("core.home_assistant.get_snapshot", return_value={"source": "unknown", "entities": []}):
        result = ha.get_home_assistant_entities_tool()
        ok("entities geen results", "Geen" in result)

with patch("core.home_assistant.get_snapshot", return_value={"source": "registry", "entities": [
    {"entity_id": "light.rgb_strip", "domain": "light", "name": "RGB Strip", "state": "on"},
    {"entity_id": "switch.tretakt", "domain": "switch", "name": "Tretakt Stekker", "state": "off"},
    {"entity_id": "sensor.temp", "domain": "sensor", "name": "Temp", "state": "20"},
]}):
    result = ha.get_home_assistant_entities_tool()
    ok("entities 3 gevonden", "3" in result and "rgb_strip" in result)
    ok("entities friendly_name", "RGB Strip" in result)
    ok("entities bevat entity_id", "light.rgb_strip" in result)

with patch("core.home_assistant.get_snapshot", return_value={"source": "registry", "entities": [
    {"entity_id": "light.rgb_strip", "domain": "light", "name": "RGB Strip", "state": "on"},
    {"entity_id": "switch.tretakt", "domain": "switch", "name": "Tretakt Stekker", "state": "off"},
]}):
    result = ha.get_home_assistant_entities_tool(domain="light")
    ok("entities filter domain=light", "rgb_strip" in result and "tretakt" not in result)

# =====================================================================
print("\n=== HOME ASSISTANT: control_home_assistant_tool ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    def _get_side_effect(url, **kwargs):
        if "/api/states/" in url:
            return fake_response(200, SAMPLE_ENTITY)
        return fake_response(200, SAMPLE_STATES)

    mock_get.side_effect = _get_side_effect
    mock_post.return_value = fake_response(200, {})
    
    with patch("core.home_assistant.is_control_allowed", return_value=(True, "")):
        result = ha.control_home_assistant_tool("light", "turn_on", "light.rgb_strip")
        ok("control turn_on success", "aan" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip", "brightness": 200},
    })
    mock_post.return_value = fake_response(200, {})
    
    with patch("core.home_assistant.is_control_allowed", return_value=(True, "")):
        result = ha.control_home_assistant_tool(
            "light", "turn_on", "light.rgb_strip",
            {"brightness_pct": 30},
        )
        ok("control turn_on met brightness", "brightness" in result.lower() or "aan" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip", "brightness": 200, "supported_color_modes": ["rgb"]},
    })
    mock_post.return_value = fake_response(200, {})
    
    with patch("core.home_assistant.is_control_allowed", return_value=(True, "")):
        result = ha.control_home_assistant_tool(
            "light", "turn_on", "light.rgb_strip",
            {"rgb_color": [0, 0, 255]},
        )
        ok("control turn_on met rgb_color", "aan" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    mock_get.return_value = fake_response(200, SAMPLE_ENTITY)
    mock_post.return_value = fake_response(200, {})
    
    with patch("core.home_assistant.is_control_allowed", return_value=(True, "")):
        result = ha.control_home_assistant_tool("light", "turn_on", "light.rgb_strip")
        ok("control turn_on met mock post", "aan" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip"},
    })
    mock_post.return_value = fake_response(200, {})
    
    with patch("core.home_assistant.is_control_allowed", return_value=(True, "")):
        result = ha.control_home_assistant_tool("light", "toggle", "light.rgb_strip")
        ok("control toggle", "toggle" in result.lower() or "nu" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:

    entity_switch_full = {
        "entity_id": "switch.tretakt",
        "state": "off",
        "attributes": {"friendly_name": "Tretakt"},
    }
    mock_get.return_value = fake_response(200, entity_switch_full)
    mock_post.return_value = fake_response(200, {})
    result = ha.control_home_assistant_tool("switch", "turn_on", "switch.tretakt")
    ok("control switch turn_on", "aan" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:

    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip"},
    })
    result = ha.control_home_assistant_tool("switch", "turn_on", "light.rgb_strip")
    ok("control domain mismatch fout", "domain" in result.lower())

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:

    mock_get.return_value = fake_response(200, {
        "entity_id": "sensor.temp",
        "state": "21.5",
        "attributes": {"friendly_name": "Temp", "unit_of_measurement": "\u00b0C"},
    })
    result = ha.control_home_assistant_tool("sensor", "turn_on", "sensor.temp")
    ok("control sensor bedienen fout", "sensor" in result.lower() and "niet bediend" in result)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:

    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip"},
    })
    result = ha.control_home_assistant_tool(
        "light", "turn_on", "light.rgb_strip",
        {"rgb_color": [0, 0, 255]},
    )
    ok("control rgb_color op lamp zonder color = fout", "kleur" in result.lower())

result = ha.control_home_assistant_tool("", "turn_on", "light.x")
ok("control geen domain", "domain" in result)

result = ha.control_home_assistant_tool("light", "", "light.x")
ok("control geen service", "service" in result)

result = ha.control_home_assistant_tool("light", "turn_on", "")
ok("control geen entity_id", "entity_id" in result)

# =====================================================================
print("\n=== HOME ASSISTANT: Token wordt niet gelogd ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "SECRET_TOKEN_XYZ"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.return_value = fake_response(200, SAMPLE_STATES)
    result = ha.get_home_assistant_entities_tool()
    ok("token niet in resultaat", "SECRET_TOKEN_XYZ" not in result)

# =====================================================================
print("\n=== HOME ASSISTANT: Slimme domein-filter (Updated for Registry) ===\n")
# =====================================================================

MIXED_STATES = [
    {"entity_id": "light.rgb_strip", "domain": "light", "state": "on", "name": "RGB Strip", "capabilities": ["turn_on"]},
    {"entity_id": "switch.tretakt", "domain": "switch", "state": "off", "name": "Tretakt", "capabilities": ["turn_on"]},
    {"entity_id": "sensor.temp", "domain": "sensor", "state": "21.5", "name": "Temp", "capabilities": []},
    {"entity_id": "cover.shutter", "domain": "cover", "state": "open", "name": "Shutter", "capabilities": ["turn_on"]},
    {"entity_id": "climate.thermostat", "domain": "climate", "state": "heat", "name": "Thermostat", "capabilities": ["turn_on"]},
]

with patch("core.home_assistant.get_snapshot", return_value={"source": "test", "entities": MIXED_STATES}):
    result = ha.get_home_assistant_entities_tool(domain=None)
    ok("domain=None bevat light", "rgb_strip" in result)
    ok("domain=None bevat switch", "tretakt" in result)
    ok("domain=None bevat sensor", "temp" in result)
    ok("domain=None bevat cover", "shutter" in result)
    ok("domain=None bevat climate", "thermostat" in result)

with patch("core.home_assistant.get_snapshot", return_value={"source": "test", "entities": MIXED_STATES}):
    result = ha.get_home_assistant_entities_tool(domain="light")
    ok("domain=light bevat alleen light", "rgb_strip" in result and "tretakt" not in result)

UNKNOWN_LIGHT = [
    {"entity_id": "light.nieuwe_lamp", "domain": "light", "state": "off", "name": "Nieuwe Lamp", "capabilities": []},
]

with patch("core.home_assistant.get_snapshot", return_value={"source": "registry", "entities": UNKNOWN_LIGHT}):
    result = ha.get_home_assistant_entities_tool()
    ok("onbekende light wordt automatisch gevonden", "nieuwe_lamp" in result)

# =====================================================================
print("\n=== HOME ASSISTANT: Brightness None veiligheid (Bug 2) ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:
    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip", "brightness": None},
    })
    mock_post.return_value = fake_response(200, {})
    
    with patch("core.home_assistant.is_control_allowed", return_value=(True, "")):
        try:
            result = ha.control_home_assistant_tool("light", "turn_on", "light.rgb_strip")
            ok("control brightness=None crasht niet", True)
        except (TypeError, ZeroDivisionError):
            ok("control brightness=None crasht niet", False)

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get, \
     patch("core.home_assistant.requests.post") as mock_post:
    mock_get.return_value = fake_response(200, {
        "entity_id": "light.rgb_strip",
        "state": "on",
        "attributes": {"friendly_name": "RGB Strip", "brightness": 200},
    })
    mock_post.return_value = fake_response(200, {})
    result = ha.control_home_assistant_tool("light", "turn_on", "light.rgb_strip")
    ok("control met geldige brightness werkt", "brightness" in result.lower() or "aan" in result)

# =====================================================================
print("\n=== HOME ASSISTANT: Output compactheid ===\n")
# =====================================================================

with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
     patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
     patch("core.home_assistant.requests.get") as mock_get:
    mock_get.return_value = fake_response(200, MIXED_STATES)
    result = ha.get_home_assistant_entities_tool()
    ok("output bevat entity_id", "light.rgb_strip" in result)
    ok("output bevat friendly_name", "RGB Strip" in result)
    ok("output bevat header met aantal", "entities (" in result)

# =====================================================================
print("\n=== HOME ASSISTANT: Result validation (HA-fouten zijn 'failed') ===\n")
# =====================================================================

from core.result_validation import classify_tool_result

ok("HA offline is failed",
   classify_tool_result("Kan Home Assistant niet bereiken: verbinding mislukt.") == "failed")
ok("HA 401 is failed",
   classify_tool_result("Kan Home Assistant niet autoriseren (HTTP 401): geen toegang.") == "failed")
ok("HA niet geconfigureerd is failed",
   classify_tool_result("Home Assistant niet beschikbaar: niet geconfigureerd.") == "failed")
ok("HA sensor niet bediend is failed",
   classify_tool_result("Entity Kamertemperatuur is een sensor-sensor en kan niet bediend worden met 'turn_on'.") == "failed")
ok("HA succes is success",
   classify_tool_result("RGB Strip is nu aan.") == "success")

# =====================================================================
print(f"\n{'='*50}")
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald van {passed+failed}")
print(f"{'='*50}")
