"""Fase 23, M1 — koppelingsbasis: opslag, OAuth met verversen, status."""

import json
import os
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request

import pytest

from core import koppelingen as kp

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEHEIM = "geheim-token-" + "x" * 20


class Antwoord:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class NepHttp:
    def __init__(self, *antwoorden):
        self.antwoorden = list(antwoorden)
        self.verstuurd = []

    def post(self, url, data=None, timeout=None):
        self.verstuurd.append((url, dict(data or {})))
        return self.antwoorden.pop(0)

    def get(self, url, **kw):
        raise AssertionError("zonder geldig token geen API-verzoek")


def _dienst(geheim=""):
    return kp.OAuthDienst(
        "test", "Testdienst", "https://auth.example/authorize", "https://auth.example/token",
        "lezen schrijven", client_id_fn=lambda: "cid", redirect_fn=lambda: "http://127.0.0.1:8890/cb",
        client_secret_fn=lambda: geheim, extra_auth={"access_type": "offline"},
        rechten={"lezen": "lezen", "schrijven": "versturen"})


class Klok:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# -----------------------------------------------------------------
# Opslag
# -----------------------------------------------------------------

def test_pad_voor_weigert_rare_namen():
    assert kp.pad_voor("gmail").endswith(os.path.join("memory", "koppelingen", "gmail.json"))
    for slecht in ("../x", "Gmail", "", "a/b", "x" * 31):
        with pytest.raises(ValueError):
            kp.pad_voor(slecht)


def test_tokenmap_staat_buiten_git():
    uit = subprocess.run(["git", "check-ignore", "-q", "memory/koppelingen/gmail.json"], cwd=PROJECT)
    if uit.returncode == 128:
        pytest.skip("geen git-checkout")
    assert uit.returncode == 0


def test_schrijven_is_atomair(tmp_path):
    pad = str(tmp_path / "a" / "t.json")
    kp.schrijf_json(pad, {"a": 1})
    assert kp.lees_json(pad) == {"a": 1} and not os.path.exists(pad + ".tmp")
    open(pad, "w").write("kapot")
    assert kp.lees_json(pad) is None


# -----------------------------------------------------------------
# OAuth
# -----------------------------------------------------------------

def test_autorisatie_url(tmp_path):
    k = kp.OAuthKoppeling(_dienst(), pad=str(tmp_path / "t.json"))
    q = urllib.parse.parse_qs(urllib.parse.urlparse(k.autorisatie_url("v" * 50, "staat")).query)
    assert q["code_challenge"] == [kp.challenge("v" * 50)] and q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["staat"] and q["access_type"] == ["offline"] and q["scope"] == ["lezen schrijven"]
    assert "client_secret" not in q


def test_wissel_code_en_status(tmp_path):
    pad = str(tmp_path / "t.json")
    http = NepHttp(Antwoord(200, {"access_token": GEHEIM, "refresh_token": "r1", "expires_in": 3600,
                                  "scope": "lezen"}))
    k = kp.OAuthKoppeling(_dienst("cs"), pad=pad, http=http, klok=Klok())
    k.wissel_code("code1", "verifier")
    assert http.verstuurd[0][1]["client_secret"] == "cs" and http.verstuurd[0][1]["code_verifier"] == "verifier"
    st = k.status()
    assert st == {"id": "test", "naam": "Testdienst", "gekoppeld": True, "rechten": ["lezen"], "probleem": None}
    assert GEHEIM not in json.dumps(st)


def test_token_wordt_ververst_en_refresh_blijft(tmp_path):
    pad = str(tmp_path / "t.json")
    klok = Klok()
    kp.schrijf_json(pad, {"access_token": "oud", "refresh_token": "r1", "verloopt": 1030, "scope": "lezen",
                          "gekoppeld_op": 5})
    http = NepHttp(Antwoord(200, {"access_token": "nieuw", "expires_in": 3600}))
    k = kp.OAuthKoppeling(_dienst(), pad=pad, http=http, klok=klok)
    assert k.access_token() == "nieuw"
    data = kp.lees_json(pad)
    assert data["refresh_token"] == "r1" and data["scope"] == "lezen" and data["gekoppeld_op"] == 5
    # Nog geldig: geen nieuw verzoek.
    assert k.access_token() == "nieuw" and len(http.verstuurd) == 1


