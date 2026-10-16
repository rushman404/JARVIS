"""Fase 15 — Game-PC Agent: berichtformaat en HMAC-authenticatie.

Dit is het gedeelde contract tussen de CLIENT (het brein) en de SERVER
(de game-pc). Beide kanten gebruiken exact dezelfde functies, zodat een
handtekening die de client maakt door de server kan worden geverifieerd.

Berichtformaat
--------------
Een opdracht is een JSON-object::

    {"tool": "open_program", "arguments": {"program": "Cyberpunk 2077"}}

De ruwe JSON-bytes worden versleuteld met TLS en ondertekend met HMAC.

Handtekening
------------
Elke aanvraag krijgt drie headers:

    X-JARVIS-Timestamp : unix-seconden (geheel getal, als tekst)
    X-JARVIS-Nonce     : eenmalige willekeurige waarde
    X-JARVIS-Signature : hex HMAC-SHA256

De handtekening gaat over een canonieke string::

    METHOD \\n PAD \\n TIJDSTEMPEL \\n NONCE \\n SHA256_HEX(ruwe body)

Omdat de body-hash wordt meegenomen, raakt elke wijziging in de body de
handtekening ongeldig. Omdat het pad en de methode meewegen, kan een
handtekening niet voor een ander endpoint worden hergebruikt.

Replay-bescherming
------------------
Er zijn twee sloten op de deur:

1. De tijdstempel moet binnen ``REMOTE_REPLAY_WINDOW_SECONDS`` van nu
   liggen (niet te oud, niet in de toekomst).
2. Elke nonce mag maar één keer voorkomen; hergebruik wordt geweigerd
   via :class:`NonceStore`.

De vergelijking van handtekeningen gebeurt met ``hmac.compare_digest``
(constant-time), zodat de responstijd niets over het geheim prijsgeeft.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time

from config import REMOTE_REPLAY_WINDOW_SECONDS

# Headers waarin de client zijn bewijs meestuurt.
HEADER_TIMESTAMP = "X-JARVIS-Timestamp"
HEADER_NONCE = "X-JARVIS-Nonce"
HEADER_SIGNATURE = "X-JARVIS-Signature"

SIGNATURE_ALGORITHM = "sha256"

# Routes (het gedeelde contract tussen client en server).
ROUTE_HEALTH = "/health"
ROUTE_COMMAND = "/command"
ROUTE_TELEMETRY = "/telemetry"

# Standaard geldigheidsvenster voor een handtekening (seconden).
DEFAULT_REPLAY_WINDOW_SECONDS = REMOTE_REPLAY_WINDOW_SECONDS

# Lengte (in bytes) van de willekeurige nonce; 16 bytes = 32 hex-tekens.
NONCE_BYTES = 16


def make_nonce():
    """Maakt een nieuwe, onvoorspelbare nonce (hex-tekst)."""
    return secrets.token_hex(NONCE_BYTES)


def _as_bytes(body):
    """Normaliseert de body naar bytes (lege body -> b'')."""

    if body is None:
        return b""

    if isinstance(body, bytes):
        return body

    if isinstance(body, bytearray):
        return bytes(body)

    if isinstance(body, str):
        return body.encode("utf-8")

    raise TypeError("Body moet bytes of tekst zijn.")


def body_digest(body):
    """SHA256-hash (hex) van de ruwe body-bytes."""

    return hashlib.sha256(_as_bytes(body)).hexdigest()


def build_canonical_string(method, path, timestamp, nonce, body=b""):
    """De exacte string die ondertekend wordt.

    Velden zijn gescheiden door newlines en in een vaste volgorde, zodat
    client en server altijd hetzelfde ondertekenen.
    """

    return "\n".join([
        str(method).upper(),
        str(path),
        str(int(timestamp)),
        str(nonce),
        body_digest(body),
    ])


def sign(token, method, path, timestamp, nonce, body=b""):
    """Berekent de hex HMAC-SHA256-handtekening.

    Een ontbrekend token is een programmeerfout en levert een
    ``ValueError`` op; de server mag nooit zonder geheim ondertekenen.
    """

    if not token or not str(token).strip():
        raise ValueError("token ontbreekt: kan niet ondertekenen")

    message = build_canonical_string(
        method, path, timestamp, nonce, body
    ).encode("utf-8")

    return hmac.new(
        str(token).encode("utf-8"), message, hashlib.sha256
    ).hexdigest()


def signed_headers(token, method, path, body=b"", timestamp=None, nonce=None):
    """Bouwt de drie bewijs-headers voor een aanvraag.

    Handig voor de client (en voor tests): één plek die tijdstempel,
    nonce en handtekening consistent maakt.
    """

    ts = int(time.time()) if timestamp is None else int(timestamp)
    nonce = nonce or make_nonce()

    signature = sign(token, method, path, ts, nonce, body)

    return {
        HEADER_TIMESTAMP: str(ts),
        HEADER_NONCE: str(nonce),
        HEADER_SIGNATURE: signature,
    }


class NonceStore:
    """Onthoudt gebruikte nonces zolang hun tijdstempel geldig kan zijn.

    Thread-safe: de server verwerkt aanvragen in meerdere threads en
    twee gelijktijdige aanvragen mogen nooit dezelfde nonce doorlaten.
    """

    def __init__(self, window_seconds=DEFAULT_REPLAY_WINDOW_SECONDS):
        self.window_seconds = int(window_seconds)
        self._lock = threading.Lock()
        self._seen = {}

    def check_and_store(self, nonce, now=None):
        """True als de nonce nieuw is (en legt hem vast); anders False."""

        now = time.time() if now is None else now
        nonce = str(nonce)

        with self._lock:
            self._prune(now)
            if nonce in self._seen:
                return False
            self._seen[nonce] = now + self.window_seconds
            return True

    def _prune(self, now):
        """Verwijdert nonces die niet meer binnen het venster vallen."""

        if not self._seen:
            return
        verlopen = [n for n, vervalt in self._seen.items() if vervalt < now]
        for nonce in verlopen:
            del self._seen[nonce]

    def __len__(self):
        return len(self._seen)


def verify_request(
    token,
    method,
    path,
    timestamp,
    nonce,
    body,
    signature,
    now=None,
    window=None,
    nonce_store=None,
):
    """Volledige controle van een aanvraag.

    Geeft ``(True, "")`` bij succes, anders ``(False, reden)``. De reden
    is een korte, vaste code (geen geheimen), bedoeld voor logging.

    Volgorde is bewust: eerst goedkope formaat-controles, dan de
    handtekening, en pas als laatste de nonce. Zo kan een aanvaller met
    een ongeldige handtekening de nonce-store niet volproppen.
    """

    if not token or not str(token).strip():
        return False, "no_token"

    if not signature:
        return False, "missing_signature"

    if timestamp in (None, "") or not nonce:
        return False, "missing_headers"

    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False, "bad_timestamp"

    window = DEFAULT_REPLAY_WINDOW_SECONDS if window is None else int(window)
    now = time.time() if now is None else now

    if now - ts > window:
        return False, "stale_timestamp"

    if ts - now > window:
        return False, "future_timestamp"

    expected = sign(token, method, path, ts, nonce, body)

    if not hmac.compare_digest(expected, str(signature)):
        return False, "bad_signature"

    if nonce_store is not None and not nonce_store.check_and_store(nonce, now=now):
        return False, "replayed_nonce"

    return True, ""


def encode_body(payload):
    """Codeert een opdracht naar compacte, deterministische JSON-bytes."""

    return json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def decode_body(raw):
    """Decodeert JSON-bytes naar een dict; leeg blijft leeg.

    Een niet-object (lijst, getal, string) is ongeldig en levert een
    ``ValueError`` op.
    """

    if raw in (None, b"", ""):
        return {}

    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("Bericht moet een JSON-object zijn.")

    return data
