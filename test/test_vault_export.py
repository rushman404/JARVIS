"""
JARVIS — Memory 2.0 naar Obsidian (Fase 14, Stap 6)
===================================================

Test de exportrichting: memory.json -> Obsidian.

Getest wordt:
  1. lege vault
  2. leeg geheugen
  3. beide leeg
  4. memory zonder notitie -> create
  5. exacte match -> unchanged
  6. drift -> drift
  7. notitie zonder memory_key -> blocked
  8. handmatig toegevoegde tekst -> niet stilzwijgend vernietigen
  9. 'ja' bij drift -> alleen de notitie wordt herschreven
 10. 'nee' bij drift -> niets wijzigen
 11. meerdere drifts achter elkaar, één voor één
 12. dubbele export -> geen tweede write
 13. exception midden in de batch -> veilig stoppen
 14. dry_run=True -> niets schrijven
 15. compare is volledig read-only
 16. memory.json byte-identiek
 17. vault byte-identiek waar geen expliciete export heeft plaatsgevonden
 18. bestaande vault-commando's blijven routeren
 19. pending_choice werkt correct
 20. nieuwe exportcommando's veroorzaken geen woordroof

PLUS: 'ja' mag een handgeschreven notitie NOOIT overschrijven.

Alle tests draaien op een tijdelijke vault, een tijdelijk
geheugenbestand en een tijdelijk gespreksbestand. De echte vault
wordt alleen in sectie 22 gelezen, nooit geschreven.
"""

import sys
import os
import io
import json
import shutil
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from unittest.mock import patch

import core.ai as ai
import core.brain as brain
from memory import obsidian as ob
from memory import memory as mem
from memory import vault_export as vx
from memory import vault_import as vi


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


# =============================================================
# Opzet
# =============================================================

work = tempfile.mkdtemp(prefix="jarvis_vault_export_")

vault_path = os.path.join(work, "Vault")
os.makedirs(vault_path)

memory_file = os.path.join(work, "memory.json")
conversation_file = os.path.join(work, "conversation.json")

_echte_conversation = ai.CONVERSATION_FILE
_echte_memory = mem.MEMORY_FILE
_echte_vault = ob.get_vault_path()

_gesprek_voor = None
_geheugen_voor = None

if os.path.exists(_echte_conversation):
    with open(_echte_conversation, "rb") as file:
        _gesprek_voor = file.read()

if os.path.exists(_echte_memory):
    with open(_echte_memory, "rb") as file:
        _geheugen_voor = file.read()


def _vault_beeld(pad):
    """
    Een volledige vingerafdruk van een map: elk bestand met zijn
    relatieve pad, grootte en inhoud.

    Nodig omdat de echte vault van de gebruiker is en niet vaststaat
    hoeveel notities en instellingen die bevat. De vraag is niet
    "welke bestanden horen er in" maar "is er iets veranderd".
    """

    beeld = {}

    if not os.path.isdir(pad):
        return beeld

    for root, _, bestanden in os.walk(pad):

        for naam in bestanden:

            vol = os.path.join(root, naam)

            try:
                with open(vol, "rb") as file:
                    beeld[os.path.relpath(vol, pad)] = file.read()

            except OSError:
                beeld[os.path.relpath(vol, pad)] = b"<onleesbaar>"

    return beeld


_vault_voor = _vault_beeld(_echte_vault)


def reset():
    """
    Schone teststand: geen geheugen, lege vault, geen openstaande keuze.

    Let op: memory.json is een bestand, dus os.remove() en NIET
    shutil.rmtree() -- die doet stil niets op een bestand.
    """

    ai.current_context["pending_choice"] = None
    ai.conversation_history.clear()

    if os.path.exists(memory_file):
        os.remove(memory_file)

    shutil.rmtree(vault_path, ignore_errors=True)
    os.makedirs(vault_path)

    mem.store.reset_cache(memory_file)
    ob.set_vault_path(vault_path)


def zet_vault(pad):
    """Stel het vault-pad in; None betekent 'bestaat niet'."""

    ob.set_vault_path(pad or os.path.join(work, "bestaat niet"))


def geheugen():
    """De volledige memory.json als dict."""

    return mem.load_memory()


def waarde(key, category="voorkeuren"):
    """De waarde van een memory, of None als die er niet is."""

    return geheugen().get(category, {}).get(key, {}).get("value")


def notitie_inhoud(note_name):
    """De ruwe notitie-inhoud, of None als die niet bestaat."""

    return ob.read_note(note_name)


