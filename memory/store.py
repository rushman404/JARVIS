"""
JARVIS — Memory Store (Fase 14, Stap 1)
======================================

Betrouwbare opslaglaag voor memory/memory.json.

Deze module is de ENIGE plek die het geheugenbestand op schijf
aanraakt. memory/memory.py doet alleen nog logica ( categoriseren,
onthouden, ophalen) en vraagt hier om te lezen en schrijven.

Verantwoordelijk voor:
  1. In-memory cache   — niet bij elke aanroep dezelfde JSON lezen
  2. Atomic writes     — een crash mag memory.json nooit hal geschreven
                          achterlaten
  3. Backup            — na elke goede write staat de laatste goede
                          staat in memory.json.bak
  4. Corruptieherstel  — bij onleesbaar JSON: eerst de backup
                          proberen, anders een veilige default
  5. File locking      — eenvoudige, fail-open vergrendeling

Ontwerpkeuzes
-------------
* Per bestand één cache-entry, herkenbaar aan het VOLLEDIGE pad.
  Tests die memory.memory.MEMORY_FILE op een tijdelijk bestand
  zetten krijgen daardoor nooit de cache van een ander bestand.
* De cache wordt gevalideerd tegen mtime + size + inode van het
  bestand. Wordt het bestand extern vervangen, dan wordt de cache
  alsnog genegeerd en opnieuw ingelezen.
* read() geeft altijd een EIGEN kopie (deepcopy) terug, net als
  toen elke aanroep de JSON opnieuw parseerde. Callers mogen hun
  resultaat dus veilig muteren zonder de cache te beschadigen.
* Geen database, geen recovery-framework. Eén bestand, één backup,
  één lock. Alles is voorspelbaar en na te lezen.
"""

import copy
import json
import os
import tempfile
import threading
import time

try:                                    # alleen beschikbaar op Windows
    import msvcrt
except ImportError:                     # pragma: no cover
    msvcrt = None


# =============================================================
# Constanten
# =============================================================

BACKUP_SUFFIX = ".bak"
CORRUPT_SUFFIX = ".corrupt"
LOCK_SUFFIX = ".lock"
TMP_SUFFIX = ".tmp"

# Identiek aan de json.dump-opties die memory.py altijd gebruikte
JSON_INDENT = 4
JSON_ENSURE_ASCII = False

# Cache-statistiek (handig voor tests en debugging)
STATS = {
    "reads": 0,
    "cache_hits": 0,
    "writes": 0,
    "recovered": 0,
    "fallbacks": 0,
    "lock_failures": 0,
}

# In-process slot. Beschermt de cache tegen gelijktijdige threads
# binnen hetzelfde proces.
_THREAD_LOCK = threading.RLock()

# pad -> {"data": <geparseerde json>, "sig": (mtime_ns, size, ino)}
_CACHE = {}


# =============================================================
# Interne helpers
# =============================================================

def _key(path):
    """Volledig genormaliseerd pad als cache-sleutel."""

    return os.path.abspath(path)


def _signature(path):
    """
    Signatuur van het huidige bestand op schijf.

    Bestaat niet -> None. Verandert er iets op schijf (mtime,
    grootte of inode), dan verandert de signatuur en wordt de
    cache genegeerd.
    """

    try:
        stat = os.stat(path)
    except OSError:
        return None

    return (
        getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
        stat.st_size,
        getattr(stat, "st_ino", 0),
    )


def reset_cache(path=None):
    """
    Leegt de cache (voor één pad, of voor alles als path None is).

    Aanroepen is nooit nodig voor normaal gebruik; het bestaat
    zodat tests en toekomstige backends de cache bewust kunnen
    legger maken.
    """

    with _THREAD_LOCK:
        if path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(_key(path), None)


def _remember_in_cache(path, data):
    """Zet de cache op de zojuist gelezen of geschreven inhoud."""

    with _THREAD_LOCK:
        _CACHE[_key(path)] = {
            "data": data,
            "sig": _signature(path),
        }


