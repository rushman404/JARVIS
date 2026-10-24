"""Bestanden vinden en veilig openen.

- Zoeken gebeurt fuzzy (rapidfuzz) en alleen in een allowlist van
  document-/mediatypes als de gebruiker geen extensie noemt.
- "Standaard weigeren": alleen types uit FILE_ALLOWED_EXTENSIONS worden
  zonder bevestiging geopend. Al het overige (onbekend, ontbrekend of
  extra gevaarlijk) vraagt eerst bevestiging via het pending-mechanisme.
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

# Woorden die via spraak in de opdracht terechtkomen maar niet in de
# bestandsnaam horen ("open het bestand X in downloads"). Alleen gebruikt
# als de eerste zoekpoging niets oplevert.
_OPVULWOORDEN = frozenset({
    "open", "opent", "het", "de", "een", "bestand", "bestanden", "file",
    "in", "uit", "vanuit", "downloads", "download", "map", "folder",
    "alsjeblieft", "graag", "even",
})

# Extensies tellen niet als "woord in de naam": bij een zoekterm zonder
# extensie zoekt find_file() juist in alle toegestane types. Zo blijft
# "jarvis test" over en niet "jarvis test txt".
_EXTENSIE_WOORDEN = frozenset(
    ext.lstrip(".").lower() for ext in FILE_ALLOWED_EXTENSIONS
)


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


def _normalize_extension(path):
    """Genormaliseerde extensie voor veiligheidsbeslissingen.

    Eerst worden spaties/punten aan het einde van het pad weggehaald, dan
    volgt de laatste extensie in kleine letters. Zo wordt "evil.exe." (of
    "evil.exe. ") gewoon ".exe" en kan zo'n bestand niet als onschuldig
    (lege extensie) doorgaan. Bij een dubbele extensie ("factuur.pdf.exe")
    telt de laatste extensie.
    """
    cleaned = path.strip().rstrip(" .")
    return os.path.splitext(cleaned)[1].lower().strip()


def _is_dangerous(path):
    """True als de genormaliseerde extensie als extra gevaarlijk geldt."""
    return _normalize_extension(path) in FILE_DANGEROUS_EXTENSIONS


def _kale_zoekterm(query):
    """Houd alleen woorden over die echt bij een bestandsnaam horen.

    Spraakopdrachten bevatten soms opvulwoorden ("open het bestand X in
    downloads"). Die verlagen de fuzzy score, waardoor een bestaand bestand
    toch niet gevonden wordt. Dit is de terugval-zoekterm.
    """
    woorden = [
        w for w in _normalize(query).split()
        if w not in _OPVULWOORDEN and w not in _EXTENSIE_WOORDEN
    ]
    return " ".join(woorden)


def _bevat_alle_woorden(pad, woorden):
    """True als elk zoekwoord in de bestandsnaam (zonder extensie) zit."""
    naam_woorden = set(_normalize(_stem(os.path.basename(pad))).split())
    return all(w in naam_woorden for w in woorden)


def _score(candidate_name, query_lower, has_extension):
    """Fuzzy score (0-100) tussen een bestandsnaam en de zoekterm.

    Bij een expliciete extensie vergelijken we alleen de naam zónder
    extensie. Anders zou de gedeelde extensie (".exe") de score opkrikken
    en zou "setup.exe" ook "factuur.pdf.exe" voorstellen.
    """
    if has_extension:
        query_stem = _normalize(_stem(query_lower))
        return fuzz.WRatio(query_stem, _normalize(_stem(candidate_name)))
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
    """Opent een pad, maar standaard weigeren.

    Alleen een extensie uit FILE_ALLOWED_EXTENSIONS wordt zonder vraag
    geopend. Alles daarbuiten (onbekend, ontbrekend of extra gevaarlijk)
    vraagt eerst bevestiging via file_open_confirm.
    """
    extension = _normalize_extension(path)

    if extension in FILE_ALLOWED_EXTENSIONS:
        return _start_path(path)

    name = os.path.basename(path)
    folder = os.path.dirname(path)
    set_pending(
        "file_open_confirm",
        {"path": path, "name": name, "folder": folder},
        ttl=CONFIRM_TTL_SECONDS,
    )

    if _is_dangerous(path):
        reden = "dat is een extra gevaarlijk uitvoerbaar bestandstype"
    else:
        reden = "dat is geen standaard veilig bestandstype"

    return (
        f"Ik heb '{name}' gevonden in {folder}, maar {reden}. "
        "Wil je het echt openen? Zeg 'ja' of 'nee'."
    )


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

    # Terugval: geen treffer? Probeer het nog eens met alleen de woorden die
    # bij een bestandsnaam horen (spraak voegt soms "open het bestand ... in
    # downloads" toe, wat de fuzzy score verpest).
    if not matches:
        kaal = _kale_zoekterm(filename)
        if kaal and kaal != _normalize(filename):
            retry = find_file(kaal)
            if retry:
                beperkt = getattr(retry, "limit_reached", False)
                gekozen = list(retry)
                # Alleen bestanden waarin élk woord terugkomt. Zo wint
                # "jarvis_test.txt" van "Test.txt" of "JARVIS.zip".
                woorden = kaal.split()
                if len(woorden) > 1:
                    strikt = [
                        pad for pad in gekozen if _bevat_alle_woorden(pad, woorden)
                    ]
                    if strikt:
                        gekozen = strikt
                matches = gekozen
                if beperkt:
                    limit_note = " Ik heb niet overal kunnen zoeken."

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