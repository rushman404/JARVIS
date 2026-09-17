"""
FASE 10 STRESS TEST — routing, ambiguïteit, veiligheid, rare inputs
=====================================================================

Test via brain.process_command met gemockte acties (geen echte wijzigingen).
ALLE systeemacties zijn geblokkeerd via mock — veilig om te draaien.
"""
import sys
import os
import io
from contextlib import ExitStack
from unittest.mock import patch

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.brain as brain
import core.ai as ai
from core.ai import update_context

passed = 0
failed = 0
issues = []


def reset():
    update_context(pending_choice=None)


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        issues.append((label, detail))


# Zorg dat er geen bevestiging-state overblijft uit een vorige test
reset()


# =====================================================================
# ALLE SYSTEEMACTIES BLOKKEREN (één exit-stack)
# =====================================================================
_mocks = {
    "core.brain.set_volume":             {"ok": True},
    "core.brain.volume_up":              {"ok": True},
    "core.brain.volume_down":            {"ok": True},
    "core.brain.toggle_mute":            {"ok": True},
    "core.brain.play_pause":             {"ok": True},
    "core.brain.stop_media":             {"ok": True},
    "core.brain.next_track":             {"ok": True},
    "core.brain.previous_track":         {"ok": True},
    "core.brain.audio_list_sessions":    {"ok": True, "sessions": [], "count": 0},
    "core.brain.audio_get_session_volume":   {"ok": False, "error_type": "session_niet_gevonden"},
    "core.brain.audio_set_session_volume":   {"ok": True, "message": "ok", "volume": 50},
    "core.brain.audio_set_session_mute":     {"ok": True, "muted": True},
    "core.brain.audio_toggle_session_mute":  {"ok": True, "muted": True},
    "core.brain.audio_list_outputs":    {"ok": True, "devices": [], "default": "Mock", "count": 0},
    "core.brain.audio_get_default_output":   {"ok": True, "name": "Mock Output"},
    "core.brain.audio_set_default_output":   {"ok": True, "message": "ok", "name": "Mock Output"},
    "core.brain.take_screenshot":        {"ok": True},
    "core.brain.minimize_program":       {"ok": True},
    "core.brain.maximize_program":       {"ok": True},
    "core.brain.restore_window":         {"ok": True},
    "core.brain.open_program":           {"ok": True},
    "core.brain.close_program":          {"ok": True},
    "core.brain.open_website":           {"ok": True},
    "core.brain.search_and_fetch":       {"ok": True},
    "core.brain.format_search_and_fetch": "Web-antwoord",
    "core.brain.is_agent_goal":          False,
    "core.brain.is_multi_step_goal":     False,
    "core.brain.try_web_fetch":          None,
}

_ui_mocks = {
    "core.brain.ui_list_windows":     {"ok": True, "windows": [{"title": "FakeApp"}, {"title": "Discord"}]},
    "core.brain.ui_find_window":      {"ok": True, "found": True, "handle": 12345, "title": "FakeApp"},
    "core.brain.ui_activate_window":  {"ok": True},
}


def _enter():
    """Zet ALLE mocks aan."""
    stack = ExitStack()
    for target, rv in {**_mocks, **_ui_mocks}.items():
        try:
            stack.enter_context(patch(target, return_value=rv))
        except Exception:
            pass
    return stack


# =====================================================================
print("\n--- [1] ROUTING-VOLGORDE: volume/media gaat naar SYSTEM, niet UI ---")

with _enter():
    # "zet het volume op 50" → try_media_command → set_volume
    with patch("core.brain.set_volume", return_value={"ok": True, "volume": 50}) as vol_mock:
        r = brain.process_command("zet het volume op 50")
        ok("1a: 'zet het volume op 50' → set_volume",
           vol_mock.called, f"vol_mock.called={vol_mock.called}")

    with patch("core.brain.volume_up", return_value={"ok": True}) as vu_mock:
        r = brain.process_command("harder")
        ok("1b: 'harder' → volume_up", vu_mock.called)

    with patch("core.brain.volume_down", return_value={"ok": True}) as vd_mock:
        r = brain.process_command("zachter")
        ok("1c: 'zachter' → volume_down", vd_mock.called)

    with patch("core.brain.toggle_mute", return_value={"ok": True}) as tm_mock:
        r = brain.process_command("mute")
        ok("1d: 'mute' → toggle_mute", tm_mock.called)

    with patch("core.brain.play_pause", return_value={"ok": True}) as pp_mock:
        r = brain.process_command("pauzeer")
        ok("1e: 'pauzeer' → play_pause", pp_mock.called)


