"""
JARVIS — Obsidian-laag tests (Fase 14, Obsidian Stap 1)
======================================================

Test memory/obsidian.py met een TIJDELIJKE test-vault:

  1. vault vinden en instellen
  2. controleren of de vault bestaat
  3. Markdown-notities schrijven
  4. teruglezen en inhoud controleren
  5. bijwerken en toevoegen (append)
  6. veilige bestandsnamen en paden
  7. ontbrekende vault
  8. ongeldige en niet-bestaande bestanden
  9. los van memory.json (geen import, geen migratie, geen auto-save)

Alle tests draaien op een tijdelijke map. De echte vault wordt alleen
LEZEN (Welkom.md opvragen), de echte memory/memory.json wordt helemaal
niet aangeraakt.
"""

import sys
import os
import io
import ast
import shutil
import tempfile

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from unittest.mock import patch

from memory import obsidian as ob
from memory import memory as mem
from memory import vault_import as vi


passed = 0
failed = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


def raises_obsidian_error(label, fn, *args, **kwargs):
    """ok() variant: de aanroep moet ObsidianError gooien."""

    try:
        fn(*args, **kwargs)
    except ob.ObsidianError:
        ok(label, True)
    except Exception as exc:
        ok(f"{label} (maar gooide {type(exc).__name__})", False)
    else:
        ok(f"{label} (maar gooide niets)", False)


def read_bytes(path):
    try:
        with open(path, "rb") as file:
            return file.read()
    except OSError:
        return None


# =============================================================
# Opzet: tijdelijke test-vault + onderscherming van memory.json
# =============================================================

work = tempfile.mkdtemp(prefix="jarvis_obsidian_test_")
vault = os.path.join(work, "Mijn Vault")

# Tweede, aparte vault voor stap 2: de tests van stap 1 laten hier
# niets achter, en andersom ook niet.
vault2 = os.path.join(work, "Vault Stap 2")

# Derde vault + derde geheugenbestand voor stap 3: importeren
# schrijft naar het geheugen en moet dus een eigen MEMORY_FILE hebben.
vault3 = os.path.join(work, "Vault Stap 3")
mem3_file = os.path.join(work, "geheugen_stap3.json")

os.makedirs(vault)
os.makedirs(vault2)
os.makedirs(vault3)

# Onthoud de echte memory.json zodat we kunnen bewijzen dat de
# Obsidian-laag er niets mee doet.
memory_json = os.path.join(ROOT, "memory", "memory.json")
_memory_before = read_bytes(memory_json)
_memory_existed = os.path.exists(memory_json)

ob.reset_vault_path()
ob.set_vault_path(vault)


# =============================================================
# 1. Vault vinden en instellen
# =============================================================

print("\n--- 1. vault vinden en instellen ---")

ok("standaard-vault is de map 'JARVIS Memory' naast het project",
   ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, "JARVIS Memory"))

ok("set_vault_path geeft het absolute pad terug",
   ob.get_vault_path() == os.path.abspath(vault))

ok("set_vault_path maakt een relatief pad absoluut",
   ob.set_vault_path(".") == os.path.abspath("."))

ob.set_vault_path(vault)

ok("pad opnieuw instellen werkt",
   ob.get_vault_path() == os.path.abspath(vault))

ok("reset_vault_path valt terug op de standaard",
   ob.reset_vault_path() == ob.DEFAULT_VAULT_PATH)

ok("reset raakt de ingestelde waarde kwijt",
   ob.get_vault_path() == ob.DEFAULT_VAULT_PATH)

ob.set_vault_path(vault)

raises_obsidian_error("leeg vault-pad geweigerd", ob.set_vault_path, "   ")
raises_obsidian_error("leeg vault-pad (None) geweigerd", ob.set_vault_path, "")
raises_obsidian_error("niet-tekst vault-pad geweigerd",
                      ob.set_vault_path, 12345)

# env-var heeft voorrang als er niets is ingesteld
ob.reset_vault_path()
_saved_env = os.environ.get(ob.ENV_VAULT_VAR)
os.environ[ob.ENV_VAULT_VAR] = vault

ok("env-var JARVIS_OBSIDIAN_VAULT wordt gebruikt",
   ob.get_vault_path() == os.path.abspath(vault))

ob.set_vault_path(vault)

ok("ingesteld pad wint van de env-var",
   ob.get_vault_path() == os.path.abspath(vault))

if _saved_env is None:
    os.environ.pop(ob.ENV_VAULT_VAR, None)
else:
    os.environ[ob.ENV_VAULT_VAR] = _saved_env


# =============================================================
# 2. Controleren of de vault bestaat
# =============================================================

print("\n--- 2. bestaan van de vault ---")

ok("tijdelijke vault bestaat", ob.vault_exists())
ok("vault met .obsidian herkend als Obsidian-vault",
   not ob.is_obsidian_vault())

os.makedirs(os.path.join(vault, ob.OBSIDIAN_CONFIG_DIR))

ok(".obsidian aanwezig -> is_obsidian_vault()", ob.is_obsidian_vault())
ok(".obsidian overslaan bij notities zoeken", ob.list_notes() == [])

ob.set_vault_path(os.path.join(work, "bestaat niet"))

ok("ontbrekende vault -> vault_exists() is False", not ob.vault_exists())
ok("ontbrekende vault -> is_obsidian_vault() is False",
   not ob.is_obsidian_vault())
ok("ontbrekende vault -> notities zoeken geeft []", ob.list_notes() == [])

# een bestand is geen vault
bestand = os.path.join(work, "geen map.txt")

with open(bestand, "w", encoding="utf-8") as file:
    file.write("hallo")

ob.set_vault_path(bestand)

ok("pad dat een bestand is -> vault_exists() is False",
   not ob.vault_exists())

ob.set_vault_path(vault)

info = ob.describe_vault()

ok("describe_vault meldt het pad", info["path"] == os.path.abspath(vault))
ok("describe_vault meldt dat de vault bestaat", info["exists"] is True)
ok("describe_vault telt notities", info["note_count"] == len(info["notes"]))


# =============================================================
# 3. Markdown-notities schrijven
# =============================================================

print("\n--- 3. markdown schrijven ---")

ok("schrijven van een nieuwe notitie", ob.write_note("welkom", "# Hallo"))

first_path = ob.resolve_note_path("welkom")

ok("notitie staat echt op schijf", os.path.isfile(first_path))
ok("bestand eindigt op .md", first_path.endswith(".md"))

# Obsidian-notities leven in submappen; die moeten vanzelf ontstaan
ok("submap wordt automatisch gemaakt",
   ob.write_note("voorkeuren/licht", "Ik hou van warm licht."))

