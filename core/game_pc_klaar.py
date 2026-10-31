"""Laat het weten als de game-pc klaar is met updaten of downloaden (Fase 28, M1).

* "laat het me weten als de game-pc klaar is met updaten" kijkt meteen op
  de game-pc (:mod:`actions.achtergrond`): loopt er iets, dan kijkt een
  wachter elke minuut opnieuw en meldt JARVIS het zodra alles klaar is.
  Steam, Riot/Valorant of Windows apart noemen kan ook ("laat het weten als
  Steam klaar is met downloaden").
* "is de game-pc al klaar met updaten?" geeft de stand van nu.
* "stop met wachten op de game-pc" zet de wachter uit.

Klaar is pas klaar als twee controles achter elkaar niets meer zien lopen
(Windows Update pauzeert soms even tussen twee updates). Wil Windows daarna
herstarten, dan biedt JARVIS dat aan en herstart hij pas na uw ja.

De melding gaat als gewone systeemmelding (gesproken + banner op de iPad);
's nachts en in de stille modus blijft hij bewaard tot het mag.
"""

import logging
import re
import threading
import time as _time

logger = logging.getLogger("jarvis.game_pc_klaar")

BRONNEN = ("windows", "steam", "riot")
RUST_CONTROLES = 2          # zo vaak achter elkaar niets bezig = klaar
MAX_WACHT = 6 * 3600        # seconden; daarna stopt de wachter
MAX_OFFLINE = 3600          # zo lang onbereikbaar = stoppen
HERSTART_TTL = 300          # seconden geldig: "zal ik herstarten?"

GAME_PC_UIT = "De game-pc staat uit of is niet bereikbaar, sir."
NIET_TE_LEZEN = "Ik kan de game-pc nu niet uitlezen, sir."
NIETS_BEZIG = "Er loopt nu geen update of download op de game-pc, sir."
GESTOPT = "Goed, sir; ik let niet meer op de game-pc."
GEEN_WACHTER = "Ik wachtte niet op de game-pc, sir."
HERSTART_VRAAG = " Windows wil de game-pc nog herstarten. Zal ik dat doen?"
HERSTART_HINT = " Windows wil de game-pc nog herstarten; zeg \"herstart de game-pc\" als het mag."

_ONDERWERP = r"(game[\s-]?pc|gaming[\s-]?pc|steam|riot|valorant|league|windows[\s-]?update|windows|download\w*)"
_KLAAR = r"(klaar|af|gedaan|voltooid|voorbij|uitgedownload|geüpdatet|geupdatet)"
_MELDEN = re.compile(
    r"\b(laat|zeg|meld|vertel)\b.*\b(weten|het|melden|zeggen)\b.*\b(als|wanneer|zodra)\b.*" + _ONDERWERP + r".*\b" + _KLAAR + r"\b"
    r"|\b(laat|zeg|meld|vertel)\b.*\b(weten|het|melden|zeggen)\b.*\b(als|wanneer|zodra)\b.*\b" + _KLAAR + r"\b.*" + _ONDERWERP,
    re.IGNORECASE)
_VRAAG = re.compile(
    r"^(is|zijn)\b.*" + _ONDERWERP + r".*\b(al\s+)?(klaar|af)\b"
    r"|^(is|zijn|loopt|lopen)\b.*\b(nog\s+)?(aan\s+het\s+)?(updaten|downloaden|update|updates|download|downloads)\b.*" + _ONDERWERP
    + r"|^(is|zijn)\b.*" + _ONDERWERP + r".*\bnog\b.*\b(aan\s+het\s+)?(updaten|downloaden)\b",
    re.IGNORECASE)
_STOP = re.compile(
    r"\b(stop|hou\s+op|houd\s+op)\b.*\b(wachten|letten|kijken)\b.*\b(game[\s-]?pc|update\w*|download\w*|steam|riot)\b"
    r"|\b(je\s+)?hoeft\b.*\bniet\s+meer\b.*\b(te\s+)?(wachten|letten)\b.*\b(game[\s-]?pc|update\w*|download\w*)\b",
    re.IGNORECASE)


def _config():
    import config

    return config


# -----------------------------------------------------------------
# Herkennen
# -----------------------------------------------------------------

def welke_bronnen(command):
    """Wat de gebruiker noemt: Steam, Riot of Windows; anders alles."""

    t = command.lower()
    gekozen = []
    if "steam" in t:
        gekozen.append("steam")
    if re.search(r"riot|valorant|league", t):
        gekozen.append("riot")
    if "windows" in t:
        gekozen.append("windows")
    if not gekozen and re.search(r"download", t) and not re.search(r"updat", t):
        gekozen = ["steam", "riot"]
    return tuple(gekozen) or BRONNEN


