""""Zet de muziek zachter/harder" past het volume van de muziek-app aan,
niet het hoofdvolume.

Live tests Fase 24:
* 2026-10-29: de verkeerde output werd zachter (het hoofdvolume).
* 2026-10-30: "soms kan hij Spotify niet zien, anders doet hij het
  hoofdgeluid". Nu eerst Spotify zelf (Web API), dan Windows op het
  huidige doel, dan op de andere pc; nooit meer het hoofdvolume.
"""

import pytest

import core.brain as brain
from core import pc_target, spotify_smaak
from core.result_validation import ToolResult


class Pcs:
    """Nep-laptop en nep-game-pc met elk (misschien) een Spotify-sessie."""

    def __init__(self):
        self.game_pc = {"volume": 60, "speelt": True}
        self.laptop = {"volume": 30, "speelt": False}
        self.web_api = None  # None = Web API kan het niet; anders het volume
        self.aanroepen = []
        self.hoofd = []

    def execute_tool(self, tool, args, vraag):
        self.aanroepen.append((tool, dict(args)))
        if tool == "game_pc_audio_get_session_volume":
            if not self.game_pc["speelt"]:
                return ToolResult(ok=False, message="Geen audio-session.")
            return ToolResult(ok=True, message="", data={"volume": self.game_pc["volume"]})
        if tool == "game_pc_audio_set_session_volume":
            self.game_pc["volume"] = args["volume"]
            return ToolResult(ok=True, message="gezet")
        if tool == "game_pc_media":
            self.hoofd.append(("game_pc", args["action"]))
            return f"hoofdvolume {args['action']}"
        return ToolResult(ok=True, message="gezet")

    def get(self, app):
        if not self.laptop["speelt"]:
            return ToolResult(ok=False, message="Geen audio-session.")
        return ToolResult(ok=True, message="", data={"volume": self.laptop["volume"]})

    def set_(self, app, procent):
        self.aanroepen.append(("laptop_set", {"app_name": app, "volume": procent}))
        self.laptop["volume"] = procent
        return ToolResult(ok=True, message="gezet")

    def volume_stap(self, stap, klant=None):
        if self.web_api is None:
            return None
        self.web_api = max(0, min(100, self.web_api + stap))
        return self.web_api


@pytest.fixture
def pcs(monkeypatch):
    p = Pcs()
    monkeypatch.setattr(brain, "execute_tool", p.execute_tool)
    monkeypatch.setattr(brain, "audio_get_session_volume", p.get)
    monkeypatch.setattr(brain, "audio_set_session_volume", p.set_)
    monkeypatch.setattr(brain, "volume_down", lambda *a, **k: p.hoofd.append(("laptop", "omlaag")) or "hoofdvolume omlaag")
    monkeypatch.setattr(brain, "volume_up", lambda *a, **k: p.hoofd.append(("laptop", "omhoog")) or "hoofdvolume omhoog")
    monkeypatch.setattr(spotify_smaak, "volume_stap", p.volume_stap)
    monkeypatch.setattr(brain, "ask_ai", lambda command, **_kw: "AI-antwoord")
    return p


@pytest.fixture
def doel_game_pc(monkeypatch):
    monkeypatch.setattr(pc_target, "is_remote", lambda command: True)


@pytest.fixture
def doel_laptop(monkeypatch):
    monkeypatch.setattr(pc_target, "is_remote", lambda command: False)


# ---------------------------------------------------------------------
# Spotify Web API eerst
# ---------------------------------------------------------------------

def test_web_api_gaat_voor(pcs, doel_game_pc):
    pcs.web_api = 40
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 30%."
    assert pcs.web_api == 30
    assert pcs.game_pc["volume"] == 60  # Windows-sessie niet aangeraakt
    assert pcs.hoofd == []


def test_web_api_ook_met_doel_laptop(pcs, doel_laptop):
    # Spotify speelt op de game-pc, JARVIS kijkt naar de laptop: via de
    # Web API maakt dat niet uit.
    pcs.web_api = 40
    assert brain.process_command("zet de muziek harder") == "Spotify harder, nu op 50%."


# ---------------------------------------------------------------------
# Windows-sessie: eerst het doel, dan de andere pc
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin, verwacht, volume", [
    ("zet de muziek zachter", "Spotify zachter, nu op 50%.", 50),
    ("zet de muziek harder", "Spotify harder, nu op 70%.", 70),
    ("maak de muziek stiller", "Spotify zachter, nu op 50%.", 50),
    ("zet het liedje harder", "Spotify harder, nu op 70%.", 70),
])
def test_sessie_op_game_pc(pcs, doel_game_pc, zin, verwacht, volume):
    assert brain.process_command(zin) == verwacht
    assert pcs.game_pc["volume"] == volume
    assert pcs.hoofd == []


