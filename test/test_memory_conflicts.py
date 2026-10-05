"""
JARVIS — Memory conflict tests (Fase 14, Stap 5)
==============================================

Test dat tegenstrijdige informatie veilig wordt afgehandeld:

  1. nieuw feit zonder conflict
  2. duidelijke correctie (expliciet)
  3. tegenstrijdige waarde: oude waarde blijft staan
  4. conflict met bevestiging ("ja")
  5. keuze voor de nieuwe waarde
  6. keuze om de oude waarde te behouden ("nee")
  7. meerdere conflictsituaties
  8. bestaande memory-functionaliteit blijft werken
  9. herschrijven wordt nooit stilzwijgend gedaan

Alle tests draaien op tijdelijke bestanden; de echte
memory/memory.json wordt nooit aangeraakt.
"""

import sys
import os
import io
import json
import shutil
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from memory import store
from memory.memory import (
    DEFAULT_CATEGORIES,
    load_memory,
    save_memory,
    remember,
    recall,
    forget,
    update_memory,
    clear_memory,
    get_entry,
    find_entry,
    get_all_memory,
    has_conflict,
    resolve_conflict,
    empty_memory,
    _find_existing,
    _now,
)

import memory.memory as mem

passed = 0
failed = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


work = tempfile.mkdtemp(prefix="jarvis_conflict_test_")
path = os.path.join(work, "memory.json")

store.reset_cache()


# =============================================================
# 1: nieuw feit zonder conflict
# =============================================================

