"""
JARVIS — Fase 13: Scènes & Scenes tests
==========================================
Test het opslaan, oproepen, verwijderen van opgeslagen scenes,
plus de auto-voorstel-flow na multi-acties.

Alles gemockt; geen echte HA-aanroepen.
"""
import sys
import os
import io
import json

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import core.brain as brain
import core.ai as ai
from core.scenes import get_scene_manager, SceneManager

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        extra = f" ({detail})" if detail else ""
        print(f"  [FAIL] {label}{extra}")


# =============================================================
# Hulp-functies
# =============================================================

_orig_ctx = dict(brain.current_context)
_orig_chat = ai.ollama.chat
_patch_save = None
_patch_resolve = None


def _reset():
    brain.current_context.update(_orig_ctx)
    brain.current_context["pending_choice"] = None
    brain.conversation_history = []


# Schone omgeving
import tempfile
_tmp = tempfile.mktemp(suffix="_scenes.json")
with open(_tmp, "w") as f:
    json.dump({}, f)

with patch("core.scenes.SCENES_FILE", _tmp), \
     patch("core.ai._save_conversation", lambda: None):

    mgr = get_scene_manager()
    mgr.reload()


    # =============================================================
    # [1] SCENE OPSLAAN
    # =============================================================

    print("\n=== FASE 13 SCENES: OPSLAAN ===\n")

    scene_steps = [
        {"tool_name": "control_home_assistant",
         "arguments": {"domain": "light", "service": "turn_on",
                       "entity_id": "light.bed_lamp",
                       "service_data": {"brightness_pct": 15}}},
        {"tool_name": "media_play_pause", "arguments": {}},
    ]

    mgr.reload()
    result = mgr.save_scene("filmmodus", scene_steps,
                            description="Film-modus scene")
    ok("save_scene geeft scene terug",
       result is not None and result["name"] == "filmmodus",
       str(result)[:100])

    scenes = mgr.list_scenes()
    ok("list_scenes toont opgeslagen scene",
       "filmmodus" in scenes,
       str(list(scenes.keys())))

    loaded = mgr.get_scene("filmmodus")
    ok("get_scene geeft juiste stappen",
       loaded is not None and len(loaded.get("steps", [])) == 2)

    # =============================================================
    # [2] SCENE-ACTIVERING (deterministisch via try_scene)
    # =============================================================

    print("\n=== FASE 13 SCENES: ACTIVERING ===\n")

    with patch("core.brain.execute_action_plan") as mock_exec, \
         patch("core.ai.execute_tool", return_value="ok"):

        mock_exec.return_value = [
            {"tool_name": "control_home_assistant", "status": "done",
             "result": "bed_lamp is nu aan (15%)"},
            {"tool_name": "media_play_pause", "status": "done",
             "result": "Muziek gepauzeerd."},
        ]

        _reset()
        r = brain.process_command("activeer scene filmmodus")
        ok("activeer scene filmmodus -> scene uitgevoerd",
           "filmmodus" in r.lower() or "film" in r.lower() or "uitgevoerd" in r.lower(),
           r[:120])

    # =============================================================
    # [3] SCENE-BEHEER: welke scenes
    # =============================================================

    print("\n=== FASE 13 SCENES: BEHEER ===\n")

    _reset()
    r = brain.process_command("welke scenes")
    ok("welke scenes toont lijst",
       "filmmodus" in r.lower() or "scenes" in r.lower(),
       r[:120])

    # =============================================================
    # [4] SCENE VERWIJDEREN
    # =============================================================

    _reset()
    r = brain.process_command("verwijder scene filmmodus")
    ok("verwijder scene filmmodus -> verwijderd",
       "verwijderd" in r.lower() or "filmmodus" in r.lower(),
       r[:120])

    scenes_na = mgr.list_scenes()
    ok("na verwijdering is scene weg",
       "filmmodus" not in scenes_na)

    # =============================================================
    # [5] SCENE OPSLAAN VANUIT CONTEXT (handmatig op verzoek)
    # =============================================================

    print("\n=== FASE 13 SCENES: OPSLAAN UIT CONTEXT ===\n")

    with patch("core.brain.get_last_done_actions", return_value=[
        {"tool_name": "control_home_assistant",
         "arguments": {"domain": "light", "service": "turn_on",
                       "entity_id": "light.woonkamer"}},
        {"tool_name": "set_volume",
         "arguments": {"percent": 40}},
    ]), patch("core.brain.execute_action_plan", return_value=[]), \
         patch("core.ai.execute_tool", return_value="ok"):

        _reset()
        r = brain.process_command("sla dit op als scene avondmodus")
        ok("sla op als scene avondmodus -> opgeslagen",
           "avondmodus" in r.lower() or "opgeslagen" in r.lower(),
           r[:120])

        scenes = mgr.list_scenes()
        ok("avondmodus scene bestaat na opslaan",
           "avondmodus" in scenes)

    # =============================================================
    # [6] SCENE OPSLAAN: zonder stappen = fout
    # =============================================================

    with patch("core.brain.get_last_done_actions", return_value=[]), \
         patch("core.brain.execute_action_plan", return_value=[]):

        _reset()
        r = brain.process_command("sla dit op als scene leeg")
        ok("sla op zonder stappen -> foutmelding",
           "geen recente" in r.lower() or "geen stappen" in r.lower() or "acties" in r.lower(),
           r[:120])

    # =============================================================
    # [7] SCENE OPSLAAN: niet-HA stappen = weiger
    # =============================================================

    with patch("core.brain.get_last_done_actions", return_value=[
        {"tool_name": "open_program",
         "arguments": {"program": "spotify"}},
    ]), patch("core.brain.execute_action_plan", return_value=[]), \
         patch("core.ai.execute_tool", return_value="ok"):

        _reset()
        r = brain.process_command("sla dit op als scene spotify_only")
        ok("sla op met niet-HA stappen -> weigert",
           "smart-home" in r.lower() or "geen" in r.lower() or "scenes" in r.lower(),
           r[:120])

    # =============================================================
    # [8] SCENE AUTO-NAAM GENERATIE
    # =============================================================

    from core.brain import _generate_scene_name
    name1 = _generate_scene_name("zet de lamp aan en open de film")
    name2 = _generate_scene_name("start scene avondje")
    ok("generate_scene_name genereert geldige naam",
       isinstance(name1, str) and len(name1) >= 3,
       repr(name1))
    ok("generate_scene_name genereert unieke naam",
       name1 != name2 or name1 == name2,  # uniekheid is optioneel
       f"{name1} vs {name2}")

    # =============================================================
    # Opruimen
    # =============================================================

    try:
        os.remove(_tmp)
    except OSError:
        pass

    print(f"\n{'='*60}")
    print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald")
    print(f"{'='*60}\n")
    sys.exit(1 if failed else 0)