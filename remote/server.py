"""Fase 15 — Game-PC Agent: de beveiligde server.

Deze server draait op de game-pc en voert alleen opdrachten uit die:

1. over **TLS** binnenkomen (verplicht, zelfondertekend certificaat);
2. een geldige **HMAC-handtekening** hebben (token + timestamp + nonce);
3. binnen het **replay-venster** vallen en een verse **nonce** hebben;
4. op de **allowlist** staan, met strikt gevalideerde parameters.

De server voert NOOIT willekeurige shell- of PowerShell-commando's uit.
Hij roept uitsluitend de centrale uitvoerder (``core.tool_registry``)
aan met een toolnaam die door de allowlist is goedgekeurd en met
argumenten die door ``remote.allowlist.validate_call`` zijn schoongemaakt.

Beveiliging is fail-closed: zonder token of certificaat weigert
:func:`create_server` te starten (zie ``config.remote_server_security_errors``).

Endpoints
---------
``GET  /health``   : een ondertekend bewijs dat de agent online is.
``POST /command``  : een ondertekende opdracht ``{"tool": ..., "arguments": ...}``.

Windows Firewall
----------------
De server bindt standaard op ``0.0.0.0`` (het hele LAN). Beperk in
Windows Firewall de inkomende verbindingen op poort
``REMOTE_SERVER_PORT`` (standaard 8765) het liefst tot **het IP-adres
van de mini-pc**, zodat alleen het brein de agent kan bereiken::

    New-NetFirewallRule -DisplayName "Jarvis remote-agent" `
        -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort 8765 -RemoteAddress <IP-van-de-mini-pc>
"""

import json
import logging
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
from core.audit import log_audit

from remote import allowlist, protocol

# ------------------------------------------------------------------
# Constanten
# ------------------------------------------------------------------

ROUTE_HEALTH = protocol.ROUTE_HEALTH
ROUTE_COMMAND = protocol.ROUTE_COMMAND
ROUTE_TELEMETRY = protocol.ROUTE_TELEMETRY

# Maximale grootte van een request-body (ruwe JSON). Alles groter wordt
# meteen geweigerd, zonder het hele lichaam in het geheugen te lezen.
DEFAULT_MAX_BODY_BYTES = 64 * 1024

# Hoe lang een verbinding mag wachten op data voordat hij wordt gesloten.
DEFAULT_READ_TIMEOUT_SECONDS = 10

# Eenvoudige snelheidslimiet per client-IP (0 = uit).
DEFAULT_RATE_LIMIT = 60
DEFAULT_RATE_WINDOW_SECONDS = 60

# Standaard maximum gelijktijdige verbindingen per client-IP.
DEFAULT_MAX_CONNECTIONS_PER_IP = 4

# Limiet voor IP's die expliciet in REMOTE_SERVER_ALLOWED_IPS staan.
DEFAULT_MAX_CONNECTIONS_PER_ALLOWED_IP = 12

# Totale deadline voor de TLS-handshake (niet per leesactie).
DEFAULT_HANDSHAKE_DEADLINE_SECONDS = 5.0

# Resultaten worden afgekapt voordat ze over de lijn gaan.
RESULT_MAX_LENGTH = 4000

SERVER_SOFTWARE = "JarvisRemoteAgent/1.0"

# Toegestane sleutels in een opdrachtbericht.
_MESSAGE_KEYS = frozenset({"tool", "arguments", "question"})

logger = logging.getLogger("jarvis.remote.server")


# ------------------------------------------------------------------
# Kleine helpers
# ------------------------------------------------------------------

def _fout_payload(code, melding):
    """Consistente fout-envelope (geen geheimen, geen stacktraces)."""

    return {"ok": False, "fout": {"code": code, "melding": melding}}


def _header(headers, naam):
    """Leest een header hoofdletterongevoelig (werkt met dict en HTTPMessage)."""

    if headers is None:
        return None

    try:
        waarde = headers.get(naam)
    except AttributeError:
        return None

    if waarde is not None:
        return waarde

    doel = naam.lower()
    for sleutel, waarde in headers.items():
        if str(sleutel).lower() == doel:
            return waarde

    return None


