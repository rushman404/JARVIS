import sys
sys.path.insert(0, r"C:\JARVIS")

import core.brain as brain
from actions.media import get_volume, set_volume

print("=== FASE 5: Media-routing (deterministisch) ===\n")

# Mock de mediatoetsen zodat er niks echt wordt ingedrukt
calls = []

for name in ("play_pause", "next_track", "previous_track", "volume_up", "volume_down", "set_volume", "toggle_mute"):

    def make(n):
        def fake(*a, **k):
            calls.append((n, a))
            return f"FAKE {n}"
        return fake

    setattr(brain, name, make(name))

tests = [
    ("zet volume op 30", "set_volume", (30,)),
    ("volume naar 50 procent", "set_volume", (50,)),
    ("harder", "volume_up", ()),
    ("volume omhoog", "volume_up", ()),
    ("luider", "volume_up", ()),
    ("zachter", "volume_down", ()),
    ("volume omlaag", "volume_down", ()),
    ("demp het geluid", "toggle_mute", ()),
    ("mute", "toggle_mute", ()),
    ("pauzeer", "play_pause", ()),
    ("zet muziek uit", "play_pause", ()),
    ("stop de muziek", "play_pause", ()),
    ("speel verder", "play_pause", ()),
    ("speel muziek", "play_pause", ()),
    ("zet muziek aan", "play_pause", ()),
    ("volgende nummer", "next_track", ()),
    ("skip", "next_track", ()),
    ("vorige nummer", "previous_track", ()),
]

all_ok = True

for phrase, expected, args in tests:
    calls.clear()
    brain.try_media_command(phrase)
    got = calls[0] if calls else None
    ok = got is not None and got[0] == expected and tuple(got[1]) == args
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' -> verwacht {expected} | kreeg {got}")

print("\n=== FASE 5: Geen valse media (moeten False zijn) ===")

negative = [
    "wat is mijn favoriete game",
    "open discord",
    "sluit spotify",
    "speel een game",
    "wat is de hoofdstad van frankrijk",
]

for phrase in negative:
    calls.clear()
    brain.try_media_command(phrase)
    ok = not calls
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' mag GEEN media zijn | kreeg {calls}")

print("\n=== FASE 5: Volume lezen en schrijven (zelfde waarde, geen wijziging) ===")

current = get_volume()

if current is not None:
    print(f"✅ volume lezen: {current}%")
    print(f"✅ set_volume({current}) -> {set_volume(current)}")
    check = get_volume()

    if check == current:
        print(f"✅ volume onveranderd: {check}%")
    else:
        all_ok = False
        print(f"❌ volume veranderd naar {check}%")
else:
    all_ok = False
    print("❌ volume lezen mislukt")

print("\nALLES OK" if all_ok else "\nFOUTEN GEVONDEN")
