import webbrowser
import os
from actions.program_finder import find_program
import win32gui
import win32con
import subprocess

def open_program(program):

    try:

        # Eerst kijken of het programma al open is
        if bring_window_to_front(program):

            return f"{program} stond al open en staat nu vooraan."

        # Programma zoeken
        results = find_program(program)

        if not results:

            return f"Ik kan {program} niet vinden."

        selected_program = results[0]

        print(f"🚀 Programma gevonden: {selected_program}")

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