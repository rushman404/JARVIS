import sys
import os
import io
from core.home_assistant import resolve_entity_id
import json
from unittest.mock import patch, MagicMock
from core.ai import execute_tool
import sys as _sys

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ENTITIES = [{'entity_id': 'light.bed_lamp', 'domain': 'light', 'name': 'Bed lamp'}, {'entity_id': 'light.woonkamer', 'domain': 'light', 'name': 'Woonkamer'}, {'entity_id': 'light.kitchen_kitchen', 'domain': 'light', 'name': 'Kitchen'}, {'entity_id': 'light.eethoek_eethoek', 'domain': 'light', 'name': 'Eethoek'}, {'entity_id': 'light.bar_bar', 'domain': 'light', 'name': 'Bar'}, {'entity_id': 'light.eethoek_hue_ambiance_spot_6', 'domain': 'light', 'name': 'Eethoek Hue ambiance spot 6'}, {'entity_id': 'light.bank_hue_ambiance_spot_1', 'domain': 'light', 'name': 'Bank Hue ambiance spot 1'}, {'entity_id': 'light.kleine_spotjes', 'domain': 'light', 'name': 'Kleine spotjes'}]
    print('\n=== ENTITY-RESOLUTIE: exact geldige entity_ids worden behouden ===\n')
    r = resolve_entity_id('light.bed_lamp', None, ENTITIES)
    assert r[0] == 'light.bed_lamp' and r[1] == 'exact', 'light.bed_lamp -> exact, ongewijzigd'
    r = resolve_entity_id('light.kleine_spotjes', None, ENTITIES)
    assert r[0] == 'light.kleine_spotjes' and r[1] == 'exact', 'light.kleine_spotjes -> exact, ongewijzigd'
    print('\n=== ENTITY-RESOLUTIE: duidelijke fuzzy matches ===\n')
    r = resolve_entity_id('light.woonkamer_lamp', None, ENTITIES)
    assert r[0] == 'light.woonkamer' and r[1] == 'resolved', 'light.woonkamer_lamp -> light.woonkamer'
    r = resolve_entity_id('light.bar_light', None, ENTITIES)
    assert r[0] == 'light.bar_bar' and r[1] == 'resolved', 'light.bar_light -> light.bar_bar'
    r = resolve_entity_id('light.bar_lamp', None, ENTITIES)
    assert r[0] == 'light.bar_bar' and r[1] == 'resolved', 'light.bar_lamp -> light.bar_bar'
    r = resolve_entity_id('light.kitchen_lamp', None, ENTITIES)
    assert r[0] == 'light.kitchen_kitchen' and r[1] == 'resolved', 'light.kitchen_lamp -> light.kitchen_kitchen'
    print('\n=== ENTITY-RESOLUTIE: twijfelachtige matches (geen uitvoering) ===\n')
    r = resolve_entity_id('light.eethoek_lamp', None, ENTITIES)
    assert r[0] is None and r[1] == 'ambiguous', 'light.eethoek_lamp -> ambiguous (meerdere eethoek-lampen)'
    print('\n=== ENTITY-RESOLUTIE: geen match ===\n')
    r = resolve_entity_id('light.living_room_lamp', None, ENTITIES)
    assert r[0] is None and r[1] == 'none', 'light.living_room_lamp -> none'
    r = resolve_entity_id('light.slaapkamerlamp', None, ENTITIES)
    assert r[0] is None and r[1] == 'none', 'light.slaapkamerlamp -> none'
    r = resolve_entity_id('light.lamp', None, ENTITIES)
    assert r[0] is None and r[1] == 'none', "'light.lamp' (enkel generiek) -> none"
    print('\n=== ENTITY-RESOLUTIE: domein-scoping en edge cases ===\n')
    r = resolve_entity_id('woonkamer_lamp', None, ENTITIES)
    assert r[0] == 'light.woonkamer' and r[1] == 'resolved', 'zonder domeinprefix maar met unieke kern -> resolved'
    r = resolve_entity_id('', None, ENTITIES)
    assert r[0] is None and r[1] == 'none', 'leeg entity_id -> none'
    r = resolve_entity_id('light.bed_lamp', None, [])
    assert r[0] is None and r[1] == 'none' and (r[2].lower().find('geen') != -1), 'geen bekende entities -> none met duidelijke melding'
    r = resolve_entity_id('light.lamp', None, ENTITIES)
    assert r[1] == 'none', "enkel generiek token 'lamp' lost niet op"
    print('\n=== ENTITY-RESOLUTIE: integratie in execute_tool (mocked HA) ===\n')

    def fake_response(status=200, json_data=None, text=''):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text if text else json.dumps(json_data) if json_data is not None else ''
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = json.JSONDecodeError('err', '', 0)
        return resp

    def states_response():
        return json.dumps([{'entity_id': 'light.bed_lamp', 'state': 'on', 'attributes': {'friendly_name': 'Bed lamp', 'supported_color_modes': ['color_temp', 'hs']}}, {'entity_id': 'light.woonkamer', 'state': 'off', 'attributes': {'friendly_name': 'Woonkamer', 'supported_color_modes': ['color_temp']}}])
    with patch.object(_sys.modules['core.home_assistant'], 'HOME_ASSISTANT_URL', 'http://ha:8123'), patch.object(_sys.modules['core.home_assistant'], 'HOME_ASSISTANT_TOKEN', 'tok123'), patch('core.home_assistant.requests.get') as mock_get, patch('core.home_assistant.requests.post') as mock_post:

        def fake_get(url, *a, **kw):
            if '/api/config/entity_registry' in str(url) or '/api/config/device_registry' in str(url) or '/api/config/area_registry' in str(url):
                return fake_response(404, [])
            if '/api/states/' in str(url):
                entity_id = str(url).split('/api/states/')[-1]
                for ent in [{'entity_id': 'light.bed_lamp', 'state': 'on', 'attributes': {'friendly_name': 'Bed lamp', 'supported_color_modes': ['color_temp', 'hs']}}, {'entity_id': 'light.woonkamer', 'state': 'off', 'attributes': {'friendly_name': 'Woonkamer', 'supported_color_modes': ['color_temp']}}]:
                    if ent['entity_id'] == entity_id:
                        return fake_response(200, ent)
                return fake_response(404, None, 'Not Found')
            return fake_response(200, json.loads(states_response()))
        mock_get.side_effect = fake_get
        mock_post.return_value = fake_response(200, {})
        out = execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.woonkamer_lamp', 'service': 'turn_off'}, 'zet de woonkamerlamp uit')
        data_ok = mock_post.call_args is not None
        post_payload = None
        if data_ok:
            post_payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args.args[0]
        assert data_ok and (post_payload or {}).get('entity_id') == 'light.woonkamer', 'verzonnen entity omgezet (POST op light.woonkamer)'
        assert out.strip() != 'Kan Home Assistant niet vinden (HTTP 404).', 'geen 404-melding'
        mock_post.reset_mock()
        out = execute_tool('control_home_assistant', {'domain': 'light', 'entity_id': 'light.slaapkamerlamp', 'service': 'turn_off'}, 'zet de slaapkamerlamp uit')
        assert mock_post.call_args is None and 'niet uitgevoerd' in out, 'niet-bestaande entity -> actie niet uitgevoerd met melding'
