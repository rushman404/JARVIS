"""Dekking van Nederlandse formuleringen voor het volume (Fase 5 + Fase 15B).

De gebruiker zegt vaak "zet geluid op" in plaats van "volume omhoog".
Zonder deze patronen valt zo'n commando terug op de LLM, die dan alleen
*vertelt* dat het volume omhoog gaat in plaats van het écht te doen.

De test draait volledig met mocks: er wordt geen echt volume gewijzigd.
"""

import sys

import pytest

sys.path.insert(0, 'C:\\JARVIS')

import core.brain as brain


OMHOOG = [
    "zet geluid op",
    "zet het geluid op",
    "volume omhoog",
    "maak het geluid harder",
    "geluid harder",
    "zet volume hoger",
    "volume opzetten",
    "geluid opzetten",
    "zet geluid omhoog",
    "maak het geluid luid",
    "luider",
]

OMLAAG = [
    "zet geluid omlaag",
    "volume omlaag",
    "maak het geluid zachter",
    "geluid zachter",
    "zet volume lager",
    "geluid stil",
    "zachter",
]

DEMPEN = [
    "demp het geluid",
    "mute",
    "zet het geluid uit",
    "zet het geluid aan",
]

PROCENT = [
    "zet het volume op 30",
    "volume naar 50 procent",
]

NIET_MEDIA = [
    "wat is de tijd",
    "vertel een mop",
    "wie was Einstein",
]


@pytest.fixture
def lokaal(monkeypatch):
    """Lokale modus: het volume-commando raakt de lokale pc."""

    calls = []
    monkeypatch.setattr(brain.pc_target, "get_pc_target", lambda: "local")
    monkeypatch.setattr(
        brain, "volume_up", lambda *a, **k: calls.append("volume_up") or "Volume omhoog."
    )
    monkeypatch.setattr(
        brain, "volume_down", lambda *a, **k: calls.append("volume_down") or "Volume omlaag."
    )
    monkeypatch.setattr(
        brain, "toggle_mute", lambda *a, **k: calls.append("toggle_mute") or "Geluid gedempt."
    )
    monkeypatch.setattr(
        brain, "set_volume", lambda p: calls.append(("set_volume", p)) or f"Volume {p}%."
    )
    return calls


@pytest.fixture
def remote(monkeypatch):
    """Remote modus (PC_TARGET=game-pc): het commando gaat naar de agent."""

    calls = []
    monkeypatch.setattr(brain.pc_target, "get_pc_target", lambda: "game-pc")
    monkeypatch.setattr(
        brain,
        "execute_tool",
        lambda name, args, question=None: calls.append((name, args)) or "ok",
    )
    return calls


@pytest.mark.parametrize("zin", OMHOOG)
def test_volume_omhoog_lokaal(lokaal, zin):
    brain.try_media_command(zin)
    assert lokaal == ["volume_up"], f"{zin!r} werd niet als volume-omhoog herkend"


@pytest.mark.parametrize("zin", OMHOOG)
def test_volume_omhoog_remote(remote, zin):
    brain.try_media_command(zin)
    assert remote and remote[0][0] == "game_pc_media", (
        f"{zin!r} ging niet naar de game-pc-agent"
    )
    assert remote[0][1] == {"action": "volume_up"}


@pytest.mark.parametrize("zin", OMLAAG)
def test_volume_omlaag_lokaal(lokaal, zin):
    brain.try_media_command(zin)
    assert lokaal == ["volume_down"], f"{zin!r} werd niet als volume-omlaag herkend"


@pytest.mark.parametrize("zin", DEMPEN)
def test_dempen_blijft_dempen(lokaal, zin):
    brain.try_media_command(zin)
    assert lokaal == ["toggle_mute"], f"{zin!r} werd verkeerd als volume-omhoog gezien"


@pytest.mark.parametrize("zin", PROCENT)
def test_procent(lokaal, zin):
    brain.try_media_command(zin)
    assert lokaal and lokaal[0][0] == "set_volume", f"{zin!r} zette het volume niet"


@pytest.mark.parametrize("zin", NIET_MEDIA)
def test_geen_media(lokaal, zin):
    assert brain.try_media_command(zin) is None, f"{zin!r} is geen mediacommando"
