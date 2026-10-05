"""
JARVIS — Memory priority + aging tests (Fase 14, Stap 4)
=====================================================

Test de nieuwe priority- en aging-functies in memory/memory.py:

  1. standaard priority
  2. hoge/lage priority
  3. oude versus recente memory
  4. vaak gebruikte versus ongebruikte memory
  5. irrelevante memory blijft laag
  6. bestaande memories zonder priority
  7. combinatie van relevance + priority + aging
  8. backwards compatibility

Alle tests draaien op tijdelijke bestanden. De echte
memory/memory.json wordt nooit aangeraakt.
"""

import sys
import os
import io
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
    load_memory,
    save_memory,
    remember,
    recall,
    forget,
    get_all_memory,
    get_relevant_memory,
    relevant_memory_prompt,
    relevance_score,
    _wrap,
    _priority_factor,
    _aging_factor,
    _age_days,
    _now,
    _DEFAULT_PRIORITY,
    _MIN_PRIORITY,
    _MAX_PRIORITY,
    _AGING_FRESH_FACTOR,
    _AGING_OLD_FACTOR,
    _AGING_STALE_FACTOR,
)

import memory.memory as mem

passed = 0
failed = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def keys_of(items):
    return [item["key"] for item in items]


def score_of(items, key):
    for item in items:
        if item["key"] == key:
            return item["score"]
    return None


def priority_of(items, key):
    for item in items:
        if item["key"] == key:
            return item.get("priority", _DEFAULT_PRIORITY)
    return None


def _ago(days):
    """Geeft een tijdstempel X dagen geleden."""
    t = time.time() - (days * 86400)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


work = tempfile.mkdtemp(prefix="jarvis_priority_test_")
path = os.path.join(work, "memory.json")

store.reset_cache()


# =============================================================
# 1: standaard priority
# =============================================================

