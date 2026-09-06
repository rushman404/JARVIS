import sys
sys.path.insert(0, '.')
from core.agent import is_goal

tests = [
    'ik ga slapen',
    'ga slapen',
    'ga maar slapen',
    'slaapmodus',
    'ik ga rusten',
    'stop jarvis',
    'welterusten',
]
for t in tests:
    print(f'is_goal("{t}"): {is_goal(t)}')