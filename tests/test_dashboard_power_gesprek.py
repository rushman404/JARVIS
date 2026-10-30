"""Tests voor de dashboard-update van 2026-10-30.

Dekt:
  - Systeem: uit / herstart / slaap lopen ALLEEN via een goedkeuring, op
    de pc die in het paneel gekozen is
  - Aan: alleen de game-pc, direct via de Wake-on-LAN-knop
  - Annuleren: alleen na een ja op uit/herstart, en tot het aftellen klaar is
  - het gesprek op schijf: blijft na een herstart, oudere pagina's,
    opruimen na 30 dagen, wissen
  - rollen op de nieuwe endpoints (kijk mag terugscrollen, niet wissen)
"""

import json

import pytest

import status
from core import confirmation
from core.confirmation import get_pending
from core.games_stem import GameStarter
from dashboard import auth
from dashboard.api import GESPREK_PAGINA, DashboardAPI
from dashboard.server import DashboardServer, standaard_hosts, standaard_origins
from remote.server import RateLimiter

VIEW = "kijk-token-0123456789abcdef"
CONTROL = "bedien-token-0123456789abcdef"
HOST = "192.168.1.5:8780"
ORIGIN = "https://192.168.1.5:8780"
IPAD = "192.168.1.20"


class Klok:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def klok():
    return Klok()


@pytest.fixture
def api(tmp_path, klok):
    a = DashboardAPI(
        widgets_pad=str(tmp_path / "dashboard.json"),
        clock=klok,
        audit_fn=lambda **v: a.audit_regels.append(v),
        power_doel_fn=lambda: "local",
        uitvoerder=lambda p, ok: "Ik sluit af." if ok else "Oké.",
        wek_fn=lambda: a.gewekt.append(True) or True,
        annuleer_fn=lambda doel: a.geannuleerd.append(doel) or "Afsluiten geannuleerd.",
        aftel_fn=lambda: 20,
        besluit_fn=lambda tekst: a.gemeld.append(tekst),
    )
    a.audit_regels, a.gewekt, a.geannuleerd, a.gemeld = [], [], [], []
    return a


def _ja(api):
    p = get_pending()
    return api.goedkeuring({"id": p[confirmation.ID_KEY], "nonce": p[confirmation.NONCE_KEY], "besluit": "ja"})


# ----- uit / herstart / slaap -----

@pytest.mark.parametrize("actie, power, vraag", [
    ("uit", "shutdown", "De game-pc afsluiten?"),
    ("herstart", "restart", "De game-pc herstarten?"),
    ("slaap", "sleep", "De game-pc in slaapstand zetten?"),
])
def test_power_maakt_alleen_een_goedkeuring_voor_het_gekozen_doel(api, actie, power, vraag):
    api.uitvoerder = lambda p, ok: pytest.fail("power mag nooit direct uitgevoerd worden")
    code, data = api.power({"actie": actie, "doel": "game-pc"})
    assert code == 202
    p = get_pending()
    assert (p["kind"], p["action"], p["target"], p["question"]) == ("power_confirm", power, "game-pc", vraag)
    assert data["id"] == p[confirmation.ID_KEY]


def test_zonder_doel_de_standaard_pc(api):
    assert api.power({"actie": "uit"})[0] == 202
    assert get_pending()["target"] == "local"
    assert get_pending()["question"] == "Deze pc afsluiten?"


@pytest.mark.parametrize("body", [{"actie": "uit", "doel": "server"}, {"actie": "uit", "doel": ""}, "uit", None])
def test_ongeldig_doel_of_body(api, body):
    assert api.power(body)[0] == 400
    assert get_pending() is None


# ----- aan -----

def test_aan_wekt_de_game_pc_direct(api):
    assert api.power({"actie": "aan", "doel": "game-pc"}) == (200, {"ok": True})
    assert api.gewekt == [True]
    assert get_pending() is None
    assert api.audit_regels[-1]["tool"] == "power_aan"


