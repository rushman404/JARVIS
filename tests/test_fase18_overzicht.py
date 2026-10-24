"""Tests voor Fase 18 M6: het overzicht (logboek, geheugen, routines).

Alles is alleen lezen. Dekt:
  - logboek: nieuwste eerst, niveau/bron/tekst, halve eerste regel,
    ontbrekend bestand, en een vangnet dat iets wat op een token lijkt
    nooit op het scherm komt
  - geheugen: categorieën met aantallen, recentst bijgewerkt eerst, ook
    voor oude/kale waarden en rare inhoud
  - routines: stappen met eerst wát er bediend wordt, gebruik, vertrouwd
  - endpoints: kijk mag lezen, zonder token 401, geen schrijfroutes
"""

import json

import pytest

from core.timers import TimerStore
from dashboard import auth
from dashboard import bronnen as mod
from dashboard.api import DashboardAPI
from dashboard.bronnen import Bronnen, geheugen_overzicht, lees_log, routines_overzicht
from dashboard.server import DashboardServer, standaard_hosts, standaard_origins
from remote.server import RateLimiter

VIEW = "kijk-token-0123456789abcdef"
CONTROL = "bedien-token-0123456789abcdef"
HOST = "192.168.1.5:8780"


# ----- logboek -----

def test_logboek_nieuwste_eerst(tmp_path):
    pad = tmp_path / "jarvis.log"
    pad.write_text(
        "2026-10-24 17:01:02,123 INFO     main: JARVIS gestart\n"
        "2026-10-24 17:02:10,555 ERROR    core.llm: Het model is niet gevonden\n"
        "losse regel zonder opmaak\n",
        encoding="utf-8",
    )
    regels = lees_log(str(pad))
    assert [r["tekst"] for r in regels] == ["losse regel zonder opmaak", "Het model is niet gevonden", "JARVIS gestart"]
    assert regels[1] == {"datum": "2026-10-24", "tijd": "17:02:10", "niveau": "ERROR",
                         "bron": "core.llm", "tekst": "Het model is niet gevonden"}


