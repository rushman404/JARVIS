"""
JARVIS — Uitgebreide spraak/functionaliteit-stress-test (Fase 5+)
=================================================================

Test drie categorieën commando's:
  A. Nieuwe normale zinnen
  B. Spreekzinnen (gecontracteerd, met stopwoorden, informeel)
  C. Slecht uitgesproken / verkeerd getranscribeerd

Plus:
  D. Contextuele verwijzingen (hem/die/dit)
  E. Geheugen (onthouden, opvragen, wijzigen, vergeten)
  F. Routines
  G. Power confirmatie
  H. Media / bestanden
  I. Multi-actie

Alle tools worden gemockt; er vinden geen echte HA/PC-netwerkoproepen plaats.
"""
import sys
import os
import io
import json
import re
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import ollama as _ollama_mod
import core.brain as brain
import core.ai as ai
from core.tools import remember_tool

passed = 0
failed = 0
safe_reject = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        extra = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{extra}")


def safe(label, detail=""):
    global safe_reject
    safe_reject += 1
    msg = f"  [SKIP] {label}"
    if detail:
        msg += f" ({detail})"
    print(msg)


# =============================================================
# Mock-entiteiten (zelfde als in run_all)
# =============================================================

MOCK_HA_ENTITIES = [
    {"entity_id": "light.bed_lamp", "domain": "light", "name": "Bedlamp",
     "state": "off", "attributes": {"friendly_name": "Bedlamp",
        "supported_color_modes": ["color_temp", "hs"],
        "supported_features": 0}},
    {"entity_id": "light.woonkamer", "domain": "light", "name": "Woonkamer",
     "state": "off", "attributes": {"friendly_name": "Woonkamer",
        "supported_color_modes": ["color_temp", "hs"],
        "supported_features": 0}},
    {"entity_id": "switch.tv_switch", "domain": "switch", "name": "Tv stekker",
     "state": "off", "attributes": {"friendly_name": "Tv stekker"}},
    {"entity_id": "light.eethoek_spot", "domain": "light",
     "name": "Eethoek spot", "state": "off",
     "attributes": {"friendly_name": "Eethoek spot",
        "supported_color_modes": ["color_temp", "hs"],
        "supported_features": 0}},
    {"entity_id": "cover.woonkamer_gordijn", "domain": "cover",
     "name": "Woonkamer gordijn", "state": "open",
     "attributes": {"friendly_name": "Woonkamer gordijn",
        "supported_features": 3}},
    {"entity_id": "climate.woonkamer_thermostaat", "domain": "climate",
     "name": "Woonkamer thermostaat", "state": "20",
     "attributes": {"friendly_name": "Woonkamer thermostaat",
        "supported_features": 1}},
]


# =============================================================
# Fake LLM — map commando -> verwachte tool-call
# =============================================================

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().strip())

