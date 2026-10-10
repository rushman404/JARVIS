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
JARVIS — Obsidian in de brain (Fase 14, Stap 4)
=================================================

Test de twee expliciete vault-commando's in core/brain.py:

  1. "wat heb ik in mijn vault staan"
  2. "zet <notitie> in mijn geheugen"

Getest wordt:
  * de routering (een commando zonder vault-woord valt er gewoon af)
  * een ontbrekende vault, een lege vault en een leeg geheugen
  * importeren van een nieuwe memory
  * een ongewijzigde memory (geen schrijfactie)
  * een conflict via de bestaande pending_choice-flow, met 'ja' en 'nee'
  * dat er GEEN automatische synchronisatie is, in beide richtingen
  * dat de bestaande memory_update-bevestiging niet kapot is gegaan

Alle tests draaien op een tijdelijke vault, een tijdelijk geheugenbestand
en een tijdelijk gespreksbestand. De echte vault, memory.json en
conversation.json worden niet aangeraakt.
"""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    work = tempfile.mkdtemp(prefix='jarvis_vault_brain_')
    vault_path = os.path.join(work, 'Vault')
    os.makedirs(vault_path)
    memory_file = os.path.join(work, 'memory.json')
    conversation_file = os.path.join(work, 'conversation.json')
    _echte_conversation = ai.CONVERSATION_FILE
    _echte_memory = mem.MEMORY_FILE
    _conversation_voor = None
    if os.path.exists(_echte_conversation):
        with open(_echte_conversation, 'rb') as file:
            _conversation_voor = file.read()
    _memory_voor = None
    if os.path.exists(_echte_memory):
        with open(_echte_memory, 'rb') as file:
            _memory_voor = file.read()

    def reset(leeg_vault=False):
        """
    Zet alles terug naar een schone teststand.

    Schoon geheugen, leeg (of niet) vault, geen openstaande keuze.
    """
        ai.current_context['pending_choice'] = None
        ai.conversation_history.clear()
        if os.path.exists(memory_file):
            os.remove(memory_file)
        shutil.rmtree(vault_path, ignore_errors=True)
        os.makedirs(vault_path)
        mem.store.reset_cache(memory_file)
        ob.reset_vault_path()
        ob.set_vault_path(vault_path)
        if not leeg_vault:
            ob.write_note('Welkom.md', 'Welkom in je vault.')

    def zet_vault(path):
        """Stel het vault-pad in; None betekent 'bestaat niet'."""
        ob.set_vault_path(path or os.path.join(work, 'bestaat niet'))

    def note(vrijgeven):
        """Schrijft een memory-notitie in de test-vault."""
        ob.write_note(ob.note_name_for_memory(vrijgeven['key'], vrijgeven['category']), ob.memory_to_note({'value': vrijgeven['value'], **vrijgeven.get('extra', {})}, key=vrijgeven['key'], category=vrijgeven['category'])['content'])

    @patch.object(ai, 'CONVERSATION_FILE', conversation_file)
    @patch.object(mem, 'MEMORY_FILE', memory_file)
    def main():
        print('\n--- 1. routering ---')
        reset()
        for commando in ['open discord', 'wat is het weer', 'onthoud dat ik blauw leuk vind', 'zet de radio aan', 'maak een bestand aan', 'vergeet dat']:
            assert brain.try_vault_info(commando) is None and brain.try_vault_import(commando) is None, f"'{commando}' raakt de vault niet"
        assert brain.try_vault_info('wat heb ik in mijn vault staan') is not None, "'wat heb ik in mijn vault staan' wordt wel herkend"
        assert brain.try_vault_import('zet voorkeuren/licht in mijn geheugen') is not None, "'zet voorkeuren/licht in mijn geheugen' wordt herkend"
        assert brain.try_vault_import('importeer obsidian') is not None, "'importeer obsidian notitie' wordt herkend"
        assert brain.try_vault_info('toon mijn vault') is not None, "'toon mijn vault' wordt als vraag herkend"
        assert brain.try_vault_info('obsidian is een programma') is None, 'een willekeurige zin over obsidian is geen commando'
        print('\n--- 2. lege vault en leeg geheugen ---')
        reset(leeg_vault=True)
        assert ob.vault_exists(), 'lege vault: vault bestaat'
        assert ob.list_notes() == [], 'lege vault: geen notities'
        assert vi.plan_import_all() == [], 'lege vault: geen memory-notities'
        assert not any((mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES)), 'lege geheugen: geen memories'
        antwoord = brain.try_vault_info('wat heb ik in mijn vault staan')
        assert isinstance(antwoord, str), 'lege vault geeft een rustig antwoord'
        assert 'leeg' in antwoord.lower(), 'lege vault zegt dat hij leeg is'
        assert 'kan niet' not in antwoord.lower(), 'lege vault geeft geen foutmelding'
        antwoord = brain.try_vault_import('zet voorkeuren/licht in mijn geheugen')
        assert isinstance(antwoord, str) and 'geen notitie vinden' in antwoord.lower(), 'import naar lege vault zegt dat hij niets vindt'
        assert not any((mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES)), 'lege import verandert het geheugen niet'
        ob.write_note('Welkom.md', 'Welkom in je vault.')
        antwoord = brain.try_vault_import('zet welkom in mijn geheugen')
        assert isinstance(antwoord, str) and 'geen notitie' in antwoord.lower(), 'handgeschreven notitie wordt niet geimporteerd'
        assert not any((mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES)), 'geen enkele memory aangemaakt door de lege tests'
        print('\n--- 3. ontbrekende vault ---')
        reset()
        zet_vault(None)
        antwoord = brain.try_vault_info('wat heb ik in mijn vault staan')
        assert isinstance(antwoord, str) and 'niet vinden' in antwoord.lower(), 'info bij ontbrekende vault noemt het pad'
        antwoord = brain.try_vault_import('zet iets in mijn geheugen')
        assert isinstance(antwoord, str) and 'niet vinden' in antwoord.lower(), 'import bij ontbrekende vault legt uit waarom niet'
        assert True, 'ontbrekende vault crasht niet'
        print('\n--- 4. vault zonder memory-notities ---')
        reset()
        ob.write_note('ideeen.md', '# Idee\n\nGeen memory hier.')
        antwoord = brain.try_vault_info('wat heb ik in mijn vault staan')
        assert isinstance(antwoord, str) and 'notitie' in antwoord.lower(), 'handgeschreven notities worden geteld'
        assert 'geen daarvan' in antwoord.lower() or 'geen memory' in antwoord.lower(), 'het meldt dat er geen memories in staan'
        print('\n--- 5. vault-info met memories ---')
        reset()
        note({'key': 'favoriete kleur', 'value': 'blauw', 'category': 'voorkeuren'})
        note({'key': 'favoriete band', 'value': 'Radiohead', 'category': 'muziek'})
        antwoord = brain.try_vault_info('wat heb ik in mijn vault staan')
        assert '2' in antwoord, 'info noemt het aantal memory-notities'
        assert 'favoriete kleur' in antwoord, 'info toont de sleutel'
        assert 'blauw' in antwoord, 'info toont de waarde'
        assert 'nieuw' in antwoord.lower(), 'info meldt dat ze nieuw zijn voor het geheugen'
        assert not any((mem.load_memory().get(c) for c in mem.DEFAULT_CATEGORIES)), 'info verandert het geheugen niet'
        assert len(ob.list_notes()) == 3, 'info verandert de vault niet'
        print('\n--- 6. importeren (nieuw) ---')
        reset()
        note({'key': 'favoriete kleur', 'value': 'blauw', 'category': 'voorkeuren'})
        antwoord = brain.try_vault_import('zet voorkeuren/favoriete-kleur in mijn geheugen')
        assert isinstance(antwoord, str), 'import van een nieuwe memory lukt'
        assert 'favoriete kleur' in antwoord, 'import meldt de sleutel'
        assert 'blauw' in antwoord, 'import meldt de waarde'
        assert mem.load_memory()['voorkeuren'].get('favoriete kleur', {}).get('value') == 'blauw', 'memory staat nu in het geheugen'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['source'] == 'obsidian', 'bron is de vault'
        assert ai.current_context.get('pending_choice') is None, 'import riep geen bevestiging op'
        assert ob.note_exists('voorkeuren/favoriete-kleur.md'), 'import liet de notitie in de vault staan'
        print('\n--- 7. ongewijzgd ---')
        antwoord = brain.try_vault_import('zet voorkeuren/favoriete-kleur in mijn geheugen')
        assert isinstance(antwoord, str) and 'al in je geheugen' in antwoord.lower(), 'tweede import zegt dat het er al staat'
        assert ai.current_context.get('pending_choice') is None, 'tweede import opent geen bevestiging'
        entry = mem.load_memory()['voorkeuren']['favoriete kleur']
        assert entry['value'] == 'blauw', 'tweede import heeft de waarde niet overschreven'
        assert entry['conflict'] is False, 'tweede import heeft geen conflict gemeld'
        print('\n--- 8. conflict en bevestiging ---')
        reset()
        note({'key': 'favoriete kleur', 'value': 'blauw', 'category': 'voorkeuren'})
        vi.import_note('voorkeuren/favoriete-kleur.md')
        note({'key': 'favoriete kleur', 'value': 'groen', 'category': 'voorkeuren'})
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'geheugen staat nog op blauw'
        antwoord = brain.try_vault_import('zet voorkeuren/favoriete-kleur in mijn geheugen')
        assert isinstance(antwoord, str) and 'Zal ik dat wijzigen' in antwoord, 'conflict geeft een bevestigingsvraag'
        assert 'blauw' in antwoord, 'de vraag noemt de oude waarde'
        assert 'groen' in antwoord, 'de vraag noemt de vault-waarde'
        assert 'ja' in antwoord.lower() and 'nee' in antwoord.lower(), 'de vraag vraagt om ja of nee'
        pending = ai.current_context.get('pending_choice')
        assert isinstance(pending, dict), 'er staat een pending_choice klaar'
        assert pending['kind'] == 'memory_update', 'pending_choice gebruikt de bestaande memory_update-vorm'
        assert 'favoriete-kleur' in pending['from_vault'], 'pending_choice onthoudt de notitie'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'GEHEUGEN IS NOG NIET OVERSCHREVEN'
        antwoord = brain.handle_pending_choice('nee')
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'nee handhaaft het geheugen'
        assert 'vault' in antwoord.lower(), 'nee noemt de vault'
        assert ai.current_context.get('pending_choice') is None, 'nee wist de pending_choice'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['conflict_rejected_value'] == 'groen', 'nee legt de afgewezen waarde vast'
        note({'key': 'favoriete kleur', 'value': 'zwart', 'category': 'voorkeuren'})
        brain.try_vault_import('zet voorkeuren/favoriete-kleur in mijn geheugen')
        pending = ai.current_context.get('pending_choice')
        assert isinstance(pending, dict), 'tweede conflict vraagt opnieuw'
        antwoord = brain.handle_pending_choice('ja')
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'zwart', 'ja past de vault-waarde toe'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['previous_value'] == 'blauw', 'ja bewaart de vorige waarde'
        assert 'vault' in antwoord.lower(), 'ja noemt de vault'
        assert ai.current_context.get('pending_choice') is None, 'ja wist de pending_choice'
        print('\n--- 9. via process_command ---')
        reset()
        note({'key': 'favoriete kleur', 'value': 'blauw', 'category': 'voorkeuren'})
        vi.import_note('voorkeuren/favoriete-kleur.md')
        note({'key': 'favoriete kleur', 'value': 'rood', 'category': 'voorkeuren'})
        antwoord = brain.process_command('zet voorkeuren/favoriete-kleur in mijn geheugen')
        assert isinstance(antwoord, str) and 'wijzigen' in antwoord, 'process_command vraagt om bevestiging'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'process_command wijzigt niets zonder bevestiging'
        antwoord = brain.process_command('ja')
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'rood', 'process_command + ja past toe'
        print('\n--- 10. geen automatische sync ---')
        reset()
        _notities = ob.list_notes()
        mem.remember('iets nieuws', 'testwaarde', category='algemeen')
        assert ob.list_notes() == _notities, 'onthouden raakt de vault niet aan'
        _geheugen_voor = mem.load_memory()
        ob.write_note('voorkeuren/nieuw', '---\nmemory_key: nieuw\n---\n\n> test')
        _geheugen_na = mem.load_memory()
        assert _geheugen_na == _geheugen_voor, 'een notitie in de vault komt niet vanzelf in het geheugen'
        assert not any((k in dir(brain) for k in ('_vault_watcher', '_vault_loop'))), 'brain.py start geen achtergrondproces'
        assert 'vault_sync.synchroniseer' not in dir(vi), 'er is geen timer voor de vault in brain.py'
        print('\n--- 11. bestaande conflict-flow werkt nog ---')
        reset()
        mem.remember('fav kleur', 'blauw', category='voorkeuren', force=True)
        ai.current_context['pending_choice'] = {'kind': 'memory_update', 'memory_key': 'fav kleur', 'memory_value': 'groen', 'memory_category': 'voorkeuren', 'old_value': 'blauw'}
        antwoord = brain.handle_pending_choice('ja')
        assert mem.load_memory()['voorkeuren']['fav kleur']['value'] == 'groen', 'gewone memory_update werkt nog'
        assert 'vault' not in antwoord.lower(), 'gewone memory_update noemt de vault niet'
        print('\n--- 12. echte bestanden ---')
        if _memory_voor is not None:
            with open(_echte_memory, 'rb') as file:
                assert file.read() == _memory_voor, 'echte memory.json is onveranderd'
        if _conversation_voor is not None:
            with open(_echte_conversation, 'rb') as file:
                assert file.read() == _conversation_voor, 'echte conversation.json is onveranderd'
        assert ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, 'JARVIS Memory'), 'echte vault staat nog op de standaard'
    main()
    ai.CONVERSATION_FILE = _echte_conversation
    ob.reset_vault_path()
    mem.store.reset_cache()
    shutil.rmtree(work, ignore_errors=True)