def test_aan_kan_niet_voor_deze_pc(api):
    assert api.power({"actie": "aan", "doel": "local"})[0] == 400
    assert api.gewekt == []


def test_aan_zonder_knop_geeft_een_nette_fout(api):
    api.wek_fn = lambda: False
    code, data = api.power({"actie": "aan", "doel": "game-pc"})
    assert code == 502 and "Wake-on-LAN" in data["fout"]["melding"]


def test_wek_drukt_op_de_knop_in_home_assistant(tmp_path):
    class Ha:
        def __init__(self):
            self.diensten = []

        def staten(self):
            return [{"entity_id": "button.game_pc_aan", "attributes": {"friendly_name": "Game PC aan"}}]

        def dienst(self, domein, dienst, data):
            self.diensten.append((domein, dienst, data))
            return True

    ha = Ha()
    starter = GameStarter(ha=ha, cache_pad=str(tmp_path / "games.json"), online_fn=lambda: False)
    assert starter.wek() is True
    assert ha.diensten == [("button", "press", {"entity_id": "button.game_pc_aan"})]


# ----- annuleren -----

def test_annuleren_kan_alleen_na_ja_op_uit_of_herstart(api):
    assert api.power({"actie": "annuleer"})[0] == 409
    api.power({"actie": "slaap", "doel": "game-pc"})
    _ja(api)
    assert api.status()[1]["afsluiting"] is None
    assert api.power({"actie": "annuleer"})[0] == 409
    assert api.geannuleerd == []


@pytest.mark.parametrize("actie, power", [("uit", "shutdown"), ("herstart", "restart")])
def test_annuleren_na_ja(api, actie, power):
    api.power({"actie": actie, "doel": "game-pc"})
    assert _ja(api)[0] == 200
    assert api.status()[1]["afsluiting"] == {"doel": "game-pc", "actie": power}
    assert api.power({"actie": "annuleer"}) == (200, {"ok": True, "resultaat": "Afsluiten geannuleerd."})
    assert api.geannuleerd == ["game-pc"]
    assert api.gemeld[-1] == "Afsluiten geannuleerd."
    assert api.status()[1]["afsluiting"] is None


def test_annuleren_niet_na_nee(api):
    api.power({"actie": "uit"})
    p = get_pending()
    api.goedkeuring({"id": p[confirmation.ID_KEY], "nonce": p[confirmation.NONCE_KEY], "besluit": "nee"})
    assert api.status()[1]["afsluiting"] is None


def test_annuleer_knop_verdwijnt_na_het_aftellen(api, klok):
    api.power({"actie": "uit"})
    _ja(api)
    klok.t += 19
    assert api.status()[1]["afsluiting"] == {"doel": "local", "actie": "shutdown"}
    klok.t += 1
    assert api.status()[1]["afsluiting"] is None
    assert api.power({"actie": "annuleer"})[0] == 409


# ----- het gesprek op schijf -----

def test_gesprek_blijft_na_een_herstart():
    status.noteer_gesprek("me", "Hoe laat is het?")
    status.noteer_gesprek("ai", "Vijf over twee, sir.")
    status._reset_gesprek()  # zoals een herstart: geheugen leeg, log blijft
    assert [b["tekst"] for b in status.gesprek()] == ["Hoe laat is het?", "Vijf over twee, sir."]
    status.noteer_gesprek("me", "Dank je")
    ids = [b["id"] for b in status.gesprek()]
    assert ids == sorted(ids) and len(set(ids)) == 3


def test_oudere_paginas():
    for i in range(75):
        status.noteer_gesprek("me", f"zin {i}")
    recent = status.gesprek()
    assert [b["tekst"] for b in recent] == [f"zin {i}" for i in range(45, 75)]
    beurten, meer = status.gesprek_ouder(recent[0]["id"], 30)
    assert [b["tekst"] for b in beurten] == [f"zin {i}" for i in range(15, 45)] and meer
    beurten, meer = status.gesprek_ouder(beurten[0]["id"], 30)
    assert [b["tekst"] for b in beurten] == [f"zin {i}" for i in range(15)] and not meer