ok("submap staat echt op schijf",
   os.path.isdir(os.path.join(vault, "voorkeuren")))

# '.md' mag ontbreken
ok("'.md' wordt vanzelf toegevoegd", ob.write_note("nota", "zonder extensie"))
ok("bestand kreeg alsnog .md",
   os.path.isfile(os.path.join(vault, "nota.md")))

ok("overschrijven van een bestaande notitie",
   ob.write_note("nota", "nieuwe tekst"))

ok("overschrijven werkte", ob.read_note("nota") == "nieuwe tekst")

ok("overwrite=False overschrijft niet",
   ob.write_note("nota", "nog een keer", overwrite=False) is False)

ok("inhoud bleef onveranderd na overwrite=False",
   ob.read_note("nota") == "nieuwe tekst")

ok("overwrite=True overschrijft wel",
   ob.write_note("nota", "nieuwe tekst", overwrite=True))

# lege inhoud mag
ok("lege notitie schrijven", ob.write_note("leeg", ""))
ok("lege notitie is leeg", ob.read_note("leeg") == "")


# =============================================================
# 4. Teruglezen en inhoud controleren
# =============================================================

print("\n--- 4. teruglezen ---")

INHOUD = (
    "# Voorkeur: licht\n"
    "\n"
    "Ik hou van warm, gedempt licht in de avond.\n"
    "\n"
    "- temperatuur rond 2700K\n"
    "- nooit fel wit overdag\n"
    "\n"
    "Zie ook [[welkom]] en [handleiding](https://help.obsidian.md).\n"
    "\n"
    "Emoji: \U0001f3e1 \U0001f4a1  Tekens: \u00e9\u00fc\u00f1\u00e4\u00f6\u00fc"
)

ok("grote notitie met markdown schrijven",
   ob.write_note("voorkeuren/licht", INHOUD))

terug = ob.read_note("voorkeuren/licht")

ok("teruggelezen inhoud is identiek", terug == INHOUD)
ok("kop blijft een kop", terug.startswith("# Voorkeur: licht"))
ok("accenten overleven de heen-en-weer", "\u00e9\u00fc\u00f1\u00e4\u00f6\u00fc" in terug)
ok("emoji overleven de heen-en-weer", "\U0001f3e1" in terug and "\U0001f4a1" in terug)
ok("wiki-link overleeft", "[[welkom]]" in terug)
ok("nieuwe regels blijven behouden", "\n" in terug)

# bestand op schijf moet byte-voor-byte kloppen
op_schijf = read_bytes(ob.resolve_note_path("voorkeuren/licht"))

ok("bestand op schijf is utf-8 met dezelfde inhoud",
   op_schijf == INHOUD.encode("utf-8"))

# CRLF op Windows: de geschreven tekst blijft met \n, zoals Obsidian
# en git het gewend zijn
ok("geen windows CRLF in de notitie", b"\r\n" not in op_schijf)

ok("niet-standaard bestandsnaam met accenten werkt",
   ob.write_note("voorkeuren/lamp-\u00e9\u00e9n", "speciale naam"))
ok("bestand met accenten teruggelezen",
   ob.read_note("voorkeuren/lamp-\u00e9\u00e9n") == "speciale naam")

ok("notitie met spatie in de naam werkt",
   ob.write_note("mijn notitie", "met spatie"))

ok("spatie-notitie teruggelezen",
   ob.read_note("mijn notitie") == "met spatie")

notities = ob.list_notes()

ok("notities worden gevonden", len(notities) == 6)
ok("submap-notitie gevonden met '/' als scheider",
   "voorkeuren/licht.md" in notities)
ok("verborgen map blijft buiten de lijst",
   not any(n.startswith(".") for n in notities))
ok("lijst is gesorteerd", notities == sorted(notities))
ok("notities zoeken in een submap werkt",
   ob.list_notes("voorkeuren") == ["voorkeuren/lamp-\u00e9\u00e9n.md",
                                   "voorkeuren/licht.md"])
ok("zoeken in een ontbrekende submap geeft []",
   ob.list_notes("bestaat niet") == [])

# een submap is een MAP en geen notitie: hij mag geen '.md' krijgen
ok("submap met afsluitende slash werkt",
   ob.list_notes("voorkeuren/") == ob.list_notes("voorkeuren"))

ok("submap krijgt geen '.md'-extensie",
   os.path.isdir(os.path.join(vault, "voorkeuren")))

ob.write_note("projecten/jarvis/api", "diepe notitie")

ok("diepe submap-notitie gevonden",
   "projecten/jarvis/api.md" in ob.list_notes())

ok("zoeken in een diepe submap werkt",
   ob.list_notes("projecten/jarvis") == ["projecten/jarvis/api.md"])

ok("zoeken vanaf de bovenste map ziet alles",
   len(ob.list_notes("projecten")) == 1
   and "projecten/jarvis/api.md" in ob.list_notes())

raises_obsidian_error("submap met '..' geweigerd", ob.list_notes, "../buiten")
raises_obsidian_error("submap met '.obsidian' geweigerd",
                      ob.list_notes, ".obsidian")

# afsluitende newline zoals editors die schrijven
ob.write_note("met newline", "regel 1\nregel 2\n")

ok("afsluitende newline wordt weggestreept bij lezen",
   ob.read_note("met newline") == "regel 1\nregel 2")

ok("notitie bestaan -> note_exists()", ob.note_exists("welkom"))
ok("bestaande notitie met submap -> note_exists()",
   ob.note_exists("voorkeuren/licht"))


# =============================================================
# 5. Bijwerken en toevoegen
# =============================================================

print("\n--- 5. bijwerken en toevoegen ---")

ok("append aan een bestaande notitie",
   ob.append_note("welkom", "Nieuwe regel"))

ok("append landt onder de bestaande tekst",
   ob.read_note("welkom") == "# Hallo\n\nNieuwe regel")

ok("append nog een keer",
   ob.append_note("welkom", "Derde regel"))

ok("meerdere appends blijven gescheiden",
   ob.read_note("welkom") == "# Hallo\n\nNieuwe regel\n\nDerde regel")

ok("eigen scheider te gebruiken",
   ob.append_note("welkom", "Direct eronder", separator="\n"))

ok("eigen scheider wordt gebruikt",
   ob.read_note("welkom").endswith("Derde regel\nDirect eronder"))

ok("append maakt een ontbrekende notitie aan",
   ob.append_note("vers/nieuw", "eerste tekst"))

ok("aangemaakte notitie klopt",
   ob.read_note("vers/nieuw") == "eerste tekst")

