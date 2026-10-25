"""Fase 20, M3 — proef met de iPad als microfoon en speaker."""

import base64
import inspect
import os
import re

import numpy as np
import pytest

from dashboard import spraakproef as sp

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PROJECT, "dashboard", "static")


def _pcm(samples):
    return base64.b64encode(np.asarray(samples, dtype=np.int16).tobytes()).decode()


class Klok:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _proef(**kw):
    kw.setdefault("wake_fn", lambda s: 0.9)
    kw.setdefault("herken_fn", lambda s: "hey jarvis hoe laat is het")
    kw.setdefault("testzin_fn", lambda: b"RIFF....WAVE")
    return sp.SpraakProef(**kw)


def _toon(seconden, hz=220, sterkte=8000):
    t = np.arange(int(sp.RATE * seconden)) / sp.RATE
    return (np.sin(2 * np.pi * hz * t) * sterkte).astype(np.int16)


# ---------------------------------------------------------------
# Meten
# ---------------------------------------------------------------

def test_meet_niveau_en_oversturing():
    stil = sp.meet(np.zeros(1000, dtype=np.int16))
    assert stil["rms_dbfs"] == -120.0 and stil["oversturing"] == 0.0
    toon = sp.meet(_toon(0.5, sterkte=16384))
    assert -10 < toon["rms_dbfs"] < -8 and -7 < toon["piek_dbfs"] < -5
    vol = sp.meet(np.full(1000, 32767, dtype=np.int16))
    assert vol["oversturing"] == 100.0


def test_volledige_proef():
    p = _proef()
    st, d = p.start()
    assert st == 200 and d["rate"] == 16000
    audio = _toon(2)
    for seq, i in enumerate(range(0, audio.size, 4000)):
        assert p.stuk({"id": d["id"], "seq": seq, "t": seq * 250, "pcm": _pcm(audio[i:i + 4000])})[0] == 200
    st, u = p.klaar({"id": d["id"]})
    assert st == 200
    assert u["seconden"] == 2.0 and u["stukken"] == 8 and u["ontbrekend"] == 0
    assert u["wake_word_score"] == 0.9 and u["herkend"] == "hey jarvis hoe laat is het"
    assert u["oordeel"].startswith("Goed")
    # Na "klaar" is de proef weg (er wordt niets bewaard).
    assert p.klaar({"id": d["id"]})[0] == 404


def test_ontbrekende_stukjes_en_slecht_oordeel():
    p = _proef(wake_fn=lambda s: 0.1)
    _, d = p.start()
    p.stuk({"id": d["id"], "seq": 0, "pcm": _pcm(np.zeros(4000))})
    p.stuk({"id": d["id"], "seq": 2, "pcm": _pcm(np.zeros(4000))})
    _, u = p.klaar({"id": d["id"]})
    assert u["ontbrekend"] == 1
    assert "niet aan" in u["oordeel"] and "erg zacht" in u["oordeel"] and "Hey JARVIS" in u["oordeel"]


@pytest.mark.parametrize("body", [
    None, {"seq": 0, "pcm": "AAAA"}, {"id": "x", "seq": -1, "pcm": "AAAA"},
    {"id": "x", "seq": True, "pcm": "AAAA"}, {"id": "x", "seq": 0, "pcm": "niet-base64!"},
    {"id": "x", "seq": 0, "pcm": base64.b64encode(b"abc").decode()},  # oneven: geen 16-bit
    {"id": "x", "seq": 0, "pcm": _pcm(np.zeros(sp.RATE + 1))},  # meer dan 1 s
])
def test_ongeldige_stukjes(body):
    p = _proef()
    p.start()
    assert p.stuk(body)[0] in (400, 404)


def test_hoogstens_tien_seconden():
    p = _proef()
    _, d = p.start()
    for seq in range(sp.MAX_SECONDEN):
        assert p.stuk({"id": d["id"], "seq": seq, "pcm": _pcm(np.zeros(sp.RATE))})[0] == 200
    assert p.stuk({"id": d["id"], "seq": sp.MAX_SECONDEN, "pcm": _pcm(np.zeros(100))})[0] == 413


def test_een_proef_tegelijk_en_verlopen():
    klok = Klok()
    p = _proef(klok=klok)
    _, oud = p.start()
    _, nieuw = p.start()
    assert p.stuk({"id": oud["id"], "seq": 0, "pcm": _pcm(np.zeros(10))})[0] == 404
    klok.t += sp.VERLOOPT_NA + 1
    assert p.stuk({"id": nieuw["id"], "seq": 0, "pcm": _pcm(np.zeros(10))})[0] == 404


