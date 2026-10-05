"""
JARVIS — Obsidian-laag (Fase 14, Obsidian Stap 1 + 2)
====================================================

Kleine, veilige laag waarmee JARVIS lokale Markdown-bestanden in een
Obsidian-vault kan vinden, lezen en schrijven.

BELANGRIJK — deze module staat VOLLEDIG LOS van memory.json
-----------------------------------------------------------
De bestaande Memory 2.0-opslag (memory/memory.py + memory/store.py) is
ongewijzigd en onafhankelijk van dit bestand:

  * obsidian.py importeert NIETS uit memory.memory of memory.store
  * memory.py / store.py importeren NIETS uit obsidian.py
  * Er is GEEN migratie: memory.json blijft ongewijzigd en leesbaar
  * Er wordt NIETS automatisch opgeslagen. Stap 2 kan memories wél
    omzetten naar notities, maar alleen als een caller dat bewust
    aanroept met dry_run=False. remember() en het hele geheugenpad
    kennen deze module niet.

Geen Obsidian API, geen plugin, geen netwerk. Alleen het lezen en
schrijven van .md-bestanden met de standaardbibliotheek.

Wat de laag kan
---------------
Stap 1 — de vault als bestandslaag:
  * het vault-pad vinden en instellen
  * controleren of het vault bestaat
  * een pad veilig omrekenen naar een pad BINNEN het vault
  * Markdown-notities lezen, schrijven, aanvullen en verwijderen

Stap 2 — memories omzetten naar notities:
  * memory_to_note()        — één memory -> Markdown (schrijft niets)
  * plan_memory_to_vault()  — wat zou er gebeuren (schrijft niets)
  * save_memory_to_vault()  — één memory opslaan, dry_run standaard True
  * plan_all_memories_to_vault()
  * save_all_memories_to_vault() — de hele export, dry_run standaard True

Veiligheidsregels
-----------------
Alles wat een bestandsnaam binnenkomt, wordt eerst gevalideerd:

  1. geen absoluut pad, geen schijfletter, geen UNC-pad
  2. geen '..' en geen '.' als mapnaam (path traversal)
  3. geen verborgen mappen ('.obsidian' en andere punt-mappen)
  4. geen Windows-oordewoorden (CON, PRN, AUX, NUL, COM1..9, LPT1..9)
  5. geen tekens die Windows verbiedt (< > : " | ? *) en geen
     control characters
  6. geen naam die op een spatie of punt eindigt (Windows stript die)
  7. lengtebegrenzing per mapnaam en op de hele notitie
  8. na het omrekenen nog een keer controleren dat het echte pad
     BINNEN het echte vault-pad valt (vangt symlinks/junctions)
  9. bovengrens op de bestandsgrootte bij schrijven
 10. atomair schrijven: een crash laat nooit een halfgeschreven
     notitie achter

Voor stap 2 komt daar nog bij:
 11. een memory-sleutel is vrije tekst en wordt eerst gesluggified,
     zodat er nooit een onveilige bestandsnaam uit kan komen
 12. twee memories met dezelfde slug krijgen een hash-suffix, zodat
     de ene nooit de notitie van de andere overschrijft

Foutafhandeling is bewust gesplitst:

  * Ongeldige invoer (onzeker pad, verboden naam) -> ObsidianError
    Dit is een programmeerfout en moet luid naar boven komen.
  * Runtime-omstandigheden (vault of bestand ontbreekt, IO-fout) ->
    lege waarde (None resp. False). JARVIS mag hier nooit op crashen.

Gebruik
-------
    from memory import obsidian

    obsidian.set_vault_path(r"C:\\JARVIS\\JARVIS Memory")
    obsidian.vault_exists()                       # -> True
    obsidian.write_note("voorkeuren/lamp", "Ik hou van warm licht.")
    obsidian.read_note("voorkeuren/lamp")         # -> "Ik hou van warm licht."

    # Stap 2: eerst nalezen, dan pas echt schrijven.
    import memory.memory as mem

    plan = obsidian.save_all_memories_to_vault(mem.load_memory())
    print(plan["count"])                          # dry_run=True: niets geschreven

    obsidian.save_all_memories_to_vault(mem.load_memory(), dry_run=False)
"""

import hashlib
import json
import ntpath
import os
import re
import tempfile
import unicodedata

from datetime import date


# =============================================================
# Constanten
# =============================================================

# Standaard-vault: de map 'JARVIS Memory' naast het project.
# Dit is waar de vault van de gebruiker staat.
DEFAULT_VAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "JARVIS Memory"
)

# Overschrijft het standaardpad zonder code aan te passen.
ENV_VAULT_VAR = "JARVIS_OBSIDIAN_VAULT"

# Obsidian houdt zelf instellingen in '.obsidian'. JARVIS mag daar
# nooit in schrijven: kapotte vault-config is niet te herstellen.
HIDDEN_PREFIX = "."

OBSIDIAN_CONFIG_DIR = ".obsidian"

MARKDOWN_SUFFIX = ".md"

# Windows-oordewoorden. Een bestand met deze naam is niet aan te maken.
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5",
    "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
    "LPT6", "LPT7", "LPT8", "LPT9",
}

# Tekens die Windows in een bestandsnaam verbiedt. '/' en '\\' worden
# apart behandeld: die zijn de map-scheider.
ILLEGAL_CHARS = set('<>:"|?*')

MAX_SEGMENT_LENGTH = 100
MAX_NOTE_PATH_LENGTH = 200
MAX_NOTE_BYTES = 1_000_000

# Actueel ingestelde vault. None = nog niet ingesteld, dan wordt de
# standaard opgehaald (env-var heeft voorrang).
_vault_path = None


