"""Automatische geluidsducking terwijl JARVIS praat (Fase 17, G).

Zodra JARVIS begint te praten wordt het systeemvolume van de pc tijdelijk
verlaagd, zodat muziek of een game niet door zijn antwoord heen klinkt.
Daarna gaat het volume automatisch terug naar de oude waarde.

Het is dus géén opdracht die u geeft, maar iets wat altijd gebeurt:

    muziek op 60%  →  JARVIS praat: 15%  →  JARVIS klaar: 60%

De module leest en schrijft het Windows-systeemvolume via
``actions.media`` (pycaw). Lukt dat niet, dan doet ducking niets en praat
JARVIS gewoon door — het mag nooit een fout opleveren.

Instellingen staan in ``config.py``: ``DUCKING_ENABLED``,
``DUCKING_PERCENT`` en ``DUCKING_MIN_PERCENT``.
"""

import logging
import threading

from config import DUCKING_ENABLED, DUCKING_MIN_PERCENT, DUCKING_PERCENT

logger = logging.getLogger(__name__)

_lock = threading.RLock()

#: Origineel volume (0-100) dat tijdens het praten geduckt is. None als er
#: op dit moment niet geduckt wordt.
_origineel = None

#: Laatst gezette volume, zodat we iets kunnen terugzetten als het opnieuw
#: lezen van het volume mislukt.
_laatst_gezet = None

#: Lopende ducking-thread (of None). Ducking gebeurt op de achtergrond, zodat
#: het ophalen van het systeemvolume het praten niet vertraagt.
_bezig = None


def is_geduckt():
    """Of het volume op dit moment geduckt is."""
    with _lock:
        return _origineel is not None


def _huidig_volume():
    """Leest het huidige systeemvolume (0-100), of None bij een fout."""
    try:
        from actions.media import get_volume

        return get_volume()
    except Exception:
        logger.debug("Kon het systeemvolume niet lezen", exc_info=True)
        return None


def _zet_volume(percent):
    """Zet het systeemvolume (0-100). Geeft True bij succes."""
    try:
        from actions.media import set_volume

        set_volume(percent)
        return True
    except Exception:
        logger.debug("Kon het systeemvolume niet instellen", exc_info=True)
        return False


def duck():
    """Verlaagt het systeemvolume zolang JARVIS praat.

    Doet dit op de achtergrond, zodat het lezen en zetten van het
    systeemvolume nooit het begin van het praten vertraagt.
    """
    if not DUCKING_ENABLED:
        return

    global _bezig

    with _lock:
        if _origineel is not None or _bezig is not None:
            return

    thread = threading.Thread(target=_duck_uitvoeren, name="jarvis-ducking", daemon=True)
    with _lock:
        if _bezig is not None:
            return
        _bezig = thread
    thread.start()


def _duck_uitvoeren():
    """De eigenlijke ducking (draait op de achtergrondthread)."""
    global _origineel, _laatst_gezet, _bezig

    try:
        huidig = _huidig_volume()
        if huidig is None:
            logger.debug("Ducking overgeslagen: volume niet leesbaar")
            return

        doel = max(int(DUCKING_MIN_PERCENT), int(huidig) - int(DUCKING_PERCENT))
        if doel >= huidig:
            # Stond het volume al laag genoeg, dan hoeft er niets te
            # veranderen — en dus ook niets te worden teruggezet.
            return

        if not _zet_volume(doel):
            return

        with _lock:
            _origineel = int(huidig)
            _laatst_gezet = doel
        logger.info("🔉 Geduckt: %s%% → %s%% (JARVIS praat).", huidig, doel)

    except Exception:
        logger.debug("Ducking mislukt", exc_info=True)

    finally:
        with _lock:
            _bezig = None


def herstel():
    """Zet het volume terug naar de waarde van vóór het praten."""
    global _origineel, _laatst_gezet

    with _lock:
        if _origineel is None:
            return

        terug = _origineel
        _origineel = None

        # Lees het volume opnieuw. Heeft u tijdens het praten zelf het
        # volume aangepast (iets anders dan de geduckte waarde), dan laten
        # we dat staan en draaien we onze eigen verlaging niet terug.
        huidig = _huidig_volume()
        if huidig is None:
            if _laatst_gezet is None:
                return
            huidig = _laatst_gezet

        if _laatst_gezet is not None and abs(int(huidig) - int(_laatst_gezet)) > 1:
            logger.info("🔊 Volume met de hand aangepast; ducking niet teruggedraaid.")
            _laatst_gezet = None
            return

        if _zet_volume(terug):
            logger.info("🔊 Volume teruggezet: %s%% → %s%%.", huidig, terug)
        _laatst_gezet = None


def reset():
    """Vergeet de ducking-staat (alleen voor tests)."""
    global _origineel, _laatst_gezet, _bezig

    with _lock:
        _origineel = None
        _laatst_gezet = None
        _bezig = None
