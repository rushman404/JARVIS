import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.brain as brain

print("=== FASE 6: Systeeminfo-routing (deterministisch) ===\n")

# Mock de systeemfuncties voor een schone test
calls = []


def _make_ret(name, value):
    def fake(*a, **k):
        calls.append(name)
        return value
    return fake


brain.system_summary = _make_ret("system_summary", "FAKE summary")
brain.cpu_info = _make_ret("cpu_info", {"naam": "X", "cores": 4, "threads": 8})
brain.ram_info = _make_ret("ram_info", {"totaal": 16, "gebruikt": 4, "vrij": 12})
brain.gpu_names = _make_ret("gpu_names", ["RTX 3060 Ti"])
brain.disk_info = _make_ret("disk_info", {"schijf": "C", "totaal": 500, "vrij": 100})
brain.battery_info = _make_ret("battery_info", {"percentage": 80, "stekker": True})
brain.os_info = _make_ret("os_info", {"systeem": "Windows", "release": "11"})
brain.uptime = _make_ret("uptime", {"dagen": 1, "uren": 2, "minuten": 3})

tests = [
    ("systeeminformatie", "system_summary"),
    ("wat voor pc heb ik", "system_summary"),
    ("welke cpu heb ik", "cpu_info"),
    ("wat is mijn processor", "cpu_info"),
    ("hoeveel ram heb ik", "ram_info"),
    ("wat is mijn geheugen", "ram_info"),
    ("welke videokaart heb ik", "gpu_names"),
    ("wat is mijn gpu", "gpu_names"),
    ("hoeveel ruimte heb ik", "disk_info"),
    ("schijfruimte", "disk_info"),
    ("hoe is het met mijn batterij", "battery_info"),
    ("welke windows heb ik", "os_info"),
    ("hoe lang staat mijn pc aan", "uptime"),
]

all_ok = True

for phrase, expected in tests:
    calls.clear()
    brain.try_system_info(phrase)
    ok = calls == [expected]
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' -> verwacht {expected} | kreeg {calls}")

print("\n=== FASE 6: Geen valse systeeminfo (moeten False zijn) ===")

negative = [
    "wat is mijn favoriete game",
    "open discord",
    "pauzeer",
    "sluit spotify",
    "zet volume op 30",
]

for phrase in negative:
    calls.clear()
    brain.try_system_info(phrase)
    ok = not calls
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' mag GEEN systeeminfo zijn | kreeg {calls}")

print("\n=== FASE 6: Venster-routing (deterministisch) ===\n")

window_calls = []


def _make_window_ret(fn):
    def fake(*a, **k):
        window_calls.append((fn, a))
        return "FAKE"
    return fake


brain.minimize_program = _make_window_ret("minimize")
brain.maximize_program = _make_window_ret("maximize")
brain.restore_window = _make_window_ret("restore")

# Context leegmaken zodat "geen naam" niet terugvalt op een vorig programma
brain.current_context["last_program"] = None

window_tests = [
    ("minimaliseer Discord", "minimize", ("discord",)),
    ("maak Spotify klein", "minimize", ("spotify",)),
    ("vergroot Discord", "maximize", ("discord",)),
    ("maak het Steam-venster groot", "maximize", ("steam",)),
    ("herstel Discord", "restore", ("discord",)),
    ("maak het venster weer normaal", "restore", (None,)),
]

for phrase, expected, expected_args in window_tests:
    window_calls.clear()
    brain.try_window_command(phrase)

    if expected_args == (None,):
        # "maak het venster weer normaal" zonder naam → false of context nodig
        ok = not window_calls
    else:
        ok = window_calls and window_calls[0][0] == expected and tuple(window_calls[0][1]) == expected_args

    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' -> verwacht {expected}{expected_args} | kreeg {window_calls}")

print("\n=== FASE 6: Geen valse venster-acties ===")

window_negative = [
    "wat is je cpu",
    "hoeveel ram heb ik",
    "open discord",
    "sluit spotify",
    "pauzeer",
    "welke videokaart",
]

for phrase in window_negative:
    window_calls.clear()
    brain.try_window_command(phrase)
    ok = not window_calls
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' mag GEEN venster-actie zijn | kreeg {window_calls}")