# =============================================================
# Fouten
# =============================================================

class ObsidianError(Exception):
    """
    Ongeldige invoer voor de Obsidian-laag.

    Wordt gegooid voor alles wat een programmeerfout is: een
    absoluut pad, '..', een verboden bestandsnaam, een notitie die
    buiten het vault zou uitkomen. Bewust een exception en geen
    stille False, zodat een fout in een caller niet onopgemerkt
    blijft.
    """


# =============================================================
# Vault-pad
# =============================================================

def set_vault_path(path):
    """
    Stelt het vault-pad in voor deze sessie.

    Geeft het absolute pad terug. Het pad hoeft niet te bestaan;
    dat controleer je daarna met vault_exists().

    Werkt ook zonder argumenten: dan wordt de standaard-vault
    gebruikt, net als bij get_vault_path().
    """

    global _vault_path

    if path is None:
        return reset_vault_path()

    if not isinstance(path, str):
        raise ObsidianError(
            "Vault-pad moet tekst zijn, kreeg: %s" % type(path).__name__
        )

    path = path.strip()

    if not path:
        raise ObsidianError("Vault-pad mag niet leeg zijn.")

    _vault_path = os.path.abspath(os.path.expanduser(path))

    return _vault_path


def reset_vault_path():
    """
    Verget het ingestelde pad en valt terug op de standaard.

    Vooral nodig voor tests: hiermee raakt een test nooit een
    ander pad dan dat hij zelf heeft ingesteld.
    """

    global _vault_path

    _vault_path = None

    return get_vault_path()


def get_vault_path():
    """
    Het huidige vault-pad, altijd absoluut.

    Volgorde van voorkeur:
      1. eerder via set_vault_path() ingesteld
      2. de environment-variable JARVIS_OBSIDIAN_VAULT
      3. de standaard-vault naast het project
    """

    if _vault_path is not None:
        return _vault_path

    from_env = os.environ.get(ENV_VAULT_VAR, "").strip()

    if from_env:
        return os.path.abspath(os.path.expanduser(from_env))

    return DEFAULT_VAULT_PATH


def vault_exists():
    """True als het pad bestaat en een map is. Geen crash bij fouten."""

    try:
        return os.path.isdir(get_vault_path())
    except OSError:
        return False


def is_obsidian_vault():
    """
    True als het pad een map is met een '.obsidian'-map erin.

    Een hint, geen eis: Obsidian maakt '.obsidian' pas aan als de
    map voor het eerst in Obsidian wordt geopend. Gebruik
    vault_exists() voor de echte controle.
    """

    if not vault_exists():
        return False

    return os.path.isdir(os.path.join(get_vault_path(), OBSIDIAN_CONFIG_DIR))


def describe_vault():
    """
    Overzicht van het vault voor logging en tests.

    Geeft een dict met het pad, of het bestaat, of het een
    Obsidian-vault lijkt, en hoeveel notities erin staan.
    """

    path = get_vault_path()

    notes = list_notes() if vault_exists() else []

    return {
        "path": path,
        "exists": vault_exists(),
        "is_obsidian_vault": is_obsidian_vault(),
        "note_count": len(notes),
        "notes": notes,
    }


# =============================================================
# Veilige paden
# =============================================================

def _validate_segment(segment):
    """Controleert één naam (map of bestand) op de veiligheidsregels."""

    if not segment:
        raise ObsidianError("Pad bevat een lege naam.")

    if segment in (".", ".."):
        raise ObsidianError(
            "Pad mag geen '.' of '..' bevatten: %r" % segment
        )

    if segment.startswith(HIDDEN_PREFIX):
        raise ObsidianError(
            "Verborgen naam geweigerd (geen '.'-mappen, zoals %s): %r"
            % (OBSIDIAN_CONFIG_DIR, segment)
        )

    if len(segment) > MAX_SEGMENT_LENGTH:
        raise ObsidianError(
            "Naam te lang (%d > %d tekens): %r"
            % (len(segment), MAX_SEGMENT_LENGTH, segment[:40])
        )

    for char in segment:
        if ord(char) < 32:
            raise ObsidianError(
                "Control character in naam: %r" % segment
            )

        if char in ILLEGAL_CHARS or char in "/\\":
            raise ObsidianError(
                "Verboden teken %r in naam: %r" % (char, segment)
            )

    # Windows stript een spatie of punt aan het einde van een naam.
    if segment != segment.rstrip(" ."):
        raise ObsidianError(
            "Naam mag niet eindigen op een spatie of punt: %r" % segment
        )

    # 'CON', 'CON.txt' en 'con' zijn alle drie verboden.
    stem = segment.split(".", 1)[0].strip().upper()

    if stem in RESERVED_NAMES:
        raise ObsidianError(
            "Windows-oordewoord, niet bruikbaar als bestandsnaam: %r" % segment
        )


