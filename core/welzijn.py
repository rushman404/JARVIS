"""Welzijn (Fase 27, M3): water, ogen en pauze, hooguit één melding per uur.

Naast het eten en de late-avond-nudge (Fase 16B) houdt JARVIS bij hoe lang
u achter de pc zit:

* **water** na een uur,
* **ogen** na 45 minuten (20-20-20: twintig seconden in de verte kijken),
* **pauze** na anderhalf uur aaneengesloten (dit vervangt de oude
  pauze-regel uit ``config/proactive_rules.json``).

Besluiten 2026-10-30: kort gesproken, **hooguit één welzijnsmelding per
uur** (is er meer tegelijk aan de beurt, dan in één zin), alleen als u
achter de pc zit, en niet in een potje (volledig scherm), de focus- of
film-modus, de stille modus of 's nachts.

Wat telt als "achter de pc": muis of toetsenbord in de laatste vijf minuten
(``core.pc_activiteit``). Bent u tien minuten weg, dan telt dat als pauze
(ook voor de ogen); na een half uur weg begint alles opnieuw.
"""

import logging
import threading
import time

logger = logging.getLogger("jarvis.welzijn")

WATER_MINUTEN = 60
OGEN_MINUTEN = 45
PAUZE_MINUTEN = 90
RUST_MINUTEN = 60          # hooguit één welzijnsmelding per uur
AANWEZIG_SECONDEN = 300    # invoer in de laatste 5 minuten = achter de pc
KORTE_PAUZE = 10 * 60      # zo lang weg = pauze genomen (ook de ogen)
LANG_WEG = 30 * 60         # zo lang weg = alles begint opnieuw

ZIN_WATER = "Tijd voor een slok water, sir."
ZIN_OGEN = "Kijk even twintig seconden in de verte, sir; dat is goed voor uw ogen."
ZIN_WATER_OGEN = "Tijd voor een slok water, en kijk even twintig seconden in de verte, sir."
ZIN_PAUZE = ("U zit al anderhalf uur achter de pc, sir. Tijd voor een korte pauze: "
             "wat drinken en even weg van het scherm.")


def _std_idle():
    from core import pc_activiteit

    return pc_activiteit.idle_seconden()


def _std_stil():
    """True als JARVIS nu niets over welzijn moet zeggen."""

    from core import filmmodus, focusmodus, proactive

    if proactive.is_nachtmodus() or proactive.is_quiet():
        return True
    if filmmodus.lees_toestand() is not None or focusmodus.is_aan():
        return True
    return _in_een_potje()


def _in_een_potje():
    """Volledig scherm op deze pc of (laatst gezien) op de game-pc."""

    try:
        from actions.discord_meldingen import _volledig_scherm

        if _volledig_scherm():
            return True
    except Exception:
        logger.debug("Volledig scherm lokaal controleren mislukt.", exc_info=True)
    try:
        from core import discord_dms

        return discord_dms.game_pc_volledig_scherm()
    except Exception:
        return False


class WelzijnPlanner:
    def __init__(self, meld_fn=None, klok=time.monotonic, idle_fn=None, stil_fn=None, interval=60):
        self.meld_fn = meld_fn
        self.klok = klok
        self.idle_fn = idle_fn or _std_idle
        self.stil_fn = stil_fn or _std_stil
        self.interval = interval
        self._vorige = None
        self.water = 0.0          # actieve minuten sinds de laatste water-melding
        self.ogen = 0.0
        self.pauze = 0.0          # aaneengesloten actieve minuten
        self.laatste_melding = None
        self._stop = threading.Event()
        self._thread = None

    def _bijwerken(self, nu):
        """Tellers bijwerken met de tijd sinds de vorige stap."""

        verstreken = 0.0 if self._vorige is None else max(0.0, nu - self._vorige)
        self._vorige = nu
        idle = self.idle_fn()
        if idle is None:
            return False  # niet te meten: dan zeggen we niets
        if idle >= LANG_WEG:
            self.water = self.ogen = self.pauze = 0.0
            return False
        if idle >= KORTE_PAUZE:
            self.ogen = self.pauze = 0.0
            return False
        if idle >= AANWEZIG_SECONDEN:
            return False
        minuten = verstreken / 60.0
        self.water += minuten
        self.ogen += minuten
        self.pauze += minuten
        return True

    def tekst(self):
        """De zin voor wat nu aan de beurt is (of None), en zet die tellers terug."""

        if self.pauze >= PAUZE_MINUTEN:
            # De pauze omvat water en ogen: één zin, alles terug.
            self.water = self.ogen = self.pauze = 0.0
            return ZIN_PAUZE
        water = self.water >= WATER_MINUTEN
        ogen = self.ogen >= OGEN_MINUTEN
        if water and ogen:
            self.water = self.ogen = 0.0
            return ZIN_WATER_OGEN
        if water:
            self.water = 0.0
            return ZIN_WATER
        if ogen:
            self.ogen = 0.0
            return ZIN_OGEN
        return None

    def stap(self):
        """Eén controle; geeft de verstuurde zin terug (of None)."""

        nu = self.klok()
        aanwezig = self._bijwerken(nu)
        if not aanwezig:
            return None
        if self.laatste_melding is not None and nu - self.laatste_melding < RUST_MINUTEN * 60:
            return None
        if self.stil_fn():
            return None
        zin = self.tekst()
        if zin is None:
            return None
        self.laatste_melding = nu
        if self.meld_fn is not None:
            try:
                self.meld_fn(zin, bron="welzijn")
            except Exception:
                logger.debug("Kon de welzijnsmelding niet versturen.", exc_info=True)
        return zin

    def _lus(self):
        while not self._stop.wait(self.interval):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout in de welzijnsplanner.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-welzijn", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
