"""Fase 21, M6 — games starten met de stem (Steam, Riot, Wake-on-LAN)."""

import json
import os

import pytest

from actions import games as ag
from core import games_stem
from core.games_stem import GameStarter
from core.result_validation import ToolResult

GAMES = [
    {"naam": "Assetto Corsa", "id": "steam:244210"},
    {"naam": "BeamNG.drive", "id": "steam:284160"},
    {"naam": "Taxi Life: A City Driving Simulator", "id": "steam:1351240"},
    {"naam": "VALORANT", "id": "riot:valorant"},
    {"naam": "League of Legends", "id": "riot:league_of_legends"},
]


# -----------------------------------------------------------------
# Bibliotheek lezen (agent-kant)
# -----------------------------------------------------------------

def test_steam_bibliotheek(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    tweede = tmp_path / "D" / "SteamLibrary"
    (tweede / "steamapps").mkdir(parents=True)
    pad = str(tweede).replace("\\", "\\\\")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "0" {{ "path" "{str(steam).replace(chr(92), chr(92) * 2)}" }}\n'
        f' "1" {{ "path" "{pad}" }}\n}}\n', encoding="utf-8")
    (steam / "steamapps" / "appmanifest_284160.acf").write_text(
        '"AppState"\n{\n "appid" "284160"\n "name" "BeamNG.drive"\n}\n', encoding="utf-8")
    (tweede / "steamapps" / "appmanifest_244210.acf").write_text(
        '"AppState"\n{\n "appid" "244210"\n "name" "Assetto Corsa"\n}\n', encoding="utf-8")
    (tweede / "steamapps" / "appmanifest_228980.acf").write_text(
        '"AppState"\n{\n "appid" "228980"\n "name" "Steamworks Common Redistributables"\n}\n',
        encoding="utf-8")
    assert ag.steam_games(str(steam)) == [
        {"naam": "Assetto Corsa", "id": "steam:244210"},
        {"naam": "BeamNG.drive", "id": "steam:284160"},
    ]


def test_riot_games(tmp_path):
    rc = tmp_path / "RiotClientServices.exe"
    rc.write_text("x")
    (tmp_path / "RiotClientInstalls.json").write_text(json.dumps({"rc_default": str(rc)}), encoding="utf-8")
    (tmp_path / "Metadata" / "valorant.live").mkdir(parents=True)
    assert ag.riot_games(str(tmp_path)) == [{"naam": "VALORANT", "id": "riot:valorant"}]
    assert ag.riot_games(str(tmp_path / "leeg")) == []


@pytest.mark.parametrize("gezegd,naam", [
    ("valorant", "VALORANT"),
    ("beamng", "BeamNG.drive"),
    ("beam ng drive", "BeamNG.drive"),
    ("taxi life", "Taxi Life: A City Driving Simulator"),
    ("assetto", "Assetto Corsa"),
    ("asseto corsa", "Assetto Corsa"),
    ("league", "League of Legends"),
])
def test_zoek_game(gezegd, naam):
    assert ag.zoek_game(gezegd, GAMES)["naam"] == naam


@pytest.mark.parametrize("gezegd", ["spotify", "discord", "netflix", "de film", "muziek", "chrome"])
def test_geen_game(gezegd):
    assert ag.zoek_game(gezegd, GAMES) is None


def test_start_alleen_eigen_ids():
    geopend, gestart = [], []
    r = ag.start_game("steam:284160", GAMES, openen=geopend.append)
    assert r.ok and geopend == ["steam://rungameid/284160"]
    r = ag.start_game("riot:valorant", GAMES, starten=gestart.append, rc="C:/Riot/RiotClientServices.exe")
    assert r.ok and gestart == [["C:/Riot/RiotClientServices.exe", "--launch-product=valorant",
                                  "--launch-patchline=live"]]
    r = ag.start_game("steam:999", GAMES, openen=geopend.append)
    assert not r.ok and len(geopend) == 1


def test_game_acties_op_de_game_pc():
    from core.tool_registry import get_tool_risk
    from remote import allowlist

    assert allowlist.validate_call("game_start", {"game_id": "steam:284160"})[0] == {"game_id": "steam:284160"}
    assert allowlist.validate_call("game_start", {"game_id": "riot:valorant"})[0] is not None
    for slecht in ("C:\\Windows\\cmd.exe", "steam:12;calc", "riot:../x"):
        assert allowlist.validate_call("game_start", {"game_id": slecht})[0] is None, slecht
    assert allowlist.is_allowed_in_profiel("game_start", allowlist.PROFIEL_BASIS)
    assert get_tool_risk("game_pc_game_start", {}) == "low"


# -----------------------------------------------------------------
# Brein-kant
# -----------------------------------------------------------------

class NepHa:
    def __init__(self, werkt=True):
        self.werkt = werkt
        self.gedrukt = []

    def staten(self):
        return [{"entity_id": "button.wake_on_lan_tv", "attributes": {"friendly_name": "Tv"}},
                {"entity_id": "button.kamer_game_pc", "attributes": {"friendly_name": "Game-Pc"}}]

    def dienst(self, domein, dienst, data):
        self.gedrukt.append(data["entity_id"])
        return self.werkt


