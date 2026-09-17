"""
Web Fetch + Search (Fase 8/9) — webpagina's ophalen, lezen en zoeken.

JARVIS kan niet alleen websites OPENEN in de browser, maar ook:
  - De INHOUD van een pagina ophalen en als leesbare tekst teruggeven (Fase 8)
  - Zoeken via DuckDuckGo en de resultaten openen/lezen (Fase 9)

Veiligheid:
  - Alleen http/https-URL's (geen file:// etc.)
  - Timeout (15 sec)
  - Grootte-begrenzing (max 2 MB) zodat enorme pagina's niet vastlopen
  - Nette foutmeldingen bij 404, netwerkfouten, ongeldige URL's
  - DuckDuckGo: HTML-zoekmodule, geen API-key nodig
"""
import re
import html as html_lib
import urllib.parse as _up
from urllib.parse import urlparse, quote_plus

import requests

TIMEOUT = 15
MAX_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_TEXT_LENGTH = 4000


def is_safe_url(url):

    url = (url or "").strip()

    if not url:
        return False

    parsed = urlparse(url)

    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _clean_text(text):

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def html_to_text(html):

    """Haal leesbare tekst uit een HTML-bron. Zonder bs4/extra libs."""

    if not html:
        return ""

    # Inline javascript/css verwijderen
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)

    # Headers/navigatiekruimels zijn geen content
    html = re.sub(r"<(head|header|footer|nav|aside)[^>]*>.*?</\1>", " ",
                  html, flags=re.S | re.I)

    # Verborgen inhoud (aria-hidden, hidden, niet-getoonde div's) weghalen:
    # die bevatten vaak JS-gegenereerde kopieën van navigatie of cookies.
    html = re.sub(
        r'<(div|section|span|p|ul|ol|form)[^>]*(?:aria-hidden=["\']?true|hidden|'
        r'display\s*:\s*none|style="[^"]*(?:display\s*:\s*none|visibility\s*:\s*hidden))[^>]*>'
        r'.*?</\1>',
        " ", html, flags=re.S | re.I)

    # Login/aanmelden-modalen zijn geen antwoordcontent
    html = re.sub(r'<div[^>]*class=["\'][^"\']*(modal|dialog|popup|login|' +
                  r'cookie|banner|cookie-banner|cookiebar)[^"\']*["\'][^>]*>.*?</div>',
                  " ", html, flags=re.S | re.I)

    # Tags vervangen door witruimte, entities decoderen
    text = re.sub(r"<[^>]+>", " ", html)
    text = html_lib.unescape(text)

    # Wikipedia-markup opschonen ([[link|weergavetekst]], {{sjabloon}}, richting-aanwijzingen)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[[^|\]]*\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[[^\]]*\]\]", " ", text)
    text = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.S | re.I)

    # Meerdere lege regels comprimeren, lege regels eruit
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if len(ln) > 1]
    text = " ".join(lines)

    return _clean_text(text)


def _strip_js_noise(text):

    """Verwijder JS-achtige snippets die in de tekst zijn achtergebleven."""

    # JS-proposities: { toggleAccordion(...) }, function(x) => { ... }, if (value) { setTimeout(...) }
    text = re.sub(r"\{[^{}]{0,200}(toggleAccordion|setTimeout|addEventListener|\.map\(|\.filter\(|initHandyNearby|if\s*\()[^}]{0,200}\}", " ", text)

    # Regels die bijna geheel uit code bestaan (CSS-selectors, var =, $.something)
    text = re.sub(r"(?:^|\s)(?:\.[\w-]+\s*\{|var\s+\w+|\.init[\w-]+|function\s*\(|const\s+\w+\s*=|=>\s*\{).*", " ", text)

    # Lineaire expressies met ";" aan het einde = JS
    text = re.sub(r"[^;]{5,200};\s*$", " ", text, flags=re.M)

    # Zin "TEST to next screen Max. X seconden resterend"
    text = re.sub(r"TEST\s+to\s+next\s+screen[^.!?]{0,120}", " ", text, flags=re.I)

    return _clean_text(text)


