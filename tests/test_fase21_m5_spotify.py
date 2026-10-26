"""Fase 21, M5 — muzieksmaak via Spotify (alleen lezen)."""

import json
import os
import random
import urllib.parse

import pytest

from core import spotify_smaak as sp
from core.result_validation import ToolResult

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def uri(n, soort="track"):
    return f"spotify:{soort}:" + str(n).rjust(22, "A")


class Antwoord:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class NepHttp:
    """Nagebootste Spotify: tokens en de vijf leesverzoeken."""

    def __init__(self, status=200):
        self.status = status
        self.posts = []
        self.gets = []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, dict(data)))
        if self.status != 200:
            return Antwoord(self.status, {})
        antwoord = {"access_token": "AT-nieuw", "expires_in": 3600}
        if data.get("grant_type") == "authorization_code":
            antwoord["refresh_token"] = "RT-1"  # bij vernieuwen geeft Spotify er vaak geen
        return Antwoord(200, antwoord)

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append((url, dict(params or {}), headers))
        if self.status != 200:
            return Antwoord(self.status, {})
        pad = url.replace(sp.API, "")
        if pad == "/me/top/artists":
            kort = params["time_range"] == "short_term"
            return Antwoord(200, {"items": [
                {"name": "Daft Punk" if kort else "Queen", "genres": ["french house"]},
                {"name": "Avicii", "genres": ["edm"]},
                {"name": "Coldplay", "genres": ["pop"]},
            ]})
        if pad == "/me/top/tracks":
            return Antwoord(200, {"items": [
                {"name": "One More Time", "uri": uri(1), "artists": [{"name": "Daft Punk"}]},
                {"name": "Levels", "uri": uri(2), "artists": [{"name": "Avicii"}]},
            ]})
        if pad == "/me/player/recently-played":
            return Antwoord(200, {"items": [{"track": {"uri": uri(1)}}]})
        if pad == "/me/playlists":
            return Antwoord(200, {"items": [{"name": "Chill", "uri": uri(7, "playlist")},
                                            {"name": "Gaming Hype", "uri": uri(8, "playlist")}]})
        return Antwoord(404, {})


@pytest.fixture
def paden(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "SPOTIFY_CLIENT_ID", "client-123")
    token = tmp_path / "token.json"
    smaak = tmp_path / "smaak.json"
    monkeypatch.setattr(sp, "TOKEN_FILE", str(token))
    monkeypatch.setattr(sp, "SMAAK_FILE", str(smaak))
    return token, smaak


def koppel(token, verloopt=10 ** 12):
    token.write_text(json.dumps({"access_token": "AT", "refresh_token": "RT", "verloopt": verloopt}),
                     encoding="utf-8")


# -----------------------------------------------------------------
# PKCE en tokens
# -----------------------------------------------------------------

def test_pkce_challenge_is_s256():
    import base64
    import hashlib

    v = sp.maak_verifier()
    assert 43 <= len(v) <= 128
    verwacht = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert sp.challenge(v) == verwacht and "=" not in sp.challenge(v)


def test_autorisatie_url_alleen_lezen_en_geen_geheim():
    url = sp.autorisatie_url("client-123", "v" * 64, "staat", "http://127.0.0.1:8888/callback")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["scope"] == ["user-top-read user-read-recently-played playlist-read-private "
                          "user-read-playback-state user-modify-playback-state"]
    assert q["code_challenge_method"] == ["S256"] and q["state"] == ["staat"]
    assert "client_secret" not in url


def test_code_wisselen_slaat_tokens_op(paden):
    token, _ = paden
    http = NepHttp()
    sp.wissel_code("CODE", "VERIFIER", "client-123", "http://127.0.0.1:8888/callback",
                   pad=str(token), http=http, klok=lambda: 1000)
    data = json.loads(token.read_text(encoding="utf-8"))
    assert data["refresh_token"] == "RT-1" and data["verloopt"] == 4600
    assert http.posts[0][1]["code_verifier"] == "VERIFIER"


def test_token_wordt_vernieuwd_en_refresh_blijft(paden):
    token, _ = paden
    koppel(token, verloopt=0)
    http = NepHttp()
    klant = sp.SpotifyKlant(pad=str(token), http=http, klok=lambda: 5000)
    klant.get("/me/playlists")
    data = json.loads(token.read_text(encoding="utf-8"))
    assert data["access_token"] == "AT-nieuw" and data["refresh_token"] == "RT"
    assert http.gets[0][2] == {"Authorization": "Bearer AT-nieuw"}


def test_fout_noemt_nooit_het_token(paden):
    token, _ = paden
    koppel(token, verloopt=0)
    with pytest.raises(sp.SpotifyFout) as fout:
        sp.SpotifyKlant(pad=str(token), http=NepHttp(status=400)).get("/me/playlists")
    assert "RT" not in str(fout.value) and "AT" not in str(fout.value)


