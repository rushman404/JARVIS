"""
JARVIS - Fase 12: Browser Reading tests
========================================

Test de browser-leesfuncties ZONDER echte browser (alles gemockt):

  [1] _find_browser_window: browser gevonden
  [2] _find_browser_window: geen browser -> nette fout
  [3] get_browser_url: URL lezen
  [4] get_browser_url: geen browser -> fout
  [5] get_browser_title: titel lezen
  [6] get_browser_content: inhoud lezen (tekst-elementen)
  [7] get_browser_content: lege browser -> lege lijst
  [8] Veiligheid: elke functie retourneert ok/status/error dict
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import actions.browser as browser

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


def _mock_window(title="Test - Brave", url="", texts=None):
    w = MagicMock()
    w.window_text.return_value = title
    edit = MagicMock()
    edit.window_text.return_value = url
    text_elems = []
    for t in (texts or []):
        te = MagicMock()
        te.window_text.return_value = t
        text_elems.append(te)
    w.descendants.side_effect = lambda control_type: text_elems if control_type == "Text" else [edit] if control_type == "Edit" else []
    return w


def _mock_desktop(windows=None):
    d = MagicMock()
    d.windows.return_value = windows or []
    return d


# =========================================================
print("=== FASE 12: BROWSER READING ===\n")

# [1] _find_browser_window: browser gevonden
mock_w = _mock_window()
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
    w, err = browser._find_browser_window()
    ok("1. _find_browser_window: browser gevonden",
       err is None and w is not None)

# [2] _find_browser_window: geen browser -> fout
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([]))
    w, err = browser._find_browser_window()
    ok("2. _find_browser_window: geen browser -> fout",
       w is None and err is not None and err.get("error_type") == "browser_niet_gevonden")

# [3] get_browser_url
mock_w = _mock_window(url="https://www.google.com/search?q=test")
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
    r = browser.get_browser_url()
    ok("3. get_browser_url: URL gelezen",
       r.get("ok") and "google.com" in r.get("url", ""), str(r))

# [4] get_browser_url: geen browser -> fout
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([]))
    r = browser.get_browser_url()
    ok("4. get_browser_url: geen browser -> fout",
       not r.get("ok") and r.get("error_type") == "browser_niet_gevonden", str(r))

# [5] get_browser_title
mock_w = _mock_window(title="Test pagina - Brave")
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
    r = browser.get_browser_title()
    ok("5. get_browser_title: titel gelezen",
       r.get("ok") and "Test pagina" in r.get("title", ""), str(r))

# [6] get_browser_content
mock_w = _mock_window(texts=["Home", "Welkom", " nieuws ", "  ", "Artikel 1"])
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
    r = browser.get_browser_content()
    ok("6. get_browser_content: inhoud gelezen (lege items gefilterd)",
       r.get("ok") and r.get("count") == 4, str(r))

# [7] get_browser_content: lege browser -> lege lijst
mock_w = _mock_window(texts=[])
with patch.object(browser, "_import_pywinauto") as imp:
    imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
    r = browser.get_browser_content()
    ok("7. get_browser_content: lege browser -> lege lijst",
       r.get("ok") and r.get("count") == 0, str(r))

# [8] Veiligheid: alle functies geven dict met ok
for fn, args in [
    (browser.get_browser_url, ()),
    (browser.get_browser_title, ()),
    (browser.get_browser_content, ()),
]:
    with patch.object(browser, "_import_pywinauto") as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([]))
        r = fn(*args)
        ok(f"8. {fn.__name__}: retourneert dict met ok",
           isinstance(r, dict) and "ok" in r, f"type={type(r).__name__}")

print(f"\n--- FASE 12: {passed} geslaagd, {failed} gefaald ---\n")