def _strip_navigation_noise(text):

    """Verwijder veelgebruikte navigatie-labels en korte niet-content."""

    nav_words = (
        r"Ontdekken|Ontdek|Koopzondagen|Koopavonden|Login|Inloggen|"
        r"Uw gegevens|Gegevens verzenden|Delen|Deel deze locatie|"
        r"Opslaan|Opslaan in lijst|Nieuwe lijst|Sluit nieuwe lijst|"
        r"Link kopiëren|Stel een bewerking voor|Bedrijf beheren|"
        r"Handig in de buurt|Postkantoren|Tankstations|"
        r"Wil je hier meer informatie over|Reacties|"
        r"Bewerking voor|Stap [0-9]/[0-9]|"
        r"Raadpleeg de winkelwebsite|Zie de website|Ga naar de website"
    )
    text = re.sub(rf"(?:^|\s)(?:{nav_words})(?:\s|$)", " ", text, flags=re.I)

    # Korte labels (1-2 woorden) die herhaald worden: filter niet te agressief
    # maar verwijder duidelijke catalogus-labels (Banken, Hotels, Restaurants etc.)
    text = re.sub(r"\b(Banken|Hotels|Restaurants|Supermarkten|"
                  r"Recepten|Allerhande|Bonusaanbiedingen|"
                  r"Bekijk|Lees meer|Toon meer|Laat een review achter)\b",
                  " ", text, flags=re.I)

    return _clean_text(text)


def extract_relevant_text(text, query=""):

    """Extraheer het meest relevante deel van een pagina.
    Zoekt naar gestructureerde patronen (dagen+tijden) die vaak
    midden op de pagina staan. Werkt op de VOLLEDIGE tekst en
    kapt pas aansluitend af op MAX_TEXT_LENGTH.
    """

    if not text:
        return text

    text = _strip_js_noise(text)
    text = _strip_navigation_noise(text)

    if len(text) <= MAX_TEXT_LENGTH:
        return text

    # Zoek naar gestructureerde tijd-gegevens (dagen met tijden)
    day = r"(?:ma|di|wo|do|vr|za|zo|maandag|dinsdag|woensdag|donderdag|" \
          r"vrijdag|zaterdag|zondag|mon|tue|wed|thu|fri|sat|sun|" \
          r"vandaag|today|gisteren|morgen)"
    hours = r"\d{1,2}[:.]\d{2}\s*(?:-|–|—|tot|/%|:)\s*\d{1,2}[:.]\d{2}"
    hours_pattern = re.compile(
        day + r"\D{0,80}" + hours, re.I
    )

    # Verzamel alle tijd-blokken en kies de grootste aaneengesloten groepering
    flat = re.sub(r"\s+", " ", text)
    matches = list(hours_pattern.finditer(flat))

    if matches:
        # Het blok met de meeste opeenvolgende tijd-regels wint
        best = []
        current = [matches[0]]
        for prev, m in zip(matches, matches[1:]):
            gap = m.start() - prev.end()
            if gap <= 900:  # dicht bij elkaar = zelfde tabel
                current.append(m)
            else:
                if len(current) > len(best):
                    best = current
                current = [m]
        if len(current) > len(best):
            best = current

        start = best[0].start() - 200
        end = best[-1].end() + 700
        start = max(0, start)
        end = min(len(flat), end)
        chunk = flat[start:end]

        # Alles na het laatste dag+tijd-blok weghalen (reviews, footers etc.)
        last_hours_match = list(hours_pattern.finditer(chunk))
        if last_hours_match:
            cut = last_hours_match[-1].end()
            chunk = chunk[:cut + 100]

        return truncate_text(chunk)

    # Geen tijd-gegevens gevonden: kies het deel met de meeste
    # zoektermen (relevante tekst bevat vaak de query-termen).
    # Alles bovenin is navigatie, onderin voettekst.
    flat = re.sub(r"\s+", " ", text)
    terms = [q for q in re.split(r"[^a-zà-ÿ0-9]+", query.lower()) if len(q) > 2]

    best_start = 0
    best_score = -1
    window = MAX_TEXT_LENGTH + 800
    if terms:
        # score elk venster venster op aanwezige zoektermen
        for start in range(0, max(1, len(flat) - window), 200):
            chunk_candidate = flat[start:start + window]
            low = chunk_candidate.lower()
            score = sum(low.count(t) for t in terms)
            if score > best_score:
                best_score = score
                best_start = start
        start = best_start
    else:
        # geen termen: pak het middelste deel van de pagina
        start = len(text) // 3

    chunk = flat[start:start + window]

    # Schone randen
    chunk = _trim_chunk_edges(chunk, True, start + len(chunk) < len(flat))

    return truncate_text(chunk)