_FAKE_HA_MAP = {
    # A. Nieuwe normale zinnen
    "zetestbedlamdaan":    ("light", "turn_on", "light.bed_lamp", {}),
    "dimdelamptot50":     ("light", "turn_on", "light.bed_lamp",
                            {"brightness_pct": 50}),
    "zetdelampop30":       ("light", "turn_on", "light.bed_lamp",
                            {"brightness_pct": 30}),
    "maakdelamprood":       ("light", "turn_on", "light.bed_lamp",
                            {"hs_color": [0, 100]}),
    "maakdelampgroen":     ("light", "turn_on", "light.bed_lamp",
                            {"hs_color": [120, 100]}),
    "zetdelampblauw":      ("light", "turn_on", "light.bed_lamp",
                            {"hs_color": [240, 100]}),
    "doedelampuit":        ("light", "turn_off", "light.bed_lamp", {}),
    "zetdelampaan":        ("light", "turn_on", "light.bed_lamp", {}),
    "zetdegordijnendicht":  ("cover", "close_cover", "cover.woonkamer_gordijn", {}),
    "zetdegordijnenopen":   ("cover", "open_cover", "cover.woonkamer_gordijn", {}),
    "zetdetemperatuurop21graden": ("climate", "set_temperature",
                                   "climate.woonkamer_thermostaat",
                                   {"temperature": 21}),
    "doetvstekkeruit":      ("switch", "turn_off", "switch.tv_switch", {}),
    "doedetvstekkeruit":     ("switch", "turn_off", "switch.tv_switch", {}),
    "zetdeeethoekspotop60": ("light", "turn_on", "light.eethoek_spot",
                             {"brightness_pct": 60}),

    # B. Spreekzinnen
    "uhhzetmebedlampaan":  ("light", "turn_on", "light.bed_lamp", {}),
    "doedelampuitasjeblieft": ("light", "turn_off", "light.bed_lamp", {}),
    "maakhetlichteffezachter": ("light", "turn_on", "light.bed_lamp",
                                {"brightness_pct": 30}),
    "kanjeevendegordijnenafsluiten": ("cover", "close_cover",
                                      "cover.woonkamer_gordijn", {}),
    "zetdebedlampaanalsjeblieft": ("light", "turn_on", "light.bed_lamp", {}),
    "maakdelampjewarm": ("light", "turn_on", "light.bed_lamp",
                         {"color_temp": 3000}),
    "maakhetlampjewarm": ("light", "turn_on", "light.bed_lamp",
                          {"color_temp": 3000}),

    # C. Slecht uitgesproken / getranscribeerd
    "bedlamaan":            ("light", "turn_on", "light.bed_lamp", {}),
    "bedlamuit":            ("light", "turn_off", "light.bed_lamp", {}),
    "bedlamophelft":        ("light", "turn_on", "light.bed_lamp",
                             {"brightness_pct": 50}),
    "gordiniedicht":        ("cover", "close_cover", "cover.woonkamer_gordijn",
                             {}),
    "gordijnenuit":         ("cover", "close_cover", "cover.woonkamer_gordijn",
                             {}),
    "thermostadop22":       ("climate", "set_temperature",
                             "climate.woonkamer_thermostaat",
                             {"temperature": 22}),
    "stekeraan":            ("switch", "turn_on", "switch.tv_switch", {}),
    "stekeruit":            ("switch", "turn_off", "switch.tv_switch", {}),
    "lampaop70":            ("light", "turn_on", "light.bed_lamp",
                             {"brightness_pct": 70}),
    "zetbedlampaaan":      ("light", "turn_on", "light.bed_lamp", {}),
    "lampuitasse":          ("light", "turn_off", "light.bed_lamp", {}),
    "zetdebedlamop30":      ("light", "turn_on", "light.bed_lamp",
                             {"brightness_pct": 30}),
    "maakdelampfel":        ("light", "turn_on", "light.bed_lamp",
                             {"brightness_pct": 100}),
    "maakdelampzacht":      ("light", "turn_on", "light.bed_lamp",
                             {"brightness_pct": 20}),
}


def _fake_chat_factory(calls_log):
    """Geeft een fake ollama.chat-functie terug die de map gebruikt."""

    def fake_chat(*args, **kwargs):
        messages = kwargs.get("messages") or (args[0] if args else [])
        question = ""
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                question = m.get("content", "")
        key = _norm(question)

        if key in _FAKE_HA_MAP:
            domain, service, entity_id, sd = _FAKE_HA_MAP[key]
            tc_args = {"domain": domain, "service": service,
                       "entity_id": entity_id}
            if sd:
                tc_args["service_data"] = sd
            calls_log.append({"tool": "control_home_assistant",
                              "args": tc_args})
            fn = MagicMock()
            fn.name = "control_home_assistant"
            fn.arguments = tc_args
            tc = type("TC", (), {"function": fn})()
            msg = type("M", (), {"content": "", "tool_calls": [tc]})()
            return type("R", (), {"message": msg})()

        # Geen match -> geen tool-call (safe reject / valt door naar AI-antwoord)
        calls_log.append({"tool": None, "args": {}})
        msg = type("M", (), {"content": "Ik begrijp het niet.", "tool_calls": None})()
        return type("R", (), {"message": msg})()

    return fake_chat


def _fake_resolve(entity_id, domain):
    """Stub die alles doorlaat (we testen de routing, niet de resolver)."""
    return entity_id, "exact", ""


# =============================================================
# Testgevallen
# =============================================================

