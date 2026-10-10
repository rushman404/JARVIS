"""Pytest-tests voor de bevestigings-flow (pending-keuzes).

Dekt:
  - ttl van core/confirmation.py (verloopt en wordt gewist)
  - pending nooit naar schijf / herstart wist de pending
  - strenge ja/nee-matching voor gevaarlijke soorten
  - geen POWER_ACTIONS zonder geldige bevestiging
  - onduidelijk antwoord: één keer herhalen, daarna annuleren
  - annuleer afsluiten / annuleer herstart (shutdown /a)

Windows-code (pycaw, ctypes, os.system) wordt in de tests gemockt.
"""
import json
import time
import pytest
import core.ai as ai
import core.brain as brain
from core.confirmation import set_pending, get_pending, clear_pending, REASKED_KEY

@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    """Elk test krijgt een lege pending en een eigen conversation.json,
    zodat de echte conversation.json van JARVIS nooit wordt aangeraakt."""
    monkeypatch.setattr(ai, 'CONVERSATION_FILE', str(tmp_path / 'conversation.json'))
    vorige = ai.current_context.get('pending_choice')
    yield
    ai.current_context['pending_choice'] = vorige

def test_pending_verloopt_na_ttl():
    """Na de ttl geeft get_pending() None en is de state gewist."""
    set_pending('power_confirm', {'action': 'shutdown'}, ttl=0.05)
    assert get_pending() is not None
    assert get_pending()['kind'] == 'power_confirm'
    time.sleep(0.1)
    assert get_pending() is None
    assert ai.current_context.get('pending_choice') is None

def test_verlopen_pending_voert_geen_power_actie_uit():
    """Een 'ja' nadat de ttl verlopen is voert de afsluiting NIET uit."""
    aangeroepen = []

    def _shutdown():
        aangeroepen.append(True)
        return 'Afsluiten...'
    oorsprong = brain.POWER_ACTIONS.get('shutdown')
    brain.POWER_ACTIONS['shutdown'] = _shutdown
    try:
        set_pending('power_confirm', {'action': 'shutdown'}, ttl=0.05)
        time.sleep(0.1)
        antwoord = brain.handle_pending_choice('ja')
        assert antwoord is None
        assert aangeroepen == []
    finally:
        if oorsprong is not None:
            brain.POWER_ACTIONS['shutdown'] = oorsprong

def test_standaard_ttl_komt_uit_config():
    """Zonder ttl-argument wordt de waarde uit config.py gebruikt."""
    from config import CONFIRM_TTL_SECONDS
    set_pending('power_confirm', {'action': 'shutdown'})
    expires = ai.current_context['pending_choice']['_expires_at']
    nu = time.time()
    assert CONFIRM_TTL_SECONDS - 1 <= expires - nu <= CONFIRM_TTL_SECONDS + 1

def test_clear_pending_wist_zonder_ttl():
    """clear_pending() wist ook een nog niet verlopen pending."""
    set_pending('power_confirm', {'action': 'restart'}, ttl=60)
    assert get_pending() is not None
    clear_pending()
    assert get_pending() is None
    assert ai.current_context.get('pending_choice') is None

def test_pending_nooit_weggeschreven(tmp_path, monkeypatch):
    """_save_conversation schrijft pending_choice nooit naar schijf."""
    bestand = tmp_path / 'conversation.json'
    monkeypatch.setattr(ai, 'CONVERSATION_FILE', str(bestand))
    set_pending('power_confirm', {'action': 'shutdown'}, ttl=60)
    ai.current_context['last_command'] = 'pc afsluiten'
    ai._save_conversation()
    op_schijf = json.loads(bestand.read_text(encoding='utf-8'))
    assert 'pending_choice' not in op_schijf.get('context', {})
    assert op_schijf['context']['last_command'] == 'pc afsluiten'
    clear_pending()

@pytest.mark.parametrize('input_text, verwacht_result', [('ja', 'yes'), ('ja doe maar', 'yes'), ('bevestig', 'yes'), ('ja graag', 'yes'), ('ja maar niet nu', 'no'), ('nee', 'no'), ('stop', 'no'), ('laat maar', 'no'), ('misschien', 'unclear'), ('ok zet de muziek harder', 'unclear')])
def test_evaluate_answer_gevaarlijk(input_text, verwacht_result):
    """Gevaarlijke acties vereisen strikte match en checken op ontkenning."""
    from core.confirmation import evaluate_answer
    set_pending('power_confirm', {'action': 'shutdown'})
    res = evaluate_answer(input_text, 'power_confirm')
    assert res == verwacht_result

@pytest.mark.parametrize('input_text, verwacht_result', [('prima', 'yes'), ('goed', 'yes'), ('oke', 'yes'), ('nee hoor', 'no'), ('geen prullenbak', 'no'), ('wat?', 'unclear')])
def test_evaluate_answer_onschuldig(input_text, verwacht_result):
    """Onschuldige acties (bijv. list) gebruiken losse matching."""
    from core.confirmation import evaluate_answer
    set_pending('list', {'matches': ['a', 'b']})
    res = evaluate_answer(input_text, 'list')
    assert res == verwacht_result

def test_herstart_wist_pending(tmp_path, monkeypatch):
    """Bij opstarten wordt pending_choice NOOIT uit conversation.json teruggelezen."""
    data = {'history': [], 'context': {'last_command': 'pc afsluiten', 'pending_choice': {'kind': 'power_confirm', 'action': 'shutdown'}}}
    bestand = tmp_path / 'conversation.json'
    bestand.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(ai, 'CONVERSATION_FILE', str(bestand))
    _history, geladen_context = ai._load_conversation()
    assert 'pending_choice' not in geladen_context
    assert geladen_context.get('last_command') == 'pc afsluiten'
    ai.current_context.update(geladen_context)
    assert get_pending() is None

def test_brain_handle_pending_reask_en_cancel(monkeypatch):
    """Brain vraagt één keer opnieuw, daarna is het 'cancel' (annuleren)."""
    set_pending('power_confirm', {'action': 'shutdown'})
    resp1 = brain.handle_pending_choice('misschien')
    assert 'Zeg duidelijk' in resp1
    assert get_pending() is not None
    assert get_pending().get(REASKED_KEY) is True
    resp2 = brain.handle_pending_choice('zal kijken')
    assert resp2 is None
    assert get_pending() is None

def test_brain_handle_pending_ja_roept_power_aan(monkeypatch):
    """Bij een geldige 'ja' wordt de actie in POWER_ACTIONS aangeroepen."""
    called = []

    def mock_shutdown():
        called.append(True)
        return 'Afsluiten...'
    monkeypatch.setitem(brain.POWER_ACTIONS, 'shutdown', mock_shutdown)
    set_pending('power_confirm', {'action': 'shutdown'})
    resp = brain.handle_pending_choice('ja graag')
    assert 'Afsluiten...' in resp
    assert called == [True]
    assert get_pending() is None

def test_shutdown_annuleren_direct(monkeypatch):
    """'annuleer afsluiten' roept cancel_shutdown aan."""
    called = []

    def mock_cancel():
        called.append(True)
        return 'Geannuleerd'
    monkeypatch.setattr(brain, 'cancel_shutdown', mock_cancel)
    resp = brain.try_power_command('annuleer het afsluiten')
    assert resp == 'Geannuleerd'
    assert called == [True]
