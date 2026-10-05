"""
JARVIS â€” Context + long-term memory tests (Fase 14, Stap 6)
==========================================================

Test de gecombineerde context/memory-laag in core/context_memory.py:

  1. alleen context
  2. alleen long-term memory
  3. context + memory samen
  4. directe verwijzingen ("hem", "die", "opnieuw")
  5. context weegt zwaarder dan een oudere memory
  6. dubbele informatie wordt weggelaten
  7. bestaande context-velden blijven werken
  8. het gecombineerde blok komt bij de AI/Agent aan
  9. backwards compatibility

Alle tests draaien op tijdelijke geheugenbestanden. De echte
memory/memory.json en memory/conversation.json worden niet aangeraakt.
"""

import sys
import os
import io
import shutil
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from memory import store
import memory.memory as mem

from core.context_memory import (
    build_memory_context,
    detect_conversation_reference,
    has_conversation_reference,
    rank_context_items,
    drop_duplicate_memories,
    _score_context_item,
    _normalize,
    _recent_history,
    DEFAULT_CONTEXT_MEMORIES,
)

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


work = tempfile.mkdtemp(prefix="jarvis_ctxmem_test_")
path = os.path.join(work, "memory.json")

store.reset_cache()

# Onthoud wat er in het echte gespreksbestand staat, zodat we kunnen
# controleren dat deze test er niks aan verandert.
_real_conversation = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memory",
    "conversation.json",
)

_real_conversation_existed = os.path.exists(_real_conversation)

_real_conversation_before = (
    open(_real_conversation, "rb").read() if _real_conversation_existed else b""
)

# Een context zoals die van JARVIS er echt uitziet.
CTX = {
    "last_command": "open kladblok",
    "last_result": "Kladblok geopend",
    "last_action": "program_started:Kladblok",
    "last_calculation": "10 + 5 = 15",
    "last_program": "kladblok",
    "last_file": "rapport.docx",
    "last_website": "",
    "last_ha_entity": "",
    "last_ha_domain": "",
    "last_ha_name": "",
    "pending_choice": None,
}

HISTORY = [
    {"role": "user", "content": "open kladblok"},
    {"role": "jarvis", "content": "Kladblok geopend"},
]


