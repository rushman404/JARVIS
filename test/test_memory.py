import sys
import os
import io
import json
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from memory.memory import remember, recall, forget, get_category_memory, get_relevant_memory

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


print("🧠 Geheugen test gestart.")


# =============================================================
# Basale smoke test (bestaand gedrag)
# =============================================================

remember("test", "Hallo vanuit het geheugen.")

print("📥 Opgeslagen.")

value = recall("test")

print("📤 Teruggelezen:", value)

ok("recall leest waarde terug", value == "Hallo vanuit het geheugen.")

forget("test")

print("🗑️ Testgeheugen verwijderd.")

ok("forget haalt de waarde weg", recall("test") is None)


# =============================================================
# Geïsoleerde bestanden voor de Fase 5-secties
# =============================================================

_tmp = tempfile.mktemp(suffix="_memory.json")
with open(_tmp, "w", encoding="utf-8") as f:
    f.write(open("memory/memory.json", encoding="utf-8").read())

_rtmp = tempfile.mktemp(suffix="_routines.json")
with open(_rtmp, "w", encoding="utf-8") as f:
    _routines_copy = json.load(open("config/routines.json", encoding="utf-8"))
    for _entry in _routines_copy.values():
        _entry.pop("usage_count", None)
        _entry.pop("last_used", None)
    f.write(json.dumps(_routines_copy, ensure_ascii=False, indent=4))


# =============================================================
# A: metadata-model + B: relevante memory (geïsoleerd bestand)
# =============================================================

print("\n===== FASE 5: METADATA-MODEL (A) =====")

with patch("memory.memory.MEMORY_FILE", _tmp):

    from memory.memory import find_entry

    result = remember("favoriete_kleur", "blauw", category="voorkeuren")

    cat, entry = find_entry("favoriete_kleur")

    ok("remember retourneert metadata-dict",
       isinstance(result, dict) and result.get("changed") is False)

    ok("entry bevat value + updated",
       cat == "voorkeuren" and entry is not None
       and entry.get("value") == "blauw" and entry.get("updated"))

    ok("entry bevat source + conflict-veld",
       entry.get("source") == "conversation" and "conflict" in entry)

    back = recall("favoriete_kleur")

    ok("recall blijft een simpele string geven (back-compat)",
       back == "blauw")

    print("\n----- relevante memory (B) -----")

    remember("lichtvoorkeur", "warm wit", category="voorkeuren")

    rel = get_relevant_memory("kun je de kamer gezellig maken met warm licht?")

    ok("relevante memory bevat lichtvoorkeur", any(
        kv.get("key") == "lichtvoorkeur" for kv in rel
    ))

    score = get_relevant_memory("welke kleur vind ik het mooist?")

    ok("favoriete_kleur scoort op 'kleur'-vraag", any(
        kv.get("key") == "favoriete_kleur" for kv in score
    ))

    prompt = None
    try:
        from memory.memory import relevant_memory_prompt
        prompt = relevant_memory_prompt("hoe moet de verlichting aan?")
    except Exception:
        prompt = None

    ok("relevante memory-prompt is beschikbaar en bevat het voorsel",
       prompt is not None and "lichtvoorkeur" in str(prompt))

    forget("favoriete_kleur")
    forget("lichtvoorkeur")


# =============================================================
# C/H/I: voorkeuren herkennen, wijzigen, conflicten
# =============================================================

print("\n===== FASE 5: VOORKEUR HERKEND (C/H/I) =====")

with patch("memory.memory.MEMORY_FILE", _tmp):

    import core.brain as brain

    print("\n--- herkenning ---")

    out = brain.auto_remember("ik hou meestal van warm wit licht")
    ok("'ik hou meestal van warm wit licht' -> herkend",
       out is not None and "warm" in str(out).lower())

    out = brain.auto_remember("ik vind zacht licht fijn")
    ok("'ik vind zacht licht fijn' -> herkend",
       out is not None and "zacht" in str(out).lower())

    out = brain.auto_remember("mijn voorkeur voor licht is helder")
    ok("'mijn voorkeur voor licht is helder' -> herkend",
       out is not None and "helder" in str(out).lower())

    ok("lichtvoorkeur staat in geheugen",
       (recall("lichtvoorkeur") or "").lower() in ("warm wit", "zacht", "helder"))

    print("\n--- wijzigen (expliciet) ---")

    out = brain.try_memory_update("wijzig mijn lichtvoorkeur naar koel wit")

    ok("'wijzig mijn lichtvoorkeur naar koel wit' -> update",
       out is not None and "koel" in str(out).lower())

    ok("lichtvoorkeur is nu 'koel wit'", recall("lichtvoorkeur") == "koel wit")

    print("\n--- conflictbevestiging (I) ---")

    brain.current_context["pending_choice"] = {
        "kind": "memory_update",
        "action": "update",
        "memory_key": "lichtvoorkeur",
        "memory_value": "warm wit",
        "current_value": "koel wit",
    }

    out = brain.process_command("ja")

    ok("'ja' op conflict -> lichtvoorkeur gewijzigd naar warm wit",
       recall("lichtvoorkeur") == "warm wit")

    brain.current_context["pending_choice"] = None

    forget("lichtvoorkeur")


