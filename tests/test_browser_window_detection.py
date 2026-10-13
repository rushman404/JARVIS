"""Tests voor het HERKENNEN van een browservenster (actions/browser.py).

win32process, psutil en pywinauto zijn gemockt. De kern: alleen een
ECHT browserproces (chrome.exe e.d.) telt, en de titel-fallback mag alleen
het typische achtervoegsel aan het EINDE matchen (geen losse substrings).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.browser as browser


def _make_window(title, idx):
    window = MagicMock()
    window.window_text.return_value = title
    window.handle = 1000 + idx
    return window


def _find(titles, process_names):
    """Roep _find_browser_window_inner aan met gemockte win32/psutil.

    ``process_names[i]`` is de procesnaam van venster i; ``None`` betekent
    dat de proces-lookup faalt (rechten/COM).
    """
    windows = [_make_window(title, i) for i, title in enumerate(titles)]

    desktop = MagicMock()
    desktop.windows.return_value = windows
    Desktop = MagicMock(return_value=desktop)

    def get_pid(handle):
        return (0, int(handle) - 1000)

    def make_process(pid):
        name = process_names[pid]
        if name is None:
            raise OSError("toegang geweigerd")
        process = MagicMock()
        process.name.return_value = name
        return process

    fake_win32 = MagicMock()
    fake_win32.GetWindowThreadProcessId.side_effect = get_pid

    with patch.object(browser, "_import_pywinauto", return_value=Desktop), \
         patch.object(browser, "win32process", fake_win32), \
         patch.object(browser.psutil, "Process", side_effect=make_process):
        return browser._find_browser_window_inner()


def test_vier_titels_met_browserwoord_zijn_geen_browser():
    titles = [
        "Knowledge base - Notepad",
        "Edge of Tomorrow - VLC",
        "Opera Gx - Discord",
        "Chromebook prijzen - Notepad",
    ]
    processes = ["notepad.exe", "vlc.exe", "discord.exe", "notepad.exe"]

    window, err = _find(titles, processes)

    assert window is None
    assert err is not None and err.error_kind == "browser_niet_gevonden"


def test_diezelfde_titels_ook_niet_bij_mislukte_procesdetectie():
    titles = [
        "Knowledge base - Notepad",
        "Edge of Tomorrow - VLC",
        "Opera Gx - Discord",
        "Chromebook prijzen - Notepad",
    ]
    processes = [None, None, None, None]  # rechten: titel-fallback

    window, err = _find(titles, processes)

    assert window is None
    assert err is not None and err.error_kind == "browser_niet_gevonden"


def test_echt_chrome_proces_wordt_gevonden():
    # Titel zonder browser-achtervoegsel: alleen het PROCES telt.
    window, err = _find(["Startpagina"], ["chrome.exe"])

    assert err is None
    assert window is not None
    assert window.handle == 1000


def test_elk_browserproces_wordt_gevonden():
    for name in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"):
        window, err = _find(["Iets"], [name.upper()])
        assert err is None and window is not None, name


def test_titel_fallback_alleen_op_achtervoegsel():
    # Proces-lookup faalt -> titel-fallback, maar alleen met echt achtervoegsel.
    for title in ("Pagina - Google Chrome", "Nieuws - Microsoft Edge",
                  "Site — Mozilla Firefox", "Test - Brave", "Iets - Opera",
                  "Forum - Vivaldi"):
        window, err = _find([title], [None])
        assert err is None and window is not None, title


def test_ander_proces_met_browserachtige_titel_blijft_geweigerd():
    # Proces is WEL bekend (geen browser) -> geen titel-fallback.
    window, err = _find(["Iets - Google Chrome"], ["notepad.exe"])
    assert window is None
    assert err is not None and err.error_kind == "browser_niet_gevonden"


def test_titel_helper():
    assert browser._title_looks_like_browser("Pagina - Google Chrome") is True
    assert browser._title_looks_like_browser("X — Mozilla Firefox") is True
    assert browser._title_looks_like_browser("Knowledge base - Notepad") is False
    assert browser._title_looks_like_browser("Chromebook prijzen - Notepad") is False
    assert browser._title_looks_like_browser("Edge of Tomorrow - VLC") is False
