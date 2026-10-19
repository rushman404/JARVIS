import numpy as np
import speech_recognition as sr
import webrtcvad
import io
import logging
import wave
import time
import collections
import status
from config import WACHT_OP_SPRAAK_SECONDEN, MAX_OPNAME_SECONDEN
from voice.audio_stream import AudioSource, get_audio_source

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
SILENCE_DURATION = 0.8
# - VAD_AGGRESSIVENESS 3 voor STARTEN: alleen duidelijke spraak start een
#   opname. Achtergrondgeluid (ruis, geklets, tv) triggert veel minder vaak.
#   "ja"/"nee" wordt nog steeds gehoord: dat was in de oorspronkelijke
#   setup met niveau 3 óók het geval (toen faalde alleen de herkenning,
#   en die is inmiddels gefixt met normalisatie + retry).
# - VAD_STOP_AGGRESSIVENESS 3 voor STOPPEN: alleen duidelijke spraak houdt
#   de opname open, achtergrondgeluid niet.
VAD_AGGRESSIVENESS = 3
VAD_STOP_AGGRESSIVENESS = 3

# Energiedrempel voor het STOPPEN: een frame houdt de opname alleen open
# als het VAD-stopoor spraak hoort ÉN de energie hoog genoeg is.
MIN_END_RMS = 400            # minimale energie om als "spraak" te tellen tijdens opname
SPEECH_RMS_RATIO = 1.8       # spraak moet tijdens opname ook boven de ruisvloer blijven
NOISE_FLOOR_DECAY = 0.1      # hoe snel de ruisvloer meebeweegt
NOISE_FLOOR_CAP = 400        # ruisvloer niet hoger laten worden dan dit

# hoeveel opeenvolgende speech-frames nodig zijn om "start" te bevestigen
SPEECH_FRAMES_TO_START = 4   # 4 x 30ms = 120ms aaneengesloten spraak

# meer context vóór de spraak vastleggen (onzichtbaar commentaar)
PRE_BUFFER_FRAMES = 15


def _normalize(recording):

    # Korte of zachte uitspraak ("ja", "nee") versterken, zodat de
    # spraakherkenning het wél herkent in plaats van "niet verstaan".
    audio = recording.astype(np.float32)

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0

    if peak <= 0:
        return audio.astype(np.int16)

    gain = min(32767.0 / peak, 4.0)

    audio *= gain

    return np.clip(audio, -32768, 32767).astype(np.int16)


def _frame_rms(frame_bytes):

    samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)

    if samples.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(samples ** 2)))


def _capture(start_ts=None, audio_source=None, wacht_seconden=None):
    """Neemt op vanaf start_ts uit de gedeelde AudioSource.

    start_ts is het tijdstip van de wake-word-detectie: alleen frames NA
    dat moment komen in de opname, dus nooit het wake word zelf. Frames
    die tijdens de pieptoon of gesproken tekst binnenkomen zijn al door de
    AudioSource weggegooid en zitten dus niet in de buffer.

    wacht_seconden vervangt de standaard wachttijd op spraak
    (``WACHT_OP_SPRAAK_SECONDEN``); de sessie-modus gebruikt hier een veel
    langere tijd (Fase 17, B2).
    """

    own_source = False
    source = audio_source if audio_source is not None else get_audio_source()
    if source is None:
        # Geen gedeelde bron (bijv. los script): open er tijdelijk één.
        source = AudioSource()
        own_source = True
        try:
            source.start()
        except Exception:
            return None

    try:
        return _capture_from_source(source, start_ts, wacht_seconden=wacht_seconden)
    finally:
        if own_source:
            source.stop()


