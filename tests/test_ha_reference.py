import sys
import os
import json
from core.home_assistant import has_ha_reference, is_ha_device_action, apply_context_copilot, apply_color_copilot
from core.ai import execute_tool, current_context
from unittest.mock import patch, MagicMock
from core.brain import try_ha_reference
from unittest.mock import patch as _patch
import core.brain as brain_mod

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    LAST_HA = {'entity_id': 'light.bed_lamp', 'domain': 'light', 'name': 'bedlamp'}
    print('\n=== VERWIJZING-DETECTIE: has_ha_reference ===\n')
    assert has_ha_reference('maak hem groen'), "'maak hem groen' is een verwijzing"
    assert has_ha_reference('zet haar uit'), "'zet haar uit' is een verwijzing"
    assert has_ha_reference('zet het op 50%'), "'zet het op 50%' is een verwijzing"
    assert has_ha_reference('maak deze lamp rood'), "'deze lamp' is een verwijzing"
    assert has_ha_reference('zet die lamp aan'), "'die lamp' is een verwijzing"
    assert has_ha_reference('doe dat apparaat uit'), "'dat apparaat' is een verwijzing"
    assert not has_ha_reference('maak de woonkamerlamp groen'), "'de woonkamerlamp' is GEEN verwijzing"
    assert not has_ha_reference('zet mijn bedlamp aan'), "'bedlamp' alleen is GEEN verwijzing"
    print('\n=== VERWIJZING-DETECTIE: is_ha_device_action ===\n')
    assert is_ha_device_action('maak hem groen'), 'kleurnaam is HA-actie'
    assert is_ha_device_action('zet hem op 50%'), 'helderheid is HA-actie'
    assert is_ha_device_action('doe hem uit'), 'uit is HA-actie'
    assert is_ha_device_action('zet hem aan'), 'aan is HA-actie'
    assert is_ha_device_action('zet haar op 30 procent'), 'procent is HA-actie'
    assert not is_ha_device_action('sluit het programma'), "'sluit hem' is GEEN open/uit/kleur HA-actie"
    print('\n=== VERWIJZING-DETECTIE: warmer/koeler (FASE 10.2) ===\n')
    assert is_ha_device_action('maak hem warmer'), "'maak hem warmer' is een HA-actie"
    assert is_ha_device_action('maak die warmer'), "'maak die warmer' is een HA-actie"
    assert is_ha_device_action('maak hem koeler'), "'maak hem koeler' is een HA-actie"
    assert is_ha_device_action('maak die koeler'), "'maak die koeler' is een HA-actie"
    assert is_ha_device_action('maak de lamp warmer'), "'maak de lamp warmer' is een HA-actie"
    assert is_ha_device_action('maak de lamp koeler'), "'maak de lamp koeler' is een HA-actie"
    assert is_ha_device_action('maak hem kouder'), "'maak hem kouder' is een HA-actie"
    assert has_ha_reference('maak hem warmer'), "'warmer' verwijzing ('maak hem warmer') is een verwijzing"
    assert has_ha_reference('maak die koeler'), "'koeler' verwijzing ('maak die koeler') is een verwijzing"
    print('\n=== VERWIJZING-COPILOOT: apply_context_copilot ===\n')
    args = apply_context_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'maak hem groen', LAST_HA)
    assert args.get('entity_id') == 'light.bed_lamp' and args.get('domain') == 'light', "'hem groen' -> entity light.bed_lamp"
    args = apply_context_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'zet haar op 50%', LAST_HA)
    assert args.get('entity_id') == 'light.bed_lamp', "'haar op 50%' -> entity light.bed_lamp"
    args = apply_context_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_off'}, 'doe dat apparaat uit', LAST_HA)
    assert args.get('entity_id') == 'light.bed_lamp', "'dat apparaat uit' -> entity light.bed_lamp"
    args = apply_context_copilot({'domain': 'light', 'entity_id': 'light.woonkamer', 'service': 'turn_on'}, 'maak de woonkamerlamp groen', LAST_HA)
    assert args.get('entity_id') == 'light.woonkamer', 'expliciete woonkamerlamp wordt niet overschreven'
    args = apply_context_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'zet mijn bedlamp op 50%', LAST_HA)
    assert args.get('entity_id') == 'light.bed_lamp', 'expliciete bedlamp-opdracht wordt niet overschreven'
    args = apply_context_copilot({'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'maak hem groen', {})
    assert args.get('entity_id') == 'light.bed_lamp', 'zonder last_ha geen overschrijving'
    print('\n=== VERWIJZING + KLEUR: copiloten werken samen ===\n')
    combined = apply_color_copilot(apply_context_copilot({'entity_id': 'light.x', 'service': 'turn_on'}, 'maak hem groen', LAST_HA), 'maak hem groen')
    assert combined.get('entity_id') == 'light.bed_lamp' and combined.get('service') == 'turn_on' and (combined.get('service_data', {}).get('hs_color') == [120, 100]), 'referentie + kleur -> entity bedlamp en hs_color groen'
    print('\n=== VERWIJZING-COPILOOT: execute_tool full flow (mocked HA, last_ha gezet) ===\n')
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
    update_ctx = {}
    current_context['last_ha_entity'] = 'light.bed_lamp'
    current_context['last_ha_domain'] = 'light'
    current_context['last_ha_name'] = 'bedlamp'
    with patch.object(sys.modules['core.home_assistant'], 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(sys.modules['core.home_assistant'], 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:

        def _collect_get(url, *a, **kw):
            if '/api/states/' in str(url):
                entity_id = str(url).split('/api/states/')[-1]
                return fake_response(200, LIGHT_ENTITY) if entity_id == 'light.bed_lamp' else fake_response(404, None, 'Not Found')
            return fake_response(200, [LIGHT_ENTITY])
        mock_get.side_effect = _collect_get
        mock_post.return_value = fake_response(200, {})
        result = execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bedroom_lamp', 'service': 'turn_on', 'service_data': {'hs_color': [0, 100]}}, 'maak hem groen')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('hs_color') == [120, 100], "'hem groen' -> POST op light.bed_lamp met hs_color [120,100]"
        mock_post.reset_mock()
        execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on', 'service_data': {'brightness_pct': 30}}, 'zet hem op 30%')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('brightness_pct') == 30 and ('hs_color' not in (data or {})), "'hem op 30%' -> brightness_pct 30 op light.bed_lamp"
        mock_post.reset_mock()
        execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_off'}, 'doe hem uit')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp', "'hem uit' -> turn_off op light.bed_lamp"
        mock_post.reset_mock()
        execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'}, 'zet hem aan')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp', "'hem aan' -> turn_on op light.bed_lamp"
    print('\n=== VERWIJZING-COPILOOT: deterministische route in brain (try_ha_reference) ===\n')
    current_context['last_ha_entity'] = 'light.bed_lamp'
    current_context['last_ha_domain'] = 'light'
    with _patch.object(sys.modules['core.home_assistant'], 'HOME_ASSISTANT_URL', 'http://ha:8123'), _patch.object(sys.modules['core.home_assistant'], 'HOME_ASSISTANT_TOKEN', 'tok123'), _patch('core.home_assistant.requests.get') as mock_get, _patch('core.home_assistant.requests.post') as mock_post:
        mock_get.return_value = fake_response(200, LIGHT_ENTITY)
        mock_post.return_value = fake_response(200, {})
        out = try_ha_reference('maak hem groen')
        assert out is not None and 'hs_color' in out, "'maak hem groen' -> deterministisch resultaat"
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('hs_color') == [120, 100], "'maak hem groen' -> POST light.bed_lamp + hs_color [120,100]"
        mock_post.reset_mock()
        out = try_ha_reference('zet hem op 30%')
        data = payload_json_data(mock_post)
        assert (data or {}).get('brightness_pct') == 30, "'zet hem op 30%' -> brightness_pct 30"
        mock_post.reset_mock()
        out = try_ha_reference('doe hem uit')
        data = payload_json_data(mock_post)
        assert out is not None and 'uit' in out, "'doe hem uit' -> turn_off"
        assert (data or {}).get('entity_id') == 'light.bed_lamp', "'doe hem uit' -> POST entity light.bed_lamp"
        mock_post.reset_mock()
        out = try_ha_reference('maak hem warmer')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('color_temp') == 3000, "'maak hem warmer' -> color_temp (warmer=3000)"
        mock_post.reset_mock()
        out = try_ha_reference('maak die koeler')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('color_temp') == 5000, "'maak die koeler' -> color_temp (koeler=5000)"
        mock_post.reset_mock()
        out = try_ha_reference('maak hem koeler')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('color_temp') == 5000, "'maak hem koeler' -> color_temp op light.bed_lamp"
        mock_post.reset_mock()
        out = try_ha_reference('maak die warmer')
        data = payload_json_data(mock_post)
        assert (data or {}).get('entity_id') == 'light.bed_lamp' and data.get('color_temp') == 3000, "'maak die warmer' -> color_temp op light.bed_lamp"
        current_context['last_ha_entity'] = ''
        current_context['last_ha_domain'] = ''
        out = try_ha_reference('doe hem uit')
        assert out is None, 'zonder last_ha -> None'
        current_context['last_ha_entity'] = 'light.bed_lamp'
        current_context['last_ha_domain'] = 'light'
