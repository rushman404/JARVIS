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
import re
import threading
import unicodedata
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


# Nederlandse getalwoorden tot en met 100. De duurtekst wordt vóór het
# matchen ontdaan van diakritische tekens, dus de sleutels staan hier
# zonder trema's ("tweeentwintig" in plaats van "tweeëntwintig").
_EENHEID_WOORDEN = {
    1: "een", 2: "twee", 3: "drie", 4: "vier", 5: "vijf",
    6: "zes", 7: "zeven", 8: "acht", 9: "negen",
}

_GETALWOORDEN = {
    "een": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5,
    "zes": 6, "zeven": 7, "acht": 8, "negen": 9, "tien": 10,
    "elf": 11, "twaalf": 12, "dertien": 13, "veertien": 14,
    "vijftien": 15, "zestien": 16, "zeventien": 17, "achttien": 18,
    "negentien": 19,
    "twintig": 20, "dertig": 30, "veertig": 40, "vijftig": 50,
    "zestig": 60, "zeventig": 70, "tachtig": 80, "negentig": 90,
    "honderd": 100,
}

_TIENTAL_WOORDEN = {
    20: "twintig", 30: "dertig", 40: "veertig", 50: "vijftig",
    60: "zestig", 70: "zeventig", 80: "tachtig", 90: "negentig",
}

# Eenentwintig tot en met negenennegentig ("vijfentwintig").
for _tiental, _tiental_woord in _TIENTAL_WOORDEN.items():
    for _eenheid, _eenheid_woord in _EENHEID_WOORDEN.items():
        _GETALWOORDEN[_eenheid_woord + "en" + _tiental_woord] = (
            _tiental + _eenheid
        )

_EENHEDEN = {
    "seconde": 1, "seconden": 1, "sec": 1,
    "minuut": 60, "minuten": 60, "min": 60, "mins": 60,
    "uur": 3600, "uren": 3600, "u": 3600,
}

# Langste woorden eerst, zodat "eenentwintig" niet als "een" wordt gelezen.
_GETAL_ALTERNATIE = "|".join(
    sorted((re.escape(w) for w in _GETALWOORDEN), key=len, reverse=True)
)
_EENHEID_ALTERNATIE = "|".join(
    sorted((re.escape(w) for w in _EENHEDEN), key=len, reverse=True)
)

_TOKEN_PATROON = re.compile(
    rf"(?P<decimaal>\d+(?:\.\d+)?)"
    rf"|(?P<getalwoord>{_GETAL_ALTERNATIE})"
    rf"|(?P<anderhalf>anderhalve|anderhalf)"
    rf"|(?P<kwart>kwartier|kwart)"
    rf"|(?P<half>halve|half)"
    rf"|(?P<eenheid>{_EENHEID_ALTERNATIE})"
    rf"|(?P<en>en)"
)


def _normaliseer_duurtekst(text):
    """Maakt tekst geschikt voor de duur-grammatica.

    Diakritische tekens vervallen (één -> een) en een decimale komma
    wordt een punt (1,5 -> 1.5).
    """

    text = str(text).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"(?<=\d)[.,](?=\d)", ".", text)


def _duur_tokens(text):
    """Zet tekst om in duur-tokens: getallen, eenheden en kwalificaties."""

    tokens = []
    for match in _TOKEN_PATROON.finditer(text):
        if match.group("decimaal") is not None:
            try:
                tokens.append(("getal", float(match.group("decimaal"))))
            except ValueError:
                continue
        elif match.group("getalwoord") is not None:
            tokens.append(
                ("getal", float(_GETALWOORDEN[match.group("getalwoord")]))
            )
        elif match.group("anderhalf") is not None:
            tokens.append(("anderhalf", None))
        elif match.group("kwart") is not None:
            tokens.append(("kwart", None))
        elif match.group("half") is not None:
            tokens.append(("half", None))
        elif match.group("eenheid") is not None:
            tokens.append(("eenheid", _EENHEDEN[match.group("eenheid")]))
        elif match.group("en") is not None:
            tokens.append(("en", None))
    return tokens


