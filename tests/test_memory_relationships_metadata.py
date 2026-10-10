import sys
import os
import io
import json
import shutil
import tempfile
from memory import store
from memory import memory as mem
from memory import obsidian as ob
from memory import vault_import as vi
from memory import vault_export as vx

def test_main():
    """
JARVIS — Memory 2.0 relaties en metadata-contract (Stap 7)
==========================================================

Gerichte tests voor de vijf dingen die Stap 7 toevoegt:

  1. `created`   : een stabiel ISO 8601-tijdstip met tijdzone dat een
                   waardewijziging overleeft
  2. het metadata-contract : één centrale definitie die echt gebruikt wordt
  3. `related`   : echte relaties in plaats van alle siblings
  4. Obsidian    : die metadata overleeft export -> import -> export
  5. backward compatibiliteit: oude data en oude notities blijven geldig

Elke test draait op tijdelijke bestanden. De echte memory/memory.json,
memory/conversation.json en de echte JARVIS Memory Vault worden nooit
aangeraakt.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    work = tempfile.mkdtemp(prefix='jarvis_stap7_')
    path = os.path.join(work, 'memory.json')
    vault = os.path.join(work, 'vault')
    os.makedirs(vault)
    _echte_mem = mem.MEMORY_FILE
    _echte_vault = ob.get_vault_path()
    mem.MEMORY_FILE = path
    ob.set_vault_path(vault)

    def reset():
        """Leeg het geheugen EN de vault.

    De vault moet mee, want de export weigert een bestaande notitie te
    overschrijven. Zonder deze lege map zou een notitie uit een
    vorige sectie blijven staan en de volgende sectie een oude
    notitie teruglezen in plaats van de verse export.
    """
        mem.clear_memory()
        store.reset_cache()
        shutil.rmtree(vault, ignore_errors=True)
        os.makedirs(vault, exist_ok=True)

    def export_all():
        """Exporteert alle memories naar de tijdelijke vault."""
        state = vx.start_export(dry_run=False)
        if state.get('paused'):
            state = vx.resolve_paused_export(state, True)
        return state

    def frontmatter(content):
        return content.split('---')[1]

    def schrijf_notitie(naam, fm, body):
        pad = ob.resolve_note_path(naam)
        os.makedirs(os.path.dirname(pad), exist_ok=True)
        with open(pad, 'w', encoding='utf-8') as f:
            f.write('---\n' + fm + '---\n\n# ' + naam.split('/')[-1][:-3] + '\n\n> ' + body + '\n\n## Details\n\n')
        return naam

    def bewerk_notitie(naam, oud, nieuw):
        """
    Vervangt tekst in een notitie, ongeacht de regeleindes.

    Notities worden op Windows met CRLF weggeschreven, dus een
    handmatige bewerking moet beide varianten proberen. Anders lijkt
    het alsof de bewerking is gelukt terwijl er niets is veranderd.
    """
        pad = ob.resolve_note_path(naam)
        with open(pad, 'r', encoding='utf-8', newline='') as f:
            inhoud = f.read()
        if oud in inhoud:
            inhoud = inhoud.replace(oud, nieuw)
        else:
            inhoud = inhoud.replace(oud.replace('\n', '\r\n'), nieuw.replace('\n', '\r\n'))
        with open(pad, 'w', encoding='utf-8', newline='') as f:
            f.write(inhoud)
        return inhoud
    print('\n===== 1: CREATED =====\n')
    reset()
    mem.remember('fav_kleur', 'blauw', category='voorkeuren')
    entry = mem.get_entry('fav_kleur', 'voorkeuren')
    assert bool(entry.get('created')), 'een nieuwe memory krijgt created'
    assert isinstance(entry.get('created'), str), 'created is een string'
    assert mem._parse_timestamp(entry['created']) is not None and ('+' in entry['created'] or entry['created'].endswith('Z')), 'created is ISO 8601 met tijdzone'
    assert bool(entry.get('updated')), 'een nieuwe memory krijgt updated'
    assert entry['created'] == entry['updated'], 'created en updated zijn bij aanmaak gelijk'
    created_1 = entry['created']
    assert 'created' in mem.ENTRY_META_KEYS, 'created valt binnen ENTRY_META_KEYS'
    mem.update_memory('fav_kleur', 'groen', category='voorkeuren')
    entry = mem.get_entry('fav_kleur', 'voorkeuren')
    assert entry['created'] == created_1, 'created blijft behouden bij update'
    assert mem._parse_timestamp(entry['updated']) is not None, 'updated is een leesbaar ISO 8601-tijdstip'
    assert mem.recall('fav_kleur') == 'groen', 'de waarde is wel gewijzigd'
    assert mem._parse_timestamp(entry['updated']) >= mem._parse_timestamp(created_1), 'updated staat niet vóór created (geen tijdmachine)'
    mem.remember('fav_kleur', 'zwart', category='voorkeuren')
    assert mem.get_entry('fav_kleur', 'voorkeuren')['created'] == created_1, 'created blijft ook bij remember() behouden'
    mem.remember('pc', 'werkplek', category='algemeen')
    mem.add_related('fav_kleur', 'pc')
    mem.update_memory('fav_kleur', 'wit', category='voorkeuren')
    assert mem.get_related('fav_kleur') == ['pc'], 'een waardewijziging maakt de relaties niet kapot'
    assert mem.get_related('pc') == ['fav_kleur'], 'de andere kant van die relatie ook'
    reset()
    store.write(path, {'voorkeuren': {'oud_feit': 'blauw'}, 'pc': {'oud_fact': {'value': 'rtx', 'source': 'conversation', 'updated': '2026-01-02T03:04:05'}}, 'projecten': {}, 'muziek': {}, 'algemeen': {}, 'apparaten': {}})
    store.reset_cache()
    oud = mem.get_entry('oud_fact', 'pc')
    assert mem.recall('oud_fact') == 'rtx', 'een oude memory blijft leesbaar'
    assert oud.get('created') is None, 'een oude memory krijgt GEEN verzonnen created'
    assert oud.get('related') == [], 'een oude memory krijgt GEEN verzonnen related'
    assert oud.get('updated') == '2026-01-02T03:04:05', 'de oude updated blijft ongemoeid'
    assert mem._age_days('2026-01-02T03:04:05') is not None, 'het oude naieve tijdstip blijft leesbaar'
    assert mem._age_days(entry['updated']) is not None, 'het nieuwe formaat is ook leesbaar'
    assert mem._age_days('gisteren') is None, 'een onleesbaar tijdstip geeft None, geen crash'
    reset()
    mem.remember('vergeten_fact', 'iets', category='algemeen')
    assert mem.recall('vergeten_fact') == 'iets', 'de memory bestaat'
    mem.forget('vergeten_fact')
    assert mem.get_entry('vergeten_fact', 'algemeen') is None, 'forget verwijdert de hele entry, metadata inbegrepen'
    assert 'created' not in json.dumps(mem.load_memory(), ensure_ascii=False), 'forget laat geen created-ophoping achter'
    print('\n===== 2: METADATA-CONTRACT =====\n')
    assert len(mem.ENTRY_META_KEYS) > 0, 'ENTRY_META_KEYS is niet leeg'
    assert 'value' in mem.ENTRY_META_KEYS, 'value is onderdeel van het contract'
    assert 'category' not in mem.ENTRY_META_KEYS, 'category staat NIET in de entry (leeft in de map)'
    for veld in ('created', 'updated', 'priority', 'usage_count', 'related'):
        assert veld in mem.ENTRY_META_KEYS, f'{veld} is onderdeel van het contract'
    assert set(mem.ENTRY_META_KEYS) == set(mem.ENTRY_META_DEFAULTS) | {'value'}, 'elk contractveld heeft een default'
    assert mem.is_entry_meta({'value': 1}) is not None, 'ENTRY_META_KEYS wordt ook echt gebruikt'
    assert mem._normalize_entry({})['priority'] == 1.0, 'ENTRY_META_DEFAULTS wordt ook echt gebruikt'
    reset()
    mem.remember('contract', 'waarde', category='algemeen')
    meta = mem.is_entry_meta(mem.get_entry('contract', 'algemeen'))
    assert set(meta) == set(mem.ENTRY_META_KEYS), 'is_entry_meta geeft alle velden terug'
    assert 'category' not in meta, 'is_entry_meta geeft geen Category terug'
    before = json.dumps(mem.load_memory(), ensure_ascii=False, sort_keys=True)
    meta['priority'] = 99.0
    meta['related'].append('hacked')
    assert json.dumps(mem.load_memory(), ensure_ascii=False, sort_keys=True) == before, 'is_entry_meta geeft een kopie, geen referentie'
    assert mem.is_entry_meta('warm') is None, 'is_entry_meta geeft None voor een kale waarde'
    assert mem.is_entry_meta(None) is None, 'is_entry_meta geeft None voor None'
    reset()
    mem.remember('handmatig', 'x', category='algemeen')
    store.write(path, {'voorkeuren': {}, 'pc': {}, 'projecten': {}, 'muziek': {}, 'algemeen': {'raar': {'value': 'x', 'related': 42, 'created': 12345, 'usage_count': 'twee'}}, 'apparaten': {}})
    store.reset_cache()
    raar = mem.get_entry('raar', 'algemeen')
    assert raar['related'] == [], 'een onbruikbare related wordt een lege lijst'
    assert mem._clean_related('mijn_band') == ['mijn_band'], 'een losse string als related wordt één relatie'
    assert raar['created'] == 12345, 'een onbruikbare created blijft ongewijzigd (geen gok)'
    print('\n===== 3: RELATIES =====\n')
    reset()
    mem.remember('fav_game', 'Valorant', category='voorkeuren')
    mem.remember('gaming_pc', 'rtx5090', category='pc')
    mem.remember('monitor', '144hz', category='pc')
    uit = mem.add_related('fav_game', 'gaming_pc')
    assert uit['added'] is True, 'add_related slaat de relatie op'
    assert mem.get_related('fav_game') == ['gaming_pc'], 'A -> B'
    assert mem.get_related('gaming_pc') == ['fav_game'], 'B -> A'
    assert mem.has_related('fav_game', 'gaming_pc'), 'has_related is waar vanuit A'
    assert mem.has_related('gaming_pc', 'fav_game'), 'has_related is waar vanuit B'
    assert mem.has_related('fav_game', 'monitor') is False, 'has_related is onwaar voor een vreemde sleutel'
    mem.add_related('fav_game', 'gaming_pc')
    assert mem.get_related('fav_game') == ['gaming_pc'], 'een dubbele relatie wordt niet dubbel opgeslagen'
    assert mem.add_related('gaming_pc', 'fav_game')['added'] and mem.get_related('gaming_pc') == ['fav_game'], 'een dubbele add vanaf de andere kant ook niet'
    mem.add_related('fav_game', 'Gaming PC')
    assert mem.get_related('fav_game') == ['gaming_pc'], 'een spellingvariant telt als dezelfde relatie'
    uit = mem.add_related('fav_game', 'fav_game')
    assert uit['added'] is False, 'een zelfrelatie wordt geweigerd'
    assert bool(uit['skipped']), 'de zelfrelatie wordt gemeld'
    assert 'fav_game' not in mem.get_related('fav_game'), 'er komt geen zelfrelatie in de lijst'
    assert mem.add_related('fav_game', 'Fav Game')['added'] is False, 'ook genormaliseerd is een zelfrelatie een zelfrelatie'
    mem.clear_related('fav_game')
    uit = mem.add_related('fav_game', 'bestaat_niet')
    assert uit['added'] is False, 'een relatie naar een onbekende sleutel wordt niet opgeslagen'
    assert bool(uit['skipped']), 'de reden wordt gemeld'
    assert mem.get_related('fav_game') == [], 'er komt niets in de lijst'
    uit = mem.add_related('bestaat_niet', 'gaming_pc')
    assert uit['added'] is False, 'een onbekende vertrek sleutel wordt geweigerd'
    assert mem.get_related('gaming_pc') == [], 'de bestaande memory blijft onaangeroerd'
    assert mem.forget('monitor') and mem.get_related('fav_game') == [], 'een relatie naar een verwijderd feit verdwijnt na forget()'
    reset()
    mem.remember('muziek_a', 'coldplay', category='muziek')
    mem.remember('muziek_b', 'radiohead', category='muziek')
    assert mem.get_related('muziek_a') == [], 'twee memories in dezelfde categorie zijn geen relaties'
    assert mem.get_related('muziek_b') == [], 'ook niet andersom'
    plannen = ob.plan_all_memories_to_vault(mem.load_memory())
    content = [p['content'] for p in plannen if p['ok']]
    assert not any(('## Gerelateerd' in c for c in content)), 'de sibling-graaf staat niet meer in de notities'
    assert not any(('related:' in frontmatter(c) for c in content)), 'er staat geen related: in de frontmatter'
    reset()
    mem.remember('fav band', 'coldplay', category='muziek')
    mem.remember('mijn band', 'imaginedragons', category='muziek')
    uit = mem.add_related('fav band', 'band')
    assert uit['added'] is False, "add_related gebruikt GEEN fuzzy: 'band' bestaat niet"
    assert 'resolved' not in uit and 'candidates' not in uit, 'add_related raakt resolve_existing_key niet aan'
    uit = mem.add_related('fav band', 'mijn band')
    assert uit['added'] is True, 'een echte, maar niet-identieke sleutel mag wél'
    assert mem.get_related('fav band') == ['mijn band'], 'de relatie wijst naar de opgeslagen sleutel'
    mem.forget('band')
    assert mem.recall('fav band') == 'coldplay', "forget gebruikt geen fuzzy: 'fav band' blijft"
    assert mem.recall('mijn band') == 'imaginedragons', "forget gebruikt geen fuzzy: 'mijn band' blijft"
    mem.remove_related('fav band', 'mijn band')
    assert mem.get_related('fav band') == [], 'remove_related haalt A -> B weg'
    assert mem.get_related('mijn band') == [], 'remove_related haalt B -> A weg'
    uit = mem.remove_related('fav band', 'mijn band')
    assert uit['removed'] is False, 'een tweede remove geeft removed=False'
    assert uit['key'] == 'fav band' and uit['related'] == 'mijn band', 'een tweede remove crasht niet'
    uit = mem.remove_related('fav band', 'bestaat_niet')
    assert uit['removed'] is False, 'remove van een onbekende sleutel crasht niet'
    assert mem.recall('fav band') == 'coldplay', 'en verandert niets'
    mem.add_related('fav band', 'mijn band')
    assert mem.clear_related('fav band'), 'clear_related leegt de ene kant'
    assert mem.get_related('mijn band') == [], 'de andere kant is ook leeg'
    assert mem.recall('fav band') == 'coldplay' and mem.recall('mijn band') == 'imaginedragons', 'de memories zelf blijven bestaan'
    assert mem.clear_related('mijn band') is False, 'clear_related op een sleutel zonder relaties doet niets'
    print('\n===== 4: FORGET EN RELATIES =====\n')
    reset()
    mem.remember('A', '1', category='algemeen')
    mem.remember('B', '2', category='algemeen')
    mem.remember('C', '3', category='algemeen')
    mem.add_related('A', 'B')
    mem.add_related('A', 'C')
    assert sorted(mem.get_related('A')) == ['B', 'C'], 'A -> [B, C]'
    mem.forget('A')
    assert mem.recall('A') is None, 'A is verwijderd'
    assert mem.get_related('B') == [], 'B heeft geen dode relatie meer'
    assert mem.get_related('C') == [], 'C heeft geen dode relatie meer'
    assert mem.recall('B') == '2' and mem.recall('C') == '3', 'B en C bestaan nog'
    assert 'A' not in json.dumps(mem.load_memory(), ensure_ascii=False), 'er staat nergens meer een verwijzing naar A'
    on_disk = json.loads(open(path, encoding='utf-8').read())
    assert all(('A' not in entry.get('related', []) for categorie in on_disk.values() if isinstance(categorie, dict) for entry in categorie.values() if isinstance(entry, dict))), 'de weggehaalde relatie staat ook echt niet meer op schijf'
    print('\n===== 5: OBSIDIAN EXPORT =====\n')
    reset()
    mem.remember('fav_game', 'Valorant', category='voorkeuren')
    mem.remember('gaming_pc', 'rtx5090', category='pc')
    mem.remember('monitor', '144hz', category='pc')
    mem.add_related('fav_game', 'gaming_pc')
    mem.add_related('fav_game', 'monitor')
    mem.touch_usage('fav_game')
    note = ob.memory_to_note(mem.get_entry('fav_game', 'voorkeuren'), key='fav_game', category='voorkeuren')
    fm = frontmatter(note['content'])
    assert 'created:' in fm, 'created wordt geëxporteerd'
    assert 'updated:' in fm, 'updated wordt geëxporteerd'
    assert 'priority:' in fm, 'priority wordt geëxporteerd'
    assert 'usage_count:' in fm, 'usage_count wordt geëxporteerd'
    assert '\nrelated:' in fm, 'related wordt geëxporteerd'
    assert '\n  - gaming_pc\n' in fm and '\n  - monitor\n' in fm, 'related is een YAML-lijst, geen tekst'
    assert 'memory_key: fav_game' in fm, 'memory_key blijft in de frontmatter'
    assert 'value_type: str' in fm, 'value_type blijft in de frontmatter'
    assert '> Valorant' in note['content'], 'de leesbare body blijft behouden'
    assert '- Aangemaakt: ' in note['content'], 'de detailslijst toont created'
    assert '[[gaming_pc]]' in note['content'] and '[[monitor]]' in note['content'], 'de body toont de wiki-links van de echte relaties'
    assert '[[pc]]' not in note['content'], 'een sibling staat NIET in de wiki-links'
    mem.remember('los_fact', 'geen relaties', category='algemeen')
    note_los = ob.memory_to_note(mem.get_entry('los_fact', 'algemeen'), key='los_fact', category='algemeen')
    assert 'related:' not in frontmatter(note_los['content']), 'een memory zonder relaties krijgt geen related:'
    assert 'related: []' not in frontmatter(note_los['content']), 'een memory zonder relaties krijgt geen lege lijst'
    assert '## Gerelateerd' not in note_los['content'], 'een memory zonder relaties krijgt geen wiki-links'
    state = export_all()
    assert vx.export_is_finished(state), 'de volledige export slaagt'
    notitie = ob.read_note(ob.note_name_for_memory('fav_game', 'voorkeuren'))
    assert '  - gaming_pc' in notitie, 'de notitie op schijf bevat de relaties'
    assert 'created:' in notitie, 'de notitie op schijf bevat created'
    print('\n===== 6: OBSIDIAN IMPORT =====\n')
    reset()
    mem.remember('fav_game', 'Valorant', category='voorkeuren')
    mem.remember('gaming_pc', 'rtx5090', category='pc')
    mem.remember('monitor', '144hz', category='pc')
    mem.add_related('fav_game', 'gaming_pc')
    export_all()
    naam = ob.note_name_for_memory('fav_game', 'voorkeuren')
    terug = vi.note_to_memory(naam)
    assert terug['created'] == mem.get_entry('fav_game', 'voorkeuren')['created'], 'created wordt gelezen'
    assert terug['related'] == ['gaming_pc'], 'related wordt gelezen'
    assert terug['usage_count'] == 0, 'usage_count wordt gelezen'
    uit = vi.import_note(naam, force=True)
    assert uit['action'] == 'unchanged', 'import zonder verschil verandert de waarde niet'
    assert mem.get_related('fav_game') == ['gaming_pc'], 'import zonder verschil verandert de relaties niet'
    assert uit['metadata']['related_added'] == [] and uit['metadata']['related_removed'] == [], 'de import is idempotent (niets te doen)'
    bewerk_notitie(naam, '  - gaming_pc', '  - gaming_pc\n  - monitor')
    uit = vi.import_note(naam, force=True)
    assert 'monitor' in uit['metadata']['related_added'], 'een handmatig toegevoegde relatie wordt verwerkt'
    assert mem.get_related('fav_game') == ['gaming_pc', 'monitor'], 'de nieuwe relatie staat er echt'
    assert mem.get_related('monitor') == ['fav_game'], 'de nieuwe relatie is ook omgekeerd'
    bewerk_notitie(naam, '  - gaming_pc\n', '')
    uit = vi.import_note(naam, force=True)
    assert 'gaming_pc' in uit['metadata']['related_removed'], 'een handmatig weggehaalde relatie wordt verwerkt'
    assert mem.get_related('fav_game') == ['monitor'], 'de relatie is weg bij A'
    assert mem.get_related('gaming_pc') == [], 'de relatie is ook weg bij B'
    bewerk_notitie(naam, '  - monitor', '  - monitor\n  - bestaat_niet')
    vi.import_note(naam, force=True)
    assert mem.get_related('fav_game') == ['monitor'], 'een relatie naar een onbekende sleutel wordt geweigerd'
    assert 'bestaat_niet' not in json.dumps(mem.load_memory(), ensure_ascii=False), 'en komt hij nergens in het geheugen voor'
    reset()
    mem.remember('inline_a', '1', category='algemeen')
    mem.remember('inline_b', '2', category='algemeen')
    schrijf_notitie('algemeen/inline_a.md', 'title: inline_a\ncategory: algemeen\ntags: []\nmemory_key: inline_a\nvalue_type: str\nrelated: ["inline_b", "inline_b", "   "]\ndate: 2026-01-01\n', '1')
    uit = vi.import_note('algemeen/inline_a.md')
    assert mem.get_related('inline_a') == ['inline_b'], 'een inline lijst wordt gelezen'
    assert mem.get_related('inline_b') == ['inline_a'], 'een inline lijst heeft geen duplicaten'
    reset()
    mem.remember('oud_fact', 'blauw', category='algemeen')
    oud = vi.note_to_memory(schrijf_notitie('algemeen/oud_fact.md', 'title: oud_fact\ncategory: algemeen\ntags: []\nmemory_key: oud_fact\ndate: 2026-01-01\n', 'blauw'))
    assert oud is not None and oud['value'] == 'blauw', 'een oude notitie zonder created blijft importeerbaar'
    assert oud is not None and oud['related'] == [], 'een oude notitie zonder related blijft importeerbaar'
    uit = vi.import_note('algemeen/oud_fact.md', force=True)
    assert uit['action'] in ('unchanged', 'conflict', 'new'), 'een oude notitie is nog steeds bruikbaar'
    assert uit['applied'] is False, 'een oude notitie verandert niets stuk'
    assert vi.note_to_memory(schrijf_notitie('welkom.md', 'title: welkom\ntags: []\n', 'hi')) is None, 'een notitie zonder memory_key wordt overgeslagen'
    print('\n===== 7: IDEMPOTENTIE =====\n')
    reset()
    mem.remember('fav_game', 'Valorant', category='voorkeuren')
    mem.remember('gaming_pc', 'rtx5090', category='pc')
    mem.remember('monitor', '144hz', category='pc')
    mem.add_related('fav_game', 'gaming_pc')
    mem.add_related('fav_game', 'monitor')
    mem.remember('vlag_getal', 42, category='algemeen')
    mem.remember('vlag_ja', True, category='algemeen')
    mem.remember('vlag_lijst', ['a', 'b'], category='algemeen')
    export_all()
    eerste = {}
    for note in ob.list_notes(''):
        eerste[note] = ob.read_note(note)
    geheugen_eerste = mem.load_memory()
    export_all()
    tweede = {note: ob.read_note(note) for note in ob.list_notes('')}
    assert eerste == tweede, 'export -> export verandert niets'
    assert json.dumps(mem.load_memory(), ensure_ascii=False, sort_keys=True) == json.dumps(geheugen_eerste, ensure_ascii=False, sort_keys=True), 'memory.json blijft byte-voor-byte gelijk'
    for note in ob.list_notes(''):
        vi.import_note(note, force=True)
    export_all()
    derde = {note: ob.read_note(note) for note in ob.list_notes('')}
    assert eerste == derde, 'memory -> export -> import -> export is identiek'
    assert mem.get_related('fav_game') == ['gaming_pc', 'monitor'], 'de relaties zijn onveranderd'
    assert mem.get_entry('fav_game', 'voorkeuren')['created'] == geheugen_eerste['voorkeuren']['fav_game']['created'], 'de created is onveranderd'
    assert mem.recall('vlag_getal') == 42 and type(mem.recall('vlag_getal')) is int, 'het type is behouden (int)'
    assert mem.recall('vlag_ja') is True, 'het type is behouden (bool)'
    assert mem.recall('vlag_lijst') == ['a', 'b'], 'het type is behouden (list)'
    assert mem.get_entry('fav_game', 'voorkeuren')['created'] == geheugen_eerste['voorkeuren']['fav_game']['created'], 'de created van de eerste memory is dezelfde blijft'
    print('\n===== 8: CONFLICTEN =====\n')
    reset()
    mem.remember('fav_game', 'Valorant', category='voorkeuren')
    mem.remember('gaming_pc', 'rtx5090', category='pc')
    mem.add_related('fav_game', 'gaming_pc')
    created_voor = mem.get_entry('fav_game', 'voorkeuren')['created']
    export_all()
    naam = ob.note_name_for_memory('fav_game', 'voorkeuren')
    inhoud = ob.read_note(naam)
    bewerkt = inhoud.replace('> Valorant', '> Apex')
    bewerkt = bewerkt.replace('  - gaming_pc', '  - gaming_pc\n  - monitor')
    mem.remember('monitor', '144hz', category='pc')
    bewerk_notitie(naam, '> Valorant', '> Apex')
    bewerk_notitie(naam, '  - gaming_pc', '  - gaming_pc\n  - monitor')
    uit = vi.import_note(naam)
    assert uit['action'] == 'conflict' and uit['needs_confirm'] is True, 'een gewijzigde waarde geeft een waardeconflict'
    assert mem.recall('fav_game') == 'Valorant', 'bij een conflict wordt de waarde NIET overschreven'
    assert uit['metadata'] == {}, 'bij een conflict verandert er GEEN metadata'
    assert mem.get_related('fav_game') == ['gaming_pc'], 'de relations blijven zoals ze waren'
    assert 'monitor' not in mem.get_related('fav_game'), 'de nieuwe relatie uit de notitie is NIET toegepast'
    vi.resolve_pending(uit['confirm_token'], keep_old=False)
    assert mem.recall('fav_game') == 'Apex', 'na bevestigen is de waarde bijgewerkt'
    assert sorted(mem.get_related('fav_game')) == ['gaming_pc', 'monitor'], 'na bevestigen is de metadata wél bijgewerkt'
    assert mem.get_related('monitor') == ['fav_game'], 'de andere kant van de nieuwe relatie ook'
    assert mem.get_entry('fav_game', 'voorkeuren')['created'] == created_voor, 'created is door de waardewijziging niet gewijzigd'
    assert mem.get_entry('fav_game', 'voorkeuren')['updated'] is not None, 'updated is door de waardewijziging wel gewijzigd'
    reset()
    mem.remember('tel_fact', 'x', category='algemeen')
    mem.reset_touch_usage()
    mem.touch_usage('tel_fact')
    export_all()
    naam = ob.note_name_for_memory('tel_fact', 'algemeen')
    bewerk_notitie(naam, 'usage_count: 1', 'usage_count: 0')
    vi.import_note(naam, force=True)
    assert mem.get_entry('tel_fact', 'algemeen')['usage_count'] == 1, 'een import kan usage_count nooit verkleinen'
    bewerk_notitie(naam, 'usage_count: 0', 'usage_count: 9')
    vi.import_note(naam, force=True)
    assert mem.get_entry('tel_fact', 'algemeen')['usage_count'] == 9, 'een hogere usage_count uit de notitie wordt wel overgenomen'
    print('\n===== 9: METADATA BEHOUD =====\n')
    _klok = {'t': 0}
    _echte_now = mem._now

    def klok():
        """Elke _now() geeft een nieuw, oplopend tijdstip."""
        _klok['t'] += 1
        seconden = _klok['t']
        return '2026-06-01T%02d:%02d:%02d+02:00' % (12 + seconden // 3600, seconden // 60 % 60, seconden % 60)
    mem._now = klok
    reset()
    mem.remember('meta_fact', 'waarde', category='algemeen')
    nieuw = mem.get_entry('meta_fact', 'algemeen')
    assert nieuw['usage_count'] == 0, '1: nieuwe memory heeft usage_count 0'
    assert nieuw['last_used'] is None, '1: nieuwe memory heeft last_used None'
    assert nieuw['related'] == [], '1: nieuwe memory heeft related []'
    assert nieuw['created'] is not None, '1: nieuwe memory heeft een created'
    assert nieuw['created'] is not None and nieuw['updated'] is not None, '1: nieuwe memory heeft created en updated'
    assert nieuw['created'].endswith('+02:00') and nieuw['updated'].endswith('+02:00'), '1: created en updated zijn ISO 8601 met tijdzone'
    assert nieuw['priority'] == 1.0, '1: nieuwe memory heeft de neutrale priority 1.0'
    assert nieuw['conflict'] is False, '1: nieuwe memory is geen conflict'
    created = nieuw['created']
    mem.remember('meta_fact', 'waarde', category='algemeen', priority=8.0)
    mem.remember('meta_peer', 'ander feit', category='algemeen')
    mem.add_related('meta_fact', 'meta_peer')
    voor_touch = json.loads(json.dumps(mem.get_entry('meta_fact', 'algemeen')))
    mem.reset_touch_usage()
    assert mem.touch_usage('meta_fact') is True, '2: touch_usage telt de eerste keer'
    mem.reset_touch_usage()
    mem.touch_usage('meta_fact')
    gebruikt = mem.get_entry('meta_fact', 'algemeen')
    assert gebruikt['usage_count'] == 2, '2: touch_usage verhoogt usage_count'
    last_used = gebruikt['last_used']
    assert last_used is not None, '2: touch_usage zet last_used'
    assert gebruikt['created'] == created, '2: touch_usage laat created staan'
    assert gebruikt['updated'] == voor_touch['updated'], '2: touch_usage laat updated staan'
    updated_voor = gebruikt['updated']
    voor = json.loads(json.dumps(gebruikt))
    mem.update_memory('meta_fact', 'nieuwe waarde', category='algemeen')
    na = mem.get_entry('meta_fact', 'algemeen')
    assert na['usage_count'] == voor['usage_count'] == 2, '3: usage_count blijft behouden'
    assert na['last_used'] == voor['last_used'], '4: last_used blijft behouden'
    assert na['created'] == voor['created'] == created, '5: created blijft behouden'
    assert na['related'] == voor['related'] == ['meta_peer'], '6: related blijft behouden'
    assert na['priority'] == voor['priority'] == 8.0, '7: priority blijft behouden'
    assert na['updated'] != updated_voor, '8: updated verandert wel'
    assert na['value'] == 'nieuwe waarde', '8: de waarde is wel bijgewerkt'
    assert na['previous_value'] == 'waarde', 'de oude waarde staat in previous_value'
    assert na['corrected'] is True, 'de correctie is gemarkeerd'
    assert mem.get_related('meta_peer') == ['meta_fact'], 'de relatie is nog steeds tweerichting'
    mem.reset_touch_usage()
    mem.touch_usage('meta_fact')
    voor = json.loads(json.dumps(mem.get_entry('meta_fact', 'algemeen')))
    mem.remember('meta_fact', 'nieuwe waarde', category='algemeen')
    gelijk = mem.get_entry('meta_fact', 'algemeen')
    assert gelijk['usage_count'] == voor['usage_count'], 'een gelijkwaardige onthouder behoudt usage_count'
    assert gelijk['last_used'] == voor['last_used'], 'een gelijkwaardige onthouder behoudt last_used'
    assert gelijk['created'] == voor['created'], 'een gelijkwaardige onthouder behoudt created'
    assert gelijk['related'] == voor['related'], 'een gelijkwaardige onthouder behoudt related'
    assert gelijk['priority'] == voor['priority'], 'een gelijkwaardige onthouder behoudt priority'
    assert gelijk['previous_value'] == voor['previous_value'], 'een gelijkwaardige onthouder behoudt previous_value'
    mem.reset_touch_usage()
    mem.touch_usage('meta_fact')
    voor_conflict = json.dumps(mem.get_entry('meta_fact', 'algemeen'), sort_keys=True)
    updated_voor_conflict = mem.get_entry('meta_fact', 'algemeen')['updated']
    voor_conflict_entry = json.loads(voor_conflict)
    uit = mem.remember('meta_fact', 'ongemapde waarde', category='algemeen')
    assert uit.get('needs_confirm') is True, 'een onbevestigd conflict vraagt eerst om bevestiging'
    assert json.dumps(mem.get_entry('meta_fact', 'algemeen'), sort_keys=True) == voor_conflict, 'een onbevestigd conflict wijzigt de entry niet'
    mem.resolve_conflict('meta_fact', 'geel', category='algemeen')
    na_conflict = mem.get_entry('meta_fact', 'algemeen')
    assert na_conflict['usage_count'] == voor_conflict_entry['usage_count'], 'resolve_conflict: usage_count blijft behouden'
    assert na_conflict['last_used'] == voor_conflict_entry['last_used'], 'resolve_conflict: last_used blijft behouden'
    assert na_conflict['created'] == created, 'resolve_conflict: created blijft behouden'
    assert na_conflict['related'] == voor_conflict_entry['related'], 'resolve_conflict: related blijft behouden'
    assert na_conflict['priority'] == 8.0, 'resolve_conflict: priority blijft behouden'
    assert na_conflict['updated'] != updated_voor_conflict, 'resolve_conflict: updated verandert wel'
    assert na_conflict['value'] == 'geel', 'resolve_conflict: de nieuwe waarde is actueel'
    assert na_conflict['previous_value'] == 'nieuwe waarde', 'resolve_conflict: de oude waarde staat in previous_value'
    assert na_conflict['conflict'] is False, 'resolve_conflict: een opgeslagen waarde is geen conflict'
    assert na_conflict['corrected'] is True, 'resolve_conflict: de correctie is gemarkeerd'
    mem.reset_touch_usage()
    mem.touch_usage('meta_fact')
    voor_keep_old = mem.get_entry('meta_fact', 'algemeen')
    mem.resolve_conflict('meta_fact', 'oranje', keep_old=True, category='algemeen')
    keep_old = mem.get_entry('meta_fact', 'algemeen')
    assert keep_old['value'] == voor_keep_old['value'], 'resolve_conflict(keep_old): de waarde blijft staan'
    assert keep_old['usage_count'] == voor_keep_old['usage_count'], 'resolve_conflict(keep_old): usage_count blijft behouden'
    assert keep_old['last_used'] == voor_keep_old['last_used'], 'resolve_conflict(keep_old): last_used blijft behouden'
    assert keep_old['created'] == voor_keep_old['created'], 'resolve_conflict(keep_old): created blijft behouden'
    assert keep_old['updated'] == voor_keep_old['updated'], 'resolve_conflict(keep_old): updated blijft ongemoeid'
    assert keep_old['related'] == ['meta_peer'], 'resolve_conflict(keep_old): related blijft behouden'
    assert keep_old['conflict'] is True, 'resolve_conflict(keep_old): het conflict staat vast'
    assert keep_old['conflict_rejected_value'] == 'oranje', 'resolve_conflict(keep_old): de afgewezen waarde is vastgelegd'
    mem._now = _echte_now
    print('\n===== 10: IDENTITEIT VAN remember() =====\n')
    reset()
    mem.remember('fav band', 'queen', category='muziek')
    mem.reset_touch_usage()
    mem.touch_usage('fav band')
    mem.remember('fav-band', 'abba', category='muziek')
    muziek = mem.load_memory()['muziek']
    assert list(muziek.keys()) == ['fav band'], 'een koppelteken-variant maakt geen tweede entry'
    assert muziek['fav band']['value'] == 'queen', 'een onbevestigde variant wijzigt de waarde niet'
    mem.update_memory('fav-band', 'abba', category='muziek')
    muziek = mem.load_memory()['muziek']
    assert list(muziek.keys()) == ['fav band'], 'de bevestigde variant werkt dezelfde entry bij'
    assert muziek['fav band']['value'] == 'abba', 'en de waarde is bijgewerkt'
    assert muziek['fav band']['usage_count'] == 1, 'usage_count gaat niet verloren bij de variant'
    assert muziek['fav band']['created'] is not None, 'created gaat niet verloren bij de variant'
    assert mem.recall('fav band') == 'abba', 'recall geeft de nieuwe waarde'
    assert mem.forget('fav-band') and mem.find_entry('fav band') == (None, None), 'forget haalt de genormaliseerde variant weg'
    reset()
    mem.remember('mijn_favoriet', 'blauw', category='voorkeuren')
    mem.reset_touch_usage()
    mem.touch_usage('mijn_favoriet')
    mem.update_memory('mijn_favoriet', 'muziek', category='voorkeuren')
    al = mem.load_memory()
    assert sum((len(items) for items in al.values())) == 1, 'een waarde uit een andere categorie maakt geen tweede entry'
    assert mem.find_entry('mijn_favoriet')[0] == 'voorkeuren', 'het feit blijft in zijn eigen categorie'
    assert mem.get_entry('mijn_favoriet')['usage_count'] == 1, 'en houdt daar zijn metadata'
    assert mem.recall('mijn_favoriet') == 'muziek', 'met de nieuwe waarde erin'
    mem.update_memory('mijn_favoriet', 'groen', category='apparaten')
    al = mem.load_memory()
    assert sum((len(items) for items in al.values())) == 1, 'een expliciet andere categorie maakt geen tweede entry'
    assert mem.find_entry('mijn_favoriet')[0] == 'voorkeuren', 'het feit is in zijn oorspronkelijke categorie bijgewerkt'
    mem.forget('mijn_favoriet')
    assert sum((len(items) for items in mem.load_memory().values())) == 0, 'forget haalt het feit echt weg'
    mem.MEMORY_FILE = _echte_mem
    ob.set_vault_path(_echte_vault)
    store.reset_cache()
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'=' * 60}")
    print(f"{'=' * 60}")
