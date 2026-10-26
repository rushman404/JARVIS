"""Muzieksmaak via Spotify (Fase 21, M5).

JARVIS koppelt uw Spotify-account met de Web API (PKCE: geen geheime
sleutel nodig). Hij leest uw toptracks, topartiesten, recent afgespeeld en
uw eigen playlists, en mag (sinds 2026-10-26, Premium) het afspelen
bedienen. Daarmee:

* "zet iets op wat ik leuk vind" → een nummer uit uw eigen smaak opent in
  Spotify (op de game-pc);
* "stel muziek voor" / "heb je een muziektip?" → JARVIS stelt iets voor en
  vraagt "Zal ik hem opzetten?";
* "wat is mijn muzieksmaak?" → uw meest beluisterde artiesten;
* bij de gamemodus stelt JARVIS een passende playlist of een nummer voor.

Afspelen gaat via de Web API op een Spotify-apparaat (bij voorkeur de
game-pc; draait Spotify daar niet, dan opent JARVIS de app eerst). Is de
koppeling nog van vóór de afspeelrechten, of lukt het niet, dan opent hij
het nummer als ``spotify:``-link in de app (dan staat het alleen klaar).

Tokens staan in ``memory/spotify_token.json`` (niet in git) en komen nooit
in de log, de URL of het auditlog. Koppelen: ``scripts/spotify_koppelen.py``
(zie docs/spotify.md).
"""

import base64
import hashlib
import json
import logging
import os
import random
import re
import secrets
import time
import urllib.parse

logger = logging.getLogger(__name__)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(PROJECT, "memory", "spotify_token.json")
SMAAK_FILE = os.path.join(PROJECT, "memory", "spotify_smaak.json")

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES_LEZEN = "user-top-read user-read-recently-played playlist-read-private"
# Afspelen (wens 2026-10-26, Premium): apparaten zien en afspelen starten.
SCOPES_AFSPELEN = "user-read-playback-state user-modify-playback-state"
SCOPES = SCOPES_LEZEN + " " + SCOPES_AFSPELEN
# Hoe lang JARVIS wacht tot Spotify (net geopend) zich als apparaat meldt.
APPARAAT_WACHT = 15.0

# Het smaakprofiel wordt hooguit zo vaak ververst (seconden).
SMAAK_GELDIG = 6 * 3600
HTTP_TIMEOUT = 8

# Playlistnamen die bij een modus passen.
MODUS_WOORDEN = {
    "gaming": ("game", "gaming", "gamen", "focus", "hype", "energy", "workout"),
}


class SpotifyFout(Exception):
    def __init__(self, melding, status=None):
        super().__init__(melding)
        self.status = status


def _client_id():
    from config import SPOTIFY_CLIENT_ID

    return SPOTIFY_CLIENT_ID


def _redirect():
    from config import SPOTIFY_REDIRECT_URI

    return SPOTIFY_REDIRECT_URI


def _lees(pad):
    try:
        with open(pad, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _schrijf(pad, data):
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    tmp = pad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, pad)


# -----------------------------------------------------------------
# PKCE-koppeling
# -----------------------------------------------------------------

def maak_verifier():
    return secrets.token_urlsafe(64)[:96]


def challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def autorisatie_url(client_id, verifier, state, redirect=None):
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect or _redirect(),
        "code_challenge_method": "S256",
        "code_challenge": challenge(verifier),
        "scope": SCOPES,
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def _token_opslaan(antwoord, pad, klok, oud_refresh=None):
    if not isinstance(antwoord, dict) or "access_token" not in antwoord:
        raise SpotifyFout("Spotify gaf geen geldig token terug.")
    data = {
        "access_token": antwoord["access_token"],
        "refresh_token": antwoord.get("refresh_token") or oud_refresh,
        "verloopt": klok() + int(antwoord.get("expires_in") or 3600),
        "scope": antwoord.get("scope", SCOPES),
    }
    _schrijf(pad, data)
    return data


def wissel_code(code, verifier, client_id=None, redirect=None, pad=None,
                http=None, klok=time.time):
    """Ruilt de code uit de browser om voor tokens en slaat ze op."""

    pad = pad or TOKEN_FILE
    http = http or _requests()
    r = http.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect or _redirect(),
        "client_id": client_id or _client_id(),
        "code_verifier": verifier,
    }, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise SpotifyFout(f"Koppelen mislukt (HTTP {r.status_code}).")
    return _token_opslaan(r.json(), pad, klok)


def _requests():
    import requests

    return requests


# -----------------------------------------------------------------
# Lezen uit de Web API
# -----------------------------------------------------------------

