"""Fase 15 — Game-PC Agent: telemetrie van de gaming-pc.

Verzamelt statusinformatie die het brein (JARVIS) op afstand kan
opvragen: CPU, RAM, schijf, uptime (via ``psutil``) en GPU-informatie
(via ``nvidia-smi``, alleen als er een NVIDIA-GPU is).

Ontwerpregels
-------------
* **Nooit crashen.** Elke meting zit in zijn eigen ``try/except``. Een
  tijdelijke fout levert een fout-envelope op, niet een exception.
* **Consistente structuur.** Elk onderdeel is óf::

        {"ok": True, "<veld>": ..., ...}

    óf::

        {"ok": False, "fout": {"code": "...", "melding": "..."}}

    ``collect_telemetry()`` bundelt de onderdelen en zet alle fouten in
  één lijst onder ``"fouten"``.
* **Veilig extern proces.** ``nvidia-smi`` wordt met een vaste
  argumentenlijst aangeroepen (nooit ``shell=True``, nooit
  gebruikersinvoer in het commando) en met een harde time-out.
* **Schaalbaar.** Ontbreekt ``nvidia-smi`` of is er geen NVIDIA-GPU, dan
  blijft de rest van de telemetrie gewoon werken.
"""

import os
import platform
import shutil
import subprocess
import time

import psutil

# ------------------------------------------------------------------
# Constanten
# ------------------------------------------------------------------

# Naam van het NVIDIA-hulpprogramma en de velden die we opvragen.
NVIDIA_SMI = "nvidia-smi"
NVIDIA_SMI_QUERY = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"

# Harde time-out (seconden) voor het externe nvidia-smi-proces.
NVIDIA_SMI_TIMEOUT_SECONDS = 5

# Standaard schijf: de systeemschijf (C:\ op Windows, / elders).
if os.name == "nt":
    DEFAULT_DISK_PAD = os.environ.get("SystemDrive", "C:") + "\\"
else:
    DEFAULT_DISK_PAD = "/"

# Vaste foutcodes (consistent, geen vrije tekst).
FOUT_SYSTEEM = "systeem_fout"
FOUT_CPU = "cpu_fout"
FOUT_RAM = "ram_fout"
FOUT_SCHIJF = "schijf_fout"
FOUT_UPTIME = "uptime_fout"
FOUT_NVIDIA_SMI_ONTBREEKT = "nvidia_smi_ontbreekt"
FOUT_NVIDIA_SMI_TIMEOUT = "nvidia_smi_timeout"
FOUT_NVIDIA_SMI_MISLUKT = "nvidia_smi_fout"
FOUT_NVIDIA_SMI_ONJUIST = "nvidia_smi_onjuist"
FOUT_GPU_NIET_BESCHIKBAAR = "gpu_niet_beschikbaar"

# Onderdelen die "essentieel" zijn: als deze falen, is de telemetrie
# onvolledig. Een ontbrekende GPU is dat NIET (dat is een normale
# situatie op een pc zonder NVIDIA-kaart).
ESSENTIELE_ONDERDELEN = ("systeem", "cpu", "ram", "schijf", "uptime")


# ------------------------------------------------------------------
# Envelope-helpers
# ------------------------------------------------------------------

def _ok(**velden):
    """Een geslaagd onderdeel."""

    resultaat = {"ok": True}
    resultaat.update(velden)
    return resultaat


def _fout(code, melding):
    """Een mislukt onderdeel met een vaste foutcode en leesbare tekst."""

    return {"ok": False, "fout": {"code": code, "melding": melding}}


def _gb(bytes_waarde):
    """Bytes naar gigabytes, op één decimaal."""

    return round(bytes_waarde / (1024 ** 3), 1)


# ------------------------------------------------------------------
# Systeem / CPU / RAM / schijf / uptime (psutil)
# ------------------------------------------------------------------

def systeem_telemetry():
    """Basisinformatie over het systeem (hostnaam, OS, architectuur)."""

    try:
        return _ok(
            hostname=platform.node(),
            os=platform.system(),
            release=platform.release(),
            versie=platform.version(),
            machine=platform.machine(),
        )
    except Exception as error:
        return _fout(FOUT_SYSTEEM, f"Systeeminformatie kon niet worden gelezen: {error}")