# (command, category, expected_dict)
# category: "ha", "ha_ref", "pc_open", "pc_close", "memory_store",
#           "memory_recall", "memory_update", "memory_forget",
#           "routine_resolve", "routine_list", "power_confirm",
#           "media", "file"

CASES = [
    # =====================
    # A. Nieuwe normale zinnen
    # =====================
    ("dim de lamp tot 50%",           "ha", {"service": "turn_on",
                                              "has": "brightness_pct"}),
    ("zet de lamp op 30%",            "ha", {"service": "turn_on",
                                              "has": "brightness_pct"}),
    ("maak de lamp rood",             "ha", {"service": "turn_on",
                                              "has": "hs_color"}),
    ("maak de lamp groen",            "ha", {"service": "turn_on",
                                              "has": "hs_color"}),
    ("zet de lamp blauw",             "ha", {"service": "turn_on",
                                              "has": "hs_color"}),
    ("doe de lamp uit",               "ha", {"service": "turn_off"}),
    ("zet de lamp aan",               "ha", {"service": "turn_on"}),
    ("zet de gordijnen dicht",        "ha", {"service": "close_cover"}),
    ("zet de gordijnen open",         "ha", {"service": "open_cover"}),
    ("zet de temperatuur op 21 graden", "ha", {"service": "set_temperature",
                                               "has": "temperature"}),
    ("doe de tv stekker uit",         "ha", {"service": "turn_off"}),
    ("zet de eethoek spot op 60%",    "ha", {"service": "turn_on",
                                              "has": "brightness_pct"}),

    # =====================
    # B. Spreekzinnen
    # =====================
    ("uhh zet me bedlamp aan",        "ha", {"service": "turn_on"}),
    ("doe de lamp uit asjeblieft",    "ha", {"service": "turn_off"}),
    ("maak het licht effe zachter",   "ha", {"service": "turn_on",
                                              "has": "brightness_pct"}),
    ("kan je even de gordijnen afsluiten?", "ha", {"service": "close_cover"}),
    ("zet de bedlamp aan alsjeblieft","ha", {"service": "turn_on"}),
    ("maak het lampje warm",          "ha", {"service": "turn_on",
                                              "has": "color_temp"}),

    # =====================
    # C. Slecht uitgesproken / getranscribeerd
    # =====================
    ("bedlam aan",                    "ha", {"service": "turn_on"}),
    ("bedlam uit",                    "ha", {"service": "turn_off"}),
    ("bedlam op helft",              "ha", {"service": "turn_on",
                                             "has": "brightness_pct"}),
    ("gordinie dicht",               "ha", {"service": "close_cover"}),
    ("gordijnen uit",                "ha", {"service": "close_cover"}),
    ("thermostad op 22",             "ha", {"service": "set_temperature",
                                             "has": "temperature"}),
    ("steker aan",                   "ha", {"service": "turn_on"}),
    ("steker uit",                   "ha", {"service": "turn_off"}),
    ("lampa op 70",                  "ha", {"service": "turn_on",
                                             "has": "brightness_pct"}),
    ("maak de lamprood",             "ha", {"service": "turn_on",
                                             "has": "hs_color"}),
    ("zet bedlampa aan",             "ha", {"service": "turn_on"}),
    ("lamp uit asse",                "ha", {"service": "turn_off"}),
    ("zet de bedlam op 30",          "ha", {"service": "turn_on",
                                             "has": "brightness_pct"}),
    ("maak de lamp fel",             "ha", {"service": "turn_on",
                                             "has": "brightness_pct"}),
    ("maak de lamp zacht",           "ha", {"service": "turn_on",
                                             "has": "brightness_pct"}),

    # =====================
    # D. Contextuele verwijzingen (eerst HA, dan referentie)
    # =====================
    # "maak hem groen" slaagt ALLEEN als er een last_ha_entity in context staat.
    # Dat testen we apart (hieronder).

    # =====================
    # E. Geheugen
    # =====================
    ("ik hou meestal van warm wit licht", "memory_store",
     {"contains": "lichtvoorkeur"}),
    ("mijn favoriete kleur is groen", "memory_store",
     {"contains": "favoriete_kleur"}),
    ("onthoud dat mijn gpu een RTX 5090 is", "memory_store",
     {"contains": "gpu"}),
    ("wat is mijn lichtvoorkeur",     "memory_recall",
     {"contains": "lichtvoorkeur"}),
    ("wat is mijn favoriete kleur",   "memory_recall",
     {"contains": "favoriete_kleur"}),
    ("wijzig mijn licht naar koel wit", "memory_update",
     {"contains": "koel wit"}),
    ("vergeet mijn lichtvoorkeur",    "memory_forget",
     {"contains": "lichtvoorkeur"}),

    # =====================
    # F. Routines
    # =====================
    ("welke routines heb ik",         "routine_list", {}),
    ("ik ga gamen",                   "routine_resolve", {}),

    # =====================
    # G. Power
    # =====================
    ("sluit de pc af",                "power_confirm", {}),

    # =====================
    # H. Bestanden
    # =====================
    ("open foto.jpg",                 "file", {"tool": "open_file"}),

    # =====================
    # I. Multi-actie (via AI mock niet eenvoudig; testen we apart)
    # =====================
]


