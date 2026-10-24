"""
Audio-laag (Fase 11) — Windows audio-besturing via pycaw.

JARVIS kan hiermee:
  - Actieve audio-sessions opsommen (welke apps maken geluid?), inclusief
    procesnaam, volume en mute-status
  - Per-app volume instellen ("zet Spotify op 50")
  - Per-app mute dempen/opheffen ("demp Discord")
  - Output-apparaten opsommen (headset, speakers, Sonar virtual device)
  - Huidig default output-apparaat opvragen
  - Default output wisselen ("zet alle audio naar de headset")

Belangrijk:
  - Algemeen bestand, geen Sonar-specifieke code (die komt in actions/sonar.py)
  - pycaw wordt lazy geïmporteerd zodat de rest blijft werken zonder pycaw
  - Volume-wijzigingen zijn per audio-SESSION (per app), NIET het
    systeemmedia-volume (dat blijft in actions/media.py)

Veiligheid:
  - Alle functies geven een ToolResult terug (ok/message/data/error_kind).
  - Foute/missende procesnamen geven een fout terug, geen crash.
"""

import time

from core.result_validation import ToolResult
from actions.com_worker import run_on_com_thread

TIMEOUT = 3


def _import_pycaw():

    """Importeer pycaw lazily. Geeft None als het niet beschikbaar is."""

    try:
        from pycaw.pycaw import (
            AudioUtilities,
            ISimpleAudioVolume,
            EDataFlow,
            DEVICE_STATE,
        )
        return AudioUtilities, EDataFlow, DEVICE_STATE
    except ImportError:
        return None


def _not_available():

    return ToolResult(
        ok=False,
        message="Audio-besturing is niet beschikbaar (pycaw is niet geïnstalleerd).",
        error_kind="audio_unavailable",
    )


# =============================================================
# SESSIONS (per-app geluid)
# =============================================================

def list_sessions():

    """Lijst actieve audio-sessions op (welke apps maken geluid?).

    Elke session bevat: proces-naam, proces-id, volume (0-100), mute-status.
    """

    pycaw = _import_pycaw()

    if pycaw is None:
        return _not_available()

    try:
        def _get():
            return _build_sessions()
        sessions = run_on_com_thread(_get)

        if not sessions:
            return ToolResult(
                ok=True,
                message="Ik heb geen audio-sessies gevonden.",
                data={"sessions": [], "count": 0},
            )

        count = len(sessions)
        return ToolResult(
            ok=True,
            message=f"Ik heb {count} audio-sessie(s) gevonden.",
            data={
                "sessions": [
                    {"name": s["name"], "pid": s["pid"],
                     "volume": s["volume"], "muted": s["muted"]}
                    for s in sessions
                ],
                "count": count,
            },
        )

    except Exception as error:
        print(f"Fout bij audio-sessions lezen: {error}")
        return ToolResult(
            ok=False,
            message=f"Kon audio-sessions niet lezen: {error}",
            error_kind="audio_error",
        )


def _build_sessions():

    """Interne sessie-lijst mét controle-objecten. Draait al op de COM-thread."""

    pycaw = _import_pycaw()

    if pycaw is None:
        return []

    AudioUtilities = pycaw[0]

    sessions = []
    raw = AudioUtilities.GetAllSessions()

    for session in raw:
        try:
            process = session.Process
            pid = process.pid if process else None
            name = process.name() if process else "Systeem"
        except Exception:
            pid = None
            name = "Systeem"

        if name == "Systeem":
            # Mag de procesnaam niet gelezen worden (bijv. een app uit de
            # Microsoft Store), dan staat het programma nog in de sessie-ID
            # van Windows: "...\Spotify.exe%b{...}".
            name = _naam_uit_sessie_id(session) or name

        try:
            volume = round(session.SimpleAudioVolume.GetMasterVolume() * 100)
        except Exception:
            volume = None

        try:
            muted = bool(session.SimpleAudioVolume.GetMute())
        except Exception:
            muted = None

        sessions.append({
            "name": name,
            "pid": pid,
            "volume": volume,
            "muted": muted,
            "control": session.SimpleAudioVolume,
        })

    return sessions