def _trim_chunk_edges(chunk, trim_start, trim_end):

    chunk = chunk.strip()

    if trim_start:
        # begin op zijn vroegst na de eerste zin/regelgrens
        m = re.search(r"(?:[.!?]\s+|\n)", chunk)
        if m:
            chunk = chunk[m.end():]

    if trim_end:
        # eindig na een volledige zin, maar sla decimalen en
        # afkortingen over (bijv. "12.5", "70.", "etc.")
        # Pak de LAATSTE zinseinde in het blok, zodat bovenaan
        # verhalende tekst blijft staan.
        sentence_ends = [
            m.end() for m in re.finditer(
                r"[.!?](?!\d)\s+[A-Z]",
                chunk
            )
        ]
        if sentence_ends:
            cut = sentence_ends[-1]
            chunk = chunk[:cut]

    return chunk.strip()


def extract_title(html):

    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.S | re.I)
    if match:
        return _clean_text(html_lib.unescape(match.group(1)))
    return ""


def extract_meta_description(html):

    # <meta name="description" content="...">
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html, flags=re.I
    )
    if not match:
        # omgekeerde volgorde van attributen
        match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
            html, flags=re.I
        )
    if match:
        return _clean_text(html_lib.unescape(match.group(1)))
    return ""


def fetch_url(url, timeout=TIMEOUT, max_bytes=MAX_BYTES):

    """Haal een webpagina op. Geeft een dict met status en inhoud terug.

    Foutreturns bevatten optioneel een `error_type` veld met een
    machine-leesbare code: invalid_url, timeout, network_error,
    http_error, too_large."""

    if not is_safe_url(url):
        return {
            "ok": False,
            "status": "ongeldige-url",
            "error_type": "invalid_url",
            "error": "Dat is geen geldige web-URL. Geef een adres dat begint met http:// of https://.",
            "title": "",
            "text": "",
        }

    try:
        response = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            },
        )

    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "status": "timeout",
            "error_type": "timeout",
            "error": "De website reageerde niet op tijd.",
            "title": "",
            "text": "",
        }

    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "status": "verbinding",
            "error_type": "network_error",
            "error": "Ik kon geen verbinding maken met die website.",
            "title": "",
            "text": "",
        }

    except requests.exceptions.MissingSchema:
        return {
            "ok": False,
            "status": "ongeldige-url",
            "error_type": "invalid_url",
            "error": "Dat is geen geldige web-URL.",
            "title": "",
            "text": "",
        }

    except requests.RequestException as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": "Er ging iets mis bij het ophalen van de pagina.",
            "title": "",
            "text": "",
        }

    if response.status_code == 404:
        return {
            "ok": False,
            "status": "404",
            "error_type": "http_error",
            "error": "Die pagina bestaat niet (404).",
            "title": "",
            "text": "",
        }

    if response.status_code != 200:
        return {
            "ok": False,
            "status": str(response.status_code),
            "error_type": "http_error",
            "error": f"De website gaf code {response.status_code} terug.",
            "title": "",
            "text": "",
        }

    html = response.text

    if len(html.encode("utf-8", errors="ignore")) > max_bytes:
        return {
            "ok": False,
            "status": "te-groot",
            "error_type": "too_large",
            "error": "Die pagina is te groot om te verwerken.",
            "title": "",
            "text": "",
        }

    text = html_to_text(html)
    title = extract_title(html) or url
    description = extract_meta_description(html)

    return {
        "ok": True,
        "status": "200",
        "url": url,
        "title": title,
        "description": description,
        "text": text,
    }


def truncate_text(text, max_length=MAX_TEXT_LENGTH):

    if not text:
        return ""

    if len(text) <= max_length:
        return text

    return text[:max_length].rsplit(" ", 1)[0] + "... (pagina afgekapt)"


def format_fetch_result(result):

    if not result.get("ok"):
        return result.get("error", "Ik kon de pagina niet ophalen.")

    parts = []

    if result.get("title"):
        parts.append(f"Titel: {result['title']}")

    if result.get("description"):
        parts.append(f"Omschrijving: {result['description']}")

    text = truncate_text(result.get("text", ""))

    if text:
        parts.append(f"Inhoud: {text}")

    return " ".join(parts)