def _capture_from_source(source, start_ts, wacht_seconden=None):

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    vad_stop = webrtcvad.Vad(VAD_STOP_AGGRESSIVENESS)

    frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
    silence_frames_needed = int(SILENCE_DURATION / (FRAME_DURATION_MS / 1000))

    # Hoe lang wachten we op het begin van spraak? Standaard de korte
    # wachttijd; in sessie-modus een veel langere (Fase 17, B2).
    wacht = (
        WACHT_OP_SPRAAK_SECONDEN
        if wacht_seconden is None
        else max(0.0, float(wacht_seconden))
    )

    status.luistert()

    frames = []
    started_talking = False
    silence_count = 0
    speech_streak = 0          # teller voor opeenvolgende speech-frames
    wait_start_time = time.time()
    speech_start_time = None
    noise_floor = None         # meebewegende ruisvloer

    pre_buffer = collections.deque(maxlen=PRE_BUFFER_FRAMES)

    # De AudioSource levert blokken van 1280 samples (80 ms); we knippen die
    # in stukjes van 30 ms voor webrtcvad.
    pending = np.empty(0, dtype=np.int16)

    # Zonder expliciet startpunt beginnen we waar de vorige opname stopte,
    # zodat al verwerkte audio nooit opnieuw wordt ingelezen (geen replay).
    if start_ts is None:
        start_ts = source.get_cursor()

    last_ts = start_ts
    stop = False

    while not stop:
        result = source.read_frame(after_ts=last_ts, timeout=0.25)

        if result is None:
            # Geen nieuwe audio (bron niet actief of nog niets binnen).
            if not started_talking and time.time() - wait_start_time > wacht:
                logger.info("💤 JARVIS gaat weer slapen.")
                return None
            if started_talking and speech_start_time is not None and \
                    time.time() - speech_start_time > MAX_OPNAME_SECONDEN:
                logger.info("⏱️ Max opnametijd bereikt.")
                break
            continue

        ts, block = result
        last_ts = ts
        source.advance_cursor(ts)

        pending = np.concatenate(
            [pending, np.asarray(block, dtype=np.int16).reshape(-1)]
        )

        while pending.size >= frame_size:
            frame = pending[:frame_size].copy()
            pending = pending[frame_size:]

            frame_bytes = frame.tobytes()

            # Energie van dit frame meten
            rms = _frame_rms(frame_bytes)

            if noise_floor is None:
                noise_floor = min(rms, NOISE_FLOOR_CAP)

            # Start-oor: alleen duidelijke spraak (VAD-niveau 3) start de
            # opname. Geen extra energiedrempel: die kan een stille maar
            # echte "ja"/"nee" blokkeren.
            is_start_speech = vad.is_speech(frame_bytes, SAMPLE_RATE)
            is_stop_speech = vad_stop.is_speech(frame_bytes, SAMPLE_RATE)

            is_active_speech = is_stop_speech and rms >= max(
                MIN_END_RMS,
                noise_floor * SPEECH_RMS_RATIO
            )

            can_start = is_start_speech

            # Ruisvloer alleen bijstellen op écht stille frames. Zo trekt harde
            # spraak (of een kort woord) de vloer niet omhoog en blokkeert het
            # de eigen start nét niet meer.
            if not (is_start_speech or is_stop_speech):
                noise_floor = min(
                    noise_floor + NOISE_FLOOR_DECAY * (rms - noise_floor),
                    NOISE_FLOOR_CAP
                )

            if not started_talking:
                pre_buffer.append(frame.copy())

                if can_start:
                    speech_streak += 1
                else:
                    speech_streak = 0

                if speech_streak >= SPEECH_FRAMES_TO_START:
                    logger.info("🎤 Spraak gedetecteerd...")
                    started_talking = True
                    speech_start_time = time.time()
                    frames.extend(pre_buffer)
                    frames.append(frame.copy())
                    silence_count = 0

            else:
                frames.append(frame.copy())
                if is_active_speech:
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count > silence_frames_needed:
                        stop = True
                        break

        if stop:
            break

        # Timer voor wachten op spraak
        if not started_talking:
            if time.time() - wait_start_time > wacht:
                logger.info("💤 JARVIS gaat weer slapen.")
                return None
        else:
            # Timer voor max opname vanaf spraakbegin
            if speech_start_time is not None:
                if time.time() - speech_start_time > MAX_OPNAME_SECONDEN:
                    logger.info("⏱️ Max opnametijd bereikt.")
                    break

    if not frames or not started_talking:
        return None

    logger.info("✅ Opname klaar.")
    status.omzetten()

    return np.concatenate(frames, axis=0)


def _capture_with_preamble(preamble_audio=None):
    """Capture with optional preamble audio prepended (niet meer gebruikt)."""
    recording = _capture()
    if recording is None:
        return None
    if preamble_audio is not None and len(preamble_audio) > 0:
        try:
            return np.concatenate([preamble_audio.astype(recording.dtype), recording], axis=0)
        except Exception:
            return recording
    return recording


def _recognize(recording):

    recording = _normalize(recording)

    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(recording.tobytes())

    wav_buffer.seek(0)

    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_buffer) as source:
        audio = recognizer.record(source)

    # De taal van het gesprek bepaalt waarmee de spraak wordt herkend
    # (Fase 17, F): standaard Nederlands, Engels als u daarom vroeg.
    import taal

    text = recognizer.recognize_google(audio, language=taal.spraak_code())

    logger.info("Jij: %s", text)
    return text


def listen(start_ts=None, preamble_audio=None, wacht_seconden=None):
    """Luistert naar een opdracht vanaf start_ts (het detectiemoment).

    preamble_audio blijft bestaan voor compatibiliteit, maar wordt bewust
    NIET gebruikt: audio van vóór de wake-word-detectie mag nooit als
    commando worden aangeboden.

    wacht_seconden is de tijd die op het begin van spraak gewacht wordt
    (standaard ``WACHT_OP_SPRAAK_SECONDEN``). In sessie-modus geeft JARVIS
    hier een veel langere tijd mee, zodat één gesprek meerdere beurten kan
    bevatten zonder opnieuw te moeten wekken (Fase 17, B2).
    """

    source = get_audio_source()

    recording = _capture(
        start_ts=start_ts, audio_source=source, wacht_seconden=wacht_seconden
    )

    if recording is None:
        return ""

    try:
        text = _recognize(recording)
        if text:
            return text
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        logger.warning("Spraakherkenning fout: %s", e)
        return "NO_CONNECTION"

    # Korte antwoorden ("ja" / "nee") worden de eerste keer nogal eens
    # gemist. Meteen een nieuwe poging zonder tussenkomst, vanaf het
    # nieuwste punt (zodat oude audio niet opnieuw wordt gebruikt).
    logger.info("🔁 Het was te kort of onduidelijk, nog een poging...")

    fresh_ts = source.latest_timestamp() if source is not None else None
    recording = _capture(start_ts=fresh_ts, audio_source=source)

    if recording is None:
        return None

    try:
        text = _recognize(recording)
        if text:
            return text
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        logger.warning("Spraakherkenning fout: %s", e)
        return "NO_CONNECTION"

    logger.warning("JARVIS kon je niet verstaan.")
    return "NOT_UNDERSTOOD"
