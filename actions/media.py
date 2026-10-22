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


def _get_volume_interface():
    """Haal de volume-interface op. Moet op de COM-thread draaien.

    Let op: deze functie wordt zelf al binnen run_on_com_thread uitgevoerd.
    Ze mag dus geen nieuwe run_on_com_thread aanroepen, want dan wacht de
    COM-thread op zichzelf (deadlock) en volgt na 10 seconden een timeout.
    """
    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()

    # Nieuwe pycaw (>= 2024-xx): GetSpeakers() geeft een AudioEndpoint met
    # een EndpointVolume-eigenschap.
    volume = getattr(device, "EndpointVolume", None)
    if volume is not None:
        return volume

    # Oudere pycaw (20240210): GetSpeakers() geeft een kale POINTER(IMMDevice).
    # Activeer IAudioEndpointVolume dan zelf.
    from ctypes import POINTER, cast

    from pycaw.pycaw import IAudioEndpointVolume

    interface = device.Activate(IAudioEndpointVolume._iid_, 0, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


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
