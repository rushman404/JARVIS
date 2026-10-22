import os
import shutil


def _via_pad(program_name):
    """Zoekt een programma dat alleen via PATH of System32 bereikbaar is.

    Kladblok, Rekenmachine en Paint hebben op Windows 11 geen snelkoppeling
    in het startmenu meer; zonder deze terugval meldde de agent "ik kan
    notepad niet vinden".
    """

    for kandidaat in (f"{program_name}.exe", program_name):

        try:
            pad = shutil.which(kandidaat)
        except OSError:
            pad = None

        if pad:
            return pad

    return None


def find_program(program_name, exact_only=False):

    program_name = program_name.lower().strip()

    search_locations = [
        os.path.expandvars(
            r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"
        ),
        os.path.expandvars(
            r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"
        ),
        os.path.expandvars(
            r"%USERPROFILE%\Desktop"
        ),
        os.path.expandvars(
            r"%PUBLIC%\Desktop"
        ),
    ]

    exact_matches = []
    partial_matches = []

    for location in search_locations:

        if not os.path.exists(location):
            continue

        for root, directories, files in os.walk(location):

            for file in files:

                if not file.lower().endswith((".lnk", ".exe")):
                    continue

                filename = os.path.splitext(file)[0].lower()
                full_path = os.path.join(root, file)

                # Sla snelkoppelingen over waarvan de naam "uninstall", "verwijder" of "setup" bevat
                if any(x in filename for x in ("uninstall", "verwijder", "setup")):
                    continue

                # Exacte match heeft voorrang
                if filename == program_name:
                    exact_matches.append(full_path)

                # Gedeeltelijke match
                elif program_name in filename:
                    partial_matches.append(full_path)


    if not exact_matches:
        pad = _via_pad(program_name)

        if pad:
            exact_matches.append(pad)

    if exact_only:
        return list(dict.fromkeys(exact_matches))

    # Eerst exacte resultaten gebruiken
    if exact_matches:
        return list(dict.fromkeys(exact_matches))

    # Anders gedeeltelijke resultaten
    return list(dict.fromkeys(partial_matches))