"""Focusmodus (Fase 26, M2): even ongestoord werken.

"JARVIS, focusmodus aan" of "focusmodus voor 2 uur":

1. Discord op de game-pc wordt gedempt (alleen als hij nog niet gedempt was);
2. nieuwe Discord-DM's worden niet voorgelezen (ze blijven "nieuw");
3. met een duur stopt de focus vanzelf, en JARVIS zegt dat;
4. bij "focusmodus uit" zet JARVIS Discord terug zoals het was en noemt hij
   de DM's die binnenkwamen.

Besluiten 2026-10-28/30: alleen Discord dempen + DM's stil, verder niets
(geen games blokkeren, geen pomodoro, geen muziek; JARVIS' eigen meldingen
gaan door). Optionele duur. Op het dashboard een knop onder de nachtmodus.

De toestand staat in ``memory/focus_toestand.json``, zodat een herstart van
JARVIS de focus (en wat er terug moet) niet vergeet.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("jarvis.focus")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOESTAND_FILE = os.path.join(PROJECT, "memory", "focus_toestand.json")

MAX_MINUTEN = 12 * 60  # langer is vast een verspreking

MELDING_KLAAR = "Uw focustijd is voorbij, sir."


# -----------------------------------------------------------------
# Toestand
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
        logger.warning("Kon de focustoestand niet opslaan", exc_info=True)


def is_aan(pad=None):
    return lees_toestand(pad) is not None


def _tot(toestand):
    try:
        return datetime.fromisoformat(toestand["tot"]) if toestand and toestand.get("tot") else None
    except (TypeError, ValueError):
        return None


def status(nu=None, pad=None):
    """Voor het dashboard: ``{"aan", "tot" ("HH:MM"), "resterend" (s)}``."""

    nu = nu or datetime.now()
    toestand = lees_toestand(pad)
    if not toestand:
        return {"aan": False, "tot": None, "resterend": None}
    tot = _tot(toestand)
    return {
        "aan": True,
        "tot": tot.strftime("%H:%M") if tot else None,
        "resterend": max(0, int((tot - nu).total_seconds())) if tot else None,
    }


# -----------------------------------------------------------------
# Discord op de game-pc
# -----------------------------------------------------------------

def _pc_tool(tool_name, arguments):
    """Een pc-tool door de bewaakte poort, zoals de film-modus het doet."""

    from core.ai import _dispatch_tool
    from core.result_validation import to_tool_result
    from core.tool_registry import run_tool_guarded

    uit = run_tool_guarded(tool_name, arguments, source="focusmodus", question="focusmodus",
                           dispatch=_dispatch_tool, approved=True)
    return to_tool_result(uit)


def _nieuwe_dms():
    """De ongelezen Discord-DM's (namen), of None als dat niet te zien is."""

    try:
        from core import discord_dms

        if discord_dms._std_online() is not True:
            return None
        dms = discord_dms.DiscordKlant().dms()
        if dms is None:
            return None
        return [d.get("van") or "iemand" for d in discord_dms.ongelezen(dms)]
    except Exception:
        logger.debug("DM's lezen na de focus mislukt", exc_info=True)
        return None


def _dm_zin(namen):
    if not namen:
        return "Er kwamen geen nieuwe DM's binnen."
    uniek = []
    for naam in namen:
        if naam not in uniek:
            uniek.append(naam)
    wie = ", ".join(uniek[:-1]) + " en " + uniek[-1] if len(uniek) > 1 else uniek[0]
    meervoud = "" if len(namen) == 1 else "'s"
    return f"U heeft {len(namen)} nieuwe DM{meervoud}, van {wie}."


def _duur_zin(minuten):
    if minuten % 60 == 0:
        uren = minuten // 60
        return f"{uren} uur"
    if minuten > 60:
        return f"{minuten // 60} uur en {minuten % 60} minuten"
    return f"{minuten} minuten"


