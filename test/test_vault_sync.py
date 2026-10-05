"""
JARVIS — Vault Analyse + Batch Import (Fase 14, Stap 5)
======================================================

Test de twee nieuwe stukken van stap 5:

  1. compare_vault_to_memory()  -- VOLLEDIG READ-ONLY
  2. start_batch() / resolve_paused_batch()

En de commando's die brain.py daaromheen hangt:
  * "vergelijk mijn vault met mijn geheugen"
  * "importeer alles uit mijn vault"

Getest wordt:
  * lege vault en leeg geheugen
  * nieuwe notities, ongewijzigde notities
  * één conflict en meerdere conflicten
  * 'ja' en 'nee' via de bestaande pending_choice-flow
  * pauzeren en hervatten
  * dubbele imports
  * onverwachte fouten: veilig stoppen
  * read-only gedrag van de analyse
  * dat de echte memory.json en de echte vault onveranderd blijven

Alle tests draaien op een tijdelijke vault, een tijdelijk geheugenbestand
en een tijdelijk gespreksbestand.
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
# Opzet
# =============================================================

work = tempfile.mkdtemp(prefix="jarvis_vault_sync_")

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


def _vault_snapshot(pad):
    """
    Alle bestanden in de echte vault, als gesorteerde lijst van paden.

    Waarom een snapshot in plaats van een vaste lijst? Deze test moet
    bewaken dat de test ZELF de echte vault niet aanraakt. Een vaste
    inventaris (".obsidian", "Welkom.md") doet dat niet: die zegt
    alleen iets over wat er toevallig in de persoonlijke vault van de
    gebruiker staat, en brak zodra daar een notitie bij kwam. Wat hier
    getoetst wordt is stabiliteit, niet voorraad.
    """

    if not os.path.isdir(pad):
        return None

    return sorted(
        os.path.relpath(os.path.join(mapnaam, naam), pad)
        for mapnaam, _, namen in os.walk(pad)
        for naam in namen
    )


_vault_voor = _vault_snapshot(_echte_vault)


def reset(leeg_vault=True):
    """
    Schone teststand: geen geheugen, lege vault, geen openstaande keuze.

    Let op: memory.json is een bestand, dus os.remove() en NIET
    shutil.rmtree() -- die doet stil niets op een bestand en zou het
    geheugen tussen de secties laten overlappen.
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


def note(key, value, category="voorkeuren", **extra):
    """Schrijft een memory-notitie in de test-vault."""

    ob.write_note(
        ob.note_name_for_memory(key, category),
        ob.memory_to_note({"value": value, **extra}, key=key,
                          category=category)["content"],
    )


def geheugen():
    """De volledige memory.json als dict."""

    return mem.load_memory()


def waarde(key, category="voorkeuren"):
    """De waarde van een memory, of None als die er niet is."""

    return geheugen().get(category, {}).get(key, {}).get("value")


def statuses(state):
    """Een compacte lijst van (notitie, status)."""

    return [(r["note_name"], r["status"]) for r in state["results"]]