def test_niet_gekoppeld(paden):
    assert sp.SpotifyKlant().is_gekoppeld() is False
    assert sp.voer_uit("stel muziek voor") == sp.NIET_GEKOPPELD


# -----------------------------------------------------------------
# Profiel en kiezen
# -----------------------------------------------------------------

def test_profiel_en_cache(paden):
    token, smaak = paden
    koppel(token)
    http = NepHttp()
    klant = sp.SpotifyKlant(pad=str(token), http=http)
    prof = sp.profiel(klant, pad=str(smaak), klok=lambda: 100)
    assert prof["artiesten_kort"][0] == "Daft Punk" and prof["recent"] == [uri(1)]
    assert prof["genres"][0] in ("french house", "edm", "pop")
    aantal = len(http.gets)
    prof["bijgewerkt"] = 100
    smaak.write_text(json.dumps(prof), encoding="utf-8")
    sp.profiel(klant, pad=str(smaak), klok=lambda: 200)
    assert len(http.gets) == aantal, "binnen 6 uur uit de cache"


def test_oud_profiel_als_spotify_weg_is(paden):
    token, smaak = paden
    koppel(token)
    smaak.write_text(json.dumps({"bijgewerkt": 0, "artiesten": ["Queen"]}), encoding="utf-8")
    klant = sp.SpotifyKlant(pad=str(token), http=NepHttp(status=500))
    assert sp.profiel(klant, pad=str(smaak), klok=lambda: 10 ** 9)["artiesten"] == ["Queen"]


PROF = {
    "artiesten_kort": ["Daft Punk", "Avicii", "Coldplay", "Muse"],
    "nummers_kort": [{"naam": "One More Time", "artiest": "Daft Punk", "uri": uri(1)},
                     {"naam": "Levels", "artiest": "Avicii", "uri": uri(2)}],
    "nummers": [{"naam": "Yellow", "artiest": "Coldplay", "uri": uri(3)}],
    "recent": [uri(1)],
    "playlists": [{"naam": "Chill", "uri": uri(7, "playlist")},
                  {"naam": "Gaming Hype", "uri": uri(8, "playlist")}],
    "genres": ["edm", "pop"],
}


def test_kies_nummer_niet_wat_net_speelde():
    gekozen = {sp.kies_nummer(PROF, random.Random(i))["uri"] for i in range(40)}
    assert uri(1) not in gekozen and gekozen == {uri(2), uri(3)}


def test_kies_voor_gamemodus_eigen_playlist():
    keuze = sp.kies_voor_modus(PROF, "gaming", random.Random(1))
    assert keuze["playlist"] and keuze["naam"] == "Gaming Hype"
    assert sp.label(keuze) == "uw playlist 'Gaming Hype'"


def test_smaak_beschrijven():
    assert sp.beschrijf_smaak(PROF) == ("De laatste tijd luistert u vooral naar Daft Punk, Avicii "
                                        "en Coldplay. Vooral edm, pop.")


# -----------------------------------------------------------------
# Opdrachten
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,soort", [
    ("zet iets op wat ik leuk vind", "speel"),
    ("JARVIS, speel iets dat ik leuk vind", "speel"),
    ("verras me met muziek", "speel"),
    ("stel muziek voor", "voorstel"),
    ("heb je een muziektip?", "voorstel"),
    ("wat zal ik luisteren", "voorstel"),
    ("wat is mijn muzieksmaak", "smaak"),
    ("naar wie luister ik het meest", "smaak"),
])
def test_herkent(zin, soort):
    assert sp.herken(zin) == soort


@pytest.mark.parametrize("zin", ["open spotify", "speel muziek", "volgende nummer", "pauze"])
def test_herkent_niet(zin):
    # Gewone mediabediening blijft zoals hij was.
    assert sp.herken(zin) is None


class Klant:
    """Gekoppeld, maar (nog) zonder afspeelrechten."""

    def is_gekoppeld(self):
        return True

    def mag_afspelen(self):
        return False


@pytest.fixture
def met_profiel(monkeypatch):
    monkeypatch.setattr(sp, "profiel", lambda klant=None, **k: PROF)
    monkeypatch.setattr(random, "choice", lambda pool: pool[0])


def test_speel_meteen(met_profiel):
    gevraagd = []

    def pc(tool, args):
        gevraagd.append((tool, args))
        return ToolResult(True, "ok", data={"resultaat": {"data": {"speelt": True}}})

    assert sp.voer_uit("zet iets op wat ik leuk vind", Klant(), pc) == "Speelt nu: 'Levels' van Avicii."
    assert gevraagd == [("spotify_open", {"uri": uri(2)})]


