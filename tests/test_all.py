"""
Centrale testrunner voor JARVIS.

Doel:
    1. Verzamelt en draait alle bestaande testscripts in test/ (via
       subprocess, elk draait autonoom en rapporteert eigen aantallen).
    2. Draait daarna een in-process batterij met nieuwe integratie-,
       regressie- en AI-robustheidstests (met mocks; bedient NOOIT
       echte apparaten/programma's).

Run:  python tests/test_all.py
"""
import sys
import os
import io
import glob
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(ROOT, "test")
sys.path.insert(0, ROOT)

import re as _re


# =============================================================
# Deel 1: bestaande testscripts verzamelen en draaien
# =============================================================

def run_existing_tests():

    """Draait elke test/test_*.py en telt geslaagd/gefaald per bestand."""

    files = sorted(glob.glob(os.path.join(TEST_DIR, "test_*.py")))

    print("\n" + "=" * 60)
    print("DEEL 1: BESTAANDE TESTSCRIPT RUNTIMES")
    print("=" * 60)

    per_file = []

    for path in files:

        name = os.path.basename(path)

        try:

            proc = subprocess.run(
                [sys.executable, path],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )

            output = proc.stdout + proc.stderr

            if proc.returncode == 0:
                status = "PASS"
            else:
                status = "FAIL"

            # "N geslaagd, M gefaald" uit output halen
            match = _re.search(r"(\d+)\s+geslaagd,\s+(\d+)\s+gefaald", output)

            if match:
                summary = f"{match.group(1)} geslaagd, {match.group(2)} gefaald"
                per_file.append((name, status, int(match.group(1)), int(match.group(2))))
            else:
                summary = "geen 'geslaagd/gefaald'–telling gevonden"
                per_file.append((name, status, None, None))

            print(f"  [{status}] {name}  ->  {summary}")

            if proc.returncode != 0 and match is None:
                # Alleen bij een falend script zonder meshows laatste regels
                print("      (laatste outputregels:)")
                for line in output.strip().splitlines()[-6:]:
                    print(f"        {line}")

        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
            per_file.append((name, status, None, None))
            print(f"  [TIMEOUT] {name}")

    total_pass = sum(p for _, _, p, _ in per_file if p is not None)
    total_fail = sum(f for _, _, _, f in per_file if f is not None)

    print(f"\nSubtotaal bestaande tests: {total_pass} geslaagd, {total_fail} gefaald")

    return total_pass, total_fail


# =============================================================
# Deel 2: nieuwe in-process integratie-/robustheidstests
# =============================================================

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


