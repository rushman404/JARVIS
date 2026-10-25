"""Film-modus 2.0 (Fase 21, M1).

"JARVIS, filmavond" of "zet Disney+ op de tv":

1. de tv gaat aan (Wake-on-LAN-knop in Home Assistant, anders
   ``media_player.turn_on``) en JARVIS wacht tot hij echt aan is;
2. de gevraagde app opent via de bronkeuze van de tv (LG webOS);
3. de pc wordt stil: Discord gedempt en Spotify gepauzeerd (alleen als die
   speelt: nooit per ongeluk muziek starten);
4. JARVIS onthoudt hoe het was, zodat "film klaar" alles terugzet
   (Discord weer aan, tv terug naar de vorige bron of uit). Spotify gaat
   bewust niet vanzelf verder.

Licht en gordijnen blijven zoals ze zijn (besluit 2026-10-25).

Elke stap krijgt een korte, film-achtige zin. Met ``vertel`` (de
``on_tekst`` van ``process_command``) klinkt die zin meteen, terwijl de
volgende stap al loopt; het volledige antwoord is alle zinnen samen.
"""

import json
import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOESTAND_FILE = os.path.join(PROJECT, "memory", "film_toestand.json")

# dienst -> (zoekwoorden in de bronnenlijst van de tv, uitspraak)
DIENSTEN = {
    "netflix": (("netflix",), "Netflix"),
    "disney": (("disney",), "Disney+"),
    "prime": (("prime video", "amazon prime", "prime"), "Prime Video"),
    "youtube": (("youtube",), "YouTube"),
}
STANDAARD_DIENST = "netflix"

# Hoe lang JARVIS wacht tot de tv aan is, en hoe vaak hij de app probeert
# (webOS accepteert een bronkeuze pas een paar seconden na het opstarten).
TV_AAN_SECONDEN = 30
APP_POGINGEN = 4
APP_PAUZE = 2.0

AAN_STATEN = ("on", "playing", "paused", "idle", "buffering")

# Herkent de dienst in een zin ("disney plus", "prime video", "you tube").
_DIENST_PATROON = re.compile(
    r"\b(netflix|disney(?:\s*(?:plus|\+))?|(?:amazon\s+)?prime(?:\s+video)?|you\s*tube)\b"
)

_TV = r"(?:\s+op\s+(?:de\s+)?(?:tv|televisie))"
_DIENST = r"(netflix|disney(?:\s*(?:plus|\+))?|(?:amazon\s+)?prime(?:\s+video)?|you\s*tube)"

# Startzinnen met een dienst. Zonder "op de tv" alleen met een kijkwoord,
# zodat "open netflix" (op de pc) blijft werken zoals het was.
START_PATRONEN = (
    re.compile(rf"^(?:zet|doe)\s+(?:de\s+tv\s+op\s+)?{_DIENST}(?:\s+op|{_TV}|\s+aan)?$"),
    re.compile(rf"^(?:open|start)\s+{_DIENST}{_TV}$"),
    re.compile(rf"^{_DIENST}{_TV}$"),
    re.compile(rf"^ik\s+(?:ga|wil)\s+(?:een\s+film\s+|een\s+serie\s+)?{_DIENST}\s+kijken$"),
    re.compile(rf"^ik\s+(?:ga|wil)\s+(?:een\s+)?(?:film|serie)\s+kijken\s+op\s+{_DIENST}$"),
    re.compile(rf"^(?:start\s+)?(?:de\s+)?(?:filmavond|film\s*modus)\s+(?:met|op)\s+{_DIENST}$"),
)

STOP_PATRONEN = (
    re.compile(r"^(?:de\s+)?film\s+(?:is\s+)?(?:klaar|afgelopen|voorbij|uit)$"),
    re.compile(r"^(?:einde|stop|stop\s+de)\s+(?:film|filmavond|film\s*modus)$"),
    re.compile(r"^(?:de\s+)?(?:filmavond|film\s*modus)\s+(?:is\s+)?(?:klaar|voorbij|uit|stoppen)$"),
    re.compile(r"^zet\s+(?:de\s+)?(?:filmavond|film\s*modus)\s+uit$"),
)


