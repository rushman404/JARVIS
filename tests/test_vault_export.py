import sys
import os
import io
import json
import shutil
import tempfile
from unittest.mock import patch
import core.ai as ai
import core.brain as brain
from memory import obsidian as ob
from memory import memory as mem
from memory import vault_export as vx
from memory import vault_import as vi

def test_main():
    """
JARVIS — Memory 2.0 naar Obsidian (Fase 14, Stap 6)
===================================================

Test de exportrichting: memory.json -> Obsidian.

Getest wordt:
  1. lege vault
  2. leeg geheugen
  3. beide leeg
  4. memory zonder notitie -> create
  5. exacte match -> unchanged
  6. drift -> drift
  7. notitie zonder memory_key -> blocked
  8. handmatig toegevoegde tekst -> niet stilzwijgend vernietigen
  9. 'ja' bij drift -> alleen de notitie wordt herschreven
 10. 'nee' bij drift -> niets wijzigen
 11. meerdere drifts achter elkaar, één voor één
 12. dubbele export -> geen tweede write
 13. exception midden in de batch -> veilig stoppen
 14. dry_run=True -> niets schrijven
 15. compare is volledig read-only
 16. memory.json byte-identiek
 17. vault byte-identiek waar geen expliciete export heeft plaatsgevonden
 18. bestaande vault-commando's blijven routeren
 19. pending_choice werkt correct
 20. nieuwe exportcommando's veroorzaken geen woordroof

PLUS: 'ja' mag een handgeschreven notitie NOOIT overschrijven.

Alle tests draaien op een tijdelijke vault, een tijdelijk
geheugenbestand en een tijdelijk gespreksbestand. De echte vault
wordt alleen in sectie 22 gelezen, nooit geschreven.
"""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    work = tempfile.mkdtemp(prefix='jarvis_vault_export_')
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

    def _vault_beeld(pad):
        """
    Een volledige vingerafdruk van een map: elk bestand met zijn
    relatieve pad, grootte en inhoud.

    Nodig omdat de echte vault van de gebruiker is en niet vaststaat
    hoeveel notities en instellingen die bevat. De vraag is niet
    "welke bestanden horen er in" maar "is er iets veranderd".
    """
        beeld = {}
        if not os.path.isdir(pad):
            return beeld
        for root, _, bestanden in os.walk(pad):
            for naam in bestanden:
                vol = os.path.join(root, naam)
                try:
                    with open(vol, 'rb') as file:
                        beeld[os.path.relpath(vol, pad)] = file.read()
                except OSError:
                    beeld[os.path.relpath(vol, pad)] = b'<onleesbaar>'
        return beeld
    _vault_voor = _vault_beeld(_echte_vault)

    def reset():
        """
    Schone teststand: geen geheugen, lege vault, geen openstaande keuze.

    Let op: memory.json is een bestand, dus os.remove() en NIET
    shutil.rmtree() -- die doet stil niets op een bestand.
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

    def geheugen():
        """De volledige memory.json als dict."""
        return mem.load_memory()

    def waarde(key, category='voorkeuren'):
        """De waarde van een memory, of None als die er niet is."""
        return geheugen().get(category, {}).get(key, {}).get('value')

    def notitie_inhoud(note_name):
        """De ruwe notitie-inhoud, of None als die niet bestaat."""
        return ob.read_note(note_name)

    def note_text(key, value, category='voorkeuren', **extra):
        """De notitie die JARVIS zou schrijven, zonder te schrijven."""
        return ob.memory_to_note({'value': value, **extra}, key=key, category=category)['content']

    def statuses(state):
        """Compacte lijst van (notitie, status)."""
        return [(r['note_name'], r['status']) for r in state['results']]

    def note_exists(name):
        return ob.note_exists(name)

    def file_hash(path):
        import hashlib
        if not os.path.exists(path):
            return None
        with open(path, 'rb') as file:
            return hashlib.sha1(file.read()).hexdigest()

    def vault_hash():
        """Hash van de volledige vault-inhoud, in een stabiele volgorde."""
        import hashlib
        hasher = hashlib.sha1()
        alles = []
        for current, dirs, files in os.walk(vault_path):
            dirs.sort()
            for name in sorted(files):
                pad = os.path.join(current, name)
                alles.append(os.path.relpath(pad, vault_path).replace(os.sep, '/'))
        for rel in sorted(alles):
            hasher.update(rel.encode('utf-8'))
            with open(os.path.join(vault_path, rel), 'rb') as file:
                hasher.update(file.read())
        return hasher.hexdigest()

    @patch.object(ai, 'CONVERSATION_FILE', conversation_file)
    @patch.object(mem, 'MEMORY_FILE', memory_file)
    def main():
        print('\n--- 1. lege vault ---')
        reset()
        zet_vault(None)
        rapport = vx.compare_memory_to_vault()
        assert rapport['ok'] is False and rapport['reason'] != '', 'analyse bij ontbrekende vault meldt dat'
        assert rapport['counts']['total'] == 0, 'analyse bij ontbrekende vault telt 0'
        state = vx.start_export()
        assert state['stopped'] is True and state['error'] != '', 'export bij ontbrekende vault stopt'
        assert not any((geheugen().get(c) for c in mem.DEFAULT_CATEGORIES)), 'export bij ontbrekende vault schrijft niets'
        reset()
        rapport = vx.compare_memory_to_vault()
        assert rapport['ok'] is True, 'lege vault geeft een gelukt rapport'
        assert rapport['counts']['total'] == 0, 'lege vault telt 0 notities'
        state = vx.start_export(dry_run=False)
        assert state['counts']['total'] == 0, 'export op lege vault doet niets'
        assert vx.export_is_finished(state) == 'done', 'export is klaar'
        assert state['error'] is None, 'export meldt geen fout'
        print('\n--- 2. leeg geheugen ---')
        reset()
        assert not any((geheugen().get(c) for c in mem.DEFAULT_CATEGORIES)), 'lege memory.json'
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['total'] == 0, 'analyse van leeg geheugen meldt 0'
        state = vx.start_export(dry_run=False)
        assert state['counts']['total'] == 0, 'export van leeg geheugen doet niets'
        assert vx.export_is_finished(state) == 'done', 'export is klaar'
        assert ob.list_notes() == [], 'de vault is nog steeds leeg'
        print('\n--- 3. beide leeg ---')
        reset()
        assert vx.compare_memory_to_vault()['counts']['total'] == 0, 'compare is gelukt en telt 0'
        state = vx.start_export()
        assert vx.export_is_finished(state) == 'done', 'dry_run export is klaar'
        assert state['results'] == [], 'geen results'
        assert state['error'] is None, 'geen fout'
        assert ob.list_notes() == [], 'er is niets geschreven'
        assert not any((geheugen().get(c) for c in mem.DEFAULT_CATEGORIES)), 'memory.json is nog steeds leeg'
        print('\n--- 4. create ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['create'] == 1, 'analyse ziet de nieuwe memory'
        assert rapport['counts']['total'] == 1, 'analyse telt 1 notitie'
        state = vx.start_export(dry_run=False)
        assert vx.export_is_finished(state) == 'done', 'export is klaar'
        assert state['counts']['written'] == 1, 'de notitie is geschreven'
        assert note_exists('voorkeuren/favoriete-kleur.md'), 'de notitie bestaat nu op schijf'
        inhoud = notitie_inhoud('voorkeuren/favoriete-kleur.md')
        assert inhoud.startswith('---'), 'de notitie begint met frontmatter'
        assert 'memory_key: favoriete kleur' in inhoud, 'de notitie bevat de memory_key'
        assert '> blauw' in inhoud, 'de notitie bevat de waarde'
        assert '- Sleutel: `favoriete kleur`' in inhoud, 'de notitie bevat de sleutelregel'
        print('\n--- 5. unchanged ---')
        state = vx.start_export(dry_run=False)
        assert state['counts']['written'] == 0, 'tweede export schrijft niets'
        assert state['counts']['unchanged'] == 1, 'de notitie wordt als onveranderd gezien'
        assert vx.export_is_finished(state) == 'done', 'export is klaar'
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['unchanged'] == 1, 'analyse ziet een exacte match'
        assert waarde('favoriete kleur') == 'blauw', 'memory.json is nog steeds blauw'
        oude = notitie_inhoud('voorkeuren/favoriete-kleur.md').replace('date: ' + _vandaag(), 'date: 2000-01-01')
        ob.write_note('voorkeuren/favoriete-kleur.md', oude)
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['unchanged'] == 1 and rapport['counts']['drift'] == 0, 'een oudere date: telt NIET als drift'
        print('\n--- 6. drift ---')
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'groen'))
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['drift'] == 1, 'analyse ziet het verschil'
        assert rapport['drift'][0]['key'] == 'favoriete kleur', 'het verschil hoort bij de juiste memory'
        assert rapport['drift'][0]['value'] == 'blauw', 'het verschil noemt de geheugenwaarde'
        state = vx.start_export(dry_run=False)
        assert state['paused'] is True, 'export pauzeert bij drift'
        assert vx.export_is_finished(state) == 'paused', 'export is nog niet klaar'
        assert isinstance(state['confirm'], dict), 'er staat een confirm klaar'
        assert state['confirm']['memory_value'] == 'blauw', 'confirm noemt de geheugenwaarde'
        assert state['confirm']['vault_value'] == 'groen', 'confirm noemt de vault-waarde'
        assert 'groen' in notitie_inhoud('voorkeuren/favoriete-kleur.md'), 'GEEN NOTITIE IS NOG AANGEROOKT'
        assert waarde('favoriete kleur') == 'blauw', 'GEEN MEMORY IS NOG AANGEROOKT'
        print('\n--- 7. blocked: geen memory_key ---')
        ob.write_note('voorkeuren/favoriete-kleur.md', 'Gewoon een handgeschreven tekst.\n')
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['blocked'] == 1, 'de notitie is geblokkeerd'
        assert 'memory_key' in rapport['blocked'][0]['reason'], 'de reden noemt het ontbrekende memory_key'
        state = vx.start_export(dry_run=False)
        assert state['counts']['written'] == 0, 'export schrijft hem niet'
        assert vx.export_is_finished(state) == 'done', 'export is klaar zonder te wachten'
        assert 'Gewoon een handgeschreven tekst.' in notitie_inhoud('voorkeuren/favoriete-kleur.md'), 'de handgeschreven tekst is bewaard'
        print('\n--- 8. eigen tekst wordt niet vernietigd ---')
        mem.remember('nog een', 'ja', category='algemeen', force=True)
        state = vx.start_export(dry_run=False)
        assert state['counts']['written'] == 1, 'de nieuwe memory is geschreven'
        assert note_exists('algemeen/nog-een.md'), 'notitie bestaat'
        ob.append_note('algemeen/nog-een.md', '\n## Mijn eigen notitie\n\nDit is van mij.\n')
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['blocked'] >= 1, 'eigen tekst maakt de notitie geblokkeerd'
        assert any(('niet van JARVIS' in r['reason'] for r in rapport['blocked'])), 'de reden noemt de eigen tekst'
        state = vx.start_export(dry_run=False)
        assert 'Dit is van mij.' in notitie_inhoud('algemeen/nog-een.md'), 'eigen tekst blijft staan'
        assert state['paused'] is False, 'de export is niet op zoek gegaan naar bevestiging'
        print('\n--- 9. ja bij drift ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'rood'))
        geheugen_voor = open(memory_file, 'rb').read()
        state = vx.start_export(dry_run=False)
        assert state['paused'] is True, 'export pauzeert'
        assert any((s == 'waiting' for s in [r['status'] for r in state['results']])), 'de status is waiting'
        state = vx.resolve_paused_export(state, overwrite=True)
        assert vx.export_is_finished(state) == 'done', 'export is klaar na de beslissing'
        assert state['counts']['overwritten'] == 1, 'de notitie is herschreven'
        assert 'blauw' in notitie_inhoud('voorkeuren/favoriete-kleur.md'), 'de notitie bevat de geheugenwaarde'
        assert 'rood' not in notitie_inhoud('voorkeuren/favoriete-kleur.md'), 'de oude waarde is niet meer in de notitie'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'MEMORY.JSON IS BYTE-IDENTIEK'
        assert waarde('favoriete kleur') == 'blauw', 'de geheugenwaarde is nog steeds blauw'
        print('\n--- 10. nee bij drift ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'geel'))
        notitie_voor = notitie_inhoud('voorkeuren/favoriete-kleur.md')
        geheugen_voor = open(memory_file, 'rb').read()
        vault_voor = vault_hash()
        state = vx.start_export(dry_run=False)
        state = vx.resolve_paused_export(state, overwrite=False)
        assert vx.export_is_finished(state) == 'done', 'export is klaar'
        assert state['counts']['kept'] == 1, "de notitie is bewaard na 'nee'"
        assert notitie_inhoud('voorkeuren/favoriete-kleur.md') == notitie_voor, 'NOTITIE IS NIET AANGEROOKT'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'memory.json is NIET aangeraakt'
        assert vault_hash() == vault_voor, 'de hele vault is NIET aangeraakt'
        assert waarde('favoriete kleur') == 'blauw', 'de geheugenwaarde is nog steeds blauw'
        print('\n--- 11. meerdere drifts ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        mem.remember('favoriete band', 'Radiohead', category='muziek', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'groen'))
        ob.write_note('muziek/favoriete-band.md', note_text('favoriete band', 'Nirvana', 'muziek'))
        geheugen_voor = open(memory_file, 'rb').read()
        state = vx.start_export(dry_run=False)
        assert state['paused'] is True, 'de eerste drift stopt de export'
        geheugen_midden = open(memory_file, 'rb').read()
        assert geheugen_midden == geheugen_voor, 'tussen de twee drifts is memory.json nog steeds gelijk'
        beslissingen = 0
        while vx.export_is_finished(state) == 'paused' and beslissingen < 10:
            beslissingen += 1
            state = vx.resolve_paused_export(state, overwrite=True)
        assert vx.export_is_finished(state) == 'done', 'de export is na twee beslissingen klaar'
        assert beslissingen == 2, 'er zijn twee bevestigingen gevraagd'
        assert sum((1 for r in state['results'] if r['status'] == 'overwritten')) == 2, 'twee notities zijn beoordeeld'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'MEMORY IS NOOIT AANGEROOKT'
        assert 'blauw' in notitie_inhoud('voorkeuren/favoriete-kleur.md') and 'Radiohead' in notitie_inhoud('muziek/favoriete-band.md'), 'beide notities zijn naar de geheugenwaarde gezet'
        print('\n--- 12. dubbele export ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        state = vx.start_export(dry_run=False)
        assert state['counts']['written'] == 1, 'eerste export schrijft'
        vault_na_eerste = vault_hash()
        tweede = vx.start_export(dry_run=False)
        assert tweede['counts']['written'] == 0, 'tweede export schrijft niets'
        assert tweede['counts']['unchanged'] == 1, 'tweede export meldt onveranderd'
        assert vault_hash() == vault_na_eerste, 'de vault is identiek na de tweede run'
        notitie = 'voorkeuren/favoriete-kleur.md'
        handmatig = {'dry_run': False, 'results': [], 'queue': [notitie, notitie], 'processed': [], 'confirm': None, 'paused': False, 'done': False, 'stopped': False, 'error': None, 'counts': {}, '_plans': {notitie: {'note_name': notitie, 'key': 'favoriete kleur', 'category': 'voorkeuren', 'value': 'blauw', 'content': note_text('favoriete kleur', 'blauw'), 'action': 'unchanged', 'reason': ''}}}
        handmatig = vx._advance_export(handmatig)
        assert any((r['status'] == 'duplicate' for r in handmatig['results'])), "een dubbele notitie krijgt status 'duplicate'"
        assert handmatig['done'] is True, 'de batch is klaar'
        assert sum((1 for r in handmatig['results'] if r['note_name'] == notitie)) == 2, 'de notitie is maar één keer verwerkt'
        print('\n--- 13. exception in de batch ---')
        reset()
        mem.remember('aaa eerste', 'een', category='voorkeuren', force=True)
        mem.remember('mmm tweede', 'twee', category='voorkeuren', force=True)
        mem.remember('zzz derde', 'drie', category='voorkeuren', force=True)
        origineel = vx._schrijf_notitie

        def kapot(note_name, inhoud, sleutel=None):
            if 'mmm-tweede' in note_name:
                raise RuntimeError('gesimuleerde schijffout')
            return origineel(note_name, inhoud, sleutel)
        vx._schrijf_notitie = kapot
        try:
            state = vx.start_export(dry_run=False)
        finally:
            vx._schrijf_notitie = origineel
        assert state['stopped'] is True, 'de export stopt bij de fout'
        assert 'RuntimeError' in (state['error'] or ''), 'de fout is vastgelegd'
        assert vx.export_is_finished(state) == 'error', 'status is error'
        assert any((r['status'] == 'error' for r in state['results'])), "de mislukte notitie kreeg status 'error'"
        assert 'voorkeuren/mmm-tweede.md' not in state['processed'], 'de notitie is NIET als verwerkt gemarkeerd'
        assert 'voorkeuren/zzz-derde.md' in state['queue'], 'de resterende wachtrij is bewaard'
        assert note_exists('voorkeuren/aaa-eerste.md'), 'de notitie van vóór de fout WEL geschreven is'
        assert not note_exists('voorkeuren/zzz-derde.md'), 'de notitie ná de fout NIET geschreven is'
        assert all((r['status'] for r in state['results'])), 'geen enkele notitie hangt zonder status'
        print('\n--- 14. dry_run ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vault_voor = vault_hash()
        geheugen_voor = open(memory_file, 'rb').read()
        state = vx.start_export()
        assert state['dry_run'] is True, 'dry_run is de standaard'
        assert state['counts']['planned'] == 1, 'dry_run meldt een plan'
        assert ob.list_notes() == [], 'dry_run schrijft niets'
        assert vault_hash() == vault_voor, 'dry_run maakt geen map aan'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'dry_run laat memory.json met rust'
        assert vx.export_is_finished(state) == 'done', 'dry_run is klaar'
        print('\n--- 15. read-only analyse ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'groen'))
        vault_voor = vault_hash()
        geheugen_voor = open(memory_file, 'rb').read()
        mtime_voor = os.path.getmtime(memory_file)
        notities_voor = sorted(ob.list_notes())
        rapport = vx.compare_memory_to_vault()
        assert rapport['counts']['drift'] == 1, 'analyse meldt het verschil'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'memory.json is byte-identiek na de analyse'
        assert os.path.getmtime(memory_file) == mtime_voor, 'memory.json mtime is onveranderd'
        assert vault_hash() == vault_voor, 'de vault is byte-identiek na de analyse'
        assert sorted(ob.list_notes()) == notities_voor, 'de lijst notities is gelijk gebleven'
        assert waarde('favoriete kleur') == 'blauw', 'het verschil is NIET opgelost'
        assert geheugen()['voorkeuren']['favoriete kleur'].get('conflict') is not True, 'er is geen conflict-vlag gezet'
        vx.compare_memory_to_vault()
        assert open(memory_file, 'rb').read() == geheugen_voor, 'dubbele analyse laat memory.json met rust'
        assert vault_hash() == vault_voor, 'dubbele analyse laat de vault met rust'
        print('\n--- 16. memory.json blijft intact ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        mem.remember('favoriete band', 'Radiohead', category='muziek', force=True)
        mem.remember('heeft gpu', True, category='pc', force=True)
        geheugen_voor = open(memory_file, 'rb').read()
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'groen'))
        ob.write_note('muziek/favoriete-band.md', note_text('favoriete band', 'Nirvana', 'muziek'))
        state = vx.start_export(dry_run=False)
        vx.resolve_paused_export(state, overwrite=True)
        assert open(memory_file, 'rb').read() == geheugen_voor, 'memory.json is na de volledige exportflow byte-identiek'
        print('\n--- 17. vault onveranderd waar niets is uitgevoerd ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('losse notitie.md', 'Dit is een losse notitie.')
        vault_voor = vault_hash()
        geheugen_voor = open(memory_file, 'rb').read()
        state = vx.start_export(dry_run=False)
        assert 'Dit is een losse notitie.' in notitie_inhoud('losse notitie.md'), 'de losse notitie wordt niet aangeraakt'
        assert note_exists('losse notitie.md'), 'de losse notitie is niet weggeschreven'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'memory.json is onveranderd'
        assert vault_hash() == vault_voor, 'de vault is onveranderd'
        print("\n--- 18. bestaande commando's ---")
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        for commando, verwacht in [('wat heb ik in mijn vault staan', 'try_vault_info'), ('importeer alles uit mijn vault', 'try_vault_batch'), ('zet voorkeuren/favoriete-kleur in mijn geheugen', 'try_vault_import'), ('vergelijk mijn vault met mijn geheugen', 'try_vault_compare')]:
            antwoord = brain.process_command(commando)
            assert isinstance(antwoord, str) and antwoord, f"'{commando}' geeft nog steeds antwoord"
            assert 'het verschil bij' not in antwoord.lower(), f"'{commando}' is geen export"
        antwoord = brain.process_command('zet voorkeuren/favoriete-kleur in mijn geheugen')
        assert isinstance(antwoord, str) and antwoord, 'de import-vraag loopt nog steeds'
        print('\n--- 19. pending_choice ---')
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'violet'))
        geheugen_voor = open(memory_file, 'rb').read()
        antwoord = brain.process_command('exporteer mijn geheugen naar de vault')
        assert isinstance(antwoord, str) and 'Zal ik de notitie bijwerken' in antwoord, 'de exportvraag bevestiging geeft'
        assert 'blauw' in antwoord and 'violet' in antwoord, 'de vraag noemt beide waarden'
        pending = ai.current_context.get('pending_choice')
        assert isinstance(pending, dict), 'er staat een pending_choice klaar'
        assert pending['kind'] == 'memory_update', 'de pending_choice is een memory_update-vorm'
        assert isinstance(pending.get('vault_export'), dict), 'de pending_choice bevat de export-state'
        assert _is_json(pending['vault_export']), 'de export-state is JSON-geschikt'
        assert pending['vault_export']['paused'] is True, 'de export-state bevat de openstaande drift'
        assert not _bevat_inhoud(pending['vault_export']), 'de state bewaart GEEN volledige notitie-inhoud'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'MEMORY IS NOG NIET AANGEROOKT'
        antwoord = brain.process_command('nee')
        assert isinstance(antwoord, str) and antwoord, "'nee' geeft een antwoord"
        assert ai.current_context.get('pending_choice') is None, "'nee' wist de pending_choice"
        assert 'violet' in notitie_inhoud('voorkeuren/favoriete-kleur.md'), "'nee' laat de notitie exact staan"
        assert open(memory_file, 'rb').read() == geheugen_voor, "'nee' laat memory.json met rust"
        print('\n--- 20. woordroof ---')
        for commando in ['open discord', 'wat is het weer', 'zet de radio aan', 'vergelijk twee dingen', 'importeer alles uit mijn vault', 'wat heb ik in mijn vault staan']:
            assert brain.try_vault_export(commando) is None, f"'{commando}' triggert GEEN export"
        for commando in ['exporteer mijn geheugen naar de vault', 'zet mijn geheugen in obsidian', 'migreer mijn geheugen naar Obsidian', 'vergelijk mijn geheugen met de vault']:
            assert brain.try_vault_import(commando) is None, f"'{commando}' gaat NIET naar de import"
        assert brain.try_vault_export('zet voorkeuren/licht in mijn geheugen') is None, 'import-zinnen triggert GEEN export'
        reset()
        mem.remember('favoriete kleur', 'blauw', category='voorkeuren', force=True)
        vx.start_export(dry_run=False)
        ob.write_note('voorkeuren/favoriete-kleur.md', note_text('favoriete kleur', 'rood'))
        uitvoer_export = brain.process_command('vergelijk mijn geheugen met de vault')
        assert "geheugen zegt 'blauw'" in uitvoer_export, 'de export-vergelijking noemt de richting correct'
        uitvoer_import = brain.process_command('vergelijk mijn vault met mijn geheugen')
        assert "je vault zegt 'rood'" in uitvoer_import, 'de import-vergelijking noemt de richting correct'
        print('\n--- 21. ja mag eigen tekst niet vernietigen ---')
        reset()
        mem.remember('nog een', 'ja', category='algemeen', force=True)
        vx.start_export(dry_run=False)
        ob.append_note('algemeen/nog-een.md', '\n## Mijn eigen notitie\n\nDit is van mij.\n')
        eigen_voor = notitie_inhoud('algemeen/nog-een.md')
        geheugen_voor = open(memory_file, 'rb').read()
        state = vx.start_export(dry_run=False)
        assert state['paused'] is False, 'de export wacht niet, want er is geen drift'
        assert notitie_inhoud('algemeen/nog-een.md') == eigen_voor, 'de eigen tekst staat er nog'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'memory.json is onveranderd'
        plan = vx.compare_memory_to_vault()
        blocked = [r for r in plan['blocked'] if r['key'] == 'nog een']
        assert len(blocked) == 1, 'de notitie staat als blocked in het rapport'
        origineel = vx._schrijf_notitie
        schrijfaanroepen = []

        def telt(note_name, inhoud, sleutel=None):
            schrijfaanroepen.append(note_name)
            return origineel(note_name, inhoud, sleutel)
        vx._schrijf_notitie = telt
        try:
            handmatig = {'dry_run': False, 'results': [{'note_name': 'algemeen/nog-een.md', 'key': 'nog een', 'category': 'algemeen', 'value': 'ja', 'status': 'waiting', 'label': '', 'reason': 'wacht op bevestiging'}], 'queue': ['algemeen/nog-een.md'], 'processed': [], 'paused': True, 'confirm': {'note_name': 'algemeen/nog-een.md', 'key': 'nog een', 'category': 'algemeen', 'memory_value': 'ja', 'vault_value': 'ja'}, 'done': False, 'stopped': False, 'error': None, 'counts': {}, '_plans': {'algemeen/nog-een.md': {'note_name': 'algemeen/nog-een.md', 'key': 'nog een', 'category': 'algemeen', 'value': 'ja', 'content': note_text('nog een', 'ja', 'algemeen'), 'action': 'blocked', 'reason': 'de notitie bevat tekst'}}}
            handmatig = vx.resolve_paused_export(handmatig, overwrite=True)
        finally:
            vx._schrijf_notitie = origineel
        assert schrijfaanroepen == [], "een handmatige 'ja' op een blocked notitie roept de schrijffunctie NIET aan"
        assert notitie_inhoud('algemeen/nog-een.md') == eigen_voor, "een handmatige 'ja' op een blocked notitie schrijft NIETS"
        assert any((r['status'] == 'blocked' for r in handmatig['results'])), 'de status is blocked'
        assert open(memory_file, 'rb').read() == geheugen_voor, 'memory.json is nog steeds onveranderd'
        print('\n--- 22. echte bestanden ---')
        if _geheugen_voor is not None:
            with open(_echte_memory, 'rb') as file:
                assert file.read() == _geheugen_voor, 'echte memory.json is onveranderd'
        if _gesprek_voor is not None:
            with open(_echte_conversation, 'rb') as file:
                assert file.read() == _gesprek_voor, 'echte conversation.json is onveranderd'
        assert _vault_beeld(_echte_vault) == _vault_voor, 'de echte vault is byte voor byte onveranderd'
        assert ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, 'JARVIS Memory'), 'de standaard-vault staat nog goed'
        print('\n--- 23. geen koppeling naar Memory 2.0 ---')
        import inspect
        import ast
        bron = inspect.getsource(vx)
        boom = ast.parse(bron)
        aanroepen = set()
        for node in ast.walk(boom):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    aanroepen.add(node.func.attr)
        for niet_toegestaan in ('remember', 'update_memory', 'resolve_conflict'):
            assert niet_toegestaan not in aanroepen, f'vault_export roept {niet_toegestaan}() NIET aan'
        assert 'requests' not in bron and 'urllib' not in bron and ('socket' not in bron), 'vault_export gebruikt geen netwerk'
        assert not any((name.startswith(('requests', 'urllib3', 'yaml', 'pyyaml')) for name in _imports(boom))), 'vault_export importeert geen nieuwe externe pakketten'
        assert _vault_beeld(_echte_vault) == _vault_voor, 'de echte vault is byte voor byte onveranderd'

    def _vandaag():
        from datetime import date
        return date.today().isoformat()

    def _imports(boom):
        import ast
        namen = set()
        for node in ast.walk(boom):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    namen.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                namen.add((node.module or '').split('.')[0])
        return namen

    def _is_json(ding):
        try:
            json.dumps(ding)
            return True
        except (TypeError, ValueError):
            return False

    def _bevat_inhoud(boom, diepte=0):
        """True als er ergens in de state een notitie-tekst staat."""
        if diepte > 8:
            return False
        if isinstance(boom, str):
            return '## Details' in boom or 'memory_key:' in boom
        if isinstance(boom, dict):
            return any((_bevat_inhoud(v, diepte + 1) for v in boom.values()))
        if isinstance(boom, (list, tuple)):
            return any((_bevat_inhoud(v, diepte + 1) for v in boom))
        return False
    main()
    ai.CONVERSATION_FILE = _echte_conversation
    ob.set_vault_path(_echte_vault)
    mem.store.reset_cache()
    shutil.rmtree(work, ignore_errors=True)
