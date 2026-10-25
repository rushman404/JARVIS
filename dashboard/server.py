"""Fase 18 — de HTTPS-server van het iPad-dashboard.

Deze module is alleen *verpakking* rond ``dashboard.api.DashboardAPI``:
alle dashboardlogica zit daar. Hier zit de beveiliging (zie
``docs/fase18_dashboard_design.md`` §10):

1. **TLS verplicht** — ``remote.server.build_ssl_context`` (TLS 1.2+), met
   dezelfde server als de game-pc-agent: handshake in de worker-thread,
   handshake-deadline en verbindingslimieten per IP.
2. **IP-allowlist** — publieke adressen altijd geweigerd (``_ip_toegestaan``).
3. **Host-controle** op elk verzoek (tegen DNS-rebinding).
4. **Rate-limit + lockout** — ``RateLimiter`` en ``AuthLockout``; een
   strengere limiet voor ``/api/pair`` en ``/api/tokens/rotatie``.
5. **Twee rollen** — ``kijk`` (lezen) en ``bedien`` (schrijven); via
   ``Authorization: Bearer`` of de sessiecookie van een gekoppeld apparaat.
6. **Origin-controle** op elke schrijfactie (behalve ``/api/pair``, waar de
   koppelcode zelf het geheim is). Geen CORS-headers.
7. **Security-headers** op elke respons: strikte CSP zonder
   ``'unsafe-inline'``, ``no-referrer``, ``nosniff``, ``frame-ancestors 'none'``;
   API-responsen ``Cache-Control: no-store``.

Een token staat nooit in een URL: de query-string wordt nergens gelezen en
ook niet gelogd. Tokens en koppelcodes komen nooit in een logregel of in
het auditlog.

``DashboardServer.process()`` is testbaar zonder sockets en geeft een
``Antwoord`` terug; ``_DashboardHandler`` schrijft dat weg (of streamt SSE).
"""

import ipaddress
import json
import logging
import os
import queue
import re
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

import config
from dashboard import auth
from dashboard.api import DashboardAPI
from dashboard.events import (
    HARTSLAG,
    HARTSLAG_SECONDEN,
    MAX_STREAM_SECONDEN,
    EventBus,
    Waarnemer,
    sse_bericht,
)
from remote.server import (
    AuthLockout,
    RateLimiter,
    RemoteAgentServer,
    _ip_toegestaan,
    build_ssl_context,
)

logger = logging.getLogger("jarvis.dashboard.server")

SERVER_SOFTWARE = "JarvisDashboard/1.0"

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Een dashboardverzoek is klein (timer, goedkeuring, widget-config).
MAX_BODY_BYTES = 16 * 1024
READ_TIMEOUT_SECONDS = 10

# Verbindingen: Safari opent tot ~6 keep-alive-verbindingen plus de SSE-stream,
# en na herladen blijven oude streams nog even open. Ruim genoeg dus; een
# volle limiet sluit alleen die ene verbinding en telt NIET als inlogfout.
MAX_CONNECTIONS = 48
MAX_CONNECTIONS_PER_IP = 24

# /api/pair, /api/koppelcode en /api/tokens/rotatie: 5 pogingen per 10 min.
STRENG_LIMIET = 5
STRENG_VENSTER = 600

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)

BASIS_HEADERS = (
    ("Content-Security-Policy", CSP),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

# Alleen deze bestandstypen worden als statisch bestand geserveerd.
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

PROFIEL_PAD = "/profiel.mobileconfig"
PROFIEL_MIME = "application/x-apple-aspen-config"

_TIMER_PAD = re.compile(r"^/api/timers/([A-Za-z0-9_-]{1,64})$")
_STATISCH_SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")

METHODEN = ("GET", "POST", "PUT", "DELETE")
SCHRIJF_METHODEN = ("POST", "PUT", "DELETE")


# ------------------------------------------------------------------
# Antwoord
# ------------------------------------------------------------------

class Antwoord:
    """Een kant-en-klaar antwoord: status, body (bytes) en headers.

    ``abonnement`` is gezet voor een SSE-stream; de handler streamt dan.
    """

    __slots__ = ("status", "body", "headers", "abonnement")

    def __init__(self, status, body=b"", headers=None, abonnement=None):
        self.status = status
        self.body = body
        self.headers = list(headers or [])
        self.abonnement = abonnement

    def header(self, naam):
        for k, v in self.headers:
            if k.lower() == naam.lower():
                return v
        return None

    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None


def _json(status, payload, extra=None):
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        status = 500
        data = json.dumps({"ok": False, "fout": {"code": "interne_fout", "melding": "Interne serverfout."}}).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Cache-Control", "no-store"),
    ]
    headers.extend(extra or [])
    return Antwoord(status, data, headers)


def _fout(status, code, melding, extra=None):
    return _json(status, {"ok": False, "fout": {"code": code, "melding": melding}}, extra)


_GEWEIGERD = ("niet_geautoriseerd", "Ongeldige of ontbrekende authenticatie.")


def _header(headers, naam):
    return auth._header(headers, naam)


def _alleen_oude_cookie(headers):
    """True als het verzoek alleen een (ongeldige) sessiecookie meestuurde,
    zonder Authorization-header."""

    aanwezig, _ = auth.lees_bearer(headers)
    return not aanwezig and auth.lees_cookie(headers) is not None