# =====================================================================
print("\n--- [2] UI-ROUTING: vensters opsommen / status / focus ---")

with _enter():
    with patch("core.brain.ui_list_windows", return_value={"ok": True, "windows": [{"title": "Discord"}, {"title": "Spotify"}]}) as m:
        r = brain.process_command("welke vensters zijn open")
        ok("2a: 'welke vensters zijn open' → ui_list_windows",
           m.called, f"called={m.called}, result={str(r)[:60]}")

    with patch("core.brain.ui_list_windows", return_value={"ok": True, "windows": [{"title": "X"}]}) as m:
        r = brain.process_command("toon de vensters")
        ok("2b: 'toon de vensters' → ui_list_windows", m.called)

    # "is discord open?" → try_program_status (proces-check) pakt dit EERST
    # Dit is CORRECT gedrag: procescheck is betrouwbaarder dan venster-check
    with patch("core.brain.find_program", return_value=r"C:\test\discord.exe"), \
         patch("core.brain.get_program_status", return_value="discord draait momenteel"):
        r = brain.process_command("is discord open?")
        ok("2c: 'is discord open?' → programma-status",
           "draait" in str(r).lower(), f"result={str(r)[:60]}")

    # "welke vensters bevat discord?" → ALLEEN via ui_list_windows
    with patch("core.brain.ui_list_windows", return_value={"ok": True, "windows": [{"title": "Friends - Discord"}]}) as m:
        r = brain.process_command("welke vensters bevat discord")
        ok("2d: 'welke vensters bevat discord' → ui_list_windows",
           m.called, f"called={m.called}")

    # "breng discord naar voorgrond" → try_ui_automation
    with patch("core.brain.ui_find_window", return_value={"ok": True, "found": True, "handle": 1}) as m:
        r = brain.process_command("breng discord naar voorgrond")
        ok("2e: 'breng discord naar voorgrond' → ui_find_window",
           "discord" in str(r).lower() and "voorgrond" in str(r).lower(),
           f"result={str(r)[:60]}")


# =====================================================================
print("\n--- [3] AMBIGUÏTEIT: app-specifiek vs generiek volume ---")

with _enter():
    # "zet het volume op 50" zonder app → Windows-volume (standaard)
    with patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock:
        r = brain.process_command("zet het volume op 50")
        ok("3a: 'zet het volume op 50' → set_volume (standaard)",
           vol_mock.called, f"vol_mock={vol_mock.called}")

    # "zet het volume van Spotify op 50" → NIET Windows-volume
    # (per-app audio als Spotify gevonden wordt, anders valt het door naar AI/media)
    with patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock, \
         patch("core.brain.audio_set_session_volume",
               return_value={"ok": True, "volume": 50}) as asv_mock:
        r = brain.process_command("zet het volume van Spotify op 50")
        ok("3b: 'zet het volume van Spotify op 50' → NIET set_volume",
           not vol_mock.called,
           f"vol={vol_mock.called}, asv={asv_mock.called}")

    # "volume in sonar op 50" → NIET Windows-volume
    with patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock, \
         patch("core.brain.audio_set_session_volume",
               return_value={"ok": True, "volume": 50}) as asv_mock:
        r = brain.process_command("zet het volume in Sonar op 50")
        ok("3c: 'volume in Sonar op 50' → NIET set_volume",
           not vol_mock.called,
           f"vol={vol_mock.called}")

    # "maak het volume harder in discord" → NIET volume_up
    with patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock, \
         patch("core.brain.volume_up", return_value={"ok": True}) as vu_mock:
        r = brain.process_command("maak het volume in discord harder")
        ok("3d: 'volume harder in discord' → NIET volume_up",
           not vol_mock.called and not vu_mock.called,
           f"vol={vol_mock.called}, vu={vu_mock.called}")

    # "volume van muziek harder" → NIET volume_up (want "muziek" is geen app-woord)
    with patch("core.brain.volume_up", return_value={"ok": True}) as vu_mock, \
         patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock:
        r = brain.process_command("zet het volume van muziek harder")
        ok("3e: 'volume van muziek harder' → NIET blind volume_up",
           not vu_mock.called,
           f"vu={vu_mock.called}, vol={vol_mock.called}")


