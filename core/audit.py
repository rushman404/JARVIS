"""Audit-log voor tooluitvoeringen (logs/audit.jsonl).

Elke geregistreerde aanroep schrijft één regel met:
    - tijd
    - gehoorde tekst
    - handler (welke component de tool aanriep)
    - toolnaam
    - argumenten (zonder geheimen)
    - risico
    - resultaat
    - of de actie goedgekeurd werd (True/False)
"""

import json
import os
import time

# Geheimen die nooit in het audit-log mogen komen.
_SECRET_KEYS = frozenset([
    "password",
    "passwd",
    "pass",
    "token",
    "api_key",
    "apikey",
    "api-token",
    "secret",
    "authorization",
    "auth",
    "key",
    "credential",
])

AUDIT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
    "audit.jsonl",
)


def _sanitize(value):
    """Vervangt geheime sleutels door '***' (ook in geneste dict/lijsten)."""

    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                cleaned[key] = "***"
            else:
                cleaned[key] = _sanitize(item)
        return cleaned

    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]

    return value


def log_audit(gehoord, handler, tool, argumenten, risico, resultaat, goedgekeurd):
    """Schrijft één auditregel. Faalt stilletjes bij schrijffouten."""

    try:
        bestand = os.path.dirname(AUDIT_FILE)
        os.makedirs(bestand, exist_ok=True)
    except OSError:
        return

    regel = {
        "tijd": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gehoorde-tekst": str(gehoord or ""),
        "handler": str(handler or ""),
        "tool": str(tool or ""),
        "argumenten": _sanitize(argumenten or {}),
        "risico": str(risico or "low"),
        "resultaat": str(resultaat or "")[:2000],
        "goedgekeurd": bool(goedgekeurd),
    }

    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(regel, ensure_ascii=False) + "\n")
    except OSError:
        pass