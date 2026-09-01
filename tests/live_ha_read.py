import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "C:\\JARVIS")
from core.home_assistant import resolve_live_entity_id, get_home_assistant_entities_tool

ok_all = True

def ok(label, cond):
    global ok_all
    if cond:
        print(f"  ✅ {label}")
    else:
        ok_all = False
        print(f"  ❌ {label}")

print("=== LIVE HA (alleen lezen; geen controles) ===\n")

# 1. Discovery bevat light.bed_lamp
disc = get_home_assistant_entities_tool("light")
ok("discovery bevat light.bed_lamp", "light.bed_lamp" in disc)

# 2. Entiteit-resolutie: exact geldig id behouden (leest /api/states)
res_id, status, msg = resolve_live_entity_id("light.bed_lamp", "light")
ok("resolve light.bed_lamp -> exact", res_id == "light.bed_lamp" and status == "exact")

# 3. Verzonnen entity -> veilige geen-match (geen uitvoering)
res_id, status, msg = resolve_live_entity_id("light.dit_bestaat_niet_lamp", "light")
ok("onbestaande entity -> none (niet uitgevoerd)", status == "none" and res_id is None)

print("\nLive HA-read klaar.")
sys.exit(0 if ok_all else 1)