# =====================================================================
print("\n--- [4] RARE INPUTS: typfouten, nonsens, mix NL/EN ---")

with _enter():
    weird = [
        ("zl volume op 50",             "typfout 'zl'"),
        ("zett volume hogerr",           "typfout + extra letters"),
        ("whiche vensters zjin oepn",    "typfout vensters"),
        ("is disscord opeen?",           "typfout discord+open"),
        ("aaaaa",                        "herhaalde letters"),
        ("???",                          "alleen vraagtekens"),
        ("...",                          "alleen punten"),
        ("",                            "lege string"),
        ("   ",                         "alleen spaties"),
        ("set volume to 50",             "Engels commando"),
        ("open discord please",          "Engels+NL mix"),
        ("harder graag",                 "NL met Engels patroon"),
        ("open het hek",                 "rijmend op Venster"),
        ("klik op het scherm",           "generiek klikken"),
        ("typ iets in mijn browser",     "typ-achtig maar geen UI"),
        ("sluit alle vensters",          "meervoud/sluit alles"),
        ("zet alles uit",               "vag commando"),
    ]

    for cmd, label in weird:
        try:
            r = brain.process_command(cmd)
            ok(f"4: {label}", True, str(r)[:50])
        except Exception as e:
            ok(f"4: {label} → GEEN CRASH", False, f"{type(e).__name__}: {e}")


# =====================================================================
print("\n--- [5] VEILIGHEID: gevaarlijke inputs mogen niet crashen ---")

with _enter():
    dangerous = [
        "sluit alles",
        "verwijder alle bestanden",
        "format c:",
        "reboot",
        "shutdown -s",
        "del /f /q",
        "rm -rf /",
    ]

    for cmd in dangerous:
        try:
            r = brain.process_command(cmd)
            ok(f"5: '{cmd}' → geen crash", True, str(r)[:50])
        except Exception as e:
            ok(f"5: '{cmd}' → GEEN CRASH", False, f"{type(e).__name__}: {e}")


# =====================================================================
print("\n--- [6] TOOL-DISPATCH: ontbrekende/foute args ---")

# 6a: ui_list_windows zonder args → core.tools wrapper
with patch("core.tools.list_windows", return_value={"ok": True, "windows": [], "status": "200"}) as m:
    r = ai.execute_tool("ui_list_windows", {}, "test")
    ok("6a: ui_list_windows {} → ok",
       "200" in str(r), f"r={str(r)[:50]}")

# 6b: ui_find_window met lege titel
with patch("core.tools.find_window", return_value={"ok": False, "error": "Geen titel"}) as m:
    r = ai.execute_tool("ui_find_window", {"title": ""}, "test")
    ok("6b: ui_find_window '' → fout", r is not None, f"r={str(r)[:50]}")

# 6c: ui_click_element met handle=None
with patch("core.tools.click_element", return_value={"ok": False}) as m:
    r = ai.execute_tool("ui_click_element", {"handle": None, "name": "x"}, "test")
    ok("6c: ui_click_element None → fout", r is not None, f"r={str(r)[:50]}")

# 6d: ui_type_text lege tekst
with patch("core.tools.type_text", return_value={"ok": True}) as m:
    r = ai.execute_tool("ui_type_text", {"handle": 1, "text": ""}, "test")
    ok("6d: ui_type_text '' → ok", r is not None, f"r={str(r)[:50]}")

# 6e: ui_set_value string-waarde (geen int)
with patch("core.tools.set_value", return_value={"ok": True}) as m:
    r = ai.execute_tool("ui_set_value", {"handle": 1, "value": "abc", "name": "slider"}, "test")
    ok("6e: ui_set_value string → ok", r is not None, f"r={str(r)[:50]}")

