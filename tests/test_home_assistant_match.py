import sys
import os
from core.ai import tool_matches_question, _smart_home_domain
from unittest.mock import patch, MagicMock
import json
import core.home_assistant as ha

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CONTROL_TOOL = {'type': 'function', 'function': {'name': 'control_home_assistant', 'description': 'Bedien een willekeurig Home Assistant apparaat.', 'parameters': {'type': 'object', 'properties': {'domain': {'type': 'string'}, 'service': {'type': 'string'}, 'entity_id': {'type': 'string'}, 'service_data': {'type': 'object'}}, 'required': ['domain', 'service', 'entity_id']}}}

    def match(q, args):
        return tool_matches_question('control_home_assistant', args, q, [CONTROL_TOOL])
    print('\n=== FIX B: tool_matches_question() accepteert HA helderheid/kleur ===\n')
    assert match('zet mijn bedlamp op 50% helderheid', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'brightness_pct': 50}}), 'helderheid-call wordt geaccepteerd'
    assert match('maak mijn bedlamp rood', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [0, 100]}}), 'kleur-call (rood) wordt geaccepteerd'
    assert match('maak mijn bedlamp paars', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [270, 100]}}), 'willekeurige kleurnaam (paars) wordt geaccepteerd'
    assert match('maak het licht warmer', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'color_temp': 3000}}), 'warmer wordt geaccepteerd'
    assert match('maak het licht koeler', {'domain': 'light', 'entity_id': 'light.woonkamer', 'service': 'turn_on', 'service_data': {'color_temp': 6000}}), 'koeler wordt geaccepteerd'
    assert match('zet mijn bedlamp aan', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}), 'aan blijft geaccepteerd'
    assert match('doe mijn bedlamp uit', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_off'}), 'uit blijft geaccepteerd'
    print('\n=== FIX B: _smart_home_domain() generieke domeinen ===\n')
    assert _smart_home_domain('light'), 'light is smart-home domein'
    assert _smart_home_domain('switch'), 'switch is smart-home domein'
    assert _smart_home_domain('cover'), 'cover is smart-home domein'
    assert _smart_home_domain('climate'), 'climate is smart-home domein'
    assert _smart_home_domain('media_player'), 'media_player is smart-home domein'
    assert not _smart_home_domain('open_program'), 'open_program is GEEN smart-home domein'
    assert not _smart_home_domain(''), 'lege string is GEEN smart-home domein'
    assert not _smart_home_domain(None), 'None is GEEN smart-home domein'
    print('\n=== FIX B: mismatching entity/domain wordt NIET geforceerd ===\n')
    assert not match('zet mijn bedlamp aan', {'domain': 'light', 'entity_id': 'switch.bed_lamp', 'service': 'turn_on'}), "domain 'light' vs entity 'switch.x' geeft geen HA-voorrang"
    print('\n=== E: home_assistant.py geeft service_data correct door (geen wijziging nodig) ===\n')

    def fake_response(status=200, json_data=None, text=''):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text if text else json.dumps(json_data) if json_data is not None else ''
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = json.JSONDecodeError('err', '', 0)
        return resp

    def payload_json_data(mock_post):
        """Haal de json-payload uit de laatste requests.post-aanroep."""
        call = mock_post.call_args
        if not call:
            return None
        return call.kwargs.get('json')
    LIGHT_ENTITY = {'entity_id': 'light.bed_lamp', 'state': 'on', 'attributes': {'friendly_name': 'Bed lamp', 'supported_color_modes': ['color_temp', 'hs'], 'supported_features': 0, 'brightness': 128}}
    with patch.object(ha, 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(ha, 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, LIGHT_ENTITY)
        mock_post.return_value = fake_response(200, {})
        ha.control_home_assistant_tool('light', 'turn_on', 'light.bed_lamp', {'brightness_pct': 50})
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('brightness_pct') == 50, 'brightness_pct=50 in POST-payload'
        mock_post.reset_mock()
        ha.control_home_assistant_tool('light', 'turn_on', 'light.bed_lamp', {'hs_color': [0, 100]})
        data = payload_json_data(mock_post)
        assert (data or {}).get('hs_color') == [0, 100], 'hs_color in POST-payload'
        mock_post.reset_mock()
        ha.control_home_assistant_tool('light', 'turn_on', 'light.bed_lamp', {'rgb_color': [255, 0, 0]})
        data = payload_json_data(mock_post)
        assert (data or {}).get('rgb_color') == [255, 0, 0], 'rgb_color in POST-payload'
        mock_post.reset_mock()
        ha.control_home_assistant_tool('light', 'turn_on', 'light.bed_lamp', {'color_temp': 3000})
        data = payload_json_data(mock_post)
        assert (data or {}).get('color_temp') == 3000, 'color_temp in POST-payload'