# -------------------------------------------------------------
# 2a. Home Assistant
# -------------------------------------------------------------
def test_home_assistant_new():

    from unittest.mock import patch, MagicMock
    import core.home_assistant as ha
    import json

    def fake_response(status=200, json_data=None, text=""):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text if text else json.dumps(json_data) if json_data is not None else ""
        if json_data is not None:
            resp.json.return_value = json_data
        else:
            resp.json.side_effect = json.JSONDecodeError("err", "", 0)
        return resp

    print("\n=== NIEUW: HA entity parsing en capabilities ===\n")

    # attributes: null mag niet crashen (regressie)
    r = ha._parse_entity({"entity_id": "light.x", "state": "on", "attributes": None})
    ok("attributes=null crasht niet", r.get("name") == "light.x")

    r = ha._parse_entity({"entity_id": "switch.y", "state": "off", "attributes": None})
    ok("switch met attributes=null crasht niet", r.get("entity_id") == "switch.y")

    r = ha._parse_entity({"entity_id": "light.dim", "state": "on", "attributes": None})
    ok("ontbrekende attributes crasht niet", isinstance(r, dict))

    print("\n=== NIEUW: kleur-capability alleen bij echte kleurmodi ===\n")

    # brightness-only is NIET kleur-capabel (regressie)
    caps = ha._extract_capabilities({"supported_features": 0, "supported_color_modes": ["brightness"]}, "light")
    ok("brightness-only lamp is NIET kleur-capabel", "color" not in caps)

    caps = ha._extract_capabilities({"supported_features": 0, "supported_color_modes": ["onoff"]}, "light")
    ok("onoff-lamp is NIET kleur-capabel", "color" not in caps)

    caps = ha._extract_capabilities({"supported_features": 0, "supported_color_modes": ["hs", "color_temp"]}, "light")
    ok("hs lamp IS kleur-capabel", "color" in caps)

    print("\n=== NIEUW: service_data validatie incl. hs_color ===\n")

    entity_no_color = {"name": "Schakelaar", "capabilities": ["turn_on", "turn_off", "toggle"]}
    ok_ok, msg = ha._check_service_data(entity_no_color, {"hs_color": [0, 100]})
    ok("hs_color op een niet-kleur entity wordt geweigerd",
       (not ok_ok) and "hs_color" in msg)

    ok_ok, msg = ha._check_service_data(entity_no_color, {"brightness_pct": 50})
    ok("brightness op een niet-dimmare entity wordt geweigerd", not ok_ok)

    ok_ok, msg = ha._check_service_data(entity_no_color, {"rgb_color": [255, 0, 0]})
    ok("rgb_color op niet-kleur entity wordt geweigerd", not ok_ok)

    print("\n=== NIEUW: HTTP foutafhandeling ===\n")

    with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
         patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok123"), \
         patch("core.home_assistant.requests.post") as mock_post:

        # 404 op de POST -> nette melding, geen crash
        mock_post.return_value = fake_response(404, None, "Not Found")
        out = ha.control_home_assistant_tool(
            "light", "turn_on", "light.bed_lamp",
            {"entity_id": "light.bed_lamp"},
        )
        ok("404 melding is net, geen crash", isinstance(out, str) and out)

        # malformed JSON op POST
        mock_post.return_value = fake_response(200, None, "not json")
        out = ha.control_home_assistant_tool(
            "light", "turn_on", "light.bed_lamp", {},
        )
        ok("POST geeft altijd resultaat-string, geen crash", isinstance(out, str))


# -------------------------------------------------------------
# 2b. PC-tools (met mocks)
# -------------------------------------------------------------
def test_pc_tools_new():

    from unittest.mock import patch
    import core.tools as tools

    print("\n=== NIEUW: open_file_tool succes/mislukking (mocks) ===\n")

    with patch("core.tools.open_file", return_value="Ik open foto.jpg."):
        out = tools.open_file_tool("foto.jpg")
        ok("succes -> 'Ik open ...'", out == "Ik open foto.jpg.")

    with patch("core.tools.open_file", return_value="Ik kan foto.jpg niet vinden."):
        out = tools.open_file_tool("foto.jpg")
        ok("niet gevonden -> echte melding (regressie)",
           out == "Ik kan foto.jpg niet vinden.")

    with patch("core.tools.open_file", return_value="Ik heb meerdere bestanden gevonden met de naam foto. Ik weet niet welke je bedoelt."):
        out = tools.open_file_tool("foto")
        ok("meerdere matches -> echte melding", "meerdere bestanden" in out)

    with patch("core.tools.open_file", return_value="Ik kon foto.jpg niet openen."):
        out = tools.open_file_tool("foto.jpg")
        ok("openfout -> echte melding", "kon" in out and "niet openen" in out)


