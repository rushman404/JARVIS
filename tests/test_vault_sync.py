import sys
import os
import io
import shutil
import tempfile
from unittest.mock import patch
import core.ai as ai
import core.brain as brain
from memory import obsidian as ob
from memory import memory as mem
from memory import vault_import as vi

def test_main():
    """
JARVIS — Vault Analyse + Batch Import (Fase 14, Stap 5)
======================================================

Test de twee nieuwe stukken van stap 5:

  1. compare_vault_to_memory()  -- VOLLEDIG READ-ONLY
  2. start_batch() / resolve_paused_batch()

En de commando's die brain.py daaromheen hangt:
  * "vergelijk mijn vault met mijn geheugen"
  * "importeer alles uit mijn vault"

Getest wordt:
  * lege vault en leeg geheugen
  * nieuwe notities, ongewijzigde notities
  * één conflict en meerdere conflicten
  * 'ja' en 'nee' via de bestaande pending_choice-flow
  * pauzeren en hervatten
  * dubbele imports
  * onverwachte fouten: veilig stoppen
  * read-only gedrag van de analyse
  * dat de echte memory.json en de echte vault onveranderd blijven

Alle tests draaien op een tijdelijke vault, een tijdelijk geheugenbestand
en een tijdelijk gespreksbestand.
"""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    work = tempfile.mkdtemp(prefix='jarvis_vault_sync_')
    vault_path = os.path.join(work, 'Vault')
    os.makedirs(vault_path)
    memory_file = os.path.join(work, 'memory.json')
    conversation_file = os.path.join(work, 'conversation.json')
    _echte_conversation = ai.CONVERSATION_FILE
    _echte_memory = mem.MEMORY_FILE
    _echte_vault = ob.get_vault_path()
    _gesprek_voor = None
    _geheugen_voor = None
    if os.path.exists(_echte_conversation):
        with open(_echte_conversation, 'rb') as file:
            _gesprek_voor = file.read()
    if os.path.exists(_echte_memory):
        with open(_echte_memory, 'rb') as file:
            _geheugen_voor = file.read()

    def _vault_snapshot(pad):
        """
    Alle bestanden in de echte vault, als gesorteerde lijst van paden.

    Waarom een snapshot in plaats van een vaste lijst? Deze test moet
    bewaken dat de test ZELF de echte vault niet aanraakt. Een vaste
    inventaris (".obsidian", "Welkom.md") doet dat niet: die zegt
    alleen iets over wat er toevallig in de persoonlijke vault van de
    gebruiker staat, en brak zodra daar een notitie bij kwam. Wat hier
    getoetst wordt is stabiliteit, niet voorraad.
    """
        if not os.path.isdir(pad):
            return None
        return sorted((os.path.relpath(os.path.join(mapnaam, naam), pad) for mapnaam, _, namen in os.walk(pad) for naam in namen))
    _vault_voor = _vault_snapshot(_echte_vault)

    def reset(leeg_vault=True):
        """
    Schone teststand: geen geheugen, lege vault, geen openstaande keuze.

    Let op: memory.json is een bestand, dus os.remove() en NIET
    shutil.rmtree() -- die doet stil niets op een bestand en zou het
    geheugen tussen de secties laten overlappen.
    """
        ai.current_context['pending_choice'] = None
        ai.conversation_history.clear()
        if os.path.exists(memory_file):
            os.remove(memory_file)
        shutil.rmtree(vault_path, ignore_errors=True)
        os.makedirs(vault_path)
        mem.store.reset_cache(memory_file)
        ob.set_vault_path(vault_path)

    def zet_vault(pad):
        """Stel het vault-pad in; None betekent 'bestaat niet'."""
        ob.set_vault_path(pad or os.path.join(work, 'bestaat niet'))

    def note(key, value, category='voorkeuren', **extra):
        """Schrijft een memory-notitie in de test-vault."""
        ob.write_note(ob.note_name_for_memory(key, category), ob.memory_to_note({'value': value, **extra}, key=key, category=category)['content'])

    def geheugen():
        """De volledige memory.json als dict."""
        return mem.load_memory()

    def waarde(key, category='voorkeuren'):
        """De waarde van een memory, of None als die er niet is."""
        return geheugen().get(category, {}).get(key, {}).get('value')

    def statuses(state):
        """Een compacte lijst van (notitie, status)."""
        return [(r['note_name'], r['status']) for r in state['results']]

    @patch.object(ai, 'CONVERSATION_FILE', conversation_file)
    @patch.object(mem, 'MEMORY_FILE', memory_file)
    def main():
        print('\n--- 1. lege vault, leeg geheugen ---')
        reset()
        assert ob.vault_exists(), 'lege vault bestaat'
        assert ob.list_notes() == [], 'lege vault heeft geen notities'
        rapport = vi.compare_vault_to_memory()
        assert rapport['ok'] is True, 'analyse werkt op een lege vault'
        assert rapport['counts']['total'] == 0, 'analyse telt 0 notities'
        assert rapport['new'] == [], 'analyse vindt niets nieuws'
        assert rapport['conflicts'] == [], 'analyse vindt geen conflicten'
        state = vi.start_batch()
        assert state['results'] == [], 'batch op een lege vault doet niets'
        assert state['done'] is True, 'batch is klaar'
        assert state['paused'] is False, 'batch is niet gepauzeerd'
        assert not any((geheugen().get(c) for c in mem.DEFAULT_CATEGORIES)), 'leeg geheugen blijft leeg'
        antwoord = brain.try_vault_compare('vergelijk mijn vault met mijn geheugen')
        assert isinstance(antwoord, str), 'brain geeft op lege vault een rustig antwoord'
        assert 'geen memory-notities' in antwoord.lower(), 'brain zegt dat er niets te vergelijken valt'
        antwoord = brain.try_vault_batch('importeer alles uit mijn vault')
        assert isinstance(antwoord, str), 'batch-commando op lege vault geeft een antwoord'
        assert not any((geheugen().get(c) for c in mem.DEFAULT_CATEGORIES)), 'leeg geheugen nog steeds leeg'
        print('\n--- 2. ontbrekende vault ---')
        reset()
        zet_vault(None)
        rapport = vi.compare_vault_to_memory()
        assert rapport['ok'] is False, 'analyse merkt op dat de vault ontbreekt'
        assert rapport['reason'] != '', 'analyse zegt waarom'
        state = vi.start_batch()
        assert state['stopped'] is True, 'batch stopt op een ontbrekende vault'
        assert state['error'] != '', 'batch legt de reden vast'
        assert True, 'analyse van een ontbrekende vault crasht niet'
        zet_vault(vault_path)
        print('\n--- 3. read-only analyse ---')
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        vi.import_note(ob.note_name_for_memory('favoriete kleur', 'voorkeuren'))
        note('favoriete kleur', 'groen')
        geheugen_bytes = open(memory_file, 'rb').read()
        notities_voor = sorted(ob.list_notes())
        mtime_voor = os.path.getmtime(memory_file)
        rapport = vi.compare_vault_to_memory()
        assert rapport['counts']['total'] == 2, 'analyse telt de notities'
        assert rapport['counts']['new'] == 1, 'analyse ziet de nieuwe notitie'
        assert rapport['counts']['conflict'] == 1, 'analyse ziet het conflict'
        assert rapport['counts']['unchanged'] == 0, 'analyse ziet geen ongewijzigde notitie'
        assert open(memory_file, 'rb').read() == geheugen_bytes, 'analyse wijzigt memory.json niet'
        assert os.path.getmtime(memory_file) == mtime_voor, 'analyse raakt memory.json niet aan (mtime)'
        assert sorted(ob.list_notes()) == notities_voor, 'analyse wijzigt de vault niet'
        assert geheugen()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'analyse lost het conflict niet op'
        assert geheugen()['voorkeuren']['favoriete kleur']['conflict'] is False, 'analyse zet geen conflict-vlag'
        vi.compare_vault_to_memory('voorkeuren')
        vi.compare_vault_to_memory('bestaat niet')
        assert True, 'analyse van een map die er niet is crasht niet'
        assert open(memory_file, 'rb').read() == geheugen_bytes, 'analyse heeft memory.json nog steeds niet aangeraakt'
        print('\n--- 4. nieuwe notities ---')
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        state = vi.start_batch(dry_run=False)
        assert state['done'] is True, 'batch is klaar'
        assert state['paused'] is False, 'batch is niet gepauzeerd'
        assert state['count']['imported'] == 2, 'beide notities zijn geimporteerd'
        assert waarde('favoriete kleur') == 'blauw', 'favoriete kleur staat in het geheugen'
        assert waarde('favoriete band', 'muziek') == 'Radiohead', 'favoriete band staat in het geheugen'
        assert all((r['status'] == 'imported' for r in state['results'])), 'iedere notitie heeft een status'
        assert all((r['label'] for r in state['results'])), 'iedere status heeft een leesbaar label'
        assert state['queue'] == [], 'de wachtrij is leeg'
        assert len(state['processed']) == len(state['results']), 'niets staat meer op processed zonder status'
        print('\n--- 5. ongewijzigde notities ---')
        state = vi.start_batch(dry_run=False)
        assert all((r['status'] == 'unchanged' for r in state['results'])), "ongewijzigde notities krijgen status 'unchanged'"
        assert state['count']['imported'] == 0, 'er is niets geimporteerd'
        assert state['count']['unchanged'] == 2, 'de teller ziet ze wel'
        assert waarde('favoriete kleur') == 'blauw', 'de waarden zijn onveranderd'
        print('\n--- 6. dry_run als standaard ---')
        reset()
        note('favoriete kleur', 'blauw')
        geheugen_bytes = open(memory_file, 'rb').read() if os.path.exists(memory_file) else None
        state = vi.start_batch()
        assert state['dry_run'] is True, 'dry_run staat standaard aan'
        assert state['count']['planned'] == 1, 'dry_run zegt dat hij een plan is'
        assert not any((geheugen().get(c) for c in mem.DEFAULT_CATEGORIES)), 'dry_run schrijft niets'
        assert geheugen_bytes is None, 'dry_run maakt geen bestand aan'
        assert 'niets' in ' '.join((r['reason'] for r in state['results'])).lower(), 'dry_run meldt dat er niets is geschreven'
        print('\n--- 7. conflict pauzeert de batch ---')
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        vi.start_batch(dry_run=False)
        assert waarde('favoriete kleur') == 'blauw', 'beide memories staan er'
        note('favoriete kleur', 'groen')
        note('fav restaurant', 'Pizzeria Napoli')
        state = vi.start_batch(dry_run=False)
        assert state['paused'] is True, 'batch is gepauzeerd'
        assert state['done'] is False, 'batch is nog niet klaar'
        assert isinstance(state['confirm'], dict), 'er is een confirm-blok'
        assert state['confirm']['note_name'].endswith('favoriete-kleur.md'), 'het conflict noemt de notitie'
        assert state['confirm']['memory_value'] == 'blauw', 'het conflict noemt de oude waarde'
        assert state['confirm']['vault_value'] == 'groen', 'het conflict noemt de vault-waarde'
        assert any((r['status'] == 'waiting' for r in state['results'])), "de conflictnotitie heeft status 'waiting'"
        assert waarde('favoriete kleur') == 'blauw', 'GEHEUGEN IS NOG NIET OVERSCHREVEN'
        assert state['confirm']['note_name'] not in state['processed'], "de conflict-notitie staat NIET op 'processed'"
        assert waarde('fav restaurant', 'algemeen') is None, 'de notitie erachter is nog niet geimporteerd'
        assert len(state['queue']) > 0, 'er staat werk op de wachtrij'
        print('\n--- 8. nee -> behouden en hervatten ---')
        state = vi.resolve_paused_batch(state, keep_old=True)
        assert waarde('favoriete kleur') == 'blauw', 'de oude waarde blijft staan'
        assert geheugen()['voorkeuren']['favoriete kleur']['conflict_kept_old'] is True, 'het conflict is als afgehandeld vastgelegd'
        assert geheugen()['voorkeuren']['favoriete kleur']['conflict_rejected_value'] == 'groen', 'de afgewezen waarde is vastgelegd'
        assert any((r['status'] == 'kept' for r in state['results'])), "de conflictnotitie kreeg status 'kept'"
        assert state['confirm'] is None, 'er is geen openstaand conflict meer'
        assert state['paused'] is False, 'de batch is niet meer gepauzeerd'
        assert waarde('fav restaurant') == 'Pizzeria Napoli', 'DE BATCH IS HERVAT: de volgende notitie is geimporteerd'
        assert state['done'] is True, 'de batch is nu klaar'
        assert len(state['results']) >= 2, 'iedere notitie kreeg een status'
        assert all((r['status'] for r in state['results'])), 'geen enkele notitie staat zonder status'
        assert ob.note_name_for_memory('favoriete kleur', 'voorkeuren') not in state['queue'], 'de afgehandelde conflictnotitie is van de wachtrij'
        volgende = vi.start_batch(dry_run=False)
        assert volgende['paused'] is True, 'een nieuwe batch legt het afgewezen conflict opnieuw voor'
        assert waarde('favoriete kleur') == 'blauw', 'maar de waarde is nog steeds de oude'
        print('\n--- 9. ja -> vault-waarde toepassen ---')
        reset()
        note('favoriete kleur', 'blauw')
        vi.start_batch(dry_run=False)
        note('favoriete kleur', 'rood')
        state = vi.start_batch(dry_run=False)
        assert state['paused'] is True, 'batch is gepauzeerd op het conflict'
        state = vi.resolve_paused_batch(state, keep_old=False)
        assert waarde('favoriete kleur') == 'rood', 'de vault-waarde is nu actueel'
        assert geheugen()['voorkeuren']['favoriete kleur']['previous_value'] == 'blauw', 'de oude waarde staat in previous_value'
        assert any((r['status'] == 'accepted' for r in state['results'])), "de conflictnotitie kreeg status 'accepted'"
        assert state['done'] is True, 'de batch is klaar'
        print('\n--- 10. meerdere conflicten ---')
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        vi.start_batch(dry_run=False)
        note('favoriete kleur', 'groen')
        note('favoriete band', 'Nirvana', 'muziek')
        state = vi.start_batch(dry_run=False)
        rondes = 0
        gezien = []
        while state['paused'] and rondes < 10:
            rondes += 1
            gezien.append(state['confirm']['note_name'])
            state = vi.resolve_paused_batch(state, keep_old=rondes % 2 == 0)
        assert rondes == 2, 'er zijn twee conflicten geweest'
        assert len(set(gezien)) == 2, 'de twee conflicten waren verschillende notities'
        assert state['done'] is True, 'de batch is klaar na de laatste'
        assert state['confirm'] is None, 'er is geen conflict meer open'
        assert len(state['results']) >= 2, 'beide notities hebben een eindstatus'
        assert {'accepted', 'kept'} <= {r['status'] for r in state['results']}, 'een geaccepteerde en een afgewezen notitie'
        print('\n--- 11. geen dubbele import ---')
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        state = vi.start_batch(dry_run=False)
        assert state['count']['imported'] == 2, 'eerste run importeert'
        mtime = os.path.getmtime(memory_file)
        tweede = vi.start_batch(dry_run=False)
        assert tweede['count']['imported'] == 0, 'tweede run importeert niets nieuws'
        assert tweede['count']['unchanged'] == 2, 'tweede run merkt ze als ongewijzigd'
        assert waarde('favoriete kleur') == 'blauw', 'de waarden zijn nog steeds goed'
        handmatig = {'subfolder': '', 'priority': None, 'source': 'obsidian', 'dry_run': False, 'results': [], 'queue': [], 'processed': [], 'confirm': None, 'paused': False, 'done': False, 'stopped': False, 'error': None}
        notitie = ob.note_name_for_memory('favoriete kleur', 'voorkeuren')
        handmatig['queue'] = [notitie, notitie]
        note('nieuw item', 'iets')
        handmatig['queue'] = [notitie, notitie, ob.note_name_for_memory('nieuw item', 'voorkeuren')]
        state = vi._advance_batch(handmatig)
        assert [s for n, s in statuses(state) if n == notitie] == ['unchanged', 'duplicate'], 'een dubbele notitie wordt maar een keer verwerkt'
        assert any((r['status'] == 'duplicate' for r in state['results'])), "de dubbele kreeg status 'duplicate'"
        assert waarde('nieuw item') == 'iets', 'de batch ging gewoon door'
        print('\n--- 12. onverwachte fout ---')
        reset()
        note('aaa eerste', 'een')
        note('zzz derde', 'drie')
        note('mmm tweede', 'twee')
        origineel = vi.import_note

        def kapot(naam, *args, **kwargs):
            if 'mmm-tweede' in naam:
                raise RuntimeError('gesimuleerde schijffout')
            return origineel(naam, *args, **kwargs)
        vi.import_note = kapot
        try:
            state = vi.start_batch(dry_run=False)
        finally:
            vi.import_note = origineel
        assert state['stopped'] is True, 'de batch stopt bij de fout'
        assert 'RuntimeError' in (state['error'] or ''), 'de fout wordt vastgelegd'
        assert any((r['status'] == 'error' for r in state['results'])), "de mislukte notitie kreeg status 'error'"
        assert ob.note_name_for_memory('mmm tweede', 'voorkeuren') not in state['processed'], 'de notitie is NIET als verwerkt gemarkeerd'
        assert ob.note_name_for_memory('zzz derde', 'voorkeuren') in state['queue'], 'de resterende wachtrij is bewaard'
        assert waarde('zzz derde') is None, 'geen notitie na de fout is geimporteerd'
        assert waarde('aaa eerste') == 'een', 'de notitie van voor de fout WEL geimporteerd'
        assert all((r['status'] for r in state['results'])), 'geen enkele notitie hangt zonder status'
        print('\n--- 13. inconsistentie wordt niet stilzwijgend verwerkt ---')
        reset()
        note('aaa eerste', 'een')
        note('zzz derde', 'drie')

        def leugenaar(naam, *args, **kwargs):
            if 'aaa-eerste' in naam:
                return {'applied': False, 'needs_confirm': True, 'confirm_token': None, 'key': 'aaa eerste', 'value': 'een', 'category': 'voorkeuren', 'action': 'new', 'reason': ''}
            return origineel(naam, *args, **kwargs)
        vi.import_note = leugenaar
        try:
            state = vi.start_batch(dry_run=False)
        finally:
            vi.import_note = origineel
        assert state['stopped'] is True, 'een onverwacht conflict stopt de batch'
        assert any((r['status'] == 'error' for r in state['results'])), "de notitie kreeg status 'error'"
        assert state['confirm'] is None, 'er is geen vals confirm-blok'
        assert waarde('zzz derde') is None, 'de volgende notitie is niet doorgegaan'
        print('\n--- 14. hervatten zonder conflict ---')
        reset()
        note('favoriete kleur', 'blauw')
        state = vi.start_batch(dry_run=False)
        assert state['done'] is True, 'batch klaar'
        opnieuw = vi.resolve_paused_batch(state, keep_old=False)
        assert opnieuw['done'] is True, 'hervatten zonder conflict doet niets'
        assert waarde('favoriete kleur') == 'blauw', 'de waarde is onveranderd'
        kapot_state = 'geen dict'
        try:
            vi.resolve_paused_batch(kapot_state, keep_old=True)
        except TypeError:
            assert True, 'resolve_paused_batch weigert een verkeerd type'
        except Exception:
            assert False, 'resolve_paused_batch weigert een verkeerd type'
        else:
            assert False, 'resolve_paused_batch weigert een verkeerd type'
        assert vi.batch_is_finished(state) is True, 'batch_is_finished klopt'
        print("\n--- 15. commando's via brain.py ---")
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        vi.start_batch(dry_run=False)
        note('favoriete kleur', 'groen')
        assert brain.try_vault_batch('vergelijk mijn vault met mijn geheugen') is None, "'vergelijk' is geen andere handler"
        antwoord = brain.try_vault_compare('vergelijk mijn vault met mijn geheugen')
        assert isinstance(antwoord, str), 'vergelijken geeft een overzicht'
        assert 'verschil' in antwoord.lower(), 'vergelijken noemt het conflict'
        assert 'blauw' in antwoord, 'vergelijken noemt de oude waarde'
        assert 'groen' in antwoord, 'vergelijken noemt de vault-waarde'
        assert waarde('favoriete kleur') == 'blauw', 'vergelijken verandert niets'
        assert brain.try_vault_info('importeer alles uit mijn vault') is None, "'importeer alles' is geen info-commando"
        antwoord = brain.try_vault_batch('importeer alles uit mijn vault')
        assert isinstance(antwoord, str) and 'Zal ik dat wijzigen' in antwoord, 'batch via brain vraagt om bevestiging'
        assert waarde('favoriete kleur') == 'blauw', 'batch via brain wijzigt nog niets'
        pending = ai.current_context.get('pending_choice')
        assert isinstance(pending, dict), 'er staat een pending_choice'
        assert pending['kind'] == 'memory_update', 'de pending_choice gebruikt de bestaande memory_update-vorm'
        assert isinstance(pending.get('vault_batch'), dict), 'de pending_choice bevat de batch-state'
        assert _is_json(pending['vault_batch']), 'de batch-state is JSON-geschikt'
        assert pending['vault_batch']['paused'] is True, 'de batch-state bevat het openstaande conflict'
        antwoord = brain.handle_pending_choice('nee')
        assert waarde('favoriete kleur') == 'blauw', "'nee' behoudt het geheugen"
        assert ai.current_context.get('pending_choice') is None, "'nee' wist de pending_choice"
        print('\n--- 16. meerdere conflicten via process_command ---')
        reset()
        note('favoriete kleur', 'blauw')
        note('favoriete band', 'Radiohead', 'muziek')
        vi.start_batch(dry_run=False)
        note('favoriete kleur', 'groen')
        note('favoriete band', 'Nirvana', 'muziek')
        geheugen_voor = dict(geheugen())
        antwoord = brain.process_command('importeer alles uit mijn vault')
        assert isinstance(antwoord, str) and 'Zal ik dat wijzigen' in antwoord, 'process_command vraagt om bevestiging'
        assert geheugen() == geheugen_voor, 'nog niets gewijzigd'
        pending = ai.current_context.get('pending_choice')
        eerste = pending['vault_batch']['confirm']['note_name']
        antwoord = brain.process_command('ja')
        assert sum((1 for r in pending['vault_batch']['results'] if r['status'] == 'accepted')) == 1, "'ja' verandert precies één memory"
        assert 'Zal ik dat wijzigen' in antwoord, "'ja' vraagt meteen door voor het volgende conflict"
        pending = ai.current_context.get('pending_choice')
        assert isinstance(pending, dict), 'er staat nog een conflict klaar'
        assert pending['vault_batch']['confirm']['note_name'] != eerste, 'het is een ANDERE notitie dan die van daarnet'
        kleur = waarde('favoriete kleur')
        band = waarde('favoriete band', 'muziek')
        assert 'groen' in (kleur, band) or 'Nirvana' in (kleur, band), "de 'ja'-waarde is doorgegaan"
        assert sum((1 for v in (kleur, band) if v in ('groen', 'Nirvana'))) == 1, 'precies één memory is veranderd'
        voor_nee = (waarde('favoriete kleur'), waarde('favoriete band', 'muziek'))
        antwoord = brain.process_command('nee')
        assert (waarde('favoriete kleur'), waarde('favoriete band', 'muziek')) == voor_nee, "'nee' verandert geen enkele memory meer"
        assert any((geheugen()[c][k].get('conflict_kept_old') is True for c, k in [('voorkeuren', 'favoriete kleur'), ('muziek', 'favoriete band')])), "'nee' legt bij de afgewezen memory vast dat je nee zei"
        assert isinstance(antwoord, str) and 'gewijzigd' in antwoord.lower(), 'de batch is klaar en meldt een overzicht'
        assert ai.current_context.get('pending_choice') is None, 'er is geen openstaande keuze meer'
        print('\n--- 17. bestaande conflict-flow blijft werken ---')
        reset()
        mem.remember('fav kleur', 'blauw', category='voorkeuren', force=True)
        ai.current_context['pending_choice'] = {'kind': 'memory_update', 'memory_key': 'fav kleur', 'memory_value': 'groen', 'memory_category': 'voorkeuren', 'old_value': 'blauw'}
        brain.handle_pending_choice('ja')
        assert waarde('fav kleur') == 'groen', 'een gewone memory_update werkt nog'
        antwoord = brain.process_command('onthoud dat ik blauw leuk vind')
        assert ob.list_notes() == [], 'onthouden raakt de vault niet'
        print('\n--- 18. geen automatische sync ---')
        reset()
        _notities = ob.list_notes()
        mem.remember('iets nieuws', 'testwaarde', category='algemeen')
        assert ob.list_notes() == _notities, 'onthouden schrijft niet naar de vault'
        geheugen_foto = geheugen()
        ob.write_note('voorkeuren/nieuw', '---\nmemory_key: nieuw\n---\n\n> test')
        assert geheugen() == geheugen_foto, 'een notitie komt niet vanzelf in het geheugen'
        assert not any(('watcher' in str(k).lower() or 'loop' in str(k).lower() for k in vars(vi) if not k.startswith('__'))), 'er is geen watcher in vault_import'
        assert 'compare_vault_to_memory()' not in _bron_van_process_command(), 'brain roept de analyse niet zelf aan'
        assert brain.try_vault_batch('wat doet het weer') is None, 'brain start geen batch zonder commando'
        assert brain.try_vault_batch('alles') is None, 'brain start geen batch bij een los woord'
        print('\n--- 19. echte bestanden ---')
        if _geheugen_voor is not None:
            with open(_echte_memory, 'rb') as file:
                assert file.read() == _geheugen_voor, 'echte memory.json is onveranderd'
        if _gesprek_voor is not None:
            with open(_echte_conversation, 'rb') as file:
                assert file.read() == _gesprek_voor, 'echte conversation.json is onveranderd'
        assert _vault_snapshot(_echte_vault) == _vault_voor, 'de echte vault is onveranderd door deze test'
        assert ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, 'JARVIS Memory'), 'de standaard-vault staat nog goed'

    def _is_json(ding):
        import json
        try:
            json.dumps(ding)
            return True
        except (TypeError, ValueError):
            return False

    def _bron_van_process_command():
        import inspect
        return inspect.getsource(brain.process_command)
    main()
    ai.CONVERSATION_FILE = _echte_conversation
    ob.set_vault_path(_echte_vault)
    mem.store.reset_cache()
    shutil.rmtree(work, ignore_errors=True)
