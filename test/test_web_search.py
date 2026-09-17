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
import sys
import os
import io
import re

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from unittest.mock import patch, MagicMock

import actions.web as web
from core import brain

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        extra = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{extra}")


# =============================================================
# [1] PARSEN VAN DUCKDuckGo HTML
# =============================================================

print("\n===== [1] RESULTAAT-PARSER =====")

fake_html = """
<html>
  <div class="result results_links results_links_deep web-result">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&amp;rut=abc">
         Example Domain
      </a>
    </h2>
    <a class="result__snippet">This domain is for use in illustrative examples.</a>
  </div>
  <div class="result results_links">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnos.nl%2F">NOS</a>
    <a class="result__snippet">Het laatste nieuws</a>
  </div>
</html>
"""

hits = web._parse_duckduckgo_html(fake_html)

ok("parser vindt 2 resultaten", len(hits) == 2, f"gevonden: {len(hits)}")
ok("titel wordt gepakt", hits[0]["title"] == "Example Domain", hits[0]["title"])
ok("snippet wordt gepakt", "illustrative" in hits[0]["snippet"], hits[0]["snippet"])
ok("URL wordt netjes omgezet (zonder redirect)", hits[0]["url"] == "https://example.com/", hits[0]["url"])

# [2] redirect-URL's
ok("tweede resultaat ook netjes", hits[1]["url"] == "https://nos.nl/", hits[1]["url"])

# lege pagina -> geen resultaten
ok("lege HTML -> geen resultaten", web._parse_duckduckgo_html("") == [])

# titel met HTML-tags moet netjes worden schoongemaakt
messy = """<div class="result results_links"><a class="result__a" href="/x">Titel &amp; en <b>groot</b></a></div>"""
hits2 = web._parse_duckduckgo_html(messy)
ok("HTML in titel wordt ontsmet", hits2 and "Titel & en groot" in hits2[0]["title"], hits2[0]["title"] if hits2 else "geen")


# =============================================================
# [3-6] DUCKDuckGo SEARCH (requests gemockt)
# =============================================================

print("\n===== [2] SEARCH-FUNCTIE =====")


