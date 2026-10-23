"""Tekstpad voor de handmatige test 'afsluiten annuleren'.

Zonder microfoon: stuurt "annuleer afsluiten" direct naar de hersenen en
bevestigt een eventuele vraag om akkoord met "ja". Dat gebeurt in hetzelfde
proces, zodat de openstaande bevestiging blijft bestaan (de state leeft
alleen in het geheugen).

De test start de countdown op DEZE pc. Daarom zet dit script PC_TARGET op
"local" voordat de hersenen worden geladen: anders annuleert JARVIS de
afsluiting van de game-pc in plaats van die van deze pc.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["PC_TARGET"] = "local"

from core.brain import process_command  # noqa: E402


def main():
    antwoord = process_command("annuleer afsluiten")
    print("JARVIS:", antwoord)

    laag = antwoord.lower()
    if "akkoord" in laag or "bevestig" in laag:
        print("JARVIS:", process_command("ja"))


if __name__ == "__main__":
    main()
