"""
JARVIS — Memory Store tests (Fase 14, Stap 1)
=============================================

Test de nieuwe opslaglaag memory/store.py:

  1. normaal laden
  2. normaal opslaan
  3. cache werkt
  4. cache wordt correct vernieuwd na een write
  5. twee verschillende MEMORY_FILE-paden lekken geen data naar elkaar
  6. atomic write
  7. corrupt JSON-bestand
  8. herstel via backup
  9. backup ontbreekt -> veilige fallback
 10. bestaande memory-functionaliteit blijft werken

Elke test draait volledig op tijdelijke bestanden. De echte
memory/memory.json wordt nooit gelezen of overschreven.
"""

import sys
import os
import io
import json
import glob
import shutil
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from memory import store
from memory.memory import (
    DEFAULT_CATEGORIES,
    empty_memory,
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
    get_category_memory,
    memory_summary,
    get_relevant_memory,
    relevant_memory_prompt,
    touch_usage,
    reset_touch_usage,
    resolve_conflict,
    _touched_keys,
)

import memory.memory as mem

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


def stats_snapshot():
    return dict(store.STATS)


def make_dir():
    return tempfile.mkdtemp(prefix="jarvis_store_test_")


# =============================================================
# 1 + 2: normaal laden en opslaan
# =============================================================

print("\n===== 1+2: NORMAAL LADEN / OPSLAAN =====\n")

work = make_dir()
path_a = os.path.join(work, "memory.json")

store.reset_cache()

sample = {
    "voorkeuren": {"favoriete_kleur": {"value": "blauw"}},
    "pc": {},
    "projecten": {},
    "muziek": {},
    "algemeen": {},
    "apparaten": {},
}

ok("write() geeft True terug", store.write(path_a, sample) is True)
ok("bestand bestaat na schrijven", os.path.exists(path_a))

loaded = store.read(path_a)

ok("read() geeft exact terug wat er geschreven is", loaded == sample)

# Unicode en formatting zoals de bestaande memory.py deed
unicode_data = {"algemeen": {"naam": "Rushi — förtòn 中文"}}
store.write(path_a, unicode_data)

with open(path_a, "r", encoding="utf-8") as handle:
    raw = handle.read()

ok("niet-ASCII blijft leesbaar (ensure_ascii=False)", "förtòn" in raw)
ok("indent=4 blijft gehandhaafd", '\n    "algemeen"' in raw)
ok("read() geeft unicode correct terug",
   store.read(path_a) == unicode_data)

# =============================================================
# 3: cache werkt
# =============================================================

print("\n===== 3: CACHE WERKT =====\n")

store.reset_cache()

cache_path = os.path.join(work, "cache.json")
store.write(cache_path, {"algemeen": {"a": 1}})

before = stats_snapshot()

for _ in range(5):
    store.read(cache_path)

after = stats_snapshot()

new_reads = after["reads"] - before["reads"]
new_hits = after["cache_hits"] - before["cache_hits"]

ok("5 reads tellen echt op", new_reads == 5)
ok("een eigen write vult de cache, dus alle 5 reads zijn cache-hits",
   new_hits == 5)

# Na een lege cache is de eerste read wél een echte schijfread
store.reset_cache()

before = stats_snapshot()
store.read(cache_path)
after = stats_snapshot()

ok("lege cache: eerste read is een echte schijfread",
   after["reads"] - before["reads"] == 1
   and after["cache_hits"] - before["cache_hits"] == 0)

before = stats_snapshot()
store.read(cache_path)
store.read(cache_path)
after = stats_snapshot()

ok("tweede en derde read komen uit de cache",
   after["cache_hits"] - before["cache_hits"] == 2)

# Externe wijziging op schijf moet de cache alsnog opheffen
external = {"algemeen": {"a": 2}}

with open(cache_path, "w", encoding="utf-8") as handle:
    json.dump(external, handle, indent=4, ensure_ascii=False)

ok("externe wijziging wordt opgepikt (cache gevalideerd op mtime/size)",
   store.read(cache_path) == external)

# Een gelezen resultaat mag veilig gemuteerd worden: de cache
# zelf mag niet meebewegen met de caller.
copy_result = store.read(cache_path)
copy_result["algemeen"]["a"] = 999

ok("gemuteerd resultaat lekt niet terug in de cache",
   store.read(cache_path) == external)

ok("read() geeft elke keer een eigen kopie terug",
   store.read(cache_path) is not store.read(cache_path))

