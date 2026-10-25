"""Fase 20, M5 — het antwoord van JARVIS op de iPad."""

import json
import os
import re
import socket

import numpy as np
import pytest

from dashboard import websocket as ws
from voice import ipad_microfoon as im
from voice import speak

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Klok:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def ipad(monkeypatch):
    """Een verbonden iPad met een nep-wachtrij en een klok die 'slaapt'."""

    klok = Klok()
    monkeypatch.setattr(im.time, "sleep", lambda s: setattr(klok, "t", klok.t + max(s, 0.001)))
    p = im.IpadMicrofoon(bron_fn=lambda: None, klok=klok)
    sessie = p.nieuwe_sessie()
    p.verzonden = []
    p.koppel_uitvoer(sessie, p.verzonden.append)
    p.verwerk(sessie, np.zeros(10, np.int16).tobytes())  # recent geluid = verbonden
    p.sessie = sessie
    p.klok_obj = klok
    return p


def _ontleed(frame):
    """Ontleedt een ongemaskeerd serverframe: (opcode, payload)."""

    n = frame[1] & 0x7F
    kop = 2
    if n == 126:
        n, kop = int.from_bytes(frame[2:4], "big"), 4
    elif n == 127:
        n, kop = int.from_bytes(frame[2:10], "big"), 10
    return frame[0] & 0x0F, frame[kop:kop + n]


# ---------------------------------------------------------------
# De iPad als speaker
# ---------------------------------------------------------------

def test_speel_stuurt_geluid_met_samplefrequentie(ipad):
    geluid = (np.arange(22050) % 100).astype(np.int16)  # 1 s
    begin = ipad.klok_obj.t
    assert ipad.speel(geluid, 22050) is True
    opcode, payload = _ontleed(ipad.verzonden[0])
    assert opcode == ws.OP_BINAIR
    assert int.from_bytes(payload[:4], "little") == 22050
    assert np.array_equal(np.frombuffer(payload[4:], np.int16), geluid)
    # Wacht tot vlak voor het einde (naadloze volgende zin) ...
    assert 0.8 <= ipad.klok_obj.t - begin <= 0.9
    # ... en wacht_tot_stil daarna tot het écht stil is (+ marge).
    ipad.wacht_tot_stil()
    assert ipad.klok_obj.t - begin >= 1.29


def test_zinnen_sluiten_op_elkaar_aan(ipad):
    begin = ipad.klok_obj.t
    for _ in range(3):
        ipad.speel(np.zeros(11025, np.int16), 22050)  # 3 x 0,5 s
    ipad.wacht_tot_stil(marge=0.0)
    assert abs((ipad.klok_obj.t - begin) - 1.5) < 0.1
    assert len(ipad.verzonden) == 3


def test_onderbreken_stuurt_stop(ipad):
    tellen = {"n": 0}

    def gestopt():
        tellen["n"] += 1
        return tellen["n"] > 3

    ipad.speel(np.zeros(22050 * 5, np.int16), 22050, gestopt)
    soorten = [_ontleed(f) for f in ipad.verzonden]
    assert soorten[-1] == (ws.OP_TEKST, json.dumps({"type": "stop"}).encode())


def test_geen_uitvoer_dan_terug_naar_het_brein():
    p = im.IpadMicrofoon(bron_fn=lambda: None, klok=Klok())
    p.nieuwe_sessie()
    assert p.kan_spreken() is False
    assert p.speel(np.zeros(100, np.int16), 22050) is False


def test_spreker_uit_via_hallo(ipad):
    assert ipad.kan_spreken()
    ipad.bericht(ipad.sessie, b'{"type": "hallo", "spreker": false}')
    assert not ipad.kan_spreken()
    ipad.bericht(ipad.sessie, b'{"type": "hallo", "spreker": true}')
    assert ipad.kan_spreken()
    for rommel in (b"geen json", b"[]", b'{"type": "anders", "spreker": false}', b'{"type": "hallo", "spreker": "nee"}'):
        ipad.bericht(ipad.sessie, rommel)
    assert ipad.kan_spreken()


def test_niet_verbonden_of_gesloten(ipad):
    ipad.klok_obj.t += 10  # al lang geen microfoongeluid
    assert not ipad.kan_spreken()
    ipad.verwerk(ipad.sessie, np.zeros(10, np.int16).tobytes())
    assert ipad.kan_spreken()
    ipad.sluit(ipad.sessie)
    assert not ipad.kan_spreken()


