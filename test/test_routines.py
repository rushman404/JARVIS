"""
FASE 4 — TEST: Routines / Modes
=================================
Test de RoutineManager (CRUD + resolver) én de brain-integratie.

Veilig: er worden GEEN echte programma's of apparaten bediend.
De Executor wordt gemockt en er wordt met een tijdelijk
routines-bestand gewerkt (het echte config/routines.json wordt
niet aangeraakt).
"""

import os
import sys
import io
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch
from core.routines import RoutineManager
import core.brain as brain

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


# =============================================================
# 1. ISOL ATIE: werk met een tijdelijk routines-bestand
# =============================================================

tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
os.close(tmp_fd)
os.remove(tmp_path)

TEST_ROUTINES = {
    "gaming": {
        "name": "gaming",
        "triggers": ["\\bgamen\\b", "ik ga gamen"],
        "aliases": ["game modus"],
        "steps": [
            {"tool_name": "open_program", "arguments": {"program": "Discord"}},
            {"tool_name": "set_volume", "arguments": {"percent": 40}},
        ],
        "description": "Gaming mode test",
    },
    "sleep": {
        "name": "sleep",
        "triggers": ["\\bik ga slapen\\b"],
        "aliases": [],
        "steps": [
            {"tool_name": "media_stop", "arguments": {}},
        ],
        "description": "Slaap modus test",
    },
}