print("\n=== FASE 6: Screenshot-routing (deterministisch) ===\n")

shot_calls = []


def _fake_screenshot(*a, **k):
    shot_calls.append(a)
    return r"C:\Users\rushi\Pictures\JARVIS\test_screenshot.png"


brain.take_screenshot = _fake_screenshot

shot_positive = [
    "maak een screenshot",
    "screenshot",
    "schermafbeelding",
    "neem een foto van mijn scherm",
]

for phrase in shot_positive:
    shot_calls.clear()
    brain.try_screenshot(phrase)
    ok = bool(shot_calls)
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' moet een screenshot maken | kreeg {shot_calls}")

print("\n=== FASE 6: Geen valse screenshot ===")

shot_negative = [
    "wat is je cpu",
    "open discord",
    "vergeet mijn favoriete game",
    "wat is mijn gpu",
]

for phrase in shot_negative:
    shot_calls.clear()
    brain.try_screenshot(phrase)
    ok = not shot_calls
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' mag GEEN screenshot zijn | kreeg {shot_calls}")

print("\n=== FASE 6: Bestandsbeheer-routing (deterministisch) ===\n")

file_calls = []


def _make_file_ret(fn):
    def fake(*a, **k):
        file_calls.append((fn, a))
        return "FAKE"
    return fake


def _fake_find_item(name):
    results = find_results.get(name, [])
    if results:
        _known_folders.add(results[0])
    return results


def _fake_resolve_location(q):
    home = os.path.expanduser("~")
    if "desktop" in q or "bureaublad" in q:
        return os.path.join(home, "Desktop")
    if "pictures" in q or "afbeeldingen" in q:
        return os.path.join(home, "Pictures")
    if "downloads" in q:
        return os.path.join(home, "Downloads")
    if "documenten" in q:
        return os.path.join(home, "Documents")
    return None


find_results = {}

_known_folders = set()
_orig_isdir = os.path.isdir


def _fake_isdir(path):
    if path in _known_folders:
        return True
    return _orig_isdir(path)


os.path.isdir = _fake_isdir

brain.create_folder = _make_file_ret("create_folder")
brain.create_file = _make_file_ret("create_file")
brain.list_folder = _make_file_ret("list_folder")
brain.list_folder_by_path = _make_file_ret("list_folder_by_path")
brain.copy_path = _make_file_ret("copy_path")
brain.move_path = _make_file_ret("move_path")
brain.find_item = _fake_find_item
brain.resolve_location = _fake_resolve_location

file_tests = [
    ("maak een map genaamd Project", "create_folder", None),
    ("maak een nieuwe map Project op het bureaublad", "create_folder", None),
    ("maak een map Project in documenten", "create_folder", None),
    ("maak een bestand notities in documenten", "create_file", None),
    ("maak een bestand genaamd lijstje op het bureaublad", "create_file", None),
    ("welke bestanden zitten in downloads", "list_folder", None),
    ("wat zit er in mijn documenten", "list_folder", None),
    ("kopieer cv naar documenten", "copy_path", "cv"),
    ("kopieer het bestand cv naar documenten", "copy_path", "cv"),
    ("verplaats rapport naar downloads", "move_path", "rapport"),
    ("verplaats de map test naar documenten", "move_path", "test"),
]

home = os.path.expanduser("~")
desktop_test = os.path.join(home, "Desktop", "test123")


def _reset_find():
    find_results.clear()
    _known_folders.clear()
    brain.current_context["pending_choice"] = None
    file_calls.clear()


for phrase, expected, find_name in file_tests:
    _reset_find()

    if find_name:
        find_results[find_name] = [os.path.join(home, "Desktop", find_name)]

    brain.try_file_command(phrase)
    ok = file_calls and file_calls[0][0] == expected
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' -> verwacht {expected} | kreeg {file_calls}")

print("\n=== FASE 6: map op naam (één match) ===")