def _is_loopback(ip):
    try:
        return ipaddress.ip_address(str(ip or "")).is_loopback
    except ValueError:
        return False


# ------------------------------------------------------------------
# Host / Origin
# ------------------------------------------------------------------

def detecteer_lan_ip():
    """Het LAN-adres van deze pc (privé), of None.

    Een UDP-``connect`` verstuurt geen pakket; het laat alleen het
    besturingssysteem de uitgaande interface kiezen.
    """

    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        if s is not None:
            s.close()
    try:
        return ip if ipaddress.ip_address(ip).is_private and not ipaddress.ip_address(ip).is_loopback else None
    except ValueError:
        return None


def standaard_hosts(poort, lan_ip=None, extra=()):
    hosts = [f"localhost:{poort}", f"127.0.0.1:{poort}"]
    if lan_ip:
        hosts.insert(0, f"{lan_ip}:{poort}")
    hosts.extend(str(h).strip().lower() for h in extra if str(h).strip())
    return tuple(dict.fromkeys(h.lower() for h in hosts))


def standaard_origins(hosts, extra=()):
    origins = [f"https://{h}" for h in hosts]
    origins.extend(str(o).strip().lower().rstrip("/") for o in extra if str(o).strip())
    return tuple(dict.fromkeys(origins))


# ------------------------------------------------------------------
# De server-logica (testbaar zonder sockets)
# ------------------------------------------------------------------

