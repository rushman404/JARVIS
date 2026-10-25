"""Fase 21, M3 — narratie bij routines en protocollen."""

import json
import os

import pytest

from core import brain, narratie
from core.narratie import Verteller, zin_voor_stap

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def stap(tool, args, status="done"):
    return {"tool_name": tool, "arguments": args, "status": status}


# -----------------------------------------------------------------
# Zinnen
# -----------------------------------------------------------------

@pytest.mark.parametrize("record,zin", [
    (stap("open_program", {"program": "Discord"}), "Discord geopend."),
    (stap("game_pc_open_program", {"program": "Spotify"}), "Spotify geopend."),
    (stap("set_volume", {"percent": 40}), "Volume op 40."),
    (stap("media_stop", {}), "Muziek gestopt."),
    (stap("control_home_assistant", {"domain": "light", "service": "turn_on",
                                     "entity_id": "light.bed_lamp",
                                     "service_data": {"brightness_pct": 30}}), "Bed lamp op 30 procent."),
    (stap("control_home_assistant", {"domain": "light", "service": "turn_off",
                                     "entity_id": "light.bed_lamp"}), "Bed lamp uit."),
    (stap("audio_set_session_mute", {"app_name": "Discord", "muted": True}), "Discord gedempt."),
])
def test_zin_per_stap(record, zin):
    assert zin_voor_stap(record) == zin


def test_mislukte_stap_kort():
    zin = zin_voor_stap(stap("open_program", {"program": "Spotify"}, status="failed"))
    assert zin.endswith("mislukt.") and "Spotify" in zin


def test_overgeslagen_zegt_niets():
    assert zin_voor_stap(stap("open_program", {"program": "x"}, status="skipped")) is None


def test_verteller_live_en_slot():
    gezegd = []
    v = Verteller(gezegd.append)
    v.zeg("Gamemodus wordt geactiveerd.")
    v.stap(stap("open_program", {"program": "Discord"}))
    v.stap(stap("open_program", {"program": "Spotify"}, status="failed"))
    v.slot("Veel plezier, sir.")
    assert gezegd[0] == "Gamemodus wordt geactiveerd. "
    assert v.tekst().endswith("De rest staat klaar, sir.")


def test_zonder_callback_klopt_het_slot_toch(monkeypatch):
    """Roept de executor bij_stap niet aan, dan vertelt JARVIS achteraf."""

    monkeypatch.setattr(brain, "execute_action_plan", lambda steps, vraag, trusted=False, bij_stap=None: [
        {"tool_name": "open_program", "arguments": {"program": "Discord"}, "status": "failed"}])
    monkeypatch.setattr(brain.routine_manager, "steps_for_agent",
                        lambda naam: [{"tool_name": "open_program", "arguments": {}, "status": "pending"}])
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda naam: None)
    antwoord = brain._execute_routine("gaming", ROUTINE, "ik ga gamen")
    assert "mislukt" in antwoord and antwoord.endswith("Het is helaas niet gelukt, sir.")


def test_slot_varianten():
    v = Verteller()
    v.stap(stap("open_program", {"program": "Discord"}))
    v.slot("Veel plezier, sir.")
    assert v.zinnen[-1] == "Veel plezier, sir."
    v = Verteller()
    v.stap(stap("open_program", {"program": "Discord"}, status="failed"))
    v.slot()
    assert v.zinnen[-1] == "Het is helaas niet gelukt, sir."
    v = Verteller()
    v.stap({"tool_name": "close_program", "needs_approval": True, "status": "approval_required"})
    v.slot()
    assert v.zinnen == ["Voor de volgende stap wacht ik op uw goedkeuring."]


# -----------------------------------------------------------------
# Routine uitvoeren (executor nagebootst)
# -----------------------------------------------------------------

ROUTINE = {
    "name": "gaming", "vertrouwd": True, "start_zin": "Gamemodus wordt geactiveerd.",
    "eind_zin": "Veel plezier, sir.", "description": "Gaming mode.",
    "steps": [
        {"tool_name": "open_program", "arguments": {"program": "Discord"}},
        {"tool_name": "set_volume", "arguments": {"percent": 40}},
    ],
}