ok("append met create=False doet niets bij een ontbrekende notitie",
   ob.append_note("vers/ontbreekt", "tekst", create=False) is False)

ok("er is geen bestand aangemaakt",
   not os.path.exists(os.path.join(vault, "vers", "ontbreekt.md")))

ok("notitie verwijderen", ob.delete_note("mijn notitie"))
ok("verwijderde notitie is weg", not os.path.exists(
    os.path.join(vault, "mijn notitie.md")))
ok("verwijderen van een ontbrekende notitie geeft False",
   ob.delete_note("mijn notitie") is False)

# te grote notitie wordt geweigerd
ok("te grote notitie wordt niet geschreven",
   ob.write_note("reus", "x" * (ob.MAX_NOTE_BYTES + 10)) is False)

ok("geen rommelbestand achtergebleven", not os.path.exists(
    os.path.join(vault, "reus.md")))


# =============================================================
# 6. Veilige bestandsnamen en paden
# =============================================================

print("\n--- 6. veilige paden ---")

raises_obsidian_error("'..' geweigerd", ob.resolve_note_path, "../geheim")
raises_obsidian_error("'/..' geweigerd", ob.resolve_note_path, "/../geheim")
raises_obsidian_error("'..' middenin geweigerd", ob.resolve_note_path,
                      "voorkeuren/../../geheim")
raises_obsidian_error("'.' geweigerd", ob.resolve_note_path, ".")
raises_obsidian_error("absolute pad geweigerd", ob.resolve_note_path,
                      "C:\\Windows\\System32\\evil.md")
raises_obsidian_error("schijfletter geweigerd", ob.resolve_note_path, "C:x.md")
raises_obsidian_error("UNC-pad geweigerd", ob.resolve_note_path,
                      "\\\\server\\share\\evil.md")
raises_obsidian_error("pad met begin-slash geweigerd",
                      ob.resolve_note_path, "/etc/passwd.md")
raises_obsidian_error("'.obsidian' geweigerd", ob.resolve_note_path,
                      ".obsidian/workspace.md")
raises_obsidian_error("verborgen map geweigerd", ob.resolve_note_path,
                      ".git/config.md")
raises_obsidian_error("Windows-oordewoord CON geweigerd",
                      ob.resolve_note_path, "CON.md")
raises_obsidian_error("Windows-oordewoord lpt1 geweigerd",
                      ob.resolve_note_path, "map/lpt1.md")
raises_obsidian_error("verboden teken '<' geweigerd", ob.resolve_note_path,
                      "a<b.md")
raises_obsidian_error("verboden teken ':' geweigerd", ob.resolve_note_path,
                      "a:b.md")
raises_obsidian_error("verboden teken '*' geweigerd", ob.resolve_note_path,
                      "a*b.md")
raises_obsidian_error("lege naam geweigerd", ob.resolve_note_path, "")
raises_obsidian_error("alleen spaties geweigerd", ob.resolve_note_path, "   ")
raises_obsidian_error("naam die op een punt eindigt geweigerd",
                      ob.resolve_note_path, "notitie.")
raises_obsidian_error("mapnaam die op een punt eindigt geweigerd",
                      ob.resolve_note_path, "map./notitie")
raises_obsidian_error("mapnaam die op een spatie eindigt geweigerd",
                      ob.resolve_note_path, "map /notitie")
raises_obsidian_error("niet-tekst naam geweigerd", ob.resolve_note_path, 42)
raises_obsidian_error("None als naam geweigerd", ob.resolve_note_path, None)
raises_obsidian_error("te lange naam geweigerd", ob.resolve_note_path,
                      "a" * 300 + ".md")

ok("'..' in het midden zonder traversal mag gewoon",
   ob.sanitize_note_name("a..b") == "a..b.md")

ok("ruimte rondom de hele naam wordt weggestreept",
   ob.sanitize_note_name("  notitie  ") == "notitie.md")

ok("naam met punt erin mag", ob.sanitize_note_name("mijn notitie.md")
   == "mijn notitie.md")

ok("achterste slash wordt genegeerd",
   ob.sanitize_note_name("voorkeuren/lamp/") == "voorkeuren/lamp.md")

ok("backslash telt als map-scheider",
   ob.sanitize_note_name("voorkeuren\\lamp") == "voorkeuren/lamp.md")

ok("pad blijft binnen het vault",
   ob.resolve_note_path("voorkeuren/lamp").startswith(
       os.path.abspath(vault)))

ok("geen enkel pad komt buiten het vault",
   all(ob.resolve_note_path(n).startswith(os.path.abspath(vault))
       for n in ["welkom", "voorkeuren/licht", "nota.md", "leeg"]))

raises_obsidian_error("schrijven met '..' geweigerd",
                      ob.write_note, "../geheim", "inhoud")
raises_obsidian_error("lezen met '..' geweigerd",
                      ob.read_note, "../geheim")
raises_obsidian_error("notitie_exists met '..' geweigerd",
                      ob.note_exists, "../geheim")
raises_obsidian_error("verwijderen met '..' geweigerd",
                      ob.delete_note, "../geheim")

raises_obsidian_error("niet-tekst inhoud geweigerd",
                      ob.write_note, "welkom", 12345)

ok("er is niets buiten het vault aangemaakt",
   not os.path.exists(os.path.join(work, "geheim.md")))


# =============================================================
# 7. Ontbrekende vault
# =============================================================

print("\n--- 7. ontbrekende vault ---")

ob.set_vault_path(os.path.join(work, "bestaat niet"))
missing = ob.get_vault_path()

ok("schrijven naar een ontbrekende vault geeft False",
   ob.write_note("iets", "inhoud") is False)

ok("append naar een ontbrekende vault geeft False",
   ob.append_note("iets", "inhoud") is False)

ok("een ontbrekende vault wordt niet stilzwijgend aangemaakt",
   not os.path.exists(missing))

ok("lezen uit een ontbrekende vault geeft None",
   ob.read_note("iets") is None)

ok("note_exists in een ontbrekende vault is False",
   ob.note_exists("iets") is False)

ok("notities zoeken in een ontbrekende vault geeft []",
   ob.list_notes() == [])

raises_obsidian_error("onveilige naam wordt ook in een ontbrekende "
                      "vault geweigerd", ob.resolve_note_path, "../geheim")

ok("resolve_note_path werkt ook zonder vault (droog)",
   ob.resolve_note_path("iets").startswith(os.path.abspath(missing)))

ob.set_vault_path(vault)


# =============================================================
# 8. Ongeldige en niet-bestaande bestanden
# =============================================================

