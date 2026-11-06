"""Barge-in (Fase 17, B1): JARVIS onderbreken terwijl hij praat.

Vier modi:

* **woord** (standaard sinds Fase 35B) — alleen **"JARVIS"** (het wake word)
  of **"stop"** onderbreekt hem. Gewone echo van zijn eigen stem telt niet:
  "stop" moet boven de echo uitkomen én als "stop" verstaan worden.
* **stem** — de microfoon hoort u praten terwijl JARVIS zelf praat. Omdat
  de eigen stem van JARVIS via de speakers ook in de microfoon terugkomt,
  leert de monitor eerst de echo-drempel (de eerste
  ``BARGE_IN_GRACE_SECONDS`` van het praten) en volgt die daarna de echo
  doorlopend (het lopend gemiddelde over ``BARGE_IN_ECHO_WINDOW_SECONDS``).
  Een onderbreking moet boven die lopende waarde uitkomen, zodat een
  luidere zinsdeel van JARVIS zichzelf niet onderbreekt.
* **sneltoets** — alleen de globale toets (standaard Ctrl+Alt+J); de
  microfoon wordt niet afgeluisterd.
* **uit** — geen onderbreking.

Bij een onderbreking zet de monitor het ``stop_event`` (waardoor
``speak_stream`` stopt) en roept :func:`voice.speak.stop_speaking` aan, zodat
de audio direct stopt. Daarna luistert JARVIS meteen verder naar uw opdracht.
"""

import logging
import re
import threading
import time

import numpy as np
import webrtcvad

