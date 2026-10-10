import sys
import os
sys.path.append('C:/JARVIS')
from core.calculator import calculate
from core.agent import is_goal
from core.routines import _manager as routine_manager

def test_negative_utterances():
    with open('C:/JARVIS/tests/negative_utterances.txt', 'r', encoding='utf-8') as f:
        utterances = [line.strip() for line in f if line.strip()]
    failed = 0
    for u in utterances:
        calc = calculate(u)
        goal = is_goal(u)
        routine, _ = routine_manager.resolve(u)
    failed = 0
    for u in utterances:
        calc = calculate(u)
        is_calc_intent = any((i in u.lower() for i in ['wat is', 'hoeveel is', 'bereken', 'reken uit']))
        if calc is not None and (not is_calc_intent):
            print(f'FAAL Calculator (onnodige actie): {u} -> {calc}')
            failed += 1
        goal = is_goal(u)
        is_goal_intent = any((pattern in u.lower() for pattern in ['zet mijn pc klaar', 'maak mijn pc klaar', 'game modus aan', 'film modus aan', 'slaap modus aan']))
        if goal is True and (not is_goal_intent):
            print(f'FAAL Agent (onnodige actie): {u}')
            failed += 1
        routine, _ = routine_manager.resolve(u)
        is_routine_intent = any((pattern in u.lower() for pattern in ['ik ga gamen', 'ik ga slapen', 'ik ga een film kijken', 'filmavond', 'gameavond']))
        if routine is not None and u not in ['ik ga gamen', 'ik ga slapen', 'ik ga een film kijken', 'filmavond', 'gameavond']:
            print(f'FAAL Routine (onnodige actie): {u} -> {routine}')
            failed += 1
if __name__ == '__main__':
    test_negative_utterances()
