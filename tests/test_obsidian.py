import sys
import os
import io
import ast
import shutil
import tempfile
from unittest.mock import patch
from memory import obsidian as ob
from memory import memory as mem
from memory import vault_import as vi

def test_main():
    """
JARVIS — Obsidian-laag tests (Fase 14, Obsidian Stap 1)
======================================================

Test memory/obsidian.py met een TIJDELIJKE test-vault:

  1. vault vinden en instellen
  2. controleren of de vault bestaat
  3. Markdown-notities schrijven
  4. teruglezen en inhoud controleren
  5. bijwerken en toevoegen (append)
  6. veilige bestandsnamen en paden
  7. ontbrekende vault
  8. ongeldige en niet-bestaande bestanden
  9. los van memory.json (geen import, geen migratie, geen auto-save)

Alle tests draaien op een tijdelijke map. De echte vault wordt alleen
LEZEN (Welkom.md opvragen), de echte memory/memory.json wordt helemaal
niet aangeraakt.
"""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)

    def raises_obsidian_error(label, fn, *args, **kwargs):
        """ok() variant: de aanroep moet ObsidianError gooien."""
        try:
            fn(*args, **kwargs)
        except ob.ObsidianError:
            assert True, label
        except Exception as exc:
            assert False, f'{label} (maar gooide {type(exc).__name__})'
        else:
            assert False, f'{label} (maar gooide niets)'

    def read_bytes(path):
        try:
            with open(path, 'rb') as file:
                return file.read()
        except OSError:
            return None
    work = tempfile.mkdtemp(prefix='jarvis_obsidian_test_')
    vault = os.path.join(work, 'Mijn Vault')
    vault2 = os.path.join(work, 'Vault Stap 2')
    vault3 = os.path.join(work, 'Vault Stap 3')
    mem3_file = os.path.join(work, 'geheugen_stap3.json')
    os.makedirs(vault)
    os.makedirs(vault2)
    os.makedirs(vault3)
    memory_json = os.path.join(ROOT, 'memory', 'memory.json')
    _memory_before = read_bytes(memory_json)
    _memory_existed = os.path.exists(memory_json)
    ob.reset_vault_path()
    ob.set_vault_path(vault)
    print('\n--- 1. vault vinden en instellen ---')
    assert ob.DEFAULT_VAULT_PATH == os.path.join(ROOT, 'JARVIS Memory'), "standaard-vault is de map 'JARVIS Memory' naast het project"
    assert ob.get_vault_path() == os.path.abspath(vault), 'set_vault_path geeft het absolute pad terug'
    assert ob.set_vault_path('.') == os.path.abspath('.'), 'set_vault_path maakt een relatief pad absoluut'
    ob.set_vault_path(vault)
    assert ob.get_vault_path() == os.path.abspath(vault), 'pad opnieuw instellen werkt'
    assert ob.reset_vault_path() == ob.DEFAULT_VAULT_PATH, 'reset_vault_path valt terug op de standaard'
    assert ob.get_vault_path() == ob.DEFAULT_VAULT_PATH, 'reset raakt de ingestelde waarde kwijt'
    ob.set_vault_path(vault)
    raises_obsidian_error('leeg vault-pad geweigerd', ob.set_vault_path, '   ')
    raises_obsidian_error('leeg vault-pad (None) geweigerd', ob.set_vault_path, '')
    raises_obsidian_error('niet-tekst vault-pad geweigerd', ob.set_vault_path, 12345)
    ob.reset_vault_path()
    _saved_env = os.environ.get(ob.ENV_VAULT_VAR)
    os.environ[ob.ENV_VAULT_VAR] = vault
    assert ob.get_vault_path() == os.path.abspath(vault), 'env-var JARVIS_OBSIDIAN_VAULT wordt gebruikt'
    ob.set_vault_path(vault)
    assert ob.get_vault_path() == os.path.abspath(vault), 'ingesteld pad wint van de env-var'
    if _saved_env is None:
        os.environ.pop(ob.ENV_VAULT_VAR, None)
    else:
        os.environ[ob.ENV_VAULT_VAR] = _saved_env
    print('\n--- 2. bestaan van de vault ---')
    assert ob.vault_exists(), 'tijdelijke vault bestaat'
    assert not ob.is_obsidian_vault(), 'vault met .obsidian herkend als Obsidian-vault'
    os.makedirs(os.path.join(vault, ob.OBSIDIAN_CONFIG_DIR))
    assert ob.is_obsidian_vault(), '.obsidian aanwezig -> is_obsidian_vault()'
    assert ob.list_notes() == [], '.obsidian overslaan bij notities zoeken'
    ob.set_vault_path(os.path.join(work, 'bestaat niet'))
    assert not ob.vault_exists(), 'ontbrekende vault -> vault_exists() is False'
    assert not ob.is_obsidian_vault(), 'ontbrekende vault -> is_obsidian_vault() is False'
    assert ob.list_notes() == [], 'ontbrekende vault -> notities zoeken geeft []'
    bestand = os.path.join(work, 'geen map.txt')
    with open(bestand, 'w', encoding='utf-8') as file:
        file.write('hallo')
    ob.set_vault_path(bestand)
    assert not ob.vault_exists(), 'pad dat een bestand is -> vault_exists() is False'
    ob.set_vault_path(vault)
    info = ob.describe_vault()
    assert info['path'] == os.path.abspath(vault), 'describe_vault meldt het pad'
    assert info['exists'] is True, 'describe_vault meldt dat de vault bestaat'
    assert info['note_count'] == len(info['notes']), 'describe_vault telt notities'
    print('\n--- 3. markdown schrijven ---')
    assert ob.write_note('welkom', '# Hallo'), 'schrijven van een nieuwe notitie'
    first_path = ob.resolve_note_path('welkom')
    assert os.path.isfile(first_path), 'notitie staat echt op schijf'
    assert first_path.endswith('.md'), 'bestand eindigt op .md'
    assert ob.write_note('voorkeuren/licht', 'Ik hou van warm licht.'), 'submap wordt automatisch gemaakt'
    assert os.path.isdir(os.path.join(vault, 'voorkeuren')), 'submap staat echt op schijf'
    assert ob.write_note('nota', 'zonder extensie'), "'.md' wordt vanzelf toegevoegd"
    assert os.path.isfile(os.path.join(vault, 'nota.md')), 'bestand kreeg alsnog .md'
    assert ob.write_note('nota', 'nieuwe tekst'), 'overschrijven van een bestaande notitie'
    assert ob.read_note('nota') == 'nieuwe tekst', 'overschrijven werkte'
    assert ob.write_note('nota', 'nog een keer', overwrite=False) is False, 'overwrite=False overschrijft niet'
    assert ob.read_note('nota') == 'nieuwe tekst', 'inhoud bleef onveranderd na overwrite=False'
    assert ob.write_note('nota', 'nieuwe tekst', overwrite=True), 'overwrite=True overschrijft wel'
    assert ob.write_note('leeg', ''), 'lege notitie schrijven'
    assert ob.read_note('leeg') == '', 'lege notitie is leeg'
    print('\n--- 4. teruglezen ---')
    INHOUD = '# Voorkeur: licht\n\nIk hou van warm, gedempt licht in de avond.\n\n- temperatuur rond 2700K\n- nooit fel wit overdag\n\nZie ook [[welkom]] en [handleiding](https://help.obsidian.md).\n\nEmoji: 🏡 💡  Tekens: éüñäöü'
    assert ob.write_note('voorkeuren/licht', INHOUD), 'grote notitie met markdown schrijven'
    terug = ob.read_note('voorkeuren/licht')
    assert terug == INHOUD, 'teruggelezen inhoud is identiek'
    assert terug.startswith('# Voorkeur: licht'), 'kop blijft een kop'
    assert 'éüñäöü' in terug, 'accenten overleven de heen-en-weer'
    assert '🏡' in terug and '💡' in terug, 'emoji overleven de heen-en-weer'
    assert '[[welkom]]' in terug, 'wiki-link overleeft'
    assert '\n' in terug, 'nieuwe regels blijven behouden'
    op_schijf = read_bytes(ob.resolve_note_path('voorkeuren/licht'))
    assert op_schijf == INHOUD.encode('utf-8'), 'bestand op schijf is utf-8 met dezelfde inhoud'
    assert b'\r\n' not in op_schijf, 'geen windows CRLF in de notitie'
    assert ob.write_note('voorkeuren/lamp-één', 'speciale naam'), 'niet-standaard bestandsnaam met accenten werkt'
    assert ob.read_note('voorkeuren/lamp-één') == 'speciale naam', 'bestand met accenten teruggelezen'
    assert ob.write_note('mijn notitie', 'met spatie'), 'notitie met spatie in de naam werkt'
    assert ob.read_note('mijn notitie') == 'met spatie', 'spatie-notitie teruggelezen'
    notities = ob.list_notes()
    assert len(notities) == 6, 'notities worden gevonden'
    assert 'voorkeuren/licht.md' in notities, "submap-notitie gevonden met '/' als scheider"
    assert not any((n.startswith('.') for n in notities)), 'verborgen map blijft buiten de lijst'
    assert notities == sorted(notities), 'lijst is gesorteerd'
    assert ob.list_notes('voorkeuren') == ['voorkeuren/lamp-één.md', 'voorkeuren/licht.md'], 'notities zoeken in een submap werkt'
    assert ob.list_notes('bestaat niet') == [], 'zoeken in een ontbrekende submap geeft []'
    assert ob.list_notes('voorkeuren/') == ob.list_notes('voorkeuren'), 'submap met afsluitende slash werkt'
    assert os.path.isdir(os.path.join(vault, 'voorkeuren')), "submap krijgt geen '.md'-extensie"
    ob.write_note('projecten/jarvis/api', 'diepe notitie')
    assert 'projecten/jarvis/api.md' in ob.list_notes(), 'diepe submap-notitie gevonden'
    assert ob.list_notes('projecten/jarvis') == ['projecten/jarvis/api.md'], 'zoeken in een diepe submap werkt'
    assert len(ob.list_notes('projecten')) == 1 and 'projecten/jarvis/api.md' in ob.list_notes(), 'zoeken vanaf de bovenste map ziet alles'
    raises_obsidian_error("submap met '..' geweigerd", ob.list_notes, '../buiten')
    raises_obsidian_error("submap met '.obsidian' geweigerd", ob.list_notes, '.obsidian')
    ob.write_note('met newline', 'regel 1\nregel 2\n')
    assert ob.read_note('met newline') == 'regel 1\nregel 2', 'afsluitende newline wordt weggestreept bij lezen'
    assert ob.note_exists('welkom'), 'notitie bestaan -> note_exists()'
    assert ob.note_exists('voorkeuren/licht'), 'bestaande notitie met submap -> note_exists()'
    print('\n--- 5. bijwerken en toevoegen ---')
    assert ob.append_note('welkom', 'Nieuwe regel'), 'append aan een bestaande notitie'
    assert ob.read_note('welkom') == '# Hallo\n\nNieuwe regel', 'append landt onder de bestaande tekst'
    assert ob.append_note('welkom', 'Derde regel'), 'append nog een keer'
    assert ob.read_note('welkom') == '# Hallo\n\nNieuwe regel\n\nDerde regel', 'meerdere appends blijven gescheiden'
    assert ob.append_note('welkom', 'Direct eronder', separator='\n'), 'eigen scheider te gebruiken'
    assert ob.read_note('welkom').endswith('Derde regel\nDirect eronder'), 'eigen scheider wordt gebruikt'
    assert ob.append_note('vers/nieuw', 'eerste tekst'), 'append maakt een ontbrekende notitie aan'
    assert ob.read_note('vers/nieuw') == 'eerste tekst', 'aangemaakte notitie klopt'
    assert ob.append_note('vers/ontbreekt', 'tekst', create=False) is False, 'append met create=False doet niets bij een ontbrekende notitie'
    assert not os.path.exists(os.path.join(vault, 'vers', 'ontbreekt.md')), 'er is geen bestand aangemaakt'
    assert ob.delete_note('mijn notitie'), 'notitie verwijderen'
    assert not os.path.exists(os.path.join(vault, 'mijn notitie.md')), 'verwijderde notitie is weg'
    assert ob.delete_note('mijn notitie') is False, 'verwijderen van een ontbrekende notitie geeft False'
    assert ob.write_note('reus', 'x' * (ob.MAX_NOTE_BYTES + 10)) is False, 'te grote notitie wordt niet geschreven'
    assert not os.path.exists(os.path.join(vault, 'reus.md')), 'geen rommelbestand achtergebleven'
    print('\n--- 6. veilige paden ---')
    raises_obsidian_error("'..' geweigerd", ob.resolve_note_path, '../geheim')
    raises_obsidian_error("'/..' geweigerd", ob.resolve_note_path, '/../geheim')
    raises_obsidian_error("'..' middenin geweigerd", ob.resolve_note_path, 'voorkeuren/../../geheim')
    raises_obsidian_error("'.' geweigerd", ob.resolve_note_path, '.')
    raises_obsidian_error('absolute pad geweigerd', ob.resolve_note_path, 'C:\\Windows\\System32\\evil.md')
    raises_obsidian_error('schijfletter geweigerd', ob.resolve_note_path, 'C:x.md')
    raises_obsidian_error('UNC-pad geweigerd', ob.resolve_note_path, '\\\\server\\share\\evil.md')
    raises_obsidian_error('pad met begin-slash geweigerd', ob.resolve_note_path, '/etc/passwd.md')
    raises_obsidian_error("'.obsidian' geweigerd", ob.resolve_note_path, '.obsidian/workspace.md')
    raises_obsidian_error('verborgen map geweigerd', ob.resolve_note_path, '.git/config.md')
    raises_obsidian_error('Windows-oordewoord CON geweigerd', ob.resolve_note_path, 'CON.md')
    raises_obsidian_error('Windows-oordewoord lpt1 geweigerd', ob.resolve_note_path, 'map/lpt1.md')
    raises_obsidian_error("verboden teken '<' geweigerd", ob.resolve_note_path, 'a<b.md')
    raises_obsidian_error("verboden teken ':' geweigerd", ob.resolve_note_path, 'a:b.md')
    raises_obsidian_error("verboden teken '*' geweigerd", ob.resolve_note_path, 'a*b.md')
    raises_obsidian_error('lege naam geweigerd', ob.resolve_note_path, '')
    raises_obsidian_error('alleen spaties geweigerd', ob.resolve_note_path, '   ')
    raises_obsidian_error('naam die op een punt eindigt geweigerd', ob.resolve_note_path, 'notitie.')
    raises_obsidian_error('mapnaam die op een punt eindigt geweigerd', ob.resolve_note_path, 'map./notitie')
    raises_obsidian_error('mapnaam die op een spatie eindigt geweigerd', ob.resolve_note_path, 'map /notitie')
    raises_obsidian_error('niet-tekst naam geweigerd', ob.resolve_note_path, 42)
    raises_obsidian_error('None als naam geweigerd', ob.resolve_note_path, None)
    raises_obsidian_error('te lange naam geweigerd', ob.resolve_note_path, 'a' * 300 + '.md')
    assert ob.sanitize_note_name('a..b') == 'a..b.md', "'..' in het midden zonder traversal mag gewoon"
    assert ob.sanitize_note_name('  notitie  ') == 'notitie.md', 'ruimte rondom de hele naam wordt weggestreept'
    assert ob.sanitize_note_name('mijn notitie.md') == 'mijn notitie.md', 'naam met punt erin mag'
    assert ob.sanitize_note_name('voorkeuren/lamp/') == 'voorkeuren/lamp.md', 'achterste slash wordt genegeerd'
    assert ob.sanitize_note_name('voorkeuren\\lamp') == 'voorkeuren/lamp.md', 'backslash telt als map-scheider'
    assert ob.resolve_note_path('voorkeuren/lamp').startswith(os.path.abspath(vault)), 'pad blijft binnen het vault'
    assert all((ob.resolve_note_path(n).startswith(os.path.abspath(vault)) for n in ['welkom', 'voorkeuren/licht', 'nota.md', 'leeg'])), 'geen enkel pad komt buiten het vault'
    raises_obsidian_error("schrijven met '..' geweigerd", ob.write_note, '../geheim', 'inhoud')
    raises_obsidian_error("lezen met '..' geweigerd", ob.read_note, '../geheim')
    raises_obsidian_error("notitie_exists met '..' geweigerd", ob.note_exists, '../geheim')
    raises_obsidian_error("verwijderen met '..' geweigerd", ob.delete_note, '../geheim')
    raises_obsidian_error('niet-tekst inhoud geweigerd', ob.write_note, 'welkom', 12345)
    assert not os.path.exists(os.path.join(work, 'geheim.md')), 'er is niets buiten het vault aangemaakt'
    print('\n--- 7. ontbrekende vault ---')
    ob.set_vault_path(os.path.join(work, 'bestaat niet'))
    missing = ob.get_vault_path()
    assert ob.write_note('iets', 'inhoud') is False, 'schrijven naar een ontbrekende vault geeft False'
    assert ob.append_note('iets', 'inhoud') is False, 'append naar een ontbrekende vault geeft False'
    assert not os.path.exists(missing), 'een ontbrekende vault wordt niet stilzwijgend aangemaakt'
    assert ob.read_note('iets') is None, 'lezen uit een ontbrekende vault geeft None'
    assert ob.note_exists('iets') is False, 'note_exists in een ontbrekende vault is False'
    assert ob.list_notes() == [], 'notities zoeken in een ontbrekende vault geeft []'
    raises_obsidian_error('onveilige naam wordt ook in een ontbrekende vault geweigerd', ob.resolve_note_path, '../geheim')
    assert ob.resolve_note_path('iets').startswith(os.path.abspath(missing)), 'resolve_note_path werkt ook zonder vault (droog)'
    ob.set_vault_path(vault)
    print('\n--- 8. ongeldige / niet-bestaande bestanden ---')
    assert ob.read_note('bestaat niet') is None, 'lezen van een niet-bestaande notitie geeft None'
    assert ob.note_exists('bestaant niet.md') is False, 'note_exists voor een niet-bestaande notitie is False'
    os.makedirs(os.path.join(vault, 'een map.md'), exist_ok=True)
    assert ob.read_note('een map.md') is None, 'lezen van een map geeft None (geen crash)'
    assert ob.note_exists('een map.md') is False, 'note_exists op een map is False'
    rommel = os.path.join(vault, 'rommel.md')
    with open(rommel, 'wb') as file:
        file.write(b'\xff\xfe\x00\x01 geen geldige utf-8')
    assert ob.read_note('rommel.md') is None, 'ongeldige utf-8 geeft None (geen crash)'
    assert ob.write_note('rommel', 'nu wel leesbaar'), 'overschrijven van binaire rommel lukt wel'
    assert ob.read_note('rommel') == 'nu wel leesbaar', 'rommel is vervangen'
    raises_obsidian_error('append met niet-tekst inhoud geweigerd', ob.append_note, 'welkom', None)
    assert ob.write_note('nieuw/deep/notitie', 'x', create_subfolders=False) is False, 'ongeldige notitie aanmaken met submap=False geeft False'
    assert not os.path.exists(os.path.join(vault, 'nieuw')), 'submap is daarbij niet aangemaakt'
    assert ob.write_note('nieuw/deep/notitie', 'x'), 'dezelfde notitie met submap=True lukt wel'
    print('\n--- 9. format_note ---')
    notitie = ob.format_note('Voorkeur licht', 'Ik hou van warm licht.', tags=['voorkeuren', 'licht'], category='voorkeuren')
    assert notitie.startswith('---'), 'format_note levert YAML-frontmatter'
    assert 'title: Voorkeur licht' in notitie, 'titel in de frontmatter'
    assert 'category: voorkeuren' in notitie, 'categorie in de frontmatter'
    assert 'tags: [voorkeuren, licht]' in notitie, 'tags in de frontmatter'
    assert 'date: ' in notitie, 'datum in de frontmatter'
    assert '# Voorkeur licht' in notitie, 'titel als kop'
    assert 'Ik hou van warm licht.' in notitie, 'inhoud in de notitie'
    assert 'tags: [liefde]' in ob.format_note('T', 'b', tags='liefde'), 'format_note met losse tag'
    assert '# Naamloos' in ob.format_note('', 'b'), 'lege titel krijgt een naam'
    assert not os.path.exists(os.path.join(vault, 'Voorkeur licht.md')), 'format_note maakt geen bestand aan'
    assert len(ob.list_notes()) == len(ob.list_notes()), 'aantal notities onveranderd na format_note'
    print('\n--- 10. los van memory.json ---')
    bron = open(os.path.join(ROOT, 'memory', 'obsidian.py'), encoding='utf-8').read()
    _geimporteerd = set()
    for _node in ast.walk(ast.parse(bron)):
        if isinstance(_node, ast.Import):
            for _alias in _node.names:
                _geimporteerd.add(_alias.name)
        elif isinstance(_node, ast.ImportFrom):
            _geimporteerd.add(_node.module or '')
    assert not any((m.split('.')[0] == 'memory' for m in _geimporteerd)), 'obsidian importeert niets uit het memory-pakket'
    assert not any((m.split('.')[0] in ('requests', 'urllib', 'http', 'socket') for m in _geimporteerd)), 'obsidian gebruikt geen netwerkbibliotheek'
    assert not any((m.split('.')[0] in ('obsidian', 'pyobsidian') for m in _geimporteerd)), 'obsidian gebruikt geen Obsidian API of plugin'
    assert not any((isinstance(v, str) and 'memory.json' in v for k, v in vars(ob).items() if not k.startswith('__'))), 'obsidian heeft geen verwijzing naar memory.json'
    _memory_sources = {}
    for naam in ('memory.py', 'store.py'):
        pad = os.path.join(ROOT, 'memory', naam)
        with open(pad, encoding='utf-8') as file:
            _memory_sources[naam] = ast.parse(file.read())

    def _haal_importen(tree):
        gevonden = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    gevonden.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                gevonden.add(node.module or '')
        return gevonden
    assert 'obsidian' not in _haal_importen(_memory_sources['memory.py']), 'memory.py importeert de Obsidian-laag niet'
    assert 'obsidian' not in _haal_importen(_memory_sources['store.py']), 'store.py importeert de Obsidian-laag niet'
    _memory_after = read_bytes(memory_json)
    assert _memory_after == _memory_before, 'echte memory.json is onveranderd gebleven'
    if not _memory_existed:
        print('  info: memory.json bestond niet voor deze test')
    print('\n--- 11. de echte vault (read-only) ---')
    ob.reset_vault_path()
    if ob.vault_exists():
        assert ob.is_obsidian_vault(), 'de echte vault is een Obsidian-vault'
        assert 'Welkom.md' in ob.list_notes(), 'de echte vault bevat Welkom.md'
        assert 'kluis' in (ob.read_note('Welkom.md') or ''), 'Welkom.md is leesbaar'
        assert ob.read_note('deze bestaat niet.md') is None, 'een niet-bestaande notitie in de echte vault geeft None'
        assert not os.path.exists(os.path.join(ob.get_vault_path(), 'test_notitie.md')), 'schrijven gebeurde niet in de echte vault'
    else:
        print('  info: geen echte vault aanwezig; sectie overgeslagen')
    print('\n--- 12. stap 2: slug en map-layout ---')
    ob.set_vault_path(vault2)
    assert ob.slugify('Favoriete kleur') == 'favoriete-kleur', 'slug uit gewone tekst'
    assert ob.slugify('voorkeur: kleur!') == 'voorkeur-kleur', 'slug uit tekst met leestekens'
    assert ob.slugify('lamp één') == 'lamp-een', 'slug haalt accenten weg'
    assert ob.slugify('!!!') == 'notitie', 'slug uit alleen leestekens'
    assert ob.slugify('   ') == 'notitie', 'slug uit lege tekst'
    assert ob.slugify('') != '', 'slug is nooit leeg'
    assert len(ob.slugify('a' * 500)) <= 60, 'slug begrenst de lengte'
    assert ob.slugify('a  --  b') == 'a-b', 'slug haalt dubbele streepjes weg'
    assert 'con' in ob.slugify('CON') and '/' not in ob.slugify('CON'), 'slug met een Windows-oordewoord is veilig'
    assert ob.folder_for_category('voorkeuren') == 'voorkeuren', 'map voor voorkeuren'
    assert ob.folder_for_category('pc') == 'pc', 'map voor pc'
    assert ob.folder_for_category('projecten') == 'projecten', 'map voor projecten'
    assert ob.folder_for_category('iets raars') == ob.DEFAULT_FOLDER, 'onbekende categorie gaat naar algemeen'
    assert ob.folder_for_category('') == ob.DEFAULT_FOLDER, 'lege categorie gaat naar algemeen'
    assert ob.folder_for_category('VOORKEUREN') == 'voorkeuren', 'categorie hoofdlettergevoelig negeren'
    assert ob.note_name_for_memory('favoriete kleur', 'voorkeuren') == 'voorkeuren/favoriete-kleur.md', 'notitiepad uit sleutel en categorie'
    assert ob.note_name_for_memory('iets') == 'algemeen/iets.md', 'notitiepad zonder categorie'
    assert ob.resolve_note_path(ob.note_name_for_memory('favoriete kleur', 'voorkeuren')).startswith(os.path.abspath(vault2)), 'notitiepad altijd binnen het vault'
    print('\n--- 13. stap 2: waarde leesbaar maken ---')
    assert ob.format_value('blauw') == 'blauw', 'tekstwaarde blijft tekst'
    assert ob.format_value(True) == 'ja', 'waarde True wordt ja'
    assert ob.format_value(False) == 'nee', 'waarde False wordt nee'
    assert ob.format_value(32) == '32', 'getal blijft leesbaar'
    assert ob.format_value(None) == 'niet ingesteld', 'None wordt niet-ingesteld'
    assert ob.format_value([]) == 'leeg', 'lege lijst'
    assert ob.format_value(['a', 'b']) == '- a\n- b', 'lijst wordt een lijstje'
    assert ob.format_value({'a': 1}) == '- a: 1', 'dict wordt sleutel-waarde'
    assert ob.format_value('   ') == 'niet ingesteld', 'lege tekst'
    assert ob.format_value([True, False]) == '- ja\n- nee', 'lijst met booleans'
    print('\n--- 14. stap 2: notitie bouwen zonder te schrijven ---')
    MEMORIES = {'voorkeuren': {'favoriete kleur': {'value': 'blauw', 'source': 'conversation', 'updated': '2026-01-10T18:00:00', 'previous_value': 'groen', 'corrected': True, 'conflict': False, 'usage_count': 3, 'last_used': None, 'priority': 2.5}, 'favoriet programma': {'value': 'Spotify', 'usage_count': 12, 'last_used': None, 'priority': 1.0}}, 'pc': {'heeft gpu': {'value': True, 'priority': 8.0}}}
    note = ob.memory_to_note(MEMORIES['voorkeuren']['favoriete kleur'], key='favoriete kleur', category='voorkeuren')
    assert note['note_name'] == 'voorkeuren/favoriete-kleur.md', 'notitiepad klopt'
    assert 'title: favoriete kleur' in note['content'], 'frontmatter met titel'
    assert 'category: voorkeuren' in note['content'], 'frontmatter met categorie'
    assert 'priority: 2.5' in note['content'], 'frontmatter met prioriteit'
    assert 'memory_key: favoriete kleur' in note['content'], 'frontmatter met memory_key'
    assert '> blauw' in note['content'], 'waarde staat erin'
    assert '- Prioriteit: 2.5' in note['content'], 'Nederlandse labels'
    assert '- Laatst gebruikt: nog niet gebruikt' in note['content'], 'lege last_used krijgt nette tekst'
    assert '- Vorige waarde: groen' in note['content'], 'vorige waarde blijft bewaard'
    assert '- Expliciet gecorrigeerd: ja' in note['content'], 'correctie blijft zichtbaar'
    assert 'updated: "2026-01-10T18:00:00"' in note['content'], 'timestamp wordt gequote in YAML'
    assert 'memory/voorkeuren' in note['content'], 'tags met categorie'
    assert ob.memory_to_note({'value': '  '}, key='leeg', category='pc') is None, 'lege string levert geen notitie op'
    _none_note = ob.memory_to_note({'value': None}, key='leeg', category='pc')
    assert _none_note is not None, 'None levert een notitie op'
    assert 'value_type: null' in _none_note['content'], 'None krijgt value_type: null'
    assert '> niet ingesteld' in _none_note['content'], 'None blijft leesbaar in de body'
    assert ob.memory_to_note('blauw', key='kleur', category='voorkeuren')['note_name'] == 'voorkeuren/kleur.md', 'kale waarde werkt ook zonder entry'
    assert ob.memory_to_note('blauw')['note_name'] == 'algemeen/blauw.md', 'zonder key valt terug op de waarde'
    note_gerelateerd = ob.memory_to_note(MEMORIES['voorkeuren']['favoriet programma'], key='favoriet programma', category='voorkeuren', related=['favoriete kleur', 'favoriet programma'])
    assert '[[favoriete kleur]]' in note_gerelateerd['content'], 'gerelateerde memory wordt een wiki-link'
    assert '[[favoriet programma]]' not in note_gerelateerd['content'], 'een memory verwijst niet naar zichzelf'
    _vorige_notities = sorted(os.listdir(vault2))
    assert sorted(os.listdir(vault2)) == _vorige_notities, 'memory_to_note schrijft niets'
    print('\n--- 15. stap 2: dry_run is de standaard ---')
    plan = ob.plan_memory_to_vault(MEMORIES['voorkeuren']['favoriete kleur'], key='favoriete kleur', category='voorkeuren')
    assert plan['action'] == 'create', 'plan zegt dat de notitie nieuw is'
    assert 'title: favoriete kleur' in plan['content'], 'plan bevat de volledige inhoud'
    assert plan['ok'] is True, 'plan is bruikbaar'
    plan = ob.save_memory_to_vault(MEMORIES['voorkeuren']['favoriete kleur'], key='favoriete kleur', category='voorkeuren')
    assert plan['dry_run'] is True, 'save_memory_to_vault is standaard een dry_run'
    assert plan['written'] is False, 'dry_run schrijft niets'
    assert not os.path.exists(os.path.join(vault2, 'voorkeuren')), 'dry_run heeft geen bestand aangemaakt'
    _alle = ob.save_all_memories_to_vault(MEMORIES)
    assert _alle['dry_run'] is True, 'save_all is standaard een dry_run'
    assert _alle['written'] is False, 'save_all schrijft niets'
    assert _alle['count']['geschreven'] == 0, 'save_all heeft geen notities geschreven'
    assert os.listdir(vault2) == [], 'dry_run vault is nog steeds leeg'
    assert _alle['count']['totaal'] == 3, 'dry_run telt wel alles'
    assert _alle['count']['nieuw'] == 3, 'dry_run telt drie nieuwe notities'
    print('\n--- 16. stap 2: echt schrijven als je erom vraagt ---')
    plan = ob.save_memory_to_vault(MEMORIES['voorkeuren']['favoriete kleur'], key='favoriete kleur', category='voorkeuren', dry_run=False)
    assert plan['written'] is True, 'dry_run=False schrijft echt'
    assert ob.note_exists('voorkeuren/favoriete-kleur.md'), 'notitie staat er'
    assert read_bytes(ob.resolve_note_path('voorkeuren/favoriete-kleur.md')) == plan['content'].encode('utf-8'), 'notitie klopt byte-voor-byte'
    assert ob.read_note('voorkeuren/favoriete-kleur.md') == plan['content'].rstrip('\n'), 'teruglezen geeft dezelfde inhoud'
    ob.append_note('voorkeuren/favoriete-kleur.md', '\n\nHandmatig toegevoegd.')
    plan = ob.save_memory_to_vault(MEMORIES['voorkeuren']['favoriete kleur'], key='favoriete kleur', category='voorkeuren', dry_run=False)
    assert plan['action'] == 'overwrite-blocked', 'bestaande notitie wordt niet overschreven'
    assert 'Handmatig toegevoegd.' in ob.read_note('voorkeuren/favoriete-kleur.md'), 'handmatige tekst staat er nog steeds'
    plan = ob.save_memory_to_vault(MEMORIES['voorkeuren']['favoriete kleur'], key='favoriete kleur', category='voorkeuren', dry_run=False, overwrite=True)
    assert plan['written'] is True, 'overwrite=True overschrijft'
    assert 'Handmatig toegevoegd.' not in ob.read_note('voorkeuren/favoriete-kleur.md'), 'handmatige tekst is weg'
    _alle = ob.save_all_memories_to_vault(MEMORIES, dry_run=False)
    assert _alle['count']['geschreven'] == 2, 'export schrijft alle notities'
    assert _alle['dry_run'] is False, 'export is geen dry_run meer'
    assert len(_alle['notes']) == 2, 'export rapporteert wat het schreef'
    assert ob.note_exists('pc/heeft-gpu.md'), 'nieuwe memory staat in de vault'
    assert _alle['count']['geschreven'] == 2, 'bestaande notitie werd niet overschreven'
    print('\n--- 17. stap 2: naambotsingen en onbruikbare memories ---')
    BOTSING = {'muziek': {'liefde nummer': {'value': 'a'}, 'liefde-nummer!': {'value': 'b'}}, 'pc': {'lege waarde': {'value': '  '}}}
    plannen = ob.plan_all_memories_to_vault(BOTSING)
    namen = [p['note_name'] for p in plannen if p['ok']]
    assert len(namen) == 2 and len(set(namen)) == 2, 'botsende memories krijgen verschillende namen'
    assert 'muziek/liefde-nummer.md' in namen, 'de eerste houdt de kale naam'
    assert any((n.startswith('muziek/liefde-nummer-') for n in namen)), 'de tweede krijgt een hash-suffix'
    _alle = ob.save_all_memories_to_vault(BOTSING, dry_run=False)
    assert _alle['count']['geschreven'] == 2, 'botsende memories worden allebei geschreven'
    assert ob.read_note('muziek/liefde-nummer.md') == _alle['plans'][0]['content'] or 'a' in ob.read_note('muziek/liefde-nummer.md'), 'geen memory overschrijft een ander'
    assert _alle['count']['overgeslagen'] == 1, 'lege waarde wordt overgeslagen'
    assert any((p['reason'] == 'geen bruikbare waarde' for p in _alle['plans'])), 'overgeslagen memory heeft een reden'
    assert ob.plan_all_memories_to_vault({'voorkeuren': 'geen dict'}) == [], 'lege categorie wordt genegeerd'
    assert ob.plan_all_memories_to_vault(None) == [], 'geen geheugen geeft een leeg plan'
    print('\n--- 18. stap 2: onveilige memories en ontbrekende vault ---')
    plan = ob.save_memory_to_vault({'value': 'x'}, 'CON', 'pc')
    assert plan['ok'] is False, 'Windows-oordewoord als sleutel wordt overgeslagen'
    assert plan['reason'].startswith('onveilige bestandsnaam'), 'de reden meldt een onveilige naam'
    plan = ob.save_memory_to_vault({'value': 'x'}, 'CON', 'pc', dry_run=False)
    assert plan['written'] is False, 'ook bij dry_run=False wordt er niets geschreven'
    assert not os.path.exists(os.path.join(vault2, 'pc', 'con.md')), 'het oordewoord heeft geen notitie aangemaakt'
    assert os.listdir(os.path.join(vault2, 'pc')) == ['heeft-gpu.md'], 'de pc-map bevat alleen de eerder geschreven notitie'
    raises_obsidian_error('resolve_note_path gooit een ObsidianError', ob.resolve_note_path, 'pc/con.md')
    plan = ob.save_memory_to_vault({'value': 'x'}, '  ', 'pc')
    assert plan['ok'] is False, 'lege sleutel wordt overgeslagen'
    assert plan['reason'] == 'sleutel is leeg', 'lege sleutel heeft een reden'
    ob.set_vault_path(os.path.join(work, 'bestaat niet'))
    plan = ob.save_memory_to_vault({'value': 'blauw'}, 'kleur', 'voorkeuren')
    assert plan['action'] == 'no-vault', 'ontbrekende vault geeft no-vault'
    assert plan['written'] is False, 'ontbrekende vault schrijft niets'
    _alle = ob.save_all_memories_to_vault(MEMORIES, dry_run=False)
    assert _alle['count']['geschreven'] == 0, 'export naar ontbrekende vault schrijft niets'
    ob.set_vault_path(vault2)
    print('\n--- 19. stap 2: GEEN automatische koppeling ---')
    assert 'obsidian' not in _haal_importen(_memory_sources['memory.py']), 'memory.py bevat geen import van obsidian'
    assert 'obsidian' not in _haal_importen(_memory_sources['store.py']), 'store.py bevat geen import van obsidian'
    assert not hasattr(ob, 'remember') and (not hasattr(ob, 'update_memory')), "er is geen functie 'remember' in de obsidian-laag"
    assert not any((isinstance(v, str) and 'memory.json' in v for k, v in vars(ob).items() if not k.startswith('__'))), 'de obsidian-laag heeft geen geheugen-laag aangeraakt'
    _geheugen_tmp = os.path.join(work, 'geheugen.json')
    with patch.object(mem, 'MEMORY_FILE', _geheugen_tmp):
        mem.store.reset_cache(_geheugen_tmp)
        _notities_voor = ob.list_notes()
        uitkomst = mem.remember('favoriete kleur', 'blauw', category='voorkeuren')
        assert uitkomst['category'] == 'voorkeuren', 'remember() werkt nog normaal'
        assert ob.list_notes() == _notities_voor, 'remember() legt niets aan in de vault'
        assert not os.path.exists(os.path.join(vault2, 'voorkeuren', 'nieuw')), 'remember() maakt geen notitie-map aan'
        assert os.path.exists(_geheugen_tmp), 'de memory staat wel in het geheugenbestand'
        mem.store.reset_cache(_geheugen_tmp)
    assert read_bytes(memory_json) == _memory_before, 'echte memory.json is na stap 2 nog steeds onveranderd'
    print('\n--- 20. stap 2: de echte gegevens, alleen gepland ---')
    ob.reset_vault_path()
    _echte_vault_notities = ob.list_notes()
    try:
        import memory.memory as mem_live
        _echt = mem_live.load_memory()
        plannen = ob.save_all_memories_to_vault(_echt)
        assert isinstance(_echt, dict), 'het echte geheugen is in te laden'
        assert isinstance(plannen['plans'], list), 'het echte geheugen is te plannen'
        assert plannen['count']['totaal'] >= 0, 'plannen tellen de echte memories'
        assert plannen['written'] is False, 'het echte geheugen wordt NIET geschreven'
        assert ob.list_notes() == _echte_vault_notities, 'de echte vault is onveranderd'
        print(f"  info: {plannen['count']['totaal']} memories in memory.json, {plannen['count']['bruikbaar']} zouden een notitie worden")
    except Exception as exc:
        assert False, f'echte geheugen plannen werkte niet ({type(exc).__name__}: {exc})'
    print('\n--- 21. stap 3: frontmatter lezen ---')
    assert vi.parse_frontmatter('---\ntitle: test\n---\n\nbody')[0]['title'] == 'test', 'frontmatter wordt geparseerd'
    assert vi.parse_frontmatter('---\ntitle: test\n---\n\nbody')[1] == 'body', 'body wordt gescheiden van metadata'
    assert vi.parse_frontmatter('# gewone notitie')[0] == {}, 'notitie zonder frontmatter geeft lege metadata'
    assert vi.parse_frontmatter('') == ({}, ''), 'geen tekst geeft lege metadata'
    assert vi.parse_frontmatter('---\npriority: 2.5\n---\n')[0]['priority'] == '2.5', 'waarde zonder quotes blijft schoon'
    assert vi.parse_frontmatter('---\nupdated: "2026-01-10T18:00:00"\n---')[0]['updated'] == '2026-01-10T18:00:00', 'dubbele quotes worden afgehaald'
    assert vi.parse_frontmatter('---\ntitle: mijn: ding\n---')[0]['title'] == 'mijn: ding', 'waarde met dubbele punt blijft heel'
    assert vi.parse_frontmatter('\ufeff---\ntitle: test\n---')[0]['title'] == 'test', 'BOM aan het begin wordt genegeerd'
    print('\n--- 22. stap 3: notitie -> memory ---')
    ob.set_vault_path(vault3)
    _m = ob.memory_to_note({'value': 'blauw'}, key='favoriete kleur', category='voorkeuren')
    ob.write_note(_m['note_name'], _m['content'])
    assert vi.read_note(_m['note_name']) is not None, 'notitie wordt gelezen'
    assert vi.read_note('bestaat niet.md') is None, 'niet-bestaande notitie geeft None'
    data = vi.note_to_memory(_m['note_name'])
    assert data['key'] == 'favoriete kleur', 'sleutel wordt herkend'
    assert data['category'] == 'voorkeuren', 'categorie wordt herkend'
    assert data['value'] == 'blauw', 'waarde wordt herkend'
    assert data['priority'] == 1.0, 'prioriteit wordt herkend'
    assert vi.note_to_memory('welkom.md') is None, 'handgeschreven notitie geeft None'
    ob.write_note('pc/heeft-gpu', ob.memory_to_note({'value': 'ja', 'priority': 8.0}, key='heeft gpu', category='pc')['content'])
    d = vi.note_to_memory('pc/heeft-gpu.md')
    assert d['priority'] == 8.0, 'prioriteit uit de notitie wordt gelezen'
    print('\n--- 23. stap 3: plannen (nog niets opslaan) ---')
    # Hermetisch: plan_import leest het geheugen. Gebruik een leeg
    # tijdelijk geheugen i.p.v. de echte memory/memory.json, anders
    # hangt de uitkomst af van runtime-staat en wordt de test flaky.
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        plan = vi.plan_import(_m['note_name'])
        assert plan['action'] == 'new', "plan voor nieuwe memory is 'new'"
        assert plan['key'] == 'favoriete kleur', 'plan bevat de sleutel'
        assert vi.plan_import('bestaat niet.md')['action'] == 'skip', 'plan voor niet-bestaande notitie geeft skip'
        assert vi.plan_import('bestaat niet.md')['reason'] != '', 'skip heeft een reden'
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        r = vi.import_all(dry_run=True)
        assert r['count']['gevonden'] >= 1, 'import_all telt de memory-notities'
        assert r['dry_run'] is True, 'import_all is standaard een dry_run'
        assert mem.store.read(mem3_file) in (None, {}), 'import_all schrijft niets naar het geheugen'
    print('\n--- 24. stap 3: importeren ---')
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        r = vi.import_all(dry_run=False)
        assert r['count']['geimporteerd'] >= 1, 'import_all importeert'
        assert 'favoriete kleur' in mem.load_memory()['voorkeuren'], 'de memory staat nu in het geheugen'
        assert mem.load_memory()['pc']['heeft gpu']['priority'] == 8.0, 'prioriteit uit de notitie is gerespecteerd'
        r2 = vi.import_all(dry_run=False)
        assert r2['count']['onveranderd'] >= 1, 'tweede import is onveranderd'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'tweede import overschrijft niets'
    print('\n--- 25. stap 3: conflictlogica wordt hergebruikt ---')
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        ob.write_note(_m['note_name'], ob.memory_to_note({'value': 'groen'}, key='favoriete kleur', category='voorkeuren')['content'])
        r = vi.import_note(_m['note_name'])
        assert r['needs_confirm'] is True, 'conflict wordt gemeld'
        assert r['action'] == 'conflict', 'conflict gebruikt de memory-action'
        assert r['value'] == 'groen', 'conflict toont de vault-waarde'
        assert r['memory_value'] == 'blauw', 'conflict toont de huidige waarde'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'geheugen is NIET overschreven zonder bevestiging'
        assert isinstance(r['confirm_token'], dict), 'conflict levert een confirm_token'
        assert r['confirm_token']['vault_value'] == 'groen', 'confirm_token bevat de vault-waarde'
        res = vi.resolve_pending(r['confirm_token'], keep_old=True)
        assert res['kept_old'] is True, 'resolve_pending meldt dat de oude bleef'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'blauw', 'oude waarde is daadwerkelijk behouden'
        r2 = vi.import_note(_m['note_name'])
        res = vi.resolve_pending(r2['confirm_token'], keep_old=False)
        assert res['applied'] is True, 'resolve_pending past de nieuwe waarde toe'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'groen', 'nieuwe waarde staat nu in het geheugen'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['previous_value'] == 'blauw', 'vorige waarde is bewaard'
        ob.write_note(_m['note_name'], ob.memory_to_note({'value': 'zwart'}, key='favoriete kleur', category='voorkeuren')['content'])
        r3 = vi.import_note(_m['note_name'], force=True)
        assert r3['applied'] is True, 'force=True past toe zonder bevestiging'
        assert mem.load_memory()['voorkeuren']['favoriete kleur']['value'] == 'zwart', 'force=True heeft de waarde toegepast'
    print('\n--- 26. stap 3: resolve_pending validatie ---')
    try:
        vi.resolve_pending('geen dict')
    except TypeError:
        assert True, 'resolve_pending met verkeerd type geweigerd'
    except Exception as exc:
        assert False, f'resolve_pending met verkeerd type gaf {type(exc).__name__}'
    else:
        assert False, 'resolve_pending met verkeerd type geweigerd'
    try:
        vi.resolve_pending({'key': 'x'})
    except ValueError:
        assert True, 'resolve_pending mist verplicht veld -> ValueError'
    except Exception as exc:
        assert False, f'resolve_pending gaf {type(exc).__name__}'
    else:
        assert False, 'resolve_pending mist verplicht veld -> ValueError'
    print('\n--- 27. stap 3: handgeschreven notities worden overgeslagen ---')
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        ob.write_note('mijn notitie', '# Handgeschreven\n\nGeen memory_key hier.')
        r = vi.import_all(dry_run=False)
        assert all(('mijn notitie' not in p['note_name'] for p in r['plans'])), 'handgeschreven notitie wordt niet meegeteld'
        assert 'mijn notitie' not in mem.load_memory()['algemeen'], 'handgeschreven notitie komt niet in het geheugen'
    print('\n--- 28. stap 3: GEEN automatische synchronisatie ---')
    assert hasattr(vi, 'ob') and hasattr(vi, 'mem'), 'vault_import importeert niets uit obsidian buiten de laag'
    _bron = open(os.path.join(ROOT, 'memory', 'obsidian.py'), encoding='utf-8').read()
    _geimporteerd_ob = set()
    for _node in ast.walk(ast.parse(_bron)):
        if isinstance(_node, ast.Import):
            for _alias in _node.names:
                _geimporteerd_ob.add(_alias.name)
        elif isinstance(_node, ast.ImportFrom):
            _geimporteerd_ob.add(_node.module or '')
    assert not any((m.startswith('memory') for m in _geimporteerd_ob)), 'obsidian.py importeert nog steeds niets uit memory'
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        _voor = ob.list_notes()
        mem.remember('een nieuwe memory', 'test', category='algemeen')
        assert ob.list_notes() == _voor, 'remember() raakt de vault niet aan'
        mem.store.reset_cache(mem3_file)
    with patch.object(mem, 'MEMORY_FILE', mem3_file):
        mem.store.reset_cache(mem3_file)
        _m2 = mem.load_memory()
        ob.write_note('voorkeuren/nieuw', '# Nieuw\n\nmemory_key: nieuw\n\n> test')
        _na = mem.load_memory()
        assert _na == _m2, 'een notitie in de vault komt niet vanzelf in het geheugen'
        mem.store.reset_cache(mem3_file)
    ob.reset_vault_path()
    shutil.rmtree(work, ignore_errors=True)
