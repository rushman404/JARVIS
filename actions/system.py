import platform
import time
import psutil
import win32com.client
import win32api


def _gb(bytes_value):

    return round(bytes_value / (1024 ** 3), 1)


def get_cpu_name():

    try:

        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")

        return name.strip()

    except Exception as error:
        print(f"Fout bij CPU-naam lezen: {error}")
        return "onbekend"


def cpu_info():

    return {
        "naam": get_cpu_name(),
        "cores": psutil.cpu_count(logical=False) or 0,
        "threads": psutil.cpu_count(logical=True) or 0,
        "gebruik": psutil.cpu_percent(interval=0.3),
    }


def ram_info():

    memory = psutil.virtual_memory()

    return {
        "totaal": _gb(memory.total),
        "gebruikt": _gb(memory.used),
        "vrij": _gb(memory.available),
        "percentage": memory.percent,
    }


def disk_info():

    usage = psutil.disk_usage("C:\\")

    return {
        "schijf": "C",
        "totaal": _gb(usage.total),
        "gebruikt": _gb(usage.used),
        "vrij": _gb(usage.free),
        "percentage": usage.percent,
    }


def gpu_names():

    try:

        wmi = win32com.client.GetObject("winmgmts:")

        names = [
            gpu.Name
            for gpu in wmi.ExecQuery("SELECT Name FROM Win32_VideoController")
            if gpu.Name
        ]

        return names or ["onbekend"]

    except Exception as error:
        print(f"Fout bij GPU lezen: {error}")
        return ["onbekend"]


def battery_info():

    try:

        status = win32api.GetSystemPowerStatus()

        percent = status.get("BatteryLifePercent", None)

        if percent is None or percent == 255 or percent < 0 or percent > 100:
            return None

        plugged = status.get("ACLineStatus", 1) == 1

        return {
            "percentage": int(percent),
            "stekker": bool(plugged),
        }

    except Exception as error:
        print(f"Fout bij batterij lezen: {error}")
        return None


def os_info():

    return {
        "systeem": platform.system(),
        "release": platform.release(),
        "versie": platform.version(),
        "machine": platform.machine(),
    }


def uptime():

    boot = psutil.boot_time()

    seconds = int(time.time() - boot)

    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60

    return {
        "dagen": days,
        "uren": hours,
        "minuten": minutes,
    }


def system_summary():

    cpu = cpu_info()
    ram = ram_info()
    disk = disk_info()
    gpus = gpu_names()
    info = os_info()

    lines = [
        f"Systeem: {info['systeem']} {info['release']} ({info['machine']})",
        f"Processor: {cpu['naam']}",
        f"GPU: {', '.join(gpus)}",
        f"RAM: {ram['totaal']} GB totaal, {ram['vrij']} GB vrij",
        f"Schijf C: {disk['vrij']} GB vrij van {disk['totaal']} GB",
    ]

    battery = battery_info()

    if battery:
        stekker = "op de stroom" if battery["stekker"] else "op de batterij"
        lines.append(f"Batterij: {battery['percentage']}%, {stekker}")

    duration = uptime()
    lines.append(
        f"Aan: {duration['dagen']} dagen, {duration['uren']} uur, "
        f"{duration['minuten']} minuten"
    )

    return ", ".join(lines) + "."