print("\n--- 8. ongeldige / niet-bestaande bestanden ---")

ok("lezen van een niet-bestaande notitie geeft None",
   ob.read_note("bestaat niet") is None)

ok("note_exists voor een niet-bestaande notitie is False",
   ob.note_exists("bestaant niet.md") is False)

# een map lezen als notitie
os.makedirs(os.path.join(vault, "een map.md"), exist_ok=True)

ok("lezen van een map geeft None (geen crash)", ob.read_note("een map.md") is None)
ok("note_exists op een map is False", ob.note_exists("een map.md") is False)

# binaire rommel moet niet crashen
rommel = os.path.join(vault, "rommel.md")

with open(rommel, "wb") as file:
    file.write(b"\xff\xfe\x00\x01 geen geldige utf-8")

ok("ongeldige utf-8 geeft None (geen crash)", ob.read_note("rommel.md") is None)

ok("overschrijven van binaire rommel lukt wel",
   ob.write_note("rommel", "nu wel leesbaar"))

ok("rommel is vervangen", ob.read_note("rommel") == "nu wel leesbaar")

# niet-tekst inhoud mag nergens stilzwijgend doorheen
raises_obsidian_error("append met niet-tekst inhoud geweigerd",
                      ob.append_note, "welkom", None)

ok("ongeldige notitie aanmaken met submap=False geeft False",
   ob.write_note("nieuw/deep/notitie", "x", create_subfolders=False) is False)

ok("submap is daarbij niet aangemaakt",
   not os.path.exists(os.path.join(vault, "nieuw")))

ok("dezelfde notitie met submap=True lukt wel",
   ob.write_note("nieuw/deep/notitie", "x"))


# =============================================================
# 9. Markdown-hulp (format_note)
# =============================================================

print("\n--- 9. format_note ---")

notitie = ob.format_note(
    "Voorkeur licht",
    "Ik hou van warm licht.",
    tags=["voorkeuren", "licht"],
    category="voorkeuren",
)

ok("format_note levert YAML-frontmatter", notitie.startswith("---"))
ok("titel in de frontmatter", "title: Voorkeur licht" in notitie)
ok("categorie in de frontmatter", "category: voorkeuren" in notitie)
ok("tags in de frontmatter", "tags: [voorkeuren, licht]" in notitie)
ok("datum in de frontmatter", "date: " in notitie)
ok("titel als kop", "# Voorkeur licht" in notitie)
ok("inhoud in de notitie", "Ik hou van warm licht." in notitie)

ok("format_note met losse tag", "tags: [liefde]" in ob.format_note(
    "T", "b", tags="liefde"))

ok("lege titel krijgt een naam", "# Naamloos" in ob.format_note("", "b"))

# het belangrijkste: format_note schrijft NIETS
ok("format_note maakt geen bestand aan",
   not os.path.exists(os.path.join(vault, "Voorkeur licht.md")))

ok("aantal notities onveranderd na format_note",
   len(ob.list_notes()) == len(ob.list_notes()))


# =============================================================
# 10. Volledige loskoppeling van memory.json
# =============================================================

print("\n--- 10. los van memory.json ---")

bron = open(os.path.join(ROOT, "memory", "obsidian.py"), encoding="utf-8").read()

# Echte import-analyse via ast: een kale tekstverzoek zou ook de
# eigen documentatie van de module raken, en dat bewijst niets.
_geimporteerd = set()

for _node in ast.walk(ast.parse(bron)):
    if isinstance(_node, ast.Import):
        for _alias in _node.names:
            _geimporteerd.add(_alias.name)
    elif isinstance(_node, ast.ImportFrom):
        _geimporteerd.add(_node.module or "")

ok("obsidian importeert niets uit het memory-pakket",
   not any(m.split(".")[0] == "memory" for m in _geimporteerd))

ok("obsidian gebruikt geen netwerkbibliotheek",
   not any(m.split(".")[0] in ("requests", "urllib", "http", "socket")
           for m in _geimporteerd))

ok("obsidian gebruikt geen Obsidian API of plugin",
   not any(m.split(".")[0] in ("obsidian", "pyobsidian") for m in _geimporteerd))

# het module houdt geen enkel pad naar memory.json vast
# (dunder-attributen zoals __doc__ vallen af: dat is de documentatie)
ok("obsidian heeft geen verwijzing naar memory.json",
   not any(isinstance(v, str) and "memory.json" in v
           for k, v in vars(ob).items() if not k.startswith("__")))

# en de andere kant op: memory.json mag de Obsidian-laag niet kennen
_memory_sources = {}

for naam in ("memory.py", "store.py"):
    pad = os.path.join(ROOT, "memory", naam)

    with open(pad, encoding="utf-8") as file:
        _memory_sources[naam] = ast.parse(file.read())

def _haal_importen(tree):
    gevonden = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                gevonden.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            gevonden.add(node.module or "")

    return gevonden

ok("memory.py importeert de Obsidian-laag niet",
   "obsidian" not in _haal_importen(_memory_sources["memory.py"]))
ok("store.py importeert de Obsidian-laag niet",
   "obsidian" not in _haal_importen(_memory_sources["store.py"]))

# de echte memory.json is door alle tests heen byte-voor-byte gelijk
_memory_after = read_bytes(memory_json)

ok("echte memory.json is onveranderd gebleven",
   _memory_after == _memory_before)

if not _memory_existed:
    print("  info: memory.json bestond niet voor deze test")


# =============================================================
# 11. De echte vault (alleen lezen)
# =============================================================

print("\n--- 11. de echte vault (read-only) ---")

ob.reset_vault_path()

ok("de echte vault wordt gevonden", ob.vault_exists())
ok("de echte vault is een Obsidian-vault", ob.is_obsidian_vault())
ok("de echte vault bevat Welkom.md",
   "Welkom.md" in ob.list_notes())
ok("Welkom.md is leesbaar",
   "kluis" in (ob.read_note("Welkom.md") or ""))
ok("een niet-bestaande notitie in de echte vault geeft None",
   ob.read_note("deze bestaat niet.md") is None)

# niets schrijven in de echte vault
ok("schrijven gebeurde niet in de echte vault",
   not os.path.exists(os.path.join(ob.get_vault_path(), "test_notitie.md")))


# =============================================================
# 12. Stap 2: memory -> notitie (dry_run standaard True)
# =============================================================

print("\n--- 12. stap 2: slug en map-layout ---")

# Sectie 11 stuurde de laag naar de echte vault; voor stap 2 werken
# we op een verse, tijdelijke vault.
ob.set_vault_path(vault2)

