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
  - Alle functies geven een dict terug met ok/status/error.
  - Foute/missende procesnamen geven een fout terug, geen crash.
"""

import time

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

    return {
        "ok": False,
        "status": "fout",
        "error_type": "audio_unavailable",
        "error": "Audio-besturing is niet beschikbaar (pycaw is niet geïnstalleerd).",
    }


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

    AudioUtilities = pycaw[0]

    try:
        sessions = _raw_sessions()

        if not sessions:
            return {"ok": True, "status": "200", "sessions": [], "count": 0}

        return {
            "ok": True,
            "status": "200",
            "sessions": [
                {"name": s["name"], "pid": s["pid"],
                 "volume": s["volume"], "muted": s["muted"]}
                for s in sessions
            ],
            "count": len(sessions),
        }

    except Exception as error:
        print(f"Fout bij audio-sessions lezen: {error}")
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon audio-sessions niet lezen: {error}"}


def _raw_sessions():

    """Interne sessie-lijst mét controle-objecten (voor wijzigacties)."""

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


def find_or_create_session(process_name, sessions=None):

    """Zoek een audio-session op procesnaam (exact of bevat).

    Geeft (session_dict, None) bij succes of (None, error_dict)."""

    if sessions is None:
        sessions = _raw_sessions()

    name = (process_name or "").lower().strip()

    if not name:
        return None, {"ok": False, "status": "fout", "error_type": "geen_naam",
                      "error": "Geef de naam van de app op."}

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

    return None, {"ok": False, "status": "fout", "error_type": "session_niet_gevonden",
                  "error": f"Ik vind geen actieve audio-session voor '{process_name}'. "
                           f"Speelt de app op dit moment geluid af?"}


def get_session_volume(process_name):

    """Lees het sessie-volume voor een app (0-100)."""

    sessions = _raw_sessions()
    session, error = find_or_create_session(process_name, sessions)

    if session is None:
        return error

    return {
        "ok": True,
        "status": "200",
        "name": session.get("name"),
        "volume": session.get("volume"),
        "muted": session.get("muted"),
    }


def set_session_volume(process_name, percent):

    """Stel het sessie-volume in voor een app (0-100)."""

    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return {"ok": False, "status": "fout", "error_type": "foute_waarde",
                "error": f"'{percent}' is geen geldig volume. Gebruik 0-100."}

    percent = max(0, min(100, percent))

    sessions = _raw_sessions()
    session, error = find_or_create_session(process_name, sessions)

    if session is None:
        return error

    try:
        control = session.get("control")
        control.SetMasterVolume(percent / 100, None)
    except Exception as exc:
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon het volume van {process_name} niet instellen: {exc}"}

    return {
        "ok": True,
        "status": "200",
        "message": f"Volume van {session.get('name')} staat nu op {percent}%.",
        "volume": percent,
    }


def set_session_mute(process_name, muted):

    """Dempen of opheffen (muted=True = dempen, False = geluid aan)."""

    sessions = _raw_sessions()
    session, error = find_or_create_session(process_name, sessions)

    if session is None:
        return error

    try:
        control = session.get("control")
        control.SetMute(bool(muted), None)
    except Exception as exc:
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon {process_name} niet {'dempten' if muted else 'ontdempen'}: {exc}"}

    state = "gedempt" if muted else "niet meer gedempt"
    return {
        "ok": True,
        "status": "200",
        "message": f"{session.get('name')} is {state}.",
        "muted": bool(muted),
    }


def toggle_session_mute(process_name):

    """Draait de mute-status van een app om."""

    sessions = _raw_sessions()
    session, error = find_or_create_session(process_name, sessions)

    if session is None:
        return error

    try:
        control = session.get("control")
        current = bool(control.GetMute())
        control.SetMute(not current, None)
    except Exception as exc:
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon mute-status van {process_name} niet omdraaien: {exc}"}

    state = "gedempt" if not current else "niet meer gedempt"
    return {
        "ok": True,
        "status": "200",
        "message": f"{session.get('name')} is {state}.",
        "muted": not current,
    }


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

    try:
        # Huidig default output apparaat bepalen
        try:
            speakers = AudioUtilities.GetSpeakers()
            default_name = getattr(speakers, "FriendlyName", "onbekend")
            default_id = getattr(speakers, "device_id", None)
        except Exception:
            default_name, default_id = None, None

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

            is_sonar = "sonar" in (name or "").lower()
            is_default = (name == default_name) if default_name else False

            is_active = state_name == "Active"

            devices.append({
                "name": name,
                "active": bool(is_active),
                "is_default": bool(is_default),
                "is_sonar": bool(is_sonar),
            })

        active_only = [d for d in devices if d["active"]]

        if not active_only:
            return {"ok": False, "status": "fout", "error_type": "geen_apparaten",
                    "error": "Ik kon geen actieve audio-apparaten vinden."}

        # Sorteer: Sonar vooraan, daarna default, daarna alfabetisch
        active_only.sort(key=lambda d: (not d["is_sonar"], not d["is_default"], d["name"].lower()))

        return {
            "ok": True,
            "status": "200",
            "devices": [
                {k: v for k, v in d.items()} for d in active_only
            ],
            "default": default_name,
            "count": len(active_only),
        }

    except Exception as error:
        print(f"Fout bij audio-apparaten lezen: {error}")
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon audio-apparaten niet lezen: {error}"}


def get_default_output():

    """Geeft het huidige default output-apparaat."""

    pycaw = _import_pycaw()

    if pycaw is None:
        return _not_available()

    AudioUtilities = pycaw[0]

    try:
        speakers = AudioUtilities.GetSpeakers()
        name = getattr(speakers, "FriendlyName", "Onbekend apparaat")
        return {"ok": True, "status": "200", "name": name}
    except Exception as error:
        print(f"Fout bij default apparaat lezen: {error}")
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon het default apparaat niet lezen: {error}"}


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
        return {"ok": False, "status": "fout", "error_type": "geen_naam",
                "error": "Geef op naar welk apparaat ik de audio moet sturen."}

    # Stoorwoordjes weghalen: "de headset" -> "headset"
    import re as _re
    name = _re.sub(r"^(de|het|mijn|een|naar|op|van)\s+", "", name).strip()

    if not name:
        return {"ok": False, "status": "fout", "error_type": "geen_naam",
                "error": "Geef op naar welk apparaat ik de audio moet sturen."}

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
        if not devices.get("ok"):
            return devices

        match = None
        # Multi-woord match: "sonar gaming" moet matchen op
        # "SteelSeries Sonar - Gaming (...)". Ook substring match.
        name_words = [w for w in name.split() if len(w) >= 3]
        for d in devices.get("devices", []):
            dname = (d.get("name") or "").lower()
            if name in dname or dname in name:
                match = d
                break
            if name_words and all(w in dname for w in name_words):
                match = d
                break

        if match is None:
            return {
                "ok": False,
                "status": "fout",
                "error_type": "apparaat_niet_gevonden",
                "error": f"Ik vind geen audio-apparaat met de naam '{device_name}'.",
            }

        target_name = match.get("name")

        # Stel het default apparaat in via Windows API (IPolicyConfig)
        target_id = _get_device_id(target_name)
        if target_id is None:
            return {"ok": False, "status": "fout", "error_type": "audio_error",
                    "error": f"Kon het apparaat '{target_name}' niet vinden om te wisselen."}

        AudioUtilities.SetDefaultDevice(target_id)

        return {
            "ok": True,
            "status": "200",
            "message": f"Alle audio gaat nu naar: {target_name}.",
            "name": target_name,
        }

    except Exception as error:
        print(f"Fout bij apparaat wisselen: {error}")
        return {"ok": False, "status": "fout", "error_type": "audio_error",
                "error": f"Kon het audio-apparaat niet wisselen: {error}"}


def _get_device_id(device_name):

    """Zoek het Windows device-id (string) van een apparaat op naam."""

    from pycaw.pycaw import AudioUtilities, EDataFlow

    try:
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
    except Exception:
        return None