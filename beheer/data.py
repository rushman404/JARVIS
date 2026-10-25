"""Welke bestanden horen bij 'het brein' (Fase 19).

Eén lijst voor de migratie naar de mini-pc (M1) en de dagelijkse backup
(M3). De code zelf hoort er niet bij (die komt van GitHub), de
stemmodellen ook niet (die haalt het installatiescript opnieuw op).

Twee soorten:

* **gegevens** — geheugen, gesprek, timers, routines, scènes, regels,
  dashboard-indeling en gekoppelde iPads, taalkeuze, auditlog en de
  Obsidian-vault;
* **geheimen** — ``.env`` (tokens) en ``certs/`` (o.a. de dashboard-CA:
  neemt u die mee, dan hoeft de iPad het profiel niet opnieuw te
  vertrouwen).
"""

import fnmatch
import os

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (glob-patroon relatief aan de projectmap, geheim?)
PATRONEN = (
    ("memory/memory.json", False),
    ("memory/conversation.json", False),
    ("config/*.json", False),
    ("taal.json", False),
    ("logs/audit*.jsonl", False),
    ("JARVIS Memory/**", False),
    (".env", True),
    ("certs/**", True),
)

# Nooit meenemen, ook niet als een patroon ze raakt.
UITSLUITEN = (
    "*.lock",
    "*.bak",
    "*.tmp",
    "*/__pycache__/*",
    "JARVIS Memory/.trash/*",
    # De privésleutel van de game-pc-agent blijft altijd op de game-pc;
    # het brein heeft alleen het publieke agent-cert.pem nodig.
    "certs/agent-key.pem",
)

# .env-sleutels die per pc kunnen verschillen: na een migratie nakijken.
PC_GEBONDEN_SLEUTELS = (
    "DASHBOARD_LAN_IP",
    "DASHBOARD_ALLOWED_HOSTS",
    "DASHBOARD_ALLOWED_ORIGINS",
    "MIC_DEVICE",
    "PIPER_MODELS_DIR",
    "JARVIS_OBSIDIAN_VAULT",
)


def _rel(pad):
    return pad.replace(os.sep, "/")


def _past(rel, patroon):
    if patroon.endswith("/**"):
        return rel.startswith(patroon[:-2])
    return fnmatch.fnmatchcase(rel, patroon)


def _uitgesloten(rel):
    return any(fnmatch.fnmatchcase(rel, p) for p in UITSLUITEN)


def classificeer(rel):
    """``None`` als het pad niet bij het brein hoort, anders of het geheim is."""

    rel = _rel(rel)
    if _uitgesloten(rel):
        return None
    for patroon, geheim in PATRONEN:
        if _past(rel, patroon):
            return geheim
    return None


def verzamel(project=PROJECT):
    """Alle bestaande brein-bestanden: lijst van ``(relatief_pad, geheim)``.

    Gesorteerd, zodat een export of backup altijd dezelfde volgorde heeft.
    """

    gevonden = {}
    for patroon, _ in PATRONEN:
        basis = patroon.split("/")[0] if "/" in patroon else ""
        start = os.path.join(project, basis) if basis else project
        if not basis:
            kandidaten = [patroon]
        elif os.path.isdir(start):
            kandidaten = []
            for map_, mappen, bestanden in os.walk(start):
                mappen[:] = [m for m in mappen if m != "__pycache__"]
                for naam in bestanden:
                    kandidaten.append(_rel(os.path.relpath(os.path.join(map_, naam), project)))
        else:
            continue
        for rel in kandidaten:
            if not os.path.isfile(os.path.join(project, rel)):
                continue
            geheim = classificeer(rel)
            if geheim is not None:
                gevonden[rel] = geheim
    return sorted(gevonden.items())
