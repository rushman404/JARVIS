import pyttsx3
import numpy as np
import sounddevice as sd

from config import BEEP_ENABLED


engine = pyttsx3.init()
voices = engine.getProperty('voices')
dutch_voice = next((v for v in voices if "dutch" in v.name.lower() or "nederlands" in v.name.lower()), None)
if dutch_voice:
    engine.setProperty('voice', dutch_voice.id)
else:
    print("⚠️ Waarschuwing: Geen Nederlandse stem gevonden voor pyttsx3.")

SAMPLE_RATE = 16000


def _beep(duration=0.15, frequency=800):
    """Play a short beep tone."""
    try:
        t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
        wave = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        wave = np.column_stack((wave, wave)) if False else wave.reshape(-1, 1)
        sd.play(wave, SAMPLE_RATE)
        sd.wait()
    except Exception as e:
        print(f"⚠️ Kon pieptoon niet afspelen: {e}")


def speak(text=None, beep_only=False):
    """Speak text or optionally play beep instead."""
    if beep_only:
        if BEEP_ENABLED:
            _beep()
        return

    if text is None:
        if BEEP_ENABLED:
            _beep()
        return

    print(f"JARVIS: {text}")

    engine.say(text)
    engine.runAndWait()