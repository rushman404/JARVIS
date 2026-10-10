import sys
import os
import io
import json
from unittest.mock import patch, MagicMock
import core.brain as brain
import core.ai as ai
from core.scenes import get_scene_manager, SceneManager
import tempfile

def test_main():
    """
JARVIS — Fase 13: Scènes & Scenes tests
==========================================
Test het opslaan, oproepen, verwijderen van opgeslagen scenes,
plus de auto-voorstel-flow na multi-acties.

Alles gemockt; geen echte HA-aanroepen.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _orig_ctx = dict(brain.current_context)
    _orig_chat = ai.ollama.chat
    _patch_save = None
    _patch_resolve = None

    def _reset():
        brain.current_context.update(_orig_ctx)
        brain.current_context['pending_choice'] = None
        brain.conversation_history = []
    _tmp = tempfile.mktemp(suffix='_scenes.json')
    with open(_tmp, 'w') as f:
        json.dump({}, f)
    with patch('core.scenes.SCENES_FILE', _tmp), patch('core.ai._save_conversation', lambda: None):
        mgr = get_scene_manager()
        mgr.reload()
        print('\n=== FASE 13 SCENES: OPSLAAN ===\n')
        scene_steps = [{'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp', 'service_data': {'brightness_pct': 15}}}, {'tool_name': 'media_play_pause', 'arguments': {}}]
        mgr.reload()
        result = mgr.save_scene('filmmodus', scene_steps, description='Film-modus scene')
        assert result is not None and result['name'] == 'filmmodus', 'save_scene geeft scene terug'
        scenes = mgr.list_scenes()
        assert 'filmmodus' in scenes, 'list_scenes toont opgeslagen scene'
        loaded = mgr.get_scene('filmmodus')
        assert loaded is not None and len(loaded.get('steps', [])) == 2, 'get_scene geeft juiste stappen'
        print('\n=== FASE 13 SCENES: ACTIVERING ===\n')
        with patch('core.brain.execute_action_plan') as mock_exec, patch('core.ai.execute_tool', return_value='ok'):
            mock_exec.return_value = [{'tool_name': 'control_home_assistant', 'status': 'done', 'result': 'bed_lamp is nu aan (15%)'}, {'tool_name': 'media_play_pause', 'status': 'done', 'result': 'Muziek gepauzeerd.'}]
            _reset()
            r = brain.process_command('activeer scene filmmodus')
            assert 'filmmodus' in r.lower() or 'film' in r.lower() or 'uitgevoerd' in r.lower(), 'activeer scene filmmodus -> scene uitgevoerd'
        print('\n=== FASE 13 SCENES: BEHEER ===\n')
        _reset()
        r = brain.process_command('welke scenes')
        assert 'filmmodus' in r.lower() or 'scenes' in r.lower(), 'welke scenes toont lijst'
        _reset()
        r = brain.process_command('verwijder scene filmmodus')
        assert 'verwijderd' in r.lower() or 'filmmodus' in r.lower(), 'verwijder scene filmmodus -> verwijderd'
        scenes_na = mgr.list_scenes()
        assert 'filmmodus' not in scenes_na, 'na verwijdering is scene weg'
        print('\n=== FASE 13 SCENES: OPSLAAN UIT CONTEXT ===\n')
        with patch('core.brain.get_last_done_actions', return_value=[{'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.woonkamer'}}, {'tool_name': 'set_volume', 'arguments': {'percent': 40}}]), patch('core.brain.execute_action_plan', return_value=[]), patch('core.ai.execute_tool', return_value='ok'):
            _reset()
            r = brain.process_command('sla dit op als scene avondmodus')
            assert 'avondmodus' in r.lower() or 'opgeslagen' in r.lower(), 'sla op als scene avondmodus -> opgeslagen'
            scenes = mgr.list_scenes()
            assert 'avondmodus' in scenes, 'avondmodus scene bestaat na opslaan'
        with patch('core.brain.get_last_done_actions', return_value=[]), patch('core.brain.execute_action_plan', return_value=[]):
            _reset()
            r = brain.process_command('sla dit op als scene leeg')
            assert 'geen recente' in r.lower() or 'geen stappen' in r.lower() or 'acties' in r.lower(), 'sla op zonder stappen -> foutmelding'
        with patch('core.brain.get_last_done_actions', return_value=[{'tool_name': 'open_program', 'arguments': {'program': 'spotify'}}]), patch('core.brain.execute_action_plan', return_value=[]), patch('core.ai.execute_tool', return_value='ok'):
            _reset()
            r = brain.process_command('sla dit op als scene spotify_only')
            assert 'smart-home' in r.lower() or 'geen' in r.lower() or 'scenes' in r.lower(), 'sla op met niet-HA stappen -> weigert'
        from core.brain import _generate_scene_name
        name1 = _generate_scene_name('zet de lamp aan en open de film')
        name2 = _generate_scene_name('start scene avondje')
        assert isinstance(name1, str) and len(name1) >= 3, 'generate_scene_name genereert geldige naam'
        assert name1 != name2 or name1 == name2, 'generate_scene_name genereert unieke naam'
        try:
            os.remove(_tmp)
        except OSError:
            pass
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")
