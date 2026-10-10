import sys
import os
import io
import shutil
import tempfile
from unittest.mock import patch
from memory import store
import memory.memory as mem
from core.context_memory import build_memory_context, detect_conversation_reference, has_conversation_reference, rank_context_items, drop_duplicate_memories, _score_context_item, _normalize, _recent_history, DEFAULT_CONTEXT_MEMORIES

def test_main():
    """
JARVIS â€” Context + long-term memory tests (Fase 14, Stap 6)
==========================================================

Test de gecombineerde context/memory-laag in core/context_memory.py:

  1. alleen context
  2. alleen long-term memory
  3. context + memory samen
  4. directe verwijzingen ("hem", "die", "opnieuw")
  5. context weegt zwaarder dan een oudere memory
  6. dubbele informatie wordt weggelaten
  7. bestaande context-velden blijven werken
  8. het gecombineerde blok komt bij de AI/Agent aan
  9. backwards compatibility

Alle tests draaien op tijdelijke geheugenbestanden. De echte
memory/memory.json en memory/conversation.json worden niet aangeraakt.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    work = tempfile.mkdtemp(prefix='jarvis_ctxmem_test_')
    path = os.path.join(work, 'memory.json')
    store.reset_cache()
    _real_conversation = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'memory', 'conversation.json')
    _real_conversation_existed = os.path.exists(_real_conversation)
    _real_conversation_before = open(_real_conversation, 'rb').read() if _real_conversation_existed else b''
    CTX = {'last_command': 'open kladblok', 'last_result': 'Kladblok geopend', 'last_action': 'program_started:Kladblok', 'last_calculation': '10 + 5 = 15', 'last_program': 'kladblok', 'last_file': 'rapport.docx', 'last_website': '', 'last_ha_entity': '', 'last_ha_domain': '', 'last_ha_name': '', 'pending_choice': None}
    HISTORY = [{'role': 'user', 'content': 'open kladblok'}, {'role': 'jarvis', 'content': 'Kladblok geopend'}]
    with patch.object(mem, 'MEMORY_FILE', path):
        mem.remember('favoriete_kleur', 'blauw', category='voorkeuren')
        mem.remember('gpu', 'RTX 3060 Ti', category='pc')
        mem.remember('favoriete_band', 'Coldplay', category='muziek')
        print('\n===== 1: ALLEEN CONTEXT =====\n')
        blok = build_memory_context('open het programma opnieuw', context=CTX, history=[])
        assert bool(blok), 'context levert een blok op'
        assert 'DIT GESPREK' in blok, 'het blok noemt het gesprek'
        assert 'kladblok' in blok, 'het blok bevat het programma'
        assert 'WAT IK OVER JOU WEET' not in blok or '(niets relevant gevonden)' in blok, 'er staat geen langetermijnblok zonder memories'
        assert build_memory_context('open het programma', context={}, history=[]) == '', 'lege context levert een lege string'
        assert build_memory_context('open kladblok', context=None, history=[]) == '', 'None als context werkt (valt terug op leeg)'
        print('\n===== 2: ALLEEN LONG-TERM MEMORY =====\n')
        blok = build_memory_context('wat is mijn gpu', context={}, history=[])
        assert bool(blok), 'memory levert een blok op'
        assert 'WAT IK OVER JOU WEET' in blok, 'het blok noemt het geheugen'
        assert 'RTX 3060 Ti' in blok, 'het blok bevat de gpu'
        assert 'DIT GESPREK' not in blok, 'het blok bevat geen gespreksblok'
        assert 'RECENTE GESPREK' not in blok, 'het blok bevat geen gespreksregels'
        kleur_blok = build_memory_context('mijn favoriete kleur', context={})
        assert 'favoriete kleur is blauw' in kleur_blok, 'een voorkeur wordt als zin getoond'
        assert 'gpu:' in blok, 'een pc-feit wordt als sleutel:waarde getoond'
        assert build_memory_context('zzqqxx wwvvuu', context={}, history=[]) == '', 'een irrelevante vraag zonder context levert niets op'
        print('\n===== 3: CONTEXT + MEMORY SAMEN =====\n')
        blok = build_memory_context('open kladblok en wat is mijn kleur', context=CTX, history=HISTORY)
        assert 'DIT GESPREK' in blok and 'WAT IK OVER JOU WEET' in blok, 'beide blokken staan erin'
        assert 'RECENTE GESPREK' in blok, 'het recente gesprek staat erbij'
        assert 'kladblok' in blok, 'het programma uit de context staat erbij'
        assert 'blauw' in blok, 'de voorkeur uit het geheugen staat erbij'
        assert 'open kladblok' in blok, 'de gebruikerszin staat in het blok'
        assert 'Kladblok geopend' in blok, 'het antwoord van jarvis staat in het blok'
        assert 'HOE JE DIT GEBRUIKT' in blok, 'er staat een regel over het gebruik'
        assert 'Verzin niets dat er niet staat' in blok, 'er staat een regel tegen verzinnen'
        assert '1. DIT GESPREK' in blok, 'blok 1 is het gesprek'
        assert '2. RECENTE GESPREK' in blok, 'blok 2 is het gesprek'
        assert '3. WAT IK OVER JOU WEET' in blok, 'blok 3 is het geheugen'
        assert 'ZWAARDER' not in blok, 'zonder verwijzing geldt de normale regel'
        print('\n===== 4: DIRECTE VERWIJZINGEN =====\n')
        cases = [('open hem opnieuw', 'hem'), ('doe die maar opnieuw', 'die'), ('nogmaals', 'nogmaals'), ('herhaal dat', 'herhaal'), ('dezelfde nog een keer', 'dezelfde'), ('sluit het af', 'het'), ('nog een keer proberen', 'opnieuw')]
        for vraag, verwacht in cases:
            gevonden = detect_conversation_reference(vraag)
            assert verwacht in gevonden, f'{vraag!r} herkent {verwacht!r}'
        assert detect_conversation_reference('wat is mijn gpu') == [], 'een gewone vraag is geen verwijzing'
        assert has_conversation_reference('open hem opnieuw', {}) is True, "'opnieuw' is een sterke verwijzing"
        assert has_conversation_reference('nogmaals') is True, "'nogmaals' is een sterke verwijzing"
        assert has_conversation_reference('open hem', {}) is False, "'hem' zonder context telt niet"
        assert has_conversation_reference('open hem', CTX) is True, "'hem' mÃ©t context telt wel"
        blok = build_memory_context('open het programma opnieuw', context=CTX, history=[])
        assert 'verwijst naar iets uit dit gesprek' in blok, 'het blok meldt de verwijzing'
        assert 'ZWAARDER' in blok, 'het blok zegt dat blok 1 zwaarder weegt'
        assert 'opnieuw' in blok, 'het blok noemt de woorden uit de vraag'
        print('\n===== 5: CONTEXT ZWAARDER DAN OUDE MEMORY =====\n')
        ctx_conflict = {'last_command': 'open kladblok', 'last_result': '', 'last_action': '', 'last_calculation': '', 'last_program': 'kladblok', 'last_file': '', 'last_website': '', 'last_ha_entity': '', 'last_ha_domain': '', 'last_ha_name': '', 'pending_choice': None}
        mem.remember('actief_programma', 'word', category='apparaten')
        blok = build_memory_context('open het actieve programma opnieuw', context=ctx_conflict, history=[])
        assert 'kladblok' in blok, 'de context staat erbij'
        assert 'ZWAARDER' in blok, 'het blok zegt dat het gesprek zwaarder weegt'
        assert 'WAT IK OVER JOU WEET' in blok, 'het geheugen staat er ook nog in'
        items = rank_context_items('open het actieve programma opnieuw', ctx_conflict)
        assert len(items) >= 1, 'de context levert treffers'
        assert items[0]['field'] == 'last_program', 'het programma staat bovenaan'
        assert all((i['score'] > 0 for i in items)), 'elk contextveld krijgt een score'
        assert _score_context_item('open kladblok', 'Laatste opdracht', 'open kladblok', 1.0) > _score_context_item('open iets anders', 'Laatste opdracht', 'open kladblok', 1.0), 'de waarde letterlijk in de vraag scoort extra'
        assert _score_context_item('open kladblok', 'Laatste opdracht', '', 1.0) == 0.0, 'een lege waarde scoort 0'
        assert [i['score'] for i in items] == sorted([i['score'] for i in items], reverse=True), 'context is aflopend gesorteerd'
        print('\n===== 6: DUBBELE INFORMATIE =====\n')
        mem.remember('blad_programma', 'kladblok', category='apparaten')
        dubbel_ctx = dict(ctx_conflict)
        dubbel_ctx['last_result'] = ''
        memories = mem.get_relevant_memory('open het blad programma')
        assert any((i['key'] == 'blad_programma' for i in memories)), 'de dubbele memory is opgehaald'
        kept = drop_duplicate_memories(memories, [{'value': 'kladblok'}], [])
        assert 'blad_programma' not in [i['key'] for i in kept], 'een memory met dezelfde waarde als de context wordt weggelaten'
        kleur_memories = mem.get_relevant_memory('mijn kleur')
        kept = drop_duplicate_memories(kleur_memories, [], [{'content': 'de kleur is blauw'}])
        assert 'favoriete_kleur' not in [i['key'] for i in kept], 'een memory die in het gesprek voorkomt wordt weggelaten'
        gpu_memories = mem.get_relevant_memory('mijn gpu')
        kept = drop_duplicate_memories(gpu_memories, [], [{'content': 'wat is mijn gpu'}])
        assert 'gpu' in [i['key'] for i in kept], 'een vraag in de geschiedenis haalt de memory niet weg'
        mem.remember('kort_fact', 'ja', category='algemeen')
        kort = mem.get_relevant_memory('kort_fact')
        assert 'kort_fact' in [i['key'] for i in drop_duplicate_memories(kort, [{'value': 'ja'}], [])], 'een korte waarde wordt nooit als dubbeling weggehaald'
        blok = build_memory_context('open het blad programma', context=dubbel_ctx, history=[])
        assert blok.count('kladblok') <= 1, "het gecombineerde blok noemt 'kladblok' maar Ã©Ã©n keer"
        print('\n===== 7: BESTAANDE CONTEXT-VELDEN =====\n')
        velden = {'last_command': 'open kladblok', 'last_result': 'Kladblok geopend', 'last_action': 'program_started:Kladblok', 'last_calculation': '10 + 5 = 15', 'last_program': 'kladblok', 'last_file': 'rapport.docx', 'last_website': 'nu.nl', 'last_ha_entity': 'woonkamer_lamp', 'last_ha_domain': 'light', 'last_ha_name': 'Woonkamerlamp', 'pending_choice': None}
        veld_vragen = {'last_command': 'open kladblok nog eens', 'last_result': 'wat was het resultaat', 'last_action': 'welke actie was dat', 'last_calculation': 'wat was de laatste berekening', 'last_program': 'welk programma stond open', 'last_file': 'welk bestand was dat', 'last_website': 'welke website was dat', 'last_ha_entity': 'zet de woonkamer_lamp aan'}
        for veld, vraag in veld_vragen.items():
            items = rank_context_items(vraag, velden)
            assert any((i['field'] == veld for i in items)), f'{veld} wordt herkend'
        assert 'last_ha_domain' not in [i['field'] for i in rank_context_items('licht', velden)], 'last_ha_domain is geen apart veld'
        items = rank_context_items('woonkamer_lamp', velden)
        assert any(('light' in i['value'] for i in items)), 'de HA-domeinnaam staat bij het apparaat'
        met_pending = dict(velden)
        met_pending['pending_choice'] = {'kind': 'memory_update'}
        blok = build_memory_context('mijn kleur', context=met_pending)
        assert 'wacht' in blok, 'een openstaande vraag wordt gemeld'
        leeg = {'last_command': '', 'last_result': None, 'last_action': '   ', 'last_calculation': '', 'last_program': '', 'last_file': '', 'last_website': '', 'last_ha_entity': '', 'last_ha_domain': '', 'last_ha_name': '', 'pending_choice': None}
        assert rank_context_items('open kladblok', leeg) == [], 'lege en None-contextvelden geven geen items'
        items = rank_context_items('woonkamer_lamp', velden)
        assert 'light' in (items[0]['value'] if items else ''), 'het HA-domein staat bij het apparaat'
        print('\n===== 8: AANKOMST BIJ AI EN AGENT =====\n')
        import core.ai as ai
        import core.agent as agent
        _conversation_patch = patch.object(ai, '_save_conversation', lambda: None)
        _conversation_patch.start()
        gevangen = {}

        class FakeBericht:
            content = 'Antwoord van het model.'
            tool_calls = None

        class FakeOllama:

            @staticmethod
            def chat(model=None, messages=None, format=None, **kwargs):
                gevangen['messages'] = messages
                return type('R', (), {'message': FakeBericht()})()

        def system_tekst(messages):
            return '\n'.join((str(m.get('content', '')) for m in messages or [] if m.get('role') == 'system'))
        with patch.object(ai, 'ollama', FakeOllama), patch.object(ai, '_save_conversation', lambda: None):
            ai.current_context.update(CTX)
            ai.conversation_history.clear()
            ai.conversation_history.extend(HISTORY)
            try:
                ai.ask_ai('open het programma opnieuw')
            except Exception:
                pass
            messages = gevangen.get('messages') or []
            system = system_tekst(messages)
            assert 'JARVIS-CONTEXT EN GEHEUGEN' in system, 'de AI krijgt het gecombineerde blok'
            assert 'kladblok' in system, 'de AI ziet het gesprek'
            assert 'ZWAARDER' in system, 'de AI ziet dat het gesprek zwaarder weegt'
            assert 'ACTUELE JARVIS-CONTEXT' not in system, 'er is geen los ACTUELE JARVIS-CONTEXT meer'
            assert 'JARVIS-GEHEUGEN (wat ik over' not in system, 'er is geen los JARVIS-GEHEUGEN-blok meer'
            assert 'verwijzen normaal naar het laatste programma' in system, 'de verwijzingsregels voor tools zijn er nog'
            assert messages and messages[-1].get('role') == 'user', 'de vraag blijft de laatste user-message'
            assert system.count('open kladblok') <= 2, 'de geschiedenis wordt niet dubbel toegevoegd'
        import core.brain as brain
        with patch.object(agent, 'ollama', FakeOllama), patch.object(agent, '_live_ha_devices', lambda: ''):
            agent_berichten = {}

            def _capture(model=None, messages=None, format=None, **kwargs):
                agent_berichten['messages'] = messages
                return type('R', (), {'message': FakeBericht()})()
            FakeOllama.chat = staticmethod(_capture)
            ai.current_context.update(CTX)
            try:
                brain.agent._generate_plan('open het programma opnieuw')
            except Exception:
                pass
            messages = agent_berichten.get('messages') or []
            system = system_tekst(messages)
            assert 'JARVIS-CONTEXT EN GEHEUGEN' in system, 'de agent krijgt het gecombineerde blok'
            assert 'ACTUELE JARVIS-CONTEXT' not in system, 'de agent ziet geen los ACTUELE JARVIS-CONTEXT'
            assert 'ZWAARDER' in system, 'de agent ziet dat het gesprek zwaarder weegt'
        print('\n===== 9: BACKWARDS COMPATIBILITY =====\n')
        assert isinstance(ai.get_context(), str), 'get_context() bestaat nog'
        assert 'kladblok' in ai.get_context(), 'get_context() toont het programma nog'
        assert ai.update_context(last_program='kladblok') is None, 'update_context() werkt nog'
        assert isinstance(ai.current_context, dict), 'current_context is nog een dict'
        assert isinstance(ai.conversation_history, list), 'conversation_history is nog een lijst'
        assert all(({'role', 'content'} <= set(m) for m in ai._chat_history())), '_chat_history() geeft nog role/content'
        assert build_memory_context('', context=CTX) == '', 'build_memory_context werkt zonder question (leeg, want geen overlap)'
        assert build_memory_context(None, context={}) == '', 'build_memory_context overleeft een None-vraag'
        assert build_memory_context('mijn kleur', context=CTX) != '', 'build_memory_context heeft default limieten'
        assert 'Coldplay' not in build_memory_context('mijn kleur muziek', context={}, max_memories=0), 'max_memories werkt'
        assert len(rank_context_items('kladblok programma', CTX, max_items=1)) <= 1, 'max_context_items werkt'
        assert len(_recent_history(HISTORY * 5, max_turns=2)) <= 2, 'max_history werkt'
        assert _normalize('Klad-Blok!  ') == 'klad blok', '_normalize maakt tekst vergelijkbaar'
        assert _recent_history([{'role': 'user'}, 'geen dict', {}], max_turns=5) == [], '_recent_history slaat ongeldige regels over'
        assert all((len(c) <= 165 for _, c in _recent_history([{'role': 'user', 'content': 'x' * 500}], max_turns=5))), '_recent_history kapt lange berichten af'
        assert 'Coldplay' in mem.relevant_memory_prompt('mijn favoriete band'), 'het oude losse geheugenpad bestaat nog'
        assert any((i['key'] == 'gpu' for i in mem.get_relevant_memory('mijn gpu'))), 'get_relevant_memory bestaat nog'
        assert mem.recall('favoriete_kleur') == 'blauw', 'memory.json is nog geldig'
        assert mem.get_entry('gpu', category='pc').get('usage_count', 0) > 0, 'usage wordt bijgehouden'
        assert mem.get_entry('gpu', category='pc').get('priority') == 1.0, 'priority blijft ongewijzigd'
        ai.update_context(pending_choice=None)
        ai.conversation_history.clear()
        _conversation_patch.stop()
    for leftover in (path, path + '.bak', path + '.lock', path + '.corrupt'):
        try:
            os.remove(leftover)
        except OSError:
            pass
    shutil.rmtree(work, ignore_errors=True)
    store.reset_cache()
    if _real_conversation_existed and os.path.exists(_real_conversation):
        same = open(_real_conversation, 'rb').read() == _real_conversation_before
        print('  info: conversation.json onveranderd:', same)
