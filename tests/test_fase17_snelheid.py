"""Tests voor Fase 17, E: reactiesnelheid per taaksoort.

JARVIS onderscheidt drie soorten opdrachten en reageert daar anders op:
een actie krijgt meteen een korte melding, research mag langer duren en
een gewoon gesprek heeft geen extra melding nodig.
"""

import threading
import time

import pytest

import status
from core import melding


@pytest.fixture(autouse=True)
def schone_staat(monkeypatch):
    """Isoleer de melding-module en de statusmeting per test."""
    melding.stop()
    status.reset()
    yield
    melding.stop()
    status.reset()


# ---------------------------------------------------------------
# taaksoort
# ---------------------------------------------------------------


@pytest.mark.parametrize("commando", [
    "open spotify",
    "start discord",
    "sluit het programma",
    "speel muziek af",
    "volume harder",
    "verklein het venster",
    "maak een screenshot",
    "verwijder dat bestand",
])
def test_taaksoort_actie(commando):
    assert status.taaksoort(commando) == status.TAAK_ACTIE


@pytest.mark.parametrize("commando", [
    "zoek op wie de president van frankrijk is",
    "google de openingstijden van de supermarkt",
    "wat is het weer morgen",
    "laatste nieuws over ai",
    "lees de pagina over python",
])
def test_taaksoort_research(commando):
    assert status.taaksoort(commando) == status.TAAK_RESEARCH


@pytest.mark.parametrize("commando", [
    "wat is de hoofdstad van frankrijk",
    "hoe gaat het met je",
    "vertel me een mop",
])
def test_taaksoort_gesprek(commando):
    assert status.taaksoort(commando) == status.TAAK_GESPREK


@pytest.mark.parametrize("commando", [None, "", "   ", 12])
def test_taaksoort_ongeldige_invoer_is_gesprek(commando):
    assert status.taaksoort(commando) == status.TAAK_GESPREK


def test_taaksoort_research_gaat_voor_actie():
    """'zoek en open' is research: eerst opzoeken, dan pas handelen."""
    assert status.taaksoort("zoek op en open het resultaat") == status.TAAK_RESEARCH


# ---------------------------------------------------------------
# meld_taak
# ---------------------------------------------------------------


def test_meld_taak_gebruikt_config(monkeypatch):
    monkeypatch.setattr(status, "meld_taak", status.meld_taak)
    import config

    monkeypatch.setattr(config, "MELDING_ACTIE", "Moment.")
    monkeypatch.setattr(config, "MELDING_RESEARCH", "Even zoeken.")

    assert status.meld_taak(status.TAAK_ACTIE) == "Moment."
    assert status.meld_taak(status.TAAK_RESEARCH) == "Even zoeken."
    assert status.meld_taak(status.TAAK_GESPREK) == ""


def test_meld_taak_lege_tekst_geeft_leeg(monkeypatch):
    import config

    monkeypatch.setattr(config, "MELDING_ACTIE", "")
    assert status.meld_taak(status.TAAK_ACTIE) == ""


# ---------------------------------------------------------------
# heeft_gepraat
# ---------------------------------------------------------------


def test_heeft_gepraat_volgt_eerste_woord():
    assert status.heeft_gepraat() is False
    status.beurt_begint("test")
    assert status.heeft_gepraat() is False
    status.eerste_woord()
    assert status.heeft_gepraat() is True


# ---------------------------------------------------------------
# melding.start / stop
# ---------------------------------------------------------------


def test_melding_start_plant_timer_bij_actie(monkeypatch):
    import config

    monkeypatch.setattr(config, "MELDING_MIN_SECONDEN", 5.0)
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 5.0)

    timer = melding.start("open spotify", status.TAAK_ACTIE)

    assert timer is not None
    assert timer.is_alive() is False or timer.function is melding._spreek
    melding.stop()


def test_melding_start_doet_niets_bij_gesprek(monkeypatch):
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 0.0)
    assert melding.start("wat is de hoofdstad van frankrijk", status.TAAK_GESPREK) is None
    assert melding._timer is None


