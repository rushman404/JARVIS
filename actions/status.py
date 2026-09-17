"""
Unified PC Status (Fase 12)

Combineert alle losse status-tools in één overzicht:
systeem + audio + browser + venster. Maakt het mogelijk
om een complete PC-status op te vragen met één commando.
"""


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
        result["audio"] = {
            "output": output.get("name") if output.get("ok") else output.get("error"),
            "sessions": [
                {"name": s.get("name"), "volume": s.get("volume"), "muted": s.get("muted")}
                for s in sessions.get("sessions", [])
            ] if sessions.get("ok") else [],
        }
    except Exception as error:
        result["audio"] = f"fout: {error}"

    # ----- Browser (URL + titel) -----
    try:
        from actions.browser import get_browser_url, get_browser_title
        url = get_browser_url()
        title = get_browser_title()
        result["browser"] = {
            "url": url.get("url") if url.get("ok") else None,
            "title": title.get("title") if title.get("ok") else None,
            "open": bool(url.get("ok")),
        }
    except Exception as error:
        result["browser"] = f"fout: {error}"

    return result