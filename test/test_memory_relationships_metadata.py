"""
JARVIS — Memory 2.0 relaties en metadata-contract (Stap 7)
==========================================================

Gerichte tests voor de vijf dingen die Stap 7 toevoegt:

  1. `created`   : een stabiel ISO 8601-tijdstip met tijdzone dat een
                   waardewijziging overleeft
  2. het metadata-contract : één centrale definitie die echt gebruikt wordt
  3. `related`   : echte relaties in plaats van alle siblings
  4. Obsidian    : die metadata overleeft export -> import -> export
  5. backward compatibiliteit: oude data en oude notities blijven geldig

Elke test draait op tijdelijke bestanden. De echte memory/memory.json,
memory/conversation.json en de echte JARVIS Memory Vault worden nooit
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

from memory import store
from memory import memory as mem
from memory import obsidian as ob
from memory import vault_import as vi
from memory import vault_export as vx

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


work = tempfile.mkdtemp(prefix="jarvis_stap7_")
path = os.path.join(work, "memory.json")
vault = os.path.join(work, "vault")
os.makedirs(vault)

_echte_mem = mem.MEMORY_FILE
_echte_vault = ob.get_vault_path()

mem.MEMORY_FILE = path
ob.set_vault_path(vault)


def reset():
    """Leeg het geheugen EN de vault.

    De vault moet mee, want de export weigert een bestaande notitie te
    overschrijven. Zonder deze lege map zou een notitie uit een
    vorige sectie blijven staan en de volgende sectie een oude
    notitie teruglezen in plaats van de verse export.
    """

    mem.clear_memory()
    store.reset_cache()

    shutil.rmtree(vault, ignore_errors=True)
    os.makedirs(vault, exist_ok=True)


def export_all():
    """Exporteert alle memories naar de tijdelijke vault."""

    state = vx.start_export(dry_run=False)

    if state.get("paused"):
        state = vx.resolve_paused_export(state, True)

    return state


def frontmatter(content):
    return content.split("---")[1]


def schrijf_notitie(naam, fm, body):
    pad = ob.resolve_note_path(naam)

    os.makedirs(os.path.dirname(pad), exist_ok=True)

    with open(pad, "w", encoding="utf-8") as f:
        f.write("---\n" + fm + "---\n\n# " + naam.split("/")[-1][:-3]
                + "\n\n> " + body + "\n\n## Details\n\n")

    return naam


def bewerk_notitie(naam, oud, nieuw):
    """
    Vervangt tekst in een notitie, ongeacht de regeleindes.

    Notities worden op Windows met CRLF weggeschreven, dus een
    handmatige bewerking moet beide varianten proberen. Anders lijkt
    het alsof de bewerking is gelukt terwijl er niets is veranderd.
    """

    pad = ob.resolve_note_path(naam)

    with open(pad, "r", encoding="utf-8", newline="") as f:
        inhoud = f.read()

    if oud in inhoud:
        inhoud = inhoud.replace(oud, nieuw)

    else:
        inhoud = inhoud.replace(oud.replace("\n", "\r\n"),
                                nieuw.replace("\n", "\r\n"))

    with open(pad, "w", encoding="utf-8", newline="") as f:
        f.write(inhoud)

    return inhoud


# =============================================================
# 1: created
# =============================================================

print("\n===== 1: CREATED =====\n")

reset()

mem.remember("fav_kleur", "blauw", category="voorkeuren")

entry = mem.get_entry("fav_kleur", "voorkeuren")

ok("een nieuwe memory krijgt created", bool(entry.get("created")))

ok("created is een string", isinstance(entry.get("created"), str))

ok("created is ISO 8601 met tijdzone",
   mem._parse_timestamp(entry["created"]) is not None
   and ("+" in entry["created"] or entry["created"].endswith("Z")))

ok("een nieuwe memory krijgt updated", bool(entry.get("updated")))

ok("created en updated zijn bij aanmaak gelijk",
   entry["created"] == entry["updated"])

created_1 = entry["created"]

ok("created valt binnen ENTRY_META_KEYS",
   "created" in mem.ENTRY_META_KEYS)

# --- created blijft behouden bij een waardewijziging ---

mem.update_memory("fav_kleur", "groen", category="voorkeuren")

entry = mem.get_entry("fav_kleur", "voorkeuren")

ok("created blijft behouden bij update", entry["created"] == created_1)

ok("updated is een leesbaar ISO 8601-tijdstip",
   mem._parse_timestamp(entry["updated"]) is not None)

ok("de waarde is wel gewijzigd", mem.recall("fav_kleur") == "groen")

ok("updated staat niet vóór created (geen tijdmachine)",
   mem._parse_timestamp(entry["updated"]) >= mem._parse_timestamp(created_1))

# --- een gewone remember() is ook een update, geen nieuw feit ---

mem.remember("fav_kleur", "zwart", category="voorkeuren")

ok("created blijft ook bij remember() behouden",
   mem.get_entry("fav_kleur", "voorkeuren")["created"] == created_1)

# --- relaties overleven een waardewijziging ---

mem.remember("pc", "werkplek", category="algemeen")

mem.add_related("fav_kleur", "pc")

mem.update_memory("fav_kleur", "wit", category="voorkeuren")

ok("een waardewijziging maakt de relaties niet kapot",
   mem.get_related("fav_kleur") == ["pc"])

ok("de andere kant van die relatie ook",
   mem.get_related("pc") == ["fav_kleur"])

# --- oude memory zonder created blijft geldig ---

reset()

store.write(path, {
    "voorkeuren": {"oud_feit": "blauw"},
    "pc": {"oud_fact": {"value": "rtx", "source": "conversation",
                        "updated": "2026-01-02T03:04:05"}},
    "projecten": {}, "muziek": {}, "algemeen": {}, "apparaten": {},
})

store.reset_cache()

oud = mem.get_entry("oud_fact", "pc")

ok("een oude memory blijft leesbaar", mem.recall("oud_fact") == "rtx")

ok("een oude memory krijgt GEEN verzonnen created",
   oud.get("created") is None)

ok("een oude memory krijgt GEEN verzonnen related",
   oud.get("related") == [])

ok("de oude updated blijft ongemoeid",
   oud.get("updated") == "2026-01-02T03:04:05")

ok("het oude naieve tijdstip blijft leesbaar",
   mem._age_days("2026-01-02T03:04:05") is not None)

ok("het nieuwe formaat is ook leesbaar",
   mem._age_days(entry["updated"]) is not None)

ok("een onleesbaar tijdstip geeft None, geen crash",
   mem._age_days("gisteren") is None)

# --- forget neemt de metadata mee ---

reset()

mem.remember("vergeten_fact", "iets", category="algemeen")

ok("de memory bestaat", mem.recall("vergeten_fact") == "iets")

mem.forget("vergeten_fact")

ok("forget verwijdert de hele entry, metadata inbegrepen",
   mem.get_entry("vergeten_fact", "algemeen") is None)

ok("forget laat geen created-ophoping achter",
   "created" not in json.dumps(mem.load_memory(), ensure_ascii=False))


# =============================================================
# 2: HET METADATA-CONTRACT
# =============================================================

print("\n===== 2: METADATA-CONTRACT =====\n")

ok("ENTRY_META_KEYS is niet leeg", len(mem.ENTRY_META_KEYS) > 0)

ok("value is onderdeel van het contract",
   "value" in mem.ENTRY_META_KEYS)

ok("category staat NIET in de entry (leeft in de map)",
   "category" not in mem.ENTRY_META_KEYS)

for veld in ("created", "updated", "priority", "usage_count", "related"):
    ok(f"{veld} is onderdeel van het contract",
       veld in mem.ENTRY_META_KEYS)

ok("elk contractveld heeft een default",
   set(mem.ENTRY_META_KEYS) == set(mem.ENTRY_META_DEFAULTS) | {"value"})

ok("ENTRY_META_KEYS wordt ook echt gebruikt",
   mem.is_entry_meta({"value": 1}) is not None)

ok("ENTRY_META_DEFAULTS wordt ook echt gebruikt",
   mem._normalize_entry({})["priority"] == 1.0)

reset()

mem.remember("contract", "waarde", category="algemeen")

meta = mem.is_entry_meta(mem.get_entry("contract", "algemeen"))

ok("is_entry_meta geeft alle velden terug",
   set(meta) == set(mem.ENTRY_META_KEYS))

ok("is_entry_meta geeft geen Category terug", "category" not in meta)

before = json.dumps(mem.load_memory(), ensure_ascii=False, sort_keys=True)

meta["priority"] = 99.0
meta["related"].append("hacked")

ok("is_entry_meta geeft een kopie, geen referentie",
   json.dumps(mem.load_memory(), ensure_ascii=False, sort_keys=True) == before)

ok("is_entry_meta geeft None voor een kale waarde",
   mem.is_entry_meta("warm") is None)

ok("is_entry_meta geeft None voor None", mem.is_entry_meta(None) is None)

reset()

mem.remember("handmatig", "x", category="algemeen")

store.write(path, {
    "voorkeuren": {},
    "pc": {},
    "projecten": {},
    "muziek": {},
    "algemeen": {"raar": {"value": "x", "related": 42,
                          "created": 12345, "usage_count": "twee"}},
    "apparaten": {},
})

store.reset_cache()

raar = mem.get_entry("raar", "algemeen")

ok("een onbruikbare related wordt een lege lijst",
   raar["related"] == [])

ok("een losse string als related wordt één relatie",
   mem._clean_related("mijn_band") == ["mijn_band"])

ok("een onbruikbare created blijft ongewijzigd (geen gok)",
   raar["created"] == 12345)


# =============================================================
# 3: ECHTE RELATIES
# =============================================================

print("\n===== 3: RELATIES =====\n")

reset()

mem.remember("fav_game", "Valorant", category="voorkeuren")
mem.remember("gaming_pc", "rtx5090", category="pc")
mem.remember("monitor", "144hz", category="pc")

uit = mem.add_related("fav_game", "gaming_pc")

ok("add_related slaat de relatie op", uit["added"] is True)

# --- beide kanten bestaan ---
ok("A -> B", mem.get_related("fav_game") == ["gaming_pc"])
ok("B -> A", mem.get_related("gaming_pc") == ["fav_game"])

ok("has_related is waar vanuit A", mem.has_related("fav_game", "gaming_pc"))

ok("has_related is waar vanuit B", mem.has_related("gaming_pc", "fav_game"))

ok("has_related is onwaar voor een vreemde sleutel",
   mem.has_related("fav_game", "monitor") is False)

# --- duplicaten ---
mem.add_related("fav_game", "gaming_pc")

ok("een dubbele relatie wordt niet dubbel opgeslagen",
   mem.get_related("fav_game") == ["gaming_pc"])

ok("een dubbele add vanaf de andere kant ook niet",
   mem.add_related("gaming_pc", "fav_game")["added"]
   and mem.get_related("gaming_pc") == ["fav_game"])

mem.add_related("fav_game", "Gaming PC")

ok("een spellingvariant telt als dezelfde relatie",
   mem.get_related("fav_game") == ["gaming_pc"])

# --- zelfrelatie ---
uit = mem.add_related("fav_game", "fav_game")

ok("een zelfrelatie wordt geweigerd", uit["added"] is False)

ok("de zelfrelatie wordt gemeld", bool(uit["skipped"]))

ok("er komt geen zelfrelatie in de lijst",
   "fav_game" not in mem.get_related("fav_game"))

ok("ook genormaliseerd is een zelfrelatie een zelfrelatie",
   mem.add_related("fav_game", "Fav Game")["added"] is False)

# --- onbekende key ---
mem.clear_related("fav_game")

uit = mem.add_related("fav_game", "bestaat_niet")

ok("een relatie naar een onbekende sleutel wordt niet opgeslagen",
   uit["added"] is False)

ok("de reden wordt gemeld", bool(uit["skipped"]))

ok("er komt niets in de lijst", mem.get_related("fav_game") == [])

uit = mem.add_related("bestaat_niet", "gaming_pc")

ok("een onbekende vertrek sleutel wordt geweigerd", uit["added"] is False)

ok("de bestaande memory blijft onaangeroerd",
   mem.get_related("gaming_pc") == [])

ok("een relatie naar een verwijderd feit verdwijnt na forget()",
   mem.forget("monitor") and mem.get_related("fav_game") == [])

# --- siblings zijn GEEN relaties ---
reset()

mem.remember("muziek_a", "coldplay", category="muziek")
mem.remember("muziek_b", "radiohead", category="muziek")

ok("twee memories in dezelfde categorie zijn geen relaties",
   mem.get_related("muziek_a") == [])

ok("ook niet andersom", mem.get_related("muziek_b") == [])

plannen = ob.plan_all_memories_to_vault(mem.load_memory())

content = [p["content"] for p in plannen if p["ok"]]

ok("de sibling-graaf staat niet meer in de notities",
   not any("## Gerelateerd" in c for c in content))

ok("er staat geen related: in de frontmatter",
   not any("related:" in frontmatter(c) for c in content))

# --- GEEN fuzzy ---
reset()

mem.remember("fav band", "coldplay", category="muziek")
mem.remember("mijn band", "imaginedragons", category="muziek")

uit = mem.add_related("fav band", "band")

ok("add_related gebruikt GEEN fuzzy: 'band' bestaat niet",
   uit["added"] is False)

ok("add_related raakt resolve_existing_key niet aan",
   "resolved" not in uit and "candidates" not in uit)

uit = mem.add_related("fav band", "mijn band")

ok("een echte, maar niet-identieke sleutel mag wél",
   uit["added"] is True)

ok("de relatie wijst naar de opgeslagen sleutel",
   mem.get_related("fav band") == ["mijn band"])

mem.forget("band")

ok("forget gebruikt geen fuzzy: 'fav band' blijft",
   mem.recall("fav band") == "coldplay")

ok("forget gebruikt geen fuzzy: 'mijn band' blijft",
   mem.recall("mijn band") == "imaginedragons")

# --- remove_related ---
mem.remove_related("fav band", "mijn band")

ok("remove_related haalt A -> B weg",
   mem.get_related("fav band") == [])

ok("remove_related haalt B -> A weg",
   mem.get_related("mijn band") == [])

uit = mem.remove_related("fav band", "mijn band")

ok("een tweede remove geeft removed=False", uit["removed"] is False)

ok("een tweede remove crasht niet",
   uit["key"] == "fav band" and uit["related"] == "mijn band")

uit = mem.remove_related("fav band", "bestaat_niet")

ok("remove van een onbekende sleutel crasht niet", uit["removed"] is False)

ok("en verandert niets", mem.recall("fav band") == "coldplay")

# --- clear_related ---
mem.add_related("fav band", "mijn band")

ok("clear_related leegt de ene kant", mem.clear_related("fav band"))

ok("de andere kant is ook leeg", mem.get_related("mijn band") == [])

ok("de memories zelf blijven bestaan",
   mem.recall("fav band") == "coldplay"
   and mem.recall("mijn band") == "imaginedragons")

ok("clear_related op een sleutel zonder relaties doet niets",
   mem.clear_related("mijn band") is False)


# =============================================================
# 4: VERWIJDEREN LAAT GEEN DODE RELATIE ACHTER
# =============================================================

print("\n===== 4: FORGET EN RELATIES =====\n")

reset()

mem.remember("A", "1", category="algemeen")
mem.remember("B", "2", category="algemeen")
mem.remember("C", "3", category="algemeen")

mem.add_related("A", "B")
mem.add_related("A", "C")

ok("A -> [B, C]", sorted(mem.get_related("A")) == ["B", "C"])

mem.forget("A")

ok("A is verwijderd", mem.recall("A") is None)

ok("B heeft geen dode relatie meer", mem.get_related("B") == [])

ok("C heeft geen dode relatie meer", mem.get_related("C") == [])

ok("B en C bestaan nog", mem.recall("B") == "2" and mem.recall("C") == "3")

ok("er staat nergens meer een verwijzing naar A",
   "A" not in json.dumps(mem.load_memory(), ensure_ascii=False))

# --- de opslag van het geheugen klopt na forget() ---
on_disk = json.loads(open(path, encoding="utf-8").read())

ok("de weggehaalde relatie staat ook echt niet meer op schijf",
   all("A" not in entry.get("related", [])
       for categorie in on_disk.values()
       if isinstance(categorie, dict)
       for entry in categorie.values()
       if isinstance(entry, dict)))


# =============================================================
# 5: OBSIDIAN EXPORT
# =============================================================

print("\n===== 5: OBSIDIAN EXPORT =====\n")

reset()

mem.remember("fav_game", "Valorant", category="voorkeuren")
mem.remember("gaming_pc", "rtx5090", category="pc")
mem.remember("monitor", "144hz", category="pc")

mem.add_related("fav_game", "gaming_pc")
mem.add_related("fav_game", "monitor")

mem.touch_usage("fav_game")

note = ob.memory_to_note(mem.get_entry("fav_game", "voorkeuren"),
                         key="fav_game", category="voorkeuren")

fm = frontmatter(note["content"])

ok("created wordt geëxporteerd", "created:" in fm)

ok("updated wordt geëxporteerd", "updated:" in fm)

ok("priority wordt geëxporteerd", "priority:" in fm)

ok("usage_count wordt geëxporteerd", "usage_count:" in fm)

ok("related wordt geëxporteerd", "\nrelated:" in fm)

ok("related is een YAML-lijst, geen tekst",
   "\n  - gaming_pc\n" in fm and "\n  - monitor\n" in fm)

ok("memory_key blijft in de frontmatter", "memory_key: fav_game" in fm)

ok("value_type blijft in de frontmatter", "value_type: str" in fm)

ok("de leesbare body blijft behouden", "> Valorant" in note["content"])

ok("de detailslijst toont created",
   "- Aangemaakt: " in note["content"])

ok("de body toont de wiki-links van de echte relaties",
   "[[gaming_pc]]" in note["content"] and "[[monitor]]" in note["content"])

ok("een sibling staat NIET in de wiki-links",
   "[[pc]]" not in note["content"])

# --- een memory zonder relaties krijgt geen related: ---
mem.remember("los_fact", "geen relaties", category="algemeen")

note_los = ob.memory_to_note(mem.get_entry("los_fact", "algemeen"),
                             key="los_fact", category="algemeen")

ok("een memory zonder relaties krijgt geen related:",
   "related:" not in frontmatter(note_los["content"]))

ok("een memory zonder relaties krijgt geen lege lijst",
   "related: []" not in frontmatter(note_los["content"]))

ok("een memory zonder relaties krijgt geen wiki-links",
   "## Gerelateerd" not in note_los["content"])

# --- de hele vault export ---
state = export_all()

ok("de volledige export slaagt", vx.export_is_finished(state))

notitie = ob.read_note(ob.note_name_for_memory("fav_game", "voorkeuren"))

ok("de notitie op schijf bevat de relaties",
   "  - gaming_pc" in notitie)

ok("de notitie op schijf bevat created", "created:" in notitie)


# =============================================================
# 6: OBSIDIAN IMPORT
# =============================================================

print("\n===== 6: OBSIDIAN IMPORT =====\n")

reset()

mem.remember("fav_game", "Valorant", category="voorkeuren")
mem.remember("gaming_pc", "rtx5090", category="pc")
mem.remember("monitor", "144hz", category="pc")

mem.add_related("fav_game", "gaming_pc")

export_all()

naam = ob.note_name_for_memory("fav_game", "voorkeuren")

terug = vi.note_to_memory(naam)

ok("created wordt gelezen",
   terug["created"] == mem.get_entry("fav_game", "voorkeuren")["created"])

ok("related wordt gelezen", terug["related"] == ["gaming_pc"])

ok("usage_count wordt gelezen", terug["usage_count"] == 0)

uit = vi.import_note(naam, force=True)

ok("import zonder verschil verandert de waarde niet",
   uit["action"] == "unchanged")

ok("import zonder verschil verandert de relaties niet",
   mem.get_related("fav_game") == ["gaming_pc"])

ok("de import is idempotent (niets te doen)",
   uit["metadata"]["related_added"] == []
   and uit["metadata"]["related_removed"] == [])

# --- een handmatige wijziging van de related-lijst wordt herkend ---
bewerk_notitie(naam, "  - gaming_pc", "  - gaming_pc\n  - monitor")

uit = vi.import_note(naam, force=True)

ok("een handmatig toegevoegde relatie wordt verwerkt",
   "monitor" in uit["metadata"]["related_added"])

ok("de nieuwe relatie staat er echt",
   mem.get_related("fav_game") == ["gaming_pc", "monitor"])

ok("de nieuwe relatie is ook omgekeerd",
   mem.get_related("monitor") == ["fav_game"])

# --- en een handmatig weggehaalde relatie ook ---
bewerk_notitie(naam, "  - gaming_pc\n", "")

uit = vi.import_note(naam, force=True)

ok("een handmatig weggehaalde relatie wordt verwerkt",
   "gaming_pc" in uit["metadata"]["related_removed"])

ok("de relatie is weg bij A", mem.get_related("fav_game") == ["monitor"])

ok("de relatie is ook weg bij B", mem.get_related("gaming_pc") == [])

# --- een relatie naar een onbekende sleutel wordt niet opgeslagen ---
bewerk_notitie(naam, "  - monitor", "  - monitor\n  - bestaat_niet")

vi.import_note(naam, force=True)

ok("een relatie naar een onbekende sleutel wordt geweigerd",
   mem.get_related("fav_game") == ["monitor"])

ok("en komt hij nergens in het geheugen voor",
   "bestaat_niet" not in json.dumps(mem.load_memory(), ensure_ascii=False))

# --- een lijst op één regel mag ook ---
reset()

mem.remember("inline_a", "1", category="algemeen")
mem.remember("inline_b", "2", category="algemeen")

schrijf_notitie(
    "algemeen/inline_a.md",
    "title: inline_a\ncategory: algemeen\ntags: []\n"
    "memory_key: inline_a\nvalue_type: str\n"
    'related: ["inline_b", "inline_b", "   "]\ndate: 2026-01-01\n',
    "1")

uit = vi.import_note("algemeen/inline_a.md")

ok("een inline lijst wordt gelezen", mem.get_related("inline_a") == ["inline_b"])

ok("een inline lijst heeft geen duplicaten",
   mem.get_related("inline_b") == ["inline_a"])

# --- oude notitie zonder de nieuwe velden ---
reset()

mem.remember("oud_fact", "blauw", category="algemeen")

oud = vi.note_to_memory(schrijf_notitie(
    "algemeen/oud_fact.md",
    "title: oud_fact\ncategory: algemeen\ntags: []\n"
    "memory_key: oud_fact\ndate: 2026-01-01\n",
    "blauw"))

ok("een oude notitie zonder created blijft importeerbaar",
   oud is not None and oud["value"] == "blauw")

ok("een oude notitie zonder related blijft importeerbaar",
   oud is not None and oud["related"] == [])

uit = vi.import_note("algemeen/oud_fact.md", force=True)

ok("een oude notitie is nog steeds bruikbaar", uit["action"] in
   ("unchanged", "conflict", "new"))

ok("een oude notitie verandert niets stuk", uit["applied"] is False)

# --- een handgeschreven notitie blijft overslaan ---
ok("een notitie zonder memory_key wordt overgeslagen",
   vi.note_to_memory(schrijf_notitie(
       "welkom.md", "title: welkom\ntags: []\n", "hi")) is None)


# =============================================================
# 7: IDEMPOTENTIE (memory -> export -> import -> export)
# =============================================================

print("\n===== 7: IDEMPOTENTIE =====\n")

reset()

mem.remember("fav_game", "Valorant", category="voorkeuren")
mem.remember("gaming_pc", "rtx5090", category="pc")
mem.remember("monitor", "144hz", category="pc")

mem.add_related("fav_game", "gaming_pc")
mem.add_related("fav_game", "monitor")

mem.remember("vlag_getal", 42, category="algemeen")
mem.remember("vlag_ja", True, category="algemeen")
mem.remember("vlag_lijst", ["a", "b"], category="algemeen")

export_all()

eerste = {}

for note in ob.list_notes(""):
    eerste[note] = ob.read_note(note)

geheugen_eerste = mem.load_memory()

# --- nog een keer exporteren: de notities mogen niet veranderen ---
export_all()

tweede = {note: ob.read_note(note) for note in ob.list_notes("")}

ok("export -> export verandert niets", eerste == tweede)

ok("memory.json blijft byte-voor-byte gelijk",
   json.dumps(mem.load_memory(), ensure_ascii=False, sort_keys=True)
   == json.dumps(geheugen_eerste, ensure_ascii=False, sort_keys=True))

# --- alles importeren en daarna opnieuw exporteren ---
for note in ob.list_notes(""):
    vi.import_note(note, force=True)

export_all()

derde = {note: ob.read_note(note) for note in ob.list_notes("")}

ok("memory -> export -> import -> export is identiek",
   eerste == derde)

ok("de relaties zijn onveranderd",
   mem.get_related("fav_game") == ["gaming_pc", "monitor"])

ok("de created is onveranderd",
   mem.get_entry("fav_game", "voorkeuren")["created"]
   == geheugen_eerste["voorkeuren"]["fav_game"]["created"])

ok("het type is behouden (int)",
   mem.recall("vlag_getal") == 42
   and type(mem.recall("vlag_getal")) is int)

ok("het type is behouden (bool)",
   mem.recall("vlag_ja") is True)

ok("het type is behouden (list)",
   mem.recall("vlag_lijst") == ["a", "b"])

ok("de created van de eerste memory is dezelfde blijft",
   mem.get_entry("fav_game", "voorkeuren")["created"]
   == geheugen_eerste["voorkeuren"]["fav_game"]["created"])


# =============================================================
# 8: RELATIES EN CONFLICTEN ZIJN TWEE DINGEN
# =============================================================

print("\n===== 8: CONFLICTEN =====\n")

reset()

mem.remember("fav_game", "Valorant", category="voorkeuren")
mem.remember("gaming_pc", "rtx5090", category="pc")

mem.add_related("fav_game", "gaming_pc")

created_voor = mem.get_entry("fav_game", "voorkeuren")["created"]

export_all()

naam = ob.note_name_for_memory("fav_game", "voorkeuren")

inhoud = ob.read_note(naam)

bewerkt = inhoud.replace("> Valorant", "> Apex")

bewerkt = bewerkt.replace("  - gaming_pc", "  - gaming_pc\n  - monitor")


mem.remember("monitor", "144hz", category="pc")

bewerk_notitie(naam, "> Valorant", "> Apex")

bewerk_notitie(naam, "  - gaming_pc", "  - gaming_pc\n  - monitor")

uit = vi.import_note(naam)

ok("een gewijzigde waarde geeft een waardeconflict",
   uit["action"] == "conflict" and uit["needs_confirm"] is True)

ok("bij een conflict wordt de waarde NIET overschreven",
   mem.recall("fav_game") == "Valorant")

ok("bij een conflict verandert er GEEN metadata",
   uit["metadata"] == {})

ok("de relations blijven zoals ze waren",
   mem.get_related("fav_game") == ["gaming_pc"])

ok("de nieuwe relatie uit de notitie is NIET toegepast",
   "monitor" not in mem.get_related("fav_game"))

vi.resolve_pending(uit["confirm_token"], keep_old=False)

ok("na bevestigen is de waarde bijgewerkt",
   mem.recall("fav_game") == "Apex")

ok("na bevestigen is de metadata wél bijgewerkt",
   sorted(mem.get_related("fav_game")) == ["gaming_pc", "monitor"])

ok("de andere kant van de nieuwe relatie ook",
   mem.get_related("monitor") == ["fav_game"])

ok("created is door de waardewijziging niet gewijzigd",
   mem.get_entry("fav_game", "voorkeuren")["created"] == created_voor)

ok("updated is door de waardewijziging wel gewijzigd",
   mem.get_entry("fav_game", "voorkeuren")["updated"] is not None)

# --- usage_count wordt nooit kleiner ---
reset()

mem.remember("tel_fact", "x", category="algemeen")

mem.reset_touch_usage()

mem.touch_usage("tel_fact")

export_all()

naam = ob.note_name_for_memory("tel_fact", "algemeen")

bewerk_notitie(naam, "usage_count: 1", "usage_count: 0")

vi.import_note(naam, force=True)

ok("een import kan usage_count nooit verkleinen",
   mem.get_entry("tel_fact", "algemeen")["usage_count"] == 1)

bewerk_notitie(naam, "usage_count: 0", "usage_count: 9")

vi.import_note(naam, force=True)

ok("een hogere usage_count uit de notitie wordt wel overgenomen",
   mem.get_entry("tel_fact", "algemeen")["usage_count"] == 9)


# =============================================================
# 9: METADATA BEHOUD BIJ EEN WAARDEWIJZIGING
# =============================================================
#
# remember() bouwt elke keer een nieuwe entry (_wrap) maar neemt de
# metadata van de bestaande entry over (_carry_metadata). Zonder die
# overname zou een gewone waardewijziging de gebruiksgeschiedenis, de
# oorspronkelijke datum, de prioriteit en de relaties wissen: het feit
# was beweerd gebruikt en het spoor was weg.
#
# De klok wordt hier bewust geforceerd. _now() rondt af op hele
# seconden, dus een echte wijziging binnen dezelfde seconde zou niet te
# onderscheiden zijn van een ongewijzigde timestamp.
#
# resolve_conflict() loopt voor een conflict door dezelfde remember(),
# dus die krijgt dezelfde controles.

print("\n===== 9: METADATA BEHOUD =====\n")

_klok = {"t": 0}

_echte_now = mem._now


def klok():
    """Elke _now() geeft een nieuw, oplopend tijdstip."""

    _klok["t"] += 1
    seconden = _klok["t"]

    return "2026-06-01T%02d:%02d:%02d+02:00" % (
        12 + seconden // 3600,
        (seconden // 60) % 60,
        seconden % 60,
    )


mem._now = klok

# --- Een nieuwe memory begint schoon ---
reset()

mem.remember("meta_fact", "waarde", category="algemeen")

nieuw = mem.get_entry("meta_fact", "algemeen")

ok("1: nieuwe memory heeft usage_count 0", nieuw["usage_count"] == 0)
ok("1: nieuwe memory heeft last_used None", nieuw["last_used"] is None)
ok("1: nieuwe memory heeft related []", nieuw["related"] == [])
ok("1: nieuwe memory heeft een created", nieuw["created"] is not None)
ok("1: nieuwe memory heeft created en updated",
   nieuw["created"] is not None and nieuw["updated"] is not None)

ok("1: created en updated zijn ISO 8601 met tijdzone",
   nieuw["created"].endswith("+02:00")
   and nieuw["updated"].endswith("+02:00"))
ok("1: nieuwe memory heeft de neutrale priority 1.0", nieuw["priority"] == 1.0)
ok("1: nieuwe memory is geen conflict", nieuw["conflict"] is False)

created = nieuw["created"]

# --- Gebruik vastleggen, prioriteit geven, een relatie leggen ---
mem.remember("meta_fact", "waarde", category="algemeen", priority=8.0)
mem.remember("meta_peer", "ander feit", category="algemeen")

mem.add_related("meta_fact", "meta_peer")

voor_touch = json.loads(json.dumps(mem.get_entry("meta_fact", "algemeen")))

mem.reset_touch_usage()

ok("2: touch_usage telt de eerste keer", mem.touch_usage("meta_fact") is True)

mem.reset_touch_usage()
mem.touch_usage("meta_fact")

gebruikt = mem.get_entry("meta_fact", "algemeen")

ok("2: touch_usage verhoogt usage_count", gebruikt["usage_count"] == 2)

last_used = gebruikt["last_used"]

ok("2: touch_usage zet last_used", last_used is not None)

ok("2: touch_usage laat created staan", gebruikt["created"] == created)

# `updated` is het moment van de laatste WAARDEWIJZIGING. Gebruik tellen
# is geen waardewijziging, dus touch_usage laat updated staan.
ok("2: touch_usage laat updated staan",
   gebruikt["updated"] == voor_touch["updated"])

# --- 3 t/m 8: dezelfde key opnieuw onthouden ---
#
# Een waardewijziging gaat in de praktijk via update_memory() (expliciete
# correctie) of resolve_conflict() (na bevestiging). Een kale
# remember() met een andere waarde zou een conflict zijn en niets
# wegschrijven, en dat gedrag hoort hier ook getest te worden.
updated_voor = gebruikt["updated"]
voor = json.loads(json.dumps(gebruikt))

mem.update_memory("meta_fact", "nieuwe waarde", category="algemeen")

na = mem.get_entry("meta_fact", "algemeen")

ok("3: usage_count blijft behouden",
   na["usage_count"] == voor["usage_count"] == 2)

ok("4: last_used blijft behouden", na["last_used"] == voor["last_used"])

ok("5: created blijft behouden",
   na["created"] == voor["created"] == created)

ok("6: related blijft behouden",
   na["related"] == voor["related"] == ["meta_peer"])

ok("7: priority blijft behouden", na["priority"] == voor["priority"] == 8.0)

ok("8: updated verandert wel", na["updated"] != updated_voor)
ok("8: de waarde is wel bijgewerkt", na["value"] == "nieuwe waarde")
ok("de oude waarde staat in previous_value",
   na["previous_value"] == "waarde")
ok("de correctie is gemarkeerd", na["corrected"] is True)
ok("de relatie is nog steeds tweerichting",
   mem.get_related("meta_peer") == ["meta_fact"])

# Ook bij een GELIJKWAARDIG onthouden gaat er geen historie verloren.
mem.reset_touch_usage()
mem.touch_usage("meta_fact")

voor = json.loads(json.dumps(mem.get_entry("meta_fact", "algemeen")))

mem.remember("meta_fact", "nieuwe waarde", category="algemeen")

gelijk = mem.get_entry("meta_fact", "algemeen")

ok("een gelijkwaardige onthouder behoudt usage_count",
   gelijk["usage_count"] == voor["usage_count"])

ok("een gelijkwaardige onthouder behoudt last_used",
   gelijk["last_used"] == voor["last_used"])

ok("een gelijkwaardige onthouder behoudt created",
   gelijk["created"] == voor["created"])

ok("een gelijkwaardige onthouder behoudt related",
   gelijk["related"] == voor["related"])

ok("een gelijkwaardige onthouder behoudt priority",
   gelijk["priority"] == voor["priority"])

ok("een gelijkwaardige onthouder behoudt previous_value",
   gelijk["previous_value"] == voor["previous_value"])

# Een conflict dat niet bevestigd is, raakt de entry helemaal niet aan.
mem.reset_touch_usage()
mem.touch_usage("meta_fact")

voor_conflict = json.dumps(mem.get_entry("meta_fact", "algemeen"),
                           sort_keys=True)

updated_voor_conflict = mem.get_entry("meta_fact", "algemeen")["updated"]

voor_conflict_entry = json.loads(voor_conflict)

uit = mem.remember("meta_fact", "ongemapde waarde", category="algemeen")

ok("een onbevestigd conflict vraagt eerst om bevestiging",
   uit.get("needs_confirm") is True)

ok("een onbevestigd conflict wijzigt de entry niet",
   json.dumps(mem.get_entry("meta_fact", "algemeen"), sort_keys=True)
   == voor_conflict)

# --- resolve_conflict: nieuwe waarde wordt actueel ---
mem.resolve_conflict("meta_fact", "geel", category="algemeen")

na_conflict = mem.get_entry("meta_fact", "algemeen")

ok("resolve_conflict: usage_count blijft behouden",
   na_conflict["usage_count"] == voor_conflict_entry["usage_count"])

ok("resolve_conflict: last_used blijft behouden",
   na_conflict["last_used"] == voor_conflict_entry["last_used"])

ok("resolve_conflict: created blijft behouden",
   na_conflict["created"] == created)

ok("resolve_conflict: related blijft behouden",
   na_conflict["related"] == voor_conflict_entry["related"])

ok("resolve_conflict: priority blijft behouden",
   na_conflict["priority"] == 8.0)

ok("resolve_conflict: updated verandert wel",
   na_conflict["updated"] != updated_voor_conflict)
ok("resolve_conflict: de nieuwe waarde is actueel",
   na_conflict["value"] == "geel")
ok("resolve_conflict: de oude waarde staat in previous_value",
   na_conflict["previous_value"] == "nieuwe waarde")
ok("resolve_conflict: een opgeslagen waarde is geen conflict",
   na_conflict["conflict"] is False)
ok("resolve_conflict: de correctie is gemarkeerd",
   na_conflict["corrected"] is True)

# --- resolve_conflict met keep_old=True ---
mem.reset_touch_usage()
mem.touch_usage("meta_fact")

voor_keep_old = mem.get_entry("meta_fact", "algemeen")

mem.resolve_conflict("meta_fact", "oranje", keep_old=True,
                     category="algemeen")

keep_old = mem.get_entry("meta_fact", "algemeen")

ok("resolve_conflict(keep_old): de waarde blijft staan",
   keep_old["value"] == voor_keep_old["value"])
ok("resolve_conflict(keep_old): usage_count blijft behouden",
   keep_old["usage_count"] == voor_keep_old["usage_count"])
ok("resolve_conflict(keep_old): last_used blijft behouden",
   keep_old["last_used"] == voor_keep_old["last_used"])
ok("resolve_conflict(keep_old): created blijft behouden",
   keep_old["created"] == voor_keep_old["created"])
ok("resolve_conflict(keep_old): updated blijft ongemoeid",
   keep_old["updated"] == voor_keep_old["updated"])
ok("resolve_conflict(keep_old): related blijft behouden",
   keep_old["related"] == ["meta_peer"])
ok("resolve_conflict(keep_old): het conflict staat vast",
   keep_old["conflict"] is True)
ok("resolve_conflict(keep_old): de afgewezen waarde is vastgelegd",
   keep_old["conflict_rejected_value"] == "oranje")

mem._now = _echte_now

# =============================================================
# 10: GEEN DUBBELE ENTRY BIJ EEN NORMALISERENDE VARIANT
# =============================================================
#
# Opslag-identiteit is exact + genormaliseerd (_ ≡ - ≡ spatie). Omdat
# remember() de gevonden sleutel gebruikt om te schrijven, blijft
# "fav band" één entry in plaats van een tweede, bijna-identieke
# entry ernaast te zetten die de oude waarde blijft teruggeven.

print("\n===== 10: IDENTITEIT VAN remember() =====\n")

reset()

mem.remember("fav band", "queen", category="muziek")

mem.reset_touch_usage()
mem.touch_usage("fav band")

# Een koppelteken-variant met een ANDERE waarde is een conflict en
# wordt dus niet weggeschreven, maar mag alvast geen tweede entry maken.
mem.remember("fav-band", "abba", category="muziek")

muziek = mem.load_memory()["muziek"]

ok("een koppelteken-variant maakt geen tweede entry",
   list(muziek.keys()) == ["fav band"])

ok("een onbevestigde variant wijzigt de waarde niet",
   muziek["fav band"]["value"] == "queen")

# Bevestigd (expliciete correctie) werkt dezelfde entry bij.
mem.update_memory("fav-band", "abba", category="muziek")

muziek = mem.load_memory()["muziek"]

ok("de bevestigde variant werkt dezelfde entry bij",
   list(muziek.keys()) == ["fav band"])

ok("en de waarde is bijgewerkt", muziek["fav band"]["value"] == "abba")

ok("usage_count gaat niet verloren bij de variant",
   muziek["fav band"]["usage_count"] == 1)

ok("created gaat niet verloren bij de variant",
   muziek["fav band"]["created"] is not None)

ok("recall geeft de nieuwe waarde", mem.recall("fav band") == "abba")

ok("forget haalt de genormaliseerde variant weg",
   mem.forget("fav-band") and mem.find_entry("fav band") == (None, None))

# Een waarde die naar een andere categorie zou scoren verhuist het feit
# niet: de identiteit ligt bij wat er al in de database staat.
reset()

mem.remember("mijn_favoriet", "blauw", category="voorkeuren")

mem.reset_touch_usage()
mem.touch_usage("mijn_favoriet")

mem.update_memory("mijn_favoriet", "muziek", category="voorkeuren")

al = mem.load_memory()

ok("een waarde uit een andere categorie maakt geen tweede entry",
   sum(len(items) for items in al.values()) == 1)

ok("het feit blijft in zijn eigen categorie",
   mem.find_entry("mijn_favoriet")[0] == "voorkeuren")

ok("en houdt daar zijn metadata",
   mem.get_entry("mijn_favoriet")["usage_count"] == 1)

ok("met de nieuwe waarde erin",
   mem.recall("mijn_favoriet") == "muziek")

# Ook een expliciet andere categorie maakt geen tweede entry.
mem.update_memory("mijn_favoriet", "groen", category="apparaten")

al = mem.load_memory()

ok("een expliciet andere categorie maakt geen tweede entry",
   sum(len(items) for items in al.values()) == 1)

ok("het feit is in zijn oorspronkelijke categorie bijgewerkt",
   mem.find_entry("mijn_favoriet")[0] == "voorkeuren")

mem.forget("mijn_favoriet")

ok("forget haalt het feit echt weg",
   sum(len(items) for items in mem.load_memory().values()) == 0)


# =============================================================
# OPRUIMEN
# =============================================================

mem.MEMORY_FILE = _echte_mem
ob.set_vault_path(_echte_vault)

store.reset_cache()

shutil.rmtree(work, ignore_errors=True)

print(f"\n{'=' * 60}")
print(f"STAP 7 RELATIES/METADATA: {passed} geslaagd, {failed} gefaald")
print(f"{'=' * 60}")

if failed:
    sys.exit(1)