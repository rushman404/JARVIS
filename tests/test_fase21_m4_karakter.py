"""Fase 21, M4 — statusbegroeting op vraag en easter eggs."""

import time

import pytest

from core import karakter
from core.karakter import dagdeel, easter_egg, problemen, statusrapport


def ok():
    return True


def weg():
    return False


def nvt():
    return None


def boem():
    raise RuntimeError("stuk")


@pytest.fixture(autouse=True)
def geen_film(monkeypatch):
    from core import filmmodus

    monkeypatch.setattr(filmmodus, "lees_toestand", lambda pad=None: None)
    karakter._teller.clear()


@pytest.mark.parametrize("uur,groet", [(7, "Goedemorgen"), (13, "Goedemiddag"),
                                       (20, "Goedenavond"), (2, "Goedenacht")])
def test_dagdeel(uur, groet):
    assert dagdeel(uur) == groet


def test_alles_in_orde():
    checks = [("Home Assistant", ok, "x"), ("de game-pc", nvt, "y")]
    assert statusrapport(checks, uur=20) == "Goedenavond, sir. Alle systemen zijn operationeel."


def test_een_probleem():
    checks = [("Home Assistant", ok, "Home Assistant reageert niet"),
              ("de game-pc", weg, "de game-pc is offline")]
    assert statusrapport(checks, uur=9) == (
        "Goedemorgen, sir. Alles draait, op één ding na: de game-pc is offline.")


def test_meer_problemen_en_fouten():
    checks = [("Home Assistant", boem, "Home Assistant reageert niet"),
              ("de game-pc", weg, "de game-pc is offline"),
              ("internet", weg, "er is geen internet")]
    assert statusrapport(checks, uur=14) == (
        "Goedemiddag, sir. Er zijn 3 problemen: Home Assistant reageert niet, "
        "de game-pc is offline en er is geen internet.")


def test_trage_check_telt_als_probleem():
    def traag():
        time.sleep(1)
        return True

    begin = time.monotonic()
    assert problemen([("de game-pc", traag, "x")], timeout=0.1) == ["de game-pc reageert niet"]
    assert time.monotonic() - begin < 0.9


def test_film_modus_wordt_genoemd(monkeypatch):
    from core import filmmodus

    monkeypatch.setattr(filmmodus, "lees_toestand", lambda pad=None: {"tv": "x"})
    assert statusrapport([("x", ok, "")], uur=21).endswith("De film-modus staat aan.")


def test_standaard_checks_namen():
    namen = [c[0] for c in karakter.standaard_checks()]
    assert namen == ["Home Assistant", "de game-pc", "het AI-model", "internet", "de backup"]


@pytest.mark.parametrize("zin", ["status", "JARVIS, status", "systeemcheck", "doe een systeemcheck",
                                 "geef me een statusrapport", "hoe staan de systemen ervoor"])
def test_status_via_het_brein(zin, monkeypatch):
    from core import brain

    monkeypatch.setattr(karakter, "statusrapport", lambda checks=None, uur=None: "rapport")
    assert brain.process_command(zin) == "rapport"


@pytest.mark.parametrize("zin", ["wat is de status van spotify", "status van de game-pc",
                                 "mijn favoriete film is iron man", "ik ben moe"])
def test_geen_karakter(zin):
    assert karakter.voer_uit(zin) is None


@pytest.mark.parametrize("zin,antwoord", [
    ("Ik ben Iron Man.", "Daar twijfelde ik geen moment aan, sir."),
    ("dank je, JARVIS", "Graag gedaan, sir."),
    ("ben je daar?", "Altijd, sir."),
    ("wie ben jij", "Just A Rather Very Intelligent System, sir. Tot uw dienst."),
    ("start protocol huisfeest", "Het huisfeest-protocol vraagt om veertig harnassen, sir. Ik tel er nul."),
])
def test_easter_eggs(zin, antwoord):
    assert easter_egg(zin) == antwoord


def test_bedankt_wisselt_af():
    antwoorden = [easter_egg("bedankt") for _ in range(4)]
    assert antwoorden[:3] == ["Graag gedaan, sir.", "Altijd tot uw dienst, sir.", "Met genoegen, sir."]
    assert antwoorden[3] == antwoorden[0]


def test_easter_egg_via_het_brein():
    from core import brain

    assert brain.process_command("ik ben iron man") == "Daar twijfelde ik geen moment aan, sir."
