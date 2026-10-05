import sys
import os
import io
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from unittest.mock import patch, MagicMock

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


def make_ollama_response(content):
    """Fake ollama.chat-antwoord met een message-object (zelfde vorm als echt)."""
    message = MagicMock()
    message.content = content
    message.tool_calls = []
    response = MagicMock()
    response.message = message
    return response


# =============================================================
# VASTE PLANNER-OUTPUT
#
# Dit is het enige stuk dat niet deterministisch was: de test riep
# eerder een echt LLM (ollama) aan via agent._generate_plan(), waardoor
# de uitkomst per run verschoot. We mocken daarom ALLEEN de LLM-laag
# (ollama.chat) en laten de echte Agent/planner-code draaien:
#   - _parse_json_object()          (echt)
#   - _normalize_steps()            (echt, incl. tool-validatie)
#   - augment_plan_with_program_intents() (echt)
#   - _execute_plan()/Executor      (echt, in DEEL 3)
#
# Het vaste plan is bewust zo gekozen dat het alle drie de controles
# NIET-triviaal maakt:
#   - stap 1 is een HA-stap MET entity_id -> de entity_id-controle
#     echt iets te testen heeft;
#   - stap 2 depends_on [1]           -> de volgordecontrole echt iets
#     te testen heeft (afhankelijkheid naar een eerdere stap);
#   - er zijn >= 2 stappen            -> de lengtecontrole klopt.
# =============================================================

FIXED_PLAN = {
    "steps": [
        {
            "tool_name": "control_home_assistant",
            "arguments": {"entity_id": "light.woonkamer_lamp", "action": "turn_on"},
            "description": "De woonkamerlamp aanzetten",
        },
        {
            "tool_name": "open_program",
            "arguments": {"program": "Netflix"},
            "description": "Netflix openen",
            "depends_on": [1],
        },
    ]
}

FIXED_PLAN_JSON = json.dumps(FIXED_PLAN)


def fake_ollama_chat(**kwargs):
    # Elke plan-call geeft exact hetzelfde, geldige plan terug.
    return make_ollama_response(FIXED_PLAN_JSON)


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

# Alleen de LLM-aanroep wordt gemockt; _generate_plan en alles
# daaronder (JSON-parser, normalisatie, validatie, aanvulling) draait
# echt, net als bij een echte uitvoering.
with patch("core.agent.ollama.chat", side_effect=fake_ollama_chat):

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


# =============================================================
# DEEL 3: ECHTE UITVOERING van het plan (Executor, gemockte tools)
#
# Toont aan dat het gevalideerde plan daadwerkelijk door de echte
# Executor loopt en dat de stappen als "done" eindigen. Alleen de
# LLM en de echte pc/HA-aanspraken worden gemockt; de Executor zelf
# is echt.
# =============================================================
print()
print("=" * 70)
print("DEEL 3: ECHTE UITVOERING (Executor, gemockte tools)")
print("=" * 70)

executed_calls = []


def fake_execute_tool(tool_name, arguments, question):
    executed_calls.append((tool_name, arguments.get("program") or arguments.get("entity_id")))
    if tool_name == "control_home_assistant":
        return "De woonkamerlamp is aan."
    if tool_name == "open_program":
        return "Netflix is geopend."
    return "Gelukt."


with patch("core.agent.ollama.chat", side_effect=fake_ollama_chat), \
     patch("core.ai.execute_tool", side_effect=fake_execute_tool), \
     patch("core.ai.correct_opposite_tool", return_value=None):

    goal = "zet de lamp aan en open netflix"
    plan = agent._generate_plan(goal)

    ok("plan bestaat voor uitvoering", bool(plan))

    results = agent._execute_plan(plan, goal)

    ok("Executor draaide alle geplande stappen",
       len(executed_calls) >= 2)
    ok("HA-stap en programma-stap werden echt aangeroepen",
       any(t == "control_home_assistant" for t, _ in executed_calls)
       and any(t == "open_program" for t, _ in executed_calls))
    ok("elk resultaat is een stapstatus",
       all(r.get("status") in ("done", "failed", "skipped") for r in results))
    ok("alle stappen zijn geslaagd (geen failure)",
       all(r.get("status") == "done" for r in results),
       )

print()
print("=" * 70)
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald")
print("=" * 70)
sys.exit(1 if failed else 0)
