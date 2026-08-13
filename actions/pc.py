import webbrowser
import os
from actions.program_finder import find_program
import win32gui
import win32con
import win32com.client
import subprocess

def get_shortcut_target(lnk_path):

    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)
        return shortcut.TargetPath or ""

    except Exception as e:
        print(f"Fout bij lezen snelkoppeling: {e}")
        return ""


def pick_best_program(results, program):

    program_lower = program.lower().strip()
    program_name = os.path.splitext(program_lower)[0]

    def score(path):

        name = os.path.basename(path).lower()

        if path.lower().endswith(".lnk"):
            resolved = get_shortcut_target(path)
            if resolved:
                name = os.path.basename(resolved).lower()

        if program_name in name:
            return 3

        if program_lower in name:
            return 2

        return 1

    return max(results, key=score)

def get_process_names(program_path, program):

    names = []

    if program_path.lower().endswith(".lnk"):
        target = get_shortcut_target(program_path)
        if target:
            base = os.path.basename(target).lower()
            if base.endswith(".exe"):
                names.append(base)

    names.append(f"{program.strip().lower()}.exe")

    return list(dict.fromkeys(names))


def is_process_running(process_names):

    try:
        result = subprocess.run(
            ["tasklist", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True
        )

        output = result.stdout.lower()

        for name in process_names:
            if name.lower() in output:
                return True

    except Exception as e:
        print(f"Fout bij processen controleren: {e}")

    return False


def open_program(program):

    try:

        # Programma zoeken
        results = find_program(program)

        if not results:

            return f"Ik kan {program} niet vinden."

        selected_program = pick_best_program(results, program)

        print(f"🚀 Programma gevonden: {selected_program}")

        process_names = get_process_names(selected_program, program)

        # Draait het programma al echt?
        if is_process_running(process_names):

            if bring_window_to_front(program):
                return f"{program} stond al open en staat nu vooraan."

            return f"{program} is al geopend."

        # Programma openen
        os.startfile(selected_program)

        return f"Ik open {program}."

    except Exception as e:

        print(f"Fout bij openen programma: {e}")

        return f"Ik kon {program} niet openen."

def open_website(url):
    try:
        webbrowser.open(url)
        return True

    except Exception as e:
        print(f"Fout bij openen van website: {e}")
        return False


def bring_window_to_front(program_name):

    program_name = program_name.lower()

    found = False

    def check_window(hwnd, extra):

        nonlocal found

        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).lower()

        if program_name in title:

            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)

                found = True

            except Exception as e:
                print(f"Venster kon niet naar voren: {e}")

    win32gui.EnumWindows(check_window, None)

    return found

def close_program(program):

    process_names = {
        "spotify": ["Spotify.exe"],
        "discord": ["Discord.exe"],
        "steam": ["steam.exe"],
        "chrome": ["chrome.exe"],
        "firefox": ["firefox.exe"],
        "edge": ["msedge.exe"],
    }

    program_lower = program.lower().strip()

    # .exe verwijderen als de AI die meegeeft
    if program_lower.endswith(".exe"):
        program_lower = program_lower[:-4]

    print(f"🔴 Programma sluiten: '{program_lower}'")

    # Bekende processen uit de vaste lijst
    processes = list(process_names.get(program_lower, []))

    # Onbekend programma: zoek de .exe via de Start Menu-links
    if not processes:
        found = find_program(program_lower)

        if found:
            exe = os.path.basename(found[0])

            if exe.lower().endswith(".exe"):
                processes.append(exe)

    # Laatste poging: gewoon op naam proberen
    if not processes:
        processes.append(f"{program_lower}.exe")

    closed = False

    for process in processes:

        print(f"🔧 Probeer proces te sluiten: {process}")

        result = subprocess.run(
            ["taskkill", "/IM", process, "/F"],
            capture_output=True,
            text=True
        )

        print(f"📤 taskkill returncode: {result.returncode}")
        print(f"📤 taskkill output: {result.stdout}")
        print(f"📤 taskkill error: {result.stderr}")

        if result.returncode == 0:
            closed = True

    if closed:
        return f"{program} wordt gesloten."

    return f"{program} was niet geopend."

if __name__ == "__main__":
    print(close_program("Spotify"))