"""Tests voor Fase 16C — externe bronnen (nieuws, reistijden, prijzen).

Alles draait zonder netwerk: HTTP-aanroepen worden geïnjecteerd via
``get_fn``/``zoek_fn`` of gemonkeypatcht. Docstrings in het Nederlands,
zelfde stijl als de andere fase-16-tests.
"""
import pytest

import config
from actions import nieuws
from actions import prijzen
from actions import reistijden
from core import externe_bronnen


RSS_VOORBEELD = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>NOS</title>
<item><title>Eerste kop</title><link>https://voorbeeld.org/1</link><pubDate>Vandaag</pubDate></item>
<item><title>Tweede &amp; kop</title><link>https://voorbeeld.org/2</link><pubDate>Gisteren</pubDate></item>
</channel></rss>"""

ATOM_VOORBEELD = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom kop</title><link href="https://voorbeeld.org/a"/><updated>2026-01-01</updated></entry>
</feed>"""


class FakeResponse:
    """Minimale nep-respons voor requests."""

    def __init__(self, content=b"", json_data=None, status=200):
        self.content = content
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _rss_get(*args, **kwargs):
    """Nep-requests.get die de RSS-voorbeeldfeed teruggeeft."""

    return FakeResponse(content=RSS_VOORBEELD)


# --- Nieuws -------------------------------------------------------------


def test_items_uit_feed_parst_rss():
    items = nieuws._items_uit_feed(RSS_VOORBEELD, 5)
    assert len(items) == 2
    assert items[0]["titel"] == "Eerste kop"
    assert items[0]["link"] == "https://voorbeeld.org/1"
    assert items[1]["titel"] == "Tweede & kop"


def test_items_uit_feed_parst_atom():
    items = nieuws._items_uit_feed(ATOM_VOORBEELD, 5)
    assert len(items) == 1
    assert items[0]["titel"] == "Atom kop"
    assert items[0]["link"] == "https://voorbeeld.org/a"


def test_items_uit_feed_max_aantal():
    assert len(nieuws._items_uit_feed(RSS_VOORBEELD, 1)) == 1


def test_beschikbare_bronnen():
    assert set(nieuws.beschikbare_bronnen()) == {"nos", "tweakers"}


def test_haal_feed_onbekende_bron():
    resultaat = nieuws.haal_feed("telegraaf")
    assert resultaat["ok"] is False
    assert "Onbekende nieuwsbron" in resultaat["error"]


def test_haal_feed_ok():
    resultaat = nieuws.haal_feed("nos", get_fn=_rss_get)
    assert resultaat["ok"] is True
    assert resultaat["naam"] == "NOS"
    assert len(resultaat["items"]) == 2


def test_haal_feed_netwerkfout():
    def _get(*args, **kwargs):
        raise RuntimeError("geen verbinding")

    resultaat = nieuws.haal_feed("nos", get_fn=_get)
    assert resultaat["ok"] is False
    assert "mislukte" in resultaat["error"]


def test_haal_feed_onleesbare_feed():
    resultaat = nieuws.haal_feed(
        "nos", get_fn=lambda *a, **k: FakeResponse(content=b"geen xml")
    )
    assert resultaat["ok"] is False
    assert "onleesbaar" in resultaat["error"]


def test_haal_feed_max_per_bron_uit_config(monkeypatch):
    monkeypatch.setattr(config, "NIEUWS_MAX_PER_BRON", 1)
    assert len(nieuws.haal_feed("nos", get_fn=_rss_get)["items"]) == 1


def test_haal_nieuws_met_bronnen():
    resultaat = nieuws.haal_nieuws(bronnen=["nos", "tweakers"], get_fn=_rss_get)
    assert resultaat["ok"] is True
    assert len(resultaat["resultaten"]) == 2


def test_haal_nieuws_gebruikt_config_bronnen(monkeypatch):
    monkeypatch.setattr(config, "NIEUWS_BRONNEN", "nos")
    resultaat = nieuws.haal_nieuws(get_fn=_rss_get)
    assert len(resultaat["resultaten"]) == 1
    assert resultaat["resultaten"][0]["bron"] == "nos"


def test_format_nieuws_bevat_koppen():
    resultaat = nieuws.haal_nieuws(bronnen=["nos"], get_fn=_rss_get)
    tekst = nieuws.format_nieuws(resultaat)
    assert "NOS" in tekst
    assert "Eerste kop" in tekst


def test_format_nieuws_meldt_fout():
    tekst = nieuws.format_nieuws(
        {"ok": False, "resultaten": [{"ok": False, "error": "Nieuws ophalen mislukte."}]}
    )
    assert "mislukte" in tekst


def test_format_nieuws_geen_items():
    tekst = nieuws.format_nieuws(
        {"ok": True, "resultaten": [{"ok": True, "naam": "NOS", "items": []}]}
    )
    assert "Geen nieuws" in tekst