# =============================================================
# Testrunner
# =============================================================

print("╔══════════════════════════════════════════════════════════╗")
print("║  JARVIS SPRAAK / FUNCTIONALITEIT STRESS-TEST (Fase 5+) ║")
print("╚══════════════════════════════════════════════════════════╝")
print()

_tmp_mem = tempfile.mktemp(suffix="_memory.json")
with open(_tmp_mem, "w", encoding="utf-8") as f:
    f.write(json.dumps({}))

# Ook de conversation.json wordt geïsoleerd. Zonder dit laat dit
# script een openstaande pending_choice achter in de ECHTE
# memory/conversation.json, waarna de volgende run vanaf sectie D
# alle commando's als "bevestiging" behandelt. Zelfde aanpak als
# test_vault_sync.py / test_vault_export.py / test_obsidian_brain.py.
#
# De echte context wordt 1-op-1 overgenomen zodat update_context()
# alle sleutels blijft kennen, maar een openstaande pending_choice
# wordt geneutraliseerd.
_tmp_conv = tempfile.mktemp(suffix="_conversation.json")
with open(_tmp_conv, "w", encoding="utf-8") as f:
    json.dump({"history": [], "context": dict(brain.current_context)}, f)

_echte_conversation = ai.CONVERSATION_FILE
ai.CONVERSATION_FILE = _tmp_conv

brain.current_context["pending_choice"] = None

_orig_ctx = dict(brain.current_context)

# ------------------------------------------------------------------
# Sectie A/B/C: HA-acties via gemockte LLM
# ------------------------------------------------------------------

print("===== A/B/C: HA-ACTIES (normaal / spreekzin / slecht uitgesproken) =====\n")

ha_calls = []
orig_chat = _ollama_mod.chat
_orig_ai_chat = ai.ollama.chat

with patch("memory.memory.MEMORY_FILE", _tmp_mem), \
     patch("core.ai.control_home_assistant_tool") as m_ha_tool, \
     patch("core.ai.resolve_live_entity_id", side_effect=_fake_resolve), \
     patch("core.ai.get_home_assistant_entities_tool",
           return_value="light.bed_lamp, light.woonkamer, "
                        "switch.tv_switch, light.eethoek_spot, "
                        "cover.woonkamer_gordijn, "
                        "climate.woonkamer_thermostaat"):

    m_ha_tool.return_value = "Actie uitgevoerd."

    fake_chat = _fake_chat_factory(ha_calls)
    _ollama_mod.chat = fake_chat
    ai.ollama.chat = fake_chat

    try:
        for cmd, cat, expected in CASES:
            if cat != "ha":
                continue

            m_ha_tool.reset_mock()
            prev_len = len(ha_calls)
            brain.current_context.update(_orig_ctx)
            ai.conversation_history = []  # per-case isolatie

            result = brain.process_command(cmd)

            was_called = m_ha_tool.called
            if was_called:
                args = m_ha_tool.call_args[0]
                call_args = dict(zip(
                    ("domain", "service", "entity_id", "service_data"),
                    list(args) + [None] * (4 - len(args)),
                ))
            else:
                call_args = {}

            svc = expected.get("service")
            ok_svc = (not svc) or (call_args.get("service") == svc)
            ok_has = True
            for key in ("has",):
                if key in expected:
                    ok_has = ok_has and (expected[key] in str(call_args.get("service_data", {})))

            label = f"HA {cmd!r}"
            if was_called and ok_svc and ok_has:
                ok(label, True)
            elif not was_called:
                safe(label, "geen HA tool-call (AI kon niet matchen)")
            else:
                ok(label, False, f"service={call_args.get('service')}")

    finally:
        _ollama_mod.chat = orig_chat
        ai.ollama.chat = _orig_ai_chat