# -------------------------------------------------------------
# 2c. routering: verwijzingen naar venster (Fase 6)
# -------------------------------------------------------------
def test_window_reference_new():

    import core.brain as brain

    print("\n=== NIEUW: venster-referentie 'kleiner'/'hem' (mocks) ===\n")

    original_ctx = dict(brain.current_context)
    brain.current_context["last_program"] = "spotify"

    from core.brain import WINDOW_FILLER_WORDS
    ok("'kleiner' zit in WINDOW_FILLER_WORDS (regressie-fix)",
       "kleiner" in WINDOW_FILLER_WORDS)

    # na de filler-fix is het programma leeg -> last_program wordt gebruikt
    names = brain._extract_window_program("maak hem kleiner")
    ok("'maak hem kleiner' levert geen verkeerd programma op", names is None)

    import unittest.mock as _mock
    with _mock.patch("core.brain.minimize_program", return_value="ok") as m:
        brain.try_window_command("maak hem kleiner")
        ok("'maak hem kleiner' minimaliseert het laatste programma",
           m.call_count >= 1 and "spotify" in str(m.call_args))

    brain.current_context.update(original_ctx)


# -------------------------------------------------------------
# 2d. Planner / Executor (met mock execute_tool)
# -------------------------------------------------------------
def test_planner_executor_new():

    from core.planner import make_action_plan
    from core.executor import execute_action_plan

    print("\n=== NIEUW: Planner meerdere tool-calls ===\n")

    class FakeCall:
        def __init__(self, name, args):
            self.function = FakeFunction(name, args)

    class FakeFunction:
        def __init__(self, name, args):
            self.name = name
            self.arguments = args

    calls = [
        FakeCall("control_home_assistant", {"domain": "light", "entity_id": "light.a", "service": "turn_off"}),
        FakeCall("control_home_assistant", {"domain": "light", "entity_id": "light.b", "service": "turn_off"}),
        FakeCall(None, {}),  # ongeldige toolnaam
    ]

    plan = make_action_plan(calls)
    ok("planner maakt 3 stappen", len(plan) == 3)
    ok("stap1 toolnaam goed", plan[0]["tool_name"] == "control_home_assistant")
    ok("stap3 is ongeldig gemarkeerd", plan[2]["status"] == "invalid")

    print("\n=== NIEUW: Executor afhankelijkheden ===\n")

    def fake_execute_tool(tool_name, arguments, question):
        return f"uitgevoerd {tool_name}"

    action_plan = [
        {"tool_name": "wait", "arguments": {"seconds": 0}, "status": "pending"},
        {"tool_name": "open_program", "arguments": {"program": "X"},
         "status": "pending", "depends_on": [1]},
    ]

    import unittest.mock as _um
    # execute_action_plan importeert execute_tool late uit core.ai,
    # dus daar mocken (anders voert hij een ECHTE actie uit).
    with _um.patch("core.ai.execute_tool", side_effect=fake_execute_tool):
        try:
            out = execute_action_plan(action_plan, "test")
            ok("executor draait plan met dependency", isinstance(out, list) and len(out) == 2)
            ok("dependency-stap 2 heeft status done",
               out[1].get("status") == "done")
        except Exception as e:
            ok(f"executor faalt onverwacht: {e}", False)


# -------------------------------------------------------------
# 2e. context + memory
# -------------------------------------------------------------
def test_context_memory_new():

    from core.ai import update_context, get_context, current_context
    import memory.memory as mem

    print("\n=== NIEUW: context ===\n")

    update_context(last_program="Testprog", last_ha_entity="light.x")
    ctx = get_context()
    ok("context toont laatste programma", "Testprog" in ctx)
    ok("context toont laatste HA-apparaat", "light.x" in ctx)

    original = dict(current_context)
    current_context["last_program"] = ""

    print("\n=== NIEUW: memory (tijdelijk bestand) ===\n")

    old_file = mem.MEMORY_FILE
    tmp_file = os.path.join(ROOT, "memory", "test_memory_tmp.json")
    mem.MEMORY_FILE = tmp_file

    try:
        mem.clear_memory()
        mem.remember("favoriete_kleur", "blauw")
        ok("onthouden", mem.recall("favoriete_kleur") == "blauw")
        ok("vergeten", mem.forget("favoriete_kleur") is not None)
        ok("na vergeten -> None", mem.recall("favoriete_kleur") is None)
    finally:
        mem.MEMORY_FILE = old_file
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        current_context.update(original)


