"""Pytest-tests voor het risico- en goedkeuringssysteem.

Dekt:
  - een high-risico tool (ui_launch_app) wordt zonder goedkeuring NIET
    uitgevoerd, en pas wél na een geldig "ja"
  - een door de LLM opgegeven risk="low" wordt genegeerd (tabel wint)
  - een onbekende tool vraagt om bevestiging (medium)
  - routines met medium stappen vragen om bevestiging, tenzij de routine
    een "vertrouwd"-vlag heeft
  - de audit-regel (logs/audit.jsonl) bevat tool, risico, resultaat,
    goedkeuring en geen geheimen

Windows-code (pycaw, ctypes, ui-automation) wordt in de tests gemockt.
"""
import json
import pytest
import core.ai as ai
import core.brain as brain
import core.audit as audit
from core.confirmation import get_pending, clear_pending
from core.executor import execute_action_plan
from core.tool_registry import get_tool_risk

@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    """Elk test krijgt een lege pending, een eigen conversation.json en
    een eigen audit-log, zodat de echte bestanden nooit worden aangeraakt."""
    monkeypatch.setattr(ai, 'CONVERSATION_FILE', str(tmp_path / 'conversation.json'))
    monkeypatch.setattr(audit, 'AUDIT_FILE', str(tmp_path / 'audit.jsonl'))
    clear_pending()
    yield
    clear_pending()

def test_ui_launch_app_zonder_goedkeuring_wordt_niet_uitgevoerd(monkeypatch):
    """Een high-risico tool draait niet zonder "ja" van de gebruiker."""
    aangeroepen = []

    def fake_dispatch(tool_name, arguments, question):
        aangeroepen.append(tool_name)
        return 'programma gestart'
    monkeypatch.setattr(ai, '_dispatch_tool', fake_dispatch)
    uitkomst = ai.execute_tool('ui_launch_app', {'path': 'C:/test/app.exe'}, 'start app')
    assert aangeroepen == []
    assert 'akkoord' in uitkomst
    pending = get_pending()
    assert pending is not None
    assert pending['kind'] == 'tool_approval'
    assert pending['tool_name'] == 'ui_launch_app'
    assert get_tool_risk('ui_launch_app') == 'high'
    antwoord = brain.handle_pending_choice('ja graag')
    assert aangeroepen == ['ui_launch_app']
    assert antwoord == 'programma gestart'
    assert get_pending() is None

def test_ui_launch_app_met_nee_wordt_overgeslagen(monkeypatch):
    """Bij "nee" wordt de tool overgeslagen en dat wordt gemeld."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    ai.execute_tool('ui_launch_app', {'path': 'C:/test/app.exe'}, 'start app')
    antwoord = brain.handle_pending_choice('laat maar')
    assert antwoord == 'Oké, ik voer het niet uit.'
    assert aangeroepen == []
    assert get_pending() is None

def test_door_llm_opgegeven_risk_low_wordt_genegeerd(monkeypatch):
    """De vaste tabel wint: move_file is medium, ook al zet de LLM risk="low"."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    plan = [{'tool_name': 'move_file', 'arguments': {'filename': 'a.txt', 'location': '.'}, 'risk': 'low', 'status': 'pending'}]
    resultaten = execute_action_plan(plan, 'verplaats a.txt')
    assert aangeroepen == []
    assert get_pending() is not None
    assert resultaten, 'het plan moet een goedkeuringsrecord teruggeven'
    assert resultaten[0]['status'] == 'approval_required'
    assert resultaten[0]['risk'] == 'medium'

def test_onbekende_tool_heeft_risico_medium():
    """Een tool die niet in de tabel staat is medium (fail-safe)."""
    assert get_tool_risk('volledig_onbekende_tool_xyz') == 'medium'

def test_onbekende_tool_vraagt_bevestiging(monkeypatch):
    """Een onbekende tool wordt niet zomaar uitgevoerd."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    uitkomst = ai.execute_tool('volledig_onbekende_tool_xyz', {'iets': 1}, 'test')
    assert 'akkoord' in uitkomst
    assert aangeroepen == []
    assert get_pending()['kind'] == 'tool_approval'

def test_routine_medium_stap_vraagt_bevestiging(monkeypatch):
    """Een gewone routine met een medium stap pauzeert op goedkeuring."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    plan = [{'tool_name': 'ui_type_text', 'arguments': {'handle': 'h1', 'text': 'hallo'}, 'status': 'pending'}]
    resultaten = execute_action_plan(plan, 'routine: autotest')
    assert aangeroepen == []
    assert get_pending() is not None
    assert resultaten[0]['status'] == 'approval_required'

def test_routine_medium_stap_zonder_vertrouwd_pauzeert(monkeypatch):
    """Zonder 'vertrouwd'-vlag vraagt een routine bevestiging (via brain)."""
    monkeypatch.setattr(brain.routine_manager, 'steps_for_agent', lambda naam: [{'tool_name': 'ui_type_text', 'arguments': {'handle': 'h1', 'text': 'x'}, 'status': 'pending'}])
    monkeypatch.setattr(brain.routine_manager, 'track_usage', lambda *a, **k: None)
    brain._execute_routine('autotest', {'name': 'autotest', 'description': ''}, 'start autotest')
    assert get_pending() is not None