class DashboardServer:
    """Beveiliging + routering rond ``DashboardAPI``.

    De attributen ``_allowed_ips``, ``_lockout`` en ``logger`` gebruikt
    ``RemoteAgentServer`` al vóór de TLS-handshake (IP-filter, lockout).
    """

    def __init__(
        self,
        api,
        authenticator,
        koppelcode,
        allowed_hosts,
        allowed_origins,
        allowed_ips=(),
        rate_limiter=None,
        streng_limiter=None,
        lockout=None,
        bus=None,
        static_dir=STATIC_DIR,
        profiel_file=None,
        audit_fn=None,
        logger_=None,
        eigen_ips=(),
    ):
        self.api = api
        self.auth = authenticator
        self.koppelcode = koppelcode
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self.allowed_origins = frozenset(o.lower() for o in allowed_origins)
        self._allowed_ips = tuple(allowed_ips or ())
        self.rate_limiter = rate_limiter or RateLimiter(
            config.DASHBOARD_RATE_LIMIT, config.DASHBOARD_RATE_WINDOW_SECONDS
        )
        self.streng_limiter = streng_limiter or RateLimiter(STRENG_LIMIET, STRENG_VENSTER)
        self.logger = logger_ if logger_ is not None else logger
        self._lockout = lockout or AuthLockout(logger_=self.logger)
        self.bus = bus or EventBus()
        self.static_dir = os.path.realpath(static_dir)
        # Eén pad of een lijst kandidaten; het eerste bestaande bestand wint.
        if isinstance(profiel_file, (list, tuple)):
            self.profiel_kandidaten = tuple(p for p in profiel_file if p)
        else:
            self.profiel_kandidaten = (profiel_file,) if profiel_file else ()
        # Adressen van deze pc zelf (naast loopback), bijv. het LAN-adres:
        # vanaf daar mag ook een nieuwe koppelcode worden aangevraagd.
        self.eigen_ips = frozenset(str(ip) for ip in (eigen_ips or ()) if ip)
        self.audit_fn = audit_fn
        self.max_body_bytes = MAX_BODY_BYTES

        k, b = auth.ROL_KIJK, auth.ROL_BEDIEN
        self._routes = {
            ("GET", "/api/status"): (k, lambda i, d: self.api.status()),
            ("GET", "/api/notifications"): (k, lambda i, d: self.api.notificaties()),
            ("POST", "/api/notifications/lees"): (b, lambda i, d: self.api.notificaties_lees(d)),
            ("POST", "/api/notifications/legen"): (b, lambda i, d: self.api.notificaties_legen()),
            ("GET", "/api/timers"): (k, lambda i, d: self.api.timers()),
            ("POST", "/api/timers"): (b, lambda i, d: self.api.timer_zet(d)),
            ("GET", "/api/pending"): (k, lambda i, d: self.api.pending()),
            ("POST", "/api/goedkeuring"): (b, lambda i, d: self.api.goedkeuring(d)),
            ("GET", "/api/widgets"): (k, lambda i, d: self.api.widgets()),
            ("PUT", "/api/widgets"): (b, lambda i, d: self.api.widgets_opslaan(d)),
            ("GET", "/api/settings"): (k, lambda i, d: self._settings()),
            ("PUT", "/api/settings"): (b, lambda i, d: self._settings_opslaan(d)),
            # M4: tegels
            ("GET", "/api/audit"): (k, lambda i, d: self.api.audit()),
            ("GET", "/api/gesprek"): (k, lambda i, d: self.api.gesprek()),
            # M6: overzichten (alleen lezen)
            ("GET", "/api/logs"): (k, lambda i, d: self.api.logboek()),
            ("GET", "/api/memory"): (k, lambda i, d: self.api.geheugen()),
            ("GET", "/api/routines"): (k, lambda i, d: self.api.routines()),
            ("GET", "/api/media"): (k, lambda i, d: self.api.media()),
            ("POST", "/api/media"): (b, lambda i, d: self.api.media_actie(d)),
            ("GET", "/api/ha/status"): (k, lambda i, d: self.api.slim_huis()),
            ("POST", "/api/ha/actie"): (b, lambda i, d: self.api.slim_huis_actie(d)),
            ("GET", "/api/ha/apparaten"): (k, lambda i, d: self.api.ha_apparaten()),
            ("PUT", "/api/ha/apparaten"): (b, lambda i, d: self.api.ha_apparaten_opslaan(d)),
            ("GET", "/api/weer"): (k, lambda i, d: self.api.weer()),
            ("GET", "/api/pc-status/local"): (k, lambda i, d: self.api.pc_status("local")),
            ("GET", "/api/pc-status/game-pc"): (k, lambda i, d: self.api.pc_status("game-pc")),
            ("POST", "/api/nachtmodus"): (b, lambda i, d: self.api.nachtmodus(d)),
            ("POST", "/api/power"): (b, lambda i, d: self.api.power(d)),
            ("POST", "/api/update"): (b, lambda i, d: self.api.update(d)),
        }
        self._bekende_paden = {pad for _, pad in self._routes} | {
            "/api/health", "/api/sessie", "/api/pair", "/api/koppelcode",
            "/api/tokens/rotatie", "/api/events", "/api/afmelden",
        }

    # ----- audit -----

    def _audit(self, tool, resultaat, goedgekeurd, reden=None, argumenten=None):
        try:
            if self.audit_fn is None:
                from core.audit import log_audit

                fn = log_audit
            else:
                fn = self.audit_fn
            fn(
                gehoord="",
                handler="dashboard",
                tool=tool,
                argumenten=argumenten or {},
                risico="low",
                resultaat=resultaat,
                goedgekeurd=goedgekeurd,
                reden=reden,
                herkomst="dashboard",
            )
        except Exception:
            self.logger.debug("Auditregel van het dashboard mislukt.", exc_info=True)

    def _oude_cookie(self):
        """401 voor een verlopen sessiecookie: de cookie wissen, maar NIET
        meetellen voor de lockout.

        Een oude cookie (na ontkoppelen, tokenrotatie of een tweede app op
        hetzelfde apparaat) is geen raadpoging: het kan alleen een
        apparaattoken van 256 bits zijn. De PWA doet bij het openen meerdere
        verzoeken tegelijk; die telden eerder allemaal als inlogfout en
        blokkeerden het apparaat 5 minuten ("Safari kan de pagina niet openen").
        """

        self.logger.debug("Verlopen sessiecookie; cookie gewist.")
        return _fout(401, *_GEWEIGERD, extra=[("Set-Cookie", auth.wis_cookie())])

    def _weiger_auth(self, client_ip, pad, reden, now=None, extra=None):
        """401 + telt mee voor de lockout + auditregel (zonder token)."""

        self._lockout.record_failure(client_ip, now=now)
        self._audit("dashboard_auth", "geweigerd", False, reden=reden,
                    argumenten={"pad": pad, "ip": str(client_ip or "")})
        return _fout(401, *_GEWEIGERD, extra=extra)

    # ----- hoofdingang -----

    def process(self, method, path, headers, body=b"", client_ip="", now=None):
        """Verwerkt één verzoek en geeft een ``Antwoord``."""

        method = (method or "").upper()
        body = bytes(body or b"")

        # 0) IP-allowlist en lockout: zonder uitleg.
        if not _ip_toegestaan(client_ip, self._allowed_ips) or self._lockout.is_blocked(client_ip, now=now):
            return _fout(403, *_GEWEIGERD)

        # 1) Host-controle op elk verzoek (DNS-rebinding).
        host = str(_header(headers, "Host") or "").strip().lower()
        if host not in self.allowed_hosts:
            return _fout(403, "verkeerde_host", "Onbekende host.")

        # 2) Rate-limit.
        if not self.rate_limiter.allow(client_ip, now=now):
            return _fout(429, "te_veel", "Te veel verzoeken; probeer het zo opnieuw.")

        if method not in METHODEN:
            return _fout(405, "methode", "Deze methode wordt niet ondersteund.", [("Allow", ", ".join(METHODEN))])

        # De query-string wordt bewust genegeerd: tokens horen nooit in een URL.
        pad = urlsplit(str(path or "")).path or "/"

        if not pad.startswith("/api/"):
            return self._statisch(method, pad)

        # 3) Schrijfacties: Origin-controle en JSON-body.
        data = None
        if method in SCHRIJF_METHODEN:
            if pad != "/api/pair":
                origin = str(_header(headers, "Origin") or "").strip().lower()
                if origin not in self.allowed_origins:
                    return _fout(403, "verkeerde_origin", "Dit verzoek komt niet van het dashboard.")
            if len(body) > self.max_body_bytes:
                return _fout(413, "te_groot", "Het verzoek is te groot.")
            if body:
                soort = str(_header(headers, "Content-Type") or "").split(";")[0].strip().lower()
                if soort != "application/json":
                    return _fout(415, "geen_json", "Stuur JSON (Content-Type: application/json).")
                try:
                    data = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    return _fout(400, "ongeldige_json", "De body is geen geldige JSON.")

        # 4) Openbare routes.
        if pad == "/api/health":
            if method != "GET":
                return _fout(405, "methode", "Gebruik GET.", [("Allow", "GET")])
            return _json(*self.api.health())
        if pad == "/api/pair":
            if method != "POST":
                return _fout(405, "methode", "Gebruik POST.", [("Allow", "POST")])
            return self._koppel(data, client_ip, now)
        if pad == "/api/koppelcode":
            return self._nieuwe_koppelcode(method, client_ip, now)
        if pad == "/api/sessie":
            if method != "GET":
                return _fout(405, "methode", "Gebruik GET.", [("Allow", "GET")])
            return self._sessie(headers, client_ip, pad, now)

        # 5) Authenticatie.
        identiteit, reden = self.auth.identificeer(headers)
        if identiteit is None:
            if reden == auth.GEEN_GEGEVENS:
                return _fout(401, *_GEWEIGERD)
            if _alleen_oude_cookie(headers):
                return self._oude_cookie()
            return self._weiger_auth(client_ip, pad, "ongeldig token", now)
        self._lockout.reset(client_ip)

        if pad == "/api/tokens/rotatie":
            if method != "POST":
                return _fout(405, "methode", "Gebruik POST.", [("Allow", "POST")])
            return self._roteer(identiteit, data, client_ip, now)

        if pad == "/api/afmelden":
            if method != "POST":
                return _fout(405, "methode", "Gebruik POST.", [("Allow", "POST")])
            return self._afmelden(identiteit)

        if pad == "/api/events":
            if method != "GET":
                return _fout(405, "methode", "Gebruik GET.", [("Allow", "GET")])
            return self._events(identiteit, client_ip)

        timer = _TIMER_PAD.match(pad)
        if timer:
            if method != "DELETE":
                return _fout(405, "methode", "Gebruik DELETE.", [("Allow", "DELETE")])
            if not identiteit.mag(auth.ROL_BEDIEN):
                return _fout(403, "rol", "Hiervoor is de bedien-rol nodig.")
            return _json(*self.api.timer_annuleer(timer.group(1)))

        route = self._routes.get((method, pad))
        if route is None:
            if pad in self._bekende_paden:
                toegestaan = sorted(m for (m, p) in self._routes if p == pad)
                return _fout(405, "methode", "Deze methode wordt niet ondersteund.",
                             [("Allow", ", ".join(toegestaan))])
            return _fout(404, "niet_gevonden", "Onbekend endpoint.")

        rol, handler = route
        if not identiteit.mag(rol):
            return _fout(403, "rol", "Hiervoor is de bedien-rol nodig.")

        try:
            status, payload = handler(identiteit, data)
        except Exception:
            self.logger.exception("Fout in dashboard-endpoint %s %s", method, pad)
            return _fout(500, "interne_fout", "Interne serverfout.")
        return _json(status, payload)

    # ----- openbare routes -----

    def _koppel(self, data, client_ip, now):
        """``POST /api/pair`` met ``{ code, rol, naam? }``."""

        if not self.streng_limiter.allow(client_ip, now=now):
            return _fout(429, "te_veel", "Te veel koppelpogingen; wacht even.")
        if not isinstance(data, dict):
            return _fout(400, "ongeldige_invoer", "Stuur een object met code en rol.")
        rol = data.get("rol")
        if rol not in auth.ROLLEN:
            return _fout(400, "ongeldige_rol", "rol moet 'kijk' of 'bedien' zijn.")
        naam = data.get("naam", "")
        if not isinstance(naam, str):
            naam = ""

        if not self.koppelcode.gebruik(data.get("code")):
            return self._weiger_auth(client_ip, "/api/pair", "ongeldige of verlopen koppelcode", now)

        self._lockout.reset(client_ip)
        apparaat, token = self.auth.register.voeg_toe(rol, naam=naam, ip=client_ip)
        self._audit("dashboard_koppelen", f"apparaat gekoppeld met rol {rol}", True,
                    argumenten={"apparaat": apparaat["id"], "rol": rol, "ip": str(client_ip or "")})
        self.logger.info("Dashboard: nieuw apparaat gekoppeld (rol %s).", rol)
        return _json(
            201,
            {"ok": True, "rol": rol, "apparaat_id": apparaat["id"], "token": token},
            [("Set-Cookie", auth.sessie_cookie(token))],
        )

    def is_deze_pc(self, client_ip):
        """True als het verzoek van deze pc zelf komt (loopback of eigen LAN-adres)."""

        return _is_loopback(client_ip) or str(client_ip or "") in self.eigen_ips

    def _nieuwe_koppelcode(self, method, client_ip, now):
        """``POST /api/koppelcode``: alleen vanaf deze pc zelf."""

        if not self.is_deze_pc(client_ip):
            return _fout(404, "niet_gevonden", "Onbekend endpoint.")
        if method != "POST":
            return _fout(405, "methode", "Gebruik POST.", [("Allow", "POST")])
        if not self.streng_limiter.allow(client_ip, now=now):
            return _fout(429, "te_veel", "Te veel verzoeken; wacht even.")
        code = self.koppelcode.nieuw()
        self._audit("dashboard_koppelcode", "nieuwe koppelcode gemaakt", True)
        return _json(200, {"ok": True, "code": code, "geldig_seconden": self.koppelcode.resterend()})

    def _sessie(self, headers, client_ip, pad, now):
        """``GET /api/sessie``: is dit apparaat gekoppeld? Nooit het token."""

        identiteit, reden = self.auth.identificeer(headers)
        if identiteit is None:
            if reden == auth.FOUT_GEGEVENS:
                if _alleen_oude_cookie(headers):
                    extra = [("Set-Cookie", auth.wis_cookie())]
                else:
                    self._weiger_auth(client_ip, pad, "ongeldig token", now)
                    extra = None
                return _json(200, {"gekoppeld": False, "rol": None,
                                   "token_ingesteld": self.auth.token_ingesteld}, extra)
            return _json(200, {"gekoppeld": False, "rol": None, "token_ingesteld": self.auth.token_ingesteld})
        self._lockout.reset(client_ip)
        return _json(200, {
            "gekoppeld": identiteit.bron == "apparaat",
            "rol": identiteit.rol,
            "token_ingesteld": self.auth.token_ingesteld,
        })

    # ----- beveiligde routes -----

    def _roteer(self, identiteit, data, client_ip, now):
        """``POST /api/tokens/rotatie`` met ``{ huidig }`` of ``{ sessie: true }``.

        Met ``huidig`` (scripts) moet het meegestuurde token kloppen en komt
        het nieuwe token één keer in de JSON. Met ``sessie: true`` (de PWA,
        die zijn token niet kent) is de HttpOnly-sessiecookie zelf het
        bewijs; dat mag alleen als het verzoek écht via die cookie binnenkwam
        (de Origin is al gecontroleerd). Het nieuwe token gaat dan alleen in
        een nieuwe cookie, nooit in de JSON.
        """

        if not self.streng_limiter.allow(client_ip, now=now):
            return _fout(429, "te_veel", "Te veel pogingen; wacht even.")
        if identiteit.bron != "apparaat":
            return _fout(409, "vast_token", "Een vast token wijzigt u in .env.")

        if isinstance(data, dict) and data.get("sessie") is True and set(data) == {"sessie"}:
            if identiteit.via != "cookie":
                return _fout(400, "geen_sessie", "Vernieuwen via de sessie kan alleen met de sessiecookie.")
            nieuw = self.auth.register.roteer(identiteit.apparaat["id"], identiteit.token)
            if nieuw is None:
                return self._weiger_auth(client_ip, "/api/tokens/rotatie", "rotatie met ongeldige sessie", now)
            self._audit("dashboard_tokenrotatie", "apparaattoken vernieuwd (sessie)", True,
                        argumenten={"apparaat": identiteit.apparaat["id"]})
            return _json(200, {"ok": True}, [("Set-Cookie", auth.sessie_cookie(nieuw))])

        huidig = data.get("huidig") if isinstance(data, dict) else None
        if not isinstance(huidig, str) or not auth._gelijk(huidig, identiteit.token or ""):
            return self._weiger_auth(client_ip, "/api/tokens/rotatie", "rotatie zonder kloppend huidig token", now)

        nieuw = self.auth.register.roteer(identiteit.apparaat["id"], huidig)
        if nieuw is None:
            return self._weiger_auth(client_ip, "/api/tokens/rotatie", "rotatie zonder kloppend huidig token", now)
        self._audit("dashboard_tokenrotatie", "apparaattoken vernieuwd", True,
                    argumenten={"apparaat": identiteit.apparaat["id"]})
        return _json(200, {"ok": True, "token": nieuw}, [("Set-Cookie", auth.sessie_cookie(nieuw))])

    def _afmelden(self, identiteit):
        """``POST /api/afmelden``: ontkoppelt dit apparaat (token ingetrokken)."""

        if identiteit.bron != "apparaat":
            return _fout(409, "vast_token", "Een vast token trekt u in via .env.")
        self.auth.register.trek_in(identiteit.apparaat["id"])
        self._audit("dashboard_ontkoppelen", "apparaat ontkoppeld", True,
                    argumenten={"apparaat": identiteit.apparaat["id"]})
        self.logger.info("Dashboard: apparaat ontkoppeld.")
        return _json(200, {"ok": True}, [("Set-Cookie", auth.wis_cookie())])

    def _events(self, identiteit=None, client_ip=None):
        abonnement = self.bus.abonneer(ip=client_ip)
        if abonnement is None:
            return _fout(503, "te_veel_streams", "Er zijn al te veel live-verbindingen.")
        if identiteit is not None and identiteit.bron == "apparaat":
            # Een open stream stopt zodra dit apparaat ontkoppeld wordt of
            # zijn token vernieuwt (dan hoort het opnieuw te verbinden).
            token = identiteit.token
            register = self.auth.register
            abonnement.nog_geldig = lambda: register.zoek(token) is not None
        return Antwoord(200, headers=[
            ("Content-Type", "text/event-stream; charset=utf-8"),
            ("Cache-Control", "no-store"),
            ("X-Accel-Buffering", "no"),
        ], abonnement=abonnement)

    def _settings(self):
        _, widgets = self.api.widgets()
        return 200, {
            "instellingen": widgets.get("instellingen", {}),
            "token_ingesteld": self.auth.token_ingesteld,
            "rollen": sorted(set(self.auth.vaste_rollen()) | set(self.auth.register.rollen())),
        }

    def _settings_opslaan(self, data):
        if not isinstance(data, dict) or set(data) != {"instellingen"}:
            return 400, {"ok": False, "fout": {"code": "ongeldige_invoer",
                                               "melding": "Stuur een object met alleen 'instellingen'."}}
        _, widgets = self.api.widgets()
        nieuw = dict(widgets)
        nieuw["instellingen"] = data["instellingen"]
        return self.api.widgets_opslaan(nieuw)

    # ----- statische bestanden -----

    def _statisch(self, method, pad):
        if method != "GET":
            return _fout(405, "methode", "Gebruik GET.", [("Allow", "GET")])

        if pad == PROFIEL_PAD:
            return self._profiel()

        relatief = "index.html" if pad == "/" else pad.lstrip("/")
        segmenten = relatief.split("/")
        if not all(_STATISCH_SEGMENT.match(s) for s in segmenten):
            return _fout(404, "niet_gevonden", "Niet gevonden.")

        mime = MIME_TYPES.get(os.path.splitext(relatief)[1].lower())
        if mime is None:
            return _fout(404, "niet_gevonden", "Niet gevonden.")

        bestand = os.path.realpath(os.path.join(self.static_dir, *segmenten))
        try:
            binnen = os.path.commonpath([bestand, self.static_dir]) == self.static_dir
        except ValueError:
            binnen = False
        if not binnen or not os.path.isfile(bestand):
            return _fout(404, "niet_gevonden", "Niet gevonden.")

        try:
            with open(bestand, "rb") as f:
                inhoud = f.read()
        except OSError:
            return _fout(404, "niet_gevonden", "Niet gevonden.")

        return Antwoord(200, inhoud, [("Content-Type", mime), ("Cache-Control", "no-cache")])

    def profiel_pad(self):
        """Het eerste bestaande profielbestand, of None."""

        for pad in self.profiel_kandidaten:
            if os.path.isfile(pad):
                return pad
        return None

    def _profiel(self):
        """Het iPad-profiel met alleen het publieke CA-certificaat."""

        pad = self.profiel_pad()
        if pad is None:
            return _fout(404, "niet_gevonden", "Niet gevonden.")
        try:
            with open(pad, "rb") as f:
                inhoud = f.read()
        except OSError:
            return _fout(404, "niet_gevonden", "Niet gevonden.")
        return Antwoord(200, inhoud, [
            ("Content-Type", PROFIEL_MIME),
            ("Content-Disposition", 'attachment; filename="jarvis-dashboard.mobileconfig"'),
            ("Cache-Control", "no-store"),
        ])


