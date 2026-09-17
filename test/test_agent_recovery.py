"""
JARVIS - Fase 12: Agent Recovery tests
========================================

Test de nieuwe method-choice + recovery logica:

  [1] _is_logical_failure: dict met ok=False detecteert
  [2] _is_logical_failure: stringified dict ({"ok": False}) detecteert
  [3] _is_logical_failure: dict met error_type detecteert
  [4] _is_logical_failure: succesvolle dict -> geen failure
  [5] _is_logical_failure: tekst "kon niet" -> failure (Fase 9 patronen)
  [6] retry: logische mislukking ONMIDDELLIJK naar fallback (geen 2e retry)
  [7] retry: fallback retourneert {"ok": False} -> niet geaccepteerd
  [8] executor: fallback_used wordt doorgegeven aan het record
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import core.retry as retry
from core.result_validation import classify_tool_result

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}" + (f"  | {detail}" if detail else ""))


# ==============================================
# _is_logical_failure
# ==============================================

ok("1. dict ok=False -> failure",
   retry._is_logical_failure({"ok": False, "status": "fout"}))
ok("2. stringified dict ok=False -> failure",
   retry._is_logical_failure("{'ok': False, 'status': 'fout'}"))
ok("3. dict error_type -> failure",
   retry._is_logical_failure({"ok": True, "error_type": "browser_niet_gevonden", "error": "x"}))
ok("4. succesvol dict -> geen failure",
   retry._is_logical_failure({"ok": True, "status": "200", "url": "..."}) is False)
ok("5. tekst 'kon niet' -> failure",
   retry._is_logical_failure("Ik kon Spotify niet vinden. Actie niet uitgevoerd."))
ok("5b. normale tekst -> geen failure",
   retry._is_logical_failure("Spotify wordt geminimaliseerd.") is False)


# ==============================================
# retry: logische mislukking -> directe fallback
# ==============================================

# [6] Logische mislukking: retry probeert dezelfde tool NIET opnieuw,
#     maar springt direct naar de fallback.
seen_calls = []

def runner_logical(tool, args, q):
    seen_calls.append(tool)
    if tool == "browser_search":
        return {"ok": False, "status": "fout", "error_type": "browser_niet_gevonden",
                "error": "geen browser"}
    if tool == "web_search":
        return "gezocht via DuckDuckGo"
    return "ok"

r = retry.execute_with_retry(runner_logical, "browser_search", {"query": "hondjes"},
                             "zoek", max_retries=2, use_fallbacks=True)
ok("6. logische mislukking -> fallback gebruikt",
   r["status"] == "done" and r.get("fallback_used") == "web_search", str(r))
ok("6b. primaire tool niet opnieuw geretried (1x geroepen)",
   seen_calls.count("browser_search") == 1, str(seen_calls))

# [7] Fallback retourneert ook een logische mislukking -> niet accepteren
seen_calls2 = []

def runner_bad_fallback(tool, args, q):
    seen_calls2.append(tool)
    if tool == "browser_search":
        raise RuntimeError("browser kapot")
    if tool == "web_search":
        return {"ok": False, "error_type": "geen_internet", "error": "geen verbinding"}
    return "should not reach"

r = retry.execute_with_retry(runner_bad_fallback, "browser_search", {"query": "x"},
                             "zoek", max_retries=1, use_fallbacks=True)
ok("7. mislukte fallback -> overall failed",
   r["status"] == "failed", str(r))

# [8] Executor geeft fallback_used door aan het record
from core.executor import execute_action_plan

plan = [
    {"tool_name": "browser_search", "arguments": {"query": "hondjes"}, "status": "pending", "goal": "x"},
]

def fake_ext(tool_name, arguments, question):
    if tool_name == "browser_search":
        return {"ok": False, "status": "fout", "error_type": "browser_niet_gevonden",
                "error": "geen browser"}
    if tool_name == "web_search":
        return "gezocht via fallback"
    raise AssertionError(f"onverwachte tool: {tool_name}")

with patch("core.ai.execute_tool", side_effect=fake_ext), \
     patch("core.ai.correct_opposite_tool", return_value=None):
    results = execute_action_plan(plan, "zoek hondjes")

ok("8. fallback_used doorgegeven aan record",
   results[0].get("fallback_used") == "web_search", str(results[0]))

print(f"\n--- FASE 12 RECOVERY: {passed} geslaagd, {failed} gefaald ---\n")