"""
Browser control via keyboard shortcuts en zoek-URL's.
Geen browser-specifieke API nodig: werkt met elke browser.

Fase 12: uitgebreid met UIA-lezing van browserinhoud.
"""
import re
import time
import webbrowser
from urllib.parse import quote_plus

from actions.media import _INPUT, INPUT_KEYBOARD, KEYEVENTF_KEYUP

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_T = 0x54
VK_W = 0x57
VK_L = 0x4C
VK_F5 = 0x74
VK_F12 = 0x7B
VK_RETURN = 0x0D

TIMEOUT = 3
BROWSER_NAMES = ("brave", "chrome", "edge", "firefox", "opera", "vivaldi")

SEARCH_URLS = {
    "youtube": "https://www.youtube.com/results?search_query=",
    "google": "https://www.google.com/search?q=",
    "bing": "https://www.bing.com/search?q=",
    "wikipedia": "https://nl.wikipedia.org/wiki/Speciaal:Zoeken?search=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "reddit": "https://www.reddit.com/search/?q=",
    "github": "https://github.com/search?q=",
    "twitter": "https://twitter.com/search?q=",
}


import ctypes
import ctypes.wintypes as wintypes


def _press_key(vk):

    down = _INPUT()
    down.type = INPUT_KEYBOARD
    down.ki.wVk = vk

    up = _INPUT()
    up.type = INPUT_KEYBOARD
    up.ki.wVk = vk
    up.ki.dwFlags = KEYEVENTF_KEYUP

    events = (_INPUT * 2)(down, up)
    ctypes.windll.user32.SendInput(2, events, ctypes.sizeof(_INPUT))
    time.sleep(0.05)


def _press_combo(vk_modifier, vk_key):

    for vk in (vk_modifier, vk_key):
        down = _INPUT()
        down.type = INPUT_KEYBOARD
        down.ki.wVk = vk
        ctypes.windll.user32.SendInput(1, ctypes.pointer(down), ctypes.sizeof(_INPUT))
        time.sleep(0.01)

    for vk in (vk_key, vk_modifier):
        up = _INPUT()
        up.type = INPUT_KEYBOARD
        up.ki.wVk = vk
        up.ki.dwFlags = KEYEVENTF_KEYUP
        ctypes.windll.user32.SendInput(1, ctypes.pointer(up), ctypes.sizeof(_INPUT))
        time.sleep(0.01)

    time.sleep(0.05)


def browser_search(query, site="google"):
    site = site.lower().strip()

    base_url = SEARCH_URLS.get(site)

    if not base_url:
        base_url = SEARCH_URLS["google"]
        site = "google"

    url = base_url + quote_plus(query)
    webbrowser.open(url)

    return f"Ik zoek '{query}' op {site}."


def browser_back():
    _press_combo(VK_MENU, VK_LEFT)
    return "Terug naar vorige pagina."


def browser_forward():
    _press_combo(VK_MENU, VK_RIGHT)
    return "Vooruit naar volgende pagina."


def browser_refresh():
    _press_key(VK_F5)
    return "Pagina ververst."


def browser_new_tab():
    _press_combo(VK_CONTROL, VK_T)
    return "Nieuw tabblad geopend."


def browser_close_tab():
    _press_combo(VK_CONTROL, VK_W)
    return "Tabblad gesloten."


def browser_focus_address_bar():
    _press_combo(VK_CONTROL, VK_L)
    return "Adresbalk geselecteerd."


# =============================================================
# BROWSER READING (Fase 12)
# Leest de huidige browserinhoud via UIA (Accessibility API).
# Werkt met alle Chromium-browsers (Brave, Chrome, Edge, Opera)
# en Firefox.
# =============================================================

def _import_pywinauto():
    try:
        from pywinauto import Desktop
        return Desktop
    except ImportError:
        return None


def _find_browser_window():
    """Zoek het voorgrond-browservenster. Geeft het pywinauto venster-object."""
    Desktop = _import_pywinauto()
    if not Desktop:
        return None, {"ok": False, "status": "fout",
                      "error_type": "ui_automation_unavailable",
                      "error": "pywinauto is niet geinstalleerd."}

    desktop = Desktop(backend="uia")
    for w in desktop.windows():
        try:
            title = w.window_text() or ""
            if any(b in title.lower() for b in BROWSER_NAMES):
                return w, None
        except Exception:
            continue

    return None, {"ok": False, "status": "fout",
                  "error_type": "browser_niet_gevonden",
                  "error": "Ik vind geen browser-venster op het scherm."}


def get_browser_url():
    """Leest de URL van de huidige browser."""
    w, err = _find_browser_window()
    if err:
        return err

    try:
        w.set_focus()
        time.sleep(0.1)
        edits = w.descendants(control_type="Edit")
        url = ""
        for e in edits:
            txt = (e.window_text() or "")
            if "." in txt and "/" in txt:
                url = txt
                break
        if not url:
            url = (w.window_text() or "").split(" - ")[-1].strip()
        return {"ok": True, "status": "200", "url": url}
    except Exception as exc:
        return {"ok": False, "status": "fout", "error_type": "browser_lees_fout",
                "error": f"Kon de URL niet lezen: {exc}"}


def get_browser_title():
    """Leest de titel van de huidige browser."""
    w, err = _find_browser_window()
    if err:
        return err

    try:
        title = w.window_text() or ""
        return {"ok": True, "status": "200", "title": title}
    except Exception as exc:
        return {"ok": False, "status": "fout", "error_type": "browser_lees_fout",
                "error": f"Kon de titel niet lezen: {exc}"}


def get_browser_content(max_items=50):
    """Leest de zichtbare tekst van de huidige browserpagina via UIA."""
    w, err = _find_browser_window()
    if err:
        return err

    try:
        w.set_focus()
        time.sleep(0.2)
        texts = w.descendants(control_type="Text")
        content = []
        seen = set()
        for t in texts:
            txt = (t.window_text() or "").strip()
            if txt and len(txt) > 1 and txt not in seen:
                seen.add(txt)
                content.append(txt)
                if len(content) >= max_items:
                    break
        return {"ok": True, "status": "200", "content": content,
                "count": len(content)}
    except Exception as exc:
        return {"ok": False, "status": "fout", "error_type": "browser_lees_fout",
                "error": f"Kon de pagina-inhoud niet lezen: {exc}"}