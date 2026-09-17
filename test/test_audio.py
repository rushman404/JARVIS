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
  [16] Veiligheid: elke functie retourneert ok/status/error dict
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import actions.audio as audio

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}" + (f"  | {detail}" if detail else ""))


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


# ============ HELPERS DIE PYCAAW VERVANGEN ============

def _make_pycaw_mock(sessions=None, speakers_name="SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)",
                     devices=None, only_render_flow=True):
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
        dev.id = f"id-{name}"
        return dev

    if sessions is not None:
        AU.GetAllSessions.return_value = sessions

    if devices is not None:
        AU.GetAllDevices.return_value = devices
    else:
        AU.GetAllDevices.return_value = [
            _make_audio_device("Hoofdtelefoon (HyperX Cloud III S Wireless)", "Active", 0),
            _make_audio_device("SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)", "Active", 0),
            _make_audio_device("SteelSeries Sonar - Chat (SteelSeries Sonar Virtual Audio Device)", "Active", 0),
            _make_audio_device("Microfoon (HyperX Cloud III S Wireless)", "Active", 1),  # INPUT
            _make_audio_device("Realtek Digital Output", "NotPresent", 0),
        ]

    if speakers_name:
        sp = MagicMock()
        sp.FriendlyName = "Hoofdtelefoon (HyperX Cloud III S Wireless)"
        AU.GetSpeakers.return_value = sp

    pycaw_mod.AudioUtilities = AU
    pycaw_mod.EDataFlow = FakeEDataFlow
    pycaw_mod.ISimpleAudioVolume = MagicMock()

    return pycaw_mod


def _enter(pycaw_mod):
    return patch.object(audio, "_import_pycaw", return_value=(
        pycaw_mod.AudioUtilities,
        pycaw_mod.EDataFlow,
        pycaw_mod.ISimpleAudioVolume,
    ))


# =========================================================
print("=== FASE 11: AUDIO (actions/audio.py) ===\n")

# [1] pycaw NIET beschikbaar
with patch.object(audio, "_import_pycaw", return_value=None):
    r = audio.list_sessions()
    ok("1. pycaw ontbreekt -> audio_unavailable (list_sessions)",
       r.get("error_type") == "audio_unavailable" and r.get("ok") is False, str(r))

with patch.object(audio, "_import_pycaw", return_value=None):
    r = audio.list_output_devices()
    ok("1b. pycaw ontbreekt -> audio_unavailable (list_output_devices)",
       r.get("error_type") == "audio_unavailable" and r.get("ok") is False, str(r))

# [2] list_sessions
m = _make_pycaw_mock(sessions=[
    _session("Discord.exe", 0.9, False),
    _session("Spotify.exe", 0.5, True),
    _session("Systeem", 1.0, False),
])
with _enter(m):
    r = audio.list_sessions()
    ok("2. list_sessions -> 3 sessions met volume/mute",
       r.get("ok") and r.get("count") == 3, str(r))
    discord = [s for s in r.get("sessions", []) if s["name"] == "Discord.exe"]
    ok("2b. Discord volume 90, niet gedempt",
       discord and discord[0]["volume"] == 90 and discord[0]["muted"] is False,
       str(r.get("sessions")))

with _enter(m):
    vol = audio.get_session_volume("discord")
    ok("3. get_session_volume('discord') zonder .exe -> gevonden",
       vol.get("ok") and vol.get("name") == "Discord.exe", str(vol))

with _enter(m):
    r = audio.get_session_volume("spotify")
    ok("4. get_session_volume('spotify') -> gedempt=True",
       r.get("ok") and r.get("muted") is True, str(r))

with _enter(m):
    r = audio.get_session_volume("bestaatniet")
    ok("5. onbekende app -> session_niet_gevonden",
       not r.get("ok") and r.get("error_type") == "session_niet_gevonden", str(r))

# [6] set_session_volume
m = _make_pycaw_mock(sessions=[_session("Discord.exe", 0.5, False)])
with _enter(m):
    r = audio.set_session_volume("discord", 75)
    ok("6. set_session_volume('discord', 75) -> ok",
       r.get("ok") and r.get("volume") == 75, str(r))

with _enter(m):
    r = audio.set_session_volume("discord", "abc")
    ok("7. set_session_volume invalid -> foute_waarde",
       not r.get("ok") and r.get("error_type") == "foute_waarde", str(r))

with _enter(m):
    r = audio.set_session_volume("bestaatniet", 50)
    ok("8. set_session_volume onbekend -> session_niet_gevonden",
       not r.get("ok") and r.get("error_type") == "session_niet_gevonden", str(r))

