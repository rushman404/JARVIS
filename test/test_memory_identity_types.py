"""
JARVIS — Memory 2.0 identiteit, types en categorieën (stabilisatie)
===================================================================

Regressietests voor de drie ontwerpbesluiten die vóór Stap 7 zijn
vastgelegd. Ze bewaken het gedrag dat eerst fout was:

  1. FUZZY KEY MATCHING SCHEIDEN VAN IDENTITEIT
     Een substring mag nooit bepalen welke memory-entry wordt
     aangemaakt, gewijzigd, verwijderd of als conflict beschouwd.
     Opslag-identiteit is exact + normalisatie (_ ≡ - ≡ spatie).
     Losse substring-matching bestaat alleen nog als
     resolve_existing_key(): een gesprekshulp die niets wegschrijft.

  2. TYPEGRENS MEMORY <-> OBSIDIAN
     memory.json bewaart JSON-types; de vault bewaart een leesbare
     body plus 'value_type' (en 'value_json' voor niet-'str').
     memory -> Obsidian -> memory geeft dezelfde Python-waarde terug,
     en een re-import levert geen vals conflict op.

  3. CATEGORIEBELEID
     Memory 2.0 kent alleen de standaardcategorieën. Een onbekende
     categorie wordt naar 'algemeen' gebracht, zodat een entry nooit
     stilzwijgend onleesbaar kan worden.

Alle tests draaien op tijdelijke bestanden; de echte
memory/memory.json en de echte Obsidian-vault worden nooit
aangeraakt.
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
from memory import memory as mem
from memory import obsidian as ob
from memory import vault_import as vi
from memory import vault_export as vx

import core.brain as brain
import core.ai as ai

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


work = tempfile.mkdtemp(prefix="jarvis_identity_test_")
path = os.path.join(work, "memory.json")
vault = os.path.join(work, "vault")
os.makedirs(vault)

_echte_mem = mem.MEMORY_FILE
_echte_vault = ob.get_vault_path()
_echte_conversation = ai.CONVERSATION_FILE

mem.MEMORY_FILE = path
ob.set_vault_path(vault)

conversation = os.path.join(work, "conversation.json")

with open(conversation, "w", encoding="utf-8") as f:
    json.dump({"history": [], "context": dict(brain.current_context)}, f)

ai.CONVERSATION_FILE = conversation
brain.current_context["pending_choice"] = None

_orig_ctx = dict(brain.current_context)


def reset():
    """Lege het geheugen en de vault, en wis de teller-toestand."""

    mem.clear_memory()
    store.reset_cache()
    brain.current_context["pending_choice"] = None


# =============================================================
# 1: FUZZY KEY MATCHING SCHEIDEN VAN IDENTITEIT
# =============================================================

print("\n===== 1: FUZZY KEY MATCHING =====\n")

reset()

mem.remember("fav band", "Coldplay", category="muziek")
mem.remember("band", "Radiohead", category="muziek")

ok("beide sleutels bestaan naast elkaar",
   set(mem.load_memory()["muziek"]) == {"fav band", "band"})

# --- 1: forget("band") verwijdert NIET "fav band" ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")
mem.remember("band", "Radiohead", category="muziek")

mem.forget("band")

ok("forget('band') verwijdert NIET 'fav band'",
   mem.recall("fav band") == "Coldplay")

ok("forget('band') verwijdert wel 'band'",
   mem.recall("band") is None)

# --- 2: touch_usage("band") wijzigt NIET "fav band" ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")
mem.remember("band", "Radiohead", category="muziek")

mem.reset_touch_usage()
mem.touch_usage("band")

ok("touch_usage('band') telt NIET bij 'fav band'",
   mem.get_entry("fav band").get("usage_count") == 0)

ok("touch_usage('band') telt bij 'band'",
   mem.get_entry("band").get("usage_count") == 1)

# --- 3: remember("band", ...) kan bestaan naast "fav band" ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")

result = mem.remember("band", "Radiohead", category="muziek")

ok("remember('band') meldt geen conflict met 'fav band'",
   result.get("conflict") is False)

ok("remember('band') slaat daadwerkelijk op",
   mem.recall("band") == "Radiohead")

ok("'fav band' blijft onveranderd",
   mem.recall("fav band") == "Coldplay")

# --- 4: _find_existing("band") vindt NIET "fav band" ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")

gevonden_cat, gevonden_key, entry = mem._find_existing("band", "muziek")

ok("_find_existing('band') vindt NIET 'fav band'",
   gevonden_key is None and entry is None)

ok("find_entry('band') vindt NIET 'fav band'",
   mem.find_entry("band", "muziek") == (None, None))

ok("recall('band') geeft niets terug",
   mem.recall("band") is None)

# --- 5: has_conflict("band", ...) conflicteert NIET met "fav band" ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")

conflict, old, category = mem.has_conflict("band", "Radiohead", "muziek")

ok("has_conflict('band') is geen conflict met 'fav band'",
   conflict is False and old is None)

# --- normalisatie blijft bestaan (dit is géén substring) ---

reset()
mem.remember("favoriete_kleur", "blauw", category="voorkeuren")

ok("normalisatie: 'favoriete kleur' vindt 'favoriete_kleur'",
   mem.recall("favoriete kleur") == "blauw")

ok("normalisatie: 'favoriete-kleur' vindt 'favoriete_kleur'",
   mem.recall("favoriete-kleur") == "blauw")

ok("normalisatie: hoofdletters doen niets",
   mem.recall("FAVORIETE_KLEUR") == "blauw")

ok("forget genormaliseerd werkt",
   mem.forget("favoriete kleur") and mem.recall("favoriete_kleur") is None)

# --- 6: de fuzzy resolver stelt 'band' -> 'fav band' voor ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")

oplossing = mem.resolve_existing_key("band", "muziek")

ok("resolver stelt 'fav band' voor",
   oplossing["status"] == "fuzzy"
   and oplossing["candidates"] == ["fav band"])

ok("resolver wijst bij één kandidaat automatisch aan",
   oplossing["key"] == "fav band")

ok("de resolver is geen exacte match",
   oplossing["exact"] is False)

ok("resolver wijst niets af (verandert niets)",
   mem.recall("fav band") == "Coldplay"
   and set(mem.load_memory()["muziek"]) == {"fav band"})

r = mem.resolve_existing_key("fav band", "muziek")

ok("resolver geeft exact terug bij een exacte sleutel",
   r["status"] == "exact" and r["key"] == "fav band" and r["exact"] is True)

r = mem.resolve_existing_key("iets wat er niet is", "muziek")

ok("resolver geeft 'none' zonder kandidaten",
   r["status"] == "none" and r["candidates"] == [])

ok("resolver valt terug op de oorspronkelijke query",
   r["key"] == "iets wat er niet is")

# --- 7: meerdere fuzzy kandidaten -> geen automatische keuze ---

reset()
mem.remember("fav band", "Coldplay", category="muziek")
mem.remember("fav bands", "Radiohead", category="muziek")
mem.remember("mijn band", "Imagine Dragons", category="muziek")

oplossing = mem.resolve_existing_key("band", "muziek")

ok("meerdere kandidaten gevonden", len(oplossing["candidates"]) == 3)

ok("meerdere kandidaten -> GEEN automatische sleutel",
   oplossing["key"] is None)

ok("meerdere kandidaten blijven wel zichtbaar",
   "fav band" in oplossing["candidates"])

# --- conversatielaag: fuzzy vraagt bevestiging, wijzigt niets stilzwijgend ---

reset()
mem.remember("lichtvoorkeur", "warm", category="voorkeuren")

antwoord = brain.try_memory_update("wijzig mijn licht naar koel wit")

ok("'wijzig mijn licht' vraagt welke sleutel bedoeld is",
   antwoord is not None
   and "bedoelde je" in str(antwoord).lower()
   and "lichtvoorkeur" in str(antwoord).lower())

ok("er is een pending_choice klaargezet",
   (brain.current_context.get("pending_choice") or {}).get("kind")
   == "memory_key_confirm")

ok("niets gewijzigd vóór de bevestiging",
   mem.recall("lichtvoorkeur") == "warm")

antwoord = brain.process_command("ja")

ok("'ja' zet de voorgestelde sleutel door",
   antwoord is not None and "koel wit" in str(antwoord))

ok("'ja' werkt de wijziging echt door",
   mem.recall("lichtvoorkeur") == "koel wit")

reset()
mem.remember("lichtvoorkeur", "warm", category="voorkeuren")

brain.try_memory_update("wijzig mijn licht naar koel wit")
brain.process_command("nee")

ok("'nee' laat de oude waarde staan",
   mem.recall("lichtvoorkeur") == "warm")

reset()
mem.remember("fav band", "Coldplay", category="muziek")
mem.remember("mijn band", "Imagine Dragons", category="muziek")

antwoord = brain.try_forget("vergeet band")

ok("'vergeet band' maakt geen automatische keuze",
   antwoord is not None
   and "meerdere" in str(antwoord).lower())

ok("'vergeet band' met meerdere kandidaten zet geen pending_choice",
   brain.current_context.get("pending_choice") is None)

ok("'vergeet band' verwijdert niets",
   mem.recall("fav band") == "Coldplay"
   and mem.recall("mijn band") == "Imagine Dragons")

reset()
mem.remember("fav band", "Coldplay", category="muziek")

antwoord = brain.try_forget("vergeet band")

ok("'vergeet band' vraagt bevestiging bij één kandidaat",
   antwoord is not None
   and "bedoelde je" in str(antwoord).lower()
   and "fav band" in str(antwoord).lower())

ok("'fav band' staat er nog steeds",
   mem.recall("fav band") == "Coldplay")

antwoord = brain.process_command("ja")

ok("'ja' verwijdert dan wel 'fav band'",
   antwoord is not None and "vergeten" in str(antwoord).lower()
   and mem.recall("fav band") is None)

# --- de oude conflict-bevestiging blijft gewoon werken ---

reset()
mem.remember("favoriete_kleur", "groen", category="voorkeuren")

antwoord = brain._remember_or_ask("favoriete_kleur", "rood", "voorkeuren")

ok("tegenstrijdige waarde vraagt nog steeds bevestiging",
   antwoord is not None and "wijzigen" in str(antwoord))

ok("de oude waarde staat er nog",
   mem.recall("favoriete_kleur") == "groen")

brain.process_command("ja")

ok("'ja' op een conflict overschrijft wel",
   mem.recall("favoriete_kleur") == "rood")


# =============================================================
# 2: TYPEGRENS MEMORY <-> OBSIDIAN
# =============================================================

print("\n===== 2: TYPEGRENS MEMORY <-> OBSIDIAN =====\n")

ok("value_type_name(True) == 'bool'", ob.value_type_name(True) == "bool")
ok("value_type_name(42) == 'int'", ob.value_type_name(42) == "int")
ok("value_type_name(1.0) == 'float'", ob.value_type_name(1.0) == "float")
ok("value_type_name('x') == 'str'", ob.value_type_name("x") == "str")
ok("value_type_name(['a']) == 'list'", ob.value_type_name(["a"]) == "list")
ok("value_type_name({'a': 1}) == 'dict'", ob.value_type_name({"a": 1}) == "dict")
ok("value_type_name(None) == 'null'", ob.value_type_name(None) == "null")
ok("value_type_name(1) is geen bool", ob.value_type_name(1) == "int")

ok("_values_equal(True, True)", mem._values_equal(True, True))
ok("_values_equal(False, False)", mem._values_equal(False, False))
ok("_values_equal(42, 42)", mem._values_equal(42, 42))
ok("_values_equal(1.0, 1.0)", mem._values_equal(1.0, 1.0))
ok("_values_equal(['a'], ['a'])", mem._values_equal(["a"], ["a"]))
ok("_values_equal({'a': 1}, {'a': 1})", mem._values_equal({"a": 1}, {"a": 1}))
ok("_values_equal(None, None)", mem._values_equal(None, None))

ok("_values_equal(True, 'ja') is NIET gelijk",
   mem._values_equal(True, "ja") is False)

ok("_values_equal(True, 1) is NIET gelijk",
   mem._values_equal(True, 1) is False)

ok("_values_equal(42, '42') is NIET gelijk",
   mem._values_equal(42, "42") is False)

ok("_values_equal(42, 42.0) IS gelijk", mem._values_equal(42, 42.0) is True)

# --- round-trip: memory -> Obsidian -> memory ---

ROUND_TRIP = [
    ("rt_tekst", "blauw"),
    ("rt_ja", True),
    ("rt_nee", False),
    ("rt_int", 42),
    ("rt_float", 1.5),
    ("rt_lijst", ["a", "b"]),
    ("rt_lijst_nr", [1, 2]),
    ("rt_dict", {"a": 1}),
    ("rt_dict_genest", {"a": [1, 2], "b": "x"}),
    ("rt_none", None),
]

reset()

for sleutel, waarde in ROUND_TRIP:
    mem.remember(sleutel, waarde, category="algemeen")

rapport = vx.compare_memory_to_vault()

ok("elk type komt in het exportrapport voor",
   all(r["action"] == "create"
       for r in rapport["notes"]
       if r["key"] in dict(ROUND_TRIP)))

state = vx.start_export(dry_run=False)

if state.get("paused"):
    state = vx.resolve_paused_export(state, True)

ok("de export is klaar", vx.export_is_finished(state))

for sleutel, waarde in ROUND_TRIP:

    note = ob.note_name_for_memory(sleutel, "algemeen")

    terug = vi.note_to_memory(note)

    label = f"round-trip {sleutel}"

    ok(f"{label}: notitie bestaat", ob.note_exists(note))

    ok(f"{label}: waarde blijft {waarde!r}",
       terug is not None
       and terug["value"] == waarde
       and type(terug["value"]) is type(waarde))

    conflict, _, _ = mem.has_conflict(sleutel, terug["value"], "algemeen")

    ok(f"{label}: geen vals conflict bij herimport", conflict is False)

# --- de leesbare body blijft bestaan ---

note = ob.read_note(ob.note_name_for_memory("rt_ja", "algemeen"))

ok("bool blijft leesbaar als 'ja'", "> ja" in note)

note = ob.read_note(ob.note_name_for_memory("rt_tekst", "algemeen"))

ok("tekst blijft leesbaar", "> blauw" in note)

note = ob.read_note(ob.note_name_for_memory("rt_lijst", "algemeen"))

ok("lijst blijft leesbaar als '- item'", "> - a" in note)

# --- oude notitie zonder value_type blijft importeerbaar ---

hand = "algemeen/handgeschreven.md"

_pad = ob.resolve_note_path(hand)

os.makedirs(os.path.dirname(_pad), exist_ok=True)


def schrijf_notitie(frontmatter, body):
    with open(_pad, "w", encoding="utf-8") as f:
        f.write("---\n" + frontmatter + "---\n\n"
                "# handgeschreven\n\n> " + body + "\n\n## Details\n\n")


schrijf_notitie(
    "title: handgeschreven\ncategory: algemeen\n"
    "memory_key: handgeschreven\ntags: []\ndate: 2026-01-01\n",
    "blauw")

terug = vi.note_to_memory(hand)

ok("oude notitie zonder value_type blijft importeerbaar",
   terug is not None and terug["value"] == "blauw")

ok("oude notitie levert een string",
   type(terug["value"]) is str)

# --- ongeldige value_type valt veilig terug op string ---

schrijf_notitie(
    "title: handgeschreven\ncategory: algemeen\n"
    "memory_key: handgeschreven\ntags: []\nvalue_type: banaan\n"
    "date: 2026-01-01\n",
    "blauw")

terug = vi.note_to_memory(hand)

ok("ongeldige value_type valt terug op string",
   terug is not None
   and terug["value"] == "blauw"
   and type(terug["value"]) is str)

# --- een bewerkte body wint van value_json ---

schrijf_notitie(
    "title: handgeschreven\ncategory: algemeen\n"
    "memory_key: handgeschreven\ntags: []\nvalue_type: int\n"
    'value_json: 32\ndate: 2026-01-01\n',
    "99")

terug = vi.note_to_memory(hand)

ok("een bewerkte body wint van value_json",
   terug is not None
   and terug["value"] == 99
   and type(terug["value"]) is int)

# --- een lege body zonder value_type blijft overgeslagen ---

schrijf_notitie(
    "title: handgeschreven\ncategory: algemeen\n"
    "memory_key: handgeschreven\ntags: []\ndate: 2026-01-01\n",
    "")

ok("lege body zonder value_type wordt overgeslagen",
   vi.note_to_memory(hand) is None)

# --- export -> import -> export is identiek ---

for sleutel, waarde in ROUND_TRIP:

    note = ob.note_name_for_memory(sleutel, "algemeen")

    terug = vi.note_to_memory(note)

    nieuw = dict(mem.get_entry(sleutel, "algemeen"))
    nieuw["value"] = terug["value"]

    eerst = ob.memory_to_note(mem.get_entry(sleutel, "algemeen"),
                              key=sleutel, category="algemeen")

    daarna = ob.memory_to_note(nieuw, key=sleutel, category="algemeen")

    ok(f"idempotentie {sleutel}: dezelfde notitie",
       eerst["content"] == daarna["content"])


# =============================================================
# 3: CATEGORIEBELEID
# =============================================================

print("\n===== 3: CATEGORIEBELEID =====\n")

reset()

mem.remember("lamp_kleur", "warm", category="sfeer")

ok("onbekende categorie wordt niet opgeslagen",
   "sfeer" not in mem.load_memory())

ok("inhoud gaat niet verloren",
   mem.recall("lamp_kleur") == "warm")

ok("het geheugen kent alleen de standaardcategorieën",
   set(mem.load_memory()) == set(mem.DEFAULT_CATEGORIES))

ok("recall() ziet de entry nu wel",
   mem.recall("lamp_kleur") == "warm")

ok("get_entry() ziet de entry nu wel",
   mem.get_entry("lamp_kleur") is not None)

ok("get_all_memory() ziet de entry nu wel",
   mem.get_all_memory().get("lamp_kleur") == "warm")

ok("memory_summary() noemt de entry nu wel",
   "lamp kleur" in mem.memory_summary())

ok("get_relevant_memory() vindt de entry nu wel",
   any(i["key"] == "lamp_kleur"
       for i in mem.get_relevant_memory("hoe zit het met de lamp kleur")))

ok("resolve_conflict() vindt de entry nu wel",
   mem.has_conflict("lamp_kleur", "koel", None)[0] is True)

ok("forget() raakt de entry nu wel",
   mem.forget("lamp_kleur") and mem.recall("lamp_kleur") is None)

ok("een standaardcategorie blijft gewoon werken",
   (mem.remember("gpu_merk", "nvidia", category="pc"),
    mem.get_entry("gpu_merk", "pc") is not None)[1])

ok("_canonical_category(None) blijft None",
   mem._canonical_category(None) is None)

ok("_canonical_category('pc') blijft 'pc'",
   mem._canonical_category("pc") == "pc")

ok("_canonical_category('PC') wordt 'pc'",
   mem._canonical_category("PC") == "pc")

ok("_canonical_category('sfeer') wordt 'algemeen'",
   mem._canonical_category("sfeer") == "algemeen")

ok("_canonical_category('') blijft None",
   mem._canonical_category("") is None)

# --- een al geschreven onbekende categorie wordt bij het laden
#     alsnog naar 'algemeen' gebracht, zonder overschrijven ---

reset()

store.write(path, {
    "voorkeuren": {},
    "pc": {},
    "projecten": {},
    "muziek": {},
    "algemeen": {"al_gekend": "ja"},
    "apparaten": {},
    "sfeer": {
        "lamp_kleur": "warm",
        "al_gekend": "nee",
    },
})

store.reset_cache()

geladen = mem.load_memory()

ok("een oude onbekende categorie verdwijnt",
   "sfeer" not in geladen)

ok("haar entries verhuizen naar 'algemeen'",
   (geladen["algemeen"].get("lamp_kleur") or {}).get("value") == "warm")

ok("een naambotsing overschrijft niet",
   mem.recall("al_gekend") == "ja")

ok("het blijft een geldige memory",
   set(geladen) == set(mem.DEFAULT_CATEGORIES))

reset()

ok("een lege memory is nog steeds geldig",
   set(mem.load_memory()) == set(mem.DEFAULT_CATEGORIES))

# --- Obsidian-export blijft de categorie in de frontmatter bewaren ---

reset()

mem.remember("lamp_kleur", "warm", category="sfeer")

state = vx.start_export(dry_run=False)

if state.get("paused"):
    state = vx.resolve_paused_export(state, True)

terug = vi.note_to_memory(ob.note_name_for_memory("lamp_kleur", "algemeen"))

ok("de notitie houdt de policy-categorie 'algemeen'",
   terug is not None and terug["category"] == "algemeen")

ok("de waarde overleeft de export",
   terug is not None and terug["value"] == "warm")


# =============================================================
# OPRUIMEN
# =============================================================

brain.current_context.update(_orig_ctx)

ai.CONVERSATION_FILE = _echte_conversation
mem.MEMORY_FILE = _echte_mem
ob.set_vault_path(_echte_vault)

store.reset_cache()

shutil.rmtree(work, ignore_errors=True)

print(f"\n{'=' * 60}")
print(f"MEMORY IDENTITEIT/TYPES/CATEGORIEEN: {passed} geslaagd, {failed} gefaald")
print(f"{'=' * 60}")

if failed:
    sys.exit(1)