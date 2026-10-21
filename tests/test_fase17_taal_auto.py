"""Tests voor Fase 17 — taal volgt uw vraag (automatische taaldetectie).

JARVIS antwoordt in de taal van uw vraag, maar alleen als die vraag
overduidelijk Engels is. Die automatische wissel geldt alleen voor dat
antwoord (taal en stem): de spraakherkenning blijft op de vaste taal en er
wordt niets bewaard. Losse Engelse woorden in een Nederlandse zin
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

    # Een vraag die niet overduidelijk Engels is, zet de antwoordtaal terug
    # op de vaste taal (Nederlands).
    assert taal.volgt_vraag("wat is de hoofdstad van frankrijk?") == taal.NEDERLANDS
    assert not taal.is_engels()


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


def test_automatische_wissel_bewaart_niets(tmp_path):
    """Een automatische wissel geldt alleen voor dat antwoord: niets op schijf."""
    bestand = tmp_path / "taal.json"
    taal.volgt_vraag("can you please open Spotify for me")

    assert taal.is_engels()
    assert not bestand.exists()


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
    # De spraakherkenning volgt de expliciete keuze.
    assert taal.spraak_code() == "nl-NL"


# =============================================================
# De automatische wissel: alleen het antwoord, nooit de herkenning
# =============================================================

def test_engels_dan_nederlands_geeft_weer_nederlands():
    assert taal.volgt_vraag("can you please open Spotify for me") == taal.ENGELS
    assert taal.is_engels()

    # De volgende vraag is niet overduidelijk Engels: terug naar Nederlands.
    assert taal.volgt_vraag("wat is de hoofdstad van frankrijk?") == taal.NEDERLANDS
    assert not taal.is_engels()


def test_automatische_wissel_verandert_spraakherkenning_niet():
    assert taal.spraak_code() == "nl-NL"

    taal.volgt_vraag("can you please open Spotify for me")

    assert taal.is_engels()
    # Alleen het antwoord is Engels; het luisteren blijft Nederlands.
    assert taal.spraak_code() == "nl-NL"
    assert taal.vaste_taal() == taal.NEDERLANDS


def test_automatische_wissel_kiest_de_engelse_stem(monkeypatch, tmp_path):
    """De TTS-stem volgt het antwoord, ook bij een automatische wissel."""
    from voice import piper_tts

    import config

    (tmp_path / "nl.onnx").write_bytes(b"x")
    (tmp_path / "en.onnx").write_bytes(b"x")

    monkeypatch.setattr(config, "PIPER_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PIPER_VOICE", "nl.onnx")
    monkeypatch.setattr(config, "PIPER_VOICE_EN", "en.onnx")

    taal.volgt_vraag("can you please open Spotify for me")

    assert piper_tts._resolve_model_path().name == "en.onnx"
    # De spraakherkenning blijft op de vaste taal.
    assert taal.spraak_code() == "nl-NL"


def test_na_herstart_is_de_taal_de_vaste_taal(tmp_path):
    """Na een herstart staat JARVIS weer in de vaste taal."""
    taal.volgt_vraag("can you please open Spotify for me")
    assert taal.is_engels()

    # Herstart: de bewaarde keuze wordt opnieuw gelezen.
    taal.reset()
    taal.laad()

    assert taal.taal() == taal.NEDERLANDS
    assert taal.spraak_code() == "nl-NL"
    assert not taal.is_vastgezet()


def test_oud_bestand_met_automatische_wissel_wordt_gegenegeerd(tmp_path):
    """Een oud taal.json van een automatische wissel mag niets bewaren."""
    bestand = tmp_path / "taal.json"
    bestand.write_text('{"taal": "en", "vastgezet": false}', encoding="utf-8")

    taal.reset()
    taal.laad()

    assert taal.taal() == taal.NEDERLANDS
    assert taal.spraak_code() == "nl-NL"
    assert not taal.is_vastgezet()


def test_einde_sessie_zet_taal_terug_op_de_vaste_taal(monkeypatch):
    """Aan het einde van de sessie is de vaste taal weer actief."""
    import main

    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 3.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    monkeypatch.setattr(main, "process_command", lambda cmd, on_tekst=None: "ok")

    reeks = iter(["can you please open Spotify for me", ""])
    monkeypatch.setattr(main, "listen", lambda start_ts=None, **kw: next(reeks))

    assert taal.volgt_vraag("can you please open Spotify for me") == taal.ENGELS
    assert taal.is_engels()

    assert main.run_wake_cycle() == "ok"

    assert not taal.is_engels()
    assert taal.spraak_code() == "nl-NL"


# =============================================================
# Herhalingen en stopwoorden wisselen nooit
# =============================================================

@pytest.mark.parametrize(
    "vraag",
    [
        "stop stop stop",
        "nee nee nee",
        "wacht wacht wacht",
        "the the the",
        "please please please",
    ],
)
def test_herhaling_van_hetzelfde_woord_wisselt_niets(vraag):
    assert taal.detecteer_vraagtaal(vraag) is None
    assert taal.volgt_vraag(vraag) is None
    assert taal.taal() == taal.NEDERLANDS
    assert taal.spraak_code() == "nl-NL"


@pytest.mark.parametrize(
    "vraag",
    [
        "stop please stop",
        "ok please ok",
    ],
)
def test_stopwoorden_tellen_niet_als_engels_signaal(vraag):
    """Stopwoorden ("stop", "wacht", "nee", "ja", "ok") zijn geen signaal."""
    assert taal.detecteer_vraagtaal(vraag) is None


def test_unieke_signaalwoorden_tellen_niet_meer():
    """Het aantal voorkomens telt niet, alleen unieke signaalwoorden."""
    # Eén uniek Engels signaalwoord is te weinig (drempel is 2).
    assert taal.detecteer_vraagtaal("what what what happened") is None
    # Twee unieke signaalwoorden zijn genoeg.
    assert taal.detecteer_vraagtaal("what is what is happening") == taal.ENGELS
