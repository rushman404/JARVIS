"""Fase 21, M1 — film-modus 2.0: tv aan, app, pc stil, terugzetten."""

import json
import os

import pytest

from core import filmmodus
from core.filmmodus import FilmModus, herken
from core.result_validation import ToolResult

TV = "media_player.lg_webos_tv"
KNOP = "button.wake_on_lan_tv"
BRONNEN = ["Disney+", "HDMI 1", "Live TV", "Netflix", "Prime Video", "YouTube"]


class NepHa:
    """Een tv die na ``aan_na`` keer vragen aan is."""

    def __init__(self, aan=False, bron=None, aan_na=2, select_werkt=True):
        self.aan = aan
        self.bron = bron
        self.aan_na = aan_na
        self.select_werkt = select_werkt
        self.diensten = []
        self._gedrukt = False
        self._gevraagd = 0

    def staten(self):
        return [
            {"entity_id": "media_player.spotify", "attributes": {"friendly_name": "Spotify"}},
            {"entity_id": TV, "attributes": {"friendly_name": "LG webOS TV"}},
            {"entity_id": "button.wake_on_lan_game_pc", "attributes": {"friendly_name": "Game-Pc"}},
            {"entity_id": KNOP, "attributes": {"friendly_name": "Tv"}},
        ]

    def staat(self, entity_id):
        if self._gedrukt and not self.aan:
            self._gevraagd += 1
            if self._gevraagd >= self.aan_na:
                self.aan = True
        attrs = {"source_list": BRONNEN if self.aan else []}
        if self.aan:
            attrs["source"] = self.bron
        return {"entity_id": entity_id, "state": "on" if self.aan else "off", "attributes": attrs}

    def dienst(self, domein, dienst, data):
        self.diensten.append((domein, dienst, dict(data)))
        if (domein, dienst) == ("button", "press"):
            self._gedrukt = True
        elif dienst == "select_source":
            if not self.select_werkt:
                return False
            self.bron = data["source"]
        elif dienst == "turn_off":
            self.aan = False
        return True


class NepPc:
    def __init__(self, discord_gedempt=False, spotify_speelt=True, offline=False):
        self.discord_gedempt = discord_gedempt
        self.spotify_speelt = spotify_speelt
        self.offline = offline
        self.aanroepen = []

    def __call__(self, tool, args):
        self.aanroepen.append((tool, dict(args)))
        if self.offline:
            return ToolResult(False, "weg", data={"fout_code": "niet_bereikbaar"},
                              error_kind="remote_mislukt")
        if tool == "audio_get_session_volume":
            # Zoals het van de game-pc terugkomt: genest in "resultaat".
            return ToolResult(True, "ok", data={"resultaat": {"data": {"muted": self.discord_gedempt}}})
        if tool == "audio_set_session_mute":
            self.discord_gedempt = args["muted"]
            return ToolResult(True, "ok")
        if tool == "media_pause_app":
            was = self.spotify_speelt
            self.spotify_speelt = False
            return ToolResult(True, "ok", data={"gepauzeerd": was})
        raise AssertionError(tool)


def _film(tmp_path, ha=None, pc=None):
    return FilmModus(ha=ha or NepHa(), pc_tool=pc or NepPc(),
                     toestand_pad=str(tmp_path / "film.json"), slaap=lambda s: None)


# -----------------------------------------------------------------
# Herkennen
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,verwacht", [
    ("zet netflix op de tv", ("start", "netflix")),
    ("JARVIS, zet Disney plus op de tv", ("start", "disney")),
    ("zet de tv op disney+", ("start", "disney")),
    ("ik ga een film kijken op prime video", ("start", "prime")),
    ("ik wil youtube kijken", ("start", "youtube")),
    ("filmavond met netflix", ("start", "netflix")),
    ("film klaar", ("stop", None)),
    ("de film is afgelopen", ("stop", None)),
    ("einde film", ("stop", None)),
    ("zet filmmodus uit", ("stop", None)),
])
def test_herkent(zin, verwacht):
    assert herken(zin) == verwacht