class SpotifyKlant:
    def __init__(self, client_id=None, pad=None, http=None, klok=time.time):
        self.client_id = client_id
        self.pad = pad or TOKEN_FILE
        self.http = http
        self.klok = klok

    def is_gekoppeld(self):
        data = _lees(self.pad)
        return bool(data and data.get("refresh_token") and (self.client_id or _client_id()))

    def _token(self):
        data = _lees(self.pad)
        if not data or not data.get("refresh_token"):
            raise SpotifyFout("Spotify is niet gekoppeld.")
        if data.get("access_token") and data.get("verloopt", 0) - 60 > self.klok():
            return data["access_token"]
        http = self.http or _requests()
        r = http.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            "client_id": self.client_id or _client_id(),
        }, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            raise SpotifyFout(f"Spotify-token vernieuwen mislukt (HTTP {r.status_code}).")
        return _token_opslaan(r.json(), self.pad, self.klok, data["refresh_token"])["access_token"]

    def get(self, pad, params=None):
        http = self.http or _requests()
        r = http.get(API + pad, params=params or {}, timeout=HTTP_TIMEOUT,
                     headers={"Authorization": "Bearer " + self._token()})
        if r.status_code != 200:
            raise SpotifyFout(f"Spotify antwoordde met HTTP {r.status_code}.", r.status_code)
        return r.json()

    def put(self, pad, params=None, body=None):
        http = self.http or _requests()
        r = http.put(API + pad, params=params or {}, json=body or {}, timeout=HTTP_TIMEOUT,
                     headers={"Authorization": "Bearer " + self._token()})
        if r.status_code not in (200, 202, 204):
            raise SpotifyFout(f"Spotify antwoordde met HTTP {r.status_code}.", r.status_code)

    def mag_afspelen(self):
        """True als de koppeling de afspeelrechten heeft (opnieuw gekoppeld)."""

        data = _lees(self.pad) or {}
        return "user-modify-playback-state" in str(data.get("scope") or "").split()


def _nummer(t):
    artiesten = [a.get("name", "") for a in (t.get("artists") or [])]
    return {"naam": t.get("name", ""), "artiest": artiesten[0] if artiesten else "",
            "uri": t.get("uri", "")}


def haal_profiel(klant):
    """Leest de smaak uit Spotify (vijf kleine verzoeken)."""

    def items(pad, params):
        return (klant.get(pad, params) or {}).get("items") or []

    kort_art = items("/me/top/artists", {"time_range": "short_term", "limit": 10})
    lang_art = items("/me/top/artists", {"time_range": "medium_term", "limit": 20})
    kort_nr = items("/me/top/tracks", {"time_range": "short_term", "limit": 20})
    lang_nr = items("/me/top/tracks", {"time_range": "medium_term", "limit": 30})
    recent = items("/me/player/recently-played", {"limit": 30})
    playlists = items("/me/playlists", {"limit": 50})

    genres = {}
    for a in kort_art + lang_art:
        for g in a.get("genres") or []:
            genres[g] = genres.get(g, 0) + 1
    return {
        "artiesten_kort": [a.get("name", "") for a in kort_art],
        "artiesten": [a.get("name", "") for a in lang_art],
        "nummers_kort": [_nummer(t) for t in kort_nr if t.get("uri")],
        "nummers": [_nummer(t) for t in lang_nr if t.get("uri")],
        "recent": [(i.get("track") or {}).get("uri", "") for i in recent],
        "playlists": [{"naam": p.get("name", ""), "uri": p.get("uri", "")}
                      for p in playlists if p and p.get("uri")],
        "genres": [g for g, _ in sorted(genres.items(), key=lambda x: -x[1])][:5],
        "bijgewerkt": time.time(),
    }


def profiel(klant=None, pad=None, klok=time.time, vers=False):
    """Het smaakprofiel uit de cache, of vers uit Spotify als het oud is."""

    pad = pad or SMAAK_FILE
    klant = klant or SpotifyKlant()
    oud = _lees(pad)
    if not vers and oud and klok() - oud.get("bijgewerkt", 0) < SMAAK_GELDIG:
        return oud
    try:
        nieuw = haal_profiel(klant)
    except SpotifyFout:
        if oud:
            return oud
        raise
    try:
        _schrijf(pad, nieuw)
    except OSError:
        logger.debug("Kon het smaakprofiel niet bewaren", exc_info=True)
    return nieuw


# -----------------------------------------------------------------
# Kiezen
# -----------------------------------------------------------------

