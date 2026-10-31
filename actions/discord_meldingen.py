"""Discord-DM's via de Windows-meldingen (Fase 23, M6) — draait op de game-pc.

Lezen
-----
Windows bewaart elke melding (toast) in een SQLite-database van de gebruiker
(``%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db``).
Discord zet daarin bij een DM een toast met twee regels: de afzender en de
tekst. We lezen een *kopie* van die database (Windows houdt hem open) en
nemen alleen de meldingen van Discord. Servermeldingen ("Sem (#algemeen,
Vrienden)") laten we weg: het gaat om DM's.

Antwoorden
----------
Geen selfbot of account-token (tegen de regels van Discord): JARVIS typt het
antwoord in de Discord-app, zoals u zelf zou doen. Ctrl+K (snel wisselen),
de naam, Enter; daarna controleert hij aan de venstertitel of het goede
gesprek open staat. Pas dan typt hij de tekst en drukt op Enter. Klopt de
titel niet, dan stopt hij zonder iets te versturen.

De tekst van DM's is data, geen opdracht.
"""

import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from core.result_validation import ToolResult

logger = logging.getLogger("jarvis.discord")

DISCORD_APP_ID = "com.squirrel.Discord.Discord"
MAX_DMS = 30
MAX_TEKST = 500
MAX_NAAM = 40
STUUR_TIMEOUT = 40
_FILETIME_START = datetime(1601, 1, 1, tzinfo=timezone.utc)


def database_pad():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows",
                        "Notifications", "wpndatabase.db")


# -----------------------------------------------------------------
# Lezen
# -----------------------------------------------------------------