def _sanitize_parts(name, suffix=None):
    """
    Gedeelde kern van pad-veiligheid: naam -> lijst met veilige delen.

    Met suffix=''.md krijgt het laatste deel een Markdown-extensie,
    zonder suffix blijft het een kale mapnaam. Zo kan list_notes()
    dezelfde regels gebruiken zonder dat een map '.md' gaat heten.
    """

    if not isinstance(name, str):
        raise ObsidianError(
            "Pad moet tekst zijn, kreeg: %s" % type(name).__name__
        )

    name = name.strip()

    if not name:
        raise ObsidianError("Pad mag niet leeg zijn.")

    if len(name) > MAX_NOTE_PATH_LENGTH:
        raise ObsidianError(
            "Pad te lang (%d > %d tekens)." % (len(name), MAX_NOTE_PATH_LENGTH)
        )

    # ntpath.splitdrive vangt zowel 'C:\\...' als '\\\\server\\share'.
    drive, _ = ntpath.splitdrive(name)

    if drive:
        raise ObsidianError(
            "Pad mag geen absoluut pad of schijfletter zijn: %r" % name
        )

    if name.startswith(("/", "\\")):
        raise ObsidianError(
            "Pad mag niet met een map-scheider beginnen: %r" % name
        )

    segments = [part for part in name.replace("\\", "/").split("/") if part]

    if not segments:
        raise ObsidianError("Pad bevat geen bruikbaar pad: %r" % name)

    for segment in segments:
        _validate_segment(segment)

    if suffix:
        last = segments[-1]

        if not last.lower().endswith(suffix):
            last += suffix
            _validate_segment(last)

        segments[-1] = last

    return segments


def _sanitize_folder(name):
    """
    Maakt van een mapnaam een veilige mapnaam binnen het vault.

    Zelfde regels als een notitie, maar zonder '.md'-extensie: het
    is immers een map en geen bestand.
    """

    return "/".join(_sanitize_parts(name, suffix=None))


def sanitize_note_name(name):
    """
    Maakt van een notitienaam een veilige naam binnen het vault.

    Wat hier gebeurt:
      * '.' en '..' worden geweigerd (geen traversal)
      * de map-scheider wordt '/' (Obsidian gebruikt dat ook)
      * '.md' wordt toegevoegd als het ontbreekt
      * elk stuk wordt gevalideerd tegen de veiligheidsregels

    Geeft de genormaliseerde notitienaam terug, of gooit
    ObsidianError. Geeft nooit een absoluut pad terug en raakt de
    schijf niet aan.
    """

    return "/".join(_sanitize_parts(name, suffix=MARKDOWN_SUFFIX))


def resolve_note_path(name):
    """
    Zet een notitienaam om naar een absoluut pad BINNEN het vault.

    Doet alles wat sanitize_note_name() doet en controleert daarna
    nog op het echte pad (realpath). Dat is de laatste schildmuur:
    een symlink of junction in het vault kan niet alsnog naar een
    plek buiten het vault wijzen.

    Gooit ObsidianError als het pad onveilig is of buiten het vault
    valt. Werkt ook als het vault (nog) niet bestaat.
    """

    safe_name = sanitize_note_name(name)

    vault = get_vault_path()
    full = os.path.abspath(os.path.join(vault, *safe_name.split("/")))

    # Tweede controle op de echte paden. Voorkomt ontsnappen via een
    # symlink/junction die al in het vault staat.
    vault_real = os.path.realpath(vault)
    full_real = os.path.realpath(full)

    try:
        inside = os.path.commonpath([vault_real, full_real]) == vault_real
    except ValueError:
        # Andere schijf: nooit binnen het vault.
        inside = False

    if not inside:
        raise ObsidianError(
            "Pad valt buiten het vault (%s): %r" % (vault, name)
        )

    return full


# =============================================================
# Lezen
# =============================================================

def note_exists(name):
    """
    True als de notitie bestaat en een echt bestand is.

    Gooit ObsidianError bij een ongeldige naam.
    """

    path = resolve_note_path(name)

    return os.path.isfile(path)


def read_note(name):
    """
    Leest een Markdown-notitie en geeft de inhoud terug.

    Geeft None terug als de notitie er niet is, geen bestand is,
    of niet te lezen viel. Een ongeldige naam geeft wel
    ObsidianError, want dat is een fout in de aanroep.

    De tekst komt ongewijzigd terug, alleen zonder de
    afsluitende newline die de meeste editors toevoegen. Zo vergelijk
    je netjes inhoud zonder strikte strijk over de laatste regel.
    """

    path = resolve_note_path(name)

    try:
        with open(path, "r", encoding="utf-8", newline="") as file:
            text = file.read()
    except (FileNotFoundError, IsADirectoryError, OSError, UnicodeDecodeError):
        return None

    if text.endswith("\n"):
        text = text[:-1]

    return text


def list_notes(subfolder=""):
    """
    Geeft de relatieve paden van alle Markdown-notities in het vault.

    Geeft een lijst met '/' als scheider, zoals Obsidian zelf
    toont. Sorteert op naam zodat de volgorde voorspelbaar blijft.

    '.obsidian' en andere verborgen mappen worden overgeslagen.
    Geeft [] terug als het vault niet bestaat of niet leesbaar is.
    """

    vault = get_vault_path()

    if not os.path.isdir(vault):
        return []

    base = vault

    if subfolder:
        # subfolder mag nooit ontsnappen; zelfde regels als notities,
        # maar zonder '.md'-extensie omdat het om een map gaat.
        safe = _sanitize_folder(subfolder)
        base = os.path.abspath(os.path.join(vault, *safe.split("/")))

        if not os.path.isdir(base):
            return []

    found = []

    for current, dirs, files in os.walk(base):
        dirs[:] = sorted(
            name for name in dirs if not name.startswith(HIDDEN_PREFIX)
        )

        for filename in sorted(files):
            if not filename.lower().endswith(MARKDOWN_SUFFIX):
                continue

            if filename.startswith(HIDDEN_PREFIX):
                continue

            full = os.path.join(current, filename)
            relative = os.path.relpath(full, vault)

            found.append(relative.replace(os.sep, "/"))

    return sorted(found)


# =============================================================
# Schrijven
# =============================================================

