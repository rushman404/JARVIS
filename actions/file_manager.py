import os
import shutil
import ctypes
from send2trash import send2trash


LOCATION_ALIASES = [
    ("bureaublad", "Desktop"),
    ("desktop", "Desktop"),
    ("downloads", "Downloads"),
    ("documenten", "Documents"),
    ("afbeeldingen", "Pictures"),
    ("pictures", "Pictures"),
    ("foto's", "Pictures"),
    ("fotos", "Pictures"),
    ("muziek", "Music"),
    ("video's", "Videos"),
    ("videos", "Videos"),
    ("movies", "Videos"),
]

LOCATION_WORDS = [
    "bureaublad", "desktop", "downloads", "documenten", "afbeeldingen",
    "pictures", "foto's", "fotos", "muziek", "video's", "videos", "movies",
]

SEARCH_FOLDERS = [
    "Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos",
]

MAX_SEARCH_DEPTH = 3


def _user_folders():

    home = os.path.expanduser("~")

    return [os.path.join(home, folder) for folder in SEARCH_FOLDERS]


def resolve_location(text):

    lower = text.lower()

    for alias in LOCATION_ALIASES:

        if alias[0] in lower:
            return os.path.join(os.path.expanduser("~"), alias[1])

    # Een direct pad?
    if ":" in text or text.startswith("\\"):
        return text.strip().strip('"')

    return None


def find_item(name, max_depth=MAX_SEARCH_DEPTH):

    name = name.lower().strip()
    has_extension = os.path.splitext(name)[1] != ""

    results = []

    for base in _user_folders():

        if not os.path.isdir(base):
            continue

        for root, dirs, files in os.walk(base):

            depth = root[len(base):].count(os.sep)

            # Niet te diep zoeken (snel genoeg blijven)
            if depth >= max_depth:
                dirs[:] = []

            dirs[:] = [d for d in dirs if not d.startswith(".") and not d.startswith("$")]

            for folder in dirs:

                if folder.lower() == name:
                    results.append(os.path.join(root, folder))

            for file_name in files:

                file_lower = file_name.lower()

                if has_extension:

                    if file_lower == name:
                        results.append(os.path.join(root, file_name))

                else:

                    if os.path.splitext(file_lower)[0] == name:
                        results.append(os.path.join(root, file_name))

    return results


def _list_contents(path, label):

    try:

        entries = os.listdir(path)

        if not entries:
            return f"In {label} zit nog niets."

        folders = [e for e in entries if os.path.isdir(os.path.join(path, e))]
        files = [e for e in entries if not os.path.isdir(os.path.join(path, e))]

        parts = []

        if folders:
            parts.append(f"{len(folders)} map/mappen: " + ", ".join(folders[:8]))
        if files:
            parts.append(f"{len(files)} bestanden: " + ", ".join(files[:8]))

        return f"In {label} zitten {len(entries)} items. " + ". ".join(parts) + "."

    except Exception as error:
        print(f"Fout bij weergeven: {error}")
        return "Ik kon die map niet openen."


def create_folder(name, location_text=""):

    name = name.strip().strip(".,")

    location = resolve_location(location_text) or os.path.join(
        os.path.expanduser("~"),
        "Desktop"
    )

    path = os.path.join(location, name)

    try:

        os.makedirs(path, exist_ok=True)

        return f"Map '{name}' is aangemaakt op {os.path.basename(location)}."

    except Exception as error:
        print(f"Fout bij map maken: {error}")
        return f"Ik kon de map '{name}' niet aanmaken."


def create_file(name, location_text=""):

    name = name.strip().strip(".,")

    if not os.path.splitext(name)[1]:
        name += ".txt"

    location = resolve_location(location_text) or os.path.join(
        os.path.expanduser("~"),
        "Desktop"
    )

    path = os.path.join(location, name)

    try:

        if os.path.exists(path):
            return f"Er bestaat al een bestand met de naam {name}."

        with open(path, "w", encoding="utf-8") as file:
            file.write("")

        return f"Bestand '{name}' is aangemaakt op {os.path.basename(location)}."

    except Exception as error:
        print(f"Fout bij bestand maken: {error}")
        return f"Ik kon het bestand '{name}' niet aanmaken."


def list_folder(location_text):

    location = resolve_location(location_text)

    if not location or not os.path.isdir(location):
        return "Dat is geen plek die ik ken. Ik ken bureaublad, downloads, documenten, afbeeldingen, muziek en video's."

    return _list_contents(location, os.path.basename(location))


def list_folder_by_path(path):

    if not os.path.isdir(path):
        return "Ik kon die map niet vinden."

    return _list_contents(path, f"de map '{os.path.basename(path)}'")


def copy_path(source, location_text):

    destination = resolve_location(location_text)

    if not destination:
        return "Dat is geen plek die ik ken. Ik ken bureaublad, downloads, documenten, afbeeldingen, muziek en video's."

    try:

        if os.path.isdir(source):
            shutil.copytree(
                source,
                os.path.join(destination, os.path.basename(source)),
                dirs_exist_ok=True
            )
        else:
            shutil.copy2(source, destination)

        return f"Ik heb {os.path.basename(source)} gekopieerd naar {os.path.basename(destination)}."

    except Exception as error:
        print(f"Fout bij kopiëren: {error}")
        return f"Ik kon {os.path.basename(source)} niet kopiëren."


def move_path(source, location_text):

    destination = resolve_location(location_text)

    if not destination:
        return "Dat is geen plek die ik ken. Ik ken bureaublad, downloads, documenten, afbeeldingen, muziek en video's."

    try:

        shutil.move(source, destination)

        return f"Ik heb {os.path.basename(source)} verplaatst naar {os.path.basename(destination)}."

    except Exception as error:
        print(f"Fout bij verplaatsen: {error}")
        return f"Ik kon {os.path.basename(source)} niet verplaatsen."


def copy_file(filename, location_text):

    found = find_item(filename)

    if not found:
        return f"Ik kan {filename} niet vinden."

    if len(found) > 1:
        return (
            f"Ik heb meerdere bestanden of mappen gevonden met de naam "
            f"{filename}. Ik weet niet welke je bedoelt."
        )

    return copy_path(found[0], location_text)


def move_file(filename, location_text):

    found = find_item(filename)

    if not found:
        return f"Ik kan {filename} niet vinden."

    if len(found) > 1:
        return (
            f"Ik heb meerdere bestanden of mappen gevonden met de naam "
            f"{filename}. Ik weet niet welke je bedoelt."
        )

    return move_path(found[0], location_text)


def send_to_recycle(path):

    try:

        send2trash(path)

        return f"Ik heb {os.path.basename(path)} naar de prullenbak gestuurd."

    except Exception as error:
        print(f"Fout bij prullenbak: {error}")
        return f"Ik kon {os.path.basename(path)} niet naar de prullenbak sturen."


def empty_recycle_bin():

    try:

        # Shemptyrecyclebin via shell32
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 1)

        if result == 0:
            return "De prullenbak is geleegd."

        return "Ik kon de prullenbak niet legen."

    except Exception as error:
        print(f"Fout bij legen prullenbak: {error}")
        return "Ik kon de prullenbak niet legen."