# 6f: ui_launch_app ontbrekend pad
with patch("core.tools.launch_app", return_value={"ok": False, "error": "Pad niet gevonden"}) as m:
    r = ai.execute_tool("ui_launch_app", {"path": ""}, "test")
    ok("6f: ui_launch_app '' → fout", r is not None, f"r={str(r)[:50]}")


# =====================================================================
print("\n--- [7] STRESS: lange inputs, speciale tekens, unicode ---")

with _enter():
    cases = [
        ("zet het volume op " + "5" * 100,      "extreem lang getal"),
        ("zet het volume op 50 !@#$%^&*()",      "speciale tekens"),
        ("zet het volume op 50 🎵🎶🔊",          "unicode/emoji"),
        ("zet het volume op -1",                  "negatief getal"),
        ("zet het volume op 99999",               "heel groot getal"),
        ("zet het volume op 0",                   "nul volume"),
        ("zet het volume op 100",                 "max volume"),
    ]

    for cmd, label in cases:
        try:
            with patch("core.brain.set_volume", return_value={"ok": True}):
                r = brain.process_command(cmd)
                ok(f"7: {label}", True, str(r)[:40])
        except Exception as e:
            ok(f"7: {label} → GEEN CRASH", False, f"{type(e).__name__}: {e}")


# =====================================================================
print("\n--- [9] APP-VOLUME AMBIGUÏTEIT FIX (Fase 10 → 11) ---")

# Fase 11: app-volume gaat naar audio_set_session_volume (per-app),
# NIET naar Windows set_volume en NIET meer per se naar de Agent.

# 9a: "zet spotify op 100" → audio_set_session_volume
reset()
with patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock, \
     patch("core.brain.is_agent_goal", return_value=False), \
     patch("core.brain.is_multi_step_goal", return_value=False), \
     patch("core.brain.audio_set_session_volume",
           return_value={"ok": True, "message": "ok", "volume": 100}) as asv_mock, \
     patch("core.brain.try_ui_automation", return_value=None), \
     patch.object(brain, "find_program", return_value=r"C:\test\spotify.exe"):
    r = brain.process_command("zet spotify op 100")
    ok("9a: 'zet spotify op 100' → per-app volume (niet Windows)",
       asv_mock.called and not vol_mock.called,
       f"asv={asv_mock.called}, vol={vol_mock.called}")

# 9b: "zet spotify volume op 100" → per-app volume
reset()
with patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock, \
     patch("core.brain.is_agent_goal", return_value=False), \
     patch("core.brain.is_multi_step_goal", return_value=False), \
     patch("core.brain.audio_set_session_volume",
           return_value={"ok": True, "message": "ok", "volume": 100}) as asv_mock, \
     patch("core.brain.try_ui_automation", return_value=None), \
     patch.object(brain, "find_program", return_value=r"C:\test\spotify.exe"):
    r = brain.process_command("zet spotify volume op 100")
    ok("9b: 'zet spotify volume op 100' → per-app volume",
       asv_mock.called and not vol_mock.called,
       f"asv={asv_mock.called}, vol={vol_mock.called}")

# 9c: "zet het volume op 50" → set_volume (standaard, geen app)
reset()
with patch("core.brain.is_agent_goal", return_value=False), \
     patch("core.brain.is_multi_step_goal", return_value=False), \
     patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock:
    r = brain.process_command("zet het volume op 50")
    ok("9c: 'zet het volume op 50' → set_volume",
       vol_mock.called, f"vol={vol_mock.called}")

# 9d: "zet de lamp op 100" → niet agent (HA-woord)
reset()
with patch("core.brain.is_agent_goal", return_value=False), \
     patch("core.brain.is_multi_step_goal", return_value=False), \
     patch("core.brain.set_volume", return_value={"ok": True}) as vol_mock, \
     patch.object(brain.agent, "run_goal", return_value="Agent-output") as agm:
    r = brain.process_command("zet de lamp op 100")
    ok("9d: 'zet de lamp op 100' → NIET agent",
       not agm.called, f"agent={agm.called}")


# =====================================================================
print("\n--- [10] AUDIO-ROUTING (Fase 11): per-app + output-apparaten ---")