def test_routine_met_vertrouwd_vlag_voert_direct_uit(monkeypatch):
    """Met 'vertrouwd': true slaat de routine de goedkeuring over."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    plan = [{'tool_name': 'ui_type_text', 'arguments': {'handle': 'h1', 'text': 'hallo'}, 'status': 'pending'}]
    resultaten = execute_action_plan(plan, 'routine: vertrouwd', trusted=True)
    assert aangeroepen == ['ui_type_text']
    assert get_pending() is None
    assert resultaten[0]['status'] == 'done'

def test_routine_vertrouwd_flag_wordt_doorgegeven_aan_executor(monkeypatch):
    """brain zet de 'vertrouwd'-vlag om naar trusted= bij de executor."""
    gezien = {}

    def fake_executor(plan, vraag, trusted=False, bij_stap=None):
        gezien['trusted'] = trusted
        return [{'tool_name': plan[0]['tool_name'], 'status': 'done', 'result': 'ok'}]
    monkeypatch.setattr(brain, 'execute_action_plan', fake_executor)
    monkeypatch.setattr(brain.routine_manager, 'steps_for_agent', lambda naam: [{'tool_name': 'move_file', 'arguments': {'filename': 'a', 'location': 'b'}, 'status': 'pending'}])
    monkeypatch.setattr(brain.routine_manager, 'track_usage', lambda *a, **k: None)
    brain._execute_routine('test', {'name': 'test', 'description': '', 'vertrouwd': True}, 'start test')
    assert gezien['trusted'] is True
    brain._execute_routine('test', {'name': 'test', 'description': ''}, 'start test')
    assert gezien['trusted'] is False

def test_multistap_plan_loopt_tot_goedkeuringsstap(monkeypatch):
    """Eerste (low) stap loopt, de medium stap pauzeert het plan."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    plan = [{'tool_name': 'open_program', 'arguments': {'program': 'kladblok'}, 'status': 'pending'}, {'tool_name': 'copy_file', 'arguments': {'filename': 'a.txt', 'location': 'b'}, 'status': 'pending'}]
    resultaten = execute_action_plan(plan, 'open kladblok en kopieer a.txt')
    assert aangeroepen == ['open_program']
    assert resultaten[0]['status'] == 'done'
    assert get_pending()['kind'] == 'tool_approval'
    assert resultaten[1]['status'] == 'approval_required'
    antwoord = brain.handle_pending_choice('ja')
    assert 'ok' in antwoord or 'ok' == antwoord
    assert aangeroepen == ['open_program', 'copy_file']
    assert get_pending() is None

def test_hervatten_na_nee_stopt_plan(monkeypatch):
    """Nee op de goedkeuring stopt netjes: de stap wordt overgeslagen."""
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    plan = [{'tool_name': 'open_program', 'arguments': {'program': 'kladblok'}, 'status': 'pending'}, {'tool_name': 'copy_file', 'arguments': {'filename': 'a.txt', 'location': 'b'}, 'status': 'pending'}]
    execute_action_plan(plan, 'open kladblok en kopieer a.txt')
    assert aangeroepen == ['open_program']
    antwoord = brain.handle_pending_choice('nee')
    assert antwoord == 'Oké, ik voer het niet uit.'
    assert aangeroepen == ['open_program']
    assert get_pending() is None

def test_audit_log_bevat_risico_resultaat_en_goedkeuring(tmp_path, monkeypatch):
    """De audit-regel bevat de gevraagde velden en saneeert geheimen."""
    monkeypatch.setattr(audit, 'AUDIT_FILE', str(tmp_path / 'audit.jsonl'))
    audit.log_audit(gehoord='verplaats a.txt', handler='test', tool='move_file', argumenten={'filename': 'a.txt', 'password': 'geheim123'}, risico='medium', resultaat='verplaatst', goedgekeurd=True)
    regel = json.loads((tmp_path / 'audit.jsonl').read_text(encoding='utf-8').strip())
    assert regel['tool'] == 'move_file'
    assert regel['risico'] == 'medium'
    assert regel['resultaat'] == 'verplaatst'
    assert regel['goedgekeurd'] is True
    assert regel['gehoorde-tekst'] == 'verplaats a.txt'
    assert regel['handler'] == 'test'
    assert 'tijd' in regel
    assert regel['argumenten']['password'] == '***'
    assert 'geheim123' not in json.dumps(regel)

def test_laag_risico_wordt_direct_uitgevoerd_en_geregistreerd(tmp_path, monkeypatch):
    """Een low-risico tool draait meteen en wordt goedgekeurd geregistreerd."""
    monkeypatch.setattr(audit, 'AUDIT_FILE', str(tmp_path / 'audit.jsonl'))
    aangeroepen = []
    monkeypatch.setattr(ai, '_dispatch_tool', lambda *a: aangeroepen.append(a[0]) or 'ok')
    uitkomst = ai.execute_tool('media_play_pause', {}, 'pauzeer')
    assert aangeroepen == ['media_play_pause']
    assert uitkomst == 'ok'
    assert get_pending() is None
    regel = json.loads((tmp_path / 'audit.jsonl').read_text(encoding='utf-8').strip())
    assert regel['tool'] == 'media_play_pause'
    assert regel['risico'] == 'low'
    assert regel['goedgekeurd'] is True
