"""Handmatige Windows-test voor de COM-worker.

Doel: laat zien dat COM-aanroepen (volume) snel terugkomen en dat de
originele fout direct doorkomt, terwijl de routine "gaming" op de
achtergrond meedraait.

Gebruik (Windows):
    python scripts/test_com_volume_manual.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import process_command
from actions.media import volume_up, volume_down, toggle_mute


def _noteer_naam(resultaat):
    if isinstance(resultaat, str):
        return resultaat
    return str(resultaat)


def main():
    print("Start routine 'gaming' op de achtergrond...")
    routine_resultaat = {}

    def draai_routine():
        try:
            routine_resultaat["antwoord"] = process_command("gaming")
        except Exception as e:
            routine_resultaat["fout"] = repr(e)

    routine_draad = threading.Thread(target=draai_routine, daemon=True)
    routine_draad.start()

    # Wacht kort zodat de routine écht bezig is (Discord/Spotify/COM).
    time.sleep(0.5)

    print("\nTest volume-aanroepen via de COM-worker terwijl 'gaming' loopt:\n")
    for naam, actie in [
        ("volume omhoog (+5)", lambda: volume_up(5)),
        ("volume omlaag (-5)", lambda: volume_down(5)),
        ("demo: dempen (toggle)", toggle_mute),
        ("demo: dempen aanzetten (toggle)", toggle_mute),
    ]:
        begin = time.time()
        try:
            uitkomst = actie()
            duur = time.time() - begin
            print(f"  [{naam}] duur={duur:.2f}s -> {_noteer_naam(uitkomst)}")
        except Exception as e:
            duur = time.time() - begin
            print(f"  [{naam}] FOUT na {duur:.2f}s -> {type(e).__name__}: {e}")

    routine_draad.join(timeout=10)
    if "fout" in routine_resultaat:
        print(f"\nRoutine 'gaming' gaf een fout: {routine_resultaat['fout']}")
    else:
        print(f"\nRoutine 'gaming' klaar: {routine_resultaat.get('antwoord')}")
    print("\nKlaar. Volume is weer in te stellen met setters.")


if __name__ == "__main__":
    main()