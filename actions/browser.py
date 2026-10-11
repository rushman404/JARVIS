"""
Browser control via keyboard shortcuts en zoek-URL's.
Geen browser-specifieke API nodig: werkt met elke browser.

Fase 12: uitgebreid met UIA-lezing van browserinhoud.
"""
import re
import time
import webbrowser
import psutil
from urllib.parse import quote_plus

try:
    import win32process
    import win32gui

    HAS_WIN32 = True
except ImportError:
    win32process = win32gui = None
    HAS_WIN32 = False

from actions.media import _INPUT, INPUT_KEYBOARD, KEYEVENTF_KEYUP
from core.result_validation import ToolResult

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_T = 0x54
VK_W = 0x57
VK_L = 0x4C
VK_F5 = 0x74

BROWSER_PROCESSES = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe")
BROWSER_TITLE_WORDS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")

def is_foreground_browser():
    """Controleert of het voorgrondvenster een browser is."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name().lower() in BROWSER_PROCESSES
    except Exception:
        return False

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

    items = []
    return ToolResult(
        ok=True,
        message=f"Ik heb {len(items)} resultaten gevonden.",
        data={"items": items, "query": query, "site": site, "url": url},
    )


def is_fullscreen():
    """Controleert of het voorgrondvenster fullscreen is (bijv. een game)."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        rect = win32gui.GetWindowRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        
        # Schermresolutie via User32
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        
        if w >= sw and h >= sh:
            style = win32gui.GetWindowLong(hwnd, -16) # GWL_STYLE
            if not (style & 0x00C00000): # Geen WS_CAPTION
                return True
        return False
    except:
        return False


def ensure_browser_focus():
    """Zet de browser op de voorgrond als dat veilig is."""
    if is_foreground_browser():
        return True
    
    if is_fullscreen():
        return False
    
    # Probeer de browser te vinden en te focussen
    w, _ = _find_browser_window()
    if w:
        try:
            w.set_focus()
            time.sleep(0.1)
            return is_foreground_browser()
        except:
            pass
    return False


def browser_back():
    if not ensure_browser_focus():
        return ToolResult(ok=False, message="De browser staat niet op de voorgrond.", error_kind="niet_op_voorgrond")
    _press_combo(VK_MENU, VK_LEFT)
    return ToolResult(ok=True, message="Terug naar de vorige pagina.")


def browser_forward():
    if not ensure_browser_focus():
        return ToolResult(ok=False, message="De browser staat niet op de voorgrond.", error_kind="niet_op_voorgrond")
    _press_combo(VK_MENU, VK_RIGHT)
    return ToolResult(ok=True, message="Naar de volgende pagina.")


def browser_refresh():
    if not ensure_browser_focus():
        return ToolResult(ok=False, message="De browser staat niet op de voorgrond.", error_kind="niet_op_voorgrond")
    _press_key(VK_F5)
    return ToolResult(ok=True, message="Pagina ververst.")


def browser_new_tab():
    if not ensure_browser_focus():
        return ToolResult(ok=False, message="De browser staat niet op de voorgrond.", error_kind="niet_op_voorgrond")
    _press_combo(VK_CONTROL, VK_T)
    return ToolResult(ok=True, message="Nieuw tabblad geopend.")


def browser_close_tab():
    if not ensure_browser_focus():
        return ToolResult(ok=False, message="De browser staat niet op de voorgrond.", error_kind="niet_op_voorgrond")
    _press_combo(VK_CONTROL, VK_W)
    return ToolResult(ok=True, message="Tabblad gesloten.")


def browser_focus_address_bar():
    if not ensure_browser_focus():
        return ToolResult(ok=False, message="De browser staat niet op de voorgrond.", error_kind="niet_op_voorgrond")
    _press_combo(VK_CONTROL, VK_L)
    return ToolResult(ok=True, message="Adresbalk geselecteerd.")


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
    """Zoek een browservenster. Geeft het pywinauto venster-object."""
    Desktop = _import_pywinauto()
    if not Desktop:
        return None, ToolResult(ok=False, message="pywinauto niet geïnstalleerd.", error_kind="ui_automation_unavailable")
    
    desktop = Desktop(backend="uia")
    for w in desktop.windows():
        try:
            # PID van venster ophalen
            thread_id, pid = win32process.GetWindowThreadProcessId(w.handle)
            process = psutil.Process(pid)
            if process.name().lower() in BROWSER_PROCESSES:
                return w, None
        except Exception:
            # Proces-lookup kan falen (rechten/COM). Val terug op de titel
            # zodat een browservenster alsnog herkend wordt.
            try:
                title = (w.window_text() or "").lower()
                if any(name in title for name in BROWSER_TITLE_WORDS):
                    return w, None
            except Exception:
                continue
            continue
    # Nogmaals op titel proberen als proces-detectie overal faalde.
    try:
        for w in desktop.windows():
            title = (w.window_text() or "").lower()
            if any(name in title for name in BROWSER_TITLE_WORDS):
                return w, None
    except Exception:
        pass
    return None, ToolResult(ok=False, message="Browser niet gevonden.", error_kind="browser_niet_gevonden")


def get_browser_url():
    """Leest de URL van de huidige browser."""
    w, err = _find_browser_window()
    if err:
        return err

    try:
        edits = w.descendants(control_type="Edit")
        url = ""
        for e in edits:
            txt = (e.window_text() or "")
            if "." in txt and "/" in txt:
                url = txt
                break
        if not url:
            url = (w.window_text() or "").split(" - ")[-1].strip()
        return ToolResult(ok=True, message=f"Huidige URL: {url}.", data={"url": url})
    except Exception as exc:
        return ToolResult(ok=False, message=f"Kon de URL niet lezen: {exc}",
                          error_kind="browser_lees_fout")


def get_browser_title():
    """Leest de titel van de huidige browser."""
    w, err = _find_browser_window()
    if err:
        return err

    try:
        title = w.window_text() or ""
        return ToolResult(ok=True, message=f"Pagina-titel: {title}.",
                          data={"title": title})
    except Exception as exc:
        return ToolResult(ok=False, message=f"Kon de titel niet lezen: {exc}",
                          error_kind="browser_lees_fout")


def get_browser_content(max_items=50):
    """Leest de zichtbare tekst van de huidige browserpagina via UIA."""
    w, err = _find_browser_window()
    if err:
        return err

    try:
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
        return ToolResult(
            ok=True,
            message="Ik heb de inhoud van de pagina gelezen.",
            data={"content": content, "count": len(content)},
        )
    except Exception as exc:
        return ToolResult(ok=False, message=f"Kon de pagina-inhoud niet lezen: {exc}",
                          error_kind="browser_lees_fout")