# =============================================================
# 4: cache wordt correct vernieuwd na een write
# =============================================================

print("\n===== 4: CACHE VERNIEUWD NA WRITE =====\n")

store.reset_cache()

refresh_path = os.path.join(work, "refresh.json")

store.write(refresh_path, {"algemeen": {"kleur": "rood"}})
ok("direct na write is de nieuwe waarde zichtbaar",
   store.read(refresh_path)["algemeen"]["kleur"] == "rood")

store.write(refresh_path, {"algemeen": {"kleur": "groen"}})
ok("tweede write overschrijft de cache",
   store.read(refresh_path)["algemeen"]["kleur"] == "groen")

store.write(refresh_path, {"algemeen": {"kleur": "blauw"}})
ok("derde write blijft consistent",
   store.read(refresh_path)["algemeen"]["kleur"] == "blauw")

with open(refresh_path, "r", encoding="utf-8") as handle:
    on_disk = json.load(handle)

ok("cache en schijf zijn identiek na writes",
   on_disk["algemeen"]["kleur"] == "blauw")

# Externe schrijfactie ná een eigen write mag niet onopgemerkt blijven
with open(refresh_path, "w", encoding="utf-8") as handle:
    json.dump({"algemeen": {"kleur": "geel"}}, handle, indent=4)

ok("externe overschrijving wint van de cache",
   store.read(refresh_path)["algemeen"]["kleur"] == "geel")

# =============================================================
# 5: twee MEMORY_FILE-paden lekken geen data naar elkaar
# =============================================================

print("\n===== 5: GEEN LEAK TUSSEN TWEE BESTANDSPADEN =====\n")

store.reset_cache()

leak_a = os.path.join(work, "pad_a.json")
leak_b = os.path.join(work, "pad_b.json")

store.write(leak_a, {"algemeen": {"naam": "A"}})
store.write(leak_b, {"algemeen": {"naam": "B"}})

ok("pad A levert zijn eigen data",
   store.read(leak_a)["algemeen"]["naam"] == "A")
ok("pad B levert zijn eigen data",
   store.read(leak_b)["algemeen"]["naam"] == "B")
ok("pad A is na het lezen van B nog steeds A",
   store.read(leak_a)["algemeen"]["naam"] == "A")

# Zelfde pad, ander bestand: cache mag niet meegaan
reuse = os.path.join(work, "hergebruikt.json")
store.write(reuse, {"algemeen": {"naam": "eerste"}})
store.read(reuse)

os.remove(reuse)
store.write(reuse, {"algemeen": {"naam": "tweede"}})

ok("herschreven pad levert nieuwe data, geen cache-ouwe",
   store.read(reuse)["algemeen"]["naam"] == "tweede")

# Ook via de memory-API zelf, met gepatchte MEMORY_FILE
with patch.object(mem, "MEMORY_FILE", leak_a):
    remember("kleur", "paars")

with patch.object(mem, "MEMORY_FILE", leak_b):
    remember("kleur", "oranje")

with patch.object(mem, "MEMORY_FILE", leak_a):
    a_value = recall("kleur")

with patch.object(mem, "MEMORY_FILE", leak_b):
    b_value = recall("kleur")

ok("memory-API: pad A heeft paars", a_value == "paars")
ok("memory-API: pad B heeft oranje", b_value == "oranje")

# =============================================================
# 6: atomic write
# =============================================================

print("\n===== 6: ATOMIC WRITE =====\n")

store.reset_cache()

atomic_path = os.path.join(work, "atomic.json")
real_replace = os.replace

with patch("memory.store.os.replace", wraps=real_replace) as replace_spy:
    store.write(atomic_path, {"algemeen": {"k": "v"}})

ok("os.replace wordt gebruikt voor het omwisselen",
   replace_spy.call_count >= 1)

leftovers = glob.glob(os.path.join(work, "*.tmp"))

ok("geen .tmp-bestanden achtergelaten", leftovers == [])

# Ook de backup moet atomair zijn geschreven
bak_path = store.backup_path(atomic_path)

ok("backup is aangemaakt", os.path.exists(bak_path))
ok("backup heeft dezelfde inhoud", store.read(bak_path) is not None
   and json.load(open(bak_path, encoding="utf-8")) == {"algemeen": {"k": "v"}})