def _atomic_write_text(path, text):
    """
    Schrijft tekst naar pad, nooit halfgeschreven.

    Zelfde aanpak als memory/store.py: eerst naar een tijdelijk
    bestand in dezelfde map, dan os.replace() om atomair om te
    wisselen. Zo kan een crash of stroomstoring JARVIS nooit een
    halfgeschreven notitie in het vault achterlaten.

    Eigen implementatie opdat deze laag niet aan memory/store.py
    vastzit.
    """

    directory = os.path.dirname(os.path.abspath(path)) or "."

    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return False

    handle = None
    tmp_path = None

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=directory,
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
        )
        handle = os.fdopen(fd, "w", encoding="utf-8", newline="\n")

        handle.write(text)
        handle.flush()

        try:
            os.fsync(handle.fileno())
        except OSError:
            pass

        handle.close()
        handle = None

        os.replace(tmp_path, path)
        tmp_path = None

        return True
    except OSError:
        return False
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def write_note(name, content, overwrite=True, create_subfolders=True):
    """
    Schrijft een Markdown-notitie in het vault.

    Maakt de notitie aan als die er nog niet is, en werkt hem bij
    als die er wel is. Het bestand krijgt een '.md'-extensie als die
    ontbreekt.

    Let op: overschrijven gebeurt ALTIJD alleen als een caller
    dit expliciet aanroept. Er zit geen enkele automatische
    koppeling vanuit het geheugen naar Obsidian; niets in
    memory.py roept deze functie aan.

    Args:
        name:        notitienaam, mag submappen bevatten
                     ("voorkeuren/lamp"). Onveilige namen worden
                     geweigerd met ObsidianError.
        content:     de Markdown-inhoud als tekst
        overwrite:   False -> een bestaande notitie wordt niet
                     overschreven en de functie geeft False
        create_subfolders:
                     False -> een submap die er nog niet is geeft
                     False in plaats van dat hij wordt gemaakt

    Returns:
        True als de notitie is geschreven, anders False. False
        komt o.a. als het vault niet bestaat, de notitie te groot
        is, of create_subfolders=False terwijl de map ontbreekt.
    """

    if not isinstance(content, str):
        raise ObsidianError(
            "Inhoud moet tekst zijn, kreeg: %s" % type(content).__name__
        )

    path = resolve_note_path(name)

    # Nooit stilzwijgend een vault aanmaken: een typefout in het pad
    # zou zomaar een lege map 'JARVIS Memory' in C:\ kunnen maken.
    if not vault_exists():
        return False

    if not overwrite and os.path.exists(path):
        return False

    if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
        return False

    if not create_subfolders:
        directory = os.path.dirname(path)

        if directory and not os.path.isdir(directory):
            return False

    return _atomic_write_text(path, content)


def append_note(name, content, separator="\n\n", create=True):
    """
    Voegt tekst toe aan een bestaande notitie.

    Geeft False terug als de notitie niet bestaat en create=False.
    Anders wordt de notitie aangemaakt met alleen de nieuwe tekst.

    Args:
        name:      notitienaam
        content:   tekst die erachter komt
        separator: wat ertussen komt (standaard een lege regel)
        create:    True -> niet-bestaande notitie wordt aangemaakt

    Returns:
        True als er iets is geschreven, anders False.
    """

    if not isinstance(content, str):
        raise ObsidianError(
            "Inhoud moet tekst zijn, kreeg: %s" % type(content).__name__
        )

    path = resolve_note_path(name)

    if not vault_exists():
        return False

    existing = None

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as file:
                existing = file.read()
        except (OSError, UnicodeDecodeError):
            return False

    if existing is None and not create:
        return False

    if not existing:
        return _atomic_write_text(path, content)

    # Voorkom dat er een blanco regel of newline tussenkruipt.
    body = existing.rstrip("\n")

    return _atomic_write_text(path, body + separator + content)


def delete_note(name):
    """
    Verwijdert een notitie uit het vault.

    Geeft True als het bestand is verwijderd, False als het er niet
    was of niet verwijderd kon worden. Alleen Markdown binnen het
    vault; een ongeldige naam geeft ObsidianError.
    """

    path = resolve_note_path(name)

    try:
        os.remove(path)
        return True
    except OSError:
        return False


# =============================================================
# Markdown-hulp
# =============================================================

def _yaml_scalar(value):
    """
    Maakt een waarde geschikt voor YAML-frontmatter.

    Getallen, booleans en 'gewone' korte tekst gaan ongewijzigd mee.
    Tekst met een dubbele punt, een komma of een koppelteken aan het
    begin wordt tussen aanhalingstekens gezet, anders zou Obsidian
    het verkeerd lezen.
    """

    if isinstance(value, bool):
        return "true" if value else "false"

    if value is None:
        return "null"

    if isinstance(value, (int, float)):
        return str(value)

    text = str(value).strip()

    if not text:
        return '""'

    needs_quotes = (
        ":" in text
        or "#" in text
        or text.startswith(("-", "[", "{", "&", "*", "!", "|", ">", "%", "@", "`"))
        or text.endswith(":")
    )

    if needs_quotes:
        return '"%s"' % text.replace('"', "'")

    return text


