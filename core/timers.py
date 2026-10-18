"""Timers en herinneringen (Fase 16A — proactieve JARVIS).

Een timer heeft een naam, een duur in seconden en een absoluut
afloop-tijdstip (epoch). Doordat het afloop-tijdstip absoluut is,
overleven timers een herstart van JARVIS: na het laden worden verlopen
timers gewoon afgehandeld.

Opslag volgt hetzelfde patroon als ``core/routines.py``: JSON met
atomair schrijven en een ``.bak``-backup.

Ontwerpregels
-------------
* **Nooit crashen.** Corrupte bestanden leveren een lege lijst op.
* **Deterministisch.** De klok is injecteerbaar (``clock``), zodat tests
  geen ``sleep()`` nodig hebben.
"""

import logging
import os
import threading
import uuid

logger = logging.getLogger(__name__)

TIMERS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "timers.json",
)


def _leeg_bestand():
    return {"timers": []}


def _laad_timers(pad=TIMERS_FILE):
    """Laadt timers uit het JSON-bestand; corruptie => lege lijst."""

    import json

    try:
        with open(pad, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("timers"), list):
                return data
    except (OSError, json.JSONDecodeError):
        pass

    # Backup proberen
    try:
        bak = pad + ".bak"
        if os.path.exists(bak):
            with open(bak, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("timers"), list):
                    return data
    except Exception:
        pass

    return _leeg_bestand()


def _sla_timers_op(data, pad=TIMERS_FILE):
    """Slaat timer-data op. Atomair, met backup van het vorige bestand."""

    import json
    import tempfile

    os.makedirs(os.path.dirname(pad), exist_ok=True)

    if os.path.exists(pad):
        try:
            import shutil
            shutil.copy2(pad, pad + ".bak")
        except Exception:
            pass

    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return False

    directory = os.path.dirname(pad) or "."
    handle = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=directory,
            prefix=os.path.basename(pad) + ".",
            suffix=".tmp",
        )
        handle = os.fdopen(fd, "w", encoding="utf-8")
        handle.write(text)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
        handle.close()
        handle = None
        os.replace(tmp_path, pad)
        tmp_path = None
        return True
    except Exception:
        return False
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def parse_duur(text):
    """Zet een Nederlandse tijdsduur om in seconden.

    Ondersteunt onder meer: "10 minuten", "10 min", "een uur", "half uur",
    "kwartier", "1 uur 30", "2 min", "30 seconden". Geeft het aantal
    seconden terug, of None als er geen duur gevonden wordt.
    """

    import re

    if not text:
        return None

    text = str(text).lower()

    eenheden = {
        "seconde": 1, "seconden": 1,
        "minuut": 60, "minuten": 60,
        "uur": 3600, "uren": 3600,
    }

    getallen = {
        "een": 1, "eën": 1, "twee": 2, "drie": 3, "vier": 4,
        "vijf": 5, "zes": 6, "zeven": 7, "acht": 8, "negen": 9,
        "tien": 10,
    }

    def _getal(token):
        if token.isdigit():
            return int(token)
        return getallen.get(token)

    total = 0
    gevonden = False

    # "kwartier" = 15 minuten
    for _ in re.finditer(r"\bkwartier\b", text):
        total += 15 * 60
        gevonden = True

    # "half uur" / "halve uur" = 30 minuten
    for _ in re.finditer(r"\b(?:half|halve)\s+uur\b", text):
        total += 30 * 60
        gevonden = True

    # Losse eenheden: "<getal> <eenheid>"
    patroon = re.compile(
        r"\b(\d+|een|eën|twee|drie|vier|vijf|zes|zeven|acht|negen|tien)"
        r"\s*(?:\+s)?"
        r"\s*(seconde|seconden|minuut|minuten|min|mins|uur|uren|u)\b"
    )

    for match in patroon.finditer(text):
        # "half uur" al hierboven verwerkt; niet dubbel tellen
        start = match.start()
        vooraf = text[max(0, start - 6):start]
        if vooraf.rstrip().endswith(("half", "halve")):
            continue

        aantal = _getal(match.group(1))
        if aantal is None:
            continue

        eenheid = match.group(2)
        if eenheid in ("min", "mins"):
            eenheid = "minuten"
        elif eenheid == "u":
            eenheid = "uur"

        total += aantal * eenheden[eenheid]
        gevonden = True

    if not gevonden or total <= 0:
        return None

    return total


