"""Fase 20, M4 — de iPad als microfoon (WebSocket-spraakstroom)."""

import base64
import io
import os
import re
import socket
import ssl

import numpy as np
import pytest

from dashboard import websocket as ws
from voice.audio_stream import AudioSource
from voice.ipad_microfoon import FRAME, FRAME_SECONDEN, IpadMicrofoon

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PROJECT, "dashboard", "static")


# ---------------------------------------------------------------
# WebSocket-frames
# ---------------------------------------------------------------

def test_accept_sleutel_volgens_rfc():
    # Het voorbeeld uit RFC 6455, §1.3.
    assert ws.accept_sleutel("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    for fout in (None, "", "geen-base64!", base64.b64encode(b"kort").decode()):
        with pytest.raises(ws.WebSocketFout):
            ws.accept_sleutel(fout)


@pytest.mark.parametrize("lengte", [0, 5, 125, 126, 3000, 70000])
def test_frame_heen_en_terug(lengte):
    data = bytes(range(256)) * (lengte // 256 + 1)
    data = data[:lengte]
    opcode, payload = ws.lees_frame(io.BytesIO(ws.masker_frame(ws.OP_BINAIR, data)), 100000)
    assert (opcode, payload) == (ws.OP_BINAIR, data)


def test_frames_die_geweigerd_worden():
    ongemaskeerd = ws.maak_frame(ws.OP_BINAIR, b"abc")
    with pytest.raises(ws.WebSocketFout, match="gemaskeerd"):
        ws.lees_frame(io.BytesIO(ongemaskeerd), 1000)
    with pytest.raises(ws.WebSocketFout, match="te groot"):
        ws.lees_frame(io.BytesIO(ws.masker_frame(ws.OP_BINAIR, b"x" * 2000)), 1000)
    gefragmenteerd = bytearray(ws.masker_frame(ws.OP_BINAIR, b"abc"))
    gefragmenteerd[0] &= 0x7F  # FIN uit
    with pytest.raises(ws.WebSocketFout, match="Gefragmenteerd"):
        ws.lees_frame(io.BytesIO(bytes(gefragmenteerd)), 1000)
    with pytest.raises(ws.WebSocketFout, match="controleframe"):
        ws.lees_frame(io.BytesIO(ws.masker_frame(ws.OP_PING, b"x" * 200)), 1000)
    with pytest.raises(ws.WebSocketFout, match="gesloten"):
        ws.lees_frame(io.BytesIO(b"\x82"), 1000)


def test_server_frames_zijn_ongemaskeerd():
    frame = ws.maak_frame(ws.OP_PONG, b"hoi")
    assert frame == b"\x8a\x03hoi"


# ---------------------------------------------------------------
# De audiobron
# ---------------------------------------------------------------

def test_bron_zonder_pc_microfoon(monkeypatch):
    def mag_niet(self):
        raise AssertionError("de pc-microfoon mag niet open")

    monkeypatch.setattr(AudioSource, "_open_stream", mag_niet)
    bron = AudioSource(lokaal=False)
    bron.start()
    try:
        assert bron.is_running()
        bron.feed(np.zeros(FRAME, np.int16), ts=5.0, extern=True)
        assert bron.read_frame(after_ts=0, timeout=0.1)[0] == 5.0
    finally:
        bron.stop()


def test_extern_tijdens_spreken_altijd_weg():
    bron = AudioSource(lokaal=False)
    bron.mute()
    bron.set_barge_in(True)
    bron.feed(np.ones(FRAME, np.int16), ts=1.0, extern=True)   # iPad: weg
    bron.feed(np.ones(FRAME, np.int16), ts=2.0)                # pc + barge-in: bewaard
    assert [ts for ts, _ in bron._frames] == [2.0]


def test_markeer_extern():
    bron = AudioSource(lokaal=False)
    assert not bron.extern_actief()
    bron.markeer_extern(5)
    assert bron.extern_actief()


def test_pc_microfoon_pauzeert_als_de_ipad_levert(monkeypatch):
    """De lees-thread slaat pc-frames over zolang de iPad levert."""

    class NepStream:
        def __init__(self):
            self.n = 0

        def read(self, n):
            self.n += 1
            if self.n > 3:
                bron._running = False
            return np.ones((n, 1), np.int16), False

    bron = AudioSource()
    bron._running = True
    bron._stream = NepStream()
    bron.markeer_extern(5)
    bron._reader()
    assert len(bron._frames) == 0

    bron._running = True
    bron._extern_tot = 0.0
    bron._stream = NepStream()
    bron._reader()
    assert len(bron._frames) == 4  # elke leesbeurt (ook de laatste) komt nu door


# ---------------------------------------------------------------
# De iPad-microfoon
# ---------------------------------------------------------------

class Klok:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _bron():
    return AudioSource(lokaal=False)


def test_frames_van_80_ms_en_rest_bewaard():
    bron, klok = _bron(), Klok()
    ipad = IpadMicrofoon(bron_fn=lambda: bron, klok=klok)
    s = ipad.nieuwe_sessie()
    assert ipad.verwerk(s, np.zeros(2000, np.int16).tobytes())   # 1 frame + 720 over
    assert len(bron._frames) == 1 and ipad._rest.size == 2000 - FRAME
    assert ipad.verwerk(s, np.zeros(600, np.int16).tobytes())    # 1320 -> 1 frame + 40
    assert len(bron._frames) == 2 and ipad._rest.size == 40
    assert bron.extern_actief()


def test_tijdstippen_oplopend_ook_bij_groepjes():
    bron, klok = _bron(), Klok()
    ipad = IpadMicrofoon(bron_fn=lambda: bron, klok=klok)
    s = ipad.nieuwe_sessie()
    bron.feed(np.zeros(FRAME, np.int16), ts=klok.t + 0.5)  # al iets in de buffer, later tijdstip
    for _ in range(3):
        ipad.verwerk(s, np.zeros(FRAME * 4, np.int16).tobytes())  # 4 frames tegelijk
        klok.t += 0.05
    stempels = [ts for ts, _ in bron._frames]
    assert stempels == sorted(stempels) and len(set(stempels)) == len(stempels)
    verschillen = np.diff(stempels[1:])
    assert np.allclose(verschillen, FRAME_SECONDEN, atol=0.002)


def test_oude_sessie_en_ongeldige_data():
    bron = _bron()
    ipad = IpadMicrofoon(bron_fn=lambda: bron, klok=Klok())
    oud = ipad.nieuwe_sessie()
    nieuw = ipad.nieuwe_sessie()
    assert ipad.verwerk(oud, np.zeros(FRAME, np.int16).tobytes()) is False
    assert ipad.verwerk(nieuw, b"abc") is False                     # geen 16-bit
    assert ipad.verwerk(nieuw, np.zeros(16001, np.int16).tobytes()) is False  # > 1 s
    assert ipad.verwerk(nieuw, "tekst") is False
    assert ipad.verwerk(nieuw, np.zeros(FRAME, np.int16).tobytes()) is True
    ipad.sluit(nieuw)
    assert ipad.verwerk(nieuw, np.zeros(FRAME, np.int16).tobytes()) is False


def test_verbonden():
    klok = Klok()
    ipad = IpadMicrofoon(bron_fn=_bron, klok=klok)
    assert not ipad.verbonden()
    s = ipad.nieuwe_sessie()
    ipad.verwerk(s, np.zeros(10, np.int16).tobytes())
    assert ipad.verbonden()
    klok.t += 10
    assert not ipad.verbonden()


# ---------------------------------------------------------------
# De server: handdruk en beveiliging
# ---------------------------------------------------------------

def _server():
    from dashboard import auth
    from dashboard.api import DashboardAPI
    from dashboard.server import DashboardServer, standaard_hosts, standaard_origins

    hosts = standaard_hosts(8780, "192.168.2.19")
    return DashboardServer(
        api=DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False),
        authenticator=auth.Authenticator("kijk-token-0123456789abcd", "bedien-token-0123456789abcd",
                                         auth.ApparaatRegister(os.path.join(PROJECT, "tests", "_niet_bestaand.json"))),
        koppelcode=auth.Koppelcode(300), allowed_hosts=hosts, allowed_origins=standaard_origins(hosts),
    )


def _kop(token="bedien-token-0123456789abcd", **extra):
    kop = {
        "Host": "192.168.2.19:8780", "Origin": "https://192.168.2.19:8780",
        "Upgrade": "websocket", "Connection": "keep-alive, Upgrade", "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Authorization": f"Bearer {token}",
    }
    kop.update(extra)
    return {k: v for k, v in kop.items() if v is not None}


def test_handdruk(monkeypatch):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    srv = _server()
    srv.ipad_microfoon_fn = lambda: "nep-ipad"
    a = srv.process("GET", "/api/spraak/stroom", _kop(), client_ip="192.168.2.59")
    assert a.status == 101
    assert a.header("Sec-WebSocket-Accept") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    assert a.websocket["ipad"] == "nep-ipad" and a.websocket["kaartje_fn"] == srv.neem_kaartje


@pytest.mark.parametrize("kop, status", [
    (_kop(Origin="https://evil.example"), 403),           # ander dashboard
    (_kop(Origin=None), 403),
    (_kop(Upgrade=None), 400),
    (_kop(**{"Sec-WebSocket-Version": "8"}), 400),
    (_kop(**{"Sec-WebSocket-Key": "kapot"}), 400),
])
def test_handdruk_geweigerd(monkeypatch, kop, status):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    assert _server().process("GET", "/api/spraak/stroom", kop, client_ip="192.168.2.59").status == status


# ---------------------------------------------------------------
# Kaartjes (Safari stuurt de cookie niet altijd mee met een WebSocket)
# ---------------------------------------------------------------

def test_handdruk_zonder_cookie(monkeypatch):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    srv = _server()
    srv.ipad_microfoon_fn = lambda: "nep-ipad"
    kop = _kop()
    del kop["Authorization"]
    assert srv.process("GET", "/api/spraak/stroom", kop, client_ip="192.168.2.59").status == 101


def _kaartje_kop(token):
    return {"Host": "192.168.2.19:8780", "Origin": "https://192.168.2.19:8780",
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_kaartje_alleen_voor_bedienen(monkeypatch):
    import json

    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    srv = _server()
    kijk = srv.process("POST", "/api/spraak/kaartje", _kaartje_kop("kijk-token-0123456789abcd"), b"{}",
                       client_ip="192.168.2.59")
    assert kijk.status == 403
    geen = srv.process("POST", "/api/spraak/kaartje", {"Host": "192.168.2.19:8780",
                       "Origin": "https://192.168.2.19:8780", "Content-Type": "application/json"}, b"{}",
                       client_ip="192.168.2.59")
    assert geen.status == 401
    a = srv.process("POST", "/api/spraak/kaartje", _kaartje_kop("bedien-token-0123456789abcd"), b"{}",
                    client_ip="192.168.2.59")
    assert a.status == 200
    kaartje = json.loads(a.body)["kaartje"]
    assert len(kaartje) >= 30
    nog_geldig = srv.neem_kaartje(kaartje)
    assert nog_geldig is not None and nog_geldig()
    assert srv.neem_kaartje(kaartje) is None, "een kaartje werkt maar één keer"
    assert srv.neem_kaartje("verzonnen") is None and srv.neem_kaartje(None) is None


def test_kaartje_verloopt(monkeypatch):
    import json

    import config
    from dashboard import server as srv_mod

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    srv = _server()
    a = srv.process("POST", "/api/spraak/kaartje", _kaartje_kop("bedien-token-0123456789abcd"), b"{}",
                    client_ip="192.168.2.59")
    kaartje = json.loads(a.body)["kaartje"]
    echt = srv_mod.time.monotonic
    monkeypatch.setattr(srv_mod.time, "monotonic", lambda: echt() + srv_mod.KAARTJE_SECONDEN + 1)
    assert srv.neem_kaartje(kaartje) is None


def test_kaartje_niet_bij_mic_bron_pc(monkeypatch):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "pc")
    a = _server().process("POST", "/api/spraak/kaartje", _kaartje_kop("bedien-token-0123456789abcd"), b"{}",
                          client_ip="192.168.2.59")
    assert a.status == 403


def test_mic_bron_pc_weigert_de_ipad(monkeypatch):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "pc")
    assert _server().process("GET", "/api/spraak/stroom", _kop(), client_ip="192.168.2.59").status == 403


