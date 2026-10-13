import sys
import os
import io
import json
import glob
import shutil
import tempfile
from unittest.mock import patch
from memory import store
from memory.memory import DEFAULT_CATEGORIES, empty_memory, load_memory, save_memory, remember, recall, forget, update_memory, clear_memory, get_entry, find_entry, get_all_memory, get_category_memory, memory_summary, get_relevant_memory, relevant_memory_prompt, touch_usage, reset_touch_usage, resolve_conflict, _touched_keys
import memory.memory as mem

def test_main():
    """
JARVIS — Memory Store tests (Fase 14, Stap 1)
=============================================

Test de nieuwe opslaglaag memory/store.py:

  1. normaal laden
  2. normaal opslaan
  3. cache werkt
  4. cache wordt correct vernieuwd na een write
  5. twee verschillende MEMORY_FILE-paden lekken geen data naar elkaar
  6. atomic write
  7. corrupt JSON-bestand
  8. herstel via backup
  9. backup ontbreekt -> veilige fallback
 10. bestaande memory-functionaliteit blijft werken

Elke test draait volledig op tijdelijke bestanden. De echte
memory/memory.json wordt nooit gelezen of overschreven.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def stats_snapshot():
        return dict(store.STATS)

    def make_dir():
        return tempfile.mkdtemp(prefix='jarvis_store_test_')
    print('\n===== 1+2: NORMAAL LADEN / OPSLAAN =====\n')
    work = make_dir()
    path_a = os.path.join(work, 'memory.json')
    store.reset_cache()
    sample = {'voorkeuren': {'favoriete_kleur': {'value': 'blauw'}}, 'pc': {}, 'projecten': {}, 'muziek': {}, 'algemeen': {}, 'apparaten': {}}
    assert store.write(path_a, sample) is True, 'write() geeft True terug'
    assert os.path.exists(path_a), 'bestand bestaat na schrijven'
    loaded = store.read(path_a)
    assert loaded == sample, 'read() geeft exact terug wat er geschreven is'
    unicode_data = {'algemeen': {'naam': 'Rushi — förtòn 中文'}}
    store.write(path_a, unicode_data)
    with open(path_a, 'r', encoding='utf-8') as handle:
        raw = handle.read()
    assert 'förtòn' in raw, 'niet-ASCII blijft leesbaar (ensure_ascii=False)'
    assert '\n    "algemeen"' in raw, 'indent=4 blijft gehandhaafd'
    assert store.read(path_a) == unicode_data, 'read() geeft unicode correct terug'
    print('\n===== 3: CACHE WERKT =====\n')
    store.reset_cache()
    cache_path = os.path.join(work, 'cache.json')
    store.write(cache_path, {'algemeen': {'a': 1}})
    before = stats_snapshot()
    for _ in range(5):
        store.read(cache_path)
    after = stats_snapshot()
    new_reads = after['reads'] - before['reads']
    new_hits = after['cache_hits'] - before['cache_hits']
    assert new_reads == 5, '5 reads tellen echt op'
    assert new_hits == 5, 'een eigen write vult de cache, dus alle 5 reads zijn cache-hits'
    store.reset_cache()
    before = stats_snapshot()
    store.read(cache_path)
    after = stats_snapshot()
    assert after['reads'] - before['reads'] == 1 and after['cache_hits'] - before['cache_hits'] == 0, 'lege cache: eerste read is een echte schijfread'
    before = stats_snapshot()
    store.read(cache_path)
    store.read(cache_path)
    after = stats_snapshot()
    assert after['cache_hits'] - before['cache_hits'] == 2, 'tweede en derde read komen uit de cache'
    external = {'algemeen': {'a': 2}}
    with open(cache_path, 'w', encoding='utf-8') as handle:
        json.dump(external, handle, indent=4, ensure_ascii=False)
    assert store.read(cache_path) == external, 'externe wijziging wordt opgepikt (cache gevalideerd op mtime/size)'
    copy_result = store.read(cache_path)
    copy_result['algemeen']['a'] = 999
    assert store.read(cache_path) == external, 'gemuteerd resultaat lekt niet terug in de cache'
    assert store.read(cache_path) is not store.read(cache_path), 'read() geeft elke keer een eigen kopie terug'
    print('\n===== 4: CACHE VERNIEUWD NA WRITE =====\n')
    store.reset_cache()
    refresh_path = os.path.join(work, 'refresh.json')
    store.write(refresh_path, {'algemeen': {'kleur': 'rood'}})
    assert store.read(refresh_path)['algemeen']['kleur'] == 'rood', 'direct na write is de nieuwe waarde zichtbaar'
    store.write(refresh_path, {'algemeen': {'kleur': 'groen'}})
    assert store.read(refresh_path)['algemeen']['kleur'] == 'groen', 'tweede write overschrijft de cache'
    store.write(refresh_path, {'algemeen': {'kleur': 'blauw'}})
    assert store.read(refresh_path)['algemeen']['kleur'] == 'blauw', 'derde write blijft consistent'
    with open(refresh_path, 'r', encoding='utf-8') as handle:
        on_disk = json.load(handle)
    assert on_disk['algemeen']['kleur'] == 'blauw', 'cache en schijf zijn identiek na writes'
    with open(refresh_path, 'w', encoding='utf-8') as handle:
        json.dump({'algemeen': {'kleur': 'geel'}}, handle, indent=4)
    assert store.read(refresh_path)['algemeen']['kleur'] == 'geel', 'externe overschrijving wint van de cache'
    print('\n===== 5: GEEN LEAK TUSSEN TWEE BESTANDSPADEN =====\n')
    store.reset_cache()
    leak_a = os.path.join(work, 'pad_a.json')
    leak_b = os.path.join(work, 'pad_b.json')
    store.write(leak_a, {'algemeen': {'naam': 'A'}})
    store.write(leak_b, {'algemeen': {'naam': 'B'}})
    assert store.read(leak_a)['algemeen']['naam'] == 'A', 'pad A levert zijn eigen data'
    assert store.read(leak_b)['algemeen']['naam'] == 'B', 'pad B levert zijn eigen data'
    assert store.read(leak_a)['algemeen']['naam'] == 'A', 'pad A is na het lezen van B nog steeds A'
    reuse = os.path.join(work, 'hergebruikt.json')
    store.write(reuse, {'algemeen': {'naam': 'eerste'}})
    store.read(reuse)
    os.remove(reuse)
    store.write(reuse, {'algemeen': {'naam': 'tweede'}})
    assert store.read(reuse)['algemeen']['naam'] == 'tweede', 'herschreven pad levert nieuwe data, geen cache-ouwe'
    with patch.object(mem, 'MEMORY_FILE', leak_a):
        remember('kleur', 'paars')
    with patch.object(mem, 'MEMORY_FILE', leak_b):
        remember('kleur', 'oranje')
    with patch.object(mem, 'MEMORY_FILE', leak_a):
        a_value = recall('kleur')
    with patch.object(mem, 'MEMORY_FILE', leak_b):
        b_value = recall('kleur')
    assert a_value == 'paars', 'memory-API: pad A heeft paars'
    assert b_value == 'oranje', 'memory-API: pad B heeft oranje'
    print('\n===== 6: ATOMIC WRITE =====\n')
    store.reset_cache()
    atomic_path = os.path.join(work, 'atomic.json')
    real_replace = os.replace
    with patch('memory.store.os.replace', wraps=real_replace) as replace_spy:
        store.write(atomic_path, {'algemeen': {'k': 'v'}})
    assert replace_spy.call_count >= 1, 'os.replace wordt gebruikt voor het omwisselen'
    leftovers = glob.glob(os.path.join(work, '*.tmp'))
    assert leftovers == [], 'geen .tmp-bestanden achtergelaten'
    bak_path = store.backup_path(atomic_path)
    assert os.path.exists(bak_path), 'backup is aangemaakt'
    assert store.read(bak_path) is not None and json.load(open(bak_path, encoding='utf-8')) == {'algemeen': {'k': 'v'}}, 'backup heeft dezelfde inhoud'
    big = {'algemeen': {f'sleutel_{i}': 'waarde' * 20 for i in range(500)}}
    store.write(atomic_path, big)
    assert store.read(atomic_path) == big, 'grote inhoud schrijft en lees volledig terug'
    deep_path = os.path.join(work, 'nieuw', 'diep', 'memory.json')
    assert store.write(deep_path, {'algemeen': {'diep': True}}) is True, 'write() maakt mappen aan zoals nodig'
    assert store.read(deep_path) is not None, 'diep genest bestand leesbaar'
    print('\n===== 7: CORRUPT JSON-BESTAND =====\n')
    store.reset_cache()
    corrupt_path_file = os.path.join(work, 'corrupt.json')
    with open(corrupt_path_file, 'w', encoding='utf-8') as handle:
        handle.write('{"voorkeuren": {"kleur": "blauw"')
    result = store.read(corrupt_path_file)
    assert result is None, 'read() geeft None bij corrupt zonder backup'
    assert os.path.exists(store.corrupt_path(corrupt_path_file)), 'corrupt bestand is bewaard als .corrupt'
    assert os.path.exists(corrupt_path_file), 'het originele corrupte bestand is niet verwijderd'
    with patch.object(mem, 'MEMORY_FILE', corrupt_path_file):
        safe = load_memory()
    assert safe == empty_memory(), 'load_memory() geeft lege memory bij corrupt'
    assert set(safe) == set(DEFAULT_CATEGORIES), 'lege memory heeft alle categorieën'
    print('\n===== 8: HERSTEL VIA BACKUP =====\n')
    store.reset_cache()
    recover_dir = make_dir()
    recover_path = os.path.join(recover_dir, 'memory.json')
    good = {'voorkeuren': {'favoriete_kleur': {'value': 'blauw'}}}
    store.write(recover_path, good)
    assert os.path.exists(store.backup_path(recover_path)), 'backup staat er na een goede write'
    with open(recover_path, 'w', encoding='utf-8') as handle:
        handle.write('{ dit is geen geldige json ]]')
    recovered = store.read(recover_path)
    assert recovered == good, 'read() herstelt de inhoud via de backup'
    assert store.STATS['recovered'] >= 1, 'herstel is geregistreerd in STATS'
    with patch.object(mem, 'MEMORY_FILE', recover_path):
        restored = load_memory()
        assert restored['voorkeuren']['favoriete_kleur']['value'] == 'blauw', 'load_memory() herstelt via backup'
        assert recall('favoriete_kleur') == 'blauw', 'recall werkt op het herstelde geheugen'
    missing = os.path.join(recover_dir, 'bestaat-niet.json')
    assert store.read(missing) is None, 'read() op ontbrekend bestand geeft None'
    store.reset_cache()
    fallback_dir = make_dir()
    fallback_path = os.path.join(fallback_dir, 'memory.json')
    with open(fallback_path, 'w', encoding='utf-8') as handle:
        handle.write('{{{ kapotte json')
    assert not os.path.exists(store.backup_path(fallback_path)), 'geen backup aanwezig'
    assert store.read(fallback_path) is None, 'read() geeft None als er geen backup is'
    assert store.STATS['fallbacks'] >= 1, 'veilige fallback is geregistreerd'
    broken_bak = os.path.join(fallback_dir, 'broken.json')
    with open(broken_bak, 'w', encoding='utf-8') as handle:
        handle.write('niets dan kapot')
    with open(store.backup_path(broken_bak), 'w', encoding='utf-8') as handle:
        handle.write('OOK KAPOT')
    assert store.read(broken_bak) is None, 'read() geeft None als de backup ook kapot is'
    with patch.object(mem, 'MEMORY_FILE', fallback_path):
        assert load_memory() == empty_memory(), 'load_memory() geeft lege memory zonder backup'
        assert remember('naam', 'tester') is not None, 'remember werkt ook na een veilige fallback'
        assert recall('naam') == 'tester', 'opnieuw opgeslagen waarde is terug te lezen'
    print('\n===== 10: BESTAANDE MEMORY-FUNCTIONALITEIT =====\n')
    store.reset_cache()
    work2 = make_dir()
    live = os.path.join(work2, 'memory.json')
    with patch.object(mem, 'MEMORY_FILE', live):
        assert load_memory() == empty_memory(), 'lege memory op een schoon pad'
        result = remember('favoriete_kleur', 'blauw')
        assert isinstance(result, dict) and result.get('changed') is False, 'remember() geeft de metadata-dict terug'
        assert recall('favoriete_kleur') == 'blauw', 'recall() geeft de waarde terug'
        category, entry = find_entry('favoriete_kleur')
        assert category == 'voorkeuren' and entry is not None, 'find_entry() vindt categorie + entry'
        assert get_entry('favoriete_kleur') is not None and get_entry('favoriete_kleur').get('value') == 'blauw', 'get_entry() geeft de entry met metadata'
        assert entry.get('source') == 'conversation' and entry.get('updated'), 'entry heeft source + updated'
        assert recall('kleur') is None, 'recall() matcht NIET meer gedeeltelijk'
        assert recall('favoriete kleur') == 'blauw', 'recall() matcht wel genormaliseerd'
        remember('lichtvoorkeur', 'warm wit', category='voorkeuren')
        relevant = get_relevant_memory('hoe moet het licht in de kamer?')
        assert any((item.get('key') == 'lichtvoorkeur' for item in relevant)), 'get_relevant_memory() vindt de lichtvoorkeur'
        assert 'lichtvoorkeur' in relevant_memory_prompt('hoe moet het licht zijn?'), 'relevant_memory_prompt() levert tekst'
        update_memory('favoriete_kleur', 'groen', category='voorkeuren')
        assert recall('favoriete_kleur') == 'groen', 'update_memory() wijzigt de waarde'
        updated_entry = get_entry('favoriete_kleur')
        assert updated_entry.get('corrected') is True, 'update_memory() markeert corrected=True'
        assert updated_entry.get('previous_value') == 'blauw', 'update_memory() bewaart de vorige waarde'
        assert updated_entry.get('conflict') is False, 'entry is niet meer in conflict'
        conflict = remember('favoriete_kleur', 'rood')
        assert conflict.get('conflict') is True, 'remember() meldt een conflict'
        assert conflict.get('needs_confirm') is True, 'remember() vraagt om bevestiging'
        assert recall('favoriete_kleur') == 'groen', 'de oude waarde blijft staan na een conflict'
        assert conflict.get('old_value') == 'groen', 'het conflict meldt de oude waarde'
        resolve_conflict('favoriete_kleur', 'rood', category='voorkeuren')
        assert recall('favoriete_kleur') == 'rood', 'na bevestiging staat de nieuwe waarde er'
        assert get_entry('favoriete_kleur').get('previous_value') == 'groen', 'na bevestiging is de vorige waarde bewaard'
        assert get_entry('favoriete_kleur').get('conflict') is False, 'na bevestiging is het conflict opgelost'
        all_mem = get_all_memory()
        assert 'favoriete_kleur' in all_mem and all_mem['favoriete_kleur'] == 'rood', 'get_all_memory() bevat sleutels zonder entry-wrapper'
        assert 'lichtvoorkeur' in get_category_memory('voorkeuren'), 'get_category_memory() werkt per categorie'
        assert 'favoriete kleur' in memory_summary(), 'memory_summary() vat het geheugen samen'
        assert forget('favoriete_kleur') is True, 'forget() verwijdert de sleutel'
        assert recall('favoriete_kleur') is None, 'vergeten sleutel is weg'
        assert forget('bestaat_niet') is False, 'forget() op onbekende sleutel geeft False'
        clear_result = clear_memory()
        assert clear_result is True, 'clear_memory() geeft True'
        assert get_all_memory() == {}, 'na clear is het geheugen leeg'
    print('\n===== 11: USAGE TRACKING =====\n')
    work3 = make_dir()
    live3 = os.path.join(work3, 'memory.json')
    with patch.object(mem, 'MEMORY_FILE', live3):
        reset_touch_usage()
        remember('favoriete_game', 'Spider-Man', category='voorkeuren')
        remember('gpu', 'RTX 3060 Ti', category='pc')
        assert touch_usage('bestaat_niet') is False, 'touch_usage op onbekende sleutel geeft False'
        result = touch_usage('favoriete_game')
        assert result is True, 'touch_usage geeft True bij succes'
        entry = get_entry('favoriete_game')
        assert entry.get('usage_count') == 1, 'usage_count is 1 na eerste gebruik'
        assert entry.get('last_used') is not None, 'last_used is gezet'
        first_used = entry['last_used']
        touch_usage('favoriete_game')
        touch_usage('favoriete_game')
        entry = get_entry('favoriete_game')
        assert entry.get('usage_count') == 1, 'usage_count blijft 1 door dedup in hetzelfde commando'
        reset_touch_usage()
        import time
        time.sleep(0.05)
        touch_usage('favoriete_game')
        entry = get_entry('favoriete_game')
        assert entry.get('last_used') is not None, 'last_used is bijgewerkt na nieuwe commando-aanroep'
        assert entry.get('usage_count') == 2, 'usage_count is 2 na twee aparte commandos'
        reset_touch_usage()
        touch_usage('gpu')
        assert get_entry('gpu').get('usage_count') == 1, 'eerste touch van gpu telt'
        touch_usage('gpu')
        assert get_entry('gpu').get('usage_count') == 1, 'tweede touch van gpu in hetzelfde commando telt NIET'
        touch_usage('gpu')
        assert get_entry('gpu').get('usage_count') == 1, 'derde touch van gpu in hetzelfde commando telt NIET'
        reset_touch_usage()
        touch_usage('gpu')
        assert get_entry('gpu').get('usage_count') == 2, 'na reset telt gpu weer'
        reset_touch_usage()
        touch_usage('favoriete_game')
        touch_usage('gpu')
        touch_usage('favoriete_game')
        assert get_entry('favoriete_game').get('usage_count') == 2 + 1, 'favoriete_game telt 1x in dit commando'
        assert get_entry('gpu').get('usage_count') == 2 + 1, 'gpu telt 1x in dit commando'
        reset_touch_usage()
        touch_usage('game')
        assert get_entry('favoriete_game').get('usage_count') == 3, "touch_usage('game') raakt 'favoriete_game' NIET meer"
        assert touch_usage('favoriete_game') and get_entry('favoriete_game').get('usage_count') == 3 + 1, 'touch_usage telt wel de exacte sleutel'
        reset_touch_usage()
        touch_usage('favoriete game')
        assert get_entry('favoriete_game').get('usage_count') == 3 + 2, 'touch_usage matcht genormaliseerd (spatie = underscore)'
        reset_touch_usage()
        touch_usage('gpu', category='pc')
        assert get_entry('gpu', category='pc').get('usage_count') == 3 + 1, 'category-parameter werkt'
        assert recall('favoriete_game') == 'Spider-Man', 'recall() werkt nog na usage-tracking'
        assert 'favoriete_game' in get_all_memory(), 'get_all_memory() toont nog steeds waarden'
        reset_touch_usage()
        assert len(_touched_keys) == 0, '_touched_keys is leeg na reset'
        touch_usage('gpu')
        assert 'gpu' in _touched_keys, "_touched_keys bevat 'gpu' na touch"
        reset_touch_usage()
        assert len(_touched_keys) == 0, '_touched_keys is weer leeg na tweede reset'
    for folder in (work, recover_dir, fallback_dir, work2, work3):
        shutil.rmtree(folder, ignore_errors=True)
    store.reset_cache()