class FocusModus:
    def __init__(self, pc_tool=None, toestand_pad=None, klok=None, dms_fn=None):
        self.pc_tool = pc_tool or _pc_tool
        self.toestand_pad = toestand_pad
        self.klok = klok or datetime.now
        self.dms_fn = dms_fn or _nieuwe_dms
        self._lock = threading.Lock()

    def aan(self, minuten=None):
        with self._lock:
            nu = self.klok()
            tot = (nu + timedelta(minutes=minuten)).isoformat(timespec="seconds") if minuten else None
            toestand = lees_toestand(self.toestand_pad)
            if toestand:
                # Al aan: alleen de duur aanpassen.
                toestand["tot"] = tot
                schrijf_toestand(toestand, self.toestand_pad)
                if minuten:
                    return f"De focus loopt nu nog {_duur_zin(minuten)}, tot {(nu + timedelta(minutes=minuten)):%H:%M}, sir."
                return "De focusmodus staat al aan; hij blijft aan tot u hem uitzet, sir."

            zinnen = []
            gedempt = False
            info = self.pc_tool("audio_get_session_volume", {"app_name": "Discord"})
            from core.filmmodus import _gegeven, _onbereikbaar

            if _onbereikbaar(info):
                zinnen.append("De game-pc is niet bereikbaar, dus Discord kon ik niet dempen.")
            elif getattr(info, "ok", False) and _gegeven(info, "muted") is False:
                r = self.pc_tool("audio_set_session_mute", {"app_name": "Discord", "muted": True})
                if getattr(r, "ok", False):
                    gedempt = True
                    zinnen.append("Discord is gedempt")
            elif getattr(info, "ok", False):
                zinnen.append("Discord stond al stil")

            schrijf_toestand({
                "gestart": nu.isoformat(timespec="seconds"),
                "tot": tot,
                "discord_gedempt": gedempt,
            }, self.toestand_pad)

            kop = f"Focusmodus aan voor {_duur_zin(minuten)}, tot {(nu + timedelta(minutes=minuten)):%H:%M}" \
                if minuten else "Focusmodus aan"
            delen = [kop + ", sir."]
            if zinnen and zinnen[0].startswith("De game-pc"):
                delen.append(zinnen[0])
            elif zinnen:
                delen.append(zinnen[0] + " en nieuwe DM's lees ik niet voor.")
            else:
                delen.append("Nieuwe DM's lees ik niet voor.")
            return " ".join(delen)

    def uit(self, vanzelf=False):
        with self._lock:
            toestand = lees_toestand(self.toestand_pad)
            if not toestand:
                return "De focusmodus staat niet aan, sir."
            delen = [MELDING_KLAAR if vanzelf else "Focusmodus uit, sir."]
            if toestand.get("discord_gedempt"):
                r = self.pc_tool("audio_set_session_mute", {"app_name": "Discord", "muted": False})
                delen.append("Discord staat weer aan." if getattr(r, "ok", False)
                             else "Discord kon ik niet terugzetten; zet hem zelf weer aan.")
            schrijf_toestand(None, self.toestand_pad)
            namen = self.dms_fn()
            if namen is not None:
                delen.append(_dm_zin(namen))
            return " ".join(delen)

    def verlopen(self):
        """True als de focus een eindtijd had die voorbij is."""

        tot = _tot(lees_toestand(self.toestand_pad))
        return tot is not None and self.klok() >= tot


_gedeeld = {"focus": None}
_gedeeld_lock = threading.Lock()


def get_focusmodus():
    with _gedeeld_lock:
        if _gedeeld["focus"] is None:
            _gedeeld["focus"] = FocusModus()
        return _gedeeld["focus"]


# -----------------------------------------------------------------
# Vanzelf stoppen
# -----------------------------------------------------------------

class FocusPlanner:
    """Stopt een focus met een eindtijd en meldt dat (elke 30 seconden)."""

    def __init__(self, meld_fn=None, focus_fn=None, interval=30):
        self.meld_fn = meld_fn
        self.focus_fn = focus_fn or get_focusmodus
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def stap(self):
        focus = self.focus_fn()
        if not focus.verlopen():
            return None
        tekst = focus.uit(vanzelf=True)
        if self.meld_fn is not None:
            try:
                self.meld_fn(tekst, bron="focus")
            except Exception:
                logger.debug("Kon het einde van de focus niet melden.", exc_info=True)
        return tekst

    def _lus(self):
        while not self._stop.wait(self.interval):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout in de focusplanner.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-focus", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()


