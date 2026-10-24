"""Koppelcode, tokens en rollen van het dashboard (Fase 18, §10.3–§10.4).

Twee rollen:

* ``kijk``   — alleen lezen;
* ``bedien`` — lezen én schrijven (timers, media, goedkeuringen).

Een verzoek kan zich op twee manieren melden:

* ``Authorization: Bearer <token>`` — de vaste tokens uit ``.env``
  (``DASHBOARD_VIEW_TOKEN`` / ``DASHBOARD_CONTROL_TOKEN``) of een
  apparaattoken;
* de sessiecookie (``HttpOnly; Secure; SameSite=Strict``) van een apparaat
  dat met de eenmalige koppelcode is gekoppeld. Die werkt ook voor SSE.

Regels die hier vastliggen:

* Een token staat nooit in een URL; de query-string wordt nergens gelezen.
* Van een apparaattoken wordt alleen de SHA-256-hash bewaard
  (``config/dashboard_devices.json``); het token zelf is één keer zichtbaar.
* Tokens en koppelcodes komen nooit in een logregel.
* Vergelijkingen gebeuren in constante tijd (``hmac.compare_digest``).
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time

logger = logging.getLogger("jarvis.dashboard.auth")

ROL_KIJK = "kijk"
ROL_BEDIEN = "bedien"
ROLLEN = (ROL_KIJK, ROL_BEDIEN)

# Naam van de sessiecookie.
COOKIE_NAAM = "jarvis_sessie"
# Een gekoppelde iPad blijft een jaar gekoppeld (tot intrekken of rotatie).
COOKIE_MAX_AGE = 365 * 24 * 3600

KOPPELCODE_CIJFERS = 8
# Na zoveel foute pogingen (van wie dan ook) vervalt de code meteen.
MAX_FOUTE_KOPPELPOGINGEN = 3

MAX_APPARAATNAAM = 40


def token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _gelijk(a, b):
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def sessie_cookie(token, max_age=COOKIE_MAX_AGE):
    """De Set-Cookie-waarde voor een apparaattoken."""

    return (
        f"{COOKIE_NAAM}={token}; Path=/; Max-Age={int(max_age)}; "
        "HttpOnly; Secure; SameSite=Strict"
    )


def wis_cookie():
    return f"{COOKIE_NAAM}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"


def _header(headers, naam):
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


def lees_cookie(headers, naam=COOKIE_NAAM):
    """Leest één cookie uit de Cookie-header (zonder http.cookies-magie)."""

    ruw = _header(headers, "Cookie")
    if not ruw:
        return None
    for deel in str(ruw).split(";"):
        sleutel, _, waarde = deel.strip().partition("=")
        if sleutel == naam and waarde:
            return waarde
    return None


def lees_bearer(headers):
    """Geeft ``(aanwezig, token)``: of er een Authorization-header is en het token."""

    ruw = _header(headers, "Authorization")
    if ruw is None:
        return False, None
    schema, _, token = str(ruw).strip().partition(" ")
    if schema.lower() != "bearer" or not token.strip():
        return True, None
    return True, token.strip()


# =============================================================
# Koppelcode
# =============================================================

class Koppelcode:
    """Eén eenmalige koppelcode van 8 cijfers, kort geldig.

    De code verschijnt alleen lokaal op de pc (console); hij gaat nooit
    over het netwerk en wordt nooit gelogd. Een nieuwe code vervangt de
    vorige. Na ``MAX_FOUTE_KOPPELPOGINGEN`` foute pogingen vervalt hij.
    """

    def __init__(self, ttl_seconden=300, clock=None):
        self.ttl = int(ttl_seconden)
        self.clock = clock if clock is not None else time.time
        self._lock = threading.Lock()
        self._code = None
        self._verloopt_op = 0.0
        self._fouten = 0

    def nieuw(self):
        """Maakt een nieuwe code en geeft die terug (alleen lokaal tonen!)."""

        code = f"{secrets.randbelow(10 ** KOPPELCODE_CIJFERS):0{KOPPELCODE_CIJFERS}d}"
        with self._lock:
            self._code = code
            self._verloopt_op = self.clock() + self.ttl
            self._fouten = 0
        return code

    def resterend(self):
        with self._lock:
            if self._code is None:
                return 0
            return max(0, int(self._verloopt_op - self.clock()))

    def gebruik(self, code):
        """True als ``code`` klopt; de code is daarna meteen ongeldig."""

        geldig_formaat = (
            isinstance(code, str) and code.isdigit() and len(code) == KOPPELCODE_CIJFERS
        )

        with self._lock:
            if self._code is None:
                return False
            if self.clock() >= self._verloopt_op:
                self._code = None
                return False
            if geldig_formaat and _gelijk(code, self._code):
                self._code = None
                return True
            self._fouten += 1
            if self._fouten >= MAX_FOUTE_KOPPELPOGINGEN:
                self._code = None
            return False


# =============================================================
# Gekoppelde apparaten
# =============================================================

class ApparaatRegister:
    """Gekoppelde apparaten in ``config/dashboard_devices.json``.

    Per apparaat: id, hash van het token, rol, naam, IP en aanmaakdatum.
    Nooit het token zelf.
    """

    def __init__(self, pad, clock=None):
        self.pad = pad
        self.clock = clock if clock is not None else time.time
        self._lock = threading.Lock()
        self._apparaten = self._laad()

    def _laad(self):
        try:
            with open(self.pad, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            logger.warning("Apparatenbestand van het dashboard is onleesbaar; leeg begonnen.")
            return []

        apparaten = data.get("apparaten") if isinstance(data, dict) else None
        if not isinstance(apparaten, list):
            return []
        geldig = []
        for a in apparaten:
            if (
                isinstance(a, dict)
                and isinstance(a.get("id"), str)
                and isinstance(a.get("hash"), str)
                and a.get("rol") in ROLLEN
            ):
                geldig.append(a)
        return geldig

    def _opslaan(self):
        map_ = os.path.dirname(self.pad)
        if map_:
            os.makedirs(map_, exist_ok=True)
        tmp = self.pad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"versie": 1, "apparaten": self._apparaten}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.pad)

    def voeg_toe(self, rol, naam="", ip=""):
        """Koppelt een nieuw apparaat. Geeft ``(apparaat, token)``; het token
        is alleen nu zichtbaar."""

        if rol not in ROLLEN:
            raise ValueError("onbekende rol")
        token = secrets.token_urlsafe(32)
        apparaat = {
            "id": secrets.token_hex(6),
            "hash": token_hash(token),
            "rol": rol,
            "naam": str(naam or "")[:MAX_APPARAATNAAM],
            "ip": str(ip or ""),
            "aangemaakt_op": self.clock(),
        }
        with self._lock:
            self._apparaten.append(apparaat)
            self._opslaan()
        return self._publiek(apparaat), token

    def zoek(self, token):
        """Het apparaat bij dit token (publieke velden), of None."""

        if not token:
            return None
        gezocht = token_hash(token)
        gevonden = None
        with self._lock:
            # Alle apparaten aflopen: geen vroege return (constante tijd).
            for a in self._apparaten:
                if _gelijk(a["hash"], gezocht):
                    gevonden = a
        return self._publiek(gevonden) if gevonden else None

    def roteer(self, apparaat_id, huidig_token):
        """Nieuw token voor dit apparaat, alleen met het kloppende huidige.

        Geeft het nieuwe token, of None. Het oude token (en daarmee de
        oude sessiecookie) werkt daarna meteen niet meer.
        """

        if not huidig_token:
            return None
        gezocht = token_hash(huidig_token)
        with self._lock:
            for a in self._apparaten:
                if a["id"] == apparaat_id and _gelijk(a["hash"], gezocht):
                    nieuw = secrets.token_urlsafe(32)
                    a["hash"] = token_hash(nieuw)
                    a["geroteerd_op"] = self.clock()
                    self._opslaan()
                    return nieuw
        return None

    def trek_in(self, apparaat_id):
        with self._lock:
            voor = len(self._apparaten)
            self._apparaten = [a for a in self._apparaten if a["id"] != apparaat_id]
            if len(self._apparaten) == voor:
                return False
            self._opslaan()
            return True

    def lijst(self):
        with self._lock:
            return [self._publiek(a) for a in self._apparaten]

    def rollen(self):
        with self._lock:
            return sorted({a["rol"] for a in self._apparaten})

    @staticmethod
    def _publiek(a):
        return {k: v for k, v in a.items() if k != "hash"}


# =============================================================
# Authenticatie
# =============================================================

class Identiteit:
    """Wie een verzoek doet: rol + bron ("token" of "apparaat")."""

    __slots__ = ("rol", "bron", "apparaat", "token", "via")

    def __init__(self, rol, bron, apparaat=None, token=None, via="header"):
        self.rol = rol
        self.bron = bron
        self.apparaat = apparaat
        # "header" (Authorization: Bearer) of "cookie" (de sessie van de PWA).
        self.via = via
        # Het gebruikte token, alleen voor de rotatiecontrole in dit
        # verzoek. Wordt nooit gelogd of teruggestuurd.
        self.token = token

    def mag(self, rol):
        return rol == ROL_KIJK or self.rol == ROL_BEDIEN


# Uitkomst van Authenticator.identificeer() zonder identiteit.
GEEN_GEGEVENS = "geen_gegevens"   # niets meegestuurd -> 401, telt niet mee
FOUT_GEGEVENS = "fout_gegevens"   # wel iets, maar fout -> 401 + lockout


class Authenticator:
    """Bepaalt de rol van een verzoek uit de Authorization-header of de cookie."""

    def __init__(self, view_token, control_token, register):
        self._view = view_token or ""
        self._control = control_token or ""
        self.register = register

    @property
    def token_ingesteld(self):
        return bool(self._view or self._control)

    def vaste_rollen(self):
        rollen = []
        if self._view:
            rollen.append(ROL_KIJK)
        if self._control:
            rollen.append(ROL_BEDIEN)
        return rollen

    def identificeer(self, headers):
        """Geeft ``(identiteit, None)`` of ``(None, GEEN_GEGEVENS|FOUT_GEGEVENS)``.

        Staat er een Authorization-header, dan beslist die; een foute header
        valt nooit terug op de cookie.
        """

        aanwezig, token = lees_bearer(headers)
        if aanwezig:
            if not token:
                return None, FOUT_GEGEVENS
            # Beide vergelijkingen altijd uitvoeren (constante tijd).
            is_control = bool(self._control) and _gelijk(token, self._control)
            is_view = bool(self._view) and _gelijk(token, self._view)
            if is_control:
                return Identiteit(ROL_BEDIEN, "token", token=token), None
            if is_view:
                return Identiteit(ROL_KIJK, "token", token=token), None
            apparaat = self.register.zoek(token)
            if apparaat:
                return Identiteit(apparaat["rol"], "apparaat", apparaat, token=token), None
            return None, FOUT_GEGEVENS

        cookie = lees_cookie(headers)
        if cookie is None:
            return None, GEEN_GEGEVENS
        apparaat = self.register.zoek(cookie)
        if apparaat:
            return Identiteit(apparaat["rol"], "apparaat", apparaat, token=cookie, via="cookie"), None
        return None, FOUT_GEGEVENS
