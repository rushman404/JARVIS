import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import process_command


print(process_command("wat is 10 min 1"))
print(process_command("hoe laat is het?"))