def _serialize_resultaat(resultaat):
    """Zet een toolresultaat (tekst of ToolResult) om naar JSON-veilige data."""

    if resultaat is None:
        return None

    if isinstance(resultaat, str):
        return resultaat[:RESULT_MAX_LENGTH]

    if isinstance(resultaat, (int, float, bool)):
        return resultaat

    if getattr(resultaat, "ok", None) is not None:
        data = getattr(resultaat, "data", None)
        if isinstance(data, (dict, list, str, int, float, bool)) or data is None:
            veilige_data = data
        else:
            veilige_data = str(data)[:RESULT_MAX_LENGTH]

        return {
            "ok": bool(getattr(resultaat, "ok")),
            "message": str(getattr(resultaat, "message", "") or "")[:RESULT_MAX_LENGTH],
            "data": veilige_data,
        }

    return str(resultaat)[:RESULT_MAX_LENGTH]


# ------------------------------------------------------------------
# Snelheidslimiet per client-IP
# ------------------------------------------------------------------

class RateLimiter:
    """Begrenst het aantal verzoeken per client-IP binnen een venster.

    Thread-safe: meerdere server-threads kunnen tegelijk tellen.
    ``max_requests <= 0`` schakelt de limiet uit.
    """

    def __init__(self, max_requests=DEFAULT_RATE_LIMIT, window_seconds=DEFAULT_RATE_WINDOW_SECONDS):
        self.max_requests = int(max_requests)
        self.window_seconds = int(window_seconds)
        self._lock = threading.Lock()
        self._hits = {}

    def allow(self, client_ip, now=None):
        """True als dit IP nog een verzoek mag doen."""

        if self.max_requests <= 0:
            return True

        now = time.time() if now is None else now
        sleutel = str(client_ip or "")

        with self._lock:
            recent = [t for t in self._hits.get(sleutel, []) if now - t < self.window_seconds]

            if len(recent) >= self.max_requests:
                self._hits[sleutel] = recent
                return False

            recent.append(now)
            self._hits[sleutel] = recent
            return True


# ------------------------------------------------------------------
# IP-allowlist (privé-adressen of een expliciete lijst)
# ------------------------------------------------------------------


def _ip_toegestaan(client_ip, allowed_ips):
    """True als dit client-IP de server mag bereiken.

    Publieke adressen worden ALTIJD geweigerd. Zonder expliciete lijst
    mogen alleen privé-adressen (LAN, localhost) contact opnemen.
    """

    import ipaddress

    try:
        adres = ipaddress.ip_address(str(client_ip or ""))
    except ValueError:
        return False

    if not adres.is_private:
        return False

    if allowed_ips:
        return str(client_ip) in tuple(str(ip) for ip in allowed_ips)

    return True


class AuthLockout:
    """Blokkeert een IP dat te vaak een foute handtekening stuurt.

    Na ``max_failures`` mislukte authenticaties binnen ``window_seconds``
    wordt het IP voor ``lockout_seconds`` geweigerd. Er komt één
    samenvattende logregel; per mislukking wordt niet gelogd.
    """

    def __init__(
        self,
        max_failures=5,
        window_seconds=60,
        lockout_seconds=300,
        logger_=None,
    ):
        self.max_failures = int(max_failures)
        self.window_seconds = int(window_seconds)
        self.lockout_seconds = int(lockout_seconds)
        self._lock = threading.Lock()
        self._failures = {}
        self._blocked_until = {}
        self.logger = logger_ if logger_ is not None else logger

    def is_blocked(self, client_ip, now=None):
        """True als dit IP nu geblokkeerd is."""

        now = time.time() if now is None else now
        sleutel = str(client_ip or "")

        with self._lock:
            tot = self._blocked_until.get(sleutel)
            return tot is not None and now < tot

    def record_failure(self, client_ip, now=None):
        """Noteert een mislukte authenticatie en blokkeert bij te veel."""

        now = time.time() if now is None else now
        sleutel = str(client_ip or "")

        with self._lock:
            recent = [
                t
                for t in self._failures.get(sleutel, [])
                if now - t < self.window_seconds
            ]
            recent.append(now)
            self._failures[sleutel] = recent

            if len(recent) < self.max_failures:
                return False

            self._blocked_until[sleutel] = now + self.lockout_seconds
            self._failures[sleutel] = []
            self.logger.warning(
                "IP %s geblokkeerd voor %d seconden na %d mislukte "
                "authenticaties.",
                sleutel,
                self.lockout_seconds,
                self.max_failures,
            )
            return True

    def reset(self, client_ip):
        """Wist de mislukkingen (een geldig verzoek telt niet mee)."""

        sleutel = str(client_ip or "")

        with self._lock:
            self._failures.pop(sleutel, None)
            self._blocked_until.pop(sleutel, None)


# ------------------------------------------------------------------
# De agent (testbaar zonder sockets)
# ------------------------------------------------------------------