def note_text(key, value, category="voorkeuren", **extra):
    """De notitie die JARVIS zou schrijven, zonder te schrijven."""

    return ob.memory_to_note({"value": value, **extra}, key=key,
                             category=category)["content"]


def statuses(state):
    """Compacte lijst van (notitie, status)."""

    return [(r["note_name"], r["status"]) for r in state["results"]]


def note_exists(name):
    return ob.note_exists(name)


def file_hash(path):
    import hashlib

    if not os.path.exists(path):
        return None

    with open(path, "rb") as file:
        return hashlib.sha1(file.read()).hexdigest()


def vault_hash():
    """Hash van de volledige vault-inhoud, in een stabiele volgorde."""

    import hashlib

    hasher = hashlib.sha1()
    alles = []

    for current, dirs, files in os.walk(vault_path):
        dirs.sort()
        for name in sorted(files):
            pad = os.path.join(current, name)
            alles.append(os.path.relpath(pad, vault_path).replace(os.sep, "/"))

    for rel in sorted(alles):
        hasher.update(rel.encode("utf-8"))
        with open(os.path.join(vault_path, rel), "rb") as file:
            hasher.update(file.read())

    return hasher.hexdigest()


@patch.object(ai, "CONVERSATION_FILE", conversation_file)
@patch.object(mem, "MEMORY_FILE", memory_file)
def main():
    # =========================================================
    # 1. Lege vault, leeg geheugen
    # =========================================================

    print("\n--- 1. lege vault ---")

    reset()
    zet_vault(None)

    rapport = vx.compare_memory_to_vault()
    ok("analyse bij ontbrekende vault meldt dat",
       rapport["ok"] is False and rapport["reason"] != "")
    ok("analyse bij ontbrekende vault telt 0", rapport["counts"]["total"] == 0)

    state = vx.start_export()
    ok("export bij ontbrekende vault stopt",
       state["stopped"] is True and state["error"] != "")
    ok("export bij ontbrekende vault schrijft niets",
       not any(geheugen().get(c) for c in mem.DEFAULT_CATEGORIES))

    reset()

    rapport = vx.compare_memory_to_vault()
    ok("lege vault geeft een gelukt rapport", rapport["ok"] is True)
    ok("lege vault telt 0 notities", rapport["counts"]["total"] == 0)

    state = vx.start_export(dry_run=False)
    ok("export op lege vault doet niets", state["counts"]["total"] == 0)
    ok("export is klaar", vx.export_is_finished(state) == "done")
    ok("export meldt geen fout", state["error"] is None)

    # =========================================================
    # 2. Leeg geheugen
    # =========================================================

    print("\n--- 2. leeg geheugen ---")

    reset()

    ok("lege memory.json",
       not any(geheugen().get(c) for c in mem.DEFAULT_CATEGORIES))

    rapport = vx.compare_memory_to_vault()
    ok("analyse van leeg geheugen meldt 0", rapport["counts"]["total"] == 0)

    state = vx.start_export(dry_run=False)
    ok("export van leeg geheugen doet niets", state["counts"]["total"] == 0)
    ok("export is klaar", vx.export_is_finished(state) == "done")
    ok("de vault is nog steeds leeg", ob.list_notes() == [])

    # =========================================================
    # 3. Beide leeg
    # =========================================================

    print("\n--- 3. beide leeg ---")

    reset()

    ok("compare is gelukt en telt 0",
       vx.compare_memory_to_vault()["counts"]["total"] == 0)

    state = vx.start_export()
    ok("dry_run export is klaar", vx.export_is_finished(state) == "done")
    ok("geen results", state["results"] == [])
    ok("geen fout", state["error"] is None)
    ok("er is niets geschreven", ob.list_notes() == [])
    ok("memory.json is nog steeds leeg",
       not any(geheugen().get(c) for c in mem.DEFAULT_CATEGORIES))

    # =========================================================
    # 4. Memory zonder notitie -> create
    # =========================================================

    print("\n--- 4. create ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)

    rapport = vx.compare_memory_to_vault()
    ok("analyse ziet de nieuwe memory", rapport["counts"]["create"] == 1)
    ok("analyse telt 1 notitie", rapport["counts"]["total"] == 1)

    state = vx.start_export(dry_run=False)
    ok("export is klaar", vx.export_is_finished(state) == "done")
    ok("de notitie is geschreven", state["counts"]["written"] == 1)
    ok("de notitie bestaat nu op schijf", note_exists("voorkeuren/favoriete-kleur.md"))

    inhoud = notitie_inhoud("voorkeuren/favoriete-kleur.md")
    ok("de notitie begint met frontmatter", inhoud.startswith("---"))
    ok("de notitie bevat de memory_key", "memory_key: favoriete kleur" in inhoud)
    ok("de notitie bevat de waarde", "> blauw" in inhoud)
    ok("de notitie bevat de sleutelregel",
       "- Sleutel: `favoriete kleur`" in inhoud)

    # =========================================================
    # 5. Exacte match -> unchanged
    # =========================================================

    print("\n--- 5. unchanged ---")

    state = vx.start_export(dry_run=False)
    ok("tweede export schrijft niets", state["counts"]["written"] == 0)
    ok("de notitie wordt als onveranderd gezien",
       state["counts"]["unchanged"] == 1)
    ok("export is klaar", vx.export_is_finished(state) == "done")

    rapport = vx.compare_memory_to_vault()
    ok("analyse ziet een exacte match", rapport["counts"]["unchanged"] == 1)

    ok("memory.json is nog steeds blauw", waarde("favoriete kleur") == "blauw")

    # De 'date:' in de frontmatter verandert elke dag; een oudere
    # notitie mag daardoor NIET als drift gezien worden.
    oude = notitie_inhoud("voorkeuren/favoriete-kleur.md").replace(
        "date: " + _vandaag(), "date: 2000-01-01")
    ob.write_note("voorkeuren/favoriete-kleur.md", oude)

    rapport = vx.compare_memory_to_vault()
    ok("een oudere date: telt NIET als drift",
       rapport["counts"]["unchanged"] == 1 and rapport["counts"]["drift"] == 0)

    # =========================================================
    # 6. Drift
    # =========================================================

    print("\n--- 6. drift ---")

    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "groen"))

    rapport = vx.compare_memory_to_vault()
    ok("analyse ziet het verschil", rapport["counts"]["drift"] == 1)
    ok("het verschil hoort bij de juiste memory",
       rapport["drift"][0]["key"] == "favoriete kleur")
    ok("het verschil noemt de geheugenwaarde",
       rapport["drift"][0]["value"] == "blauw")

    state = vx.start_export(dry_run=False)
    ok("export pauzeert bij drift", state["paused"] is True)
    ok("export is nog niet klaar", vx.export_is_finished(state) == "paused")
    ok("er staat een confirm klaar", isinstance(state["confirm"], dict))
    ok("confirm noemt de geheugenwaarde",
       state["confirm"]["memory_value"] == "blauw")
    ok("confirm noemt de vault-waarde",
       state["confirm"]["vault_value"] == "groen")
    ok("GEEN NOTITIE IS NOG AANGEROOKT",
       "groen" in notitie_inhoud("voorkeuren/favoriete-kleur.md"))
    ok("GEEN MEMORY IS NOG AANGEROOKT", waarde("favoriete kleur") == "blauw")

    # =========================================================
    # 7. Notitie zonder memory_key -> blocked
    # =========================================================

    print("\n--- 7. blocked: geen memory_key ---")

    ob.write_note("voorkeuren/favoriete-kleur.md",
                  "Gewoon een handgeschreven tekst.\n")

    rapport = vx.compare_memory_to_vault()
    ok("de notitie is geblokkeerd", rapport["counts"]["blocked"] == 1)
    ok("de reden noemt het ontbrekende memory_key",
       "memory_key" in rapport["blocked"][0]["reason"])

    state = vx.start_export(dry_run=False)
    ok("export schrijft hem niet", state["counts"]["written"] == 0)
    ok("export is klaar zonder te wachten",
       vx.export_is_finished(state) == "done")
    ok("de handgeschreven tekst is bewaard",
       "Gewoon een handgeschreven tekst." in notitie_inhoud(
           "voorkeuren/favoriete-kleur.md"))

    # =========================================================
    # 8. Handmatig toegevoegde tekst
    # =========================================================

    print("\n--- 8. eigen tekst wordt niet vernietigd ---")

    mem.remember("nog een", "ja", category="algemeen", force=True)

    state = vx.start_export(dry_run=False)
    ok("de nieuwe memory is geschreven",
       state["counts"]["written"] == 1)
    ok("notitie bestaat", note_exists("algemeen/nog-een.md"))

    # Voeg eigen tekst toe aan die JARVIS-notitie.
    ob.append_note("algemeen/nog-een.md",
                   "\n## Mijn eigen notitie\n\nDit is van mij.\n")

    rapport = vx.compare_memory_to_vault()
    ok("eigen tekst maakt de notitie geblokkeerd",
       rapport["counts"]["blocked"] >= 1)
    ok("de reden noemt de eigen tekst",
       any("niet van JARVIS" in r["reason"] for r in rapport["blocked"]))

    state = vx.start_export(dry_run=False)
    ok("eigen tekst blijft staan",
       "Dit is van mij." in notitie_inhoud("algemeen/nog-een.md"))
    ok("de export is niet op zoek gegaan naar bevestiging",
       state["paused"] is False)

    # =========================================================
    # 9. 'ja' bij drift -> alleen de notitie
    # =========================================================

    print("\n--- 9. ja bij drift ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)

    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "rood"))

    geheugen_voor = open(memory_file, "rb").read()

    state = vx.start_export(dry_run=False)
    ok("export pauzeert", state["paused"] is True)
    ok("de status is waiting",
       any(s == "waiting" for s in [r["status"] for r in state["results"]]))

    state = vx.resolve_paused_export(state, overwrite=True)
    ok("export is klaar na de beslissing",
       vx.export_is_finished(state) == "done")
    ok("de notitie is herschreven", state["counts"]["overwritten"] == 1)
    ok("de notitie bevat de geheugenwaarde",
       "blauw" in notitie_inhoud("voorkeuren/favoriete-kleur.md"))
    ok("de oude waarde is niet meer in de notitie",
       "rood" not in notitie_inhoud("voorkeuren/favoriete-kleur.md"))
    ok("MEMORY.JSON IS BYTE-IDENTIEK",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("de geheugenwaarde is nog steeds blauw",
       waarde("favoriete kleur") == "blauw")

    # =========================================================
    # 10. 'nee' bij drift -> niets wijzigen
    # =========================================================

    print("\n--- 10. nee bij drift ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)

    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "geel"))

    notitie_voor = notitie_inhoud("voorkeuren/favoriete-kleur.md")
    geheugen_voor = open(memory_file, "rb").read()
    vault_voor = vault_hash()

    state = vx.start_export(dry_run=False)
    state = vx.resolve_paused_export(state, overwrite=False)

    ok("export is klaar", vx.export_is_finished(state) == "done")
    ok("de notitie is bewaard na 'nee'", state["counts"]["kept"] == 1)
    ok("NOTITIE IS NIET AANGEROOKT",
       notitie_inhoud("voorkeuren/favoriete-kleur.md") == notitie_voor)
    ok("memory.json is NIET aangeraakt",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("de hele vault is NIET aangeraakt", vault_hash() == vault_voor)
    ok("de geheugenwaarde is nog steeds blauw",
       waarde("favoriete kleur") == "blauw")

    # =========================================================
    # 11. Meerdere drifts, één voor één
    # =========================================================

    print("\n--- 11. meerdere drifts ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    mem.remember("favoriete band", "Radiohead", category="muziek", force=True)
    vx.start_export(dry_run=False)

    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "groen"))
    ob.write_note("muziek/favoriete-band.md",
                  note_text("favoriete band", "Nirvana", "muziek"))

    geheugen_voor = open(memory_file, "rb").read()

    state = vx.start_export(dry_run=False)
    ok("de eerste drift stopt de export", state["paused"] is True)

    geheugen_midden = open(memory_file, "rb").read()
    ok("tussen de twee drifts is memory.json nog steeds gelijk",
       geheugen_midden == geheugen_voor)

    # De batch stopt per keer bij de EERSTE drift; beslis dus zo
    # vaak tot er niets meer wacht.
    beslissingen = 0

    while vx.export_is_finished(state) == "paused" and beslissingen < 10:
        beslissingen += 1
        state = vx.resolve_paused_export(state, overwrite=True)

    ok("de export is na twee beslissingen klaar",
       vx.export_is_finished(state) == "done")
    ok("er zijn twee bevestigingen gevraagd", beslissingen == 2)
    ok("twee notities zijn beoordeeld",
       sum(1 for r in state["results"] if r["status"] == "overwritten") == 2)
    ok("MEMORY IS NOOIT AANGEROOKT",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("beide notities zijn naar de geheugenwaarde gezet",
       "blauw" in notitie_inhoud("voorkeuren/favoriete-kleur.md")
       and "Radiohead" in notitie_inhoud("muziek/favoriete-band.md"))

    # =========================================================
    # 12. Dubbele export -> geen tweede write
    # =========================================================

    print("\n--- 12. dubbele export ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    state = vx.start_export(dry_run=False)
    ok("eerste export schrijft", state["counts"]["written"] == 1)

    vault_na_eerste = vault_hash()

    tweede = vx.start_export(dry_run=False)
    ok("tweede export schrijft niets", tweede["counts"]["written"] == 0)
    ok("tweede export meldt onveranderd",
       tweede["counts"]["unchanged"] == 1)
    ok("de vault is identiek na de tweede run", vault_hash() == vault_na_eerste)

    # Ook een expliciete dubbele notitie in de queue.
    notitie = "voorkeuren/favoriete-kleur.md"
    handmatig = {
        "dry_run": False, "results": [], "queue": [notitie, notitie],
        "processed": [], "confirm": None, "paused": False,
        "done": False, "stopped": False, "error": None,
        "counts": {},
        "_plans": {notitie: {
            "note_name": notitie, "key": "favoriete kleur",
            "category": "voorkeuren", "value": "blauw",
            "content": note_text("favoriete kleur", "blauw"),
            "action": "unchanged", "reason": "",
        }},
    }
    handmatig = vx._advance_export(handmatig)
    ok("een dubbele notitie krijgt status 'duplicate'",
       any(r["status"] == "duplicate" for r in handmatig["results"]))
    ok("de batch is klaar", handmatig["done"] is True)
    ok("de notitie is maar één keer verwerkt",
       sum(1 for r in handmatig["results"] if r["note_name"] == notitie) == 2)

    # =========================================================
    # 13. Exception midden in de batch
    # =========================================================

    print("\n--- 13. exception in de batch ---")

    reset()
    mem.remember("aaa eerste", "een", category="voorkeuren", force=True)
    mem.remember("mmm tweede", "twee", category="voorkeuren", force=True)
    mem.remember("zzz derde", "drie", category="voorkeuren", force=True)

    origineel = vx._schrijf_notitie

    def kapot(note_name, inhoud, sleutel=None):
        if "mmm-tweede" in note_name:
            raise RuntimeError("gesimuleerde schijffout")
        return origineel(note_name, inhoud, sleutel)

    vx._schrijf_notitie = kapot
    try:
        state = vx.start_export(dry_run=False)
    finally:
        vx._schrijf_notitie = origineel

    ok("de export stopt bij de fout", state["stopped"] is True)
    ok("de fout is vastgelegd", "RuntimeError" in (state["error"] or ""))
    ok("status is error", vx.export_is_finished(state) == "error")
    ok("de mislukte notitie kreeg status 'error'",
       any(r["status"] == "error" for r in state["results"]))
    ok("de notitie is NIET als verwerkt gemarkeerd",
       "voorkeuren/mmm-tweede.md" not in state["processed"])
    ok("de resterende wachtrij is bewaard",
       "voorkeuren/zzz-derde.md" in state["queue"])
    ok("de notitie van vóór de fout WEL geschreven is",
       note_exists("voorkeuren/aaa-eerste.md"))
    ok("de notitie ná de fout NIET geschreven is",
       not note_exists("voorkeuren/zzz-derde.md"))
    ok("geen enkele notitie hangt zonder status",
       all(r["status"] for r in state["results"]))

    # =========================================================
    # 14. dry_run = standaard
    # =========================================================

    print("\n--- 14. dry_run ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)

    vault_voor = vault_hash()
    geheugen_voor = open(memory_file, "rb").read()

    state = vx.start_export()
    ok("dry_run is de standaard", state["dry_run"] is True)
    ok("dry_run meldt een plan", state["counts"]["planned"] == 1)
    ok("dry_run schrijft niets", ob.list_notes() == [])
    ok("dry_run maakt geen map aan", vault_hash() == vault_voor)
    ok("dry_run laat memory.json met rust",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("dry_run is klaar", vx.export_is_finished(state) == "done")

    # =========================================================
    # 15. Compare is volledig read-only
    # =========================================================

    print("\n--- 15. read-only analyse ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)
    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "groen"))

    vault_voor = vault_hash()
    geheugen_voor = open(memory_file, "rb").read()
    mtime_voor = os.path.getmtime(memory_file)
    notities_voor = sorted(ob.list_notes())

    rapport = vx.compare_memory_to_vault()

    ok("analyse meldt het verschil", rapport["counts"]["drift"] == 1)
    ok("memory.json is byte-identiek na de analyse",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("memory.json mtime is onveranderd",
       os.path.getmtime(memory_file) == mtime_voor)
    ok("de vault is byte-identiek na de analyse", vault_hash() == vault_voor)
    ok("de lijst notities is gelijk gebleven",
       sorted(ob.list_notes()) == notities_voor)
    ok("het verschil is NIET opgelost", waarde("favoriete kleur") == "blauw")
    ok("er is geen conflict-vlag gezet",
       geheugen()["voorkeuren"]["favoriete kleur"].get("conflict") is not True)

    # Ook een analyse op een lege map mag niets doen.
    vx.compare_memory_to_vault()
    ok("dubbele analyse laat memory.json met rust",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("dubbele analyse laat de vault met rust", vault_hash() == vault_voor)

    # =========================================================
    # 16. memory.json byte-identiek na de hele exportflow
    # =========================================================

    print("\n--- 16. memory.json blijft intact ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    mem.remember("favoriete band", "Radiohead", category="muziek", force=True)
    mem.remember("heeft gpu", True, category="pc", force=True)

    geheugen_voor = open(memory_file, "rb").read()

    vx.start_export(dry_run=False)
    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "groen"))
    ob.write_note("muziek/favoriete-band.md",
                  note_text("favoriete band", "Nirvana", "muziek"))

    state = vx.start_export(dry_run=False)
    vx.resolve_paused_export(state, overwrite=True)

    ok("memory.json is na de volledige exportflow byte-identiek",
       open(memory_file, "rb").read() == geheugen_voor)

    # =========================================================
    # 17. vault blijft intact waar geen export plaatsvond
    # =========================================================

    print("\n--- 17. vault onveranderd waar niets is uitgevoerd ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)

    # Maak een aparte notitie die niet aan een memory gekoppeld is.
    ob.write_note("losse notitie.md", "Dit is een losse notitie.")

    vault_voor = vault_hash()
    geheugen_voor = open(memory_file, "rb").read()

    state = vx.start_export(dry_run=False)

    ok("de losse notitie wordt niet aangeraakt",
       "Dit is een losse notitie." in notitie_inhoud("losse notitie.md"))
    ok("de losse notitie is niet weggeschreven", note_exists("losse notitie.md"))
    ok("memory.json is onveranderd",
       open(memory_file, "rb").read() == geheugen_voor)
    ok("de vault is onveranderd", vault_hash() == vault_voor)

    # =========================================================
    # 18. Bestaande vault-commando's blijven routeren
    # =========================================================

    print("\n--- 18. bestaande commando's ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)

    for commando, verwacht in [
        ("wat heb ik in mijn vault staan", "try_vault_info"),
        ("importeer alles uit mijn vault", "try_vault_batch"),
        ("zet voorkeuren/favoriete-kleur in mijn geheugen", "try_vault_import"),
        ("vergelijk mijn vault met mijn geheugen", "try_vault_compare"),
    ]:
        antwoord = brain.process_command(commando)
        ok(f"'{commando}' geeft nog steeds antwoord",
           isinstance(antwoord, str) and antwoord)
        ok(f"'{commando}' is geen export",
           "het verschil bij" not in antwoord.lower())

    # De import-zin mag het geheugen nog steeds mogen aanraken.
    antwoord = brain.process_command("zet voorkeuren/favoriete-kleur "
                                     "in mijn geheugen")
    ok("de import-vraag loopt nog steeds",
       isinstance(antwoord, str) and antwoord)

    # =========================================================
    # 19. pending_choice werkt correct
    # =========================================================

    print("\n--- 19. pending_choice ---")

    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)

    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "violet"))

    geheugen_voor = open(memory_file, "rb").read()

    antwoord = brain.process_command("exporteer mijn geheugen naar de vault")
    ok("de exportvraag bevestiging geeft",
       isinstance(antwoord, str) and "Zal ik de notitie bijwerken" in antwoord)
    ok("de vraag noemt beide waarden",
       "blauw" in antwoord and "violet" in antwoord)

    pending = ai.current_context.get("pending_choice")
    ok("er staat een pending_choice klaar", isinstance(pending, dict))
    ok("de pending_choice is een memory_update-vorm",
       pending["kind"] == "memory_update")
    ok("de pending_choice bevat de export-state",
       isinstance(pending.get("vault_export"), dict))
    ok("de export-state is JSON-geschikt",
       _is_json(pending["vault_export"]))
    ok("de export-state bevat de openstaande drift",
       pending["vault_export"]["paused"] is True)
    ok("de state bewaart GEEN volledige notitie-inhoud",
       not _bevat_inhoud(pending["vault_export"]))
    ok("MEMORY IS NOG NIET AANGEROOKT",
       open(memory_file, "rb").read() == geheugen_voor)

    antwoord = brain.process_command("nee")
    ok("'nee' geeft een antwoord", isinstance(antwoord, str) and antwoord)
    ok("'nee' wist de pending_choice",
       ai.current_context.get("pending_choice") is None)
    ok("'nee' laat de notitie exact staan",
       "violet" in notitie_inhoud("voorkeuren/favoriete-kleur.md"))
    ok("'nee' laat memory.json met rust",
       open(memory_file, "rb").read() == geheugen_voor)

    # =========================================================
    # 20. Woordroof
    # =========================================================

    print("\n--- 20. woordroof ---")

    # Zinnen zonder exportwoord mogen de export niet aanschakelen.
    for commando in [
        "open discord",
        "wat is het weer",
        "zet de radio aan",
        "vergelijk twee dingen",
        "importeer alles uit mijn vault",
        "wat heb ik in mijn vault staan",
    ]:
        ok(f"'{commando}' triggert GEEN export",
           brain.try_vault_export(commando) is None)

    # De export-vormen mogen NIET door de import opgepakt worden.
    for commando in [
        "exporteer mijn geheugen naar de vault",
        "zet mijn geheugen in obsidian",
        "migreer mijn geheugen naar Obsidian",
        "vergelijk mijn geheugen met de vault",
    ]:
        ok(f"'{commando}' gaat NIET naar de import",
           brain.try_vault_import(commando) is None)

    # En de import-vormen mogen niet door de export opgepakt worden.
    ok("import-zinnen triggert GEEN export",
       brain.try_vault_export("zet voorkeuren/licht in mijn geheugen") is None)

    # Richting-beslissing: beide vergelijk-zinnen werken, in beide
    # richtingen.
    reset()
    mem.remember("favoriete kleur", "blauw", category="voorkeuren", force=True)
    vx.start_export(dry_run=False)
    ob.write_note("voorkeuren/favoriete-kleur.md",
                  note_text("favoriete kleur", "rood"))

    uitvoer_export = brain.process_command("vergelijk mijn geheugen met de vault")
    ok("de export-vergelijking noemt de richting correct",
       "geheugen zegt 'blauw'" in uitvoer_export)

    uitvoer_import = brain.process_command("vergelijk mijn vault met mijn geheugen")
    ok("de import-vergelijking noemt de richting correct",
       "je vault zegt 'rood'" in uitvoer_import)

    # =========================================================
    # 21. Een handgeschreven notitie overleeft 'ja'
    # =========================================================

    print("\n--- 21. ja mag eigen tekst niet vernietigen ---")

    reset()
    mem.remember("nog een", "ja", category="algemeen", force=True)
    vx.start_export(dry_run=False)

    ob.append_note("algemeen/nog-een.md",
                   "\n## Mijn eigen notitie\n\nDit is van mij.\n")

    eigen_voor = notitie_inhoud("algemeen/nog-een.md")
    geheugen_voor = open(memory_file, "rb").read()

    state = vx.start_export(dry_run=False)
    ok("de export wacht niet, want er is geen drift",
       state["paused"] is False)
    ok("de eigen tekst staat er nog", notitie_inhoud("algemeen/nog-een.md")
       == eigen_voor)
    ok("memory.json is onveranderd",
       open(memory_file, "rb").read() == geheugen_voor)

    # Zelfs als iemand met de hand een 'ja' afdwingt voor een
    # geblokkeerde notitie, mag er niets gebeuren.
    plan = vx.compare_memory_to_vault()
    blocked = [r for r in plan["blocked"] if r["key"] == "nog een"]
    ok("de notitie staat als blocked in het rapport", len(blocked) == 1)

    origineel = vx._schrijf_notitie
    schrijfaanroepen = []

    def telt(note_name, inhoud, sleutel=None):
        schrijfaanroepen.append(note_name)
        return origineel(note_name, inhoud, sleutel)

    vx._schrijf_notitie = telt
    try:
        handmatig = {
            "dry_run": False,
            # Zo zou _advance_export() de resultaten hebben achtergelaten
            # vlak vóór het pauzeren.
            "results": [{"note_name": "algemeen/nog-een.md", "key": "nog een",
                         "category": "algemeen", "value": "ja",
                         "status": "waiting", "label": "",
                         "reason": "wacht op bevestiging"}],
            "queue": ["algemeen/nog-een.md"],
            "processed": [], "paused": True,
            "confirm": {"note_name": "algemeen/nog-een.md", "key": "nog een",
                        "category": "algemeen", "memory_value": "ja",
                        "vault_value": "ja"},
            "done": False, "stopped": False, "error": None, "counts": {},
            "_plans": {"algemeen/nog-een.md": {
                "note_name": "algemeen/nog-een.md", "key": "nog een",
                "category": "algemeen", "value": "ja",
                "content": note_text("nog een", "ja", "algemeen"),
                "action": "blocked", "reason": "de notitie bevat tekst",
            }},
        }
        handmatig = vx.resolve_paused_export(handmatig, overwrite=True)
    finally:
        vx._schrijf_notitie = origineel

    ok("een handmatige 'ja' op een blocked notitie roept de "
       "schrijffunctie NIET aan", schrijfaanroepen == [])
    ok("een handmatige 'ja' op een blocked notitie schrijft NIETS",
       notitie_inhoud("algemeen/nog-een.md") == eigen_voor)
    ok("de status is blocked", any(r["status"] == "blocked"
                                   for r in handmatig["results"]))
    ok("memory.json is nog steeds onveranderd",
       open(memory_file, "rb").read() == geheugen_voor)

    # =========================================================
    # 22. De echte bestanden mogen onveranderd zijn
    # =========================================================

    print("\n--- 22. echte bestanden ---")

    if _geheugen_voor is not None:
        with open(_echte_memory, "rb") as file:
            ok("echte memory.json is onveranderd", file.read() == _geheugen_voor)

    if _gesprek_voor is not None:
        with open(_echte_conversation, "rb") as file:
            ok("echte conversation.json is onveranderd",
               file.read() == _gesprek_voor)

    ok("de echte vault is byte voor byte onveranderd",
       _vault_beeld(_echte_vault) == _vault_voor)

    ok("de standaard-vault staat nog goed",
       ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, "JARVIS Memory"))

    # =========================================================
    # 23. De export roept geen Memory 2.0-schrijffuncties aan
    # =========================================================

    print("\n--- 23. geen koppeling naar Memory 2.0 ---")

    import inspect
    import ast

    bron = inspect.getsource(vx)

    boom = ast.parse(bron)
    aanroepen = set()

    for node in ast.walk(boom):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                aanroepen.add(node.func.attr)

    for niet_toegestaan in ("remember", "update_memory", "resolve_conflict"):
        ok(f"vault_export roept {niet_toegestaan}() NIET aan",
           niet_toegestaan not in aanroepen)

    ok("vault_export gebruikt geen netwerk",
       "requests" not in bron and "urllib" not in bron
       and "socket" not in bron)
    ok("vault_export importeert geen nieuwe externe pakketten",
       not any(name.startswith(("requests", "urllib3", "yaml", "pyyaml"))
               for name in _imports(boom)))

# De echte vault is niet veranderd door alle tests heen.
    ok("de echte vault is byte voor byte onveranderd",
       _vault_beeld(_echte_vault) == _vault_voor)


def _vandaag():
    from datetime import date

    return date.today().isoformat()


def _imports(boom):
    import ast

    namen = set()

    for node in ast.walk(boom):
        if isinstance(node, ast.Import):
            for alias in node.names:
                namen.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            namen.add((node.module or "").split(".")[0])

    return namen


def _is_json(ding):
    try:
        json.dumps(ding)
        return True
    except (TypeError, ValueError):
        return False


def _bevat_inhoud(boom, diepte=0):
    """True als er ergens in de state een notitie-tekst staat."""

    if diepte > 8:
        return False

    if isinstance(boom, str):
        return "## Details" in boom or "memory_key:" in boom

    if isinstance(boom, dict):
        return any(_bevat_inhoud(v, diepte + 1) for v in boom.values())

    if isinstance(boom, (list, tuple)):
        return any(_bevat_inhoud(v, diepte + 1) for v in boom)

    return False


main()

ai.CONVERSATION_FILE = _echte_conversation
ob.set_vault_path(_echte_vault)
mem.store.reset_cache()

shutil.rmtree(work, ignore_errors=True)

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)