def test_format_nieuws_none():
    assert "niet ophalen" in nieuws.format_nieuws(None)


# --- Reistijden ---------------------------------------------------------


@pytest.fixture(autouse=True)
def schone_geocode_cache():
    """Zorgt dat de geocode-cache per test leeg is."""

    reistijden.reset_cache()
    yield
    reistijden.reset_cache()


def test_geocode_geeft_coordinaten():
    def _get(*args, **kwargs):
        return FakeResponse(json_data=[{"lat": "52.0", "lon": "4.3"}])

    assert reistijden.geocode("Amsterdam", get_fn=_get) == (52.0, 4.3)


def test_geocode_cache_voorkomt_tweede_aanroep():
    teller = {"aantal": 0}

    def _get(*args, **kwargs):
        teller["aantal"] += 1
        return FakeResponse(json_data=[{"lat": "52.0", "lon": "4.3"}])

    reistijden.geocode("Amsterdam", get_fn=_get)
    reistijden.geocode("amsterdam", get_fn=_get)
    assert teller["aantal"] == 1


def test_geocode_leeg():
    assert reistijden.geocode("") is None


def test_geocode_geen_resultaat():
    assert reistijden.geocode(
        "Nergens", get_fn=lambda *a, **k: FakeResponse(json_data=[])
    ) is None


def test_geocode_fout():
    def _get(*args, **kwargs):
        raise RuntimeError("kapot")

    assert reistijden.geocode("Amsterdam", get_fn=_get) is None


def test_bereken_reis_ok():
    def _get(*args, **kwargs):
        if "nominatim" in args[0]:
            return FakeResponse(json_data=[{"lat": "52.0", "lon": "4.3"}])
        return FakeResponse(
            json_data={"routes": [{"distance": 15000.0, "duration": 1800.0}]}
        )

    resultaat = reistijden.bereken_reis("Amsterdam", "Utrecht", get_fn=_get)
    assert resultaat["ok"] is True
    assert resultaat["afstand_km"] == 15.0
    assert resultaat["minuten"] == 30


def test_bereken_reis_zonder_plaatsen():
    resultaat = reistijden.bereken_reis("", "Utrecht")
    assert resultaat["ok"] is False
    assert "vertrekpunt" in resultaat["error"]


def test_bereken_reis_plaats_onbekend():
    resultaat = reistijden.bereken_reis(
        "Nergens", "Ook nergens", get_fn=lambda *a, **k: FakeResponse(json_data=[])
    )
    assert resultaat["ok"] is False
    assert "niet vinden" in resultaat["error"]


def test_bereken_reis_osrm_fout():
    def _get(*args, **kwargs):
        if "nominatim" in args[0]:
            return FakeResponse(json_data=[{"lat": "1", "lon": "2"}])
        raise RuntimeError("OSRM kapot")

    resultaat = reistijden.bereken_reis("A", "B", get_fn=_get)
    assert resultaat["ok"] is False
    assert "mislukte" in resultaat["error"]


def test_format_reis_kort():
    tekst = reistijden.format_reis(
        {"ok": True, "van": "A", "naar": "B", "afstand_km": 5.0, "minuten": 12}
    )
    assert "12 minuten" in tekst
    assert "5.0 kilometer" in tekst


def test_format_reis_lang():
    tekst = reistijden.format_reis(
        {"ok": True, "van": "A", "naar": "B", "afstand_km": 120.0, "minuten": 90}
    )
    assert "1 uur en 30 minuten" in tekst


def test_format_reis_fout():
    assert "niet berekenen" in reistijden.format_reis(None)


# --- Prijzen ------------------------------------------------------------


def test_beschikbare_winkels():
    assert set(prijzen.beschikbare_winkels()) == {"bol", "coolblue", "amazon"}


def test_winkels_uit_tekst():
    assert prijzen._winkels_uit_tekst("wat kost een ipad bij bol.com") == ["bol"]
    assert len(prijzen._winkels_uit_tekst("wat kost een ipad")) == 3


def test_zoek_prijs_zonder_product():
    assert prijzen.zoek_prijs("")["ok"] is False


def test_zoek_prijs_ok():
    def zoek_fn(query):
        return {
            "ok": True,
            "pages": [{"snippet": "499 euro", "url": "https://x", "title": "IPad"}],
        }
    resultaat = prijzen.zoek_prijs("ipad", zoek_fn=zoek_fn)
    assert resultaat["ok"] is True
    assert len(resultaat["resultaten"]) == 3
    assert resultaat["resultaten"][0]["winkel"] == "Bol.com"
    assert resultaat["resultaten"][0]["snippet"] == "499 euro"


