import sys
import os
import io
import json
import shutil
import tempfile
from unittest.mock import patch
from memory import store
from memory.memory import DEFAULT_CATEGORIES, load_memory, save_memory, remember, recall, forget, update_memory, clear_memory, get_entry, find_entry, get_all_memory, has_conflict, resolve_conflict, empty_memory, _find_existing, _now
import memory.memory as mem
import core.brain as brain

def test_main():
    """
JARVIS — Memory conflict tests (Fase 14, Stap 5)
==============================================

Test dat tegenstrijdige informatie veilig wordt afgehandeld:

  1. nieuw feit zonder conflict
  2. duidelijke correctie (expliciet)
  3. tegenstrijdige waarde: oude waarde blijft staan
  4. conflict met bevestiging ("ja")
  5. keuze voor de nieuwe waarde
  6. keuze om de oude waarde te behouden ("nee")
  7. meerdere conflictsituaties
  8. bestaande memory-functionaliteit blijft werken
  9. herschrijven wordt nooit stilzwijgend gedaan

Alle tests draaien op tijdelijke bestanden; de echte
memory/memory.json wordt nooit aangeraakt.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    work = tempfile.mkdtemp(prefix='jarvis_conflict_test_')
    path = os.path.join(work, 'memory.json')
    store.reset_cache()
    print('\n===== 1: NIEUW FEIT ZONDER CONFLICT =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        result = remember('favoriete_kleur', 'blauw', category='voorkeuren')
        assert recall('favoriete_kleur') == 'blauw', 'nieuw feit wordt opgeslagen'
        assert result.get('conflict') is False, 'geen conflict gemeld'
        assert result.get('needs_confirm') is None, 'geen bevestiging nodig'
        assert result.get('changed') is False, 'changed is False bij een nieuw feit'
        assert result.get('previous') is None, 'previous is None bij een nieuw feit'
        result = remember('favoriete_kleur', 'blauw', category='voorkeuren')
        assert result.get('conflict') is False, 'dezelfde waarde geeft geen conflict'
        assert recall('favoriete_kleur') == 'blauw', 'dezelfde waarde blijft staan'
        assert result.get('needs_confirm') is not True, 'needs_confirm bij identieke waarde'
        conflict, old, category = has_conflict('bestaat_niet', 'iets')
        assert conflict is False, 'has_conflict op onbekende sleutel is False'
        assert old is None, 'has_conflict op onbekende sleutel geeft geen waarde'
    print('\n===== 2: DUIDELIJKE CORRECTIE (EXPLICIET) =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        result = update_memory('favoriete_kleur', 'groen', category='voorkeuren')
        assert recall('favoriete_kleur') == 'groen', 'expliciete correctie slaat direct op'
        assert result.get('needs_confirm') is not True, 'expliciete correctie vraagt geen bevestiging'
        assert result.get('corrected') is True, 'expliciete correctie is gemarkeerd als corrected'
        assert result.get('conflict') is False, 'expliciete correctie geeft geen conflict'
        entry = get_entry('favoriete_kleur')
        assert entry.get('corrected') is True, 'entry is corrected'
        assert entry.get('previous_value') == 'blauw', 'entry bewaart de vorige waarde'
        assert entry.get('conflict') is False, 'entry is niet in conflict'
        conflict, old, category = has_conflict('favoriete_kleur', 'rood', 'voorkeuren')
        assert conflict is True, 'has_conflict ziet het verschil'
        assert old == 'groen', 'has_conflict geeft de huidige waarde'
        assert category == 'voorkeuren', 'has_conflict geeft de categorie'
    print('\n===== 3: TEGENSTRIJDIGE WAARDE =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        result = remember('favoriete_kleur', 'rood', category='voorkeuren')
        assert result.get('conflict') is True, 'conflict wordt gemeld'
        assert result.get('needs_confirm') is True, 'bevestiging wordt gevraagd'
        assert recall('favoriete_kleur') == 'groen', 'de oude waarde is NIET overschreven'
        assert result.get('old_value') == 'groen', 'het conflict meldt de oude waarde'
        assert result.get('memory_value') == 'rood', 'het conflict meldt de nieuwe waarde'
        assert result.get('memory_key') == 'favoriete_kleur', 'het conflict meldt de sleutel'
        entry = get_entry('favoriete_kleur')
        assert entry.get('value') == 'groen', 'entry houdt de oude waarde'
        assert entry.get('conflict') is not True, 'entry is niet overschreven'
        result = remember('naam', 'Rushi', category='algemeen')
        assert recall('naam') == 'Rushi', 'tweede nieuw feit zonder conflict slaat op'
        assert result.get('needs_confirm') is not True, 'tweede nieuw feit meldt geen conflict'
        result = remember('naam', 'Rufus')
        assert recall('naam') == 'Rushi', 'tegenstrijdige naam is niet opgeslagen'
        assert result.get('needs_confirm') is True, 'tegenstrijdige naam vraagt bevestiging'
    print('\n===== 4+5: BEVESTIGING -> NIEUWE WAARDE =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        result = resolve_conflict('favoriete_kleur', 'rood', keep_old=False, category='voorkeuren')
        assert result.get('applied') is True, 'resolve meldt dat er iets is opgeslagen'
        assert result.get('kept_old') is False, 'resolve meldt dat de oude waarde niet is behouden'
        assert result.get('value') == 'rood', 'resolve meldt de nieuwe waarde'
        assert result.get('previous') == 'groen', 'resolve meldt de vorige waarde'
        assert result.get('corrected') is True, 'resolve markeert het als gecorrigeerd'
        assert recall('favoriete_kleur') == 'rood', 'de nieuwe waarde is nu actueel'
        entry = get_entry('favoriete_kleur')
        assert entry.get('previous_value') == 'groen', 'previous_value is bijgewerkt'
        assert entry.get('conflict') is False, 'conflict is opgelost'
        assert entry.get('corrected') is True, 'corrected staat aan'
        assert entry.get('conflict_resolved') is not None, 'het afhandelen is vastgelegd'
        result = resolve_conflict('nieuw_fact', 'waarde', category='algemeen')
        assert recall('nieuw_fact') == 'waarde', 'resolve zonder conflict slaat gewoon op'
        assert result.get('applied') is True, 'resolve zonder conflict meldt applied'
    print('\n===== 6: OUDE WAARDE BEHOUDEN =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        result = resolve_conflict('favoriete_kleur', 'paars', keep_old=True, category='voorkeuren')
        assert result.get('applied') is False, 'resolve meldt dat niets is overschreven'
        assert result.get('kept_old') is True, 'resolve meldt dat de oude waarde is behouden'
        assert result.get('value') == 'rood', 'resolve meldt de waarde die geldt'
        assert recall('favoriete_kleur') == 'rood', 'de oude waarde staat er nog steeds'
        entry = get_entry('favoriete_kleur')
        assert entry.get('conflict_rejected_value') == 'paars', 'de afgewezen waarde is vastgelegd'
        assert entry.get('conflict_kept_old') is True, 'het afwijzen is vastgelegd'
        assert entry.get('value') == 'rood', 'de waarde zelf is onveranderd'
        assert entry.get('value') != entry.get('conflict_rejected_value'), 'de afgewezen waarde staat er niet in'
    print('\n===== 7: MEERDERE CONFLICTSITUATIES =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        remember('gpu', 'RTX 3060', category='pc')
        remember('cpu', 'Ryzen 5', category='pc')
        remember('monitor', 'Samsung', category='pc')
        conflicts = []
        for key, new in (('gpu', 'RTX 4090'), ('cpu', 'Ryzen 7'), ('monitor', 'LG')):
            result = remember(key, new, category='pc')
            conflicts.append(result.get('needs_confirm') is True)
        assert all(conflicts), 'alle drie de conflicts worden gemeld'
        assert recall('gpu') == 'RTX 3060', 'gpu is niet overschreven'
        assert recall('cpu') == 'Ryzen 5', 'cpu is niet overschreven'
        assert recall('monitor') == 'Samsung', 'monitor is niet overschreven'
        resolve_conflict('gpu', 'RTX 4090', keep_old=False, category='pc')
        resolve_conflict('cpu', 'Ryzen 7', keep_old=False, category='pc')
        resolve_conflict('monitor', 'LG', keep_old=True, category='pc')
        assert recall('gpu') == 'RTX 4090', 'gpu is bijgewerkt'
        assert recall('cpu') == 'Ryzen 7', 'cpu is bijgewerkt'
        assert recall('monitor') == 'Samsung', 'monitor is onveranderd'
        assert get_entry('gpu', category='pc').get('previous_value') == 'RTX 3060', 'gpu bewaart zijn vorige waarde'
        assert get_entry('cpu', category='pc').get('previous_value') == 'Ryzen 5', 'cpu bewaart zijn vorige waarde'
        assert get_entry('monitor', category='pc').get('previous_value') is None, 'monitor heeft geen previous_value'
        remember('favoriete_band', 'Coldplay', category='muziek')
        remember('favoriete_band', 'Radiohead')
        assert recall('favoriete_band') == 'Coldplay', 'muziek-conflict is apart afgehandeld'
        assert recall('gpu') == 'RTX 4090', 'pc-feiten zijn niet geraakt'
        remember('favoriete_sport', 'voetbal', category='voorkeuren')
        result = remember('favoriete sport', 'handbal', category='voorkeuren')
        assert result.get('needs_confirm') is True, 'flexibele sleutelmatch herkent het conflict'
        assert recall('favoriete_sport') == 'voetbal', 'de waarde is niet overschreven'
    print('\n===== 8: BESTAANDE FUNCTIONALITEIT =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        assert recall('gpu') == 'RTX 4090', 'recall leest een waarde'
        assert recall('bestaat_niet') is None, 'recall vindt niets voor een onbekende sleutel'
        assert get_entry('gpu', category='pc') is not None, 'get_entry geeft de entry terug'
        assert get_entry('bestaat_niet') is None, 'get_entry geeft None voor onbekend'
        assert find_entry('gpu', 'pc')[0] == 'pc', 'find_entry vindt categorie + entry'
        assert find_entry('bestaat_niet') == (None, None), 'find_entry geeft (None, None) voor onbekend'
        assert 'gpu' in get_all_memory(), 'get_all_memory bevat de sleutels'
        assert forget('nieuw_fact') is True, 'forget verwijdert een sleutel'
        assert forget('bestaat_niet') is False, 'forget geeft False voor onbekend'
        assert recall('nieuw_fact') is None, 'vergeet sleutel is echt weg'
        for entry in load_memory()['pc'].values():
            if entry.get('previous_value') is not None:
                assert entry['value'] is not None, 'entry met historie blijft integer'
                break
        with open(path, 'r', encoding='utf-8') as handle:
            raw = json.load(handle)
        assert isinstance(raw, dict), 'memory.json is valide JSON'
        assert set(raw) == set(DEFAULT_CATEGORIES), 'alle categorieën aanwezig'
    print('\n===== 9: NOOIT STILZWIJGEND OVERSCHRIJVEN =====\n')
    with patch.object(mem, 'MEMORY_FILE', path):
        result_plain = remember('gpu', 'stilzwijgend', category='pc')
        assert result_plain.get('needs_confirm') is True, 'plain remember overschrijft niet'
        result_forced = remember('gpu', 'bewust', category='pc', force=True)
        assert recall('gpu') == 'bewust', 'force=True overschrijft wel'
        assert result_forced.get('needs_confirm') is not True, 'force=True meldt geen conflict'
        result_explicit = update_memory('gpu', 'expliciet', category='pc')
        assert recall('gpu') == 'expliciet', 'update_memory overschrijft direct'
        assert result_explicit.get('corrected') is True, 'update_memory is een correctie'
        for result in (result_plain, result_forced, result_explicit):
            assert all((field in result for field in ('changed', 'conflict', 'previous', 'category'))), 'resultaat bevat changed/conflict/previous/category'
        remember('naam', 'Rushi', category='algemeen')
        resolve_conflict('naam', 'Rufus', keep_old=True, category='algemeen')
        assert recall('naam') == 'Rushi', 'geheugen is onveranderd na afwijzen'
        assert len(get_all_memory()) == len(set(get_all_memory())), 'het geheugen telt geen nieuwe sleutels'
    print('\n===== 10: BRAIN-INTEGRATIE =====\n')
    _stubs = ('ask_ai', 'open_website', 'send_to_recycle', 'empty_recycle_bin', 'copy_path', 'move_path', 'list_folder_by_path', 'lock_pc', 'sleep_pc', 'shutdown_pc', 'restart_pc', 'logoff_pc', 'run_goal', 'speak', 'say', 'set_volume', 'play_pause', 'next_track', 'previous_track', 'volume_up', 'volume_down', 'toggle_mute')
    _saved = {name: getattr(brain, name) for name in _stubs if hasattr(brain, name)}
    for name in _saved:
        setattr(brain, name, lambda *a, **k: 'FAKE')
    work2 = os.path.join(work, 'brain.json')
    try:
        with patch.object(mem, 'MEMORY_FILE', work2):
            brain.update_context(pending_choice=None)
            reply = brain.process_command('mijn favoriete kleur is blauw')
            assert 'onthoud' in reply.lower(), 'nieuw feit wordt bevestigd in het antwoord'
            assert recall('favoriete_kleur') == 'blauw', 'nieuw feit staat in het geheugen'
            reply = brain.process_command('mijn favoriete kleur is rood')
            assert 'wijzigen' in reply.lower(), 'tegenstrijdig feit vraagt om bevestiging'
            assert 'rood' in reply, 'tegenstrijdig feit noemt de nieuwe waarde'
            assert 'blauw' in reply, 'tegenstrijdig feit noemt de oude waarde'
            assert recall('favoriete_kleur') == 'blauw', 'de oude waarde is nog niet overschreven'
            pending = brain.current_context.get('pending_choice')
            assert bool(pending), 'er staat een pending keuze klaar'
            assert pending and pending.get('kind') == 'memory_update', 'pending keuze is van het type memory_update'
            assert pending and pending.get('memory_key') == 'favoriete_kleur', 'pending keuze onthoudt de sleutel'
            assert pending and pending.get('old_value') == 'blauw', 'pending keuze onthoudt de oude waarde'
            assert pending and pending.get('memory_value') == 'rood', 'pending keuze onthoudt de nieuwe waarde'
            reply = brain.process_command('ja')
            assert 'aangepast' in reply.lower(), 'bevestiging wordt beantwoord'
            assert recall('favoriete_kleur') == 'rood', 'de nieuwe waarde staat er nu'
            assert get_entry('favoriete_kleur').get('previous_value') == 'blauw', 'de vorige waarde is bewaard'
            assert get_entry('favoriete_kleur').get('conflict') is False, 'het conflict is opgelost'
            assert brain.current_context.get('pending_choice') is None, 'de keuze is gewist'
            reply = brain.process_command('mijn favoriete kleur is groen')
            assert 'wijzigen' in reply.lower(), 'tweede tegenspraak vraagt opnieuw om bevestiging'
            assert recall('favoriete_kleur') == 'rood', 'de waarde is nog niet overschreven'
            reply = brain.process_command('nee')
            assert 'geheugen' in reply.lower(), 'afwijzing wordt beantwoord'
            assert recall('favoriete_kleur') == 'rood', 'de oude waarde blijft staan'
            entry = get_entry('favoriete_kleur')
            assert entry.get('conflict_rejected_value') == 'groen', 'de afgewezen waarde is vastgelegd'
            assert entry.get('conflict_kept_old') is True, 'het afwijzen is vastgelegd'
            assert brain.current_context.get('pending_choice') is None, 'de keuze is gewist na afwijzen'
            reply = brain.process_command('wijzig mijn favoriete kleur naar geel')
            assert recall('favoriete_kleur') == 'geel', 'expliciete correctie wordt direct uitgevoerd'
            assert 'zellig' not in reply.lower() and 'wijzigen' not in reply.lower(), 'expliciete correctie vraagt geen bevestiging'
            assert get_entry('favoriete_kleur').get('previous_value') == 'rood', 'expliciete correctie bewaart de vorige waarde'
            assert get_entry('favoriete_kleur').get('corrected') is True, 'expliciete correctie is gemarkeerd'
            brain.process_command('mijn gpu is een rtx 3060')
            assert recall('gpu') == 'een rtx 3060', 'een ander feit wordt wel gewoon opgeslagen'
            reply = brain.process_command('mijn gpu is een rtx 4090')
            assert 'wijzigen' in reply.lower(), 'pc-feiten doen ook mee met de conflict-logica'
            assert recall('gpu') == 'een rtx 3060', 'de gpu-waarde is niet overschreven'
    except Exception as error:
        assert False, f'brain-integratie liep zonder fout ({error})'
    finally:
        for name, value in _saved.items():
            setattr(brain, name, value)
        brain.update_context(pending_choice=None)
    for leftover in (path, path + '.bak', path + '.lock', path + '.corrupt'):
        try:
            os.remove(leftover)
        except OSError:
            pass
    shutil.rmtree(work, ignore_errors=True)
    store.reset_cache()