# Een bestaand bestand wordt niet half overschreven: als het
# origineel onleesbaar zou zijn, moet de inhoud geheel of niets zijn.
big = {"algemeen": {f"sleutel_{i}": "waarde" * 20 for i in range(500)}}

store.write(atomic_path, big)
ok("grote inhoud schrijft en lees volledig terug",
   store.read(atomic_path) == big)

# Een directory die nog niet bestaat wordt aangemaakt
deep_path = os.path.join(work, "nieuw", "diep", "memory.json")

ok("write() maakt mappen aan zoals nodig",
   store.write(deep_path, {"algemeen": {"diep": True}}) is True)
ok("diep genest bestand leesbaar", store.read(deep_path) is not None)

# =============================================================
# 7: corrupt JSON-bestand
# =============================================================

print("\n===== 7: CORRUPT JSON-BESTAND =====\n")

store.reset_cache()

corrupt_path_file = os.path.join(work, "corrupt.json")

with open(corrupt_path_file, "w", encoding="utf-8") as handle:
    handle.write('{"voorkeuren": {"kleur": "blauw"')   # afgebroken JSON

result = store.read(corrupt_path_file)

ok("read() geeft None bij corrupt zonder backup", result is None)
ok("corrupt bestand is bewaard als .corrupt",
   os.path.exists(store.corrupt_path(corrupt_path_file)))
ok("het originele corrupte bestand is niet verwijderd",
   os.path.exists(corrupt_path_file))

# load_memory zelf tegen een corrupt bestand zetten
with patch.object(mem, "MEMORY_FILE", corrupt_path_file):
    safe = load_memory()

ok("load_memory() geeft lege memory bij corrupt",
   safe == empty_memory())
ok("lege memory heeft alle categorieën", set(safe) == set(DEFAULT_CATEGORIES))

# =============================================================
# 8: herstel via backup
# =============================================================

print("\n===== 8: HERSTEL VIA BACKUP =====\n")

store.reset_cache()

recover_dir = make_dir()
recover_path = os.path.join(recover_dir, "memory.json")

good = {"voorkeuren": {"favoriete_kleur": {"value": "blauw"}}}

store.write(recover_path, good)
ok("backup staat er na een goede write",
   os.path.exists(store.backup_path(recover_path)))

# Nu het hoofdbestand kapotmaken
with open(recover_path, "w", encoding="utf-8") as handle:
    handle.write("{ dit is geen geldige json ]]")

recovered = store.read(recover_path)

ok("read() herstelt de inhoud via de backup", recovered == good)
ok("herstel is geregistreerd in STATS", store.STATS["recovered"] >= 1)

with patch.object(mem, "MEMORY_FILE", recover_path):
    restored = load_memory()
    ok("load_memory() herstelt via backup",
       restored["voorkeuren"]["favoriete_kleur"]["value"] == "blauw")
    ok("recall werkt op het herstelde geheugen",
       recall("favoriete_kleur") == "blauw")

# Ook een leesfout (geen bestand) mag veilig terugvallen
missing = os.path.join(recover_dir, "bestaat-niet.json")

ok("read() op ontbrekend bestand geeft None", store.read(missing) is None)

# =============================================================
# 9: backup ontbreekt -> veilige fallback
# =============================================================

store.reset_cache()

fallback_dir = make_dir()
fallback_path = os.path.join(fallback_dir, "memory.json")

with open(fallback_path, "w", encoding="utf-8") as handle:
    handle.write("{{{ kapotte json")

ok("geen backup aanwezig", not os.path.exists(store.backup_path(fallback_path)))
ok("read() geeft None als er geen backup is",
   store.read(fallback_path) is None)
ok("veilige fallback is geregistreerd", store.STATS["fallbacks"] >= 1)

# Ook een corrupt backup-bestand mag het niet opblazen
broken_bak = os.path.join(fallback_dir, "broken.json")

with open(broken_bak, "w", encoding="utf-8") as handle:
    handle.write("niets dan kapot")

with open(store.backup_path(broken_bak), "w", encoding="utf-8") as handle:
    handle.write("OOK KAPOT")

ok("read() geeft None als de backup ook kapot is",
   store.read(broken_bak) is None)

with patch.object(mem, "MEMORY_FILE", fallback_path):
    ok("load_memory() geeft lege memory zonder backup",
       load_memory() == empty_memory())
    ok("remember werkt ook na een veilige fallback",
       remember("naam", "tester") is not None)
    ok("opnieuw opgeslagen waarde is terug te lezen",
       recall("naam") == "tester")