from config import (
    BARGE_IN_ECHO_RATIO,
    BARGE_IN_ECHO_WINDOW_SECONDS,
    BARGE_IN_FRAMES,
    BARGE_IN_GRACE_SECONDS,
    BARGE_IN_HOTKEY,
    BARGE_IN_MIN_RMS,
    BARGE_IN_MODE,
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

# De modi van barge-in.
MODUS_WOORD = "woord"
MODUS_STEM = "stem"
MODUS_SNELTOETS = "sneltoets"
MODUS_UIT = "uit"
MODI = (MODUS_WOORD, MODUS_STEM, MODUS_SNELTOETS, MODUS_UIT)

# Waarom JARVIS onderbroken werd (``BargeInMonitor.reden``).
REDEN_JARVIS = "jarvis"
REDEN_STOP = "stop"
REDEN_SNELTOETS = "sneltoets"
REDEN_STEM = "stem"

# Modus "woord": zo lang mag een "stop" duren (in frames van 30 ms) en zoveel
# frames onder de drempel betekent dat het woord klaar is.
STOP_MIN_FRAMES = 5      # 0,15 s
STOP_MAX_FRAMES = 60     # 1,8 s
STOP_EINDE_FRAMES = 8    # 0,24 s

_STOP_WOORDEN = re.compile(
    r"^(?:(?:hey|hé|he)\s+)?(?:jarvis[,\s]+)?(?:stop|stoppen|stop\s+maar|stop\s+ermee|hou\s+op|houd\s+op|"
    r"stil|wees\s+stil|stil\s+maar|ophouden|genoeg|laat\s+maar)(?:[,\s]+jarvis)?$"
)


def is_stopwoord(tekst):
    """True als ``tekst`` een "stop" is ("stop", "hou op", "jarvis stop", …)."""

    t = " ".join(str(tekst or "").lower().replace(",", " ").strip(" .!?").split())
    return bool(t) and bool(_STOP_WOORDEN.match(t))

# De gekozen modus (alleen in het geheugen). None = de standaard uit config.
_modus = None


def huidige_modus():
    """De actieve modus van barge-in ("stem", "sneltoets" of "uit")."""
    if _modus is not None:
        return _modus
    return BARGE_IN_MODE


def zet_modus(modus):
    """Zet de modus van barge-in. Geeft de (nieuwe) modus terug."""
    global _modus
    if modus not in MODI:
        return huidige_modus()
    _modus = modus
    logger.info("Barge-in staat nu op '%s'.", modus)
    return modus

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
                 echo_ratio=None, grace_seconds=None, modus=None,
                 echo_window_seconds=None):
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
        self._modus = modus if modus is not None else huidige_modus()
        self._echo_window = (
            echo_window_seconds
            if echo_window_seconds is not None
            else BARGE_IN_ECHO_WINDOW_SECONDS
        )
        # Smoothing van het lopende gemiddelde: hoe groter het venster, hoe
        # rustiger de echo-drempel meebeweegt. Met het standaardvenster
        # (1,5 s) is dit ongeveer 0,04 per frame van 30 ms.
        self._alpha = min(
            1.0,
            max(
                0.01,
                2.0 * (FRAME_DURATION_MS / 1000.0) / max(0.1, float(self._echo_window)),
            ),
        )

        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self._barge_actief = False
        self._echo_floor = None
        #: Lopend gemiddelde van de eigen stem (de echo) tijdens het praten.
        self._echo_niveau = 0.0

        #: True zodra JARVIS is onderbroken.
        self.triggered = False
        #: Tijdstip waarop uw onderbreking begon (of None bij de sneltoets).
        #: Bij "JARVIS" is dat het einde van het wake word: wat u daarna zegt
        #: is de opdracht.
        self.trigger_ts = None
        #: Waarom (zie ``REDEN_*``); bij "stop" stopt de sessie.
        self.reden = None

    # ---------------- levensduur ----------------

    def start(self):
        """Start de monitor (de sneltoets wordt eenmalig geregistreerd)."""
        if self._running:
            return
        if self._modus == MODUS_UIT:
            logger.info("Barge-in staat uit; de monitor start niet.")
            return
        self._running = True
        _sneltoets_event.clear()
        _registreer_sneltoets(self._hotkey)
        if self._modus in (MODUS_WOORD, MODUS_STEM):
            # Meteen frames bewaren: tijdens het praten is de microfoon
            # gedempt, en zonder deze stand komt er dan niets meer binnen
            # (Fase 35B: daardoor werkte onderbreken met de stem nooit).
            self._zet_barge_in(True)
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

    def _activeer(self, trigger_ts=None, reden=None):
        """Onderbreekt JARVIS: stop_event + audio stopt meteen."""
        with self._lock:
            if self.triggered:
                return
            self.triggered = True
            self.trigger_ts = trigger_ts
            self.reden = reden or (REDEN_SNELTOETS if trigger_ts is None else REDEN_STEM)
        logger.info("Onderbroken (%s).", self.reden)
        if self._stop_event is not None:
            self._stop_event.set()
        try:
            speak_module.stop_speaking()
        except Exception:
            logger.exception("Kon het spreken niet onderbreken")

    # ---------------- de lus ----------------

    def _lus(self):
        """Verdeelt de monitor over de gekozen modus."""
        if self._modus == MODUS_SNELTOETS:
            self._lus_sneltoets()
            return
        if self._modus == MODUS_WOORD:
            self._lus_woord()
            return
        self._lus_stem()

    def _lus_sneltoets(self):
        """Wacht alleen op de sneltoets (de microfoon blijft ongemoeid)."""
        while self._running and not self.triggered:
            if _sneltoets_event.wait(timeout=0.1):
                _sneltoets_event.clear()
                self._activeer(None)
                return

    def _wake_model(self):
        try:
            from voice import wakeword

            model = wakeword.get_model()
            if model is not None:
                model.reset()
            return model, wakeword.DREMPEL
        except Exception:
            logger.debug("Geen wake word-model voor barge-in", exc_info=True)
            return None, None

    def _herken_kort(self, audio):
        """Wat er in een kort stukje audio gezegd werd (Whisper als die klaar is, anders Google)."""

        try:
            import taal
            from voice import whisper_stt

            if whisper_stt.motor() == "whisper" and whisper_stt.status()["stand"] == "klaar":
                try:
                    return whisper_stt.herken(audio, taal.spraak_code(), max_seconden=2.0)
                except whisper_stt.WhisperFout:
                    pass
            import speech_recognition as sr

            from voice import listen

            opname = listen._met_stilte_aanvullen(listen._normalize(audio))
            data = sr.AudioData(opname.tobytes(), SAMPLE_RATE, 2)
            return sr.Recognizer().recognize_google(data, language=taal.spraak_code())
        except Exception:
            logger.debug("Kort stukje niet verstaan", exc_info=True)
            return ""

    def _lus_woord(self):
        """Modus "woord": alleen "JARVIS" (wake word) of "stop" onderbreekt."""
        source = self._source_obj()
        if source is None:
            logger.warning("Barge-in zonder audiobron; de monitor stopt.")
            return

        model, wake_drempel = self._wake_model()
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
        wake_size = 1280
        pending = np.empty(0, dtype=np.int16)
        wake_pending = np.empty(0, dtype=np.int16)

        laatste_ts = source.latest_timestamp()
        if laatste_ts is None:
            laatste_ts = time.monotonic()

        echo_samples = []
        burst_start = None
        woord = []          # frames van een mogelijk "stop" (boven de echo)
        onder = 0           # frames onder de drempel sinds het laatste woordframe
        woord_eind_ts = None

        while self._running and not self.triggered:
            if _sneltoets_event.is_set():
                _sneltoets_event.clear()
                self._activeer(None, REDEN_SNELTOETS)
                break

            result = source.read_frame(after_ts=laatste_ts, timeout=0.1)
            if result is None:
                continue
            ts, block = result
            laatste_ts = ts
            blok = np.asarray(block, dtype=np.int16).reshape(-1)

            if not self._is_speaking():
                # Denken of stil: niets onderbreken; de echo vergeten.
                if burst_start is not None:
                    burst_start, echo_samples = None, []
                    self._echo_floor, self._echo_niveau = None, 0.0
                pending = np.empty(0, dtype=np.int16)
                wake_pending = np.empty(0, dtype=np.int16)
                woord, onder = [], 0
                continue
            if burst_start is None:
                burst_start = ts
                echo_samples = []

            # 1. "JARVIS": het wake word-model op de microfoon.
            if model is not None:
                wake_pending = np.concatenate([wake_pending, blok])
                while wake_pending.size >= wake_size:
                    stuk, wake_pending = wake_pending[:wake_size], wake_pending[wake_size:]
                    try:
                        scores = model.predict(stuk)
                    except Exception:
                        logger.debug("Wake word tijdens praten mislukt", exc_info=True)
                        model = None
                        break
                    if any(score > wake_drempel for score in scores.values()):
                        model.reset()
                        self._activeer(ts + blok.size / SAMPLE_RATE, REDEN_JARVIS)
                        return

            # 2. "stop": boven de echo uitkomen en als "stop" verstaan worden.
            pending = np.concatenate([pending, blok])
            index = 0
            while pending.size >= frame_size:
                frame, pending = pending[:frame_size], pending[frame_size:]
                kader_ts = ts + index * (FRAME_DURATION_MS / 1000.0)
                index += 1
                rms = _frame_rms(frame.tobytes())
                self._echo_niveau = self._echo_niveau * (1.0 - self._alpha) + rms * self._alpha
                if kader_ts - burst_start < self._grace:
                    echo_samples.append(rms)
                    continue
                if self._echo_floor is None and echo_samples:
                    self._echo_floor = max(echo_samples) or 1.0
                    self._echo_niveau = sum(echo_samples) / len(echo_samples)
                drempel = max(
                    float(self._min_rms),
                    (self._echo_floor or 0.0) * float(self._echo_ratio),
                    self._echo_niveau * float(self._echo_ratio),
                )
                if rms >= drempel and vad.is_speech(frame.tobytes(), SAMPLE_RATE):
                    woord.append(frame)
                    onder = 0
                    woord_eind_ts = kader_ts + FRAME_DURATION_MS / 1000.0
                    if len(woord) > STOP_MAX_FRAMES:
                        woord = []  # te lang voor "stop": iets anders
                    continue
                if woord:
                    woord.append(frame)
                    onder += 1
                    if onder >= STOP_EINDE_FRAMES:
                        stuk = np.concatenate(woord[:-onder] or woord)
                        lang = len(woord) - onder
                        woord, onder = [], 0
                        if STOP_MIN_FRAMES <= lang <= STOP_MAX_FRAMES and is_stopwoord(self._herken_kort(stuk)):
                            self._activeer(woord_eind_ts, REDEN_STOP)
                            return

    def _lus_stem(self):
        """Luistert tijdens het praten naar de stem van de gebruiker."""
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
                    # De leerperiode loopt in audi tijd (het tijdstip van de
                    # audio zelf), zodat die niet van de snelheid van de
                    # computer afhangt.
                    burst_start = ts
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

                # De echo doorlopend volgen: het lopend gemiddelde van de
                # recente eigen stem is de echo van dit moment.
                self._echo_niveau = (
                    self._echo_niveau * (1.0 - self._alpha)
                    + rms * self._alpha
                )

                # De eerste momenten van het praten: drempel leren.
                if burst_start is not None and (
                    kader_ts - burst_start
                ) < self._grace:
                    echo_samples.append(rms)
                    continue

                if self._echo_floor is None and echo_samples:
                    self._echo_floor = max(echo_samples) or 1.0
                    # Het lopend gemiddelde begint bij de geleerde echo.
                    self._echo_niveau = sum(echo_samples) / len(echo_samples)

                # Onderbreken mag alleen boven de echo uitkomen: boven de
                # minimale RMS, boven de geleerde echo én boven het lopend
                # gemiddelde. Zo onderbreekt een luidere zinsdeel van JARVIS
                # zichzelf niet.
                drempel = max(
                    float(self._min_rms),
                    (self._echo_floor or 0.0) * float(self._echo_ratio),
                    self._echo_niveau * float(self._echo_ratio),
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
                self._echo_niveau = 0.0
                burst_start = None
                echo_samples = []
                streak = 0
                streak_start = None