# ---------------------------------------------------------------
# speak(): iPad of de speaker van het brein
# ---------------------------------------------------------------

class NepIpad:
    def __init__(self, kan=True, lukt=True):
        self.kan = kan
        self.lukt = lukt
        self.gespeeld = []
        self.stops = 0
        self.stil = 0

    def kan_spreken(self):
        return self.kan

    def speel(self, samples, rate, gestopt=None, vooruit=0.15):
        self.gespeeld.append((len(np.asarray(samples).reshape(-1)), rate))
        return self.lukt

    def wacht_tot_stil(self, gestopt=None, marge=0.3):
        self.stil += 1

    def stop_afspelen(self):
        self.stops += 1


@pytest.fixture
def lokaal(monkeypatch):
    gespeeld = []
    monkeypatch.setattr(speak.sd, "play", lambda *a, **k: gespeeld.append(a))
    monkeypatch.setattr(speak.sd, "wait", lambda: None)
    monkeypatch.setattr(speak.sd, "stop", lambda: None)
    return gespeeld


def test_play_naar_de_ipad(monkeypatch, lokaal):
    nep = NepIpad()
    monkeypatch.setattr(im, "peek_ipad_microfoon", lambda: nep)
    speak._play(np.zeros(500, np.int16), 22050)
    assert nep.gespeeld == [(500, 22050)] and lokaal == []


def test_play_valt_terug_op_het_brein(monkeypatch, lokaal):
    for nep in (None, NepIpad(kan=False), NepIpad(lukt=False)):
        lokaal.clear()
        monkeypatch.setattr(im, "peek_ipad_microfoon", lambda nep=nep: nep)
        speak._play(np.zeros(500, np.int16), 22050)
        assert len(lokaal) == 1


def test_piep_ook_op_de_ipad(monkeypatch, lokaal):
    nep = NepIpad()
    monkeypatch.setattr(im, "peek_ipad_microfoon", lambda: nep)
    speak._beep()
    assert nep.gespeeld and lokaal == [] and nep.stil == 1


def test_speak_wacht_tot_de_ipad_stil_is_en_stop(monkeypatch, lokaal):
    nep = NepIpad()
    monkeypatch.setattr(im, "peek_ipad_microfoon", lambda: nep)
    monkeypatch.setattr(speak, "_say", lambda text, stop_event=None: None)
    monkeypatch.setattr(speak, "_duck", lambda: None)
    monkeypatch.setattr(speak, "_herstel_volume", lambda: None)
    speak.speak("Goedenavond, sir.")
    assert nep.stil == 1
    speak.stop_speaking()
    assert nep.stops == 1


# ---------------------------------------------------------------
# De verbinding: lezen en tussendoor schrijven
# ---------------------------------------------------------------

def test_socketlezer():
    a, b = socket.socketpair()
    try:
        lezer = ws.SocketLezer(a)
        assert lezer.klaar(0.01) is False
        b.sendall(ws.masker_frame(ws.OP_BINAIR, b"abcdef") + ws.masker_frame(ws.OP_TEKST, "k"))
        assert lezer.klaar(0.5) is True
        assert ws.lees_frame(lezer, 1000) == (ws.OP_BINAIR, b"abcdef")
        assert lezer.klaar(0.0) is True  # het tweede frame zit al in de buffer
        assert ws.lees_frame(lezer, 1000) == (ws.OP_TEKST, b"k")
        b.close()
        with pytest.raises(ws.WebSocketFout):
            ws.lees_frame(lezer, 1000)
    finally:
        a.close()


from test_fase18_e2e import _verzoek, certs, omgeving  # noqa: E402,F401  (fixtures)


