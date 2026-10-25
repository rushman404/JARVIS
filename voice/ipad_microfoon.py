"""De iPad als microfoon (Fase 20, M4).

Het spraakpaneel (``spraak.html`` in Safari) stuurt via een WebSocket
voortdurend 16 kHz-geluid (mono, int16) naar het brein. Deze module maakt
daar frames van 80 ms van (1280 samples, zoals de pc-microfoon) en zet die
in de gedeelde :class:`voice.audio_stream.AudioSource`. Het wake word en
het luisteren merken geen verschil.

* **Eén iPad tegelijk.** Een nieuwe verbinding vervangt de oude; frames van
  een oude sessie worden genegeerd (zie :meth:`IpadMicrofoon.nieuwe_sessie`).
* **Nooit twee microfoons door elkaar.** Zolang de iPad levert, slaat de
  bron de pc-microfoon over (``markeer_extern``).
* **Tijdstippen.** De stukjes komen soms in groepjes binnen; elk frame krijgt
  daarom een eigen, oplopend tijdstip (80 ms na het vorige), zodat de
  volgorde altijd klopt.
* **Niets bewaard.** Het geluid gaat alleen de ringbuffer van ~3 s in, net
  als bij de pc-microfoon.
"""

import logging
import secrets
import threading
import time

import numpy as np

logger = logging.getLogger("jarvis.ipad_microfoon")

RATE = 16000
FRAME = 1280                 # 80 ms
FRAME_SECONDEN = FRAME / RATE
MAX_STUK_BYTES = RATE * 2    # hoogstens 1 s per bericht
EXTERN_NAGLOEI = 1.0         # zo lang na het laatste stukje telt de iPad als actief


class IpadMicrofoon:
    """Ontvangt het iPad-geluid en zet het in de gedeelde audiobron."""

    def __init__(self, bron_fn=None, klok=time.monotonic):
        if bron_fn is None:
            from voice.audio_stream import get_audio_source as bron_fn
        self.bron_fn = bron_fn
        self.klok = klok
        self._lock = threading.Lock()
        self._sessie = None
        self._rest = np.empty(0, dtype=np.int16)
        self._volgende_ts = None
        self._laatste_ontvangst = None
        self.frames = 0

    # ----- sessies -----

    def nieuwe_sessie(self):
        """Een nieuwe iPad-verbinding; een eventuele oude telt niet meer."""

        with self._lock:
            self._sessie = secrets.token_hex(8)
            self._rest = np.empty(0, dtype=np.int16)
            self._volgende_ts = None
            logger.info("iPad-microfoon verbonden.")
            return self._sessie

    def sluit(self, sessie):
        with self._lock:
            if sessie == self._sessie:
                self._sessie = None
                self._rest = np.empty(0, dtype=np.int16)
                logger.info("iPad-microfoon verbroken.")

    def is_huidig(self, sessie):
        with self._lock:
            return sessie is not None and sessie == self._sessie

    def verbonden(self):
        """True als er een iPad verbonden is én recent geluid stuurde."""

        with self._lock:
            if self._sessie is None or self._laatste_ontvangst is None:
                return False
            return self.klok() - self._laatste_ontvangst < EXTERN_NAGLOEI * 3

    # ----- geluid -----

    def verwerk(self, sessie, data):
        """Eén stuk geluid (bytes, int16 mono 16 kHz). False = sessie stoppen."""

        if not isinstance(data, (bytes, bytearray)) or len(data) % 2 or len(data) > MAX_STUK_BYTES:
            return False
        with self._lock:
            if sessie is None or sessie != self._sessie:
                return False  # vervangen door een nieuwere iPad-verbinding
            bron = self.bron_fn()
            nu = self.klok()
            self._laatste_ontvangst = nu
            if bron is None:
                return True
            samples = np.frombuffer(bytes(data), dtype=np.int16)
            self._rest = np.concatenate([self._rest, samples])
            aantal = self._rest.size // FRAME
            if not aantal:
                return True

            # Tijdstip van het eerste nieuwe frame: aansluitend op het vorige,
            # nooit vóór wat er al in de buffer staat en nooit ver vooruit.
            begin = nu - aantal * FRAME_SECONDEN
            ts = begin if self._volgende_ts is None else max(self._volgende_ts, begin)
            if ts > nu + 2.0:
                ts = begin
            laatste = bron.latest_timestamp()
            if laatste is not None and ts <= laatste:
                ts = laatste + 0.001

            bron.markeer_extern(EXTERN_NAGLOEI)
            for i in range(aantal):
                bron.feed(self._rest[i * FRAME:(i + 1) * FRAME], ts=ts, extern=True)
                ts += FRAME_SECONDEN
            self._volgende_ts = ts
            self._rest = self._rest[aantal * FRAME:]
            self.frames += aantal
        return True


_ipad = None
_ipad_lock = threading.Lock()


def get_ipad_microfoon():
    """De gedeelde iPad-microfoon (lazy)."""

    global _ipad
    with _ipad_lock:
        if _ipad is None:
            _ipad = IpadMicrofoon()
        return _ipad