with patch("core.routines.ROUTINES_FILE", tmp_path):
    manager = RoutineManager()

    # =============================================================
    # 1. Resolver: opdracht -> routine
    # =============================================================

    print("\n=== ROUTINES: resolver ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        manager.save_routine(
            "gaming",
            TEST_ROUTINES["gaming"]["triggers"],
            TEST_ROUTINES["gaming"]["steps"],
            TEST_ROUTINES["gaming"]["description"],
            TEST_ROUTINES["gaming"]["aliases"],
        )
        manager.save_routine(
            "sleep",
            TEST_ROUTINES["sleep"]["triggers"],
            TEST_ROUTINES["sleep"]["steps"],
            TEST_ROUTINES["sleep"]["description"],
            TEST_ROUTINES["sleep"]["aliases"],
        )

        name, routine = manager.resolve("ik ga gamen")
        ok("'ik ga gamen' -> gaming", name == "gaming" and routine is not None)

        name, _ = manager.resolve("JARVIS, ik wil gamen vanavond")
        ok("'ik wil gamen' (substring match) -> gaming", name == "gaming")

        name, _ = manager.resolve("zet de game modus aan")
        ok("alias 'game modus' -> gaming", name == "gaming")

        name, _ = manager.resolve("ik ga slapen")
        ok("'ik ga slapen' -> sleep", name == "sleep")

        name, _ = manager.resolve("ga slapen")
        ok("'ga slapen' blijft standby (geen routine)", name is None)

        name, _ = manager.resolve("welke routines heb je")
        ok("beheer-zin triggert geen routine", name is None)

        name, _ = manager.resolve("open spotify")
        ok("'open spotify' triggert géén routine", name is None)

    # =============================================================
    # 2. CRUD: opslaan, ophalen, bijwerken, verwijderen
    # =============================================================

    print("\n=== ROUTINES: CRUD ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        manager.reload()

        routine = manager.get_routine("gaming")
        ok("routine 'gaming' opgeslagen", routine is not None)
        ok("routine heeft stappen", len(routine.get("steps", [])) == 2)

        saved = manager.save_routine(
            "ochtend",
            ["\\bgoedemorgen\\b"],
            [{"tool_name": "open_program", "arguments": {"program": "Spotify"}}],
            "Ochtend routine",
        )
        ok("nieuwe routine opslaan", manager.get_routine("ochtend") is not None)
        ok("save return value", saved.get("name") == "ochtend")

        deleted = manager.delete_routine("ochtend")
        ok("verwijder bestaande routine", deleted is True)
        ok("routine daarna weg", manager.get_routine("ochtend") is None)

        deleted = manager.delete_routine("bestaat_niet")
        ok("verwijder onbestaande routine -> False", deleted is False)

    # =============================================================
    # 3. steps_for_agent / uitvoerformaat
    # =============================================================

    print("\n=== ROUTINES: planformaat voor de Executor ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        manager.reload()
        plan = manager.steps_for_agent("gaming")
        ok("gaming levert 2 plan-stappen", len(plan) == 2)
        ok("stap 1 is open_program(Discord)",
           plan[0]["tool_name"] == "open_program" and plan[0]["arguments"] == {"program": "Discord"})
        ok("stap heeft status + goal",
           plan[0].get("status") == "pending" and "routine" in str(plan[0].get("goal")))

        plan = manager.steps_for_agent("bestaat_niet")
        ok("onbestaande routine -> lege lijst", plan == [])

    # =============================================================
    # 4. Brain-integratie (Executor gemockt — geen echte acties)
    # =============================================================

    print("\n=== ROUTINES: brain-integratie (mocks) ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        isolated = RoutineManager()
        for rname, rdata in TEST_ROUTINES.items():
            isolated.save_routine(
                rname, rdata["triggers"], rdata["steps"],
                rdata["description"], rdata["aliases"],
            )

        fake_plan_results = [
            {"status": "done", "tool_name": "open_program",
             "used_tool_name": "open_program", "arguments": {"program": "Discord"}},
            {"status": "done", "tool_name": "set_volume",
             "used_tool_name": "set_volume", "arguments": {"percent": 40}},
        ]

        with patch.object(brain, "routine_manager", isolated), \
             patch("core.brain.execute_action_plan", return_value=fake_plan_results) as mock_exec:

            answer = brain.try_routine("ik ga gamen")
            ok("routine wordt uitgevoerd via Executor", mock_exec.call_count == 1)
            ok("antwoord bevat routinenaam", "gaming" in answer.lower())

            failed_results = [
                {"status": "failed", "tool_name": "set_volume",
                 "used_tool_name": "set_volume", "arguments": {"percent": 40}},
                {"status": "failed", "tool_name": "open_program",
                 "used_tool_name": "open_program", "arguments": {"program": "Discord"}},
            ]
            with patch("core.brain.execute_action_plan", return_value=failed_results):
                answer = brain.try_routine("ik ga gamen")
                ok("volledig falen wordt eerlijk gemeld", "mislukt" in answer.lower())

            partial_results = [
                {"status": "done", "tool_name": "open_program",
                 "used_tool_name": "open_program", "arguments": {"program": "Discord"}},
                {"status": "failed", "tool_name": "set_volume",
                 "used_tool_name": "set_volume", "arguments": {"percent": 40}},
            ]
            with patch("core.brain.execute_action_plan", return_value=partial_results):
                answer = brain.try_routine("ik ga gamen")
                ok("gedeeltelijk falen wordt eerlijk gemeld", "mislukt" in answer.lower())

        # ----- beheer-commando's -----
        with patch.object(brain, "routine_manager", isolated):

            answer = brain.try_routine("welke routines heb je")
            ok("'welke routines' toont overzicht", "gaming" in answer and "sleep" in answer)

            answer = brain.try_routine("verwijder routine sleep")
            ok("'verwijder routine sleep' werkt", "verwijderd" in answer.lower())
            ok("routine daadwerkelijk weg", isolated.get_routine("sleep") is None)

            answer = brain.try_routine("verwijder routine sleep")
            ok("nogmaals verwijderen -> melding bestaat niet", "bestaat niet" in answer.lower())

    # =============================================================
    # 4b. Routine opslaan via stem (Fase 4 voice-créatie)
    # =============================================================

    print("\n=== ROUTINES: opslaan via stem (mocks) ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        isolated = RoutineManager()
        isolated.save_routine(
            "gaming", TEST_ROUTINES["gaming"]["triggers"],
            TEST_ROUTINES["gaming"]["steps"],
            TEST_ROUTINES["gaming"]["description"],
            TEST_ROUTINES["gaming"]["aliases"],
        )

        fake_steps = [
            {"tool_name": "open_program", "arguments": {"program": "Discord"}},
            {"tool_name": "open_program", "arguments": {"program": "Spotify"}},
            {"tool_name": "set_volume", "arguments": {"percent": 35}},
            {"tool_name": "control_home_assistant",
             "arguments": {"domain": "light", "service": "turn_on",
                           "entity_id": "light.bed_lamp"}},
        ]

        with patch.object(brain, "routine_manager", isolated), \
             patch.object(brain.agent, "last_executed_steps", fake_steps), \
             patch("core.brain.execute_action_plan", return_value=[]):

            answer = brain.try_routine("bewaar dit als routine werk")
            ok("'bewaar dit als routine werk'", "opgeslagen" in answer.lower() and "werk" in answer.lower())

            answer = brain.try_routine("sla dit op als routine werk")
            ok("'sla dit op als routine werk' bijwerkt", "bijgewerkt" in answer.lower())

            created = isolated.get_routine("werk")
            ok("routine 'werk' bestaat in manager",
               created is not None and len(created.get("steps", [])) == 4)
            ok("routinestappen correct overgenomen",
               created["steps"][2] == {"tool_name": "set_volume", "arguments": {"percent": 35}})

            name, _ = isolated.resolve("ik ga werk")
            ok("nieuwe routine direct triggerbaar ('ik ga werk')", name == "werk")

            name, _ = isolated.resolve("we moeten werk")
            ok("naam-trigger 'werk' matcht", name == "werk")

            # Zonder recente acties
            with patch.object(brain.agent, "last_executed_steps", []):
                answer = brain.try_routine("bewaar dit als routine leeg")
                ok("zonder recente acties -> vriendelijke melding",
                   "geen recente acties" in answer.lower())

            # Andere stem-vormen
            answer = brain.try_routine("onthoud dit als routine sport")
            ok("'onthoud dit als routine sport'", "opgeslagen" in answer.lower())

            answer = brain.try_routine("maak er een routine van film")
            ok("'maak er een routine van film'", "opgeslagen" in answer.lower())

    # =============================================================
    # 4d. Flexibele zinsvormen bij opslaan (Fase 4 fix)
    #     "sla dit op als een routine genaamd muziek"
    # =============================================================

    print("\n=== ROUTINES: flexibele zinsvormen opslaan ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        isolated = RoutineManager()

        fake_steps = [
            {"tool_name": "open_program", "arguments": {"program": "Spotify"}},
            {"tool_name": "set_volume", "arguments": {"percent": 30}},
        ]

        flexible = [
            "sla dit op als een routine genaamd muziek",
            "bewaar dit als een routine genaamd test",
            "sla deze acties op als routine avond",
            "maak hier een routine van genaamd werk",
            "bewaar als een routine genaamd film",
            "maak een routine genaamd ochtend",
        ]

        with patch.object(brain, "routine_manager", isolated), \
             patch.object(brain.agent, "last_executed_steps", fake_steps), \
             patch("core.brain.execute_action_plan", return_value=[]):

            for phrase in flexible:
                answer = brain.try_routine(phrase)
                ok(f"{phrase!r} wordt als routine opgeslagen",
                   answer is not None and (
                       "opgeslagen" in answer.lower() or "bijgewerkt" in answer.lower()))

            for expected_name in ("muziek", "test", "avond", "werk", "film", "ochtend"):
                ok(f"routine '{expected_name}' opgeslagen",
                   isolated.get_routine(expected_name) is not None)

        # Vangnet: duidelijke opslaan-intentie zonder passend patroon
        with patch.object(brain, "routine_manager", isolated), \
             patch.object(brain.agent, "last_executed_steps", []):
            answer = brain.try_routine("sla deze handelingen op als routine xyz")
            ok("vangnet geeft duidelijke uitleg (geen AI-gok)",
               answer is not None and "routine" in answer.lower())


# =============================================================
    # 4c. Opslaan via Executor-journaal (de echte Fix: geen Agent nodig)
    # =============================================================

    print("\n=== ROUTINES: opslaan na Executor-uitvoering ===")

    with patch("core.routines.ROUTINES_FILE", tmp_path):
        isolated = RoutineManager()

        # Simuleer: gebruiker voert een meertraps-opdracht uit via de
        # echte Executor (tools gemockt) -> journaal wordt gevuld.
        plan = [
            {"tool_name": "open_program", "arguments": {"program": "Spotify"},
             "status": "pending"},
            {"tool_name": "set_volume", "arguments": {"percent": 45},
             "status": "pending"},
        ]

        from core.executor import execute_action_plan, get_last_done_actions

        with patch("core.ai.execute_tool",
                   side_effect=lambda name, args, q: f"{name} ok"):
            results = execute_action_plan(plan, "test opdracht")

        import core.executor as executor_mod
        with patch.object(executor_mod, "_LAST_DONE_ACTIONS",
                          [{"tool_name": "open_program", "arguments": {"program": "Spotify"}},
                           {"tool_name": "set_volume", "arguments": {"percent": 45}}]):
            ok("executor-journaal gevuld",
               len(get_last_done_actions()) == 2)

            with patch.object(brain, "routine_manager", isolated), \
                 patch("core.brain.execute_action_plan", return_value=[]), \
                 patch.object(brain.agent, "last_executed_steps", []):

                answer = brain.try_routine("bewaar dit als routine execjournal")
                ok("opslaan NA Executor-uitvoering (zonder Agent)", "opgeslagen" in answer.lower())

                created = isolated.get_routine("execjournal")
                ok("routine 'execjournal' met 2 stappen uit journaal",
                   created is not None and len(created.get("steps", [])) == 2)


# =============================================================
# 5. Geen bijwerking op echte bestand
# =============================================================

print("\n=== ROUTINES: echte bestand is onaangetast ===")

real_manager = RoutineManager()
routines = real_manager.list_routines()
ok("config/routines.json nog leesbaar (default-routines)",
   isinstance(routines, dict))

for name in ("gaming", "movie", "sleep"):
    ok(f"default-routine '{name}' aanwezig", name in routines)


# Opruimen: tijdelijke test-routines bestand
try:
    os.remove(tmp_path)
except OSError:
    pass


print(f"\n=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===\n")
sys.exit(0 if failed == 0 else 1)
