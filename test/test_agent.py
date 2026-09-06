import sys
import os
import io
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from unittest.mock import patch, MagicMock

from core.agent import (
    is_goal,
    Agent,
    _parse_json_object,
    VALID_TOOL_NAMES,
    MAX_PLAN_ITERATIONS,
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


def make_ollama_response(content, tool_calls=None):
    """Maakt een fake ollama.chat response met een message object."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []
    response = MagicMock()
    response.message = message
    return response


# =============================================================
# 1. GOAL-DETECTIE
# =============================================================
print("=== AGENT FASE 10: altijd een doel herkennen ===")

GOAL_YES = [
    "maak mijn pc klaar om te gamen",
    "JARVIS maak alles klaar voor de filmavond",
    "ik ga gamen",
    "ik ga slapen",
    "start de game avond",
    "zet alles klaar voor werk",
    "maak mijn kamer klaar voor de film",
]

GOAL_NO = [
    "open discord",
    "sluit discord",
    "zet het volume op 20",
    "wat is de hoofdstad van frankrijk",
    "open discord en spotify",
    "maak een screenshot",
    "zet de bedlamp uit",
    "welk programma heb ik zojuist geopend",
    "ik ga naar youtube",
    "ik ga naar de website van buienradar",
]

for phrase in GOAL_YES:
    ok(f"is_goal('{phrase}') == True", is_goal(phrase) is True)

for phrase in GOAL_NO:
    ok(f"is_goal('{phrase}') == False", is_goal(phrase) is False)


# =============================================================
# 2. JSON-PARSING (robust tegen losse tekst van qwen)
# =============================================================
print()
print("=== AGENT: JSON-parsing (fallbacks) ===")

ok("puur JSON-object parseert", _parse_json_object(
    '{"steps": [{"tool_name": "open_program"}]}'
) is not None)

ok("JSON met uitleg-omheen parseert", _parse_json_object(
    'Hier is het plan: {"steps": []} Veel succes!'
) is not None)

ok("kapot JSON geeft None (geen crash)", _parse_json_object(
    "geen json hier"
) is None)

ok("lege input geeft None", _parse_json_object("") is None)


# =============================================================
# 3. PLAN-NORMALISATIE: onbekende tools worden geweerd
# =============================================================
print()
print("=== AGENT: plan-normalisatie (Fase 9-principe) ===")

agent = Agent()

plan = agent._normalize_steps([
    {"tool_name": "open_program", "arguments": {"program": "Discord"}},
    {"tool_name": "hallucinatie_tool", "arguments": {}},
    {"tool_name": "set_volume", "arguments": {"percent": 30}},
    {"tool_name": "", "arguments": {}},
], "test doel")

ok("bekende tools blijven behouden", len(plan) == 2)
ok("onbekende tool wordt geweerd", plan[0]["tool_name"] == "open_program")
ok("planformaat voldoet aan Executor", plan[0]["status"] == "pending")
ok("stap bevat arguments", plan[1]["arguments"] == {"percent": 30})
ok("max stappen begrensd", len(agent._normalize_steps(
    [{"tool_name": "system_info", "arguments": {}}] * 20, "x"
)) <= 8)


# =============================================================
# 4. VOLLEDIGE AGENT-FLOW (gemockt): plan -> uitvoer -> antwoord
# =============================================================
print()
print("=== AGENT: volledige flow 'maak mijn pc klaar om te gamen' (mocks) ===")

PLAN_JSON = json.dumps({
    "steps": [
        {"tool_name": "open_program", "arguments": {"program": "Discord"},
         "description": "Discord openen"},
        {"tool_name": "open_program", "arguments": {"program": "Spotify"},
         "description": "Spotify openen"},
        {"tool_name": "set_volume", "arguments": {"percent": 30},
         "description": "Volume op 30"},
    ]
})

executed_calls = []

def fake_ollama_chat(**kwargs):
    # Alle plan-calls geven hetzelfde plan
    return make_ollama_response(PLAN_JSON)

def fake_execute_tool(tool_name, arguments, question):
    executed_calls.append(tool_name)
    if tool_name == "open_program":
        return f"Ik open {arguments.get('program')}."
    if tool_name == "set_volume":
        return "Volume staat op 30%."
    return "ok"

with patch("core.agent.ollama.chat", side_effect=fake_ollama_chat), \
     patch("core.ai.execute_tool", side_effect=fake_execute_tool), \
     patch("core.ai.correct_opposite_tool", return_value=None):
    answer = agent.run_goal("maak mijn pc klaar om te gamen")

ok("alle 3 stappen uitgevoerd", executed_calls == [
    "open_program", "open_program", "set_volume"])
ok("antwoord is een zin", isinstance(answer, str) and len(answer) > 0)
ok("antwoord noemt succestool 'gamen' niet letterlijk maar klaar",
   "klaar" in answer.lower() or "discord" in answer.lower() or "geopend" in answer.lower())


# =============================================================
# 5. RE-PLANNING BIJ MISLUKKING (één herpoging, overslaan bij HA 404)
# =============================================================
print()
print("=== AGENT: re-planning bij mislukte HA-stap (leeg plan = overslaan) ===")

executed_calls.clear()

plan_counter = {"n": 0}

def fake_ollama_chat_replan(**kwargs):
    plan_counter["n"] += 1
    if plan_counter["n"] == 1:
        # Eerst plan: Spotify openen (lukt), HA-apparaat mislukt
        return make_ollama_response(json.dumps({
            "steps": [
                {"tool_name": "open_program", "arguments": {"program": "Spotify"}},
                {"tool_name": "control_home_assistant", "arguments": {"domain": "light", "entity_id": "light.onbekend", "service": "turn_on"}},
            ]
        }))
    # Herplan: HA 404 -> leeg plan (overslaan)
    return make_ollama_response(json.dumps({"steps": []}))

def fake_execute_tool_replan(tool_name, arguments, question):
    executed_calls.append(tool_name)
    if tool_name == "control_home_assistant":
        return "Actie niet uitgevoerd: Kon 'light.onbekend' niet aan een bestaand Home Assistant apparaat koppelen."
    return f"Ik open {arguments.get('program', '')}."

with patch("core.agent.ollama.chat", side_effect=fake_ollama_chat_replan), \
     patch("core.ai.execute_tool", side_effect=fake_execute_tool_replan), \
     patch("core.ai.correct_opposite_tool", return_value=None):
    answer = agent.run_goal("open discord en spotify klaar")

ok("eerste plan uitgevoerd (2 stappen), herplan is leeg -> overslaan", len(executed_calls) == 2)
ok("Spotify wordt geopend", "spotify" in answer.lower())
ok("antwoord meldt de mislukking eerlijk", "lukten niet" in answer.lower() or "apparaat" in answer.lower())


# =============================================================
# 6. PLAN GENEREREN LUKT NIET (geen JSON) -> nette afhandeling
# =============================================================
print()
print("=== AGENT: LLM geeft geen geldig plan ===")

with patch("core.agent.ollama.chat", return_value=make_ollama_response("sorry, geen plan")):
    answer = agent.run_goal("maak mijn pc klaar om te gamen")

ok("geen plan -> eerlijke melding", isinstance(answer, str) and "plan" in answer.lower())


# =============================================================
# 7. MAX-AANTAL ITERATIES HARD BEGRENSD
# =============================================================
print()
print("=== AGENT: iteraties hard begrensd ===")

ok("MAX_PLAN_ITERATIONS is 2 (initieel + max 1 herplan)",
   MAX_PLAN_ITERATIONS == 2)


# =============================================================
# SAMENVATTING
# =============================================================
print()
print(f"Agent tests: {passed} geslaagd, {failed} gefaald")
sys.exit(1 if failed else 0)