class TimerStore:
    """Beheert timers: aanmaken, tonen, annuleren en verloop afhandelen.

    De store is thread-safe: de proactieve engine (achtergrondthread) en
    de brain (hoofdthread) gebruiken hem tegelijk.
    """

    def __init__(self, pad=TIMERS_FILE, clock=None):
        import time as _time

        self.pad = pad
        self.clock = clock if clock is not None else _time.time
        self._lock = threading.Lock()
        self._data = _laad_timers(pad)

    def _opslaan(self):
        """Schrijft de huidige staat naar schijf (onder de lock)."""
        return _sla_timers_op(self._data, self.pad)

    def zet(self, naam, seconden):
        """Zet een nieuwe timer van ``seconden``.

        Geeft de timer-dict terug (met id, naam, afloop-tijdstip), of None
        als de duur ongeldig is.
        """

        try:
            seconden = int(seconden)
        except (TypeError, ValueError):
            return None

        if seconden <= 0:
            return None

        naam = (naam or "herinnering").strip() or "herinnering"
        nu = self.clock()

        timer = {
            "id": uuid.uuid4().hex[:12],
            "naam": naam,
            "gezet_op": nu,
            "af_loopt_op": nu + seconden,
            "duur_seconden": seconden,
        }

        with self._lock:
            self._data["timers"].append(timer)
            self._opslaan()

        logger.info(
            "Timer gezet: '%s' over %d seconden (om %d).",
            naam, seconden, timer["af_loopt_op"],
        )
        return timer

    def lijst(self):
        """Geeft de (nog niet verlopen) timers terug, op afloop gesorteerd."""

        nu = self.clock()
        with self._lock:
            actief = [
                t for t in self._data["timers"]
                if isinstance(t, dict) and t.get("af_loopt_op", 0) > nu
            ]
        return sorted(actief, key=lambda t: t.get("af_loopt_op", 0))

    def annuleer(self, naam=None):
        """Annuleert timers. Zonder ``naam`` alle timers.

        Geeft het aantal geannuleerde timers terug.
        """

        with self._lock:
            if naam is None:
                aantal = len(self._data["timers"])
                self._data["timers"] = []
            else:
                naam_l = naam.lower().strip()
                te_houden = [
                    t for t in self._data["timers"]
                    if not (isinstance(t, dict)
                            and str(t.get("naam", "")).lower().strip() == naam_l)
                ]
                aantal = len(self._data["timers"]) - len(te_houden)
                self._data["timers"] = te_houden
            if aantal:
                self._opslaan()
        return aantal

    def verlopen_timers(self):
        """Haalt alle verlopen timers uit de store en geeft ze terug.

        Wordt elke engine-tick aangeroepen; timers die tijdens een
        herstart verlopen zijn worden zo alsnog afgehandeld.
        """

        nu = self.clock()
        with self._lock:
            verlopen = [
                t for t in self._data["timers"]
                if isinstance(t, dict) and t.get("af_loopt_op", 0) <= nu
            ]
            if verlopen:
                ids = {t.get("id") for t in verlopen}
                self._data["timers"] = [
                    t for t in self._data["timers"]
                    if not (isinstance(t, dict) and t.get("id") in ids)
                ]
                self._opslaan()
        return verlopen


# ---------------------------------------------------------------
# Module-level store (zoals core/routines.py een module-level
# manager heeft). Tests maken hun eigen store met een fake klok.
# ---------------------------------------------------------------

_store = None
_store_lock = threading.Lock()


def get_store():
    """Geeft de gedeelde TimerStore terug (lazy init)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = TimerStore()
        return _store


def reset_store(store=None):
    """Vervangt de gedeelde store (voor tests en herstart-simulaties)."""
    global _store
    with _store_lock:
        _store = store