def test_speel_staat_klaar(met_profiel):
    pc = lambda t, a: ToolResult(True, "ok", data={"speelt": False})  # noqa: E731
    assert sp.voer_uit("verras me", Klant(), pc) == (
        "'Levels' van Avicii staat klaar in Spotify. "
        "Koppel Spotify opnieuw, dan kan ik het meteen laten spelen.")


def test_voorstel_en_ja(met_profiel):
    from core import brain, confirmation

    antwoord = sp.voer_uit("stel muziek voor", Klant())
    assert antwoord == "Wat dacht u van 'Levels' van Avicii? Zal ik hem opzetten?"
    pending = confirmation.get_pending()
    assert pending["kind"] == "muziek_voorstel" and pending["question"] == antwoord
    assert confirmation.beschrijf_pending()["actie"] == "'Levels' van Avicii opzetten in Spotify"
    gevraagd = []
    import core.filmmodus as fm

    orig = fm._pc_tool
    fm._pc_tool = lambda t, a: gevraagd.append(a) or ToolResult(True, "ok", data={"speelt": True})
    try:
        assert brain.handle_pending_choice("ja") == "Speelt nu: 'Levels' van Avicii."
    finally:
        fm._pc_tool = orig
    assert gevraagd == [{"uri": uri(2)}]


def test_voorstel_en_nee(met_profiel):
    from core import brain

    sp.voer_uit("heb je een muziektip", Klant())
    assert brain.handle_pending_choice("nee") == "Goed, een andere keer, sir."


def test_smaak_via_het_brein(paden, monkeypatch):
    from core import brain

    token, _ = paden
    koppel(token)
    monkeypatch.setattr(sp, "profiel", lambda klant=None, **k: PROF)
    assert brain.process_command("wat is mijn muzieksmaak").startswith(
        "De laatste tijd luistert u vooral naar Daft Punk")


def test_voorstel_bij_gamemodus(monkeypatch):
    monkeypatch.setattr(sp, "profiel", lambda klant=None, **k: PROF)
    monkeypatch.setattr(random, "choice", lambda pool: pool[0])
    zin = sp.voorstel_bij_modus("gaming", Klant())
    assert zin == "Muziek erbij? Wat dacht u van uw playlist 'Gaming Hype'? Zal ik hem opzetten?"


def test_voorstel_bij_modus_gooit_nooit(monkeypatch):
    def stuk(klant=None, **k):
        raise sp.SpotifyFout("weg")

    monkeypatch.setattr(sp, "profiel", stuk)
    assert sp.voorstel_bij_modus("gaming", Klant()) is None


def test_gaming_routine_stelt_muziek_voor():
    data = json.load(open(os.path.join(PROJECT, "config", "routines.json"), encoding="utf-8"))
    assert data["gaming"]["muziek_voorstel"] == "gaming"


# -----------------------------------------------------------------
# Spotify-link openen (agent-actie)
# -----------------------------------------------------------------

def test_open_spotify_alleen_geldige_links():
    from actions.media import open_spotify

    geopend = []
    r = open_spotify("https://evil.example/x", opener=geopend.append)
    assert not r.ok and geopend == []
    titel = {"t": "Spotify Premium"}

    def openen(u):
        geopend.append(u)
        titel["t"] = "Avicii - Levels"

    r = open_spotify("spotify:track:" + "A" * 22, opener=openen,
                     vensters_fn=lambda n: [(1, titel["t"])], wacht=0)
    assert r.ok and r.data["speelt"] is True and geopend == ["spotify:track:" + "A" * 22]
    r = open_spotify("spotify:playlist:" + "B" * 22, opener=geopend.append,
                     vensters_fn=lambda n: [(1, "Spotify Premium")], wacht=0)
    assert r.ok and r.data["speelt"] is False


def test_spotify_open_op_de_game_pc():
    from core.tool_registry import get_tool_risk
    from remote import allowlist

    goed = "spotify:track:" + "A" * 22
    assert allowlist.validate_call("spotify_open", {"uri": goed})[0] == {"uri": goed}
    assert allowlist.validate_call("spotify_open", {"uri": "C:\\Windows\\cmd.exe"})[0] is None
    assert allowlist.is_allowed_in_profiel("spotify_open", allowlist.PROFIEL_BASIS)
    assert get_tool_risk("game_pc_spotify_open", {}) == "low"


def test_tokens_niet_in_git():
    tekst = open(os.path.join(PROJECT, ".gitignore"), encoding="utf-8").read()
    assert "memory/spotify_token.json" in tekst and "memory/spotify_smaak.json" in tekst


# -----------------------------------------------------------------
# Afspelen via de Web API (wens 2026-10-26, Premium)
# -----------------------------------------------------------------

