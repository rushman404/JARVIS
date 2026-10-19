"""Tests voor de streaming-pipeline (Fase 17, stap A3).

Dekt de keten die antwoorden sneller laat klinken:

- ``TekstStroom`` (voice/stream_bridge.py): stukjes tekst gaan naar een
  eigen thread die ze via ``speak_stream`` uitspreekt, en pas vanaf het
  eerste stuk tekst.
- ``ask_ai`` (core/ai.py): met ``on_tekst`` streamt een gewone vraag via
  ``llm.chat_stream``; zonder callback blijft alles blokkerend.
- ``process_command`` (core/brain.py): geeft ``on_tekst`` door aan de AI,
  maar laat bestaande aanroepen (zonder callback) precies zo werken.
- ``spreek_antwoord`` (main.py): herhaalt een al gestreamd antwoord niet.
"""

import threading
import types

import pytest

import main
from core import ai
from voice import stream_bridge


# =============================================================
# TekstStroom: van tekststukjes naar spraak
# =============================================================

def test_tekststroom_spreekt_de_stukjes_uit(monkeypatch):
    """Alle stukjes komen in volgorde bij speak_stream aan."""
    ontvangen = []

    def fake_speak_stream(deltas, stop_event=None):
        ontvangen.extend(list(deltas))

    monkeypatch.setattr(stream_bridge, "speak_stream", fake_speak_stream)

    stroom = stream_bridge.TekstStroom()
    assert stroom.gestreamd is False

    stroom.schrijf("Hallo ")
    stroom.schrijf("wereld.")
    stroom.sluit_af()

    assert stroom.gestreamd is True
    assert ontvangen == ["Hallo ", "wereld."]


def test_tekststroom_zonder_tekst_start_niets(monkeypatch):
    """Lege stukjes starten geen thread en spreken niets uit."""
    monkeypatch.setattr(
        stream_bridge, "speak_stream", lambda *a, **k: pytest.fail("mag niet")
    )

    stroom = stream_bridge.TekstStroom()
    stroom.schrijf("")
    stroom.schrijf(None)
    stroom.sluit_af()

    assert stroom.gestreamd is False
    assert stroom._thread is None


def test_tekststroom_geeft_stop_event_door(monkeypatch):
    """Een meegegeven stop_event bereikt speak_stream (voor barge-in)."""
    gevangen = {}

    def fake_speak_stream(deltas, stop_event=None):
        gevangen["stop_event"] = stop_event
        list(deltas)

    monkeypatch.setattr(stream_bridge, "speak_stream", fake_speak_stream)

    event = threading.Event()
    stroom = stream_bridge.TekstStroom(stop_event=event)
    stroom.schrijf("Hallo.")
    stroom.sluit_af()

    assert gevangen["stop_event"] is event


def test_tekststroom_vangt_fouten_in_de_spreekthread(monkeypatch):
    """Een fout in speak_stream laat sluit_af() niet hangen."""
    def kapot(deltas, stop_event=None):
        raise RuntimeError("kapot")

    monkeypatch.setattr(stream_bridge, "speak_stream", kapot)

    stroom = stream_bridge.TekstStroom()
    stroom.schrijf("Hallo.")
    stroom.sluit_af()

    assert stroom.gestreamd is True
    assert stroom._thread.is_alive() is False


# =============================================================
# ask_ai: streamen met en zonder callback
# =============================================================

def _stille_ai(monkeypatch, *, extra=None):
    """Neutraliseert de bijwerkingen van ask_ai voor de tests."""
    monkeypatch.setattr(ai, "is_action_request", lambda vraag: False)
    monkeypatch.setattr(ai, "update_context", lambda **kw: None)
    monkeypatch.setattr(ai, "add_to_history", lambda *a, **kw: None)
    monkeypatch.setattr(ai, "_chat_history", lambda: [])
    monkeypatch.setattr(ai, "extract_personal_info", lambda vraag, antwoord: None)
    if extra:
        for naam, waarde in extra.items():
            monkeypatch.setattr(ai, naam, waarde)


def test_ask_ai_streamt_de_stukjes_naar_de_callback(monkeypatch):
    _stille_ai(monkeypatch)
    stukken = ["De hoofdstad ", "van Frankrijk ", "is Parijs."]
    monkeypatch.setattr(
        ai.llm, "chat_stream", lambda messages=None, **kw: iter(stukken)
    )
    monkeypatch.setattr(
        ai.llm, "chat", lambda *a, **kw: pytest.fail("blokkerende chat mag niet")
    )

    gezien = []
    resultaat = ai.ask_ai("wat is de hoofdstad van frankrijk", on_tekst=gezien.append)

    assert gezien == stukken
    assert resultaat == "De hoofdstad van Frankrijk is Parijs."


