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
AI_KEEP_ALIVE = os.environ.get("AI_KEEP_ALIVE", "30m")

# Home Assistant (optioneel) – via environment variables
HOME_ASSISTANT_URL = os.environ.get("HOME_ASSISTANT_URL", "")
HOME_ASSISTANT_TOKEN = os.environ.get("HOME_ASSISTANT_TOKEN", "")

# Bevestigingen verlopen na 20 seconden
CONFIRM_TTL_SECONDS = 20

# Spraakinvoer instellingen
WACHT_OP_SPRAAK_SECONDEN = 10
MAX_OPNAME_SECONDEN = 15
BEEP_ENABLED = True

# Executor instellingen
EXECUTOR_MAX_WORKERS = 4