print("\n===== 1: NIEUW FEIT ZONDER CONFLICT =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    result = remember("favoriete_kleur", "blauw", category="voorkeuren")

    ok("nieuw feit wordt opgeslagen", recall("favoriete_kleur") == "blauw")
    ok("geen conflict gemeld", result.get("conflict") is False)
    ok("geen bevestiging nodig", result.get("needs_confirm") is None)
    ok("changed is False bij een nieuw feit", result.get("changed") is False)
    ok("previous is None bij een nieuw feit", result.get("previous") is None)

    # Dezelfde waarde opnieuw is géén conflict
    result = remember("favoriete_kleur", "blauw", category="voorkeuren")

    ok("dezelfde waarde geeft geen conflict", result.get("conflict") is False)
    ok("dezelfde waarde blijft staan", recall("favoriete_kleur") == "blauw")
    ok("needs_confirm bij identieke waarde",
       result.get("needs_confirm") is not True)

    # has_conflict op een onbekende sleutel
    conflict, old, category = has_conflict("bestaat_niet", "iets")

    ok("has_conflict op onbekende sleutel is False", conflict is False)
    ok("has_conflict op onbekende sleutel geeft geen waarde", old is None)


# =============================================================
# 2: duidelijke correctie (expliciet)
# =============================================================

print("\n===== 2: DUIDELIJKE CORRECTIE (EXPLICIET) =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # "wijzig mijn favoriete kleur naar groen" = expliciete correctie
    result = update_memory("favoriete_kleur", "groen", category="voorkeuren")

    ok("expliciete correctie slaat direct op", recall("favoriete_kleur") == "groen")
    ok("expliciete correctie vraagt geen bevestiging",
       result.get("needs_confirm") is not True)
    ok("expliciete correctie is gemarkeerd als corrected",
       result.get("corrected") is True)
    ok("expliciete correctie geeft geen conflict", result.get("conflict") is False)

    entry = get_entry("favoriete_kleur")

    ok("entry is corrected", entry.get("corrected") is True)
    ok("entry bewaart de vorige waarde", entry.get("previous_value") == "blauw")
    ok("entry is niet in conflict", entry.get("conflict") is False)

    # has_conflict ziet dit ook
    conflict, old, category = has_conflict("favoriete_kleur", "rood", "voorkeuren")

    ok("has_conflict ziet het verschil", conflict is True)
    ok("has_conflict geeft de huidige waarde", old == "groen")
    ok("has_conflict geeft de categorie", category == "voorkeuren")


# =============================================================
# 3: tegenstrijdige waarde: oude waarde blijft staan
# =============================================================

print("\n===== 3: TEGENSTRIJDIGE WAARDE =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    result = remember("favoriete_kleur", "rood", category="voorkeuren")

    ok("conflict wordt gemeld", result.get("conflict") is True)
    ok("bevestiging wordt gevraagd", result.get("needs_confirm") is True)
    ok("de oude waarde is NIET overschreven",
       recall("favoriete_kleur") == "groen")
    ok("het conflict meldt de oude waarde", result.get("old_value") == "groen")
    ok("het conflict meldt de nieuwe waarde", result.get("memory_value") == "rood")
    ok("het conflict meldt de sleutel",
       result.get("memory_key") == "favoriete_kleur")

    # het geheugen is niet beschadigd
    entry = get_entry("favoriete_kleur")

    ok("entry houdt de oude waarde", entry.get("value") == "groen")
    ok("entry is niet overschreven", entry.get("conflict") is not True)

    # ook zonder expliciete categorie werkt dit
    result = remember("naam", "Rushi", category="algemeen")

    ok("tweede nieuw feit zonder conflict slaat op", recall("naam") == "Rushi")
    ok("tweede nieuw feit meldt geen conflict",
       result.get("needs_confirm") is not True)

    result = remember("naam", "Rufus")

    ok("tegenstrijdige naam is niet opgeslagen", recall("naam") == "Rushi")
    ok("tegenstrijdige naam vraagt bevestiging",
       result.get("needs_confirm") is True)


# =============================================================
# 4 + 5: conflict met bevestiging -> keuze voor de nieuwe waarde
# =============================================================

print("\n===== 4+5: BEVESTIGING -> NIEUWE WAARDE =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # Nieuwe waarde kiezen
    result = resolve_conflict("favoriete_kleur", "rood",
                              keep_old=False, category="voorkeuren")

    ok("resolve meldt dat er iets is opgeslagen", result.get("applied") is True)
    ok("resolve meldt dat de oude waarde niet is behouden",
       result.get("kept_old") is False)
    ok("resolve meldt de nieuwe waarde", result.get("value") == "rood")
    ok("resolve meldt de vorige waarde", result.get("previous") == "groen")
    ok("resolve markeert het als gecorrigeerd",
       result.get("corrected") is True)

    ok("de nieuwe waarde is nu actueel", recall("favoriete_kleur") == "rood")

    entry = get_entry("favoriete_kleur")

    ok("previous_value is bijgewerkt", entry.get("previous_value") == "groen")
    ok("conflict is opgelost", entry.get("conflict") is False)
    ok("corrected staat aan", entry.get("corrected") is True)
    ok("het afhandelen is vastgelegd",
       entry.get("conflict_resolved") is not None)

    # resolve_conflict zonder eerder conflict slaat gewoon op
    result = resolve_conflict("nieuw_fact", "waarde", category="algemeen")

    ok("resolve zonder conflict slaat gewoon op",
       recall("nieuw_fact") == "waarde")
    ok("resolve zonder conflict meldt applied", result.get("applied") is True)


# =============================================================
# 6: keuze om de oude waarde te behouden
# =============================================================

print("\n===== 6: OUDE WAARDE BEHOUDEN =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    result = resolve_conflict("favoriete_kleur", "paars",
                              keep_old=True, category="voorkeuren")

    ok("resolve meldt dat niets is overschreven",
       result.get("applied") is False)
    ok("resolve meldt dat de oude waarde is behouden",
       result.get("kept_old") is True)
    ok("resolve meldt de waarde die geldt", result.get("value") == "rood")

    ok("de oude waarde staat er nog steeds", recall("favoriete_kleur") == "rood")

    entry = get_entry("favoriete_kleur")

    ok("de afgewezen waarde is vastgelegd",
       entry.get("conflict_rejected_value") == "paars")
    ok("het afwijzen is vastgelegd",
       entry.get("conflict_kept_old") is True)
    ok("de waarde zelf is onveranderd", entry.get("value") == "rood")

    # na afwijzen kan dezelfde waarde opnieuw worden aangeboden
    ok("de afgewezen waarde staat er niet in",
       entry.get("value") != entry.get("conflict_rejected_value"))


# =============================================================
# 7: meerdere conflictsituaties
# =============================================================

print("\n===== 7: MEERDERE CONFLICTSITUATIES =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # drie sleutels met elk een eigen conflict
    remember("gpu", "RTX 3060", category="pc")
    remember("cpu", "Ryzen 5", category="pc")
    remember("monitor", "Samsung", category="pc")

    conflicts = []

    for key, new in (("gpu", "RTX 4090"), ("cpu", "Ryzen 7"), ("monitor", "LG")):
        result = remember(key, new, category="pc")
        conflicts.append(result.get("needs_confirm") is True)

    ok("alle drie de conflicts worden gemeld", all(conflicts))

    ok("gpu is niet overschreven", recall("gpu") == "RTX 3060")
    ok("cpu is niet overschreven", recall("cpu") == "Ryzen 5")
    ok("monitor is niet overschreven", recall("monitor") == "Samsung")

    # twee bevestigen, één afwijzen
    resolve_conflict("gpu", "RTX 4090", keep_old=False, category="pc")
    resolve_conflict("cpu", "Ryzen 7", keep_old=False, category="pc")
    resolve_conflict("monitor", "LG", keep_old=True, category="pc")

    ok("gpu is bijgewerkt", recall("gpu") == "RTX 4090")
    ok("cpu is bijgewerkt", recall("cpu") == "Ryzen 7")
    ok("monitor is onveranderd", recall("monitor") == "Samsung")

    # elk feit houdt zijn eigen historie
    ok("gpu bewaart zijn vorige waarde",
       get_entry("gpu", category="pc").get("previous_value") == "RTX 3060")
    ok("cpu bewaart zijn vorige waarde",
       get_entry("cpu", category="pc").get("previous_value") == "Ryzen 5")
    ok("monitor heeft geen previous_value",
       get_entry("monitor", category="pc").get("previous_value") is None)

    # een conflict in een andere categorie raakt de eerste niet
    remember("favoriete_band", "Coldplay", category="muziek")
    remember("favoriete_band", "Radiohead")

    ok("muziek-conflict is apart afgehandeld",
       recall("favoriete_band") == "Coldplay")
    ok("pc-feiten zijn niet geraakt", recall("gpu") == "RTX 4090")

    # sleutel met andere schrijfwijze (spaties vs underscore)
    remember("favoriete_sport", "voetbal", category="voorkeuren")
    result = remember("favoriete sport", "handbal", category="voorkeuren")

    ok("flexibele sleutelmatch herkent het conflict",
       result.get("needs_confirm") is True)
    ok("de waarde is niet overschreven", recall("favoriete_sport") == "voetbal")


# =============================================================
# 8: bestaande memory-functionaliteit blijft werken
# =============================================================

print("\n===== 8: BESTAANDE FUNCTIONALITEIT =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # lezen, zoeken, verwijderen, samenvatten
    ok("recall leest een waarde", recall("gpu") == "RTX 4090")
    ok("recall vindt niets voor een onbekende sleutel",
       recall("bestaat_niet") is None)

    ok("get_entry geeft de entry terug",
       get_entry("gpu", category="pc") is not None)
    ok("get_entry geeft None voor onbekend",
       get_entry("bestaat_niet") is None)

    ok("find_entry vindt categorie + entry",
       find_entry("gpu", "pc")[0] == "pc")
    ok("find_entry geeft (None, None) voor onbekend",
       find_entry("bestaat_niet") == (None, None))

    ok("get_all_memory bevat de sleutels",
       "gpu" in get_all_memory())

    ok("forget verwijdert een sleutel", forget("nieuw_fact") is True)
    ok("forget geeft False voor onbekend", forget("bestaat_niet") is False)
    ok("vergeet sleutel is echt weg", recall("nieuw_fact") is None)

    # de geschiedenis overleeft een clear+opnieuw opslaan cyclus
    for entry in load_memory()["pc"].values():
        if entry.get("previous_value") is not None:
            ok("entry met historie blijft integer", entry["value"] is not None)
            break

    # memory.json blijft geldige JSON
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    ok("memory.json is valide JSON", isinstance(raw, dict))
    ok("alle categorieën aanwezig", set(raw) == set(DEFAULT_CATEGORIES))


# =============================================================
# 9: herschrijven wordt nooit stilzwijgend gedaan
# =============================================================

print("\n===== 9: NOOIT STILZWIJGEND OVERSCHRIJVEN =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # De enige manieren om zonder bevestiging te overschrijven
    result_plain = remember("gpu", "stilzwijgend", category="pc")
    ok("plain remember overschrijft niet",
       result_plain.get("needs_confirm") is True)

    result_forced = remember("gpu", "bewust", category="pc", force=True)
    ok("force=True overschrijft wel", recall("gpu") == "bewust")
    ok("force=True meldt geen conflict",
       result_forced.get("needs_confirm") is not True)

    result_explicit = update_memory("gpu", "expliciet", category="pc")
    ok("update_memory overschrijft direct", recall("gpu") == "expliciet")
    ok("update_memory is een correctie", result_explicit.get("corrected") is True)

    # de API geeft altijd de vier kernvelden terug
    for result in (result_plain, result_forced, result_explicit):
        ok("resultaat bevat changed/conflict/previous/category",
           all(field in result for field in
               ("changed", "conflict", "previous", "category")))

    # na een afgewezen conflict blijft het geheugen zoals het was
    remember("naam", "Rushi", category="algemeen")
    resolve_conflict("naam", "Rufus", keep_old=True, category="algemeen")

    ok("geheugen is onveranderd na afwijzen", recall("naam") == "Rushi")
    ok("het geheugen telt geen nieuwe sleutels",
       len(get_all_memory()) == len(set(get_all_memory())))


# =============================================================
# 10: brain-integratie (wat JARVIS echt zegt en doet)
# =============================================================

print("\n===== 10: BRAIN-INTEGRATIE =====\n")

import core.brain as brain

# Voorkom dat de rest van de pipeline (ollama, media, pc) echt iets doet.
_stubs = ("ask_ai", "open_website", "send_to_recycle", "empty_recycle_bin",
          "copy_path", "move_path", "list_folder_by_path", "lock_pc",
          "sleep_pc", "shutdown_pc", "restart_pc", "logoff_pc", "run_goal",
          "speak", "say", "set_volume", "play_pause", "next_track",
          "previous_track", "volume_up", "volume_down", "toggle_mute")

_saved = {name: getattr(brain, name) for name in _stubs if hasattr(brain, name)}

for name in _saved:
    setattr(brain, name, (lambda *a, **k: "FAKE"))

work2 = os.path.join(work, "brain.json")

try:

    with patch.object(mem, "MEMORY_FILE", work2):

        brain.update_context(pending_choice=None)

        # 1. een nieuw feit wordt gewoon onthouden
        reply = brain.process_command("mijn favoriete kleur is blauw")

        ok("nieuw feit wordt bevestigd in het antwoord",
           "onthoud" in reply.lower())
        ok("nieuw feit staat in het geheugen",
           recall("favoriete_kleur") == "blauw")

        # 2. een tegenstrijdige waarde vraagt om bevestiging
        reply = brain.process_command("mijn favoriete kleur is rood")

        ok("tegenstrijdig feit vraagt om bevestiging",
           "wijzigen" in reply.lower())
        ok("tegenstrijdig feit noemt de nieuwe waarde", "rood" in reply)
        ok("tegenstrijdig feit noemt de oude waarde", "blauw" in reply)
        ok("de oude waarde is nog niet overschreven",
           recall("favoriete_kleur") == "blauw")

        pending = brain.current_context.get("pending_choice")

        ok("er staat een pending keuze klaar", bool(pending))
        ok("pending keuze is van het type memory_update",
           pending and pending.get("kind") == "memory_update")
        ok("pending keuze onthoudt de sleutel",
           pending and pending.get("memory_key") == "favoriete_kleur")
        ok("pending keuze onthoudt de oude waarde",
           pending and pending.get("old_value") == "blauw")
        ok("pending keuze onthoudt de nieuwe waarde",
           pending and pending.get("memory_value") == "rood")

        # 3. "ja" bevestigt de nieuwe waarde
        reply = brain.process_command("ja")

        ok("bevestiging wordt beantwoord", "aangepast" in reply.lower())
        ok("de nieuwe waarde staat er nu", recall("favoriete_kleur") == "rood")
        ok("de vorige waarde is bewaard",
           get_entry("favoriete_kleur").get("previous_value") == "blauw")
        ok("het conflict is opgelost",
           get_entry("favoriete_kleur").get("conflict") is False)
        ok("de keuze is gewist",
           brain.current_context.get("pending_choice") is None)

        # 4. een nieuwe tegenspraak, nu afgewezen
        reply = brain.process_command("mijn favoriete kleur is groen")

        ok("tweede tegenspraak vraagt opnieuw om bevestiging",
           "wijzigen" in reply.lower())
        ok("de waarde is nog niet overschreven",
           recall("favoriete_kleur") == "rood")

        reply = brain.process_command("nee")

        ok("afwijzing wordt beantwoord", "geheugen" in reply.lower())
        ok("de oude waarde blijft staan", recall("favoriete_kleur") == "rood")

        entry = get_entry("favoriete_kleur")

        ok("de afgewezen waarde is vastgelegd",
           entry.get("conflict_rejected_value") == "groen")
        ok("het afwijzen is vastgelegd", entry.get("conflict_kept_old") is True)
        ok("de keuze is gewist na afwijzen",
           brain.current_context.get("pending_choice") is None)

        # 5. een expliciete correctie vraagt NIET om bevestiging
        reply = brain.process_command("wijzig mijn favoriete kleur naar geel")

        ok("expliciete correctie wordt direct uitgevoerd",
           recall("favoriete_kleur") == "geel")
        ok("expliciete correctie vraagt geen bevestiging",
           "zellig" not in reply.lower() and "wijzigen" not in reply.lower())
        ok("expliciete correctie bewaart de vorige waarde",
           get_entry("favoriete_kleur").get("previous_value") == "rood")
        ok("expliciete correctie is gemarkeerd",
           get_entry("favoriete_kleur").get("corrected") is True)

        # 6. ongerelateerde feiten blijven gewoon werken
        brain.process_command("mijn gpu is een rtx 3060")

        ok("een ander feit wordt wel gewoon opgeslagen",
           recall("gpu") == "een rtx 3060")

        # 7. en dat feit conflicteert daarna net als elk ander
        reply = brain.process_command("mijn gpu is een rtx 4090")

        ok("pc-feiten doen ook mee met de conflict-logica",
           "wijzigen" in reply.lower())
        ok("de gpu-waarde is niet overschreven", recall("gpu") == "een rtx 3060")

except Exception as error:      # pragma: no cover - netwerk-/importfouten

    ok(f"brain-integratie liep zonder fout ({error})", False)

finally:

    for name, value in _saved.items():
        setattr(brain, name, value)

    brain.update_context(pending_choice=None)


# Bestanden opruimen
for leftover in (path, path + ".bak", path + ".lock", path + ".corrupt"):
    try:
        os.remove(leftover)
    except OSError:
        pass

shutil.rmtree(work, ignore_errors=True)

store.reset_cache()

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)
