"""Bestanden vinden en veilig openen.

- Zoeken gebeurt fuzzy (rapidfuzz) en alleen in een allowlist van
  document-/mediatypes als de gebruiker geen extensie noemt.
- Uitvoerbare/gevaarlijke types (.exe, .bat, ...) worden NOOIT zonder
  expliciete bevestiging geopend.
- Meerdere goede treffers geven een genummerde keuze via het
  pending-mechanisme.
- Het zoeken is begrensd (diepte + tijd) en slaat zware mappen over.
"""
import os
import re
import time

from rapidfuzz import fuzz

from actions.paths import get_known_folder
from core.confirmation import set_pending
from config import (
    CONFIRM_TTL_SECONDS,
    FILE_ALLOWED_EXTENSIONS,
    FILE_DANGEROUS_EXTENSIONS,
    FILE_FUZZY_THRESHOLD,
    FILE_MAX_DEPTH,
    FILE_SEARCH_TIMEOUT_SECONDS,
    FILE_SKIP_DIRS,
)

DEFAULT_SEARCH_FOLDERS = ("Desktop", "Downloads", "Documents", "Videos", "Pictures")

MAX_CHOICES = 3


class FileSearchResults(list):
    """Lijst met gevonden paden + of de zoeklimiet bereikt is."""

    def __init__(self, items=(), limit_reached=False):
        super().__init__(items)
        self.limit_reached = limit_reached


def _normalize(text):
    """Kleine letters, leestekens/underscores weg (voor fuzzy matching)."""
    text = text.lower().replace("_", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _stem(name):
    return os.path.splitext(name)[0]


def _folder_label(path):
    label = os.path.basename(os.path.dirname(path))
    return label or os.path.dirname(path)


def _is_dangerous(path):
    return os.path.splitext(path)[1].lower() in FILE_DANGEROUS_EXTENSIONS


def _score(candidate_name, query_lower, has_extension):
    """Fuzzy score (0-100) tussen een bestandsnaam en de zoekterm."""
    if has_extension:
        query_stem = _normalize(_stem(query_lower))
        full = fuzz.WRatio(_normalize(query_lower), _normalize(candidate_name))
        stem = fuzz.WRatio(query_stem, _normalize(_stem(candidate_name)))
        return max(full, stem)
    return fuzz.WRatio(_normalize(query_lower), _normalize(_stem(candidate_name)))


def find_file_detailed(filename, search_locations=None):
    """Zoekt fuzzy en geeft {matches, limit_reached} terug.

    Zonder extensie wordt alleen in FILE_ALLOWED_EXTENSIONS gezocht;
    met extensie moet die extensie exact kloppen. Beste treffers eerst.
    """
    query = (filename or "").strip()
    if not query:
        return {"matches": [], "limit_reached": False}

    query_lower = query.lower()
    query_ext = os.path.splitext(query_lower)[1]
    has_extension = query_ext != ""

    if search_locations is None:
        search_locations = [get_known_folder(name) for name in DEFAULT_SEARCH_FOLDERS]

    scored = []
    seen = set()
    limit_reached = False
    start = time.monotonic()
    stop = False

    for location in search_locations:

        if stop:
            break

        if not os.path.isdir(location):
            continue

        for root, dirs, files in os.walk(location, topdown=True):

            rel = os.path.relpath(root, location)
            depth = 0 if rel == os.curdir else rel.count(os.sep) + 1

            # Zware/verborgen mappen overslaan.
            dirs[:] = [d for d in dirs if d.lower() not in FILE_SKIP_DIRS]

            if depth > FILE_MAX_DEPTH:
                dirs[:] = []
                continue

            for name in files:

                if time.monotonic() - start > FILE_SEARCH_TIMEOUT_SECONDS:
                    limit_reached = True
                    stop = True
                    break

                ext = os.path.splitext(name)[1].lower()

                if has_extension:
                    if ext != query_ext:
                        continue
                elif ext not in FILE_ALLOWED_EXTENSIONS:
                    continue

                score = _score(name, query_lower, has_extension)

                if score >= FILE_FUZZY_THRESHOLD:
                    full = os.path.join(root, name)
                    if full not in seen:
                        seen.add(full)
                        scored.append((score, full))

            if stop:
                break

    scored.sort(key=lambda item: (-item[0], item[1].lower()))

    return {"matches": [path for _, path in scored], "limit_reached": limit_reached}


def find_file(filename, search_locations=None):
    """Zoekt een bestand en geeft de paden terug (beste treffer eerst)."""
    detailed = find_file_detailed(filename, search_locations)
    return FileSearchResults(detailed["matches"], detailed["limit_reached"])


def _start_path(path):
    try:
        os.startfile(path)
        return f"Ik open {os.path.basename(path)}."
    except Exception as error:
        print(f"Fout bij openen: {error}")
        return f"Ik kon {os.path.basename(path)} niet openen."


def open_path(path):
    """Opent een pad, maar vraagt eerst bevestiging bij gevaarlijke types."""
    if _is_dangerous(path):
        name = os.path.basename(path)
        folder = os.path.dirname(path)
        set_pending(
            "file_open_confirm",
            {"path": path, "name": name, "folder": folder},
            ttl=CONFIRM_TTL_SECONDS,
        )
        return (
            f"Ik heb '{name}' gevonden in {folder}, maar dat is een "
            "uitvoerbaar/gevaarlijk bestandstype. Wil je het echt openen? "
            "Zeg 'ja' of 'nee'."
        )
    return _start_path(path)


def open_confirmed(path):
    """Opent een pad dat de gebruiker al expliciet heeft goedgekeurd."""
    return _start_path(path)


def open_file(filename):

    matches = find_file(filename)

    limit_note = (
        " Ik heb niet overal kunnen zoeken."
        if getattr(matches, "limit_reached", False)
        else ""
    )

    matches = list(matches)

    if not matches:
        return f"Ik kan {filename} niet vinden.{limit_note}"

    if len(matches) > 1:

        top = matches[:MAX_CHOICES]

        set_pending(
            "file_choice",
            {"matches": top, "query": filename},
            ttl=CONFIRM_TTL_SECONDS,
        )

        lines = [
            f"{index}: {os.path.basename(path)} in {_folder_label(path)}"
            for index, path in enumerate(top, 1)
        ]

        return (
            "Ik heb meerdere bestanden gevonden:\n"
            + "\n".join(lines)
            + "\nWelke bedoel je? Geef een nummer."
            + limit_note
        )

    return open_path(matches[0])