class AfspeelKlant:
    def __init__(self, apparaten, weiger=None, mag=True):
        self.apparaten = list(apparaten)
        self.weiger = weiger
        self.mag = mag
        self.gespeeld = []
        self.later = []  # apparaten die pas na een paar keer vragen verschijnen

    def is_gekoppeld(self):
        return True

    def mag_afspelen(self):
        return self.mag

    def get(self, pad, params=None):
        assert pad == "/me/player/devices"
        self.gevraagd = getattr(self, "gevraagd", 0) + 1
        if not self.apparaten and self.later and self.gevraagd > 1:
            self.apparaten = [self.later.pop(0)]  # pas na het openen van de app
        return {"devices": self.apparaten}

    def put(self, pad, params=None, body=None):
        if self.weiger:
            raise sp.SpotifyFout("nee", self.weiger)
        self.gespeeld.append((pad, params, body))


GAME_PC = {"id": "d1", "name": "GAME-PC", "type": "Computer", "is_active": False}
TELEFOON = {"id": "d2", "name": "iPhone", "type": "Smartphone", "is_active": True}
NUMMER = {"naam": "Levels", "artiest": "Avicii", "uri": uri(2)}
PLAYLIST = {"naam": "Gaming Hype", "artiest": "", "uri": uri(8, "playlist"), "playlist": True}


def geen_pc(tool, args):
    raise AssertionError(f"geen pc-tool verwacht: {tool}")


def test_speelt_echt_af_op_het_actieve_apparaat():
    klant = AfspeelKlant([GAME_PC, TELEFOON])
    assert sp.speel(NUMMER, geen_pc, klant) == "Speelt nu: 'Levels' van Avicii."
    assert klant.gespeeld == [("/me/player/play", {"device_id": "d2"}, {"uris": [uri(2)]})]


def test_ingesteld_apparaat_wint(monkeypatch):
    import config

    monkeypatch.setattr(config, "SPOTIFY_APPARAAT", "game")
    klant = AfspeelKlant([GAME_PC, TELEFOON])
    sp.speel(PLAYLIST, geen_pc, klant)
    assert klant.gespeeld == [("/me/player/play", {"device_id": "d1"}, {"context_uri": uri(8, "playlist")})]


def test_spotify_dicht_wordt_eerst_geopend():
    klant = AfspeelKlant([])
    klant.later = [GAME_PC]
    geopend = []
    antwoord = sp.speel(NUMMER, lambda t, a: geopend.append((t, a)), klant, slaap=lambda s: None)
    assert geopend == [("open_program", {"program": "Spotify"})]
    assert antwoord == "Speelt nu: 'Levels' van Avicii." and klant.gespeeld


def test_geen_apparaat_valt_terug_op_de_link():
    klant = AfspeelKlant([])
    aanroepen = []

    def pc(tool, args):
        aanroepen.append(tool)
        return ToolResult(True, "ok", data={"speelt": False})

    antwoord = sp.speel(NUMMER, pc, klant, slaap=lambda s: None)
    assert aanroepen == ["open_program", "spotify_open"]
    assert antwoord == "'Levels' van Avicii staat klaar in Spotify."


def test_zonder_premium_eerlijk():
    klant = AfspeelKlant([GAME_PC], weiger=403)
    assert sp.speel(NUMMER, geen_pc, klant) == "Spotify weigert het afspelen, sir. Daarvoor is Spotify Premium nodig."


def test_andere_fout_valt_terug_op_de_link():
    klant = AfspeelKlant([GAME_PC], weiger=500)
    pc = lambda t, a: ToolResult(True, "ok", data={"speelt": True})  # noqa: E731
    assert sp.speel(NUMMER, pc, klant) == "Speelt nu: 'Levels' van Avicii."


def test_mag_afspelen_leest_de_scope(paden):
    token, _ = paden
    token.write_text(json.dumps({"refresh_token": "RT", "scope": sp.SCOPES_LEZEN}), encoding="utf-8")
    assert sp.SpotifyKlant(pad=str(token)).mag_afspelen() is False
    token.write_text(json.dumps({"refresh_token": "RT", "scope": sp.SCOPES}), encoding="utf-8")
    assert sp.SpotifyKlant(pad=str(token)).mag_afspelen() is True


def test_put_stuurt_bearer_en_body(paden):
    token, _ = paden
    koppel(token)

    class Http(NepHttp):
        def put(self, url, params=None, json=None, headers=None, timeout=None):
            self.gets.append((url, params, json, headers))
            return Antwoord(204, None)

    http = Http()
    sp.SpotifyKlant(pad=str(token), http=http).put("/me/player/play", {"device_id": "d"}, {"uris": ["x"]})
    assert http.gets[0] == (sp.API + "/me/player/play", {"device_id": "d"}, {"uris": ["x"]},
                            {"Authorization": "Bearer AT"})