def test_ingetrokken_toegang_wordt_een_probleem(tmp_path):
    pad = str(tmp_path / "t.json")
    kp.schrijf_json(pad, {"access_token": "oud", "refresh_token": "r1", "verloopt": 0, "scope": "lezen"})
    k = kp.OAuthKoppeling(_dienst(), pad=pad, http=NepHttp(Antwoord(400)), klok=Klok())
    with pytest.raises(kp.KoppelFout, match="opnieuw gekoppeld"):
        k.access_token()
    assert k.status()["probleem"] == kp.PROBLEEM_OPNIEUW


def test_netwerkfout_wordt_koppelfout(tmp_path):
    pad = str(tmp_path / "t.json")
    kp.schrijf_json(pad, {"refresh_token": "r1", "verloopt": 0})

    class Kapot:
        def post(self, *a, **kw):
            raise TimeoutError("traag")

    with pytest.raises(kp.KoppelFout) as fout:
        kp.OAuthKoppeling(_dienst(), pad=pad, http=Kapot(), klok=Klok()).access_token()
    assert fout.value.status == "netwerk"


def test_niet_gekoppeld(tmp_path):
    k = kp.OAuthKoppeling(_dienst(), pad=str(tmp_path / "geen.json"))
    assert not k.is_gekoppeld() and k.status()["rechten"] == []
    with pytest.raises(kp.KoppelFout, match="niet gekoppeld"):
        k.access_token()


# -----------------------------------------------------------------
# Koppelen vanuit een script (loopback)
# -----------------------------------------------------------------

def _vrije_poort():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("query,verwacht", [
    ("code=abc&state=s1", "abc"),
    ("code=abc&state=fout", "state"),
    ("error=access_denied&state=s1", "geen toestemming"),
])
def test_ontvang_code(query, verwacht):
    redirect = f"http://127.0.0.1:{_vrije_poort()}/cb"

    def openen():
        def bezoek():
            urllib.request.urlopen(redirect + "?" + query, timeout=5).read()

        threading.Thread(target=bezoek, daemon=True).start()

    if verwacht == "abc":
        assert kp.ontvang_code(redirect, "s1", openen, wacht=5) == "abc"
    else:
        with pytest.raises(kp.KoppelFout, match=verwacht):
            kp.ontvang_code(redirect, "s1", openen, wacht=5)


def test_ontvang_code_alleen_lokaal():
    with pytest.raises(kp.KoppelFout):
        kp.ontvang_code("https://voorbeeld.nl/cb", "s", wacht=1)


# -----------------------------------------------------------------
# Overzicht en stem
# -----------------------------------------------------------------

def test_overzicht_vangt_kapotte_koppeling():
    def kapot():
        raise RuntimeError("stuk")

    lijst = kp.overzicht({"a": lambda: {"naam": "A", "gekoppeld": True, "rechten": ["lezen"]}, "b": kapot})
    assert lijst[0] == {"id": "a", "naam": "A", "gekoppeld": True, "rechten": ["lezen"], "probleem": None}
    assert lijst[1]["gekoppeld"] is False and "onbekend" in lijst[1]["probleem"]