def kies_nummer(prof, rng=random):
    """Een nummer uit uw smaak dat u de laatste tijd niet al draaide."""

    recent = set(prof.get("recent") or [])
    kort = [n for n in prof.get("nummers_kort") or [] if n["uri"] not in recent]
    lang = [n for n in prof.get("nummers") or [] if n["uri"] not in recent]
    pool = kort * 2 + lang  # de laatste weken tellen dubbel
    if not pool:
        pool = (prof.get("nummers_kort") or []) + (prof.get("nummers") or [])
    return rng.choice(pool) if pool else None


def kies_voor_modus(prof, modus, rng=random):
    """Een eigen playlist die bij de modus past, anders een nummer."""

    woorden = MODUS_WOORDEN.get(modus, ())
    passend = [p for p in prof.get("playlists") or []
               if any(w in p["naam"].lower() for w in woorden)]
    if passend:
        p = rng.choice(passend)
        return {"naam": p["naam"], "artiest": "", "uri": p["uri"], "playlist": True}
    return kies_nummer(prof, rng)


def label(keuze):
    if keuze.get("playlist"):
        return f"uw playlist '{keuze['naam']}'"
    if keuze.get("artiest"):
        return f"'{keuze['naam']}' van {keuze['artiest']}"
    return f"'{keuze['naam']}'"


def beschrijf_smaak(prof):
    namen = [n for n in (prof.get("artiesten_kort") or prof.get("artiesten") or []) if n][:3]
    if not namen:
        return "Ik heb nog te weinig gegevens over uw muzieksmaak, sir."
    lijst = namen[0] if len(namen) == 1 else ", ".join(namen[:-1]) + " en " + namen[-1]
    zin = f"De laatste tijd luistert u vooral naar {lijst}."
    if prof.get("genres"):
        zin += f" Vooral {', '.join(prof['genres'][:2])}."
    return zin


# -----------------------------------------------------------------
# Afspelen (via de Spotify-app) en het voorstel
# -----------------------------------------------------------------

def kies_apparaat(apparaten):
    """Het Spotify-apparaat om op af te spelen: de ingestelde naam
    (SPOTIFY_APPARAAT), anders het actieve, anders een computer."""

    from config import SPOTIFY_APPARAAT

    apparaten = [a for a in apparaten or [] if a.get("id") and not a.get("is_restricted")]
    if not apparaten:
        return None
    if SPOTIFY_APPARAAT:
        for a in apparaten:
            if SPOTIFY_APPARAAT.lower() in str(a.get("name", "")).lower():
                return a
    for a in apparaten:
        if a.get("is_active"):
            return a
    for a in apparaten:
        if str(a.get("type", "")).lower() == "computer":
            return a
    return apparaten[0]


def afspelen(keuze, klant, pc_tool, slaap=time.sleep):
    """Start de keuze via de Web API. True als het lukte, False als er geen
    Spotify-apparaat te vinden is. Gooit SpotifyFout bij een weigering."""

    apparaat = kies_apparaat((klant.get("/me/player/devices") or {}).get("devices"))
    if apparaat is None:
        # Spotify draait nergens: open de app (op de game-pc) en wacht tot
        # hij zich meldt.
        pc_tool("open_program", {"program": "Spotify"})
        gewacht = 0.0
        while apparaat is None and gewacht < APPARAAT_WACHT:
            slaap(1.5)
            gewacht += 1.5
            apparaat = kies_apparaat((klant.get("/me/player/devices") or {}).get("devices"))
        if apparaat is None:
            return False
    uri = keuze["uri"]
    body = {"uris": [uri]} if uri.startswith("spotify:track:") else {"context_uri": uri}
    klant.put("/me/player/play", {"device_id": apparaat["id"]}, body)
    return True


def speel(keuze, pc_tool=None, klant=None, slaap=time.sleep):
    """Speelt de keuze af. Geeft het antwoord terug."""

    if pc_tool is None:
        from core.filmmodus import _pc_tool as pc_tool
    klant = klant or SpotifyKlant()
    try:
        if klant.is_gekoppeld() and klant.mag_afspelen() and afspelen(keuze, klant, pc_tool, slaap):
            return f"Speelt nu: {label(keuze)}."
    except SpotifyFout as fout:
        if fout.status == 403:
            return "Spotify weigert het afspelen, sir. Daarvoor is Spotify Premium nodig."
        logger.info("Afspelen via Spotify lukte niet (%s); ik open de link.", fout)
    r = pc_tool("spotify_open", {"uri": keuze["uri"]})
    if not getattr(r, "ok", False):
        return "Spotify kon ik niet openen, sir."
    from core.filmmodus import _gegeven

    if _gegeven(r, "speelt"):
        return f"Speelt nu: {label(keuze)}."
    tekst = f"{label(keuze)[:1].upper() + label(keuze)[1:]} staat klaar in Spotify."
    try:
        if klant.is_gekoppeld() and not klant.mag_afspelen():
            tekst += " Koppel Spotify opnieuw, dan kan ik het meteen laten spelen."
    except Exception:
        pass
    return tekst


