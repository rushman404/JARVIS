"""
Routines (Fase 4 - JARVIS Routines / Modes)

Routines zijn opgeslagen reeksen acties die JARVIS kan uitvoeren
op basis van een natuurlijke zin. Bijv. "ik ga gamen" opent Discord,
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


# =========================================================
# INTENTIE-DETECTIE
#
# Een routine mag ALLEEN starten als de gebruiker echt om de routine
# vraagt. Vragen ("hoe lang moet ik slapen?") en beschrijvingen
# ("filmavond is leuk") starten dus nooit een routine.
# =========================================================

# Vraagwoorden: een zin die hiermee begint is een vraag, geen opdracht.
QUESTION_STARTERS = frozenset([
    "wat", "waarom", "hoe", "hoeveel", "wanneer", "wie", "waar", "welke",
    "is", "zijn",
])

# Vormen waarin een routine-opdracht gegoten mag worden.
# "{x}" is de routinenaam of een alias (volledige woorden/zinnen).
COMMAND_PATTERNS = (
    "{x}",
    "ik ga {x}",
    "ik wil {x}",
    "start {x}",
    "start de {x}",
    "start een {x}",
    "zet {x} aan",
    "zet de {x} aan",
    "zet een {x} aan",
    "{x} aan",
    "{x} modus",
    "{x} modus aan",
)


def _normalize_for_match(text):
    """Kleine letters, leestekens weg, spaties samengevat.

    Een eventuele aanroep ("jarvis, ...") wordt vooraan weggehaald.
    """
    t = str(text or "").lower().strip()
    t = re.sub(r"^\s*(hey\s+|ok\s+|okay\s+)?jarvis\b[,\s]*", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def is_question(text):
    """True als de zin een vraag is (vraagwoord vooraan of eindigt op '?').

    Vragen mogen nooit een routine starten.
    """
    raw = str(text or "").strip()
    if not raw:
        return False
    if raw.endswith("?"):
        return True
    woorden = _normalize_for_match(raw).split()
    return bool(woorden) and woorden[0] in QUESTION_STARTERS


def _matches_phrase(text, phrase):
    """True als de hele genormaliseerde zin een opdrachtvorm voor 'phrase' is.

    De alias/naam wordt letterlijk genomen (re.escape) en moet als
    volledige woorden/zinnen matchen, nooit als deel van een ander woord
    ("geslapen" raakt "slapen" dus niet).
    """
    p = _normalize_for_match(phrase)
    if not p:
        return False
    escapeerd = re.escape(p)
    return any(re.fullmatch(pat.format(x=escapeerd), text) for pat in COMMAND_PATTERNS)


def _matches_trigger(text, trigger):
    """True als de genormaliseerde zin exact gelijk is aan een triggerpatroon."""
    if not trigger:
        return False
    try:
        return re.fullmatch(str(trigger), text, re.IGNORECASE) is not None
    except re.error:
        return False


def matches_routine_command(text, routine):
    """Bepaalt of 'text' een echte routine-opdracht is voor 'routine'.

    Een routine start alleen bij een opdracht: "ik ga <x>", "start <x>",
    "zet <x> aan", "<x> modus (aan)", de volledige naam/alias als hele
    zin, of een expliciete triggerzin. Vragen en beschrijvingen niet.
    """
    if is_question(text):
        return False

    genormaliseerd = _normalize_for_match(text)
    if not genormaliseerd:
        return False

    phrases = [routine.get("name", "")] + list(routine.get("aliases", []) or [])
    if any(_matches_phrase(genormaliseerd, phrase) for phrase in phrases):
        return True

    return any(
        _matches_trigger(genormaliseerd, trigger)
        for trigger in (routine.get("triggers", []) or [])
    )


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
        """Zoekt de routine die bij deze opdracht hoort, of (None, None).

        Er wordt alleen gematcht als de zin een echte opdracht is:
        vraag- en beschrijvende zinnen starten geen routine. Zie
        matches_routine_command() voor de exacte regels.
        """
        for name, routine in self._routines.items():
            if matches_routine_command(command, routine):
                return name, routine

        return None, None


    def protocollen(self):
        """``{protocolnaam: routinenaam}`` (Fase 21, M3).

        Een routine heeft protocolnamen in ``"protocollen"``; haar eigen
        naam telt ook ("protocol gaming").
        """

        uit = {}
        for name, routine in self._routines.items():
            namen = list(routine.get("protocollen") or []) + [name]
            for p in namen:
                sleutel = _protocol_sleutel(p)
                if sleutel and sleutel not in uit:
                    uit[sleutel] = (name, str(p))
        return uit

    def resolve_protocol(self, command):
        """Protocolopdracht herkennen. Geeft één van:

        - ``("start", routinenaam, routine, protocolnaam)``
        - ``("onbekend", gevraagd, [bekende namen])``
        - ``("lijst", [bekende namen])``
        - ``None`` als de zin geen protocolopdracht is.
        """

        tekst = _normalize_for_match(command)
        bekend = self.protocollen()
        zichtbaar = []
        for name, routine in self._routines.items():
            eerste = (routine.get("protocollen") or [name])[0]
            zichtbaar.append(str(eerste))
        if PROTOCOL_LIJST.fullmatch(tekst):
            return ("lijst", zichtbaar)
        m = PROTOCOL_START.fullmatch(tekst)
        if not m:
            return None
        gevraagd = m.group(1).strip()
        treffer = bekend.get(_protocol_sleutel(gevraagd))
        if treffer is None:
            return ("onbekend", gevraagd, zichtbaar)
        name, label = treffer
        return ("start", name, self._routines[name], label)

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


# "start protocol filmavond", "activeer protocol slaap", "protocol gamen",
# "voer protocol filmavond uit". Na _normalize_for_match (kleine letters,
# geen leestekens).
PROTOCOL_START = re.compile(
    r"(?:start|activeer|begin|voer)?\s*(?:het\s+)?protocol\s+(.+?)(?:\s+(?:uit|starten|activeren))?"
)
PROTOCOL_LIJST = re.compile(r"(?:welke|wat zijn (?:de|mijn))\s+protocollen(?:\s+(?:zijn er|heb ik|ken je))?")


def _protocol_sleutel(naam):
    """Naam zonder spaties ("film avond" = "filmavond")."""

    return _normalize_for_match(naam).replace(" ", "")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# Globaal exemplaar
_manager = RoutineManager()
