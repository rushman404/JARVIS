import webbrowser
import os
from actions.program_finder import find_program
import win32gui
import win32con

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