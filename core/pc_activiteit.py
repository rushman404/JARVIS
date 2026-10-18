"""Detectie van pc-activiteit (Fase 16B — dagtaken & zorg).

Bepaalt of de gebruiker de pc recent heeft gebruikt, op basis van de
laatste muis- of toetsenbordinvoer. Dit signaal gebruikt de proactieve
engine om te weten of JARVIS "wakker" moet blijven (iemand zit achter de
pc) of in de auto-slaap mag (niemand aanwezig).

Ontwerpregels
-------------
* **Nooit crashen.** Elke meting zit in een ``try/except``; lukt het niet,
  dan is het antwoord ``None`` ("onbekend").
* **Alleen Windows.** ``GetLastInputInfo`` bestaat alleen op Windows. Op
  andere systemen geeft :func:`idle_seconden` ``None`` terug.
* **Injecteerbaar.** :func:`is_actief` accepteert een eigen ``idle_fn``
  zodat tests geen echte invoer nodig hebben.
"""

import logging

from config import PC_IDLE_DREMPEL_SECONDEN

logger = logging.getLogger(__name__)


def idle_seconden():
    """Seconden sinds de laatste muis-/toetsenbordinvoer.

    Geeft ``None`` terug als het niet gemeten kan worden (geen Windows,
    of een fout bij het aanroepen van de systeem-API).
    """

    try:
        import ctypes
        from ctypes import wintypes

        if not hasattr(ctypes, "windll"):
            return None

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)

        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None

        millis = ctypes.windll.kernel32.GetTickCount()
        verstreken = (millis - info.dwTime) & 0xFFFFFFFF
        return verstreken / 1000.0
    except Exception:
        logger.debug("Kon de pc-inactiviteit niet meten.", exc_info=True)
        return None


def is_actief(drempel_seconden=None, idle_fn=None):
    """True als de pc recent is gebruikt.

    ``drempel_seconden`` is het aantal seconden inactiviteit waarbinnen de
    pc nog als "in gebruik" geldt (standaard uit de configuratie).
    Geeft ``None`` terug als de activiteit onbekend is.
    """

    if drempel_seconden is None:
        drempel_seconden = PC_IDLE_DREMPEL_SECONDEN

    if idle_fn is None:
        idle_fn = idle_seconden

    idle = idle_fn()
    if idle is None:
        return None

    try:
        return float(idle) < float(drempel_seconden)
    except (TypeError, ValueError):
        return None
