"""Fase 20, M1 — typen met JARVIS vanaf de iPad en de lopende taak."""

import inspect
import os
import threading
import time

import pytest

import status
from core import opdrachten, proactive

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wacht_tot_klaar(runner, timeout=3.0):
    eind = time.time() + timeout
    while runner.bezig() and time.time() < eind:
        time.sleep(0.01)
    assert not runner.bezig(), "de opdracht werd niet afgerond"


# ---------------------------------------------------------------
# Invoer
# ---------------------------------------------------------------

@pytest.mark.parametrize("tekst, verwacht", [
    ("zet spotify op 30 procent", "zet spotify op 30 procent"),
    ("  hoe   laat\tis het?  ", "hoe laat is het?"),
    ("regel\neen\r\ntwee", "regel een twee"),
])
def test_schoon(tekst, verwacht):
    assert opdrachten.schoon(tekst) == verwacht


@pytest.mark.parametrize("tekst", ["", "   ", "\n\t", None, 12, ["x"], "x" * 301])
def test_schoon_weigert(tekst):
    assert opdrachten.schoon(tekst) is None


# ---------------------------------------------------------------
# De runner
# ---------------------------------------------------------------

def test_opdracht_komt_in_het_gesprek_stil(monkeypatch):
    gezien, gesproken, audit = [], [], []
    runner = opdrachten.OpdrachtRunner(
        verwerk_fn=lambda t: gezien.append(t) or "Het is 14:05, sir.",
        spreek_fn=gesproken.append, audit_fn=lambda **k: audit.append(k),
    )
    assert runner.start("Hoe laat is het?") == (True, None)
    _wacht_tot_klaar(runner)
    assert gezien == ["hoe laat is het?"]  # zoals de spraaklus: kleine letters
    # Het gesprek onthoudt maximaal 12 beurten: kijk naar de laatste twee.
    nieuw = status.gesprek()[-2:]
    assert [(b["wie"], b["tekst"]) for b in nieuw] == [("me", "Hoe laat is het?"), ("ai", "Het is 14:05, sir.")]
    assert gesproken == []
    assert audit[0]["handler"] == "dashboard" and audit[0]["herkomst"] == "dashboard"
    assert audit[0]["argumenten"] == {"hardop": False}


def test_opdracht_hardop():
    gesproken = []
    runner = opdrachten.OpdrachtRunner(verwerk_fn=lambda t: "Komt eraan.", spreek_fn=gesproken.append,
                                       audit_fn=lambda **k: None)
    runner.start("speel muziek", hardop=True)
    _wacht_tot_klaar(runner)
    assert gesproken == ["Komt eraan."]


def test_een_tegelijk():
    los = threading.Event()
    runner = opdrachten.OpdrachtRunner(verwerk_fn=lambda t: los.wait(2) and "klaar",
                                       audit_fn=lambda **k: None)
    assert runner.start("eerste")[0]
    assert runner.start("tweede") == (False, "bezig")
    los.set()
    _wacht_tot_klaar(runner)
    assert runner.start("derde")[0]
    _wacht_tot_klaar(runner)


def test_ongeldig_wordt_niet_gestart():
    runner = opdrachten.OpdrachtRunner(verwerk_fn=lambda t: pytest.fail("mag niet"), audit_fn=lambda **k: None)
    assert runner.start("   ") == (False, "ongeldig")
    assert not runner.bezig()


def test_fout_in_brein_geeft_nette_melding():
    def stuk(t):
        raise RuntimeError("kapot")

    runner = opdrachten.OpdrachtRunner(verwerk_fn=stuk, audit_fn=lambda **k: None)
    runner.start("doe iets")
    _wacht_tot_klaar(runner)
    assert status.gesprek()[-1]["tekst"].startswith("Er ging iets mis")


def test_wacht_op_gesproken_opdracht():
    """Spreekt u net iets in, dan wacht de getypte opdracht op het slot."""
    volgorde = []
    runner = opdrachten.OpdrachtRunner(verwerk_fn=lambda t: volgorde.append("getypt") or "ok",
                                       audit_fn=lambda **k: None)
    with opdrachten.BREIN_LOCK:
        runner.start("getypt")
        time.sleep(0.1)
        volgorde.append("gesproken")
    _wacht_tot_klaar(runner)
    assert volgorde == ["gesproken", "getypt"]


def test_typen_maakt_wakker():
    proactive.ga_slapen(proactive.SLAAP_COMMANDO)
    runner = opdrachten.OpdrachtRunner(verwerk_fn=lambda t: "ok", audit_fn=lambda **k: None)
    runner.start("hallo")
    _wacht_tot_klaar(runner)
    assert not proactive.slaapt()