# ------------------------------------------------------------------
# HTTP-koppeling
# ------------------------------------------------------------------

class _TeGroot(Exception):
    pass


def zet_keepalive(sock):
    """TCP-keepalive op een live-verbinding: een dode iPad-verbinding wordt
    binnen ~30 s opgemerkt in plaats van na vele minuten. Fouten negeren."""

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            # Windows: aan, na 15 s stilte proberen, elke 5 s opnieuw.
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 15000, 5000))
        else:
            for naam, waarde in (("TCP_KEEPIDLE", 15), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
                if hasattr(socket, naam):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, naam), waarde)
    except (OSError, AttributeError, ValueError):
        pass


class _DashboardHandler(BaseHTTPRequestHandler):
    """Koppelt HTTP aan DashboardServer; bevat zelf geen logica."""

    server_version = SERVER_SOFTWARE
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = READ_TIMEOUT_SECONDS

    def do_GET(self):  # noqa: N802 (naam is voorgeschreven door http.server)
        self._verwerk()

    def do_POST(self):  # noqa: N802
        self._verwerk()

    def do_PUT(self):  # noqa: N802
        self._verwerk()

    def do_DELETE(self):  # noqa: N802
        self._verwerk()

    def do_PATCH(self):  # noqa: N802
        self._verwerk()

    def do_OPTIONS(self):  # noqa: N802
        self._verwerk()

    def do_HEAD(self):  # noqa: N802
        self._verwerk()

    def _lees_body(self, max_bytes):
        if self.headers.get("Transfer-Encoding"):
            raise _TeGroot()
        try:
            lengte = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            lengte = 0
        if lengte < 0:
            lengte = 0
        if lengte > max_bytes:
            raise _TeGroot()
        return self.rfile.read(lengte) if lengte else b""

    def _verwerk(self):
        server = self.server.agent
        client_ip = self.client_address[0] if self.client_address else ""

        try:
            body = self._lees_body(server.max_body_bytes)
        except _TeGroot:
            self.close_connection = True
            self._stuur(_fout(413, "te_groot", "Het verzoek is te groot."))
            return
        except (socket.timeout, TimeoutError, OSError):
            self.close_connection = True
            return

        try:
            antwoord = server.process(self.command, self.path, self.headers, body, client_ip=client_ip)
        except Exception:
            server.logger.exception("Onverwachte fout in het dashboard")
            antwoord = _fout(500, "interne_fout", "Interne serverfout.")

        if antwoord.abonnement is not None:
            self._stream(server, antwoord)
        else:
            self._stuur(antwoord)

    def _schrijf_kop(self, antwoord, lengte=None):
        self.send_response(antwoord.status)
        for naam, waarde in BASIS_HEADERS:
            self.send_header(naam, waarde)
        for naam, waarde in antwoord.headers:
            self.send_header(naam, waarde)
        if lengte is not None:
            self.send_header("Content-Length", str(lengte))
        self.end_headers()

    def _stuur(self, antwoord):
        try:
            self._schrijf_kop(antwoord, len(antwoord.body))
            if self.command != "HEAD":
                self.wfile.write(antwoord.body)
        except OSError:
            self.close_connection = True

    def _stream(self, server, antwoord):
        """Houdt de SSE-verbinding open tot de client weggaat of de server stopt."""

        ab = antwoord.abonnement
        self.close_connection = True
        zet_keepalive(self.connection)
        einde = time.monotonic() + MAX_STREAM_SECONDEN
        try:
            self._schrijf_kop(antwoord)
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while not server.bus.gesloten.is_set() and not ab.overgelopen:
                if time.monotonic() >= einde:
                    break  # de PWA verbindt binnen 3 s opnieuw
                try:
                    item = ab.wachtrij.get(timeout=HARTSLAG_SECONDEN)
                except queue.Empty:
                    item = False
                if not ab.nog_geldig():
                    break
                if item is False:
                    self.wfile.write(HARTSLAG)
                    self.wfile.flush()
                    continue
                if item is None:
                    break
                soort, data = item
                self.wfile.write(sse_bericht(soort, data))
                self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            server.bus.zeg_op(ab)

    def log_request(self, code="-", size="-"):
        # Nooit de query-string loggen (en dus nooit iets dat op een token lijkt).
        pad = urlsplit(self.path or "").path
        self.server.agent.logger.debug("%s %s %s %s", self.address_string(), self.command, pad, code)

    def log_message(self, fmt, *args):
        self.server.agent.logger.debug("%s - dashboard-verbinding", self.address_string())


