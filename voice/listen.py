import sounddevice as sd
import numpy as np
import speech_recognition as sr
import io
import wave

SAMPLE_RATE = 16000
RECORDING_TIME = 5


def listen():

    print("🎙️ JARVIS luistert...")
    print("🗣️ Zeg iets...")

    recording = sd.rec(
        int(RECORDING_TIME * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    print("✅ Opname klaar.")
    print("🧠 JARVIS verwerkt je stem...")

    # Float32 → 16-bit PCM
    audio_int16 = np.int16(
        recording * 32767
    )

    # WAV-bestand in geheugen
    wav_buffer = io.BytesIO()

    with wave.open(wav_buffer, "wb") as wav_file:

        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)

        wav_file.writeframes(
            audio_int16.tobytes()
        )

    wav_buffer.seek(0)

    # Speech Recognition
    recognizer = sr.Recognizer()

    with sr.AudioFile(wav_buffer) as source:

        audio = recognizer.record(source)

    try:

        text = recognizer.recognize_google(
            audio,
            language="nl-NL"
        )

        print(f"Jij: {text}")

        return text

    except sr.UnknownValueError:

        print("❌ JARVIS kon je niet verstaan.")

        return ""

    except sr.RequestError as e:

        print(f"❌ Spraakherkenning fout: {e}")

        return ""