def test_main_neemt_hetzelfde_slot():
    import main

    bron = inspect.getsource(main.run_wake_cycle)
    assert "with BREIN_LOCK:" in bron
    assert main.BREIN_LOCK is opdrachten.BREIN_LOCK


# ---------------------------------------------------------------
# Lopende taak
# ---------------------------------------------------------------

def test_lopende_taak_tijdens_een_tool():
    from core.tool_registry import run_tool_guarded

    tijdens = []

    def dispatch(tool, args, vraag):
        tijdens.append(status.taak())
        return "ok"

    run_tool_guarded("set_volume", {"percent": 30}, dispatch=dispatch, approved=True)
    assert tijdens == ["het volume op 30% zetten"]
    # Na afloop blijft hij nog even staan (het dashboard kijkt maar elke seconde).
    assert status.taak() == "het volume op 30% zetten"


def test_taak_gloeit_na_en_verdwijnt(monkeypatch):
    nu = {"t": 1000.0}
    monkeypatch.setattr(status.time, "time", lambda: nu["t"])
    status.zet_taak("Spotify op 30% zetten")
    nu["t"] += 60
    assert status.taak() == "Spotify op 30% zetten", "zolang de tool loopt, blijft hij staan"
    status.zet_taak(None)
    nu["t"] += status.TAAK_NAGLOEI - 0.5
    assert status.taak() == "Spotify op 30% zetten"
    nu["t"] += 1
    assert status.taak() is None


def test_taak_omschrijving():
    from core.tool_registry import beschrijf_taak

    assert beschrijf_taak("audio_set_session_volume", {"app_name": "Spotify", "volume": 30}) == "Spotify op 30% zetten"
    assert beschrijf_taak("game_pc_open_program", {"program": "Valorant"}) == "Valorant openen op de game-pc"
    assert beschrijf_taak("media_next") == "naar het volgende nummer"
    # Onbekend: de bestaande omschrijving van de goedkeuringsvraag.
    assert beschrijf_taak("empty_recycle_bin") == "de prullenbak leegmaken"


def test_taak_gewist_na_fout():
    from core.tool_registry import run_tool_guarded

    def stuk(tool, args, vraag):
        raise RuntimeError

    with pytest.raises(RuntimeError):
        run_tool_guarded("set_volume", {"percent": 30}, dispatch=stuk, approved=True)
    assert status._taak_tot != float("inf"), "na een fout loopt de taak niet eindeloos door"


# ---------------------------------------------------------------
# Dashboard-API en route
# ---------------------------------------------------------------

def _api():
    from dashboard.api import DashboardAPI

    return DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False, audit_fn=lambda **k: None)


class NepRunner:
    def __init__(self, uitkomst):
        self.uitkomst = uitkomst
        self.gezien = []

    def start(self, tekst, hardop=False):
        self.gezien.append((tekst, hardop))
        return self.uitkomst


def test_api_opdracht():
    api = _api()
    api.opdrachten = NepRunner((True, None))
    assert api.opdracht({"tekst": "hoe laat is het", "hardop": True}) == (202, {"ok": True})
    assert api.opdrachten.gezien == [("hoe laat is het", True)]

    api.opdrachten = NepRunner((False, "bezig"))
    assert api.opdracht({"tekst": "x"})[0] == 409
    api.opdrachten = NepRunner((False, "ongeldig"))
    assert api.opdracht({"tekst": ""})[0] == 400
    assert api.opdracht({"tekst": "x", "hardop": "ja"})[0] == 400
    assert api.opdracht(["geen", "object"])[0] == 400


def test_status_bevat_taak(monkeypatch):
    api = _api()
    nu = {"t": 1000.0}
    monkeypatch.setattr(status.time, "time", lambda: nu["t"])
    status.zet_taak("Spotify op 30 procent zetten")
    assert api.status()[1]["taak"] == "Spotify op 30 procent zetten"
    status.zet_taak(None)
    nu["t"] += status.TAAK_NAGLOEI + 1
    assert api.status()[1]["taak"] is None


def test_route_alleen_bedienen():
    from dashboard.server import DashboardServer

    assert '("POST", "/api/command"): (b,' in inspect.getsource(DashboardServer)