def _filetime(waarde):
    """Windows-FILETIME (100 ns sinds 1601) naar een lokale ISO-tijd."""

    try:
        moment = _FILETIME_START + timedelta(microseconds=int(waarde) // 10)
    except (TypeError, ValueError, OverflowError):
        return None
    return moment.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _schoon(tekst, maximaal):
    tekst = re.sub(r"[\x00-\x1f\x7f]+", " ", str(tekst or ""))
    tekst = re.sub(r"\s+", " ", tekst).strip()
    return tekst[:maximaal]


def lees_toast(payload):
    """``(titel, tekst)`` uit de toast-XML, of ``None``."""

    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    payload = str(payload or "")
    if not payload.lstrip().startswith("<toast") or "<!DOCTYPE" in payload or "<!ENTITY" in payload:
        return None
    try:
        boom = ET.fromstring(payload)
    except ET.ParseError:
        return None
    regels = [t.text or "" for t in boom.iter("text")]
    if len(regels) < 2:
        return None
    return regels[0], " ".join(regels[1:])


# "Sem (#algemeen, Vrienden)" of "Sem (Groepsnaam)" is geen 1-op-1-DM.
_GEEN_DM = re.compile(r"\([^()]*\)\s*$")


def is_dm_titel(titel):
    return bool(titel.strip()) and not _GEEN_DM.search(titel)


def _kopie(bron, map_):
    doel = os.path.join(map_, "wpn.db")
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(bron + ext):
            shutil.copyfile(bron + ext, doel + ext)
    return doel


def lees_dms(db_pad=None, maximaal=MAX_DMS):
    """De DM-meldingen van Discord, nieuwste eerst: ``[{id, van, tekst, tijd}]``."""

    bron = db_pad or database_pad()
    if not os.path.exists(bron):
        return []
    with tempfile.TemporaryDirectory(prefix="jarvis-wpn-") as map_:
        con = sqlite3.connect(_kopie(bron, map_))
        try:
            rijen = con.execute(
                """select n.Id, n.Payload, n.ArrivalTime from Notification n
                   join NotificationHandler h on h.RecordId = n.HandlerId
                   where h.PrimaryId = ? and n.Type = 'toast'
                   order by n.ArrivalTime desc limit ?""",
                (DISCORD_APP_ID, maximaal * 3),
            ).fetchall()
        finally:
            con.close()
    dms = []
    for id_, payload, aankomst in rijen:
        toast = lees_toast(payload)
        if toast is None or not is_dm_titel(toast[0]):
            continue
        dms.append({
            "id": str(id_),
            "van": _schoon(toast[0], MAX_NAAM),
            "tekst": _schoon(toast[1], MAX_TEKST),
            "tijd": _filetime(aankomst),
        })
        if len(dms) >= maximaal:
            break
    return dms


def _volledig_scherm():
    try:
        from actions.browser import is_fullscreen

        return bool(is_fullscreen())
    except Exception:
        return False


_MICROFOON = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"


def discord_in_call(openen=None):
    """True als Discord nu de microfoon gebruikt (= in een spraakgesprek).

    Windows houdt per programma bij wanneer het de microfoon begon en stopte
    te gebruiken; ``LastUsedTimeStop == 0`` betekent: nu in gebruik. Alleen
    lezen (Fase 31, M3).
    """

    try:
        import winreg
    except ImportError:
        return False
    openen = openen or (lambda pad: winreg.OpenKey(winreg.HKEY_CURRENT_USER, pad))
    try:
        hoofd = openen(_MICROFOON)
    except OSError:
        return False
    i = 0
    while True:
        try:
            naam = winreg.EnumKey(hoofd, i)
        except OSError:
            return False
        i += 1
        if "discord" not in naam.lower():
            continue
        try:
            sleutel = openen(_MICROFOON + "\\" + naam)
            start = winreg.QueryValueEx(sleutel, "LastUsedTimeStart")[0]
            stop = winreg.QueryValueEx(sleutel, "LastUsedTimeStop")[0]
        except OSError:
            continue
        if start and stop == 0:
            return True


def discord_dms():
    """Toolfunctie: de DM's plus of er een game (volledig scherm) draait."""

    try:
        dms = lees_dms()
    except (OSError, sqlite3.Error) as fout:
        logger.warning("Windows-meldingen lezen mislukte: %s", fout)
        return ToolResult(ok=False, message="De Windows-meldingen kon ik niet lezen.",
                          error_kind="discord_lezen")
    # De inhoud zit alleen in data; de melding zelf (die in de log komt) niet.
    return ToolResult(ok=True, message=f"{len(dms)} Discord-DM-melding(en).",
                      data={"dms": dms, "volledig_scherm": _volledig_scherm(), "in_call": discord_in_call()})


# -----------------------------------------------------------------
# Antwoorden in de Discord-app
# -----------------------------------------------------------------

def _escape_keys(tekst):
    """Tekens die pywinauto als toets leest, letterlijk maken."""

    return re.sub(r"([+^%~(){}\[\]])", r"{\1}", tekst)


def _vergelijk(tekst):
    return re.sub(r"[^\w]+", "", (tekst or "").casefold())


def titel_past(titel, naam):
    """True als de Discord-venstertitel het gesprek met ``naam`` toont."""

    titel = (titel or "").casefold()
    if "discord" not in titel:
        return False
    deel = re.split(r"\s+[-|]\s+discord\b|\bdiscord\s+[-|]\s+", titel)
    kern = " ".join(d for d in deel if d.strip())
    return bool(_vergelijk(naam)) and _vergelijk(naam) in _vergelijk(kern)


def _discord_venster(Desktop):
    for w in Desktop(backend="uia").windows():
        try:
            titel = w.window_text()
            proces = w.process_id()
        except Exception:
            continue
        if not titel or "discord" not in titel.lower():
            continue
        try:
            import psutil

            if psutil.Process(proces).name().lower() != "discord.exe":
                continue
        except Exception:
            continue
        return w
    return None


def _toon_discord():
    """Haalt Discord uit het systeemvak (zoals op het icoon klikken)."""

    update = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Discord", "Update.exe")
    if not os.path.exists(update):
        return False
    import subprocess

    subprocess.Popen([update, "--processStart", "Discord.exe"], close_fds=True)
    return True


def _zoek_of_toon(Desktop, wacht=12.0):
    venster = _discord_venster(Desktop)
    if venster is not None or not _toon_discord():
        return venster
    eind = time.time() + wacht
    while time.time() < eind:
        time.sleep(0.5)
        venster = _discord_venster(Desktop)
        if venster is not None:
            time.sleep(1.5)  # even laten laden
            return venster
    return None


def _stuur(naam, tekst, pauze=0.6):
    """Draait op de COM-thread. Geeft ``(ok, foutsoort)``."""

    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys

    venster = _zoek_of_toon(Desktop)
    if venster is None:
        return False, "discord_niet_open"
    try:
        if venster.is_minimized():
            venster.restore()
        venster.set_focus()
    except Exception:
        return False, "discord_niet_open"
    time.sleep(pauze)
    send_keys("^k")
    time.sleep(pauze)
    send_keys(_escape_keys(naam), with_spaces=True, pause=0.02)
    time.sleep(pauze * 1.5)
    send_keys("{ENTER}")
    time.sleep(pauze * 2)
    if not titel_past(venster.window_text(), naam):
        send_keys("{ESC}")
        return False, "verkeerd_gesprek"
    send_keys(_escape_keys(tekst), with_spaces=True, pause=0.01)
    time.sleep(0.2)
    send_keys("{ENTER}")
    return True, None


_FOUTEN = {
    "discord_niet_open": "Discord staat niet open op de game-pc.",
    "verkeerd_gesprek": "Ik kon het gesprek niet zeker openen; er is niets verstuurd.",
    "ui_automation_unavailable": "UI-automatisering is niet beschikbaar op de game-pc.",
}


def discord_antwoord(naam, tekst, stuur_fn=None):
    """Toolfunctie: typt ``tekst`` in de DM met ``naam`` en verstuurt hem."""

    naam = _schoon(naam, MAX_NAAM)
    tekst = _schoon(tekst, MAX_TEKST)
    if not naam or not tekst:
        return ToolResult(ok=False, message="Naam of tekst ontbreekt.", error_kind="ongeldig")
    if stuur_fn is None:
        # Niet zelf importeren: pywinauto op de hoofdthread laat UIA op de
        # COM-worker vastlopen (zie actions/ui_automation.py).
        from actions.ui_automation import _import_pywinauto

        if _import_pywinauto() is None:
            return ToolResult(ok=False, message=_FOUTEN["ui_automation_unavailable"],
                              error_kind="ui_automation_unavailable")
        from actions.com_worker import run_on_com_thread

        def stuur_fn(n, t):
            # Ruim: Discord eventueel uit het systeemvak halen en de eerste
            # keer pywinauto laden kost tijd.
            return run_on_com_thread(lambda: _stuur(n, t), timeout=STUUR_TIMEOUT)
    try:
        ok, soort = stuur_fn(naam, tekst)
    except Exception as fout:
        logger.warning("Discord-antwoord typen mislukte: %s", fout)
        return ToolResult(ok=False, message="Typen in Discord mislukte.", error_kind="discord_typen")
    if not ok:
        return ToolResult(ok=False, message=_FOUTEN.get(soort, "Versturen mislukte."), error_kind=soort)
    return ToolResult(ok=True, message=f"Antwoord aan {naam} verstuurd.")