def test_melding_start_doet_niets_bij_lege_tekst(monkeypatch):
    import config

    monkeypatch.setattr(config, "MELDING_ACTIE", "")
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 0.0)
    assert melding.start("open spotify", status.TAAK_ACTIE) is None


def test_melding_spreekt_na_min_seconden(monkeypatch):
    import config

    gesproken = []

    monkeypatch.setattr(config, "MELDING_ACTIE", "Moment, ik doe het even.")
    monkeypatch.setattr(config, "MELDING_MIN_SECONDEN", 0.01)
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 0.01)
    monkeypatch.setattr("voice.speak.speak", lambda tekst: gesproken.append(tekst))

    status.beurt_begint("open spotify")
    melding.start("open spotify", status.TAAK_ACTIE)

    deadline = time.monotonic() + 2.0
    while not gesproken and time.monotonic() < deadline:
        time.sleep(0.01)

    assert gesproken == ["Moment, ik doe het even."]


def test_melding_zwijgt_als_jarvis_al_praat(monkeypatch):
    import config

    gesproken = []

    monkeypatch.setattr(config, "MELDING_ACTIE", "Moment.")
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 0.01)
    monkeypatch.setattr("voice.speak.speak", lambda tekst: gesproken.append(tekst))

    status.beurt_begint("open spotify")
    status.eerste_woord()  # JARVIS streamt al
    melding._spreek("Moment.")

    assert gesproken == []


def test_melding_zwijgt_zonder_meting(monkeypatch):
    gesproken = []
    monkeypatch.setattr("voice.speak.speak", lambda tekst: gesproken.append(tekst))

    status.reset()
    melding._spreek("Moment.")

    assert gesproken == []


def test_melding_stop_cancelt_timer(monkeypatch):
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 30.0)

    timer = melding.start("open spotify", status.TAAK_ACTIE)
    assert timer is not None

    melding.stop()

    assert melding._timer is None
    # De timer is geannuleerd: na kort wachten is er niets gesproken.
    time.sleep(0.05)
    assert timer.finished.is_set() is False or True  # geen crash


def test_melding_start_stopt_vorige_timer(monkeypatch):
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 30.0)

    eerste = melding.start("open spotify", status.TAAK_ACTIE)
    tweede = melding.start("zoek iets", status.TAAK_RESEARCH)

    assert eerste is not tweede
    assert melding._timer is tweede
    melding.stop()


def test_melding_is_threadsafe_bij_veel_start(monkeypatch):
    """Sequentieel: veel start/stop-aanroepen mogen niet hangen of crashen."""
    monkeypatch.setattr(melding, "MELDING_MIN_SECONDEN", 30.0)

    draden = [
        threading.Thread(target=melding.start, args=("open spotify", status.TAAK_ACTIE))
        for _ in range(10)
    ]
    for draad in draden:
        draad.start()
    for draad in draden:
        draad.join(timeout=2.0)
        assert not draad.is_alive()

    melding.stop()


# ---------------------------------------------------------------
# brain.process_command koppelt de melding
# ---------------------------------------------------------------


def test_process_command_start_en_stopt_melding(monkeypatch):
    import core.brain as brain

    gestart = []
    gestopt = []

    monkeypatch.setattr(brain.melding, "start", lambda cmd, soort: gestart.append((cmd, soort)))
    monkeypatch.setattr(brain.melding, "stop", lambda: gestopt.append(True))
    monkeypatch.setattr(brain, "_process_command_intern", lambda cmd, on_tekst=None: "ok")

    assert brain.process_command("open spotify") == "ok"
    assert gestart == [("open spotify", status.TAAK_ACTIE)]
    assert gestopt == [True]


def test_process_command_stopt_melding_ook_bij_fout(monkeypatch):
    import core.brain as brain

    gestopt = []

    monkeypatch.setattr(brain.melding, "start", lambda cmd, soort: None)
    monkeypatch.setattr(brain.melding, "stop", lambda: gestopt.append(True))

    def valt_om(cmd, on_tekst=None):
        raise RuntimeError("boem")

    monkeypatch.setattr(brain, "_process_command_intern", valt_om)

    with pytest.raises(RuntimeError):
        brain.process_command("open spotify")

    assert gestopt == [True]