def format_note(title, body="", tags=None, category=None, extra=None):
    """
    Zet een memory om in een Markdown-notitie met YAML-frontmatter.

    Pure tekst: er wordt NIETS geschreven. De caller beslist zelf
    of en waar dit terechtkomt. Dat is bewust zo, zodat er in stap 1
    nog geen enkele automatische opslag in de vault kan gebeuren.

    Args:
        title:    titel van de notitie
        body:     inhoud (Markdown)
        tags:     lijst met tags
        category: Memory 2.0-categorie, bijv. "voorkeuren"
        extra:    dict met EXTRA frontmatter-velden, bijv.
                  {"priority": 1.0, "source": "conversation"}.
                  De invoervolgorde blijft bewaard, dus de notitie
                  is reproduceerbaar.

    Returns:
        de volledige notitie als tekst.
    """

    title = str(title).strip() or "Naamloos"

    if isinstance(tags, str):
        tags = [tags]
    elif not tags:
        tags = []

    lines = ["---", "title: %s" % _yaml_scalar(title)]

    if category:
        lines.append("category: %s" % _yaml_scalar(category))

    lines.append("tags: [%s]" % ", ".join(str(tag).strip() for tag in tags))

    if extra:
        for veld, waarde in extra.items():

            # Een lijst gaat als YAML-blocksequence, zodat Obsidian
            # hem als lijst toont en je hem met de hand kunt
            # aanvullen of verkleinen:
            #
            #     related:
            #       - gaming_pc
            #       - monitor
            #
            # Lege lijsten worden helemaal weggelaten: "related:" met
            # niets eronder leest als een lege string, niet als een
            # lege lijst.
            if isinstance(waarde, (list, tuple)):

                if not waarde:
                    continue

                lines.append("%s:" % veld)
                lines.extend("  - %s" % _yaml_scalar(item) for item in waarde)
                continue

            lines.append("%s: %s" % (veld, _yaml_scalar(waarde)))

    lines.append("date: %s" % date.today().isoformat())
    lines.append("---")
    lines.append("")
    lines.append("# %s" % title)
    lines.append("")

    if body:
        lines.append(str(body).strip())
        lines.append("")

    return "\n".join(lines)


# =============================================================
# Memory -> notitie (Fase 14, Obsidian Stap 2)
# =============================================================
#
# Hiermee maakt JARVIS van één memory uit memory.json een
# Markdown-notitie in de vault.
#
# WAT hier NIET gebeurt, en dat is de hele pointe van stap 2:
#
#   * Er wordt NIETS automatisch opgeslagen. De standaard is
#     dry_run=True: je krijgt alleen een plan terug, op schijf
#     verandert er niets.
#   * Er is GEEN koppeling met remember() of met enig ander deel
#     van Memory 2.0. memory.py en store.py blijven volledig
#     onafhankelijk; deze module importeert ze niet.
#   * Er vindt GELEZEN en GESCHREVEN plaats via de laag hierboven,
#     dus met dezelfde pad-veiligheid.
#
# Om echt te schrijven moet een caller dry_run=False meegeven, en
# dan nog overschrijft het niets tenzij overwrite=True ook gezet is.
# Twee lagen beveiliging op rij, dus een onzorgvuldige caller
# kan hooguit een lege vault vullen en nooit een notitie verliezen.
# =============================================================

# Map-layout van het vault: Memory 2.0-categorie -> mapnaam.
# Categorieen die hier niet in staan gaan naar DEFAULT_FOLDER.
CATEGORY_FOLDERS = {
    "voorkeuren": "voorkeuren",
    "pc": "pc",
    "projecten": "projecten",
    "muziek": "muziek",
    "apparaten": "apparaten",
    "algemeen": "algemeen",
}

DEFAULT_FOLDER = "algemeen"

# Velden uit een memory-entry die in de frontmatter of details
# thuishoren. Onbekende velden worden bewust genegeerd: dit is een
# notitie, geen volledige dump van het geheugenbestand.
# De memory-velden die in de frontmatter én in de detailslijst van een
# notitie terechtkomen. Dit is de leesbare helft van het
# metadata-contract uit memory.py (ENTRY_META_KEYS): alles wat je in
# memory.json kunt terugvinden, staat hier ook in de notitie.
#
# `related` staat er NIET bij, omdat dat een lijst is en geen scalar;
# die krijgt een YAML-blocksequence (Zie format_note()). De
# wiki-links onderaan de body komen uit dezelfde echte relaties.
PRIORITY_FIELDS = ("priority", "source", "created", "updated",
                   "usage_count", "last_used")

# Nette Nederlandse labels voor die velden in de detailslijst.
FIELD_LABELS = {
    "priority": "Prioriteit",
    "source": "Bron",
    "created": "Aangemaakt",
    "updated": "Bijgewerkt",
    "usage_count": "Keer gebruikt",
    "last_used": "Laatst gebruikt",
}

# Wat er staat waar een veld leeg is.
FIELD_EMPTY = {
    "priority": "neutraal",
    "source": "onbekend",
    "created": "onbekend",
    "updated": "onbekend",
    "usage_count": "0",
    "last_used": "nog niet gebruikt",
}


def _field_text(veld, waarde):
    """Leesbare tekst voor één memory-veld in de detailslijst."""

    if waarde is None or (isinstance(waarde, str) and not waarde.strip()):
        return FIELD_EMPTY.get(veld, "niet ingesteld")

    return _scalar_text(waarde)


def slugify(text, max_length=60):
    """
    Maakt van vrije tekst een veilige slug voor een bestandsnaam.

    "Favoriete kleur"      -> "favoriete-kleur"
    "voorkeur: kleur!"     -> "voorkeur-kleur"
    "lamp één"             -> "lamp-een"
    "!!!"                  -> "notitie"

    Diacrieten worden weggehaald, alles wat geen letter of cijfer is
    wordt een streepje. Geeft nooit een lege string terug.
    """

    text = str(text).strip().lower()

    # 'é' -> 'e': tekens met een accent losmaken en het teken zelf weggooien.
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )

    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")

    if len(text) > max_length:
        text = text[:max_length].rstrip("-")

    return text or "notitie"


