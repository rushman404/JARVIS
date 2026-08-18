import sounddevice as sd
import numpy as np
import speech_recognition as sr
import webrtcvad
import io
import wave
import time
import collections

SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
SILENCE_DURATION = 0.8
MAX_RECORD_SECONDS = 10

# Twee "oren":
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


def _capture():

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    vad_stop = webrtcvad.Vad(VAD_STOP_AGGRESSIVENESS)

    frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
    silence_frames_needed = int(SILENCE_DURATION / (FRAME_DURATION_MS / 1000))

    print("🎙️ JARVIS luistert...")
    print("🗣️ Zeg iets...")

    frames = []
    started_talking = False
    silence_count = 0
    speech_streak = 0          # teller voor opeenvolgende speech-frames
    start_time = time.time()
    noise_floor = None         # meebewegende ruisvloer

    pre_buffer = collections.deque(maxlen=PRE_BUFFER_FRAMES)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        while True:
            block, _ = stream.read(frame_size)
            frame_bytes = block.tobytes()

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
                pre_buffer.append(block.copy())

                if can_start:
                    speech_streak += 1
                else:
                    speech_streak = 0

                if speech_streak >= SPEECH_FRAMES_TO_START:
                    print("🎤 Spraak gedetecteerd...")
                    started_talking = True
                    frames.extend(pre_buffer)
                    frames.append(block.copy())
                    silence_count = 0

            else:
                frames.append(block.copy())
                if is_active_speech:
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count > silence_frames_needed:
                        break

            if time.time() - start_time > MAX_RECORD_SECONDS:

                if not started_talking:
                    print("💤 JARVIS gaat weer slapen.")
                    return None
                
                print("⏱️ Max opnametijd bereikt.")
                break

    if not frames or not started_talking:
        return None

    print("✅ Opname klaar.")
    print("🧠 JARVIS verwerkt je stem...")

    return np.concatenate(frames, axis=0)


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

    text = recognizer.recognize_google(audio, language="nl-NL")

    print(f"Jij: {text}")
    return text


def listen():

    recording = _capture()

    if recording is None:
        return ""

    try:
        text = _recognize(recording)
        if text:
            return text
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        print(f"❌ Spraakherkenning fout: {e}")
        return None

    # Korte antwoorden ("ja" / "nee") worden de eerste keer nogal eens
    # gemist. Meteen een nieuwe poging zonder tussenkomst.
    print("🔁 Het was te kort of onduidelijk, nog een poging...")

    recording = _capture()

    if recording is None:
        return None

    try:
        text = _recognize(recording)
        if text:
            return text
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        print(f"❌ Spraakherkenning fout: {e}")
        return None

    print("❌ JARVIS kon je niet verstaan.")
    return None