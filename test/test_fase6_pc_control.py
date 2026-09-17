import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import core.brain as brain
import core.ai as ai
from core.ai import update_context

print("=" * 60)
print("FASE 6: PC CONTROL 2.0 — COMPREHENSIVE TOOL TEST")
print("=" * 60)

PASS = 0
FAIL = 0


def check(name, expected, got):
    global PASS, FAIL
    ok = expected == got
    PASS += ok
    FAIL += (not ok)
    print(f"{'✅' if ok else '❌'} [{name}] expected={expected!r}, got={got!r}")
    return ok


def reset():
    update_context(pending_choice=None)


# =====================================================================
# SECTION 1: Browser search
# =====================================================================
print("\n--- Browser Search ---")

browser_calls = []

def fake_browser_search(query, site="google"):
    browser_calls.append(("search", query, site))
    return f"search:{query}:{site}"

reset()
with patch("core.brain.browser_search", side_effect=fake_browser_search), \
     patch("core.brain.search_and_fetch", return_value={"ok": True}) as fake_web, \
     patch("core.brain.format_search_and_fetch", return_value="Web-agent antwoord"):
    browser_calls.clear()
    result = brain.process_command("zoek op youtube naar spider-man")
    check("browser_search_youtube", ("search", "spider-man", "youtube"), browser_calls[0] if browser_calls else None)
    check("browser_search_youtube_ret", "search:spider-man:youtube", result)

    # Fase 9: "google naar X" gaat nu naar de WEB-AGENT (niet de browser),
    # omdat JARVIS zelf kan zoeken en het antwoord kan lezen.
    browser_calls.clear()
    result = brain.process_command("google naar nieuwe films")
    check("google_naar_web_agent_geen_browser", None, browser_calls[0] if browser_calls else None)
    check("google_naar_web_agent_zoekt", True, fake_web.called)
    check("google_naar_web_agent_ret", "Web-agent antwoord", result)

    browser_calls.clear()
    result = brain.process_command("zoek op wikipedia naar python")
    check("browser_search_wiki", ("search", "python", "wikipedia"), browser_calls[0] if browser_calls else None)

    browser_calls.clear()
    result = brain.process_command("zoek bing naar news")
    check("browser_search_bing", ("search", "news", "bing"), browser_calls[0] if browser_calls else None)


# =====================================================================
# SECTION 2: Browser navigation
# =====================================================================
print("\n--- Browser Navigation ---")

nav_calls = []

def fake_nav(*args, **kwargs):
    nav_calls.append(args[0] if args else None)
    return f"nav:{args[0] if args else 'unknown'}"

reset()
with patch("core.brain.browser_back", side_effect=lambda: fake_nav("back")):
    with patch("core.brain.browser_forward", side_effect=lambda: fake_nav("forward")):
        with patch("core.brain.browser_refresh", side_effect=lambda: fake_nav("refresh")):
            with patch("core.brain.browser_new_tab", side_effect=lambda: fake_nav("new_tab")):
                with patch("core.brain.browser_close_tab", side_effect=lambda: fake_nav("close_tab")):

                    nav_calls.clear()
                    brain.process_command("ga terug")
                    check("nav_back", "back", nav_calls[0] if nav_calls else None)

                    nav_calls.clear()
                    brain.process_command("vooruit")
                    check("nav_forward", "forward", nav_calls[0] if nav_calls else None)

                    nav_calls.clear()
                    brain.process_command("ververs")
                    check("nav_refresh", "refresh", nav_calls[0] if nav_calls else None)

                    nav_calls.clear()
                    brain.process_command("nieuw tabblad")
                    check("nav_new_tab", "new_tab", nav_calls[0] if nav_calls else None)

                    nav_calls.clear()
                    brain.process_command("sluit tabblad")
                    check("nav_close_tab", "close_tab", nav_calls[0] if nav_calls else None)


# =====================================================================
# SECTION 3: Known site open
# =====================================================================
print("\n--- Known Site Open ---")

site_calls = []

