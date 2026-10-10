import sys
import os
import core.brain as brain
from core.brain import try_home_assistant, has_intent, CLOSE_PATTERNS, extract_program_names

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ai_calls = []

    def fake_ask_ai(command):
        ai_calls.append(command)
        return 'AI-ROUTE'
    brain.ask_ai = fake_ask_ai
    print("\n=== HA-ROUTING: smart-home commando's gaan naar AI-route ===\n")
    ai_calls.clear()
    r = try_home_assistant('doe bedlamp uit')
    assert r is not None, 'doe bedlamp uit -> AI-route (of deterministisch)'
    ai_calls.clear()
    r = try_home_assistant('zet bedlamp aan')
    assert r is not None, 'zet bedlamp aan -> AI-route (of deterministisch)'
    ai_calls.clear()
    try_home_assistant('zet het licht uit')
    assert 'zet het licht uit' in ai_calls, 'zet het licht uit -> AI-route'
    ai_calls.clear()
    try_home_assistant('doe de stekker uit')
    assert 'doe de stekker uit' in ai_calls, 'doe de stekker uit -> AI-route'
    ai_calls.clear()
    try_home_assistant('zet de thermostaat op 20')
    assert 'zet de thermostaat op 20' in ai_calls, 'thermostaat -> AI-route'
    print("\n=== HA-ROUTING: PC-commando's blijven op PC ===\n")
    ai_calls.clear()
    result = try_home_assistant('sluit Discord')
    assert result is None and (not ai_calls), 'sluit Discord -> NIET AI-route (None)'
    ai_calls.clear()
    result = try_home_assistant('open Spotify')
    assert result is None and (not ai_calls), 'open Spotify -> NIET AI-route (None)'
    ai_calls.clear()
    result = try_home_assistant('speel muziek')
    assert result is None and (not ai_calls), 'speel muziek -> NIET AI-route (None)'
    ai_calls.clear()
    result = try_home_assistant('wat is de hoofdstad van frankrijk')
    assert result is None and (not ai_calls), 'kennisvraag -> NIET AI-route (None)'
    print("\n=== HA-ROUTING: 'uit' wordt niet meer als close/intent gezien ===\n")
    assert has_intent('doe bedlamp uit', CLOSE_PATTERNS), "'doe bedlamp uit' matcht CLOSE_PATTERNS"
    ai_calls.clear()
    r = try_home_assistant('doe bedlamp uit')
    assert r is not None, "'doe bedlamp uit' wordt afgevangen door try_home_assistant (niet naar taskkill)"
    assert has_intent('sluit Discord', CLOSE_PATTERNS), "'sluit Discord' matcht CLOSE_PATTERNS"
    assert try_home_assistant('sluit Discord') is None, "'sluit Discord' gaat NIET via try_home_assistant"
    print('\n=== ERROR-MSG: PC-programmasluiten logt geen HA-apparaten ===\n')
    names = extract_program_names('doe bedlamp uit')
    assert names == ['bedlamp'], "extract_program_names('doe bedlamp uit') = ['bedlamp'] (maar wordt afgevangen)"
