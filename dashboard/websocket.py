"""Minimale WebSocket (RFC 6455) voor de spraakstroom van de iPad (Fase 20, M4).

Alleen wat de spraakstroom nodig heeft, en streng:

* **Handdruk:** ``Sec-WebSocket-Accept`` uit de sleutel van de browser.
* **Frames van de browser** moeten gemaskeerd zijn (zo eist de RFC) en
  mogen niet groter zijn dan ``max_lengte``; gefragmenteerde berichten
  worden niet geaccepteerd (de iPad stuurt kleine, losse frames).
* **Frames naar de browser** zijn ongemaskeerd (tekst, binair, pong, sluiten).

Geen extensies (geen compressie) en geen subprotocollen.
"""

import base64
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEKST = 0x1
OP_BINAIR = 0x2
OP_SLUIT = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocketFout(Exception):
    """Ongeldig frame of de verbinding is weg; de sessie stopt."""


def accept_sleutel(sleutel):
    """De waarde voor ``Sec-WebSocket-Accept`` bij de sleutel van de browser."""

    if not isinstance(sleutel, str):
        raise WebSocketFout("Geen Sec-WebSocket-Key.")
    sleutel = sleutel.strip()
    try:
        if len(base64.b64decode(sleutel, validate=True)) != 16:
            raise WebSocketFout("Ongeldige Sec-WebSocket-Key.")
    except (ValueError, TypeError):
        raise WebSocketFout("Ongeldige Sec-WebSocket-Key.") from None
    digest = hashlib.sha1((sleutel + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _lees_precies(rfile, n):
    data = b""
    while len(data) < n:
        stuk = rfile.read(n - len(data))
        if not stuk:
            raise WebSocketFout("Verbinding gesloten.")
        data += stuk
    return data


def lees_frame(rfile, max_lengte):
    """Leest één frame van de browser: ``(opcode, payload)``."""

    kop = _lees_precies(rfile, 2)
    fin = kop[0] & 0x80
    rsv = kop[0] & 0x70
    opcode = kop[0] & 0x0F
    gemaskeerd = kop[1] & 0x80
    lengte = kop[1] & 0x7F

    if rsv:
        raise WebSocketFout("Extensies worden niet ondersteund.")
    if not fin or opcode == 0x0:
        raise WebSocketFout("Gefragmenteerde berichten worden niet ondersteund.")
    if opcode not in (OP_TEKST, OP_BINAIR, OP_SLUIT, OP_PING, OP_PONG):
        raise WebSocketFout("Onbekende opcode.")
    if not gemaskeerd:
        raise WebSocketFout("Frames van de browser moeten gemaskeerd zijn.")

    if lengte == 126:
        lengte = struct.unpack("!H", _lees_precies(rfile, 2))[0]
    elif lengte == 127:
        lengte = struct.unpack("!Q", _lees_precies(rfile, 8))[0]
    if opcode >= 0x8 and lengte > 125:
        raise WebSocketFout("Een controleframe mag hoogstens 125 bytes zijn.")
    if lengte > max_lengte:
        raise WebSocketFout("Frame is te groot.")

    masker = _lees_precies(rfile, 4)
    data = bytearray(_lees_precies(rfile, lengte))
    for i in range(lengte):
        data[i] ^= masker[i & 3]
    return opcode, bytes(data)


class SocketLezer:
    """Leest frames rechtstreeks van de socket, met een eigen buffer.

    Zo kan de WebSocket-thread eerst kijken of er iets te lezen is
    (:meth:`klaar`) en anders tussendoor geluid naar de iPad sturen (Fase 20,
    M5). Dezelfde thread leest én schrijft: gelijktijdig lezen en schrijven
    vanuit twee threads op één TLS-verbinding is in Python niet veilig.
    """

    def __init__(self, sock):
        self.sock = sock
        self._buf = b""

    def klaar(self, wacht):
        """True als er (binnen ``wacht`` seconden) iets te lezen is."""

        import select

        if self._buf:
            return True
        pending = getattr(self.sock, "pending", None)
        if pending is not None and pending() > 0:
            return True
        try:
            leesbaar, _, _ = select.select([self.sock], [], [], wacht)
        except (OSError, ValueError):
            raise WebSocketFout("Verbinding gesloten.") from None
        return bool(leesbaar)

    def read(self, n):
        while len(self._buf) < n:
            stuk = self.sock.recv(max(4096, n - len(self._buf)))
            if not stuk:
                break
            self._buf += stuk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data


def maak_frame(opcode, payload=b""):
    """Een ongemaskeerd frame van de server naar de browser."""

    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    lengte = len(payload)
    kop = bytes([0x80 | opcode])
    if lengte < 126:
        kop += bytes([lengte])
    elif lengte < 65536:
        kop += bytes([126]) + struct.pack("!H", lengte)
    else:
        kop += bytes([127]) + struct.pack("!Q", lengte)
    return kop + payload


def masker_frame(opcode, payload, masker=b"\x01\x02\x03\x04"):
    """Een gemaskeerd frame zoals een browser het stuurt (voor de tests)."""

    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    lengte = len(payload)
    kop = bytes([0x80 | opcode])
    if lengte < 126:
        kop += bytes([0x80 | lengte])
    elif lengte < 65536:
        kop += bytes([0x80 | 126]) + struct.pack("!H", lengte)
    else:
        kop += bytes([0x80 | 127]) + struct.pack("!Q", lengte)
    data = bytes(b ^ masker[i & 3] for i, b in enumerate(payload))
    return kop + masker + data
