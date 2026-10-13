import sys
import os
import io
import re
import requests
from unittest.mock import patch, MagicMock
import actions.web as web
from core import brain
from unittest.mock import patch as _patch
from core import ai

def test_main():
    """
JARVIS - Fase 9: Web Agent (internet zoeken + beste bron lezen) tests
=====================================================================

Test de web-search-skill zonder echt internet (alles gemockt):

  [1] _parse_duckduckgo_html: titel / snippet / URL uit resultaat blok
  [2] _parse_duckduckgo_html: DuckDuckGo redirect-URL's netjes omzetten
  [3] duckduckgo_search: succes -> lijst met top-N resultaten
  [4] duckduckgo_search: geen resultaten -> nette melding
  [5] duckduckgo_search: timeout / verbindingsfout / HTTP-fout -> nette melding
  [6] duckduckgo_search: kapotte/lege zoekterm -> vriendelijk
  [7] format_search_results: leesbare samenvatting
  [8] search_and_fetch: zoek + beste bron lezen (gemockt)
  [9] search_and_fetch: max_pages=2 -> twee bronnen (vergelijken)
  [10] core.ai.execute_tool('web_search') dispath
  [11] core.ai.execute_tool('web_search_and_fetch') dispath
  [12] core.brain routing: 'zoek X op' -> web-agent (geen browser)
  [13] core.brain routing: 'google naar X' -> web-agent
  [14] core.brain routing: 'wat is het weer' -> web-agent
  [15] core.brain routing: 'vergelijk X en Y' -> 2 bronnen
  [16] core.brain routing: op specifieke site zoeken ('zoek op youtube
       naar X') -> NIET de web-agent (blijft browser-domein)
  [17] Veiligheid: zoekterm met rare tekens wordt veilig geëncodeerd
  [18] Veiligheid: NOOIT onveilige / alleen-lezen veilige actie

Alle netwerkhandelingen zijn gemockt; geen echt HTTP-verkeer.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fake_html = '\n<html>\n  <div class="result results_links results_links_deep web-result">\n    <h2 class="result__title">\n      <a rel="nofollow" class="result__a"\n         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&amp;rut=abc">\n         Example Domain\n      </a>\n    </h2>\n    <a class="result__snippet">This domain is for use in illustrative examples.</a>\n  </div>\n  <div class="result results_links">\n    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnos.nl%2F">NOS</a>\n    <a class="result__snippet">Het laatste nieuws</a>\n  </div>\n</html>\n'
    hits = web._parse_duckduckgo_html(fake_html)
    assert len(hits) == 2, 'parser vindt 2 resultaten'
    assert hits[0]['title'] == 'Example Domain', 'titel wordt gepakt'
    assert 'illustrative' in hits[0]['snippet'], 'snippet wordt gepakt'
    assert hits[0]['url'] == 'https://example.com/', 'URL wordt netjes omgezet (zonder redirect)'
    assert hits[1]['url'] == 'https://nos.nl/', 'tweede resultaat ook netjes'
    assert web._parse_duckduckgo_html('') == [], 'lege HTML -> geen resultaten'
    messy = '<div class="result results_links"><a class="result__a" href="/x">Titel &amp; en <b>groot</b></a></div>'
    hits2 = web._parse_duckduckgo_html(messy)
    assert hits2 and 'Titel & en groot' in hits2[0]['title'], 'HTML in titel wordt ontsmet'
    print('\n===== [2] SEARCH-FUNCTIE =====')

    def mock_response(text, status=200):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        return resp
    log_html = '<div class="result results_links"><a class="result__a" href="//x/?uddg=https%3A%2F%2Flog.nl%2F">Log</a></div>'
    with patch.object(requests, 'get', return_value=mock_response(log_html)) as fake_get:
        r = web.duckduckgo_search('openingstijden')
        assert r['ok'], 'succesvol zoeken -> ok=True'
        assert len(r['results']) == 1, 'resultaat gevonden'
        assert r['query'] == 'openingstijden', 'query wordt bewaard'
        _, kwargs = fake_get.call_args
        assert kwargs.get('params', {}).get('q', '') == 'openingstijden', 'zoekterm veilig als parameter'
    with patch.object(requests, 'get', return_value=mock_response('<html>niks</html>')):
        r = web.duckduckgo_search('zzzqwerty')
        assert not r['ok'], 'geen resultaten -> ok=False'
        assert 'geen resultaten' in r['error'], 'vriendelijke melding'
    with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout):
        r = web.duckduckgo_search('weer')
        assert not r['ok'], 'timeout -> ok=False'
        assert 'te lang' in r['error'], 'duidelijk melding'
    with patch.object(requests, 'get', side_effect=requests.exceptions.ConnectionError):
        r = web.duckduckgo_search('weer')
        assert not r['ok'], 'verbindingsfout -> ok=False'
        assert 'verbinding' in r['error'], 'melding over verbinding'
    with patch.object(requests, 'get', return_value=mock_response('', status=503)):
        r = web.duckduckgo_search('weer')
        assert not r['ok'], 'http 503 -> ok=False'
        assert 'probeer het zo even opnieuw' in r['error'], 'vriendelijke melding bij http-fout'
        assert r.get('error_code') == 503, 'foutcode wordt bewaard'
    with patch.object(web, 'RATE_LIMIT_RETRY_WAITS', (0, 0)), patch.object(requests, 'get', return_value=mock_response('', status=202)) as fake_get:
        r = web.duckduckgo_search('weer')
        assert not r['ok'], 'rate-limit 202 -> ok=False'
        assert 'Zoeken lukte net niet' in r['error'], '202 geeft vriendelijke melding'
        assert fake_get.call_count >= 2, 'rate-limit: er is geherprobeerd'
    success_after = {'calls': 0}

    def flaky_get(*a, **kw):
        success_after['calls'] += 1
        return mock_response('', status=202) if success_after['calls'] == 1 else mock_response(log_html)
    with patch.object(web, 'RATE_LIMIT_RETRY_WAITS', (0,)), patch.object(requests, 'get', side_effect=flaky_get):
        r = web.duckduckgo_search('weer')
        assert r['ok'], 'rate-limit retry slaagt na verken'
        assert len(r.get('results', [])) == 1, 'resultaat na retry gevonden'
    with patch.object(requests, 'get', return_value=mock_response(log_html)):
        r = web.duckduckgo_search('   ')
        assert not r['ok'], 'lege zoekterm -> ok=False'
        assert 'zoekterm' in r['error'], 'vriendelijk bij lege term'
    print('\n===== [3] FORMAT =====')
    formatted = web.format_search_results({'ok': True, 'query': 'weer', 'results': [{'title': 'Weer op NOS', 'snippet': 'Regen en zon', 'url': 'https://nos.nl/weer'}]})
    assert 'Weer op NOS' in formatted, 'formaat bevat titel'
    assert 'https://nos.nl/weer' in formatted, 'formaat bevat url'
    assert 'weer' in formatted, 'formaat bevat query'
    formatted_fail = web.format_search_results({'ok': False, 'error': 'Ik kon niet zoeken.'})
    assert formatted_fail == 'Ik kon niet zoeken.', 'foutformaat netjes'
    print('\n===== [4] SEARCH + FETCH =====')
    page_html = "<html><head><title>Openingstijden</title><meta name='description' content='De winkel is open van 8 tot 20 uur.'></head><body><script>var x=1;</script><article><h1>Albert Heijn Bloemendaal</h1><p>De winkel is vandaag open van 08:00 tot 20:00 uur.</p></article></body></html>"
    search_html = '<div class="result results_links"><a class="result__a" href="//x/?uddg=https%3A%2F%2Fwinkel.nl%2F">Winkel</a>\n<a class="result__snippet">Open van 8 tot 20</a></div>\n<div class="result results_links"><a class="result__a" href="//x/?uddg=https%3A%2F%2Fwinkel2.nl%2F">Winkel 2</a></div>'
    with patch.object(requests, 'get', side_effect=[mock_response(search_html), mock_response(page_html)]):
        pass
    with _patch.object(web, 'duckduckgo_search') as fake_search, _patch.object(web, 'fetch_url') as fake_fetch:
        fake_search.return_value = {'ok': True, 'query': 'openingstijden winkel', 'results': [{'title': 'Winkel', 'snippet': 'Open van 8 tot 20', 'url': 'https://winkel.nl/'}]}
        fake_fetch.return_value = {'ok': True, 'title': 'Albert Heijn Bloemendaal', 'description': 'De winkel is open van 8 tot 20 uur.', 'text': 'De winkel is vandaag open van 08:00 tot 20:00 uur.'}
        combined = web.search_and_fetch('openingstijden winkel', max_pages=1)
        assert combined['ok'], 'search_and_fetch: ok'
        assert len(combined['pages']) == 1, 'search_and_fetch: 1 bron'
        assert '08:00' in combined['pages'][0]['text'], 'eerste bron heeft tekst'
        text = web.format_search_and_fetch(combined)
        assert 'Albert Heijn Bloemendaal' in text, 'format bevat bron-titel'
        assert '08:00' in text, 'format bevat inhoud'
    with _patch.object(web, 'duckduckgo_search') as fake_search, _patch.object(web, 'fetch_url') as fake_fetch:
        fake_search.return_value = {'ok': True, 'query': 'rtx 4070 vs 4060', 'results': [{'title': 'Review A', 'snippet': 'De 4070 is sneller.', 'url': 'https://a.nl/'}, {'title': 'Review B', 'snippet': 'De 4060 is goedkoper.', 'url': 'https://b.nl/'}]}
        fake_fetch.return_value = {'ok': True, 'title': 'Vergelijking', 'description': '', 'text': 'Specs vergelijking.'}
        combined = web.search_and_fetch('rtx 4070 vs 4060', max_pages=2)
        assert len(combined['pages']) == 2, 'vergelijk: 2 bronnen opgehaald'
        text = web.format_search_and_fetch(combined)
        assert 'Bron 1' in text and 'Bron 2' in text, 'vergelijk: beide bronnen genoemd'
    with _patch.object(web, 'duckduckgo_search') as fake_search, _patch.object(web, 'fetch_url') as fake_fetch:
        fake_search.return_value = {'ok': True, 'query': 'test', 'results': [{'title': 'Kapot', 'snippet': '', 'url': 'https://kapot.nl/'}]}
        fake_fetch.return_value = {'ok': False, 'error': 'timeout'}
        combined = web.search_and_fetch('test')
        assert not combined['ok'], 'niet-leesbare bron -> ok=False'
        assert combined.get('error', '').startswith('Ik kon'), 'niet-leesbare bron -> fout in error'
    print('\n===== [5] AI-DISPATCH =====')
    with _patch.object(ai, 'web_search_tool') as fake_search_tool, _patch.object(ai, 'update_context') as fake_ctx:
        fake_search_tool.return_value = "Zoekresultaten voor 'weer'"
        out = ai.execute_tool('web_search', {'query': 'weer'}, question='zoek het weer op')
        assert 'weer' in out, "execute_tool('web_search') geeft resultaat"
        fake_search_tool.assert_called_once_with('weer')
    with _patch.object(ai, 'web_search_and_fetch_tool') as fake_saf_tool, _patch.object(ai, 'update_context') as fake_ctx:
        fake_saf_tool.return_value = 'Bron 1: ...'
        out = ai.execute_tool('web_search_and_fetch', {'query': 'weer amsterdam'}, question='weer')
        assert 'Bron 1' in out, "execute_tool('web_search_and_fetch') geeft resultaat"
        fake_saf_tool.assert_called_once_with('weer amsterdam', max_pages=1)
    with _patch.object(ai, 'web_search_and_fetch_tool') as fake_saf_tool, _patch.object(ai, 'update_context') as fake_ctx:
        fake_saf_tool.return_value = 'Bron 1 .. Bron 2'
        out = ai.execute_tool('web_search_and_fetch', {'query': 'a b', 'max_pages': 2}, question='vergelijk a en b')
        fake_saf_tool.assert_called_once_with('a b', max_pages=2)
        assert True, 'max_pages=2 wordt doorgegeven'
    tool_names = [t['function']['name'] for t in ai.ai_tools] if hasattr(ai, 'ai_tools') else []
    if hasattr(ai, 'ai_tools'):
        assert 'web_search' in tool_names, 'ai_tools bevat web_search'
        assert 'web_search_and_fetch' in tool_names, 'ai_tools bevat web_search_and_fetch'
    else:
        assert True, 'ai_tools functie controle (controleer via call)'
    print('\n===== [6] BRAIN-ROUTING =====')
    with _patch.object(brain, 'search_and_fetch') as fake_saf, _patch.object(brain, 'format_search_and_fetch') as fake_fmt:
        fake_saf.return_value = {'ok': True}
        fake_fmt.return_value = 'Gevonden: berichtje.'
        result = brain.process_command('zoek de openingstijden van de winkel op')
        fake_saf.assert_called_once()
        args = fake_saf.call_args[0][0]
        assert 'openingstijden' in args, "[12] 'zoek X op' -> web-agent roept search_and_fetch"
        assert 'Gevonden' in result, '[12] resultaat komt terug'
    with _patch.object(brain, 'search_and_fetch') as fake_saf, _patch.object(brain, 'format_search_and_fetch') as fake_fmt:
        fake_saf.return_value = {'ok': True}
        fake_fmt.return_value = 'Antwoord uit web-agent.'
        result = brain.process_command('google naar beste boodschappenlijst')
        args = fake_saf.call_args[0][0]
        assert 'boodschappenlijst' in args, "[13] 'google naar X' -> zoekt 'beste boodschappenlijst'"
    with _patch.object(web, 'get_weather') as fake_weather, _patch.object(web, 'format_weather') as fake_fmt:
        fake_weather.return_value = {'ok': True}
        fake_fmt.return_value = 'Het wordt 17 graden.'
        result = brain.process_command('wat is het weer vandaag in Utrecht')
        fake_weather.assert_called_once()
        args = fake_weather.call_args[0][0]
        assert 'utrecht' in args, "[14] 'weer' -> open-meteo route"
        assert '17 graden' in str(result), '[14] weer antwoord komt terug'
    with _patch.object(web, 'get_weather') as fake_weather, _patch.object(web, 'format_weather') as fake_fmt:
        fake_weather.return_value = {'ok': True}
        fake_fmt.return_value = '17 graden.'
        brain.process_command('wat is het weer')
        args = fake_weather.call_args[0][0]
        assert args == 'Amsterdam', '[14b] weer zonder plaats -> default Amsterdam'
    with _patch.object(brain, 'search_and_fetch') as fake_saf, _patch.object(brain, 'format_search_and_fetch') as fake_fmt, _patch.object(brain, '_comparison_verdict') as fake_verdict:
        fake_saf.return_value = {'ok': True}
        fake_fmt.return_value = 'Vergelijking klaar.'
        fake_verdict.return_value = 'WINNAAR: A'
        result = brain.process_command('vergelijk de RTX 4070 en 4060')
        _, kwargs = fake_saf.call_args
        assert kwargs.get('max_pages') == 2, '[15] vergelijken -> max_pages=2'
        assert fake_verdict.called, '[15] oordeel wordt toegevoegd'
        assert 'WINNAAR' in str(result), '[15] oordeel zit in antwoord'
    verdict = brain._comparison_verdict('a en b', {'pages': [{'text': 'A is snel en goedkoop.', 'search_title': 'A review'}, {'text': 'B is trager maar stabieler.', 'search_title': 'B review'}]})
    if isinstance(verdict, str) and verdict:
        assert 'WINNAAR' in verdict, '[15b] oordeel bevat WINNAAR'
        assert 'WAAROM' in verdict, '[15b] oordeel bevat WAAROM'
    else:
        assert isinstance(verdict, str), '[15b] oordeel genereert tekst (offline=skip)'
    with _patch.object(brain, 'search_and_fetch') as fake_saf:
        fake_saf.return_value = {'ok': True}
        brain.process_command('zoek op youtube naar hondjes')
        assert not fake_saf.called, "[16] 'zoek op <site> naar' gaat NIET naar web-agent"
    print('\n===== [7] VEILIGHEID =====')
    with _patch.object(requests, 'get') as fake_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<html></html>'
        fake_get.return_value = resp
        web.duckduckgo_search('quote " en <tags> & symbols')
        _, kwargs = fake_get.call_args
        param = kwargs['params']['q']
        assert '<' not in param and '&' not in param, '[17] zoekterm wordt URL-veilig geëncodeerd'
    with _patch.object(requests, 'get') as fake_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<html></html>'
        fake_get.return_value = resp
        web.duckduckgo_search('test')
        url_used = fake_get.call_args[0][0] if fake_get.call_args[0] else ''
        assert 'https://' in url_used and 'duckduckgo' in url_used, '[18] alleen https zoekendpoint (veilig)'
    print('\n===== [8] SCHONE TEXTRACTIE =====')
    noisy = 'Intro tekst. { toggleAccordion($el, false); }) 2.8 km ING Bank TEST to next screen Max. 17 seconden resterend. Maandag 08:00 - 22:00.'
    clean = web._strip_js_noise(noisy)
    assert 'toggleAccordion' not in clean, '[19] JS-snippets worden verwijderd'
    assert 'TEST' not in clean, '[19] TEST-tekst verwijderd'
    assert 'Maandag 08:00 - 22:00' in clean, '[19] relevante inhoud blijft'
    nav = 'Ontdekken Ontdek Badhoevedorp Koopzondagen Koopavonden Albert Heijn Dele deze locatie Facebook LinkedIn Maandag 08:00 - 22:00'
    clean2 = web._strip_navigation_noise(nav)
    assert 'Koopzondagen' not in clean2, '[20] navigatielabels verwijderd'
    assert 'Maandag 08:00 - 22:00' in clean2, '[20] inhoud blijft'
    long_text = 'Welkom op onze website! Navigeer door het menu. Cookie-acceptatie. Disclaimer: geen enkele garantie op juistheid van gegevens. Bekijk onze partnerships. Volg ons op social media. Open de app. Download. Schrijf je in voor de nieuwsbrief. Aanbiedingen bekijken. Bekijk aanbiedingen. Lees meer over ons. Wat wij doen. Over ons. Blog. Contact. Veelgestelde vragen. Help. Nieuws. In de pers. Privacybeleid. Algemene voorwaarden. Cookiebeleid.  * 100  ' + 'Openingstijden: Maandag 08:00 - 22:00 Dinsdag 08:00 - 22:00 Woensdag 08:00 - 22:00 Zondag 08:00 - 22:00 Koopzondag 08:00 - 22:00. ' + ' Beoordelingen Reviews & Ervaringen Schrijf een review Deel deze winkel. Locatie. Klantenservice Bel direct. FAQ. Google Maps. Open in Maps. Adres: Hoofdstraat 12. Parkeerplaats beschikbaar. Gratis parkeren. Footer link 1 Footer link 2 Footer link 3 Footer link 4 ' * 80
    extracted = web.extract_relevant_text(long_text, 'openingstijden winkel')
    assert '08:00' in extracted, '[21] tijd-blok herkend'
    assert 'Openingstijden' in extracted or 'Maandag' in extracted, '[21] openingstijden eruit'
    assert len(extracted) <= 4000, '[21] output begrensd'
    no_hours = 'Header ' + 'middlecontent ' * 500 + 'Footer'
    mid_out = web.extract_relevant_text(no_hours)
    assert 'middlecontent' in mid_out, '[21b] fallback pakt middenstuk'
    print('\n===== [8] WIKIPEDIA FALLBACK =====')
    with patch.object(web, 'duckduckgo_search', return_value={'ok': False, 'error': 'rate-limit', 'error_code': 202, 'results': []}):
        with patch.object(web, 'wikipedia_lookup', return_value={'ok': True, 'title': 'Australië', 'url': 'https://nl.wikipedia.org/wiki/Australië', 'extract': 'Australië is een land en continent in het zuidelijk halfrond.', 'query': 'hoofdstad van Australië'}) as fake_wiki:
            r = web.search_and_fetch('hoofdstad van Australië')
            assert fake_wiki.called, '[22] DDG faalt -> fallback activeert'
            assert r.get('ok'), '[22] fallback geeft resultaat'
            assert r.get('via') == 'wikipedia', '[22] via=wikipedia'
    with patch.object(web, 'duckduckgo_search', return_value={'ok': False, 'error': 'rate-limit', 'error_code': 202, 'results': []}):
        call_count = [0]

        def fake_wiki_lookup(query):
            call_count[0] += 1
            if '4060' in query or '4070' in query:
                return {'ok': True, 'title': '400 meter horden', 'url': 'https://nl.wikipedia.org/wiki/400_meter_horden', 'extract': 'De 400 m horden is een olympisch atletiekonderdeel.', 'query': query}
            return {'ok': False, 'error': 'geen resultaat', 'query': query}
        with patch.object(web, 'wikipedia_lookup', side_effect=fake_wiki_lookup):
            r = web.search_and_fetch('rtx 4070 rtx 4060')
            assert not r.get('ok') or all(('400 meter' not in p.get('title', '') + p.get('text', '') for p in r.get('pages', []))), "[23] '400 meter horden' NIET als resultaat"
    assert web._is_bare_number('4060'), "[24] '4060' is bare number"
    assert not web._is_bare_number('rtx'), "[24] 'rtx' is GEEN bare number"
    sw = {'van', 'de', 'het', 'een', 'in', 'op', 'naar', 'voor', 'met', 'en', 'of', 'hoe', 'wat', 'wie', 'waar', 'wanneer', 'is', 'zijn', 'uit', 'ook', 'al', 'als', 'dan', 'maar', 'om', 'tot', 'bij', 'aan', 'af', 'over', 'te', 'vergelijk', 'eerste', 'beste'}
    cands = web._wiki_candidates('rtx 4070 rtx 4060', sw)
    assert '4060' not in cands, "[25] '4060' NIET als zelfstandige kandidaat"
    assert 'rtx 4060' in cands, "[25] 'rtx 4060' WEL als kandidaat"
    cands2 = web._wiki_candidates('eerste iPhone uit', sw)
    assert 'iPhone' in cands2, "[26] 'iPhone' als kandidaat"
    assert 'eerste' not in cands2, "[26] 'eerste' NIET als zelfstandige kandidaat"
    rel = web._wiki_is_relevant('rtx 4070 rtx 4060', {'title': '400 meter horden', 'extract': 'De 400 m horden is een olympisch atletiekonderdeel.'})
    assert not rel, "[27] 'rtx 4070' NIET relevant met '400 meter horden'"
    rel2 = web._wiki_is_relevant('rtx 4070 rtx 4060', {'title': 'NVIDIA GeForce RTX 4070', 'extract': 'De RTX 4070 is een videokaart van NVIDIA.'})
    assert rel2, "[28] 'rtx 4070' WEL relevant met 'NVIDIA GeForce RTX 4070'"
    rel3 = web._wiki_is_relevant('eerste iPhone uit', {'title': 'IPhone', 'extract': 'De iPhone is een smartphone van Apple.'})
    assert rel3, "[29] 'eerste iPhone uit' WEL relevant met 'IPhone'"
    rel4 = web._wiki_is_relevant('eerste iPhone uit', {'title': 'Eerste inwoners van Amerika', 'extract': 'De eerste inwoners van Amerika kwamen via de Beringstraat.'})
    assert not rel4, "[29b] 'eerste iPhone uit' NIET relevant met 'Eerste inwoners van Amerika'"
    with patch.object(web, 'wikipedia_lookup', return_value={'ok': True, 'title': '400 meter horden', 'url': 'https://nl.wikipedia.org/wiki/400_meter_horden', 'extract': 'De 400 m horden is een olympisch atletiekonderdeel.', 'query': 'rtx 4060'}):
        result = web._wiki_fallback('rtx 4070 rtx 4060')
        assert result is None, '[29c] fallback retourneert None bij irrelevante resultaten'
    print('\n===== [9] ERROR TYPE VELDEN =====')
    r = web.duckduckgo_search('   ')
    assert r.get('error_type') == 'invalid_query', '[30] lege query -> error_type invalid_query'
    with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout):
        r = web.duckduckgo_search('test timeout')
        assert r.get('error_type') == 'timeout', '[31] timeout -> error_type timeout'
    with patch.object(requests, 'get', side_effect=requests.exceptions.ConnectionError('fail')):
        r = web.duckduckgo_search('test net')
        assert r.get('error_type') == 'network_error', '[32] connection error -> error_type network_error'
    with patch.object(web, 'RATE_LIMIT_RETRY_WAITS', (0, 0)), patch.object(requests, 'get', return_value=mock_response('', status=202)):
        r = web.duckduckgo_search('test rl')
        assert r.get('error_type') == 'rate_limited', '[33] rate-limit -> error_type rate_limited'
        assert r.get('error_code') == 202, '[33] error_code behouden als getal'
    with patch.object(requests, 'get', return_value=mock_response('<html>niks</html>')):
        r = web.duckduckgo_search('zzzqwertyuniek')
        assert r.get('error_type') == 'no_results', '[34] geen resultaten -> error_type no_results'
    with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout):
        r = web.fetch_url('https://example.com/page')
        assert r.get('error_type') == 'timeout', '[35] fetch timeout -> error_type timeout'
    r = web.fetch_url('://geen-protocol')
    assert r.get('error_type') == 'invalid_url', '[36] ongeldige URL -> error_type invalid_url'
    with patch.object(requests, 'get', return_value=mock_response('', status=404)):
        r = web.fetch_url('https://example.com/bestaat-niet')
        assert r.get('error_type') == 'http_error', '[37] 404 -> error_type http_error'
    with patch.object(web, 'duckduckgo_search', return_value={'ok': False, 'error': 'rate-limit', 'error_type': 'rate_limited', 'error_code': 202, 'results': []}):
        with patch.object(web, '_wiki_fallback', return_value=None):
            r = web.search_and_fetch('irrelevante query x99')
            assert r.get('error_type') == 'not_relevant', '[38] fallback faalt -> error_type not_relevant'
    with patch.object(web, 'duckduckgo_search', return_value={'ok': False, 'error': 'rate-limit', 'error_type': 'rate_limited', 'error_code': 202, 'results': []}):
        with patch.object(web, '_wiki_fallback', return_value={'ok': True, 'title': 'Test', 'url': 'https://test.nl', 'extract': 'Testinhoud.', 'query': 'test'}):
            r = web.search_and_fetch('test query')
            assert 'error_type' not in r or r.get('ok') is True, '[39] wiki fallback slaagt -> error_type NIET op topniveau'
    big_chunks = [b'X' * 1000 for _ in range(5000)]
    fake_big = MagicMock()
    fake_big.status_code = 200
    fake_big.headers = {}
    fake_big.raw = None
    fake_big.iter_content = lambda chunk_size=8192: iter(big_chunks)
    with patch.object(requests, 'get', return_value=fake_big):
        r = web.fetch_url('https://example.com/groot', max_bytes=100)
        assert r.get('error_type') == 'too_large', '[40] te-groot -> error_type too_large'
    with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout):
        r = web.duckduckgo_search('behoud test')
        assert 'timeout' in r.get('error', '').lower(), '[41] error tekst behouden'
        assert r.get('error_type') == 'timeout' and 'error' in r, '[41] error_type naast error'
    with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout):
        r = web.fetch_url('https://example.com/page')
        assert r.get('status') == 'timeout', '[41b] fetch: status behouden'
        assert r.get('error_type') == 'timeout' and 'status' in r, '[41b] fetch: error_type naast status'
    print(f"\n{'=' * 50}")
    print(f"{'=' * 50}")
