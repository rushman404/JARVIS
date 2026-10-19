"""Barge-in (Fase 17, B1): JARVIS onderbreken terwijl hij praat.

Twee triggers werken samen:

* **Stem** — de microfoon hoort u praten terwijl JARVIS zelf praat. Omdat
  de eigen stem van JARVIS via de speakers ook in de microfoon terugkomt,
  leert de monitor eerst de echo-drempel (de eerste
  ``BARGE_IN_GRACE_SECONDS`` van het praten) en reageert pas als de
  microfoon daar duidelijk bovenuit komt (``BARGE_IN_MIN_RMS`` en
  ``BARGE_IN_ECHO_RATIO``).
* **Sneltoets** — een globale toets (standaard Ctrl+Alt+J) werkt altijd,
  ook als een game of video focus heeft.

Bij een onderbreking zet de monitor het ``stop_event`` (waardoor
``speak_stream`` stopt) en roept :func:`voice.speak.stop_speaking` aan, zodat
de audio direct stopt. Daarna luistert JARVIS meteen verder naar uw opdracht.
"""

import logging
import threading
import time

import numpy as np
import webrtcvad

from config import (
    BARGE_IN_ECHO_RATIO,
    BARGE_IN_FRAMES,
    BARGE_IN_GRACE_SECONDS,
    BARGE_IN_HOTKEY,
    BARGE_IN_MIN_RMS,
)
from voice import speak as speak_module
from voice.audio_stream import get_audio_source

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
VAD_AGGRESSIVENESS = 3

# Zoveel seconden stilte betekent het einde van een spreek-burst: de echo-
# drempel wordt dan vergeten (een volgend antwoord leert een nieuwe drempel).
BURST_EINDE_SECONDEN = 0.6

# Globale sneltoets: eenmalig registreren, daarna alleen een vlag zetten.
_sneltoets_event = threading.Event()
_sneltoets_geregistreerd = False


def _registreer_sneltoets(hotkey):
    """Registreert eenmalig de globale barge-in-sneltoets."""
    global _sneltoets_geregistreerd
    if _sneltoets_geregistreerd:
        return
    _sneltoets_geregistreerd = True
    try:
        import keyboard

        keyboard.add_hotkey(hotkey, _sneltoets_event.set)
        logger.info("Barge-in-sneltoets actief: %s", hotkey)
    except Exception as e:
        logger.warning("Kon de barge-in-sneltoets niet registreren: %s", e)


def _frame_rms(frame_bytes):
    samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


