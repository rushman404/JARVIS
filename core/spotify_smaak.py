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
(zie docs/spotify.md). Opslag, PKCE en de status lopen sinds Fase 23 via
:mod:`core.koppelingen`.
"""

import logging
import os
import random
import re
import time
import urllib.parse

from core import koppelingen
from core.koppelingen import challenge, maak_verifier  # noqa: F401 (scripts en tests)

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
APPARAAT_WACHT = 20.0
# Na de afspeelopdracht: zo vaak (elke seconde) vragen of het echt speelt.
CONTROLE_POGINGEN = 4

# Het smaakprofiel wordt hooguit zo vaak ververst (seconden).
SMAAK_GELDIG = 6 * 3600
# Versie 2 (2026-10-26): per nummer ook het album en of het speelbaar is.
PROFIEL_VERSIE = 2
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


_lees = koppelingen.lees_json
_schrijf = koppelingen.schrijf_json


# -----------------------------------------------------------------
# PKCE-koppeling
# -----------------------------------------------------------------

def autorisatie_url(client_id, verifier, state, redirect=None):
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect or _redirect(),
        "code_challenge_method": "S256",
        "code_challenge": challenge(verifier),
        "scope": SCOPES,
        "state": state,
        # Altijd de toestemmingspagina tonen: anders stuurt Spotify een app
        # die al eens goedgekeurd is soms meteen door, zonder de nieuwe
        # rechten (afspelen) te vragen.
        "show_dialog": "true",
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
    oud = _lees(pad) or {}
    if oud.get("gekoppeld_op"):
        data["gekoppeld_op"] = oud["gekoppeld_op"]
    _schrijf(pad, data)
    return data


def wissel_code(code, verifier, client_id=None, redirect=None, pad=None,
                http=None, klok=time.time):
    """Ruilt de code uit de browser om voor tokens en slaat ze op."""

    pad = pad or TOKEN_FILE
    http = http or _requests()
    r = _verzoek(http.post, TOKEN_URL, data={
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


def _verzoek(fn, *args, **kwargs):
    """Een HTTP-verzoek; een netwerkfout (time-out, geen verbinding) wordt
    een SpotifyFout, zodat JARVIS netjes antwoordt in plaats van vast te
    lopen (fix 2026-10-26: time-out bij api.spotify.com)."""

    try:
        return fn(*args, **kwargs)
    except SpotifyFout:
        raise
    except Exception as fout:
        raise SpotifyFout(f"Spotify reageerde niet ({type(fout).__name__}).", "netwerk") from None


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
        r = _verzoek(http.post, TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            "client_id": self.client_id or _client_id(),
        }, timeout=HTTP_TIMEOUT)
        if r.status_code in (400, 401):
            # Toegang ingetrokken: alleen opnieuw koppelen helpt (Fase 23).
            data["probleem"] = koppelingen.PROBLEEM_OPNIEUW
            _schrijf(self.pad, data)
            raise SpotifyFout("Spotify moet opnieuw gekoppeld worden.", r.status_code)
        if r.status_code != 200:
            raise SpotifyFout(f"Spotify-token vernieuwen mislukt (HTTP {r.status_code}).")
        return _token_opslaan(r.json(), self.pad, self.klok, data["refresh_token"])["access_token"]

    def get(self, pad, params=None):
        http = self.http or _requests()
        r = _verzoek(http.get, API + pad, params=params or {}, timeout=HTTP_TIMEOUT,
                     headers={"Authorization": "Bearer " + self._token()})
        if r.status_code == 204:
            return {}  # bijv. /me/player als er niets speelt
        if r.status_code != 200:
            raise SpotifyFout(f"Spotify antwoordde met HTTP {r.status_code}.", r.status_code)
        return r.json()

    def put(self, pad, params=None, body=None):
        http = self.http or _requests()
        r = _verzoek(http.put, API + pad, params=params or {}, json=body or {}, timeout=HTTP_TIMEOUT,
                     headers={"Authorization": "Bearer " + self._token()})
        if r.status_code not in (200, 202, 204):
            raise SpotifyFout(f"Spotify antwoordde met HTTP {r.status_code}.", r.status_code)

    def mag_afspelen(self):
        """True als de koppeling de afspeelrechten heeft (opnieuw gekoppeld)."""

        data = _lees(self.pad) or {}
        return "user-modify-playback-state" in str(data.get("scope") or "").split()


def koppeling_status(klant=None):
    """Voor :func:`core.koppelingen.overzicht` (zonder tokens)."""

    klant = klant or SpotifyKlant()
    gekoppeld = klant.is_gekoppeld()
    rechten = ["lezen", "afspelen"] if klant.mag_afspelen() else ["lezen"]
    return {
        "id": "spotify",
        "naam": "Spotify",
        "gekoppeld": gekoppeld,
        "rechten": rechten if gekoppeld else [],
        "probleem": (_lees(klant.pad) or {}).get("probleem") if gekoppeld else None,
    }


def _nummer(t):
    artiesten = [a.get("name", "") for a in (t.get("artists") or [])]
    return {"naam": t.get("name", ""), "artiest": artiesten[0] if artiesten else "",
            "uri": t.get("uri", ""), "album": (t.get("album") or {}).get("uri", ""),
            # Met market=from_token zegt Spotify of het hier af te spelen is.
            "speelbaar": t.get("is_playable", True) is not False}


def haal_profiel(klant):
    """Leest de smaak uit Spotify (vijf kleine verzoeken)."""

    def items(pad, params):
        return (klant.get(pad, params) or {}).get("items") or []

    kort_art = items("/me/top/artists", {"time_range": "short_term", "limit": 10})
    lang_art = items("/me/top/artists", {"time_range": "medium_term", "limit": 20})
    kort_nr = items("/me/top/tracks", {"time_range": "short_term", "limit": 20, "market": "from_token"})
    lang_nr = items("/me/top/tracks", {"time_range": "medium_term", "limit": 30, "market": "from_token"})
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
        "versie": PROFIEL_VERSIE,
    }


def profiel(klant=None, pad=None, klok=time.time, vers=False):
    """Het smaakprofiel uit de cache, of vers uit Spotify als het oud is."""

    pad = pad or SMAAK_FILE
    klant = klant or SpotifyKlant()
    oud = _lees(pad)
    if not vers and oud and oud.get("versie") == PROFIEL_VERSIE             and klok() - oud.get("bijgewerkt", 0) < SMAAK_GELDIG:
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
    speelbaar = [n for n in (prof.get("nummers_kort") or []) + (prof.get("nummers") or [])
                 if n.get("speelbaar", True) is not False]
    kort = [n for n in prof.get("nummers_kort") or [] if n["uri"] not in recent and n in speelbaar]
    lang = [n for n in prof.get("nummers") or [] if n["uri"] not in recent and n in speelbaar]
    pool = kort * 2 + lang  # de laatste weken tellen dubbel
    if not pool:
        pool = speelbaar
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


def afspeel_body(klant, keuze):
    """Wat JARVIS naar /me/player/play stuurt.

    Een los nummer (``{"uris": [...]}``) laadt de Spotify-app op Windows vaak
    niet, of stopt meteen (gezien op 2026-10-26); een playlist werkte wel.
    Daarom speelt JARVIS een nummer binnen zijn eigen album, vanaf dat
    nummer, zoals u het in de app zelf zou starten.
    """

    uri = keuze["uri"]
    if not uri.startswith("spotify:track:"):
        return {"context_uri": uri}
    album = keuze.get("album")
    if not album:
        try:
            album = ((klant.get("/tracks/" + uri.rsplit(":", 1)[-1]) or {}).get("album") or {}).get("uri")
        except SpotifyFout:
            album = None
    if album:
        return {"context_uri": album, "offset": {"uri": uri}}
    return {"uris": [uri]}


def _speelt_het(klant, uri):
    """True als Spotify zegt dat precies deze keuze nu speelt."""

    nu = klant.get("/me/player") or {}
    if not nu.get("is_playing"):
        return False
    if uri.startswith("spotify:track:"):
        item = nu.get("item") or {}
        # Spotify speelt soms een andere uitgave van hetzelfde nummer
        # ("track relinking"); dan staat de gevraagde code in linked_from.
        return uri in (item.get("uri"), (item.get("linked_from") or {}).get("uri"))
    return ((nu.get("context") or {}).get("uri")) == uri


def afspelen(keuze, klant, pc_tool, slaap=time.sleep):
    """Start de keuze via de Web API.

    Geeft ``None`` (geen Spotify-apparaat), ``("speelt", naam)`` of
    ``("onbevestigd", naam)``. Gooit SpotifyFout bij een weigering.

    Spotify neemt een afspeelopdracht voor een apparaat dat niet actief is
    soms aan (204) zonder iets te spelen. Daarom zet JARVIS het apparaat
    eerst actief en vraagt hij daarna of het echt speelt (fix 2026-10-26).
    """

    apparaat = kies_apparaat((klant.get("/me/player/devices") or {}).get("devices"))
    if apparaat is None:
        # Geen apparaat: Spotify is dicht, of de app staat open maar "slaapt"
        # (na een tijdje niets doen verdwijnt hij uit de lijst). De link
        # openen op de game-pc start de app of maakt hem wakker; daarna
        # meldt hij zich weer als apparaat.
        geopend = pc_tool("spotify_open", {"uri": keuze["uri"]})
        gewacht = 0.0
        while apparaat is None and gewacht < APPARAAT_WACHT:
            slaap(1.5)
            gewacht += 1.5
            try:
                apparaat = kies_apparaat((klant.get("/me/player/devices") or {}).get("devices"))
            except SpotifyFout:
                apparaat = None
        if apparaat is None:
            return ("geopend", geopend)
    naam = str(apparaat.get("name") or "Spotify")
    if not apparaat.get("is_active"):
        klant.put("/me/player", None, {"device_ids": [apparaat["id"]], "play": False})
        slaap(1.0)
    uri = keuze["uri"]
    body = afspeel_body(klant, keuze)
    for poging in range(2):
        klant.put("/me/player/play", {"device_id": apparaat["id"]}, body)
        for _ in range(CONTROLE_POGINGEN):
            slaap(1.0)
            try:
                if _speelt_het(klant, uri):
                    return ("speelt", naam)
            except SpotifyFout:
                pass  # even geen antwoord: gewoon opnieuw vragen
    return ("onbevestigd", naam)


def speel(keuze, pc_tool=None, klant=None, slaap=time.sleep):
    """Speelt de keuze af. Geeft het antwoord terug."""

    if pc_tool is None:
        from core.filmmodus import _pc_tool as pc_tool
    klant = klant or SpotifyKlant()
    try:
        uitkomst = None
        if klant.is_gekoppeld() and klant.mag_afspelen():
            uitkomst = afspelen(keuze, klant, pc_tool, slaap)
        if uitkomst and uitkomst[0] == "speelt":
            return f"Speelt nu: {label(keuze)}, op {uitkomst[1]}."
        if uitkomst and uitkomst[0] == "geopend":
            return _na_link(keuze, uitkomst[1], klant)
        if uitkomst:
            return (f"Ik heb {label(keuze)} naar Spotify op {uitkomst[1]} gestuurd, "
                    "maar Spotify speelt het nog niet af, sir.")
    except SpotifyFout as fout:
        if fout.status == 403:
            return "Spotify weigert het afspelen, sir. Daarvoor is Spotify Premium nodig."
        logger.info("Afspelen via Spotify lukte niet (%s); ik open de link.", fout)
    return _na_link(keuze, pc_tool("spotify_open", {"uri": keuze["uri"]}), klant)


def _na_link(keuze, r, klant):
    """Het antwoord nadat de spotify:-link op de pc geopend is."""

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
