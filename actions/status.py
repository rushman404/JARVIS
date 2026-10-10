"""
Unified PC Status (Fase 12)

Combineert alle losse status-tools in één overzicht:
systeem + audio + browser + venster. Maakt het mogelijk
om een complete PC-status op te vragen met één commando.
"""


def _as_result(res):
    """Normaliseer een dict- of ToolResult-antwoord naar (ok, data, message)."""
    if res is None:
        return False, {}, ""
    if isinstance(res, dict):
        ok = bool(res.get("ok"))
        data = res.get("data") if isinstance(res.get("data"), dict) else res
        message = res.get("message") or res.get("error") or ""
        return ok, (data or {}), message
    ok = bool(getattr(res, "ok", False))
    data = getattr(res, "data", None)
    if not isinstance(data, dict):
        data = {}
    message = getattr(res, "message", "") or ""
    return ok, data, message


def get_pc_status():

    """Bewijs de huidige PC-status in één overzicht."""

    result = {"ok": True, "status": "200"}

    # ----- Systeem (CPU/RAM/disk/batterij) -----
    try:
        from actions.system import cpu_info, ram_info, disk_info, battery_info, os_info, uptime
        cpu = cpu_info()
        ram = ram_info()
        disk = disk_info()
        info = os_info()
        bat = battery_info()
        up = uptime()

        result["systeem"] = {
            "os": f"{info['systeem']} {info['release']} ({info['machine']})",
            "cpu": cpu.get("naam", "?"),
            "ram_totaal": ram.get("totaal"),
            "ram_vrij": ram.get("vrij"),
            "disk_vrij": disk.get("vrij"),
            "disk_totaal": disk.get("totaal"),
            "batterij": bat,
            "uptime_dagen": up.get("dagen"),
            "uptime_uren": up.get("uren"),
            "uptime_minuten": up.get("minuten"),
        }
        result["pc_draait"] = True
    except Exception as error:
        result["systeem"] = f"fout: {error}"

    # ----- Audio (huidige output + actieve sessions) -----
    try:
        from actions.audio import get_default_output, list_sessions
        output = get_default_output()
        sessions = list_sessions()

        output_ok, output_data, output_msg = _as_result(output)
        output_naam = output_data.get("name") if output_ok else output_msg

        sess_ok, sess_data, _ = _as_result(sessions)

        result["audio"] = {
            "output": output_naam,
            "sessions": [
                {"name": s.get("name"), "volume": s.get("volume"), "muted": s.get("muted")}
                for s in sess_data.get("sessions", [])
            ] if sess_ok else [],
        }
    except Exception as error:
        result["audio"] = f"fout: {error}"

    # ----- Browser (URL + titel) -----
    try:
        from actions.browser import get_browser_url, get_browser_title
        url = get_browser_url()
        title = get_browser_title()
        url_ok, url_data, _ = _as_result(url)
        title_ok, title_data, _ = _as_result(title)
        result["browser"] = {
            "url": url_data.get("url") if url_ok else None,
            "title": title_data.get("title") if title_ok else None,
            "open": bool(url_ok),
        }
    except Exception as error:
        result["browser"] = f"fout: {error}"

    return result