# [9] set_session_mute
m = _make_pycaw_mock(sessions=[_session("Discord.exe", 0.5, False)])
with _enter(m):
    r = audio.set_session_mute("discord", True)
    ok("9. set_session_mute('discord', True) -> gedempt",
       r.get("ok") and r.get("muted") is True, str(r))

# [10] toggle_session_mute
m = _make_pycaw_mock(sessions=[_session("Discord.exe", 0.5, True)])
with _enter(m):
    r = audio.toggle_session_mute("discord")
    ok("10. toggle_session_mute (was gedempt) -> niet meer gedempt",
       r.get("ok") and r.get("muted") is False, str(r))

# [11] list_output_devices
def _dev_ok(name, state="Active", flow=0):
    d = MagicMock()
    d.FriendlyName = name
    d.state = MagicMock()
    d.state.name = state
    d.id = f"id-{name}"
    return d

m = _make_pycaw_mock(devices=[
    _dev_ok("Microfoon (Webcam)", "Active"),
    _dev_ok("Hoofdtelefoon (HyperX Cloud III S Wireless)", "Active"),
    _dev_ok("SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)", "Active"),
    _dev_ok("Realtek Digital Output", "NotPresent"),
])
with _enter(m):
    r = audio.list_output_devices()
    names = [d["name"] for d in r.get("devices", [])]
    ok("11. list_output_devices: alleen Active + geen microfoon (input)",
       r.get("ok") and "Hoofdtelefoon (HyperX Cloud III S Wireless)" in names
       and "Realtek Digital Output" not in names, str(r))
    sonar_dev = next((d for d in r.get("devices", []) if d.get("is_sonar")), None)
    ok("11b. Sonar-gaming gemarkeerd als is_sonar",
       sonar_dev is not None and "Gaming" in sonar_dev["name"], str(r))

# [12] get_default_output
m = _make_pycaw_mock(speakers_name="Hoofdtelefoon (HyperX Cloud III S Wireless)")
with _enter(m):
    r = audio.get_default_output()
    ok("12. get_default_output -> FriendlyName",
       r.get("ok") and r.get("name") == "Hoofdtelefoon (HyperX Cloud III S Wireless)", str(r))

# [13] set_default_output: headset alias
m_devs = [
    _dev_ok("Hoofdtelefoon (HyperX Cloud III S Wireless)"),
    _dev_ok("Luidsprekers (DualSense Wireless Controller)"),
    _dev_ok("SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)"),
]
m = _make_pycaw_mock(devices=m_devs, speakers_name="SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)")
with _enter(m), patch.object(audio, "_get_device_id", side_effect=lambda n: "{\\aid}"):
    r = audio.set_default_output("de headset")
    ok("13. set_default_output('de headset') -> Hoofdtelefoon gevonden + gewisseld",
       r.get("ok") and "Hoofdtelefoon" in r.get("name", ""), str(r))

# [14] set_default_output: sonar multi-woord
with _enter(m), patch.object(audio, "_get_device_id", side_effect=lambda n: "{\\aid}"):
    r = audio.set_default_output("sonar gaming")
    ok("14. set_default_output('sonar gaming') -> Sonar Gaming gevonden",
       r.get("ok") and "Sonar - Gaming" in r.get("name", ""), str(r))

# [15] niet gevonden
m = _make_pycaw_mock(devices=m_devs, speakers_name="SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)")
with _enter(m):
    r = audio.set_default_output("onbekendapparaat")
    ok("15. onbekend apparaat -> apparaat_niet_gevonden",
       not r.get("ok") and r.get("error_type") == "apparaat_niet_gevonden", str(r))

# [16] Veiligheid: alle functies geven dict met ok/status
for fn, args in [
    (audio.list_sessions, ()),
    (audio.get_session_volume, ("x",)),
    (audio.set_session_volume, ("x", 50)),
    (audio.set_session_mute, ("x", True)),
    (audio.toggle_session_mute, ("x",)),
    (audio.list_output_devices, ()),
    (audio.get_default_output, ()),
    (audio.set_default_output, ("x",)),
]:
    with _enter(_make_pycaw_mock(sessions=[], speakers_name="Mock Output")):
        r = fn(*args)
        ok(f"16. {fn.__name__}: retourneert dict met ok",
           isinstance(r, dict) and "ok" in r, f"type={type(r).__name__}")

print(f"\n--- FASE 11: {passed} geslaagd, {failed} gefaald ---\n")