_reset_find()
find_results["test123"] = [
    os.path.join(home, "Desktop", "test123"),
    os.path.join(home, "Desktop", "test123", "iets.mp4"),
]
brain.try_file_command("wat zit er in test123")
ok = bool(file_calls) and file_calls[0][0] == "list_folder_by_path" and file_calls[0][1] == (desktop_test,)
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'wat zit er in test123' (1 match) -> opent de map | kreeg {file_calls}")

_reset_find()
find_results["test2"] = [
    os.path.join(home, "Desktop", "test2"),
    os.path.join(home, "Desktop", "test2", "iets.mp4"),
]
brain.try_file_command("wat zit er een test2")
ok = bool(file_calls) and file_calls[0][0] == "list_folder_by_path"
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'wat zit er een test2' (STT-variant) -> opent de map | kreeg {file_calls}")

_reset_find()
find_results["test3"] = [
    os.path.join(home, "Desktop", "test3"),
    os.path.join(home, "Desktop", "test3", "iets.mp4"),
]
brain.try_file_command("wat zit er in de map test3")
ok = bool(file_calls) and file_calls[0][0] == "list_folder_by_path" and file_calls[0][1] == (os.path.join(home, "Desktop", "test3"),)
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'wat zit er in de map test3' -> opent de map | kreeg {file_calls}")

print("\n=== FASE 6: wachtende keuze (meerdere matches) ===")

_reset_find()
find_results["test"] = [
    os.path.join(home, "Desktop", "test"),
    os.path.join(home, "Pictures", "test"),
]
r = brain.try_file_command("wat zit er in test")
pending = brain.current_context.get("pending_choice")
ok = not file_calls and pending is not None and len(pending["matches"]) == 2
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'wat zit er in test' (2 matches) -> vraagt welke + pending keuze | pending={bool(pending)}")

file_calls.clear()
r = brain.handle_pending_choice("desktop")
pending = brain.current_context.get("pending_choice")
ok = bool(file_calls) and file_calls[0][0] == "list_folder_by_path" and pending is None
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} antwoord 'desktop' -> opent bureaublad-map, pending gewist | kreeg {file_calls}")

_reset_find()
find_results["test"] = [
    os.path.join(home, "Desktop", "test"),
    os.path.join(home, "Pictures", "test"),
]
brain.try_file_command("wat zit er in test")
file_calls.clear()
brain.handle_pending_choice("2")
ok = bool(file_calls) and file_calls[0][0] == "list_folder_by_path" and file_calls[0][1] == (os.path.join(home, "Pictures", "test"),)
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} antwoord '2' -> opent tweede match (Pictures) | kreeg {file_calls}")

print("\n=== FASE 6: wachtende keuze bij kopiëren/verplaatsen ===")

_reset_find()
find_results["cv"] = [
    os.path.join(home, "Desktop", "cv"),
    os.path.join(home, "Pictures", "cv"),
]
brain.try_file_command("kopieer cv naar documenten")
pending = brain.current_context.get("pending_choice")
ok = not file_calls and pending is not None and pending["kind"] == "copy" and pending["destination"] == "documenten"
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'kopieer cv naar documenten' (2 matches) -> vraagt welke | kind={pending.get('kind') if pending else None}")

file_calls.clear()
brain.handle_pending_choice("2")
ok = bool(file_calls) and file_calls[0][0] == "copy_path" and file_calls[0][1] == (os.path.join(home, "Pictures", "cv"), "documenten")
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} antwoord '2' -> kopieert de tweede | kreeg {file_calls}")

_reset_find()
find_results["rapport"] = [
    os.path.join(home, "Desktop", "rapport"),
    os.path.join(home, "Downloads", "rapport"),
]
brain.try_file_command("verplaats rapport naar downloads")
file_calls.clear()
brain.handle_pending_choice("desktop")
ok = bool(file_calls) and file_calls[0][0] == "move_path" and file_calls[0][1] == (os.path.join(home, "Desktop", "rapport"), "downloads")
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} antwoord 'desktop' bij verplaatsen -> verplaatst bureaublad-versie | kreeg {file_calls}")

print("\n=== FASE 6: verwijderen + prullenbak (met bevestiging) ===\n")

recycle_calls = []


def _make_recycle_ret(fn):
    def fake(*a, **k):
        recycle_calls.append(fn)
        return "FAKE"
    return fake


