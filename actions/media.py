import time
import ctypes
import threading
from actions.com_worker import run_on_com_thread

# Virtuele mediatoetsen van Windows (werken met vrijwel alle muziekapps)
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002


class _MOUSEINPUT(ctypes.Structure):

    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):

    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _HARDWAREINPUT(ctypes.Structure):

    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUT(ctypes.Structure):

    class _INPUTUNION(ctypes.Union):

        _fields_ = [
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    _anonymous_ = ("i",)

    _fields_ = [
        ("type", ctypes.c_ulong),
        ("i", _INPUTUNION),
    ]


def _press_media_key(vk):

    # Windows' keybd_event levert mediabewerkingen (volgende/vorige)
    # niet altijd door. SendInput is de betrouwbare methode.
    try:
        down = _INPUT()
        down.type = INPUT_KEYBOARD
        down.ki.wVk = vk

        up = _INPUT()
        up.type = INPUT_KEYBOARD
        up.ki.wVk = vk
        up.ki.dwFlags = KEYEVENTF_KEYUP

        events = (_INPUT * 2)(down, up)
        sent = ctypes.windll.user32.SendInput(2, events, ctypes.sizeof(_INPUT))
        time.sleep(0.05)
        return sent == 2

    except Exception as error:
        print(f"Fout bij mediatoets: {error}")
        return False


# De COM-objects blijven levend houden. Waarom: met de oude pycaw
# (20240210) is de volume-interface een *tweede* COM-pointer op hetzelfde
# adres (via cast). Zou de garbage collector die loslaten, dan wordt
# Release() tweemaal aangeroepen -> "access violation" in comtypes.
# In modulevariabelen bewaard worden ze pas vrijgegeven bij het afsluiten
# van het proces, en dan slaat comtypes de Release() over.
_device_cache = None
_interface_cache = None
_volume_cache = None


def reset_volume_cache():
    """Vergeet de gecachte volume-interface (bv. na een apparaatwissel)."""

    global _device_cache, _interface_cache, _volume_cache

    _device_cache = None
    _interface_cache = None
    _volume_cache = None


def _get_volume_interface():
    """Haal de volume-interface op. Moet op de COM-thread draaien.

    Let op: deze functie wordt zelf al binnen run_on_com_thread uitgevoerd.
    Ze mag dus geen nieuwe run_on_com_thread aanroepen, want dan wacht de
    COM-thread op zichzelf (deadlock) en volgt na 10 seconden een timeout.
    """

    global _device_cache, _interface_cache, _volume_cache

    if _volume_cache is not None:
        return _volume_cache

    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()
    _device_cache = device

    # Nieuwe pycaw (>= 2024-xx): GetSpeakers() geeft een AudioEndpoint met
    # een EndpointVolume-eigenschap.
    volume = getattr(device, "EndpointVolume", None)
    if volume is None:
        # Oudere pycaw (20240210): GetSpeakers() geeft een kale POINTER(IMMDevice).
        # Activeer IAudioEndpointVolume dan zelf.
        from ctypes import POINTER, cast

        from pycaw.pycaw import IAudioEndpointVolume

        interface = device.Activate(IAudioEndpointVolume._iid_, 0, None)
        _interface_cache = interface
        volume = cast(interface, POINTER(IAudioEndpointVolume))

    _volume_cache = volume

    return volume


_volume_lock = threading.RLock()  # deprecated (kept for compatibility)

def get_volume():
    try:
        def _get():
            volume=_get_volume_interface()
            return round(volume.GetMasterVolumeLevelScalar()*100)
        waarde = run_on_com_thread(_get)
        # pycaw hoort een getal te geven; alles anders is onbruikbaar.
        if isinstance(waarde, bool) or not isinstance(waarde, (int, float)):
            return None
        return int(waarde)
    except Exception as error:
        print(f'Fout bij volume lezen: {error}')
        return None

def set_volume(percent):
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return 'Ik kon het volume niet instellen.'
    percent=int(max(0,min(100,percent)))
    try:
        def _set():
            volume=_get_volume_interface()
            volume.SetMasterVolumeLevelScalar(percent/100,None)
        run_on_com_thread(_set)
        return f'Volume staat nu op {percent}%.'
    except Exception as error:
        print(f'Fout bij volume instellen: {error}')
        return 'Ik kon het volume niet instellen.'

def toggle_mute():
    try:
        def _toggle():
            volume=_get_volume_interface()
            muted=bool(volume.GetMute())
            volume.SetMute(not muted,None)
            return muted
        muted=run_on_com_thread(_toggle)
        if muted: return 'Geluid staat weer aan.'
        return 'Geluid gedempt.'
    except Exception as error:
        print(f'Fout bij dempen: {error}')
        return 'Ik kon het geluid niet dempen.'


def volume_up(step=5):
    current = get_volume()
    if current is None:
        return "Ik kon het volume niet lezen."
    new = min(100, current + step)
    set_volume(new)
    return f"Volume omhoog, nu op {new}%."


def volume_down(step=5):
    current = get_volume()
    if current is None:
        return "Ik kon het volume niet lezen."
    new = max(0, current - step)
    set_volume(new)
    return f"Volume omlaag, nu op {new}%."

def play_pause():

    if _press_media_key(VK_MEDIA_PLAY_PAUSE):
        return "Ik heb de muziek gepauzeerd of hervat."

    return "Ik kon de mediatoets niet indrukken."


def stop_media():

    if _press_media_key(VK_MEDIA_STOP):
        return "Muziek gestopt."

    return "Ik kon de mediatoets niet indrukken."


def next_track():

    if _press_media_key(VK_MEDIA_NEXT_TRACK):
        return "Ik sla het nummer over."

    return "Ik kon de mediatoets niet indrukken."


def previous_track():

    if _press_media_key(VK_MEDIA_PREV_TRACK):
        return "Ik ga terug naar het vorige nummer."

    return "Ik kon de mediatoets niet indrukken."


# ---------------------------------------------------------------
# Eén app pauzeren (Fase 21, M1: film-modus)
# ---------------------------------------------------------------
# De mediatoets wisselt (afspelen <-> pauze) en gaat naar de app die
# Windows kiest. Voor "pc stil" mag JARVIS nooit per ongeluk muziek
# STARTEN, dus pauzeert hij alleen een app die echt speelt, en stuurt hij
# de toets rechtstreeks naar het venster van die app (WM_APPCOMMAND).

WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_PLAY_PAUSE = 14

# Zo heet het Spotify-venster als er NIETS speelt; tijdens het afspelen
# staat er "Artiest - Nummer" in de titel.
_SPOTIFY_STIL = ("spotify", "spotify premium", "spotify free")


def _vensters_van(app_name):
    """``[(hwnd, titel)]`` van de zichtbare vensters van een app."""

    import psutil
    import win32gui
    import win32process

    doel = str(app_name or "").strip().lower()
    if doel.endswith(".exe"):
        doel = doel[:-4]
    vensters = []

    def _bekijk(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        titel = win32gui.GetWindowText(hwnd)
        if not titel:
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            naam = psutil.Process(pid).name().lower()
        except Exception:
            return True
        if (naam[:-4] if naam.endswith(".exe") else naam) == doel:
            vensters.append((hwnd, titel))
        return True

    win32gui.EnumWindows(_bekijk, None)
    return vensters


def _speelt(app_name, vensters):
    """True als de app nu afspeelt (alleen Spotify is betrouwbaar te lezen)."""

    if str(app_name).strip().lower().startswith("spotify"):
        return any(t.strip().lower() not in _SPOTIFY_STIL for _, t in vensters)
    return None


def pauzeer_app(app_name, vensters_fn=None, stuur_fn=None, wacht=1.0):
    """Pauzeert ``app_name`` als die speelt. Geeft een ToolResult terug.

    ``data["gepauzeerd"]`` is True als JARVIS echt iets op pauze zette;
    ``data["reden"]`` is "niet_open", "speelde_niet" of "onbekend".
    """

    from core.result_validation import ToolResult

    if vensters_fn is None:
        vensters_fn = _vensters_van
    if stuur_fn is None:
        def stuur_fn(hwnd):
            import win32api

            win32api.PostMessage(hwnd, WM_APPCOMMAND, hwnd, APPCOMMAND_MEDIA_PLAY_PAUSE << 16)

    naam = str(app_name or "").strip() or "de app"
    try:
        vensters = vensters_fn(app_name)
    except Exception as fout:
        return ToolResult(ok=False, message=f"Kon {naam} niet bekijken: {fout}", error_kind="media_error")
    if not vensters:
        return ToolResult(ok=True, message=f"{naam} is niet open.",
                          data={"gepauzeerd": False, "reden": "niet_open"})
    speelt = _speelt(app_name, vensters)
    if speelt is None:
        return ToolResult(ok=False, message=f"Ik kan niet zien of {naam} speelt.",
                          error_kind="niet_ondersteund", data={"gepauzeerd": False, "reden": "onbekend"})
    if not speelt:
        return ToolResult(ok=True, message=f"{naam} speelde niet.",
                          data={"gepauzeerd": False, "reden": "speelde_niet"})
    try:
        stuur_fn(vensters[0][0])
    except Exception as fout:
        return ToolResult(ok=False, message=f"Kon {naam} niet pauzeren: {fout}", error_kind="media_error")
    if wacht:
        time.sleep(wacht)
    try:
        nog = _speelt(app_name, vensters_fn(app_name))
    except Exception:
        nog = False
    if nog:
        return ToolResult(ok=False, message=f"{naam} speelt nog.", error_kind="media_error",
                          data={"gepauzeerd": False, "reden": "speelt_nog"})
    return ToolResult(ok=True, message=f"{naam} staat op pauze.", data={"gepauzeerd": True})


# ---------------------------------------------------------------
# Een Spotify-link openen (Fase 21, M5: muziekvoorstel)
# ---------------------------------------------------------------
# Alleen "spotify:<soort>:<id>" (geen willekeurige links of bestanden).
# Spotify opent het nummer of de playlist; daarna kijkt JARVIS aan de
# venstertitel of er echt iets speelt, zodat hij eerlijk kan zeggen
# "speelt nu" of "staat klaar".

import re as _re

SPOTIFY_URI = _re.compile(r"^spotify:(track|album|playlist|artist):[A-Za-z0-9]{22}$")


def open_spotify(uri, opener=None, vensters_fn=None, wacht=4.0, stap=0.5):
    from core.result_validation import ToolResult

    uri = str(uri or "").strip()
    if not SPOTIFY_URI.match(uri):
        return ToolResult(ok=False, message="Dat is geen geldige Spotify-link.", error_kind="foute_waarde")
    if opener is None:
        import os

        opener = os.startfile
    if vensters_fn is None:
        vensters_fn = _vensters_van
    try:
        opener(uri)
    except Exception as fout:
        return ToolResult(ok=False, message=f"Kon Spotify niet openen: {fout}", error_kind="media_error")
    speelt = False
    gewacht = 0.0
    while True:
        try:
            speelt = bool(_speelt("Spotify", vensters_fn("Spotify")))
        except Exception:
            speelt = False
        if speelt or gewacht >= wacht:
            break
        time.sleep(stap)
        gewacht += stap
    return ToolResult(ok=True, message="Spotify speelt." if speelt else "Staat klaar in Spotify.",
                      data={"speelt": speelt})
