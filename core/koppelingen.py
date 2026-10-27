"""Koppelingen met externe diensten (Fase 23, M1).

Eén plek voor alle accounts die JARVIS mag gebruiken (Spotify, straks Gmail
en de iCloud-agenda):

* **tokens veilig bewaren** in ``memory/`` (buiten git), atomair geschreven;
  een token komt nooit in de log, het auditlog, een URL of een antwoord;
* **OAuth met PKCE** (:class:`OAuthKoppeling`): inlog-URL maken, de code uit
  de browser omruilen en het token vanzelf verversen. Lukt verversen niet
  meer (toegang ingetrokken), dan onthoudt hij dat als *probleem*: "opnieuw
  koppelen";
* **koppelen met een script** (:func:`ontvang_code`): het script opent de
  inlogpagina en vangt het antwoord op via ``http://127.0.0.1:<poort>/…``;
* **status** (:func:`overzicht`): per koppeling gekoppeld ja/nee, welke
  rechten en of er een probleem is, voor "welke koppelingen heb ik?", het
  Systeem-paneel en ⚙.

Een nieuwe koppeling meldt zich aan in ``_STANDAARD`` met een functie die zijn
status geeft (zonder tokens).
"""

import base64
import hashlib
import importlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse

logger = logging.getLogger("jarvis.koppelingen")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(PROJECT, "memory", "koppelingen")
HTTP_TIMEOUT = 10
WACHT_SECONDEN = 300

PROBLEEM_OPNIEUW = "opnieuw koppelen nodig"

# id -> "module:functie" die de status geeft. Zo laadt het overzicht alleen
# wat het nodig heeft, en kan een kapotte koppeling de rest niet raken.
_STANDAARD = {
    "spotify": "core.spotify_smaak:koppeling_status",
    "gmail": "core.gmail:koppeling_status",
}


class KoppelFout(Exception):
    """Een koppeling werkt niet; de melding is veilig om te tonen."""

    def __init__(self, melding, status=None):
        super().__init__(melding)
        self.status = status


# -----------------------------------------------------------------
# Opslag
# -----------------------------------------------------------------

def pad_voor(naam):
    """Standaardpad van het tokenbestand van een koppeling."""

    if not re.fullmatch(r"[a-z0-9_]{1,30}", naam or ""):
        raise ValueError(f"Ongeldige koppelingsnaam: {naam!r}")
    return os.path.join(MAP, naam + ".json")


def lees_json(pad):
    try:
        with open(pad, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def schrijf_json(pad, data):
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    tmp = pad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, pad)


# -----------------------------------------------------------------
# PKCE
# -----------------------------------------------------------------

def maak_verifier():
    return secrets.token_urlsafe(64)[:96]


def challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _requests():
    import requests

    return requests


def verzoek(fn, *args, dienst="de dienst", **kwargs):
    """Een HTTP-verzoek; een netwerkfout wordt een :class:`KoppelFout`."""

    try:
        return fn(*args, **kwargs)
    except KoppelFout:
        raise
    except Exception as fout:
        raise KoppelFout(f"{dienst} reageerde niet ({type(fout).__name__}).", "netwerk") from None


class OAuthDienst:
    """Vaste gegevens van een OAuth-dienst (geen geheimen)."""

    def __init__(self, id, naam, auth_url, token_url, scopes, client_id_fn, redirect_fn,
                 client_secret_fn=None, extra_auth=None, rechten=None):
        self.id = id
        self.naam = naam
        self.auth_url = auth_url
        self.token_url = token_url
        self.scopes = scopes
        self.client_id_fn = client_id_fn
        self.redirect_fn = redirect_fn
        self.client_secret_fn = client_secret_fn or (lambda: "")
        self.extra_auth = dict(extra_auth or {})
        # scope -> leesbaar recht ("lezen", "versturen"), voor de status.
        self.rechten = dict(rechten or {})