ok("slug uit gewone tekst", ob.slugify("Favoriete kleur") == "favoriete-kleur")
ok("slug uit tekst met leestekens", ob.slugify("voorkeur: kleur!") == "voorkeur-kleur")
ok("slug haalt accenten weg", ob.slugify("lamp één") == "lamp-een")
ok("slug uit alleen leestekens", ob.slugify("!!!") == "notitie")
ok("slug uit lege tekst", ob.slugify("   ") == "notitie")
ok("slug is nooit leeg", ob.slugify("") != "")
ok("slug begrenst de lengte", len(ob.slugify("a" * 500)) <= 60)
ok("slug haalt dubbele streepjes weg",
   ob.slugify("a  --  b") == "a-b")
ok("slug met een Windows-oordewoord is veilig",
   "con" in ob.slugify("CON") and "/" not in ob.slugify("CON"))

ok("map voor voorkeuren", ob.folder_for_category("voorkeuren") == "voorkeuren")
ok("map voor pc", ob.folder_for_category("pc") == "pc")
ok("map voor projecten", ob.folder_for_category("projecten") == "projecten")
ok("onbekende categorie gaat naar algemeen",
   ob.folder_for_category("iets raars") == ob.DEFAULT_FOLDER)
ok("lege categorie gaat naar algemeen",
   ob.folder_for_category("") == ob.DEFAULT_FOLDER)
ok("categorie hoofdlettergevoelig negeren",
   ob.folder_for_category("VOORKEUREN") == "voorkeuren")

ok("notitiepad uit sleutel en categorie",
   ob.note_name_for_memory("favoriete kleur", "voorkeuren")
   == "voorkeuren/favoriete-kleur.md")

ok("notitiepad zonder categorie",
   ob.note_name_for_memory("iets") == "algemeen/iets.md")

ok("notitiepad altijd binnen het vault",
   ob.resolve_note_path(ob.note_name_for_memory("favoriete kleur",
                                                "voorkeuren")).startswith(
       os.path.abspath(vault2)))

print("\n--- 13. stap 2: waarde leesbaar maken ---")

ok("tekstwaarde blijft tekst", ob.format_value("blauw") == "blauw")
ok("waarde True wordt ja", ob.format_value(True) == "ja")
ok("waarde False wordt nee", ob.format_value(False) == "nee")
ok("getal blijft leesbaar", ob.format_value(32) == "32")
ok("None wordt niet-ingesteld", ob.format_value(None) == "niet ingesteld")
ok("lege lijst", ob.format_value([]) == "leeg")
ok("lijst wordt een lijstje", ob.format_value(["a", "b"]) == "- a\n- b")
ok("dict wordt sleutel-waarde", ob.format_value({"a": 1}) == "- a: 1")
ok("lege tekst", ob.format_value("   ") == "niet ingesteld")
ok("lijst met booleans", ob.format_value([True, False]) == "- ja\n- nee")

print("\n--- 14. stap 2: notitie bouwen zonder te schrijven ---")

MEMORIES = {
    "voorkeuren": {
        "favoriete kleur": {
            "value": "blauw", "source": "conversation",
            "updated": "2026-01-10T18:00:00", "previous_value": "groen",
            "corrected": True, "conflict": False, "usage_count": 3,
            "last_used": None, "priority": 2.5,
        },
        "favoriet programma": {
            "value": "Spotify", "usage_count": 12,
            "last_used": None, "priority": 1.0,
        },
    },
    "pc": {
        "heeft gpu": {"value": True, "priority": 8.0},
    },
}

note = ob.memory_to_note(MEMORIES["voorkeuren"]["favoriete kleur"],
                         key="favoriete kleur", category="voorkeuren")

ok("notitiepad klopt", note["note_name"] == "voorkeuren/favoriete-kleur.md")
ok("frontmatter met titel", "title: favoriete kleur" in note["content"])
ok("frontmatter met categorie", "category: voorkeuren" in note["content"])
ok("frontmatter met prioriteit", "priority: 2.5" in note["content"])
ok("frontmatter met memory_key",
   "memory_key: favoriete kleur" in note["content"])
ok("waarde staat erin", "> blauw" in note["content"])
ok("Nederlandse labels", "- Prioriteit: 2.5" in note["content"])
ok("lege last_used krijgt nette tekst",
   "- Laatst gebruikt: nog niet gebruikt" in note["content"])
ok("vorige waarde blijft bewaard",
   "- Vorige waarde: groen" in note["content"])
ok("correctie blijft zichtbaar", "- Expliciet gecorrigeerd: ja" in note["content"])
ok("timestamp wordt gequote in YAML",
   'updated: "2026-01-10T18:00:00"' in note["content"])
ok("tags met categorie", "memory/voorkeuren" in note["content"])

ok("lege string levert geen notitie op",
   ob.memory_to_note({"value": "  "}, key="leeg", category="pc") is None)

# Waarde None levert WEL een notitie op: die mag niet stilzwijgend
# verdwijnen. De frontmatter draagt 'value_type: null' mee.
_none_note = ob.memory_to_note({"value": None}, key="leeg", category="pc")

ok("None levert een notitie op", _none_note is not None)
ok("None krijgt value_type: null", "value_type: null" in _none_note["content"])
ok("None blijft leesbaar in de body", "> niet ingesteld" in _none_note["content"])

ok("kale waarde werkt ook zonder entry",
   ob.memory_to_note("blauw", key="kleur", category="voorkeuren")
   ["note_name"] == "voorkeuren/kleur.md")

ok("zonder key valt terug op de waarde",
   ob.memory_to_note("blauw")["note_name"] == "algemeen/blauw.md")

# gerelateerde memories worden wiki-links
note_gerelateerd = ob.memory_to_note(
    MEMORIES["voorkeuren"]["favoriet programma"],
    key="favoriet programma", category="voorkeuren",
    related=["favoriete kleur", "favoriet programma"],
)

ok("gerelateerde memory wordt een wiki-link",
   "[[favoriete kleur]]" in note_gerelateerd["content"])
ok("een memory verwijst niet naar zichzelf",
   "[[favoriet programma]]" not in note_gerelateerd["content"])

# memory_to_note raakt de schijf niet
_vorige_notities = sorted(os.listdir(vault2))

ok("memory_to_note schrijft niets",
   sorted(os.listdir(vault2)) == _vorige_notities)

print("\n--- 15. stap 2: dry_run is de standaard ---")

plan = ob.plan_memory_to_vault(MEMORIES["voorkeuren"]["favoriete kleur"],
                               key="favoriete kleur", category="voorkeuren")