@pytest.mark.parametrize("zin", ["open netflix", "wat is netflix?", "hoe lang duurt de film",
                                 "filmavond", "zet de lamp aan"])
def test_herkent_niet(zin):
    # "open netflix" blijft de pc; "filmavond" loopt via de routine movie.
    assert herken(zin) is None


# -----------------------------------------------------------------
# Start
# -----------------------------------------------------------------

def test_start_tv_uit(tmp_path):
    ha, pc, gezegd = NepHa(), NepPc(), []
    antwoord = _film(tmp_path, ha, pc).start("disney", vertel=gezegd.append)
    assert antwoord == ("Tv wordt geactiveerd. Disney+ geladen. Discord gedempt. "
                        "Muziek gepauzeerd. Geniet van de film, sir.")
    # Live verteld, zin voor zin (met spatie zodat de spraak per zin kan).
    assert gezegd[0] == "Tv wordt geactiveerd. " and len(gezegd) == 5
    assert ha.diensten[0] == ("button", "press", {"entity_id": KNOP})
    assert ("media_player", "select_source", {"entity_id": TV, "source": "Disney+"}) in ha.diensten
    # Nooit iets met licht of gordijnen.
    assert not [d for d in ha.diensten if d[0] in ("light", "cover", "scene")]
    toestand = json.load(open(tmp_path / "film.json", encoding="utf-8"))
    assert toestand["tv_was_aan"] is False and toestand["discord_gedempt"] is True


def test_start_standaard_netflix_tv_al_aan(tmp_path):
    ha = NepHa(aan=True, bron="Live TV")
    antwoord = _film(tmp_path, ha).start()
    assert antwoord.startswith("Netflix geladen.")
    assert ("button", "press", {"entity_id": KNOP}) not in ha.diensten
    toestand = json.load(open(tmp_path / "film.json", encoding="utf-8"))
    assert toestand["tv_was_aan"] is True and toestand["bron"] == "Live TV"


def test_discord_al_gedempt_en_spotify_speelt_niet(tmp_path):
    pc = NepPc(discord_gedempt=True, spotify_speelt=False)
    antwoord = _film(tmp_path, NepHa(aan=True), pc).start()
    assert antwoord == "Netflix geladen. Geniet van de film, sir."
    assert ("audio_set_session_mute", {"app_name": "Discord", "muted": True}) not in pc.aanroepen
    # Na de film blijft Discord dus ook gedempt (zoals het was).
    assert json.load(open(tmp_path / "film.json", encoding="utf-8"))["discord_gedempt"] is False


def test_game_pc_offline(tmp_path):
    antwoord = _film(tmp_path, NepHa(aan=True), NepPc(offline=True)).start()
    assert "De game-pc is niet bereikbaar; die sla ik over." in antwoord
    assert antwoord.endswith("Geniet van de film, sir.")


def test_tv_reageert_niet(tmp_path, monkeypatch):
    monkeypatch.setattr(filmmodus, "TV_AAN_SECONDEN", 0)
    ha = NepHa(aan_na=10 ** 6)
    pc = NepPc()
    antwoord = _film(tmp_path, ha, pc).start()
    assert antwoord == "Tv wordt geactiveerd. De tv reageert niet, sir."
    assert pc.aanroepen == []


def test_app_opent_niet(tmp_path):
    antwoord = _film(tmp_path, NepHa(aan=True, select_werkt=False)).start("youtube")
    assert "YouTube kon ik niet openen op de tv." in antwoord


def test_tweede_start_houdt_de_eerste_toestand(tmp_path):
    ha = NepHa(aan=True, bron="Live TV")
    film = _film(tmp_path, ha)
    film.start("netflix")
    film.start("youtube")
    toestand = json.load(open(tmp_path / "film.json", encoding="utf-8"))
    assert toestand["bron"] == "Live TV" and toestand["discord_gedempt"] is True


def test_tv_zoeken_in_ha(tmp_path):
    film = _film(tmp_path)
    assert film._zoek_tv() == (TV, KNOP)


# -----------------------------------------------------------------
# Stop
# -----------------------------------------------------------------

