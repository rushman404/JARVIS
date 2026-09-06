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
    is_multi_step_goal,
    Agent,
    MAX_PLAN_ITERATIONS,
    augment_plan_with_program_intents,
    _extract_program_action_intents,
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


def make_response(content):
    message = MagicMock()
    message.content = content
    response = MagicMock()
    response.message = message
    return response


# =============================================================
# 1. MULTI-ACTIE DETECTIE (Fase 2)
# =============================================================
print("=== FASE 2: meerdere acties herkennen ===")

MULTI_YES = [
    "doe mijn lamp aan, zet hem op 40% en open Spotify",
    "Open Discord, zet mijn muziek aan en maak Discord kleiner",
    "open discord en spotify",
    "sluit chrome en start steam",
    "open netflix en doe de lamp uit",
    "open spotify en zet het volume op 30",
    "open youtube en vervolgens buienradar",
]

MULTI_NO = [
    "open discord",
    "sluit discord",
    "zet het volume op 20",
    "wat is de hoofdstad van frankrijk",
    "open een bestand",
    "zet de bedlamp uit",
    "maak een screenshot",
    "weet je wat discord is",
    "maak een map project op het bureaublad",
]

for cmd in MULTI_YES:
    ok(f"multi-step: '{cmd}'", is_multi_step_goal(cmd))

for cmd in MULTI_NO:
    ok(f"geen multi-step: '{cmd}'", not is_multi_step_goal(cmd))

# Modi blijven herkend
ok("mode blijft: 'maak mijn pc klaar om te gamen'", is_goal("maak mijn pc klaar om te gamen"))
ok("mode blijft: 'ik ga slapen'", is_goal("ik ga slapen"))

print()

# =============================================================
# 2. PLAN MET depends_on: doorgegeven aan de Executor
# =============================================================
print("=== FASE 2: depends_on wordt doorgegeven ===")

agent = Agent()

steps = [
    {"tool_name": "open_program", "arguments": {"program": "Discord"}, "description": "Discord openen"},
    {"tool_name": "media_play_pause", "arguments": {}, "description": "Muziek aan"},
    {"tool_name": "minimize_window", "arguments": {"program": "Discord"}, "depends_on": [1], "description": "Discord kleiner"},
]

plan = agent._normalize_steps(steps, "open discord, muziek aan en discord kleiner", max_steps=8)

stap3 = plan[2] if len(plan) > 2 else {}
ok("3 stappen in plan", len(plan) == 3)
ok("stap 3 heeft depends_on [1]", stap3.get("depends_on") == [1])
ok("stap 1 heeft geen depends_on", plan[0].get("depends_on") is None)

# depends_on als int
steps_int = [
    {"tool_name": "open_program", "arguments": {"program": "Steam"}, "description": "Steam"},
    {"tool_name": "minimize_window", "arguments": {"program": "Steam"}, "depends_on": 1, "description": "kleiner"},
]
plan_int = agent._normalize_steps(steps_int, "steam kleiner", max_steps=8)
ok("depends_on als int wordt lijst", plan_int[1].get("depends_on") == [1])

# ongeldige depends_on
steps_bad = [
    {"tool_name": "open_program", "arguments": {"program": "Steam"}, "description": "Steam"},
    {"tool_name": "minimize_window", "arguments": {"program": "Steam"}, "depends_on": 0, "description": "kleiner"},
]
plan_bad = agent._normalize_steps(steps_bad, "steam kleiner", max_steps=8)
ok("depends_on=0 wordt genegeerd", plan_bad[1].get("depends_on") is None)

print()

# =============================================================
# 3. VOLLEDIGE FLOW: multi-actie met depends_on (mocks)
# =============================================================
print("=== FASE 2: volledige multi-actie flow (mocks) ===")

MULTI_PLAN = json.dumps({
    "steps": [
        {"tool_name": "open_program", "arguments": {"program": "Discord"}, "description": "Discord openen"},
        {"tool_name": "media_play_pause", "arguments": {}, "description": "Muziek aan"},
        {"tool_name": "minimize_window", "arguments": {"program": "Discord"}, "depends_on": [1], "description": "Discord kleiner"},
    ]
})

executed = []

def fake_chat_plan(**kwargs):
    return make_response(MULTI_PLAN)

def fake_verify_ok(**kwargs):
    return make_response("R")