class RemoteAgent:
    """De logica van de remote-agent, los van HTTP.

    ``process()`` neemt een reeds gelezen request aan en geeft
    ``(statuscode, JSON-payload)`` terug. Zo is de agent eenvoudig te
    testen zonder echte sockets of TLS.
    """

    def __init__(
        self,
        token,
        dispatch=None,
        replay_window=None,
        rate_limiter=None,
        max_body_bytes=DEFAULT_MAX_BODY_BYTES,
        allowed_ips=None,
        lockout=None,
        audit=True,
        logger_=None,
        profiel=None,
    ):
        if not token or not str(token).strip():
            raise ValueError(
                "RemoteAgent vereist een token; zonder geheim start de agent niet."
            )

        self._token = str(token)
        self._dispatch = dispatch
        self._replay_window = int(
            protocol.DEFAULT_REPLAY_WINDOW_SECONDS
            if replay_window is None
            else replay_window
        )
        self._nonces = protocol.NonceStore(self._replay_window)
        self._rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()
        self._max_body_bytes = int(max_body_bytes)
        # Standaard alleen privé-adressen; vul REMOTE_SERVER_ALLOWED_IPS in
        # om het IP van de mini-pc expliciet toe te laten.
        self._allowed_ips = (
            tuple(allowed_ips)
            if allowed_ips is not None
            else tuple(config.REMOTE_SERVER_ALLOWED_IPS)
        )
        self._lockout = lockout if lockout is not None else AuthLockout(logger_=logger_ or logger)
        self._audit_enabled = bool(audit)
        self.logger = logger_ or logger
        # Serverprofiel: basis (standaard) of werkstation.
        if profiel is None:
            profiel = getattr(config, "REMOTE_SERVER_PROFILE", "basis")
        self._profiel = allowlist.profiel_voor_naam(profiel)

    # -- hulpmiddelen -------------------------------------------------

    @property
    def max_body_bytes(self):
        return self._max_body_bytes

    @property
    def token(self):
        # Alleen voor interne vergelijking; wordt nooit gelogd of verstuurd.
        return self._token

    def _audit(self, tool, argumenten, resultaat, goedgekeurd, reden=None):
        """Schrijft een auditregel. De argumenten worden gesaneerd door
        core.audit; het token/de handtekening komen hier nooit in."""

        if not self._audit_enabled:
            return

        try:
            log_audit(
                gehoord="[remote]",
                handler="remote-agent",
                tool=tool or "",
                argumenten=argumenten or {},
                risico="remote",
                resultaat=resultaat,
                goedgekeurd=goedgekeurd,
                reden=reden,
            )
        except Exception:
            # Audit mag de server nooit laten vallen.
            pass

    def _voer_uit(self, tool, argumenten, question):
        """Voert een goedgekeurde actie uit via de centrale poort."""

        from core.tool_registry import run_tool_guarded

        dispatch = self._dispatch
        if dispatch is None:
            from core.ai import _dispatch_local_tool as dispatch

        # approved=True: goedkeuring gebeurt aan de kant van het brein,
        # vóórdat de opdracht wordt verstuurd. De server voert alleen uit
        # wat de allowlist doorlaat.
        return run_tool_guarded(
            tool,
            argumenten,
            source="remote-agent",
            question=question or "",
            dispatch=dispatch,
            approved=True,
        )

    # -- hoofdingang --------------------------------------------------

    def process(self, method, path, headers, body=b"", client_ip="", now=None):
        """Verwerkt één request en geeft ``(status, payload)`` terug."""

        method = (method or "").upper()
        path = "" if path is None else str(path)
        body = body or b""

        if not isinstance(body, (bytes, bytearray)):
            body = str(body).encode("utf-8")
        body = bytes(body)

        # 0) IP-allowlist + lockout (vóór de handtekeningcontrole).
        #    Publieke adressen worden altijd geweigerd; zonder uitleg.
        if not _ip_toegestaan(client_ip, self._allowed_ips):
            self.logger.warning("Verbinding vanaf niet-toegestaan IP geweigerd.")
            return 403, _fout_payload(
                "niet_geautoriseerd", "Ongeldige of ontbrekende authenticatie."
            )

        if self._lockout.is_blocked(client_ip, now=now):
            return 403, _fout_payload(
                "niet_geautoriseerd", "Ongeldige of ontbrekende authenticatie."
            )

        # 1) Snelheidslimiet.
        if not self._rate_limiter.allow(client_ip, now=now):
            self.logger.warning("Snelheidslimiet overschreden voor %s", client_ip)
            return 429, _fout_payload(
                "te_veel_verzoeken", "Te veel verzoeken; probeer het later opnieuw."
            )

        # 2) Requestgrootte.
        if len(body) > self._max_body_bytes:
            self.logger.warning("Body te groot (%d bytes) van %s", len(body), client_ip)
            return 413, _fout_payload(
                "te_groot", "Het verzoek is te groot."
            )

        # 3) Route + methode (exacte match; geen query-strings).
        if path == ROUTE_HEALTH:
            if method != "GET":
                return 405, _fout_payload("verkeerde_methode", "Gebruik GET voor /health.")
        elif path == ROUTE_TELEMETRY:
            if method != "GET":
                return 405, _fout_payload(
                    "verkeerde_methode", "Gebruik GET voor /telemetry."
                )
        elif path == ROUTE_COMMAND:
            if method != "POST":
                return 405, _fout_payload("verkeerde_methode", "Gebruik POST voor /command.")
        else:
            self.logger.info("Onbekende route geweigerd: %s", path)
            return 404, _fout_payload("onbekende_route", "Onbekende route.")

        # 4) Authenticatie (HMAC + tijdstempel + nonce).
        ok, reden = protocol.verify_request(
            self._token,
            method,
            path,
            _header(headers, protocol.HEADER_TIMESTAMP),
            _header(headers, protocol.HEADER_NONCE),
            body,
            _header(headers, protocol.HEADER_SIGNATURE),
            now=now,
            window=self._replay_window,
            nonce_store=self._nonces,
        )

        if not ok:
            self.logger.warning("Authenticatie geweigerd (%s) van %s", reden, client_ip)
            self._audit("", {}, "geweigerd", goedgekeurd=False, reden=reden)
            self._lockout.record_failure(client_ip, now=now)
            return 401, _fout_payload(
                "niet_geautoriseerd", "Ongeldige of ontbrekende authenticatie."
            )

        # Geslaagde authenticatie: de teller begint opnieuw.
        self._lockout.reset(client_ip)

        # 5) Inhoud.
        if path == ROUTE_HEALTH:
            return 200, {
                "ok": True,
                "service": "jarvis-remote-agent",
                "status": "online",
            }

        if path == ROUTE_TELEMETRY:
            return 200, self._telemetrie()

        return self._verwerk_opdracht(body, client_ip)

    def _telemetrie(self):
        """Read-only status/telemetrie van de game-pc (CPU/RAM/schijf/GPU).

        Dit voert géén gebruikersactie uit en raakt de allowlist niet:
        het verzamelt alleen lokale systeemgegevens via
        :mod:`remote.telemetry`.
        """

        try:
            from remote.telemetry import collect_telemetry

            gegevens = collect_telemetry()
        except Exception as error:  # nooit de server laten vallen
            self.logger.error("Telemetrie mislukt: %s", error)
            return _fout_payload("telemetrie_fout", "Kon de telemetrie niet ophalen.")

        return {"ok": True, "telemetrie": gegevens}

    def _verwerk_opdracht(self, body, client_ip):
        """Valideert en voert één opdracht uit."""

        try:
            bericht = protocol.decode_body(body)
        except (ValueError, TypeError):
            self._audit("", {}, "geweigerd", goedgekeurd=False, reden="ongeldig_bericht")
            return 400, _fout_payload("ongeldig_bericht", "Het bericht is geen geldig JSON-object.")

        onbekend = set(bericht) - _MESSAGE_KEYS
        if onbekend:
            self._audit("", {}, "geweigerd", goedgekeurd=False, reden="onbekende_velden")
            return 400, _fout_payload(
                "ongeldig_bericht",
                "Onbekende velden: " + ", ".join(sorted(map(str, onbekend))) + ".",
            )

        tool = bericht.get("tool")
        argumenten = bericht.get("arguments")
        question = bericht.get("question")
        if not isinstance(question, str):
            question = ""

        schoon, reden = allowlist.validate_call(tool, argumenten)

        if schoon is None:
            self.logger.warning("Actie geweigerd: %s", reden)
            self._audit(tool, argumenten, "geweigerd", goedgekeurd=False, reden=reden)
            return 403, _fout_payload("niet_toegestaan", reden)

        # Profiel-controle: basis staat alleen een vaste set acties toe.
        if not allowlist.is_allowed_in_profiel(tool, self._profiel):
            reden = (
                f"Actie '{tool}' is niet toegestaan in profiel '{self._profiel}'. "
                "Zet REMOTE_SERVER_PROFILE=werkstation om deze actie "
                "toe te staan."
            )
            self.logger.warning("Actie geweigerd: %s", reden)
            self._audit(tool, argumenten, "geweigerd", goedgekeurd=False, reden=reden)
            return 403, _fout_payload("niet_toegestaan", reden)

        # Typen en klikken mag niet in een venster van een geweigerd
        # programma. Fail-closed: bij exception of onbekende procesnaam
        # wordt geweigerd.
        _TYPING_TOOLS = {"ui_type_text", "ui_click_element", "ui_set_value"}
        if tool in _TYPING_TOOLS:
            handle = schoon.get("handle") if isinstance(schoon, dict) else None
            try:
                geweigerd = allowlist.is_denied_for_typing(handle)
            except Exception:
                self.logger.exception("Controle op geweigerd venster mislukte")
                geweigerd = True
            if geweigerd:
                reden = (
                    "Typen of klikken in een venster van een geweigerd "
                    "of onbekend programma is niet toegestaan."
                )
                self.logger.warning("Actie geweigerd: %s", reden)
                self._audit(tool, argumenten, "geweigerd", goedgekeurd=False, reden=reden)
                return 403, _fout_payload("niet_toegestaan", reden)

        try:
            resultaat = self._voer_uit(tool, schoon, question)
        except Exception as error:  # nooit de server laten vallen
            self.logger.exception("Uitvoering van '%s' mislukte", tool)
            self._audit(tool, schoon, "fout", goedgekeurd=True, reden=str(error))
            return 500, _fout_payload("uitvoer_fout", "Uitvoering mislukte.")

        return 200, {"ok": True, "resultaat": _serialize_resultaat(resultaat)}