def fake_open_website(url):
    site_calls.append(url)
    return True

reset()
with patch("core.brain.open_website", side_effect=fake_open_website):
    site_calls.clear()
    brain.process_command("open youtube")
    check("open_youtube", "https://www.youtube.com", site_calls[0] if site_calls else None)

    site_calls.clear()
    brain.process_command("open google")
    check("open_google", "https://www.google.com", site_calls[0] if site_calls else None)


# =====================================================================
# SECTION 4: Program status
# =====================================================================
print("\n--- Program Status ---")

status_calls = []

def fake_status(program):
    status_calls.append(program)
    return f"status:{program}:draait"

reset()
with patch("core.brain.get_program_status", side_effect=fake_status):
    with patch("core.brain.find_program", return_value=["C:\\Program Files\\Spotify\\spotify.exe"]):

        status_calls.clear()
        result = brain.process_command("draait spotify?")
        check("status_draait", "spotify", status_calls[0] if status_calls else None)
        check("status_ret", "status:spotify:draait", result)

        status_calls.clear()
        result = brain.process_command("is discord geopend")
        check("status_is_open", "discord", status_calls[0] if status_calls else None)


# =====================================================================
# SECTION 5: Program restart
# =====================================================================
print("\n--- Program Restart ---")

restart_calls = []

def fake_restart(program):
    restart_calls.append(program)
    return f"restart:{program}"

reset()
with patch("core.brain.restart_program", side_effect=fake_restart):
    with patch("core.brain.find_program", return_value=["C:\\Program Files\\Spotify\\spotify.exe"]):

        restart_calls.clear()
        result = brain.process_command("herstart spotify")
        check("restart_herstart", "spotify", restart_calls[0] if restart_calls else None)
        check("restart_ret", "restart:spotify", result)

        restart_calls.clear()
        result = brain.process_command("restart discord")
        check("restart_restart", "discord", restart_calls[0] if restart_calls else None)

        restart_calls.clear()
        result = brain.process_command("start spotify opnieuw")
        check("restart_opnieuw", "spotify", restart_calls[0] if restart_calls else None)


# =====================================================================
# SECTION 5b: "herstart de pc" must NOT trigger program restart
# =====================================================================
print("\n--- 'herstart de pc' stays power (not program restart) ---")

reset()
restart_calls.clear()
result = brain.process_command("herstart de pc")
check("restart_de_pc_not_program", None, restart_calls[0] if restart_calls else None)


# =====================================================================
# SECTION 6: Find program
# =====================================================================
print("\n--- Find Program ---")

find_calls = []

def fake_find_location(program):
    find_calls.append(program)
    return f"loc:C:\\{program}\\{program}.exe"

reset()
with patch("core.brain.find_program_location", side_effect=fake_find_location):
    with patch("core.brain.find_program", return_value=["dummy"]):

        find_calls.clear()
        result = brain.process_command("vind spotify")
        check("find_vind", "spotify", find_calls[0] if find_calls else None)

        find_calls.clear()
        result = brain.process_command("waar staat discord")
        check("find_waar", "discord", find_calls[0] if find_calls else None)


# =====================================================================
# SECTION 7: Open folder
# =====================================================================
print("\n--- Open Folder ---")

folder_calls = []

def fake_open_folder(location):
    folder_calls.append(location)
    return f"folder_opened:{location}"

reset()
with patch("core.brain.open_folder", side_effect=fake_open_folder):
    folder_calls.clear()
    result = brain.process_command("open de map downloads")
    check("folder_downloads", "downloads", folder_calls[0] if folder_calls else None)

    folder_calls.clear()
    result = brain.process_command("open de map documenten")
    check("folder_documenten", "documenten", folder_calls[0] if folder_calls else None)

    folder_calls.clear()
    result = brain.process_command("open downloads")
    check("folder_open_downloads", "downloads", folder_calls[0] if folder_calls else None)


# =====================================================================
# SECTION 8: Recent files
# =====================================================================
print("\n--- Recent Files ---")