class OAuthKoppeling:
    """Tokens van één account: koppelen, verversen en de status."""

    def __init__(self, dienst, pad=None, http=None, klok=time.time):
        self.dienst = dienst
        self.pad = pad or pad_voor(dienst.id)
        self.http = http
        self.klok = klok

    # -- koppelen ---------------------------------------------------

    def autorisatie_url(self, verifier, state, scopes=None):
        params = {
            "client_id": self.dienst.client_id_fn(),
            "response_type": "code",
            "redirect_uri": self.dienst.redirect_fn(),
            "code_challenge_method": "S256",
            "code_challenge": challenge(verifier),
            "scope": scopes or self.dienst.scopes,
            "state": state,
        }
        params.update(self.dienst.extra_auth)
        return self.dienst.auth_url + "?" + urllib.parse.urlencode(params)

    def _client_velden(self):
        velden = {"client_id": self.dienst.client_id_fn()}
        geheim = self.dienst.client_secret_fn()
        if geheim:
            velden["client_secret"] = geheim
        return velden

    def wissel_code(self, code, verifier):
        """Ruilt de code uit de browser om voor tokens en slaat ze op."""

        http = self.http or _requests()
        r = verzoek(http.post, self.dienst.token_url, dienst=self.dienst.naam, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.dienst.redirect_fn(),
            "code_verifier": verifier,
            **self._client_velden(),
        }, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            raise KoppelFout(f"Koppelen met {self.dienst.naam} mislukt (HTTP {r.status_code}).",
                             r.status_code)
        return self._opslaan(r.json())

    def _opslaan(self, antwoord, oud=None):
        if not isinstance(antwoord, dict) or "access_token" not in antwoord:
            raise KoppelFout(f"{self.dienst.naam} gaf geen geldig token terug.")
        oud = oud or {}
        data = {
            "access_token": antwoord["access_token"],
            "refresh_token": antwoord.get("refresh_token") or oud.get("refresh_token"),
            "verloopt": self.klok() + int(antwoord.get("expires_in") or 3600),
            "scope": antwoord.get("scope") or oud.get("scope") or self.dienst.scopes,
            "gekoppeld_op": oud.get("gekoppeld_op") or self.klok(),
        }
        schrijf_json(self.pad, data)
        return data

    # -- gebruiken --------------------------------------------------

    def gegevens(self):
        return lees_json(self.pad) or {}

    def is_gekoppeld(self):
        return bool(self.gegevens().get("refresh_token") and self.dienst.client_id_fn())

    def heeft(self, scope):
        return scope in str(self.gegevens().get("scope") or "").split()

    def access_token(self):
        """Een geldig access-token; ververst het zo nodig."""

        data = self.gegevens()
        if not data.get("refresh_token"):
            raise KoppelFout(f"{self.dienst.naam} is niet gekoppeld.")
        if data.get("access_token") and data.get("verloopt", 0) - 60 > self.klok():
            return data["access_token"]
        http = self.http or _requests()
        r = verzoek(http.post, self.dienst.token_url, dienst=self.dienst.naam, data={
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            **self._client_velden(),
        }, timeout=HTTP_TIMEOUT)
        if r.status_code in (400, 401):
            # Toegang ingetrokken of verlopen: alleen opnieuw koppelen helpt.
            data["probleem"] = PROBLEEM_OPNIEUW
            schrijf_json(self.pad, data)
            raise KoppelFout(f"{self.dienst.naam} moet opnieuw gekoppeld worden.", r.status_code)
        if r.status_code != 200:
            raise KoppelFout(f"{self.dienst.naam}-token vernieuwen mislukt (HTTP {r.status_code}).",
                             r.status_code)
        return self._opslaan(r.json(), data)["access_token"]

    def status(self):
        """Voor het overzicht: nooit tokens, alleen wat er mag."""

        data = self.gegevens()
        gekoppeld = self.is_gekoppeld()
        rechten = [label for scope, label in self.dienst.rechten.items() if self.heeft(scope)]
        return {
            "id": self.dienst.id,
            "naam": self.dienst.naam,
            "gekoppeld": gekoppeld,
            "rechten": list(dict.fromkeys(rechten)) if gekoppeld else [],
            "probleem": data.get("probleem") if gekoppeld else None,
        }


# -----------------------------------------------------------------
# Koppelen vanuit een script
# -----------------------------------------------------------------

