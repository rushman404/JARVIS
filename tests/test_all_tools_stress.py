import sys
import os
import io
import json
import re
import tempfile
from unittest.mock import patch, MagicMock
import ollama as _ollama_mod
import core.brain as brain
import core.ai as ai
import core.routines as _routines_mod

def test_main(request):
    """
JARVIS — alle-tools-stress-test (volledige gereedschapsdekking)
================================================================

Test ALLE tools van JARVIS end-to-end via brain.process_command() waar
dat kan, en de tool-dispatcher core.ai.execute_tool() voor elke toolnaam.

Dekking per sectie:
  [1] Programma's openen/sluiten (open_program, close_program)
  [2] Media (play/pause, next, prev, volume, mute)
  [3] Systeeminformatie (cpu/ram/gpu/opslag/batterij/os/uptime/overzicht)
  [4] Vensters (minimaliseren, maximaliseren, herstellen)
  [5] Screenshot
  [6] Power-acties met bevestigingsflow (lock/sleep/shutdown/restart/logoff)
  [7] Bestandsbeheer (map maken, bestand maken, lijst, kopiëren, verplaatsen)
  [8] AI-route-tools via gemockte LLM (open_file/open_website/remember/
      recall/forget/media_stop/get_home_assistant_entities/
      control_home_assistant)
  [9] Conversatie / kennisvragen + vervolgvraag
  [10] Tijd en rekenen
  [11] Agent (multi-actie + doel-gebaseerd) met gemockte JSON-planner
  [12] Tool-dispatcher: elke VALID_TOOL_NAME door core.ai.execute_tool

Alle echte netwerk-, HA-, audio-, venster- en bestandshandelingen zijn
gemockt; er vinden geen echte zij-effecten plaats.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    safe_reject = 0

    def safe(label, detail=''):
        nonlocal safe_reject
        safe_reject += 1
        msg = f'  [SKIP] {label}'
        if detail:
            msg += f' ({detail})'
        print(msg)

    def _norm(text):
        return re.sub('[^a-z0-9]', '', (text or '').lower())
    _tmp_mem = tempfile.mktemp(suffix='_memory.json')
    with open(_tmp_mem, 'w', encoding='utf-8') as f:
        f.write(json.dumps({}))
    _orig_ctx = dict(brain.current_context)
    _orig_ollama_chat = _ollama_mod.chat
    _orig_ai_save = ai._save_conversation
    _memory_patch = patch('memory.memory.MEMORY_FILE', _tmp_mem)
    _memory_patch.start()
    _patch_save = patch('core.ai._save_conversation', lambda: None)
    _patch_save.start()
    _patch_approval = patch('core.executor.APPROVAL_REQUIRED_RISKS', ())
    _patch_approval.start()

    def _safe_stub(*args, **kwargs):
        """Laat de LLM nooit echt aangestuurd worden buiten de fake-secties."""
        msg = type('M', (), {'content': 'geen idee', 'tool_calls': None})()
        return type('R', (), {'message': msg})()
    _ollama_mod.chat = _safe_stub
    ai.ollama.chat = _safe_stub
    _ROUTINE_SEED = {'gaming': {'name': 'gaming', 'triggers': ['\\bgamen\\b', 'ik ga gamen', 'maak mijn pc klaar om te gamen'], 'aliases': ['game modus', 'gaming modus'], 'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'Discord'}, 'description': 'Discord openen'}, {'tool_name': 'open_program', 'arguments': {'program': 'Spotify'}, 'description': 'Spotify openen'}, {'tool_name': 'set_volume', 'arguments': {'percent': 40}, 'description': 'Volume op 40%'}, {'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_on', 'entity_id': 'light.bed_lamp', 'service_data': {'brightness_pct': 30}}, 'description': 'Bedlamp aan op 30%'}], 'description': 'Test-routine gaming mode.', 'usage_count': 0, 'last_used': ''}, 'filmen': {'name': 'filmen', 'triggers': ['ik ga filmen'], 'aliases': ['film modus', 'filmen'], 'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'Premiere Pro'}, 'description': 'Premiere Pro openen'}], 'description': 'Test-routine filmen mode.', 'usage_count': 0, 'last_used': ''}}
    _tmp_routines = tempfile.mktemp(suffix='_routines.json')
    with open(_tmp_routines, 'w', encoding='utf-8') as f:
        json.dump(_ROUTINE_SEED, f)
    _routines_patch = patch('core.routines.ROUTINES_FILE', _tmp_routines)
    _routines_patch.start()
    _routines_mod._manager.reload()

    # Exception-safe cleanup: de handmatige stop()-reeks onderaan de test wordt
    # bij een assertion-fout nooit bereikt (bleek in de praktijk: na een gefaalde
    # run lekten APPROVAL_REQUIRED_RISKS, ROUTINES_FILE, MEMORY_FILE,
    # _save_conversation en ollama.chat naar de rest van de suite). pytest voert
    # addfinalizer-callbacks ook bij een failed test uit. Registratievolgorde is
    # omgekeerd van uitvoer (LIFO): de routines-reload staat als laatste klaar en
    # draait dus nadat _routines_patch gestopt is en het echte bestand weer geldt.
    def _restore_routines():
        try:
            _routines_mod._manager.reload()
        except Exception:
            pass
    request.addfinalizer(_restore_routines)
    for _p in (_routines_patch, _memory_patch, _patch_save, _patch_approval):
        request.addfinalizer(_p.stop)

    def _restore_ollama():
        _ollama_mod.chat = _orig_ollama_chat
        ai.ollama.chat = _orig_ollama_chat
    request.addfinalizer(_restore_ollama)

    def _cleanup_tmp():
        for _f in (_tmp_mem, _tmp_routines):
            try:
                os.remove(_f)
            except OSError:
                pass
    request.addfinalizer(_cleanup_tmp)

    def _reset_state():
        """Set een schone context en lege gespreksgeschiedenis per case."""
        brain.current_context.update(_orig_ctx)
        brain.current_context['pending_choice'] = None
        brain.current_context['last_ha_entity'] = None
        brain.current_context['last_ha_domain'] = None
        brain.current_context['last_ha_name'] = None
        ai.conversation_history = []
    print('=' * 60)
    print('JARVIS ALLE-TOOLS STRESS-TEST')
    print('=' * 60)
    print()
    print("===== 1: PROGRAMMA'S =====\n")
    _KNOWN_PROGRAMS = {'spotify', 'discord', 'chrome', 'steam'}

    def _fake_find_program(name, exact_only=False):
        if name in _KNOWN_PROGRAMS:
            return f'C:\\Programs\\{name}.lnk'
        return None
    with patch('core.brain.find_program', side_effect=_fake_find_program), patch('core.brain.open_program_tool', return_value='Spotify is geopend.') as m_open, patch('core.brain.close_program_tool', return_value='Spotify is gesloten.') as m_close:
        _reset_state()
        brain.process_command('open spotify')
        assert m_open.called and m_open.call_args[0][0] == 'spotify', "open spotify -> open_program_tool('spotify')"
        m_open.reset_mock()
        _reset_state()
        r = brain.process_command('start discord')
        assert m_open.called and m_open.call_args[0][0] == 'discord', "start discord -> open_program_tool('discord')"
        m_open.reset_mock()
        _reset_state()
        r = brain.process_command('start discord')
        assert m_open.called and m_open.call_args[0][0] == 'discord', "start discord -> open_program_tool('discord')"
        m_close.reset_mock()
        _reset_state()
        brain.process_command('sluit spotify')
        assert m_close.called and m_close.call_args[0][0] == 'spotify', "sluit spotify -> close_program_tool('spotify')"
        m_open.reset_mock()
        m_close.reset_mock()
        _reset_state()
        brain.process_command('open spotify')
        brain.current_context['last_program'] = 'spotify'
        brain.process_command('sluit hem')
        assert m_close.called and m_close.call_args[0][0] == 'spotify', "context-fallback: 'sluit hem' -> close('spotify')"
        m_open.reset_mock()
        _reset_state()
        brain.process_command('open denkbeeldigeprogramma')
        assert not m_open.called, 'onbekend programma blijft bij de AI (geen directe open)'
    print('\n===== 2: MEDIA =====\n')
    with patch('core.brain.set_volume', return_value='Volume staat nu op 30%.') as m_setv, patch('core.brain.volume_up', return_value='Volume omhoog, nu op 30%.') as m_up, patch('core.brain.volume_down', return_value='Volume omlaag, nu op 20%.') as m_down, patch('core.brain.toggle_mute', return_value='Geluid gedempt.') as m_mute, patch('core.brain.play_pause', return_value='Muziek gepauzeerd.') as m_pp, patch('core.brain.next_track', return_value='Volgend nummer.') as m_next, patch('core.brain.previous_track', return_value='Vorig nummer.') as m_prev:
        _reset_state()
        brain.process_command('zet volume op 30')
        assert m_setv.called and m_setv.call_args[0][0] == 30, 'zet volume op 30 -> set_volume(30)'
        m_up.reset_mock()
        _reset_state()
        r = brain.process_command('zet het volume harder')
        assert m_up.called, "'harder' -> volume_up()"
        m_up.reset_mock()
        _reset_state()
        brain.process_command('zet het geluid luider')
        assert m_up.called, "'luider' -> volume_up()"
        m_down.reset_mock()
        _reset_state()
        brain.process_command('volume omlaag')
        assert m_down.called, 'volume omlaag -> volume_down()'
        m_down.reset_mock()
        _reset_state()
        brain.process_command('maak het geluid zachter')
        assert m_down.called, "'zachter' (geen apparaatwoord) -> volume_down()"
        m_mute.reset_mock()
        _reset_state()
        brain.process_command('demp het geluid')
        assert m_mute.called, 'demp het geluid -> toggle_mute()'
        m_pp.reset_mock()
        _reset_state()
        brain.process_command('pauzeer de muziek')
        assert m_pp.called, 'pauzeer de muziek -> play_pause()'
        m_pp.reset_mock()
        _reset_state()
        brain.process_command('speel de muziek')
        assert m_pp.called, 'speel de muziek -> play_pause()'
        m_next.reset_mock()
        _reset_state()
        brain.process_command('volgende nummer')
        assert m_next.called, 'volgende nummer -> next_track()'
        m_prev.reset_mock()
        _reset_state()
        brain.process_command('vorige nummer')
        assert m_prev.called, 'vorige nummer -> previous_track()'
    print('\n===== 3: SYSTEEMINFORMATIE =====\n')
    _SYS_MOCKS = {'core.brain.cpu_info': {'naam': 'Intel Core i9-13900K', 'cores': 24, 'threads': 32}, 'core.brain.ram_info': {'totaal': 32, 'gebruikt': 8, 'vrij': 24}, 'core.brain.gpu_names': ['NVIDIA RTX 5090'], 'core.brain.disk_info': {'totaal': 500, 'vrij': 123, 'gebruikt': 377}, 'core.brain.battery_info': {'percentage': 80, 'stekker': True}, 'core.brain.os_info': {'systeem': 'Windows', 'release': '11'}, 'core.brain.uptime': {'dagen': 2, 'uren': 5, 'minuten': 30}, 'core.brain.system_summary': '=== SYSTEEMINFORMATIE ===\nIntel Core i9-13900K, 32 GB RAM, NVIDIA RTX 5090'}
    with patch('core.brain.cpu_info', return_value=_SYS_MOCKS['core.brain.cpu_info']), patch('core.brain.ram_info', return_value=_SYS_MOCKS['core.brain.ram_info']), patch('core.brain.gpu_names', return_value=_SYS_MOCKS['core.brain.gpu_names']), patch('core.brain.disk_info', return_value=_SYS_MOCKS['core.brain.disk_info']), patch('core.brain.battery_info', return_value=_SYS_MOCKS['core.brain.battery_info']), patch('core.brain.os_info', return_value=_SYS_MOCKS['core.brain.os_info']), patch('core.brain.uptime', return_value=_SYS_MOCKS['core.brain.uptime']), patch('core.brain.system_summary', return_value=_SYS_MOCKS['core.brain.system_summary']):
        _reset_state()
        r = brain.process_command('wat is mijn cpu')
        assert 'Intel Core i9-13900K' in r, "cpu -> 'Intel Core i9-13900K' in antwoord"
        _reset_state()
        r = brain.process_command('hoeveel ram heb ik')
        assert "'32 GB RAM' in " and '32' in r and ('RAM' in r), "ram -> '32 GB RAM' in antwoord"
        _reset_state()
        r = brain.process_command('welke gpu heb ik')
        assert 'NVIDIA RTX 5090' in r, "gpu -> 'NVIDIA RTX 5090' in antwoord"
        _reset_state()
        r = brain.process_command('hoeveel opslag heb ik')
        assert '123' in r, 'opslag -> vrij-getal in antwoord'
        _reset_state()
        r = brain.process_command('hoe zit het met de batterij')
        assert '80' in r and 'stroom' in r, 'batterij -> percentage + stroom in antwoord'
        _reset_state()
        r = brain.process_command('welke windows heb je')
        assert 'Windows 11' in r, "windows -> 'Windows 11' in antwoord"
        _reset_state()
        r = brain.process_command('hoe lang staat de pc aan')
        assert '2 dagen' in r, "uptime -> '2 dagen' in antwoord"
        _reset_state()
        r = brain.process_command('systeeminformatie')
        assert 'SYSTEEMINFORMATIE' in str(r), 'systeeminformatie -> overzicht in antwoord'
    print('\n===== 4: VENSTERS =====\n')
    with patch('core.brain.minimize_program', return_value='Spotify is verkleind.') as m_min, patch('core.brain.maximize_program', return_value='Spotify is vergroot.') as m_max, patch('core.brain.restore_window', return_value='Spotify is hersteld.') as m_res:
        _reset_state()
        r = brain.process_command('minimaliseer spotify')
        assert m_min.called and m_min.call_args[0][0] == 'spotify', "minimaliseer spotify -> minimize_program('spotify')"
        m_max.reset_mock()
        _reset_state()
        r = brain.process_command('vergroot spotify')
        assert m_max.called and m_max.call_args[0][0] == 'spotify', "vergroot spotify -> maximize_program('spotify')"
        m_res.reset_mock()
        _reset_state()
        r = brain.process_command('herstel spotify')
        assert m_res.called and m_res.call_args[0][0] == 'spotify', "herstel spotify -> restore_window('spotify')"
    print('\n===== 5: SCREENSHOT =====\n')
    with patch('core.brain.take_screenshot', return_value='C:\\Shots\\moment.png') as m_shot:
        _reset_state()
        r = brain.process_command('maak een screenshot')
        assert 'moment.png' in r, 'screenshot -> bestandsnaam in antwoord'
        assert m_shot.called, 'screenshot via take_screenshot()'
    print('\n===== 6: POWER (ALLEN MOCKED) =====\n')
    _POWER_MOCKS = {'lock': MagicMock(return_value='De pc is vergrendeld.'), 'sleep': MagicMock(return_value='De pc gaat in slaapstand.'), 'shutdown': MagicMock(return_value='De pc gaat afsluiten.'), 'restart': MagicMock(return_value='De pc wordt herstart.'), 'logoff': MagicMock(return_value='Je wordt afgemeld.')}
    with patch.dict('core.brain.POWER_ACTIONS', _POWER_MOCKS):

        def _power_flow(cmd, action, expectation):
            m = _POWER_MOCKS[action]
            m.reset_mock()
            _reset_state()
            r1 = brain.process_command(cmd)
            assert not m.called, f"'{cmd}' vraagt eerst bevestiging (niks uitgevoerd)"
            r2 = brain.process_command('ja')
            assert m.called, f"'{cmd}' + 'ja' roept POWER_ACTIONS.mock['{action}']"
            assert expectation in str(r2), f"'{cmd}' bevestiging geeft '{expectation}'"
        _power_flow('sluit de pc af', 'shutdown', 'afsluiten')
        _power_flow('herstart de pc', 'restart', 'herstart')
        _power_flow('zet de pc in slaapstand', 'sleep', 'slaapstand')
        _power_flow('vergrendel de pc', 'lock', 'vergrendeld')
        _power_flow('log uit van de pc', 'logoff', 'afgemeld')
        _POWER_MOCKS['shutdown'].reset_mock()
        _reset_state()
        brain.process_command('sluit de pc af')
        r_no = brain.process_command('nee')
        assert not _POWER_MOCKS['shutdown'].called and 'doe het niet' in r_no, "'nee' annuleert (geen shutdown)"
    print('\n===== 7: BESTANDSBEHEER =====\n')
    with patch('core.brain.create_folder', return_value="Map 'testmap' aangemaakt.") as m_mkdir, patch('core.brain.create_file', return_value="Bestand 'test.txt' aangemaakt.") as m_mkfile, patch('core.brain.list_folder', return_value='afbeeldingen.jpg, notities.txt') as m_list, patch('core.brain.copy_path', return_value='Kopie gemaakt.') as m_copy, patch('core.brain.move_path', return_value='Bestand verplaatst.') as m_move, patch('core.brain.find_item', return_value=['C:\\Users\\stu\\Downloads\\notities.txt']):
        _reset_state()
        r = brain.process_command('maak een map genaamd testmap')
        assert m_mkdir.called and m_mkdir.call_args[0][0] == 'testmap', "maak een map -> create_folder('testmap')"
        _reset_state()
        r = brain.process_command('maak een bestand genaamd test.txt')
        assert m_mkfile.called and m_mkfile.call_args[0][0] == 'test.txt', "maak een bestand -> create_file('test.txt')"
        _reset_state()
        r = brain.process_command('welke bestanden zijn er op het bureaublad')
        assert m_list.called and 'afbeeldingen.jpg' in str(r), 'lijst bestanden -> list_folder() aangeroepen'
        _reset_state()
        r = brain.process_command('kopieer notities.txt naar documenten')
        assert m_copy.called, 'kopieer -> copy_path(...)'
        _reset_state()
        r = brain.process_command('verplaats notities.txt naar documenten')
        assert m_move.called, 'verplaats -> move_path(...)'
    print('\n===== 8: AI-ROUTE TOOLS =====\n')

    def _resolve_fake(entity_id, domain):
        return (entity_id, 'exact', '')
    _AI_TOOL_MAP = {'openhetbestandnotitiestxt': ('open_file', {'filename': 'notities.txt'}), 'opendewebsitegooglecom': ('open_website', {'url': 'https://google.com'}), 'onthouddatmijnfavorietegameeldenringis': ('remember', {'key': 'favoriete_game', 'value': 'Elden Ring'}), 'vergeetmijnfavorietegame': ('forget', {'key': 'favoriete_game'}), 'welkelampenhebje': ('get_home_assistant_entities', {'domain': 'light'}), 'maakhetlichtindewoonkameruit': ('control_home_assistant', {'domain': 'light', 'service': 'turn_off', 'entity_id': 'light.woonkamer'}), 'zetdeverwarmingop21graden': ('control_home_assistant', {'domain': 'climate', 'service': 'set_temperature', 'entity_id': 'climate.woonkamer_thermostaat', 'service_data': {'temperature': 21}})}

    def _ai_tool_fake(calls_log):

        def fake_chat(*args, **kwargs):
            messages = kwargs.get('messages') or (args[0] if args else [])
            last_user = ''
            for m in messages:
                if isinstance(m, dict) and m.get('role') == 'user':
                    last_user = m.get('content', '')
            key = _norm(last_user)
            if key in _AI_TOOL_MAP:
                tool_name, tool_args = _AI_TOOL_MAP[key]
                calls_log.append({'tool': tool_name, 'args': tool_args})
                fn = MagicMock()
                fn.name = tool_name
                if tool_name in ('open_file', 'open_website'):
                    fn.arguments = dict(tool_args)
                else:
                    fn.arguments = dict(tool_args)
                tc = type('TC', (), {'function': fn})()
                msg = type('M', (), {'content': '', 'tool_calls': [tc]})()
                return type('R', (), {'message': msg})()
            msg = type('M', (), {'content': 'geen idee', 'tool_calls': None})()
            return type('R', (), {'message': msg})()
        return fake_chat
    _ai_log = []
    with patch('core.ai.control_home_assistant_tool', return_value='Actie uitgevoerd.') as m_ai_ha, patch('core.ai.get_home_assistant_entities_tool', return_value='light.bed_lamp, light.woonkamer') as m_ai_list, patch('core.ai.open_file_tool', return_value='Bestand geopend.') as m_ai_file, patch('core.ai.open_website_tool', return_value='Website geopend.') as m_ai_web, patch('core.ai.remember_tool', return_value='Oké, ik onthoud dat.') as m_ai_rem, patch('core.ai.recall_tool', return_value='Elden Ring') as m_ai_rec, patch('core.ai.forget_tool', return_value='Vergeten.') as m_ai_for, patch('core.ai.media_stop_tool', return_value='Muziek gestopt.') as m_ai_stop, patch('core.ai.resolve_live_entity_id', side_effect=_resolve_fake), patch('core.tool_registry.get_tool_risk', return_value='low'):
        _fake = _ai_tool_fake(_ai_log)
        _ollama_mod.chat = _fake
        ai.ollama.chat = _fake

        def _ai_case(cmd, mock):
            mock.reset_mock()
            _reset_state()
            brain.process_command(cmd)
            return mock.called
        assert _ai_case('open het bestand notities.txt', m_ai_file), "open het bestand notities.txt -> open_file('notities.txt')"
        assert _ai_case('open de website google.com', m_ai_web), "open de website google.com -> open_website('https://google.com')"
        assert _ai_case('onthoud dat mijn favoriete game elden ring is', m_ai_rem), 'onthoud ... elden ring -> remember(favoriete_game)'
        assert _ai_case('vergeet mijn favoriete game', m_ai_for), 'vergeet mijn favoriete game -> forget(favoriete_game)'
        assert _ai_case('welke lampen heb je', m_ai_list), 'welke lampen heb je -> get_home_assistant_entities'
        assert _ai_case('maak het licht in de woonkamer uit', m_ai_ha), 'maak het licht in de woonkamer uit -> control_home_assistant'
        assert _ai_case('zet de verwarming op 21 graden', m_ai_ha), 'zet de verwarming op 21 graden -> control_home_assistant(climate)'
    print('\n===== 9: CONVERSATIE =====\n')

    def _chat_fake(*args, **kwargs):
        messages = kwargs.get('messages') or (args[0] if args else [])
        last_user = ''
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'user':
                last_user = m.get('content', '')
        if 'duitsland' in last_user.lower():
            text = 'Berlijn.'
        else:
            text = 'Parijs.'
        msg = type('M', (), {'content': text, 'tool_calls': None})()
        return type('R', (), {'message': msg})()
    with patch('core.ai.ollama.chat', side_effect=_chat_fake), patch('core.brain.get_context_answer', return_value=None), patch('core.ai.resolve_live_entity_id', side_effect=_resolve_fake):
        _reset_state()
        r = brain.process_command('wat is de hoofdstad van frankrijk')
        assert 'Parijs' in r, "kennisvraag -> LLM-antwoord 'Parijs'"
        ai.conversation_history = [{'role': 'user', 'content': 'wat is de hoofdstad van frankrijk', 'ts': ''}, {'role': 'assistant', 'content': 'Parijs.', 'ts': ''}]
        brain.current_context.update(_orig_ctx)
        r2 = brain.process_command('en van duitsland?')
        assert 'Berlijn' in r2, "vervolgvraag 'en van duitsland?' -> 'Berlijn'"
    print('\n===== 10: TIJD EN REKENEN =====\n')
    _reset_state()
    r = brain.process_command('hoe laat is het')
    assert 'het is' in r.lower() and any((ch.isdigit() for ch in r)), "'hoe laat is het' -> tijd-antwoord"
    _reset_state()
    r = brain.process_command('wat is 12 keer 4')
    assert '48' in r, "'wat is 12 keer 4' -> antwoord 48"
    print('\n===== 11: AGENT =====\n')
    _AGENT_PLANS = {'doelampuitenopenspotify': json.dumps({'steps': [{'tool_name': 'control_home_assistant', 'arguments': {'domain': 'light', 'service': 'turn_off', 'entity_id': 'light.bed_lamp', 'service_data': {}}, 'description': 'Lamp uitzetten'}, {'tool_name': 'open_program', 'arguments': {'program': 'spotify'}, 'description': 'Spotify openen'}]}), 'maakmijnpcklaaromtegamen': json.dumps({'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'steam'}, 'description': 'Steam openen'}, {'tool_name': 'set_volume', 'arguments': {'percent': 40}, 'description': 'Volume op 40%'}]}), 'opendiscordenspotify': json.dumps({'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'discord'}, 'description': 'Discord openen'}, {'tool_name': 'open_program', 'arguments': {'program': 'spotify'}, 'description': 'Spotify openen'}]}), 'ikgafilmen': json.dumps({'steps': [{'tool_name': 'open_program', 'arguments': {'program': 'premiere pro'}, 'description': 'Premiere Pro openen'}]})}

    def _agent_fake(*args, **kwargs):
        messages = kwargs.get('messages') or (args[0] if args else [])
        sys_text = ''
        last_user = ''
        for m in messages:
            if isinstance(m, dict):
                if m.get('role') == 'system':
                    sys_text += ' ' + str(m.get('content', ''))
                if m.get('role') == 'user':
                    last_user = m.get('content', '')
        key = _norm(last_user)
        if 'GEEF ALLEEN JSON' in sys_text.upper() and key in _AGENT_PLANS:
            msg = type('M', (), {'content': _AGENT_PLANS[key], 'tool_calls': None})()
            return type('R', (), {'message': msg})()
        msg = type('M', (), {'content': 'geen idee', 'tool_calls': None})()
        return type('R', (), {'message': msg})()
    with patch('core.ai.control_home_assistant_tool', return_value='Lamp is uit.') as m_agent_ha, patch('core.ai.open_program_tool', return_value='Programma geopend.') as m_agent_open, patch('core.ai.media_set_volume_tool', return_value='Volume op 40%.') as m_agent_vol, patch('core.ai.resolve_live_entity_id', side_effect=_resolve_fake), patch('core.tool_registry.get_tool_risk', return_value='low'):
        _ollama_mod.chat = _agent_fake
        ai.ollama.chat = _agent_fake
        _reset_state()
        brain.process_command('doe lamp uit en open spotify')
        assert m_agent_ha.called, 'agent multi-actie: HA-tool uitgevoerd'
        assert m_agent_open.called and m_agent_open.call_args[0][0] in ('spotify', 'Spotify'), "agent multi-actie: open_program('spotify') uitgevoerd"
        m_agent_open.reset_mock()
        m_agent_vol.reset_mock()
        m_agent_ha.reset_mock()
        _reset_state()
        brain.process_command('maak mijn pc klaar om te gamen')
        _opened = [c[0][0] for c in m_agent_open.call_args_list]
        assert any((p in ('Discord', 'discord') for p in _opened)), 'game-modus (routine): opent Discord'
        assert any((p in ('Spotify', 'spotify') for p in _opened)), 'game-modus (routine): opent Spotify'
        assert m_agent_vol.called and m_agent_vol.call_args[0][0] == 40, 'game-modus (routine): zet volume op 40'
        assert m_agent_ha.called, 'game-modus (routine): zet bedlamp aan (HA)'
        m_agent_open.reset_mock()
        _reset_state()
        brain.process_command('ik ga filmen')
        assert m_agent_open.called and any((p in ('premiere pro', 'Premiere Pro') for p in [c[0][0] for c in m_agent_open.call_args_list])), "agent doel 'ik ga filmen': open_program('premiere pro')"
        m_agent_open.reset_mock()
        _reset_state()
        brain.process_command('open discord en spotify')
        assert m_agent_open.called and m_agent_open.call_count >= 2, "agent multi-open: 'open discord en spotify' opent beide"
    print('\n===== 12: TOOL-DISPATCHER (execute_tool) =====\n')
    _DISPATCH_CASES = [('open_file', {'filename': 'notities.txt'}, 'open het bestand alsjeblieft', 'open_file_tool'), ('open_website', {'url': 'https://google.com'}, 'open de website alsjeblieft', 'open_website_tool'), ('open_program', {'program': 'spotify'}, 'open spotify alsjeblieft', 'open_program_tool'), ('close_program', {'program': 'spotify'}, 'sluit spotify alsjeblieft', 'close_program_tool'), ('remember', {'key': 'test_sleutel', 'value': 'testwaarde'}, 'onthoud dat alsjeblieft', 'remember_tool'), ('recall', {'key': 'test_sleutel'}, 'wat is test alsjeblieft', 'recall_tool'), ('forget', {'key': 'test_sleutel'}, 'vergeet test alsjeblieft', 'forget_tool'), ('media_play_pause', {}, 'speel muziek alsjeblieft', 'media_play_pause_tool'), ('media_next', {}, 'volgende nummer alsjeblieft', 'media_next_tool'), ('media_previous', {}, 'vorige nummer alsjeblieft', 'media_previous_tool'), ('media_stop', {}, 'stop de muziek alsjeblieft', 'media_stop_tool'), ('volume_up', {}, 'volume omhoog alsjeblieft', 'media_volume_up_tool'), ('volume_down', {}, 'volume omlaag alsjeblieft', 'media_volume_down_tool'), ('set_volume', {'percent': 30}, 'zet volume op 30 alsjeblieft', 'media_set_volume_tool'), ('media_mute', {}, 'demp het geluid alsjeblieft', 'media_mute_tool'), ('system_info', {}, 'toon systeeminformatie alsjeblieft', 'system_info_tool'), ('screenshot', {}, 'maak een screenshot alsjeblieft', 'screenshot_tool'), ('create_folder', {'name': 'testmap', 'location': ''}, 'maak een map alsjeblieft', 'create_folder_tool'), ('create_file', {'name': 'test.txt', 'location': ''}, 'maak een bestand alsjeblieft', 'create_file_tool'), ('list_files', {'location': 'C:\\Shots'}, 'toon de bestanden alsjeblieft', 'list_files_tool'), ('copy_file', {'filename': 'a.txt', 'location': 'Documenten'}, 'kopieer een bestand alsjeblieft', 'copy_file_tool'), ('move_file', {'filename': 'a.txt', 'location': 'Documenten'}, 'verplaats een bestand alsjeblieft', 'move_file_tool'), ('minimize_window', {'program': 'spotify'}, 'maak spotify kleiner alsjeblieft', 'minimize_window_tool'), ('maximize_window', {'program': 'spotify'}, 'vergroot spotify alsjeblieft', 'maximize_window_tool'), ('restore_window', {'program': 'spotify'}, 'herstel spotify alsjeblieft', 'restore_window_tool'), ('get_home_assistant_entities', {'domain': 'light'}, 'welke lampen zijn er alsjeblieft', 'get_home_assistant_entities_tool'), ('control_home_assistant', {'domain': 'light', 'service': 'turn_off', 'entity_id': 'light.bed_lamp', 'service_data': {}}, 'zet de lamp uit alsjeblieft', 'control_home_assistant_tool'), ('restart_program', {'program': 'spotify'}, 'herstart spotify alsjeblieft', 'restart_program_tool'), ('program_status', {'program': 'spotify'}, 'wat is de status van spotify alsjeblieft', 'program_status_tool'), ('find_program_location', {'program': 'spotify'}, 'waar staat spotify alsjeblieft', 'find_program_location_tool'), ('rename_file', {'old_name': 'a.txt', 'new_name': 'b.txt'}, 'hernoem a.txt naar b.txt alsjeblieft', 'rename_file_tool'), ('open_folder', {'location': 'Documenten'}, 'open de map Documenten alsjeblieft', 'open_folder_tool'), ('search_files', {'query': 'rapport'}, 'zoek naar rapport alsjeblieft', 'search_files_tool'), ('recent_files', {'count': 5}, 'toon mijn recente bestanden alsjeblieft', 'recent_files_tool'), ('browser_search', {'query': 'opencode', 'site': 'google'}, 'zoek opencode in de browser alsjeblieft', 'browser_search_tool'), ('browser_back', {}, 'ga terug in de browser alsjeblieft', 'browser_back_tool'), ('browser_forward', {}, 'ga vooruit in de browser alsjeblieft', 'browser_forward_tool'), ('browser_refresh', {}, 'ververs de browser alsjeblieft', 'browser_refresh_tool'), ('browser_new_tab', {}, 'open een nieuwe tab alsjeblieft', 'browser_new_tab_tool'), ('browser_close_tab', {}, 'sluit de tab alsjeblieft', 'browser_close_tab_tool'), ('browser_get_url', {}, 'welke url zit er open alsjeblieft', 'browser_get_url_tool'), ('browser_get_title', {}, 'wat is de titel van de pagina alsjeblieft', 'browser_get_title_tool'), ('browser_get_content', {'max_items': 20}, 'lees de pagina inhoud alsjeblieft', 'browser_get_content_tool'), ('pc_status', {}, 'toon de pc status alsjeblieft', 'pc_status_tool'), ('web_fetch', {'url': 'https://example.com'}, 'haal deze pagina op alsjeblieft', 'web_fetch_tool'), ('web_search', {'query': 'opencode'}, 'zoek opencode op internet alsjeblieft', 'web_search_tool'), ('web_search_and_fetch', {'query': 'opencode', 'max_pages': 2}, "zoek opencode en lees de pagina's alsjeblieft", 'web_search_and_fetch_tool'), ('ui_list_windows', {'filter': 'Sonar'}, 'lijst de vensters alsjeblieft', 'ui_list_windows_tool'), ('ui_find_window', {'title': 'Sonar'}, 'vind het venster Sonar alsjeblieft', 'ui_find_window_tool'), ('ui_activate_window', {'handle': 77}, 'activeer dat venster alsjeblieft', 'ui_activate_window_tool'), ('ui_list_elements', {'handle': 77, 'name_filter': ''}, 'lijst de elementen alsjeblieft', 'ui_list_elements_tool'), ('ui_find_element', {'handle': 77, 'name': 'spelen', 'control_type': 'Button'}, 'vind de knop spelen alsjeblieft', 'ui_find_element_tool'), ('ui_click_element', {'handle': 77, 'name': 'spelen', 'control_type': 'Button'}, 'klik op spelen alsjeblieft', 'ui_click_element_tool'), ('ui_type_text', {'handle': 77, 'text': 'hallo', 'element_name': 'veld'}, 'typ hallo alsjeblieft', 'ui_type_text_tool'), ('ui_get_value', {'handle': 77, 'name': 'volume'}, 'lees de waarde van volume alsjeblieft', 'ui_get_value_tool'), ('ui_set_value', {'handle': 77, 'value': 50, 'name': 'volume'}, 'zet volume op 50 alsjeblieft', 'ui_set_value_tool'), ('ui_launch_app', {'path': 'C:\\Program Files\\test.exe'}, 'start deze app alsjeblieft', 'ui_launch_app_tool'), ('audio_list_sessions', {}, 'welke apps maken geluid alsjeblieft', 'audio_list_sessions_tool'), ('audio_get_session_volume', {'app_name': 'spotify'}, 'wat is het volume van spotify alsjeblieft', 'audio_get_session_volume_tool'), ('audio_set_session_volume', {'app_name': 'spotify', 'volume': 40}, 'zet spotify op 40 alsjeblieft', 'audio_set_session_volume_tool'), ('audio_set_session_mute', {'app_name': 'spotify', 'muted': True}, 'demp spotify alsjeblieft', 'audio_set_session_mute_tool'), ('audio_toggle_session_mute', {'app_name': 'spotify'}, 'zet het geluid van spotify uit en aan alsjeblieft', 'audio_toggle_session_mute_tool'), ('audio_list_outputs', {}, 'welke audio uitgangen zijn er alsjeblieft', 'audio_list_outputs_tool'), ('audio_get_default_output', {}, 'wat is de audio uitgang alsjeblieft', 'audio_get_default_output_tool'), ('audio_set_default_output', {'device_name': 'headset'}, 'zet de audio uitgang op headset alsjeblieft', 'audio_set_default_output_tool')]
    _DISPATCH_MOCKS = {'open_file_tool': ('core.ai.open_file_tool', 'Bestand geopend.'), 'open_website_tool': ('core.ai.open_website_tool', 'Website geopend.'), 'open_program_tool': ('core.ai.open_program_tool', 'Programma geopend.'), 'close_program_tool': ('core.ai.close_program_tool', 'Programma gesloten.'), 'remember_tool': ('core.ai.remember_tool', 'Geheugen opgeslagen.'), 'recall_tool': ('core.ai.recall_tool', 'testwaarde'), 'forget_tool': ('core.ai.forget_tool', 'Vergeten.'), 'media_play_pause_tool': ('core.ai.media_play_pause_tool', 'Muziek gepauzeerd.'), 'media_next_tool': ('core.ai.media_next_tool', 'Volgend nummer.'), 'media_previous_tool': ('core.ai.media_previous_tool', 'Vorig nummer.'), 'media_stop_tool': ('core.ai.media_stop_tool', 'Muziek gestopt.'), 'media_volume_up_tool': ('core.ai.media_volume_up_tool', 'Volume omhoog.'), 'media_volume_down_tool': ('core.ai.media_volume_down_tool', 'Volume omlaag.'), 'media_set_volume_tool': ('core.ai.media_set_volume_tool', 'Volume op 30%.'), 'media_mute_tool': ('core.ai.media_mute_tool', 'Geluid gedempt.'), 'system_info_tool': ('core.ai.system_info_tool', 'systeeminformatie: i9'), 'screenshot_tool': ('core.ai.screenshot_tool', 'screenshot gemaakt'), 'create_folder_tool': ('core.ai.create_folder_tool', 'Map aangemaakt.'), 'create_file_tool': ('core.ai.create_file_tool', 'Bestand aangemaakt.'), 'list_files_tool': ('core.ai.list_files_tool', 'notities.txt'), 'copy_file_tool': ('core.ai.copy_file_tool', 'Kopie gemaakt.'), 'move_file_tool': ('core.ai.move_file_tool', 'Verplaatst.'), 'minimize_window_tool': ('core.ai.minimize_window_tool', 'Verkleind.'), 'maximize_window_tool': ('core.ai.maximize_window_tool', 'Vergroot.'), 'restore_window_tool': ('core.ai.restore_window_tool', 'Hersteld.'), 'get_home_assistant_entities_tool': ('core.ai.get_home_assistant_entities_tool', 'light.bed_lamp'), 'control_home_assistant_tool': ('core.ai.control_home_assistant_tool', 'Actie uitgevoerd.'), 'restart_program_tool': ('core.ai.restart_program_tool', 'Programma herstart.'), 'program_status_tool': ('core.ai.program_status_tool', 'Programma draait.'), 'find_program_location_tool': ('core.ai.find_program_location_tool', 'C:\\Programs\\spotify.lnk'), 'rename_file_tool': ('core.ai.rename_file_tool', 'Bestand hernoemd.'), 'open_folder_tool': ('core.ai.open_folder_tool', 'Map geopend.'), 'search_files_tool': ('core.ai.search_files_tool', 'bestanden gevonden'), 'recent_files_tool': ('core.ai.recent_files_tool', 'recente bestanden'), 'browser_search_tool': ('core.ai.browser_search_tool', 'Gezocht in browser.'), 'browser_back_tool': ('core.ai.browser_back_tool', 'Browser terug.'), 'browser_forward_tool': ('core.ai.browser_forward_tool', 'Browser vooruit.'), 'browser_refresh_tool': ('core.ai.browser_refresh_tool', 'Browser ververst.'), 'browser_new_tab_tool': ('core.ai.browser_new_tab_tool', 'Nieuwe tab geopend.'), 'browser_close_tab_tool': ('core.ai.browser_close_tab_tool', 'Tab gesloten.'), 'browser_get_url_tool': ('core.ai.browser_get_url_tool', 'https://example.com'), 'browser_get_title_tool': ('core.ai.browser_get_title_tool', 'Testpagina'), 'browser_get_content_tool': ('core.ai.browser_get_content_tool', 'inhoud gelezen'), 'pc_status_tool': ('core.ai.pc_status_tool', 'PC-status ok'), 'web_fetch_tool': ('core.ai.web_fetch_tool', 'pagina opgehaald'), 'web_search_tool': ('core.ai.web_search_tool', 'zoekresultaten'), 'web_search_and_fetch_tool': ('core.ai.web_search_and_fetch_tool', "zoekresultaten en pagina's"), 'ui_list_windows_tool': ('core.ai.ui_list_windows_tool', 'vensterlijst'), 'ui_find_window_tool': ('core.ai.ui_find_window_tool', 'venster gevonden'), 'ui_activate_window_tool': ('core.ai.ui_activate_window_tool', 'venster geactiveerd'), 'ui_list_elements_tool': ('core.ai.ui_list_elements_tool', 'elementenlijst'), 'ui_find_element_tool': ('core.ai.ui_find_element_tool', 'element gevonden'), 'ui_click_element_tool': ('core.ai.ui_click_element_tool', 'geklikt'), 'ui_type_text_tool': ('core.ai.ui_type_text_tool', 'tekst getypt'), 'ui_get_value_tool': ('core.ai.ui_get_value_tool', 'waarde gelezen'), 'ui_set_value_tool': ('core.ai.ui_set_value_tool', 'waarde gezet'), 'ui_launch_app_tool': ('core.ai.ui_launch_app_tool', 'app gestart'), 'audio_list_sessions_tool': ('core.ai.audio_list_sessions_tool', 'audio sessies'), 'audio_get_session_volume_tool': ('core.ai.audio_get_session_volume_tool', '50'), 'audio_set_session_volume_tool': ('core.ai.audio_set_session_volume_tool', 'volume gezet'), 'audio_set_session_mute_tool': ('core.ai.audio_set_session_mute_tool', 'gedempt'), 'audio_toggle_session_mute_tool': ('core.ai.audio_toggle_session_mute_tool', 'mute gewisseld'), 'audio_list_outputs_tool': ('core.ai.audio_list_outputs_tool', 'outputs'), 'audio_get_default_output_tool': ('core.ai.audio_get_default_output_tool', 'speakers'), 'audio_set_default_output_tool': ('core.ai.audio_set_default_output_tool', 'output gewisseld')}
    _dispatch_patches = []
    _dispatch_mock_by_target = {}
    for _t in sorted({t for _, _, _, t in _DISPATCH_CASES}):
        _dpath, _dret = _DISPATCH_MOCKS[_t]
        _po = patch(_dpath, return_value=_dret)
        _dispatch_patches.append(_po)
        _dispatch_mock_by_target[_t] = _po.start()
    _patch_resolve = patch('core.ai.resolve_live_entity_id', side_effect=_resolve_fake)
    _patch_resolve.start()
    _patch_risk = patch('core.tool_registry.get_tool_risk', return_value='low')
    _patch_risk.start()
    for _tool_name, _args, _question, _target in _DISPATCH_CASES:
        _dmock = _dispatch_mock_by_target[_target]
        _dmock.reset_mock()
        _result = ai.execute_tool(_tool_name, _args, _question)
        assert _dmock.called, f"execute_tool('{_tool_name}') roept tool aan"
    _patch_risk.stop()
    _patch_approval.stop()
    _ollama_mod.chat = _orig_ollama_chat
    ai.ollama.chat = _orig_ollama_chat
    _patch_save.stop()
    _memory_patch.stop()
    for _p in _dispatch_patches:
        _p.stop()
    _patch_resolve.stop()
    try:
        _routines_patch.stop()
    except Exception:
        pass
    try:
        _routines_mod._manager.reload()
    except Exception:
        pass
    try:
        os.remove(_tmp_mem)
        os.remove(_tmp_routines)
    except OSError:
        pass
    print()
    print('=' * 60)
    print('=' * 60)
