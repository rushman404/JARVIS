"""
Routines (Fase 4 - JARVIS Routines / Modes)

Routines zijn opgeslagen reeksen acties die JARVIS kan uitvoeren
op basis van een自然lijke zin. Bijv. "ik ga gamen" opent Discord,
start Spotify, stelt volume in en zet de bedlamp aan.

Architectuur:
    RoutineManager : CRUD + resolver (JSON-beheer)
    brain.py       : Detectie + routing vóór AI/Agent
    agent/executor : Uitvoering van de stappenlijst

Een routine bevat:
    - name       : unieke naam (bijv. "gaming")
    - triggers   : lijst van patronen die de routine activeren
    - aliases    : extra namen (bijv. "game modus", "gamersessie")
    - steps      : lijst van tool-calls (hetzelfde formaat als Executor)
    - description: korte uitleg voor de gebruiker
"""

import json
import os
import re
import time

ROUTINES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "routines.json",
)


def _load_routines():
    """Laadt routines uit het JSON-bestand."""
    try:
        with open(ROUTINES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        # Probeer backup
        try:
            bak = ROUTINES_FILE + ".bak"
            if os.path.exists(bak):
                with open(bak, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception:
            pass
    return {}


def _save_routines(routines):
    """Slaat routines op naar het JSON-bestand. Atomair met backup bij corruptie."""
    import tempfile

    os.makedirs(os.path.dirname(ROUTINES_FILE), exist_ok=True)
    
    # Backup maken van bestaande bestand
    if os.path.exists(ROUTINES_FILE):
        try:
            bak = ROUTINES_FILE + ".bak"
            import shutil
            shutil.copy2(ROUTINES_FILE, bak)
        except Exception:
            pass
    
    # Probeer eerst te valideren door te parsen
    try:
        text = json.dumps(routines, indent=2, ensure_ascii=False)
    except Exception:
        return False
    
    # Atomair schrijven
    directory = os.path.dirname(ROUTINES_FILE) or "."
    handle = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=directory,
            prefix=os.path.basename(ROUTINES_FILE) + ".",
            suffix=".tmp"
        )
        handle = os.fdopen(fd, "w", encoding="utf-8")
        handle.write(text)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
        handle.close()
        handle = None
        os.replace(tmp_path, ROUTINES_FILE)
        tmp_path = None
        return True
    except Exception:
        return False
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _normalize(text):
    """Normaliseert tekst voor matching."""
    if not text:
        return ""
    s = str(text).lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


class RoutineManager:
    """
    Beheert opgeslagen routines: opslaan, ophalen, verwijderen,
    triggeren en bijwerken.
    """

    def __init__(self):
        self._routines = _load_routines()

    def reload(self):
        """Herlaadt routines uit het JSON-bestand."""
        self._routines = _load_routines()

    def list_routines(self):
        """Geeft een lijst van alle routines terug."""
        return dict(self._routines)

    def get_routine(self, name):
        """Haalt een specifieke routine op."""
        return self._routines.get(name)

    def save_routine(self, name, triggers, steps, description="", aliases=None):
        """
        Slaat een routine op (nieuw of bijwerken).

        Parameters:
            name        : unieke naam (kleine letters, geen spaties)
            triggers    : lijst van regex-patronen
            steps       : lijst van tool-calls (dict met tool_name + arguments)
            description : korte uitleg
            aliases     : extra namen voor de resolver
        """
        routine = {
            "name": name,
            "triggers": triggers or [],
            "aliases": aliases or [],
            "steps": steps or [],
            "description": description,
        }
        self._routines[name] = routine
        _save_routines(self._routines)
        return routine

    def delete_routine(self, name):

        """Verwijdert een routine. Geeft True terug als die bestond."""

        if name in self._routines:

            del self._routines[name]

            _save_routines(self._routines)

            return True

        return False

    def track_usage(self, name):

        """Registreert wanneer een routine wordt uitgevoerd (Fase 5)."""

        routine = self._routines.get(name)

        if not routine:

            return

        routine["usage_count"] = int(routine.get("usage_count") or 0) + 1

        routine["last_used"] = _now()

        _save_routines(self._routines)


    def most_used_routines(self, max_items=5):

        """Routines gesorteerd op usage_count (Fase 5)."""

        items = []

        for name, routine in self._routines.items():

            items.append((

                int(routine.get("usage_count") or 0),

                routine.get("last_used") or "",

                name,

                routine.get("description", ""),

            ))

        items.sort(reverse=True)

        return items[:max_items]

    def resolve(self, command):
        """
        Zoekt een routine die past bij de gegeven opdracht.

        Triggers zijn regex-patronen (re.search) zodat varianten als
        "JARVIS, ik wil gamen vanavond" ook matchen. Aliases zijn losse
        trefwoorden (substring-match).
        """
        text = (command or "").lower().strip()
        for name, routine in self._routines.items():
            for pattern in routine.get("triggers", []):
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        return name, routine
                except re.error:
                    continue
            for alias in routine.get("aliases", []):
                alias = (alias or "").lower().strip()
                if alias and alias in text:
                    return name, routine

        return None, None


    def steps_for_agent(self, routine_name):
        """
        Zet routine-stappen om naar het formaat van de Executor.
        Geeft een lijst van plan-stappen terug, of een lege lijst.
        """
        routine = self._routines.get(routine_name)
        if not routine:
            return []

        steps = routine.get("steps", [])
        plan = []

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            tool_name = step.get("tool_name", "")
            if not tool_name:
                continue
            arguments = dict(step.get("arguments", {}))
            plan.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "status": "pending",
                "goal": f"routine: {routine_name}",
            })

        return plan


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# Globaal exemplaar
_manager = RoutineManager()
