"""Fase 17 — de twee laatste afgeronde punten.

* **Niet-begrepen-drempel:** JARVIS vraagt niet eindeloos om herhaling,
  maar zegt na een paar mislukkingen een vriendelijk woord. De sessie
  blijft daarna gewoon open.
* **Vloeiende context-wissel:** binnen een sessie blijft de context van
  de vorige taak beschikbaar, ook als er tussendoor een andere taak is
  uitgevoerd.
"""

import pytest

import main
from config import NIET_BEGREPEN_DREMPEL


# =============================================================
# 1. Niet-begrepen-drempel
# =============================================================

def test_teller_bereikt_drempel_na_aantal_pogingen():
    teller = main.NietBegrepenTeller(2)

    assert teller.registreer() is False  # 1e mislukking
    assert teller.registreer() is True   # 2e mislukking -> drempel


def test_teller_reset_na_geslaagde_herkenning():
    teller = main.NietBegrepenTeller(2)

    teller.registreer()
    teller.reset()

    assert teller.registreer() is False


def test_teller_minimaal_een():
    # Een drempel van 0 of negatief zou betekenen dat hij meteen opgeeft;
    # dat mag nooit: minstens één keer om herhaling vragen.
    assert main.NietBegrepenTeller(0).drempel == 1
    assert main.NietBegrepenTeller(-5).drempel == 1


def test_spreek_niet_begrepen_vraagt_om_herhaling_onder_drempel(monkeypatch):
    gezegd = []
    monkeypatch.setattr(main, "speak", lambda tekst, **k: gezegd.append(tekst))
    monkeypatch.setattr(main, "get_pending", lambda: False)

    teller = main.NietBegrepenTeller(2)
    main._spreek_niet_begrepen(teller)

    assert gezegd and "herhalen" in gezegd[0].lower()


def test_spreek_niet_begrepen_meldt_vriendelijk_op_drempel(monkeypatch):
    gezegd = []
    monkeypatch.setattr(main, "speak", lambda tekst, **k: gezegd.append(tekst))
    monkeypatch.setattr(main, "get_pending", lambda: False)
    monkeypatch.setattr(main, "NIET_BEGREPEN_MELDING", "Ik laat het even rusten.")

    teller = main.NietBegrepenTeller(2)
    main._spreek_niet_begrepen(teller)  # 1e: om herhaling
    main._spreek_niet_begrepen(teller)  # 2e: drempel bereikt

    assert gezegd[-1] == "Ik laat het even rusten."


def test_spreek_niet_begrepen_reset_na_melding(monkeypatch):
    gezegd = []
    monkeypatch.setattr(main, "speak", lambda tekst, **k: gezegd.append(tekst))
    monkeypatch.setattr(main, "get_pending", lambda: False)
    monkeypatch.setattr(main, "NIET_BEGREPEN_MELDING", "Ik laat het even rusten.")

    teller = main.NietBegrepenTeller(2)
    main._spreek_niet_begrepen(teller)  # 1e: om herhaling
    main._spreek_niet_begrepen(teller)  # 2e: melding, teller weer op 0
    main._spreek_niet_begrepen(teller)  # 1e na reset: weer om herhaling

    assert "herhalen" in gezegd[-1].lower()


def test_sessie_blijft_open_en_stopt_na_melding(monkeypatch):
    """Na de drempel gaat de sessie NIET dicht: hij blijft luisteren."""
    monkeypatch.setattr(main, "wait_for_wake_word", lambda *a, **k: {"detected_at": 1.0})

    gezegd = []
    monkeypatch.setattr(main, "speak", lambda tekst=None, **k: gezegd.append(tekst))

    # Twee keer niet verstaan, daarna een geldige opdracht, daarna stilte.
    opdrachten = [None, "NOT_UNDERSTOOD", "open spotify", ""]

    def fake_listen(start_ts=None, **k):
        return opdrachten.pop(0)

    monkeypatch.setattr(main, "listen", fake_listen)

    verwerkt = []
    monkeypatch.setattr(
        main,
        "process_command",
        lambda cmd, on_tekst=None: verwerkt.append(cmd) or "ok",
    )

    main.run_wake_cycle()

    # De geldige opdracht is gewoon verwerkt: de sessie bleef dus open.
    assert verwerkt == ["open spotify"]


# =============================================================
# 2. Vloeiende context-wissel
# =============================================================

def test_context_behouden_over_taakwissel(monkeypatch):
    """De context van taak A blijft staan als taak B niets overschrijft."""
    from core import ai

    # Verse context met de bekende sleutels.
    for sleutel in ai.current_context:
        ai.current_context[sleutel] = None if sleutel == "pending_choice" else ""
    monkeypatch.setattr(ai, "_save_conversation", lambda *a, **k: None)

    ai.update_context(last_command="open spotify", last_program="spotify")

    # Taak B is een gewone vraag: die raakt de programma-context niet aan.
    ai.update_context(last_action="normale vraag")

    assert ai.current_context["last_command"] == "open spotify"
    assert ai.current_context["last_program"] == "spotify"


def test_recente_geschiedenis_bewaard_bij_wissel(monkeypatch):
    """Beide taken staan nog in de geschiedenis, in volgorde."""
    from core import ai

    ai.conversation_history.clear()
    monkeypatch.setattr(ai, "_save_conversation", lambda *a, **k: None)

    ai.add_to_history("user", "open spotify")
    ai.add_to_history("assistant", "Spotify is geopend.")
    ai.add_to_history("user", "wat voor weer is het?")
    ai.add_to_history("assistant", "Het is zonnig.")

    inhoud = [m["content"] for m in ai.conversation_history]
    assert "open spotify" in inhoud
    assert "wat voor weer is het?" in inhoud
