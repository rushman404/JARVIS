"""In gesprek: JARVIS luistert na een antwoord niet door (Fase 31, M2 en M3).

* **Knop op de iPad** (:func:`zet`): zolang "In gesprek" aan staat, eindigt
  elke sessie na het antwoord; voor de volgende opdracht is "JARVIS" weer
  nodig. Blijft aan tot u hem uitzet.
* **Discord-call** (M3): gebruikt Discord nu de microfoon, op de game-pc
  (laatst gezien, via de Discord-controle van elke minuut) of op deze pc,
  dan geldt "In gesprek" vanzelf.
"""

import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger("jarvis.gespreksmodus")

TOESTAND_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "memory", "gespreksmodus.json")

_lock = threading.Lock()


def _lees(pad=None):
    try:
        with open(pad or TOESTAND_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def knop_aan(pad=None):
    return bool(_lees(pad).get("aan"))


def zet(aan, pad=None, nu=None):
    """Zet de knop aan of uit; geeft de stand terug."""

    pad = pad or TOESTAND_FILE
    with _lock:
        os.makedirs(os.path.dirname(pad), exist_ok=True)
        data = {"aan": bool(aan), "sinds": (nu or datetime.now()).isoformat(timespec="seconds") if aan else None}
        tijdelijk = pad + ".tmp"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tijdelijk, pad)
    logger.info("In gesprek: %s", "aan" if aan else "uit")
    return status(pad)


def discord_call():
    """True als Discord nu de microfoon gebruikt (game-pc of deze pc)."""

    try:
        from core import discord_dms

        if discord_dms.game_pc_in_call():
            return True
    except Exception:
        pass
    try:
        from actions.discord_meldingen import discord_in_call

        return discord_in_call()
    except Exception:
        return False


def status(pad=None):
    knop = knop_aan(pad)
    call = discord_call()
    bron = "knop" if knop else ("discord" if call else None)
    return {"aan": knop or call, "knop": knop, "discord": call, "bron": bron}


def is_actief(pad=None):
    """Moet JARVIS na een antwoord stoppen met doorluisteren?"""

    try:
        return knop_aan(pad) or discord_call()
    except Exception:
        return False