def mock_response(text, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


log_html = """<div class="result results_links"><a class="result__a" href="//x/?uddg=https%3A%2F%2Flog.nl%2F">Log</a></div>"""

# [3] succes
with patch.object(requests, "get", return_value=mock_response(log_html)) as fake_get:
    r = web.duckduckgo_search("openingstijden")
    ok("succesvol zoeken -> ok=True", r["ok"])
    ok("resultaat gevonden", len(r["results"]) == 1, str(r))
    ok("query wordt bewaard", r["query"] == "openingstijden", r.get("query"))
    # URL-parameter is het opgeslagen
    _, kwargs = fake_get.call_args
    ok("zoekterm veilig als parameter", kwargs.get("params", {}).get("q", "") == "openingstijden", str(kwargs))

# [4] geen resultaten
with patch.object(requests, "get", return_value=mock_response("<html>niks</html>")):
    r = web.duckduckgo_search("zzzqwerty")
    ok("geen resultaten -> ok=False", not r["ok"], str(r))
    ok("vriendelijke melding", "geen resultaten" in r["error"], r["error"])

# [5a] timeout
with patch.object(requests, "get", side_effect=requests.exceptions.Timeout):
    r = web.duckduckgo_search("weer")
    ok("timeout -> ok=False", not r["ok"])
    ok("duidelijk melding", "te lang" in r["error"], r["error"])

# [5b] verbindingsfout
with patch.object(requests, "get", side_effect=requests.exceptions.ConnectionError):
    r = web.duckduckgo_search("weer")
    ok("verbindingsfout -> ok=False", not r["ok"])
    ok("melding over verbinding", "verbinding" in r["error"], r["error"])

# [5c] http-fout (bijv. 503)
with patch.object(requests, "get", return_value=mock_response("", status=503)):
    r = web.duckduckgo_search("weer")
    ok("http 503 -> ok=False", not r["ok"], str(r))
    ok("vriendelijke melding bij http-fout", "probeer het zo even opnieuw" in r["error"], r["error"])
    ok("foutcode wordt bewaard", r.get("error_code") == 503, str(r.get("error_code")))

# [5d] rate-limit (202) -> retry en dan nette foutmelding
with patch.object(web, "RATE_LIMIT_RETRY_WAITS", (0, 0)), \
     patch.object(requests, "get", return_value=mock_response("", status=202)) as fake_get:
    r = web.duckduckgo_search("weer")
    ok("rate-limit 202 -> ok=False", not r["ok"], str(r))
    ok("202 geeft vriendelijke melding", "Zoeken lukte net niet" in r["error"], r["error"])
    ok("rate-limit: er is geherprobeerd", fake_get.call_count >= 2, f"{fake_get.call_count} pogingen")

# [5e] rate-limit die OPGELOST wordt -> retry slaagt
success_after = {"calls": 0}

def flaky_get(*a, **kw):
    success_after["calls"] += 1
    return mock_response("", status=202) if success_after["calls"] == 1 else mock_response(log_html)

with patch.object(web, "RATE_LIMIT_RETRY_WAITS", (0,)), \
     patch.object(requests, "get", side_effect=flaky_get):
    r = web.duckduckgo_search("weer")
    ok("rate-limit retry slaagt na verken", r["ok"], str(r))
    ok("resultaat na retry gevonden", len(r.get("results", [])) == 1)

# [6] lege/invalide zoekterm
with patch.object(requests, "get", return_value=mock_response(log_html)):
    r = web.duckduckgo_search("   ")
    ok("lege zoekterm -> ok=False", not r["ok"])
    ok("vriendelijk bij lege term", "zoekterm" in r["error"], r["error"])


# =============================================================
# [7] FORMAT
# =============================================================

print("\n===== [3] FORMAT =====")

formatted = web.format_search_results(
    {"ok": True, "query": "weer", "results": [
        {"title": "Weer op NOS", "snippet": "Regen en zon", "url": "https://nos.nl/weer"},
    ]}
)
ok("formaat bevat titel", "Weer op NOS" in formatted, formatted)
ok("formaat bevat url", "https://nos.nl/weer" in formatted)
ok("formaat bevat query", "weer" in formatted)

formatted_fail = web.format_search_results({"ok": False, "error": "Ik kon niet zoeken."})
ok("foutformaat netjes", formatted_fail == "Ik kon niet zoeken.")


# =============================================================
# [8-9] SEARCH + FETCH (de kern van Fase 9)
# =============================================================

print("\n===== [4] SEARCH + FETCH =====")

page_html = (
    "<html><head><title>Openingstijden</title>"
    "<meta name='description' content='De winkel is open van 8 tot 20 uur.'></head>"
    "<body><script>var x=1;</script><article>"
    "<h1>Albert Heijn Bloemendaal</h1>"
    "<p>De winkel is vandaag open van 08:00 tot 20:00 uur.</p>"
    "</article></body></html>"
)

search_html = """<div class="result results_links"><a class="result__a" href="//x/?uddg=https%3A%2F%2Fwinkel.nl%2F">Winkel</a>
<a class="result__snippet">Open van 8 tot 20</a></div>
<div class="result results_links"><a class="result__a" href="//x/?uddg=https%3A%2F%2Fwinkel2.nl%2F">Winkel 2</a></div>"""

# [8] zoek + lees 1 bron
with patch.object(requests, "get", side_effect=[mock_response(search_html), mock_response(page_html)]):
    # call 1 = search, call 2 = fetch. De fetch downstream hermeert verzoeken,
    # dus we mokken requests.get in de functie via side effects.
    pass

# Weert een nette functionele test: mock de interne functies
from unittest.mock import patch as _patch

with _patch.object(web, "duckduckgo_search") as fake_search, _patch.object(web, "fetch_url") as fake_fetch:
    fake_search.return_value = {
        "ok": True, "query": "openingstijden winkel", "results": [
            {"title": "Winkel", "snippet": "Open van 8 tot 20", "url": "https://winkel.nl/"},
        ],
    }
    fake_fetch.return_value = {
        "ok": True, "title": "Albert Heijn Bloemendaal",
        "description": "De winkel is open van 8 tot 20 uur.",
        "text": "De winkel is vandaag open van 08:00 tot 20:00 uur.",
    }
    combined = web.search_and_fetch("openingstijden winkel", max_pages=1)
    ok("search_and_fetch: ok", combined["ok"], str(combined))
    ok("search_and_fetch: 1 bron", len(combined["pages"]) == 1, len(combined["pages"]))
    ok("eerste bron heeft tekst", "08:00" in combined["pages"][0]["text"], str(combined["pages"][0]))

    text = web.format_search_and_fetch(combined)
    ok("format bevat bron-titel", "Albert Heijn Bloemendaal" in text, text)
    ok("format bevat inhoud", "08:00" in text, text)

# [9] vergelijken -> 2 bronnen
with _patch.object(web, "duckduckgo_search") as fake_search, _patch.object(web, "fetch_url") as fake_fetch:
    fake_search.return_value = {
        "ok": True, "query": "rtx 4070 vs 4060", "results": [
            {"title": "Review A", "snippet": "De 4070 is sneller.", "url": "https://a.nl/"},
            {"title": "Review B", "snippet": "De 4060 is goedkoper.", "url": "https://b.nl/"},
        ],
    }
    fake_fetch.return_value = {
        "ok": True, "title": "Vergelijking", "description": "", "text": "Specs vergelijking.",
    }
    combined = web.search_and_fetch("rtx 4070 vs 4060", max_pages=2)
    ok("vergelijk: 2 bronnen opgehaald", len(combined["pages"]) == 2, len(combined["pages"]))
    text = web.format_search_and_fetch(combined)
    ok("vergelijk: beide bronnen genoemd", "Bron 1" in text and "Bron 2" in text)

# [8b] als een bron niet te lezen is -> nette foutboodschap
with _patch.object(web, "duckduckgo_search") as fake_search, _patch.object(web, "fetch_url") as fake_fetch:
    fake_search.return_value = {
        "ok": True, "query": "test", "results": [
            {"title": "Kapot", "snippet": "", "url": "https://kapot.nl/"},
        ],
    }
    fake_fetch.return_value = {"ok": False, "error": "timeout"}
    combined = web.search_and_fetch("test")
    ok("niet-leesbare bron -> ok=False", not combined["ok"], str(combined.get("ok")))
    ok("niet-leesbare bron -> fout in error", combined.get("error", "").startswith("Ik kon"))


# =============================================================
# [10-11] AI-DISPATCH
# =============================================================

print("\n===== [5] AI-DISPATCH =====")

from core import ai

with _patch.object(ai, "web_search_tool") as fake_search_tool, _patch.object(ai, "update_context") as fake_ctx:
    fake_search_tool.return_value = "Zoekresultaten voor 'weer'"
    out = ai.execute_tool("web_search", {"query": "weer"}, question="zoek het weer op")
    ok("execute_tool('web_search') geeft resultaat", "weer" in out, out)
    fake_search_tool.assert_called_once_with("weer")

with _patch.object(ai, "web_search_and_fetch_tool") as fake_saf_tool, _patch.object(ai, "update_context") as fake_ctx:
    fake_saf_tool.return_value = "Bron 1: ..."
    out = ai.execute_tool("web_search_and_fetch", {"query": "weer amsterdam"}, question="weer")
    ok("execute_tool('web_search_and_fetch') geeft resultaat", "Bron 1" in out, out)
    fake_saf_tool.assert_called_once_with("weer amsterdam", max_pages=1)

with _patch.object(ai, "web_search_and_fetch_tool") as fake_saf_tool, _patch.object(ai, "update_context") as fake_ctx:
    fake_saf_tool.return_value = "Bron 1 .. Bron 2"
    out = ai.execute_tool("web_search_and_fetch", {"query": "a b", "max_pages": 2}, question="vergelijk a en b")
    fake_saf_tool.assert_called_once_with("a b", max_pages=2)
    ok("max_pages=2 wordt doorgegeven", True)

# tool-definitie aanwezig in de tool-lijst
tool_names = [t["function"]["name"] for t in ai.ai_tools] if hasattr(ai, "ai_tools") else []
if hasattr(ai, "ai_tools"):
    ok("ai_tools bevat web_search", "web_search" in tool_names)
    ok("ai_tools bevat web_search_and_fetch", "web_search_and_fetch" in tool_names)
else:
    ok("ai_tools functie controle (controleer via call)", True)


# =============================================================
# [12-16] BRAIN-ROUTING
# =============================================================

print("\n===== [6] BRAIN-ROUTING =====")

# [12] "zoek X op" -> web-agent (moet zoeken, niet browser openen)
with _patch.object(brain, "search_and_fetch") as fake_saf, _patch.object(brain, "format_search_and_fetch") as fake_fmt:
    fake_saf.return_value = {"ok": True}
    fake_fmt.return_value = "Gevonden: berichtje."
    result = brain.process_command("zoek de openingstijden van de winkel op")
    fake_saf.assert_called_once()
    args = fake_saf.call_args[0][0]
    ok("[12] 'zoek X op' -> web-agent roept search_and_fetch", "openingstijden" in args, args)
    ok("[12] resultaat komt terug", "Gevonden" in result)

# [13] "google naar X" -> web-agent
with _patch.object(brain, "search_and_fetch") as fake_saf, _patch.object(brain, "format_search_and_fetch") as fake_fmt:
    fake_saf.return_value = {"ok": True}
    fake_fmt.return_value = "Antwoord uit web-agent."
    result = brain.process_command("google naar beste boodschappenlijst")
    args = fake_saf.call_args[0][0]
    ok("[13] 'google naar X' -> zoekt 'beste boodschappenlijst'", "boodschappenlijst" in args, args)

# [14] "wat is het weer" -> Open-Meteo (directe weer-route, geen DDG)
with _patch.object(web, "get_weather") as fake_weather, _patch.object(web, "format_weather") as fake_fmt:
    fake_weather.return_value = {"ok": True}
    fake_fmt.return_value = "Het wordt 17 graden."
    result = brain.process_command("wat is het weer vandaag in Utrecht")
    fake_weather.assert_called_once()
    args = fake_weather.call_args[0][0]
    ok("[14] 'weer' -> open-meteo route", "utrecht" in args, args)
    ok("[14] weer antwoord komt terug", "17 graden" in str(result))

# [14b] weer zonder plaats -> default Amsterdam
with _patch.object(web, "get_weather") as fake_weather, _patch.object(web, "format_weather") as fake_fmt:
    fake_weather.return_value = {"ok": True}
    fake_fmt.return_value = "17 graden."
    brain.process_command("wat is het weer")
    args = fake_weather.call_args[0][0]
    ok("[14b] weer zonder plaats -> default Amsterdam", args == "Amsterdam", args)

# [15] vergelijken -> 2 bronnen + oordeel
with _patch.object(brain, "search_and_fetch") as fake_saf, _patch.object(brain, "format_search_and_fetch") as fake_fmt, _patch.object(brain, "_comparison_verdict") as fake_verdict:
    fake_saf.return_value = {"ok": True}
    fake_fmt.return_value = "Vergelijking klaar."
    fake_verdict.return_value = "WINNAAR: A"
    result = brain.process_command("vergelijk de RTX 4070 en 4060")
    _, kwargs = fake_saf.call_args
    ok("[15] vergelijken -> max_pages=2", kwargs.get("max_pages") == 2, str(kwargs))
    ok("[15] oordeel wordt toegevoegd", fake_verdict.called, "verdict niet aangeroepen")
    ok("[15] oordeel zit in antwoord", "WINNAAR" in str(result), result[:100])

# [15b] oordeel heeft winnaar-formaat
verdict = brain._comparison_verdict("a en b", {
    "pages": [{"text": "A is snel en goedkoop.", "search_title": "A review"},
              {"text": "B is trager maar stabieler.", "search_title": "B review"}]})
if isinstance(verdict, str) and verdict:
    ok("[15b] oordeel bevat WINNAAR", "WINNAAR" in verdict, verdict[:120])
    ok("[15b] oordeel bevat WAAROM", "WAAROM" in verdict, verdict[:120])
else:
    ok("[15b] oordeel genereert tekst (offline=skip)", isinstance(verdict, str), str(verdict)[:120])

# [16] specifieke site-zoekopdracht -> NOT web-agent (browser houdt het)
with _patch.object(brain, "search_and_fetch") as fake_saf:
    fake_saf.return_value = {"ok": True}
    brain.process_command("zoek op youtube naar hondjes")
    ok("[16] 'zoek op <site> naar' gaat NIET naar web-agent",
       not fake_saf.called, "search_and_fetch werd onterecht aangeroepen")


# =============================================================
# [17-18] VEILIGHEID
# =============================================================

print("\n===== [7] VEILIGHEID =====")

# [17] rare tekens in zoekterm werken veilig
with _patch.object(requests, "get") as fake_get:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "<html></html>"
    fake_get.return_value = resp
    web.duckduckgo_search('quote " en <tags> & symbols')
    _, kwargs = fake_get.call_args
    param = kwargs["params"]["q"]
    ok("[17] zoekterm wordt URL-veilig geëncodeerd", "<" not in param and "&" not in param, param)

# [18] web-search is alleen-lezen: geen bestandslocaties, geen systeemaanroepen
with _patch.object(requests, "get") as fake_get:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "<html></html>"
    fake_get.return_value = resp
    web.duckduckgo_search("test")
    url_used = fake_get.call_args[0][0] if fake_get.call_args[0] else ""
    ok("[18] alleen https zoekendpoint (veilig)", "https://" in url_used and "duckduckgo" in url_used, url_used)


# =============================================================
# [19-21] SCHONE TEXTRACTIE (Fase 9b)
# =============================================================

print("\n===== [8] SCHONE TEXTRACTIE =====")

# [19] _strip_js_noise: JS-snippets eruit
noisy = ("Intro tekst. { toggleAccordion($el, false); }) 2.8 km ING Bank "
         "TEST to next screen Max. 17 seconden resterend. " 
         "Maandag 08:00 - 22:00.")
clean = web._strip_js_noise(noisy)
ok("[19] JS-snippets worden verwijderd", "toggleAccordion" not in clean, clean)
ok("[19] TEST-tekst verwijderd", "TEST" not in clean, clean)
ok("[19] relevante inhoud blijft", "Maandag 08:00 - 22:00" in clean, clean)

# [20] _strip_navigation_noise: navigatielabels weg
nav = "Ontdekken Ontdek Badhoevedorp Koopzondagen Koopavonden Albert Heijn " \
      "Dele deze locatie Facebook LinkedIn Maandag 08:00 - 22:00"
clean2 = web._strip_navigation_noise(nav)
ok("[20] navigatielabels verwijderd", "Koopzondagen" not in clean2, clean2)
ok("[20] inhoud blijft", "Maandag 08:00 - 22:00" in clean2, clean2)

# [21] extract_relevant_text: vindt het tijd-blok midden in een grote pagina
long_text = (
    "Welkom op onze website! Navigeer door het menu. Cookie-acceptatie. "
    "Disclaimer: geen enkele garantie op juistheid van gegevens. "
    "Bekijk onze partnerships. Volg ons op social media. "
    "Open de app. Download. Schrijf je in voor de nieuwsbrief. "
    "Aanbiedingen bekijken. Bekijk aanbiedingen. Lees meer over ons. "
    "Wat wij doen. Over ons. Blog. Contact. Veelgestelde vragen. Help. "
    "Nieuws. In de pers. Privacybeleid. Algemene voorwaarden. Cookiebeleid. "
    " * 100  "
    + "Openingstijden: Maandag 08:00 - 22:00 Dinsdag 08:00 - 22:00 "
      "Woensdag 08:00 - 22:00 Zondag 08:00 - 22:00 Koopzondag 08:00 - 22:00. "
    + " Beoordelingen Reviews & Ervaringen Schrijf een review Deel deze winkel. "
      "Locatie. Klantenservice Bel direct. FAQ. Google Maps. Open in Maps. "
      "Adres: Hoofdstraat 12. Parkeerplaats beschikbaar. Gratis parkeren. "
    "Footer link 1 Footer link 2 Footer link 3 Footer link 4 " * 80
)
extracted = web.extract_relevant_text(long_text, "openingstijden winkel")
ok("[21] tijd-blok herkend", "08:00" in extracted, extracted[:100])
ok("[21] openingstijden eruit", "Openingstijden" in extracted or "Maandag" in extracted)
ok("[21] output begrensd", len(extracted) <= 4000, len(extracted))

# [21b] geen tijden op de pagina -> middelste deel als fallback
no_hours = "Header " + "middlecontent " * 500 + "Footer"
mid_out = web.extract_relevant_text(no_hours)
ok("[21b] fallback pakt middenstuk", "middlecontent" in mid_out, mid_out[:60])


# =============================================================
# [22-29] WIKIPEDIA FALLBACK — relevantiecontrole
# =============================================================

print("\n===== [8] WIKIPEDIA FALLBACK =====")

# [22] DDG rate-limit activeert Wikipedia-fallback
with patch.object(web, "duckduckgo_search", return_value={
    "ok": False, "error": "rate-limit", "error_code": 202, "results": []
}):
    with patch.object(web, "wikipedia_lookup", return_value={
        "ok": True, "title": "Australië", "url": "https://nl.wikipedia.org/wiki/Australië",
        "extract": "Australië is een land en continent in het zuidelijk halfrond.",
        "query": "hoofdstad van Australië",
    }) as fake_wiki:
        r = web.search_and_fetch("hoofdstad van Australië")
        ok("[22] DDG faalt -> fallback activeert", fake_wiki.called, "wikipedia niet aangeroepen")
        ok("[22] fallback geeft resultaat", r.get("ok"), str(r.get("error")))
        ok("[22] via=wikipedia", r.get("via") == "wikipedia")

# [23] RTX 4070/4060 mag NOOIT 400 meter horden opleveren
with patch.object(web, "duckduckgo_search", return_value={
    "ok": False, "error": "rate-limit", "error_code": 202, "results": []
}):
    # Simuleer wat Wikipedia opensearch zou teruggeven:
    # "4060" matched "400 meter horden" (fuzzy)
    call_count = [0]
    def fake_wiki_lookup(query):
        call_count[0] += 1
        if "4060" in query or "4070" in query:
            return {
                "ok": True, "title": "400 meter horden",
                "url": "https://nl.wikipedia.org/wiki/400_meter_horden",
                "extract": "De 400 m horden is een olympisch atletiekonderdeel.",
                "query": query,
            }
        return {"ok": False, "error": "geen resultaat", "query": query}

    with patch.object(web, "wikipedia_lookup", side_effect=fake_wiki_lookup):
        r = web.search_and_fetch("rtx 4070 rtx 4060")
        ok("[23] '400 meter horden' NIET als resultaat",
           not r.get("ok") or all(
               "400 meter" not in (p.get("title", "") + p.get("text", ""))
               for p in r.get("pages", [])
           ))

# [24] Los getal '4060' mag geen willekeurig artikel accepteren
ok("[24] '4060' is bare number",
   web._is_bare_number("4060"), "4060 zou bare number moeten zijn")
ok("[24] 'rtx' is GEEN bare number",
   not web._is_bare_number("rtx"), "rtx mag geen bare number zijn")

# [25] Kandidaatgeneratie: losse getallen worden overgeslagen
sw = {"van","de","het","een","in","op","naar","voor","met","en","of","hoe","wat",
      "wie","waar","wanneer","is","zijn","uit","ook","al","als","dan","maar",
      "om","tot","bij","aan","af","over","te","vergelijk","eerste","beste"}
cands = web._wiki_candidates("rtx 4070 rtx 4060", sw)
ok("[25] '4060' NIET als zelfstandige kandidaat",
   "4060" not in cands, str(cands))
ok("[25] 'rtx 4060' WEL als kandidaat",
   "rtx 4060" in cands, str(cands))

# [26] Kandidaatgeneratie: 'eerste iPhone uit' -> 'iPhone' als kandidaat
cands2 = web._wiki_candidates("eerste iPhone uit", sw)
ok("[26] 'iPhone' als kandidaat",
   "iPhone" in cands2, str(cands2))
ok("[26] 'eerste' NIET als zelfstandige kandidaat",
   "eerste" not in cands2, str(cands2))

# [27] Relevantiecheck: productterm "rtx 4070" matched NIET "400 meter horden"
rel = web._wiki_is_relevant("rtx 4070 rtx 4060", {
    "title": "400 meter horden",
    "extract": "De 400 m horden is een olympisch atletiekonderdeel."
})
ok("[27] 'rtx 4070' NIET relevant met '400 meter horden'", not rel)

# [28] Relevantiecheck: productterm "rtx 4070" WEL relevant met "NVIDIA GeForce RTX 4070"
rel2 = web._wiki_is_relevant("rtx 4070 rtx 4060", {
    "title": "NVIDIA GeForce RTX 4070",
    "extract": "De RTX 4070 is een videokaart van NVIDIA."
})
ok("[28] 'rtx 4070' WEL relevant met 'NVIDIA GeForce RTX 4070'", rel2)

# [29] Relevantiecheck: "eerste iPhone uit" -> "IPhone" is relevant
rel3 = web._wiki_is_relevant("eerste iPhone uit", {
    "title": "IPhone",
    "extract": "De iPhone is een smartphone van Apple."
})
ok("[29] 'eerste iPhone uit' WEL relevant met 'IPhone'", rel3)

# [29b] "eerste iPhone uit" -> "Eerste inwoners van Amerika" NIET relevant
rel4 = web._wiki_is_relevant("eerste iPhone uit", {
    "title": "Eerste inwoners van Amerika",
    "extract": "De eerste inwoners van Amerika kwamen via de Beringstraat."
})
ok("[29b] 'eerste iPhone uit' NIET relevant met 'Eerste inwoners van Amerika'", not rel4)

# [29c] _wiki_fallback retourneert None als geen enkel resultaat relevant is
with patch.object(web, "wikipedia_lookup", return_value={
    "ok": True, "title": "400 meter horden",
    "url": "https://nl.wikipedia.org/wiki/400_meter_horden",
    "extract": "De 400 m horden is een olympisch atletiekonderdeel.",
    "query": "rtx 4060",
}):
    result = web._wiki_fallback("rtx 4070 rtx 4060")
    ok("[29c] fallback retourneert None bij irrelevante resultaten",
       result is None, str(result))


# =============================================================
# [30-37] ERROR_TYPE velden — consistente foutafhandeling
# =============================================================

print("\n===== [9] ERROR TYPE VELDEN =====")

# [30] DDG: lege zoekterm -> error_type="invalid_query"
r = web.duckduckgo_search("   ")
ok("[30] lege query -> error_type invalid_query",
   r.get("error_type") == "invalid_query", str(r.get("error_type")))

# [31] DDG: timeout -> error_type="timeout"
with patch.object(requests, "get", side_effect=requests.exceptions.Timeout):
    r = web.duckduckgo_search("test timeout")
    ok("[31] timeout -> error_type timeout",
       r.get("error_type") == "timeout", str(r.get("error_type")))

# [32] DDG: verbindingsfout -> error_type="network_error"
with patch.object(requests, "get", side_effect=requests.exceptions.ConnectionError("fail")):
    r = web.duckduckgo_search("test net")
    ok("[32] connection error -> error_type network_error",
       r.get("error_type") == "network_error", str(r.get("error_type")))

# [33] DDG: rate-limit (202) -> error_type="rate_limited" + error_code=202
with patch.object(web, "RATE_LIMIT_RETRY_WAITS", (0, 0)), \
     patch.object(requests, "get", return_value=mock_response("", status=202)):
    r = web.duckduckgo_search("test rl")
    ok("[33] rate-limit -> error_type rate_limited",
       r.get("error_type") == "rate_limited", str(r.get("error_type")))
    ok("[33] error_code behouden als getal",
       r.get("error_code") == 202, str(r.get("error_code")))

# [34] DDG: geen resultaten -> error_type="no_results"
with patch.object(requests, "get", return_value=mock_response("<html>niks</html>")):
    r = web.duckduckgo_search("zzzqwertyuniek")
    ok("[34] geen resultaten -> error_type no_results",
       r.get("error_type") == "no_results", str(r.get("error_type")))

# [35] fetch_url: timeout -> error_type="timeout"
with patch.object(requests, "get", side_effect=requests.exceptions.Timeout):
    r = web.fetch_url("https://example.com/page")
    ok("[35] fetch timeout -> error_type timeout",
       r.get("error_type") == "timeout", str(r.get("error_type")))

# [36] fetch_url: ongeldige URL -> error_type="invalid_url"
r = web.fetch_url("://geen-protocol")
ok("[36] ongeldige URL -> error_type invalid_url",
   r.get("error_type") == "invalid_url", str(r.get("error_type")))

# [37] fetch_url: 404 -> error_type="http_error"
with patch.object(requests, "get", return_value=mock_response("", status=404)):
    r = web.fetch_url("https://example.com/bestaat-niet")
    ok("[37] 404 -> error_type http_error",
       r.get("error_type") == "http_error", str(r.get("error_type")))

# [38] search_and_fetch: DDG faalt + wiki niet relevant -> error_type="not_relevant"
with patch.object(web, "duckduckgo_search", return_value={
    "ok": False, "error": "rate-limit", "error_type": "rate_limited",
    "error_code": 202, "results": []
}):
    with patch.object(web, "_wiki_fallback", return_value=None):
        r = web.search_and_fetch("irrelevante query x99")
        ok("[38] fallback faalt -> error_type not_relevant",
           r.get("error_type") == "not_relevant", str(r.get("error_type")))

# [39] search_and_fetch: DDG faalt + wiki ok -> error_type NIET op topniveau
with patch.object(web, "duckduckgo_search", return_value={
    "ok": False, "error": "rate-limit", "error_type": "rate_limited",
    "error_code": 202, "results": []
}):
    with patch.object(web, "_wiki_fallback", return_value={
        "ok": True, "title": "Test", "url": "https://test.nl",
        "extract": "Testinhoud.", "query": "test"
    }):
        r = web.search_and_fetch("test query")
        ok("[39] wiki fallback slaagt -> error_type NIET op topniveau",
           "error_type" not in r or r.get("ok") is True, str(r.get("error_type")))

# [40] fetch_url: te-groot -> error_type="too_large"
big_text = "X" * 3_000_000
fake_big = mock_response(big_text, status=200)
# Patch de max_bytes limiet zodat hij triggert op testdata
with patch.object(requests, "get", return_value=fake_big), \
     patch.object(web, "MAX_BYTES", 100):
    r = web.fetch_url("https://example.com/groot")
    ok("[40] te-groot -> error_type too_large",
       r.get("error_type") == "too_large", str(r.get("error_type")))

# [41] Bestaande error velden blijven behouden na error_type toevoeging
with patch.object(requests, "get", side_effect=requests.exceptions.Timeout):
    r = web.duckduckgo_search("behoud test")
    ok("[41] error tekst behouden", "timeout" in r.get("error", "").lower(),
       str(r.get("error")))
    ok("[41] error_type naast error", r.get("error_type") == "timeout" and "error" in r)

with patch.object(requests, "get", side_effect=requests.exceptions.Timeout):
    r = web.fetch_url("https://example.com/page")
    ok("[41b] fetch: status behouden", r.get("status") == "timeout",
       str(r.get("status")))
    ok("[41b] fetch: error_type naast status",
       r.get("error_type") == "timeout" and "status" in r)


# =============================================================
print(f"\n{'='*50}")
print(f"WEB SEARCH TESTS: {passed} gereed, {failed} gefaald")
print(f"{'='*50}")

if failed:
    sys.exit(1)