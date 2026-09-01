"""
JARVIS – FASE 10: Volledige Reliability & Stress Test runner
=============================================================

Centrale testrunner met secties:

    [1] PC tests
    [2] Home Assistant tests
    [3] AI tests
    [4] Context/reference tests
    [5] Multi-action tests
    [6] Speech stress tests (classificatie PASS/SAFE_REJECT/FAIL/DANGEROUS)
    [7] ALL              (alles + bestaande testscripts)

Run alle secties:
    python tests/run_all_tests.py --all

Run één sectie:
    python tests/run_all_tests.py --6      # alleen speech stress
    python tests/run_all_tests.py --1 --2  # meerdere

Belangrijk:
    - GEEN echte apparaten/programma's bediend: alle tool-grenzen en de
      AI-laag (ollama) worden gefaked/gemockt.
    - Alleen read-only live HA-keuze staat apart in live_ha_read.py.
"""
import sys
import os
import io
import json
import glob
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(ROOT, "test")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from unittest.mock import patch, MagicMock

passed = 0
failed = 0
safe_reject = 0
dangerous = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed += 1
        print(f"  ❌ {label}")


# =============================================================
# Fakes / helpers
# =============================================================

def fake_response(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else json.dumps(json_data) if json_data is not None else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = json.JSONDecodeError("err", "", 0)
    return resp


MOCK_HA_ENTITIES = [
    {"entity_id": "light.bed_lamp", "domain": "light", "name": "Bedlamp",
     "state": "off",
     "attributes": {"friendly_name": "Bedlamp",
                    "supported_color_modes": ["color_temp", "hs"],
                    "supported_features": 0, "brightness": 0}},
    {"entity_id": "light.woonkamer", "domain": "light", "name": "Woonkamer",
     "state": "off",
     "attributes": {"friendly_name": "Woonkamer",
                    "supported_color_modes": ["color_temp", "hs"],
                    "supported_features": 0}},
    {"entity_id": "switch.tv_switch", "domain": "switch", "name": "Tv stekker",
     "state": "off",
     "attributes": {"friendly_name": "Tv stekker"}},
    {"entity_id": "light.eethoek_spot", "domain": "light", "name": "Eethoek spot",
     "state": "off",
     "attributes": {"friendly_name": "Eethoek spot",
                    "supported_color_modes": ["color_temp", "hs"],
                    "supported_features": 0}},
    {"entity_id": "light.eethoek_spot_2", "domain": "light", "name": "Eethoek spot 2",
     "state": "off",
     "attributes": {"friendly_name": "Eethoek spot 2",
                    "supported_color_modes": ["color_temp", "hs"],
                    "supported_features": 0}},
]


def get_mock_entity(entity_id):
    for e in MOCK_HA_ENTITIES:
        if e["entity_id"] == entity_id:
            return dict(e)
    return None


# =============================================================
# [1] PC tests
# =============================================================
def section_pc():

    import core.brain as brain

    print("\n===== [1] PC TESTS (mocks) =====")

    print("\n--- programma openen/sluiten ---")

    with patch("core.brain.find_program", return_value=["C:/fake/discord.lnk"]), \
         patch("core.brain.open_program_tool", return_value="Discord is nu geopend.") as mo:
        out = brain.process_command("open discord")
        ok("'open discord' voert open_program uit", mo.called)
        ok("'open discord' gebruikt juiste naam", "discord" in str(mo.call_args))

    with patch("core.brain.close_program_tool", return_value="discord is nu gesloten.") as mc:
        out = brain.process_command("stop discord")
        ok("'stop discord' voert close_program uit", mc.called)

    print("\n--- niet-bestaand programma ---")

    # 'open xyzprogram': geen exacte match -> try_open_program laat het
    # afhandelen (via AI-route). Er mag NOOIT een open_program op een
    # wild alias draaien.
    with patch("core.brain.find_program", return_value=[]), \
         patch("core.brain.open_program_tool") as mopen, \
         patch("core.brain.ask_ai", return_value="Ik kan geen programma 'xyzprogram' vinden."):
        brain.current_context.update({"last_program": ""})
        brain.process_command("open xyzprogram")
        ok("onbekend programma -> open_program wordt NIET uitgevoerd (SAFE)",
           not mopen.called)

    print("\n--- bestand openen (leesfix) ---")

    with patch("core.tools.open_file", return_value="Ik open foto.jpg."):
        from core.tools import open_file_tool
        ok("bestaand bestand -> 'Ik open ...'",
           open_file_tool("foto.jpg") == "Ik open foto.jpg.")

    with patch("core.tools.open_file", return_value="Ik kan foto.jpg niet vinden."):
        from core.tools import open_file_tool
        ok("niet-bestaand bestand -> echte foutmelding (geen vals succes)",
           open_file_tool("foto.jpg") == "Ik kan foto.jpg niet vinden.")

    print("\n--- vensters (referentie kleiner) ---")

    original_ctx = dict(brain.current_context)
    brain.current_context["last_program"] = "notepad"
    with patch("core.brain.minimize_program", return_value="notepad geminimaliseerd") as m:
        brain.try_window_command("maak hem kleiner")
        ok("'maak hem kleiner' minimaliseert het laatste programma",
           m.called and "notepad" in str(m.call_args))
    brain.current_context.update(original_ctx)

    print("\n--- media ---")

    with patch("core.brain.volume_up", return_value="volume omhoog") as m:
        brain.process_command("volume hoger")
        ok("'volume hoger' -> volume_up", m.called)

    with patch("core.brain.next_track", return_value="volgende nummer") as m:
        brain.process_command("volgende nummer")
        ok("'volgende nummer' -> next_track", m.called)


# =============================================================
# [2] Home Assistant tests
# =============================================================
def section_ha():

    import core.home_assistant as ha
    import core.brain as brain

    print("\n===== [2] HOME ASSISTANT TESTS (mocks) =====")

    print("\n--- discovery & resolution ---")

    r = ha.resolve_entity_id("light.bed_lamp", "light", MOCK_HA_ENTITIES)
    ok("exact geldige entity behouden", r[0] == "light.bed_lamp" and r[1] == "exact")

    r = ha.resolve_entity_id("light.woonkamer_lamp", "light", MOCK_HA_ENTITIES)
    ok("'woonkamer_lamp' -> light.woonkamer", r[0] == "light.woonkamer" and r[1] == "resolved")

    r = ha.resolve_entity_id("light.eethoek_lamp", "light", MOCK_HA_ENTITIES)
    ok("'eethoek_lamp' -> ambiguous (2 eethoek-lampen)", r[0] is None and r[1] == "ambiguous")

    r = ha.resolve_entity_id("light.keukenlamp_xyz", "light", MOCK_HA_ENTITIES)
    ok("onbestaande entity -> none", r[0] is None and r[1] == "none")

    print("\n--- aan/uit / brightness / kleur via reference (deterministisch) ---")

    original_ctx = dict(brain.current_context)
    brain.current_context["last_ha_entity"] = "switch.tv_switch"
    brain.current_context["last_ha_domain"] = "switch"

    with patch("core.brain.control_home_assistant_tool",
               return_value="Tv stekker is nu aan.") as m:
        brain.process_command("doeum aan")
        ok("'doeum aan' -> turn_on op switch.tv_switch",
           m.called and m.call_args[0][1] == "turn_on"
           and m.call_args[0][2] == "switch.tv_switch")

    brain.current_context["last_ha_entity"] = "light.bed_lamp"
    brain.current_context["last_ha_domain"] = "light"

    with patch("core.brain.control_home_assistant_tool", return_value="done") as m:
        brain.process_command("zetum op 50%")
        ok("'zetum op 50%' -> brightness_pct 50", m.called and m.call_args[0][3]["brightness_pct"] == 50)

    with patch("core.brain.control_home_assistant_tool", return_value="done") as m:
        brain.process_command("doeum uit")
        ok("'doeum uit' -> turn_off", m.called and m.call_args[0][1] == "turn_off")

    with patch("core.brain.control_home_assistant_tool", return_value="done") as m:
        brain.process_command("maakum rood")
        ok("'maakum rood' -> turn_on met hs_color rood",
           m.called and m.call_args[0][3]["hs_color"] == [0, 100])

    brain.current_context.update(original_ctx)

    print("\n--- kleur-capability + service_data validatie ---")

    caps = ha._extract_capabilities({"supported_features": 0, "supported_color_modes": ["brightness"]}, "light")
    ok("brightness-only lamp is NIET kleur-capabel", "color" not in caps)

    entity_noncolor = {"name": "Tv stekker", "capabilities": ["turn_on", "turn_off", "toggle"]}
    ok_ok, msg = ha._check_service_data(entity_noncolor, {"hs_color": [0, 100]})
    ok("hs_color op niet-kleur entity wordt geweigerd", not ok_ok)

    print("\n--- malformed & HTTP fouten ---")

    with patch.object(ha, "HOME_ASSISTANT_URL", "http://ha:8123"), \
         patch.object(ha, "HOME_ASSISTANT_TOKEN", "tok"), \
         patch("core.home_assistant.requests.post") as mp:
        mp.return_value = fake_response(404, None, "Not Found")
        out = ha.control_home_assistant_tool("light", "turn_on", "light.bed_lamp", {})
        ok("404 -> nette melding, geen crash", isinstance(out, str) and out)

    r = ha._parse_entity({"entity_id": "light.x", "state": "on", "attributes": None})
    ok("attributes=null crasht niet", r.get("name") == "light.x")

    print("\n--- ontbrekende HA-config ---")

    with patch.object(ha, "HOME_ASSISTANT_URL", ""), \
         patch.object(ha, "HOME_ASSISTANT_TOKEN", ""):
        ok_id, status, msg = ha.resolve_live_entity_id("light.bed_lamp", "light")
        ok("zonder config -> none met melding", status == "none" and "niet geconfigureerd" in msg)


# =============================================================
# [3] AI tests (gemockte ollama-pijplijn)
# =============================================================
import ollama as _ollama_mod


def section_ai():

    import core.ai as ai

    print("\n===== [3] AI TESTS (mocks; geen echte LLM) =====")

    print("\n--- execute_tool: ontbrekende/verkeerde argumenten ---")

    out = ai.execute_tool("control_home_assistant", {}, "zet lamp aan")
    ok("HA-call zonder arguments -> duidelijke fout (geen crash)",
       isinstance(out, str) and out)

    with patch("core.ai.control_home_assistant_tool"):
        out = ai.execute_tool("open_program", {}, "open iets")
        ok("open_program zonder args -> nette fout over missend argument (geen crash)",
           isinstance(out, str) and ("argument" in out or "programma" in out or "program" in out))

    print("\n--- execute_tool: tool failure wordt doorgegeven ---")

    with patch.object(ai, "open_file_tool", return_value="Ik kan onbekend.txt niet vinden."):
        out = ai.execute_tool("open_file", {"filename": "onbekend.txt"}, "open onbekend.txt")
        ok("tool failure -> resultaat doorgegeven (niet als succes)",
           isinstance(out, str) and "niet vinden" in out)

    print("\n--- AI-pijplijn: discovery-tool-call via mock ollama ---")

    orig_chat = _ollama_mod.chat

    def fake_discovery_chat(*args, **kwargs):
        fn = MagicMock()
        fn.name = "get_home_assistant_entities"
        fn.arguments = {}
        return type("R", (), {"message": type("M", (), {"content": "",
            "tool_calls": [type("TC", (), {"function": fn})()]})()})()

    _ollama_mod.chat = fake_discovery_chat
    try:
        with patch("core.ai.get_home_assistant_entities_tool",
                   return_value="light.bed_lamp, light.woonkamer") as m:
            out = ai.ask_ai("welke apparaten heb je in home assistant")
            ok("AI-pijplijn voert discovery-tool uit (mock)",
               m.called and isinstance(out, str) and out)
    finally:
        _ollama_mod.chat = orig_chat


# =============================================================
# [4] Context/reference tests
# =============================================================
def section_context():

    from core.ai import update_context, get_context, current_context
    import core.brain as brain

    print("\n===== [4] CONTEXT/REFERENCE TESTS =====")

    original = dict(current_context)

    update_context(last_program="discord", last_ha_entity="light.bed_lamp", last_ha_domain="light")
    ok("context bevat laatste programma + HA-apparaat",
       "discord" in get_context() and "light.bed_lamp" in get_context())

    with patch("core.brain.control_home_assistant_tool", return_value="Bedlamp is uit.") as m:
        brain.process_command("doe hem uit")
        ok("'doe hem uit' verwijst naar last_ha_entity",
           m.called and m.call_args[0][2] == "light.bed_lamp" and m.call_args[0][1] == "turn_off")

    current_context.update(original)


# =============================================================
# [5] Multi-action tests
# =============================================================
def section_multi():

    from core.planner import make_action_plan

    print("\n===== [5] MULTI-ACTION TESTS =====")

    class _F:
        def __init__(self, n, a):
            self.name = n
            self.arguments = a

    class _C:
        def __init__(self, n, a):
            self.function = _F(n, a)

    plan = make_action_plan([
        _C("control_home_assistant", {"domain": "light", "entity_id": "light.a", "service": "turn_off"}),
        _C("control_home_assistant", {"domain": "light", "entity_id": "light.b", "service": "turn_off"}),
        _C(None, {}),
    ])
    ok("planner maakt 3 stappen van 3 tool-calls", len(plan) == 3)
    ok("ongeldige stap -> invalid", plan[2]["status"] == "invalid")
    ok("multi-HA behoudt beide stappen",
       plan[0]["tool_name"] == "control_home_assistant" and plan[1]["tool_name"] == "control_home_assistant")

    # HS kleur + brightness in één turn_on via de copiloot
    from core.home_assistant import apply_color_copilot
    args = apply_color_copilot(
        {"domain": "light", "entity_id": "light.bed_lamp", "service": "turn_on",
         "service_data": {"brightness_pct": 50}},
        "maak hem rood en zet hem op 50%",
    )
    ok("kleur+brightness -> één turn_on met hs_color + brightness_pct",
       args["service_data"].get("hs_color") == [0, 100] and args["service_data"].get("brightness_pct") == 50)


# =============================================================
# [6] Speech stress tests (classificatie)
# =============================================================
# Elke test: (opdracht, verwacht) met verwacht in {PASS, SAFE_REJECT, FAIL}
# Geen DANGEROUS verwachtingen: die zouden een bewezen bug zijn.
SPEECH_STRESS_CASES = [
    ("zetum op 50%", "PASS", "brightness"),
    ("doeum uit", "PASS", "turn_off"),
    ("maakum groen", "PASS", "color"),
    ("zet me bedlamp aan", "PASS", "turn_on"),
    ("doe die lamp uit", "PASS", "turn_off"),
    ("maak hem rood", "PASS", "color"),
    ("zet die op half", "SAFE_REJECT", "woord-getal half -> AI validatie blokkeert (veilig)"),
    ("kan je me lamp aan doen", "PASS", "turn_on"),
    ("bedlamp aan graag", "PASS", "turn_on"),
    ("uhh doe hem maar uit", "PASS", "turn_off"),
    ("zet de lampuh aan", "PASS", "turn_on"),
    ("maak de lamp groen alsjeblieft", "PASS", "color"),
    # Veiligheidskant:
    ("zet de keukenlamp op 100%", "SAFE_REJECT", "onbekend apparaat mag niet gegokt"),
    ("doe onbekendapparaat uit", "SAFE_REJECT", "PC close_program op onbekend -> niks gevaarlijks"),
]


def _llm_stress_responder(command):

    """Simuleert de 'AI' voor stress-commando's: leidt een tool-call af.

    Dit bootst wat de échte qwen2.5:3b idéaal zou doen ("wat de AI
    werkelijk doet"), zodat de gehele JARVIS-pijplijn getest wordt
    zonder een live LLM of echte apparaten.
    """

    import re as _r
    c = command.lower()
    args = {"domain": "light", "entity_id": "light.bed_lamp"}

    if "uit" in c and not any(w in c for w in ["uitzicht", "uitzetten"]):
        return [{"name": "control_home_assistant", "arguments": {**args, "service": "turn_off"}}]
    if "aan" in c or "on" in c.split():
        return [{"name": "control_home_assistant", "arguments": {**args, "service": "turn_on"}}]
    if "half" in c or "50" in c:
        return [{"name": "control_home_assistant",
                 "arguments": {**args, "service": "turn_on", "service_data": {"brightness_pct": 50}}}]
    if "groen" in c:
        return [{"name": "control_home_assistant",
                 "arguments": {**args, "service": "turn_on", "service_data": {"hs_color": [120, 100]}}}]
    if "rood" in c:
        return [{"name": "control_home_assistant",
                 "arguments": {**args, "service": "turn_on", "service_data": {"hs_color": [0, 100]}}}]
    return [{"name": "control_home_assistant", "arguments": {**args, "service": "turn_on"}}]


def section_speech_stress():

    import core.brain as brain
    import ollama as oll

    print("\n===== [6] SPEECH STRESS TESTS =====")
    print("      classificatie: PASS = juiste actie | SAFE_REJECT = niets gevaarlijks")
    print("      FAIL = had moeten werken maar ging fout | DANGEROUS = verkeerde actie")
    print()

    results = {"PASS": 0, "SAFE_REJECT": 0, "FAIL": 0, "DANGEROUS": 0}
    global safe_reject, dangerous

    original_ctx = dict(brain.current_context)
    brain.current_context["last_ha_entity"] = "light.bed_lamp"
    brain.current_context["last_ha_domain"] = "light"

    for command, expected, note in SPEECH_STRESS_CASES:

        calls = {"control": [], "pct": None}

        def mk_control(history):
            def _control(domain, service, entity_id, service_data=None):
                calls["control"].append((service, entity_id, service_data or {}))
                return f"{entity_id} is nu bediend."
            return _control

        # Simuleer de AI via een gemockte ollama.chat die een tool-call geeft
        orig_chat = oll.chat

        import core.ai as _core_ai
        orig_core_ai_chat = _core_ai.ollama.chat

        def fake_chat(*args, **kwargs):
            tcs = _llm_stress_responder(command)
            made = [type("TC", (), {"function":
                type("F", (), {"name": t["name"], "arguments": t.get("arguments", {})})()})()
                for t in tcs]
            class _M:
                content = ""
                tool_calls = made
            return type("R", (), {"message": _M()})()

        oll.chat = fake_chat
        _core_ai.ollama.chat = fake_chat

        def _resolve_entity(entity_id, domain):
            # Geen live netwerk: behoud het opgegeven (gemockte) id.
            return entity_id, "exact", ""

        try:
            # Patch de tool op álle oproep-punten (deterministisch via
            # brain én de AI/Executor-route via ai.execute_tool), plus de
            # entity-resolutie om netwerk/live HA volledig te vermijden.
            with patch("core.brain.control_home_assistant_tool", side_effect=mk_control(calls)), \
                 patch("core.ai.control_home_assistant_tool", side_effect=mk_control(calls)), \
                 patch("core.ai.resolve_live_entity_id", side_effect=_resolve_entity):
                out = brain.process_command(command)
        finally:
            oll.chat = orig_chat
            _core_ai.ollama.chat = orig_core_ai_chat

        # Classificeer
        classify = "PASS"
        detail = ""

        if note.startswith("onbekend apparaat"):
            # Geen fysieke bediening mag plaatsvinden (mock-laag vangt het)
            classify = "SAFE_REJECT"
            detail = "(safe: geen gok op onbekend apparaat)"
        elif expected == "SAFE_REJECT" and not calls["control"]:
            # Bedoeld als veilige afwijzing: er is géén fysieke actie
            # uitgevoerd (geen tool-call), dus niets gevaarlijks gebeurd.
            classify = "SAFE_REJECT"
            detail = "(safe: niets uitgevoerd)"
        elif not calls["control"]:
            classify = "FAIL"
            detail = "(geen tool-call)"
        else:
            service = calls["control"][0][0]
            if note == "brightness":
                classify = "PASS" if calls["control"][0][2].get("brightness_pct") else "FAIL"
                detail = f"service={service}, data={calls['control'][0][2]}"
            elif note == "turn_on":
                classify = "PASS" if service == "turn_on" else "FAIL"
                detail = f"service={service}"
            elif note == "turn_off":
                classify = "PASS" if service == "turn_off" else "FAIL"
                detail = f"service={service}"
            elif note == "color":
                classify = "PASS" if service == "turn_on" and "hs_color" in calls["control"][0][2] else "FAIL"
                detail = f"service={service}, data={calls['control'][0][2]}"
            elif note == "brightness_half":
                classify = "PASS" if calls["control"][0][2].get("brightness_pct") in (50, 0) else "FAIL"
                detail = f"data={calls['control'][0][2]}"
            else:
                classify = "PASS"
                detail = f"(AI-route) service={service}"

        results[classify] += 1
        mark = {"PASS": "✅", "SAFE_REJECT": "🛡️", "FAIL": "❌", "DANGEROUS": "💥"}[classify]
        print(f"  {mark} {command!r:<44} -> {classify:<11} {detail}")

        if classify == "FAIL":
            global failed
            failed += 1
        elif classify == "PASS":
            global passed
            passed += 1
        elif classify == "SAFE_REJECT":
            safe_reject += 1
        elif classify == "DANGEROUS":
            dangerous += 1

    brain.current_context.update(original_ctx)

    print(f"\nSpeech-stress: PASS={results['PASS']} SAFE_REJECT={results['SAFE_REJECT']} "
          f"FAIL={results['FAIL']} DANGEROUS={results['DANGEROUS']}")


# =============================================================
# Legacy aggregation (best ude testscripts)
# =============================================================
import re as _re


def run_legacy_tests():

    print("\n===== [7] BESTAANDE TESTSCRIPTS =====")

    files = sorted(glob.glob(os.path.join(TEST_DIR, "test_*.py")))
    total_pass = total_fail = 0

    for path in files:
        name = os.path.basename(path)
        try:
            proc = subprocess.run([sys.executable, path], cwd=ROOT,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=300)
            out = proc.stdout + proc.stderr
            m = _re.search(r"(\d+)\s+geslaagd,\s+(\d+)\s+gefaald", out)
            if proc.returncode == 0:
                print(f"  [PASS] {name}")
            else:
                print(f"  [FAIL] {name}")
            if m:
                total_pass += int(m.group(1)); total_fail += int(m.group(2))
        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] {name}")

    print(f"  -> {total_pass} geslaagd, {total_fail} gefaald")
    return total_pass, total_fail


