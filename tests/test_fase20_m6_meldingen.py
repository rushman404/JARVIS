"""Fase 20, M6 — banner en geluidje bij een nieuwe melding in de app."""

import json
import os
import shutil
import subprocess

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PROJECT, "dashboard", "static")


def _lees(naam):
    return open(os.path.join(STATIC, naam), encoding="utf-8").read()


def _functie(js, naam):
    return "function " + naam + "(" + js.split(f"function {naam}(")[1].split("\n  function ")[0]


# ---------------------------------------------------------------
# De logica, echt uitgevoerd (Node)
# ---------------------------------------------------------------

def _draai(stappen, meld_geluid=True, nacht=False, tonen=True):
    """Voert nieuweMeldingen uit voor een reeks meldingenlijsten."""

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is niet geïnstalleerd")
    code = (
        "var staat = {gezien: null, meldingenTonen: %s, meldGeluid: %s, nachtAan: %s};\n"
        "var log = [];\n"
        "function toonBanner(t) { log.push(['banner', t]); }\n"
        "function speelGong() { log.push(['gong']); }\n"
        "%s\n"
        "%s.forEach(function (lijst) { nieuweMeldingen(lijst); });\n"
        "console.log(JSON.stringify(log));\n"
    ) % (json.dumps(tonen), json.dumps(meld_geluid), json.dumps(nacht),
         _functie(_lees("app.js"), "nieuweMeldingen"), json.dumps(stappen))
    uit = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=20)
    assert uit.returncode == 0, uit.stderr
    return json.loads(uit.stdout)


def m(i, tekst, gelezen=False):
    return {"id": i, "tekst": tekst, "gelezen": gelezen}


def test_bij_openen_geen_banner_daarna_wel():
    log = _draai([
        [m(1, "oud")],                         # bij het openen: al bekend
        [m(1, "oud"), m(2, "Uw timer is afgelopen.")],
    ])
    assert log == [["banner", "Uw timer is afgelopen."], ["gong"]]


def test_zelfde_melding_maar_een_keer():
    log = _draai([[], [m(5, "Pauze")], [m(5, "Pauze")], [m(5, "Pauze", gelezen=True)]])
    assert log == [["banner", "Pauze"], ["gong"]]


def test_meerdere_tegelijk_toont_de_nieuwste():
    log = _draai([[], [m(1, "eerste"), m(2, "tweede")]])
    assert log == [["banner", "tweede"], ["gong"]]


def test_s_nachts_of_uit_geen_geluid():
    assert _draai([[], [m(1, "x")]], nacht=True) == [["banner", "x"]]
    assert _draai([[], [m(1, "x")]], meld_geluid=False) == [["banner", "x"]]


def test_meldingen_uit_geen_banner():
    assert _draai([[], [m(1, "x")]], tonen=False) == []


def test_al_gelezen_geen_banner():
    assert _draai([[], [m(1, "x", gelezen=True)]]) == []


# ---------------------------------------------------------------
# Instelling, pagina en regels
# ---------------------------------------------------------------

def test_instelling_meldgeluid(tmp_path):
    from dashboard.api import STANDAARD_WIDGETS, DashboardAPI

    api = DashboardAPI(widgets_pad=str(tmp_path / "d.json"), fase_fn=lambda: "rust",
                       spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    config = json.loads(json.dumps(STANDAARD_WIDGETS))
    config["instellingen"]["meldgeluid"] = False
    assert api.widgets_opslaan(config)[0] == 200
    assert api.widgets()[1]["instellingen"]["meldgeluid"] is False
    config["instellingen"]["meldgeluid"] = "uit"
    assert api.widgets_opslaan(config)[0] == 400


def test_pagina():
    js = _lees("app.js")
    html = _lees("index.html")
    assert 'id="banner"' in html and 'id="instMeldGeluid"' in html
    assert "nieuweMeldingen(staat.meldingen);" in js
    # iOS: geluid pas na een tik; de banner opent de lijst.
    assert "document.addEventListener('touchend', ontgrendelGeluid);" in js
    assert "staat.nachtAan = !!actief;" in js
    assert ".innerHTML" not in js and "localStorage" not in js
    gong = _functie(js, "speelGong")
    assert "exponentialRampToValueAtTime(0.18" in gong  # zacht, geen volle sterkte


# ---------------------------------------------------------------
# Testmelding en bevestiging na de eerste tik
# ---------------------------------------------------------------

def test_testmelding_door_de_echte_keten():
    from dashboard.api import DashboardAPI

    api = DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    live = []
    api.melding_luisteraars.append(live.append)
    assert api.testmelding() == (200, {"ok": True})
    lijst = api.notificaties()[1]["meldingen"]
    assert lijst[0]["tekst"] == "Dit is een testmelding van JARVIS." and lijst[0]["bron"] == "test"
    assert live and live[0]["tekst"] == lijst[0]["tekst"], "de live-verbinding (SSE) krijgt hem ook"


def test_testmelding_route_alleen_bedienen():
    import inspect

    from dashboard.server import DashboardServer

    assert '("POST", "/api/notifications/test"): (b,' in inspect.getsource(DashboardServer)


def test_eerste_tik_geeft_bevestiging():
    js = _lees("app.js")
    ontgrendel = _functie(js, "ontgrendelGeluid")
    assert "toonBanner('Geluid voor meldingen staat aan.')" in ontgrendel and "speelGong()" in ontgrendel
    assert 'id="instTestMelding"' in _lees("index.html")


def test_versieophogen_raakt_geen_iconen():
    """Het tandwiel-icoon begint met "M19.4 15". Een te ruime zoek-en-vervang
    bij het ophogen van de versie veranderde dat getal mee (Fase 19-20)."""
    assert '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l' in _lees("index.html")
