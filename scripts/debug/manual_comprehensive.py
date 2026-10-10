import sys
sys.path.insert(0, '.')
from core.ai import current_context

def reset_context():
    current_context.clear()
    current_context.update({
        'last_command': '',
        'last_result': '',
        'last_action': '',
        'last_program': '',
        'last_file': '',
        'last_website': '',
        'last_ha_entity': '',
        'last_ha_domain': '',
        'last_calculation': '',
    })

# Test 1: "stop de muziek" - should use media_play_pause
print("=== TEST 1: stop de muziek ===")
reset_context()
from core.brain import process_command
result = process_command("stop de muziek")
print(f"Result: {result}")
print()

# Test 2: "maak de muziek stil" / "muziek uit"
print("=== TEST 2: muziek uit ===")
reset_context()
result = process_command("muziek uit")
print(f"Result: {result}")
print()

# Test 3: "ik ga slapen" - agent routine
print("=== TEST 3: ik ga slapen ===")
reset_context()
result = process_command("ik ga slapen")
print(f"Result: {result}")
print()

# Test 4: "slaapmodus"
print("=== TEST 4: slaapmodus ===")
reset_context()
result = process_command("slaapmodus")
print(f"Result: {result}")
print()

# Test 5: "ik ga gamen"
print("=== TEST 5: ik ga gamen ===")
reset_context()
result = process_command("ik ga gamen")
print(f"Result: {result}")
print()

# Test 6: "maak mijn pc klaar om te gamen"
print("=== TEST 6: maak mijn pc klaar om te gamen ===")
reset_context()
result = process_command("maak mijn pc klaar om te gamen")
print(f"Result: {result}")
print()

# Test 7: "filmavond"
print("=== TEST 7: filmavond ===")
reset_context()
result = process_command("filmavond")
print(f"Result: {result}")
print()

# Test 8: "ga slapen" - standby
print("=== TEST 8: ga slapen (standby) ===")
# This goes through main.py, so we test is_goal
from core.agent import is_goal
print(f"is_goal('ga slapen'): {is_goal('ga slapen')}")
print(f"is_goal('ik ga slapen'): {is_goal('ik ga slapen')}")
print(f"is_goal('slaapmodus'): {is_goal('slaapmodus')}")
print(f"is_goal('ik ga gamen'): {is_goal('ik ga gamen')}")
print(f"is_goal('stop jarvis'): {is_goal('stop jarvis')}")
print()

# Test 9: context references
print("=== TEST 9: context references ===")
reset_context()
result = process_command("open discord")
print(f"Open Discord: {result}")
result = process_command("sluit hem")
print(f"Sluit hem: {result}")
print()

# Test 10: HA control
print("=== TEST 10: HA control ===")
reset_context()
result = process_command("maak de bedlamp aan")
print(f"Bedlamp aan: {result}")
result = process_command("doe hem uit")
print(f"Hem uit: {result}")
print()

# Test 11: multi-action single command
print("=== TEST 11: multi-action ===")
reset_context()
result = process_command("open discord en spotify")
print(f"Discord en Spotify: {result}")
print()

print("=== ALLE TESTS VOLTOOID ===")