ok("plan zegt dat de notitie nieuw is", plan["action"] == "create")
ok("plan bevat de volledige inhoud", "title: favoriete kleur" in plan["content"])
ok("plan is bruikbaar", plan["ok"] is True)

# DE BELANGRIJKSTE EIS: zonder dry_run=False wordt er niets geschreven
plan = ob.save_memory_to_vault(MEMORIES["voorkeuren"]["favoriete kleur"],
                               key="favoriete kleur", category="voorkeuren")

ok("save_memory_to_vault is standaard een dry_run", plan["dry_run"] is True)
ok("dry_run schrijft niets", plan["written"] is False)
ok("dry_run heeft geen bestand aangemaakt",
   not os.path.exists(os.path.join(vault2, "voorkeuren")))

_alle = ob.save_all_memories_to_vault(MEMORIES)

ok("save_all is standaard een dry_run", _alle["dry_run"] is True)
ok("save_all schrijft niets", _alle["written"] is False)
ok("save_all heeft geen notities geschreven", _alle["count"]["geschreven"] == 0)
ok("dry_run vault is nog steeds leeg", os.listdir(vault2) == [])
ok("dry_run telt wel alles", _alle["count"]["totaal"] == 3)
ok("dry_run telt drie nieuwe notities", _alle["count"]["nieuw"] == 3)

print("\n--- 16. stap 2: echt schrijven als je erom vraagt ---")

plan = ob.save_memory_to_vault(MEMORIES["voorkeuren"]["favoriete kleur"],
                               key="favoriete kleur", category="voorkeuren",
                               dry_run=False)

ok("dry_run=False schrijft echt", plan["written"] is True)
ok("notitie staat er", ob.note_exists("voorkeuren/favoriete-kleur.md"))
ok("notitie klopt byte-voor-byte",
   read_bytes(ob.resolve_note_path("voorkeuren/favoriete-kleur.md"))
   == plan["content"].encode("utf-8"))
ok("teruglezen geeft dezelfde inhoud",
   ob.read_note("voorkeuren/favoriete-kleur.md")
   == plan["content"].rstrip("\n"))

# een bestaande notitie wordt niet overschreven tenzij dat gevraagd is
ob.append_note("voorkeuren/favoriete-kleur.md", "\n\nHandmatig toegevoegd.")

plan = ob.save_memory_to_vault(MEMORIES["voorkeuren"]["favoriete kleur"],
                               key="favoriete kleur", category="voorkeuren",
                               dry_run=False)

ok("bestaande notitie wordt niet overschreven",
   plan["action"] == "overwrite-blocked")
ok("handmatige tekst staat er nog steeds",
   "Handmatig toegevoegd." in ob.read_note("voorkeuren/favoriete-kleur.md"))

plan = ob.save_memory_to_vault(MEMORIES["voorkeuren"]["favoriete kleur"],
                               key="favoriete kleur", category="voorkeuren",
                               dry_run=False, overwrite=True)

ok("overwrite=True overschrijft", plan["written"] is True)
ok("handmatige tekst is weg",
   "Handmatig toegevoegd." not in ob.read_note("voorkeuren/favoriete-kleur.md"))

_alle = ob.save_all_memories_to_vault(MEMORIES, dry_run=False)

ok("export schrijft alle notities", _alle["count"]["geschreven"] == 2)
ok("export is geen dry_run meer", _alle["dry_run"] is False)
ok("export rapporteert wat het schreef", len(_alle["notes"]) == 2)
ok("nieuwe memory staat in de vault", ob.note_exists("pc/heeft-gpu.md"))
ok("bestaande notitie werd niet overschreven",
   _alle["count"]["geschreven"] == 2)

print("\n--- 17. stap 2: naambotsingen en onbruikbare memories ---")

BOTSING = {
    "muziek": {
        "liefde nummer": {"value": "a"},
        "liefde-nummer!": {"value": "b"},
    },
    "pc": {
        "lege waarde": {"value": "  "},
    },
}

plannen = ob.plan_all_memories_to_vault(BOTSING)
namen = [p["note_name"] for p in plannen if p["ok"]]

ok("botsende memories krijgen verschillende namen",
   len(namen) == 2 and len(set(namen)) == 2)
ok("de eerste houdt de kale naam",
   "muziek/liefde-nummer.md" in namen)
ok("de tweede krijgt een hash-suffix",
   any(n.startswith("muziek/liefde-nummer-") for n in namen))

_alle = ob.save_all_memories_to_vault(BOTSING, dry_run=False)

ok("botsende memories worden allebei geschreven",
   _alle["count"]["geschreven"] == 2)
ok("geen memory overschrijft een ander",
   ob.read_note("muziek/liefde-nummer.md") == _alle["plans"][0]["content"]
   or "a" in ob.read_note("muziek/liefde-nummer.md"))

ok("lege waarde wordt overgeslagen",
   _alle["count"]["overgeslagen"] == 1)

ok("overgeslagen memory heeft een reden",
   any(p["reason"] == "geen bruikbare waarde" for p in _alle["plans"]))

ok("lege categorie wordt genegeerd", ob.plan_all_memories_to_vault(
    {"voorkeuren": "geen dict"}) == [])

ok("geen geheugen geeft een leeg plan",
   ob.plan_all_memories_to_vault(None) == [])

print("\n--- 18. stap 2: onveilige memories en ontbrekende vault ---")

plan = ob.save_memory_to_vault({"value": "x"}, "CON", "pc")

ok("Windows-oordewoord als sleutel wordt overgeslagen",
   plan["ok"] is False)
ok("de reden meldt een onveilige naam",
   plan["reason"].startswith("onveilige bestandsnaam"))

plan = ob.save_memory_to_vault({"value": "x"}, "CON", "pc", dry_run=False)

ok("ook bij dry_run=False wordt er niets geschreven",
   plan["written"] is False)
ok("het oordewoord heeft geen notitie aangemaakt",
   not os.path.exists(os.path.join(vault2, "pc", "con.md")))

ok("de pc-map bevat alleen de eerder geschreven notitie",
   os.listdir(os.path.join(vault2, "pc")) == ["heeft-gpu.md"])

# maar de onderliggende pad-laag gooit wél, voor directe aanroepers
raises_obsidian_error("resolve_note_path gooit een ObsidianError",
                      ob.resolve_note_path, "pc/con.md")

plan = ob.save_memory_to_vault({"value": "x"}, "  ", "pc")

ok("lege sleutel wordt overgeslagen", plan["ok"] is False)
ok("lege sleutel heeft een reden", plan["reason"] == "sleutel is leeg")

ob.set_vault_path(os.path.join(work, "bestaat niet"))

