"""Nieuws ophalen via RSS/Atom (Fase 16C) — alleen op aanvraag.

JARVIS haalt de koppen van een paar vaste nieuwsbronnen op:

  * NOS      — https://feeds.nos.nl/nosnieuwsalgemeen
  * Tweakers — https://tweakers.net/feeds/nieuws.xml

Er is geen API-sleutel nodig en er wordt geen extra bibliotheek gebruikt:
de feeds worden met de standaardbibliotheek (``xml.etree``) geparseerd.

Er wordt NOOIT vanzelf gepusht: de gebruiker vraagt erom ("wat is het
nieuws", "nieuws van Tweakers"). Alle functies zijn fail-closed: bij een
netwerk- of parseerfout komt er een nette melding terug in plaats van een
crash.
"""
import re
import xml.etree.ElementTree as ET

import requests

import config

#: Vaste nieuwsbronnen: sleutel -> (weergavenaam, feed-URL).
FEEDS = {
    "nos": ("NOS", "https://feeds.nos.nl/nosnieuwsalgemeen"),
    "tweakers": ("Tweakers", "https://tweakers.net/feeds/nieuws.xml"),
}

USER_AGENT = "Mozilla/5.0 (compatible; JARVIS/1.0)"
TIMEOUT = (3, 10)
ATOM_NS = "{http://www.w3.org/2005/Atom}"

_TAG_PATROON = re.compile(r"<[^>]+>")


def beschikbare_bronnen():
    """Geeft de sleutels van de bekende nieuwsbronnen terug."""

    return list(FEEDS.keys())


def _schoon(tekst):
    """Verwijdert HTML-tags en overtollige witruimte."""

    tekst = _TAG_PATROON.sub("", tekst or "")
    return re.sub(r"\s+", " ", tekst).strip()


def _tekst(element, pad):
    """Leest de tekst van een sub-element (of een lege string)."""

    if element is None:
        return ""
    return _schoon(element.findtext(pad))


def _items_uit_feed(data, max_items):
    """Parseert RSS- of Atom-bytes naar een lijst items.

    Elk item is een dict met ``titel``, ``link`` en ``datum``. Gooit een
    fout als de feed niet te lezen is; de aanroeper vangt die af.
    """

    root = ET.fromstring(data)
    items = []

    if root.tag == "rss" or root.tag.endswith("}rss") or root.find("channel") is not None:
        for item in root.iter("item"):
            items.append({
                "titel": _tekst(item, "title"),
                "link": _tekst(item, "link"),
                "datum": _tekst(item, "pubDate"),
            })
    else:
        for entry in root.iter(f"{ATOM_NS}entry"):
            link_el = entry.find(f"{ATOM_NS}link")
            href = link_el.get("href", "") if link_el is not None else ""
            items.append({
                "titel": _tekst(entry, f"{ATOM_NS}title"),
                "link": href,
                "datum": (_tekst(entry, f"{ATOM_NS}updated")
                          or _tekst(entry, f"{ATOM_NS}published")),
            })

    return [item for item in items if item["titel"]][:max_items]


def haal_feed(bron, max_items=None, timeout=TIMEOUT, get_fn=None):
    """Haalt één nieuwsbron op.

    Geeft ``{"ok": True, "bron", "naam", "items"}`` terug, of
    ``{"ok": False, "error": ...}`` bij een onbekende bron of een fout.
    """

    sleutel = (bron or "").strip().lower()
    if sleutel not in FEEDS:
        return {
            "ok": False,
            "bron": sleutel,
            "error": f"Onbekende nieuwsbron: '{bron}'.",
        }

    naam, url = FEEDS[sleutel]
    if max_items is None:
        max_items = getattr(config, "NIEUWS_MAX_PER_BRON", 5)

    ophalen = get_fn or requests.get
    try:
        response = ophalen(
            url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        data = response.content
    except Exception as error:  # noqa: BLE001 - fail-closed, nooit crashen
        return {
            "ok": False,
            "bron": sleutel,
            "naam": naam,
            "error": f"Nieuws ophalen mislukte: {error}",
        }

    try:
        items = _items_uit_feed(data, max_items)
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "bron": sleutel,
            "naam": naam,
            "error": f"Nieuwsfeed onleesbaar: {error}",
        }

    return {"ok": True, "bron": sleutel, "naam": naam, "items": items}


def haal_nieuws(bronnen=None, max_per_bron=None, get_fn=None):
    """Haalt meerdere nieuwsbronnen op.

    Zonder ``bronnen`` wordt de configuratielijst gebruikt
    (``JARVIS_NIEUWS_BRONNEN``, standaard "nos,tweakers").
    """

    if not bronnen:
        ruw = str(getattr(config, "NIEUWS_BRONNEN", "nos,tweakers"))
        bronnen = [deel.strip().lower() for deel in ruw.split(",") if deel.strip()]

    resultaten = [
        haal_feed(bron, max_items=max_per_bron, get_fn=get_fn)
        for bron in bronnen
    ]
    return {
        "ok": any(r.get("ok") for r in resultaten),
        "resultaten": resultaten,
    }


def format_nieuws(resultaat):
    """Zet het resultaat van :func:`haal_nieuws` om in spreekbare tekst."""

    if not resultaat:
        return "Ik kon het nieuws niet ophalen."

    stukken = []
    for bron in resultaat.get("resultaten", []):
        if not bron.get("ok"):
            if bron.get("error"):
                stukken.append(bron["error"])
            continue
        items = bron.get("items", [])
        if not items:
            stukken.append(f"Geen nieuws gevonden bij {bron.get('naam', 'de bron')}.")
            continue
        koppen = "; ".join(item.get("titel", "") for item in items if item.get("titel"))
        stukken.append(f"{bron.get('naam', 'Nieuws')}: {koppen}.")

    if not stukken:
        return "Ik kon het nieuws niet ophalen."
    return " ".join(stukken)
