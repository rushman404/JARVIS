import sys
import os
import json
import io
from unittest.mock import patch, MagicMock
import core.home_assistant as ha
from core.result_validation import classify_tool_result

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def fake_response(status=200, json_data=None, text=''):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text if text else json.dumps(json_data) if json_data is not None else ''
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = json.JSONDecodeError('err', '', 0)
        return resp
    SAMPLE_STATES = [{'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip', 'supported_features': 17, 'supported_color_modes': ['rgb', 'brightness'], 'brightness': 128}}, {'entity_id': 'switch.tretakt', 'state': 'off', 'attributes': {'friendly_name': 'Tretakt Stekker'}}, {'entity_id': 'sensor.kamer_temperatuur', 'state': '21.5', 'attributes': {'friendly_name': 'Kamertemperatuur', 'unit_of_measurement': '°C'}}]
    SAMPLE_ENTITY = SAMPLE_STATES[0]
    print('=== HOME ASSISTANT: Config-check ===\n')
    assert ha._config_ok.__wrapped__() if hasattr(ha._config_ok, '__wrapped__') else True, 'config_ok met URL+TOKEN'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'):
        assert ha._config_ok(), '_config_ok True'
    with patch.object(ha, 'HOME_ASSISTANT_URL', ''), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'):
        assert not ha._config_ok(), '_config_ok False (geen URL)'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', ''):
        assert not ha._config_ok(), '_config_ok False (geen TOKEN)'
    print('\n=== HOME ASSISTANT: Health check ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', ''), patch.object(ha, 'HOME_ASSISTANT_TOKEN', ''):
        result = ha.ha_health_check()
        assert 'niet geconfigureerd' in result, 'health_check niet geconfigureerd'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(200, {'message': 'API running.'})
        result = ha.ha_health_check()
        assert 'bereikbaar' in result, 'health_check success'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.side_effect = ha.requests.ConnectionError('offline')
        result = ha.ha_health_check()
        assert 'mislukt' in result, 'health_check offline'
    print('\n=== HOME ASSISTANT: GET fouten ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.side_effect = ha.requests.ConnectionError('offline')
        ok_bool, data = ha._ha_get('/api/states')
        assert not ok_bool and 'mislukt' in data, 'GET connection error'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.side_effect = ha.requests.Timeout('timeout')
        ok_bool, data = ha._ha_get('/api/states')
        assert not ok_bool and 'mislukt' in data, 'GET timeout'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(401)
        ok_bool, data = ha._ha_get('/api/states')
        assert not ok_bool and 'geen toegang' in data, 'GET 401'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(404)
        ok_bool, data = ha._ha_get('/api/states')
        assert not ok_bool and 'niet vinden' in data, 'GET 404'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(500)
        ok_bool, data = ha._ha_get('/api/states')
        assert not ok_bool and 'mislukt' in data, 'GET 500'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'not json at all'
        mock_resp.json.side_effect = json.JSONDecodeError('err', '', 0)
        mock_get.return_value = mock_resp
        ok_bool, data = ha._ha_get('/api/states')
        assert not ok_bool and 'JSON' in data, 'GET invalid JSON'
    print('\n=== HOME ASSISTANT: POST fouten ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', ''), patch.object(ha, 'HOME_ASSISTANT_TOKEN', ''):
        ok_bool, data = ha._ha_post('/api/services/light/turn_on')
        assert not ok_bool and 'niet geconfigureerd' in data, 'POST missing config'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.post') as mock_post:
        mock_post.side_effect = ha.requests.ConnectionError('offline')
        ok_bool, data = ha._ha_post('/api/services/light/turn_on', {'entity_id': 'light.x'})
        assert not ok_bool and 'mislukt' in data, 'POST connection error'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.post') as mock_post:
        mock_post.return_value = fake_response(401)
        ok_bool, data = ha._ha_post('/api/services/light/turn_on', {})
        assert not ok_bool and 'geen toegang' in data, 'POST 401'
    print('\n=== HOME ASSISTANT: Entity parsing ===\n')
    entity = ha._parse_entity(SAMPLE_STATES[0])
    assert entity['entity_id'] == 'light.rgb_strip', 'parse entity_id'
    assert entity['domain'] == 'light', 'parse domain'
    assert entity['name'] == 'RGB Strip', 'parse name'
    assert entity['state'] == 'on', 'parse state'
    assert 'turn_on' in entity.get('capabilities', []), 'parse capabilities bevat turn_on'
    assert 'brightness' in entity.get('capabilities', []), 'parse capabilities bevat brightness'
    assert 'color' in entity.get('capabilities', []), 'parse capabilities bevat color'
    assert entity.get('brightness_pct') == 50, 'parse brightness_pct'
    entity_switch = ha._parse_entity(SAMPLE_STATES[1])
    assert entity_switch['domain'] == 'switch', 'parse switch domain'
    assert 'turn_on' in entity_switch.get('capabilities', []), 'parse switch capabilities turn_on'
    entity_sensor = ha._parse_entity(SAMPLE_STATES[2])
    assert entity_sensor.get('capabilities', []) == [], 'parse sensor geen capabilities'
    print('\n=== HOME ASSISTANT: Capabilities ===\n')
    caps = ha._extract_capabilities({'supported_features': 17, 'supported_color_modes': ['rgb', 'brightness']}, 'light')
    assert 'brightness' in caps and 'color' in caps, 'light met rgb+brightness caps'
    caps_basic = ha._extract_capabilities({}, 'light')
    assert 'turn_on' in caps_basic and 'turn_off' in caps_basic, 'light zonder features caps'
    assert 'color' not in caps_basic, 'light zonder features geen color'
    caps_hs = ha._extract_capabilities({'supported_features': 0, 'supported_color_modes': ['color_temp', 'hs']}, 'light')
    assert 'brightness' in caps_hs and 'color' in caps_hs, 'light met hs/color_temp is dimbaar'
    caps_bright = ha._extract_capabilities({'supported_features': 0, 'supported_color_modes': ['brightness']}, 'light')
    assert 'brightness' in caps_bright, 'light met brightness-mode is dimbaar'
    caps_onoff = ha._extract_capabilities({'supported_features': 0, 'supported_color_modes': ['onoff']}, 'light')
    assert 'brightness' not in caps_onoff, 'light met onoff-mode is NIET dimbaar'
    caps_switch = ha._extract_capabilities({}, 'switch')
    assert 'turn_on' in caps_switch and 'toggle' in caps_switch, 'switch caps'
    caps_cover = ha._extract_capabilities({'supported_features': 1}, 'cover')
    assert 'set_position' in caps_cover, 'cover set_position'
    caps_climate = ha._extract_capabilities({}, 'climate')
    assert 'set_temperature' in caps_climate, 'climate caps'
    print('\n=== HOME ASSISTANT: Entity/service validatie ===\n')
    ok_bool, msg = ha._entity_fits_service({'entity_id': 'light.x', 'domain': 'light', 'capabilities': ['turn_on']}, 'light', 'turn_on')
    assert ok_bool, 'light.turn_on op light = geldig'
    ok_bool, msg = ha._entity_fits_service({'entity_id': 'light.x', 'domain': 'light', 'capabilities': ['turn_on']}, 'switch', 'turn_on')
    assert not ok_bool and 'domain' in msg, 'light.turn_on op switch = fout'
    ok_bool, msg = ha._entity_fits_service({'entity_id': 'sensor.temp', 'domain': 'sensor', 'capabilities': []}, 'sensor', 'turn_on')
    assert not ok_bool and 'sensor' in msg, 'sensor.turn_on = fout (read-only)'
    print('\n=== HOME ASSISTANT: Service data validatie ===\n')
    ok_bool, msg = ha._check_service_data({'capabilities': ['brightness']}, {'brightness_pct': 50})
    assert ok_bool, 'brightness_pct op lamp met brightness = ok'
    ok_bool, msg = ha._check_service_data({'capabilities': []}, {'rgb_color': [0, 0, 255]})
    assert not ok_bool and 'kleur' in msg, 'rgb_color op lamp zonder color = fout'
    ok_bool, msg = ha._check_service_data({'capabilities': []}, {'brightness_pct': 50})
    assert not ok_bool and 'helderheid' in msg, 'brightness_pct op lamp zonder brightness = fout'
    ok_bool, msg = ha._check_service_data({'capabilities': []}, {})
    assert ok_bool, 'lege service_data = altijd ok'
    print('\n=== HOME ASSISTANT: get_home_assistant_entities_tool ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', ''), patch.object(ha, 'HOME_ASSISTANT_TOKEN', ''):
        with patch('core.home_assistant.get_snapshot', return_value={'source': 'unknown', 'entities': []}):
            result = ha.get_home_assistant_entities_tool()
            assert 'Geen' in result, 'entities geen results'
    with patch('core.home_assistant.get_snapshot', return_value={'source': 'registry', 'entities': [{'entity_id': 'light.rgb_strip', 'domain': 'light', 'name': 'RGB Strip', 'state': 'on'}, {'entity_id': 'switch.tretakt', 'domain': 'switch', 'name': 'Tretakt Stekker', 'state': 'off'}, {'entity_id': 'sensor.temp', 'domain': 'sensor', 'name': 'Temp', 'state': '20'}]}):
        result = ha.get_home_assistant_entities_tool()
        assert '3' in result and 'rgb_strip' in result, 'entities 3 gevonden'
        assert 'RGB Strip' in result, 'entities friendly_name'
        assert 'light.rgb_strip' in result, 'entities bevat entity_id'
    with patch('core.home_assistant.get_snapshot', return_value={'source': 'registry', 'entities': [{'entity_id': 'light.rgb_strip', 'domain': 'light', 'name': 'RGB Strip', 'state': 'on'}, {'entity_id': 'switch.tretakt', 'domain': 'switch', 'name': 'Tretakt Stekker', 'state': 'off'}]}):
        result = ha.get_home_assistant_entities_tool(domain='light')
        assert 'rgb_strip' in result and 'tretakt' not in result, 'entities filter domain=light'
    print('\n=== HOME ASSISTANT: control_home_assistant_tool ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:

        def _get_side_effect(url, **kwargs):
            if '/api/states/' in url:
                return fake_response(200, SAMPLE_ENTITY)
            return fake_response(200, SAMPLE_STATES)
        mock_get.side_effect = _get_side_effect
        mock_post.return_value = fake_response(200, {})
        with patch('core.home_assistant.is_control_allowed', return_value=(True, '')):
            result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip')
            assert 'aan' in result, 'control turn_on success'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip', 'brightness': 200}})
        mock_post.return_value = fake_response(200, {})
        with patch('core.home_assistant.is_control_allowed', return_value=(True, '')):
            result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip', {'brightness_pct': 30})
            assert 'brightness' in result.lower() or 'aan' in result, 'control turn_on met brightness'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip', 'brightness': 200, 'supported_color_modes': ['rgb']}})
        mock_post.return_value = fake_response(200, {})
        with patch('core.home_assistant.is_control_allowed', return_value=(True, '')):
            result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip', {'rgb_color': [0, 0, 255]})
            assert 'aan' in result, 'control turn_on met rgb_color'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, SAMPLE_ENTITY)
        mock_post.return_value = fake_response(200, {})
        with patch('core.home_assistant.is_control_allowed', return_value=(True, '')):
            result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip')
            assert 'aan' in result, 'control turn_on met mock post'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip'}})
        mock_post.return_value = fake_response(200, {})
        with patch('core.home_assistant.is_control_allowed', return_value=(True, '')):
            result = ha.control_home_assistant_tool('light', 'toggle', 'light.rgb_strip')
            assert 'toggle' in result.lower() or 'nu' in result, 'control toggle'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        entity_switch_full = {'entity_id': 'switch.tretakt', 'state': 'off', 'attributes': {'friendly_name': 'Tretakt'}}
        mock_get.return_value = fake_response(200, entity_switch_full)
        mock_post.return_value = fake_response(200, {})
        result = ha.control_home_assistant_tool('switch', 'turn_on', 'switch.tretakt')
        assert 'aan' in result, 'control switch turn_on'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip'}})
        result = ha.control_home_assistant_tool('switch', 'turn_on', 'light.rgb_strip')
        assert 'domain' in result.lower(), 'control domain mismatch fout'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(200, {'entity_id': 'sensor.temp', 'state': '21.5', 'attributes': {'friendly_name': 'Temp', 'unit_of_measurement': '°C'}})
        result = ha.control_home_assistant_tool('sensor', 'turn_on', 'sensor.temp')
        assert 'sensor' in result.lower() and 'niet bediend' in result, 'control sensor bedienen fout'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip'}})
        result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip', {'rgb_color': [0, 0, 255]})
        assert 'kleur' in result.lower(), 'control rgb_color op lamp zonder color = fout'
    result = ha.control_home_assistant_tool('', 'turn_on', 'light.x')
    assert 'domain' in result, 'control geen domain'
    result = ha.control_home_assistant_tool('light', '', 'light.x')
    assert 'service' in result, 'control geen service'
    result = ha.control_home_assistant_tool('light', 'turn_on', '')
    assert 'entity_id' in result, 'control geen entity_id'
    print('\n=== HOME ASSISTANT: Token wordt niet gelogd ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'SECRET_TOKEN_XYZ'), patch('core.home_assistant.requests.get') as mock_get:
        mock_get.return_value = fake_response(200, SAMPLE_STATES)
        result = ha.get_home_assistant_entities_tool()
        assert 'SECRET_TOKEN_XYZ' not in result, 'token niet in resultaat'
    print('\n=== HOME ASSISTANT: Slimme domein-filter (Updated for Registry) ===\n')
    MIXED_STATES = [{'entity_id': 'light.rgb_strip', 'domain': 'light', 'state': 'on', 'name': 'RGB Strip', 'capabilities': ['turn_on']}, {'entity_id': 'switch.tretakt', 'domain': 'switch', 'state': 'off', 'name': 'Tretakt', 'capabilities': ['turn_on']}, {'entity_id': 'sensor.temp', 'domain': 'sensor', 'state': '21.5', 'name': 'Temp', 'capabilities': []}, {'entity_id': 'cover.shutter', 'domain': 'cover', 'state': 'open', 'name': 'Shutter', 'capabilities': ['turn_on']}, {'entity_id': 'climate.thermostat', 'domain': 'climate', 'state': 'heat', 'name': 'Thermostat', 'capabilities': ['turn_on']}]
    with patch('core.home_assistant.get_snapshot', return_value={'source': 'test', 'entities': MIXED_STATES}):
        result = ha.get_home_assistant_entities_tool(domain=None)
        assert 'rgb_strip' in result, 'domain=None bevat light'
        assert 'tretakt' in result, 'domain=None bevat switch'
        assert 'temp' in result, 'domain=None bevat sensor'
        assert 'shutter' in result, 'domain=None bevat cover'
        assert 'thermostat' in result, 'domain=None bevat climate'
    with patch('core.home_assistant.get_snapshot', return_value={'source': 'test', 'entities': MIXED_STATES}):
        result = ha.get_home_assistant_entities_tool(domain='light')
        assert 'rgb_strip' in result and 'tretakt' not in result, 'domain=light bevat alleen light'
    UNKNOWN_LIGHT = [{'entity_id': 'light.nieuwe_lamp', 'domain': 'light', 'state': 'off', 'name': 'Nieuwe Lamp', 'capabilities': []}]
    with patch('core.home_assistant.get_snapshot', return_value={'source': 'registry', 'entities': UNKNOWN_LIGHT}):
        result = ha.get_home_assistant_entities_tool()
        assert 'nieuwe_lamp' in result, 'onbekende light wordt automatisch gevonden'
    print('\n=== HOME ASSISTANT: Brightness None veiligheid (Bug 2) ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip', 'brightness': None}})
        mock_post.return_value = fake_response(200, {})
        with patch('core.home_assistant.is_control_allowed', return_value=(True, '')):
            try:
                result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip')
                assert True, 'control brightness=None crasht niet'
            except (TypeError, ZeroDivisionError):
                assert False, 'control brightness=None crasht niet'
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, {'entity_id': 'light.rgb_strip', 'state': 'on', 'attributes': {'friendly_name': 'RGB Strip', 'brightness': 200}})
        mock_post.return_value = fake_response(200, {})
        result = ha.control_home_assistant_tool('light', 'turn_on', 'light.rgb_strip')
        assert 'brightness' in result.lower() or 'aan' in result, 'control met geldige brightness werkt'
    print('\n=== HOME ASSISTANT: Output compactheid ===\n')
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.get_snapshot', return_value={'source': 'test', 'entities': MIXED_STATES}):
        result = ha.get_home_assistant_entities_tool()
        assert 'light.rgb_strip' in result, 'output bevat entity_id'
        assert 'RGB Strip' in result, 'output bevat friendly_name'
        assert 'entities (' in result, 'output bevat header met aantal'
    assert classify_tool_result('Kan Home Assistant niet bereiken: verbinding mislukt.') == 'failed', 'HA offline is failed'
    assert classify_tool_result('Kan Home Assistant niet autoriseren (HTTP 401): geen toegang.') == 'failed', 'HA 401 is failed'
    assert classify_tool_result('Home Assistant niet beschikbaar: niet geconfigureerd.') == 'failed', 'HA niet geconfigureerd is failed'
    assert classify_tool_result("Entity Kamertemperatuur is een sensor-sensor en kan niet bediend worden met 'turn_on'.") == 'failed', 'HA sensor niet bediend is failed'
    assert classify_tool_result('RGB Strip is nu aan.') == 'success', 'HA succes is success'
    print(f"\n{'=' * 50}")
    print(f"{'=' * 50}")
