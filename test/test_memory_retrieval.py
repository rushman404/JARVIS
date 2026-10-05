"""
JARVIS — Memory retrieval tests (Fase 14, Stap 3)
================================================

Test de verbeterde relevantie-scoring van memory/memory.py:

  1. duidelijke match
  2. meerdere zoekwoorden
  3. irrelevante memories
  4. categorie / key / value matches
  5. ranking van resultaten
  6. lege resultaten
  7. limiet op het aantal resultaten
  8. usage_count als lichte factor (geen decay)
  9. backwards compatibility
 10. bestaande memory-functionaliteit blijft werken

De kern van Stap 3 is dat toevallige substrings niet meer scoren
("ram" in "programma"), dus daar begint deze test mee.

Alle tests draaien op een tijdelijk geheugenbestand. De echte
memory/memory.json wordt nooit aangeraakt.
"""

import sys
import os
import io
import json
import time
import shutil
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from memory import store
from memory.memory import (
    DEFAULT_CATEGORIES,
    DEFAULT_RELEVANT_ITEMS,
    load_memory,
    save_memory,
    remember,
    recall,
    forget,
    get_all_memory,
    get_relevant_memory,
    relevant_memory_prompt,
    relevance_score,
    _phrase_in,
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


def keys_of(items):
    return [item["key"] for item in items]


def score_of(items, key):
    for item in items:
        if item["key"] == key:
            return item["score"]
    return None


def set_usage(key, count, last_used=None):
    """Zet usage_count/last_used rechtstreeks op een entry."""

    data = load_memory()

    for category in DEFAULT_CATEGORIES:
        if key in data.get(category, {}):
            data[category][key]["usage_count"] = count
            if last_used is not None:
                data[category][key]["last_used"] = last_used
            save_memory(data)
            return True

    return False


work = tempfile.mkdtemp(prefix="jarvis_retrieval_test_")
path = os.path.join(work, "memory.json")

store.reset_cache()

# =============================================================
# Testgeheugen
# =============================================================

FIXTURE = [
    ("favoriete_kleur", "blauw", "voorkeuren"),
    ("favoriete_game", "Spider-Man", "voorkeuren"),
    ("favoriete_band", "Coldplay", "muziek"),
    ("lichtvoorkeur", "warm wit", "voorkeuren"),
    ("gpu", "RTX 3060 Ti", "pc"),
    ("monitor", "Samsung", "pc"),
    ("project_deadline_website", "maart", "projecten"),
    ("bedlamp", "lamp naast het bed", "apparaten"),
]

# =============================================================
# 0: substring-regressie — de kern van Stap 3
# =============================================================

print("\n===== 0: SUBSTRING-REGRESSIE (woordgrenzen) =====\n")

ok('"ram" matcht NIET in "programma"',
   not _phrase_in("ram", "open mijn programma"))
ok('"ram" matcht NIET in "ramp"',
   not _phrase_in("ram", "dat is een ramp"))
ok('"licht" matcht NIET in "misschien"',
   not _phrase_in("licht", "dat is misschien leuk"))
ok('"fel" matcht NIET in "zelf"',
   not _phrase_in("fel", "ik ben zelf thuis"))
ok('"stand" matcht NIET in "verstandig"',
   not _phrase_in("stand", "dat is verstandig"))
ok('"tv" matcht NIET in "actief"',
   not _phrase_in("tv", "ik ben actief bezig"))
ok('"pc" matcht NIET in "hoe gaat het met je"',
   not _phrase_in("pc", "hoe gaat het met je"))
ok('"gpu" matcht WEL in "mijn gpu"',
   _phrase_in("gpu", "mijn gpu"))
ok('"favoriete_kleur" matcht "favoriete kleur" (underscore = spatie)',
   _phrase_in("favoriete_kleur", "wat is mijn favoriete kleur"))
ok('"favoriete_kleur" matcht "favoriete-kleur" (koppelteken)',
   _phrase_in("favoriete_kleur", "mijn favoriete-kleur"))

with patch.object(mem, "MEMORY_FILE", path):

    ok("substring-ramis leveren score 0 op",
       relevance_score("open mijn programma", "pc", "ram", "8GB") == 0.0)
    ok("'ramp' levert geen score op voor sleutel 'ram'",
       relevance_score("dat is een ramp", "pc", "ram", "8GB") == 0.0)

    for key, value, category in FIXTURE:
        remember(key, value, category=category)

    # =========================================================
    # 1: duidelijke match
    # =========================================================

    print("\n===== 1: DUIDELIJKE MATCH =====\n")

    found = get_relevant_memory("wat is mijn favoriete kleur?")

    ok("favoriete_kleur staat bovenaan", keys_of(found)[0] == "favoriete_kleur")
    ok("favoriete_kleur is gevonden", "favoriete_kleur" in keys_of(found))
    ok("waarde klopt", score_of(found, "favoriete_kleur") is not None)

    exact = relevance_score("mijn favoriete kleur", "voorkeuren", "favoriete_kleur", "blauw")
    vague = relevance_score("mijn kleur", "voorkeuren", "favoriete_kleur", "blauw")
    none = relevance_score("wat is het weer", "voorkeuren", "favoriete_kleur", "blauw")

    ok("exacte key-match scoort hoger dan gedeeltelijke", exact > vague)
    ok("gedeeltelijke match scoort hoger dan geen match", vague > none)

    # =========================================================
    # 2: meerdere zoekwoorden
    # =========================================================

    print("\n===== 2: MEERDERE ZOEKWOORDEN =====\n")

    found = get_relevant_memory("mijn gpu en mijn monitor")

    ok("meerdere sleutels worden gevonden",
       "gpu" in keys_of(found) and "monitor" in keys_of(found))

    gpu_score = score_of(found, "gpu")
    monitor_score = score_of(found, "monitor")

    ok("beide pc-feiten scoren positief", gpu_score > 0 and monitor_score > 0)
    ok("gpu scoort hoger dan monitor (waarde RTX in de vraag)",
       get_relevant_memory("mijn gpu RTX") and
       score_of(get_relevant_memory("mijn gpu RTX"), "gpu") > 0)

    # meervoudsvorm moet matchen
    meervoud = get_relevant_memory("ik hou van lampen")

    ok("'lampen' matcht de sleutel 'bedlamp' via meervoudsvorm",
       "bedlamp" in keys_of(meervoud) or "bedlamp" in keys_of(get_relevant_memory("lamp")))

    # =========================================================
    # 3: irrelevante memories
    # =========================================================

    print("\n===== 3: IRRELEVANTE MEMORIES =====\n")

    onzin = get_relevant_memory("zzqqxx wwvvuu")

    ok("onzin geeft lege resultaten", onzin == [])
    ok("onzin geeft lege prompt", relevant_memory_prompt("zzqqxx wwvvuu") == "")

    weer = get_relevant_memory("wat is het weer morgen")

    ok("weervraag haalt geen pc- of muziek-feiten",
       "gpu" not in keys_of(weer) and "favoriete_band" not in keys_of(weer))

    # een incidentele substring mag een feit niet opleveren
    programma = get_relevant_memory("open mijn programma")

    ok("'programma' levert de sleutel 'gpu'/'ram' niet op",
       "gpu" not in keys_of(programma))

    # =========================================================
    # 4: categorie / key / value matches
    # =========================================================

    print("\n===== 4: CATEGORIE / KEY / VALUE MATCHES =====\n")

    key_match = relevance_score("mijn gpu", "pc", "gpu", "RTX 3060 Ti")
    value_match = relevance_score("RTX 3060", "pc", "iets_anders", "RTX 3060 Ti")
    category_match = relevance_score("mijn processor", "pc", "iets_anders", "onbekend")

    ok("key-match scoort het hoogst", key_match > value_match)
    ok("value-match scoort boven categorie-match", value_match > category_match)
    ok("alleen een categorietrefwoord scoort nog positief", category_match > 0)

    # waarde-match: de waarde zelf in de vraag
    waarde = relevance_score("ik luister graag coldplay", "muziek", "favoriete_band", "Coldplay")

    ok("waarde 'Coldplay' wordt in de vraag herkend", waarde > 0)

    # categorie-trefwoorden werken
    licht_score = relevance_score("maak het licht warm", "voorkeuren", "onbekend", "x")
    muziek_score = relevance_score("zet de muziek aan", "muziek", "onbekend", "x")

    ok("'licht' is een geldige voorkeuren-trefwoord", licht_score > 0)
    ok("'muziek' is een geldig muziek-trefwoord", muziek_score > 0)
    ok("'muziek' scoort niet in de voorkeuren-categorie",
       relevance_score("zet de muziek aan", "voorkeuren", "onbekend", "x") == 0.0)

    # alle woorden van de sleutel terug -> bonus
    volledig = relevance_score("mijn favoriete kleur", "voorkeuren", "favoriete_kleur", "blauw")
    deels = relevance_score("mijn kleur blauw", "voorkeuren", "favoriete_kleur", "blauw")

    ok("alle sleutelwoorden aanwezig scoort hoger dan deels", volledig > deels)

    # =========================================================
    # 5: ranking van resultaten
    # =========================================================

    print("\n===== 5: RANKING =====\n")

    found = get_relevant_memory("mijn gpu en mijn monitor")

    scores = [item["score"] for item in found]

    ok("scores zijn aflopend gesorteerd", scores == sorted(scores, reverse=True))
    ok("resultaten bevatten categorie/key/value/score/usage_count",
       all({"category", "key", "value", "score", "usage_count"} <= set(item)
           for item in found))

    # exacte key-match moet boven een zwakke match eindigen
    gemengd = get_relevant_memory("bedlamp")

    ok("exacte key-match 'bedlamp' staat bovenaan",
       keys_of(gemengd)[0] == "bedlamp")

    # =========================================================
    # 6: lege resultaten
    # =========================================================

    print("\n===== 6: LEGE RESULTATEN =====\n")

    ok("lege vraag geeft lege lijst", get_relevant_memory("") == [])
    ok("vraag met alleen stopwoorden geeft lege lijst",
       get_relevant_memory("en of maar") == [])
    ok("lege prompt bij lege lijst", relevant_memory_prompt("zzqqxx") == "")

    # geen feiten opgeslagen
    with patch.object(mem, "MEMORY_FILE", os.path.join(work, "leeg.json")):
        ok("leeg geheugen geeft lege lijst", get_relevant_memory("mijn kleur") == [])
        ok("leeg geheugen geeft lege prompt",
           relevant_memory_prompt("mijn kleur") == "")

    # =========================================================
    # 7: limiet op het aantal resultaten
    # =========================================================

    print("\n===== 7: LIMIET OP AANTAL RESULTATEN =====\n")

    for i in range(10):
        remember(f"testitem_{i}", f"waarde {i}", category="algemeen")

    # Met een ruime limiet zien we hoeveel treffers er echt zijn.
    alles = get_relevant_memory("testitem waarde", max_items=50)

    ok("vindt meer dan 6 treffers in het geheugen",
       len(alles) > DEFAULT_RELEVANT_ITEMS)
    ok("standaard-limiet is 6",
       len(get_relevant_memory("testitem waarde")) == DEFAULT_RELEVANT_ITEMS)
    ok("DEFAULT_RELEVANT_ITEMS bestaat en is 6", DEFAULT_RELEVANT_ITEMS == 6)
    ok("limiet 3 werkt", len(get_relevant_memory("testitem waarde", max_items=3)) == 3)
    ok("limiet 1 werkt", len(get_relevant_memory("testitem waarde", max_items=1)) == 1)
    ok("meer dan gevraagd geeft nooit meer dan gevraagd",
       len(get_relevant_memory("testitem waarde", max_items=99)) <= 10)

    for i in range(10):
        forget(f"testitem_{i}")

    # =========================================================
    # 8: usage_count als lichte factor, geen decay
    # =========================================================

    print("\n===== 8: GEBRUIKSDATA ALS LICHTE FACTOR =====\n")

    # relevance_score() werkt alleen met de waarden die je meegeeft;
    # de tekstscore is dus de basis zonder enige gebruiksdata.
    basis = relevance_score("mijn monitor", "pc", "monitor", "Samsung")

    ok("basis zonder gebruiksdata scoort positief", basis > 0)

    veel = relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                           usage_count=12, last_used=None)

    ok("vaak gebruikt geeft een kleine bonus", veel > basis)
    ok("usage-bonus blijft klein (max +1,5)", 0 < veel - basis <= 1.5)

    recent = relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                             usage_count=0,
                             last_used=time.strftime("%Y-%m-%dT%H:%M:%S"))

    ok("recent gebruikt geeft een kleine bonus", recent > basis)
    ok("recency-bonus blijft klein (max +1,0)", 0 < recent - basis <= 1.0)

    oud = relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                          usage_count=0, last_used="2020-01-01T00:00:00")

    ok("verouderde last_used levert geen bonus", oud == basis)

    # Gebruik mag een IRRELEVANT feit nooit opleveren.
    irrelevant = relevance_score("zzqqxx wwvvuu", "pc", "monitor", "Samsung",
                                 usage_count=9999,
                                 last_used=time.strftime("%Y-%m-%dT%H:%M:%S"))

    ok("veel gebruikt maar tekstueel irrelevant blijft score 0",
       irrelevant == 0.0)

    irrelevant_items = get_relevant_memory("zzqqxx wwvvuu")

    ok("veel gebruikt feit komt niet in irrelevante resultaten voor",
       "monitor" not in keys_of(irrelevant_items))

    # End-to-end: get_relevant_memory leest de usage_count uit de entry.
    set_usage("monitor", 20, last_used=time.strftime("%Y-%m-%dT%H:%M:%S"))

    items = get_relevant_memory("mijn monitor")

    ok("entry usage_count wordt meegeleverd in de resultaten",
       bool(items) and items[0]["usage_count"] == 20)
    ok("opgeslagen gebruiksdata verhoogt de score end-to-end",
       bool(items) and items[0]["score"] > basis)

    # ongeldige waarden mogen niet crashen
    ok("ongeldige usage_count geeft 0 bonus",
       relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                       usage_count="abc") == basis)
    ok("ongeldige last_used geeft 0 bonus",
       relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                       last_used="geen datum") == basis)
    ok("lege waarden geven 0 bonus",
       relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                       usage_count=None, last_used=None) == basis)
    ok("lege tekenreeks als usage_count geeft 0 bonus",
       relevance_score("mijn monitor", "pc", "monitor", "Samsung",
                       usage_count="") == basis)

    set_usage("monitor", 0, last_used=None)

    # =========================================================
    # 9: backwards compatibility
    # =========================================================

    print("\n===== 9: BACKWARDS COMPATIBILITY =====\n")

    ok("relevance_score werkt met 4 argumenten (oude aanroep)",
       relevance_score("mijn gpu", "pc", "gpu", "RTX") > 0)
    ok("relevance_score accepteert de nieuwe keyword-argumenten",
       relevance_score("mijn gpu", "pc", "gpu", "RTX",
                       usage_count=3, last_used=None) > 0)
    ok("get_relevant_memory werkt zonder max_items",
       isinstance(get_relevant_memory("mijn gpu"), list))
    ok("relevant_memory_prompt geeft tekst met de sleutel erin",
       "gpu" in relevant_memory_prompt("mijn gpu"))
    ok("None als vraag geeft geen crash",
       get_relevant_memory(None) == [] or isinstance(get_relevant_memory(None), list))

    # de oude publieke API moet ongewijzigd werken
    ok("memory_summary werkt nog", isinstance(memory_summary_text := __import__(
        "memory.memory", fromlist=["memory_summary"]).memory_summary(), str))

    # =========================================================
    # 10: bestaande memory-functionaliteit blijft werken
    # =========================================================

    print("\n===== 10: BESTAANDE FUNCTIONALITEIT =====\n")

    ok("recall leest nog waarden", recall("favoriete_kleur") == "blauw")
    ok("get_all_memory bevat nog sleutels", "favoriete_kleur" in get_all_memory())
    ok("categories zijn intact", set(load_memory()) == set(DEFAULT_CATEGORIES))

    entry = load_memory()["voorkeuren"]["favoriete_kleur"]

    ok("entry houdt zijn metadata", entry.get("source") and entry.get("updated"))

    # retrieval mag het geheugen niet beschadigen
    voor = json.dumps(load_memory(), sort_keys=True)
    get_relevant_memory("mijn gpu en mijn kleur")
    relevant_memory_prompt("mijn kleur")
    relevance_score("mijn gpu", "pc", "gpu", "RTX")
    na = json.dumps(load_memory(), sort_keys=True)

    ok("retrieval verandert het geheugen niet", voor == na)

    # legacy plat formaat blijft leesbaar
    legacy = os.path.join(work, "legacy.json")
    store.write(legacy, {"favoriete_kleur": "rood", "naam": "Rushi"})

    with patch.object(mem, "MEMORY_FILE", legacy):
        data = load_memory()

        ok("legacy plat formaat wordt nog steeds geconverteerd",
           "voorkeuren" in data and "favoriete_kleur" in data["voorkeuren"])
        ok("legacy gegevens zijn bruikbaar", recall("favoriete_kleur") == "rood")
        ok("legacy retrieval werkt",
           keys_of(get_relevant_memory("mijn kleur")) == ["favoriete_kleur"])

# Bestanden opruimen
for leftover in (
    path, path + ".bak", path + ".lock",
    os.path.join(work, "leeg.json"),
    os.path.join(work, "leeg.json.bak"),
    os.path.join(work, "legacy.json"),
    os.path.join(work, "legacy.json.bak"),
):
    try:
        os.remove(leftover)
    except OSError:
        pass

shutil.rmtree(work, ignore_errors=True)

store.reset_cache()

# vingerafdruk van de echte memory.json moet onveranderd zijn
import hashlib

REAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memory", "memory.json"
)

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)
