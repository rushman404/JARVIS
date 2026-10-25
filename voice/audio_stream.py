"""Één gedeelde microfoonstroom voor wake word én opname.

Er staat tijdens de hele levensduur van JARVIS één sd.InputStream open
(16 kHz, mono, int16, blokken van 1280 samples). Een achtergrondthread
leest die blokken en bewaart ze met een tijdstempel in een thread-veilige
ringbuffer van ongeveer 3 seconden. Wake word en opname lezen allebei uit
dezelfde buffer, zodat er geen audio verloren gaat tussen het wake word en
het commando ("hey jarvis, zet de lamp aan" in één adem).

Tijdens het afspelen van de pieptoon of gesproken tekst wordt de bron
gedempt: die frames komen niet in de buffer, zodat JARVIS zichzelf niet
opneemt.

Fase 20 (M4): de iPad kan óók geluid leveren (``feed(..., extern=True)``,
zie ``voice/ipad_microfoon.py``). Zolang dat binnenkomt, slaat de bron de
frames van de pc-microfoon over, zodat er nooit twee microfoons door elkaar
lopen. Met ``lokaal=False`` (``MIC_BRON=ipad``) wordt de pc-microfoon niet
eens geopend.
"""

import logging
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import MIC_DEVICE

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
BLOCK_SIZE = 1280        # 80 ms bij 16 kHz
BUFFER_SECONDS = 3.0

# Eén gedeelde bron voor het hele programma (via get/set_audio_source).
_audio_source = None


def get_audio_source():
    """Geeft de gedeelde AudioSource, of None als die nog niet bestaat."""
    return _audio_source


def set_audio_source(source):
    """Zet de gedeelde AudioSource (aangeroepen door main.py)."""
    global _audio_source
    _audio_source = source


