"""Handmatige microfoontest: laat horen/zien wat er is opgenomen.

Gebruik (Windows):
    python scripts/test_mic_manual.py

Zeg "hey jarvis", wacht op de pieptoon en zeg daarna je commando.
De opname wordt opgeslagen als scripts/mic_manual_opname.wav.

Ontbreekt het wake word-model, dan slaat het script alleen de wake
word-trigger over: het neemt nog steeds ~2 seconden op en print de
opdracht om het model te downloaden.
"""
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice.audio_stream import AudioSource, set_audio_source
from voice.wakeword import wait_for_wake_word
from voice.listen import _capture
from voice.speak import speak

SAMPLE_RATE = 16000
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mic_manual_opname.wav")


def main():
    source = AudioSource()
    set_audio_source(source)
    source.start()

    print("Zeg 'hey jarvis'...")
    resultaat = wait_for_wake_word()

    detected_at = resultaat.get("detected_at") if isinstance(resultaat, dict) else None
    status = resultaat.get("status") if isinstance(resultaat, dict) else None

    if detected_at is not None:
        print("Wake word gedetecteerd! Zeg nu je commando...")
    elif status == "geen_model":
        print()
        print("Het wake word-model ontbreekt; de wake word-trigger wordt")
        print("overgeslagen. Ik test nu alleen de microfoonopname.")
        print("Download het model eenmalig met:")
        print(
            '  python -c "from openwakeword.utils import download_models; '
            'download_models()"'
        )
        print("Daarna opnieuw dit script voor de echte wake word-test.")
        print()
        print("Spreek nu je commando...")
    else:
        print(f"Wake word overgeslagen ({status or 'onbekende reden'}).")
        print("Ik test nu alleen de microfoonopname. Spreek je commando...")

    try:
        speak(beep_only=True)
    except Exception:
        pass

    opname = _capture(start_ts=detected_at, audio_source=source)

    try:
        if opname is None or np.size(opname) == 0:
            print("Er is niets opgenomen.")
            return

        samples = np.asarray(opname, dtype=np.int16)
        with wave.open(OUTPUT, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(samples.tobytes())

        seconden = samples.size / SAMPLE_RATE
        print(f"Opgenomen: {samples.size} samples (~{seconden:.1f} s)")
        print(f"Opgeslagen als: {OUTPUT}")
    finally:
        source.stop()


if __name__ == "__main__":
    main()