def _drop_from_cache(path):
    """Verwijdert de cache-entry voor één pad."""

    with _THREAD_LOCK:
        _CACHE.pop(_key(path), None)


# =============================================================
# Locking
# =============================================================
#
# Onderzoeksvraag: is locking nodig in de huidige JARVIS?
#
# Antwoord: strikt genomen NEEIT. JARVIS draait als één proces
# (main.py) en memory.json wordt door niets anders geschreven.
# De atomic write hieronder voorkomt al het gevaar dat je wel echt
# wilt afdekken: een halfgeschreven bestand dat een crash achterlaat.
#
# Wat overblijft is read-modify-write ("lees, pas aan, schrijf")
# tussen twee processen tegelijk. Dat speelt nu niet, maar wel
# zodra Fase 15 (Game-PC Agent) een tweede proces wordt dat ook
# memory aanraakt. Daarom zit hier een kleine, fail-open lock:
#
#   * ~30 regels, geen extra package
#   * geen deadlock: het OS ruimt een lock op bij proceseinde
#   * faalt het lock, dan gaan we gewoon door (huidig gedrag).
#     Vergrendelen mag JARVIS nooit tegenhouden.
# =============================================================

def _acquire(handle):
    """Probeert 1 byte te vergrendelen. True = verkregen."""

    if msvcrt is None or os.name != "nt":
        return True

    try:
        handle.seek(0)
    except OSError:
        return True

    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False

    return True


def _release(handle):
    """Haalt de vergrendeling weer weg (beste effort)."""

    if msvcrt is None or os.name != "nt":
        return

    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


def _acquire_with_retry(handle, attempts=20, delay=0.01):
    """
    Kort proberen de lock te krijgen. Geeft de lock na een
    halve seconde op: dan gaat JARVIS gewoon verder zonder.
    """

    for attempt in range(attempts):
        if _acquire(handle):
            return True

        time.sleep(delay)

    STATS["lock_failures"] += 1

    return False


def file_lock(path):
    """
    Context manager die het geheugenbestand vergrendelt.

    Gebruik:

        with file_lock(MEMORY_FILE):
            data = read(path)
            ...
            write(path, data)

    Fail-open: als de lock niet te krijgen is, wordt de code
    alsnog uitgevoerd, alleen zonder vergrendeling. Voorkomt dat
    een vastgelopen lock JARVIS lamlegt.
    """

    class _Lock:
        def __enter__(self):
            _THREAD_LOCK.acquire()

            self._handle = None
            self._held = False

            if msvcrt is None or os.name != "nt":
                return self

            try:
                self._handle = open(path + LOCK_SUFFIX, "a+b")

                # msvcrt heeft minimaal 1 byte nodig om te vergrendelen
                if self._handle.seek(0, os.SEEK_END) == 0:
                    self._handle.write(b"\0")
                    self._handle.flush()

                self._held = _acquire_with_retry(self._handle)
            except OSError:
                self._held = False

            return self

        def __exit__(self, exc_type, exc, traceback):
            try:
                if self._held and self._handle is not None:
                    _release(self._handle)
            finally:
                if self._handle is not None:
                    try:
                        self._handle.close()
                    except OSError:
                        pass
                _THREAD_LOCK.release()

            return False

    return _Lock()


# =============================================================
# Atomic write
# =============================================================

def _atomic_write_text(path, text):
    """
    Schrijft text naar path zonder ooit een halfgeschreven bestand
    achter te laten.

    1. schrijf naar een tijdelijk bestand in dezelfde map
    2. flush + fsync zodat de data echt op schijf staat
    3. os.replace() wisselt het origineel en het tijdelijke bestand
       atomair om

    Geeft True bij succes, False als het niet lukte.
    """

    directory = os.path.dirname(os.path.abspath(path)) or "."

    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return False

    handle = None
    tmp_path = None

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=directory,
            prefix=os.path.basename(path) + ".",
            suffix=TMP_SUFFIX,
        )
        handle = os.fdopen(fd, "w", encoding="utf-8")

        handle.write(text)
        handle.flush()

        try:
            os.fsync(handle.fileno())
        except OSError:
            # sommige bestandssystemen ondersteunen fsync niet
            pass

        handle.close()
        handle = None

        os.replace(tmp_path, path)
        tmp_path = None

        return True
    except OSError:
        return False
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# =============================================================
# Backup
# =============================================================

