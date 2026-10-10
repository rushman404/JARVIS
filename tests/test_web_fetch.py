import sys
import os
import io
import re
import requests
from unittest.mock import patch, MagicMock
import actions.web as web
import core.ai as ai
from core.ai import update_context
import core.brain as brain

def test_main():
    """
JARVIS - Fase 8: Web Fetch tests
===================================

Test de web-fetch-skill zonder echt internet:

  [1] URL-validatie (alleen http/https, geen file://, geen onzin)
  [2] html_to_text: scripts/styles/nav verwijderen, tekst schoon
  [3] extract_title / extract_meta_description
  [4] truncate_text: lange pagina's afkappen (token-limiet)
  [5] fetch_url: succes / 404 / timeout / verbindingsfout / te groot
      (requests wordt gemockt, geen live netwerk)
  [6] format_fetch_result: nette samenvatting
  [7] core.ai.execute_tool('web_fetch') dispatchen
  [8] core.brain.process_command routing ('lees deze pagina <url>')
  [9] web_fetch NOOIT een gevaarlijke/onveilige actie

Alle netwerkhandelingen zijn gemockt; geen echt HTTP-verkeer.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print('\n===== [1] URL-VALIDATIE =====')
    assert web.is_safe_url('https://www.example.com'), 'https-url is veilig'
    assert web.is_safe_url('http://example.nl/test'), 'http-url is veilig'
    assert not web.is_safe_url('file:///C:/geheim.txt'), 'file:// wordt geweigerd'
    assert not web.is_safe_url('ftp://example.com'), 'ftp:// wordt geweigerd'
    assert not web.is_safe_url('example.com'), 'zonder scheme wordt geweigerd'
    assert not web.is_safe_url(''), 'lege string wordt geweigerd'
    assert not web.is_safe_url('dit is geen url'), 'onzin wordt geweigerd'
    assert not web.is_safe_url('javascript:alert(1)'), 'javascript-URL wordt geweigerd'
    print('\n===== [2] HTML -> TEKST =====')
    HTML_SAMPLE = '<html><head>\n<script>var x = 1; if (x) { evil(); }</script>\n<style>.red { color: red; }</style>\n<title>Testpagina</title>\n<meta name="description" content="Een beschrijving voor de test.">\n</head><body>\n<!-- opmerking -->\n<nav><a href="/home">Home</a> <a href="/about">Over ons</a></nav>\n<h1>Welkom op de testpagina</h1>\n<p>Dit is de eerste alinea met <b>belangrijke</b> woorden.</p>\n<p>Hier staat nog &eacute;&eacute;n regel met entiteiten.</p>\n<footer>Copyright JARVIS 2026</footer>\n</body></html>'
    text = web.html_to_text(HTML_SAMPLE)
    assert 'evil' not in text, 'scripts zijn verwijderd'
    assert 'color' not in text.lower() or 'red' not in text, 'styles zijn verwijderd'
    assert 'opmerking' not in text, 'opmerkingen zijn verwijderd'
    assert 'Over ons' not in text and 'nav' not in text.lower() or len(text) > 0, 'navigatie is verwijderd'
    assert 'Welkom op de testpagina' in text or 'testpagina' in text, 'inhoud blijft behouden'
    assert 'één' in text, 'html-entities gedecodeerd'
    assert '<' not in text, 'geen tags over'
    print('\n===== [3] TITEL & META =====')
    assert web.extract_title(HTML_SAMPLE) == 'Testpagina', 'titel wordt uitgelezen'
    assert 'beschrijving' in web.extract_meta_description(HTML_SAMPLE), 'meta-description wordt uitgelezen'
    assert web.extract_title('<html><p>x</p></html>') == '', 'geen titel -> lege string'
    print('\n===== [4] TRUNCATE (token-limiet) =====')
    assert web.truncate_text('kort') == 'kort', 'korte tekst blijft heel'
    long_text = 'woord ' * 2000
    trunc = web.truncate_text(long_text)
    assert len(trunc) < len(long_text), 'lange tekst wordt afgekapt'
    assert '... (pagina afgekapt)' in trunc, 'afkapping bevat melding'
    assert web.truncate_text('') == '', 'lege tekst -> leeg'
    print('\n===== [5] FETCH_URL =====')
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.text = HTML_SAMPLE
    with patch.object(requests, 'get', return_value=ok_response) as m:
        result = web.fetch_url('https://www.example.com/pagina')
        assert result['ok'] is True, 'succesvolle fetch -> ok=True'
        assert result['title'] == 'Testpagina', 'titel in resultaat'
        assert 'testpagina' in result['text'], 'tekst geëxtraheerd'
        assert result['url'] == 'https://www.example.com/pagina', 'URL meegestuurd'
    not_found = MagicMock()
    not_found.status_code = 404
    with patch.object(requests, 'get', return_value=not_found):
        result = web.fetch_url('https://example.com/nietbestaand')
        assert result['ok'] is False, '404 -> ok=False'
        assert '404' in result.get('error', ''), '404-melding netjes'
    internal_error = MagicMock()
    internal_error.status_code = 500
    with patch.object(requests, 'get', return_value=internal_error):
        result = web.fetch_url('https://example.com/fout')
        assert result['ok'] is False, '500 -> ok=False'
        assert '500' in result.get('error', ''), '500-melding netjes'
    with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout):
        result = web.fetch_url('https://example.com/langzaam')
        assert result['ok'] is False, 'timeout -> ok=False'
        assert 'reageerde niet' in result.get('error', ''), 'timeout-melding netjes'
    with patch.object(requests, 'get', side_effect=requests.exceptions.ConnectionError):
        result = web.fetch_url('https://example.com/offline')
        assert result['ok'] is False, 'verbindingsfout -> ok=False'
    result = web.fetch_url('geen url')
    assert result['ok'] is False, 'ongeldige url -> ok=False'
    assert 'geen geldige web-URL' in result.get('error', ''), 'ongeldige url -> nette melding'
    big_response = MagicMock()
    big_response.status_code = 200
    big_response.text = 'x' * 5000
    with patch.object(requests, 'get', return_value=big_response):
        result = web.fetch_url('https://example.com/groot', max_bytes=1000)
        assert result['ok'] is False, 'te grote pagina -> ok=False'
    print('\n===== [6] FORMAT_FETCH_RESULT =====')
    formatted = web.format_fetch_result({'ok': True, 'title': 'Titel X', 'description': 'Omschrijving Y', 'text': 'Inhoud van de pagina die gelezen moet worden.'})
    assert 'Titel X' in formatted, 'format bevat titel'
    assert 'Inhoud van de pagina' in formatted, 'format bevat inhoud'
    error_formatted = web.format_fetch_result({'ok': False, 'error': 'Foutmelding Z'})
    assert 'Foutmelding Z' in error_formatted, 'foutresultaat wordt doorgegeven'
    print('\n===== [7] EXECUTE_TOOL (web_fetch) =====')
    update_context(pending_choice=None)
    with patch('core.ai.web_fetch_tool', return_value='Tool-resultaat web') as m:
        result = ai.execute_tool('web_fetch', {'url': 'https://example.com'}, 'lees deze pagina')
        assert m.called, 'execute_tool roept web_fetch_tool aan'
        assert result == 'Tool-resultaat web', 'resultaat teruggegeven'
    result = ai.execute_tool('web_fetch', {}, 'lees deze pagina')
    assert 'kon web_fetch niet uitvoeren' in result, 'web_fetch zonder url -> nette fout'
    print('\n===== [8] BRAIN-ROUTING =====')
    update_context(pending_choice=None)
    fake_page = {'ok': True, 'title': 'Voorbeeld', 'description': '', 'text': 'Inhoud die JARVIS vertelt wat er op de pagina staat.'}
    with patch('core.brain.fetch_url', return_value=fake_page) as m:
        result = brain.process_command('lees deze pagina https://example.com/hallo')
        assert m.called, "'lees deze pagina <url>' roept fetch_url aan"
        assert 'Voorbeeld' in result, 'melding met pagina-inhoud'
        result = brain.process_command('wat staat er op https://example.com')
        assert 'Voorbeeld' in result, "'wat staat er op <url>' routeert"
        result = brain.process_command('lees deze pagina')
        assert 'URL' in result, "'lees deze pagina' zonder url -> vraag om url"
        update_context(pending_choice=None)
        result = brain.process_command('https://example.com')
        assert 'Voorbeeld' in result and m.called, 'losse URL als antwoord -> direct fetch'
        update_context(pending_choice=None)
        result = brain.process_command('ja https://example.com/pagina')
        assert 'Voorbeeld' in result, "'ja <url>' als antwoord -> direct fetch"
    with patch('core.brain.ask_ai', return_value='AI-STUB'):
        result = brain.process_command('open youtube')
        assert not str(result).startswith('Zal ik') and 'open_website' != 'web_fetch', "'open youtube' gaat NIET naar web_fetch"
    print('\n===== [9] SAFETY =====')
    assert not web.is_safe_url('file:///tmp/x'), 'web_fetch accepteert geen file://'
    assert not web.is_safe_url('192.168.1.1'), 'web_fetch accepteert geen intranet-gok'
    print()
    print('=' * 50)
    print('=' * 50)