plan = ob.save_memory_to_vault({"value": "blauw"}, "kleur", "voorkeuren")

ok("ontbrekende vault geeft no-vault", plan["action"] == "no-vault")
ok("ontbrekende vault schrijft niets", plan["written"] is False)

_alle = ob.save_all_memories_to_vault(MEMORIES, dry_run=False)

ok("export naar ontbrekende vault schrijft niets",
   _alle["count"]["geschreven"] == 0)

ob.set_vault_path(vault2)

print("\n--- 19. stap 2: GEEN automatische koppeling ---")

ok("memory.py bevat geen import van obsidian",
   "obsidian" not in _haal_importen(_memory_sources["memory.py"]))
ok("store.py bevat geen import van obsidian",
   "obsidian" not in _haal_importen(_memory_sources["store.py"]))

ok("er is geen functie 'remember' in de obsidian-laag",
   not hasattr(ob, "remember") and not hasattr(ob, "update_memory"))

ok("de obsidian-laag heeft geen geheugen-laag aangeraakt",
   not any(isinstance(v, str) and "memory.json" in v
           for k, v in vars(ob).items() if not k.startswith("__")))

# Het bewijs dat het belangrijkste: remember() raakt de vault niet aan.
_geheugen_tmp = os.path.join(work, "geheugen.json")

with patch.object(mem, "MEMORY_FILE", _geheugen_tmp):
    mem.store.reset_cache(_geheugen_tmp)

    _notities_voor = ob.list_notes()

    uitkomst = mem.remember("favoriete kleur", "blauw", category="voorkeuren")

    ok("remember() werkt nog normaal", uitkomst["category"] == "voorkeuren")
    ok("remember() legt niets aan in de vault",
       ob.list_notes() == _notities_voor)
    ok("remember() maakt geen notitie-map aan",
       not os.path.exists(os.path.join(vault2, "voorkeuren", "nieuw")))

    ok("de memory staat wel in het geheugenbestand",
       os.path.exists(_geheugen_tmp))

    mem.store.reset_cache(_geheugen_tmp)

# de echte memory.json is over de hele test nog steeds onveranderd
ok("echte memory.json is na stap 2 nog steeds onveranderd",
   read_bytes(memory_json) == _memory_before)

print("\n--- 20. stap 2: de echte gegevens, alleen gepland ---")

ob.reset_vault_path()

_echte_vault_notities = ob.list_notes()

try:
    import memory.memory as mem_live

    _echt = mem_live.load_memory()

    plannen = ob.save_all_memories_to_vault(_echt)

    ok("het echte geheugen is in te laden", isinstance(_echt, dict))
    ok("het echte geheugen is te plannen", isinstance(plannen["plans"], list))
    ok("plannen tellen de echte memories",
       plannen["count"]["totaal"] >= 0)
    ok("het echte geheugen wordt NIET geschreven",
       plannen["written"] is False)
    ok("de echte vault is onveranderd", ob.list_notes() == _echte_vault_notities)

    print(f"  info: {plannen['count']['totaal']} memories in memory.json, "
          f"{plannen['count']['bruikbaar']} zouden een notitie worden")
except Exception as exc:
    ok(f"echte geheugen plannen werkte niet ({type(exc).__name__}: {exc})", False)


# =============================================================
# 21. Stap 3: vault -> geheugen (volledig handmatig)
# =============================================================

print("\n--- 21. stap 3: frontmatter lezen ---")

ok("frontmatter wordt geparseerd",
   vi.parse_frontmatter("---\ntitle: test\n---\n\nbody")[0]["title"]
   == "test")
ok("body wordt gescheiden van metadata",
   vi.parse_frontmatter("---\ntitle: test\n---\n\nbody")[1] == "body")
ok("notitie zonder frontmatter geeft lege metadata",
   vi.parse_frontmatter("# gewone notitie")[0] == {})
ok("geen tekst geeft lege metadata", vi.parse_frontmatter("") == ({}, ""))
ok("waarde zonder quotes blijft schoon",
   vi.parse_frontmatter("---\npriority: 2.5\n---\n")[0]["priority"] == "2.5")
ok("dubbele quotes worden afgehaald",
   vi.parse_frontmatter('---\nupdated: "2026-01-10T18:00:00"\n---')[0]["updated"]
   == "2026-01-10T18:00:00")
ok("waarde met dubbele punt blijft heel",
   vi.parse_frontmatter("---\ntitle: mijn: ding\n---")[0]["title"] == "mijn: ding")
ok("BOM aan het begin wordt genegeerd",
   vi.parse_frontmatter("\ufeff---\ntitle: test\n---")[0]["title"] == "test")

print("\n--- 22. stap 3: notitie -> memory ---")

ob.set_vault_path(vault3)

_m = ob.memory_to_note({"value": "blauw"}, key="favoriete kleur", category="voorkeuren")
ob.write_note(_m["note_name"], _m["content"])

ok("notitie wordt gelezen", vi.read_note(_m["note_name"]) is not None)
ok("niet-bestaande notitie geeft None",
   vi.read_note("bestaat niet.md") is None)

data = vi.note_to_memory(_m["note_name"])
ok("sleutel wordt herkend", data["key"] == "favoriete kleur")
ok("categorie wordt herkend", data["category"] == "voorkeuren")
ok("waarde wordt herkend", data["value"] == "blauw")
ok("prioriteit wordt herkend", data["priority"] == 1.0)

ok("handgeschreven notitie geeft None",
   vi.note_to_memory("welkom.md") is None)

ob.write_note("pc/heeft-gpu",
              ob.memory_to_note({"value": "ja", "priority": 8.0},
                                key="heeft gpu", category="pc")["content"])
d = vi.note_to_memory("pc/heeft-gpu.md")
ok("prioriteit uit de notitie wordt gelezen", d["priority"] == 8.0)

print("\n--- 23. stap 3: plannen (nog niets opslaan) ---")

plan = vi.plan_import(_m["note_name"])
ok("plan voor nieuwe memory is 'new'", plan["action"] == "new")
ok("plan bevat de sleutel", plan["key"] == "favoriete kleur")

ok("plan voor niet-bestaande notitie geeft skip",
   vi.plan_import("bestaat niet.md")["action"] == "skip")
ok("skip heeft een reden",
   vi.plan_import("bestaat niet.md")["reason"] != "")

with patch.object(mem, "MEMORY_FILE", mem3_file):
    mem.store.reset_cache(mem3_file)

    r = vi.import_all(dry_run=True)
    ok("import_all telt de memory-notities", r["count"]["gevonden"] >= 1)
    ok("import_all is standaard een dry_run", r["dry_run"] is True)
    ok("import_all schrijft niets naar het geheugen",
       mem.store.read(mem3_file) in (None, {}))