class DashboardHTTPServer(RemoteAgentServer):
    """Dezelfde beveiligde server als de game-pc-agent, met de dashboard-handler."""

    # Een browser die veel verbindingen opent is geen aanvaller; alleen een
    # fout token of een foute koppelcode telt mee voor de lockout.
    limiet_telt_als_fout = False

    def __init__(self, server_address, dashboard, ssl_context=None, **kwargs):
        kwargs.setdefault("max_connections", MAX_CONNECTIONS)
        kwargs.setdefault("max_connections_per_ip", MAX_CONNECTIONS_PER_IP)
        kwargs.setdefault("max_connections_per_allowed_ip", MAX_CONNECTIONS_PER_IP)
        super().__init__(
            server_address,
            dashboard,
            ssl_context=ssl_context,
            handler_class=_DashboardHandler,
            **kwargs,
        )

    def server_close(self):
        self.agent.bus.sluit()
        super().server_close()


# ------------------------------------------------------------------
# Opzetten / starten
# ------------------------------------------------------------------

def bouw_dashboard(
    api=None,
    view_token=None,
    control_token=None,
    devices_file=None,
    poort=None,
    lan_ip=None,
    allowed_ips=None,
    static_dir=STATIC_DIR,
    profiel_file=None,
    audit_fn=None,
):
    """Bouwt de ``DashboardServer`` (zonder sockets) uit de configuratie."""

    poort = config.DASHBOARD_PORT if poort is None else poort
    if lan_ip is None:
        lan_ip = config.DASHBOARD_LAN_IP or detecteer_lan_ip()
    hosts = standaard_hosts(poort, lan_ip, config.DASHBOARD_ALLOWED_HOSTS)
    origins = standaard_origins(hosts, config.DASHBOARD_ALLOWED_ORIGINS)

    register = auth.ApparaatRegister(devices_file or config.DASHBOARD_DEVICES_FILE)
    authenticator = auth.Authenticator(
        config.DASHBOARD_VIEW_TOKEN if view_token is None else view_token,
        config.DASHBOARD_CONTROL_TOKEN if control_token is None else control_token,
        register,
    )

    if profiel_file is None:
        # Het script zet het profiel naast het certificaat; zoek dus ook
        # daar, voor het geval het in een andere map terechtkwam.
        profiel_file = [config.DASHBOARD_PROFILE_FILE]
        if config.DASHBOARD_CERT_FILE:
            map_ = os.path.dirname(os.path.abspath(config.DASHBOARD_CERT_FILE))
            profiel_file.append(os.path.join(map_, "jarvis-dashboard.mobileconfig"))

    return DashboardServer(
        api=api or DashboardAPI(),
        authenticator=authenticator,
        koppelcode=auth.Koppelcode(config.DASHBOARD_PAIR_CODE_TTL_SECONDS),
        allowed_hosts=hosts,
        allowed_origins=origins,
        allowed_ips=config.DASHBOARD_ALLOWED_IPS if allowed_ips is None else allowed_ips,
        static_dir=static_dir,
        profiel_file=profiel_file,
        audit_fn=audit_fn,
        eigen_ips=(lan_ip,) if lan_ip else (),
    )


