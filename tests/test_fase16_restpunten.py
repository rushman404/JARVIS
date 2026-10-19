"""Tests voor de vijf restpunten van Fase 16.

1. Een vraag naar de nachtmodus verandert niets.
2. De nachtmodus-stand kan terug naar automatisch en een override
   verloopt bij de eerstvolgende automatische overgang.
3. Nieuws-opdrachten met "laatste", "tech", "me/mij" en losse "nieuws".
4. ``parse_duur`` weigert vage tellers, negatieve getallen, dubbele
   eenheden en duurdan 48 uur; "tweeënhalf" en "driëenhalf" werken.
5. De gespreksvlag-watchdog zet een blijven hangen vlag zelf uit.
"""

import os
from datetime import datetime

import pytest

from core import proactive
from core.proactive import ProactiveEngine
from core.proactive_commands import _verwerk_proactief
from core.timers import TimerStore, parse_duur
import core.externe_bronnen as eb


@pytest.fixture(autouse=True)
def schone_staat():
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    yield
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")


# =============================================================
# 1. Vraag naar de stand verandert niets
# =============================================================

VRAGEN = [
    "staat de nachtmodus aan",
    "is het nachtmodus",
    "is de nachtmodus actief",
    "geldt de nachtmodus nu",
    "werkt de nachtmodus",
    "nachtmodus?",
]


@pytest.mark.parametrize("vraag", VRAGEN)
def test_vraag_over_nachtmodus_verandert_niets(vraag):
    proactive.set_nachtmodus("auto")
    antwoord = _verwerk_proactief(vraag)
    assert antwoord is not None
    assert proactive.get_nachtmodus_stand() == "auto"


def test_vraag_over_nachtmodus_in_de_nacht_zet_niets_aan():
    # 23:30 valt in het automatische venster; een vraag mag de stand
    # niet op "aan" zetten.
    proactive.set_nachtmodus("auto")
    assert proactive.is_nachtmodus(datetime(2026, 6, 1, 23, 30)) is True
    _verwerk_proactief("staat de nachtmodus aan")
    assert proactive.get_nachtmodus_stand() == "auto"


# =============================================================
# 2. Terug naar automatisch en verloop van de override
# =============================================================

def test_zet_nachtmodus_aan_werkt():
    _verwerk_proactief("zet de nachtmodus aan")
    assert proactive.get_nachtmodus_stand() == "aan"
    assert proactive.is_nachtmodus(datetime(2026, 6, 1, 14, 0)) is True


def test_zet_nachtmodus_uit_werkt():
    _verwerk_proactief("nachtmodus uit")
    assert proactive.get_nachtmodus_stand() == "uit"
    assert proactive.is_nachtmodus(datetime(2026, 6, 1, 23, 30)) is False


@pytest.mark.parametrize("zin", [
    "nachtmodus automatisch",
    "nachtmodus auto",
    "nachtmodus normaal",
    "zet de nachtmodus automatisch",
    "zet de nachtmodus op automatisch",
    "reset de nachtmodus",
])
def test_nachtmodus_terug_naar_automatisch(zin):
    proactive.set_nachtmodus("uit")
    assert proactive.get_nachtmodus_stand() == "uit"
    antwoord = _verwerk_proactief(zin)
    assert antwoord is not None
    assert proactive.get_nachtmodus_stand() == "auto"


def test_override_uit_verloopt_bij_de_volgende_overgang():
    # "uit" gezet om 23:30 geldt tot 07:00; daarna weer auto.
    proactive.set_nachtmodus("uit", nu=datetime(2026, 6, 1, 23, 30).timestamp())
    verloopt = proactive.get_nachtmodus_verloopt()
    assert datetime.fromtimestamp(verloopt) == datetime(2026, 6, 2, 7, 0)
    assert proactive.is_nachtmodus(datetime(2026, 6, 1, 23, 45)) is False
    assert proactive.is_nachtmodus(datetime(2026, 6, 2, 6, 59)) is False
    assert (
        proactive.get_nachtmodus_stand(nu=datetime(2026, 6, 2, 7, 1).timestamp())
        == "auto"
    )


def test_override_aan_verloopt_bij_de_volgende_overgang():
    # "aan" gezet om 14:00 geldt tot 23:00; daarna weer auto.
    proactive.set_nachtmodus("aan", nu=datetime(2026, 6, 1, 14, 0).timestamp())
    verloopt = proactive.get_nachtmodus_verloopt()
    assert datetime.fromtimestamp(verloopt) == datetime(2026, 6, 1, 23, 0)
    assert proactive.is_nachtmodus(datetime(2026, 6, 1, 23, 30)) is True
    assert (
        proactive.get_nachtmodus_stand(nu=datetime(2026, 6, 1, 23, 5).timestamp())
        == "auto"
    )


def test_nachtmodus_auto_heeft_geen_vervaltijd():
    proactive.set_nachtmodus("aan")
    assert proactive.get_nachtmodus_verloopt() is not None
    proactive.set_nachtmodus("auto")
    assert proactive.get_nachtmodus_verloopt() is None