def parse_duur(text):
    """Zet een Nederlandse tijdsduur om in seconden.

    Ondersteunt cijfers met komma of punt ("1,5 uur"), "anderhalf" en
    "anderhalve", "half", "kwart" en "kwartier", "drie kwartier",
    "2 en een half uur", getalwoorden tot en met honderd
    ("vijfentwintig minuten") en combinaties van uren, minuten en
    seconden met of zonder "en". Afkortingen als "u", "min" en "sec"
    zijn toegestaan.

    Onleesbare of dubbelzinnige invoer geeft None; er wordt nooit een
    waarde geraden.
    """

    if not text:
        return None

    tekst = _normaliseer_duurtekst(text)

    # Kloktijden ("kwart over drie", "kwart voor half vier") zijn geen
    # duur; die zouden anders als "een kwartier" worden gelezen.
    if re.search(r"\bkwart(?:ier)?\s+(?:over|voor)\b", tekst):
        return None

    tokens = _duur_tokens(tekst)
    if not tokens:
        return None

    totaal = 0.0
    gevonden = False
    onvolledig = False
    n = len(tokens)
    i = 0

    while i < n:
        soort, waarde = tokens[i]

        if soort == "getal":
            # "2 en een half uur" = 2,5 uur.
            if (i + 4 < n
                    and tokens[i + 1][0] == "en"
                    and tokens[i + 2][0] == "getal"
                    and tokens[i + 2][1] == 1
                    and tokens[i + 3][0] == "half"
                    and tokens[i + 4][0] == "eenheid"):
                totaal += (waarde + 0.5) * tokens[i + 4][1]
                gevonden = True
                i += 5
                continue

            # "en" tussen delen hoort bij de duur ("1 uur en 30 minuten").
            j = i + 1
            while j < n and tokens[j][0] == "en":
                j += 1

            if j >= n:
                onvolledig = True
                i += 1
                continue

            if tokens[j][0] == "kwart":
                # "drie kwartier" = 45 minuten.
                totaal += waarde * 15 * 60
                gevonden = True
                i = j + 1
                continue

            if tokens[j][0] == "half":
                # "een half uur" = 30 minuten. "twee half uur" is
                # dubbelzinnig en levert None op.
                if waarde == 1:
                    k = j + 1
                    while k < n and tokens[k][0] == "en":
                        k += 1
                    if k < n and tokens[k][0] == "eenheid":
                        totaal += 0.5 * tokens[k][1]
                        gevonden = True
                        i = k + 1
                        continue
                onvolledig = True
                i += 1
                continue

            if tokens[j][0] == "eenheid":
                eenheid = tokens[j][1]
                # "2 uur en een half [uur]" = 2,5 uur.
                k = j + 1
                if k < n and tokens[k][0] == "en":
                    m = k + 1
                    if (m + 1 < n
                            and tokens[m][0] == "getal"
                            and tokens[m][1] == 1
                            and tokens[m + 1][0] == "half"):
                        p = m + 2
                        if p < n and tokens[p][0] == "eenheid":
                            eenheid = tokens[p][1]
                            i = p + 1
                        else:
                            i = p
                        totaal += (waarde + 0.5) * eenheid
                        gevonden = True
                        continue
                totaal += waarde * eenheid
                gevonden = True
                i = j + 1
                continue

            # Los getal zonder eenheid: onvolledig, dus geen gok.
            onvolledig = True
            i += 1
            continue

        if soort == "anderhalf":
            j = i + 1
            while j < n and tokens[j][0] == "en":
                j += 1
            if j < n and tokens[j][0] == "eenheid":
                totaal += 1.5 * tokens[j][1]
                gevonden = True
                i = j + 1
                continue
            onvolledig = True
            i += 1
            continue

        if soort == "half":
            j = i + 1
            while j < n and tokens[j][0] == "en":
                j += 1
            if j < n and tokens[j][0] == "eenheid":
                totaal += 0.5 * tokens[j][1]
                gevonden = True
                i = j + 1
                continue
            onvolledig = True
            i += 1
            continue

        if soort == "kwart":
            # Los "kwart"/"kwartier" = 15 minuten.
            totaal += 15 * 60
            gevonden = True
            i += 1
            continue

        # "en" of een onbekend token: overslaan.
        i += 1

    if onvolledig or not gevonden or totaal <= 0:
        return None

    if float(totaal).is_integer():
        return int(totaal)
    return totaal


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