# -----------------------------------------------------------------
# Stemopdrachten
# -----------------------------------------------------------------

_FOCUS = r"(?:focus\s*modus|focusmodus|focus)"
_AAN = re.compile(
    rf"^(?:jarvis[, ]+)?(?:zet\s+(?:de\s+)?{_FOCUS}\s+aan|{_FOCUS}\s+aan|start\s+(?:de\s+)?{_FOCUS}"
    rf"|ik\s+(?:wil|ga)\s+(?:me\s+)?(?:even\s+)?(?:focussen|concentreren)|{_FOCUS})"
    r"(?P<rest>(?:\s+(?:voor|gedurende|van)?\s*.+)?)$"
)
_UIT = re.compile(
    rf"^(?:jarvis[, ]+)?(?:zet\s+(?:de\s+)?{_FOCUS}\s+uit|{_FOCUS}\s+(?:uit|klaar|stoppen|voorbij)"
    rf"|stop\s+(?:de\s+)?{_FOCUS}|einde\s+(?:van\s+de\s+)?{_FOCUS}|ik\s+ben\s+klaar\s+met\s+(?:de\s+)?{_FOCUS})$"
)
_STATUS = re.compile(
    rf"^(?:staat\s+(?:de\s+)?{_FOCUS}\s+aan|hoe\s+lang\s+(?:nog\s+)?(?:duurt\s+)?(?:de\s+)?{_FOCUS}(?:\s+nog)?"
    rf"|hoe\s+lang\s+nog\s+focus(?:sen)?)$"
)
_GETAL = {"een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "tien": 10,
          "twintig": 20, "dertig": 30, "veertig": 40, "vijftig": 50, "vijfenveertig": 45, "vijfentwintig": 25}
_DUUR = re.compile(
    r"(?P<getal>\d+(?:[.,]\d+)?|anderhalf|half|een|één|twee|drie|vier|vijf|zes|tien|twintig|dertig|veertig|"
    r"vijftig|vijfenveertig|vijfentwintig)?\s*(?P<eenheid>uur|uren|minuten|minuutjes|min|kwartier)\b"
)


def lees_duur(tekst):
    """Minuten uit "2 uur", "anderhalf uur", "45 minuten", "een kwartier"; of None."""

    m = _DUUR.search(tekst or "")
    if not m:
        return None
    getal, eenheid = m.group("getal"), m.group("eenheid")
    if getal is None:
        waarde = 1.0
    elif getal == "anderhalf":
        waarde = 1.5
    elif getal == "half":
        waarde = 0.5
    elif getal in _GETAL:
        waarde = float(_GETAL[getal])
    else:
        waarde = float(getal.replace(",", "."))
    if eenheid in ("uur", "uren"):
        minuten = waarde * 60
    elif eenheid == "kwartier":
        minuten = waarde * 15
    else:
        minuten = waarde
    minuten = int(round(minuten))
    return minuten if 0 < minuten <= MAX_MINUTEN else None


def herken(tekst):
    """``("aan", minuten|None)``, ``("uit", None)``, ``("status", None)`` of None."""

    t = " ".join(str(tekst or "").lower().strip().rstrip("?!.").split())
    if _UIT.match(t):
        return "uit", None
    if _STATUS.match(t):
        return "status", None
    m = _AAN.match(t)
    if not m:
        return None
    rest = m.group("rest").strip()
    if rest and not _DUUR.search(rest):
        return None  # "focus op het werk" e.d. is geen opdracht
    return "aan", lees_duur(rest)


def voer_uit(tekst, focus=None, nu=None):
    """Voor de brain-router: het antwoord, of None."""

    herkend = herken(tekst)
    if herkend is None:
        return None
    focus = focus or get_focusmodus()
    soort, minuten = herkend
    if soort == "uit":
        return focus.uit()
    if soort == "status":
        s = status(nu=nu, pad=focus.toestand_pad)
        if not s["aan"]:
            return "De focusmodus staat uit, sir."
        if s["tot"]:
            return f"De focus loopt nog tot {s['tot']}, sir."
        return "De focusmodus staat aan, zonder eindtijd."
    return focus.aan(minuten)