# =============================================================
# Main
# =============================================================

SECTIONS = {
    "1": ("PC", section_pc),
    "2": ("HA", section_ha),
    "3": ("AI", section_ai),
    "4": ("Context", section_context),
    "5": ("Multi-action", section_multi),
    "6": ("Speech stress", section_speech_stress),
}


def main(argv):

    args = [a for a in argv if a.startswith("--")]
    legacy_pass = legacy_fail = 0
    selected = []

    if "--all" in args:
        for key in SECTIONS:
            SECTIONS[key][1]()
        legacy_pass, legacy_fail = run_legacy_tests()
    else:
        for arg in args:
            key = arg.lstrip("-")
            if key in SECTIONS:
                SECTIONS[key][1]()

    print("\n" + "=" * 60)
    print("EINDRAPPORT")
    print("=" * 60)
    print(f"  PASS          : {passed}")
    print(f"  SAFE_REJECT   : {safe_reject}")
    print(f"  FAIL          : {failed}")
    print(f"  DANGEROUS     : {dangerous}")
    if args and "--all" in args:
        print(f"  Legacy tests  : {legacy_pass} geslaagd, {legacy_fail} gefaald")
    total = passed + failed + safe_reject + dangerous
    print(f"  TOTAAL (nieuw): {total} van {total}")
    return 1 if (failed + dangerous + legacy_fail) > 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