# =============================================================
# 10: bestaande memory-functionaliteit blijft werken
# =============================================================

print("\n===== 10: BESTAANDE MEMORY-FUNCTIONALITEIT =====\n")

store.reset_cache()

work2 = make_dir()
live = os.path.join(work2, "memory.json")

with patch.object(mem, "MEMORY_FILE", live):

    ok("lege memory op een schoon pad", load_memory() == empty_memory())

    result = remember("favoriete_kleur", "blauw")

    ok("remember() geeft de metadata-dict terug",
       isinstance(result, dict) and result.get("changed") is False)

    ok("recall() geeft de waarde terug", recall("favoriete_kleur") == "blauw")

    category, entry = find_entry("favoriete_kleur")

    ok("find_entry() vindt categorie + entry",
       category == "voorkeuren" and entry is not None)

    ok("get_entry() geeft de entry met metadata",
       get_entry("favoriete_kleur") is not None
       and get_entry("favoriete_kleur").get("value") == "blauw")

    ok("entry heeft source + updated",
       entry.get("source") == "conversation" and entry.get("updated"))

    ok("recall() matcht NIET meer gedeeltelijk",
       recall("kleur") is None)

    ok("recall() matcht wel genormaliseerd",
       recall("favoriete kleur") == "blauw")

    remember("lichtvoorkeur", "warm wit", category="voorkeuren")

    relevant = get_relevant_memory("hoe moet het licht in de kamer?")

    ok("get_relevant_memory() vindt de lichtvoorkeur",
       any(item.get("key") == "lichtvoorkeur" for item in relevant))

    ok("relevant_memory_prompt() levert tekst",
       "lichtvoorkeur" in relevant_memory_prompt("hoe moet het licht zijn?"))

    # expliciet wijzigen
    update_memory("favoriete_kleur", "groen", category="voorkeuren")

    ok("update_memory() wijzigt de waarde", recall("favoriete_kleur") == "groen")

    updated_entry = get_entry("favoriete_kleur")

    ok("update_memory() markeert corrected=True",
       updated_entry.get("corrected") is True)
    ok("update_memory() bewaart de vorige waarde",
       updated_entry.get("previous_value") == "blauw")
    ok("entry is niet meer in conflict",
       updated_entry.get("conflict") is False)

    # conflict via remember: de nieuwe waarde wordt NIET stilzwijgend
    # opgeslagen (Fase 14 Stap 5), maar ter bevestiging aangeboden.
    conflict = remember("favoriete_kleur", "rood")

    ok("remember() meldt een conflict", conflict.get("conflict") is True)
    ok("remember() vraagt om bevestiging",
       conflict.get("needs_confirm") is True)
    ok("de oude waarde blijft staan na een conflict",
       recall("favoriete_kleur") == "groen")
    ok("het conflict meldt de oude waarde",
       conflict.get("old_value") == "groen")

    # na bevestiging wordt wél de nieuwe waarde opgeslagen
    resolve_conflict("favoriete_kleur", "rood", category="voorkeuren")

    ok("na bevestiging staat de nieuwe waarde er",
       recall("favoriete_kleur") == "rood")
    ok("na bevestiging is de vorige waarde bewaard",
       get_entry("favoriete_kleur").get("previous_value") == "groen")
    ok("na bevestiging is het conflict opgelost",
       get_entry("favoriete_kleur").get("conflict") is False)

    # categorie-overzichten
    all_mem = get_all_memory()

    ok("get_all_memory() bevat sleutels zonder entry-wrapper",
       "favoriete_kleur" in all_mem and all_mem["favoriete_kleur"] == "rood")

    ok("get_category_memory() werkt per categorie",
       "lichtvoorkeur" in get_category_memory("voorkeuren"))

    ok("memory_summary() vat het geheugen samen",
       "favoriete kleur" in memory_summary())

    # verwijderen
    ok("forget() verwijdert de sleutel", forget("favoriete_kleur") is True)
    ok("vergeten sleutel is weg", recall("favoriete_kleur") is None)
    ok("forget() op onbekende sleutel geeft False",
       forget("bestaat_niet") is False)

    # clear
    clear_result = clear_memory()

    ok("clear_memory() geeft True", clear_result is True)
    ok("na clear is het geheugen leeg", get_all_memory() == {})

# =============================================================
# 11: USAGE TRACKING
# =============================================================

print("\n===== 11: USAGE TRACKING =====\n")

