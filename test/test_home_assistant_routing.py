import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.brain as brain
from core.brain import (
    try_home_assistant,
    has_intent,
    CLOSE_PATTERNS,
    extract_program_names,
)

passed = 0
failed = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}")


# Monkey-patch ask_ai om te registreren wanneer HA-route wordt gebruik
ai_calls = []


def fake_ask_ai(command):
    ai_calls.append(command)
    return "AI-ROUTE"


brain.ask_ai = fake_ask_ai


print("\n=== HA-ROUTING: smart-home commando's gaan naar AI-route ===\n")

ai_calls.clear()
try_home_assistant("doe bedlamp uit")
ok("doe bedlamp uit -> AI-route", "doe bedlamp uit" in ai_calls)

ai_calls.clear()
try_home_assistant("zet bedlamp aan")
ok("zet bedlamp aan -> AI-route", "zet bedlamp aan" in ai_calls)

ai_calls.clear()
try_home_assistant("zet het licht uit")
ok("zet het licht uit -> AI-route", "zet het licht uit" in ai_calls)

ai_calls.clear()
try_home_assistant("doe de stekker uit")
ok("doe de stekker uit -> AI-route", "doe de stekker uit" in ai_calls)

ai_calls.clear()
try_home_assistant("zet de thermostaat op 20")
ok("thermostaat -> AI-route", "zet de thermostaat op 20" in ai_calls)


print("\n=== HA-ROUTING: PC-commando's blijven op PC ===\n")

ai_calls.clear()
result = try_home_assistant("sluit Discord")
ok("sluit Discord -> NIET AI-route (None)", result is None and not ai_calls)

ai_calls.clear()
result = try_home_assistant("open Spotify")
ok("open Spotify -> NIET AI-route (None)", result is None and not ai_calls)

ai_calls.clear()
result = try_home_assistant("speel muziek")
ok("speel muziek -> NIET AI-route (None)", result is None and not ai_calls)

ai_calls.clear()
result = try_home_assistant("wat is de hoofdstad van frankrijk")
ok("kennisvraag -> NIET AI-route (None)", result is None and not ai_calls)


print("\n=== HA-ROUTING: 'uit' wordt niet meer als close/intent gezien ===\n")

# "doe bedlamp uit" moet niet meer als PC-close-patroon voor 'bedlamp' worden herkend
# doordat try_home_assistant hem eerder afvangt.
ok(
    "'doe bedlamp uit' matcht CLOSE_PATTERNS",
    has_intent("doe bedlamp uit", CLOSE_PATTERNS),
)
# Maar try_home_assistant vangt het wél af vóór try_close_program.
ai_calls.clear()
try_home_assistant("doe bedlamp uit")
ok(
    "'doe bedlamp uit' wordt naar AI-route gestuurd (niet naar taskkill)",
    "doe bedlamp uit" in ai_calls,
)

# "sluit Discord" blijft een PC-close commando
ok(
    "'sluit Discord' matcht CLOSE_PATTERNS",
    has_intent("sluit Discord", CLOSE_PATTERNS),
)
ok(
    "'sluit Discord' gaat NIET via try_home_assistant",
    try_home_assistant("sluit Discord") is None,
)


print("\n=== ERROR-MSG: PC-programmasluiten logt geen HA-apparaten ===\n")

# Bevestig dat "bedlamp" géén PC-programmanaam is bij een HA-commando
names = extract_program_names("doe bedlamp uit")
ok(
    "extract_program_names('doe bedlamp uit') = ['bedlamp'] (maar wordt afgevangen)",
    names == ["bedlamp"],
)


print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===\n")
sys.exit(1 if failed else 0)