def _short_hash(text):
    """
    Korte, stabiele identificatie van een stuk tekst.

    Wordt alleen gebruikt als twee memories dezelfde slug zouden
    krijgen: zo raakt de ene memory de notitie van de andere niet.
    """

    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:6]


def folder_for_category(category):
    """
    De vault-map die bij een Memory 2.0-categorie hoort.

    Onbekende categorieen belanden in DEFAULT_FOLDER, zodat er nooit
    een notitie buiten de layout terechtkomt.
    """

    key = str(category or "").strip().lower()

    if key in CATEGORY_FOLDERS:
        return CATEGORY_FOLDERS[key]

    return DEFAULT_FOLDER


def note_name_for_memory(key, category=None):
    """
    Het notitiepad (relatief aan het vault) voor een memory-sleutel.

    Geeft bijvoorbeeld "voorkeuren/favoriete-kleur.md".

    De sleutel is vrije tekst uit het geheugen en kan van alles
    bevatten, dus hij wordt eerst gesluggified. Een sleutel die
    helemaal geen slug oplevert wordt alsnog bruikbaar gemaakt.
    """

    folder = folder_for_category(category)
    slug = slugify(key)

    return "%s/%s.md" % (folder, slug)


def format_value(value):
    """
    Maakt de waarde van een memory leesbaar in Markdown.

    Memory 2.0 bewaart van alles: een string, een getal, True/False,
    een lijst of zelfs een dict. Dit maakt daar iets van zonder te
    gokken wat het is.

      "blauw"      -> "blauw"
      True         -> "ja"
      32           -> "32"
      None         -> "niet ingesteld"
      ["a", "b"]   -> een lijstje
      {"a": 1}     -> een lijstje met sleutel: waarde
    """

    if value is None:
        return "niet ingesteld"

    if isinstance(value, bool):
        return "ja" if value else "nee"

    if isinstance(value, str):
        return value.strip() or "niet ingesteld"

    if isinstance(value, dict):
        if not value:
            return "leeg"

        return "\n".join(
            "- %s: %s" % (sleutel, _scalar_text(waarde))
            for sleutel, waarde in value.items()
        )

    if isinstance(value, (list, tuple, set)):
        if not value:
            return "leeg"

        return "\n".join("- %s" % _scalar_text(item) for item in value)

    return str(value)


def _scalar_text(value):
    """Korte tekstvorm van een waarde, voor gebruik in een lijstje."""

    if isinstance(value, bool):
        return "ja" if value else "nee"

    if isinstance(value, (dict, list, tuple)):
        return "(%s)" % type(value).__name__

    text = str(value).strip()

    return text if text else "niet ingesteld"


def _as_entry(memory):
    """
    Accepteert zowel een volledige memory-entry als een kale waarde.

    memory.json bevat entries met een 'value'-veld, maar het is
    handig om hier ook gewoon "blauw" of 42 te kunnen meegeven.
    """

    if isinstance(memory, dict) and "value" in memory:
        return memory

    return {"value": memory}


VALUE_TYPES = ("str", "bool", "int", "float", "list", "dict", "null")


def value_type_name(value):
    """
    De memory-type van een waarde, als naam voor de frontmatter.

    De volgorde van de checks is belangrijk: bool is een subclass van
    int in Python, dus bool moet eerst worden gevangen.

        "blauw"  -> "str"
        True      -> "bool"
        32        -> "int"
        1.0       -> "float"
        ["a","b"] -> "list"
        {"a": 1}  -> "dict"
        None      -> "null"
    """

    if value is None:
        return "null"

    if isinstance(value, bool):
        return "bool"

    if isinstance(value, int):
        return "int"

    if isinstance(value, float):
        return "float"

    if isinstance(value, (list, tuple)):
        return "list"

    if isinstance(value, dict):
        return "dict"

    return "str"


def value_json_text(value):
    """
    Compacte, machine-leesbare kopie van een waarde voor de
    frontmatter.

    Alleen nodig voor niet-'str'-waarden. De leesbare body blijft de
    vorm die een mens in Obsidian ziet en bewerkt; dit veld staat er
    alleen zodat een import het type exact kan terugzetten — ook voor
    waarden waarvan de body-rendering niet eenduidig terug te lezen is
    (een dict met een lijst erin).

    Een lege string betekent: niet bruikbaar of niet nodig.
    """

    if isinstance(value, str) or value is None:
        return ""

    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    except (TypeError, ValueError):
        return ""