def test_antwoord_van_aan_noemt_de_stand_en_de_geldigheid():
    antwoord = _verwerk_proactief("zet de nachtmodus aan")
    assert "nachtmodus staat aan" in antwoord.lower()
    assert "geldt tot" in antwoord.lower()


# =============================================================
# 3. Nieuws-opdrachten
# =============================================================

NIEUWS_POSITIEF = [
    "wat is het laatste nieuws",
    "geef me het laatste nieuws",
    "lees het laatste nieuws voor",
    "laatste nieuws",
    "vertel me het nieuws",
    "wat is het tech nieuws",
    "wat is het actuele nieuws",
    "wat is het nieuwste nieuws",
    "geef mij het nieuwste nieuws",
    "nieuws",
    "wat is het nieuws",
    "nieuws van tweakers",
]


@pytest.mark.parametrize("zin", NIEUWS_POSITIEF)
def test_nieuws_opdracht_matcht(zin):
    assert eb._NIEUWS_PATROON_OPDRACHT.search(zin.lower()) is not None


NIEUWS_NEGATIEF = [
    "ik heb het nieuws gezien",
    "het nieuws was slecht vandaag",
    "nieuws is saai",
    "het nieuws van gisteren was interessant",
    "ik mis het nieuws van vroeger",
]


@pytest.mark.parametrize("zin", NIEUWS_NEGATIEF)
def test_nieuws_mededeling_matcht_niet(zin):
    assert eb._NIEUWS_PATROON_OPDRACHT.search(zin.lower()) is None


# =============================================================
# 4. parse_duur
# =============================================================

def test_parse_duur_weigert_vage_tellers():
    assert parse_duur("een paar minuten") is None
    assert parse_duur("een tijdje") is None
    assert parse_duur("een poosje") is None


def test_parse_duur_weigert_negatieve_getallen():
    assert parse_duur("-5 minuten") is None
    assert parse_duur("min 5 minuten") is None


def test_parse_duur_weigert_dubbele_eenheid():
    assert parse_duur("1 uur 2 uur") is None
    assert parse_duur("5 minuten 10 minuten") is None


def test_parse_duur_weigert_boven_48_uur():
    assert parse_duur("99999 uur") is None
    assert parse_duur("49 uur") is None
    assert parse_duur("48 uur") == 48 * 3600


def test_parse_duur_tweeënhalf_uur():
    assert parse_duur("tweeënhalf uur") == 9000
    assert parse_duur("drieënhalf uur") == 12600


def test_parse_duur_bestaande_gevallen_blijven_werken():
    assert parse_duur("een half uur") == 1800
    assert parse_duur("1 uur en 30 minuten") == 5400
    assert parse_duur("anderhalf uur") == 5400
    assert parse_duur("drie kwartier") == 2700
    assert parse_duur("vijfentwintig minuten") == 1500
    assert parse_duur("1,5 uur") == 5400


# =============================================================
# 5. Gespreksvlag-watchdog
# =============================================================

def _maak_engine(tmp_path, klok):
    regels = os.path.join(tmp_path, "regels.json")
    with open(regels, "w", encoding="utf-8") as f:
        f.write("[]")
    store = TimerStore(pad=os.path.join(tmp_path, "timers.json"))
    engine = ProactiveEngine(
        store=store,
        rules_pad=regels,
        time_fn=lambda: klok[0],
        now_fn=lambda: datetime.fromtimestamp(klok[0]),
        lever_fn=lambda t: None,
    )
    return engine


def test_watchdog_zet_vastgelopen_gespreksvlag_uit(tmp_path):
    klok = [datetime(2026, 6, 1, 12, 0, 0).timestamp()]
    engine = _maak_engine(str(tmp_path), klok)

    proactive.set_in_gesprek(True)
    engine.tick()
    assert proactive.is_in_gesprek() is True

    klok[0] += 300
    engine.tick()
    assert proactive.is_in_gesprek() is True

    klok[0] += 301
    engine.tick()
    assert proactive.is_in_gesprek() is False


def test_watchdog_laat_korte_gesprekken_met_rust(tmp_path):
    klok = [datetime(2026, 6, 1, 12, 0, 0).timestamp()]
    engine = _maak_engine(str(tmp_path), klok)

    proactive.set_in_gesprek(True)
    engine.tick()
    klok[0] += 60
    engine.tick()
    klok[0] += 60
    engine.tick()
    # De teller loopt door zolang de vlag aan blijft.
    assert proactive.is_in_gesprek() is True


def test_watchdog_reset_als_vlag_weer_uit_is(tmp_path):
    klok = [datetime(2026, 6, 1, 12, 0, 0).timestamp()]
    engine = _maak_engine(str(tmp_path), klok)

    proactive.set_in_gesprek(True)
    engine.tick()
    proactive.set_in_gesprek(False)
    engine.tick()
    assert engine._gesprek_sinds is None


def test_timer_wacht_nooit_langer_dan_dertig_minuten():
    from core.proactive import GEBRUIKER_MELDING_TTL
    assert GEBRUIKER_MELDING_TTL == 30 * 60


def test_watchdog_duur_is_tien_minuten():
    assert proactive.GESPREK_WATCHDOG_SECONDEN == 10 * 60