def test_stop_zet_alles_terug_tv_was_uit(tmp_path):
    ha, pc = NepHa(), NepPc()
    film = _film(tmp_path, ha, pc)
    film.start()
    gezegd = []
    antwoord = film.stop(vertel=gezegd.append)
    assert antwoord == ("Film-modus wordt afgesloten. Discord staat weer aan. Tv uit. "
                        "Alles staat weer zoals het was, sir.")
    assert pc.discord_gedempt is False and ha.aan is False
    # Spotify gaat bewust niet vanzelf verder.
    assert pc.spotify_speelt is False
    assert not os.path.exists(tmp_path / "film.json")
    assert len(gezegd) == 4


def test_stop_tv_was_aan_terug_naar_bron(tmp_path):
    ha = NepHa(aan=True, bron="Live TV")
    film = _film(tmp_path, ha, NepPc(discord_gedempt=True))
    film.start("prime")
    antwoord = film.stop()
    assert antwoord == "Film-modus wordt afgesloten. Tv terug naar Live TV. Alles staat weer zoals het was, sir."
    assert ha.aan is True and ha.bron == "Live TV"


def test_stop_zonder_film(tmp_path):
    assert _film(tmp_path).stop() == "De film-modus staat niet aan, sir."


# -----------------------------------------------------------------
# Koppeling: brein, routine, pc-tool
# -----------------------------------------------------------------

def test_routine_movie_is_de_film_modus():
    pad = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "routines.json")
    movie = json.load(open(pad, encoding="utf-8"))["movie"]
    assert movie["soort"] == "film" and movie["steps"] == []
    assert "\\bfilmavond\\b" in movie["triggers"]


def test_brein_routeert_naar_film(monkeypatch):
    from core import brain

    gezien = []

    class Nep:
        def start(self, dienst=None, vertel=None):
            gezien.append(("start", dienst, vertel))
            return "film gestart"

        def stop(self, vertel=None):
            gezien.append(("stop", None, vertel))
            return "film gestopt"

    monkeypatch.setattr(filmmodus, "_film", Nep())
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda naam: None)
    assert brain.process_command("zet disney plus op de tv") == "film gestart"
    assert brain.process_command("film klaar") == "film gestopt"
    assert brain.process_command("filmavond") == "film gestart"
    assert [g[:2] for g in gezien] == [("start", "disney"), ("stop", None), ("start", None)]


def test_pauzeer_app_alleen_als_spotify_speelt():
    from actions.media import pauzeer_app

    titels = {"t": "Daft Punk - One More Time"}
    gestuurd = []

    def vensters(naam):
        return [(42, titels["t"])]

    def stuur(hwnd):
        gestuurd.append(hwnd)
        titels["t"] = "Spotify Premium"

    r = pauzeer_app("Spotify", vensters_fn=vensters, stuur_fn=stuur, wacht=0)
    assert r.ok and r.data["gepauzeerd"] is True and gestuurd == [42]
    # Speelt niet: niets sturen (de toets zou de muziek juist starten).
    r = pauzeer_app("Spotify", vensters_fn=vensters, stuur_fn=stuur, wacht=0)
    assert r.ok and r.data == {"gepauzeerd": False, "reden": "speelde_niet"} and gestuurd == [42]
    r = pauzeer_app("Spotify", vensters_fn=lambda n: [], stuur_fn=stuur, wacht=0)
    assert r.data["reden"] == "niet_open"


def test_pauzeer_app_op_de_game_pc_toegestaan():
    from core.tool_registry import get_tool_risk
    from remote import allowlist

    assert allowlist.validate_call("media_pause_app", {"app_name": "Spotify"})[0] == {"app_name": "Spotify"}
    assert allowlist.is_allowed_in_profiel("media_pause_app", allowlist.PROFIEL_BASIS)
    assert get_tool_risk("media_pause_app", {}) == "low"
    assert get_tool_risk("game_pc_media_pause_app", {}) == "low"


def test_toestand_niet_in_git():
    pad = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".gitignore")
    assert "memory/film_toestand.json" in open(pad, encoding="utf-8").read()
