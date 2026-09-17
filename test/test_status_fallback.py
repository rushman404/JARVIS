"""
JARVIS - Fase 12: Status + Fallback tests
===========================================

Test de Unified PC-status en de Fallback Chains (alles gemockt):

  [1] retry: primaire tool werkt -> done, geen fallback
  [2] retry: primaire tool faalt altijd -> failed
  [3] retry: primaire tool faalt, fallback werkt -> done + fallback_used
  [4] retry: fallback-args transformatie
  [5] retry: geen fallback gedefinieerd -> gewoon failed
  [6] pc_status: systeem + audio + browser in één dict
  [7] pc_status: audio-fout breekt niks op
  [8] pc_status: browser-fout breekt niks op
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import core.retry as retry
import actions.status as status

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}" + (f"  | {detail}" if detail else ""))


# ==============================================
# RETRY / FALLBACK CHAIN TESTS
# ==============================================

# [1] Primaire tool werkt
def runner_ok(tool, args, q):
    return "geslaagd"

r = retry.execute_with_retry(runner_ok, "ui_click_element", {}, "test", max_retries=1)
ok("1. tool werkt -> done, geen fallback",
   r["status"] == "done" and r.get("fallback_used") is None, str(r))

# [2] Primaire tool faalt altijd, geen fallback werktmissch
def runner_fail(tool, args, q):
    raise RuntimeError("kan niet")

r = retry.execute_with_retry(runner_fail, "bestaat_niet", {}, "test", max_retries=1)
ok("2. tool faalt altijd -> failed",
   r["status"] == "failed", str(r))

# [3] Primaire tool faalt, fallback werkt
def runner_with_fallback(tool, args, q):
    if tool == "browser_search":
        raise RuntimeError("browser kapot")
    if tool == "web_search":
        return "gezocht op web"
    raise RuntimeError(f"onbekend: {tool}")

r = retry.execute_with_retry(runner_with_fallback, "browser_search", {"query": "katten", "site": "youtube"},
                             "zoek katten", max_retries=1, use_fallbacks=True)
ok("3. fallback werkt -> done met fallback_used",
   r["status"] == "done" and r.get("fallback_used") == "web_search", str(r))

# [4] Fallback met transform_args
def runner_transform(tool, args, q):
    if tool == "browser_search":
        raise RuntimeError("browser kapot")
    if tool == "web_search":
        assert args.get("query") == "hondjes", str(args)
        return "gezocht op web"
    raise RuntimeError(f"onbekend: {tool}")

r = retry.execute_with_retry(runner_transform, "browser_search", {"query": "hondjes", "site": "youtube"},
                             "zoek hondjes", max_retries=1, use_fallbacks=True)
ok("4. fallback transform_args -> correcte args",
   r["status"] == "done" and r.get("fallback_used") == "web_search", str(r))

# [5] Geen fallback gedefinieerd -> gewoon failed
def runner_no_fallback(tool, args, q):
    raise RuntimeError("mislukt")

r = retry.execute_with_retry(runner_no_fallback, "nooit_bestaand", {}, "test",
                             max_retries=1, use_fallbacks=True)
ok("5. geen fallback -> failed",
   r["status"] == "failed", str(r))


# ==============================================
# PC STATUS TESTS
# ==============================================

base_system = MagicMock(
    cpu_info=lambda: {"naam": "AMD Ryzen"},
    ram_info=lambda: {"totaal": 32, "vrij": 16},
    disk_info=lambda: {"vrij": 100, "totaal": 500},
    battery_info=lambda: {"percentage": 80, "stekker": True},
    os_info=lambda: {"systeem": "Windows", "release": "11", "machine": "AMD64"},
    uptime=lambda: {"dagen": 1, "uren": 2, "minuten": 3},
)
base_audio = MagicMock(
    get_default_output=lambda: {"ok": True, "name": "Headset"},
    list_sessions=lambda: {"ok": True, "sessions": [
        {"name": "Spotify.exe", "volume": 50, "muted": False},
        {"name": "Discord.exe", "volume": 80, "muted": True},
    ]},
)
base_browser = MagicMock(
    get_browser_url=lambda: {"ok": True, "url": "https://www.google.com"},
    get_browser_title=lambda: {"ok": True, "title": "Google"},
)

# [6] Volledige status
import actions.system as sys_mod
import actions.audio as aud_mod
import actions.browser as br_mod

_orig_sys = {n: getattr(sys_mod, n) for n in ("cpu_info", "ram_info", "disk_info", "battery_info", "os_info", "uptime")}
_orig_aud = {n: getattr(aud_mod, n) for n in ("get_default_output", "list_sessions")}
_orig_br  = {n: getattr(br_mod, n) for n in ("get_browser_url", "get_browser_title")}

sys_mod.cpu_info = base_system.cpu_info
sys_mod.ram_info = base_system.ram_info
sys_mod.disk_info = base_system.disk_info
sys_mod.battery_info = base_system.battery_info
sys_mod.os_info = base_system.os_info
sys_mod.uptime = base_system.uptime
aud_mod.get_default_output = base_audio.get_default_output
aud_mod.list_sessions = base_audio.list_sessions
br_mod.get_browser_url = base_browser.get_browser_url
br_mod.get_browser_title = base_browser.get_browser_title

try:
    r = status.get_pc_status()
    ok("6. pc_status: volledig overzicht",
       r.get("ok") and "systeem" in r and "audio" in r and "browser" in r, str(r)[:100])
    ok("6b. pc_status: CPU naam + browser URL opgehaald",
       r["systeem"]["cpu"] == "AMD Ryzen" and r["browser"]["url"].startswith("https:"),
       str(r)[:120])
finally:
    for n, v in _orig_sys.items(): setattr(sys_mod, n, v)
    for n, v in _orig_aud.items(): setattr(aud_mod, n, v)
    for n, v in _orig_br.items(): setattr(br_mod, n, v)

# [7] Audio-fout breekt niks op
sys_mod.cpu_info = base_system.cpu_info
sys_mod.ram_info = base_system.ram_info
sys_mod.disk_info = base_system.disk_info
sys_mod.battery_info = base_system.battery_info
sys_mod.os_info = base_system.os_info
sys_mod.uptime = base_system.uptime
aud_mod.get_default_output = MagicMock(side_effect=Exception("COM fout"))
aud_mod.list_sessions = base_audio.list_sessions
br_mod.get_browser_url = base_browser.get_browser_url
br_mod.get_browser_title = base_browser.get_browser_title

try:
    r = status.get_pc_status()
    ok("7. pc_status: audio-fout geen crash",
       isinstance(r.get("audio"), str) and "fout" in r.get("audio", ""), str(r.get("audio"))[:80])
finally:
    for n, v in _orig_sys.items(): setattr(sys_mod, n, v)
    for n, v in _orig_aud.items(): setattr(aud_mod, n, v)
    for n, v in _orig_br.items(): setattr(br_mod, n, v)

# [8] Browser-fout breekt niks op
sys_mod.cpu_info = base_system.cpu_info
sys_mod.ram_info = base_system.ram_info
sys_mod.disk_info = base_system.disk_info
sys_mod.battery_info = base_system.battery_info
sys_mod.os_info = base_system.os_info
sys_mod.uptime = base_system.uptime
aud_mod.get_default_output = base_audio.get_default_output
aud_mod.list_sessions = base_audio.list_sessions
br_mod.get_browser_url = MagicMock(side_effect=Exception("UIA fout"))
br_mod.get_browser_title = base_browser.get_browser_title

try:
    r = status.get_pc_status()
    ok("8. pc_status: browser-fout geen crash",
       isinstance(r.get("browser"), str) and "fout" in r.get("browser", ""), str(r.get("browser"))[:80])
finally:
    for n, v in _orig_sys.items(): setattr(sys_mod, n, v)
    for n, v in _orig_aud.items(): setattr(aud_mod, n, v)
    for n, v in _orig_br.items(): setattr(br_mod, n, v)


print(f"\n--- FASE 12 STATUS/FALLBACK: {passed} geslaagd, {failed} gefaald ---\n")