def cpu_telemetry():
    """CPU-informatie: naam, cores, threads, gebruik en kloksnelheid."""

    try:
        freq = None
        try:
            freq = psutil.cpu_freq()
        except Exception:
            freq = None

        snelheid = None
        if freq is not None and getattr(freq, "current", None):
            snelheid = round(float(freq.current))

        return _ok(
            naam=platform.processor() or "",
            cores=psutil.cpu_count(logical=False) or 0,
            threads=psutil.cpu_count(logical=True) or 0,
            gebruik_percent=round(float(psutil.cpu_percent(interval=0.2)), 1),
            snelheid_mhz=snelheid,
        )
    except Exception as error:
        return _fout(FOUT_CPU, f"CPU-informatie kon niet worden gelezen: {error}")


def ram_telemetry():
    """RAM-gebruik in GB en procentueel."""

    try:
        geheugen = psutil.virtual_memory()
        return _ok(
            totaal_gb=_gb(geheugen.total),
            gebruikt_gb=_gb(geheugen.used),
            vrij_gb=_gb(geheugen.available),
            percentage=round(float(geheugen.percent), 1),
        )
    except Exception as error:
        return _fout(FOUT_RAM, f"RAM-informatie kon niet worden gelezen: {error}")


def schijf_telemetry(pad=None):
    """Schijfgebruik van één schijf (standaard de systeemschijf)."""

    pad = DEFAULT_DISK_PAD if pad is None else pad

    try:
        gebruik = psutil.disk_usage(pad)
        return _ok(
            pad=str(pad),
            totaal_gb=_gb(gebruik.total),
            gebruikt_gb=_gb(gebruik.used),
            vrij_gb=_gb(gebruik.free),
            percentage=round(float(gebruik.percent), 1),
        )
    except Exception as error:
        return _fout(FOUT_SCHIJF, f"Schijfinformatie van '{pad}' kon niet worden gelezen: {error}")


def uptime_telemetry():
    """Hoe lang de pc al aanstaat."""

    try:
        seconden = int(time.time() - psutil.boot_time())
        if seconden < 0:
            seconden = 0

        dagen, rest = divmod(seconden, 86400)
        uren, rest = divmod(rest, 3600)
        minuten = rest // 60

        return _ok(
            seconden=seconden,
            dagen=dagen,
            uren=uren,
            minuten=minuten,
        )
    except Exception as error:
        return _fout(FOUT_UPTIME, f"Uptime kon niet worden bepaald: {error}")


# ------------------------------------------------------------------
# GPU (nvidia-smi)
# ------------------------------------------------------------------

def _naar_getal(tekst):
    """Zet nvidia-smi-tekst om naar een getal; 'N/A' wordt None."""

    tekst = (tekst or "").strip()

    if tekst in ("", "N/A", "[N/A]", "[Not Supported]", "n/a", "-"):
        return None

    try:
        return int(float(tekst))
    except (TypeError, ValueError):
        return None


def _parse_gpu_uitvoer(stdout):
    """Parseert de CSV-uitvoer van nvidia-smi.

    Geeft een lijst met GPU-dicts terug, een lege lijst als er geen
    regels zijn, of ``None`` als de uitvoer onbruikbaar is (verkeerd
    aantal kolommen).
    """

    if stdout is None:
        return None

    regels = [regel.strip() for regel in str(stdout).splitlines() if regel.strip()]

    if not regels:
        return []

    gpus = []

    for regel in regels:
        kolommen = [deel.strip() for deel in regel.split(",")]

        if len(kolommen) < 5:
            return None

        gpus.append({
            "naam": kolommen[0],
            "gebruik_percent": _naar_getal(kolommen[1]),
            "geheugen_gebruikt_mb": _naar_getal(kolommen[2]),
            "geheugen_totaal_mb": _naar_getal(kolommen[3]),
            "temperatuur_c": _naar_getal(kolommen[4]),
        })

    return gpus


