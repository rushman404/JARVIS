"""Tests voor de COM-worker: snelle foutdoorgifte, timeout + annulering.

COM/pycaw/pywinauto worden gemockt; de worker zelf is een echte thread.
"""
import threading
import time

import pytest

from actions import com_worker
from actions.com_worker import run_on_com_thread


def test_resultaat_komt_terug():
    assert run_on_com_thread(lambda: 42, timeout=5) == 42


def test_exception_komt_snel_terug_met_origineel_type():
    """De originele exception moet binnen 1 seconde terugkomen, niet na
    de volledige timeout van 10 seconden."""

    def boom():
        raise ValueError("kapot")

    begin = time.time()
    with pytest.raises(ValueError) as excinfo:
        run_on_com_thread(boom, timeout=10)

    assert "kapot" in str(excinfo.value)
    assert time.time() - begin < 1.0


def test_timeout_geeft_nederlandse_Timeouter_ook_bij_strfout():
    """Een echte timeout geeft een TimeoutError met Nederlandse melding."""

    blokkade = threading.Event()
    bezig = threading.Event()

    def trage():
        bezig.set()
        blokkade.wait(3)

    def late():
        raise AssertionError("mag nooit lopen")

    # Houd de worker bezig met een blokkerende taak.
    draad = threading.Thread(target=lambda: run_on_com_thread(trage, timeout=5))
    draad.start()
    assert bezig.wait(2)

    with pytest.raises(TimeoutError) as excinfo:
        run_on_com_thread(late, timeout=0.1)

    assert "geannuleerd" in str(excinfo.value)

    blokkade.set()
    draad.join(timeout=3)


def test_te_late_taak_wordt_niet_uitgevoerd():
    """Een taak die na de timeout in de wachtrij blijft, mag niet lopen."""

    uitgevoerd = []
    blokkade = threading.Event()
    bezig = threading.Event()

    def trage():
        bezig.set()
        blokkade.wait(3)

    def te_laat():
        uitgevoerd.append(True)

    draad = threading.Thread(target=lambda: run_on_com_thread(trage, timeout=5))
    draad.start()
    assert bezig.wait(2)

    with pytest.raises(TimeoutError):
        run_on_com_thread(te_laat, timeout=0.1)

    blokkade.set()
    draad.join(timeout=3)

    # Laat de worker tijd om de taak op te pakken en over te slaan.
    time.sleep(1.0)
    assert uitgevoerd == []


def test_eigen_Timeouter_van_de_taak_wordt_doorgegeven():
    """Als de functie zelf een TimeoutError gooit, wordt die doorgegeven."""

    def eigen_timeout():
        raise TimeoutError("mijn eigen vertraging")

    with pytest.raises(TimeoutError) as excinfo:
        run_on_com_thread(eigen_timeout, timeout=5)

    assert "mijn eigen vertraging" in str(excinfo.value)


def test_parallelle_aanroepen_op_dezelfde_thread():
    """20 parallelle aanroepen moeten allemaal op dezelfde thread draaien."""

    ids = []
    lock = threading.Lock()

    def noteer():
        with lock:
            ids.append(threading.get_ident())

    draden = [
        threading.Thread(target=lambda: run_on_com_thread(noteer, timeout=5))
        for _ in range(20)
    ]
    for d in draden:
        d.start()
    for d in draden:
        d.join()

    assert len(ids) == 20
    assert len(set(ids)) == 1


def test_shutdown_is_idempotent():
    """shutdown_com_thread() mag vaker aangeroepen worden zonder fouten."""
    com_worker.shutdown_com_thread()
    com_worker.shutdown_com_thread()

    # Na shutdown moet de worker vanzelf weer opstarten.
    assert run_on_com_thread(lambda: "ok", timeout=5) == "ok"