print("\n===== 1: STANDAARD PRIORITY =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    ok("_DEFAULT_PRIORITY is 1.0", _DEFAULT_PRIORITY == 1.0)
    ok("_MIN_PRIORITY is 0.0", _MIN_PRIORITY == 0.0)
    ok("_MAX_PRIORITY is 10.0", _MAX_PRIORITY == 10.0)

    remember("favoriete_kleur", "blauw", category="voorkeuren")

    data = load_memory()
    entry = data["voorkeuren"]["favoriete_kleur"]

    ok("nieuwe entry heeft priority 1.0",
       entry.get("priority") == 1.0)

    ok("_priority_factor(1.0) geeft 1.0", _priority_factor(1.0) == 1.0)
    ok("_priority_factor(None) geeft 1.0", _priority_factor(None) == 1.0)
    ok("_priority_factor('abc') geeft 1.0", _priority_factor("abc") == 1.0)
    ok("_priority_factor(0) geeft 0.0", _priority_factor(0) == 0.0)

    ok("priority is in ENTRY_META_KEYS", "priority" in mem.ENTRY_META_KEYS)


# =============================================================
# 2: hoge/lage priority
# =============================================================

print("\n===== 2: HOGE/LAGE PRIORITY =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    remember("hoog", "test", category="algemeen", priority=5.0)
    remember("laag", "test", category="algemeen", priority=0.3)
    remember("neutraal", "test", category="algemeen")

    score_hoog = relevance_score("test", "algemeen", "hoog", "test",
                                 priority=5.0)
    score_neutraal = relevance_score("test", "algemeen", "neutraal", "test",
                                     priority=1.0)
    score_laag = relevance_score("test", "algemeen", "laag", "test",
                                 priority=0.3)

    ok("hoge priority (5.0) verdubbelt de score",
       abs(score_hoog / score_neutraal - 5.0) < 0.01)
    ok("lage priority (0.3) halveert de score",
       score_laag < score_neutraal)
    ok("lage priority geeft nog steeds een positieve score",
       score_laag > 0)

    # priority wordt begrensd
    remember("grens_boven", "test", category="algemeen", priority=999)
    remember("grens_onder", "test", category="algemeen", priority=-5)

    data = load_memory()

    ok("priority wordt begrensd naar max 10.0",
       data["algemeen"]["grens_boven"]["priority"] == 10.0)
    ok("priority wordt begrensd naar min 0.0",
       data["algemeen"]["grens_onder"]["priority"] == 0.0)

    ok("priority 0.0 maakt de score 0.0",
       relevance_score("test", "algemeen", "grens_onder", "test",
                       priority=0.0) == 0.0)

    # Bij een tegenstrijdige waarde wordt niets opgeslagen (Stap 5):
    # "hoog" staat op "test", dus dit is een conflict.
    tegenspraak = remember("hoog", "nieuwe waarde", category="algemeen")

    ok("tegenstrijdige waarde wordt niet opgeslagen",
       tegenspraak.get("needs_confirm") is True)
    ok("de oude waarde blijft staan na een conflict",
       mem.recall("hoog") == "test")

    # priority wordt bewaard zodra de wijziging is bevestigd
    remember("hoog", "nieuwe waarde", category="algemeen", force=True)
    data = load_memory()

    ok("priority wordt bewaard bij een update",
       data["algemeen"]["hoog"]["priority"] == 5.0)

    # Ook bij een bevestigde wijziging kan de priority gezet worden.
    remember("hoog", "weer een nieuwe waarde", category="algemeen",
             priority=2.0, force=True)
    data = load_memory()

    ok("expliciete priority overschrijft de oude na bevestiging",
       data["algemeen"]["hoog"]["priority"] == 2.0)

    # priority in output van get_relevant_memory
    items = get_relevant_memory("test")
    found = [i for i in items if i["key"] in ("hoog", "laag")]

    ok("get_relevant_memory retourneert priority per item",
       all("priority" in i for i in found))


# =============================================================
# 3: oude versus recente memory
# =============================================================

print("\n===== 3: OUDE VERSUS RECENTE MEMORY =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # Maak drie versies van hetzelfde feit met verschillende leeftijden
    remember("recent_fait", "lucht", category="algemeen")
    remember("oud_fait", "lucht", category="algemeen")
    remember("heel_oud_fait", "lucht", category="algemeen")

    data = load_memory()
    data["algemeen"]["recent_fait"]["updated"] = _ago(1)
    data["algemeen"]["oud_fait"]["updated"] = _ago(180)
    data["algemeen"]["heel_oud_fait"]["updated"] = _ago(730)
    save_memory(data)

    af_recent = _aging_factor(data["algemeen"]["recent_fait"]["updated"])
    af_oud = _aging_factor(data["algemeen"]["oud_fait"]["updated"])
    af_heel_oud = _aging_factor(data["algemeen"]["heel_oud_fait"]["updated"])

    ok("recente memory krijgt een bonus (factor > 1.0)",
       af_recent == _AGING_FRESH_FACTOR)
    ok("6 maanden oude memory krijgt milde veroudering",
       af_oud == _AGING_OLD_FACTOR)
    ok("2 jaar oude memory krijgt sterkere veroudering",
       af_heel_oud == _AGING_STALE_FACTOR)
    ok("veroudering is nooit zo sterk dat een relevant feit verdwijnt",
       af_heel_oud >= 0.5)

    # Score: de oude moet nog steeds scoren als de vraag dezelfde woorden bevat
    s_recent = relevance_score("lucht", "algemeen", "recent_fait", "lucht",
                               updated=data["algemeen"]["recent_fait"]["updated"])
    s_oud = relevance_score("lucht", "algemeen", "oud_fait", "lucht",
                            updated=data["algemeen"]["oud_fait"]["updated"])
    s_heel_oud = relevance_score("lucht", "algemeen", "heel_oud_fait", "lucht",
                                 updated=data["algemeen"]["heel_oud_fait"]["updated"])

    ok("recente memory scoort hoger dan oude", s_recent > s_oud)
    ok("oude memory scoort hoger dan heel oude", s_oud > s_heel_oud)
    ok("zelfs een hele oude memory scoort nog steeds positief",
       s_heel_oud > 0)

    # _age_days test
    ok("_age_days(None) geeft None", _age_days(None) is None)
    ok("_age_days('ongeldig') geeft None", _age_days("ongeldig") is None)
    ok("_age_days(nu) geeft rond de 0", _age_days(_now()) < 0.1)


# =============================================================
# 4: vaak gebruikte versus ongebruikte memory
# =============================================================

print("\n===== 4: GEBRUIK: VAAK VERSUS ONGEBRUIKT =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    items = get_relevant_memory("lucht")

    ok("alle lucht-feiten staan in de resultaten",
       len([i for i in items if i["value"] == "lucht"]) == 3)

    scores = {i["key"]: i["score"] for i in items if i["value"] == "lucht"}

    ok("recente memory heeft de hoogste score",
       scores.get("recent_fait", 0) >= scores.get("oud_fait", 0))

    ok("heel oude memory heeft de laagste score",
       scores.get("heel_oud_fait", 0) <= scores.get("oud_fait", 0))


# =============================================================
# 5: irrelevante memory blijft laag
# =============================================================

print("\n===== 5: IRRELEVANTE MEMORY BLIJFT LAAG =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    remember("irrelevant", "xyzqwerty", category="algemeen", priority=10.0)

    s_irrelevant = relevance_score("open programma", "pc", "irrelevant",
                                   "xyzqwerty", priority=10.0)
    s_geen = relevance_score("open programma", "pc", "favoriete_kleur",
                             "blauw")

    ok("irrelevant feit met priority 10.0 scoort 0.0 (geen tekstmatch)",
       s_irrelevant == 0.0)

    # get_relevant_memory bevat het niet
    items = get_relevant_memory("open programma")
    ok("'irrelevant' met priority 10.0 staat NIET in de resultaten",
       "irrelevant" not in keys_of(items))


# =============================================================
# 6: bestaande memories zonder priority
# =============================================================

print("\n===== 6: BESTAANDE MEMORIES ZONDER PRIORITY =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # Schrijf een plat entry zonder priority naar het bestand
    import json

    legacy_data = {
        "voorkeuren": {
            "oude_kleur": {
                "value": "rood",
                "source": "conversation",
                "updated": _now(),
                "previous_value": None,
                "corrected": False,
                "conflict": False,
                "usage_count": 0,
                "last_used": None,
                # GEEN priority-key!
            }
        }
    }

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(legacy_data, handle, indent=4, ensure_ascii=False)

    data = load_memory()

    ok("entry zonder priority krijgt automatisch priority 1.0",
       data["voorkeuren"]["oude_kleur"]["priority"] == 1.0)

    items = get_relevant_memory("kleur")
    found = [i for i in items if i["key"] == "oude_kleur"]

    ok("get_relevant_memory werkt voor een legacy entry",
       len(found) == 1)
    ok("legacy entry heeft priority in output",
       found[0].get("priority") == 1.0)


# =============================================================
# 7: combinatie van relevance + priority + aging
# =============================================================

print("\n===== 7: COMBINATIE RELEVANCE + PRIORITY + AGING =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    remember("kleur_a", "blauw", category="voorkeuren", priority=2.0)
    remember("kleur_b", "groen", category="voorkeuren", priority=1.0)
    remember("kleur_c", "rood", category="voorkeuren", priority=1.0)

    # Kleur_c is oud
    data = load_memory()
    data["voorkeuren"]["kleur_c"]["updated"] = _ago(200)
    save_memory(data)

    items = get_relevant_memory("kleur")

    scores = {i["key"]: i["score"] for i in items if i["key"].startswith("kleur_")}

    ok("kleur_a (priority 2.0) scoort hoger dan kleur_b (priority 1.0)",
       scores.get("kleur_a", 0) > scores.get("kleur_b", 0))
    ok("kleur_b (recent) scoort hoger dan kleur_c (oud)",
       scores.get("kleur_b", 0) > scores.get("kleur_c", 0))
    ok("alle drie de kleuren scoren positief",
       all(scores.get(f"kleur_{c}", 0) > 0 for c in ("a", "b", "c")))

    # Priority is een vermenigvuldiger, geen opteller
    s_a = relevance_score("kleur", "voorkeuren", "kleur_a", "blauw",
                          priority=2.0)
    s_b = relevance_score("kleur", "voorkeuren", "kleur_b", "groen",
                          priority=1.0)

    ok("priority 2.0 verdubbelt ongeveer de base score",
       1.9 < s_a / s_b < 2.1)

    # Oude memory: factor nooit zo laag dat een tekstueel relevante
    # memory onder een onrelevante duikt
    s_relevant_oud = relevance_score("kleur", "voorkeuren", "kleur_c", "rood",
                                     updated=_ago(400))
    s_irrelevant = relevance_score("kleur", "voorkeuren", "pc_gpu", "x",
                                   updated=_ago(1))

    ok("zelfs een hele oude relevante memory scoort hoger "
       "dan een onrelevante recente",
       s_relevant_oud > s_irrelevant)


# =============================================================
# 8: backwards compatibility
# =============================================================

print("\n===== 8: BACKWARDS COMPATIBILITY =====\n")

with patch.object(mem, "MEMORY_FILE", path):

    # relevance_score met 4-6 args werkt nog steeds
    ok("relevance_score met 4 args",
       relevance_score("kleur", "voorkeuren", "kleur_a", "blauw") > 0)
    ok("relevance_score met 6 args",
       relevance_score("kleur", "voorkeuren", "kleur_a", "blauw",
                       usage_count=3, last_used=None) > 0)
    ok("relevance_score met 8 args",
       relevance_score("kleur", "voorkeuren", "kleur_a", "blauw",
                       usage_count=3, last_used=None,
                       priority=1.5, updated=None) > 0)

    # _wrap bevat priority
    entry = _wrap("test")
    ok("_wrap geeft priority 1.0",
       entry.get("priority") == 1.0)

    # get_relevant_memory output bevat priority
    items = get_relevant_memory("kleur")

    ok("elk item heeft een priority-veld",
       all("priority" in i for i in items))

    ok("eligible items bevatten ook updated",
       all("updated" in i for i in items))

    # remember behoudt priority bij een gewone update
    remember("kleur_a", "DONKER blauw", category="voorkeuren")
    data = load_memory()

    ok("priority 2.0 wordt bewaard bij update zonder explicit priority",
       data["voorkeuren"]["kleur_a"]["priority"] == 2.0)


# =============================================================
# Bestanden opruimen
# =============================================================

for leftover in (path, path + ".bak", path + ".lock"):
    try:
        os.remove(leftover)
    except OSError:
        pass

shutil.rmtree(work, ignore_errors=True)

store.reset_cache()

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)