def test_e2e_geluid_naar_de_ipad(omgeving, monkeypatch):
    import select
    import time

    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    dashboard, poort, context, werk, caplog = omgeving
    p = im.IpadMicrofoon(bron_fn=lambda: None)
    dashboard.ipad_microfoon_fn = lambda: p
    code = dashboard.koppelcode.nieuw()
    _, _, set_cookie = _verzoek(poort, context, "POST", "/api/pair", body={"code": code, "rol": "bedien"})
    cookie = set_cookie.split(";")[0]

    import base64

    sok = context.wrap_socket(socket.create_connection(("127.0.0.1", poort), timeout=5), server_hostname="127.0.0.1")
    sok.sendall((f"GET /api/spraak/stroom HTTP/1.1\r\nHost: 127.0.0.1:{poort}\r\nUpgrade: websocket\r\n"
                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n"
                 f"Sec-WebSocket-Version: 13\r\nOrigin: https://127.0.0.1:{poort}\r\nCookie: {cookie}\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sok.recv(1024)
    buf = buf.split(b"\r\n\r\n", 1)[1]
    sok.sendall(ws.masker_frame(ws.OP_TEKST, '{"type":"hallo","spreker":true}'))
    sok.sendall(ws.masker_frame(ws.OP_BINAIR, np.zeros(1486, np.int16).tobytes()))
    eind = time.time() + 3
    while not p.kan_spreken() and time.time() < eind:
        time.sleep(0.02)
    assert p.kan_spreken()

    assert p.speel(np.arange(300, dtype=np.int16), 22050, vooruit=1.0)
    eind = time.time() + 3
    while time.time() < eind:
        if sok.pending() or select.select([sok], [], [], 0.05)[0]:
            buf += sok.recv(65536)
        if len(buf) >= 2 + 2 + 4 + 600:
            break
    opcode, payload = _ontleed(buf)
    assert opcode == ws.OP_BINAIR and int.from_bytes(payload[:4], "little") == 22050
    assert np.array_equal(np.frombuffer(payload[4:604], np.int16), np.arange(300, dtype=np.int16))
    sok.close()


# ---------------------------------------------------------------
# Het spraakpaneel
# ---------------------------------------------------------------

def test_paneel_speelt_af_en_luistert_dan_niet():
    js = open(os.path.join(PROJECT, "dashboard", "static", "spraak.js"), encoding="utf-8").read()
    html = open(os.path.join(PROJECT, "dashboard", "static", "spraak.html"), encoding="utf-8").read()
    assert "function speel(" in js and "getUint32(0, true)" in js and "createBufferSource" in js
    assert "if (speeltAf()) { return; }" in js          # geen echo naar het brein
    assert "m.type === 'stop'" in js and "function stopAfspelen(" in js
    assert "type: 'hallo', spreker:" in js
    assert 'id="spreker"' in html
    assert "=>" not in js and not re.search(r"\b(let|const|class)\s", js)


# ---------------------------------------------------------------
# Na de iPad-test: het antwoord viel na ±3 s terug naar de laptop
# ---------------------------------------------------------------

def test_spreken_blijft_op_de_ipad_zonder_microfoongeluid(ipad):
    """Tijdens het afspelen stuurt het paneel geen geluid, alleen elke 3 s
    een levensteken. Dan moet JARVIS gewoon op de iPad blijven praten."""
    for _ in range(4):
        ipad.klok_obj.t += 3
        ipad.levensteken(ipad.sessie)
        assert ipad.kan_spreken(), "na een levensteken blijft de iPad de speaker"
    assert not ipad.verbonden(), "de microfoon telt wel alleen echt geluid"


def test_zonder_enig_bericht_terug_naar_het_brein(ipad):
    ipad.klok_obj.t += im.LEVEND_SECONDEN + 0.1
    assert not ipad.kan_spreken()


def test_levensteken_van_oude_sessie_telt_niet(ipad):
    oud = ipad.sessie
    ipad.klok_obj.t += im.LEVEND_SECONDEN + 1   # alles verouderd
    ipad.nieuwe_sessie()
    ipad.levensteken(oud)                        # oude verbinding: telt niet
    assert ipad.klok_obj.t - ipad._laatste_bericht > im.LEVEND_SECONDEN


def test_status_toont_route(ipad, monkeypatch):
    from dashboard.api import DashboardAPI

    monkeypatch.setattr(im, "peek_ipad_microfoon", lambda: ipad)
    s = DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False).status()[1]
    assert s["ipad"] == {"microfoon": True, "speaker": True}
    monkeypatch.setattr(im, "peek_ipad_microfoon", lambda: None)
    s = DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False).status()[1]
    assert s["ipad"] == {"microfoon": False, "speaker": False}


def test_server_geeft_levensteken_bij_elk_bericht():
    import inspect

    from dashboard.server import _DashboardHandler as DashboardHandler

    bron = inspect.getsource(DashboardHandler._websocket)
    assert "levensteken" in bron.split("ws.lees_frame(lezer")[1].split("OP_BINAIR")[0]


def test_paneel_toont_route():
    js = open(os.path.join(PROJECT, "dashboard", "static", "spraak.js"), encoding="utf-8").read()
    assert "'Microfoon: '" in js and "' · Speaker: '" in js
