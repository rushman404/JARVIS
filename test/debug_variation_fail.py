import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import is_goal, is_multi_step_goal

for prompt in ["open de lamp", "open netflix en doe de lamp uit", "zet de lamp aan en open netflix",
               "open des lamp", "open een lamp", "de lamp openen"]:
    print(f"multi={is_multi_step_goal(prompt)!s:5} | goal={is_goal(prompt)!s:5} | '{prompt}'")