def test_csp_staat_alleen_eigen_wss_toe():
    srv = _server()
    connect = srv.csp.split("connect-src")[1].split(";")[0]
    assert "wss://192.168.2.19:8780" in connect and "'self'" in connect
    assert "wss: " not in connect + " " and "*" not in connect
    assert "unsafe-inline" not in srv.csp


from test_fase18_e2e import _verzoek, certs, omgeving  # noqa: E402,F401  (fixtures)


def test_e2e_spraakstroom_over_tls(omgeving, monkeypatch):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    dashboard, poort, context, werk, caplog = omgeving
    ontvangen = []

    class NepIpad:
        def nieuwe_sessie(self):
            return "s1"

        def verwerk(self, sessie, data):
            ontvangen.append(data)
            return True

        def sluit(self, sessie):
            ontvangen.append("dicht")

    dashboard.ipad_microfoon_fn = NepIpad
    code = dashboard.koppelcode.nieuw()
    _, _, set_cookie = _verzoek(poort, context, "POST", "/api/pair", body={"code": code, "rol": "bedien"})
    cookie = set_cookie.split(";")[0]

    st, d, _ = _verzoek(poort, context, "POST", "/api/spraak/kaartje", cookie=cookie, body={})
    assert st == 200
    # Zoals Safari: de WebSocket zélf zonder cookie; het kaartje als eerste bericht.
    sok = context.wrap_socket(socket.create_connection(("127.0.0.1", poort), timeout=5), server_hostname="127.0.0.1")
    sleutel = base64.b64encode(os.urandom(16)).decode()
    sok.sendall((f"GET /api/spraak/stroom HTTP/1.1\r\nHost: 127.0.0.1:{poort}\r\nUpgrade: websocket\r\n"
                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {sleutel}\r\nSec-WebSocket-Version: 13\r\n"
                 f"Origin: https://127.0.0.1:{poort}\r\n\r\n").encode())
    kop = b""
    while b"\r\n\r\n" not in kop:
        kop += sok.recv(1024)
    assert kop.startswith(b"HTTP/1.1 101") and ws.accept_sleutel(sleutel).encode() in kop
    assert b"wss://127.0.0.1:" in kop  # de CSP op dit antwoord kent de eigen wss
    sok.sendall(ws.masker_frame(ws.OP_TEKST, '{"type": "kaartje", "kaartje": "%s"}' % d["kaartje"]))

    geluid = np.arange(1486, dtype=np.int16).tobytes()
    sok.sendall(ws.masker_frame(ws.OP_BINAIR, geluid))
    sok.sendall(ws.masker_frame(ws.OP_PING, b"p"))
    pong = sok.recv(16)
    assert pong.startswith(b"\x8a\x01p")
    sok.sendall(ws.masker_frame(ws.OP_SLUIT, b"\x03\xe8"))
    assert sok.recv(16).startswith(b"\x88")
    sok.close()
    assert ontvangen[0] == geluid and ontvangen[-1] == "dicht"