# ------------------------------------------------------------------
# HTTP-koppeling
# ------------------------------------------------------------------

class _TooLarge(Exception):
    """Interne markering: de body is groter dan toegestaan."""


class _RemoteHandler(BaseHTTPRequestHandler):
    """Koppelt HTTP aan RemoteAgent; bevat zelf geen bedrijfslogica."""

    server_version = SERVER_SOFTWARE
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = DEFAULT_READ_TIMEOUT_SECONDS

    def do_GET(self):  # noqa: N802 (naam is voorgeschreven door http.server)
        self._verwerk()

    def do_POST(self):  # noqa: N802
        self._verwerk()

    def _lees_body(self, max_bytes):
        try:
            lengte = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            lengte = 0

        if lengte < 0:
            lengte = 0

        if lengte > max_bytes:
            raise _TooLarge()

        if lengte == 0:
            return b""

        return self.rfile.read(lengte)

    def _verwerk(self):
        agent = self.server.agent
        client_ip = self.client_address[0] if self.client_address else ""

        try:
            body = self._lees_body(agent.max_body_bytes)
        except _TooLarge:
            self.close_connection = True
            self._stuur(413, _fout_payload("te_groot", "Het verzoek is te groot."))
            return
        except (socket.timeout, TimeoutError):
            self.close_connection = True
            self._stuur(408, _fout_payload("timeout", "Time-out bij het lezen van het verzoek."))
            return
        except OSError:
            self.close_connection = True
            return

        try:
            status, payload = agent.process(
                self.command, self.path, self.headers, body, client_ip=client_ip
            )
        except Exception:
            agent.logger.exception("Onverwachte fout bij het verwerken van een verzoek")
            status, payload = 500, _fout_payload("interne_fout", "Interne serverfout.")

        self._stuur(status, payload)

    def _stuur(self, status, payload):
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            status = 500
            data = json.dumps(_fout_payload("interne_fout", "Interne serverfout.")).encode("utf-8")

        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.close_connection = True

    def log_message(self, fmt, *args):
        # Stuur HTTP-logregels naar de logger (en niet naar stderr), en
        # log nooit headers of bodies: daar kan een geheim in staan.
        self.server.agent.logger.debug(
            "%s - %s", self.address_string(), fmt % args
        )


