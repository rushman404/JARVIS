import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice.speak import speak


speak("Goedendag Rushil. Ik ben online.")