def test_ask_ai_streamt_de_onthouden_notitie_mee(monkeypatch):
    _stille_ai(
        monkeypatch,
        extra={"extract_personal_info": lambda vraag, antwoord: "Ik onthoud het."},
    )
    monkeypatch.setattr(
        ai.llm, "chat_stream", lambda messages=None, **kw: iter(["Hallo."])
    )

    gezien = []
    resultaat = ai.ask_ai("hoi", on_tekst=gezien.append)

    assert gezien == ["Hallo.", " Ik onthoud het."]
    assert resultaat == "Hallo. Ik onthoud het."


def test_ask_ai_zonder_callback_blijft_blokkerend(monkeypatch):
    _stille_ai(monkeypatch)
    monkeypatch.setattr(
        ai.llm, "chat_stream", lambda *a, **kw: pytest.fail("stream mag niet")
    )
    monkeypatch.setattr(
        ai.llm,
        "chat",
        lambda messages=None, **kw: types.SimpleNamespace(
            message=types.SimpleNamespace(content="Hallo.")
        ),
    )

    assert ai.ask_ai("hoi") == "Hallo."


def test_ask_ai_streamfout_zonder_tekst_gooit_door(monkeypatch):
    _stille_ai(monkeypatch)

    def kapot(messages=None, **kw):
        raise RuntimeError("model onbereikbaar")
        yield  # pragma: no cover

    monkeypatch.setattr(ai.llm, "chat_stream", kapot)

    gezien = []
    with pytest.raises(RuntimeError):
        ai.ask_ai("hoi", on_tekst=gezien.append)

    assert gezien == []


def test_ask_ai_halve_stream_geeft_deel_terug(monkeypatch):
    """Een afgebroken stream met al tekst levert dat deel op (geen crash)."""
    _stille_ai(monkeypatch)

    def half(messages=None, **kw):
        yield "Hallo "
        raise RuntimeError("verbinding weg")

    monkeypatch.setattr(ai.llm, "chat_stream", half)

    gezien = []
    resultaat = ai.ask_ai("hoi", on_tekst=gezien.append)

    assert gezien == ["Hallo "]
    assert resultaat == "Hallo "


# =============================================================
# process_command: doorgeven zonder bestaande aanroepen te breken
# =============================================================

def test_process_command_geeft_on_tekst_door(monkeypatch):
    import core.brain as brain

    gezien = {}

    def fake_ask_ai(command, on_tekst=None):
        gezien["command"] = command
        gezien["on_tekst"] = on_tekst
        if on_tekst is not None:
            on_tekst("stukje")
        return "Antwoord."

    monkeypatch.setattr(brain, "ask_ai", fake_ask_ai)

    callback = lambda tekst: None  # noqa: E731
    resultaat = brain.process_command(
        "wat is de hoofdstad van frankrijk", on_tekst=callback
    )

    assert resultaat == "Antwoord."
    assert gezien["on_tekst"] is callback


def test_process_command_zonder_on_tekst_werkt_met_oude_stubs(monkeypatch):
    """Bestaande stubs met één parameter blijven werken."""
    import core.brain as brain

    def fake_ask_ai(command):  # geen on_tekst-parameter
        return "AI-STUB"

    monkeypatch.setattr(brain, "ask_ai", fake_ask_ai)

    assert brain.process_command("wat is de hoofdstad van frankrijk") == "AI-STUB"


# =============================================================
# main.spreek_antwoord: niet dubbel uitspreken
# =============================================================

def test_spreek_antwoord_spreekt_blokkerend_uit(monkeypatch):
    gesproken = []
    monkeypatch.setattr(main, "speak", gesproken.append)

    assert main.spreek_antwoord("Hallo.") is True
    assert gesproken == ["Hallo."]


def test_spreek_antwoord_herhaalt_gestreamd_antwoord_niet(monkeypatch):
    gesproken = []
    monkeypatch.setattr(main, "speak", gesproken.append)

    stroom = types.SimpleNamespace(gestreamd=True)
    assert main.spreek_antwoord("Hallo.", stroom) is True
    assert gesproken == []


def test_spreek_antwoord_negeert_lege_antwoorden(monkeypatch):
    gesproken = []
    monkeypatch.setattr(main, "speak", gesproken.append)

    assert main.spreek_antwoord("") is False
    assert main.spreek_antwoord(None) is False
    assert gesproken == []