# =============================================================
# SEARCH (Fase 9) — DuckDuckGo HTML-zoekmodule
# =============================================================

SEARCH_URL = "https://html.duckduckgo.com/html/"
SEARCH_TIMEOUT = 10
RATE_LIMIT_RETRY_WAITS = (3, 6, 10)


def duckduckgo_search(query, timeout=SEARCH_TIMEOUT, max_results=5):

    """Zoek op DuckDuckGo en geef een lijst met {title, snippet, url} terug.

    Foutreturns bevatten optioneel een `error_type` veld:
    invalid_query, timeout, network_error, rate_limited, http_error,
    no_results."""

    if not query or not query.strip():
        return {
            "ok": False,
            "error_type": "invalid_query",
            "error": "Geef me een zoekterm.",
            "results": [],
        }

    query = query.strip()
    encoded = quote_plus(query)

    try:
        response = requests.get(
            SEARCH_URL,
            params={"q": encoded},
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            },
        )

    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error_type": "timeout",
            "error": "De zoekopdracht duurde te lang (timeout).",
            "results": [],
        }

    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "error_type": "network_error",
            "error": "Ik kon geen verbinding maken met de zoekmachine.",
            "results": [],
        }

    except requests.RequestException:
        return {
            "ok": False,
            "error_type": "network_error",
            "error": "Er ging iets mis bij het zoeken.",
            "results": [],
        }

    if response.status_code != 200:

        # DuckDuckGo rate-limit (202): probeer meerdere keren met oplopende pauze
        if response.status_code == 202:
            import time as _time
            for wait in RATE_LIMIT_RETRY_WAITS:
                _time.sleep(wait)
                try:
                    response = requests.get(
                        SEARCH_URL,
                        params={"q": encoded},
                        timeout=timeout,
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36"
                            ),
                            "Accept": "text/html,application/xhtml+xml",
                            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                        },
                    )
                    if response.status_code == 200:
                        break
                except Exception:
                    continue

        if response.status_code != 200:
            return {
                "ok": False,
                "error_type": "rate_limited" if response.status_code == 202 else "http_error",
                "error": "Zoeken lukte net niet, probeer het zo even opnieuw.",
                "error_code": response.status_code,
                "results": [],
            }

    html = response.text
    results = _parse_duckduckgo_html(html)

    if not results:
        return {
            "ok": False,
            "error_type": "no_results",
            "error": "Ik vond geen resultaten voor je zoekterm.",
            "results": [],
        }

    return {
        "ok": True,
        "query": query,
        "results": results[:max_results],
    }


def _parse_duckduckgo_html(html):

    results = []

    # DuckDuckGo HTML-pagina heeft blokken met klasse "result results_links"
    # Elke hit heeft een .result__a link + .result__snippet
    blocks = re.split(r'<div\s+class="result\s+results_links', html, flags=re.I)

    for block in blocks[1:]:  # eerste blok is voor de header

        title_match = re.search(r'<a[^>]+class="result__a"[^>]*>(.*?)</a>', block, flags=re.S)
        snippet_match = re.search(r'<a\s+class="result__snippet"[^>]*>(.*?)</a>', block, flags=re.S)
        url_match = re.search(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"', block, flags=re.I)

        title = ""
        if title_match:
            title = re.sub(r"<[^>]+>", "", title_match.group(1))
            title = html_lib.unescape(title).strip()

        snippet = ""
        if snippet_match:
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1))
            snippet = html_lib.unescape(snippet).strip()

        url = ""
        if url_match:
            url = url_match.group(1)
            # DuckDuckGo voegt een redirect-URL toe (//duckduckgo.com/l/?uddg=...)
            uddg = re.search(r'uddg=(https?%3A[^&]+)', url)
            if uddg:
                try:
                    url = _up.unquote(uddg.group(1))
                except Exception:
                    pass

        if title or snippet:
            results.append({
                "title": title,
                "snippet": snippet,
                "url": url,
            })

    return results