with patch.object(mem, "MEMORY_FILE", path):

    mem.remember("favoriete_kleur", "blauw", category="voorkeuren")
    mem.remember("gpu", "RTX 3060 Ti", category="pc")
    mem.remember("favoriete_band", "Coldplay", category="muziek")

    # =========================================================
    # 1: alleen context
    # =========================================================

    print("\n===== 1: ALLEEN CONTEXT =====\n")

    blok = build_memory_context(
        "open het programma opnieuw", context=CTX, history=[]
    )

    ok("context levert een blok op", bool(blok))
    ok("het blok noemt het gesprek", "DIT GESPREK" in blok)
    ok("het blok bevat het programma", "kladblok" in blok)

    # Zonder memories en zonder history blijft alleen de context staan
    ok("er staat geen langetermijnblok zonder memories",
       "WAT IK OVER JOU WEET" not in blok or "(niets relevant gevonden)" in blok)

    ok("lege context levert een lege string",
       build_memory_context("open het programma", context={}, history=[]) == "")

    ok("None als context werkt (valt terug op leeg)",
       build_memory_context("open kladblok", context=None, history=[]) == "")

    # =========================================================
    # 2: alleen long-term memory
    # =========================================================

    print("\n===== 2: ALLEEN LONG-TERM MEMORY =====\n")

    blok = build_memory_context("wat is mijn gpu", context={}, history=[])

    ok("memory levert een blok op", bool(blok))
    ok("het blok noemt het geheugen", "WAT IK OVER JOU WEET" in blok)
    ok("het blok bevat de gpu", "RTX 3060 Ti" in blok)
    ok("het blok bevat geen gespreksblok", "DIT GESPREK" not in blok)
    ok("het blok bevat geen gespreksregels", "RECENTE GESPREK" not in blok)

    # Voorkeuren lezen als een zin, andere categorieÃ«n als sleutel:waarde
    kleur_blok = build_memory_context("mijn favoriete kleur", context={})

    ok("een voorkeur wordt als zin getoond",
       "favoriete kleur is blauw" in kleur_blok)
    ok("een pc-feit wordt als sleutel:waarde getoond", "gpu:" in blok)

    # Een irrelevante vraag levert lege memories op
    ok("een irrelevante vraag zonder context levert niets op",
       build_memory_context("zzqqxx wwvvuu", context={}, history=[]) == "")

    # =========================================================
    # 3: context + memory samen
    # =========================================================

    print("\n===== 3: CONTEXT + MEMORY SAMEN =====\n")

    # Een vraag die zowel bij de context (kladblok) als bij het
    # geheugen (kleur) past.
    blok = build_memory_context(
        "open kladblok en wat is mijn kleur", context=CTX, history=HISTORY
    )

    ok("beide blokken staan erin",
       "DIT GESPREK" in blok and "WAT IK OVER JOU WEET" in blok)
    ok("het recente gesprek staat erbij", "RECENTE GESPREK" in blok)
    ok("het programma uit de context staat erbij", "kladblok" in blok)
    ok("de voorkeur uit het geheugen staat erbij", "blauw" in blok)

    # De geschiedenis wordt zichtbaar gemaakt
    ok("de gebruikerszin staat in het blok", "open kladblok" in blok)
    ok("het antwoord van jarvis staat in het blok", "Kladblok geopend" in blok)

    # Er staat een duidelijke regel over de volgorde
    ok("er staat een regel over het gebruik", "HOE JE DIT GEBRUIKT" in blok)
    ok("er staat een regel tegen verzinnen",
       "Verzin niets dat er niet staat" in blok)

    # Bloknummers kloppen
    ok("blok 1 is het gesprek", "1. DIT GESPREK" in blok)
    ok("blok 2 is het gesprek", "2. RECENTE GESPREK" in blok)
    ok("blok 3 is het geheugen", "3. WAT IK OVER JOU WEET" in blok)

    # Zonder verwijzing geldt de gewone regel, niet de zwaardere
    ok("zonder verwijzing geldt de normale regel", "ZWAARDER" not in blok)

    # =========================================================
    # 4: directe verwijzingen
    # =========================================================

    print("\n===== 4: DIRECTE VERWIJZINGEN =====\n")

    cases = [
        ("open hem opnieuw", "hem"),
        ("doe die maar opnieuw", "die"),
        ("nogmaals", "nogmaals"),
        ("herhaal dat", "herhaal"),
        ("dezelfde nog een keer", "dezelfde"),
        ("sluit het af", "het"),
        ("nog een keer proberen", "opnieuw"),
    ]

    for vraag, verwacht in cases:

        gevonden = detect_conversation_reference(vraag)

        ok(f"{vraag!r} herkent {verwacht!r}", verwacht in gevonden)

    ok("een gewone vraag is geen verwijzing",
       detect_conversation_reference("wat is mijn gpu") == [])

    ok("'opnieuw' is een sterke verwijzing",
       has_conversation_reference("open hem opnieuw", {}) is True)
    ok("'nogmaals' is een sterke verwijzing",
       has_conversation_reference("nogmaals") is True)
    ok("'hem' zonder context telt niet",
       has_conversation_reference("open hem", {}) is False)
    ok("'hem' mÃ©t context telt wel",
       has_conversation_reference("open hem", CTX) is True)

    # Het blok zegt het expliciet
    blok = build_memory_context("open het programma opnieuw",
                                context=CTX, history=[])

    ok("het blok meldt de verwijzing", "verwijst naar iets uit dit gesprek" in blok)
    ok("het blok zegt dat blok 1 zwaarder weegt", "ZWAARDER" in blok)
    ok("het blok noemt de woorden uit de vraag", "opnieuw" in blok)

    # =========================================================
    # 5: context weegt zwaarder dan een oudere memory
    # =========================================================

    print("\n===== 5: CONTEXT ZWAARDER DAN OUDE MEMORY =====\n")

    ctx_conflict = {
        "last_command": "open kladblok",
        "last_result": "",
        "last_action": "",
        "last_calculation": "",
        "last_program": "kladblok",
        "last_file": "",
        "last_website": "",
        "last_ha_entity": "",
        "last_ha_domain": "",
        "last_ha_name": "",
        "pending_choice": None,
    }

    mem.remember("actief_programma", "word", category="apparaten")

    blok = build_memory_context(
        "open het actieve programma opnieuw",
        context=ctx_conflict, history=[],
    )

    ok("de context staat erbij", "kladblok" in blok)
    ok("het blok zegt dat het gesprek zwaarder weegt", "ZWAARDER" in blok)
    ok("het geheugen staat er ook nog in",
       "WAT IK OVER JOU WEET" in blok)

    items = rank_context_items("open het actieve programma opnieuw", ctx_conflict)

    ok("de context levert treffers", len(items) >= 1)
    ok("het programma staat bovenaan", items[0]["field"] == "last_program")
    ok("elk contextveld krijgt een score", all(i["score"] > 0 for i in items))

    # Het gewicht per veld werkt
    ok("de waarde letterlijk in de vraag scoort extra",
       _score_context_item("open kladblok", "Laatste opdracht", "open kladblok", 1.0)
       > _score_context_item("open iets anders", "Laatste opdracht", "open kladblok", 1.0))

    ok("een lege waarde scoort 0",
       _score_context_item("open kladblok", "Laatste opdracht", "", 1.0) == 0.0)

    # Relevantie-aflopend gesorteerd
    ok("context is aflopend gesorteerd",
       [i["score"] for i in items] == sorted([i["score"] for i in items], reverse=True))

    # =========================================================
    # 6: dubbele informatie
    # =========================================================

    print("\n===== 6: DUBBELE INFORMATIE =====\n")

    mem.remember("blad_programma", "kladblok", category="apparaten")

    # Dezelfde waarde staat in de context Ã©n in het geheugen
    dubbel_ctx = dict(ctx_conflict)
    dubbel_ctx["last_result"] = ""

    # Vraag naar het programma: dan komt blad_programma mee.
    memories = mem.get_relevant_memory("open het blad programma")

    ok("de dubbele memory is opgehaald",
       any(i["key"] == "blad_programma" for i in memories))

    kept = drop_duplicate_memories(memories, [
        {"value": "kladblok"}
    ], [])

    ok("een memory met dezelfde waarde als de context wordt weggelaten",
       "blad_programma" not in [i["key"] for i in kept])

    # Tegenover het gesprek: de kleur staat als zin in de geschiedenis
    kleur_memories = mem.get_relevant_memory("mijn kleur")

    kept = drop_duplicate_memories(kleur_memories, [], [
        {"content": "de kleur is blauw"}
    ])

    ok("een memory die in het gesprek voorkomt wordt weggelaten",
       "favoriete_kleur" not in [i["key"] for i in kept])

    # Niet op sleutel: een vraag in de geschiedenis is geen dubbeling
    gpu_memories = mem.get_relevant_memory("mijn gpu")

    kept = drop_duplicate_memories(gpu_memories, [], [
        {"content": "wat is mijn gpu"}
    ])

    ok("een vraag in de geschiedenis haalt de memory niet weg",
       "gpu" in [i["key"] for i in kept])

    # Korte waarden blijven staan (geen betekenis als zoekterm)
    mem.remember("kort_fact", "ja", category="algemeen")
    kort = mem.get_relevant_memory("kort_fact")

    ok("een korte waarde wordt nooit als dubbeling weggehaald",
       "kort_fact" in [i["key"] for i in drop_duplicate_memories(
           kort, [{"value": "ja"}], [])])

    # In het volledige blok staat het niet dubbel
    blok = build_memory_context(
        "open het blad programma", context=dubbel_ctx, history=[]
    )

    ok("het gecombineerde blok noemt 'kladblok' maar Ã©Ã©n keer",
       blok.count("kladblok") <= 1)

    # =========================================================
    # 7: bestaande context-velden blijven werken
    # =========================================================

    print("\n===== 7: BESTAANDE CONTEXT-VELDEN =====\n")

    velden = {
        "last_command": "open kladblok",
        "last_result": "Kladblok geopend",
        "last_action": "program_started:Kladblok",
        "last_calculation": "10 + 5 = 15",
        "last_program": "kladblok",
        "last_file": "rapport.docx",
        "last_website": "nu.nl",
        "last_ha_entity": "woonkamer_lamp",
        "last_ha_domain": "light",
        "last_ha_name": "Woonkamerlamp",
        "pending_choice": None,
    }

    # Elk contextveld is vindbaar met een natuurlijke vraag.
    veld_vragen = {
        "last_command": "open kladblok nog eens",
        "last_result": "wat was het resultaat",
        "last_action": "welke actie was dat",
        "last_calculation": "wat was de laatste berekening",
        "last_program": "welk programma stond open",
        "last_file": "welk bestand was dat",
        "last_website": "welke website was dat",
        "last_ha_entity": "zet de woonkamer_lamp aan",
    }

    for veld, vraag in veld_vragen.items():

        items = rank_context_items(vraag, velden)

        ok(f"{veld} wordt herkend", any(i["field"] == veld for i in items))

    # last_ha_domain en last_ha_name zijn geen eigen velden, maar
    # details die bij last_ha_entity horen.
    ok("last_ha_domain is geen apart veld",
       "last_ha_domain" not in [i["field"] for i in rank_context_items(
           "licht", velden)])

    items = rank_context_items("woonkamer_lamp", velden)

    ok("de HA-domeinnaam staat bij het apparaat",
       any("light" in i["value"] for i in items))

    # pending_choice blijft zichtbaar
    met_pending = dict(velden)
    met_pending["pending_choice"] = {"kind": "memory_update"}

    blok = build_memory_context("mijn kleur", context=met_pending)

    ok("een openstaande vraag wordt gemeld", "wacht" in blok)

    # Lege en None-waarden worden genegeerd
    leeg = {
        "last_command": "", "last_result": None, "last_action": "   ",
        "last_calculation": "", "last_program": "", "last_file": "",
        "last_website": "", "last_ha_entity": "", "last_ha_domain": "",
        "last_ha_name": "", "pending_choice": None,
    }

    ok("lege en None-contextvelden geven geen items",
       rank_context_items("open kladblok", leeg) == [])

    # De HA-domeinnaam wordt meegenomen
    items = rank_context_items("woonkamer_lamp", velden)

    ok("het HA-domein staat bij het apparaat",
       "light" in (items[0]["value"] if items else ""))

    # =========================================================
    # 8: het blok komt aan bij de AI en de Agent
    # =========================================================

    print("\n===== 8: AANKOMST BIJ AI EN AGENT =====\n")

    import core.ai as ai
    import core.agent as agent

    # Vanaf hier wordt niets meer weggeschreven naar het echte
    # conversation.json of memory.json van de gebruiker.
    _conversation_patch = patch.object(ai, "_save_conversation", lambda: None)
    _conversation_patch.start()

    gevangen = {}

    class FakeBericht:
        content = "Antwoord van het model."
        tool_calls = None

    class FakeOllama:

        @staticmethod
        def chat(model=None, messages=None, format=None, **kwargs):
            gevangen["messages"] = messages
            return type("R", (), {"message": FakeBericht()})()

    def system_tekst(messages):
        return "\n".join(
            str(m.get("content", ""))
            for m in (messages or [])
            if m.get("role") == "system"
        )

    # Let op: ask_ai schrijft normaal naar conversation.json; dat
    # gebeurt hier niet.
    with patch.object(ai, "ollama", FakeOllama), \
         patch.object(ai, "_save_conversation", lambda: None):

        ai.current_context.update(CTX)
        ai.conversation_history.clear()
        ai.conversation_history.extend(HISTORY)

        try:
            ai.ask_ai("open het programma opnieuw")
        except Exception:
            pass

        messages = gevangen.get("messages") or []
        system = system_tekst(messages)

        ok("de AI krijgt het gecombineerde blok",
           "JARVIS-CONTEXT EN GEHEUGEN" in system)
        ok("de AI ziet het gesprek", "kladblok" in system)
        ok("de AI ziet dat het gesprek zwaarder weegt", "ZWAARDER" in system)
        ok("er is geen los ACTUELE JARVIS-CONTEXT meer",
           "ACTUELE JARVIS-CONTEXT" not in system)
        ok("er is geen los JARVIS-GEHEUGEN-blok meer",
           "JARVIS-GEHEUGEN (wat ik over" not in system)
        ok("de verwijzingsregels voor tools zijn er nog",
           "verwijzen normaal naar het laatste programma" in system)

        # De vraag zelf blijft de laatste gebruikersboodschap
        ok("de vraag blijft de laatste user-message",
           messages and messages[-1].get("role") == "user")

        # De geschiedenis staat er één keer in: via _chat_history
        ok("de geschiedenis wordt niet dubbel toegevoegd",
           system.count("open kladblok") <= 2)

    # Agent
    import core.brain as brain

    with patch.object(agent, "ollama", FakeOllama), \
         patch.object(agent, "_live_ha_devices", lambda: ""):

        agent_berichten = {}

        def _capture(model=None, messages=None, format=None, **kwargs):
            agent_berichten["messages"] = messages
            return type("R", (), {"message": FakeBericht()})()

        FakeOllama.chat = staticmethod(_capture)

        ai.current_context.update(CTX)

        try:
            brain.agent._generate_plan("open het programma opnieuw")
        except Exception:
            pass

        messages = agent_berichten.get("messages") or []
        system = system_tekst(messages)

        ok("de agent krijgt het gecombineerde blok",
           "JARVIS-CONTEXT EN GEHEUGEN" in system)
        ok("de agent ziet geen los ACTUELE JARVIS-CONTEXT",
           "ACTUELE JARVIS-CONTEXT" not in system)
        ok("de agent ziet dat het gesprek zwaarder weegt", "ZWAARDER" in system)

    # =========================================================
    # 9: backwards compatibility
    # =========================================================

    print("\n===== 9: BACKWARDS COMPATIBILITY =====\n")

    ok("get_context() bestaat nog", isinstance(ai.get_context(), str))
    ok("get_context() toont het programma nog",
       "kladblok" in ai.get_context())
    ok("update_context() werkt nog", ai.update_context(last_program="kladblok") is None)
    ok("current_context is nog een dict", isinstance(ai.current_context, dict))
    ok("conversation_history is nog een lijst",
       isinstance(ai.conversation_history, list))

    ok("_chat_history() geeft nog role/content",
       all({"role", "content"} <= set(m) for m in ai._chat_history()))

    ok("build_memory_context werkt zonder question (leeg, want geen overlap)",
       build_memory_context("", context=CTX) == "")

    ok("build_memory_context overleeft een None-vraag",
       build_memory_context(None, context={}) == "")

    ok("build_memory_context heeft default limieten",
       build_memory_context("mijn kleur", context=CTX) != "")

    ok("max_memories werkt", "Coldplay" not in
       build_memory_context("mijn kleur muziek", context={}, max_memories=0))

    ok("max_context_items werkt",
       len(rank_context_items("kladblok programma", CTX, max_items=1)) <= 1)

    ok("max_history werkt",
       len(_recent_history(HISTORY * 5, max_turns=2)) <= 2)

    ok("_normalize maakt tekst vergelijkbaar",
       _normalize("Klad-Blok!  ") == "klad blok")

    ok("_recent_history slaat ongeldige regels over",
       _recent_history([{"role": "user"}, "geen dict", {}], max_turns=5) == [])

    ok("_recent_history kapt lange berichten af",
       all(len(c) <= 165 for _, c in _recent_history(
           [{"role": "user", "content": "x" * 500}], max_turns=5)))

    ok("het oude losse geheugenpad bestaat nog",
       "Coldplay" in mem.relevant_memory_prompt("mijn favoriete band"))
    ok("get_relevant_memory bestaat nog",
       any(i["key"] == "gpu" for i in mem.get_relevant_memory("mijn gpu")))

    # Het geheugen zelf is niet beschadigd door het ophalen
    ok("memory.json is nog geldig",
       mem.recall("favoriete_kleur") == "blauw")
    ok("usage wordt bijgehouden",
       mem.get_entry("gpu", category="pc").get("usage_count", 0) > 0)

    ok("priority blijft ongewijzigd",
       mem.get_entry("gpu", category="pc").get("priority") == 1.0)

    # Herstel de context voor de andere tests
    ai.update_context(pending_choice=None)
    ai.conversation_history.clear()

    _conversation_patch.stop()

# Bestanden opruimen
for leftover in (path, path + ".bak", path + ".lock", path + ".corrupt"):
    try:
        os.remove(leftover)
    except OSError:
        pass

shutil.rmtree(work, ignore_errors=True)

store.reset_cache()

# Het echte gespreksbestand mag onveranderd zijn gebleven.
if _real_conversation_existed and os.path.exists(_real_conversation):
    same = (open(_real_conversation, "rb").read() == _real_conversation_before)
    print("  info: conversation.json onveranderd:", same)

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)