def test_spotify_staat_in_het_overzicht(tmp_path, monkeypatch):
    from core import spotify_smaak as sp

    monkeypatch.setattr(sp, "TOKEN_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(sp, "_client_id", lambda: "cid")
    assert kp.overzicht()[0] == {"id": "spotify", "naam": "Spotify", "gekoppeld": False, "rechten": [],
                                 "probleem": None}
    kp.schrijf_json(sp.TOKEN_FILE, {"refresh_token": "r", "scope": sp.SCOPES})
    assert kp.overzicht()[0]["rechten"] == ["lezen", "afspelen"]


def test_spotify_ingetrokken_wordt_probleem(tmp_path):
    from core import spotify_smaak as sp

    pad = str(tmp_path / "s.json")
    kp.schrijf_json(pad, {"access_token": "a", "refresh_token": "r", "verloopt": 0, "scope": sp.SCOPES})
    klant = sp.SpotifyKlant(client_id="cid", pad=pad, http=NepHttp(Antwoord(400)))
    with pytest.raises(sp.SpotifyFout, match="opnieuw"):
        klant.get("/me")
    assert sp.koppeling_status(klant)["probleem"] == kp.PROBLEEM_OPNIEUW


def test_beschrijf():
    lijst = [
        {"id": "spotify", "naam": "Spotify", "gekoppeld": True, "rechten": ["lezen", "afspelen"], "probleem": None},
        {"id": "gmail", "naam": "Gmail", "gekoppeld": True, "rechten": ["lezen"], "probleem": "opnieuw koppelen nodig"},
        {"id": "icloud", "naam": "iCloud-agenda", "gekoppeld": False, "rechten": [], "probleem": None},
    ]
    assert kp.beschrijf(lijst) == ("Gekoppeld: Spotify (lezen en afspelen). Gmail: opnieuw koppelen nodig. "
                                   "Nog niet gekoppeld: iCloud-agenda.")


@pytest.mark.parametrize("zin", ["welke koppelingen heb ik?", "Status van mijn koppelingen",
                                 "zijn mijn koppelingen in orde", "koppelingen"])
def test_stemcommando(zin):
    assert kp.probeer_commando(zin, lijst_fn=lambda: []) == "Er zijn nog geen koppelingen ingesteld, sir."


@pytest.mark.parametrize("zin", ["koppel de lamp aan de routine", "wat is een koppeling", "zet muziek op"])
def test_geen_stemcommando(zin):
    assert kp.probeer_commando(zin) is None


def test_brein_routeert_de_vraag(monkeypatch):
    from core import brain

    monkeypatch.setattr(kp, "overzicht", lambda bronnen=None: [])
    assert brain.process_command("welke koppelingen heb ik") == "Er zijn nog geen koppelingen ingesteld, sir."


# -----------------------------------------------------------------
# Dashboard: Systeem-paneel
# -----------------------------------------------------------------

def test_brein_status_bevat_koppelingen(monkeypatch):
    from beheer import waakhond
    from dashboard import bronnen

    monkeypatch.setattr(waakhond, "brein_status", lambda: {})
    monkeypatch.setattr(kp, "overzicht", lambda bronnen=None: [{"id": "spotify", "naam": "Spotify",
                                                                 "gekoppeld": True, "rechten": [], "probleem": None}])
    assert bronnen._std_brein()["koppelingen"][0]["naam"] == "Spotify"


def test_systeem_paneel_toont_koppelingen():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is niet geïnstalleerd")
    js = open(os.path.join(PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    functie = "function breinRegel(" + js.split("function breinRegel(")[1].split("\n  function ")[0]
    code = (
        "function el(tag, klasse, tekst) { return {klasse: klasse, tekst: tekst || '', kids: [],"
        " appendChild: function (k) { this.kids.push(k); }}; }\n"
        "function duur(m) { return m + ' min'; }\n"
        + functie +
        "\nvar b = breinRegel({koppelingen: ["
        "{naam: 'Spotify', gekoppeld: true, probleem: null},"
        "{naam: 'Gmail', gekoppeld: true, probleem: 'opnieuw koppelen nodig'},"
        "{naam: 'iCloud-agenda', gekoppeld: false, probleem: null}]});\n"
        "console.log(JSON.stringify(b.kids[1]));\n"
    )
    uit = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert uit.returncode == 0, uit.stderr
    rij = json.loads(uit.stdout)
    assert rij["klasse"] == "waarschuwing"
    assert rij["tekst"] == ("Koppelingen: Spotify ✓ · Gmail ! · iCloud-agenda – "
                            "(Gmail: opnieuw koppelen nodig)")