def format_search_results(search_result):

    if not search_result.get("ok"):
        return search_result.get("error", "Ik kon niet zoeken.")

    parts = [f"Zoekresultaten voor '{search_result.get('query', '?')}':"]
    for i, hit in enumerate(search_result.get("results", []), 1):
        url_hint = f"\n   {hit['url']}" if hit.get("url") else ""
        parts.append(f"  {i}. {hit['title']}{url_hint}\n      {hit['snippet']}")

    return "\n".join(parts)


def search_and_fetch(query, max_pages=1):

    """Zoek, lees het beste resultaat (of de eerste N) en geef een antwoord-klaar
    blok terug: zoekresultaten + opgehaalde pagina-inhoud."""

    search = duckduckgo_search(query)

    if not search.get("ok"):
        # Fallback: DDG faalt vaak door rate-limit (202). Gebruik dan
        # Wikipedia, dat gratis en zonder rate-limit beschikbaar is.
        ddg_error_type = search.get("error_type", "http_error")
        wiki = _wiki_fallback(query)
        if wiki is not None:
            return {
                "ok": True,
                "query": query,
                "via": "wikipedia",
                "search": search,
                "pages": [{
                    "search_title": wiki.get("title", ""),
                    "url": wiki.get("url", ""),
                    "title": wiki.get("title", ""),
                    "text": wiki.get("extract", ""),
                    "source": "wikipedia",
                }],
                "errors": [{"error": search.get("error", ""), "error_type": ddg_error_type}],
            }
        return {
            "ok": False,
            "error_type": "not_relevant",
            "error": "Zoeken lukte net niet. Probeer het over een paar seconden opnieuw.",
            "search": search,
            "pages": [],
        }

    results = search.get("results", [])

    pages = []
    errors = []
    used_urls = set()
    real_pages = 0

    # Blijf hits proberen tot we genoeg ECHT leesbare bronnen hebben.
    # Bij veel 403/te-groot sites vullen we later aan met snippets.
    for hit in results:
        if real_pages >= max_pages:
            break
        if not hit.get("url") or hit["url"] in used_urls:
            continue
        used_urls.add(hit["url"])
        title_from_search = hit.get("title", "")
        page = fetch_url(hit["url"])

        if page.get("ok"):
            clean_text = extract_relevant_text(page.get("text", ""), query)
            if not clean_text and real_pages >= max_pages:
                continue
            pages.append({
                "search_title": title_from_search,
                "url": hit["url"],
                "snippet": hit.get("snippet", ""),
                "title": page.get("title", title_from_search),
                "text": clean_text,
            })
            real_pages += 1
        else:
            errors.append({
                "search_title": title_from_search,
                "url": hit["url"],
                "error": page.get("error", ""),
            })

    # Vergelijkingen hebben minimaal 2 bronnen nodig: als er na alle
    # pogingen nog geen max_pages leesbare bronnen zijn, vullen we aan
    # met zoek-snippets als mini-bron (beter dan niets).
    if len(pages) < max_pages:
        used_snippets = set()
        for hit in results:
            if len(pages) >= max_pages:
                break
            url = hit.get("url") or ""
            if url in used_snippets or not hit.get("snippet"):
                continue
            used_snippets.add(url)
            pages.append({
                "search_title": hit.get("title", ""),
                "url": url,
                "snippet": hit.get("snippet", ""),
                "title": hit.get("title", ""),
                "text": hit.get("snippet", ""),
                "fallback_snippet": True,
            })

    # Als geen enkele bron leesbaar was, rapporteer dat keurig
    if not pages and errors:
        # De dominante fout: als alle errors hetzelfde error_type hebben,
        # gebruik dat; anders een generieke indicator.
        error_types = [e.get("error_type", "") for e in errors if e.get("error_type")]
        dominant_type = error_types[0] if len(set(error_types)) == 1 else "network_error"
        return {
            "ok": False,
            "error_type": dominant_type,
            "error": "Ik kon de zoekresultaten niet lezen (" +
                     ", ".join(e.get("error", "fout") for e in errors[:3]) + ").",
            "query": query,
            "search": search,
            "pages": [],
            "errors": errors,
        }

    return {
        "ok": True,
        "query": query,
        "search": search,
        "pages": pages,
        "errors": errors,
    }