class AudioSource:
    """Thread-veilige, continu open microfoonstroom met ringbuffer."""

    def __init__(self, device=MIC_DEVICE, samplerate=SAMPLE_RATE,
                 channels=CHANNELS, dtype=DTYPE, blocksize=BLOCK_SIZE,
                 buffer_seconds=BUFFER_SECONDS, lokaal=True):
        self.device = device
        self.lokaal = lokaal
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self._maxlen = max(1, int(buffer_seconds * samplerate / blocksize))

        self._frames = deque(maxlen=self._maxlen)   # (tijdstip, frame)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        self._stream = None
        self._thread = None
        self._running = False
        self._muted = False
        self._mute_count = 0
        self._barge_in = False      # barge-in: frames ook tijdens praten bewaren
        self._error_reported = False
        self._cursor = None          # tijdstip tot waar audio verwerkt is
        self._extern_tot = 0.0       # tot wanneer de iPad levert (monotonic)

    # ---------------- levensduur ----------------

    def start(self):
        """Opent de stream en start de lees-thread (eenmalig)."""
        with self._lock:
            if self._running:
                return
            self._running = True
        if not self.lokaal:
            # Alleen geluid van buiten (de iPad): geen pc-microfoon openen.
            logger.info("Microfoon: alleen de iPad (MIC_BRON=ipad).")
            return
        try:
            self._open_stream()
        except Exception as e:
            self._report_error(f"⚠️ Kon de microfoon niet openen: {e}")
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self):
        """Sluit de stream en stopt de lees-thread netjes (idempotent)."""
        with self._lock:
            self._running = False
            stream = self._stream
            self._stream = None
            self._cond.notify_all()

        if self._thread is not None:
            self._thread.join(timeout=2.0)

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _open_stream(self):
        stream = sd.InputStream(
            device=self.device,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=self.blocksize,
        )
        stream.start()
        with self._lock:
            self._stream = stream
        self._error_reported = False

    # ---------------- lees-thread ----------------

    def _reader(self):
        while True:
            with self._lock:
                if not self._running:
                    break
                stream = self._stream

            if stream is None:
                self._reopen()
                continue

            try:
                block, _ = stream.read(self.blocksize)
            except Exception:
                self._handle_stream_error()
                continue

            if block is None:
                continue

            # Levert de iPad op dit moment geluid, dan de pc-microfoon even
            # overslaan (MIC_BRON=auto): nooit twee microfoons door elkaar.
            if time.monotonic() < self._extern_tot:
                continue

            self.feed(block)

    def _reopen(self):
        try:
            self._open_stream()
        except Exception as e:
            self._report_error(f"⚠️ Kon de microfoon niet openen: {e}")
            time.sleep(0.5)

    def _handle_stream_error(self):
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        self._report_error("⚠️ Microfoon viel weg. Ik probeer opnieuw verbinding te maken.")

    def _report_error(self, message):
        if not self._error_reported:
            logger.warning(message)
            self._error_reported = True

    # ---------------- buffer ----------------

    def feed(self, frame, ts=None, extern=False):
        """Zet één frame in de ringbuffer (gedempt = niet opslaan).

        In barge-in-modus worden frames ook tijdens het praten bewaard, zodat
        de monitor u kan horen onderbreken (zie :meth:`set_barge_in`).

        ``extern=True``: het frame komt van de iPad (Fase 20). Tijdens het
        praten wordt dat altijd weggegooid, ook in barge-in-modus: de
        barge-in-monitor vergelijkt met de eigen speaker en zou JARVIS via de
        iPad-microfoon voor een onderbreking aanzien.
        """
        array = np.asarray(frame, dtype=self.dtype).reshape(-1).copy()
        if array.size == 0:
            return
        stamp = time.monotonic() if ts is None else ts
        with self._cond:
            if self._muted and (extern or not self._barge_in):
                return
            self._frames.append((stamp, array))
            self._cond.notify_all()

    def _first_after(self, after_ts):
        for stamp, frame in self._frames:
            if after_ts is None or stamp > after_ts:
                return stamp, frame
        return None

    def read_frame(self, after_ts=None, timeout=None):
        """Geeft de oudste (tijdstip, frame) met tijdstip > after_ts.

        Blokkeert tot zo'n frame bestaat of tot de timeout. Verbruikt
        niets: de ringbuffer blijft voor andere lezers intact.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                found = self._first_after(after_ts)
                if found is not None:
                    return found
                if not self._running:
                    return None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._cond.wait(remaining)
                else:
                    self._cond.wait(0.25)

    def markeer_extern(self, seconden=1.0):
        """De iPad levert geluid: de pc-microfoon zo lang overslaan."""
        with self._lock:
            self._extern_tot = max(self._extern_tot, time.monotonic() + seconden)

    def extern_actief(self):
        """True zolang er (recent) geluid van de iPad binnenkomt."""
        with self._lock:
            return time.monotonic() < self._extern_tot

    def latest_timestamp(self):
        """Tijdstip van het nieuwste frame, of None als de buffer leeg is."""
        with self._lock:
            if self._frames:
                return self._frames[-1][0]
            return None

    def advance_cursor(self, ts):
        """Schuift de lees-cursor op naar ts (gaat nooit terug).

        De cursor houdt bij tot welk tijdstip audio al verwerkt is, zodat
        een volgende opname niet dezelfde audio opnieuw inleest.
        """
        if ts is None:
            return
        with self._lock:
            if self._cursor is None or ts > self._cursor:
                self._cursor = ts

    def get_cursor(self):
        """Tijdstip tot waar audio verwerkt is, of None."""
        with self._lock:
            return self._cursor

    def reset_cursor(self, ts=None):
        """Zet de lees-cursor (bijv. naar het wake-word-detectiemoment)."""
        with self._lock:
            self._cursor = ts

    def clear(self):
        """Gooit alle gebufferde frames weg."""
        with self._lock:
            self._frames.clear()

    # ---------------- dempen ----------------

    def mute(self):
        """Frames komen niet in de buffer (tijdens pieptoon/spraak)."""
        with self._lock:
            self._mute_count += 1
            self._muted = self._mute_count > 0

    def unmute(self):
        with self._lock:
            if self._mute_count > 0:
                self._mute_count -= 1
            self._muted = self._mute_count > 0

    def is_muted(self):
        with self._lock:
            return self._muted

    # ---------------- barge-in ----------------

    def set_barge_in(self, active):
        """Zet de bron in barge-in-modus.

        In deze modus worden frames óók bewaard terwijl de microfoon gedempt
        is (tijdens het praten), zodat de barge-in-monitor kan horen of u
        JARVIS onderbreekt (Fase 17, B1). Standaard uit.
        """
        with self._cond:
            self._barge_in = bool(active)
            self._cond.notify_all()

    def is_barge_in(self):
        with self._lock:
            return self._barge_in

    def is_running(self):
        """Of de lees-thread/stream actief is.

        Zodra de bron gestopt is, kan er nooit meer audio bij komen; lezers
        (zoals het wake word) stoppen dan direct in plaats van te blijven
        wachten.
        """
        with self._lock:
            return self._running
