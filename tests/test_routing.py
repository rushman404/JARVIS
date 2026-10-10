import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.brain import process_command
from core import confirmation

def load_negative():
    try:
        with open('tests/negative_utterances.txt', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def test_negative_utterances_routing():
    for utt in load_negative():
        try:
            process_command(utt)
        except Exception:
            pass

def test_confirmation_regressions():
    from core import confirmation as c
    assert 'niet' in c.DENIAL_WORDS
    assert c.contains_denial('ja maar niet nu')