def test_ouder_dan_30_dagen_wordt_opgeruimd():
    oud = 1_000.0
    with open(status.GESPREK_LOG, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": 1, "wie": "me", "tekst": "heel oud", "tijd": oud}) + "\n")
        f.write("half geschreven regel\n")
    status.noteer_gesprek("me", "nieuw")
    assert [b["tekst"] for b in status.gesprek()] == ["nieuw"]
    with open(status.GESPREK_LOG, encoding="utf-8") as f:
        assert "heel oud" not in f.read()


def test_wissen_ook_op_schijf():
    status.noteer_gesprek("me", "geheim")
    status.wis_gesprek()
    assert status.gesprek() == []
    status._reset_gesprek()
    assert status.gesprek() == []


def test_api_gesprek_met_tijd_en_oudere_pagina(api):
    for i in range(GESPREK_PAGINA + 5):
        status.noteer_gesprek("ai", f"zin {i}")
    code, recent = api.gesprek()
    assert code == 200 and len(recent) == GESPREK_PAGINA
    assert set(recent[0]) == {"id", "wie", "tekst", "tijd"} and isinstance(recent[0]["tijd"], float)
    code, data = api.gesprek_ouder({"voor": recent[0]["id"]})
    assert code == 200 and [b["tekst"] for b in data["beurten"]] == [f"zin {i}" for i in range(5)]
    assert data["meer"] is False


@pytest.mark.parametrize("body", [{}, {"voor": "12"}, {"voor": True}, {"voor": 0}, None])
def test_api_gesprek_ouder_ongeldig(api, body):
    assert api.gesprek_ouder(body)[0] == 400


def test_api_gesprek_wissen(api):
    status.noteer_gesprek("me", "hallo")
    assert api.gesprek_wissen() == (200, {"ok": True})
    assert api.gesprek()[1] == []
    assert api.audit_regels[-1]["tool"] == "gesprek_wissen"


# ----- rollen -----

@pytest.fixture
def srv(tmp_path, api):
    hosts = standaard_hosts(8780, "192.168.1.5")
    return DashboardServer(
        api=api,
        authenticator=auth.Authenticator(VIEW, CONTROL, auth.ApparaatRegister(str(tmp_path / "d.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts,
        allowed_origins=standaard_origins(hosts),
        rate_limiter=RateLimiter(1000, 60),
        audit_fn=lambda **v: None,
    )


def _req(srv, method, pad, token, body=None):
    h = {"Host": HOST, "Authorization": f"Bearer {token}"}
    data = b""
    if method != "GET":
        h["Origin"] = ORIGIN
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
    return srv.process(method, pad, h, data, client_ip=IPAD)


def test_kijk_mag_terugscrollen_maar_niet_wissen(srv):
    status.noteer_gesprek("me", "hallo")
    voor = status.gesprek()[-1]["id"] + 1
    assert _req(srv, "POST", "/api/gesprek/ouder", VIEW, {"voor": voor}).json()["beurten"][0]["tekst"] == "hallo"
    assert _req(srv, "POST", "/api/gesprek/wissen", VIEW, {}).status == 403
    assert status.gesprek() != []
    assert _req(srv, "POST", "/api/gesprek/wissen", CONTROL, {}).status == 200
    assert status.gesprek() == []


@pytest.mark.parametrize("body", [{"actie": "aan", "doel": "game-pc"}, {"actie": "uit", "doel": "local"}])
def test_kijk_mag_geen_power(srv, api, body):
    assert _req(srv, "POST", "/api/power", VIEW, body).status == 403
    assert api.gewekt == [] and get_pending() is None
