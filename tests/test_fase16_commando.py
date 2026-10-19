"""Tests voor Fase 16A: spraak-commando's (core/proactive_commands.py).

Elke test krijgt een eigen TimerStore in tmp_path (geen echte
config/timers.json); de quiet-vlag wordt na elke test hersteld.
"""

import pytest

from core import proactive
from core import timers as timers_module
from core.proactive_commands import _extraheer_timer, try_proactive_command


@pytest.fixture(autouse=True)
def schone_staat(tmp_path):
    """Eigen store in tmp_path + schone quiet-/gesprek-vlaggen."""

    klok = [1_000_000.0]
    store = timers_module.TimerStore(
        pad=str(tmp_path / "timers.json"), clock=lambda: klok[0]
    )
    timers_module.reset_store(store)
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")

    yield store

    timers_module.reset_store(None)
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")


# ---------------------------------------------------------------
# Timers
# ---------------------------------------------------------------

def test_herinner_me_maakt_timer(schone_staat):
    """'herinner me over X om ...' zet een timer met de opgegeven naam."""
    antwoord = try_proactive_command(
        "herinner me over 20 minuten om de oven uit te zetten"
    )

    assert antwoord is not None
    assert "20 minuten" in antwoord

    timers = schone_staat.lijst()
    assert len(timers) == 1
    assert timers[0]["duur_seconden"] == 1200
    assert timers[0]["naam"] == "de oven uit te zetten"


def test_timer_zetten_zonder_voorzetsel(schone_staat):
    """'zet een timer van 10 minuten' werkt zonder over/in/na."""
    antwoord = try_proactive_command("zet een timer van 10 minuten")

    assert "10 minuten" in antwoord
    timers = schone_staat.lijst()
    assert timers[0]["duur_seconden"] == 600
    assert timers[0]["naam"] == "timer"


def test_timer_met_een_uur(schone_staat):
    """'over een uur' wordt 3600 seconden."""
    antwoord = try_proactive_command("herinner me over een uur")

    assert antwoord is not None
    assert schone_staat.lijst()[0]["duur_seconden"] == 3600


def test_welke_timers_leeg(schone_staat):
    assert try_proactive_command("welke timers") == (
        "Er zijn geen actieve timers."
    )


def test_welke_timers_met_timer(schone_staat):
    """De lijst toont naam en resterende tijd in menselijke taal."""
    try_proactive_command("herinner me over 30 minuten voor wandelen")

    antwoord = try_proactive_command("welke timers")

    assert antwoord.startswith("Je timers:")
    assert "wandelen" in antwoord
    assert "30 minuten" in antwoord


def test_annuleer_timer(schone_staat):
    """'annuleer timer voor X' verwijdert precies die timer."""
    try_proactive_command("herinner me over 10 minuten voor thee")

    antwoord = try_proactive_command("annuleer timer voor thee")

    assert antwoord == "Timer 'thee' is geannuleerd."
    assert schone_staat.lijst() == []


def test_annuleer_zonder_timers(schone_staat):
    assert try_proactive_command("annuleer timer") == (
        "Er zijn geen actieve timers."
    )


def test_annuleer_onbekende_naam(schone_staat):
    try_proactive_command("herinner me over 10 minuten voor thee")

    antwoord = try_proactive_command("annuleer timer voor koffie")

    assert antwoord == "Er is geen timer met de naam 'koffie'."
    assert len(schone_staat.lijst()) == 1


@pytest.mark.parametrize(
    "commando,seconden",
    [
        ("zet een wekker over een half uur", 1800),
        ("zet een wekker over anderhalf uur", 5400),
        ("zet een alarm over 10 minuten", 600),
        ("waarschuw me over 5 minuten", 300),
        ("zet een alarm voor drie kwartier", 2700),
        ("zet een wekker over twintig minuten", 1200),
    ],
)
def test_wekker_alarm_en_waarschuw_me(schone_staat, commando, seconden):
    """Wekker, alarm en 'waarschuw me' gelden als timerwoorden."""
    antwoord = try_proactive_command(commando)

    assert antwoord is not None
    timers = schone_staat.lijst()
    assert len(timers) == 1
    assert timers[0]["duur_seconden"] == seconden


def test_wekker_met_kloktijd_is_geen_duur(schone_staat):
    """Een absolute kloktijd ('om 7 uur') wordt niet als duur gelezen."""
    assert try_proactive_command("alarm om 7 uur") is None
    assert try_proactive_command("wekker voor 06:30") is None
    assert schone_staat.lijst() == []


# ---------------------------------------------------------------
# Nachtmodus en stille modus
# ---------------------------------------------------------------

def test_nachtmodus_aan_en_uit():
    aan = try_proactive_command("zet de nachtmodus aan")
    assert "nachtmodus staat aan" in aan.lower()

    uit = try_proactive_command("nachtmodus uit")
    assert "uitgeschakeld" in uit.lower()


def test_stille_modus_aan_en_uit():
    assert proactive.is_quiet() is False

    aan = try_proactive_command("stille modus aan")
    assert proactive.is_quiet() is True
    assert "stille modus staat aan" in aan.lower()

    uit = try_proactive_command("stille modus uit")
    assert proactive.is_quiet() is False
    assert "uitgeschakeld" in uit.lower()


def test_wees_stil_zet_quiet():
    antwoord = try_proactive_command("wees stil")
    assert proactive.is_quiet() is True
    assert antwoord is not None


# ---------------------------------------------------------------
# Router-gedrag
# ---------------------------------------------------------------

def test_ongerelateerd_commando_gaat_naar_andere_router():
    """Geen proactief onderdeel => None (de brain gaat verder)."""
    assert try_proactive_command("wat is het weer") is None
    assert try_proactive_command("speel muziek") is None
    assert try_proactive_command("") is None
    assert try_proactive_command(None) is None


def test_extraheer_timer_direct():
    """Losse extractie van duur + naam uit een timer-verzoek."""
    assert _extraheer_timer("herinner me over een uur") == (
        3600, "herinnering",
    )
    assert _extraheer_timer("boodschappen doen") is None
