import sys
import os
import io
import json
import hashlib
import tempfile
from unittest.mock import patch
from memory.memory import remember, recall, forget, get_category_memory, get_relevant_memory

def test_main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print('🧠 Geheugen test gestart.')
    _tmp = tempfile.mktemp(suffix='_memory.json')
    with open(_tmp, 'w', encoding='utf-8') as f:
        f.write(open('memory/memory.json', encoding='utf-8').read())
    _REAL_MEMORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'memory', 'memory.json')

    def _real_memory_fingerprint():
        try:
            with open(_REAL_MEMORY, 'rb') as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None
    _real_before = _real_memory_fingerprint()
    with patch('memory.memory.MEMORY_FILE', _tmp):
        remember('test', 'Hallo vanuit het geheugen.')
        print('📥 Opgeslagen.')
        value = recall('test')
        print('📤 Teruggelezen:', value)
        assert value == 'Hallo vanuit het geheugen.', 'recall leest waarde terug'
        forget('test')
        print('🗑️ Testgeheugen verwijderd.')
        assert recall('test') is None, 'forget haalt de waarde weg'
    _rtmp = tempfile.mktemp(suffix='_routines.json')
    with open(_rtmp, 'w', encoding='utf-8') as f:
        _routines_copy = json.load(open('config/routines.json', encoding='utf-8'))
        for _entry in _routines_copy.values():
            _entry.pop('usage_count', None)
            _entry.pop('last_used', None)
        f.write(json.dumps(_routines_copy, ensure_ascii=False, indent=4))
    print('\n===== FASE 5: METADATA-MODEL (A) =====')
    with patch('memory.memory.MEMORY_FILE', _tmp):
        from memory.memory import find_entry
        result = remember('favoriete_kleur', 'blauw', category='voorkeuren')
        cat, entry = find_entry('favoriete_kleur')
        assert isinstance(result, dict) and result.get('changed') is False, 'remember retourneert metadata-dict'
        assert cat == 'voorkeuren' and entry is not None and (entry.get('value') == 'blauw') and entry.get('updated'), 'entry bevat value + updated'
        assert entry.get('source') == 'conversation' and 'conflict' in entry, 'entry bevat source + conflict-veld'
        back = recall('favoriete_kleur')
        assert back == 'blauw', 'recall blijft een simpele string geven (back-compat)'
        print('\n----- relevante memory (B) -----')
        remember('lichtvoorkeur', 'warm wit', category='voorkeuren')
        rel = get_relevant_memory('kun je de kamer gezellig maken met warm licht?')
        assert any((kv.get('key') == 'lichtvoorkeur' for kv in rel)), 'relevante memory bevat lichtvoorkeur'
        score = get_relevant_memory('welke kleur vind ik het mooist?')
        assert any((kv.get('key') == 'favoriete_kleur' for kv in score)), "favoriete_kleur scoort op 'kleur'-vraag"
        prompt = None
        try:
            from memory.memory import relevant_memory_prompt
            prompt = relevant_memory_prompt('hoe moet de verlichting aan?')
        except Exception:
            prompt = None
        assert prompt is not None and 'lichtvoorkeur' in str(prompt), 'relevante memory-prompt is beschikbaar en bevat het voorsel'
        forget('favoriete_kleur')
        forget('lichtvoorkeur')
    print('\n===== FASE 5: VOORKEUR HERKEND (C/H/I) =====')
    with patch('memory.memory.MEMORY_FILE', _tmp):
        import core.brain as brain
        print('\n--- herkenning ---')
        out = brain.auto_remember('ik hou meestal van warm wit licht')
        assert out is not None and 'warm' in str(out).lower(), "'ik hou meestal van warm wit licht' -> herkend"
        out = brain.auto_remember('ik vind zacht licht fijn')
        assert out is not None and 'zacht' in str(out).lower(), "'ik vind zacht licht fijn' -> herkend"
        out = brain.auto_remember('mijn voorkeur voor licht is helder')
        assert out is not None and 'helder' in str(out).lower(), "'mijn voorkeur voor licht is helder' -> herkend"
        assert (recall('lichtvoorkeur') or '').lower() in ('warm wit', 'zacht', 'helder'), 'lichtvoorkeur staat in geheugen'
        print('\n--- wijzigen (expliciet) ---')
        out = brain.try_memory_update('wijzig mijn lichtvoorkeur naar koel wit')
        assert out is not None and 'koel' in str(out).lower(), "'wijzig mijn lichtvoorkeur naar koel wit' -> update"
        assert recall('lichtvoorkeur') == 'koel wit', "lichtvoorkeur is nu 'koel wit'"
        print('\n--- conflictbevestiging (I) ---')
        brain.current_context['pending_choice'] = {'kind': 'memory_update', 'action': 'update', 'memory_key': 'lichtvoorkeur', 'memory_value': 'warm wit', 'current_value': 'koel wit'}
        out = brain.process_command('ja')
        assert recall('lichtvoorkeur') == 'warm wit', "'ja' op conflict -> lichtvoorkeur gewijzigd naar warm wit"
        brain.current_context['pending_choice'] = None
        forget('lichtvoorkeur')
    print('\n===== FASE 5: APPARATEN ONTHOUDEN (D) =====')
    with patch('memory.memory.MEMORY_FILE', _tmp):
        import core.brain as brain
        out = brain.try_remember_device('de voordeur heet deurbel')
        assert out is not None and 'deurbel' in str(out), "'de voordeur heet deurbel' -> onthouden"
        items = get_category_memory('apparaten')
        assert 'deurbel' in items and 'voordeur' in str(items.get('deurbel')), "apparaatnaam staat in categorie 'apparaten'"
        out = brain.try_remember_device('bedlamp is mijn lamp in de slaapkamer')
        assert out is not None, "'bedlamp is mijn ...' -> onthouden"
        listed = brain.try_list_devices('welke apparaten ken je')
        assert listed is not None and 'deurbel' in listed and ('bedlamp' in listed), "'welke apparaten ken je' -> lijst van namen"
        assert brain.try_remember_device('ik heet rushil') is None, "persoonlijke zin ('ik heet X') wordt niet als apparaat gelezen"
        linked = True
        try:
            from core.ha_registry import add_user_alias
            with patch('core.ha_registry._config_ok', return_value=False):
                linked = add_user_alias('light.nepapparaat', ['nepnaam'])
        except Exception:
            linked = False
        assert linked is False, 'add_user_alias zonder HA-config -> geen bestandswijziging'
        forget('deurbel')
        forget('bedlamp')
    print('\n===== FASE 5: ROUTINES GEBRUIK (E) =====')
    with patch('core.routines.ROUTINES_FILE', _rtmp):
        from core.routines import RoutineManager
        manager = RoutineManager()
        manager.save_routine('gareden', ['ik ga tuinieren'], ['eerste stap'], 'tuinmodus', ['tuindag'])
        manager.save_routine('lezen', ['ik ga lezen'], ['eerste stap'], 'leesmodus', ['leesmoment'])
        manager.track_usage('gareden')
        manager.track_usage('gareden')
        manager.track_usage('lezen')
        ranking = manager.most_used_routines()
        assert ranking and ranking[0][2] == 'gareden' and (ranking[0][0] == 2), 'meest gebruikte routine staat bovenaan'
        stored = manager._routines.get('gareden')
        assert stored is not None and stored.get('usage_count') == 2 and stored.get('last_used'), 'usage_count + last_used opgeslagen'
        loaded = RoutineManager()
        assert 'gaming' in loaded._routines and 'gareden' in loaded._routines, 'herladen houdt de defaults intact'
    print('\n===== FASE 5: PROJECTEN (F) =====')
    with patch('memory.memory.MEMORY_FILE', _tmp):
        import core.brain as brain
        out = brain.auto_remember('de deadline van schoolproject is vrijdag')
        assert out is not None and 'vrijdag' in str(out), 'deadline herkend'
        q = brain.try_project_query('wat is de deadline van schoolproject')
        assert q is not None and 'vrijdag' in q, 'deadline opvragen werkt'
        out = brain.auto_remember('schoolproject is bijna klaar')
        assert out is not None and 'klaar' in str(out), 'status herkend'
        q = brain.try_project_query('hoe gaat het met schoolproject')
        assert q is not None and 'klaar' in q, 'status opvragen werkt'
        forget('project_deadline_schoolproject')
        forget('project_status_schoolproject')
    print('\n===== FASE 5: CONTEXT / TIMESTAMPS (G) =====')
    with patch('core.ai.conversation_history', []), patch('core.ai._save_conversation', lambda: None):
        import core.ai as ai
        ai.add_to_history('user', 'testbericht')
        item = ai.conversation_history[0]
        assert item.get('ts'), 'historisch bericht heeft tijdstempel'
        cleaned = ai._chat_history()
        assert cleaned and 'role' in cleaned[0] and ('ts' not in cleaned[0]), '_chat_history stuurt alleen role+content (geen ts mee)'
        assert ai.MAX_HISTORY == 15, 'MAX_HISTORY is verruimd naar 15'
    print('\n===== ECHTE GEBRUIKERSMEMORY ONGENAakt (H) =====\n')
    assert _real_memory_fingerprint() == _real_before, 'memory/memory.json is byte-voor-byte onveranderd'
    for _leftover in (_tmp, _tmp + '.bak', _tmp + '.corrupt', _tmp + '.lock', _rtmp):
        try:
            os.remove(_leftover)
        except OSError:
            pass