# =============================================================
# D: apparaten onthouden
# =============================================================

print("\n===== FASE 5: APPARATEN ONTHOUDEN (D) =====")

with patch("memory.memory.MEMORY_FILE", _tmp):

    import core.brain as brain

    out = brain.try_remember_device("de voordeur heet deurbel")

    ok("'de voordeur heet deurbel' -> onthouden",
       out is not None and "deurbel" in str(out))

    items = get_category_memory("apparaten")

    ok("apparaatnaam staat in categorie 'apparaten'",
       "deurbel" in items and "voordeur" in str(items.get("deurbel")))

    out = brain.try_remember_device("bedlamp is mijn lamp in de slaapkamer")

    ok("'bedlamp is mijn ...' -> onthouden", out is not None)

    listed = brain.try_list_devices("welke apparaten ken je")

    ok("'welke apparaten ken je' -> lijst van namen",
       listed is not None and "deurbel" in listed and "bedlamp" in listed)

    ok("persoonlijke zin ('ik heet X') wordt niet als apparaat gelezen",
       brain.try_remember_device("ik heet rushil") is None)

    linked = True
    try:
        from core.ha_registry import add_user_alias
        with patch("core.ha_registry._config_ok", return_value=False):
            linked = add_user_alias("light.nepapparaat", ["nepnaam"])
    except Exception:
        linked = False

    ok("add_user_alias zonder HA-config -> geen bestandswijziging",
       linked is False)

    forget("deurbel")
    forget("bedlamp")


# =============================================================
# E: routines-gebruik bijhouden
# =============================================================

print("\n===== FASE 5: ROUTINES GEBRUIK (E) =====")

with patch("core.routines.ROUTINES_FILE", _rtmp):

    from core.routines import RoutineManager

    manager = RoutineManager()

    manager.save_routine("gareden", ["ik ga tuinieren"], ["eerste stap"],
                          "tuinmodus", ["tuindag"])
    manager.save_routine("lezen", ["ik ga lezen"], ["eerste stap"],
                          "leesmodus", ["leesmoment"])

    manager.track_usage("gareden")
    manager.track_usage("gareden")
    manager.track_usage("lezen")

    ranking = manager.most_used_routines()

    ok("meest gebruikte routine staat bovenaan",
       ranking and ranking[0][2] == "gareden" and ranking[0][0] == 2)

    stored = manager._routines.get("gareden")

    ok("usage_count + last_used opgeslagen",
       stored is not None and stored.get("usage_count") == 2 and stored.get("last_used"))

    loaded = RoutineManager()

    ok("herladen houdt de defaults intact",
       "gaming" in loaded._routines and "gareden" in loaded._routines)


# =============================================================
# F: projecten (deadline + status)
# =============================================================

print("\n===== FASE 5: PROJECTEN (F) =====")

with patch("memory.memory.MEMORY_FILE", _tmp):

    import core.brain as brain

    out = brain.auto_remember("de deadline van schoolproject is vrijdag")

    ok("deadline herkend", out is not None and "vrijdag" in str(out))

    q = brain.try_project_query("wat is de deadline van schoolproject")

    ok("deadline opvragen werkt", q is not None and "vrijdag" in q)

    out = brain.auto_remember("schoolproject is bijna klaar")

    ok("status herkend", out is not None and "klaar" in str(out))

    q = brain.try_project_query("hoe gaat het met schoolproject")

    ok("status opvragen werkt", q is not None and "klaar" in q)

    forget("project_deadline_schoolproject")
    forget("project_status_schoolproject")


# =============================================================
# G: context / timestamps
# =============================================================

print("\n===== FASE 5: CONTEXT / TIMESTAMPS (G) =====")

with patch("core.ai.conversation_history", []), \
     patch("core.ai._save_conversation", lambda: None):

    import core.ai as ai

    ai.add_to_history("user", "testbericht")

    item = ai.conversation_history[0]

    ok("historisch bericht heeft tijdstempel", item.get("ts"))

    cleaned = ai._chat_history()

    ok("_chat_history stuurt alleen role+content (geen ts mee)",
       cleaned and "role" in cleaned[0] and "ts" not in cleaned[0])

    ok("MAX_HISTORY is verruimd naar 15", ai.MAX_HISTORY == 15)


print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

try:
    os.remove(_tmp)
    os.remove(_rtmp)
except OSError:
    pass

sys.exit(1 if failed else 0)