def _wiki_fallback(query):

    """Probeer Wikipedia als DDG faalt. Geeft een dict terug met ok=True
    alleen als het resultaat ook daadwerkelijk relevant is voor de query.

    Geeft None terug als geen enkel resultaat relevant is."""

    stopwords = {
        "van", "de", "het", "een", "in", "op", "naar", "voor", "met",
        "en", "of", "hoe", "wat", "wie", "waar", "wanneer", "is", "zijn",
        "uit", "ook", "al", "als", "dan", "maar", "om", "tot", "bij",
        "aan", "af", "over", "te", "welk", "welke", "dit", "deze",
    }

    # Stap 1: Kandidaten genereren
    candidates = _wiki_candidates(query, stopwords)

    # Stap 2: Elke kandidaat proberen met relevantie-check
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        wiki = wikipedia_lookup(candidate)
        if not wiki.get("ok"):
            continue

        # Relevantie-controle: is het gevonden artikel wel gerelateerd
        # aan de originele query?
        if _wiki_is_relevant(query, wiki):
            return wiki

    return None


def _wiki_candidates(query, stopwords):

    """Genereer een geordende lijst van kandidaten voor Wikipedia-zoekopdracht.

    Regels:
    - Volledige query altijd als eerste kandidaat
    - Productnamen/substantieven worden samengevoegd (niet opgesplitst)
    - Losse getallen (< 4 tekens) worden OVERGESLAGEN als zelfstandige kandidaat
    - Stopwoorden worden verwijderd"""

    candidates = [query]

    # Woorden opsplitsen: bewaar zowel losse woorden als groepen
    raw_words = [w for w in re.split(r"[^a-zà-ÿA-ZÀ-ÿ0-9]+", query) if len(w) > 2]

    if not raw_words:
        return candidates

    content = [w for w in raw_words if w.lower() not in stopwords]

    if not content:
        return candidates

    # Laatste content-woord als kandidaat (MAAR niet als het een kort getal is)
    last = content[-1]
    if not _is_bare_number(last):
        candidates.append(last)

    # Laatste 2 content-woorden (bijv. "RTX 4070", "iPhone uit")
    if len(content) > 1:
        pair = " ".join(content[-2:])
        if pair not in candidates:
            candidates.append(pair)

    # Alle content-woorden samen
    all_content = " ".join(content)
    if all_content not in candidates:
        candidates.append(all_content)

    return candidates


def _is_bare_number(word):

    """Controleer of een woord een kort, los getal is dat niet als
    zelfstandige zoekterm kan dienen (bijv. '4060', '2007', '15')."""

    return bool(re.fullmatch(r"\d{1,6}", word))


