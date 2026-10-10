import sys
import os
from unittest.mock import patch
import core.brain as _brain
import core.ai as _ai
from core.brain import process_command

def test_main():
    """
FASE 11.1 — End-to-end natuurlijke context-flows.

Draait de exacte flows uit de opdracht door de volledige pipeline
(process_command) heen, met gemockte AI + tools + entity-resolutie,
zodat verifierebaar is dat verwijzingen tussendoor correct blijven
koppelen aan het meest relevante recente apparaat/programma.
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def reset():
        _ai.current_context.update({'last_command': '', 'last_result': '', 'last_action': '', 'last_calculation': '', 'last_program': '', 'last_file': '', 'last_website': '', 'last_ha_entity': '', 'last_ha_domain': '', 'last_ha_name': '', 'pending_choice': None})
    pc_calls = []
    ha_calls = []
    ai_log = []

    def fake_min(p):
        pc_calls.append(('minimize', p))
        return f'{p} geminimaliseerd.'

    def fake_cls(p):
        pc_calls.append(('close', p))
        return f'{p} gesloten.'

    def fake_ope(p):
        pc_calls.append(('open', p))
        return f'{p} geopend.'

    def fake_ha(d, s, e, sd=None):
        ha_calls.append((d, s, e, sd or {}))
        return f'{e} is {s} (ok).'

    def fake_resolve(e, d):
        known = {'light.bed_lamp', 'light.woonkamer'}
        return (e, 'exact', '') if e in known else (None, 'none', f'geen match {e}')

    def run(cmd):
        with patch.object(_brain, 'minimize_program', side_effect=fake_min), patch.object(_brain, 'close_program_tool', side_effect=fake_cls), patch.object(_brain, 'open_program_tool', side_effect=fake_ope), patch.object(_brain, 'control_home_assistant_tool', side_effect=fake_ha), patch.object(_ai, 'control_home_assistant_tool', side_effect=fake_ha), patch.object(_ai, 'resolve_live_entity_id', side_effect=fake_resolve), patch.object(_ai.ollama, 'chat', side_effect=_mk_ai(cmd)):
            return process_command(cmd)

    def _mk_ai(cmd):
        c = cmd.lower()

        def fake_chat(*a, **kw):
            calls = []
            if 'bedlamp' in c and 'aan' in c:
                calls = [('control_home_assistant', {'domain': 'light', 'entity_id': 'light.bed_lamp', 'service': 'turn_on'})]
            elif 'woonkamer' in c:
                calls = [('control_home_assistant', {'domain': 'light', 'entity_id': 'light.woonkamer', 'service': 'turn_on'})]
            made = [type('TC', (), {'function': type('F', (), {'name': n, 'arguments': a})()})() for n, a in calls]

            class _M:
                content = ''
                tool_calls = made if made else None
            return type('R', (), {'message': _M()})()
        return fake_chat
    print('\n=== FASE 11.1 END-TO-END FLOWS ===\n')
    print('[FLOW PC] open Discord -> maak hem kleiner -> sluit hem\n')
    reset()
    pc_calls.clear()
    run('open Discord')
    assert pc_calls == [('open', 'discord')], 'open Discord -> pc open discord'
    pc_calls.clear()
    run('maak hem kleiner')
    assert pc_calls == [('minimize', 'discord')], 'maak hem kleiner -> minimize discord'
    pc_calls.clear()
    run('sluit hem')
    assert pc_calls == [('close', 'discord')], 'sluit hem -> close discord'
    print('\n[FLOW HA] zet mijn bedlamp aan -> maak hem groen -> zet hem op 30% -> doe hem uit\n')
    reset()
    ha_calls.clear()
    run('zet mijn bedlamp aan')
    assert ha_calls and ha_calls[0][2] == 'light.bed_lamp' and (ha_calls[0][1] == 'turn_on'), 'aan -> bed_lamp turn_on'
    assert _ai.current_context['last_ha_entity'] == 'light.bed_lamp', 'last_ha = bed_lamp'
    ha_calls.clear()
    run('maak hem groen')
    assert ha_calls and ha_calls[0][2] == 'light.bed_lamp' and (ha_calls[0][3].get('hs_color') == [120, 100]), 'groen -> bed_lamp hs_color'
    ha_calls.clear()
    run('zet hem op 30%')
    assert ha_calls and ha_calls[0][3].get('brightness_pct') == 30, '30% -> bed_lamp brightness 30'
    ha_calls.clear()
    run('doe hem uit')
    assert ha_calls and ha_calls[0][2] == 'light.bed_lamp' and (ha_calls[0][1] == 'turn_off'), 'uit -> bed_lamp turn_off'
    print('\n[FLOW GEMENGD] open Discord -> zet mijn bedlamp aan -> maak hem blauw\n')
    reset()
    pc_calls.clear()
    ha_calls.clear()
    run('open Discord')
    run('zet mijn bedlamp aan')
    assert _ai.current_context['last_program'] == 'discord' and _ai.current_context['last_ha_entity'] == 'light.bed_lamp', 'na beide: last_program=discord én last_ha=bed_lamp'
    ha_calls.clear()
    run('maak hem blauw')
    assert ha_calls and ha_calls[0][2] == 'light.bed_lamp' and (ha_calls[0][3].get('hs_color') == [240, 100]), 'maak hem blauw -> HA bed_lamp (niet pc discord)'
