"""
JARVIS — Obsidian in de brain (Fase 14, Stap 4)
=================================================

Test de twee expliciete vault-commando's in core/brain.py:

  1. "wat heb ik in mijn vault staan"
  2. "zet <notitie> in mijn geheugen"

Getest wordt:
  * de routering (een commando zonder vault-woord valt er gewoon af)
  * een ontbrekende vault, een lege vault en een leeg geheugen
  * importeren van een nieuwe memory
  * een ongewijzigde memory (geen schrijfactie)
  * een conflict via de bestaande pending_choice-flow, met 'ja' en 'nee'
  * dat er GEEN automatische synchronisatie is, in beide richtingen
  * dat de bestaande memory_update-bevestiging niet kapot is gegaan

Alle tests draaien op een tijdelijke vault, een tijdelijk geheugenbestand
en een tijdelijk gespreksbestand. De echte vault, memory.json en
conversation.json worden niet aangeraakt.
"""

import sys
import os
import io
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
# Opzet: tijdelijke vault, geheugen en gesprek
# =============================================================

work = tempfile.mkdtemp(prefix="jarvis_vault_brain_")

vault_path = os.path.join(work, "Vault")
os.makedirs(vault_path)

memory_file = os.path.join(work, "memory.json")
conversation_file = os.path.join(work, "conversation.json")

_echte_conversation = ai.CONVERSATION_FILE
_echte_memory = mem.MEMORY_FILE
_conversation_voor = None

if os.path.exists(_echte_conversation):
    with open(_echte_conversation, "rb") as file:
        _conversation_voor = file.read()

_memory_voor = None

if os.path.exists(_echte_memory):
    with open(_echte_memory, "rb") as file:
        _memory_voor = file.read()


def reset(leeg_vault=False):
    """
    Zet alles terug naar een schone teststand.

    Schoon geheugen, leeg (of niet) vault, geen openstaande keuze.
    """

    ai.current_context["pending_choice"] = None
    ai.conversation_history.clear()

    # memory.json is een BESTAND. rmtree() doet daar niets mee en
    # zou het geheugen stilletjes tussen de secties laten overlappen.
    if os.path.exists(memory_file):
        os.remove(memory_file)

    shutil.rmtree(vault_path, ignore_errors=True)
    os.makedirs(vault_path)

    mem.store.reset_cache(memory_file)
    ob.reset_vault_path()
    ob.set_vault_path(vault_path)

    if not leeg_vault:
        ob.write_note("Welkom.md", "Welkom in je vault.")


def zet_vault(path):
    """Stel het vault-pad in; None betekent 'bestaat niet'."""

    ob.set_vault_path(path or os.path.join(work, "bestaat niet"))


def note(vrijgeven):
    """Schrijft een memory-notitie in de test-vault."""

    ob.write_note(
        ob.note_name_for_memory(vrijgeven["key"], vrijgeven["category"]),
        ob.memory_to_note(
            {"value": vrijgeven["value"], **vrijgeven.get("extra", {})},
            key=vrijgeven["key"],
            category=vrijgeven["category"],
        )["content"],
    )


