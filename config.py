import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


JARVIS_NAME = "JARVIS"
USER_NAME = "Rushil"

# AI instellingen (override via omgevingsvariabelen)
AI_MODEL = os.environ.get("AI_MODEL", "qwen2.5:3b")
# Contextgrootte in tokens voor Ollama. 8192 geeft het model genoeg ruimte
# voor de systeemtekst + toolbeschrijvingen. Lager (bijv. 4096) bespaart
# geheugen en wat wachttijd, maar dan kunnen tools worden afgekapt.
AI_NUM_CTX = int(os.environ.get("AI_NUM_CTX", "8192"))
AI_TEMPERATURE_TOOLS = 0.0
AI_TEMPERATURE_CHAT = float(os.environ.get("AI_TEMPERATURE_CHAT", "0.3"))
AI_KEEP_ALIVE = os.environ.get("AI_KEEP_ALIVE", "30m")

# Home Assistant (optioneel) – via environment variables
HOME_ASSISTANT_URL = os.environ.get("HOME_ASSISTANT_URL", "")
HOME_ASSISTANT_TOKEN = os.environ.get("HOME_ASSISTANT_TOKEN", "")

# Bevestigingen verlopen na 20 seconden
CONFIRM_TTL_SECONDS = 20

# Wachttijd (seconden) voordat de pc echt afsluit/herstart. De gebruiker
# hoort deze tijd en kan binnen dat venster "annuleer afsluiten" zeggen.
POWER_COUNTDOWN_SECONDS = int(os.environ.get("POWER_COUNTDOWN_SECONDS", "20"))

# --- Standaarddoel PC-bediening (Fase 15B) ---
# 'game-pc' = alle PC-bediening op het werkstation (standaard)
# 'local'   = alleen lokaal op deze machine (expliciet via "mini-pc"/"server")
PC_TARGET = os.environ.get("PC_TARGET", "game-pc")

# Spraakinvoer instellingen
WACHT_OP_SPRAAK_SECONDEN = 10
MAX_OPNAME_SECONDEN = 15
BEEP_ENABLED = True

# Microfoonapparaat voor de gedeelde audiostream (None = standaardapparaat).
# Overschrijfbaar via de omgevingsvariabele MIC_DEVICE.
MIC_DEVICE = os.environ.get("MIC_DEVICE") or None

# Executor instellingen
EXECUTOR_MAX_WORKERS = 4

# --- Bestanden zoeken en openen ---

# Document-/mediatypes waarin JARVIS zoekt als de gebruiker geen extensie
# noemt (en die hij zonder waarschuwing mag openen).
FILE_ALLOWED_EXTENSIONS = frozenset([
    ".txt", ".md", ".pdf", ".rtf",
    ".doc", ".docx", ".odt",
    ".xls", ".xlsx", ".ods", ".csv",
    ".ppt", ".pptx", ".odp",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".zip", ".rar", ".7z", ".tar", ".gz",
])

# Uitvoerbare/gevaarlijke types: alleen openen na expliciete bevestiging.
FILE_DANGEROUS_EXTENSIONS = frozenset([
    ".exe", ".bat", ".cmd", ".ps1", ".js", ".vbs",
    ".msi", ".lnk", ".scr", ".com", ".jar", ".reg",
    # Extra risicovolle types: HTML-applicaties, Windows Script Host,
    # macro-documenten, snelkoppelingen en configuratie/installatie.
    ".hta", ".wsf", ".wsh", ".vbe", ".jse", ".url", ".pif", ".cpl",
    ".msc", ".msp", ".docm", ".xlsm", ".pptm", ".application",
    ".appref-ms", ".gadget", ".ps1xml", ".psm1", ".scf", ".inf",
])

# Fuzzy-drempel (0-100) voor bestandsnaam-matching (rapidfuzz).
FILE_FUZZY_THRESHOLD = 75

# Zoeklimieten: maximale diepte en maximale zoektijd in seconden.
FILE_MAX_DEPTH = 4
FILE_SEARCH_TIMEOUT_SECONDS = 5

# Mappen die tijdens het zoeken worden overgeslagen (kleine letters).
FILE_SKIP_DIRS = frozenset([
    "node_modules", ".git", "appdata", "$recycle.bin", "venv", ".venv",
])


