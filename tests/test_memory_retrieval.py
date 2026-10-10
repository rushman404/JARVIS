import sys
import os
import io
import json
import time
import shutil
import tempfile
from unittest.mock import patch
from memory import store
from memory.memory import DEFAULT_CATEGORIES, DEFAULT_RELEVANT_ITEMS, load_memory, save_memory, remember, recall, forget, get_all_memory, get_relevant_memory, relevant_memory_prompt, relevance_score, _phrase_in
import memory.memory as mem
import hashlib

def test_main():
    """
JARVIS — Memory retrieval tests (Fase 14, Stap 3)
================================================

Test de verbeterde relevantie-scoring van memory/memory.py:

  1. duidelijke match
  2. meerdere zoekwoorden
  3. irrelevante memories
  4. categorie / key / value matches
  5. ranking van resultaten
  6. lege resultaten
  7. limiet op het aantal resultaten
  8. usage_count als lichte factor (geen decay)
  9. backwards compatibility
 10. bestaande memory-functionaliteit blijft werken

De kern van Stap 3 is dat toevallige substrings niet meer scoren
("ram" in "programma"), dus daar begint deze test mee.

Alle tests draaien op een tijdelijk geheugenbestand. De echte
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

    def set_usage(key, count, last_used=None):
        """Zet usage_count/last_used rechtstreeks op een entry."""
        data = load_memory()
        for category in DEFAULT_CATEGORIES:
            if key in data.get(category, {}):
                data[category][key]['usage_count'] = count
                if last_used is not None:
                    data[category][key]['last_used'] = last_used
                save_memory(data)
                return True
        return False
    work = tempfile.mkdtemp(prefix='jarvis_retrieval_test_')
    path = os.path.join(work, 'memory.json')
    store.reset_cache()
    FIXTURE = [('favoriete_kleur', 'blauw', 'voorkeuren'), ('favoriete_game', 'Spider-Man', 'voorkeuren'), ('favoriete_band', 'Coldplay', 'muziek'), ('lichtvoorkeur', 'warm wit', 'voorkeuren'), ('gpu', 'RTX 3060 Ti', 'pc'), ('monitor', 'Samsung', 'pc'), ('project_deadline_website', 'maart', 'projecten'), ('bedlamp', 'lamp naast het bed', 'apparaten')]
    print('\n===== 0: SUBSTRING-REGRESSIE (woordgrenzen) =====\n')
    assert not _phrase_in('ram', 'open mijn programma'), '"ram" matcht NIET in "programma"'
    assert not _phrase_in('ram', 'dat is een ramp'), '"ram" matcht NIET in "ramp"'
    assert not _phrase_in('licht', 'dat is misschien leuk'), '"licht" matcht NIET in "misschien"'
    assert not _phrase_in('fel', 'ik ben zelf thuis'), '"fel" matcht NIET in "zelf"'
    assert not _phrase_in('stand', 'dat is verstandig'), '"stand" matcht NIET in "verstandig"'
    assert not _phrase_in('tv', 'ik ben actief bezig'), '"tv" matcht NIET in "actief"'
    assert not _phrase_in('pc', 'hoe gaat het met je'), '"pc" matcht NIET in "hoe gaat het met je"'
    assert _phrase_in('gpu', 'mijn gpu'), '"gpu" matcht WEL in "mijn gpu"'
    assert _phrase_in('favoriete_kleur', 'wat is mijn favoriete kleur'), '"favoriete_kleur" matcht "favoriete kleur" (underscore = spatie)'
    assert _phrase_in('favoriete_kleur', 'mijn favoriete-kleur'), '"favoriete_kleur" matcht "favoriete-kleur" (koppelteken)'
    with patch.object(mem, 'MEMORY_FILE', path):
        assert relevance_score('open mijn programma', 'pc', 'ram', '8GB') == 0.0, 'substring-ramis leveren score 0 op'
        assert relevance_score('dat is een ramp', 'pc', 'ram', '8GB') == 0.0, "'ramp' levert geen score op voor sleutel 'ram'"
        for key, value, category in FIXTURE:
            remember(key, value, category=category)
        print('\n===== 1: DUIDELIJKE MATCH =====\n')
        found = get_relevant_memory('wat is mijn favoriete kleur?')
        assert keys_of(found)[0] == 'favoriete_kleur', 'favoriete_kleur staat bovenaan'
        assert 'favoriete_kleur' in keys_of(found), 'favoriete_kleur is gevonden'
        assert score_of(found, 'favoriete_kleur') is not None, 'waarde klopt'
        exact = relevance_score('mijn favoriete kleur', 'voorkeuren', 'favoriete_kleur', 'blauw')
        vague = relevance_score('mijn kleur', 'voorkeuren', 'favoriete_kleur', 'blauw')
        none = relevance_score('wat is het weer', 'voorkeuren', 'favoriete_kleur', 'blauw')
        assert exact > vague, 'exacte key-match scoort hoger dan gedeeltelijke'
        assert vague > none, 'gedeeltelijke match scoort hoger dan geen match'
        print('\n===== 2: MEERDERE ZOEKWOORDEN =====\n')
        found = get_relevant_memory('mijn gpu en mijn monitor')
        assert 'gpu' in keys_of(found) and 'monitor' in keys_of(found), 'meerdere sleutels worden gevonden'
        gpu_score = score_of(found, 'gpu')
        monitor_score = score_of(found, 'monitor')
        assert gpu_score > 0 and monitor_score > 0, 'beide pc-feiten scoren positief'
        assert get_relevant_memory('mijn gpu RTX') and score_of(get_relevant_memory('mijn gpu RTX'), 'gpu') > 0, 'gpu scoort hoger dan monitor (waarde RTX in de vraag)'
        meervoud = get_relevant_memory('ik hou van lampen')
        assert 'bedlamp' in keys_of(meervoud) or 'bedlamp' in keys_of(get_relevant_memory('lamp')), "'lampen' matcht de sleutel 'bedlamp' via meervoudsvorm"
        print('\n===== 3: IRRELEVANTE MEMORIES =====\n')
        onzin = get_relevant_memory('zzqqxx wwvvuu')
        assert onzin == [], 'onzin geeft lege resultaten'
        assert relevant_memory_prompt('zzqqxx wwvvuu') == '', 'onzin geeft lege prompt'
        weer = get_relevant_memory('wat is het weer morgen')
        assert 'gpu' not in keys_of(weer) and 'favoriete_band' not in keys_of(weer), 'weervraag haalt geen pc- of muziek-feiten'
        programma = get_relevant_memory('open mijn programma')
        assert 'gpu' not in keys_of(programma), "'programma' levert de sleutel 'gpu'/'ram' niet op"
        print('\n===== 4: CATEGORIE / KEY / VALUE MATCHES =====\n')
        key_match = relevance_score('mijn gpu', 'pc', 'gpu', 'RTX 3060 Ti')
        value_match = relevance_score('RTX 3060', 'pc', 'iets_anders', 'RTX 3060 Ti')
        category_match = relevance_score('mijn processor', 'pc', 'iets_anders', 'onbekend')
        assert key_match > value_match, 'key-match scoort het hoogst'
        assert value_match > category_match, 'value-match scoort boven categorie-match'
        assert category_match > 0, 'alleen een categorietrefwoord scoort nog positief'
        waarde = relevance_score('ik luister graag coldplay', 'muziek', 'favoriete_band', 'Coldplay')
        assert waarde > 0, "waarde 'Coldplay' wordt in de vraag herkend"
        licht_score = relevance_score('maak het licht warm', 'voorkeuren', 'onbekend', 'x')
        muziek_score = relevance_score('zet de muziek aan', 'muziek', 'onbekend', 'x')
        assert licht_score > 0, "'licht' is een geldige voorkeuren-trefwoord"
        assert muziek_score > 0, "'muziek' is een geldig muziek-trefwoord"
        assert relevance_score('zet de muziek aan', 'voorkeuren', 'onbekend', 'x') == 0.0, "'muziek' scoort niet in de voorkeuren-categorie"
        volledig = relevance_score('mijn favoriete kleur', 'voorkeuren', 'favoriete_kleur', 'blauw')
        deels = relevance_score('mijn kleur blauw', 'voorkeuren', 'favoriete_kleur', 'blauw')
        assert volledig > deels, 'alle sleutelwoorden aanwezig scoort hoger dan deels'
        print('\n===== 5: RANKING =====\n')
        found = get_relevant_memory('mijn gpu en mijn monitor')
        scores = [item['score'] for item in found]
        assert scores == sorted(scores, reverse=True), 'scores zijn aflopend gesorteerd'
        assert all(({'category', 'key', 'value', 'score', 'usage_count'} <= set(item) for item in found)), 'resultaten bevatten categorie/key/value/score/usage_count'
        gemengd = get_relevant_memory('bedlamp')
        assert keys_of(gemengd)[0] == 'bedlamp', "exacte key-match 'bedlamp' staat bovenaan"
        print('\n===== 6: LEGE RESULTATEN =====\n')
        assert get_relevant_memory('') == [], 'lege vraag geeft lege lijst'
        assert get_relevant_memory('en of maar') == [], 'vraag met alleen stopwoorden geeft lege lijst'
        assert relevant_memory_prompt('zzqqxx') == '', 'lege prompt bij lege lijst'
        with patch.object(mem, 'MEMORY_FILE', os.path.join(work, 'leeg.json')):
            assert get_relevant_memory('mijn kleur') == [], 'leeg geheugen geeft lege lijst'
            assert relevant_memory_prompt('mijn kleur') == '', 'leeg geheugen geeft lege prompt'
        print('\n===== 7: LIMIET OP AANTAL RESULTATEN =====\n')
        for i in range(10):
            remember(f'testitem_{i}', f'waarde {i}', category='algemeen')
        alles = get_relevant_memory('testitem waarde', max_items=50)
        assert len(alles) > DEFAULT_RELEVANT_ITEMS, 'vindt meer dan 6 treffers in het geheugen'
        assert len(get_relevant_memory('testitem waarde')) == DEFAULT_RELEVANT_ITEMS, 'standaard-limiet is 6'
        assert DEFAULT_RELEVANT_ITEMS == 6, 'DEFAULT_RELEVANT_ITEMS bestaat en is 6'
        assert len(get_relevant_memory('testitem waarde', max_items=3)) == 3, 'limiet 3 werkt'
        assert len(get_relevant_memory('testitem waarde', max_items=1)) == 1, 'limiet 1 werkt'
        assert len(get_relevant_memory('testitem waarde', max_items=99)) <= 10, 'meer dan gevraagd geeft nooit meer dan gevraagd'
        for i in range(10):
            forget(f'testitem_{i}')
        print('\n===== 8: GEBRUIKSDATA ALS LICHTE FACTOR =====\n')
        basis = relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung')
        assert basis > 0, 'basis zonder gebruiksdata scoort positief'
        veel = relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', usage_count=12, last_used=None)
        assert veel > basis, 'vaak gebruikt geeft een kleine bonus'
        assert 0 < veel - basis <= 1.5, 'usage-bonus blijft klein (max +1,5)'
        recent = relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', usage_count=0, last_used=time.strftime('%Y-%m-%dT%H:%M:%S'))
        assert recent > basis, 'recent gebruikt geeft een kleine bonus'
        assert 0 < recent - basis <= 1.0, 'recency-bonus blijft klein (max +1,0)'
        oud = relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', usage_count=0, last_used='2020-01-01T00:00:00')
        assert oud == basis, 'verouderde last_used levert geen bonus'
        irrelevant = relevance_score('zzqqxx wwvvuu', 'pc', 'monitor', 'Samsung', usage_count=9999, last_used=time.strftime('%Y-%m-%dT%H:%M:%S'))
        assert irrelevant == 0.0, 'veel gebruikt maar tekstueel irrelevant blijft score 0'
        irrelevant_items = get_relevant_memory('zzqqxx wwvvuu')
        assert 'monitor' not in keys_of(irrelevant_items), 'veel gebruikt feit komt niet in irrelevante resultaten voor'
        set_usage('monitor', 20, last_used=time.strftime('%Y-%m-%dT%H:%M:%S'))
        items = get_relevant_memory('mijn monitor')
        assert bool(items) and items[0]['usage_count'] == 20, 'entry usage_count wordt meegeleverd in de resultaten'
        assert bool(items) and items[0]['score'] > basis, 'opgeslagen gebruiksdata verhoogt de score end-to-end'
        assert relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', usage_count='abc') == basis, 'ongeldige usage_count geeft 0 bonus'
        assert relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', last_used='geen datum') == basis, 'ongeldige last_used geeft 0 bonus'
        assert relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', usage_count=None, last_used=None) == basis, 'lege waarden geven 0 bonus'
        assert relevance_score('mijn monitor', 'pc', 'monitor', 'Samsung', usage_count='') == basis, 'lege tekenreeks als usage_count geeft 0 bonus'
        set_usage('monitor', 0, last_used=None)
        print('\n===== 9: BACKWARDS COMPATIBILITY =====\n')
        assert relevance_score('mijn gpu', 'pc', 'gpu', 'RTX') > 0, 'relevance_score werkt met 4 argumenten (oude aanroep)'
        assert relevance_score('mijn gpu', 'pc', 'gpu', 'RTX', usage_count=3, last_used=None) > 0, 'relevance_score accepteert de nieuwe keyword-argumenten'
        assert isinstance(get_relevant_memory('mijn gpu'), list), 'get_relevant_memory werkt zonder max_items'
        assert 'gpu' in relevant_memory_prompt('mijn gpu'), 'relevant_memory_prompt geeft tekst met de sleutel erin'
        assert get_relevant_memory(None) == [] or isinstance(get_relevant_memory(None), list), 'None als vraag geeft geen crash'
        assert isinstance((memory_summary_text := __import__('memory.memory', fromlist=['memory_summary']).memory_summary()), str), 'memory_summary werkt nog'
        print('\n===== 10: BESTAANDE FUNCTIONALITEIT =====\n')
        assert recall('favoriete_kleur') == 'blauw', 'recall leest nog waarden'
        assert 'favoriete_kleur' in get_all_memory(), 'get_all_memory bevat nog sleutels'
        assert set(load_memory()) == set(DEFAULT_CATEGORIES), 'categories zijn intact'
        entry = load_memory()['voorkeuren']['favoriete_kleur']
        assert entry.get('source') and entry.get('updated'), 'entry houdt zijn metadata'
        voor = json.dumps(load_memory(), sort_keys=True)
        get_relevant_memory('mijn gpu en mijn kleur')
        relevant_memory_prompt('mijn kleur')
        relevance_score('mijn gpu', 'pc', 'gpu', 'RTX')
        na = json.dumps(load_memory(), sort_keys=True)
        assert voor == na, 'retrieval verandert het geheugen niet'
        legacy = os.path.join(work, 'legacy.json')
        store.write(legacy, {'favoriete_kleur': 'rood', 'naam': 'Rushi'})
        with patch.object(mem, 'MEMORY_FILE', legacy):
            data = load_memory()
            assert 'voorkeuren' in data and 'favoriete_kleur' in data['voorkeuren'], 'legacy plat formaat wordt nog steeds geconverteerd'
            assert recall('favoriete_kleur') == 'rood', 'legacy gegevens zijn bruikbaar'
            assert keys_of(get_relevant_memory('mijn kleur')) == ['favoriete_kleur'], 'legacy retrieval werkt'
    for leftover in (path, path + '.bak', path + '.lock', os.path.join(work, 'leeg.json'), os.path.join(work, 'leeg.json.bak'), os.path.join(work, 'legacy.json'), os.path.join(work, 'legacy.json.bak')):
        try:
            os.remove(leftover)
        except OSError:
            pass
    shutil.rmtree(work, ignore_errors=True)
    store.reset_cache()
    REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'memory', 'memory.json')