def ontvang_code(redirect, state, open_fn=None, wacht=WACHT_SECONDEN, naam="de dienst",
                 toon_fn=print):
    """Wacht op de terugkeer van de browser en geeft de code.

    ``redirect`` moet ``http://127.0.0.1:<poort>/<pad>`` zijn. ``open_fn``
    opent de inlogpagina (krijgt geen argumenten). Gooit :class:`KoppelFout`.
    """

    from http.server import BaseHTTPRequestHandler, HTTPServer

    deel = urllib.parse.urlparse(redirect)
    if deel.scheme != "http" or deel.hostname not in ("127.0.0.1", "localhost") or not deel.port:
        raise KoppelFout(f"Het terugkeeradres moet http://127.0.0.1:<poort>/... zijn, niet {redirect}.")
    uitkomst = {}
    klaar = threading.Event()

    class Terug(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (naam is voorgeschreven door http.server)
            url = urllib.parse.urlparse(self.path)
            if url.path != (deel.path or "/"):
                self.send_response(404)
                self.end_headers()
                return
            vraag = urllib.parse.parse_qs(url.query)
            if vraag.get("state", [""])[0] != state:
                uitkomst["fout"] = "De controlecode klopte niet (state). Probeer het opnieuw."
            elif "error" in vraag:
                uitkomst["fout"] = f"{naam} gaf geen toestemming ({vraag['error'][0][:60]})."
            else:
                uitkomst["code"] = vraag.get("code", [""])[0]
            tekst = (f"{naam} is gekoppeld aan JARVIS. U kunt dit venster sluiten."
                     if uitkomst.get("code") else "Koppelen is niet gelukt. Kijk in het venster van het script.")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(tekst.encode("utf-8"))
            klaar.set()

        def log_message(self, *args):
            pass  # de URL bevat de code: niet loggen

    server = HTTPServer(("127.0.0.1", deel.port), Terug)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if open_fn:
            open_fn()
        if not klaar.wait(wacht):
            raise KoppelFout(f"Geen antwoord van {naam} binnen {wacht // 60} minuten. Probeer het opnieuw.")
    finally:
        server.shutdown()
        server.server_close()
    if "fout" in uitkomst:
        raise KoppelFout(uitkomst["fout"])
    if not uitkomst.get("code"):
        raise KoppelFout(f"{naam} stuurde geen code terug.")
    return uitkomst["code"]


# -----------------------------------------------------------------
# Overzicht
# -----------------------------------------------------------------

def overzicht(bronnen=None):
    """Status van alle koppelingen (lijst van dicts, zonder tokens)."""

    uit = []
    for id_, doel in (bronnen or _STANDAARD).items():
        try:
            if callable(doel):
                status = doel()
            else:
                module, functie = doel.split(":")
                status = getattr(importlib.import_module(module), functie)()
        except Exception as fout:
            logger.debug("Status van koppeling %s mislukte.", id_, exc_info=True)
            status = {"id": id_, "naam": id_.capitalize(), "gekoppeld": False, "rechten": [],
                      "probleem": f"status onbekend ({type(fout).__name__})"}
        uit.append({
            "id": status.get("id") or id_,
            "naam": status.get("naam") or id_.capitalize(),
            "gekoppeld": bool(status.get("gekoppeld")),
            "rechten": [str(r) for r in status.get("rechten") or []],
            "probleem": status.get("probleem") or None,
        })
    return uit


def _rechten(k):
    return f" ({' en '.join(k['rechten'])})" if k["rechten"] else ""


def beschrijf(lijst=None):
    """Gesproken antwoord op "welke koppelingen heb ik?"."""

    lijst = overzicht() if lijst is None else lijst
    if not lijst:
        return "Er zijn nog geen koppelingen ingesteld, sir."
    zinnen = []
    goed = [k for k in lijst if k["gekoppeld"] and not k["probleem"]]
    fout = [k for k in lijst if k["gekoppeld"] and k["probleem"]]
    los = [k for k in lijst if not k["gekoppeld"]]
    if goed:
        zinnen.append("Gekoppeld: " + "; ".join(k["naam"] + _rechten(k) for k in goed) + ".")
    for k in fout:
        zinnen.append(f"{k['naam']}: {k['probleem']}.")
    if los:
        zinnen.append("Nog niet gekoppeld: " + ", ".join(k["naam"] for k in los) + ".")
    return " ".join(zinnen)


_VRAAG = re.compile(
    r"^(?:welke|wat\s+voor)\s+koppelingen\s+(?:heb\s+ik|zijn\s+er|heeft\s+jarvis)$"
    r"|^(?:wat\s+is\s+de\s+)?status\s+van\s+(?:mijn|de)\s+koppelingen$"
    r"|^(?:zijn|werken)\s+(?:mijn|de|alle)\s+koppelingen(?:\s+(?:in\s+orde|goed))?$"
    r"|^(?:mijn\s+)?koppelingen$"
)


def probeer_commando(command, lijst_fn=None):
    """``None`` als het geen koppelingsvraag is, anders het antwoord."""

    tekst = (command or "").strip().lower().rstrip(" ?.!")
    if not _VRAAG.match(tekst):
        return None
    return beschrijf((lijst_fn or overzicht)())
