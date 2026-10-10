import sys
import os
import io
import json
from unittest.mock import patch, MagicMock
from core.agent import is_goal, is_multi_step_goal, Agent

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def make_ollama_response(content):
        """Fake ollama.chat-antwoord met een message-object (zelfde vorm als echt)."""
        message = MagicMock()
        message.content = content
        message.tool_calls = []
        response = MagicMock()
        response.message = message
        return response
    FIXED_PLAN = {'steps': [{'tool_name': 'control_home_assistant', 'arguments': {'entity_id': 'light.woonkamer_lamp', 'action': 'turn_on'}, 'description': 'De woonkamerlamp aanzetten'}, {'tool_name': 'open_program', 'arguments': {'program': 'Netflix'}, 'description': 'Netflix openen', 'depends_on': [1]}]}
    FIXED_PLAN_JSON = json.dumps(FIXED_PLAN)

    def fake_ollama_chat(**kwargs):
        return make_ollama_response(FIXED_PLAN_JSON)
    print('=' * 70)
    print('DEEL 1: DETECTIE met andere prompts')
    print('=' * 70)
    cases = [('zet de lamp aan en open netflix', True), ('kun je voor mij de lamp aan doen en spotify openen', True), ('open eerst discord en dan spotify', True), ('maak mijn werkdag klaar: open chrome, outlook en word', True), ('pauzeer de muziek en doe de lamp uit', True), ('vergroot spotify en zet de lamp aan', True), ('doe het licht uit en start een film', True), ('open youtube en youtube music', True), ('zorg dat discord en steam open staan', True), ('zet het volume op 20 en sluit chrome', True), ('minimaliseer alle vensters en zet muziek aan', True), ('open de lamp', False), ('zet netflix aan', False), ('hoe laat is het', False), ('word wakker', False), ('zoek een bestand', False), ('onthoud dat ik pizza lekker vind', False), ('mijn favoriete game is minecraft', False), ('verplaats een bestand', False)]
    for prompt, expected in cases:
        got = is_goal(prompt) or is_multi_step_goal(prompt)
        assert got == expected, f"{('multi' if expected else 'geen')}: '{prompt}'"
    print()
    print('=' * 70)
    print('DEEL 2: LLM-PLANNING (alleen plan, NIET uitvoeren)')
    print('=' * 70)
    agent = Agent()
    plan_cases = ['zet de lamp aan en open netflix', 'kun je voor mij de lamp aan doen en spotify openen', 'open eerst discord en dan spotify', 'pauzeer de muziek en doe de lamp uit', 'zet het volume op 20 en sluit chrome', 'vergroot spotify en zet de lamp aan']
    with patch('core.agent.ollama.chat', side_effect=fake_ollama_chat):
        for prompt in plan_cases:
            print(f'\n--- {prompt} ---')
            plan = agent._generate_plan(prompt)
            if not plan:
                print('  GEVEN PLAN!')
                failed += 1
                assert False, f"plan voor '{prompt}'"
                continue
            tools_valid = all((p['tool_name'] for p in plan))
            ha_ok = all((p['arguments'].get('entity_id') for p in plan if p['tool_name'] == 'control_home_assistant'))
            order_ok = True
            for p in plan:
                for dep in p.get('depends_on', []):
                    if dep < 1 or dep > len(plan):
                        order_ok = False
                    if dep == plan.index(p) + 1:
                        order_ok = False
                    if dep >= plan.index(p) + 1:
                        order_ok = False
            for i, p in enumerate(plan, 1):
                dep = p.get('depends_on')
                print(f"  {i}. {p['tool_name']}({p['arguments']})" + (f'  depends_on={dep}' if dep else ''))
            assert len(plan) >= 2, f"plan heeft stappen voor '{prompt}'"
            assert ha_ok, f"HA-steps hebben entity_id voor '{prompt}'"
            assert order_ok, f"depends_on-volgorde correct voor '{prompt}'"
    print()
    print('=' * 70)
    print('DEEL 3: ECHTE UITVOERING (Executor, gemockte tools)')
    print('=' * 70)
    executed_calls = []

    def fake_execute_tool(tool_name, arguments, question):
        executed_calls.append((tool_name, arguments.get('program') or arguments.get('entity_id')))
        if tool_name == 'control_home_assistant':
            return 'De woonkamerlamp is aan.'
        if tool_name == 'open_program':
            return 'Netflix is geopend.'
        return 'Gelukt.'
    with patch('core.agent.ollama.chat', side_effect=fake_ollama_chat), patch('core.ai.execute_tool', side_effect=fake_execute_tool), patch('core.ai.correct_opposite_tool', return_value=None), patch('core.executor.APPROVAL_REQUIRED_RISKS', ()):
        goal = 'zet de lamp aan en open netflix'

        plan = agent._generate_plan(goal)
        assert bool(plan), 'plan bestaat voor uitvoering'
        results = agent._execute_plan(plan, goal)
        assert len(executed_calls) >= 2, 'Executor draaide alle geplande stappen'
        assert any((t == 'control_home_assistant' for t, _ in executed_calls)) and any((t == 'open_program' for t, _ in executed_calls)), 'HA-stap en programma-stap werden echt aangeroepen'
        assert all((r.get('status') in ('done', 'failed', 'skipped') for r in results)), 'elk resultaat is een stapstatus'
        assert all((r.get('status') == 'done' for r in results)), 'alle stappen zijn geslaagd (geen failure)'

    print()
    print('=' * 70)
    print('=' * 70)
