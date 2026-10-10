import sys
import os
import io
import json
from unittest.mock import patch, MagicMock
import core.brain as brain
import core.ai as ai

def test_main():
    """
JARVIS — Fase 13: Automations-voorstel flow tests
====================================================
Test de auto-voorstel-flow na multi-actie en de pending_choice handling.

Alles gemockt; geen echte HA-aanroepen.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _orig_ctx = dict(brain.current_context)
    _orig_chat = ai.ollama.chat

    def _reset():
        brain.current_context.update(_orig_ctx)
        brain.current_context['pending_choice'] = None
        brain.conversation_history = []
    print('\n=== FASE 13 AUTOMATIONS-VOORSTEL ===\n')
    print('--- auto-voorstel na multi-actie ---\n')
    with patch('core.brain.get_scene_manager') as mock_scene_mgr, patch('core.ai.ollama.chat') as mock_chat, patch('core.ai._save_conversation', lambda: None), patch('core.brain.execute_action_plan') as mock_exec, patch('core.ai.execute_tool', return_value='ok'):
        mock_scene_inst = MagicMock()
        mock_scene_mgr.return_value = mock_scene_inst
        mock_scene_inst.get_scene.return_value = None
        mock_scene_inst.save_scene.return_value = {'name': 'auto_scene', 'steps': []}

        class FakeResponse:

            class Message:
                content = '{"steps": [{"tool_name": "control_home_assistant", "arguments": {"domain": "light", "service": "turn_on", "entity_id": "light.bed_lamp", "service_data": {"brightness_pct": 30}}, "description": "lamp aan"}, {"tool_name": "media_play_pause", "arguments": {}, "description": "media"}]}'
                tool_calls = None
            message = Message()
        mock_chat.return_value = FakeResponse()
        mock_exec.return_value = [{'tool_name': 'control_home_assistant', 'status': 'done', 'result': 'lamp aan', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp'}}, {'tool_name': 'media_play_pause', 'status': 'done', 'result': 'muziek', 'arguments': {}}]
        _reset()
        r = brain.process_command('zet de lamp aan en pauzeer muziek')
        assert isinstance(r, str) and len(r) > 10, 'multi-actie retourneert een antwoord'
        pending = brain.current_context.get('pending_choice')
        assert pending and pending.get('kind') == 'scene_save_suggest', 'pending_choice = scene_save_suggest na multi-actie'
        steps = pending.get('steps', []) if pending else []
        assert len(steps) >= 2, 'pending bevat executed steps'
    print('\n--- ja op het voorstel ---\n')
    _reset()
    brain.current_context['pending_choice'] = {'kind': 'scene_save_suggest', 'steps': [{'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp'}}, {'tool_name': 'media_play_pause', 'arguments': {}}], 'last_command': 'zet lamp aan en pauzeer'}
    with patch('core.brain.get_scene_manager') as mock_mgr:
        mock_inst = MagicMock()
        mock_mgr.return_value = mock_inst
        mock_inst.get_scene.return_value = None
        mock_inst.save_scene.return_value = {'name': 'lamp_pauze', 'steps': []}
        _reset()
        brain.current_context['pending_choice'] = {'kind': 'scene_save_suggest', 'steps': [{'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp'}}, {'tool_name': 'media_play_pause', 'arguments': {}}], 'last_command': 'zet lamp aan en pauzeer'}
        r = brain.process_command('ja')
        assert 'opgeslagen' in r.lower() or 'scene' in r.lower(), 'ja op scene_suggest slaat op'
        assert brain.current_context.get('pending_choice') is None, 'pending_choice gewist na ja'
    print('\n--- nee op het voorstel ---\n')
    _reset()
    brain.current_context['pending_choice'] = {'kind': 'scene_save_suggest', 'steps': [{'tool_name': 'media_play_pause', 'arguments': {}}], 'last_command': 'test'}
    r = brain.process_command('nee')
    assert 'niet' in r.lower() or 'nee' in r.lower() or 'sla niets' in r.lower(), 'nee op scene_suggest → afgebroken'
    assert brain.current_context.get('pending_choice') is None, 'pending_choice gewist na nee'
    print('\n--- handmatig opslaan ---\n')
    with patch('core.brain.get_scene_manager') as mock_mgr, patch('core.brain.get_last_done_actions', return_value=[{'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp', 'service_data': {'brightness_pct': 50}}}, {'tool_name': 'control_home_assistant', 'arguments': {'domain': 'switch', 'service': 'turn_on', 'entity_id': 'switch.tv_switch'}}]):
        mock_inst = MagicMock()
        mock_mgr.return_value = mock_inst
        mock_inst.get_scene.return_value = None
        mock_inst.save_scene.return_value = {'name': 'filmavond', 'steps': []}
        _reset()
        r = brain.process_command('sla dit op als scene filmavond')
        assert 'opgeslagen' in r.lower() or 'filmavond' in r.lower(), 'handmatig opslaan → opgeslagen'
    print(f"\n{'=' * 60}")
    print(f"{'=' * 60}\n")
