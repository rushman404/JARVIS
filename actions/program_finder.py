import os


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


    if exact_only:
        return list(dict.fromkeys(exact_matches))

    # Eerst exacte resultaten gebruiken
    if exact_matches:
        return list(dict.fromkeys(exact_matches))

    # Anders gedeeltelijke resultaten
    return list(dict.fromkeys(partial_matches))