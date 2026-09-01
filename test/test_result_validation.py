import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.result_validation import classify_tool_result

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


print("=== RESULTAATVALIDATIE: Home Assistant-fouten (FIX BUG 1) ===")

# Eerder onterecht als 'success' beoordeeld -> nu 'failed'.
ha_foutmeldingen = [
    "Kan Home Assistant niet bereiken (HTTP 400).",
    "Kan Home Assistant niet bereiken (HTTP 403).",
    "Kan Home Assistant niet bereiken (HTTP 500).",
    "Kan Home Assistant niet bereiken (HTTP 502).",
    "Kan Home Assistant niet bereiken: verbinding mislukt.",
    "Kan Home Assistant niet bereiken: timeout (mislukt).",
    "Kan Home Assistant niet bereiken (HTTP 400 serverfout mislukt).",
    "Kan Home Assistant niet vinden (HTTP 404).",
    "Kan Home Assistant niet autoriseren (HTTP 401): geen toegang.",
]

for msg in ha_foutmeldingen:
    ok(f"{msg!r} -> failed", classify_tool_result(msg) == "failed")

print()
print("=== RESULTAATVALIDATIE: succesmeldingen blijven success ===")

succesmeldingen = [
    "Bed lamp is nu aan.",
    "Bed lamp is nu aan. (brightness 50%) (kleur: hs_color 120, 100)",
    "Spotify stond al open en staat nu vooraan.",
    "Ik heb een screenshot gemaakt en geopend.",
    "Ik heb de muziek gepauzeerd of hervat.",
    "Volume staat nu op 30%.",
]

for msg in succesmeldingen:
    ok(f"{msg!r} -> success", classify_tool_result(msg) == "success")

print()
print("=== RESULTAATVALIDATIE: andere fouten blijven failed ===")

overige_fouten = [
    "Ik kan het bestand niet vinden.",
    "Welk programma wil je openen?",
    "Ik kon de website niet openen.",
    "Fout bij het uitvoeren van de actie.",
]

# Enige vraag -> uncertain
ok("vraag -> uncertain", classify_tool_result("Welk programma wil je openen?") == "uncertain")
ok("'ik kan bestand niet vinden' -> failed", classify_tool_result("Ik kan het bestand niet vinden.") == "failed")
ok("leeg resultaat -> uncertain", classify_tool_result("") == "uncertain")

print()
print(f"=== RESULTAAT: {passed} geslaagd, {failed} gefaald ===")
