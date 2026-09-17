import sys
import os
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from core.agent import is_goal, is_multi_step_goal, Agent

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


print("=" * 70)
print("DEEL 1: DETECTIE met andere prompts")
print("=" * 70)

# Variaties: meervoudige acties, beleefdheid, andere werkwoorden
cases = [
    # (prompt, verwacht multi / goal?)
    ("zet de lamp aan en open netflix", True),
    ("kun je voor mij de lamp aan doen en spotify openen", True),
    ("open eerst discord en dan spotify", True),
    ("maak mijn werkdag klaar: open chrome, outlook en word", True),
    ("pauzeer de muziek en doe de lamp uit", True),
    ("vergroot spotify en zet de lamp aan", True),
    ("doe het licht uit en start een film", True),
    ("open youtube en youtube music", True),
    ("zorg dat discord en steam open staan", True),
    ("zet het volume op 20 en sluit chrome", True),
    ("minimaliseer alle vensters en zet muziek aan", True),
    # Deze mogen NIET naar de Agent (enkelvoudig of algemeen)
    ("open de lamp", False),
    ("zet netflix aan", False),
    ("hoe laat is het", False),
    ("word wakker", False),
    ("zoek een bestand", False),
    ("onthoud dat ik pizza lekker vind", False),
    ("mijn favoriete game is minecraft", False),
    ("verplaats een bestand", False),
]

for prompt, expected in cases:
    got = is_goal(prompt) or is_multi_step_goal(prompt)
    ok(f"{'multi' if expected else 'geen'}: '{prompt}'", got == expected)

print()
print("=" * 70)
print("DEEL 2: LLM-PLANNING (alleen plan, NIET uitvoeren)")
print("=" * 70)

agent = Agent()

plan_cases = [
    "zet de lamp aan en open netflix",
    "kun je voor mij de lamp aan doen en spotify openen",
    "open eerst discord en dan spotify",
    "pauzeer de muziek en doe de lamp uit",
    "zet het volume op 20 en sluit chrome",
    "vergroot spotify en zet de lamp aan",
]

for prompt in plan_cases:
    print(f"\n--- {prompt} ---")
    plan = agent._generate_plan(prompt)
    if not plan:
        print("  GEVEN PLAN!")
        failed += 1
        ok(f"plan voor '{prompt}'", False)
        continue

    tools_valid = all(
        p["tool_name"]
        for p in plan
    )
    # Controleer dat HA-stappen een entity_id hebben
    ha_ok = all(
        p["arguments"].get("entity_id") for p in plan
        if p["tool_name"] == "control_home_assistant"
    )
    # Volgorde: depends_on punten altijd naar eerdere stap
    order_ok = True
    for p in plan:
        for dep in p.get("depends_on", []):
            if dep < 1 or dep > len(plan):
                order_ok = False
            if dep == plan.index(p) + 1:
                order_ok = False
            # dependency moet naar een stóérder stapnummer
            if dep >= plan.index(p) + 1:
                order_ok = False

    for i, p in enumerate(plan, 1):
        dep = p.get("depends_on")
        print(f"  {i}. {p['tool_name']}({p['arguments']})" + (f"  depends_on={dep}" if dep else ""))

    ok(f"plan heeft stappen voor '{prompt}'", len(plan) >= 2)
    ok(f"HA-steps hebben entity_id voor '{prompt}'", ha_ok)
    ok(f"depends_on-volgorde correct voor '{prompt}'", order_ok)

print()
print("=" * 70)
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald")
print("=" * 70)
sys.exit(1 if failed else 0)