def _schoon(tekst):
    t = str(tekst or "").lower().strip()
    t = re.sub(r"^\s*(hey\s+|ok\s+|okay\s+)?jarvis\b[,\s]*", "", t)
    t = re.sub(r"[^\w\s+]", " ", t)
    return " ".join(t.split())


def dienst_uit(tekst):
    """De dienst-sleutel uit een zin ("disney"), of None."""

    m = _DIENST_PATROON.search(_schoon(tekst))
    if not m:
        return None
    woord = m.group(1).replace(" ", "")
    if woord.startswith("disney"):
        return "disney"
    if "prime" in woord:
        return "prime"
    if woord == "youtube":
        return "youtube"
    return "netflix"


def herken(tekst):
    """``("start", dienst)``, ``("stop", None)`` of None."""

    t = _schoon(tekst)
    if not t:
        return None
    if any(p.match(t) for p in STOP_PATRONEN):
        return "stop", None
    if any(p.match(t) for p in START_PATRONEN):
        return "start", dienst_uit(t)
    return None


# -----------------------------------------------------------------
# Home Assistant en de pc (los te vervangen in tests)
# -----------------------------------------------------------------

class HaKlant:
    """Dunne laag over de HA REST API."""

    def staten(self):
        from core.home_assistant import _ha_get

        ok, data = _ha_get("/api/states")
        return data if ok and isinstance(data, list) else []

    def staat(self, entity_id):
        from core.home_assistant import _ha_get

        ok, data = _ha_get(f"/api/states/{entity_id}")
        return data if ok and isinstance(data, dict) else None

    def dienst(self, domein, dienst, data):
        from core.home_assistant import _ha_post

        ok, _ = _ha_post(f"/api/services/{domein}/{dienst}", data)
        _audit(f"{domein}.{dienst}", data, ok)
        return bool(ok)


def _audit(tool, argumenten, ok):
    try:
        from core.audit import log_audit

        log_audit(gehoord="film-modus", handler="filmmodus", tool=tool,
                  argumenten=argumenten, risico="low",
                  resultaat="gelukt" if ok else "mislukt", goedgekeurd=True)
    except Exception:
        logger.debug("Audit film-modus mislukt", exc_info=True)


def _pc_tool(tool_name, arguments):
    """Een pc-tool door de bewaakte poort (gaat naar de game-pc als die het
    doel is, net als elke andere pc-opdracht)."""

    from core.ai import _dispatch_tool
    from core.result_validation import to_tool_result
    from core.tool_registry import run_tool_guarded

    uit = run_tool_guarded(tool_name, arguments, source="filmmodus", question="film-modus",
                           dispatch=_dispatch_tool, approved=True)
    return to_tool_result(uit)


def _gegeven(resultaat, sleutel):
    """Zoekt ``sleutel`` in het resultaat, ook als het van de game-pc komt
    (dan zit het in ``data["resultaat"]``)."""

    data = getattr(resultaat, "data", None) or {}
    if sleutel in data:
        return data[sleutel]
    binnen = data.get("resultaat")
    for laag in (binnen, (binnen or {}).get("data") if isinstance(binnen, dict) else None):
        if isinstance(laag, dict) and sleutel in laag:
            return laag[sleutel]
    return None


def _onbereikbaar(resultaat):
    soort = getattr(resultaat, "error_kind", "") or ""
    return soort in ("remote_config", "remote_onzeker") or (
        soort == "remote_mislukt"
        and str(_gegeven(resultaat, "fout_code") or "") in ("niet_bereikbaar", "tls_fout", "config_fout")
    )


# -----------------------------------------------------------------
# Toestand (wat er vóór de film was)
# -----------------------------------------------------------------

