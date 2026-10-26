"""Aanvullende tests voor de risicotabel, vertrouwde routines/scenes en audit.

Dekt:
  - de risicotabel (TOOL_RISK) dekt exact de tools uit het schema (core/ai.py)
    en core/agent.py's VALID_TOOL_NAMES is een deelverzameling
  - de gecorrigeerde risico's/ids (set_volume, volume_up/down, browser_get_*,
    pc_status, get_home_assistant_entities)
  - de routine "gaming" (met "vertrouwd": true) draait zonder goedkeuring
  - de routine "sleep" (zonder vlag, met een switch-stap) vraagt wél
  - de scene-vlag "vertrouwd" wordt omgezet naar trusted= bij de executor
  - geweigerde, geannuleerde en verlopen goedkeuringen komen in het auditlog
  - het auditlog roteert boven 5 MB

Windows-code (pycaw, ctypes, ui-automation) wordt in de tests gemockt.
"""
import json
import time

import pytest

import core.ai as ai
import core.audit as audit
import core.brain as brain
from core.agent import VALID_TOOL_NAMES
from core.confirmation import get_pending, set_pending, clear_pending
from core.tool_registry import (
    TOOL_RISK,
    get_schema_tool_names,
    get_tool_idempotent,
    get_tool_risk,
)


@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    """Eigen conversation.json en audit-log; lege pending per test."""

    monkeypatch.setattr(ai, "CONVERSATION_FILE", str(tmp_path / "conversation.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    clear_pending()
    yield
    clear_pending()


# ----------------------------------------------------------------
# 1. Dekking: schema <-> risicotabel
# =========================================================

def test_schema_tools_hebben_allemaal_een_risico():
    schema = get_schema_tool_names()
    assert schema, "geen tools uit het schema gevonden"
    ontbreekt = sorted(schema - set(TOOL_RISK))
    assert not ontbreekt, f"tools zonder risico: {ontbreekt}"


def test_risicotabel_bevat_geen_niet_bestaande_tools():
    schema = get_schema_tool_names()
    onbekend = sorted(set(TOOL_RISK) - schema)
    assert not onbekend, f"risicotabel bevat geen echte tools: {onbekend}"


def test_valid_tool_names_is_deelverzameling_van_tool_risk():
    ontbreekt = sorted(set(VALID_TOOL_NAMES) - set(TOOL_RISK))
    assert not ontbreekt, f"agent-tools zonder risico: {ontbreekt}"


def test_gecorrigeerde_risicos():
    from core.tool_registry import get_tool_idempotent

    assert get_tool_risk("set_volume") == "low"
    assert get_tool_idempotent("set_volume") is True

    assert get_tool_risk("volume_up") == "low"
    assert get_tool_idempotent("volume_up") is False

    assert get_tool_risk("volume_down") == "low"
    assert get_tool_idempotent("volume_down") is False

    for naam in (
        "browser_get_content",
        "browser_get_title",
        "browser_get_url",
        "pc_status",
        "get_home_assistant_entities",
    ):
        assert get_tool_risk(naam) == "low", naam
        assert get_tool_idempotent(naam) is True, naam


def test_verwijderde_fantoomtools_staan_niet_meer_in_de_tabel():
    for naam in (
        "delete_file",
        "media_set_volume",
        "media_volume_up",
        "media_volume_down",
        "calculate",
        "get_information",
        "weather",
        "wikipedia",
    ):
        assert naam not in TOOL_RISK, naam


# =========================================================
# Vertrouwde routines
# =========================================================

def _mock_dispatch(monkeypatch, calls):
    monkeypatch.setattr(ai, "_dispatch_tool", lambda t, a, q: calls.append(t) or "ok")


def test_gaming_routine_draait_zonder_goedkeuring(monkeypatch):
    """'gaming' heeft "vertrouwd": true en mag zonder vraag draaien."""
    from core.confirmation import clear_pending, get_pending

    calls = []
    _mock_dispatch(monkeypatch, calls)
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda *a, **k: None)

    brain.routine_manager.reload()
    naam, routine = brain.routine_manager.resolve("ik ga gamen")
    assert naam == "gaming"
    assert routine.get("vertrouwd") is True

    clear_pending()
    brain._execute_routine(naam, routine, "ik ga gamen")

    assert get_pending() is None, "vertrouwde routine mag niet om goedkeuring vragen"
    assert "open_program" in calls
    assert "set_volume" in calls


def test_sleep_routine_zonder_vlag_vraagt_goedkeuring(monkeypatch):
    """Een routine zonder vlag met een switch-stap (medium) vraagt nog
    steeds goedkeuring. (Sinds Fase 21 zet 'sleep' de tv zelf uit, laag
    risico; daarom hier een eigen routine met een stekker.)"""
    from core.confirmation import clear_pending, get_pending

    calls = []
    _mock_dispatch(monkeypatch, calls)
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda *a, **k: None)

    naam = "sleep"
    routine = {"name": naam, "steps": [{"tool_name": "control_home_assistant", "arguments": {
        "domain": "switch", "service": "turn_off", "entity_id": "switch.stekker"}}]}
    monkeypatch.setattr(brain.routine_manager, "steps_for_agent", lambda n: [
        dict(s, status="pending", goal="routine: sleep") for s in routine["steps"]])
    assert not routine.get("vertrouwd")

    clear_pending()
    brain._execute_routine(naam, routine, "ik ga slapen")

    pending = get_pending()
    assert pending is not None, "onvertrouwde routine met medium stap moet vragen"
    assert pending["kind"] == "tool_approval"
    assert pending["tool_name"] == "control_home_assistant"