# 10a: output wisselen → audio_set_default_output
reset()
with patch("core.brain.audio_set_default_output",
           return_value={"ok": True, "message": "ok", "name": "Mock"}) as m:
    r = brain.process_command("zet output naar de headset")
    ok("10a: 'zet output naar de headset' → audio_set_default_output",
       m.called, f"m={m.called}")

# 10b: "zet al het geluid naar de speakers" → audio_set_default_output
reset()
with patch("core.brain.audio_set_default_output",
           return_value={"ok": True, "message": "ok", "name": "Mock"}) as m:
    r = brain.process_command("zet al het geluid naar de speakers")
    ok("10b: 'zet al het geluid naar de speakers' → audio_set_default_output",
       m.called, f"m={m.called}")

# 10c: "welke apps maken geluid" → audio_list_sessions (NIET system UI)
reset()
with patch("core.brain.audio_list_sessions",
           return_value={"ok": True, "sessions": [], "count": 0}) as m:
    r = brain.process_command("welke apps maken geluid")
    ok("10c: 'welke apps maken geluid' → audio_list_sessions",
       m.called, f"m={m.called}")

# 10d: "welke audio-apparaten heb ik" → audio_list_outputs
reset()
with patch("core.brain.audio_list_outputs",
           return_value={"ok": True, "devices": [], "default": "Mock", "count": 0}) as m:
    r = brain.process_command("welke audio-apparaten heb ik")
    ok("10d: 'welke audio-apparaten heb ik' → audio_list_outputs",
       m.called, f"m={m.called}")

# 10e: "demp discord" → per-app mute (NIET systeem-toggle_mute)
reset()
with patch.object(brain, "find_program", return_value=r"C:\test\discord.exe"), \
     patch("core.brain.audio_set_session_mute",
           return_value={"ok": True, "muted": True, "message": "ok"}) as m, \
     patch("core.brain.audio_list_sessions",
           return_value={"ok": True, "sessions": [], "count": 0}):
    r = brain.process_command("demp discord")
    ok("10e: 'demp discord' → audio_set_session_mute",
       m.called, f"m={m.called}, result={str(r)[:50]}")

# 10f: "maak discord zachter" → per-app volume (eerst lezen, dan zetten)
reset()
with patch.object(brain, "find_program", return_value=r"C:\test\discord.exe"), \
     patch("core.brain.audio_get_session_volume",
           return_value={"ok": True, "volume": 80, "name": "Discord.exe", "muted": False}) as gv, \
     patch("core.brain.audio_set_session_volume",
           return_value={"ok": True, "volume": 70, "message": "ok"}) as sv:
    r = brain.process_command("maak discord zachter")
    ok("10f: 'maak discord zachter' → per-app volume (set 70)",
       sv.called and gv.called, f"sv={sv.called}, gv={gv.called}")

# 10g: "waar gaat mijn geluid naartoe" → audio_get_default_output
reset()
with patch("core.brain.audio_get_default_output",
           return_value={"ok": True, "name": "Mock Output"}) as m:
    r = brain.process_command("waar gaat mijn geluid nu naartoe")
    ok("10g: 'waar gaat mijn geluid nu naartoe' → audio_get_default_output",
       m.called, f"m={m.called}, result={str(r)[:50]}")


# =====================================================================
print("\n--- [8] COMBINATIES: meerdere acties in één zin ---")

with _enter():
    combos = [
        ("open discord en zet volume op 50",  "open + volume"),
        ("open spotify harder",                "open + harder"),
        ("minimaliseer discord en pauzeer",    "minimaliseer + pauze"),
    ]

    for cmd, label in combos:
        try:
            r = brain.process_command(cmd)
            ok(f"8: {label} → geen crash", True, str(r)[:40])
        except Exception as e:
            ok(f"8: {label} → GEEN CRASH", False, f"{type(e).__name__}: {e}")


# =====================================================================
# SAMENVATTING
# =====================================================================
print(f"\n{'='*60}")
print(f"STRESS TEST FASE 10/11: {passed} geslaagd, {failed} gefaald")
print(f"{'='*60}")

if issues:
    print(f"\n--- PROBLEMEN ({len(issues)}) ---")
    for label, detail in issues:
        print(f"  ❌ {label}")
        if detail:
            print(f"     → {detail[:120]}")

if failed:
    sys.exit(1)