brain.send_to_recycle = _make_recycle_ret("send_to_recycle")
brain.empty_recycle_bin = _make_recycle_ret("empty_recycle_bin")

# Eén match: eerst bevestiging vragen, pas dan verwijderen
_reset_find()
find_results["oudeproject"] = [os.path.join(home, "Desktop", "oudeproject")]
brain.try_file_command("verwijder de map oudeproject")
pending = brain.current_context.get("pending_choice")
ok = pending is not None and pending["kind"] == "delete_confirm"
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'verwijder de map oudeproject' -> vraagt om bevestiging | kind={pending.get('kind') if pending else None}")

recycle_calls.clear()
brain.handle_pending_choice("nee")
pending = brain.current_context.get("pending_choice")
ok = not recycle_calls and pending is None
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} antwoord 'nee' -> niets verwijderd, pending gewist")

_reset_find()
find_results["oudeproject"] = [os.path.join(home, "Desktop", "oudeproject")]
brain.try_file_command("verwijder de map oudeproject")
recycle_calls.clear()
brain.handle_pending_choice("ja")
pending = brain.current_context.get("pending_choice")
ok = recycle_calls == ["send_to_recycle"] and pending is None
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} antwoord 'ja' -> naar de prullenbak, pending gewist | kreeg {recycle_calls}")

# Meerdere matches: eerst kiezen, dan bevestigen
_reset_find()
recycle_calls.clear()
find_results["test"] = [
    os.path.join(home, "Desktop", "test"),
    os.path.join(home, "Pictures", "test"),
]
brain.try_file_command("verwijder de map test")
pending = brain.current_context.get("pending_choice")
ok = not recycle_calls and pending is not None and pending["kind"] == "delete_choose"
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 2 matches -> vraagt welke | kind={pending.get('kind') if pending else None}")

brain.handle_pending_choice("tweede")
pending = brain.current_context.get("pending_choice")
ok = not recycle_calls and pending is not None and pending["kind"] == "delete_confirm"
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'tweede' -> vraagt bevestiging | kind={pending.get('kind') if pending else None}")

recycle_calls.clear()
brain.handle_pending_choice("ja")
ok = recycle_calls == ["send_to_recycle"] and brain.current_context.get("pending_choice") is None
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'ja' -> tweede match naar de prullenbak | kreeg {recycle_calls}")

# "verwijder X" zonder bestand/map-hint = geheugenvergeten, géén bestandsactie
_reset_find()
recycle_calls.clear()
brain.try_file_command("verwijder mijn favoriete game")
pending = brain.current_context.get("pending_choice")
ok = not recycle_calls and pending is None
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'verwijder mijn favoriete game' -> géén bestandsactie (geheugenvergeten) | pending={bool(pending)}")

# Prullenbak legen vraagt eerst bevestiging
_reset_find()
recycle_calls.clear()
brain.try_file_command("leeg de prullenbak")
pending = brain.current_context.get("pending_choice")
ok = not recycle_calls and pending is not None and pending["kind"] == "empty_confirm"
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'leeg de prullenbak' -> vraagt bevestiging | kind={pending.get('kind') if pending else None}")

recycle_calls.clear()
brain.handle_pending_choice("ja")
ok = recycle_calls == ["empty_recycle_bin"] and brain.current_context.get("pending_choice") is None
all_ok = all_ok and ok
print(f"{'✅' if ok else '❌'} 'ja' -> prullenbak geleegd | kreeg {recycle_calls}")

brain.current_context["pending_choice"] = None
os.path.isdir = _orig_isdir

print("\n=== FASE 6: Geen valse bestandsacties ===")

file_negative = [
    "open discord",
    "hoeveel ram heb ik",
    "pauzeer",
    "wat is het weer",
]

for phrase in file_negative:
    file_calls.clear()
    brain.try_file_command(phrase)
    ok = not file_calls
    all_ok = all_ok and ok
    print(f"{'✅' if ok else '❌'} '{phrase}' mag GEEN bestandsactie zijn | kreeg {file_calls}")

print("\nALLES OK" if all_ok else "\nFOUTEN GEVONDEN")