def memory_to_note(memory, key=None, category=None, related=None, slug_suffix=""):
    """
    Zet één memory om in een notitie. Pure functie: schrijft niets.

    De frontmatter krijgt twee velden die de typegrens rond de vault
    sluiten:

        value_type : str | bool | int | float | list | dict | null
        value_json : alleen bij niet-'str'-waarden de compacte JSON

    De leesbare body blijft ongewijzigd: `format_value()` levert nog
    steeds "> blauw", "> ja" of "- a: 1".

    De metadata uit memory.json gaat mee naar de frontmatter, zodat een
    notitie het hele contract bevat: `priority`, `source`, `created`,
    `updated`, `usage_count`, `last_used`, de typegrens (`value_type`,
    `value_json`) en de echte `related`-relaties als YAML-lijst.

    Args:
        memory:      een memory-entry uit memory.json, of een kale waarde
        key:         de memory-sleutel; gebruikt als titel en slug.
                     Zonder key valt de functie terug op de waarde.
        category:    Memory 2.0-categorie, bepaalt de map
        related:     OVERSCHRIFT de relaties uit de entry. Standaard is
                     `related` uit de entry zelf: alleen wat er echt in
                     staat. De oude aanroep met alle sleutels uit dezelfde
                     categorie is bewust vervangen — siblings zijn geen
                     relatie.
                     Wat er overblijft verschijnt als wiki-links onderaan,
                     zodat je in Obsidian tussen memories kunt navigeren.
        slug_suffix: extra stukje achter de slug. Wordt gebruikt als twee
                     memories dezelfde slug zouden krijgen.

    Returns:
        Een dict met 'note_name' en 'content', of None als er uit
        deze memory geen notitie te maken valt (lege tekst).
    """

    entry = _as_entry(memory)
    value = entry.get("value")

    if isinstance(value, str) and not value.strip():
        return None

    # Echte relaties: uit de entry, niet uit de categorie.
    if related is None:
        related = list(entry.get("related") or [])

    related = [str(item).strip() for item in related
               if isinstance(item, str) and item.strip()]

    if key is None:
        key = str(value).strip()[:60] or "notitie"

    folder = folder_for_category(category)
    slug = slugify(key) + slug_suffix
    note_name = "%s/%s.md" % (folder, slug)

    title = str(key).strip() or "Naamloos"

    regels = [
        "> %s" % format_value(value).replace("\n", "\n> "),
        "",
        "## Details",
        "",
        "- Sleutel: `%s`" % key,
        "- Categorie: %s" % (str(category).strip() if category else "niet ingesteld"),
    ]

    for veld in PRIORITY_FIELDS:
        if veld in entry:
            regels.append("- %s: %s" % (FIELD_LABELS.get(veld, veld),
                                        _field_text(veld, entry[veld])))

    vorige = entry.get("previous_value")

    if vorige is not None:
        regels.append("- Vorige waarde: %s" % _scalar_text(vorige))

    if entry.get("corrected"):
        regels.append("- Expliciet gecorrigeerd: ja")

    uniek = []

    for sibling in related:
        if sibling != key and sibling not in uniek:
            uniek.append(sibling)

    if uniek:
        regels.extend(["", "## Gerelateerd", ""])
        regels.extend("- [[%s]]" % sibling for sibling in uniek)

    extra = {"memory_key": key, "value_type": value_type_name(value)}

    for veld in PRIORITY_FIELDS:
        if veld in entry:
            extra[veld] = entry[veld]

    # De echte relaties, als lijst. Zo kan een handmatige
    # wijziging in Obsidian weer terugkomen bij memory.json.
    if uniek:
        extra["related"] = sorted(uniek)

    # Typegrens: de leesbare body alleen is niet altijd terug te lezen
    # naar hetzelfde Python-type, dus daar staat een compacte JSON bij.
    json_tekst = value_json_text(value)

    if json_tekst:
        extra["value_json"] = json_tekst

    content = format_note(
        title=title,
        body="\n".join(regels),
        tags=["memory", "memory/%s" % folder, "memory/%s" % slug],
        category=str(category).strip() if category else None,
        extra=extra,
    )

    return {"note_name": note_name, "content": content}


def plan_memory_to_vault(memory, key=None, category=None,
                         related=None, slug_suffix=""):
    """
    Berekent wat er met deze memory zou gebeuren. Schrijft nooit iets.

    Dit is de kern achter dry_run: de volledige notitie-inhoud en
    het bestemmingspad worden al berekend, zodat je kunt nalezen wat
    er zou gebeuren voordat je dry_run=False meegeeft.

    Geeft een plan-dict terug:

        ok            : is dit een bruikbare memory?
        note_name     : het pad dat gebruikt zou worden (of None)
        content       : de volledige notitie (of None)
        action        : "create", "update", "overwrite-blocked",
                        "no-vault" of "skip"
        reason        : toelichting bij skip/fout
        memory_key    : de sleutel
        category      : de categorie
        value         : de waarde, leesbaar gemaakt
    """

    plan = {
        "ok": False,
        "note_name": None,
        "content": None,
        "action": "skip",
        "reason": "",
        "memory_key": key,
        "category": category,
        "value": None,
    }

    if key is not None and (not isinstance(key, str) or not key.strip()):
        plan["reason"] = "sleutel is leeg"

        return plan

    note = memory_to_note(memory, key=key, category=category,
                          related=related, slug_suffix=slug_suffix)

    if note is None:
        plan["reason"] = "geen bruikbare waarde"

        return plan

    plan["ok"] = True
    plan["note_name"] = note["note_name"]
    plan["content"] = note["content"]
    plan["memory_key"] = key
    plan["category"] = category
    plan["value"] = _scalar_text(_as_entry(memory).get("value"))

    # Een onveilige sleutel (met ':' of een Windows-oordewoord) mag
    # nooit stilletjes naar buiten wijzen: dat is een echte fout.
    try:
        resolve_note_path(note["note_name"])
    except ObsidianError as exc:
        plan["ok"] = False
        plan["action"] = "skip"
        plan["reason"] = "onveilige bestandsnaam: %s" % exc

        return plan

    if not vault_exists():
        plan["action"] = "no-vault"
        plan["reason"] = "vault bestaat niet"

        return plan

    if note_exists(note["note_name"]):
        plan["action"] = "update"
    else:
        plan["action"] = "create"

    return plan


