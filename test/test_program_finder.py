import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.program_finder import find_program


results = find_program("steam")


if results:

    print("Programma gevonden:")

    for result in results:
        print(result)

else:

    print("Programma niet gevonden.")