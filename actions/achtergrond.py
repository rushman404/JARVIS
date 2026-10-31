"""Wat de game-pc op de achtergrond doet: updates en downloads (Fase 28, M1).

Draait op de game-pc-agent en leest alleen:

* **Windows Update:** of er nu een update wordt geïnstalleerd
  (``Microsoft.Update.Installer.IsBusy``) en of Windows wil herstarten
  (de bekende ``RebootRequired``/``RebootPending``-sleutels in het register).
* **Steam:** per game de ``appmanifest_<id>.acf``: een update of download
  die loopt (``StateFlags``) en hoe ver hij is (``BytesDownloaded``).
* **Riot (best effort):** eerst de lokale Riot Client-API via de
  ``lockfile`` (alleen 127.0.0.1, met het wachtwoord uit die lockfile);
  zegt die niets, dan: schrijft de Riot Client meer dan ~1 MB/s naar
  schijf? Dat doet hij alleen tijdens het patchen.

Het resultaat is per bron ``{"bezig": True | False | None, ...}``;
``None`` betekent: niet te zien.
"""

import glob
import os
import re
import warnings

from core.result_validation import ToolResult

# Steam StateFlags: 256 = update loopt, 1024 = update gestart, 512 = gepauzeerd.
STEAM_LOOPT = 256 | 1024
STEAM_PAUZE = 512

_HERSTART_SLEUTELS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
)

RIOT_LOCKFILE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Riot Games", "Riot Client", "Config", "lockfile")
RIOT_PADEN = ("/patch/v1/installs",)
_RIOT_RUST = {"", "idle", "none", "up_to_date", "uptodate", "complete", "completed", "finished"}


# -----------------------------------------------------------------
# Windows Update
# -----------------------------------------------------------------

def _installer_bezig():
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            return bool(win32com.client.Dispatch("Microsoft.Update.Installer").IsBusy)
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return None


def _herstart_nodig():
    try:
        import winreg
    except ImportError:
        return None
    for pad in _HERSTART_SLEUTELS:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, pad))
            return True
        except OSError:
            continue
    return False


def windows_update(bezig_fn=None, herstart_fn=None):
    return {"bezig": (bezig_fn or _installer_bezig)(), "herstart": bool((herstart_fn or _herstart_nodig)())}


# -----------------------------------------------------------------
# Steam
# -----------------------------------------------------------------

def _getal(tekst, sleutel):
    m = re.search(r'"%s"\s+"(\d+)"' % sleutel, tekst)
    return int(m.group(1)) if m else 0


def steam_download(tekst):
    """``{"naam", "procent"}`` als dit manifest een lopende download is, anders None."""

    from actions.games import lees_manifest

    gevonden = lees_manifest(tekst)
    if not gevonden:
        return None
    vlaggen = _getal(tekst, "StateFlags")
    totaal = _getal(tekst, "BytesToDownload")
    binnen = _getal(tekst, "BytesDownloaded")
    if vlaggen & STEAM_PAUZE:
        return None
    if not (vlaggen & STEAM_LOOPT or (0 < binnen < totaal)):
        return None
    procent = int(binnen * 100 / totaal) if totaal else None
    return {"naam": gevonden[1], "procent": procent}


def steam(steam_map=None):
    from actions.games import steam_bibliotheken, steam_pad

    steam_map = steam_map or steam_pad()
    if not steam_map:
        return {"bezig": None, "games": []}
    games = []
    for map_ in steam_bibliotheken(steam_map):
        for pad in glob.glob(os.path.join(map_, "steamapps", "appmanifest_*.acf")):
            try:
                download = steam_download(open(pad, encoding="utf-8", errors="replace").read())
            except OSError:
                continue
            if download:
                games.append(download)
    return {"bezig": bool(games), "games": games}


# -----------------------------------------------------------------
# Riot (best effort)
# -----------------------------------------------------------------

def _riot_get(pad, lockfile=RIOT_LOCKFILE):
    import requests

    with open(lockfile, encoding="utf-8") as f:
        delen = f.read().strip().split(":")
    poort, wachtwoord = delen[2], delen[3]
    # De Riot Client gebruikt een eigen certificaat op 127.0.0.1; alleen daar.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.get(f"https://127.0.0.1:{poort}{pad}", auth=("riot", wachtwoord), verify=False, timeout=3)
    r.raise_for_status()
    return r.json()


def _riot_acties(data, uit):
    if isinstance(data, dict):
        for sleutel, waarde in data.items():
            if sleutel.lower() in ("action", "patch_state", "state") and isinstance(waarde, str):
                uit.append(waarde)
            else:
                _riot_acties(waarde, uit)
    elif isinstance(data, list):
        for waarde in data:
            _riot_acties(waarde, uit)
    return uit


RIOT_PROCESSEN = ("riotclientservices.exe", "riot client.exe")
RIOT_MEET_SECONDEN = 2.0
RIOT_SCHRIJF_DREMPEL = 2 * 1024 * 1024  # bytes in die 2 s: ~1 MB/s


def _riot_processen():
    import psutil

    return [p for p in psutil.process_iter(["name"])
            if (p.info.get("name") or "").lower() in RIOT_PROCESSEN]


def _riot_schrijft(processen_fn=None, slaap=None, seconden=RIOT_MEET_SECONDEN):
    """True als de Riot Client flink naar schijf schrijft (patchen), None als dat niet te zien is."""

    import time

    processen = (processen_fn or _riot_processen)()
    if not processen:
        return False

    def geschreven():
        totaal = 0
        for proc in processen:
            try:
                totaal += proc.io_counters().write_bytes
            except Exception:
                continue
        return totaal

    try:
        voor = geschreven()
        (slaap or time.sleep)(seconden)
        return geschreven() - voor >= RIOT_SCHRIJF_DREMPEL
    except Exception:
        return None


def riot(get_fn=None, lockfile=RIOT_LOCKFILE, schrijft_fn=None):
    """Eerst de lokale API (als de client daar iets over zegt), anders: schrijft hij veel?"""

    if get_fn is None and not os.path.isfile(lockfile):
        return {"bezig": False, "draait": False}
    get_fn = get_fn or (lambda pad: _riot_get(pad, lockfile))
    acties = []
    for pad in RIOT_PADEN:
        try:
            _riot_acties(get_fn(pad), acties)
        except Exception:
            continue
    if acties:
        bezig = any(a.strip().lower().replace(" ", "_") not in _RIOT_RUST for a in acties)
        return {"bezig": bezig, "draait": True}
    return {"bezig": (schrijft_fn or _riot_schrijft)(), "draait": True}


# -----------------------------------------------------------------
# Samen
# -----------------------------------------------------------------

def achtergrond_status():
    status = {}
    for naam, fn in (("windows", windows_update), ("steam", steam), ("riot", riot)):
        try:
            status[naam] = fn()
        except Exception:
            status[naam] = {"bezig": None}
    return ToolResult(ok=True, message="Achtergrondstatus gelezen.", data=status)
