"""Tests voor Fase 16C — negatieve zinnen en twijfelgevallen.

Gewone gesprekszinnen mogen géén timer, nieuws, reistijd of
prijsopzoeking starten. De zinnen staan in
``tests/data/negatieve_zinnen.txt``; hier controleren we dat geen enkele
zin een actie start, en dat een echt twijfelgeval netjes een ja/nee-vraag
stelt met een korte TTL.

Er gaat geen netwerkverkeer overheen: ``prijzen.zoek_prijs``,
``nieuws.haal_nieuws`` en ``reistijden.bereken_reis`` worden vervangen.
"""
from pathlib import Path

import pytest

from actions import nieuws
from actions import prijzen
from actions import reistijden
from core import confirmation
from core import externe_bronnen
from core import proactive_commands

DATA = Path(__file__).parent / "data" / "negatieve_zinnen.txt"

# Zinnen die de opdracht expliciet noemde: deze moeten er zeker in staan.
VERPLICHTE_ZINNEN = [
    "ik ben over 10 minuten thuis",
    "in 5 minuten is het eten klaar",
    "de wasmachine is over 20 minuten klaar",
    "na 2 uur gamen ben ik moe",
    "over een uur begint de film",
    "over 5 minuten moet ik weg",
    "hoe lang duurt een timer van 5 minuten op de oven",
    "ik heb het nieuws gezien",
    "het nieuws was slecht vandaag",
    "nieuws is saai",
    "wat kost een brood",
    "wat is de prijs van die jas",
    "wat kost het om te parkeren",
    "de prijs is hoog",
    "wat kost een nieuwe fiets",
    "hoe lang duurt het van mijn huis naar de winkel",
]


def _zinnen():
    """Leest de negatieve zinnen (zonder opmerkingen en lege regels)."""

    regels = DATA.read_text(encoding="utf-8").splitlines()
    return [
        r.strip()
        for r in regels
        if r.strip() and not r.lstrip().startswith("#")
    ]


@pytest.fixture(autouse=True)
def geen_netwerk(monkeypatch):
    """Laat elke externe aanroep falen: zo zien we meteen wie er start."""

    gestart = []

    def _fake_zoek_prijs(product, winkels=None, **kwargs):
        gestart.append(product)
        return {"ok": False, "error": "geen netwerk"}

    def _fake_haal_nieuws(bronnen=None, **kwargs):
        gestart.append(bronnen)
        return {"ok": False, "error": "geen netwerk"}

    def _fake_bereken_reis(van, naar, **kwargs):
        gestart.append((van, naar))
        return {"ok": False, "error": "geen netwerk"}

    monkeypatch.setattr(prijzen, "zoek_prijs", _fake_zoek_prijs)
    monkeypatch.setattr(nieuws, "haal_nieuws", _fake_haal_nieuws)
    monkeypatch.setattr(reistijden, "bereken_reis", _fake_bereken_reis)
    confirmation.clear_pending()
    yield gestart
    confirmation.clear_pending()


# Zinnen die wél een echte opdracht zijn (de winkel maakt de vraag
# concreet); die komen niet in de negatieve lijst terecht.
WINKEL_VRAAG = "wat kost een stoel bij de kringloop"


def _negatieve_zinnen():
    """De negatieve zinnen, zonder de bewust concrete winkelvraag."""

    return [z for z in _zinnen() if z != WINKEL_VRAAG]


def test_bestand_heeft_minimaal_veertig_zinnen():
    zinnen = _negatieve_zinnen()
    assert len(zinnen) >= 40, f"Te weinig negatieve zinnen: {len(zinnen)}"


def test_verplichte_zinnen_staan_erin():
    zinnen = set(_negatieve_zinnen())
    ontbreekt = [z for z in VERPLICHTE_ZINNEN if z not in zinnen]
    assert ontbreekt == [], f"Ontbrekende verplichte zinnen: {ontbreekt}"


def test_negatieve_zinnen_starten_geen_timer():
    for zin in _negatieve_zinnen():
        assert proactive_commands._extraheer_timer(zin) is None, zin


def test_negatieve_zinnen_starten_geen_externe_bron(geen_netwerk):
    for zin in _negatieve_zinnen():
        externe_bronnen.try_externe_bron_command(zin)
    # Niets mag de externe diensten hebben aangeraakt.
    assert geen_netwerk == []
    assert confirmation.get_pending() is None


def test_winkelvraag_is_wel_concreet(monkeypatch):
    """Noemt de zin een winkel, dan is het een echte productvraag."""

    gestart = []

    def _fake_zoek_prijs(product, winkels=None, **kwargs):
        gestart.append((product, winkels))
        return {"ok": True, "product": product, "resultaten": []}

    monkeypatch.setattr(prijzen, "zoek_prijs", _fake_zoek_prijs)

    externe_bronnen.try_externe_bron_command(WINKEL_VRAAG)
    assert gestart and gestart[0][0] == "stoel"


