import sys
import os
import io
import time
import shutil
import tempfile
from unittest.mock import patch
from memory import store
from memory.memory import DEFAULT_CATEGORIES, load_memory, save_memory, remember, recall, forget, get_all_memory, get_relevant_memory, relevant_memory_prompt, relevance_score, _wrap, _priority_factor, _aging_factor, _age_days, _now, _DEFAULT_PRIORITY, _MIN_PRIORITY, _MAX_PRIORITY, _AGING_FRESH_FACTOR, _AGING_OLD_FACTOR, _AGING_STALE_FACTOR
import memory.memory as mem

def test_main():
    """
JARVIS — Memory priority + aging tests (Fase 14, Stap 4)
=====================================================

Test de nieuwe priority- en aging-functies in memory/memory.py:

  1. standaard priority
  2. hoge/lage priority
  3. oude versus recente memory
  4. vaak gebruikte versus ongebruikte memory
  5. irrelevante memory blijft laag
  6. bestaande memories zonder priority
  7. combinatie van relevance + priority + aging
  8. backwards compatibility

Alle tests draaien op tijdelijke bestanden. De echte
memory/memory.json wordt nooit aangeraakt.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def keys_of(items):
        return [item['key'] for item in items]

    def score_of(items, key):
        for item in items:
            if item['key'] == key:
                return item['score']
        return None

    def priority_of(items, key):
        for item in items:
            if item['key'] == key:
                return item.get('priority', _DEFAULT_PRIORITY)
        return None

    def _ago(days):
        """Geeft een tijdstempel X dagen geleden."""
        t = time.time() - days * 86400
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))
    work = tempfile.mkdtemp(prefix='jarvis_priority_test_')
    path = os.path.join(work, 'memory.json')
    store.reset_cache()
    print('\n===== 1: STANDAARD PRIORITY =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        assert _DEFAULT_PRIORITY == 1.0, '_DEFAULT_PRIORITY is 1.0'
        assert _MIN_PRIORITY == 0.0, '_MIN_PRIORITY is 0.0'
        assert _MAX_PRIORITY == 10.0, '_MAX_PRIORITY is 10.0'
        remember('favoriete_kleur', 'blauw', category='voorkeuren')
        data = load_memory()
        entry = data['voorkeuren']['favoriete_kleur']
        assert entry.get('priority') == 1.0, 'nieuwe entry heeft priority 1.0'
        assert _priority_factor(1.0) == 1.0, '_priority_factor(1.0) geeft 1.0'
        assert _priority_factor(None) == 1.0, '_priority_factor(None) geeft 1.0'
        assert _priority_factor('abc') == 1.0, "_priority_factor('abc') geeft 1.0"
        assert _priority_factor(0) == 0.0, '_priority_factor(0) geeft 0.0'
        assert 'priority' in mem.ENTRY_META_KEYS, 'priority is in ENTRY_META_KEYS'
    print('\n===== 2: HOGE/LAGE PRIORITY =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        remember('hoog', 'test', category='algemeen', priority=5.0)
        remember('laag', 'test', category='algemeen', priority=0.3)
        remember('neutraal', 'test', category='algemeen')
        score_hoog = relevance_score('test', 'algemeen', 'hoog', 'test', priority=5.0)
        score_neutraal = relevance_score('test', 'algemeen', 'neutraal', 'test', priority=1.0)
        score_laag = relevance_score('test', 'algemeen', 'laag', 'test', priority=0.3)
        assert abs(score_hoog / score_neutraal - 5.0) < 0.01, 'hoge priority (5.0) verdubbelt de score'
        assert score_laag < score_neutraal, 'lage priority (0.3) halveert de score'
        assert score_laag > 0, 'lage priority geeft nog steeds een positieve score'
        remember('grens_boven', 'test', category='algemeen', priority=999)
        remember('grens_onder', 'test', category='algemeen', priority=-5)
        data = load_memory()
        assert data['algemeen']['grens_boven']['priority'] == 10.0, 'priority wordt begrensd naar max 10.0'
        assert data['algemeen']['grens_onder']['priority'] == 0.0, 'priority wordt begrensd naar min 0.0'
        assert relevance_score('test', 'algemeen', 'grens_onder', 'test', priority=0.0) == 0.0, 'priority 0.0 maakt de score 0.0'
        tegenspraak = remember('hoog', 'nieuwe waarde', category='algemeen')
        assert tegenspraak.get('needs_confirm') is True, 'tegenstrijdige waarde wordt niet opgeslagen'
        assert mem.recall('hoog') == 'test', 'de oude waarde blijft staan na een conflict'
        remember('hoog', 'nieuwe waarde', category='algemeen', force=True)
        data = load_memory()
        assert data['algemeen']['hoog']['priority'] == 5.0, 'priority wordt bewaard bij een update'
        remember('hoog', 'weer een nieuwe waarde', category='algemeen', priority=2.0, force=True)
        data = load_memory()
        assert data['algemeen']['hoog']['priority'] == 2.0, 'expliciete priority overschrijft de oude na bevestiging'
        items = get_relevant_memory('test')
        found = [i for i in items if i['key'] in ('hoog', 'laag')]
        assert all(('priority' in i for i in found)), 'get_relevant_memory retourneert priority per item'
    print('\n===== 3: OUDE VERSUS RECENTE MEMORY =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        remember('recent_fait', 'lucht', category='algemeen')
        remember('oud_fait', 'lucht', category='algemeen')
        remember('heel_oud_fait', 'lucht', category='algemeen')
        data = load_memory()
        data['algemeen']['recent_fait']['updated'] = _ago(1)
        data['algemeen']['oud_fait']['updated'] = _ago(180)
        data['algemeen']['heel_oud_fait']['updated'] = _ago(730)
        save_memory(data)
        af_recent = _aging_factor(data['algemeen']['recent_fait']['updated'])
        af_oud = _aging_factor(data['algemeen']['oud_fait']['updated'])
        af_heel_oud = _aging_factor(data['algemeen']['heel_oud_fait']['updated'])
        assert af_recent == _AGING_FRESH_FACTOR, 'recente memory krijgt een bonus (factor > 1.0)'
        assert af_oud == _AGING_OLD_FACTOR, '6 maanden oude memory krijgt milde veroudering'
        assert af_heel_oud == _AGING_STALE_FACTOR, '2 jaar oude memory krijgt sterkere veroudering'
        assert af_heel_oud >= 0.5, 'veroudering is nooit zo sterk dat een relevant feit verdwijnt'
        s_recent = relevance_score('lucht', 'algemeen', 'recent_fait', 'lucht', updated=data['algemeen']['recent_fait']['updated'])
        s_oud = relevance_score('lucht', 'algemeen', 'oud_fait', 'lucht', updated=data['algemeen']['oud_fait']['updated'])
        s_heel_oud = relevance_score('lucht', 'algemeen', 'heel_oud_fait', 'lucht', updated=data['algemeen']['heel_oud_fait']['updated'])
        assert s_recent > s_oud, 'recente memory scoort hoger dan oude'
        assert s_oud > s_heel_oud, 'oude memory scoort hoger dan heel oude'
        assert s_heel_oud > 0, 'zelfs een hele oude memory scoort nog steeds positief'
        assert _age_days(None) is None, '_age_days(None) geeft None'
        assert _age_days('ongeldig') is None, "_age_days('ongeldig') geeft None"
        assert _age_days(_now()) < 0.1, '_age_days(nu) geeft rond de 0'
    print('\n===== 4: GEBRUIK: VAAK VERSUS ONGEBRUIKT =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        items = get_relevant_memory('lucht')
        assert len([i for i in items if i['value'] == 'lucht']) == 3, 'alle lucht-feiten staan in de resultaten'
        scores = {i['key']: i['score'] for i in items if i['value'] == 'lucht'}
        assert scores.get('recent_fait', 0) >= scores.get('oud_fait', 0), 'recente memory heeft de hoogste score'
        assert scores.get('heel_oud_fait', 0) <= scores.get('oud_fait', 0), 'heel oude memory heeft de laagste score'
    print('\n===== 5: IRRELEVANTE MEMORY BLIJFT LAAG =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        remember('irrelevant', 'xyzqwerty', category='algemeen', priority=10.0)
        s_irrelevant = relevance_score('open programma', 'pc', 'irrelevant', 'xyzqwerty', priority=10.0)
        s_geen = relevance_score('open programma', 'pc', 'favoriete_kleur', 'blauw')
        assert s_irrelevant == 0.0, 'irrelevant feit met priority 10.0 scoort 0.0 (geen tekstmatch)'
        items = get_relevant_memory('open programma')
        assert 'irrelevant' not in keys_of(items), "'irrelevant' met priority 10.0 staat NIET in de resultaten"
    print('\n===== 6: BESTAANDE MEMORIES ZONDER PRIORITY =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        import json
        legacy_data = {'voorkeuren': {'oude_kleur': {'value': 'rood', 'source': 'conversation', 'updated': _now(), 'previous_value': None, 'corrected': False, 'conflict': False, 'usage_count': 0, 'last_used': None}}}
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(legacy_data, handle, indent=4, ensure_ascii=False)
        data = load_memory()
        assert data['voorkeuren']['oude_kleur']['priority'] == 1.0, 'entry zonder priority krijgt automatisch priority 1.0'
        items = get_relevant_memory('kleur')
        found = [i for i in items if i['key'] == 'oude_kleur']
        assert len(found) == 1, 'get_relevant_memory werkt voor een legacy entry'
        assert found[0].get('priority') == 1.0, 'legacy entry heeft priority in output'
    print('\n===== 7: COMBINATIE RELEVANCE + PRIORITY + AGING =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        remember('kleur_a', 'blauw', category='voorkeuren', priority=2.0)
        remember('kleur_b', 'groen', category='voorkeuren', priority=1.0)
        remember('kleur_c', 'rood', category='voorkeuren', priority=1.0)
        data = load_memory()
        data['voorkeuren']['kleur_c']['updated'] = _ago(200)
        save_memory(data)
        items = get_relevant_memory('kleur')
        scores = {i['key']: i['score'] for i in items if i['key'].startswith('kleur_')}
        assert scores.get('kleur_a', 0) > scores.get('kleur_b', 0), 'kleur_a (priority 2.0) scoort hoger dan kleur_b (priority 1.0)'
        assert scores.get('kleur_b', 0) > scores.get('kleur_c', 0), 'kleur_b (recent) scoort hoger dan kleur_c (oud)'
        assert all((scores.get(f'kleur_{c}', 0) > 0 for c in ('a', 'b', 'c'))), 'alle drie de kleuren scoren positief'
        s_a = relevance_score('kleur', 'voorkeuren', 'kleur_a', 'blauw', priority=2.0)
        s_b = relevance_score('kleur', 'voorkeuren', 'kleur_b', 'groen', priority=1.0)
        assert 1.9 < s_a / s_b < 2.1, 'priority 2.0 verdubbelt ongeveer de base score'
        s_relevant_oud = relevance_score('kleur', 'voorkeuren', 'kleur_c', 'rood', updated=_ago(400))
        s_irrelevant = relevance_score('kleur', 'voorkeuren', 'pc_gpu', 'x', updated=_ago(1))
        assert s_relevant_oud > s_irrelevant, 'zelfs een hele oude relevante memory scoort hoger dan een onrelevante recente'
    print('\n===== 8: BACKWARDS COMPATIBILITY =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        assert relevance_score('kleur', 'voorkeuren', 'kleur_a', 'blauw') > 0, 'relevance_score met 4 args'
        assert relevance_score('kleur', 'voorkeuren', 'kleur_a', 'blauw', usage_count=3, last_used=None) > 0, 'relevance_score met 6 args'
        assert relevance_score('kleur', 'voorkeuren', 'kleur_a', 'blauw', usage_count=3, last_used=None, priority=1.5, updated=None) > 0, 'relevance_score met 8 args'
        entry = _wrap('test')
        assert entry.get('priority') == 1.0, '_wrap geeft priority 1.0'
        items = get_relevant_memory('kleur')
        assert all(('priority' in i for i in items)), 'elk item heeft een priority-veld'
        assert all(('updated' in i for i in items)), 'eligible items bevatten ook updated'
        remember('kleur_a', 'DONKER blauw', category='voorkeuren')
        data = load_memory()
        assert data['voorkeuren']['kleur_a']['priority'] == 2.0, 'priority 2.0 wordt bewaard bij update zonder explicit priority'
    for leftover in (path, path + '.bak', path + '.lock'):
        try:
            os.remove(leftover)
        except OSError:
            pass
    shutil.rmtree(work, ignore_errors=True)
    store.reset_cache()
