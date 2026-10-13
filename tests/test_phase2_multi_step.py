import sys
import os
import io
import json
from unittest.mock import patch, MagicMock
from core.agent import is_goal, is_multi_step_goal, Agent, MAX_PLAN_ITERATIONS, augment_plan_with_program_intents, _extract_program_action_intents
from core.executor import execute_action_plan

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def make_response(content):
        message = MagicMock()
        message.content = content
        response = MagicMock()
        response.message = message
        return response
    print('=== FASE 2: meerdere acties herkennen ===')
    MULTI_YES = ['doe mijn lamp aan, zet hem op 40% en open Spotify', 'Open Discord, zet mijn muziek aan en maak Discord kleiner', 'open discord en spotify', 'sluit chrome en start steam', 'open netflix en doe de lamp uit', 'open spotify en zet het volume op 30', 'open youtube en vervolgens buienradar']
    MULTI_NO = ['open discord', 'sluit discord', 'zet het volume op 20', 'wat is de hoofdstad van frankrijk', 'open een bestand', 'zet de bedlamp uit', 'maak een screenshot', 'weet je wat discord is', 'maak een map project op het bureaublad']
    for cmd in MULTI_YES:
        assert is_multi_step_goal(cmd), f"multi-step: '{cmd}'"
    for cmd in MULTI_NO:
        assert not is_multi_step_goal(cmd), f"geen multi-step: '{cmd}'"
    assert is_goal('maak mijn pc klaar om te gamen'), "mode blijft: 'maak mijn pc klaar om te gamen'"
    assert is_goal('activeer slaap modus'), "mode blijft: 'activeer slaap modus'"
    print()
    print('=== FASE 2: depends_on wordt doorgegeven ===')
    agent = Agent()
    steps = [{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}, 'description': 'Discord openen'}, {'tool_name': 'media_play_pause', 'arguments': {}, 'description': 'Muziek aan'}, {'tool_name': 'minimize_window', 'arguments': {'program': 'Discord'}, 'depends_on': [1], 'description': 'Discord kleiner'}]
    plan = agent._normalize_steps(steps, 'open discord, muziek aan en discord kleiner', max_steps=8)
    stap3 = plan[2] if len(plan) > 2 else {}
    assert len(plan) == 3, '3 stappen in plan'
    assert stap3.get('depends_on') == [1], 'stap 3 heeft depends_on [1]'
    assert plan[0].get('depends_on') is None, 'stap 1 heeft geen depends_on'
    steps_int = [{'tool_name': 'open_program', 'arguments': {'program': 'Steam'}, 'description': 'Steam'}, {'tool_name': 'minimize_window', 'arguments': {'program': 'Steam'}, 'depends_on': 1, 'description': 'kleiner'}]
    plan_int = agent._normalize_steps(steps_int, 'steam kleiner', max_steps=8)
    assert plan_int[1].get('depends_on') == [1], 'depends_on als int wordt lijst'
    steps_bad = [{'tool_name': 'open_program', 'arguments': {'program': 'Steam'}, 'description': 'Steam'}, {'tool_name': 'minimize_window', 'arguments': {'program': 'Steam'}, 'depends_on': 0, 'description': 'kleiner'}]
    plan_bad = agent._normalize_steps(steps_bad, 'steam kleiner', max_steps=8)
    assert plan_bad[1].get('depends_on') is None, 'depends_on=0 wordt genegeerd'
    print()
    print('=== FASE 2: volledige multi-actie flow (mocks) ===')
    MULTI_PLAN = json.dumps({'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}, 'description': 'Discord openen'}, {'tool_name': 'media_play_pause', 'arguments': {}, 'description': 'Muziek aan'}, {'tool_name': 'minimize_window', 'arguments': {'program': 'Discord'}, 'depends_on': [1], 'description': 'Discord kleiner'}]})
    executed = []

    def fake_chat_plan(**kwargs):
        return make_response(MULTI_PLAN)

    def fake_verify_ok(**kwargs):
        return make_response('R')

    def fake_ext(tool_name, arguments, question):
        executed.append((tool_name, dict(arguments)))
        if tool_name == 'open_program':
            return 'Ik open Discord.'
        if tool_name == 'media_play_pause':
            return 'Ik heb de muziek gepauzeerd of hervat.'
        if tool_name == 'minimize_window':
            return 'Discord wordt geminimaliseerd.'
        return 'ok'
    with patch('core.agent.ollama.chat', side_effect=fake_chat_plan), patch('core.ai.execute_tool', side_effect=fake_ext), patch('core.ai.correct_opposite_tool', return_value=None), patch('core.agent.Agent._verify_goal', return_value=None), patch('core.executor.APPROVAL_REQUIRED_RISKS', ()):
        answer = agent.run_goal('Open Discord, zet mijn muziek aan en maak Discord kleiner')
    tools = [t for t, _ in executed]
    assert len(tools) == 3, '3 tools uitgevoerd'
    assert tools.index('open_program') < tools.index('minimize_window'), 'open_program vóór minimize_window (afhankelijkheid)'
    assert tools[-1] == 'minimize_window', 'minimize_window laatste'
    assert 'media_play_pause' in tools, 'media uitvoering'
    assert isinstance(answer, str) and len(answer) > 0, 'antwoord is een zin'
    assert 'discord' in answer.lower(), 'antwoord noemt discord'
    print()
    print('=== FASE 2: fout in stap 1 -> afhankelijke stap wordt overgeslagen ===')
    plan2 = [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}, 'status': 'pending', 'goal': 'x'}, {'tool_name': 'minimize_window', 'arguments': {'program': 'Spotify'}, 'status': 'pending', 'goal': 'x', 'depends_on': [1]}, {'tool_name': 'set_volume', 'arguments': {'percent': 20}, 'status': 'pending', 'goal': 'x'}]
    volatile_calls = []

    def fake_ext2(tool_name, arguments, question):
        volatile_calls.append(tool_name)
        if tool_name == 'open_program':
            return 'Ik kon Spotify niet vinden. Actie niet uitgevoerd.'
        if tool_name == 'minimize_window':
            return 'Spotify wordt geminimaliseerd.'
        if tool_name == 'set_volume':
            return 'Volume op 20%.'
        return 'ok'
    with patch('core.ai.execute_tool', side_effect=fake_ext2), patch('core.ai.correct_opposite_tool', return_value=None), patch('core.executor.APPROVAL_REQUIRED_RISKS', ()):
        results = execute_action_plan(plan2, 'test doel')
    by_tool = {r['tool_name']: r['status'] for r in results}
    snippets = {r['tool_name']: r.get('result', '') for r in results}
    assert by_tool.get('open_program') == 'failed', 'open_program is failed'
    assert by_tool.get('minimize_window') in ('skipped', 'failed'), 'minimize_window is skipped (afhankelijk van failed stap)'
    assert by_tool.get('set_volume') == 'done', 'set_volume draait door (onafhankelijk)'
    assert 'minimize_window' not in volatile_calls, 'minimize werd NIET daadwerkelijk uitgevoerd'
    print()
    print('=== FASE 2: eindresultaat controle (deterministisch) ===')
    records_done = [{'tool_name': 'set_volume', 'used_tool_name': 'set_volume', 'arguments': {'percent': 50}, 'status': 'done', 'result': 'Volume op 50%'}]
    gap_none = agent._verify_goal(records_done, [], [])
    assert gap_none is None, 'verificatie: alle stappen klaar -> None'
    skipped = [{'tool_name': 'minimize_window', 'arguments': {'program': 'Discord'}, 'status': 'skipped', 'result': 'overgeslagen'}]
    gap_skip = agent._verify_goal(records_done, [], skipped)
    assert isinstance(gap_skip, str) and 'discord' in gap_skip.lower(), 'verificatie: skipped stap -> melding'
    failed_rec = [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}, 'status': 'failed', 'result': 'niet gevonden'}]
    gap_fail = agent._verify_goal(records_done, failed_rec, [])
    assert gap_fail is None, 'verificatie: failed stap -> None (wordt in samenvatting gemeld)'
    skipped2 = [{'tool_name': 'minimize_window', 'arguments': {'program': 'Discord'}, 'status': 'skipped'}, {'tool_name': 'control_home_assistant', 'arguments': {'entity_id': 'light.bed_lamp'}, 'status': 'skipped'}]
    gap_multi = agent._verify_goal([], [], skipped2)
    assert isinstance(gap_multi, str) and ' en ' in gap_multi, 'verificatie: meerdere skips -> melding met en'
    print()
    print('=== FASE 2: natuurlijk eindantwoord ===')
    answer2 = agent._generate_response('doe de lamp aan en zet volume op 50', records_done, failed_rec, gap='Let op: de lamp is niet uitgevoerd omdat een eerdere stap mislukte.')
    assert isinstance(answer2, str) and 'lamp' in answer2.lower(), 'antwoord bevat gap'
    assert isinstance(answer2, str) and len(answer2) > 0, 'antwoord start natuurlijk'
    print('=== FASE 2: intent-augmentatie (algemeen, geen vaste zinnen) ===')
    missed_plan = [{'tool_name': 'set_volume', 'arguments': {'percent': 30}, 'status': 'pending', 'goal': 'x'}, {'tool_name': 'control_home_assistant', 'arguments': {'entity_id': 'light.bed_lamp'}, 'status': 'pending', 'goal': 'x'}]
    aug = augment_plan_with_program_intents('zet het volume op 30 en sluit chrome en doe de lamp aan', missed_plan)
    aug_tools = [p['tool_name'] for p in aug]
    assert 'close_program' in aug_tools, 'close_program toegevoegd als ontbrekend'
    assert any(((p['arguments'].get('program') or '').lower() == 'chrome' for p in aug if p['tool_name'] == 'close_program')), 'close_program target is Chrome'
    aug2 = augment_plan_with_program_intents('vergroot spotify en doe het licht uit', [])
    aug2_tools = [p['tool_name'] for p in aug2]
    assert 'maximize_window' in aug2_tools, 'maximize_window toegevoegd'
    assert any(((p['arguments'].get('program') or '').lower() == 'spotify' for p in aug2 if p['tool_name'] == 'maximize_window')), 'maximize target is spotify'
    assert ('close_program', 'chrome') in _extract_program_action_intents('sluit chrome'), "intent: 'sluit chrome'"
    assert ('minimize_window', 'discord') in _extract_program_action_intents('maak discord kleiner'), "intent: 'maak discord kleiner'"
    assert ('minimize_window', 'discord') in _extract_program_action_intents('kun je discord verkleinen'), "intent: 'discord verkleinen'"
    assert ('maximize_window', 'spotify') in _extract_program_action_intents('vergroot het venster van spotify'), "intent: 'vergroot het venster van spotify'"
    assert ('restore_window', 'discord') in _extract_program_action_intents('herstel discord'), "intent: 'herstel discord'"
    assert _extract_program_action_intents('open chrome') == [], "geen intent: 'open chrome'"
    assert _extract_program_action_intents('doe de lamp uit') == [], 'geen intent: HA-only zin'
    assert _extract_program_action_intents('wat is de hoofdstad') == [], 'geen intent: algemene vraag'
    aug3 = augment_plan_with_program_intents('zet het volume op 40 en open spotify', [])
    assert any((p['tool_name'] == 'set_volume' and p['arguments'].get('percent') == 40 for p in aug3)), 'volume-intentie toegevoegd'
    aug4 = augment_plan_with_program_intents('sluit chrome en open spotify', [{'tool_name': 'close_program', 'arguments': {'program': 'Chrome'}, 'status': 'pending', 'goal': 'x'}])
    assert len(aug4) == 1, 'geen duplicaat close_program'
    print()
    print()
    print('=' * 30)
