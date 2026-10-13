"""Centrale logging-configuratie voor JARVIS.

Schrijft naar ``logs/jarvis.log`` (roterend: 1 MB, 3 back-ups) én naar de
console. Alle modules die ``logging.getLogger(__name__)`` gebruiken, komen
automatisch hier binnen zodra :func:`setup_logging` één keer is aangeroepen.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_configured = False


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup_logging(log_dir=None, level=logging.INFO):
    """Zet de root-logger op (idempotent). Geeft de root-logger terug."""
    global _configured

    root = logging.getLogger()
    if _configured:
        return root

    log_dir = log_dir or os.path.join(_project_root(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "jarvis.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Op Windows kan stderr cp1252 zijn; vervang onverteerbare tekens zodat
    # emoji's de console-logging nooit laten crashen.
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    root.setLevel(level)
    _configured = True

    return root
