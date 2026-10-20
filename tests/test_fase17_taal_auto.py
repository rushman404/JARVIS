"""Tests voor Fase 17 — taal volgt uw vraag (automatische taaldetectie).

JARVIS antwoordt in de taal van uw vraag, maar alleen als die vraag
overduidelijk in één taal is. Losse Engelse woorden in een Nederlandse zin
veranderen niets. Een expliciete keuze ("switch to English") wordt vastgezet
en wint altijd; met "taal mag automatisch" geeft u die weer vrij.
"""

import json

import pytest

import taal


@pytest.fixture(autouse=True)
def schone_taalstaat(monkeypatch, tmp_path):
    """Zet de taal en het taalbestand per test terug."""

    bestand = tmp_path / "taal.json"
    monkeypatch.setattr(taal, "TAAL_BESTAND", str(bestand))
    taal.reset()
    yield
    taal.reset()


# =============================================================
# detecteer_vraagtaal: alleen overduidelijk Engels
# =============================================================

@pytest.mark.parametrize(
    "vraag",
    [
        "what is the capital of France?",
        "can you please open Spotify for me",
        "could you tell me what the weather is like",
        "i would like you to play some music",
        "where is my file and how do i open it",
    ],
)
def test_duidelijke_engelse_vraag_geeft_engels(vraag):
    assert taal.detecteer_vraagtaal(vraag) == taal.ENGELS


@pytest.mark.parametrize(
    "vraag",
    [
        "zet even Spotify op, dan kijken we de film",
        "speel mijn favorite playlist af",
        "open de game Steam en zet Discord klaar",
        "wat is de release date van die film?",
        "start een youtube video over python",
    ],
)
def test_engelse_woorden_in_nederlandse_zin_geven_niets(vraag):
    assert taal.detecteer_vraagtaal(vraag) is None


@pytest.mark.parametrize(
    "vraag",
    [
        "oké",
        "spotify",
        "",
        None,
        42,
        "???",
    ],
)
def test_te_kort_of_geen_letters_geeft_niets(vraag):
    assert taal.detecteer_vraagtaal(vraag) is None


def test_gemengde_zin_geeft_niets():
    # Duidelijke Nederlandse woorden → geen automatische wissel.
    assert taal.detecteer_vraagtaal("kan je the volume op 50 zetten?") is None


# =============================================================
# volgt_vraag: past de taal aan, tenzij vastgezet/uit
# =============================================================

def test_volgt_vraag_wisselt_naar_engels():
    assert taal.volgt_vraag("can you please open Spotify for me") == taal.ENGELS
    assert taal.is_engels()
    assert not taal.is_vastgezet()


def test_volgt_vraag_wisselt_terug_naar_nederlands():
    taal.zet(taal.ENGELS, vastgezet=False)

    assert taal.volgt_vraag("wat is de hoofdstad van frankrijk?") is None
    # Een Nederlandse vraag met Engelse woorden geeft geen oordeel...
    assert taal.is_engels()

    # ...maar een expliciet Nederlandse zin zonder Engelse signalen zou ook
    # geen wissel geven (detectie is streng). Reset daarom via het commando.
    taal.reset()


def test_vaste_keuze_wint_altijd():
    taal.wissel("switch to English")
    assert taal.is_vastgezet()

    # Een Nederlandse vraag mag de vaste keuze niet overrulen.
    assert taal.volgt_vraag("wat is de hoofdstad van frankrijk?") is None
    assert taal.is_engels()


def test_volgt_vraag_niets_als_automaat_uit_staat(monkeypatch):
    import config

    monkeypatch.setattr(config, "TAAL_AUTOMATISCH", False)

    assert taal.volgt_vraag("can you please open Spotify for me") is None
    assert taal.taal() == taal.NEDERLANDS


# =============================================================
# Vrijgave met "taal mag automatisch"
# =============================================================

@pytest.mark.parametrize(
    "commando",
    [
        "taal mag automatisch",
        "mag automatisch wisselen",
        "schakel automatisch wisselen in",
        "volg mijn taal",
    ],
)
def test_vrijgave_commando_geeft_vastgezette_taal_vrij(commando):
    taal.wissel("switch to English")
    assert taal.is_vastgezet()

    antwoord = taal.wissel(commando)

    assert antwoord is not None
    assert not taal.is_vastgezet()
    # Daarna mag de automaat weer volgen.
    taal.reset()
    assert taal.volgt_vraag("can you please open Spotify for me") == taal.ENGELS


def test_vrijgave_doet_niets_als_niets_vaststaat():
    assert taal.vrijgeven() is False
    assert not taal.is_vastgezet()


# =============================================================
# Opslag: vastgezet in taal.json
# =============================================================

def test_expliciete_keuze_bewaart_vastgezet(tmp_path):
    bestand = tmp_path / "taal.json"
    taal.wissel("switch to English")

    data = json.loads(bestand.read_text(encoding="utf-8"))
    assert data == {"taal": "en", "vastgezet": True}


def test_automatische_wissel_bewaart_niet_vastgezet(tmp_path):
    bestand = tmp_path / "taal.json"
    taal.volgt_vraag("can you please open Spotify for me")

    data = json.loads(bestand.read_text(encoding="utf-8"))
    assert data == {"taal": "en", "vastgezet": False}


def test_laad_leest_vastgezet(tmp_path):
    bestand = tmp_path / "taal.json"
    bestand.write_text('{"taal": "en", "vastgezet": true}', encoding="utf-8")

    taal.reset()
    taal.laad()

    assert taal.is_engels()
    assert taal.is_vastgezet()


def test_laad_oude_bestand_zonder_vlag_is_vastgezet(tmp_path):
    """Een oud taal.json (zonder 'vastgezet') telt als een vaste keuze."""
    bestand = tmp_path / "taal.json"
    bestand.write_text('{"taal": "en"}', encoding="utf-8")

    taal.reset()
    taal.laad()

    assert taal.is_engels()
    assert taal.is_vastgezet()


# =============================================================
# Per beurt opnieuw
# =============================================================

def test_per_beurt_opnieuw_engels_dan_weer_vrij():
    assert taal.volgt_vraag("can you please open Spotify for me") == taal.ENGELS
    assert taal.is_engels()

    # Vrijgeven (vage/geen wissel) en dan een expliciete NL-keuze.
    taal.wissel("praat nederlands")
    assert not taal.is_engels()