def fake_ext(tool_name, arguments, question):
    executed.append((tool_name, dict(arguments)))
    if tool_name == "open_program":
        return "Ik open Discord."
    if tool_name == "media_play_pause":
        return "Ik heb de muziek gepauzeerd of hervat."
    if tool_name == "minimize_window":
        return "Discord wordt geminimaliseerd."
    return "ok"

with patch("core.agent.ollama.chat", side_effect=fake_chat_plan), \
     patch("core.ai.execute_tool", side_effect=fake_ext), \
     patch("core.ai.correct_opposite_tool", return_value=None), \
     patch("core.agent.Agent._verify_goal", return_value=None):
    answer = agent.run_goal("Open Discord, zet mijn muziek aan en maak Discord kleiner")

tools = [t for t, _ in executed]
ok("3 tools uitgevoerd", len(tools) == 3)
ok("open_program eerst", tools[0] == "open_program")
ok("minimize_window laatste", tools[-1] == "minimize_window")
ok("media uitvoering", "media_play_pause" in tools)
ok("antwoord is een zin", isinstance(answer, str) and len(answer) > 0)
ok("antwoord noemt discord", "discord" in answer.lower())

print()

# =============================================================
# 4. FOUTAFHANDELING: mislukte stap slaat afhankelijke over
# =============================================================
print("=== FASE 2: fout in stap 1 -> afhankelijke stap wordt overgeslagen ===")

plan2 = [
    {"tool_name": "open_program", "arguments": {"program": "Spotify"}, "status": "pending", "goal": "x"},
    {"tool_name": "minimize_window", "arguments": {"program": "Spotify"}, "status": "pending", "goal": "x",
     "depends_on": [1]},
    {"tool_name": "set_volume", "arguments": {"percent": 20}, "status": "pending", "goal": "x"},
]

volatile_calls = []

def fake_ext2(tool_name, arguments, question):
    volatile_calls.append(tool_name)
    if tool_name == "open_program":
        # Simuleer een mislukte open (bijv. programma niet gevonden)
        return "Ik kon Spotify niet vinden. Actie niet uitgevoerd."
    if tool_name == "minimize_window":
        return "Spotify wordt geminimaliseerd."
    if tool_name == "set_volume":
        return "Volume op 20%."
    return "ok"

# Executor: afhankelijke stap wordt geskipt als dependency faalt;
# onafhankelijke stappen draaien gewoon door.
from core.executor import execute_action_plan

with patch("core.ai.execute_tool", side_effect=fake_ext2), \
     patch("core.ai.correct_opposite_tool", return_value=None):
    results = execute_action_plan(plan2, "test doel")

by_tool = {r["tool_name"]: r["status"] for r in results}
snippets = {r["tool_name"]: r.get("result", "") for r in results}

ok("open_program is failed", by_tool.get("open_program") == "failed")
ok("minimize_window is skipped (afhankelijk van failed stap)",
   by_tool.get("minimize_window") in ("skipped", "failed"))
ok("set_volume draait door (onafhankelijk)", by_tool.get("set_volume") == "done")
ok("minimize werd NIET daadwerkelijk uitgevoerd", "minimize_window" not in volatile_calls)

print()

# =============================================================
# 5. EINDRESULTAAT CONTROLEREN: deterministische verificatie
# =============================================================
print("=== FASE 2: eindresultaat controle (deterministisch) ===")

records_done = [
    {"tool_name": "set_volume", "used_tool_name": "set_volume",
     "arguments": {"percent": 50}, "status": "done", "result": "Volume op 50%"},
]

# Alles geslaagd + niets overgeslagen -> None (doel bereikt)
gap_none = agent._verify_goal(records_done, [], [])
ok("verificatie: alle stappen klaar -> None", gap_none is None)

# Overgeslagen stap door dependency-failure -> eerlijke melding
skipped = [
    {"tool_name": "minimize_window", "arguments": {"program": "Discord"},
     "status": "skipped", "result": "overgeslagen"},
]
gap_skip = agent._verify_goal(records_done, [], skipped)
ok("verificatie: skipped stap -> melding", isinstance(gap_skip, str) and "discord" in gap_skip.lower())

# Mislukte stappen -> None (worden al eerlijk in samenvatting gemeld)
failed_rec = [
    {"tool_name": "open_program", "arguments": {"program": "Spotify"},
     "status": "failed", "result": "niet gevonden"},
]
gap_fail = agent._verify_goal(records_done, failed_rec, [])
ok("verificatie: failed stap -> None (wordt in samenvatting gemeld)", gap_fail is None)