def create_server(dashboard, host=None, port=None, cert_file=None, key_file=None, **kwargs):
    """Bouwt de TLS-server (nog niet gestart). Fail-closed: zonder tokens of
    certificaat een ``RuntimeError``."""

    host = config.DASHBOARD_HOST if host is None else host
    port = config.DASHBOARD_PORT if port is None else port
    cert_file = config.DASHBOARD_CERT_FILE if cert_file is None else cert_file
    key_file = config.DASHBOARD_KEY_FILE if key_file is None else key_file

    fouten = config.dashboard_security_errors(
        enabled=True,
        view_token=dashboard.auth._view,
        control_token=dashboard.auth._control,
        cert_file=cert_file,
        key_file=key_file,
    )
    if fouten:
        raise RuntimeError("Onveilige dashboard-configuratie; server start niet: " + " ".join(fouten))

    try:
        ssl_context = build_ssl_context(cert_file, key_file)
    except (ssl.SSLError, OSError, ValueError) as error:
        raise RuntimeError(f"Certificaat of sleutel is ongeldig; dashboard start niet: {error}") from error

    return DashboardHTTPServer((host, int(port)), dashboard, ssl_context=ssl_context, **kwargs)


def controleer_certificaat(cert_file, lan_ip, nu=None):
    """Waarschuwingen (lijst met tekst) als het certificaat niet past.

    De iPad weigert de verbinding als het IP-adres van de laptop niet in het
    certificaat staat (bijv. na een nieuw IP via DHCP) of als het verlopen
    is. In Safari kunt u dat met "Bezoek deze website" omzeilen, maar de app
    op het beginscherm niet: die toont dan alleen "Geen verbinding".
    Zonder de module ``cryptography`` wordt er niets gecontroleerd.
    """

    try:
        from cryptography import x509
    except ImportError:
        return []

    try:
        with open(cert_file, "rb") as f:
            cert = x509.load_pem_x509_certificates(f.read())[0]
    except (OSError, ValueError, IndexError):
        return ["Het certificaat kon niet gelezen worden."]

    waarschuwingen = []
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    except x509.ExtensionNotFound:
        ips = set()
    if lan_ip and lan_ip not in ips:
        bekend = ", ".join(sorted(ips)) or "geen"
        waarschuwingen.append(
            f"Het certificaat geldt niet voor {lan_ip} (wel voor: {bekend}). "
            f"Maak een nieuw: python scripts/make_dashboard_cert.py --force --ip {lan_ip}"
        )

    import datetime as _dt

    nu = nu or _dt.datetime.now(_dt.timezone.utc)
    verloopt = cert.not_valid_after_utc
    if verloopt <= nu:
        waarschuwingen.append(
            "Het certificaat is verlopen. Maak een nieuw: python scripts/make_dashboard_cert.py --force"
        )
    elif (verloopt - nu).days < 30:
        waarschuwingen.append(
            f"Het certificaat verloopt over {(verloopt - nu).days} dagen. "
            "Maak op tijd een nieuw: python scripts/make_dashboard_cert.py --force"
        )
    return waarschuwingen