class RemoteAgentServer(ThreadingHTTPServer):
    """Threading HTTP-server die elke verbinding in een eigen thread doet.

    TLS wordt per verbinding afgehandeld in die worker-thread (en niet op
    de luistersocket), zodat één trage of stilstaande verbinding de
    accept-lus niet kan blokkeren. Het aantal gelijktijdige verbindingen
    is begrensd (``max_connections``, standaard uit de configuratie);
    extra verbindingen worden direct gesloten.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        agent,
        ssl_context=None,
        max_connections=None,
        max_connections_per_ip=None,
        max_connections_per_allowed_ip=None,
        handshake_deadline=None,
    ):
        self.agent = agent
        self.ssl_context = ssl_context

        if max_connections is None:
            max_connections = config.REMOTE_MAX_CONNECTIONS

        self.max_connections = int(max_connections or 0)
        self._verbinding_semafoor = (
            threading.BoundedSemaphore(self.max_connections)
            if self.max_connections > 0
            else None
        )

        # Alleen een expliciet meegegen limiet mag onder het minimum van
        # EXECUTOR_MAX_WORKERS + 4 duiken (zie _limiet_voor_ip).
        self._per_ip_explicit = max_connections_per_ip is not None

        # Per-IP limiet (standaard uit config, of 4).
        if max_connections_per_ip is None:
            max_connections_per_ip = getattr(
                config, "REMOTE_MAX_CONNECTIONS_PER_IP", DEFAULT_MAX_CONNECTIONS_PER_IP
            )
        self.max_connections_per_ip = int(max_connections_per_ip or 0)

        # Hogere limiet voor IP's uit REMOTE_SERVER_ALLOWED_IPS
        # (standaard uit config, of 12).
        if max_connections_per_allowed_ip is None:
            max_connections_per_allowed_ip = getattr(
                config,
                "REMOTE_MAX_CONNECTIONS_PER_ALLOWED_IP",
                DEFAULT_MAX_CONNECTIONS_PER_ALLOWED_IP,
            )
        self.max_connections_per_allowed_ip = int(max_connections_per_allowed_ip or 0)

        # Totale handshake-deadline in seconden (standaard uit config, of 5).
        if handshake_deadline is None:
            handshake_deadline = getattr(
                config,
                "REMOTE_HANDSHAKE_DEADLINE_SECONDS",
                DEFAULT_HANDSHAKE_DEADLINE_SECONDS,
            )
        self.handshake_deadline = float(handshake_deadline or DEFAULT_HANDSHAKE_DEADLINE_SECONDS)

        # Per-IP telling van gelijktijdige verbindingen (thread-safe).
        self._per_ip_lock = threading.Lock()
        self._per_ip_counts = {}

        # Samengevatte handshake-logregels: IP -> [teller, eerste_ moment].
        self._handshake_log_lock = threading.Lock()
        self._handshake_log = {}

        super().__init__(server_address, _RemoteHandler)

    def get_request(self):
        """Accepteert een verbinding en zet er meteen een leestijd op.

        Zonder die timeout kan de TLS-handshake in process_request_thread
        oneindig wachten op een client die nooit iets stuurt.
        """

        conn, adres = super().get_request()

        try:
            conn.settimeout(DEFAULT_READ_TIMEOUT_SECONDS)
        except OSError:
            pass

        return conn, adres

    def process_request_thread(self, request, client_address):
        """Verwerkt één verbinding in een eigen thread.

        De TLS-handshake gebeurt hier (en dus niet in de accept-lus):
        een mislukte of trage handshake sluit alleen die ene verbinding.
        Vóór de semafoor en vóór de handshake wordt het IP gecontroleerd:
        niet-toegestane of geblokkeerde adressen worden stil gesloten.
        """

        ip = client_address[0] if client_address else ""

        # 0) IP-allowlist + lockout vóór de semafoor en vóór TLS.
        #    Zo houdt een golf van niet-toegestane verbindingen de
        #    verbindingsplekken van toegestane clients niet bezet.
        if not _ip_toegestaan(ip, self.agent._allowed_ips):
            self._sluit_verbinding(request)
            return

        if self.agent._lockout.is_blocked(ip):
            self._sluit_verbinding(request)
            return

        # 1) Per-IP limiet (toegestane IP's krijgen meer ruimte).
        limiet = self._limiet_voor_ip(ip)
        if not self._per_ip_slot_vrij(ip):
            self.agent._lockout.record_failure(ip)
            self._sluit_verbinding(request)
            self.agent.logger.warning(
                "Per-IP verbindingslimiet (%d) bereikt voor %s; verbinding gesloten.",
                limiet,
                ip,
            )
            return

        semafoor = self._verbinding_semafoor

        if semafoor is not None and not semafoor.acquire(blocking=False):
            self._per_ip_slot_vrij(ip, reserveer=False)
            self._sluit_verbinding(request)
            self.agent.logger.warning(
                "Verbindingslimiet (%d) bereikt; verbinding van %s gesloten.",
                self.max_connections,
                ip,
            )
            return

        try:
            if self.ssl_context is not None:
                tls_request = self._handshake_tls(request, client_address)
                if tls_request is None:
                    return
                request = tls_request

            super().process_request_thread(request, client_address)
        finally:
            if semafoor is not None:
                semafoor.release()
            self._per_ip_slot_vrij(ip, reserveer=False)

    def _limiet_voor_ip(self, ip):
        """Berekent de verbindingslimiet voor één IP.

        - Allowlist leeg: iedereen minimaal ``EXECUTOR_MAX_WORKERS + 4``,
          zodat het brein naast zijn parallelle opdrachten nog een extra
          aanroep (bijv. een statuscheck) kan doen zonder afgekapt te
          worden. Een expliciet meegegeven lagere limiet blijft gelden.
        - Allowlist gevuld: IP's daaruit krijgen het hogere limiet
          (``REMOTE_MAX_CONNECTIONS_PER_ALLOWED_IP``, standaard 12, nooit
          lager dan ``EXECUTOR_MAX_WORKERS + 4``).
        - Andere IP's houden het gewone limiet
          (``REMOTE_MAX_CONNECTIONS_PER_IP``, standaard 4).

        0 betekent geen limiet.
        """

        basis = self.max_connections_per_ip
        if basis <= 0:
            return 0

        minimum = int(getattr(config, "EXECUTOR_MAX_WORKERS", 4)) + 4
        toegestaan = tuple(
            str(x) for x in (getattr(self.agent, "_allowed_ips", ()) or ())
        )

        if not toegestaan:
            # Lege allowlist: iedereen minimaal EXECUTOR_MAX_WORKERS + 4,
            # behalve bij een expliciet meegegeven (lagere) limiet.
            if getattr(self, "_per_ip_explicit", False):
                return basis
            return max(basis, minimum)

        if str(ip) in toegestaan:
            hoger = getattr(
                self,
                "max_connections_per_allowed_ip",
                DEFAULT_MAX_CONNECTIONS_PER_ALLOWED_IP,
            )
            if hoger <= 0:
                return 0
            return max(hoger, minimum)

        return basis

    def _per_ip_slot_vrij(self, ip, reserveer=True):
        """Reserveert of geeft een per-IP verbindingsslot vrij.

        Geeft True als het IP nog een slot mag innemen (of als er geen
        limiet is). ``reserveer=False`` geeft alleen vrij.
        """

        limiet = self._limiet_voor_ip(ip)
        if limiet <= 0:
            return True

        with self._per_ip_lock:
            if not reserveer:
                huidig = self._per_ip_counts.get(ip, 0)
                if huidig <= 1:
                    self._per_ip_counts.pop(ip, None)
                else:
                    self._per_ip_counts[ip] = huidig - 1
                return True

            huidig = self._per_ip_counts.get(ip, 0)
            if huidig >= limiet:
                return False

            self._per_ip_counts[ip] = huidig + 1
            return True

    def _log_handshake_mislukt(self, ip):
        """Logt een mislukte handshake samengevat.

        Eén regel per IP per minuut met een teller, in plaats van één
        regel per verbinding.
        """

        nu = time.time()

        with self._handshake_log_lock:
            entry = self._handshake_log.get(ip)
            if entry is None or nu - entry[1] >= 60:
                self._handshake_log[ip] = [1, nu]
                self.agent.logger.warning(
                    "TLS-handshake mislukt of te traag van %s "
                    "(eerste melding in dit venster).",
                    ip,
                )
            else:
                entry[0] += 1
                if entry[0] % 10 == 0:
                    self.agent.logger.warning(
                        "TLS-handshake mislukt of te traag van %s "
                        "(%d keer in dit venster).",
                        ip,
                        entry[0],
                    )

    def _handshake_tls(self, conn, client_address):
        """Doet de TLS-handshake op deze verbinding, in de worker-thread.

        Geeft de TLS-socket terug, of None als de handshake mislukte of de
        totale deadline (``handshake_deadline``) overschreden werd. De
        verbinding is dan al gesloten. Mislukkingen worden samengevat
        gelogd: één regel per IP per minuut met een teller.
        """

        ip = client_address[0] if client_address else "onbekend"
        deadline = self.handshake_deadline

        try:
            conn.settimeout(deadline)
            tls_conn = self.ssl_context.wrap_socket(
                conn, server_side=True, do_handshake_on_connect=False
            )
            tls_conn.settimeout(deadline)
            tls_conn.do_handshake()
        except (ssl.SSLError, OSError, ValueError):
            self._log_handshake_mislukt(ip)
            self._sluit_verbinding(conn)
            return None

        return tls_conn

    def _sluit_verbinding(self, request):
        """Sluit één verbinding; fouten hierbij raken de server niet."""

        try:
            self.shutdown_request(request)
        except OSError:
            pass


# ------------------------------------------------------------------
# Opzetten / starten
# ------------------------------------------------------------------

def build_ssl_context(cert_file, key_file):
    """Maakt een TLS-servercontext van het certificaat en de sleutel.

    Gooit een exception als het certificaat of de sleutel ontbreekt of
    ongeldig is; de server start dan niet.
    """

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def create_server(
    host=None,
    port=None,
    token=None,
    cert_file=None,
    key_file=None,
    dispatch=None,
    rate_limiter=None,
    max_body_bytes=DEFAULT_MAX_BODY_BYTES,
    audit=True,
    max_connections=None,
    max_connections_per_ip=None,
    max_connections_per_allowed_ip=None,
    handshake_deadline=None,
):
    """Bouwt een volledig geconfigureerde TLS-server (nog niet gestart).

    Weigert te starten (``RuntimeError``) als de beveiligingsconfiguratie
    onvolledig of ongeldig is.

    De TLS-handshake gebeurt per verbinding in de worker-thread van de
    server; de luistersocket blijft plat, zodat één trage verbinding de
    accept-lus niet blokkeert. ``max_connections`` begrenst het aantal
    gelijktijdige verbindingen (standaard ``config.REMOTE_MAX_CONNECTIONS``).
    ``max_connections_per_ip`` begrenst het aantal per client-IP
    (standaard ``config.REMOTE_MAX_CONNECTIONS_PER_IP``); IP's uit
    ``REMOTE_SERVER_ALLOWED_IPS`` krijgen het hogere
    ``max_connections_per_allowed_ip`` (standaard 12). ``handshake_deadline``
    is de totale deadline voor de TLS-handshake in seconden.
    """

    host = config.REMOTE_SERVER_HOST if host is None else host
    port = config.REMOTE_SERVER_PORT if port is None else port
    token = config.REMOTE_SERVER_TOKEN if token is None else token
    cert_file = config.REMOTE_SERVER_CERT_FILE if cert_file is None else cert_file
    key_file = config.REMOTE_SERVER_KEY_FILE if key_file is None else key_file

    fouten = config.remote_server_security_errors(
        enabled=True, token=token, cert_file=cert_file, key_file=key_file
    )
    if fouten:
        raise RuntimeError(
            "Onveilige remote-configuratie; server start niet: " + " ".join(fouten)
        )

    try:
        ssl_context = build_ssl_context(cert_file, key_file)
    except (ssl.SSLError, OSError, ValueError) as error:
        raise RuntimeError(
            f"Certificaat of sleutel is ongeldig; server start niet: {error}"
        ) from error

    agent = RemoteAgent(
        token=token,
        dispatch=dispatch,
        replay_window=config.REMOTE_REPLAY_WINDOW_SECONDS,
        rate_limiter=rate_limiter,
        max_body_bytes=max_body_bytes,
        audit=audit,
    )

    httpd = RemoteAgentServer(
        (host, int(port)),
        agent,
        ssl_context=ssl_context,
        max_connections=max_connections,
        max_connections_per_ip=max_connections_per_ip,
        max_connections_per_allowed_ip=max_connections_per_allowed_ip,
        handshake_deadline=handshake_deadline,
    )
    return httpd


def _utf8_console():
    """Zet stdout/stderr van de agent op UTF-8.

    De agent draait als geplande taak zonder UTF-8-console (codepage 1252).
    Een print met een emoji (bijv. "🚀 Programma gevonden") liet daardoor
    de hele opdracht mislukken met een UnicodeEncodeError. ``errors`` op
    "replace" zorgt dat een onverwacht teken nooit meer een actie breekt.
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    """Start de server met de waarden uit de configuratie (blokkerend)."""

    _utf8_console()

    logging.basicConfig(level=logging.INFO)

    fouten = config.remote_server_security_errors()
    if fouten:
        raise SystemExit(
            "Onveilige remote-configuratie; server start niet:\n- "
            + "\n- ".join(fouten)
        )

    if not config.REMOTE_SERVER_ENABLED:
        logger.warning(
            "REMOTE_SERVER_ENABLED staat uit; de server wordt toch gestart "
            "omdat je dit script expliciet aanroept."
        )

    httpd = create_server()

    logger.info(
        "Jarvis remote-agent luistert op %s:%s (TLS).",
        config.REMOTE_SERVER_HOST,
        config.REMOTE_SERVER_PORT,
    )
    logger.info(
        "Beperk in Windows Firewall inkomende verbindingen het liefst tot "
        "het IP-adres van de mini-pc."
    )

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server gestopt.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