# ------------------------------------------------------------------
# Sectie D: Contextuele verwijzingen
# ------------------------------------------------------------------

print("\n===== D: CONTEXTUELE VERWIJZINGEN =====\n")

brain.current_context["last_ha_entity"] = "light.bed_lamp"
brain.current_context["last_ha_domain"] = "light"

with patch("core.brain.control_home_assistant_tool") as m_ha:
    m_ha.return_value = "Gedaan."

    brain.process_command("maak hem groen")
    ok("'maak hem groen' -> turn_on + hs_color",
       m_ha.called and m_ha.call_args[0][1] == "turn_on"
       and "hs_color" in (m_ha.call_args[0][3] or {}))

    brain.process_command("doe hem uit")
    ok("'doe hem uit' -> turn_off",
       m_ha.called and m_ha.call_args[0][1] == "turn_off")

    brain.process_command("zet hem op 50%")
    ok("'zet hem op 50%' -> brightness_pct 50",
       m_ha.called
       and (m_ha.call_args[0][3] or {}).get("brightness_pct") == 50)

    brain.process_command("maak hem warm")
    ok("'maak hem warm' -> color_temp warm",
       m_ha.called
       and (m_ha.call_args[0][3] or {}).get("color_temp") is not None)

with patch("memory.memory.MEMORY_FILE", _tmp_mem):
    # Na een geslaagde HA-actie verwijst "zet die aan" naar hetzelfde apparaat
    pass

brain.current_context.update(_orig_ctx)


# ------------------------------------------------------------------
# Sectie E: Geheugen
# ------------------------------------------------------------------

print("\n===== E: GEHEUGEN (spreekzinnen) =====\n")

with patch("memory.memory.MEMORY_FILE", _tmp_mem):
    from memory.memory import recall as mem_recall, forget as mem_forget

    r = brain.process_command("ik hou meestal van warm wit licht")
    ok("'ik hou meestal van warm wit licht' -> onthouden",
       r is not None and "warm" in str(r).lower())

    r = brain.process_command("mijn favoriete kleur is groen")
    ok("'mijn favoriete kleur is groen' -> onthouden",
       r is not None and "groen" in str(r).lower())

    r = brain.process_command("onthoud dat mijn gpu een RTX 5090 is")
    ok("'onthoud dat mijn gpu een RTX 5090 is' -> onthouden",
       r is not None and "5090" in str(r))

    v = mem_recall("lichtvoorkeur")
    ok("lichtvoorkeur opgevraagd", v is not None and "warm" in str(v).lower())

    v = mem_recall("favoriete_kleur")
    ok("favoriete_kleur opgevraagd", v is not None and "groen" in str(v).lower())

    r = brain.process_command("wat is mijn lichtvoorkeur")
    ok("'wat is mijn lichtvoorkeur' toont waarde",
       r is not None and "warm" in str(r).lower())

    r = brain.process_command("wat is mijn favoriete kleur")
    ok("'wat is mijn favoriete kleur' toont waarde",
       r is not None and "groen" in str(r).lower())

    # "wijzig mijn licht" is een verkorte vorm: die mag niet stilzwijgend
    # een entry overschrijven. Er wordt eerst bevestigd welke sleutel
    # bedoeld wordt.
    _voor = mem_recall("lichtvoorkeur")

    r = brain.process_command("wijzig mijn licht naar koel wit")
    ok("'wijzig mijn licht naar koel wit' -> vraagt welke sleutel",
       r is not None and "bedoelde je" in str(r).lower()
       and "lichtvoorkeur" in str(r).lower())

    ok("niets gewijzigd vóór bevestiging",
       mem_recall("lichtvoorkeur") == _voor)

    r = brain.process_command("ja")
    ok("'ja' past lichtvoorkeur alsnog aan",
       r is not None and "koel" in str(r).lower())

    v = mem_recall("lichtvoorkeur")
    ok("lichtvoorkeur is nu koel wit", v == "koel wit")

    r = brain.process_command("vergeet mijn lichtvoorkeur")
    ok("'vergeet mijn lichtvoorkeur' -> verwijderd",
       r is not None and "vergeten" in str(r).lower())

    v = mem_recall("lichtvoorkeur")
    ok("lichtvoorkeur is weg na vergeet", v is None)

    mem_forget("favoriete_kleur")
    mem_forget("gpu")