def lees_toestand(pad=None):
    try:
        with open(pad or TOESTAND_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def schrijf_toestand(toestand, pad=None):
    pad = pad or TOESTAND_FILE
    try:
        if toestand is None:
            if os.path.exists(pad):
                os.remove(pad)
            return
        os.makedirs(os.path.dirname(pad), exist_ok=True)
        tmp = pad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(toestand, f, ensure_ascii=False, indent=2)
        os.replace(tmp, pad)
    except OSError:
        logger.warning("Kon de film-toestand niet opslaan", exc_info=True)


# -----------------------------------------------------------------
# De film-modus
# -----------------------------------------------------------------

class FilmModus:
    def __init__(self, ha=None, pc_tool=None, toestand_pad=None, slaap=time.sleep,
                 tv_entity=None, tv_knop=None):
        self.ha = ha or HaKlant()
        self.pc_tool = pc_tool or _pc_tool
        self.toestand_pad = toestand_pad
        self.slaap = slaap
        self._tv_entity = tv_entity
        self._tv_knop = tv_knop
        self._lock = threading.Lock()

    # ----- de tv vinden -----

    def _zoek_tv(self):
        """``(media_player, aan-knop)``; uit config of zelf gezocht."""

        from config import FILM_TV_AAN_KNOP, FILM_TV_ENTITY

        tv = self._tv_entity or FILM_TV_ENTITY
        knop = self._tv_knop or FILM_TV_AAN_KNOP
        if tv and knop:
            return tv, knop
        staten = self.ha.staten()

        def naam(s):
            return str((s.get("attributes") or {}).get("friendly_name") or "").lower()

        if not tv:
            spelers = [s for s in staten if str(s.get("entity_id", "")).startswith("media_player.")]
            # Voorkeur: een webOS-tv, dan iets met "tv" in de naam.
            for s in sorted(spelers, key=lambda s: (
                    "webos" not in (s["entity_id"] + naam(s)),
                    "tv" not in (s["entity_id"] + naam(s)))):
                if "webos" in (s["entity_id"] + naam(s)) or "tv" in (s["entity_id"] + naam(s)):
                    tv = s["entity_id"]
                    break
        if not knop:
            for s in staten:
                eid = str(s.get("entity_id", ""))
                if eid.startswith("button.") and "wake_on_lan" in eid and naam(s) in ("tv", "televisie"):
                    knop = eid
                    break
        return tv, knop

    # ----- start -----

    def start(self, dienst=None, vertel=None):
        with self._lock:
            return self._start(dienst or STANDAARD_DIENST, vertel)

    def _start(self, dienst, vertel):
        zinnen = []

        def zeg(zin):
            zinnen.append(zin)
            if vertel is not None:
                try:
                    vertel(zin + " ")
                except Exception:
                    logger.debug("Vertellen mislukt", exc_info=True)

        woorden, uitspraak = DIENSTEN.get(dienst, DIENSTEN[STANDAARD_DIENST])
        tv, knop = self._zoek_tv()
        if not tv:
            return "Ik vind de tv niet in Home Assistant, sir."

        vorige = lees_toestand(self.toestand_pad)
        staat = self.ha.staat(tv)
        was_aan = bool(staat) and staat.get("state") in AAN_STATEN
        bron = ((staat or {}).get("attributes") or {}).get("source")
        if vorige:
            # Al in film-modus (bijv. een andere app): de oorspronkelijke
            # toestand van vóór de eerste film blijft de terugweg.
            toestand = vorige
        else:
            toestand = {"tv": tv, "tv_was_aan": was_aan, "bron": bron if was_aan else None,
                        "discord_gedempt": False, "gestart": time.strftime("%Y-%m-%dT%H:%M:%S")}

        # 1. tv aan
        if not was_aan:
            zeg("Tv wordt geactiveerd.")
            if not self._tv_aan(tv, knop):
                zeg("De tv reageert niet, sir.")
                schrijf_toestand(toestand, self.toestand_pad)
                return " ".join(zinnen)

        # 2. de app
        if self._kies_app(tv, woorden):
            zeg(f"{uitspraak} geladen.")
        else:
            zeg(f"{uitspraak} kon ik niet openen op de tv.")

        # 3. de pc stil
        pc_zinnen, gedempt = self._pc_stil()
        for zin in pc_zinnen:
            zeg(zin)
        toestand["discord_gedempt"] = bool(toestand.get("discord_gedempt") or gedempt)
        schrijf_toestand(toestand, self.toestand_pad)

        zeg("Geniet van de film, sir.")
        return " ".join(zinnen)

    def _tv_aan(self, tv, knop):
        if knop:
            self.ha.dienst("button", "press", {"entity_id": knop})
        else:
            self.ha.dienst("media_player", "turn_on", {"entity_id": tv})
        einde = time.monotonic() + TV_AAN_SECONDEN
        while True:
            staat = self.ha.staat(tv)
            if staat and staat.get("state") in AAN_STATEN:
                return True
            if time.monotonic() >= einde:
                return False
            self.slaap(1.0)

    def _bron_naam(self, tv, woorden):
        staat = self.ha.staat(tv) or {}
        bronnen = (staat.get("attributes") or {}).get("source_list") or []
        for woord in woorden:
            for b in bronnen:
                if woord in str(b).lower():
                    return b
        return None

    def _kies_app(self, tv, woorden):
        for poging in range(APP_POGINGEN):
            bron = self._bron_naam(tv, woorden)
            if bron and self.ha.dienst("media_player", "select_source",
                                       {"entity_id": tv, "source": bron}):
                return True
            if poging < APP_POGINGEN - 1:
                self.slaap(APP_PAUZE)
        return False

    def _pc_stil(self):
        """Discord dempen en Spotify pauzeren. ``(zinnen, discord_gedempt)``."""

        zinnen = []
        gedempt = False

        info = self.pc_tool("audio_get_session_volume", {"app_name": "Discord"})
        if _onbereikbaar(info):
            return ["De game-pc is niet bereikbaar; die sla ik over."], False
        if getattr(info, "ok", False) and _gegeven(info, "muted") is False:
            r = self.pc_tool("audio_set_session_mute", {"app_name": "Discord", "muted": True})
            if getattr(r, "ok", False):
                gedempt = True
                zinnen.append("Discord gedempt.")

        r = self.pc_tool("media_pause_app", {"app_name": "Spotify"})
        if getattr(r, "ok", False) and _gegeven(r, "gepauzeerd"):
            zinnen.append("Muziek gepauzeerd.")
        return zinnen, gedempt

    # ----- stop -----

    def stop(self, vertel=None):
        with self._lock:
            return self._stop(vertel)

    def _stop(self, vertel):
        toestand = lees_toestand(self.toestand_pad)
        if not toestand:
            return "De film-modus staat niet aan, sir."
        zinnen = []

        def zeg(zin):
            zinnen.append(zin)
            if vertel is not None:
                try:
                    vertel(zin + " ")
                except Exception:
                    logger.debug("Vertellen mislukt", exc_info=True)

        zeg("Film-modus wordt afgesloten.")
        if toestand.get("discord_gedempt"):
            r = self.pc_tool("audio_set_session_mute", {"app_name": "Discord", "muted": False})
            zeg("Discord staat weer aan." if getattr(r, "ok", False) else "Discord kon ik niet terugzetten.")

        tv = toestand.get("tv")
        if tv:
            if not toestand.get("tv_was_aan"):
                if self.ha.dienst("media_player", "turn_off", {"entity_id": tv}):
                    zeg("Tv uit.")
            elif toestand.get("bron"):
                nu = ((self.ha.staat(tv) or {}).get("attributes") or {}).get("source")
                if nu != toestand["bron"] and self.ha.dienst(
                        "media_player", "select_source", {"entity_id": tv, "source": toestand["bron"]}):
                    zeg(f"Tv terug naar {toestand['bron']}.")

        schrijf_toestand(None, self.toestand_pad)
        zeg("Alles staat weer zoals het was, sir.")
        return " ".join(zinnen)


_film = None


def get_filmmodus():
    global _film
    if _film is None:
        _film = FilmModus()
    return _film


def voer_uit(tekst, vertel=None):
    """Voor de brain-router: het antwoord, of None als de zin niet over de
    film-modus gaat."""

    soort = herken(tekst)
    if soort is None:
        return None
    if soort[0] == "stop":
        return get_filmmodus().stop(vertel=vertel)
    return get_filmmodus().start(soort[1], vertel=vertel)