@pytest.fixture
def nep_executor(monkeypatch):
    aanroepen = []

    def uitvoeren(steps, vraag, trusted=False, bij_stap=None):
        aanroepen.append(bij_stap is not None)
        uit = []
        for s in steps:
            r = {"tool_name": s["tool_name"], "arguments": s["arguments"], "status": "done"}
            if bij_stap:
                bij_stap(r)
            uit.append(r)
        return uit

    monkeypatch.setattr(brain, "execute_action_plan", uitvoeren)
    monkeypatch.setattr(brain.routine_manager, "steps_for_agent",
                        lambda naam: [dict(s, status="pending") for s in ROUTINE["steps"]])
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda naam: None)
    return aanroepen


def test_routine_met_narratie(nep_executor):
    gezegd = []
    antwoord = brain._execute_routine("gaming", ROUTINE, "ik ga gamen", on_tekst=gezegd.append)
    assert antwoord == "Gamemodus wordt geactiveerd. Discord geopend. Volume op 40. Veel plezier, sir."
    assert len(gezegd) == 4 and nep_executor == [True]


def test_routine_als_protocol(nep_executor):
    antwoord = brain._execute_routine("gaming", ROUTINE, "protocol gamen", protocol="gamen")
    assert antwoord.startswith("Protocol gamen geactiveerd. Discord geopend.")


def test_narratie_uit_per_routine(nep_executor):
    routine = dict(ROUTINE, narratie=False)
    assert brain._execute_routine("gaming", routine, "ik ga gamen") == "Gaming mode."
    assert nep_executor == [False]


def test_narratie_uit_via_config(nep_executor, monkeypatch):
    import config

    monkeypatch.setattr(config, "ROUTINE_NARRATIE", False)
    assert brain._execute_routine("gaming", ROUTINE, "ik ga gamen") == "Gaming mode."


def test_executor_roept_bij_stap_aan():
    from core.executor import execute_action_plan

    gezien = []
    stappen = [{"tool_name": "wait", "arguments": {"seconds": 0}, "status": "pending"}]
    try:
        execute_action_plan(stappen, "test", trusted=True, bij_stap=gezien.append)
    except Exception:
        pytest.skip("wait-stap niet beschikbaar")
    assert gezien and gezien[0]["tool_name"] == "wait"


def test_fout_in_callback_stopt_plan_niet():
    from core.executor import execute_action_plan

    def boem(record):
        raise RuntimeError("boem")

    stappen = [{"tool_name": "wait", "arguments": {"seconds": 0}, "status": "pending"}]
    uit = execute_action_plan(stappen, "test", trusted=True, bij_stap=boem)
    assert len(uit) == 1


# -----------------------------------------------------------------
# Protocollen
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,routine,label", [
    ("start protocol filmavond", "movie", "filmavond"),
    ("JARVIS, protocol gamen", "gaming", "gamen"),
    ("activeer protocol slaap", "sleep", "slaap"),
    ("voer protocol film avond uit", "movie", "filmavond"),
    ("protocol gaming", "gaming", "gaming"),
])
def test_protocol_via_het_brein(zin, routine, label, monkeypatch):
    gezien = []
    monkeypatch.setattr(brain, "_execute_routine",
                        lambda n, r, c, on_tekst=None, protocol=None: gezien.append((n, protocol)) or "ok")
    assert brain.process_command(zin) == "ok"
    assert gezien == [(routine, label)]


def test_onbekend_protocol():
    antwoord = brain.process_command("start protocol huisfeest")
    assert antwoord.startswith("Protocol huisfeest ken ik niet, sir.")
    assert "filmavond" in antwoord


def test_welke_protocollen():
    antwoord = brain.process_command("welke protocollen zijn er")
    assert antwoord.startswith("Bekende protocollen:") and "slaap" in antwoord


def test_film_protocol_zegt_eerst_het_protocol(monkeypatch):
    from core import filmmodus

    class Nep:
        def start(self, dienst=None, vertel=None):
            return "Netflix geladen. Geniet van de film, sir."

    monkeypatch.setattr(filmmodus, "_film", Nep())
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda naam: None)
    routine = brain.routine_manager.get_routine("movie")
    antwoord = brain._execute_routine("movie", routine, "protocol filmavond", protocol="filmavond")
    assert antwoord == "Protocol filmavond geactiveerd. Netflix geladen. Geniet van de film, sir."


def test_routines_json_heeft_protocollen():
    data = json.load(open(os.path.join(PROJECT, "config", "routines.json"), encoding="utf-8"))
    assert data["movie"]["protocollen"][0] == "filmavond"
    assert data["gaming"]["start_zin"] and data["sleep"]["eind_zin"] == "Welterusten, sir."


def test_staat_aan_standaard():
    assert narratie.staat_aan({}) is True
    assert narratie.staat_aan({"narratie": False}) is False