def test_logboek_maximaal_aantal_en_halve_eerste_regel(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LOG_LEES_BYTES", 2000)
    pad = tmp_path / "jarvis.log"
    pad.write_text("".join(f"2026-10-24 17:00:{i % 60:02d},000 INFO     x: regel {i}\n" for i in range(500)),
                   encoding="utf-8")
    regels = lees_log(str(pad), aantal=10)
    assert len(regels) == 10
    assert regels[0]["tekst"] == "regel 499"
    assert all(r["niveau"] == "INFO" for r in regels)


@pytest.mark.parametrize("tekst", [
    "token=abc123geheim", "Authorization: Bearer abc123geheim", "password abc123geheim",
    "api_key=abc123geheim", "wachtwoord: abc123geheim",
])
def test_logboek_toont_nooit_iets_dat_op_een_geheim_lijkt(tmp_path, tekst):
    pad = tmp_path / "jarvis.log"
    pad.write_text(f"2026-10-24 17:00:00,000 INFO     x: {tekst}\n", encoding="utf-8")
    assert "abc123geheim" not in json.dumps(lees_log(str(pad)))


def test_logboek_zonder_bestand(tmp_path):
    assert lees_log(str(tmp_path / "bestaat-niet.log")) == []


# ----- geheugen -----

def test_geheugen_overzicht():
    g = geheugen_overzicht({
        "algemeen": {"naam": {"value": "Rushil", "updated": "2026-10-18T12:00:00", "usage_count": 4},
                     "oud_feit": "kale waarde"},
        "voorkeuren": {"favoriete_game": {"value": "Valorant", "updated": "2026-10-20T09:00:00"}},
        "leeg": {},
        "kapot": "geen dict",
    })
    assert g["totaal"] == 3
    assert g["categorieen"] == [{"naam": "algemeen", "aantal": 2}, {"naam": "voorkeuren", "aantal": 1}]
    assert [i["sleutel"] for i in g["items"]] == ["favoriete game", "naam", "oud feit"]
    assert g["items"][0]["bijgewerkt"] == "2026-10-20 09:00"
    assert g["items"][1]["gebruikt"] == 4
    assert g["items"][2]["waarde"] == "kale waarde"


def test_geheugen_lange_en_niet_tekst_waarden():
    g = geheugen_overzicht({"x": {"lijst": {"value": ["a", "b"]}, "lang": {"value": "y" * 500}}})
    waarden = {i["sleutel"]: i["waarde"] for i in g["items"]}
    assert waarden["lijst"] == '["a", "b"]'
    assert len(waarden["lang"]) <= mod.MAX_TEKST


def test_geheugen_fout_geeft_leeg_overzicht():
    b = Bronnen(geheugen_fn=lambda: (_ for _ in ()).throw(OSError("kapot")))
    assert b.geheugen() == {"categorieen": [], "items": [], "totaal": 0}
    assert geheugen_overzicht(None) == {"categorieen": [], "items": [], "totaal": 0}


# ----- routines -----

def test_routines_overzicht():
    r = routines_overzicht({
        "sleep": {
            "name": "sleep", "description": "Slaapmodus", "usage_count": 3, "last_used": "2026-10-12T23:37:00",
            "steps": [
                {"tool_name": "media_stop", "arguments": {}},
                {"tool_name": "control_home_assistant",
                 "arguments": {"domain": "light", "service": "turn_off", "entity_id": "light.bed_lamp"}},
                "kapotte stap",
            ],
        },
        "gaming": {"name": "gaming", "vertrouwd": True, "steps": [{"tool_name": "open_program", "arguments": {"program": "Discord"}}]},
    })
    assert [x["naam"] for x in r] == ["gaming", "sleep"]
    assert r[0]["vertrouwd"] is True and r[1]["vertrouwd"] is False
    assert r[1]["stappen"] == ["media_stop", "control_home_assistant · light.bed_lamp · turn_off"]
    assert r[1]["gebruikt"] == 3
    assert r[1]["laatst_gebruikt"] == "2026-10-12 23:37"
    assert routines_overzicht("geen dict") == []


def test_echte_routines_config_is_leesbaar():
    r = routines_overzicht(mod._std_routines())
    assert all(isinstance(x["stappen"], list) for x in r)


# ----- endpoints -----

@pytest.fixture
def srv(tmp_path):
    log = tmp_path / "jarvis.log"
    log.write_text("2026-10-24 17:00:00,000 INFO     main: <img src=x onerror=alert(1)>\n", encoding="utf-8")
    bronnen = Bronnen(
        log_pad_fn=lambda: str(log),
        geheugen_fn=lambda: {"algemeen": {"naam": {"value": "Rushil"}}},
        routines_fn=lambda: {"sleep": {"name": "sleep", "steps": []}},
    )
    api = DashboardAPI(timer_store=TimerStore(pad=str(tmp_path / "t.json")), audit_fn=lambda **v: None, bronnen=bronnen)
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


def _get(srv, pad, token=VIEW):
    h = {"Host": HOST}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return srv.process("GET", pad, h, b"", client_ip="192.168.1.20")


@pytest.mark.parametrize("pad", ["/api/logs", "/api/memory", "/api/routines"])
def test_overzicht_endpoints_lezen_met_kijk_rol(srv, pad):
    assert _get(srv, pad).status == 200
    assert _get(srv, pad, token=None).status == 401


@pytest.mark.parametrize("pad", ["/api/logs", "/api/memory", "/api/routines"])
def test_overzicht_heeft_geen_schrijfroutes(srv, pad):
    h = {"Host": HOST, "Authorization": f"Bearer {CONTROL}", "Origin": "https://" + HOST,
         "Content-Type": "application/json"}
    for methode in ("POST", "PUT", "DELETE"):
        assert srv.process(methode, pad, h, b"{}", client_ip="192.168.1.20").status == 405


def test_html_in_log_blijft_tekst(srv):
    assert _get(srv, "/api/logs").json()[0]["tekst"] == "<img src=x onerror=alert(1)>"


def test_query_string_verandert_niets(srv):
    # Het design noemde /api/logs?regels=200; de server leest geen query.
    assert _get(srv, "/api/logs?regels=99999").json() == _get(srv, "/api/logs").json()