def gpu_telemetry(smi_pad=None, timeout=None, runner=None, which=None):
    """GPU-informatie via nvidia-smi.

    ``smi_pad``, ``timeout``, ``runner`` en ``which`` zijn er voor tests;
    zonder argumenten wordt het echte nvidia-smi gebruikt met een harde
    time-out. Er wordt NOOIT een shell gebruikt en er komt geen
    gebruikersinvoer in het commando: de argumentenlijst staat vast.
    """

    which = which or shutil.which
    runner = runner or subprocess.run
    timeout = NVIDIA_SMI_TIMEOUT_SECONDS if timeout is None else timeout

    pad = smi_pad or which(NVIDIA_SMI)

    if not pad:
        return _fout(
            FOUT_NVIDIA_SMI_ONTBREEKT,
            "nvidia-smi is niet gevonden; GPU-informatie is niet beschikbaar.",
        )

    argumenten = [
        pad,
        "--query-gpu=" + NVIDIA_SMI_QUERY,
        "--format=csv,noheader,nounits",
    ]

    # Op Windows geen console-venster openen; elders geen extra flags.
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proces = runner(
            argumenten,
            capture_output=True,
            text=True,
            timeout=timeout,
            **extra,
        )
    except subprocess.TimeoutExpired:
        return _fout(
            FOUT_NVIDIA_SMI_TIMEOUT,
            f"nvidia-smi reageerde niet binnen {timeout} seconden.",
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return _fout(
            FOUT_NVIDIA_SMI_ONTBREEKT,
            "nvidia-smi kon niet worden gestart; GPU-informatie is niet beschikbaar.",
        )
    except Exception as error:
        # Onverwachte fout: nooit laten doorwerken, altijd netjes falen.
        return _fout(
            FOUT_NVIDIA_SMI_MISLUKT,
            f"nvidia-smi kon niet worden uitgevoerd: {error}",
        )

    if proces.returncode != 0:
        stderr = (getattr(proces, "stderr", "") or "").strip()
        return _fout(
            FOUT_NVIDIA_SMI_MISLUKT,
            "nvidia-smi gaf een fout terug"
            + (f": {stderr.splitlines()[0]}" if stderr else "."),
        )

    gpus = _parse_gpu_uitvoer(proces.stdout)

    if gpus is None:
        return _fout(
            FOUT_NVIDIA_SMI_ONJUIST,
            "Onverwachte uitvoer van nvidia-smi; GPU-informatie is onbruikbaar.",
        )

    if not gpus:
        return _fout(
            FOUT_GPU_NIET_BESCHIKBAAR,
            "nvidia-smi vond geen NVIDIA-GPU op deze pc.",
        )

    return _ok(gpus=gpus, aantal=len(gpus))


# ------------------------------------------------------------------
# Bundel
# ------------------------------------------------------------------

def collect_telemetry(disk_pad=None, smi_pad=None, timeout=None, runner=None, which=None):
    """Verzamelt alle telemetrie in één consistent resultaat.

    Structuur::

        {
            "ok": bool,            # alle ESSENTIELE onderdelen geslaagd
            "tijdstip": int,       # unix-seconden
            "systeem": {...},
            "cpu": {...},
            "ram": {...},
            "schijf": {...},
            "uptime": {...},
            "gpu": {...},
            "fouten": [{"onderdeel", "code", "melding"}, ...],
        }

    Deze functie gooit nooit een exception: elke fout wordt een
    fout-envelope plus een regel in ``"fouten"``.
    """

    onderdelen = {
        "systeem": systeem_telemetry(),
        "cpu": cpu_telemetry(),
        "ram": ram_telemetry(),
        "schijf": schijf_telemetry(disk_pad),
        "uptime": uptime_telemetry(),
        "gpu": gpu_telemetry(smi_pad=smi_pad, timeout=timeout, runner=runner, which=which),
    }

    fouten = []
    for naam, deel in onderdelen.items():
        if not deel.get("ok"):
            fout = deel.get("fout") or {}
            fouten.append({
                "onderdeel": naam,
                "code": fout.get("code", "onbekend"),
                "melding": fout.get("melding", ""),
            })

    kern_ok = all(onderdelen[naam].get("ok") for naam in ESSENTIELE_ONDERDELEN)

    resultaat = {"ok": kern_ok, "tijdstip": int(time.time())}
    resultaat.update(onderdelen)
    resultaat["fouten"] = fouten
    return resultaat