class DashboardDienst:
    """De draaiende dashboard-server + waarnemer, met nette stop()."""

    def __init__(self, httpd, dashboard, waarnemer):
        self.httpd = httpd
        self.dashboard = dashboard
        self.waarnemer = waarnemer
        self._thread = None

    @property
    def poort(self):
        return self.httpd.server_address[1]

    def start(self):
        self.waarnemer.start()
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="dashboard-server", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self.waarnemer.stop()
        self.dashboard.api.ontkoppel()
        self.dashboard.bus.sluit()
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)


def start_dashboard(engine=None, toon=print):
    """Start het dashboard in een daemon-thread (vanuit ``main.py``).

    Geeft de ``DashboardDienst`` terug; gooit ``RuntimeError`` bij een
    onveilige configuratie. De koppelcode gaat alleen naar ``toon`` (de
    console van deze pc), nooit naar de log.
    """

    api = DashboardAPI(engine=engine)
    dashboard = bouw_dashboard(api=api)
    httpd = create_server(dashboard)
    dienst = DashboardDienst(httpd, dashboard, Waarnemer(api, dashboard.bus)).start()

    lan_hosts = [h for h in dashboard.allowed_hosts if not h.startswith(("localhost", "127.0.0.1"))]
    adres = sorted(lan_hosts)[0] if lan_hosts else f"localhost:{dienst.poort}"
    logger.info("Dashboard luistert op poort %s (HTTPS).", dienst.poort)

    code = dashboard.koppelcode.nieuw()
    minuten = max(1, dashboard.koppelcode.ttl // 60)
    # Bewust geen emoji: een Windows-console met codepage 1252 kan die niet
    # tonen, en het dashboard mag nooit op een printregel stuklopen.
    lan_ip = adres.rsplit(":", 1)[0] if lan_hosts else None
    cert_waarschuwingen = controleer_certificaat(config.DASHBOARD_CERT_FILE, lan_ip)
    for w in cert_waarschuwingen:
        logger.warning("Dashboard: %s", w)
    cert_tekst = "".join(f"   LET OP: {w}\n" for w in cert_waarschuwingen)

    if dashboard.profiel_pad():
        profiel = f"   iPad-profiel: https://{adres}{PROFIEL_PAD}\n"
    else:
        gezocht = " of ".join(dashboard.profiel_kandidaten) or "(geen pad ingesteld)"
        profiel = (
            f"   LET OP: iPad-profiel niet gevonden ({gezocht}).\n"
            "   Maak het met: python scripts/make_dashboard_cert.py\n"
        )
        logger.warning("Dashboard: iPad-profiel niet gevonden (%s).", gezocht)
    try:
        toon(
            f"\nJARVIS-dashboard: open https://{adres} op de iPad.\n"
            f"   Koppelcode: {code}  ({minuten} minuten geldig, een keer bruikbaar)\n"
            f"   Nieuwe code (op deze pc): https://{adres}/koppel.html\n"
            + profiel
            + cert_tekst
        )
    except Exception:
        logger.warning("Kon de koppelcode niet in de console tonen.")
    return dienst
