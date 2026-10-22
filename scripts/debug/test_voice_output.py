import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from voice import piper_tts
from voice.speak import speak


if piper_tts.is_available():
    print("Stem: Piper (lokaal Nederlands model).")
else:
    print("Stem: pyttsx3-terugval (geen Piper-stemmodel gevonden).")
    print("Installeer de Nederlandse stem met:")
    print("  python scripts/download_piper_voice.py")
    print()

speak("Goedendag Rushil. Ik ben online.")