class BargeInMonitor:
    """Let tijdens het praten op een onderbreking (stem of sneltoets).

    ``stop_event`` (optioneel) wordt bij een onderbreking gezet en hoort
    hetzelfde event te zijn als waarmee ``speak_stream`` is gestart.
    """

    def __init__(self, stop_event=None, source=None, hotkey=None,
                 is_speaking=None, frames_needed=None, min_rms=None,
                 echo_ratio=None, grace_seconds=None):
        self._stop_event = stop_event
        self._source = source
        self._hotkey = hotkey if hotkey is not None else BARGE_IN_HOTKEY
        self._is_speaking = (
            is_speaking if is_speaking is not None else speak_module.is_speaking
        )
        self._frames_needed = (
            frames_needed if frames_needed is not None else BARGE_IN_FRAMES
        )
        self._min_rms = min_rms if min_rms is not None else BARGE_IN_MIN_RMS
        self._echo_ratio = (
            echo_ratio if echo_ratio is not None else BARGE_IN_ECHO_RATIO
        )
        self._grace = (
            grace_seconds if grace_seconds is not None else BARGE_IN_GRACE_SECONDS
        )

        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self._barge_actief = False
        self._echo_floor = None

        #: True zodra JARVIS is onderbroken.
        self.triggered = False
        #: Tijdstip waarop uw onderbreking begon (of None bij de sneltoets).
        self.trigger_ts = None

    # ---------------- levensduur ----------------

    def start(self):
        """Start de monitor (de sneltoets wordt eenmalig geregistreerd)."""
        if self._running:
            return
        self._running = True
        _sneltoets_event.clear()
        _registreer_sneltoets(self._hotkey)
        self._thread = threading.Thread(
            target=self._lus, name="jarvis-barge-in", daemon=True
        )
        self._thread.start()

    def stop(self):
        """Stopt de monitor en zet de bron terug in normale stand (idempotent)."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._barge_actief:
            self._zet_barge_in(False)

    # ---------------- hulpmiddelen ----------------

    def _source_obj(self):
        if self._source is not None:
            return self._source
        return get_audio_source()

    def _zet_barge_in(self, actief):
        """Zet de bron in/uit barge-in-modus (frames tijdens praten bewaren)."""
        self._barge_actief = actief
        source = self._source_obj()
        if source is None:
            return
        try:
            source.set_barge_in(actief)
        except Exception:
            logger.exception("Kon de barge-in-modus niet instellen")
        if not actief:
            # De frames van tijdens het praten (echo van JARVIS' eigen stem)
            # mogen nooit als commando worden opgenomen.
            ts = source.latest_timestamp()
            if ts is not None:
                source.advance_cursor(ts)

    def _activeer(self, trigger_ts=None):
        """Onderbreekt JARVIS: stop_event + audio stopt meteen."""
        with self._lock:
            if self.triggered:
                return
            self.triggered = True
            self.trigger_ts = trigger_ts
        if self._stop_event is not None:
            self._stop_event.set()
        try:
            speak_module.stop_speaking()
        except Exception:
            logger.exception("Kon het spreken niet onderbreken")

    # ---------------- de lus ----------------

    def _lus(self):
        source = self._source_obj()
        if source is None:
            logger.warning("Barge-in zonder audiobron; de monitor stopt.")
            return

        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
        pending = np.empty(0, dtype=np.int16)

        laatste_ts = source.latest_timestamp()
        if laatste_ts is None:
            laatste_ts = time.monotonic()

        streak = 0
        streak_start = None
        echo_samples = []
        burst_start = None
        laatste_spraak = 0.0

        while self._running and not self.triggered:
            if _sneltoets_event.is_set():
                _sneltoets_event.clear()
                self._activeer(None)
                break

            result = source.read_frame(after_ts=laatste_ts, timeout=0.1)
            if result is None:
                continue

            ts, block = result
            laatste_ts = ts

            spreekt = bool(self._is_speaking())
            if spreekt != self._barge_actief:
                self._zet_barge_in(spreekt)

            if spreekt:
                laatste_spraak = time.monotonic()
                if burst_start is None:
                    burst_start = laatste_spraak
                    echo_samples = []

            pending = np.concatenate(
                [pending, np.asarray(block, dtype=np.int16).reshape(-1)]
            )

            index = 0
            while pending.size >= frame_size:
                frame = pending[:frame_size]
                pending = pending[frame_size:]
                kader_ts = ts + index * (FRAME_DURATION_MS / 1000.0)
                index += 1

                if not spreekt:
                    streak = 0
                    streak_start = None
                    continue

                rms = _frame_rms(frame.tobytes())
                nu = time.monotonic()

                # De eerste momenten van het praten: drempel leren.
                if burst_start is not None and (nu - burst_start) < self._grace:
                    echo_samples.append(rms)
                    continue

                if self._echo_floor is None and echo_samples:
                    self._echo_floor = max(echo_samples) or 1.0

                drempel = max(
                    float(self._min_rms),
                    (self._echo_floor or 0.0) * float(self._echo_ratio),
                )

                if rms >= drempel and vad.is_speech(frame.tobytes(), SAMPLE_RATE):
                    if streak == 0:
                        streak_start = kader_ts
                    streak += 1
                    if streak >= self._frames_needed:
                        self._activeer(streak_start)
                        break
                else:
                    streak = 0
                    streak_start = None

            if self.triggered:
                break

            # Einde van een spreek-burst: echo-drempel vergeten en opruimen.
            if (self._barge_actief and not spreekt
                    and (time.monotonic() - laatste_spraak) > BURST_EINDE_SECONDEN):
                self._zet_barge_in(False)
                self._echo_floor = None
                burst_start = None
                echo_samples = []
                streak = 0
                streak_start = None