@patch.object(ai, "CONVERSATION_FILE", conversation_file)
@patch.object(mem, "MEMORY_FILE", memory_file)
def main():
    # =========================================================
    # 1. Lege vault en leeg geheugen
    # =========================================================

    print("\n--- 1. lege vault, leeg geheugen ---")

    reset()

    ok("lege vault bestaat", ob.vault_exists())
    ok("lege vault heeft geen notities", ob.list_notes() == [])

    rapport = vi.compare_vault_to_memory()
    ok("analyse werkt op een lege vault", rapport["ok"] is True)
    ok("analyse telt 0 notities", rapport["counts"]["total"] == 0)
    ok("analyse vindt niets nieuws", rapport["new"] == [])
    ok("analyse vindt geen conflicten", rapport["conflicts"] == [])

    state = vi.start_batch()
    ok("batch op een lege vault doet niets", state["results"] == [])
    ok("batch is klaar", state["done"] is True)
    ok("batch is niet gepauzeerd", state["paused"] is False)
    ok("leeg geheugen blijft leeg",
       not any(geheugen().get(c) for c in mem.DEFAULT_CATEGORIES))

    antwoord = brain.try_vault_compare("vergelijk mijn vault met mijn geheugen")
    ok("brain geeft op lege vault een rustig antwoord", isinstance(antwoord, str))
    ok("brain zegt dat er niets te vergelijken valt",
       "geen memory-notities" in antwoord.lower())

    antwoord = brain.try_vault_batch("importeer alles uit mijn vault")
    ok("batch-commando op lege vault geeft een antwoord",
       isinstance(antwoord, str))
    ok("leeg geheugen nog steeds leeg",
       not any(geheugen().get(c) for c in mem.DEFAULT_CATEGORIES))

    # =========================================================
    # 2. Ontbrekende vault
    # =========================================================

    print("\n--- 2. ontbrekende vault ---")

    reset()
    zet_vault(None)

    rapport = vi.compare_vault_to_memory()
    ok("analyse merkt op dat de vault ontbreekt", rapport["ok"] is False)
    ok("analyse zegt waarom", rapport["reason"] != "")

    state = vi.start_batch()
    ok("batch stopt op een ontbrekende vault", state["stopped"] is True)
    ok("batch legt de reden vast", state["error"] != "")

    ok("analyse van een ontbrekende vault crasht niet", True)

    zet_vault(vault_path)

    # =========================================================
    # 3. De analyse is VOLLEDIG read-only
    # =========================================================

    print("\n--- 3. read-only analyse ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")

    vi.import_note(ob.note_name_for_memory("favoriete kleur", "voorkeuren"))

    # Wijzig alleen de vault: nu is er 1 conflict.
    note("favoriete kleur", "groen")

    geheugen_bytes = open(memory_file, "rb").read()
    notities_voor = sorted(ob.list_notes())
    mtime_voor = os.path.getmtime(memory_file)

    rapport = vi.compare_vault_to_memory()

    ok("analyse telt de notities", rapport["counts"]["total"] == 2)
    ok("analyse ziet de nieuwe notitie", rapport["counts"]["new"] == 1)
    ok("analyse ziet het conflict", rapport["counts"]["conflict"] == 1)
    ok("analyse ziet geen ongewijzigde notitie",
       rapport["counts"]["unchanged"] == 0)

    ok("analyse wijzigt memory.json niet",
       open(memory_file, "rb").read() == geheugen_bytes)
    ok("analyse raakt memory.json niet aan (mtime)",
       os.path.getmtime(memory_file) == mtime_voor)
    ok("analyse wijzigt de vault niet", sorted(ob.list_notes()) == notities_voor)
    ok("analyse lost het conflict niet op",
       geheugen()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")
    ok("analyse zet geen conflict-vlag", 
       geheugen()["voorkeuren"]["favoriete kleur"]["conflict"] is False)

    # Ook een lege analyse mag niets doen.
    vi.compare_vault_to_memory("voorkeuren")
    vi.compare_vault_to_memory("bestaat niet")
    ok("analyse van een map die er niet is crasht niet", True)
    ok("analyse heeft memory.json nog steeds niet aangeraakt",
       open(memory_file, "rb").read() == geheugen_bytes)

    # =========================================================
    # 4. Nieuwe notities importeren
    # =========================================================

    print("\n--- 4. nieuwe notities ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")

    state = vi.start_batch(dry_run=False)

    ok("batch is klaar", state["done"] is True)
    ok("batch is niet gepauzeerd", state["paused"] is False)
    ok("beide notities zijn geimporteerd", state["count"]["imported"] == 2)
    ok("favoriete kleur staat in het geheugen", waarde("favoriete kleur") == "blauw")
    ok("favoriete band staat in het geheugen",
       waarde("favoriete band", "muziek") == "Radiohead")
    ok("iedere notitie heeft een status",
       all(r["status"] == "imported" for r in state["results"]))
    ok("iedere status heeft een leesbaar label",
       all(r["label"] for r in state["results"]))
    ok("de wachtrij is leeg", state["queue"] == [])
    ok("niets staat meer op processed zonder status",
       len(state["processed"]) == len(state["results"]))

    # =========================================================
    # 5. Ongewijzigde notities
    # =========================================================

    print("\n--- 5. ongewijzigde notities ---")

    state = vi.start_batch(dry_run=False)

    ok("ongewijzigde notities krijgen status 'unchanged'",
       all(r["status"] == "unchanged" for r in state["results"]))
    ok("er is niets geimporteerd", state["count"]["imported"] == 0)
    ok("de teller ziet ze wel", state["count"]["unchanged"] == 2)
    ok("de waarden zijn onveranderd", waarde("favoriete kleur") == "blauw")

    # =========================================================
    # 6. dry_run is de veilige standaard
    # =========================================================

    print("\n--- 6. dry_run als standaard ---")

    reset()
    note("favoriete kleur", "blauw")

    geheugen_bytes = open(memory_file, "rb").read() if os.path.exists(memory_file) else None

    state = vi.start_batch()

    ok("dry_run staat standaard aan", state["dry_run"] is True)
    ok("dry_run zegt dat hij een plan is", state["count"]["planned"] == 1)
    ok("dry_run schrijft niets",
       not any(geheugen().get(c) for c in mem.DEFAULT_CATEGORIES))
    ok("dry_run maakt geen bestand aan", geheugen_bytes is None)
    ok("dry_run meldt dat er niets is geschreven",
       "niets" in " ".join(r["reason"] for r in state["results"]).lower())

    # =========================================================
    # 7. Een conflict pauzeert de batch
    # =========================================================

    print("\n--- 7. conflict pauzeert de batch ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")

    vi.start_batch(dry_run=False)
    ok("beide memories staan er", waarde("favoriete kleur") == "blauw")

    # Verander alleen de vault -> conflict, plus een nieuwe notitie erna.
    note("favoriete kleur", "groen")
    note("fav restaurant", "Pizzeria Napoli")

    state = vi.start_batch(dry_run=False)

    ok("batch is gepauzeerd", state["paused"] is True)
    ok("batch is nog niet klaar", state["done"] is False)
    ok("er is een confirm-blok", isinstance(state["confirm"], dict))
    ok("het conflict noemt de notitie",
       state["confirm"]["note_name"].endswith("favoriete-kleur.md"))
    ok("het conflict noemt de oude waarde",
       state["confirm"]["memory_value"] == "blauw")
    ok("het conflict noemt de vault-waarde",
       state["confirm"]["vault_value"] == "groen")

    ok("de conflictnotitie heeft status 'waiting'",
       any(r["status"] == "waiting" for r in state["results"]))
    ok("GEHEUGEN IS NOG NIET OVERSCHREVEN", waarde("favoriete kleur") == "blauw")
    ok("de conflict-notitie staat NIET op 'processed'",
       state["confirm"]["note_name"] not in state["processed"])
    ok("de notitie erachter is nog niet geimporteerd",
       waarde("fav restaurant", "algemeen") is None)
    ok("er staat werk op de wachtrij", len(state["queue"]) > 0)

    # =========================================================
    # 8. 'nee' behoudt het geheugen en hervat de batch
    # =========================================================

    print("\n--- 8. nee -> behouden en hervatten ---")

    state = vi.resolve_paused_batch(state, keep_old=True)

    ok("de oude waarde blijft staan", waarde("favoriete kleur") == "blauw")
    ok("het conflict is als afgehandeld vastgelegd",
       geheugen()["voorkeuren"]["favoriete kleur"]["conflict_kept_old"] is True)
    ok("de afgewezen waarde is vastgelegd",
       geheugen()["voorkeuren"]["favoriete kleur"]["conflict_rejected_value"]
       == "groen")
    ok("de conflictnotitie kreeg status 'kept'",
       any(r["status"] == "kept" for r in state["results"]))
    ok("er is geen openstaand conflict meer", state["confirm"] is None)
    ok("de batch is niet meer gepauzeerd", state["paused"] is False)

    ok("DE BATCH IS HERVAT: de volgende notitie is geimporteerd",
       waarde("fav restaurant") == "Pizzeria Napoli")
    ok("de batch is nu klaar", state["done"] is True)
    ok("iedere notitie kreeg een status", len(state["results"]) >= 2)
    ok("geen enkele notitie staat zonder status",
       all(r["status"] for r in state["results"]))

    # Het afgehandelde conflict staat NIET meer op deze wachtrij.
    ok("de afgehandelde conflictnotitie is van de wachtrij",
       ob.note_name_for_memory("favoriete kleur", "voorkeuren")
       not in state["queue"])

    # Let op: memory.py's has_conflict() vergelijkt alleen waarden. Een
    # afgewezen notitie wordt daarom bij een VOLGENDE batch opnieuw
    # voorgelegd. Dat is bestaand gedrag, geen regressie.
    volgende = vi.start_batch(dry_run=False)
    ok("een nieuwe batch legt het afgewezen conflict opnieuw voor",
       volgende["paused"] is True)
    ok("maar de waarde is nog steeds de oude",
       waarde("favoriete kleur") == "blauw")

    # =========================================================
    # 9. 'ja' past de vault-waarde toe
    # =========================================================

    print("\n--- 9. ja -> vault-waarde toepassen ---")

    reset()
    note("favoriete kleur", "blauw")
    vi.start_batch(dry_run=False)
    note("favoriete kleur", "rood")

    state = vi.start_batch(dry_run=False)
    ok("batch is gepauzeerd op het conflict", state["paused"] is True)

    state = vi.resolve_paused_batch(state, keep_old=False)

    ok("de vault-waarde is nu actueel", waarde("favoriete kleur") == "rood")
    ok("de oude waarde staat in previous_value",
       geheugen()["voorkeuren"]["favoriete kleur"]["previous_value"] == "blauw")
    ok("de conflictnotitie kreeg status 'accepted'",
       any(r["status"] == "accepted" for r in state["results"]))
    ok("de batch is klaar", state["done"] is True)

    # =========================================================
    # 10. Meerdere conflicten, één voor één
    # =========================================================

    print("\n--- 10. meerdere conflicten ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")
    vi.start_batch(dry_run=False)

    note("favoriete kleur", "groen")
    note("favoriete band", "Nirvana", "muziek")

    state = vi.start_batch(dry_run=False)

    rondes = 0
    gezien = []

    while state["paused"] and rondes < 10:
        rondes += 1
        gezien.append(state["confirm"]["note_name"])
        state = vi.resolve_paused_batch(state, keep_old=rondes % 2 == 0)

    ok("er zijn twee conflicten geweest", rondes == 2)
    ok("de twee conflicten waren verschillende notities",
       len(set(gezien)) == 2)
    ok("de batch is klaar na de laatste", state["done"] is True)
    ok("er is geen conflict meer open", state["confirm"] is None)
    ok("beide notities hebben een eindstatus",
       len(state["results"]) >= 2)

    # Het tweede conflict was 'nee' -> die waarde bleef staan.
    ok("een geaccepteerde en een afgewezen notitie",
       {"accepted", "kept"} <= {r["status"] for r in state["results"]})

    # =========================================================
    # 11. Geen dubbele import
    # =========================================================

    print("\n--- 11. geen dubbele import ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")

    state = vi.start_batch(dry_run=False)
    ok("eerste run importeert", state["count"]["imported"] == 2)

    mtime = os.path.getmtime(memory_file)
    tweede = vi.start_batch(dry_run=False)

    ok("tweede run importeert niets nieuws", tweede["count"]["imported"] == 0)
    ok("tweede run merkt ze als ongewijzigd",
       tweede["count"]["unchanged"] == 2)
    ok("de waarden zijn nog steeds goed", waarde("favoriete kleur") == "blauw")

    # Een notitie die twee keer op de wachtrij staat.
    handmatig = {
        "subfolder": "", "priority": None, "source": "obsidian",
        "dry_run": False, "results": [], "queue": [],
        "processed": [], "confirm": None, "paused": False,
        "done": False, "stopped": False, "error": None,
    }
    notitie = ob.note_name_for_memory("favoriete kleur", "voorkeuren")
    handmatig["queue"] = [notitie, notitie]
    # Eerst een 'nieuwe' maken zodat er iets te doen valt.
    note("nieuw item", "iets")
    handmatig["queue"] = [notitie, notitie,
                          ob.note_name_for_memory("nieuw item", "voorkeuren")]

    state = vi._advance_batch(handmatig)
    ok("een dubbele notitie wordt maar een keer verwerkt",
       [s for n, s in statuses(state) if n == notitie] == ["unchanged", "duplicate"])
    ok("de dubbele kreeg status 'duplicate'",
       any(r["status"] == "duplicate" for r in state["results"]))
    ok("de batch ging gewoon door",
       waarde("nieuw item") == "iets")

    # =========================================================
    # 12. Onverwachte fout -> veilig stoppen
    # =========================================================

    print("\n--- 12. onverwachte fout ---")

    reset()
    note("aaa eerste", "een")
    note("zzz derde", "drie")
    note("mmm tweede", "twee")

    origineel = vi.import_note

    def kapot(naam, *args, **kwargs):
        if "mmm-tweede" in naam:
            raise RuntimeError("gesimuleerde schijffout")
        return origineel(naam, *args, **kwargs)

    vi.import_note = kapot
    try:
        state = vi.start_batch(dry_run=False)
    finally:
        vi.import_note = origineel

    ok("de batch stopt bij de fout", state["stopped"] is True)
    ok("de fout wordt vastgelegd", "RuntimeError" in (state["error"] or ""))
    ok("de mislukte notitie kreeg status 'error'",
       any(r["status"] == "error" for r in state["results"]))
    ok("de notitie is NIET als verwerkt gemarkeerd",
       ob.note_name_for_memory("mmm tweede", "voorkeuren")
       not in state["processed"])
    ok("de resterende wachtrij is bewaard",
       ob.note_name_for_memory("zzz derde", "voorkeuren") in state["queue"])
    ok("geen notitie na de fout is geimporteerd",
       waarde("zzz derde") is None)
    ok("de notitie van voor de fout WEL geimporteerd",
       waarde("aaa eerste") == "een")
    ok("geen enkele notitie hangt zonder status",
       all(r["status"] for r in state["results"]))

    # =========================================================
    # 13. Onverwacht conflict bij een 'nieuwe' memory
    # =========================================================

    print("\n--- 13. inconsistentie wordt niet stilzwijgend verwerkt ---")

    reset()
    note("aaa eerste", "een")
    note("zzz derde", "drie")

    def leugenaar(naam, *args, **kwargs):
        if "aaa-eerste" in naam:
            # Zegt 'nieuw', maar doet alsof er een conflict is.
            return {"applied": False, "needs_confirm": True,
                    "confirm_token": None, "key": "aaa eerste",
                    "value": "een", "category": "voorkeuren",
                    "action": "new", "reason": ""}
        return origineel(naam, *args, **kwargs)

    vi.import_note = leugenaar
    try:
        state = vi.start_batch(dry_run=False)
    finally:
        vi.import_note = origineel

    ok("een onverwacht conflict stopt de batch", state["stopped"] is True)
    ok("de notitie kreeg status 'error'",
       any(r["status"] == "error" for r in state["results"]))
    ok("er is geen vals confirm-blok", state["confirm"] is None)
    ok("de volgende notitie is niet doorgegaan", waarde("zzz derde") is None)

    # =========================================================
    # 14. resolve_paused_batch zonder openstaand conflict
    # =========================================================

    print("\n--- 14. hervatten zonder conflict ---")

    reset()
    note("favoriete kleur", "blauw")

    state = vi.start_batch(dry_run=False)
    ok("batch klaar", state["done"] is True)

    opnieuw = vi.resolve_paused_batch(state, keep_old=False)
    ok("hervatten zonder conflict doet niets", opnieuw["done"] is True)
    ok("de waarde is onveranderd", waarde("favoriete kleur") == "blauw")

    kapot_state = "geen dict"
    try:
        vi.resolve_paused_batch(kapot_state, keep_old=True)
    except TypeError:
        ok("resolve_paused_batch weigert een verkeerd type", True)
    except Exception:
        ok("resolve_paused_batch weigert een verkeerd type", False)
    else:
        ok("resolve_paused_batch weigert een verkeerd type", False)

    ok("batch_is_finished klopt", vi.batch_is_finished(state) is True)

    # =========================================================
    # 15. De commando's in brain.py
    # =========================================================

    print("\n--- 15. commando's via brain.py ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")
    vi.start_batch(dry_run=False)
    note("favoriete kleur", "groen")

    ok("'vergelijk' is geen andere handler",
       brain.try_vault_batch("vergelijk mijn vault met mijn geheugen") is None)

    antwoord = brain.try_vault_compare("vergelijk mijn vault met mijn geheugen")
    ok("vergelijken geeft een overzicht", isinstance(antwoord, str))
    ok("vergelijken noemt het conflict", "verschil" in antwoord.lower())
    ok("vergelijken noemt de oude waarde", "blauw" in antwoord)
    ok("vergelijken noemt de vault-waarde", "groen" in antwoord)
    ok("vergelijken verandert niets", waarde("favoriete kleur") == "blauw")

    ok("'importeer alles' is geen info-commando",
       brain.try_vault_info("importeer alles uit mijn vault") is None)

    antwoord = brain.try_vault_batch("importeer alles uit mijn vault")
    ok("batch via brain vraagt om bevestiging",
       isinstance(antwoord, str) and "Zal ik dat wijzigen" in antwoord)
    ok("batch via brain wijzigt nog niets", waarde("favoriete kleur") == "blauw")

    pending = ai.current_context.get("pending_choice")
    ok("er staat een pending_choice", isinstance(pending, dict))
    ok("de pending_choice gebruikt de bestaande memory_update-vorm",
       pending["kind"] == "memory_update")
    ok("de pending_choice bevat de batch-state",
       isinstance(pending.get("vault_batch"), dict))
    ok("de batch-state is JSON-geschikt",
       _is_json(pending["vault_batch"]))
    ok("de batch-state bevat het openstaande conflict",
       pending["vault_batch"]["paused"] is True)

    # 'nee' via de bestaande flow
    antwoord = brain.handle_pending_choice("nee")
    ok("'nee' behoudt het geheugen", waarde("favoriete kleur") == "blauw")
    ok("'nee' wist de pending_choice",
       ai.current_context.get("pending_choice") is None)

    # =========================================================
    # 16. Meerdere conflicten via process_command
    # =========================================================

    print("\n--- 16. meerdere conflicten via process_command ---")

    reset()
    note("favoriete kleur", "blauw")
    note("favoriete band", "Radiohead", "muziek")
    vi.start_batch(dry_run=False)
    note("favoriete kleur", "groen")
    note("favoriete band", "Nirvana", "muziek")

    geheugen_voor = dict(geheugen())

    antwoord = brain.process_command("importeer alles uit mijn vault")
    ok("process_command vraagt om bevestiging",
       isinstance(antwoord, str) and "Zal ik dat wijzigen" in antwoord)
    ok("nog niets gewijzigd", geheugen() == geheugen_voor)

    # Welke notitie eerst komt hangt van de volgorde in de vault af,
    # dus we sturen 'ja' en 'nee' aan zonder ons vast te leggen op volgorde.
    pending = ai.current_context.get("pending_choice")
    eerste = pending["vault_batch"]["confirm"]["note_name"]

    antwoord = brain.process_command("ja")
    ok("'ja' verandert precies één memory",
       sum(1 for r in pending["vault_batch"]["results"] if r["status"] == "accepted") == 1)
    ok("'ja' vraagt meteen door voor het volgende conflict",
       "Zal ik dat wijzigen" in antwoord)

    pending = ai.current_context.get("pending_choice")
    ok("er staat nog een conflict klaar", isinstance(pending, dict))
    ok("het is een ANDERE notitie dan die van daarnet",
       pending["vault_batch"]["confirm"]["note_name"] != eerste)

    kleur = waarde("favoriete kleur")
    band = waarde("favoriete band", "muziek")
    ok("de 'ja'-waarde is doorgegaan",
       "groen" in (kleur, band) or "Nirvana" in (kleur, band))
    ok("precies één memory is veranderd",
       sum(1 for v in (kleur, band) if v in ("groen", "Nirvana")) == 1)

    # Vlak voor de 'nee' onthouden wat er staat; na de 'nee' moet dat
    # nog exact hetzelfde zijn.
    voor_nee = (waarde("favoriete kleur"), waarde("favoriete band", "muziek"))

    antwoord = brain.process_command("nee")

    ok("'nee' verandert geen enkele memory meer",
       (waarde("favoriete kleur"), waarde("favoriete band", "muziek"))
       == voor_nee)
    ok("'nee' legt bij de afgewezen memory vast dat je nee zei",
       any(geheugen()[c][k].get("conflict_kept_old") is True
           for c, k in [("voorkeuren", "favoriete kleur"),
                        ("muziek", "favoriete band")]))
    ok("de batch is klaar en meldt een overzicht",
       isinstance(antwoord, str) and "gewijzigd" in antwoord.lower())
    ok("er is geen openstaande keuze meer",
       ai.current_context.get("pending_choice") is None)

    # =========================================================
    # 17. Een gewone memory_update blijft gewoon werken
    # =========================================================

    print("\n--- 17. bestaande conflict-flow blijft werken ---")

    reset()

    mem.remember("fav kleur", "blauw", category="voorkeuren", force=True)

    ai.current_context["pending_choice"] = {
        "kind": "memory_update",
        "memory_key": "fav kleur",
        "memory_value": "groen",
        "memory_category": "voorkeuren",
        "old_value": "blauw",
    }

    brain.handle_pending_choice("ja")
    ok("een gewone memory_update werkt nog",
       waarde("fav kleur") == "groen")

    # En via het gewone onthouden, zonder vault.
    antwoord = brain.process_command("onthoud dat ik blauw leuk vind")
    ok("onthouden raakt de vault niet", ob.list_notes() == [])

    # =========================================================
    # 18. GEEN automatische synchronisatie
    # =========================================================

    print("\n--- 18. geen automatische sync ---")

    reset()

    _notities = ob.list_notes()

    mem.remember("iets nieuws", "testwaarde", category="algemeen")

    ok("onthouden schrijft niet naar de vault", ob.list_notes() == _notities)

    # Eerst ná het onthouden een foto van het geheugen maken; anders
    # vergelijk je het met de situatie van vóór de onthoudactie.
    geheugen_foto = geheugen()

    ob.write_note("voorkeuren/nieuw", "---\nmemory_key: nieuw\n---\n\n> test")
    ok("een notitie komt niet vanzelf in het geheugen",
       geheugen() == geheugen_foto)

    ok("er is geen watcher in vault_import",
       not any("watcher" in str(k).lower() or "loop" in str(k).lower()
               for k in vars(vi) if not k.startswith("__")))
    ok("brain roept de analyse niet zelf aan",
       "compare_vault_to_memory()" not in _bron_van_process_command())
    ok("brain start geen batch zonder commando",
       brain.try_vault_batch("wat doet het weer") is None)
    ok("brain start geen batch bij een los woord",
       brain.try_vault_batch("alles") is None)

    # =========================================================
    # 19. Echte bestanden mogen onveranderd zijn
    # =========================================================

    print("\n--- 19. echte bestanden ---")

    if _geheugen_voor is not None:
        with open(_echte_memory, "rb") as file:
            ok("echte memory.json is onveranderd", file.read() == _geheugen_voor)

    if _gesprek_voor is not None:
        with open(_echte_conversation, "rb") as file:
            ok("echte conversation.json is onveranderd",
               file.read() == _gesprek_voor)

    ok("de echte vault is onveranderd door deze test",
       _vault_snapshot(_echte_vault) == _vault_voor)

    ok("de standaard-vault staat nog goed",
       ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, "JARVIS Memory"))


def _is_json(ding):
    import json

    try:
        json.dumps(ding)
        return True
    except (TypeError, ValueError):
        return False


def _bron_van_process_command():
    import inspect

    return inspect.getsource(brain.process_command)


main()

ai.CONVERSATION_FILE = _echte_conversation
ob.set_vault_path(_echte_vault)
mem.store.reset_cache()

shutil.rmtree(work, ignore_errors=True)

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)