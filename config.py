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
AI_NUM_CTX = int(os.environ.get("AI_NUM_CTX", "4096"))
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
