import sys
import os
import io
from unittest.mock import patch, MagicMock
import actions.browser as browser
from core.result_validation import ToolResult

def test_main():
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
  [8] Veiligheid: elke functie retourneert een ToolResult
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _mock_window(title='Test - Brave', url='', texts=None):
        w = MagicMock()
        w.window_text.return_value = title
        edit = MagicMock()
        edit.window_text.return_value = url
        text_elems = []
        for t in texts or []:
            te = MagicMock()
            te.window_text.return_value = t
            text_elems.append(te)
        w.descendants.side_effect = lambda control_type: text_elems if control_type == 'Text' else [edit] if control_type == 'Edit' else []
        return w

    def _mock_desktop(windows=None):
        d = MagicMock()
        d.windows.return_value = windows or []
        return d
    print('=== FASE 12: BROWSER READING ===\n')
    mock_w = _mock_window()
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
        w, err = browser._find_browser_window()
        assert err is None and w is not None, '1. _find_browser_window: browser gevonden'
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([]))
        w, err = browser._find_browser_window()
        assert w is None and err is not None and (err.error_kind == 'browser_niet_gevonden'), '2. _find_browser_window: geen browser -> fout'
    mock_w = _mock_window(url='https://www.google.com/search?q=test')
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
        r = browser.get_browser_url()
        assert r.ok and 'google.com' in (r.data or {}).get('url', ''), '3. get_browser_url: URL gelezen'
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([]))
        r = browser.get_browser_url()
        assert not r.ok and r.error_kind == 'browser_niet_gevonden', '4. get_browser_url: geen browser -> fout'
    mock_w = _mock_window(title='Test pagina - Brave')
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
        r = browser.get_browser_title()
        assert r.ok and 'Test pagina' in (r.data or {}).get('title', ''), '5. get_browser_title: titel gelezen'
    mock_w = _mock_window(texts=['Home', 'Welkom', ' nieuws ', '  ', 'Artikel 1'])
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
        r = browser.get_browser_content()
        assert r.ok and (r.data or {}).get('count') == 4, '6. get_browser_content: inhoud gelezen (lege items gefilterd)'
    mock_w = _mock_window(texts=[])
    with patch.object(browser, '_import_pywinauto') as imp:
        imp.return_value = MagicMock(return_value=_mock_desktop([mock_w]))
        r = browser.get_browser_content()
        assert r.ok and (r.data or {}).get('count') == 0, '7. get_browser_content: lege browser -> lege lijst'
    for fn, args in [(browser.get_browser_url, ()), (browser.get_browser_title, ()), (browser.get_browser_content, ())]:
        with patch.object(browser, '_import_pywinauto') as imp:
            imp.return_value = MagicMock(return_value=_mock_desktop([]))
            r = fn(*args)
            assert isinstance(r, ToolResult), f'8. {fn.__name__}: retourneert ToolResult'