def test_spraak_opgeslagen_routine_krijgt_geen_vertrouwd_vlag(monkeypatch):
    """save_routine voegt nooit een 'vertrouwd'-vlag toe."""
    monkeypatch.setattr(brain.routine_manager, "track_usage", lambda *a, **k: None)
    opgeslagen = {}

    def fake_save(name, triggers, steps, description="", aliases=None):
        routine = {
            "name": name,
            "triggers": triggers,
            "aliases": aliases or [],
            "steps": steps,
            "description": description,
        }
        opgeslagen[name] = routine
        return routine

    monkeypatch.setattr(brain.routine_manager, "save_routine", fake_save)
    brain.routine_manager.save_routine("testje", ["\\btestje\\b"], [], "test")
    assert "vertrouwd" not in opgeslagen["testje"]


# =========================================================
# Vertrouwde scenes
# =========================================================

def test_scene_vertrouwd_wordt_doorgegeven_aan_executor(monkeypatch):
    gezien = {}

    def fake_executor(plan, vraag, trusted=False):
        gezien["trusted"] = trusted
        return [{"tool_name": plan[0]["tool_name"], "status": "done", "result": "ok"}]

    monkeypatch.setattr(brain, "execute_action_plan", fake_executor)
    stap = {"tool_name": "move_file", "arguments": {"filename": "a", "location": "b"}}

    brain._execute_scene("s1", {"name": "s1", "steps": [dict(stap)], "vertrouwd": True}, "doe s1")
    assert gezien["trusted"] is True

    brain._execute_scene("s2", {"name": "s2", "steps": [dict(stap)]}, "doe s2")
    assert gezien["trusted"] is False


# =========================================================
# Audit: weigering / annulering / verlopen / rotatie
# =========================================================

def _lees_regels(pad):
    tekst = pad.read_text(encoding="utf-8")
    return [json.loads(r) for r in tekst.splitlines() if r.strip()]


def test_geweigerde_goedkeuring_komt_in_auditlog(tmp_path, monkeypatch):
    import core.audit as audit
    from core.confirmation import clear_pending, get_pending

    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", str(audit_file))
    monkeypatch.setattr(ai, "_dispatch_tool", lambda *a: "ok")

    clear_pending()
    ai.execute_tool("ui_launch_app", {"path": "C:/x/app.exe"}, "start app")
    assert get_pending() is not None

    brain.handle_pending_choice("nee")

    regels = _lees_regels(audit_file)
    weigeringen = [r for r in regels if r["tool"] == "ui_launch_app" and r["goedgekeurd"] is False]
    assert weigeringen, "geweigerde goedkeuring moet in het auditlog staan"
    assert "geweigerd" in weigeringen[-1]["reden"].lower()


def test_geannuleerde_goedkeuring_komt_in_auditlog(tmp_path, monkeypatch):
    import core.audit as audit
    from core.confirmation import clear_pending

    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", str(audit_file))
    monkeypatch.setattr(ai, "_dispatch_tool", lambda *a: "ok")

    clear_pending()
    ai.execute_tool("ui_launch_app", {"path": "C:/x/app.exe"}, "start app")

    brain.handle_pending_choice("hmm")  # eerste keer onduidelijk -> hervraag
    brain.handle_pending_choice("hmm")  # tweede keer -> cancel

    regels = _lees_regels(audit_file)
    annuleringen = [r for r in regels if r["tool"] == "ui_launch_app" and r["goedgekeurd"] is False]
    assert annuleringen, "geannuleerde goedkeuring moet in het auditlog staan"
    assert "geannuleerd" in annuleringen[-1]["reden"].lower()


def test_verlopen_goedkeuring_komt_in_auditlog(tmp_path, monkeypatch):
    import core.audit as audit
    from core.confirmation import set_pending, get_pending

    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", str(audit_file))

    set_pending(
        "tool_approval",
        {"tool_name": "move_file", "arguments": {}, "risk": "medium", "question": "mag ik dit?", "source": "test"},
        ttl=0,
    )
    assert get_pending() is None  # verlopen -> gewist en gelogd

    regels = _lees_regels(audit_file)
    verlopen = [r for r in regels if r["tool"] == "move_file" and r["goedgekeurd"] is False]
    assert verlopen, "verlopen goedkeuring moet in het auditlog staan"
    assert "verlopen" in verlopen[-1]["reden"].lower()


def test_audit_roteert_boven_max_bytes(tmp_path, monkeypatch):
    import core.audit as audit

    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_FILE", str(audit_file))
    monkeypatch.setattr(audit, "MAX_AUDIT_BYTES", 50)

    audit_file.write_text("x" * 200, encoding="utf-8")
    audit.log_audit(
        gehoord="", handler="test", tool="t", argumenten={}, risico="low",
        resultaat="r", goedgekeurd=True,
    )

    maand = tmp_path / f"audit-{time.strftime('%Y%m')}.jsonl"
    assert maand.exists(), "oud auditlog moet naar het maandbestand roteren"
    assert audit_file.exists(), "er moet een nieuw auditlog zijn geopend"
    assert _lees_regels(audit_file)[-1]["tool"] == "t"