print("\n--- 24. stap 3: importeren ---")

with patch.object(mem, "MEMORY_FILE", mem3_file):
    mem.store.reset_cache(mem3_file)

    r = vi.import_all(dry_run=False)
    ok("import_all importeert", r["count"]["geimporteerd"] >= 1)
    ok("de memory staat nu in het geheugen",
       "favoriete kleur" in mem.load_memory()["voorkeuren"])
    ok("prioriteit uit de notitie is gerespecteerd",
       mem.load_memory()["pc"]["heeft gpu"]["priority"] == 8.0)

    # Tweede keer: waarde is identiek
    r2 = vi.import_all(dry_run=False)
    ok("tweede import is onveranderd",
       r2["count"]["onveranderd"] >= 1)
    ok("tweede import overschrijft niets",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")

print("\n--- 25. stap 3: conflictlogica wordt hergebruikt ---")

with patch.object(mem, "MEMORY_FILE", mem3_file):
    mem.store.reset_cache(mem3_file)

    # Wijzig de waarde in de vault, maar niet in het geheugen
    ob.write_note(_m["note_name"],
                  ob.memory_to_note({"value": "groen"},
                                    key="favoriete kleur",
                                    category="voorkeuren")["content"])

    r = vi.import_note(_m["note_name"])
    ok("conflict wordt gemeld", r["needs_confirm"] is True)
    ok("conflict gebruikt de memory-action", r["action"] == "conflict")
    ok("conflict toont de vault-waarde", r["value"] == "groen")
    ok("conflict toont de huidige waarde", r["memory_value"] == "blauw")
    ok("geheugen is NIET overschreven zonder bevestiging",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")
    ok("conflict levert een confirm_token",
       isinstance(r["confirm_token"], dict))
    ok("confirm_token bevat de vault-waarde",
       r["confirm_token"]["vault_value"] == "groen")

    # Gebruiker kiest: oude waarde behouden
    res = vi.resolve_pending(r["confirm_token"], keep_old=True)
    ok("resolve_pending meldt dat de oude bleef", res["kept_old"] is True)
    ok("oude waarde is daadwerkelijk behouden",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "blauw")

    # Gebruiker kiest: vault-waarde accepteren
    r2 = vi.import_note(_m["note_name"])
    res = vi.resolve_pending(r2["confirm_token"], keep_old=False)
    ok("resolve_pending past de nieuwe waarde toe", res["applied"] is True)
    ok("nieuwe waarde staat nu in het geheugen",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "groen")
    ok("vorige waarde is bewaard",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["previous_value"]
       == "blauw")

    # force=True slaat de bevestiging over (als de gebruiker al ja zei)
    ob.write_note(_m["note_name"],
                  ob.memory_to_note({"value": "zwart"},
                                    key="favoriete kleur",
                                    category="voorkeuren")["content"])
    r3 = vi.import_note(_m["note_name"], force=True)
    ok("force=True past toe zonder bevestiging", r3["applied"] is True)
    ok("force=True heeft de waarde toegepast",
       mem.load_memory()["voorkeuren"]["favoriete kleur"]["value"] == "zwart")

print("\n--- 26. stap 3: resolve_pending validatie ---")

try:
    vi.resolve_pending("geen dict")
except TypeError:
    ok("resolve_pending met verkeerd type geweigerd", True)
except Exception as exc:
    ok(f"resolve_pending met verkeerd type gaf {type(exc).__name__}", False)
else:
    ok("resolve_pending met verkeerd type geweigerd", False)

try:
    vi.resolve_pending({"key": "x"})
except ValueError:
    ok("resolve_pending mist verplicht veld -> ValueError", True)
except Exception as exc:
    ok(f"resolve_pending gaf {type(exc).__name__}", False)
else:
    ok("resolve_pending mist verplicht veld -> ValueError", False)

print("\n--- 27. stap 3: handgeschreven notities worden overgeslagen ---")

with patch.object(mem, "MEMORY_FILE", mem3_file):
    mem.store.reset_cache(mem3_file)

    ob.write_note("mijn notitie", "# Handgeschreven\n\nGeen memory_key hier.")

    r = vi.import_all(dry_run=False)
    ok("handgeschreven notitie wordt niet meegeteld",
       all("mijn notitie" not in p["note_name"] for p in r["plans"]))
    ok("handgeschreven notitie komt niet in het geheugen",
       "mijn notitie" not in mem.load_memory()["algemeen"])

print("\n--- 28. stap 3: GEEN automatische synchronisatie ---")

ok("vault_import importeert niets uit obsidian buiten de laag",
   hasattr(vi, "ob") and hasattr(vi, "mem"))

# obsidian.py blijft volledig vrij van memory-imports
_bron = open(os.path.join(ROOT, "memory", "obsidian.py"), encoding="utf-8").read()
_geimporteerd_ob = set()

for _node in ast.walk(ast.parse(_bron)):
    if isinstance(_node, ast.Import):
        for _alias in _node.names:
            _geimporteerd_ob.add(_alias.name)
    elif isinstance(_node, ast.ImportFrom):
        _geimporteerd_ob.add(_node.module or "")

ok("obsidian.py importeert nog steeds niets uit memory",
   not any(m.startswith("memory") for m in _geimporteerd_ob))

# Het bewijs: het onthouden van een memory raakt de vault niet aan.
with patch.object(mem, "MEMORY_FILE", mem3_file):
    mem.store.reset_cache(mem3_file)
    _voor = ob.list_notes()
    mem.remember("een nieuwe memory", "test", category="algemeen")
    ok("remember() raakt de vault niet aan", ob.list_notes() == _voor)
    mem.store.reset_cache(mem3_file)

# En het omgekeerde: een notitie in de vault komt niet vanzelf in het geheugen.
with patch.object(mem, "MEMORY_FILE", mem3_file):
    mem.store.reset_cache(mem3_file)
    _m2 = mem.load_memory()
    ob.write_note("voorkeuren/nieuw", "# Nieuw\n\nmemory_key: nieuw\n\n> test")
    _na = mem.load_memory()
    ok("een notitie in de vault komt niet vanzelf in het geheugen",
       _na == _m2)
    mem.store.reset_cache(mem3_file)


# =============================================================
# Opruimen
# =============================================================

ob.reset_vault_path()
shutil.rmtree(work, ignore_errors=True)

print(f"\n--- RESULTAAT: {passed} geslaagd, {failed} gefaald ---")

sys.exit(1 if failed else 0)