def test_zoek_prijs_beperkt_tot_een_winkel():
    def zoek_fn(query):
        return {
            "ok": True,
            "pages": [{"snippet": "199 euro", "url": "https://x", "title": "Y"}],
        }
    resultaat = prijzen.zoek_prijs("ipad", winkels=["bol"], zoek_fn=zoek_fn)
    assert len(resultaat["resultaten"]) == 1


def test_zoek_prijs_fout():
    def zoek_fn(query):
        raise RuntimeError("kapot")

    resultaat = prijzen.zoek_prijs("ipad", winkels=["bol"], zoek_fn=zoek_fn)
    assert resultaat["ok"] is False
    assert resultaat["fouten"][0]["winkel"] == "Bol.com"


def test_zoek_prijs_geen_resultaat():
    resultaat = prijzen.zoek_prijs(
        "ipad", winkels=["bol"], zoek_fn=lambda q: {"ok": False, "error": "niets"}
    )
    assert resultaat["ok"] is False
    assert "niets" in resultaat["fouten"][0]["error"]


def test_format_prijs_ok():
    tekst = prijzen.format_prijs({
        "ok": True,
        "product": "ipad",
        "resultaten": [{"winkel": "Bol.com", "snippet": "499 euro"}],
    })
    assert "Bol.com" in tekst
    assert "kan afwijken" in tekst


def test_format_prijs_leeg():
    leeg = prijzen.format_prijs({"ok": False, "product": "ipad", "resultaten": []})
    assert "geen prijsindicatie" in leeg


def test_format_prijs_none():
    assert "geen prijzen" in prijzen.format_prijs(None)


# --- Router (core.externe_bronnen) --------------------------------------


def test_router_reistijd(monkeypatch):
    """'hoe lang duurt het van A naar B' wordt doorgestuurd met de juiste plaatsen."""

    gezien = {}

    def _fake_reis(van, naar):
        gezien["van"] = van
        gezien["naar"] = naar
        return {"ok": True, "van": van, "naar": naar, "afstand_km": 15.0, "minuten": 20}

    monkeypatch.setattr(externe_bronnen.reistijden, "bereken_reis", _fake_reis)
    tekst = externe_bronnen.try_externe_bron_command(
        "hoe lang duurt het van Amsterdam naar Utrecht met de auto"
    )
    assert gezien == {"van": "amsterdam", "naar": "utrecht"}
    assert isinstance(tekst, str) and tekst


def test_router_route_zonder_reiswoord_is_geen_reistijd():
    assert externe_bronnen.try_externe_bron_command("wat is de route van het leven") is None


def test_router_nieuws(monkeypatch):
    """'wat is het nieuws' vraagt alle bronnen op."""

    gezien = {}

    def _fake_haal(bronnen=None, **kwargs):
        gezien["bronnen"] = bronnen
        return {"ok": True, "resultaten": [{"ok": True, "naam": "NOS", "items": []}]}

    monkeypatch.setattr(externe_bronnen.nieuws, "haal_nieuws", _fake_haal)
    tekst = externe_bronnen.try_externe_bron_command("wat is het nieuws")
    assert gezien["bronnen"] is None
    assert "NOS" in tekst


def test_router_nieuws_met_bron(monkeypatch):
    """'nieuws van tweakers' beperkt zich tot die bron."""

    gezien = {}

    def _fake_haal(bronnen=None, **kwargs):
        gezien["bronnen"] = bronnen
        return {"ok": True, "resultaten": [{"ok": True, "naam": "Tweakers", "items": []}]}

    monkeypatch.setattr(externe_bronnen.nieuws, "haal_nieuws", _fake_haal)
    externe_bronnen.try_externe_bron_command("wat is het nieuws van tweakers")
    assert gezien["bronnen"] == ["tweakers"]


def test_router_prijs(monkeypatch):
    """'wat kost een ipad bij bol.com' bepaalt product en winkel."""

    gezien = {}

    def _fake_zoek(product, winkels=None, **kwargs):
        gezien["product"] = product
        gezien["winkels"] = winkels
        return {"ok": True, "product": product, "resultaten": [
            {"winkel": "Bol.com", "snippet": "499 euro"}
        ]}

    monkeypatch.setattr(externe_bronnen.prijzen, "zoek_prijs", _fake_zoek)
    tekst = externe_bronnen.try_externe_bron_command("wat kost een ipad bij bol.com")
    assert gezien["product"] == "ipad"
    assert gezien["winkels"] == ["bol"]
    assert "499 euro" in tekst


def test_router_ongerelateerd():
    assert externe_bronnen.try_externe_bron_command("speel muziek") is None
    assert externe_bronnen.try_externe_bron_command("wat is het weer") is None
    assert externe_bronnen.try_externe_bron_command("") is None
    assert externe_bronnen.try_externe_bron_command(None) is None


def test_brain_importeert_de_router():
    """brain.py koppelt de router (zodat het pad echt actief is)."""

    from core import brain

    assert hasattr(brain, "try_externe_bron_command")
