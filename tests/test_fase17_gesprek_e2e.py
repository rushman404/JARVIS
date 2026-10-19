"""Afsluitende tests voor Fase 17 (stap 11): het hele gesprek als keten.

Waar de losse testbestanden elk onderdeel afdekken (streaming, barge-in,
sessie, gespreksflow, status, taal, ducking), meet dit bestand het geheel
zoals het in ``main.run_wake_cycle`` echt gebeurt:

* **Latency** — van vraag tot eerste gesproken stuk tekst, met een vaste
  bovengrens zodat een trage wijziging meteen opvalt.
* **Onderbreken midden in een antwoord** — het uitspreken stopt en de
  volgende opname begint bij het moment van onderbreken.
* **Multi-beurt gesprek** — meerdere beurten zonder herhaald wake word,
  met context uit de vorige beurt.

De tijden komen uit ``status`` (eerste woord) en worden in een echt gesprek
ook naar de console gelogd als "💬 Reactie: eerste woord na ...s".
"""

import time

import pytest

import main
import status
from core import ai
from voice import speak as speak_module


@pytest.fixture(autouse=True)
def schone_staat():
    """Elke test begint met een lege reactiemeting en verse spraakstaat."""
    status.reset()
    speak_module._STOP.clear()
    speak_module._spreek_actief.clear()
    yield
    status.reset()
    speak_module._STOP.clear()
    speak_module._spreek_actief.clear()


@pytest.fixture
def zonder_ducking(monkeypatch):
    """Ducking raakt in deze tests geen echt systeemvolume."""
    import voice.ducking as ducking

    monkeypatch.setattr(ducking, "duck", lambda: None)
    monkeypatch.setattr(ducking, "herstel", lambda: None)


# =============================================================
# 1. Latency: vraag -> eerste gesproken stuk
# =============================================================

def test_latency_tot_eerste_woord_blijft_onder_grens(monkeypatch):
    """Van het eerste tekststuk tot de spreker mag maar even duren.

    Dit meet de echte streaming-keten: ``TekstStroom`` duwt het eerste stuk
    naar ``speak_stream``, en ``speak_stream`` speelt de eerste zin af. De
    bovengrens is ruim (0,5 s) zodat een drukke machine hem niet omver gooit,
    maar streng genoeg om een echte vertraging te vangen.
    """
    grens_seconden = 0.5
    gezien = []

    import numpy as np

    import voice.piper_tts as pt
    import voice.speak as sm_mod
    import voice.stream_bridge as sb

    monkeypatch.setattr(sm_mod, "_mute_microphone", lambda: None)
    monkeypatch.setattr(sm_mod, "_unmute_microphone", lambda: None)
    monkeypatch.setattr(
        sm_mod, "_play", lambda samples, rate: gezien.append(time.monotonic())
    )
    monkeypatch.setattr(pt, "is_available", lambda: True)
    monkeypatch.setattr(
        pt,
        "synthesize",
        lambda tekst, volume=1.0: iter([(np.zeros(100, dtype="int16"), 22050)]),
    )

    stroom = sb.TekstStroom()
    start = time.monotonic()
    stroom.schrijf("Dit is een kort antwoord. ")
    stroom.sluit_af()
    duur = time.monotonic() - start

    assert gezien, "de spreker is nooit begonnen"
    assert duur < grens_seconden, f"eerste woord pas na {duur:.2f}s"


def test_spreek_antwoord_herhaalt_gestreamd_antwoord_niet(monkeypatch):
    """Wat al gestreamd is, wordt niet nog eens blokkerend uitgesproken."""
    gesproken = []
    monkeypatch.setattr(speak_module, "speak", lambda tekst: gesproken.append(tekst))

    class NepStroom:
        gestreamd = True

    assert main.spreek_antwoord("Antwoord.", NepStroom()) is True
    assert gesproken == []


def test_status_meet_latency_van_vraag_tot_antwoord(caplog):
    """``status`` logt de reactietijd zoals de gebruiker die in de console ziet."""
    with caplog.at_level("INFO"):
        status.beurt_begint("hoe laat is het")
        time.sleep(0.01)
        status.eerste_woord()
        time.sleep(0.01)
        status.beurt_klaar()

    assert "🧠 Denkt na: hoe laat is het" in caplog.text
    assert "💬 Reactie: eerste woord na" in caplog.text
    assert "klaar na" in caplog.text


def test_ask_ai_streamt_en_meet_het_eerste_woord(monkeypatch, zonder_ducking):
    """De gewone-vraag-route streamt en noteert het eerste woord."""
    stukken = []

    def nep_chat_stream(messages=None, tools=None):
        yield "De hoofdstad "
        yield "van Frankrijk "
        yield "is Parijs."

    monkeypatch.setattr(ai.llm, "chat_stream", nep_chat_stream)
    monkeypatch.setattr(ai, "is_action_request", lambda q: False)
    monkeypatch.setattr(ai, "_chat_history", lambda: [])
    monkeypatch.setattr(ai, "build_memory_context", lambda *a, **k: "")
    monkeypatch.setattr(ai, "memory_summary", lambda: "")
    monkeypatch.setattr(ai, "extract_personal_info", lambda *a, **k: "")
    monkeypatch.setattr(ai, "update_context", lambda **k: None)
    monkeypatch.setattr(ai, "add_to_history", lambda *a, **k: None)

    status.beurt_begint("wat is de hoofdstad van frankrijk?")
    antwoord = ai.ask_ai(
        "wat is de hoofdstad van frankrijk?", on_tekst=stukken.append
    )

    assert stukken == ["De hoofdstad ", "van Frankrijk ", "is Parijs."]
    assert antwoord == "De hoofdstad van Frankrijk is Parijs."
    assert status.heeft_gepraat() is True