KIND = "muziek_voorstel"


def stel_voor(keuze, inleiding=""):
    """Zet het voorstel klaar voor "ja" en geeft de vraag terug."""

    from core import confirmation

    vraag = f"Wat dacht u van {label(keuze)}? Zal ik hem opzetten?"
    # "question" en "action" toont het dashboard in de ja/nee-popup.
    confirmation.set_pending(KIND, {"keuze": keuze, "question": vraag,
                                    "action": f"{label(keuze)} opzetten in Spotify"}, ttl=60)
    return inleiding + vraag


def na_ja(pending, pc_tool=None):
    keuze = pending.get("keuze") or (pending.get("payload") or {}).get("keuze")
    if not isinstance(keuze, dict) or not keuze.get("uri"):
        return "Ik weet niet meer wat ik voorstelde, sir."
    return speel(keuze, pc_tool)


def voorstel_bij_modus(modus, klant=None):
    """Eén zin met een voorstel voor deze modus, of None (niet gekoppeld,
    geen gegevens of Spotify onbereikbaar). Gooit nooit."""

    try:
        klant = klant or SpotifyKlant()
        if not klant.is_gekoppeld():
            return None
        keuze = kies_voor_modus(profiel(klant), modus)
        if not keuze:
            return None
        return stel_voor(keuze, "Muziek erbij? ")
    except Exception:
        logger.debug("Geen muziekvoorstel bij de modus", exc_info=True)
        return None


# -----------------------------------------------------------------
# Brain-router
# -----------------------------------------------------------------

_SPEEL = re.compile(
    r"^(?:zet|speel|draai|doe)\s+(?:eens\s+)?(?:iets|wat|muziek|een\s+nummer)\s+(?:op\s+)?"
    r"(?:wat|die|dat)\s+ik\s+(?:leuk|mooi|goed)\s+vind(?:\s+op)?$"
    r"|^verras\s+me(?:\s+met\s+muziek)?$|^zet\s+(?:een\s+)?muziektip\s+op$"
)
_VOORSTEL = re.compile(
    r"^(?:stel\s+(?:eens\s+)?(?:wat\s+|iets\s+|een\s+nummer\s+)?(?:muziek\s+)?voor"
    r"|wat\s+(?:zal|moet|kan)\s+ik\s+(?:gaan\s+)?(?:luisteren|opzetten)"
    r"|heb\s+je\s+(?:een\s+)?muziektip|muziektip|geef\s+(?:me\s+)?(?:een\s+)?muziektip)$"
)
_SMAAK = re.compile(
    r"^(?:wat\s+is\s+mijn\s+muzieksmaak|welke\s+(?:artiesten|muziek)\s+luister\s+ik\s+(?:het\s+)?(?:meest|vaak|veel)"
    r"|naar\s+wie\s+luister\s+ik\s+(?:het\s+)?(?:meest|vaak|veel)|wie\s+zijn\s+mijn\s+favoriete\s+artiesten)$"
)
NIET_GEKOPPELD = ("Spotify is nog niet gekoppeld, sir. In docs/spotify.md staat hoe dat moet "
                  "(eenmalig, een paar minuten).")


def herken(tekst):
    from core.filmmodus import _schoon

    t = _schoon(tekst)
    if _SPEEL.match(t):
        return "speel"
    if _VOORSTEL.match(t):
        return "voorstel"
    if _SMAAK.match(t):
        return "smaak"
    return None


def voer_uit(tekst, klant=None, pc_tool=None):
    soort = herken(tekst)
    if soort is None:
        return None
    klant = klant or SpotifyKlant()
    if not klant.is_gekoppeld():
        return NIET_GEKOPPELD
    try:
        prof = profiel(klant)
    except SpotifyFout as fout:
        logger.info("Spotify niet bereikbaar: %s", fout)
        return "Spotify is nu niet bereikbaar, sir."
    if soort == "smaak":
        return beschrijf_smaak(prof)
    keuze = kies_nummer(prof)
    if not keuze:
        return "Ik heb nog te weinig gegevens over uw muzieksmaak, sir."
    if soort == "speel":
        return speel(keuze, pc_tool, klant)
    return stel_voor(keuze)