def herken(command):
    """``("melden" | "vraag" | "stop", bronnen)`` of None."""

    tekst = " ".join(str(command or "").strip().rstrip("?.!").split())
    if not tekst:
        return None
    if _STOP.search(tekst):
        return "stop", BRONNEN
    if _MELDEN.search(tekst):
        return "melden", welke_bronnen(tekst)
    if _VRAAG.search(tekst):
        return "vraag", welke_bronnen(tekst)
    return None


# -----------------------------------------------------------------
# De game-pc uitlezen
# -----------------------------------------------------------------

def _std_pc(tool, args):
    from remote import tools as remote_tools

    return remote_tools.execute_remote_tool(tool, args, question="game-pc klaar")


def _std_online():
    from core.discord_dms import _std_online as online

    return online()


def lees_status(pc_fn=None):
    """De status per bron (zie :mod:`actions.achtergrond`), of None."""

    from core.discord_dms import _gegeven, _gelukt

    r = (pc_fn or _std_pc)("game_pc_achtergrond_status", {})
    if not _gelukt(r):
        return None
    status = {bron: _gegeven(r, bron) for bron in BRONNEN}
    if not any(isinstance(s, dict) for s in status.values()):
        return None
    return {bron: (s if isinstance(s, dict) else {"bezig": None}) for bron, s in status.items()}


def _procent(p):
    return f" ({p} procent)" if isinstance(p, int) and 0 <= p <= 100 else ""


def bezig(status, bronnen=BRONNEN):
    """Wat er nu loopt, als korte zinsdelen ("Steam downloadt Valorant (40 procent)")."""

    uit = []
    if "windows" in bronnen and status["windows"].get("bezig") is True:
        uit.append("Windows installeert updates")
    if "steam" in bronnen and status["steam"].get("bezig") is True:
        games = [g for g in status["steam"].get("games") or [] if isinstance(g, dict) and g.get("naam")]
        if not games:
            uit.append("Steam is aan het downloaden")
        for g in games[:3]:
            uit.append(f"Steam downloadt {g['naam']}{_procent(g.get('procent'))}")
    if "riot" in bronnen and status["riot"].get("bezig") is True:
        uit.append("Riot is aan het updaten")
    return uit


def _herstart(status, bronnen):
    return "windows" in bronnen and bool(status["windows"].get("herstart"))


def _riot_onbekend(status, bronnen):
    return bronnen == ("riot",) and status["riot"].get("bezig") is None and status["riot"].get("draait")


def _opsomming(delen):
    if len(delen) <= 1:
        return "".join(delen)
    return ", ".join(delen[:-1]) + " en " + delen[-1]


def _std_stil():
    from core import proactive

    return proactive.is_nachtmodus() or proactive.is_quiet()


def bied_herstart_aan(stil_fn=None):
    """Vraagt om de herstart (na ja via ``power_confirm``), of geeft alleen een hint als het stil is."""

    try:
        if (stil_fn or _std_stil)():
            return HERSTART_HINT
    except Exception:
        return HERSTART_HINT
    from core import pc_target
    from core.confirmation import get_pending, set_pending

    if get_pending():
        return HERSTART_HINT  # een andere vraag loopt nog: die niet overschrijven
    set_pending("power_confirm", {"action": "restart", "target": pc_target.GAME_PC,
                                  "question": "herstart de game-pc"}, ttl=HERSTART_TTL)
    return HERSTART_VRAAG


# -----------------------------------------------------------------
# De wachter
# -----------------------------------------------------------------

_meld = {"fn": None}
_lock = threading.Lock()
_actief = {"wachter": None}


def zet_meld(meld_fn):
    """Bij het opstarten: hoe de wachter iets meldt (``engine.meld``)."""

    _meld["fn"] = meld_fn