def _naam_uit_sessie_id(session):
    """De .exe-naam uit de sessie-ID van Windows, of None."""

    import re

    try:
        sessie_id = str(session.Identifier or "")
    except Exception:
        return None
    gevonden = re.findall(r"([^\\/|%]+\.exe)", sessie_id, flags=re.IGNORECASE)
    return gevonden[-1] if gevonden else None


def _raw_sessions():

    """Interne sessie-lijst mét controle-objecten (voor wijzigacties)."""

    return run_on_com_thread(_build_sessions)


def find_or_create_session(process_name, sessions=None):

    """Zoek een audio-session op procesnaam (exact of bevat).

    Geeft (session_dict, None) bij succes of (None, fout-ToolResult)."""

    if sessions is None:
        sessions = _raw_sessions()

    name = (process_name or "").lower().strip()

    if not name:
        return None, ToolResult(
            ok=False,
            message="Geef de naam van de app op.",
            error_kind="geen_naam",
        )

    for s in sessions:
        sname = (s.get("name") or "").lower()
        if sname == name or sname.startswith(name.split()[0]):
            control = s.get("control")
            if control is not None:
                return s, None

    # Tweede pas: bevat (zonder extensie vergelijking)
    for s in sessions:
        sname = (s.get("name") or "").lower()
        if name in sname or sname.replace(".exe", "") in name or name.replace(".exe", "") in sname:
            control = s.get("control")
            if control is not None:
                return s, None

    return None, ToolResult(
        ok=False,
        message=f"Ik vind geen actieve audio-session voor '{process_name}'. "
                f"Speelt de app op dit moment geluid af?",
        error_kind="session_niet_gevonden",
    )


def get_session_volume(process_name):

    """Lees het sessie-volume voor een app (0-100)."""

    try:
        def _get():
            sessions = _build_sessions()
            session, error = find_or_create_session(process_name, sessions)
            if session is None:
                return error
            return ToolResult(
                ok=True,
                message=f"Volume van {session.get('name')}: {session.get('volume')}%.",
                data={
                    "name": session.get("name"),
                    "volume": session.get("volume"),
                    "muted": session.get("muted"),
                },
            )
        return run_on_com_thread(_get)
    except Exception as e:
        return ToolResult(ok=False, message=str(e), error_kind="audio_error")


def set_session_volume(process_name, percent):

    """Stel het sessie-volume in voor een app (0-100)."""

    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return ToolResult(
            ok=False,
            message=f"'{percent}' is geen geldig volume. Gebruik 0-100.",
            error_kind="foute_waarde",
        )

    percent = max(0, min(100, percent))

    try:
        def _set():
            sessions = _build_sessions()
            session, error = find_or_create_session(process_name, sessions)

            if session is None:
                return error

            try:
                control = session.get("control")
                control.SetMasterVolume(percent / 100, None)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    message=f"Kon het volume van {process_name} niet instellen: {exc}",
                    error_kind="audio_error",
                )

            return ToolResult(
                ok=True,
                message=f"Volume van {session.get('name')} staat op {percent}%.",
                data={"volume": percent},
            )
        return run_on_com_thread(_set)
    except Exception as e:
        return ToolResult(ok=False, message=str(e), error_kind="audio_error")


def set_session_mute(process_name, muted):

    """Dempen of opheffen (muted=True = dempen, False = geluid aan)."""

    try:
        def _set():
            sessions = _build_sessions()
            session, error = find_or_create_session(process_name, sessions)

            if session is None:
                return error

            try:
                control = session.get("control")
                control.SetMute(bool(muted), None)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    message=f"Kon {process_name} niet {'dempten' if muted else 'ontdempen'}: {exc}",
                    error_kind="audio_error",
                )

            state = "gedempt" if muted else "niet meer gedempt"
            return ToolResult(
                ok=True,
                message=f"Audio van {session.get('name')} is {state}.",
                data={"muted": bool(muted)},
            )
        return run_on_com_thread(_set)
    except Exception as e:
        return ToolResult(ok=False, message=str(e), error_kind="audio_error")


