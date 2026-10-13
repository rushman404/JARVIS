import os
import shutil
import ctypes
import time
from send2trash import send2trash
from core.confirmation import set_pending
from rapidfuzz import process as fuzzy
from actions.paths import get_known_folder

# Gereserveerde Windows-namen (ook met extensie, bijv. CON.txt).
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5",
    "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
    "LPT6", "LPT7", "LPT8", "LPT9",
}

# Tekens die in een nieuwe bestands-/mapnaam niet mogen.
_ILLEGAL_NAME_CHARS = set('<>:"|?*')


def safe_join(basis, naam):
    """Maakt van (basis, naam) een veilig pad BINNEN basis.

    naam moet één enkele naam zijn: geen padscheidingstekens, geen
    '..', geen stationsletter, geen gereserveerde Windows-naam en geen
    verboden tekens. Daarna wordt met realpath + commonpath gecontroleerd
    dat het eindpad echt binnen 'basis' blijft (ook bij symlinks/junctions).

    Gooit ValueError met een Nederlandse melding bij onveilige invoer.
    """

    if not isinstance(naam, str) or not naam or naam in (".", ".."):
        raise ValueError("Ongeldige naam")

    if "/" in naam or "\\" in naam:
        raise ValueError("Een naam mag geen pad of mappenscheidingsteken bevatten")

    if os.path.splitdrive(naam)[0]:
        raise ValueError("Een naam mag geen stationsletter bevatten")

    if any(char in _ILLEGAL_NAME_CHARS for char in naam):
        raise ValueError("De naam bevat een teken dat niet mag")

    if naam.split(".", 1)[0].strip().upper() in _RESERVED_NAMES:
        raise ValueError("Die naam is gereserveerd door Windows")

    basis_real = os.path.realpath(basis)
    kandidaat = os.path.join(basis_real, naam)
    kandidaat_real = os.path.realpath(kandidaat)

    try:
        binnen = os.path.commonpath([basis_real, kandidaat_real]) == basis_real
    except ValueError:
        # Andere schijf: onmogelijk binnen de basis.
        binnen = False

    if not binnen:
        raise ValueError("Onveilig pad gedetecteerd")

    return kandidaat


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

    return [get_known_folder(folder) for folder in SEARCH_FOLDERS]


def resolve_location(text):

    lower = text.lower()

    for alias in LOCATION_ALIASES:

        if alias[0] in lower:
            return get_known_folder(alias[1])

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

    location = resolve_location(location_text) or get_known_folder("Desktop")

    try:
        path = safe_join(location, name)
    except ValueError:
        return "Die naam kan ik niet gebruiken."

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

    location = resolve_location(location_text) or get_known_folder("Desktop")

    try:
        path = safe_join(location, name)
    except ValueError:
        return "Die naam kan ik niet gebruiken."

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
        dest_path = safe_join(destination, os.path.basename(source))
    except ValueError:
        return "Die naam kan ik niet gebruiken."

    try:

        if os.path.isdir(source):
            if os.path.exists(dest_path):
                return f"Map '{os.path.basename(source)}' bestaat al in {os.path.basename(destination)}."
            shutil.copytree(source, dest_path)
        else:
            if os.path.exists(dest_path):
                return f"Bestand '{os.path.basename(source)}' bestaat al in {os.path.basename(destination)}."
            shutil.copy2(source, dest_path)

        return f"Ik heb {os.path.basename(source)} gekopieerd naar {os.path.basename(destination)}."
    except Exception as error:
        print(f"Fout bij kopiëren: {error}")
        return f"Ik kon {os.path.basename(source)} niet kopiëren."


def move_path(source, location_text):

    destination = resolve_location(location_text)

    if not destination:
        return "Dat is geen plek die ik ken. Ik ken bureaublad, downloads, documenten, afbeeldingen, muziek en video's."

    try:
        dest_path = safe_join(destination, os.path.basename(source))
    except ValueError:
        return "Die naam kan ik niet gebruiken."

    if os.path.exists(dest_path):
        return (
            f"Er staat al iets met de naam {os.path.basename(source)} in "
            f"{os.path.basename(destination)}. Ik heb niets verplaatst."
        )

    try:

        shutil.move(source, dest_path)

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

        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 1)

        if result == 0:
            return "De prullenbak is geleegd."

        return "Ik kon de prullenbak niet legen."

    except Exception as error:
        print(f"Fout bij legen prullenbak: {error}")
        return "Ik kon de prullenbak niet legen."


def rename_file(source_name, new_name):
    found = find_item(source_name)

    if not found:
        return f"Ik kan {source_name} niet vinden."

    if len(found) > 1:
        return f"Ik heb meerdere bestanden of mappen gevonden met de naam {source_name}. Ik weet niet welke je bedoelt."

    source_path = found[0]
    dir_path = os.path.dirname(source_path)

    try:
        dest_path = safe_join(dir_path, new_name.strip())
    except ValueError:
        return "Die naam kan ik niet gebruiken."

    try:
        if os.path.exists(dest_path):
            return f"Er bestaat al iets met de naam {new_name} in die map."

        os.rename(source_path, dest_path)

        return f"Ik heb {os.path.basename(source_path)} hernoemd naar {new_name}."

    except Exception as error:
        print(f"Fout bij hernoemen: {error}")
        return f"Ik kon {source_name} niet hernoemen naar {new_name}."


def open_folder(location_text=""):
    location = resolve_location(location_text) or location_text

    if not location or not os.path.isdir(location):
        return "Dat is geen map die ik ken."

    try:
        os.startfile(location)
        return f"Map '{os.path.basename(location)}' geopend."
    except Exception as error:
        print(f"Fout bij openen map: {error}")
        return f"Ik kon de map niet openen."


def search_files(query):
    results = find_item(query)

    if not results:
        return f"Ik kan '{query}' niet vinden op deze computer."

    lines = []
    for i, path in enumerate(results[:8], 1):
        label = "📁" if os.path.isdir(path) else "📄"
        lines.append(f"{label} {path}")

    summary = "\n".join(lines)

    if len(results) > 8:
        summary += f"\n... en nog {len(results) - 8} meer."

    return f"Gevonden {len(results)} resultaten voor '{query}':\n{summary}"


def get_recent_files(count=10):
    recent_dir = os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Recent"
    )

    if not os.path.isdir(recent_dir):
        return "Kan recente bestanden niet vinden."

    items = []
    for name in os.listdir(recent_dir):
        full = os.path.join(recent_dir, name)
        if os.path.isfile(full):
            items.append((name, os.path.getmtime(full)))

    items.sort(key=lambda x: x[1], reverse=True)

    if not items:
        return "Geen recente bestanden gevonden."

    lines = []
    for name, _ in items[:count]:
        base = os.path.splitext(name)[0]
        lines.append(f"- {base}")

    return "Recente bestanden:\n" + "\n".join(lines)