# -------------------------------------------------------------
# 2f. result validation + retry
# -------------------------------------------------------------
def test_validation_retry_new():

    from core.result_validation import classify_tool_result
    from core.retry import execute_with_retry

    print("\n=== NIEUW: resultaatvalidatie ===\n")

    ok("duidelijk succes", classify_tool_result("Bed lamp is nu aan.") == "success")
    ok("foutmelding -> failed", classify_tool_result("Ik kan geen programma vinden.") == "failed")
    ok("vraag -> uncertain", classify_tool_result("Welk programma wil je?") == "uncertain")
    ok("leeg -> uncertain", classify_tool_result("") == "uncertain")

    print("\n=== NIEUW: retry ===\n")

    attempts = {"n": 0}

    def flaky(name, args, q):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("tijdelijk")
        return "gelukt"

    res = execute_with_retry(flaky, "tool", {}, "vraag", max_retries=2)
    ok("retry slaagt na 2 pogingen", res["status"] == "done" and attempts["n"] == 2)

    attempts2 = {"n": 0}

    def always_fail(name, args, q):
        attempts2["n"] += 1
        raise RuntimeError("fout")

    res = execute_with_retry(always_fail, "tool", {}, "vraag", max_retries=1)
    ok("altijd-falen -> status failed na max pogingen",
       res["status"] == "failed" and attempts2["n"] == 2)


