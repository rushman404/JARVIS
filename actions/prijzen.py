"""Prijzen opzoeken (Fase 16C) — alleen op aanvraag, best-effort.

Er is geen prijs-API met sleutel beschikbaar, dus JARVIS gebruikt de
bestaande webzoekfunctie (DuckDuckGo + pagina lezen) om per winkel een
prijsindicatie te vinden. Dat is een schatting: het kan voorkomen dat de
prijs ontbreekt of verouderd is. Alle functies zijn fail-closed.
"""
import re

from actions import web

#: Bekende winkels: sleutel -> (weergavenaam, site-filter voor de zoekterm).
WINKELS = {
    "bol": ("Bol.com", "site:bol.com"),
    "coolblue": ("Coolblue", "site:coolblue.nl"),
    "amazon": ("Amazon.nl", "site:amazon.nl"),
}

#: Koppeling van trefwoorden in een commando aan een winkelsleutel.
_WINKEL_WOORDEN = {
    "bol": "bol",
    "bol.com": "bol",
    "coolblue": "coolblue",
    "amazon": "amazon",
    "amazon.nl": "amazon",
}

MAX_SNIPPET_LENGTE = 300


def beschikbare_winkels():
    """Geeft de sleutels van de bekende winkels terug."""

    return list(WINKELS.keys())


def _winkels_uit_tekst(tekst):
    """Welke winkels worden in de tekst genoemd? (anders: alle winkels)."""

    gevonden = []
    for woord, sleutel in _WINKEL_WOORDEN.items():
        if re.search(rf"\b{re.escape(woord)}\b", tekst, re.IGNORECASE):
            if sleutel not in gevonden:
                gevonden.append(sleutel)
    return gevonden or list(WINKELS.keys())


def _kort(tekst, lengte=MAX_SNIPPET_LENGTE):
    tekst = re.sub(r"\s+", " ", tekst or "").strip()
    if len(tekst) <= lengte:
        return tekst
    return tekst[:lengte].rstrip() + "..."


def zoek_prijs(product, winkels=None, zoek_fn=None):
    """Zoekt per winkel een prijsindicatie voor ``product``.

    ``zoek_fn`` is injecteerbaar voor tests; standaard wordt
    :func:`actions.web.search_and_fetch` gebruikt.
    """

    product = (product or "").strip()
    if not product:
        return {"ok": False, "error": "Ik weet niet welk product u bedoelt."}

    if winkels is None:
        winkels = list(WINKELS.keys())
    elif isinstance(winkels, str):
        winkels = [winkels]

    zoeken = zoek_fn or (lambda query: web.search_and_fetch(query, max_pages=1))

    resultaten = []
    fouten = []
    for sleutel in winkels:
        if sleutel not in WINKELS:
            continue
        naam, site_filter = WINKELS[sleutel]
        query = f"{product} prijs {site_filter}"
        try:
            uitkomst = zoeken(query)
        except Exception as error:  # noqa: BLE001 - fail-closed
            fouten.append({"winkel": naam, "error": str(error)})
            continue

        if not uitkomst or not uitkomst.get("ok"):
            fouten.append({
                "winkel": naam,
                "error": (uitkomst or {}).get("error", "geen resultaat"),
            })
            continue

        pagina = (uitkomst.get("pages") or [{}])[0]
        snippet = _kort(pagina.get("snippet") or pagina.get("text") or "")
        resultaten.append({
            "winkel": naam,
            "snippet": snippet,
            "url": pagina.get("url", ""),
            "titel": pagina.get("title", ""),
        })

    return {
        "ok": bool(resultaten),
        "product": product,
        "resultaten": resultaten,
        "fouten": fouten,
    }


def format_prijs(resultaat):
    """Zet het resultaat van :func:`zoek_prijs` om in spreekbare tekst."""

    if not resultaat:
        return "Ik kon geen prijzen vinden."

    product = resultaat.get("product", "het product")
    if not resultaat.get("ok"):
        return (
            f"Ik kon geen prijsindicatie vinden voor {product}. "
            f"Probeer het eventueel opnieuw."
        )

    stukken = []
    for rij in resultaat.get("resultaten", []):
        tekst = rij.get("snippet")
        if tekst:
            stukken.append(f"{rij.get('winkel')}: {tekst}")
        else:
            stukken.append(f"{rij.get('winkel')}: geen prijs gevonden in het resultaat")

    begin = (
        f"Dit zijn gevonden prijsindicaties voor {product} "
        f"(via webzoek, kan afwijken):"
    )
    return begin + " " + " | ".join(stukken) + "."
