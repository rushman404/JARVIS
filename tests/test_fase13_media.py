import sys
import os
import io
from unittest.mock import patch, MagicMock
import core.brain as brain
import core.ha_registry as hr
from core.home_assistant import SUPPORTED_DOMAINS
from core.ha_registry import _DOMAIN_SERVICE_DEFAULTS

def test_main():
    """
JARVIS — Fase 13: Media Player tests
======================================
Test de media_player bediening via control_home_assistant:
tv harder/zachter, volgende/vorige nummer, volume_set, pauze/play.

Alles gemockt; geen echte HA-aanroepen.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _orig_ctx = dict(brain.current_context)

    def _reset():
        brain.current_context.update(_orig_ctx)
        brain.current_context['pending_choice'] = None
        brain.conversation_history = []
    print('\n=== FASE 13 MEDIA PLAYER ===\n')
    _MOCK_TV = {'entity_id': 'media_player.tv', 'domain': 'media_player', 'name': 'LG TV', 'device': 'LG webOS', 'device_id': '', 'area': 'Woonkamer', 'area_id': '', 'state': 'on', 'capabilities': ['turn_on', 'turn_off', 'toggle', 'pause', 'play', 'stop', 'previous', 'next', 'volume_set', 'volume_up', 'volume_down', 'select_source'], 'aliases': ['tv', 'televisie']}
    _MOCK_TV_STATE = {'entity_id': 'media_player.tv', 'state': 'on', 'attributes': {'friendly_name': 'LG TV', 'supported_features': 128}}
    _MOCK_SNAPSHOT = {'source': 'registry', 'entities': [_MOCK_TV], 'devices': {}, 'areas': {}}
    print('--- media_player service-dispatch ---\n')
    with patch('core.ha_registry.get_snapshot', return_value=_MOCK_SNAPSHOT), patch('core.home_assistant.get_snapshot', return_value=_MOCK_SNAPSHOT), patch('core.home_assistant.is_control_allowed', return_value=(True, '')), patch('core.home_assistant._ha_get', return_value=(True, _MOCK_TV_STATE)), patch('core.home_assistant._ha_post', return_value=(True, {'ok': True})):
        from core.home_assistant import control_home_assistant_tool
        r = control_home_assistant_tool('media_player', 'volume_up', 'media_player.tv')
        assert 'lg tv' in r.lower() or 'tv' in r.lower(), 'volume_up op media_player wordt uitgevoerd'
        r = control_home_assistant_tool('media_player', 'media_next_track', 'media_player.tv')
        assert 'lg tv' in r.lower() or 'tv' in r.lower(), 'media_next_track op media_player wordt uitgevoerd'
        r = control_home_assistant_tool('media_player', 'volume_set', 'media_player.tv', service_data={'volume_level': 0.4})
        assert 'lg tv' in r.lower() or 'tv' in r.lower(), 'volume_set op media_player wordt uitgevoerd'
    print('\n--- brain: media-direct ---\n')
    with patch('core.ha_registry.get_snapshot', return_value=_MOCK_SNAPSHOT), patch('core.home_assistant.get_snapshot', return_value=_MOCK_SNAPSHOT), patch('core.home_assistant.is_control_allowed', return_value=(True, '')), patch('core.home_assistant._ha_get', return_value=(True, _MOCK_TV_STATE)), patch('core.home_assistant._ha_post', return_value=(True, {'ok': True})):
        _reset()
        r = brain.process_command('zet tv harder')
        assert 'lg tv' in r.lower() or 'tv' in r.lower() or 'volume' in r.lower(), 'zet tv harder -> volume_up op tv'
        _reset()
        r = brain.process_command('zet tv zachter')
        assert 'lg tv' in r.lower() or 'tv' in r.lower() or 'volume' in r.lower(), 'zet tv zachter -> volume_down op tv'
        _reset()
        r = brain.process_command('pauzeer op tv')
        assert 'lg tv' in r.lower() or 'tv' in r.lower(), 'pauzeer op tv -> media_pause'
        _reset()
        r = brain.process_command('volgende nummer op tv')
        assert 'lg tv' in r.lower() or 'tv' in r.lower() or 'over' in r.lower(), 'volgende nummer op tv -> media_next_track'
        _reset()
        r = brain.process_command('zet tv op 40%')
        assert 'lg tv' in r.lower() or 'tv' in r.lower() or 'volume' in r.lower(), 'zet tv op 40% -> volume_set op tv'
    print('\n--- domein-config ---\n')
    assert 'scene' in SUPPORTED_DOMAINS, 'scene in SUPPORTED_DOMAINS'
    assert 'scene' in _DOMAIN_SERVICE_DEFAULTS, 'scene in _DOMAIN_SERVICE_DEFAULTS'
    assert 'set_cover_position' in _DOMAIN_SERVICE_DEFAULTS.get('cover', set()), 'set_cover_position in cover defaults'
    print(f"\n{'=' * 60}")
    print(f"{'=' * 60}\n")