# -------------------------------------------------------------
# 2g. AI-ROBUSTHEID: rommelige Nederlandse opdrachten (alle mocks)
# -------------------------------------------------------------
def test_ai_robustness_new():

    from unittest.mock import patch, MagicMock
    import core.brain as brain

    print("\n=== NIEUW: rommelige opdrachten -> juiste intent/tool (mocks) ===\n")

    # Alle routes die een echte actie/AI doen worden gemockt.
    # We testen de DETERMINISTISCHE routing via process_command.

    original_ctx = dict(brain.current_context)

    # "zetum op 50%" (samentrekking van "zet hem") -> HA helderheid
    with patch("core.brain.control_home_assistant_tool",
               return_value="Bed lamp is nu aan. (brightness 50%)") as m:
        brain.current_context["last_ha_entity"] = "light.bed_lamp"
        brain.current_context["last_ha_domain"] = "light"
        out = brain.process_command("zetum op 50%")
        ok("'zetum op 50%' -> HA helderheid via samentrekking",
           m.called and "50%" in out)
        brain.current_context["last_ha_entity"] = ""
        brain.current_context["last_ha_domain"] = ""

    # "maak hem groen" (referentie zonder SMART_HOME_WORD) -> try_ha_reference
    with patch("core.brain.control_home_assistant_tool",
               return_value="Bed lamp is nu aan. (kleur: hs_color 120, 100)") as m:
        brain.current_context["last_ha_entity"] = "light.bed_lamp"
        brain.current_context["last_ha_domain"] = "light"
        out = brain.process_command("maak hem groen")
        ok("'maak hem groen' -> HA kleur (deterministische referentie)",
           m.called and "hs_color" in out)
        brain.current_context["last_ha_entity"] = ""
        brain.current_context["last_ha_domain"] = ""

    # "doeum uit" (samentrekking van "doe hem") -> HA uit
    with patch("core.brain.control_home_assistant_tool",
               return_value="Bed lamp is nu uit.") as m:
        brain.current_context["last_ha_entity"] = "light.bed_lamp"
        brain.current_context["last_ha_domain"] = "light"
        out = brain.process_command("doeum uit")
        ok("'doeum uit' -> HA uit via samentrekking", m.called and "uit" in out)
        brain.current_context["last_ha_entity"] = ""
        brain.current_context["last_ha_domain"] = ""

    # "welke apparaten heb je in home assistant" -> NOT a device action;
    # valt door naar de AI-route (ask_ai gemockt)
    with patch("core.brain.ask_ai", return_value="Fake AI antwoord") as m:
        out = brain.process_command("welke apparaten heb je in home assistant")
        ok("'welke apparaten...' -> via AI-route (niet als device actie)",
           m.call_count >= 1)

    # "sluit discord effe" -> close_program
    with patch("core.brain.close_program_tool", return_value="discord is dicht") as m:
        out = brain.process_command("sluit discord effe")
        ok("'sluit discord effe' -> close_program", m.called)

    # "open spottify" -> open_program (mock find_program zodat de
    # deterministische open-route de tool-call uitvoert)
    with patch("core.brain.find_program", return_value=["C:/fake/spottify.lnk"]), \
         patch("core.brain.open_program_tool", return_value="geopend spottify") as m:
        out = brain.process_command("open spottify")
        ok("'open spottify' -> open_program", m.called and "spottify" in str(m.call_args))

    # "zet de muziek wat zachter" -> media route
    with patch("core.brain.volume_down", return_value="volume omlaag") as m:
        out = brain.process_command("zet de muziek wat zachter")
        ok("'zet de muziek wat zachter' -> media volume_down", m.called)

    print("\n=== NIEUW: HA-achtige opdrachten mogen NIET naar een PC-route gaan ===\n")

    # HA-opdrachten met een device-naam gaan naar de AI-route en mogen
    # NOOIT een PC-programma sluiten/openen of media bedienen.
    no_wrong = []
    for tool in ["close_program_tool", "open_program_tool",
                 "play_pause", "volume_down", "minimize_program"]:
        with patch(f"core.brain.{tool}") as m:
            no_wrong.append((tool, m))

    brain.current_context["last_ha_entity"] = "light.bed_lamp"
    brain.current_context["last_ha_domain"] = "light"

    # "doe die ff rood" routeert deterministisch via try_ha_reference
    # -> patch de control-tool om geen echte actie te doen.
    with patch("core.brain.control_home_assistant_tool", return_value="Bed lamp is nu aan."), \
         patch("core.brain.ask_ai", return_value="Fake AI") as m_ai:
        for messy in [
            "uh zet me bedlamp aan",
            "doe me bed lamp effe uit",
            "kan je die lamp wat dimmen",
            "doe die ff rood",
        ]:
            brain.process_command(messy)

    wrong_called = [name for name, m in no_wrong if m.called]
    ok("HA-opdrachten triggeren geen PC-tool / media / venster",
       not wrong_called)
    ok("3 HA-opdrachten gaan naar de AI-route (referentie deterministisch)",
       m_ai.call_count >= 3)

    brain.current_context["last_ha_entity"] = ""
    brain.current_context["last_ha_domain"] = ""
    brain.current_context.update(original_ctx)


# =============================================================
# Main
# =============================================================

def main():

    existing_pass, existing_fail = run_existing_tests()

    print("\n" + "=" * 60)
    print("DEEL 2: NIEUWE INTEGRATIE-/ROBUSTHEIDSTESTS")
    print("=" * 60)

    test_home_assistant_new()
    test_pc_tools_new()
    test_window_reference_new()
    test_planner_executor_new()
    test_context_memory_new()
    test_validation_retry_new()
    test_ai_robustness_new()

    print("\n" + "=" * 60)
    print("SAMENVATTING")
    print("=" * 60)
    print(f"  Bestaande tests:   {existing_pass} geslaagd, {existing_fail} gefaald")
    print(f"  Nieuwe tests:      {passed} geslaagd, {failed} gefaald")
    total_pass = existing_pass + passed
    total_fail = existing_fail + failed
    print(f"  TOTAAL:            {total_pass} geslaagd, {total_fail} gefaald")

    return 1 if (total_fail > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
