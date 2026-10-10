import sys
import os
import io
import json
import shutil
import tempfile
from unittest.mock import patch
from memory import store
from memory import memory as mem
from memory import obsidian as ob
from memory import vault_import as vi
from memory import vault_export as vx
import core.brain as brain
import core.ai as ai

def test_main():
    """
JARVIS — Memory 2.0 identiteit, types en categorieën (stabilisatie)
===================================================================

Regressietests voor de drie ontwerpbesluiten die vóór Stap 7 zijn
vastgelegd. Ze bewaken het gedrag dat eerst fout was:

  1. FUZZY KEY MATCHING SCHEIDEN VAN IDENTITEIT
     Een substring mag nooit bepalen welke memory-entry wordt
     aangemaakt, gewijzigd, verwijderd of als conflict beschouwd.
     Opslag-identiteit is exact + normalisatie (_ ≡ - ≡ spatie).
     Losse substring-matching bestaat alleen nog als
     resolve_existing_key(): een gesprekshulp die niets wegschrijft.

  2. TYPEGRENS MEMORY <-> OBSIDIAN
     memory.json bewaart JSON-types; de vault bewaart een leesbare
     body plus 'value_type' (en 'value_json' voor niet-'str').
     memory -> Obsidian -> memory geeft dezelfde Python-waarde terug,
     en een re-import levert geen vals conflict op.

  3. CATEGORIEBELEID
     Memory 2.0 kent alleen de standaardcategorieën. Een onbekende
     categorie wordt naar 'algemeen' gebracht, zodat een entry nooit
     stilzwijgend onleesbaar kan worden.

Alle tests draaien op tijdelijke bestanden; de echte
memory/memory.json en de echte Obsidian-vault worden nooit
aangeraakt.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    work = tempfile.mkdtemp(prefix='jarvis_identity_test_')
    path = os.path.join(work, 'memory.json')
    vault = os.path.join(work, 'vault')
    os.makedirs(vault)
    _echte_mem = mem.MEMORY_FILE
    _echte_vault = ob.get_vault_path()
    _echte_conversation = ai.CONVERSATION_FILE
    mem.MEMORY_FILE = path
    ob.set_vault_path(vault)
    conversation = os.path.join(work, 'conversation.json')
    with open(conversation, 'w', encoding='utf-8') as f:
        json.dump({'history': [], 'context': dict(brain.current_context)}, f)
    ai.CONVERSATION_FILE = conversation
    brain.current_context['pending_choice'] = None
    _orig_ctx = dict(brain.current_context)

    def reset():
        """Lege het geheugen en de vault, en wis de teller-toestand."""
        mem.clear_memory()
        store.reset_cache()
        brain.current_context['pending_choice'] = None
    print('\n===== 1: FUZZY KEY MATCHING =====\n')
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    mem.remember('band', 'Radiohead', category='muziek')
    assert set(mem.load_memory()['muziek']) == {'fav band', 'band'}, 'beide sleutels bestaan naast elkaar'
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    mem.remember('band', 'Radiohead', category='muziek')
    mem.forget('band')
    assert mem.recall('fav band') == 'Coldplay', "forget('band') verwijdert NIET 'fav band'"
    assert mem.recall('band') is None, "forget('band') verwijdert wel 'band'"
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    mem.remember('band', 'Radiohead', category='muziek')
    mem.reset_touch_usage()
    mem.touch_usage('band')
    assert mem.get_entry('fav band').get('usage_count') == 0, "touch_usage('band') telt NIET bij 'fav band'"
    assert mem.get_entry('band').get('usage_count') == 1, "touch_usage('band') telt bij 'band'"
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    result = mem.remember('band', 'Radiohead', category='muziek')
    assert result.get('conflict') is False, "remember('band') meldt geen conflict met 'fav band'"
    assert mem.recall('band') == 'Radiohead', "remember('band') slaat daadwerkelijk op"
    assert mem.recall('fav band') == 'Coldplay', "'fav band' blijft onveranderd"
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    gevonden_cat, gevonden_key, entry = mem._find_existing('band', 'muziek')
    assert gevonden_key is None and entry is None, "_find_existing('band') vindt NIET 'fav band'"
    assert mem.find_entry('band', 'muziek') == (None, None), "find_entry('band') vindt NIET 'fav band'"
    assert mem.recall('band') is None, "recall('band') geeft niets terug"
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    conflict, old, category = mem.has_conflict('band', 'Radiohead', 'muziek')
    assert conflict is False and old is None, "has_conflict('band') is geen conflict met 'fav band'"
    reset()
    mem.remember('favoriete_kleur', 'blauw', category='voorkeuren')
    assert mem.recall('favoriete kleur') == 'blauw', "normalisatie: 'favoriete kleur' vindt 'favoriete_kleur'"
    assert mem.recall('favoriete-kleur') == 'blauw', "normalisatie: 'favoriete-kleur' vindt 'favoriete_kleur'"
    assert mem.recall('FAVORIETE_KLEUR') == 'blauw', 'normalisatie: hoofdletters doen niets'
    assert mem.forget('favoriete kleur') and mem.recall('favoriete_kleur') is None, 'forget genormaliseerd werkt'
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    oplossing = mem.resolve_existing_key('band', 'muziek')
    assert oplossing['status'] == 'fuzzy' and oplossing['candidates'] == ['fav band'], "resolver stelt 'fav band' voor"
    assert oplossing['key'] == 'fav band', 'resolver wijst bij één kandidaat automatisch aan'
    assert oplossing['exact'] is False, 'de resolver is geen exacte match'
    assert mem.recall('fav band') == 'Coldplay' and set(mem.load_memory()['muziek']) == {'fav band'}, 'resolver wijst niets af (verandert niets)'
    r = mem.resolve_existing_key('fav band', 'muziek')
    assert r['status'] == 'exact' and r['key'] == 'fav band' and (r['exact'] is True), 'resolver geeft exact terug bij een exacte sleutel'
    r = mem.resolve_existing_key('iets wat er niet is', 'muziek')
    assert r['status'] == 'none' and r['candidates'] == [], "resolver geeft 'none' zonder kandidaten"
    assert r['key'] == 'iets wat er niet is', 'resolver valt terug op de oorspronkelijke query'
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    mem.remember('fav bands', 'Radiohead', category='muziek')
    mem.remember('mijn band', 'Imagine Dragons', category='muziek')
    oplossing = mem.resolve_existing_key('band', 'muziek')
    assert len(oplossing['candidates']) == 3, 'meerdere kandidaten gevonden'
    assert oplossing['key'] is None, 'meerdere kandidaten -> GEEN automatische sleutel'
    assert 'fav band' in oplossing['candidates'], 'meerdere kandidaten blijven wel zichtbaar'
    reset()
    mem.remember('lichtvoorkeur', 'warm', category='voorkeuren')
    antwoord = brain.try_memory_update('wijzig mijn licht naar koel wit')
    assert antwoord is not None and 'bedoelde je' in str(antwoord).lower() and ('lichtvoorkeur' in str(antwoord).lower()), "'wijzig mijn licht' vraagt welke sleutel bedoeld is"
    assert (brain.current_context.get('pending_choice') or {}).get('kind') == 'memory_key_confirm', 'er is een pending_choice klaargezet'
    assert mem.recall('lichtvoorkeur') == 'warm', 'niets gewijzigd vóór de bevestiging'
    antwoord = brain.process_command('ja')
    assert antwoord is not None and 'koel wit' in str(antwoord), "'ja' zet de voorgestelde sleutel door"
    assert mem.recall('lichtvoorkeur') == 'koel wit', "'ja' werkt de wijziging echt door"
    reset()
    mem.remember('lichtvoorkeur', 'warm', category='voorkeuren')
    brain.try_memory_update('wijzig mijn licht naar koel wit')
    brain.process_command('nee')
    assert mem.recall('lichtvoorkeur') == 'warm', "'nee' laat de oude waarde staan"
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    mem.remember('mijn band', 'Imagine Dragons', category='muziek')
    antwoord = brain.try_forget('vergeet band')
    assert antwoord is not None and 'meerdere' in str(antwoord).lower(), "'vergeet band' maakt geen automatische keuze"
    assert brain.current_context.get('pending_choice') is None, "'vergeet band' met meerdere kandidaten zet geen pending_choice"
    assert mem.recall('fav band') == 'Coldplay' and mem.recall('mijn band') == 'Imagine Dragons', "'vergeet band' verwijdert niets"
    reset()
    mem.remember('fav band', 'Coldplay', category='muziek')
    antwoord = brain.try_forget('vergeet band')
    assert antwoord is not None and 'bedoelde je' in str(antwoord).lower() and ('fav band' in str(antwoord).lower()), "'vergeet band' vraagt bevestiging bij één kandidaat"
    assert mem.recall('fav band') == 'Coldplay', "'fav band' staat er nog steeds"
    antwoord = brain.process_command('ja')
    assert antwoord is not None and 'vergeten' in str(antwoord).lower() and (mem.recall('fav band') is None), "'ja' verwijdert dan wel 'fav band'"
    reset()
    mem.remember('favoriete_kleur', 'groen', category='voorkeuren')
    antwoord = brain._remember_or_ask('favoriete_kleur', 'rood', 'voorkeuren')
    assert antwoord is not None and 'wijzigen' in str(antwoord), 'tegenstrijdige waarde vraagt nog steeds bevestiging'
    assert mem.recall('favoriete_kleur') == 'groen', 'de oude waarde staat er nog'
    brain.process_command('ja')
    assert mem.recall('favoriete_kleur') == 'rood', "'ja' op een conflict overschrijft wel"
    print('\n===== 2: TYPEGRENS MEMORY <-> OBSIDIAN =====\n')
    assert ob.value_type_name(True) == 'bool', "value_type_name(True) == 'bool'"
    assert ob.value_type_name(42) == 'int', "value_type_name(42) == 'int'"
    assert ob.value_type_name(1.0) == 'float', "value_type_name(1.0) == 'float'"
    assert ob.value_type_name('x') == 'str', "value_type_name('x') == 'str'"
    assert ob.value_type_name(['a']) == 'list', "value_type_name(['a']) == 'list'"
    assert ob.value_type_name({'a': 1}) == 'dict', "value_type_name({'a': 1}) == 'dict'"
    assert ob.value_type_name(None) == 'null', "value_type_name(None) == 'null'"
    assert ob.value_type_name(1) == 'int', 'value_type_name(1) is geen bool'
    assert mem._values_equal(True, True), '_values_equal(True, True)'
    assert mem._values_equal(False, False), '_values_equal(False, False)'
    assert mem._values_equal(42, 42), '_values_equal(42, 42)'
    assert mem._values_equal(1.0, 1.0), '_values_equal(1.0, 1.0)'
    assert mem._values_equal(['a'], ['a']), "_values_equal(['a'], ['a'])"
    assert mem._values_equal({'a': 1}, {'a': 1}), "_values_equal({'a': 1}, {'a': 1})"
    assert mem._values_equal(None, None), '_values_equal(None, None)'
    assert mem._values_equal(True, 'ja') is False, "_values_equal(True, 'ja') is NIET gelijk"
    assert mem._values_equal(True, 1) is False, '_values_equal(True, 1) is NIET gelijk'
    assert mem._values_equal(42, '42') is False, "_values_equal(42, '42') is NIET gelijk"
    assert mem._values_equal(42, 42.0) is True, '_values_equal(42, 42.0) IS gelijk'
    ROUND_TRIP = [('rt_tekst', 'blauw'), ('rt_ja', True), ('rt_nee', False), ('rt_int', 42), ('rt_float', 1.5), ('rt_lijst', ['a', 'b']), ('rt_lijst_nr', [1, 2]), ('rt_dict', {'a': 1}), ('rt_dict_genest', {'a': [1, 2], 'b': 'x'}), ('rt_none', None)]
    reset()
    for sleutel, waarde in ROUND_TRIP:
        mem.remember(sleutel, waarde, category='algemeen')
    rapport = vx.compare_memory_to_vault()
    assert all((r['action'] == 'create' for r in rapport['notes'] if r['key'] in dict(ROUND_TRIP))), 'elk type komt in het exportrapport voor'
    state = vx.start_export(dry_run=False)
    if state.get('paused'):
        state = vx.resolve_paused_export(state, True)
    assert vx.export_is_finished(state), 'de export is klaar'
    for sleutel, waarde in ROUND_TRIP:
        note = ob.note_name_for_memory(sleutel, 'algemeen')
        terug = vi.note_to_memory(note)
        label = f'round-trip {sleutel}'
        assert ob.note_exists(note), f'{label}: notitie bestaat'
        assert terug is not None and terug['value'] == waarde and (type(terug['value']) is type(waarde)), f'{label}: waarde blijft {waarde!r}'
        conflict, _, _ = mem.has_conflict(sleutel, terug['value'], 'algemeen')
        assert conflict is False, f'{label}: geen vals conflict bij herimport'
    note = ob.read_note(ob.note_name_for_memory('rt_ja', 'algemeen'))
    assert '> ja' in note, "bool blijft leesbaar als 'ja'"
    note = ob.read_note(ob.note_name_for_memory('rt_tekst', 'algemeen'))
    assert '> blauw' in note, 'tekst blijft leesbaar'
    note = ob.read_note(ob.note_name_for_memory('rt_lijst', 'algemeen'))
    assert '> - a' in note, "lijst blijft leesbaar als '- item'"
    hand = 'algemeen/handgeschreven.md'
    _pad = ob.resolve_note_path(hand)
    os.makedirs(os.path.dirname(_pad), exist_ok=True)

    def schrijf_notitie(frontmatter, body):
        with open(_pad, 'w', encoding='utf-8') as f:
            f.write('---\n' + frontmatter + '---\n\n# handgeschreven\n\n> ' + body + '\n\n## Details\n\n')
    schrijf_notitie('title: handgeschreven\ncategory: algemeen\nmemory_key: handgeschreven\ntags: []\ndate: 2026-01-01\n', 'blauw')
    terug = vi.note_to_memory(hand)
    assert terug is not None and terug['value'] == 'blauw', 'oude notitie zonder value_type blijft importeerbaar'
    assert type(terug['value']) is str, 'oude notitie levert een string'
    schrijf_notitie('title: handgeschreven\ncategory: algemeen\nmemory_key: handgeschreven\ntags: []\nvalue_type: banaan\ndate: 2026-01-01\n', 'blauw')
    terug = vi.note_to_memory(hand)
    assert terug is not None and terug['value'] == 'blauw' and (type(terug['value']) is str), 'ongeldige value_type valt terug op string'
    schrijf_notitie('title: handgeschreven\ncategory: algemeen\nmemory_key: handgeschreven\ntags: []\nvalue_type: int\nvalue_json: 32\ndate: 2026-01-01\n', '99')
    terug = vi.note_to_memory(hand)
    assert terug is not None and terug['value'] == 99 and (type(terug['value']) is int), 'een bewerkte body wint van value_json'
    schrijf_notitie('title: handgeschreven\ncategory: algemeen\nmemory_key: handgeschreven\ntags: []\ndate: 2026-01-01\n', '')
    assert vi.note_to_memory(hand) is None, 'lege body zonder value_type wordt overgeslagen'
    for sleutel, waarde in ROUND_TRIP:
        note = ob.note_name_for_memory(sleutel, 'algemeen')
        terug = vi.note_to_memory(note)
        nieuw = dict(mem.get_entry(sleutel, 'algemeen'))
        nieuw['value'] = terug['value']
        eerst = ob.memory_to_note(mem.get_entry(sleutel, 'algemeen'), key=sleutel, category='algemeen')
        daarna = ob.memory_to_note(nieuw, key=sleutel, category='algemeen')
        assert eerst['content'] == daarna['content'], f'idempotentie {sleutel}: dezelfde notitie'
    print('\n===== 3: CATEGORIEBELEID =====\n')
    reset()
    mem.remember('lamp_kleur', 'warm', category='sfeer')
    assert 'sfeer' not in mem.load_memory(), 'onbekende categorie wordt niet opgeslagen'
    assert mem.recall('lamp_kleur') == 'warm', 'inhoud gaat niet verloren'
    assert set(mem.load_memory()) == set(mem.DEFAULT_CATEGORIES), 'het geheugen kent alleen de standaardcategorieën'
    assert mem.recall('lamp_kleur') == 'warm', 'recall() ziet de entry nu wel'
    assert mem.get_entry('lamp_kleur') is not None, 'get_entry() ziet de entry nu wel'
    assert mem.get_all_memory().get('lamp_kleur') == 'warm', 'get_all_memory() ziet de entry nu wel'
    assert 'lamp kleur' in mem.memory_summary(), 'memory_summary() noemt de entry nu wel'
    assert any((i['key'] == 'lamp_kleur' for i in mem.get_relevant_memory('hoe zit het met de lamp kleur'))), 'get_relevant_memory() vindt de entry nu wel'
    assert mem.has_conflict('lamp_kleur', 'koel', None)[0] is True, 'resolve_conflict() vindt de entry nu wel'
    assert mem.forget('lamp_kleur') and mem.recall('lamp_kleur') is None, 'forget() raakt de entry nu wel'
    assert (mem.remember('gpu_merk', 'nvidia', category='pc'), mem.get_entry('gpu_merk', 'pc') is not None)[1], 'een standaardcategorie blijft gewoon werken'
    assert mem._canonical_category(None) is None, '_canonical_category(None) blijft None'
    assert mem._canonical_category('pc') == 'pc', "_canonical_category('pc') blijft 'pc'"
    assert mem._canonical_category('PC') == 'pc', "_canonical_category('PC') wordt 'pc'"
    assert mem._canonical_category('sfeer') == 'algemeen', "_canonical_category('sfeer') wordt 'algemeen'"
    assert mem._canonical_category('') is None, "_canonical_category('') blijft None"
    reset()
    store.write(path, {'voorkeuren': {}, 'pc': {}, 'projecten': {}, 'muziek': {}, 'algemeen': {'al_gekend': 'ja'}, 'apparaten': {}, 'sfeer': {'lamp_kleur': 'warm', 'al_gekend': 'nee'}})
    store.reset_cache()
    geladen = mem.load_memory()
    assert 'sfeer' not in geladen, 'een oude onbekende categorie verdwijnt'
    assert (geladen['algemeen'].get('lamp_kleur') or {}).get('value') == 'warm', "haar entries verhuizen naar 'algemeen'"
    assert mem.recall('al_gekend') == 'ja', 'een naambotsing overschrijft niet'
    assert set(geladen) == set(mem.DEFAULT_CATEGORIES), 'het blijft een geldige memory'
    reset()
    assert set(mem.load_memory()) == set(mem.DEFAULT_CATEGORIES), 'een lege memory is nog steeds geldig'
    reset()
    mem.remember('lamp_kleur', 'warm', category='sfeer')
    state = vx.start_export(dry_run=False)
    if state.get('paused'):
        state = vx.resolve_paused_export(state, True)
    terug = vi.note_to_memory(ob.note_name_for_memory('lamp_kleur', 'algemeen'))
    assert terug is not None and terug['category'] == 'algemeen', "de notitie houdt de policy-categorie 'algemeen'"
    assert terug is not None and terug['value'] == 'warm', 'de waarde overleeft de export'
    brain.current_context.update(_orig_ctx)
    ai.CONVERSATION_FILE = _echte_conversation
    mem.MEMORY_FILE = _echte_mem
    ob.set_vault_path(_echte_vault)
    store.reset_cache()
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'=' * 60}")
    print(f"{'=' * 60}")