def toggle_session_mute(process_name):

    """Draait de mute-status van een app om."""

    try:
        def _toggle():
            sessions = _build_sessions()
            session, error = find_or_create_session(process_name, sessions)

            if session is None:
                return error

            try:
                control = session.get("control")
                current = bool(control.GetMute())
                control.SetMute(not current, None)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    message=f"Kon mute-status van {process_name} niet omdraaien: {exc}",
                    error_kind="audio_error",
                )

            if current:
                message = f"Audio van {session.get('name')} is niet meer gedempt."
            else:
                message = f"Audio van {session.get('name')} is gedempt."

            return ToolResult(
                ok=True,
                message=message,
                data={"muted": not current},
            )
        return run_on_com_thread(_toggle)
    except Exception as e:
        return ToolResult(ok=False, message=str(e), error_kind="audio_error")


# =============================================================
# OUTPUT-APPARATEN
# =============================================================

def list_output_devices():

    """Lijst alle output-apparaten op (headset, speaker, Sonar virtual device).

    Elke device bevat: naam, actief-status, is_default, is_sonar.
    """

    pycaw = _import_pycaw()

    if pycaw is None:
        return _not_available()

    AudioUtilities = pycaw[0]
    EDataFlow = pycaw[1]

    def _collect():
        # Huidig default output apparaat bepalen
        try:
            speakers = AudioUtilities.GetSpeakers()
            default_name = getattr(speakers, "FriendlyName", "onbekend")
        except Exception:
            default_name = None

        # Alleen OUTPUT-apparaten (eRender), alle statussen
        all_devs = AudioUtilities.GetAllDevices(
            data_flow=EDataFlow.eRender.value,
            device_state=15,  # DEVICE_STATE.MASK_ALL (1|2|4|8)
        )
        devices = []
        for dev in all_devs:
            try:
                name = getattr(dev, "FriendlyName", "?")
                state = getattr(dev, "state", None)
                state_name = getattr(state, "name", str(state))
            except Exception:
                continue

            if not name or name == "?":
                continue

            devices.append({
                "name": name,
                "active": state_name == "Active",
                "is_default": (name == default_name) if default_name else False,
                "is_sonar": "sonar" in (name or "").lower(),
            })

        return devices, default_name

    try:
        # Alle pycaw/COM-aanroepen draaien op de COM-thread.
        devices, default_name = run_on_com_thread(_collect, timeout=TIMEOUT)

        active_only = [d for d in devices if d["active"]]

        if not active_only:
            return ToolResult(
                ok=False,
                message="Ik kon geen actieve audio-apparaten vinden.",
                error_kind="geen_apparaten",
            )

        # Sorteer: Sonar vooraan, daarna default, daarna alfabetisch
        active_only.sort(key=lambda d: (not d["is_sonar"], not d["is_default"], d["name"].lower()))

        count = len(active_only)
        return ToolResult(
            ok=True,
            message=f"Ik heb {count} audio-apparaat(s) gevonden.",
            data={
                "devices": [
                    {k: v for k, v in d.items()} for d in active_only
                ],
                "default": default_name,
                "count": count,
            },
        )

    except Exception as error:
        print(f"Fout bij audio-apparaten lezen: {error}")
        return ToolResult(
            ok=False,
            message=f"Kon audio-apparaten niet lezen: {error}",
            error_kind="audio_error",
        )


def get_default_output():

    """Geeft het huidige default output-apparaat."""

    pycaw = _import_pycaw()

    if pycaw is None:
        return _not_available()

    AudioUtilities = pycaw[0]

    def _read_default_name():
        speakers = AudioUtilities.GetSpeakers()
        return getattr(speakers, "FriendlyName", "Onbekend apparaat")

    try:
        name = run_on_com_thread(_read_default_name, timeout=TIMEOUT)
        return ToolResult(
            ok=True,
            message=f"Huidige output: {name}.",
            data={"name": name},
        )
    except Exception as error:
        print(f"Fout bij default apparaat lezen: {error}")
        return ToolResult(
            ok=False,
            message=f"Kon het default apparaat niet lezen: {error}",
            error_kind="audio_error",
        )