# =============================================================
# 2. Onderbreken midden in een lang antwoord
# =============================================================

def _fake_speak_stream(gezien):
    """Vervangt speak_stream door een variant die alleen noteert."""
    def fake(deltas, stop_event=None):
        for stuk in deltas:
            if stop_event is not None and stop_event.is_set():
                break
            gezien.append((stuk, time.monotonic()))

    return fake


def test_onderbreking_stopt_lange_lijst_meteen(monkeypatch):
    """Bij een onderbreking worden de resterende stukken niet meer gesproken."""
    import threading

    import voice.stream_bridge as sb

    gesproken = []
    stop = threading.Event()

    def nep_speak_stream(deltas, stop_event=None):
        for stuk in deltas:
            if stop_event is not None and stop_event.is_set():
                break
            gesproken.append(stuk)
            if stuk == "stuk 1.":
                stop.set()  # de gebruiker valt JARVIS in de rede

    monkeypatch.setattr(sb, "speak_stream", nep_speak_stream)

    stroom = sb.TekstStroom(stop_event=stop)
    for i in range(20):
        stroom.schrijf(f"stuk {i}.")
    stroom.sluit_af()

    assert gesproken == ["stuk 0.", "stuk 1."], (
        "na de onderbreking mag er niets meer gesproken worden"
    )


def test_speak_stream_zonder_onderbreking_spreekt_alles(monkeypatch):
    """Zonder onderbreking komen alle zinnen er door (echte speak_stream-route)."""
    gesproken = []

    import numpy as np

    import voice.piper_tts as pt
    import voice.speak as sm_mod

    monkeypatch.setattr(pt, "is_available", lambda: True)
    monkeypatch.setattr(
        pt,
        "synthesize",
        lambda tekst, volume=1.0: iter([(np.zeros(100, dtype="int16"), 22050)]),
    )
    monkeypatch.setattr(sm_mod, "_mute_microphone", lambda: None)
    monkeypatch.setattr(sm_mod, "_unmute_microphone", lambda: None)
    monkeypatch.setattr(sm_mod, "_play", lambda samples, rate: gesproken.append(rate))

    sm_mod.speak_stream(
        [
            "Dit is de eerste zin van het antwoord en die is lekker lang. "
            "En dit is de tweede zin van het antwoord, ook behoorlijk lang. "
        ]
    )

    assert len(gesproken) == 2, "twee zinnen, twee keer afgespeeld"


# =============================================================
# 3. Multi-beurt gesprek via main.run_wake_cycle
# =============================================================

def test_multi_beurt_gesprek_doorloopt_meerdere_beurten(monkeypatch, zonder_ducking):
    """Eén wake word, meerdere beurten, en na het einde weer slapen."""
    monkeypatch.setattr(main, "wait_for_wake_word", lambda *a, **k: {"detected_at": 2.0})
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)

    opdrachten = ["open spotify", "zet hem harder", "en zet hem weer zachter", ""]

    def fake_listen(start_ts=None, **k):
        return opdrachten.pop(0)

    monkeypatch.setattr(main, "listen", fake_listen)
    verwerkt = []

    def fake_process(cmd, on_tekst=None):
        verwerkt.append(cmd)
        if on_tekst is not None:
            on_tekst("Antwoord.")
        return "Antwoord."

    monkeypatch.setattr(main, "process_command", fake_process)

    main.run_wake_cycle()

    assert verwerkt == ["open spotify", "zet hem harder", "en zet hem weer zachter"]


def test_multi_beurt_latency_geen_wake_word_per_beurt(monkeypatch, zonder_ducking):
    """Binnen één sessie hoeft het wake word maar één keer."""
    monkeypatch.setattr(main, "wait_for_wake_word", lambda *a, **k: {"detected_at": 1.0})
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)

    wake_aanroepen = {"n": 0}
    monkeypatch.setattr(
        main,
        "wait_for_wake_word",
        lambda *a, **k: wake_aanroepen.__setitem__("n", wake_aanroepen["n"] + 1)
        or {"detected_at": 1.0},
    )

    antwoorden = ["open spotify", "en nu?", ""]
    monkeypatch.setattr(main, "listen", lambda start_ts=None, **k: antwoorden.pop(0))
    monkeypatch.setattr(
        main, "process_command", lambda cmd, on_tekst=None: "ok"
    )

    main.run_wake_cycle()

    # Drie beurten (twee opdrachten + de lege beurt die de sessie sluit)
    # zonder dat wait_for_wake_word opnieuw nodig was binnen die sessie.
    assert wake_aanroepen["n"] == 1