def _wiki_is_relevant(query, wiki):

    """Controleer of een Wikipedia-resultaat relevant is voor de query.

    Strategie:
    1. Productnamen (bijv. "rtx 4070") moeten als geheel voorkomen
    2. Significante termen moeten in titel of extract staan
    3. Losse getallen tellen nooit als relevantie
    4. Generieke/commando-woorden tellen niet mee"""

    title = (wiki.get("title") or "").lower()
    extract = (wiki.get("extract") or "").lower()
    combined = title + " " + extract

    query_lower = query.lower()

    # Stopwoorden: Nederlandse functiewoorden + vraag/commando-woorden
    # die niets zeggen over het gewenste onderwerp
    stopwords = {
        "van", "de", "het", "een", "in", "op", "naar", "voor", "met",
        "en", "of", "hoe", "wat", "wie", "waar", "wanneer", "is", "zijn",
        "uit", "ook", "al", "als", "dan", "maar", "om", "tot", "bij",
        "aan", "af", "over", "te", "welk", "welke", "dit", "deze",
        # Commando/vraag-woorden: zeggen niets over het onderwerp
        "vergelijk", "eerste", "beste", "goedkoopste", "snelste",
        "zoek", "google", "lees",
        # Algemene woorden die te breed zijn
        "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag",
        "zaterdag", "zondag", "vandaag", "morgen",
    }

    # Woorden uit de query
    query_words = [w for w in re.split(r"[^a-zà-ÿA-ZÀ-ÿ0-9]+", query_lower) if len(w) > 2]
    content_words = [w for w in query_words if w not in stopwords]

    if not content_words:
        return False

    # Productnamen/substantieven combineren (bijv. ["rtx", "4070"] → "rtx 4070")
    multi_word_terms = _extract_product_terms(content_words)

    # Check 1: Als er producttermen zijn (zoals "rtx 4070"), moeten die
    # als geheel in de titel of extract voorkomen
    if multi_word_terms:
        for term in multi_word_terms:
            if term in combined:
                return True
        # Als productterm niet gevonden: check of de ALFABETISCHE delen
        # (bijv. "rtx") in de titel staan + er een getal-deel bij zit
        for term in multi_word_terms:
            parts = term.split()
            if len(parts) == 2:
                alpha, num = parts
                if alpha in title and num in combined:
                    return True

    # Check 2: Significante enkele termen (niet-getallen) in de titel
    significant_words = [w for w in content_words if not _is_bare_number(w)]
    if significant_words:
        matches_in_title = sum(1 for w in significant_words if w in title)
        matches_in_extract = sum(1 for w in significant_words if w in extract)
        # Minstens de helft van de significante termen in de titel
        if matches_in_title >= max(1, len(significant_words) // 2):
            return True
        # Of minstens 1 term in titel + 1 in extract
        if matches_in_title >= 1 and matches_in_extract >= 1:
            return True

    # Check 3: Korte queries (1 significant woord) — als dat woord
    # in de titel staat, is het relevant
    if len(significant_words) == 1 and significant_words[0] in title:
        return True

    return False


def _extract_product_terms(content_words):

    """Herken producttermen die uit meerdere woorden bestaan
    (bijv. ['rtx', '4070'] → ['rtx 4070'], ['iphone', '15'] → ['iphone 15']).

    Een productterm is een combinatie van een alfabetisch woord + een getal
    of een herkenbare productserie."""

    terms = []
    i = 0
    while i < len(content_words):
        word = content_words[i]
        # Als het een niet-getal is en het volgende woord een getal is
        # (bijv. "rtx" + "4070", "iphone" + "15", "samsung" + "s24")
        if not _is_bare_number(word) and i + 1 < len(content_words):
            next_word = content_words[i + 1]
            if _is_bare_number(next_word):
                terms.append(f"{word} {next_word}")
                i += 2
                continue
        i += 1

    return terms


def format_search_and_fetch(result):

    parts = []

    for i, page in enumerate(result.get("pages", []), 1):
        name = page.get("title") or page.get("search_title") or "Resultaat"
        parts.append(f"Bron {i}: {name}")
        if page.get("url"):
            parts.append(f"   ({page['url']})")
        if page.get("text"):
            parts.append(page["text"])
        elif page.get("error"):
            parts.append(f"   (kon niet lezen: {page['error']})")

    if not parts:
        return result.get("error", "Ik kon niets vinden over dat onderwerp.")

    return "\n\n".join(parts)


# =============================================================
# WEER (Open-Meteo) — gratis, geen API-key
# =============================================================

WEATHER_CODES = {
    0: "helder", 1: "overwegend helder", 2: "deels bewolkt",
    3: "bewolkt", 45: "mist", 48: "rijp",
    51: "lighte motregen", 53: "motregen", 55: "heftige motregen",
    61: "lighte regen", 63: "regen", 65: "heftige regen",
    66: "bevroren regen", 67: "hevige bevroren regen",
    71: "lichte sneeuw", 73: "sneeuw", 75: "hevige sneeuw",
    77: "sneeuwbuien", 80: "buien", 81: "matige buien",
    82: "hevige buien", 85: "sneeuwbuien", 86: "hevige sneeuwbuien",
    95: "onweer", 96: "onweer met hagel", 99: "hevig onweer met hagel",
}


def get_weather(plaats="Nederland", taal="nl"):

    """Haal weer op via Open-Meteo (gratis, geen key)."""

    # Stap 1: geocodeer de plaats
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": plaats, "count": 1},
            timeout=10,
        )
        geo = r.json().get("results", [])
        if not geo:
            return {
                "ok": False,
                "error": f"Ik kon '{plaats}' niet vinden als locatie.",
                "plaats": plaats,
            }
    except requests.RequestException:
        return {
            "ok": False,
            "error": "Ik kon de locatie niet opzoeken.",
            "plaats": plaats,
        }

    loc = geo[0]
    name = loc.get("name", plaats)
    country = loc.get("country", "")

    # Stap 2: haal weer op
    try:
        r2 = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,"
                           "wind_speed_10m,relative_humidity_2m",
                "daily": "temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max",
                "timezone": "auto",
            },
            timeout=10,
        )
        data = r2.json()
        cur = data["current"]
        daily = data["daily"]
    except requests.RequestException:
        return {
            "ok": False,
            "error": "Ik kon het weer niet ophalen.",
            "plaats": name,
        }

    code = cur.get("weather_code", 0)
    beschrijving = WEATHER_CODES.get(code, f"weercode {code}")

    return {
        "ok": True,
        "plaats": f"{name}{', ' + country if country else ''}",
        "temperatuur": cur["temperature_2m"],
        "gevoelstemperatuur": cur["apparent_temperature"],
        "beschrijving": beschrijving,
        "wind": cur.get("wind_speed_10m"),
        "luchtvochtigheid": cur.get("relative_humidity_2m"),
        "vandaag_max": daily.get("temperature_2m_max", [None])[0],
        "vandaag_min": daily.get("temperature_2m_min", [None])[0],
        "neerslag_pct": daily.get("precipitation_probability_max", [None])[0],
    }


