import webbrowser
import os
import win32gui
import win32con
import win32api
import win32process
import win32com.client
import pythoncom
import subprocess
import threading
import time
from actions.program_finder import find_program

# _volume_lock removed (was unused)

def get_shortcut_target(lnk_path):

    def _do():
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(lnk_path)
            return shortcut.TargetPath or ""
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass

    try:
        from actions.com_worker import run_on_com_thread
        return run_on_com_thread(_do)
    except Exception:
        # fallback
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(lnk_path)
            return shortcut.TargetPath or ""
        except Exception as e:
            print(f"Fout bij lezen snelkoppeling: {e}")
            return ""
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


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

            # Geen zichtbaar venster gevonden (bijv. in de systeemlade):
            # probeer het programma alsnog op het scherm te tonen.
            os.startfile(selected_program)

            return f"{program} is al geopend en wordt nu getoond."

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

                # Focus-stelen blokkade van Windows omzeilen
                foreground = win32gui.GetForegroundWindow()
                fg_thread = win32process.GetWindowThreadProcessId(foreground)[0]
                this_thread = win32api.GetCurrentThreadId()
                win32process.AttachThreadInput(this_thread, fg_thread, True)
                win32gui.SetForegroundWindow(hwnd)
                win32process.AttachThreadInput(this_thread, fg_thread, False)

                found = True

            except Exception as e:
                print(f"Venster kon niet naar voren: {e}")

    win32gui.EnumWindows(check_window, None)

    return found


def set_window_state(program_name, state):

    program_name = program_name.lower()

    show_command = {
        "minimize": win32con.SW_MINIMIZE,
        "maximize": win32con.SW_MAXIMIZE,
        "restore": win32con.SW_RESTORE,
    }.get(state)

    if show_command is None:
        return False

    found = False

    def check_window(hwnd, extra):

        nonlocal found

        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).lower()

        if program_name in title:

            try:
                win32gui.ShowWindow(hwnd, show_command)
                found = True

            except Exception as e:
                print(f"Venster kon niet aangepast worden: {e}")

    win32gui.EnumWindows(check_window, None)

    return found


def minimize_program(program_name):

    if set_window_state(program_name, "minimize"):
        return f"Ik minimaliseer {program_name}."

    return f"Ik kon geen venster van {program_name} vinden."


def maximize_program(program_name):

    program_name = program_name.lower()

    found = False
    restored = False

    def check_window(hwnd, extra):

        nonlocal found, restored

        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).lower()

        if program_name in title:

            try:

                # Al gemaximaliseerd? Dan "poppen" we hem eruit
                # terug naar het normale formaat (toggle).
                placement = win32gui.GetWindowPlacement(hwnd)

                if placement[1] == win32con.SW_MINIMIZE:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    placement = win32gui.GetWindowPlacement(hwnd)

                if placement[1] == win32con.SW_MAXIMIZE:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    restored = True
                else:
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)

                found = True

            except Exception as e:
                print(f"Venster kon niet vergroot worden: {e}")

    win32gui.EnumWindows(check_window, None)

    if not found:
        return f"Ik kon geen venster van {program_name} vinden."

    if restored:
        return f"Ik zet {program_name} terug naar het normale formaat."

    return f"Ik vergroot {program_name}."


def restore_window(program_name):

    if set_window_state(program_name, "restore"):
        return f"Ik herstel {program_name}."

    return f"Ik kon geen venster van {program_name} vinden."

def close_program(program):

    import psutil

    program_lower = program.lower().strip()

    # .exe verwijderen als de AI die meegeeft
    if program_lower.endswith(".exe"):
        program_lower = program_lower[:-4]

    print(f"🔴 Programma sluiten: '{program_lower}'")

    process_names = {
        "spotify": ["spotify.exe"],
        "discord": ["discord.exe"],
        "steam": ["steam.exe"],
        "chrome": ["chrome.exe"],
        "firefox": ["firefox.exe"],
        "edge": ["msedge.exe"],
    }

    # Bekende processen uit de vaste lijst
    targets = list(process_names.get(program_lower, []))

    # Zoek de .exe via de Start Menu-links als het niet bekend is
    if not targets:
        found = find_program(program_lower)
        if found:
            exe = os.path.basename(found[0])
            if exe.lower().endswith(".exe"):
                targets.append(exe.lower())

    # Laatste optie: gewoon op naam proberen
    if not targets:
        targets.append(f"{program_lower}.exe")

    closed = False

    # Doorloop alle actieve processen op het systeem
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pinfo = proc.info
            pname = str(pinfo["name"]).lower()

            # Controleer of de procesnaam matcht op een van de targets
            # OF controleer of de procesnaam exact de program_lower is
            is_match = False
            for target in targets:
                if target == pname or pname == f"{program_lower}.exe":
                    is_match = True
                    break

            if is_match:
                print(f"🔧 Probeer proces te sluiten via psutil: {pname} (PID: {pinfo['pid']})")
                proc.terminate()
                closed = True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if closed:
        return f"{program} wordt gesloten."

    return f"{program} was niet geopend."

def restart_program(program):
    close_result = close_program(program)
    if "niet geopend" in close_result:
        return f"{program} was niet geopend, maar ik probeer het te starten."

    time.sleep(1.5)

    open_result = open_program(program)

    return f"{program} wordt herstart. {open_result}"


def get_program_status(program):
    results = find_program(program)

    if not results:
        return f"{program} is niet gevonden op deze computer."

    selected = pick_best_program(results, program)

    process_names = get_process_names(selected, program)

    if is_process_running(process_names):
        return f"{program} draait momenteel."

    return f"{program} is niet geopend."


def find_program_location(program):
    results = find_program(program)

    if not results:
        return f"{program} is niet gevonden."

    return results[0]