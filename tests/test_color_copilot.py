import sys
import os
import json
from core.home_assistant import extract_color_hs, apply_color_copilot, _COLOR_NAMES
from core.ai import execute_tool, tool_matches_question
from unittest.mock import patch, MagicMock

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CONTROL_TOOL = {'type': 'function', 'function': {'name': 'control_home_assistant', 'description': 'Bedien een willekeurig Home Assistant apparaat.', 'parameters': {'type': 'object', 'properties': {'domain': {'type': 'string'}, 'service': {'type': 'string'}, 'entity_id': {'type': 'string'}, 'service_data': {'type': 'object'}}, 'required': ['domain', 'service', 'entity_id']}}}

    def match(q, args):
        return tool_matches_question('control_home_assistant', args, q, [CONTROL_TOOL])
    print('\n=== KLEUR-COPILOOT: deterministische kleurnamen -> hs_color ===\n')
    assert extract_color_hs('maak mijn bedlamp rood') == ([0, 100], 'rood'), 'rood -> hue 0'
    assert extract_color_hs('maak mijn bedlamp groen') == ([120, 100], 'groen'), 'groen -> hue 120'
    assert extract_color_hs('maak mijn bedlamp blauw') == ([240, 100], 'blauw'), 'blauw -> hue 240'
    assert extract_color_hs('maak mijn bedlamp geel') == ([60, 100], 'geel'), 'geel -> hue 60'
    assert extract_color_hs('maak mijn bedlamp paars') == ([270, 100], 'paars'), 'paars -> hue 270'
    assert extract_color_hs('maak mijn bedlamp roze') == ([330, 100], 'roze'), 'roze -> hue 330'
    assert extract_color_hs('maak mijn bedlamp oranje') == ([30, 100], 'oranje'), 'oranje -> hue 30'
    assert extract_color_hs('lichtblauw') == ([200, 100], 'lichtblauw'), 'lichtblauw heeft voorrang op blauw'
    assert extract_color_hs('zet mijn bedlamp op 50%') == (None, None), 'geen kleurnaam -> None'
    assert extract_color_hs('zet mijn bedlamp aan') == (None, None), 'geen kleurnaam (aan) -> None'
    assert extract_color_hs('doe mijn bedlamp uit') == (None, None), 'geen kleurnaam (uit) -> None'
    assert extract_color_hs('maak mijn bedlamp neongeelgroen') == (None, None), 'onbekende kleur -> None'
    assert len(_COLOR_NAMES) >= 10, 'minimaal 10 kleuren bekend'
    print('\n=== KLEUR-COPILOOT: apply_color_copilot normaliseert arguments ===\n')
    args = apply_color_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'maak mijn bedlamp rood')
    assert args.get('service_data', {}).get('hs_color') == [0, 100], 'zonder service_data krijgt alsnog hs_color'
    assert args.get('service') == 'turn_on', 'service blijft turn_on'
    args = apply_color_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [0, 100]}}, 'maak mijn bedlamp groen')
    assert args.get('service_data', {}).get('hs_color') == [120, 100], 'verkeerde AI hs_color wordt gecorrigeerd naar groen'
    args = apply_color_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'rgb_color': [255, 0, 0]}}, 'maak mijn bedlamp blauw')
    assert args.get('service_data', {}).get('hs_color') == [240, 100] and 'rgb_color' not in args.get('service_data', {}), 'rgb_color vervangen door hs_color (blauw)'
    print('\n=== KLEUR-COPILOOT: bestaande functies blijven intact ===\n')
    args = apply_color_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'brightness_pct': 50}}, 'zet mijn bedlamp op 50% helderheid')
    assert args.get('service') == 'turn_on' and args.get('service_data', {}).get('brightness_pct') == 50 and ('hs_color' not in args.get('service_data', {})), 'helderheid-call ongewijzigd'
    args = apply_color_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'zet mijn bedlamp aan')
    assert args.get('service') == 'turn_on' and args.get('service_data', {}) == {}, 'aan-call ongewijzigd'
    args = apply_color_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_off'}, 'doe mijn bedlamp uit')
    assert args.get('service') == 'turn_off' and args.get('service_data', {}) == {}, 'uit-call ongewijzigd'
    print('\n=== KLEUR-COPILOOT: routing blijft acceptabel (FASE 9) ===\n')
    assert match('maak mijn bedlamp rood', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [0, 100]}}), 'rood-call wordt geaccepteerd door tool_matches_question'
    assert match('maak mijn bedlamp groen', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [120, 100]}}), 'groen-call (met copiloot resultaat) wordt geaccepteerd'
    assert match('maak mijn bedlamp paars', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [270, 100]}}), 'paars-call wordt geaccepteerd'
    print('\n=== KLEUR-COPILOOT: execute_tool doorloopt de copiloot (mocked HA) ===\n')
    LIGHT_ENTITY = {'entity_id': 'light.bed_lamp', 'state': 'on', 'attributes': {'friendly_name': 'Bed lamp', 'supported_color_modes': ['color_temp', 'hs'], 'supported_features': 0, 'brightness': 128}}

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
        call = mock_post.call_args
        if not call:
            return None
        return call.kwargs.get('json')
    with patch.object(sys.modules['core.home_assistant'], 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(sys.modules['core.home_assistant'], 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:

        def _collect_get(url, *a, **kw):
            if '/api/states/' in str(url):
                entity_id = str(url).split('/api/states/')[-1]
                return fake_response(200, LIGHT_ENTITY) if entity_id == 'light.bed_lamp' else fake_response(404, None, 'Not Found')
            return fake_response(200, [LIGHT_ENTITY])
        mock_get.side_effect = _collect_get
        mock_post.return_value = fake_response(200, {})
        msg = execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'maak mijn bedlamp rood')
        data = payload_json_data(mock_post)
        assert (data or {}).get('hs_color') == [0, 100], 'rood zonder service_data -> hs_color [0,100] in POST'
        assert 'hs_color 0, 100' in msg, 'rood-call bevestigd in resultaat'
        mock_post.reset_mock()
        execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [0, 100]}}, 'maak mijn bedlamp groen')
        data = payload_json_data(mock_post)
        assert (data or {}).get('hs_color') == [120, 100], 'groen -> hs_color [120,100] in POST'
