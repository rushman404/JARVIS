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
MAX_RECORD_SECONDS = 15
VAD_AGGRESSIVENESS = 3

# hoeveel opeenvolgende speech-frames nodig zijn om "start" te bevestigen
SPEECH_FRAMES_TO_START = 4   # 4 x 30ms = 120ms aaneengesloten spraak


def listen():
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
    silence_frames_needed = int(SILENCE_DURATION / (FRAME_DURATION_MS / 1000))

    print("🎙️ JARVIS luistert...")
    print("🗣️ Zeg iets...")

    frames = []
    started_talking = False
    silence_count = 0
    speech_streak = 0          # teller voor opeenvolgende speech-frames
    start_time = time.time()

    pre_buffer = collections.deque(maxlen=10)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        while True:
            block, _ = stream.read(frame_size)
            frame_bytes = block.tobytes()

            is_speech = vad.is_speech(frame_bytes, SAMPLE_RATE)

            if not started_talking:
                pre_buffer.append(block.copy())

                if is_speech:
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
                if is_speech:
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count > silence_frames_needed:
                        break

            if time.time() - start_time > MAX_RECORD_SECONDS:

                if not started_talking:
                    print("💤 JARVIS gaat weer slapen.")
                    return ""
                
                print("⏱️ Max opnametijd bereikt.")
                break

    if not frames or not started_talking:
        return ""

    print("✅ Opname klaar.")
    print("🧠 JARVIS verwerkt je stem...")

    recording = np.concatenate(frames, axis=0)

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

    try:
        text = recognizer.recognize_google(audio, language="nl-NL")
        print(f"Jij: {text}")
        return text

    except sr.UnknownValueError:
        print("❌ JARVIS kon je niet verstaan.")
        return ""

    except sr.RequestError as e:
        print(f"❌ Spraakherkenning fout: {e}")
        return ""