work3 = make_dir()
live3 = os.path.join(work3, "memory.json")

with patch.object(mem, "MEMORY_FILE", live3):

    reset_touch_usage()

    # --- eerst een geheugen aanmaken om te touchen ---
    remember("favoriete_game", "Spider-Man", category="voorkeuren")
    remember("gpu", "RTX 3060 Ti", category="pc")

    # --- 11a: eerste gebruik ---
    ok("touch_usage op onbekende sleutel geeft False",
       touch_usage("bestaat_niet") is False)

    result = touch_usage("favoriete_game")

    ok("touch_usage geeft True bij succes", result is True)

    entry = get_entry("favoriete_game")

    ok("usage_count is 1 na eerste gebruik",
       entry.get("usage_count") == 1)
    ok("last_used is gezet",
       entry.get("last_used") is not None)

    first_used = entry["last_used"]

    # --- 11b: meerdere keren gebruiken ---
    touch_usage("favoriete_game")
    touch_usage("favoriete_game")

    entry = get_entry("favoriete_game")

    ok("usage_count blijft 1 door dedup在同一 commando",
       entry.get("usage_count") == 1)

    # --- 11c: last_used wordt bijgewerkt (eerste aanroep) ---
    reset_touch_usage()
    import time
    time.sleep(0.05)
    touch_usage("favoriete_game")

    entry = get_entry("favoriete_game")

    ok("last_used is bijgewerkt na nieuwe commando-aanroep",
       entry.get("last_used") is not None)
    ok("usage_count is 2 na twee aparte commandos",
       entry.get("usage_count") == 2)

    # --- 11d: dedup binnen één commando ---
    reset_touch_usage()

    touch_usage("gpu")
    ok("eerste touch van gpu telt", get_entry("gpu").get("usage_count") == 1)

    touch_usage("gpu")
    ok("tweede touch van gpu在同一 commando telt NIET",
       get_entry("gpu").get("usage_count") == 1)

    touch_usage("gpu")
    ok("derde touch van gpu在同一 commando telt NIET",
       get_entry("gpu").get("usage_count") == 1)

    # reset → opnieuw tellen
    reset_touch_usage()

    touch_usage("gpu")
    ok("na reset telt gpu weer",
       get_entry("gpu").get("usage_count") == 2)

    # --- 11e: verschillende sleutels在同一 commando ---
    reset_touch_usage()

    touch_usage("favoriete_game")
    touch_usage("gpu")
    touch_usage("favoriete_game")

    ok("favoriete_game telt 1x in dit commando",
       get_entry("favoriete_game").get("usage_count") == 2 + 1)
    ok("gpu telt 1x in dit commando",
       get_entry("gpu").get("usage_count") == 2 + 1)

    # --- 11f: geen substring-match meer ---
    reset_touch_usage()

    touch_usage("game")
    ok("touch_usage('game') raakt 'favoriete_game' NIET meer",
       get_entry("favoriete_game").get("usage_count") == 3)

    ok("touch_usage telt wel de exacte sleutel",
       touch_usage("favoriete_game")
       and get_entry("favoriete_game").get("usage_count") == 3 + 1)

    reset_touch_usage()

    touch_usage("favoriete game")
    ok("touch_usage matcht genormaliseerd (spatie = underscore)",
       get_entry("favoriete_game").get("usage_count") == 3 + 2)

    # --- 11g: category-parameter ---
    reset_touch_usage()

    touch_usage("gpu", category="pc")
    ok("category-parameter werkt",
       get_entry("gpu", category="pc").get("usage_count") == 3 + 1)

    # --- 11h: bestaande functionaliteit niet gebroken ---
    ok("recall() werkt nog na usage-tracking",
       recall("favoriete_game") == "Spider-Man")
    ok("get_all_memory() toont nog steeds waarden",
       "favoriete_game" in get_all_memory())

    # --- 11i: reset_touch_usage wist de set ---
    reset_touch_usage()
    ok("_touched_keys is leeg na reset", len(_touched_keys) == 0)
    touch_usage("gpu")
    ok("_touched_keys bevat 'gpu' na touch",
       "gpu" in _touched_keys)
    reset_touch_usage()
    ok("_touched_keys is weer leeg na tweede reset",
       len(_touched_keys) == 0)

# Bestanden opruimen
for folder in (work, recover_dir, fallback_dir, work2, work3):
    shutil.rmtree(folder, ignore_errors=True)

store.reset_cache()

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)