# Meerdere overgeslagen stappen
skipped2 = [
    {"tool_name": "minimize_window", "arguments": {"program": "Discord"}, "status": "skipped"},
    {"tool_name": "control_home_assistant", "arguments": {"entity_id": "light.bed_lamp"}, "status": "skipped"},
]
gap_multi = agent._verify_goal([], [], skipped2)
ok("verificatie: meerdere skips -> melding met en", isinstance(gap_multi, str) and " en " in gap_multi)

print()

# =============================================================
# 6. NATUURLIJK EINDANTWOORD MET GAP
# =============================================================
print("=== FASE 2: natuurlijk eindantwoord ===")

answer2 = agent._generate_response(
    "doe de lamp aan en zet volume op 50",
    records_done,
    failed_rec,
    gap="Let op: de lamp is niet uitgevoerd omdat een eerdere stap mislukte.",
)

ok("antwoord bevat gap", isinstance(answer2, str) and "lamp" in answer2.lower())
ok("antwoord start natuurlijk", isinstance(answer2, str) and len(answer2) > 0)


# =============================================================
# 7. INTENT-AUGMENTATIE: LLM mist "sluit/vergroot/volume" (algemeen)
# =============================================================
print("=== FASE 2: intent-augmentatie (algemeen, geen vaste zinnen) ===")

# Leg dat LLM-plannen missen wat duidelijke programma-acties zijn:
missed_plan = [
    {"tool_name": "set_volume", "arguments": {"percent": 30}, "status": "pending", "goal": "x"},
    {"tool_name": "control_home_assistant", "arguments": {"entity_id": "light.bed_lamp"}, "status": "pending", "goal": "x"},
]

aug = augment_plan_with_program_intents(
    "zet het volume op 30 en sluit chrome en doe de lamp aan",
    missed_plan,
)
aug_tools = [p["tool_name"] for p in aug]
ok("close_program toegevoegd als ontbrekend", "close_program" in aug_tools)
ok("close_program target is Chrome", any(
    (p["arguments"].get("program") or "").lower() == "chrome"
    for p in aug if p["tool_name"] == "close_program"))

aug2 = augment_plan_with_program_intents(
    "vergroot spotify en doe het licht uit",
    [],
)
aug2_tools = [p["tool_name"] for p in aug2]
ok("maximize_window toegevoegd", "maximize_window" in aug2_tools)
ok("maximize target is spotify", any(
    (p["arguments"].get("program") or "").lower() == "spotify"
    for p in aug2 if p["tool_name"] == "maximize_window"))

# Algemene formuleringen (niet de exacte testzinnen)
ok("intent: 'sluit chrome'", ("close_program", "chrome") in _extract_program_action_intents("sluit chrome"))
ok("intent: 'maak discord kleiner'", ("minimize_window", "discord") in _extract_program_action_intents("maak discord kleiner"))
ok("intent: 'discord verkleinen'", ("minimize_window", "discord") in _extract_program_action_intents("kun je discord verkleinen"))
ok("intent: 'vergroot het venster van spotify'", ("maximize_window", "spotify") in _extract_program_action_intents("vergroot het venster van spotify"))
ok("intent: 'herstel discord'", ("restore_window", "discord") in _extract_program_action_intents("herstel discord"))
ok("geen intent: 'open chrome'", _extract_program_action_intents("open chrome") == [])
ok("geen intent: HA-only zin", _extract_program_action_intents("doe de lamp uit") == [])
ok("geen intent: algemene vraag", _extract_program_action_intents("wat is de hoofdstad") == [])

# Augmentatie voegt volume toe als het ontbreekt
aug3 = augment_plan_with_program_intents("zet het volume op 40 en open spotify", [])
ok("volume-intentie toegevoegd", any(
    p["tool_name"] == "set_volume" and p["arguments"].get("percent") == 40
    for p in aug3))

# Al bestaande stappen worden NIET gedupliceerd
aug4 = augment_plan_with_program_intents(
    "sluit chrome en open spotify",
    [{"tool_name": "close_program", "arguments": {"program": "Chrome"}, "status": "pending", "goal": "x"}],
)
ok("geen duplicaat close_program", len(aug4) == 1)

print()

print()
print("=" * 30)
print(f"Fase 2 tests: {passed} geslaagd, {failed} gefaald")
sys.exit(1 if failed else 0)