def test_pwa_invoer():
    js = open(os.path.join(PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    html = open(os.path.join(PROJECT, "dashboard", "static", "index.html"), encoding="utf-8").read()
    assert "function verstuurOpdracht(" in js and "'/api/command'" in js
    assert "$('opdracht').disabled = !magBedienen();" in js
    assert 'id="hardop"' in html and 'id="verstuur"' in html and 'maxlength="300"' in html
    assert "typen volgt later" not in html
    # Het antwoord via textContent, nooit als HTML (zie toonGesprek).
    assert ".innerHTML" not in js


# ---------------------------------------------------------------
# Echt over TLS, met de echte server (zoals test_fase18_e2e)
# ---------------------------------------------------------------

from test_fase18_e2e import _verzoek, certs, omgeving  # noqa: E402,F401  (fixtures)


def _koppel(dashboard, poort, context, rol):
    code = dashboard.koppelcode.nieuw()
    st, _, set_cookie = _verzoek(poort, context, "POST", "/api/pair", body={"code": code, "rol": rol})
    assert st == 201
    return set_cookie.split(";")[0]


def test_e2e_typen_over_tls(omgeving):
    dashboard, poort, context, werk, caplog = omgeving
    dashboard.api.opdrachten = opdrachten.OpdrachtRunner(
        verwerk_fn=lambda t: "Het is vijf over twee, sir.", audit_fn=lambda **k: None)

    bedien = _koppel(dashboard, poort, context, "bedien")
    st, data, _ = _verzoek(poort, context, "POST", "/api/command", cookie=bedien,
                           body={"tekst": "Hoe laat is het?", "hardop": False})
    assert (st, data) == (202, {"ok": True})
    _wacht_tot_klaar(dashboard.api.opdrachten)
    assert [b["tekst"] for b in status.gesprek()[-2:]] == ["Hoe laat is het?", "Het is vijf over twee, sir."]

    # Ongeldige invoer en het kijk-token.
    assert _verzoek(poort, context, "POST", "/api/command", cookie=bedien, body={"tekst": "x" * 301})[0] == 400
    kijk = _koppel(dashboard, poort, context, "kijk")
    assert _verzoek(poort, context, "POST", "/api/command", cookie=kijk, body={"tekst": "hoi"})[0] == 403


def test_hardop_keuze_op_de_server(tmp_path):
    from dashboard.api import DashboardAPI, STANDAARD_WIDGETS

    api = DashboardAPI(widgets_pad=str(tmp_path / "dashboard.json"), fase_fn=lambda: "rust",
                       spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    config = {**STANDAARD_WIDGETS, "instellingen": {**STANDAARD_WIDGETS.get("instellingen", {}), "hardop": True}}
    assert api.widgets_opslaan(config)[0] == 200
    assert api.widgets()[1]["instellingen"]["hardop"] is True
    fout = {**config, "instellingen": {"hardop": "ja"}}
    assert api.widgets_opslaan(fout)[0] == 400

    js = open(os.path.join(PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    assert "function bewaarHardop(" in js and "zetHardop(inst.hardop === true);" in js


# ---------------------------------------------------------------
# Na de iPad-test: "zet spotify op 30"
# ---------------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "audio_set_session_volume", "audio_set_session_mute", "audio_toggle_session_mute",
    "game_pc_audio_set_session_volume", "game_pc_audio_set_session_mute", "game_pc_audio_toggle_session_mute",
])
def test_volume_per_app_vraagt_geen_ja_nee(tool):
    from core.tool_registry import get_tool_risk

    assert get_tool_risk(tool, {"app_name": "Spotify", "volume": 30}) == "low"


def test_open_vraag_slikt_nieuwe_opdracht_niet_in():
    from core import confirmation

    confirmation.set_pending("power_confirm", {"action": "sleep", "question": "slaapstand?"})
    gezien = []
    runner = opdrachten.OpdrachtRunner(verwerk_fn=lambda t: gezien.append(t) or "ok", audit_fn=lambda **k: None)
    runner.start("zet spotify op 30")
    _wacht_tot_klaar(runner)
    assert gezien == ["zet spotify op 30"]
    assert confirmation.get_pending() is None


def test_getypt_ja_blijft_het_antwoord():
    from core import confirmation

    confirmation.set_pending("power_confirm", {"action": "sleep", "question": "slaapstand?"})
    try:
        opdrachten._vervang_open_vraag("ja")
        assert confirmation.get_pending() is not None, "een getypt 'ja' laat de vraag staan voor het brein"
    finally:
        confirmation.clear_pending()


def test_ja_nee_vraag_verwijst_naar_het_venster():
    from core import confirmation

    confirmation.set_pending("tool_approval", {"tool_name": "move_file", "arguments": {}, "risk": "medium"})
    try:
        tekst = opdrachten._maak_dashboardvriendelijk(
            "Ik ga een bestand verplaatsen uitvoeren. Ga je akkoord? Zeg 'ja' of 'nee'.")
        assert "oranje venster" in tekst and "typ 'ja' of 'nee'" in tekst
    finally:
        confirmation.clear_pending()
    assert opdrachten._maak_dashboardvriendelijk("Zeg 'ja' of 'nee'.") == "Zeg 'ja' of 'nee'."


def test_pwa_toont_taak_ook_na_afloop():
    js = open(os.path.join(PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    status_fn = js.split("function toonStatus(")[1].split("\n  function ")[0]
    assert "if (s.taak) {" in status_fn
