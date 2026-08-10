import os


FILE_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",

    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",

    ".mp3",
    ".wav",
    ".flac",

    ".pdf",

    ".txt",
    ".doc",
    ".docx",

    ".xls",
    ".xlsx",

    ".ppt",
    ".pptx"
]


def find_file(filename, search_locations=None):

    filename = filename.lower().strip()

    # Als de gebruiker geen extensie heeft gegeven,
    # zoeken we naar bekende bestandstypen.
    has_extension = os.path.splitext(filename)[1] != ""

    if search_locations is None:
        search_locations = [
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~/Videos"),
            os.path.expanduser("~/Pictures"),
        ]

    results = []

    for location in search_locations:

        if not os.path.exists(location):
            continue

        for root, directories, files in os.walk(location):

            for file in files:

                file_lower = file.lower()
                name_without_extension = os.path.splitext(file_lower)[0]

                if has_extension:

                    if file_lower == filename:
                        results.append(os.path.join(root, file))

                else:

                    if name_without_extension == filename:
                        results.append(os.path.join(root, file))

    return results


def open_file(filename):

    results = find_file(filename)

    if not results:
        return f"Ik kan {filename} niet vinden."

    if len(results) > 1:

        print("Meerdere bestanden gevonden:")

        for result in results:
            print(result)

        return (
            f"Ik heb meerdere bestanden gevonden met de naam "
            f"{filename}. Ik weet niet welke je bedoelt."
        )

    try:

        os.startfile(results[0])

        return f"Ik open {os.path.basename(results[0])}."

    except Exception as e:

        print(f"Fout bij openen: {e}")

        return f"Ik kon {filename} niet openen."