recent_calls = []

def fake_recent(count=10):
    recent_calls.append(count)
    return "recent_list"

reset()
with patch("core.brain.get_recent_files", side_effect=fake_recent):
    recent_calls.clear()
    result = brain.process_command("recente bestanden")
    check("recent_files", True, len(recent_calls) == 1)
    check("recent_ret", "recent_list", result)


# =====================================================================
# SECTION 9: File search
# =====================================================================
print("\n--- File Search ---")

search_calls = []

def fake_search_files(query):
    search_calls.append(query)
    return f"search_result:{query}"

reset()
with patch("core.brain.search_files", side_effect=fake_search_files):
    search_calls.clear()
    result = brain.process_command("zoek naar notities.txt")
    check("file_search", "notities.txt", search_calls[0] if search_calls else None)

    search_calls.clear()
    result = brain.process_command("zoek mijn cv")
    check("file_search_cv", "cv", search_calls[0] if search_calls else None)


# =====================================================================
# SECTION 10: Rename file
# =====================================================================
print("\n--- Rename File ---")

rename_calls = []

def fake_rename(old, new):
    rename_calls.append((old, new))
    return f"renamed:{old}->{new}"

reset()
with patch("core.brain.rename_file", side_effect=fake_rename):
    rename_calls.clear()
    result = brain.process_command("hernoem notities naar notities_v2")
    check("rename_file", ("notities", "notities_v2"), rename_calls[0] if rename_calls else None)


# =====================================================================
# SECTION 11: AI tool definitions exist
# =====================================================================
print("\n--- AI Tool Definitions ---")

from core.ai import execute_tool as exec_tool

new_tools = [
    ("restart_program", {"program": "spotify"}),
    ("program_status", {"program": "spotify"}),
    ("find_program_location", {"program": "spotify"}),
    ("browser_search", {"query": "test", "site": "youtube"}),
    ("browser_back", {}),
    ("browser_forward", {}),
    ("browser_refresh", {}),
    ("browser_new_tab", {}),
    ("browser_close_tab", {}),
    ("rename_file", {"old_name": "a.txt", "new_name": "b.txt"}),
    ("open_folder", {"location": "downloads"}),
    ("search_files", {"query": "test"}),
    ("recent_files", {"count": 10}),
]

reset()
for tool_name, args in new_tools:
    try:
        result = exec_tool(tool_name, args, f"test {tool_name}")
        check(f"ai_tool_{tool_name}", True, result is not None and "Ik weet niet" not in str(result))
    except Exception as e:
        check(f"ai_tool_{tool_name}", "no_exception", f"EXCEPTION: {e}")


# =====================================================================
# SECTION 12: VALID_TOOL_NAMES in agent.py
# =====================================================================
print("\n--- Agent VALID_TOOL_NAMES ---")

from core.agent import VALID_TOOL_NAMES, TOOL_LIST_TEXT

expected_tools = [
    "restart_program",
    "program_status",
    "find_program_location",
    "browser_search",
    "browser_back",
    "browser_forward",
    "browser_refresh",
    "browser_new_tab",
    "browser_close_tab",
    "rename_file",
    "open_folder",
    "search_files",
    "recent_files",
]

for tool in expected_tools:
    check(f"agent_valid_{tool}", True, tool in VALID_TOOL_NAMES)


# =====================================================================
# SECTION 13: TOOL_LIST_TEXT contains new entries
# =====================================================================
print("\n--- TOOL_LIST_TEXT ---")

for tool in expected_tools:
    check(f"tool_list_{tool}", True, tool in TOOL_LIST_TEXT)


# =====================================================================
# SECTION 14: No regression — existing patterns still work
# =====================================================================
print("\n--- Regression: existing patterns ---")

reset()
result = brain.process_command("open discord")
check("regression_open_fallback", True, result is not None)


# =====================================================================
# SUMMARY
# =====================================================================
print("\n" + "=" * 60)
print(f"RESULTAAT: {PASS} geslaagd, {FAIL} gefaald")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
