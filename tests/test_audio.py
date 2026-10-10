import sys
import os
import io
from unittest.mock import patch, MagicMock
import actions.audio as audio
from core.result_validation import ToolResult

def test_main():
    """
JARVIS - Fase 11: Audio tests
==============================

Test de audio-laag (actions/audio.py) ZONDER echte Windows-audio
(alles gemockt):

  [1] pycaw NIET beschikbaar -> nette foutmelding (geen crash)
  [2] list_sessions: meerdere apps + volumes + mute
  [3] get_session_volume: exacte naam
  [4] get_session_volume: bevat-match zonder .exe
  [5] get_session_volume: niet gevonden -> nette fout
  [6] set_session_volume: geldig percentage
  [7] set_session_volume: fout percentage -> foute_waarde
  [8] set_session_volume: app niet gevonden -> session_niet_gevonden
  [9] set_session_mute: dempen
  [10] toggle_session_mute: omdraaien
  [11] list_output_devices: alleen ACTIVE + render + Sonar-markering
  [12] get_default_output: leest FriendlyName
  [13] set_default_output: substring-match "headset" -> Hoofdtelefoon
  [14] set_default_output: sonar multi-woord match
  [15] set_default_output: niet gevonden -> apparaat_niet_gevonden
  [16] Veiligheid: elke functie retourneert een ToolResult
"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _proc(name):
        p = MagicMock()
        p.pid = 1234
        p.name.return_value = name
        return p

    def _sav(volume=0.8, mute=False):
        s = MagicMock()
        s.GetMasterVolume.return_value = volume
        s.GetMute.return_value = mute
        s.SetMasterVolume.return_value = None
        s.SetMute.return_value = None
        return s

    def _session(name, volume=0.8, mute=False):
        s = MagicMock()
        s.Process = _proc(name)
        s.SimpleAudioVolume = _sav(volume, mute)
        return s

    def fake_audio_utilities(module):
        """Build a fake module with AudioUtilities for _import_pycaw patch."""
        return module

    def _make_pycaw_mock(sessions=None, speakers_name='SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)', devices=None, only_render_flow=True):
        pycaw_mod = MagicMock()

        class FakeEDataFlow:
            eRender = MagicMock()
            eRender.value = 0
            eCapture = 1
            eAll = 2

        class FakeDevState:
            ACTIVE = 1
            DISABLED = 2
            NOTPRESENT = 4
            UNPLUGGED = 8
            MASK_ALL = 15
        AU = MagicMock()

        def _make_audio_device(name, state, flow):
            dev = MagicMock()
            dev.FriendlyName = name
            dev.state = MagicMock()
            dev.state.name = state
            dev.id = f'id-{name}'
            return dev
        if sessions is not None:
            AU.GetAllSessions.return_value = sessions
        if devices is not None:
            AU.GetAllDevices.return_value = devices
        else:
            AU.GetAllDevices.return_value = [_make_audio_device('Hoofdtelefoon (HyperX Cloud III S Wireless)', 'Active', 0), _make_audio_device('SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)', 'Active', 0), _make_audio_device('SteelSeries Sonar - Chat (SteelSeries Sonar Virtual Audio Device)', 'Active', 0), _make_audio_device('Microfoon (HyperX Cloud III S Wireless)', 'Active', 1), _make_audio_device('Realtek Digital Output', 'NotPresent', 0)]
        if speakers_name:
            sp = MagicMock()
            sp.FriendlyName = 'Hoofdtelefoon (HyperX Cloud III S Wireless)'
            AU.GetSpeakers.return_value = sp
        pycaw_mod.AudioUtilities = AU
        pycaw_mod.EDataFlow = FakeEDataFlow
        pycaw_mod.ISimpleAudioVolume = MagicMock()
        return pycaw_mod

    def _enter(pycaw_mod):
        return patch.object(audio, '_import_pycaw', return_value=(pycaw_mod.AudioUtilities, pycaw_mod.EDataFlow, pycaw_mod.ISimpleAudioVolume))
    print('=== FASE 11: AUDIO (actions/audio.py) ===\n')
    with patch.object(audio, '_import_pycaw', return_value=None):
        r = audio.list_sessions()
        assert r.error_kind == 'audio_unavailable' and r.ok is False, '1. pycaw ontbreekt -> audio_unavailable (list_sessions)'
    with patch.object(audio, '_import_pycaw', return_value=None):
        r = audio.list_output_devices()
        assert r.error_kind == 'audio_unavailable' and r.ok is False, '1b. pycaw ontbreekt -> audio_unavailable (list_output_devices)'
    m = _make_pycaw_mock(sessions=[_session('Discord.exe', 0.9, False), _session('Spotify.exe', 0.5, True), _session('Systeem', 1.0, False)])
    with _enter(m):
        r = audio.list_sessions()
        assert r.ok and (r.data or {}).get('count') == 3, '2. list_sessions -> 3 sessions met volume/mute'
        discord = [s for s in (r.data or {}).get('sessions', []) if s['name'] == 'Discord.exe']
        assert discord and discord[0]['volume'] == 90 and (discord[0]['muted'] is False), '2b. Discord volume 90, niet gedempt'
    with _enter(m):
        vol = audio.get_session_volume('discord')
        assert vol.ok and (vol.data or {}).get('name') == 'Discord.exe', "3. get_session_volume('discord') zonder .exe -> gevonden"
    with _enter(m):
        r = audio.get_session_volume('spotify')
        assert r.ok and (r.data or {}).get('muted') is True, "4. get_session_volume('spotify') -> gedempt=True"
    with _enter(m):
        r = audio.get_session_volume('bestaatniet')
        assert not r.ok and r.error_kind == 'session_niet_gevonden', '5. onbekende app -> session_niet_gevonden'
    m = _make_pycaw_mock(sessions=[_session('Discord.exe', 0.5, False)])
    with _enter(m):
        r = audio.set_session_volume('discord', 75)
        assert r.ok and (r.data or {}).get('volume') == 75, "6. set_session_volume('discord', 75) -> ok"
    with _enter(m):
        r = audio.set_session_volume('discord', 'abc')
        assert not r.ok and r.error_kind == 'foute_waarde', '7. set_session_volume invalid -> foute_waarde'
    with _enter(m):
        r = audio.set_session_volume('bestaatniet', 50)
        assert not r.ok and r.error_kind == 'session_niet_gevonden', '8. set_session_volume onbekend -> session_niet_gevonden'
    m = _make_pycaw_mock(sessions=[_session('Discord.exe', 0.5, False)])
    with _enter(m):
        r = audio.set_session_mute('discord', True)
        assert r.ok and (r.data or {}).get('muted') is True, "9. set_session_mute('discord', True) -> gedempt"
    m = _make_pycaw_mock(sessions=[_session('Discord.exe', 0.5, True)])
    with _enter(m):
        r = audio.toggle_session_mute('discord')
        assert r.ok and (r.data or {}).get('muted') is False, '10. toggle_session_mute (was gedempt) -> niet meer gedempt'

    def _dev_ok(name, state='Active', flow=0):
        d = MagicMock()
        d.FriendlyName = name
        d.state = MagicMock()
        d.state.name = state
        d.id = f'id-{name}'
        return d
    m = _make_pycaw_mock(devices=[_dev_ok('Microfoon (Webcam)', 'Active'), _dev_ok('Hoofdtelefoon (HyperX Cloud III S Wireless)', 'Active'), _dev_ok('SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)', 'Active'), _dev_ok('Realtek Digital Output', 'NotPresent')])
    with _enter(m):
        r = audio.list_output_devices()
        names = [d['name'] for d in (r.data or {}).get('devices', [])]
        assert r.ok and 'Hoofdtelefoon (HyperX Cloud III S Wireless)' in names and ('Realtek Digital Output' not in names), '11. list_output_devices: alleen Active + geen microfoon (input)'
        sonar_dev = next((d for d in (r.data or {}).get('devices', []) if d.get('is_sonar')), None)
        assert sonar_dev is not None and 'Gaming' in sonar_dev['name'], '11b. Sonar-gaming gemarkeerd als is_sonar'
    m = _make_pycaw_mock(speakers_name='Hoofdtelefoon (HyperX Cloud III S Wireless)')
    with _enter(m):
        r = audio.get_default_output()
        assert r.ok and (r.data or {}).get('name') == 'Hoofdtelefoon (HyperX Cloud III S Wireless)', '12. get_default_output -> FriendlyName'
    m_devs = [_dev_ok('Hoofdtelefoon (HyperX Cloud III S Wireless)'), _dev_ok('Luidsprekers (DualSense Wireless Controller)'), _dev_ok('SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)')]
    m = _make_pycaw_mock(devices=m_devs, speakers_name='SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)')
    with _enter(m), patch.object(audio, '_get_device_id', side_effect=lambda n: '{\\aid}'):
        r = audio.set_default_output('de headset')
        assert r.ok and 'Hoofdtelefoon' in (r.data or {}).get('name', ''), "13. set_default_output('de headset') -> Hoofdtelefoon gevonden + gewisseld"
    with _enter(m), patch.object(audio, '_get_device_id', side_effect=lambda n: '{\\aid}'):
        r = audio.set_default_output('sonar gaming')
        assert r.ok and 'Sonar - Gaming' in (r.data or {}).get('name', ''), "14. set_default_output('sonar gaming') -> Sonar Gaming gevonden"
    m = _make_pycaw_mock(devices=m_devs, speakers_name='SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)')
    with _enter(m):
        r = audio.set_default_output('onbekendapparaat')
        assert not r.ok and r.error_kind == 'apparaat_niet_gevonden', '15. onbekend apparaat -> apparaat_niet_gevonden'
    for fn, args in [(audio.list_sessions, ()), (audio.get_session_volume, ('x',)), (audio.set_session_volume, ('x', 50)), (audio.set_session_mute, ('x', True)), (audio.toggle_session_mute, ('x',)), (audio.list_output_devices, ()), (audio.get_default_output, ()), (audio.set_default_output, ('x',))]:
        with _enter(_make_pycaw_mock(sessions=[], speakers_name='Mock Output')):
            r = fn(*args)
            assert isinstance(r, ToolResult) and isinstance(r.message, str), f'16. {fn.__name__}: retourneert ToolResult'