def test_leeg_en_fouten_in_wake_en_herkenning():
    def stuk(s):
        raise RuntimeError

    p = _proef(wake_fn=stuk, herken_fn=stuk)
    _, d = p.start()
    assert p.klaar({"id": d["id"]})[0] == 400  # niets ontvangen
    _, d = p.start()
    p.stuk({"id": d["id"], "seq": 0, "pcm": _pcm(_toon(0.5))})
    _, u = p.klaar({"id": d["id"]})
    assert u["wake_word_score"] is None and u["herkend"] is None


def test_testzin_eenmalig_gemaakt():
    gemaakt = []
    p = _proef(testzin_fn=lambda: gemaakt.append(1) or b"RIFFwav")
    assert p.testzin() == (b"RIFFwav", None)
    assert p.testzin() == (b"RIFFwav", None)
    assert gemaakt == [1]

    def stuk():
        raise RuntimeError("geen piper")

    assert p.__class__(testzin_fn=stuk).testzin()[0] is None


# ---------------------------------------------------------------
# Server en routes
# ---------------------------------------------------------------

def test_routes_alleen_bedienen():
    from dashboard.server import DashboardServer

    bron = inspect.getsource(DashboardServer)
    for pad in ("/api/spraak/proef/start", "/api/spraak/proef/stuk", "/api/spraak/proef/klaar"):
        assert f'("POST", "{pad}"): (b,' in bron
    assert '("GET", "/api/spraak/proef/testzin.wav"): (b,' in bron


def test_wav_antwoord():
    from dashboard.server import _wav

    a = _wav(200, b"RIFFdata")
    assert a.status == 200 and a.header("Content-Type") == "audio/wav" and a.body == b"RIFFdata"
    f = _wav(503, {"ok": False})
    assert f.status == 503 and "json" in f.header("Content-Type")


from test_fase18_e2e import _verzoek, certs, omgeving  # noqa: E402,F401  (fixtures)


def test_e2e_proef_over_tls(omgeving):
    import http.client

    dashboard, poort, context, werk, caplog = omgeving
    dashboard.api._spraakproef = _proef()
    code = dashboard.koppelcode.nieuw()
    _, _, set_cookie = _verzoek(poort, context, "POST", "/api/pair", body={"code": code, "rol": "bedien"})
    cookie = set_cookie.split(";")[0]

    st, d, _ = _verzoek(poort, context, "POST", "/api/spraak/proef/start", cookie=cookie, body={})
    assert st == 200
    audio = _toon(1)
    for seq, i in enumerate(range(0, audio.size, 4000)):
        assert _verzoek(poort, context, "POST", "/api/spraak/proef/stuk", cookie=cookie,
                        body={"id": d["id"], "seq": seq, "pcm": _pcm(audio[i:i + 4000])})[0] == 200
    st, u, _ = _verzoek(poort, context, "POST", "/api/spraak/proef/klaar", cookie=cookie, body={"id": d["id"]})
    assert st == 200 and u["stukken"] == 4

    c = http.client.HTTPSConnection("127.0.0.1", poort, context=context, timeout=5)
    c.request("GET", "/api/spraak/proef/testzin.wav", headers={"Cookie": cookie})
    a = c.getresponse()
    assert a.status == 200 and a.getheader("Content-Type") == "audio/wav" and a.read() == b"RIFF....WAVE"
    c.close()

    # Een stukje van 0,25 s (base64 in JSON) past ruim binnen de bodylimiet.
    stuk = {"id": "x" * 16, "seq": 0, "t": 0, "pcm": _pcm(np.zeros(4000))}
    import json

    from dashboard.server import MAX_BODY_BYTES

    assert len(json.dumps(stuk)) < MAX_BODY_BYTES


# ---------------------------------------------------------------
# De pagina
# ---------------------------------------------------------------

def test_pagina_volgt_de_regels():
    from dashboard.api import API_VERSIE

    html = open(os.path.join(STATIC, "spraak-proef.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "spraak-proef.js"), encoding="utf-8").read()
    refs = re.findall(r'(?:href|src)="(/[^"]+)"', html)
    assert refs and all(r.endswith(f"?v={API_VERSIE}") for r in refs)
    assert "<script>" not in html and " style=" not in html and "onclick" not in html
    assert ".innerHTML" not in js and "localStorage" not in js and "Authorization" not in js
    assert "credentials: 'same-origin'" in js
    # iOS 12: geen pijlfuncties, let/const of class (ES5 zoals app.js).
    assert "=>" not in js and not re.search(r"\b(let|const|class)\s", js)
    assert "webkitAudioContext" in js and "createScriptProcessor" in js
