import sys
import os
import io
from unittest.mock import patch, MagicMock
import core.retry as retry
import actions.status as status
import actions.system as sys_mod
import actions.audio as aud_mod
import actions.browser as br_mod

def test_main():
    """
JARVIS - Fase 12: Status + Fallback tests
===========================================

Test de Unified PC-status en de Fallback Chains (alles gemockt):

  [1] retry: primaire tool werkt -> done, geen fallback
  [2] retry: primaire tool faalt altijd -> failed
  [3] retry: primaire tool faalt, fallback werkt -> done + fallback_used
  [4] retry: fallback-args transformatie
  [5] retry: geen fallback gedefinieerd -> gewoon failed
  [6] pc_status: systeem + audio + browser in één dict
  [7] pc_status: audio-fout breekt niks op
  [8] pc_status: browser-fout breekt niks op
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def runner_ok(tool, args, q):
        return 'geslaagd'
    r = retry.execute_with_retry(runner_ok, 'ui_click_element', {}, 'test', max_retries=1)
    assert r['status'] == 'done' and r.get('fallback_used') is None, '1. tool werkt -> done, geen fallback'

    def runner_fail(tool, args, q):
        raise RuntimeError('kan niet')
    r = retry.execute_with_retry(runner_fail, 'bestaat_niet', {}, 'test', max_retries=1)
    assert r['status'] == 'failed', '2. tool faalt altijd -> failed'

    def runner_with_fallback(tool, args, q):
        if tool == 'browser_search':
            raise RuntimeError('browser kapot')
        if tool == 'web_search':
            return 'gezocht op web'
        raise RuntimeError(f'onbekend: {tool}')
    r = retry.execute_with_retry(runner_with_fallback, 'browser_search', {'query': 'katten', 'site': 'youtube'}, 'zoek katten', max_retries=1, use_fallbacks=True)
    assert r['status'] == 'done' and r.get('fallback_used') == 'web_search', '3. fallback werkt -> done met fallback_used'

    def runner_transform(tool, args, q):
        if tool == 'browser_search':
            raise RuntimeError('browser kapot')
        if tool == 'web_search':
            assert args.get('query') == 'hondjes', str(args)
            return 'gezocht op web'
        raise RuntimeError(f'onbekend: {tool}')
    r = retry.execute_with_retry(runner_transform, 'browser_search', {'query': 'hondjes', 'site': 'youtube'}, 'zoek hondjes', max_retries=1, use_fallbacks=True)
    assert r['status'] == 'done' and r.get('fallback_used') == 'web_search', '4. fallback transform_args -> correcte args'

    def runner_no_fallback(tool, args, q):
        raise RuntimeError('mislukt')
    r = retry.execute_with_retry(runner_no_fallback, 'nooit_bestaand', {}, 'test', max_retries=1, use_fallbacks=True)
    assert r['status'] == 'failed', '5. geen fallback -> failed'
    base_system = MagicMock(cpu_info=lambda: {'naam': 'AMD Ryzen'}, ram_info=lambda: {'totaal': 32, 'vrij': 16}, disk_info=lambda: {'vrij': 100, 'totaal': 500}, battery_info=lambda: {'percentage': 80, 'stekker': True}, os_info=lambda: {'systeem': 'Windows', 'release': '11', 'machine': 'AMD64'}, uptime=lambda: {'dagen': 1, 'uren': 2, 'minuten': 3})
    base_audio = MagicMock(get_default_output=lambda: {'ok': True, 'name': 'Headset'}, list_sessions=lambda: {'ok': True, 'sessions': [{'name': 'Spotify.exe', 'volume': 50, 'muted': False}, {'name': 'Discord.exe', 'volume': 80, 'muted': True}]})
    base_browser = MagicMock(get_browser_url=lambda: {'ok': True, 'url': 'https://www.google.com'}, get_browser_title=lambda: {'ok': True, 'title': 'Google'})
    _orig_sys = {n: getattr(sys_mod, n) for n in ('cpu_info', 'ram_info', 'disk_info', 'battery_info', 'os_info', 'uptime')}
    _orig_aud = {n: getattr(aud_mod, n) for n in ('get_default_output', 'list_sessions')}
    _orig_br = {n: getattr(br_mod, n) for n in ('get_browser_url', 'get_browser_title')}
    sys_mod.cpu_info = base_system.cpu_info
    sys_mod.ram_info = base_system.ram_info
    sys_mod.disk_info = base_system.disk_info
    sys_mod.battery_info = base_system.battery_info
    sys_mod.os_info = base_system.os_info
    sys_mod.uptime = base_system.uptime
    aud_mod.get_default_output = base_audio.get_default_output
    aud_mod.list_sessions = base_audio.list_sessions
    br_mod.get_browser_url = base_browser.get_browser_url
    br_mod.get_browser_title = base_browser.get_browser_title
    try:
        r = status.get_pc_status()
        assert r.get('ok') and 'systeem' in r and ('audio' in r) and ('browser' in r), '6. pc_status: volledig overzicht'
        assert r['systeem']['cpu'] == 'AMD Ryzen' and r['browser']['url'].startswith('https:'), '6b. pc_status: CPU naam + browser URL opgehaald'
    finally:
        for n, v in _orig_sys.items():
            setattr(sys_mod, n, v)
        for n, v in _orig_aud.items():
            setattr(aud_mod, n, v)
        for n, v in _orig_br.items():
            setattr(br_mod, n, v)
    sys_mod.cpu_info = base_system.cpu_info
    sys_mod.ram_info = base_system.ram_info
    sys_mod.disk_info = base_system.disk_info
    sys_mod.battery_info = base_system.battery_info
    sys_mod.os_info = base_system.os_info
    sys_mod.uptime = base_system.uptime
    aud_mod.get_default_output = MagicMock(side_effect=Exception('COM fout'))
    aud_mod.list_sessions = base_audio.list_sessions
    br_mod.get_browser_url = base_browser.get_browser_url
    br_mod.get_browser_title = base_browser.get_browser_title
    try:
        r = status.get_pc_status()
        assert isinstance(r.get('audio'), str) and 'fout' in r.get('audio', ''), '7. pc_status: audio-fout geen crash'
    finally:
        for n, v in _orig_sys.items():
            setattr(sys_mod, n, v)
        for n, v in _orig_aud.items():
            setattr(aud_mod, n, v)
        for n, v in _orig_br.items():
            setattr(br_mod, n, v)
    sys_mod.cpu_info = base_system.cpu_info
    sys_mod.ram_info = base_system.ram_info
    sys_mod.disk_info = base_system.disk_info
    sys_mod.battery_info = base_system.battery_info
    sys_mod.os_info = base_system.os_info
    sys_mod.uptime = base_system.uptime
    aud_mod.get_default_output = base_audio.get_default_output
    aud_mod.list_sessions = base_audio.list_sessions
    br_mod.get_browser_url = MagicMock(side_effect=Exception('UIA fout'))
    br_mod.get_browser_title = base_browser.get_browser_title
    try:
        r = status.get_pc_status()
        assert isinstance(r.get('browser'), str) and 'fout' in r.get('browser', ''), '8. pc_status: browser-fout geen crash'
    finally:
        for n, v in _orig_sys.items():
            setattr(sys_mod, n, v)
        for n, v in _orig_aud.items():
            setattr(aud_mod, n, v)
        for n, v in _orig_br.items():
            setattr(br_mod, n, v)