class NepPc:
    def __init__(self, games=GAMES):
        self.games = games
        self.aanroepen = []

    def __call__(self, tool, args):
        self.aanroepen.append((tool, dict(args)))
        if tool == "game_lijst":
            return ToolResult(True, "", data={"resultaat": {"data": {"games": self.games}}})
        if tool == "game_start":
            return ToolResult(True, "gestart")
        raise AssertionError(tool)


class Klok:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def slaap(self, s):
        self.t += s


def maak(tmp_path, online=True, pc=None, ha=None, meld=None, klok=None):
    klok = klok or Klok()
    staat = {"online": online}
    starter = GameStarter(pc_tool=pc or NepPc(), ha=ha or NepHa(),
                          online_fn=lambda: staat["online"], meld_fn=meld,
                          cache_pad=str(tmp_path / "games.json"), klok=klok,
                          slaap=klok.slaap, achtergrond=False)
    return starter, staat


def test_start_meteen_als_de_game_pc_aan_staat(tmp_path):
    pc = NepPc()
    starter, _ = maak(tmp_path, pc=pc)
    assert starter.start("valorant") == "VALORANT wordt gestart, sir."
    assert ("game_start", {"game_id": "riot:valorant"}) in pc.aanroepen
    assert json.load(open(tmp_path / "games.json", encoding="utf-8"))["games"] == GAMES


def test_geen_game_valt_door(tmp_path):
    starter, _ = maak(tmp_path)
    assert starter.start("spotify") is None


def test_lijst_uit_de_cache_zonder_nieuwe_aanvraag(tmp_path):
    pc = NepPc()
    starter, _ = maak(tmp_path, pc=pc)
    starter.start("valorant")
    starter.start("beamng")
    assert [a for a in pc.aanroepen if a[0] == "game_lijst"] == [("game_lijst", {})]


def test_game_pc_uit_wordt_gewekt(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "GAME_PC_AAN_KNOP", "")
    monkeypatch.setattr(config, "GAME_PC_OPSTART_SECONDEN", 60)
    (tmp_path / "games.json").write_text(json.dumps({"games": GAMES, "bijgewerkt": 1000}), encoding="utf-8")
    ha, pc, meldingen, klok = NepHa(), NepPc(), [], Klok()
    starter, staat = maak(tmp_path, online=False, pc=pc, ha=ha, meld=meldingen.append, klok=klok)

    orig = klok.slaap

    def slaap(s):
        orig(s)
        if klok.t >= 1020:
            staat["online"] = True  # na ±20 s is de agent er

    starter.slaap = slaap
    antwoord = starter.start("beam ng")
    assert antwoord == "De game-pc wordt opgestart, sir. Ik start BeamNG.drive zodra hij er is."
    assert ha.gedrukt == ["button.kamer_game_pc"]
    assert meldingen == ["BeamNG.drive wordt gestart, sir. De game-pc is er."]
    assert ("game_start", {"game_id": "steam:284160"}) in pc.aanroepen


def test_game_pc_komt_niet_online(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "GAME_PC_OPSTART_SECONDEN", 30)
    (tmp_path / "games.json").write_text(json.dumps({"games": GAMES, "bijgewerkt": 1000}), encoding="utf-8")
    meldingen = []
    starter, _ = maak(tmp_path, online=False, meld=meldingen.append)
    starter.start("valorant")
    assert meldingen == ["De game-pc kwam niet online, sir. VALORANT heb ik niet gestart."]


def test_al_aan_het_wekken(tmp_path):
    (tmp_path / "games.json").write_text(json.dumps({"games": GAMES, "bijgewerkt": 1000}), encoding="utf-8")
    starter, _ = maak(tmp_path, online=False)
    starter._wekken.acquire()
    assert starter.start("valorant") == ("De game-pc is al aan het opstarten, sir. "
                                         "Ik start VALORANT zodra hij er is.")


def test_geen_wekknop(tmp_path):
    class Leeg(NepHa):
        def staten(self):
            return []

    (tmp_path / "games.json").write_text(json.dumps({"games": GAMES, "bijgewerkt": 1000}), encoding="utf-8")
    starter, _ = maak(tmp_path, online=False, ha=Leeg())
    assert starter.start("valorant").startswith("De game-pc staat uit en ik vind geen knop")


def test_welke_games(tmp_path):
    starter, _ = maak(tmp_path)
    assert starter.lijst().startswith("Op de game-pc staan 5 games: Assetto Corsa, BeamNG.drive")


@pytest.mark.parametrize("zin,naam", [
    ("start valorant", "valorant"),
    ("JARVIS, ik wil BeamNG spelen", "beamng"),
    ("laten we een potje league spelen", "league"),
    ("open assetto corsa op de game-pc", "assetto corsa"),
    ("start het spel taxi life", "taxi life"),
])
def test_brein_herkent(zin, naam, monkeypatch):
    gezien = []
    monkeypatch.setattr(games_stem, "_starter", type("N", (), {
        "start": lambda self, n: gezien.append(n) or "ok", "lijst": lambda self: "lijst"})())
    from core import brain

    assert brain.process_command(zin) == "ok"
    assert gezien == [naam]


def test_open_spotify_blijft_een_programma(monkeypatch):
    # Zonder bekende game gaat de zin gewoon door (conftest: geen games).
    assert games_stem.voer_uit("open spotify") is None


def test_cache_niet_in_git():
    tekst = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".gitignore"), encoding="utf-8").read()
    assert "memory/games.json" in tekst