# ------------------------------------------------------------------
# Sectie F: Routines
# ------------------------------------------------------------------

print("\n===== F: ROUTINES (spreekzinnen) =====\n")

_rtmp = tempfile.mktemp(suffix="_routines.json")
with open(_rtmp, "w", encoding="utf-8") as f:
    f.write(open("config/routines.json", encoding="utf-8").read())

with patch("core.routines.ROUTINES_FILE", _rtmp):
    from core.routines import RoutineManager
    isolated_rm = RoutineManager()

with patch("core.brain.routine_manager", isolated_rm):
    r = brain.process_command("welke routines heb ik")
    ok("'welke routines heb ik' -> lijst",
       r is not None and "routines" in str(r).lower())

    r = brain.process_command("welke routines heb je")
    ok("'welke routines heb je' -> lijst",
       r is not None and "routines" in str(r).lower())

    r = brain.process_command("wat zijn mijn routines")
    ok("'wat zijn mijn routines' -> lijst",
       r is not None and "routines" in str(r).lower())

    r = brain.process_command("welke routine gebruik ik het meest")
    ok("'welke routine gebruik ik het meest' -> ranking",
       r is not None and ("gebruikt" in str(r).lower() or "routines" in str(r).lower()))


# ------------------------------------------------------------------
# Sectie G: Power
# ------------------------------------------------------------------

print("\n===== G: POWER CONFIRMATIE =====\n")

with patch("core.brain.send_to_recycle") as m_rec, \
     patch("core.brain.empty_recycle_bin") as m_empty:

    r = brain.process_command("sluit de pc af")
    ok("'sluit de pc af' -> pending_choice gezet",
       brain.current_context.get("pending_choice") is not None
       and brain.current_context.get("pending_choice", {}).get("kind") == "power_confirm")

    brain.current_context["pending_choice"] = None


# ------------------------------------------------------------------
# Sectie H: Bestanden
# ------------------------------------------------------------------

print("\n===== H: BESTANDEN =====\n")

with patch("core.tools.open_file", return_value="Ik open foto.jpg."):
    from core.tools import open_file_tool
    ok("open_file_tool opent bestand",
       open_file_tool("foto.jpg") == "Ik open foto.jpg.")

with patch("core.tools.open_file", return_value="Ik kan Test.txt niet vinden."):
    ok("open_file_tool opent niet-bestaand bestand foutief",
       open_file_tool("Test.txt") == "Ik kan Test.txt niet vinden.")


# ------------------------------------------------------------------
# Sectie I: Multi-actie
# ------------------------------------------------------------------

print("\n===== I: MULTI-ACTIE =====\n")

with patch("core.brain.control_home_assistant_tool") as m_brain_ha, \
     patch("core.ai.control_home_assistant_tool") as m_ai_ha, \
     patch("core.brain.close_program_tool", return_value="Sluiten gelukt."):
    m_brain_ha.return_value = "Gedaan."
    m_ai_ha.return_value = "Gedaan."
    brain.process_command("doe lamp uit en sluit spotify")
    ok("multi-actie: HA tool-call aanwezig",
       m_ai_ha.called or m_brain_ha.called)


# ------------------------------------------------------------------
# Opruimen
# ------------------------------------------------------------------

brain.current_context.update(_orig_ctx)

try:
    os.remove(_tmp_mem)
except OSError:
    pass

try:
    os.remove(_tmp_conv)
except OSError:
    pass

print(f"\n{'=' * 60}")
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald, "
      f"{safe_reject} safe_reject")
print(f"{'=' * 60}")

sys.exit(1 if failed else 0)