def _write_backup(path, text):
    """
    Houdt memory.json.bak gelijk aan de laatste succesvolle write.

    Bewust simpel: na iedere goede write is de backup een kopie van
    wat er net op schijf staat. Raakt memory.json daarna kapot
    (schijfprobleem, halfgeschreven door een extern programma),
    dan staat hier de laatste goede staat.
    """

    _atomic_write_text(path + BACKUP_SUFFIX, text)


def _read_backup(path):
    """
    Probeert de backup te lezen. Geeft de geparseerde inhoud of None.
    """

    backup = path + BACKUP_SUFFIX

    if not os.path.exists(backup):
        return None

    try:
        with open(backup, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _quarantine(path):
    """
    Bewaart een kapot bestand als memory.json.corrupt.

    Het origineel wordt NIET verwijderd of overschreven: het wordt
    gekopieerd. Zo gaat er niets verloren en is de situatie
    terug te vinden, maar een kapot bestand blijft JARVIS niet
    hinderen.
    """

    corrupt = path + CORRUPT_SUFFIX

    try:
        if os.path.exists(path) and not os.path.exists(corrupt):
            with open(path, "rb") as source:
                data = source.read()

            with open(corrupt, "wb") as target:
                target.write(data)
    except OSError:
        pass


# =============================================================
# Publieke API
# =============================================================

def read(path):
    """
    Leest het geheugenbestand en geeft de geparseerde inhoud terug.

    Geeft None terug als er niets te lezen viel:
      * bestand bestaat niet
      * bestand is niet leesbaar
      * bestand is corrupt EN er is geen bruikbare backup

    Geeft altijd een eigen kopie terug, zodat de caller vrij kan
    muteren zonder de cache te beschadigen.
    """

    key = _key(path)
    current = _signature(key)

    # ---- cache: alleen geldig als het bestand onveranderd is ----
    with _THREAD_LOCK:
        cached = _CACHE.get(key)

        if cached is not None and current is not None \
                and cached.get("sig") == current:

            STATS["reads"] += 1
            STATS["cache_hits"] += 1

            return copy.deepcopy(cached["data"])

    # ---- echt lezen ----
    STATS["reads"] += 1

    data = None
    failed = False

    try:
        with open(key, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        _drop_from_cache(key)
        return None
    except (json.JSONDecodeError, OSError, ValueError, UnicodeDecodeError):
        failed = True

    if failed:
        # kapot bestand veilig bewaren, dan de backup proberen
        _quarantine(key)
        _drop_from_cache(key)

        recovered = _read_backup(key)

        if recovered is not None:
            STATS["recovered"] += 1
            _remember_in_cache(key, recovered)

            return copy.deepcopy(recovered)

        STATS["fallbacks"] += 1

        return None

    _remember_in_cache(key, data)

    return copy.deepcopy(data)


def write(path, data, indent=JSON_INDENT, ensure_ascii=JSON_ENSURE_ASCII):
    """
    Schrijft data atomair naar path en houdt de backup bij.

    Geeft True bij succes, False als het schrijven mislukte.
    """

    try:
        text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    except (TypeError, ValueError):
        return False

    with file_lock(path):

        if not _atomic_write_text(path, text):
            return False

        _write_backup(path, text)

    STATS["writes"] += 1

    # pas de cache aan: dit is per definitie de actuele inhoud
    _remember_in_cache(path, data)

    return True


def backup_path(path):
    """Pad van de backup bij dit geheugenbestand."""

    return path + BACKUP_SUFFIX


def corrupt_path(path):
    """Pad waar een corrupt bestand bewaard wordt."""

    return path + CORRUPT_SUFFIX