def set_default_output(device_name):

    """Wissel het default output-apparaat naar een ander apparaat.

    Zoekt de opgegeven naam in de lijst van actieve output-apparaten
    (substring-match) en stelt dat apparaat in als Windows default.
    """

    pycaw = _import_pycaw()

    if pycaw is None:
        return _not_available()

    AudioUtilities = pycaw[0]

    name = (device_name or "").lower().strip()

    if not name:
        return ToolResult(
            ok=False,
            message="Geef op naar welk apparaat ik de audio moet sturen.",
            error_kind="geen_naam",
        )

    # Stoorwoordjes weghalen: "de headset" -> "headset"
    import re as _re
    name = _re.sub(r"^(de|het|mijn|een|naar|op|van)\s+", "", name).strip()

    if not name:
        return ToolResult(
            ok=False,
            message="Geef op naar welk apparaat ik de audio moet sturen.",
            error_kind="geen_naam",
        )

    # Aliassen in het Nederlands: "headset" -> "Hoofdtelefoon"
    alias_lookup = {
        "headset": "Hoofdtelefoon",
        "koptelefoon": "Hoofdtelefoon",
        "hoofdtelefoon": "Hoofdtelefoon",
        "speaker": "Luidsprekers",
        "speakers": "Luidsprekers",
        "luidspreker": "Luidsprekers",
        "luidsprekers": "Luidsprekers",
    }
    aliased = alias_lookup.get(name)
    if aliased:
        name = aliased.lower()

    try:
        # Zoek het apparaat in de lokale lijst
        devices = list_output_devices()
        if not devices.ok:
            return devices

        match = None
        # Multi-woord match: "sonar gaming" moet matchen op
        # "SteelSeries Sonar - Gaming (...)". Ook substring match.
        name_words = [w for w in name.split() if len(w) >= 3]
        for d in (devices.data or {}).get("devices", []):
            dname = (d.get("name") or "").lower()
            if name in dname or dname in name:
                match = d
                break
            if name_words and all(w in dname for w in name_words):
                match = d
                break

        if match is None:
            return ToolResult(
                ok=False,
                message=f"Ik vind geen audio-apparaat met de naam '{device_name}'.",
                error_kind="apparaat_niet_gevonden",
            )

        target_name = match.get("name")

        # Stel het default apparaat in via Windows API (IPolicyConfig)
        target_id = _get_device_id(target_name)
        if target_id is None:
            return ToolResult(
                ok=False,
                message=f"Kon het apparaat '{target_name}' niet vinden om te wisselen.",
                error_kind="audio_error",
            )

        # Stel het default apparaat in op de COM-thread.
        run_on_com_thread(AudioUtilities.SetDefaultDevice, target_id, timeout=TIMEOUT)

        # Het default-apparaat is gewisseld: de gecachte volume-interface
        # in actions.media hoort nu bij het oude apparaat en moet weg.
        try:
            from actions.media import reset_volume_cache

            reset_volume_cache()
        except Exception:
            pass

        return ToolResult(
            ok=True,
            message=f"Output staat nu op {target_name}.",
            data={"name": target_name},
        )

    except Exception as error:
        print(f"Fout bij apparaat wisselen: {error}")
        return ToolResult(
            ok=False,
            message=f"Kon het audio-apparaat niet wisselen: {error}",
            error_kind="audio_error",
        )


def _get_device_id(device_name):

    """Zoek het Windows device-id (string) van een apparaat op naam."""

    try:
        from pycaw.pycaw import AudioUtilities, EDataFlow

        return run_on_com_thread(
            _find_device_id, AudioUtilities, EDataFlow, device_name,
            timeout=TIMEOUT,
        )
    except Exception:
        return None


def _find_device_id(AudioUtilities, EDataFlow, device_name):

    """Draait op de COM-thread: leest GetAllDevices en device-id's."""

    all_devs = AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eRender.value,
        device_state=15,  # DEVICE_STATE.MASK_ALL (1|2|4|8)
    )
    for dev in all_devs:
        try:
            n = getattr(dev, "FriendlyName", "").lower()
        except Exception:
            continue
        if n == device_name.lower():
            # pycaw.utils.AudioDevice heeft .id (device-id string)
            did = getattr(dev, "id", None)
            if did:
                return did
            # Fallback: de onderliggende IMMDevice.GetId()
            underlying = getattr(dev, "_dev", None)
            if underlying is not None and hasattr(underlying, "GetId"):
                try:
                    return underlying.GetId()
                except Exception:
                    pass
    return None