def format_weather(w):

    if not w.get("ok"):
        return w.get("error", "Ik kon het weer niet ophalen.")

    parts = [f"Weer in {w['plaats']}:"]
    parts.append(f"  {w['beschrijving'].capitalize()}, {w['temperatuur']}°C (voelt als {w['gevoelstemperatuur']}°C)")

    if w.get("vandaag_max") is not None and w.get("vandaag_min") is not None:
        parts.append(f"  Vandaag: {w['vandaag_min']}°C - {w['vandaag_max']}°C")

    extras = []
    if w.get("wind") is not None:
        extras.append(f"wind {w['wind']} km/h")
    if w.get("luchtvochtigheid") is not None:
        extras.append(f"luchtvochtigheid {w['luchtvochtigheid']}%")
    if w.get("neerslag_pct") is not None:
        extras.append(f"neerslag {w['neerslag_pct']}%")
    if extras:
        parts.append(f"  {', '.join(extras)}")

    return "\n".join(parts)


# =============================================================
# WIKIPEDIA LOOKUP — gratis, geen rate-limit, feiten + definities
# =============================================================

WIKI_BASE = "https://nl.wikipedia.org/w/api.php"
WIKI_HEADERS = {"User-Agent": "JARVIS/1.0 (persoonlijke assistent; github.com/jarvis)"}


def wikipedia_lookup(query, taal="nl"):

    """Zoek een artikel op Wikipedia en geef de introductie terug.

    Foutreturns bevatten `error_type`: no_results, network_error."""

    base = f"https://{taal}.wikipedia.org/w/api.php"

    try:
        r = requests.get(
            base,
            params={
                "action": "opensearch",
                "search": query,
                "format": "json",
                "limit": 1,
                "namespace": 0,
            },
            headers=WIKI_HEADERS,
            timeout=10,
        )
        d = r.json()
        titles = d[1] if len(d) > 1 else []
        urls = d[3] if len(d) > 3 else []

        if not titles:
            return {
                "ok": False,
                "error_type": "no_results",
                "error": f"Ik vond geen Wikipedia-artikel over '{query}'.",
                "query": query,
                "results": [],
            }

    except requests.RequestException:
        return {
            "ok": False,
            "error_type": "network_error",
            "error": "Ik kon Wikipedia niet bereiken.",
            "query": query,
            "results": [],
        }

    # Haal de introductie op
    title = titles[0]
    url = urls[0] if urls else ""

    try:
        r2 = requests.get(
            base,
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "format": "json",
                "titles": title,
                "redirects": 1,
            },
            headers=WIKI_HEADERS,
            timeout=10,
        )
        pages = r2.json().get("query", {}).get("pages", {})
        extract = ""
        for pid, page in pages.items():
            if pid != "-1":
                extract = page.get("extract", "")
                break
    except requests.RequestException:
        extract = ""

    return {
        "ok": True,
        "query": query,
        "title": title,
        "url": url,
        "extract": truncate_text(extract, 1200),
    }


def format_wikipedia(result):

    if not result.get("ok"):
        return result.get("error", "Ik kon niets vinden.")

    parts = [f"Wikipedia: {result['title']}"]
    if result.get("url"):
        parts.append(f"({result['url']})")
    if result.get("extract"):
        parts.append(result["extract"])
    return "\n".join(parts)