def save_memory_to_vault(memory, key=None, category=None,
                         dry_run=True, overwrite=False):
    """
    Zet één memory om in een notitie in het vault.

    LET OP: dry_run staat STANDAARD op True. Dan wordt er niets
    geschreven en krijg je alleen het plan terug. Om echt te schrijven
    moet je dry_run=False meegeven, en dan wordt een bestaande
    notitie alleen overschreven als je ook overwrite=True zet.

    Er zit geen koppeling met remember() of met enig ander deel van
    Memory 2.0: deze functie wordt alleen aangeroepen als een caller
    er bewust om vraagt.

    Args:
        memory:    memory-entry uit memory.json, of een kale waarde
        key:       de memory-sleutel (titel en bestandsnaam)
        category:  Memory 2.0-categorie, bepaalt de map
        dry_run:   True = alleen een plan, schrijft niets (standaard)
        overwrite: bestaande notitie overschrijven (standaard False)

    Returns:
        het plan-dict, aangevuld met 'dry_run' en 'written'.
    """

    plan = plan_memory_to_vault(memory, key=key, category=category)

    plan["dry_run"] = bool(dry_run)
    plan["written"] = False

    if not plan["ok"] or plan["action"] == "no-vault":
        return plan

    # Standaard blijft het bij een plan: er verandert niets op schijf.
    if dry_run:
        return plan

    if plan["action"] == "update" and not overwrite:
        plan["action"] = "overwrite-blocked"
        plan["reason"] = "notitie bestaat al; overschrijven niet gevraagd"

        return plan

    plan["written"] = write_note(plan["note_name"], plan["content"],
                                 overwrite=True)

    if not plan["written"]:
        plan["action"] = "skip"
        plan["reason"] = "schrijven mislukt"

    return plan


def plan_all_memories_to_vault(memories):
    """
    Berekent het plan voor alle memories. Schrijft nooit iets.

    Args:
        memories: het geheugen zoals het uit memory.json komt:
                  {categorie: {sleutel: entry}}

    Geeft een lijst plan-dicts terug, gesorteerd op notitiepad.

    Twee memories kunnen dezelfde slug opleverden ("muziek: liedje"
    en "muziek liedje" worden allebei "muziek-liedje"). Die krijgen
    dan een korte hash-suffix, zodat de ene de notitie van de
    andere niet zou overschrijven.
    """

    if not isinstance(memories, dict):
        return []

    # Eerst alle kandidaten verzamelen.
    kandidaten = []

    for category, inhoud in memories.items():
        if not isinstance(inhoud, dict):
            continue

        sleutels = sorted(s for s in inhoud
                          if isinstance(s, str) and s.strip())

        for sleutel in sleutels:
            kandidaten.append((note_name_for_memory(sleutel, category),
                               sleutel, category, inhoud[sleutel]))

    # Naamsbotsing opvangen: twee memories kunnen dezelfde slug
    # opleverden ("liefde nummer" en "liefde-nummer!"). Die krijgen een
    # korte hash-suffix, zodat de ene de notitie van de andere niet
    # zou overschrijven. De eerste die de naam claimt houdt hem.
    gebruikt = set()
    plannen = []

    for note_name, sleutel, category, entry in kandidaten:
        slug_suffix = ""

        if note_name in gebruikt:
            slug_suffix = "-" + _short_hash(sleutel)

            mapnaam, _, bestandsnaam = note_name.rpartition("/")
            stam = bestandsnaam[:-len(MARKDOWN_SUFFIX)]

            note_name = "%s/%s%s.md" % (mapnaam, stam, slug_suffix)

        gebruikt.add(note_name)

        # Geen related= meer: de wiki-links komen uit de echte
        # `related` van de entry (Stap 7). Alle sleutels uit dezelfde
        # categorie meesturen zou elke memory met iedere andere memory
        # in haar map verbinden, en dat is geen relatie.
        plannen.append(
            plan_memory_to_vault(entry, key=sleutel, category=category,
                                 slug_suffix=slug_suffix)
        )

    return sorted(plannen, key=lambda p: (p["note_name"] or ""))


def save_all_memories_to_vault(memories, dry_run=True, overwrite=False):
    """
    Zet alle memories om in notities. dry_run staat STANDAARD op True.

    Dit is een EXPORT die een caller bewust aanroept. Er is geen
    automatische koppeling met remember(): een onthouden feit komt
    niet in de vault terecht tenzij hier iets aanroept.

    Args:
        memories:  het geheugen uit memory.json
        dry_run:   True = alleen een plan, schrijft niets (standaard)
        overwrite: bestaande notities overschrijven (standaard False)

    Returns:
        Een dict met de plannen, een telling en de lijst van
        daadwerkelijk geschreven notities.
    """

    plannen = plan_all_memories_to_vault(memories)

    for plan in plannen:
        plan["dry_run"] = bool(dry_run)
        plan["written"] = False

    geschreven = []

    if not dry_run:
        for plan in plannen:
            if not plan["ok"] or plan["action"] == "no-vault":
                continue

            if plan["action"] == "update" and not overwrite:
                plan["action"] = "overwrite-blocked"
                plan["reason"] = "notitie bestaat al; overschrijven niet gevraagd"

                continue

            plan["written"] = write_note(plan["note_name"], plan["content"],
                                         overwrite=True)

            if plan["written"]:
                geschreven.append(plan["note_name"])

    telling = {
        "totaal": len(plannen),
        "bruikbaar": sum(1 for p in plannen if p["ok"]),
        "overgeslagen": sum(1 for p in plannen if not p["ok"]),
        "nieuw": sum(1 for p in plannen if p["action"] == "create"),
        "bestaand": sum(1 for p in plannen if p["action"] == "update"),
        "geschreven": len(geschreven),
    }

    return {
        "dry_run": bool(dry_run),
        "written": bool(geschreven),
        "count": telling,
        "notes": geschreven,
        "plans": plannen,
    }