# --- twijfelgevallen ----------------------------------------------------


def test_twijfelgeval_stelt_ja_nee_vraag(monkeypatch):
    """Een onbekend product zonder merk/cijfer vraagt eerst om bevestiging."""

    gestart = []

    def _fake_zoek_prijs(product, winkels=None, **kwargs):
        gestart.append(product)
        return {"ok": False, "error": "geen netwerk"}

    monkeypatch.setattr(prijzen, "zoek_prijs", _fake_zoek_prijs)

    tekst = externe_bronnen.try_externe_bron_command("wat kost een espressomachine")
    assert tekst is not None
    assert "espressomachine" in tekst
    assert "ja" in tekst.lower() and "nee" in tekst.lower()
    # Nog geen zoekopdracht vertrokken.
    assert gestart == []


def test_twijfelgeval_zet_pending_met_korte_ttl():
    externe_bronnen.try_externe_bron_command("wat kost een espressomachine")
    pending = confirmation.get_pending()
    assert pending is not None
    assert pending["kind"] == "prijs_confirm"
    assert pending["product"] == "espressomachine"
    # Korte TTL: binnen enkele tientallen seconden vergeten.
    assert externe_bronnen.PRIJS_CONFIRM_TTL_SECONDS <= 30


def test_merk_product_zoekt_direct(monkeypatch):
    """Een merknaam is concreet genoeg: geen ja/nee-vraag."""

    gestart = []

    def _fake_zoek_prijs(product, winkels=None, **kwargs):
        gestart.append(product)
        return {"ok": True, "product": product, "resultaten": []}

    monkeypatch.setattr(prijzen, "zoek_prijs", _fake_zoek_prijs)

    tekst = externe_bronnen.try_externe_bron_command("wat kost een ipad")
    assert gestart == ["ipad"]
    assert tekst is not None
    assert confirmation.get_pending() is None


def test_alledaags_product_start_niets():
    for zin in ("wat kost een brood", "wat kost een nieuwe fiets", "wat kost het om te parkeren"):
        assert externe_bronnen.try_externe_bron_command(zin) is None
        assert confirmation.get_pending() is None


def test_mededeling_over_prijs_start_niets():
    for zin in (
        "de prijs is hoog",
        "een auto kost veel geld",
        "dat kost me te veel",
        "de prijs van boter is gestegen",
    ):
        assert externe_bronnen.try_externe_bron_command(zin) is None


def test_nieuws_mededeling_start_niets():
    for zin in ("ik heb het nieuws gezien", "nieuws is saai", "het nieuws was slecht vandaag"):
        assert externe_bronnen.try_externe_bron_command(zin) is None


def test_nieuws_opdracht_start_wel(monkeypatch):
    """De echte opdrachtvorm blijft werken."""

    gestart = []

    def _fake_haal_nieuws(bronnen=None, **kwargs):
        gestart.append(bronnen)
        return {"ok": True, "resultaten": [{"ok": True, "naam": "NOS", "items": []}]}

    monkeypatch.setattr(nieuws, "haal_nieuws", _fake_haal_nieuws)

    tekst = externe_bronnen.try_externe_bron_command("wat is het nieuws")
    assert gestart == [None]
    assert tekst is not None

    gestart.clear()
    externe_bronnen.try_externe_bron_command("nieuws van tweakers")
    assert gestart == [["tweakers"]]


def test_algemene_plaats_start_geen_reistijd():
    for zin in (
        "hoe lang duurt het van mijn huis naar de winkel",
        "hoe lang duurt het van werk naar school",
    ):
        assert externe_bronnen.try_externe_bron_command(zin) is None


def test_echte_reisvraag_start_wel(monkeypatch):
    gestart = []

    def _fake_bereken_reis(van, naar, **kwargs):
        gestart.append((van, naar))
        return {"ok": True, "van": van, "naar": naar, "minuten": 30, "km": 25}

    monkeypatch.setattr(reistijden, "bereken_reis", _fake_bereken_reis)

    externe_bronnen.try_externe_bron_command(
        "hoe lang duurt het van Amsterdam naar Utrecht"
    )
    assert gestart == [("amsterdam", "utrecht")]


def test_timer_vraag_start_geen_timer():
    assert proactive_commands._extraheer_timer(
        "hoe lang duurt een timer van 5 minuten op de oven"
    ) is None
    assert proactive_commands._extraheer_timer(
        "wat is een timer van 10 minuten"
    ) is None


def test_echte_timer_opdracht_start_wel():
    assert proactive_commands._extraheer_timer("zet een timer van 10 minuten") == (
        600,
        "timer",
    )
    assert proactive_commands._extraheer_timer("herinner me over een half uur") is not None
