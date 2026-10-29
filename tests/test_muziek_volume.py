""""Zet de muziek zachter/harder" past het volume van de muziek-app aan,
niet het hoofdvolume (live test Fase 24, 2026-10-29: de verkeerde output
werd zachter)."""

import pytest

import core.brain as brain
from core import pc_target
from core.result_validation import ToolResult


@pytest.fixture
def game_pc(monkeypatch):
    staat = {"volume": 60, "speelt": True, "aanroepen": []}

    def execute_tool(tool, args, vraag):
        staat["aanroepen"].append((tool, dict(args)))
        if tool == "game_pc_audio_get_session_volume":
            if not staat["speelt"]:
                return ToolResult(ok=False, message="Spotify maakt geen geluid.")
            return ToolResult(ok=True, message="", data={"volume": staat["volume"]})
        if tool == "game_pc_audio_set_session_volume":
            staat["volume"] = args["volume"]
            return ToolResult(ok=True, message="gezet")
        if tool == "game_pc_media":
            return f"hoofdvolume {args['action']}"
        return "?"

    monkeypatch.setattr(pc_target, "is_remote", lambda command: True)
    monkeypatch.setattr(brain, "execute_tool", execute_tool)
    monkeypatch.setattr(brain, "ask_ai", lambda command, **_kw: "AI-antwoord")
    return staat


@pytest.fixture
def lokaal(monkeypatch):
    staat = {"volume": 30, "speelt": True, "gezet": [], "hoofd": []}

    def get(app):
        if not staat["speelt"]:
            return ToolResult(ok=False, message=f"{app} maakt geen geluid.")
        return ToolResult(ok=True, message="", data={"volume": staat["volume"]})

    def set_(app, procent):
        staat["gezet"].append((app, procent))
        staat["volume"] = procent
        return ToolResult(ok=True, message="gezet")

    monkeypatch.setattr(pc_target, "is_remote", lambda command: False)
    monkeypatch.setattr(brain, "audio_get_session_volume", get)
    monkeypatch.setattr(brain, "audio_set_session_volume", set_)
    monkeypatch.setattr(brain, "volume_down", lambda *a, **k: staat["hoofd"].append("omlaag") or "hoofdvolume omlaag")
    monkeypatch.setattr(brain, "volume_up", lambda *a, **k: staat["hoofd"].append("omhoog") or "hoofdvolume omhoog")
    monkeypatch.setattr(brain, "ask_ai", lambda command, **_kw: "AI-antwoord")
    return staat


@pytest.mark.parametrize("zin, verwacht, volume", [
    ("zet de muziek zachter", "Spotify zachter, nu op 50%.", 50),
    ("zet de muziek harder", "Spotify harder, nu op 70%.", 70),
    ("maak de muziek stiller", "Spotify zachter, nu op 50%.", 50),
    ("zet het liedje harder", "Spotify harder, nu op 70%.", 70),
])
def test_muziek_op_game_pc_alleen_spotify(game_pc, zin, verwacht, volume):
    assert brain.process_command(zin) == verwacht
    assert game_pc["volume"] == volume
    assert ("game_pc_audio_set_session_volume", {"app_name": "Spotify", "volume": volume}) in game_pc["aanroepen"]
    assert not any(t == "game_pc_media" for t, _a in game_pc["aanroepen"])


def test_muziek_typfout_ook_spotify(game_pc):
    antwoord = brain.process_command("zet de muziek zachtr")
    assert antwoord == "Ik nam aan dat u 'zet de muziek zachter' bedoelde. Spotify zachter, nu op 50%."


def test_grenzen(game_pc):
    game_pc["volume"] = 5
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 0%."
    game_pc["volume"] = 95
    assert brain.process_command("zet de muziek harder") == "Spotify harder, nu op 100%."


def test_spotify_speelt_niet_dan_hoofdvolume(game_pc):
    game_pc["speelt"] = False
    assert brain.process_command("zet de muziek zachter") == "hoofdvolume volume_down"


def test_volume_zachter_blijft_hoofdvolume(game_pc):
    assert brain.process_command("zet het volume zachter") == "hoofdvolume volume_down"
    assert not any(t == "game_pc_audio_set_session_volume" for t, _a in game_pc["aanroepen"])


def test_andere_app_blijft_werken(game_pc):
    brain.process_command("maak discord zachter")
    assert ("game_pc_audio_set_session_volume", {"app_name": "discord", "volume": 50}) in game_pc["aanroepen"]


def test_muziek_lokaal_alleen_spotify(lokaal):
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 20%."
    assert lokaal["gezet"] == [("Spotify", 20)]
    assert lokaal["hoofd"] == []


def test_muziek_lokaal_terugval(lokaal):
    lokaal["speelt"] = False
    brain.process_command("zet de muziek harder")
    assert lokaal["gezet"] == []
    assert lokaal["hoofd"] == ["omhoog"]


def test_andere_muziek_app_via_config(lokaal, monkeypatch):
    monkeypatch.setattr(brain, "MUZIEK_APP", "Tidal")
    assert brain.process_command("zet de muziek zachter") == "Tidal zachter, nu op 20%."
    assert lokaal["gezet"] == [("Tidal", 20)]
