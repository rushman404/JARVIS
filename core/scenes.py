"""
Scenes (Fase 13 — Home Assistant 2.0)

Scenes zijn benoemde combinaties van tool-acties (vaak HA-services,
maar ook PC-acties), bedoeld om met één commando een hele sfeer te
creëren: "zet filmmodus aan" dimt het licht, zet de tv aan en start
een film.

Architectuur:
    scenes.py      : CRUD + resolutie (JSON-beheer)
    brain.py       : Detectie + routing (try_scene)+ voorstel-flow
    executor       : Uitvoering van de stappenlijst

Het beste gebruik: JARVIS stelt zelf een scene voor na een multi-actie
("Wil je dit opslaan als scene?"), jij keurt goed, en daarna is de
scene altijd oproepbaar met één zin.

Een scene bevat:
    - name       : unieke naam (bijv. "filmmodus")
    - steps      : lijst van tool-calls (Executor-formaat)
    - description: korte uitleg voor de gebruiker

Scenes zijn BEWUST naast routines gezet (routines = PC-modes zoals
"ik ga gamen"; scenes = HA-gericht, meerdere apparaten in één
commando). Beide worden door de Executor uitgevoerd.
"""

import json
import os
import re
import time

SCENES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ha_scenes.json",
)


def _load_scenes():
    """Laadt scenes uit het JSON-bestand."""
    try:
        with open(SCENES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_scenes(scenes):
    """Slaat scenes op naar het JSON-bestand."""
    os.makedirs(os.path.dirname(SCENES_FILE), exist_ok=True)
    with open(SCENES_FILE, "w", encoding="utf-8") as f:
        json.dump(scenes, f, indent=2, ensure_ascii=False)


def _normalize(text):
    """Normaliseert tekst voor matching."""
    if not text:
        return ""
    s = str(text).lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


class SceneManager:
    """Beheert opgeslagen scenes: opslaan, ophalen, verwijderen, triggeren."""

    def __init__(self):
        self._scenes = _load_scenes()

    def reload(self):
        """Herlaadt scenes uit het JSON-bestand."""
        self._scenes = _load_scenes()

    def list_scenes(self):
        """Geeft een lijst van alle scenes terug."""
        return dict(self._scenes)

    def get_scene(self, name):
        """Haalt een specifieke scene op."""
        return self._scenes.get(name)

    def save_scene(self, name, steps, description=""):
        """
        Slaat een scene op (nieuw of bijwerken).

        Parameters:
            name        : unieke naam (kleine letters, geen spaties)
            steps       : lijst van tool-calls (dict met tool_name + arguments)
            description : korte uitleg
        """
        name = _normalize(name)
        if not name:
            return None

        scene = {
            "name": name,
            "steps": steps or [],
            "description": description,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._scenes[name] = scene
        _save_scenes(self._scenes)
        return scene

    def delete_scene(self, name):
        """Verwijdert een scene. Geeft True terug als die bestond."""
        name = _normalize(name)
        if name in self._scenes:
            del self._scenes[name]
            _save_scenes(self._scenes)
            return True
        return False

    def resolve(self, question):
        """
        Vindt een scene op basis van een gebruikerszin.

        Accepteert: de scenaam zelf, patronen als "scene <naam> aan",
        "zet <naam> aan", "activeer <naam>", "scène <naam>".

        Geeft (naam, scene) of (None, None).
        """
        if not question:
            return None, None

        q = _normalize(question)
        if not q:
            return None, None

        scenes = self._scenes

        # 1) Exacte scenaam ("filmmodus")
        if q in scenes:
            return q, scenes[q]

        # 2) Zinnen met "scene" en de naam erin
        m = re.search(r"\bscene?\s+([a-z0-9 ]+)", q)
        if m:
            candidate = m.group(1).strip()
            # "zet scene filmmodus aan" -> "filmmodus"
            candidate = re.sub(r"\b(?:aan|uit|zet|maak|doe|start|activeer|activ)\b", "", candidate).strip()
            if candidate in scenes:
                return candidate, scenes[candidate]

        # 3) "activeer <naam>" of "zet <naam> aan"
        m = re.search(r"\b(?:activeer|activ|start|zet|doe|maak)\s+(?:de\s+|de\s+)?scène?\s+([a-z0-9 ]+)", q)
        if m:
            candidate = m.group(1).strip()
            if candidate in scenes:
                return candidate, scenes[candidate]

        # 4) Naam als substring in de zin ("zet filmmodusmodus aan")
        for name in scenes:
            if name in q:
                return name, scenes[name]

        return None, None


def _manager():
    """Accessor voor de billing-bewuste shared manager."""
    if _manager.instance is None:
        _manager.instance = SceneManager()
    return _manager.instance


_manager.instance = None


def get_scene_manager():
    """Geeft de gedeelde SceneManager (singleton) terug."""
    return _manager()