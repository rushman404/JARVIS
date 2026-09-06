"""
Stress test voor Agent V1 - test meerdere scenario's achter elkaar
en rapporteert alle bugs voordat we iets fixen.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from core.brain import process_command
from core.ai import current_context, conversation_history

TESTS = [
    # --- Modi / doelen ---
    ("maak mijn pc klaar om te gamen", "gaming mode"),
    ("ik ga gamen", "gaming korte vorm"),
    ("ik ga slapen", "slaap modus"),
    ("filmavond", "filmavond"),
    ("ik ga film kijken", "film kijken"),
    ("ik ga muziek luisteren", "muziek luisteren"),
    ("start de werkdag", "werkdag"),
    
    # --- Enkele acties (moeten NIET via Agent gaan) ---
    ("open discord", "enkelvoudig openen"),
    ("sluit steam", "enkelvoudig sluiten"),
    ("zet volume op 30", "volume instellen"),
    ("maak de lamp aan", "HA aan"),
    ("doe de lamp uit", "HA uit"),
    
    # --- Context / referenties ---
    ("maak hem kleiner", "context: minimaliseer laatste"),
    ("sluit hem", "context: sluit laatste"),
    
    # --- Edge cases ---
    ("open onbekendprogramma12345", "onbestaand programma"),
    ("zet de onbekendelamp aan", "onbestaand HA apparaat"),
    ("klaar maken voor pizza", "onbekend doel"),
]

BUGS = []

def run_test(command, label):
    """Voert één test uit en vangt exceptions af."""
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"INPUT: '{command}'")
    print(f"{'='*60}")
    
    try:
        # Reset context voor schone test
        current_context.clear()
        current_context.update({
            "last_command": "",
            "last_result": "",
            "last_action": "",
            "last_program": "",
            "last_file": "",
            "last_website": "",
            "last_ha_entity": "",
            "last_ha_domain": "",
            "last_calculation": "",
        })
        
        result = process_command(command)
        
        print(f"RESULT: {result[:200]}{'...' if len(result) > 200 else ''}")
        
        # Basis validaties
        issues = []
        
        if "traceback" in result.lower() or "error" in result.lower() and "fout" not in result.lower():
            issues.append("Mogelijke exception in output")
        
        if len(result) < 5:
            issues.append("Resultaat te kort / leeg")
            
        # Check of Agent đúng getriggerd is (bij doelen)
        is_goal_test = label in ["gaming mode", "gaming korte vorm", "slaap modus", "filmavond", "film kijken", "muziek luisteren", "werkdag"]
        if is_goal_test:
            if "klaar" not in result.lower() and "ingesteld" not in result.lower() and "gesloten" not in result.lower() and "geopend" not in result.lower():
                issues.append("Geen duidelijke bevestiging van acties bij doel-opdracht")
        
        # Bij onbestaand programma/apparaat: geen crash, nette afhandeling
        if label in ["onbestaand programma", "onbestaand HA apparaat"]:
            if "traceback" in result.lower() or "exception" in result.lower():
                issues.append("Crash bij onbestaand item")
        
        if issues:
            BUGS.append({
                "test": label,
                "command": command,
                "result": result[:500],
                "issues": issues
            })
            print(f"⚠️ ISSUES: {issues}")
        else:
            print("✅ OK")
            
    except Exception as e:
        BUGS.append({
            "test": label,
            "command": command,
            "result": f"EXCEPTION: {type(e).__name__}: {e}",
            "issues": [f"Uncaught exception: {e}"]
        })
        print(f"💥 EXCEPTION: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    return len(BUGS) == 0 or BUGS[-1]["test"] != label


if __name__ == "__main__":
    print("="*60)
    print("AGENT V1 STRESS TEST")
    print("="*60)
    
    passed = 0
    for cmd, label in TESTS:
        if run_test(cmd, label):
            passed += 1
    
    print("\n" + "="*60)
    print(f"SAMENVATTING: {passed}/{len(TESTS)} tests zonder issues")
    print(f"BUGS GEVONDEN: {len(BUGS)}")
    print("="*60)
    
    if BUGS:
        print("\n📋 DETAILLENDE BUG RAPPORTAGE:")
        for i, bug in enumerate(BUGS, 1):
            print(f"\n{i}. {bug['test']} ('{bug['command']}')")
            print(f"   Issues: {', '.join(bug['issues'])}")
            print(f"   Output: {bug['result'][:300]}")
    else:
        print("\n🎉 GEEN BUGS - alle tests geslaagd!")
    
    sys.exit(1 if BUGS else 0)