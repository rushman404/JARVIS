"""Fase 21 — welke versie van JARVIS draait, in ⚙ Instellingen."""

import os
import shutil
import subprocess

import pytest

from dashboard import api as dapi

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "static")


def _api():
    return dapi.DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False, audit_fn=lambda **k: None)


class Uit:
    def __init__(self, stdout, code=0):
        self.stdout = stdout
        self.returncode = code


def test_lees_git_versie():
    gezien = []

    def run(cmd, **kw):
        gezien.append(cmd)
        return Uit("62a6ab4\x1f2026-10-26T18:24:05+01:00\x1ffeat(fase21): Spotify\n")

    assert dapi.lees_git_versie(run=run) == {
        "commit": "62a6ab4", "datum": "26-10-2026 18:24", "omschrijving": "feat(fase21): Spotify"}
    # Alleen lezen: nooit fetch/pull.
    assert gezien[0][:2] == ["git", "log"]


def test_zonder_git_onbekend():
    def kapot(cmd, **kw):
        raise FileNotFoundError("git")

    assert dapi.lees_git_versie(run=kapot) is None
    assert dapi.lees_git_versie(run=lambda c, **k: Uit("", 128)) is None


def test_versie_en_herstart_nodig(monkeypatch):
    monkeypatch.setattr(dapi, "_GESTART_MET", None)
    api = _api()
    status, data = api.versie(lambda: {"commit": "aaa1111", "datum": "26-10-2026 10:00", "omschrijving": "x"})
    assert status == 200 and data["commit"] == "aaa1111" and data["herstart_nodig"] is False
    assert data["dashboard"] == dapi.API_VERSIE
    # Na een git pull zonder herstart: de oude versie draait nog.
    status, data = api.versie(lambda: {"commit": "bbb2222", "datum": "", "omschrijving": ""})
    assert data["commit"] == "aaa1111" and data["herstart_nodig"] is True and data["op_schijf"] == "bbb2222"


def test_versie_onbekend(monkeypatch):
    monkeypatch.setattr(dapi, "_GESTART_MET", None)
    assert _api().versie(lambda: None)[1]["commit"] == "onbekend"


def test_route_alleen_voor_gekoppelde_apparaten():
    import inspect

    from dashboard.server import DashboardServer

    assert '("GET", "/api/versie"): (k,' in inspect.getsource(DashboardServer)


def test_instellingen_tonen_de_versie():
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'id="instVersie"' in html and 'id="instVersieTekst"' in html
    assert "api('/api/versie')" in js and "laadVersie();" in js
    assert ".innerHTML" not in js


def test_app_js_is_geldige_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is niet geïnstalleerd")
    uit = subprocess.run([node, "--check", os.path.join(STATIC, "app.js")], capture_output=True, text=True)
    assert uit.returncode == 0, uit.stderr
