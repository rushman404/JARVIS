import sys
import os
import io
import json
from unittest.mock import patch, MagicMock
from core.agent import is_goal, Agent, _parse_json_object, VALID_TOOL_NAMES, MAX_PLAN_ITERATIONS

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def make_ollama_response(content, tool_calls=None):
        """Maakt een fake ollama.chat response met een message object."""
        message = MagicMock()
        message.content = content
        message.tool_calls = tool_calls or []
        response = MagicMock()
        response.message = message
        return response
    print('=== AGENT FASE 10: altijd een doel herkennen ===')
    GOAL_YES = ['maak mijn pc klaar om te gamen', 'zet mijn pc klaar om te gamen', 'activeer game modus', 'game modus aan', 'film modus aan', 'slaap modus aan']
    GOAL_NO = ['open discord', 'sluit discord', 'zet het volume op 20', 'wat is de hoofdstad van frankrijk', 'open discord en spotify', 'maak een screenshot', 'zet de bedlamp uit', 'welk programma heb ik zojuist geopend', 'ik ga naar youtube', 'ik ga naar de website van buienradar']
    for phrase in GOAL_YES:
        assert is_goal(phrase) is True, f"is_goal('{phrase}') == True"
    for phrase in GOAL_NO:
        assert is_goal(phrase) is False, f"is_goal('{phrase}') == False"
    print()
    print('=== AGENT: JSON-parsing (fallbacks) ===')
    assert _parse_json_object('{"steps": [{"tool_name": "open_program"}]}') is not None, 'puur JSON-object parseert'
    assert _parse_json_object('Hier is het plan: {"steps": []} Veel succes!') is not None, 'JSON met uitleg-omheen parseert'
    assert _parse_json_object('geen json hier') is None, 'kapot JSON geeft None (geen crash)'
    assert _parse_json_object('') is None, 'lege input geeft None'
    print()
    print('=== AGENT: plan-normalisatie (Fase 9-principe) ===')
    agent = Agent()
    plan = agent._normalize_steps([{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}}, {'tool_name': 'hallucinatie_tool', 'arguments': {}}, {'tool_name': 'set_volume', 'arguments': {'percent': 30}}, {'tool_name': '', 'arguments': {}}], 'test doel')
    assert len(plan) == 2, 'bekende tools blijven behouden'
    assert plan[0]['tool_name'] == 'open_program', 'onbekende tool wordt geweerd'
    assert plan[0]['status'] == 'pending', 'planformaat voldoet aan Executor'
    assert plan[1]['arguments'] == {'percent': 30}, 'stap bevat arguments'
    assert len(agent._normalize_steps([{'tool_name': 'system_info', 'arguments': {}}] * 20, 'x')) <= 8, 'max stappen begrensd'
    print()
    print("=== AGENT: volledige flow 'maak mijn pc klaar om te gamen' (mocks) ===")
    PLAN_JSON = json.dumps({'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}, 'description': 'Discord openen'}, {'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}, 'description': 'Spotify openen'}, {'tool_name': 'set_volume', 'arguments': {'percent': 30}, 'description': 'Volume op 30'}]})
    executed_calls = []

    def fake_ollama_chat(**kwargs):
        return make_ollama_response(PLAN_JSON)

    def fake_execute_tool(tool_name, arguments, question):
        executed_calls.append(tool_name)
        if tool_name == 'open_program':
            return f"Ik open {arguments.get('program')}."
        if tool_name == 'set_volume':
            return 'Volume staat op 30%.'
        return 'ok'
    with patch('core.agent.ollama.chat', side_effect=fake_ollama_chat), patch('core.ai.execute_tool', side_effect=fake_execute_tool), patch('core.ai.correct_opposite_tool', return_value=None), patch('core.executor.APPROVAL_REQUIRED_RISKS', ()):
        answer = agent.run_goal('maak mijn pc klaar om te gamen')
    assert executed_calls == ['open_program', 'open_program', 'set_volume'], 'alle 3 stappen uitgevoerd'
    assert isinstance(answer, str) and len(answer) > 0, 'antwoord is een zin'
    assert 'klaar' in answer.lower() or 'discord' in answer.lower() or 'geopend' in answer.lower(), "antwoord noemt succestool 'gamen' niet letterlijk maar klaar"
    print()
    print('=== AGENT: re-planning bij mislukte HA-stap (leeg plan = overslaan) ===')
    executed_calls.clear()
    plan_counter = {'n': 0}

    def fake_ollama_chat_replan(**kwargs):
        plan_counter['n'] += 1
        if plan_counter['n'] == 1:
            return make_ollama_response(json.dumps({'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}}, {'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'entity_id': 'light.onbekend', 'service': 'turn_on'}}]}))
        return make_ollama_response(json.dumps({'steps': []}))

    def fake_execute_tool_replan(tool_name, arguments, question):
        executed_calls.append(tool_name)
        if tool_name == 'control_home_assistant':
            return "Actie niet uitgevoerd: Kon 'light.onbekend' niet aan een bestaand Home Assistant apparaat koppelen."
        return f"Ik open {arguments.get('program', '')}."
    with patch('core.agent.ollama.chat', side_effect=fake_ollama_chat_replan), patch('core.ai.execute_tool', side_effect=fake_execute_tool_replan), patch('core.ai.correct_opposite_tool', return_value=None), patch('core.executor.APPROVAL_REQUIRED_RISKS', ()):
        answer = agent.run_goal('open discord en spotify klaar')
    assert len(executed_calls) == 2, 'eerste plan uitgevoerd (2 stappen), herplan is leeg -> overslaan'
    assert 'spotify' in answer.lower(), 'Spotify wordt geopend'
    assert 'lukten niet' in answer.lower() or 'apparaat' in answer.lower(), 'antwoord meldt de mislukking eerlijk'
    print()
    print('=== AGENT: LLM geeft geen geldig plan ===')
    with patch('core.agent.ollama.chat', return_value=make_ollama_response('sorry, geen plan')):
        answer = agent.run_goal('maak mijn pc klaar om te gamen')
    assert isinstance(answer, str) and 'plan' in answer.lower(), 'geen plan -> eerlijke melding'
    print()
    print('=== AGENT: iteraties hard begrensd ===')
    assert MAX_PLAN_ITERATIONS == 2, 'MAX_PLAN_ITERATIONS is 2 (initieel + max 1 herplan)'
    print()
