import logging

import pyttsx3
import numpy as np
import sounddevice as sd

from config import BEEP_ENABLED

logger = logging.getLogger(__name__)


engine = pyttsx3.init()
voices = engine.getProperty('voices')
dutch_voice = next((v for v in voices if "dutch" in v.name.lower() or "nederlands" in v.name.lower()), None)
if dutch_voice:
    engine.setProperty('voice', dutch_voice.id)
else:
        logger.warning("Geen Nederlandse stem gevonden voor pyttsx3.")

SAMPLE_RATE = 16000


def _mute_microphone():
    """Dempen zolang JARVIS zelf geluid maakt (pieptoon of spraak)."""
    try:
        from voice.audio_stream import get_audio_source

        source = get_audio_source()
        if source is not None:
            source.mute()
    except Exception:
        pass


def _unmute_microphone():
    try:
        from voice.audio_stream import get_audio_source

        source = get_audio_source()
        if source is not None:
            source.unmute()
    except Exception:
        pass


def _beep(duration=0.15, frequency=800):
    """Play a short beep tone."""
    _mute_microphone()
    try:
        t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
        wave = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        wave = wave.reshape(-1, 1)
        sd.play(wave, SAMPLE_RATE)
        sd.wait()
    except Exception as e:
        logger.warning("Kon pieptoon niet afspelen: %s", e)
    finally:
        _unmute_microphone()


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

    logger.info("JARVIS: %s", text)

    _mute_microphone()
    try:
        engine.say(text)
        engine.runAndWait()
    finally:
        _unmute_microphone()