# ---------------------------------------------------------------
# Instellingen, dokter en de pagina
# ---------------------------------------------------------------

def test_mic_bron_standaard_auto():
    import config

    if "MIC_BRON" not in os.environ:
        assert config.MIC_BRON == "auto"


def test_dokter_slaat_pc_microfoon_over_bij_ipad(monkeypatch):
    import config
    from beheer import dokter

    monkeypatch.setattr(config, "MIC_BRON", "ipad")
    assert dokter.controleer_microfoon().status == dokter.OVERGESLAGEN


def test_spraakpaneel_volgt_de_regels():
    from dashboard.api import API_VERSIE

    html = open(os.path.join(STATIC, "spraak.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "spraak.js"), encoding="utf-8").read()
    refs = re.findall(r'(?:href|src)="(/[^"]+)"', html)
    assert refs and all(r.endswith(f"?v={API_VERSIE}") for r in refs)
    assert "<script>" not in html and " style=" not in html
    assert ".innerHTML" not in js and "localStorage" not in js and "Authorization" not in js
    assert "=>" not in js and not re.search(r"\b(let|const|class)\s", js)
    assert "'wss://' + location.host + '/api/spraak/stroom'" in js
    assert "bufferedAmount" in js  # niet eindeloos bufferen bij een trage verbinding


def test_e2e_zonder_kaartje_dicht(omgeving, monkeypatch):
    import config

    monkeypatch.setattr(config, "MIC_BRON", "auto")
    dashboard, poort, context, werk, caplog = omgeving
    ontvangen = []

    class NepIpad:
        def nieuwe_sessie(self):
            ontvangen.append("sessie")
            return "s1"

        def verwerk(self, sessie, data):
            ontvangen.append(data)
            return True

        def sluit(self, sessie):
            pass

    dashboard.ipad_microfoon_fn = NepIpad
    sok = context.wrap_socket(socket.create_connection(("127.0.0.1", poort), timeout=8), server_hostname="127.0.0.1")
    sok.sendall((f"GET /api/spraak/stroom HTTP/1.1\r\nHost: 127.0.0.1:{poort}\r\nUpgrade: websocket\r\n"
                 f"Connection: Upgrade\r\nSec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n"
                 f"Sec-WebSocket-Version: 13\r\nOrigin: https://127.0.0.1:{poort}\r\n\r\n").encode())
    kop = b""
    while b"\r\n\r\n" not in kop:
        kop += sok.recv(1024)
    rest = kop.split(b"\r\n\r\n", 1)[1]
    # Meteen geluid in plaats van een kaartje: de server sluit (1008).
    sok.sendall(ws.masker_frame(ws.OP_BINAIR, np.zeros(100, np.int16).tobytes()))
    while len(rest) < 4:
        stuk = sok.recv(64)
        if not stuk:
            break
        rest += stuk
    assert rest[0] & 0x0F == ws.OP_SLUIT and rest[2:4] == b"\x03\xf0"
    assert ontvangen == [], "zonder kaartje komt er geen geluid binnen"
    sok.close()


def test_ssl_context_import():
    # Zorgt dat de e2e-hulp beschikbaar is (anders slaat pytest de fixture stil over).
    assert ssl.PROTOCOL_TLS_CLIENT
