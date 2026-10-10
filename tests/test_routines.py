import os
import sys
import io
import tempfile
from unittest.mock import patch
from core.routines import RoutineManager
import core.brain as brain

def test_main():
    """
FASE 4 — TEST: Routines / Modes
=================================
Test de RoutineManager (CRUD + resolver) én de brain-integratie.

Veilig: er worden GEEN echte programma's of apparaten bediend.
De Executor wordt gemockt en er wordt met een tijdelijk
routines-bestand gewerkt (het echte config/routines.json wordt
niet aangeraakt).
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.json')
    os.close(tmp_fd)
    os.remove(tmp_path)
    TEST_ROUTINES = {'gaming': {'name': 'gaming', 'triggers': ['\\bgamen\\b', 'ik ga gamen'], 'aliases': ['game modus'], 'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}}, {'tool_name': 'set_volume', 'arguments': {'percent': 40}}], 'description': 'Gaming mode test'}, 'sleep': {'name': 'sleep', 'triggers': ['\\bik ga slapen\\b'], 'aliases': [], 'steps': [{'tool_name': 'media_stop', 'arguments': {}}], 'description': 'Slaap modus test'}}
    with patch('core.routines.ROUTINES_FILE', tmp_path):
        manager = RoutineManager()
        print('\n=== ROUTINES: resolver ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            manager.save_routine('gaming', TEST_ROUTINES['gaming']['triggers'], TEST_ROUTINES['gaming']['steps'], TEST_ROUTINES['gaming']['description'], TEST_ROUTINES['gaming']['aliases'])
            manager.save_routine('sleep', TEST_ROUTINES['sleep']['triggers'], TEST_ROUTINES['sleep']['steps'], TEST_ROUTINES['sleep']['description'], TEST_ROUTINES['sleep']['aliases'])
            name, routine = manager.resolve('ik ga gamen')
            assert name == 'gaming' and routine is not None, "'ik ga gamen' -> gaming"
            name, _ = manager.resolve('JARVIS, ik wil gamen vanavond')
            assert name == 'gaming', "'ik wil gamen' (substring match) -> gaming"
            name, _ = manager.resolve('zet de game modus aan')
            assert name == 'gaming', "alias 'game modus' -> gaming"
            name, _ = manager.resolve('ik ga slapen')
            assert name == 'sleep', "'ik ga slapen' -> sleep"
            name, _ = manager.resolve('ga slapen')
            assert name is None, "'ga slapen' blijft standby (geen routine)"
            name, _ = manager.resolve('welke routines heb je')
            assert name is None, 'beheer-zin triggert geen routine'
            name, _ = manager.resolve('open spotify')
            assert name is None, "'open spotify' triggert géén routine"
        print('\n=== ROUTINES: CRUD ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            manager.reload()
            routine = manager.get_routine('gaming')
            assert routine is not None, "routine 'gaming' opgeslagen"
            assert len(routine.get('steps', [])) == 2, 'routine heeft stappen'
            saved = manager.save_routine('ochtend', ['\\bgoedemorgen\\b'], [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}}], 'Ochtend routine')
            assert manager.get_routine('ochtend') is not None, 'nieuwe routine opslaan'
            assert saved.get('name') == 'ochtend', 'save return value'
            deleted = manager.delete_routine('ochtend')
            assert deleted is True, 'verwijder bestaande routine'
            assert manager.get_routine('ochtend') is None, 'routine daarna weg'
            deleted = manager.delete_routine('bestaat_niet')
            assert deleted is False, 'verwijder onbestaande routine -> False'
        print('\n=== ROUTINES: planformaat voor de Executor ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            manager.reload()
            plan = manager.steps_for_agent('gaming')
            assert len(plan) == 2, 'gaming levert 2 plan-stappen'
            assert plan[0]['tool_name'] == 'open_program' and plan[0]['arguments'] == {'program': 'Discord'}, 'stap 1 is open_program(Discord)'
            assert plan[0].get('status') == 'pending' and 'routine' in str(plan[0].get('goal')), 'stap heeft status + goal'
            plan = manager.steps_for_agent('bestaat_niet')
            assert plan == [], 'onbestaande routine -> lege lijst'
        print('\n=== ROUTINES: brain-integratie (mocks) ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            isolated = RoutineManager()
            for rname, rdata in TEST_ROUTINES.items():
                isolated.save_routine(rname, rdata['triggers'], rdata['steps'], rdata['description'], rdata['aliases'])
            fake_plan_results = [{'status': 'done', 'tool_name': 'open_program', 'used_tool_name': 'open_program', 'arguments': {'program': 'Discord'}}, {'status': 'done', 'tool_name': 'set_volume', 'used_tool_name': 'set_volume', 'arguments': {'percent': 40}}]
            with patch.object(brain, 'routine_manager', isolated), patch('core.brain.execute_action_plan', return_value=fake_plan_results) as mock_exec:
                answer = brain.try_routine('ik ga gamen')
                assert mock_exec.call_count == 1, 'routine wordt uitgevoerd via Executor'
                assert 'gaming' in answer.lower(), 'antwoord bevat routinenaam'
                failed_results = [{'status': 'failed', 'tool_name': 'set_volume', 'used_tool_name': 'set_volume', 'arguments': {'percent': 40}}, {'status': 'failed', 'tool_name': 'open_program', 'used_tool_name': 'open_program', 'arguments': {'program': 'Discord'}}]
                with patch('core.brain.execute_action_plan', return_value=failed_results):
                    answer = brain.try_routine('ik ga gamen')
                    assert 'mislukt' in answer.lower(), 'volledig falen wordt eerlijk gemeld'
                partial_results = [{'status': 'done', 'tool_name': 'open_program', 'used_tool_name': 'open_program', 'arguments': {'program': 'Discord'}}, {'status': 'failed', 'tool_name': 'set_volume', 'used_tool_name': 'set_volume', 'arguments': {'percent': 40}}]
                with patch('core.brain.execute_action_plan', return_value=partial_results):
                    answer = brain.try_routine('ik ga gamen')
                    assert 'mislukt' in answer.lower(), 'gedeeltelijk falen wordt eerlijk gemeld'
            with patch.object(brain, 'routine_manager', isolated):
                answer = brain.try_routine('welke routines heb je')
                assert 'gaming' in answer and 'sleep' in answer, "'welke routines' toont overzicht"
                answer = brain.try_routine('verwijder routine sleep')
                assert 'verwijderd' in answer.lower(), "'verwijder routine sleep' werkt"
                assert isolated.get_routine('sleep') is None, 'routine daadwerkelijk weg'
                answer = brain.try_routine('verwijder routine sleep')
                assert 'bestaat niet' in answer.lower(), 'nogmaals verwijderen -> melding bestaat niet'
        print('\n=== ROUTINES: opslaan via stem (mocks) ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            isolated = RoutineManager()
            isolated.save_routine('gaming', TEST_ROUTINES['gaming']['triggers'], TEST_ROUTINES['gaming']['steps'], TEST_ROUTINES['gaming']['description'], TEST_ROUTINES['gaming']['aliases'])
            fake_steps = [{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}}, {'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}}, {'tool_name': 'set_volume', 'arguments': {'percent': 35}}, {'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp'}}]
            with patch.object(brain, 'routine_manager', isolated), patch.object(brain.agent, 'last_executed_steps', fake_steps), patch('core.brain.execute_action_plan', return_value=[]):
                answer = brain.try_routine('bewaar dit als routine werk')
                assert 'opgeslagen' in answer.lower() and 'werk' in answer.lower(), "'bewaar dit als routine werk'"
                answer = brain.try_routine('sla dit op als routine werk')
                assert 'bijgewerkt' in answer.lower(), "'sla dit op als routine werk' bijwerkt"
                created = isolated.get_routine('werk')
                assert created is not None and len(created.get('steps', [])) == 4, "routine 'werk' bestaat in manager"
                assert created['steps'][2] == {'tool_name': 'set_volume', 'arguments': {'percent': 35}}, 'routinestappen correct overgenomen'
                name, _ = isolated.resolve('ik ga werk')
                assert name == 'werk', "nieuwe routine direct triggerbaar ('ik ga werk')"
                name, _ = isolated.resolve('we moeten werk')
                assert name == 'werk', "naam-trigger 'werk' matcht"
                with patch.object(brain.agent, 'last_executed_steps', []):
                    answer = brain.try_routine('bewaar dit als routine leeg')
                    assert 'geen recente acties' in answer.lower(), 'zonder recente acties -> vriendelijke melding'
                answer = brain.try_routine('onthoud dit als routine sport')
                assert 'opgeslagen' in answer.lower(), "'onthoud dit als routine sport'"
                answer = brain.try_routine('maak er een routine van film')
                assert 'opgeslagen' in answer.lower(), "'maak er een routine van film'"
        print('\n=== ROUTINES: flexibele zinsvormen opslaan ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            isolated = RoutineManager()
            fake_steps = [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}}, {'tool_name': 'set_volume', 'arguments': {'percent': 30}}]
            flexible = ['sla dit op als een routine genaamd muziek', 'bewaar dit als een routine genaamd test', 'sla deze acties op als routine avond', 'maak hier een routine van genaamd werk', 'bewaar als een routine genaamd film', 'maak een routine genaamd ochtend']
            with patch.object(brain, 'routine_manager', isolated), patch.object(brain.agent, 'last_executed_steps', fake_steps), patch('core.brain.execute_action_plan', return_value=[]):
                for phrase in flexible:
                    answer = brain.try_routine(phrase)
                    assert answer is not None and ('opgeslagen' in answer.lower() or 'bijgewerkt' in answer.lower()), f'{phrase!r} wordt als routine opgeslagen'
                for expected_name in ('muziek', 'test', 'avond', 'werk', 'film', 'ochtend'):
                    assert isolated.get_routine(expected_name) is not None, f"routine '{expected_name}' opgeslagen"
            with patch.object(brain, 'routine_manager', isolated), patch.object(brain.agent, 'last_executed_steps', []):
                answer = brain.try_routine('sla deze handelingen op als routine xyz')
                assert answer is not None and 'routine' in answer.lower(), 'vangnet geeft duidelijke uitleg (geen AI-gok)'
        print('\n=== ROUTINES: opslaan na Executor-uitvoering ===')
        with patch('core.routines.ROUTINES_FILE', tmp_path):
            isolated = RoutineManager()
            plan = [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}, 'status': 'pending'}, {'tool_name': 'set_volume', 'arguments': {'percent': 45}, 'status': 'pending'}]
            from core.executor import execute_action_plan, get_last_done_actions
            with patch('core.ai.execute_tool', side_effect=lambda name, args, q: f'{name} ok'):
                results = execute_action_plan(plan, 'test opdracht')
            import core.executor as executor_mod
            with patch.object(executor_mod, '_LAST_DONE_ACTIONS', [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}}, {'tool_name': 'set_volume', 'arguments': {'percent': 45}}]):
                assert len(get_last_done_actions()) == 2, 'executor-journaal gevuld'
                with patch.object(brain, 'routine_manager', isolated), patch('core.brain.execute_action_plan', return_value=[]), patch.object(brain.agent, 'last_executed_steps', []):
                    answer = brain.try_routine('bewaar dit als routine execjournal')
                    assert 'opgeslagen' in answer.lower(), 'opslaan NA Executor-uitvoering (zonder Agent)'
                    created = isolated.get_routine('execjournal')
                    assert created is not None and len(created.get('steps', [])) == 2, "routine 'execjournal' met 2 stappen uit journaal"
    print('\n=== ROUTINES: echte bestand is onaangetast ===')
    real_manager = RoutineManager()
    routines = real_manager.list_routines()
    assert isinstance(routines, dict), 'config/routines.json nog leesbaar (default-routines)'
    for name in ('gaming', 'movie', 'sleep'):
        assert name in routines, f"default-routine '{name}' aanwezig"
    try:
        os.remove(tmp_path)
    except OSError:
        pass