# =============================================================
# FASE 15 — Game-PC Agent (remote)
# =============================================================
# De SERVER draait op de game-pc (de huidige pc) en voert alleen
# toegestane acties uit. De CLIENT draait op het brein (nu nog deze
# pc, later de mini-pc) en stuurt ondertekende opdrachten.
#
# Beveiliging is fail-closed: zonder token of certificaat start de
# server niet (zie remote_server_security_errors()).


def _env_bool(name, default=False):
    """Leest een boolean uit de omgeving (1/true/yes/on)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    """Leest een int uit de omgeving; valt terug op default bij onzin."""
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    """Leest een float uit de omgeving; valt terug op default bij onzin."""
    try:
        return float(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


# --- Server (game-pc) ---
REMOTE_SERVER_ENABLED = _env_bool("REMOTE_SERVER_ENABLED", False)
REMOTE_SERVER_HOST = os.environ.get("REMOTE_SERVER_HOST", "0.0.0.0")
REMOTE_SERVER_PORT = _env_int("REMOTE_SERVER_PORT", 8765)
REMOTE_SERVER_TOKEN = os.environ.get("REMOTE_SERVER_TOKEN", "")
REMOTE_SERVER_CERT_FILE = os.environ.get("REMOTE_SERVER_CERT_FILE", "")
REMOTE_SERVER_KEY_FILE = os.environ.get("REMOTE_SERVER_KEY_FILE", "")

# --- Client (brein) ---
REMOTE_CLIENT_ENABLED = _env_bool("REMOTE_CLIENT_ENABLED", False)
REMOTE_CLIENT_HOST = os.environ.get("REMOTE_CLIENT_HOST", "127.0.0.1")
REMOTE_CLIENT_PORT = _env_int("REMOTE_CLIENT_PORT", 8765)
REMOTE_CLIENT_TOKEN = os.environ.get("REMOTE_CLIENT_TOKEN", "")
REMOTE_CLIENT_CA_FILE = os.environ.get("REMOTE_CLIENT_CA_FILE", "")
REMOTE_CLIENT_TIMEOUT = _env_float("REMOTE_CLIENT_TIMEOUT", 5.0)

# --- Gedeeld ---
# Hoeveel seconden mag een ondertekend verzoek oud zijn (replay-bescherming).
REMOTE_REPLAY_WINDOW_SECONDS = _env_int("REMOTE_REPLAY_WINDOW_SECONDS", 30)

# Minimale lengte van het gedeelde geheim (token).
REMOTE_MIN_TOKEN_LENGTH = 16


def remote_server_security_errors(
    enabled=None,
    token=None,
    cert_file=None,
    key_file=None,
):
    """Controleert of de server veilig geconfigureerd is (fail-closed).

    Geeft een lijst met leesbare foutmeldingen terug. Een lege lijst
    betekent: veilig genoeg om te starten. Ontbrekende beveiliging mag
    NOOIT leiden tot een onbeschermde server, dus bij twijfel is dit
    een fout.

    De parameters zijn er voor tests; zonder argumenten worden de
    waarden uit dit bestand gebruikt.
    """

    enabled = REMOTE_SERVER_ENABLED if enabled is None else enabled
    token = REMOTE_SERVER_TOKEN if token is None else token
    cert_file = REMOTE_SERVER_CERT_FILE if cert_file is None else cert_file
    key_file = REMOTE_SERVER_KEY_FILE if key_file is None else key_file

    if not enabled:
        return []

    errors = []

    if not token:
        errors.append(
            "REMOTE_SERVER_TOKEN ontbreekt: zonder gedeeld geheim start "
            "de server niet."
        )
    elif len(token) < REMOTE_MIN_TOKEN_LENGTH:
        errors.append(
            f"REMOTE_SERVER_TOKEN is te kort (minimaal "
            f"{REMOTE_MIN_TOKEN_LENGTH} tekens)."
        )

    if not cert_file:
        errors.append("REMOTE_SERVER_CERT_FILE ontbreekt: TLS is verplicht.")

    if not key_file:
        errors.append("REMOTE_SERVER_KEY_FILE ontbreekt: TLS is verplicht.")

    if cert_file and not os.path.isfile(cert_file):
        errors.append(f"Certificaatbestand niet gevonden: {cert_file}")

    if key_file and not os.path.isfile(key_file):
        errors.append(f"Sleutelbestand niet gevonden: {key_file}")

    return errors