class Wachter:
    """Kijkt elke minuut of wat liep klaar is, en meldt dat één keer."""

    def __init__(self, bronnen=BRONNEN, pc_fn=None, meld_fn=None, klok=None, interval=None,
                 stil_fn=None):
        self.bronnen = tuple(bronnen)
        self.pc_fn = pc_fn
        self.meld_fn = meld_fn
        self.klok = klok or _time.monotonic
        self.interval = interval if interval is not None else _config().GAMEPC_KLAAR_CHECK_SECONDEN
        self.stil_fn = stil_fn
        self.start_tijd = self.klok()
        self.laatst_gezien = self.start_tijd
        self.rust = 0
        self.gezien = []          # wat er liep: "Windows Update", "Valorant", "Riot"
        self.klaar = False
        self._stop = threading.Event()
        self._thread = None

    def _onthoud(self, status):
        namen = []
        if "windows" in self.bronnen and status["windows"].get("bezig") is True:
            namen.append("Windows Update")
        if "steam" in self.bronnen and status["steam"].get("bezig") is True:
            namen += [g["naam"] for g in status["steam"].get("games") or []
                      if isinstance(g, dict) and g.get("naam")] or ["de Steam-download"]
        if "riot" in self.bronnen and status["riot"].get("bezig") is True:
            namen.append("de Riot-update")
        for naam in namen:
            if naam not in self.gezien:
                self.gezien.append(naam)

    def _meld(self, tekst):
        self.klaar = True
        fn = self.meld_fn or _meld["fn"]
        if fn is None:
            logger.info("Game-pc klaar, maar er is niemand om het te melden: %s", tekst)
            return tekst
        try:
            fn(tekst, bron="game-pc")
        except Exception:
            logger.debug("Kon de game-pc-melding niet versturen.", exc_info=True)
        return tekst

    def stap(self):
        """Eén controle; geeft de melding terug als die nu gaat, anders None."""

        if self.klaar:
            return None
        nu = self.klok()
        status = lees_status(self.pc_fn)
        if status is None:
            if nu - self.laatst_gezien >= MAX_OFFLINE:
                return self._meld("Sir, de game-pc is al een uur niet bereikbaar; ik let er niet meer op.")
            return None
        self.laatst_gezien = nu
        self._onthoud(status)
        if bezig(status, self.bronnen):
            self.rust = 0
            if nu - self.start_tijd >= MAX_WACHT:
                return self._meld("Sir, de game-pc is na zes uur nog steeds bezig; ik let er niet meer op.")
            return None
        self.rust += 1
        if self.rust < RUST_CONTROLES:
            return None
        wat = _opsomming(self.gezien) or "het updaten"
        tekst = f"Sir, de game-pc is klaar: {wat} {'is' if len(self.gezien) <= 1 else 'zijn'} klaar."
        if "Windows Update" in self.gezien and _herstart(status, self.bronnen):
            tekst += bied_herstart_aan(self.stil_fn)
        return self._meld(tekst)

    def _lus(self):
        while not self._stop.wait(self.interval):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout bij het letten op de game-pc.")
            if self.klaar:
                break
        with _lock:
            if _actief["wachter"] is self:
                _actief["wachter"] = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-game-pc-klaar", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()


def actieve_wachter():
    with _lock:
        w = _actief["wachter"]
    return w if w is not None and not w.klaar and not w._stop.is_set() else None


def _start_wachter(bronnen, status, maak_wachter=None):
    with _lock:
        oud = _actief["wachter"]
        if oud is not None and not oud.klaar and not oud._stop.is_set():
            bronnen = tuple(b for b in BRONNEN if b in bronnen or b in oud.bronnen)
            oud.stop()
        wachter = (maak_wachter or Wachter)(bronnen)
        wachter._onthoud(status)
        _actief["wachter"] = wachter
    wachter.start()
    return wachter


# -----------------------------------------------------------------
# Antwoorden
# -----------------------------------------------------------------

def melden(bronnen, pc_fn=None, online_fn=None, maak_wachter=None, stil_fn=None):
    if (online_fn or _std_online)() is False:
        return GAME_PC_UIT
    status = lees_status(pc_fn)
    if status is None:
        return NIET_TE_LEZEN
    nu = bezig(status, bronnen)
    if not nu:
        if _riot_onbekend(status, bronnen):
            return "Of Riot aan het updaten is, kan ik nu niet zien, sir."
        if _herstart(status, bronnen):
            return "Windows Update is al klaar, sir." + bied_herstart_aan(stil_fn)
        return NIETS_BEZIG
    _start_wachter(bronnen, status, maak_wachter)
    return f"Komt goed, sir. {_opsomming(nu)}; ik laat het weten zodra het klaar is."


def vraag(bronnen, pc_fn=None, online_fn=None, stil_fn=None):
    if (online_fn or _std_online)() is False:
        return GAME_PC_UIT
    status = lees_status(pc_fn)
    if status is None:
        return NIET_TE_LEZEN
    nu = bezig(status, bronnen)
    if nu:
        return f"Nee, sir: {_opsomming(nu)}."
    if _riot_onbekend(status, bronnen):
        return "Of Riot aan het updaten is, kan ik nu niet zien, sir."
    if _herstart(status, bronnen):
        return "Ja, sir, de updates zijn klaar." + bied_herstart_aan(stil_fn)
    return "Ja, sir; er loopt geen update of download meer op de game-pc."


def stop():
    w = actieve_wachter()
    if w is None:
        return GEEN_WACHTER
    w.stop()
    with _lock:
        if _actief["wachter"] is w:
            _actief["wachter"] = None
    return GESTOPT


def probeer_commando(command, pc_fn=None, online_fn=None, maak_wachter=None, stil_fn=None):
    """``None`` als het hier niet over gaat, anders het antwoord."""

    herkend = herken(command)
    if herkend is None:
        return None
    soort, bronnen = herkend
    if soort == "stop":
        return stop()
    if soort == "melden":
        return melden(bronnen, pc_fn, online_fn, maak_wachter, stil_fn)
    return vraag(bronnen, pc_fn, online_fn, stil_fn)