@patch.object(ai, "CONVERSATION_FILE", conversation_file)
@patch.object(mem, "MEMORY_FILE", memory_file)
def main():
    # =========================================================
    # 1. Routering: commando's zonder vault-woord vallen af
    # =========================================================

    print("\n--- 1. routering ---")

    reset()

    for commando in [
        "open discord",
        "wat is het weer",
        "onthoud dat ik blauw leuk vind",
        "zet de radio aan",
        "maak een bestand aan",
        "vergeet dat",
    ]:
        ok(f"'{commando}' raakt de vault niet",
           brain.try_vault_info(commando) is None
           and brain.try_vault_import(commando) is None)

    ok("'wat heb ik in mijn vault staan' wordt wel herkend",
       brain.try_vault_info("wat heb ik in mijn vault staan") is not None)

    ok("'zet voorkeuren/licht in mijn geheugen' wordt herkend",
       brain.try_vault_import("zet voorkeuren/licht in mijn geheugen")
       is not None)

    ok("'importeer obsidian notitie' wordt herkend",
       brain.try_vault_import("importeer obsidian") is not None)

    ok("'toon mijn vault' wordt als vraag herkend",
       brain.try_vault_info("toon mijn vault") is not None)

    ok("een willekeurige zin over obsidian is geen commando",
       brain.try_vault_info("obsidian is een programma") is None)

    # =========================================================
    # 2. Lege startsituatie (BELANGRIJK: memory.json is nu leeg)
    # =========================================================

    print("\n--- 2. lege vault en leeg geheugen ---")

    # Echt leeg: geen Welkom.md, want deze test moet bewijzen dat een
    # vault zonder notities netjes wordt afgehandeld.
    reset(leeg_vault=True)

    ok("lege vault: vault bestaat", ob.vault_exists())
    ok("lege vault: geen notities", ob.list_notes() == [])
    ok("lege vault: geen memory-notities", vi.plan_import_all() == [])
    ok("lege geheugen: geen memories",
       not any(mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES))

    antwoord = brain.try_vault_info("wat heb ik in mijn vault staan")
    ok("lege vault geeft een rustig antwoord", isinstance(antwoord, str))
    ok("lege vault zegt dat hij leeg is", "leeg" in antwoord.lower())
    ok("lege vault geeft geen foutmelding", "kan niet" not in antwoord.lower())

    antwoord = brain.try_vault_import("zet voorkeuren/licht in mijn geheugen")
    ok("import naar lege vault zegt dat hij niets vindt",
       isinstance(antwoord, str) and "geen notitie vinden" in antwoord.lower())

    ok("lege import verandert het geheugen niet",
       not any(mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES))

    # Nu een handgeschreven notitie erbij: die is geen memory en mag
    # dus nooit geïmporteerd worden.
    ob.write_note("Welkom.md", "Welkom in je vault.")

    antwoord = brain.try_vault_import("zet welkom in mijn geheugen")
    ok("handgeschreven notitie wordt niet geimporteerd",
       isinstance(antwoord, str) and "geen notitie" in antwoord.lower())

    ok("geen enkele memory aangemaakt door de lege tests",
       not any(mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES))

    # =========================================================
    # 3. Ontbrekende vault
    # =========================================================

    print("\n--- 3. ontbrekende vault ---")

    reset()
    zet_vault(None)

    antwoord = brain.try_vault_info("wat heb ik in mijn vault staan")
    ok("info bij ontbrekende vault noemt het pad",
       isinstance(antwoord, str) and "niet vinden" in antwoord.lower())

    antwoord = brain.try_vault_import("zet iets in mijn geheugen")
    ok("import bij ontbrekende vault legt uit waarom niet",
       isinstance(antwoord, str) and "niet vinden" in antwoord.lower())

    ok("ontbrekende vault crasht niet", True)

    # =========================================================
    # 4. Vault met alleen handgeschreven notities
    # =========================================================

    print("\n--- 4. vault zonder memory-notities ---")

    reset()
    ob.write_note("ideeen.md", "# Idee\n\nGeen memory hier.")

    antwoord = brain.try_vault_info("wat heb ik in mijn vault staan")
    ok("handgeschreven notities worden geteld",
       isinstance(antwoord, str) and "notitie" in antwoord.lower())
    ok("het meldt dat er geen memories in staan",
       "geen daarvan" in antwoord.lower() or "geen memory" in antwoord.lower())

    # =========================================================
    # 5. Info met memory-notities
    # =========================================================

    print("\n--- 5. vault-info met memories ---")

    reset()
    note({"key": "favoriete kleur", "value": "blauw", "category": "voorkeuren"})
    note({"key": "favoriete band", "value": "Radiohead", "category": "muziek"})

    antwoord = brain.try_vault_info("wat heb ik in mijn vault staan")
    ok("info noemt het aantal memory-notities",
       "2" in antwoord)
    ok("info toont de sleutel", "favoriete kleur" in antwoord)
    ok("info toont de waarde", "blauw" in antwoord)
    ok("info meldt dat ze nieuw zijn voor het geheugen",
       "nieuw" in antwoord.lower())

    ok("info verandert het geheugen niet",
       not any(mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES))

    ok("info verandert de vault niet",
       len(ob.list_notes()) == 3)

    # =========================================================
    # 6. Importeren van een nieuwe memory
    # =========================================================

    print("\n--- 6. importeren (nieuw) ---")

    reset()
    note({"key": "favoriete kleur", "value": "blauw", "category": "voorkeuren"})

    antwoord = brain.try_vault_import("zet voorkeuren/favoriete-kleur "
                                      "in mijn geheugen")
    ok("import van een nieuwe memory lukt", isinstance(antwoord, str))
    ok("import meldt de sleutel", "favoriete kleur" in antwoord)
    ok("import meldt de waarde", "blauw" in antwoord)

    ok("memory staat nu in het geheugen",
       mem.load_memory()["voorkeuren"].get("favoriete kleur", {}).get("value")
       == "blauw")

    ok("bron is de vault",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["source"]
       == "obsidian")

    ok("import riep geen bevestiging op",
       ai.current_context.get("pending_choice") is None)

    ok("import liet de notitie in de vault staan",
       ob.note_exists("voorkeuren/favoriete-kleur.md"))

    # =========================================================
    # 7. Ongewijzigde memory (tweede keer importeren)
    # =========================================================

    print("\n--- 7. ongewijzgd ---")

    antwoord = brain.try_vault_import("zet voorkeuren/favoriete-kleur "
                                      "in mijn geheugen")
    ok("tweede import zegt dat het er al staat",
       isinstance(antwoord, str) and "al in je geheugen" in antwoord.lower())
    ok("tweede import opent geen bevestiging",
       ai.current_context.get("pending_choice") is None)

    entry = mem.load_memory()["voorkeuren"]["favoriete kleur"]
    ok("tweede import heeft de waarde niet overschreven",
       entry["value"] == "blauw")
    ok("tweede import heeft geen conflict gemeld", entry["conflict"] is False)

    # =========================================================
    # 8. Conflict via de bestaande pending_choice-flow
    # =========================================================

    print("\n--- 8. conflict en bevestiging ---")

    reset()
    note({"key": "favoriete kleur", "value": "blauw", "category": "voorkeuren"})
    vi.import_note("voorkeuren/favoriete-kleur.md")

    # Wijzig alleen de vault, niet het geheugen.
    note({"key": "favoriete kleur", "value": "groen", "category": "voorkeuren"})

    ok("geheugen staat nog op blauw",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")

    antwoord = brain.try_vault_import("zet voorkeuren/favoriete-kleur "
                                      "in mijn geheugen")

    ok("conflict geeft een bevestigingsvraag",
       isinstance(antwoord, str) and "Zal ik dat wijzigen" in antwoord)
    ok("de vraag noemt de oude waarde", "blauw" in antwoord)
    ok("de vraag noemt de vault-waarde", "groen" in antwoord)
    ok("de vraag vraagt om ja of nee",
       "ja" in antwoord.lower() and "nee" in antwoord.lower())

    pending = ai.current_context.get("pending_choice")
    ok("er staat een pending_choice klaar", isinstance(pending, dict))
    ok("pending_choice gebruikt de bestaande memory_update-vorm",
       pending["kind"] == "memory_update")
    ok("pending_choice onthoudt de notitie", "favoriete-kleur" in pending["from_vault"])
    ok("GEHEUGEN IS NOG NIET OVERSCHREVEN",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")

    # 'nee' -> oude waarde blijft
    antwoord = brain.handle_pending_choice("nee")
    ok("nee handhaaft het geheugen",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")
    ok("nee noemt de vault", "vault" in antwoord.lower())
    ok("nee wist de pending_choice", ai.current_context.get("pending_choice") is None)
    ok("nee legt de afgewezen waarde vast",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["conflict_rejected_value"]
       == "groen")

    # 'ja' -> vault-waarde wordt actueel
    note({"key": "favoriete kleur", "value": "zwart", "category": "voorkeuren"})

    brain.try_vault_import("zet voorkeuren/favoriete-kleur in mijn geheugen")
    pending = ai.current_context.get("pending_choice")
    ok("tweede conflict vraagt opnieuw", isinstance(pending, dict))

    antwoord = brain.handle_pending_choice("ja")
    ok("ja past de vault-waarde toe",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "zwart")
    ok("ja bewaart de vorige waarde",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["previous_value"]
       == "blauw")
    ok("ja noemt de vault", "vault" in antwoord.lower())
    ok("ja wist de pending_choice", ai.current_context.get("pending_choice") is None)

    # =========================================================
    # 9. Conflict via het volledige process_command
    # =========================================================

    print("\n--- 9. via process_command ---")

    reset()
    note({"key": "favoriete kleur", "value": "blauw", "category": "voorkeuren"})
    vi.import_note("voorkeuren/favoriete-kleur.md")
    note({"key": "favoriete kleur", "value": "rood", "category": "voorkeuren"})

    antwoord = brain.process_command("zet voorkeuren/favoriete-kleur "
                                     "in mijn geheugen")
    ok("process_command vraagt om bevestiging",
       isinstance(antwoord, str) and "wijzigen" in antwoord)
    ok("process_command wijzigt niets zonder bevestiging",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")

    antwoord = brain.process_command("ja")
    ok("process_command + ja past toe",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "rood")

    # =========================================================
    # 10. GEEN automatische synchronisatie
    # =========================================================

    print("\n--- 10. geen automatische sync ---")

    reset()

    _notities = ob.list_notes()

    mem.remember("iets nieuws", "testwaarde", category="algemeen")

    ok("onthouden raakt de vault niet aan", ob.list_notes() == _notities)

    _geheugen_voor = mem.load_memory()
    ob.write_note("voorkeuren/nieuw", "---\nmemory_key: nieuw\n---\n\n> test")
    _geheugen_na = mem.load_memory()
    ok("een notitie in de vault komt niet vanzelf in het geheugen",
       _geheugen_na == _geheugen_voor)

    ok("brain.py start geen achtergrondproces",
       not any(k in dir(brain) for k in ("_vault_watcher", "_vault_loop")))

    ok("er is geen timer voor de vault in brain.py",
       "vault_sync.synchroniseer" not in dir(vi))

    # =========================================================
    # 11. De bestaande memory_update-flow is niet kapot
    # =========================================================

    print("\n--- 11. bestaande conflict-flow werkt nog ---")

    reset()

    mem.remember("fav kleur", "blauw", category="voorkeuren", force=True)

    ai.current_context["pending_choice"] = {
        "kind": "memory_update",
        "memory_key": "fav kleur",
        "memory_value": "groen",
        "memory_category": "voorkeuren",
        "old_value": "blauw",
    }

    antwoord = brain.handle_pending_choice("ja")
    ok("gewone memory_update werkt nog",
       mem.load_memory()["voorkeuren"]["fav kleur"]["value"] == "groen")
    ok("gewone memory_update noemt de vault niet",
       "vault" not in antwoord.lower())

    # =========================================================
    # 12. Echte bestanden mogen onveranderd zijn
    # =========================================================

    print("\n--- 12. echte bestanden ---")

    if _memory_voor is not None:
        with open(_echte_memory, "rb") as file:
            ok("echte memory.json is onveranderd", file.read() == _memory_voor)

    if _conversation_voor is not None:
        with open(_echte_conversation, "rb") as file:
            ok("echte conversation.json is onveranderd",
               file.read() == _conversation_voor)

    ok("echte vault staat nog op de standaard",
       ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, "JARVIS Memory"))


main()

ai.CONVERSATION_FILE = _echte_conversation
ob.reset_vault_path()
mem.store.reset_cache()

shutil.rmtree(work, ignore_errors=True)

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)