def test_doel_laptop_maar_spotify_op_game_pc(pcs, doel_laptop):
    # Dit ging "soms" mis: op de laptop speelt niets.
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 50%."
    assert pcs.game_pc["volume"] == 50
    assert pcs.hoofd == []


def test_doel_game_pc_maar_spotify_op_laptop(pcs, doel_game_pc):
    pcs.game_pc["speelt"] = False
    pcs.laptop["speelt"] = True
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 20%."
    assert pcs.laptop["volume"] == 20
    assert pcs.hoofd == []


def test_doel_laptop_speelt_op_laptop(pcs, doel_laptop):
    pcs.laptop["speelt"] = True
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 20%."
    # De game-pc hoeft dan niet gevraagd te worden.
    assert not any(t.startswith("game_pc_audio") for t, _a in pcs.aanroepen)


def test_muziek_typfout_ook_spotify(pcs, doel_game_pc):
    antwoord = brain.process_command("zet de muziek zachtr")
    assert antwoord == "Ik nam aan dat u 'zet de muziek zachter' bedoelde. Spotify zachter, nu op 50%."


def test_grenzen(pcs, doel_game_pc):
    pcs.game_pc["volume"] = 5
    assert brain.process_command("zet de muziek zachter") == "Spotify zachter, nu op 0%."
    pcs.game_pc["volume"] = 95
    assert brain.process_command("zet de muziek harder") == "Spotify harder, nu op 100%."


# ---------------------------------------------------------------------
# Nooit meer het hoofdvolume
# ---------------------------------------------------------------------

@pytest.mark.parametrize("doel", ["doel_game_pc", "doel_laptop"])
def test_nergens_gevonden_laat_hoofdvolume_met_rust(pcs, doel, request):
    request.getfixturevalue(doel)
    pcs.game_pc["speelt"] = False
    antwoord = brain.process_command("zet de muziek zachter")
    assert antwoord.startswith("Ik kan Spotify nu niet vinden, sir")
    assert "zet het volume zachter" in antwoord
    assert pcs.hoofd == []


def test_volume_zachter_blijft_hoofdvolume(pcs, doel_game_pc):
    assert brain.process_command("zet het volume zachter") == "hoofdvolume volume_down"
    assert not any(t == "game_pc_audio_set_session_volume" for t, _a in pcs.aanroepen)


def test_andere_app_blijft_werken(pcs, doel_game_pc):
    brain.process_command("maak discord zachter")
    assert ("game_pc_audio_set_session_volume", {"app_name": "discord", "volume": 50}) in pcs.aanroepen


def test_andere_muziek_app_via_config_slaat_web_api_over(pcs, doel_laptop, monkeypatch):
    monkeypatch.setattr(brain, "MUZIEK_APP", "Tidal")
    pcs.web_api = 40
    pcs.laptop["speelt"] = True
    assert brain.process_command("zet de muziek zachter") == "Tidal zachter, nu op 20%."
    assert pcs.web_api == 40


# ---------------------------------------------------------------------
# spotify_smaak.volume_stap (de Web API zelf)
# ---------------------------------------------------------------------

class Klant:
    def __init__(self, speler=None, gekoppeld=True, afspelen=True, fout_bij_put=None):
        self.speler = speler
        self.gekoppeld = gekoppeld
        self.afspelen = afspelen
        self.fout_bij_put = fout_bij_put
        self.puts = []

    def is_gekoppeld(self):
        return self.gekoppeld

    def mag_afspelen(self):
        return self.afspelen

    def get(self, pad, params=None):
        assert pad == "/me/player"
        return self.speler or {}

    def put(self, pad, params=None, body=None):
        if self.fout_bij_put:
            raise self.fout_bij_put
        self.puts.append((pad, params))


def test_volume_stap_web_api():
    klant = Klant({"device": {"id": "pc1", "volume_percent": 55, "supports_volume": True}})
    assert spotify_smaak.volume_stap(-10, klant=klant) == 45
    assert klant.puts == [("/me/player/volume", {"volume_percent": 45, "device_id": "pc1"})]


@pytest.mark.parametrize("klant", [
    Klant(gekoppeld=False),
    Klant(afspelen=False),
    Klant({}),                                                           # niets actief
    Klant({"device": {"id": "tv", "supports_volume": False, "volume_percent": 50}}),
    Klant({"device": {"id": "pc1", "volume_percent": None}}),
    Klant({"device": {"id": "pc1", "volume_percent": 50}},
          fout_bij_put=spotify_smaak.SpotifyFout("geen Premium", 403)),
])
def test_volume_stap_kan_niet(klant):
    assert spotify_smaak.volume_stap(10, klant=klant) is None


def test_volume_stap_grenzen():
    klant = Klant({"device": {"id": "pc1", "volume_percent": 97}})
    assert spotify_smaak.volume_stap(10, klant=klant) == 100
