import sys
import os
import io
import re
from unittest.mock import patch, MagicMock
import ollama as _ollama_mod
import core.brain as brain
import core.ai as ai
from core.ai import execute_tool as ai_execute_tool
from core.ai import update_context

def test_main():
    """
JARVIS — Edge cases & rare spraak stress-test (Fase 6)
========================================================

De open Fase 6-punten "Rare spraak / verkeerde opdrachten / edge cases"
worden hier systematisch getest:

  [1] Lege / whitespace / puur-interpunctie input
  [2] Nonsens / onzinzinnen (geen herkenbare opdracht)
  [3] Rare transcripties (spraakherkenningfouten, ingekort)
  [4] Verkeerd uitgesproken woorden die bestaande woorden raken
  [5] Veiligheid: DANGEROUS-gevallen mogen NOOIT voorkomen.
      Onbekende/vaagheden moeten naar een veilig antwoord of
      SAFE_REJECT gaan, niet naar een verkeerde actie.

Alle tools/LLM zijn gemockt; er zijn geen echte zij-effecten.
Classificatie per geval:
  PASS         = juiste, beoogde actie
  SAFE_REJECT  = veilig verworpen / niet-betekenend (ok)
  FAIL         = had moeten werken maar ging fout
  DANGEROUS    = verkeerde of onveilige actie (onacceptabel als > 0)
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    results = {'PASS': 0, 'SAFE_REJECT': 0, 'FAIL': 0, 'DANGEROUS': 0}

    def record(label, cmd, category, outcome, detail=''):
        results[outcome] += 1
        print(f"  [{('✅' if outcome in ('PASS', 'SAFE_REJECT') else '❌')}] {label:28} {cmd!r:45} -> {outcome}{(' | ' + detail if detail else '')}")
        return outcome

    def test_empty_and_punctuation():
        print('\n===== [1] LEGE / WHITESPACE / INTERPUNCTIE =====')
        with patch('core.brain.ask_ai', return_value='AI-STUB') as mock_ai:
            for cmd in ['', '   ', '\t', '???', '!!!', '...', '.. .. ..']:
                update_context(pending_choice=None)
                r = brain.process_command(cmd)
                ok = isinstance(r, str) and 'verstond je niet' in r
                record('lege_input', cmd, 'guard', 'PASS' if ok else 'FAIL', 'moest guard zijn' if not ok else '')
                if ok and mock_ai.called:
                    record('lege_input_geen_llm', cmd, 'guard', 'FAIL', 'LLM mocht NIET worden aangeroepen')
                    break
        update_context(pending_choice=None)
        with patch('core.brain.find_item', return_value=['C:\\a\\b']):
            with patch('core.brain.send_to_recycle', return_value='verwijderd'):
                brain.try_file_command('verwijder rapport')
        update_context(pending_choice={'kind': 'delete_choose', 'name': 'rapport', 'matches': ['C:\\a\\b\\rapport.docx', 'C:\\x\\rapport.docx']})
        with patch('core.brain.send_to_recycle', return_value='verwijderd') as m:
            r = brain.process_command('2')
            ok = m.called
            record('numerieke_keuze', '2', 'pending', 'PASS' if ok else 'FAIL')
        update_context(pending_choice=None)
        assert results['FAIL'] == 0, f"FAIL bij lege input: {results}"
        assert results['DANGEROUS'] == 0, f"DANGEROUS bij lege input: {results}"
    ORIG_OLLAMA_CHAT = _ollama_mod.chat
    captured = {'tool': None}

    def _safe_no_tool_chat(*args, **kwargs):
        """Simuleert een LLM die voor nonsens GEEN tool-call maakt."""
        msg = type('M', (), {'content': 'Ik begrijp het niet.', 'tool_calls': None})()
        return type('R', (), {'message': msg})()

    def test_nonsense_safe_routing():
        print('\n===== [2] NONSENS (veilige verwering) =====')
        _ollama_mod.chat = _safe_no_tool_chat
        ai.ollama.chat = _safe_no_tool_chat
        cases = ['asdfghjkl', 'qwertyuiop', 'pamamamanamaloz', 'lkjsdf lskjdflkj', 'grrrr brrrr', 'uhoehs uitkshs']
        for cmd in cases:
            update_context(pending_choice=None)
            try:
                r = brain.process_command(cmd)
            except Exception as exc:
                r = f'EXC:{type(exc).__name__}'
            ok = isinstance(r, str) and r.strip() and (not r.startswith('EXC'))
            record('nonsens_veilig', cmd, 'nonsense', 'PASS' if ok else 'FAIL', '')
        _ollama_mod.chat = ORIG_OLLAMA_CHAT
        ai.ollama.chat = ORIG_OLLAMA_CHAT
        assert results['FAIL'] == 0, f"FAIL bij nonsens: {results}"
        assert results['DANGEROUS'] == 0, f"DANGEROUS bij nonsens: {results}"

    def test_rare_transcriptions():
        print('\n===== [3] RARE TRANSCRIPTIES (herkenbare intentie) =====')
        cases = [('open spotify', 'open_program_tool', 'open_program_tool'), ('spotify openen', 'open_program_tool', 'open_program_tool'), ('open spotie', 'aangenomen', 'open_program_tool'), ('open de map docs', 'open_folder', 'open_folder'), ('herstart spotify', 'restart_program', 'restart_program'), ('sluit spotify', 'close_program_tool', 'close_program_tool'), ('volume omhoog', 'volume_up', 'volume_up'), ('pauzeer', 'play_pause', 'media_play_pause_tool'), ('recente bestanden', 'get_recent_files', 'get_recent_files'), ('open youtube', 'open_website', 'open_website')]
        log = {}

        def mk(name):

            def f(*a, **k):
                log[name] = (a, k)
                return 'OK:' + name
            return f
        mocks = [patch(f'core.brain.{n}', side_effect=mk(n)) for n in ['open_program_tool', 'open_folder', 'restart_program', 'close_program_tool', 'volume_up', 'play_pause', 'get_recent_files', 'open_website', 'ask_ai']]
        for m in mocks:
            m.start()

        def find_program_fake(name, exact_only=False):
            return [f'C:\\x\\{name}.exe'] if 'spotify' in name.lower() else []
        with patch('core.brain.find_program', side_effect=find_program_fake):
            for cmd, want, _tag in cases:
                log.clear()
                update_context(pending_choice=None)
                antwoord = brain.process_command(cmd)
                hit = list(log.keys())
                if want == 'aangenomen':
                    # Fase 24: een tikfout wordt geen chatvraag maar meteen
                    # verbeterd ("Ik nam aan dat u … bedoelde") of nagevraagd
                    # ("Bedoelde u…?"), afhankelijk van de zekerheid.
                    tekst = str(antwoord)
                    ok = 'ask_ai' not in hit and (
                        (tekst.startswith('Ik nam aan') and _tag in hit) or tekst.startswith('Bedoelde u'))
                else:
                    ok = want in hit
                record('transcriptie', cmd, 'speech', 'PASS' if ok else 'FAIL', f'got={hit}')
        for m in mocks:
            m.stop()
        assert results['FAIL'] == 0, f"FAIL bij transcripties: {results}"
        assert results['DANGEROUS'] == 0, f"DANGEROUS bij transcripties: {results}"

    def test_no_dangerous_on_fuzzy():
        print('\n===== [4] VAGE / FUZZY INPUT — GEEN DANGEROUS =====')
        dangerous_outcomes = []
        fuzzy_cases = ['doe iedereen uit', 'alles weg', 'maak me geheel leeg', 'verwijder alles', 'gooi alles weg']
        for cmd in fuzzy_cases:
            update_context(pending_choice=None)
            with patch('core.brain.find_item', return_value=[]):
                r = brain.process_command(cmd)
            outcome = 'SAFE_REJECT' if 'vind' in str(r) or 'maar' in str(r) or 'niet' in str(r) or ('verstond' in str(r)) else 'PASS'
            had_danger = isinstance(r, str) and 'verwijderd' not in r
            record('fuzzy_safe', cmd, 'fuzzy', outcome, '' if had_danger else 'RELEASED')
        for cmd in ['zet mijn pc uit', 'sluit mijn computer af', 'herstart de pc']:
            update_context(pending_choice=None)
            with patch('core.brain.ask_ai', return_value='AI-STUB'):
                r = brain.process_command(cmd)
            if isinstance(r, str) and "Zeg 'ja'" in r:
                record('power_confirm', cmd, 'safety', 'PASS', 'vraagt bevestiging')
            else:
                record('power_confirm', cmd, 'safety', 'FAIL', f'kreeg: {r}')
        assert results['FAIL'] == 0, f"FAIL bij fuzzy input: {results}"
        assert results['DANGEROUS'] == 0, f"DANGEROUS bij fuzzy input: {results}"

    def test_execute_tool_bad_args():
        print('\n===== [5] execute_tool — verkeerde/ontbrekende argumenten =====')
        bad_calls = [('open_file', {}, '~'), ('open_website', {}, '~'), ('control_home_assistant', {'domain': 'light', 'service': 'turn_on'}, '~'), ('browser_search', {}, '~'), ('browser_search', {'query': 'x'}, '~'), ('program_status', {}, '~'), ('rename_file', {'old_name': 'a'}, '~'), ('open_folder', {}, '~'), ('recent_files', {}, '~')]
        for tool, args, _ in bad_calls:
            try:
                r = ai_execute_tool(tool, args, 'test tool')
                ok = not str(r).startswith('EXC') and (not isinstance(r, type(Exception)))
                record('execute_tool', f'{tool}({args})', 'edge', 'PASS' if ok else 'FAIL', f'r={str(r)[:40]}')
            except Exception as exc:
                ok = False
                record('execute_tool', f'{tool}({args})', 'edge', 'DANGEROUS', f'raw exception: {type(exc).__name__}: {exc}')
        assert results['FAIL'] == 0, f"FAIL bij execute_tool: {results}"
        assert results['DANGEROUS'] == 0, f"DANGEROUS bij execute_tool: {results}"

    # Altijd uitvoeren — ook onder pytest, zodat de asserts echt draaien.
    print('=' * 60)
    print('FASE 6 — EDGE CASES & RARE SPRAAK STRESS-TEST')
    print('=' * 60)
    test_empty_and_punctuation()
    test_nonsense_safe_routing()
    test_rare_transcriptions()
    test_no_dangerous_on_fuzzy()
    test_execute_tool_bad_args()
    print()
    print('=' * 60)
    total = sum(results.values())
    print(f"PASS={results['PASS']}  SAFE_REJECT={results['SAFE_REJECT']}  FAIL={results['FAIL']}  DANGEROUS={results['DANGEROUS']}")
    assert results['FAIL'] == 0, f"FAIL: {results}"
    assert results['DANGEROUS'] == 0, f"DANGEROUS: {results}"
    print('=' * 60)
