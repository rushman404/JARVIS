"""Fase 15 — tests voor remote/telemetry.py.

Dekt:
    - normale CPU-, RAM-, schijf- en uptime-resultaten (gemockte psutil);
    - beschikbare en ontbrekende GPU-informatie;
    - fouten en time-outs van nvidia-smi;
    - ontbrekende/ongeldige telemetriegegevens (fout-envelopes);
    - de uitvoerstructuur en dat collect_telemetry() nooit crasht;
    - veiligheid: vaste argumentenlijst, geen shell, time-out meegegeven.
"""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

from remote import telemetry


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _goede_psutil():
    """Een psutil-mock die voor alle onderdelen geldige data geeft."""

    fake = MagicMock()
    fake.cpu_count.side_effect = [8, 16]
    fake.cpu_percent.return_value = 12.5
    fake.cpu_freq.return_value = SimpleNamespace(current=3600.0)
    fake.virtual_memory.return_value = SimpleNamespace(
        total=32 * 1024 ** 3,
        used=16 * 1024 ** 3,
        available=16 * 1024 ** 3,
        percent=50.0,
    )
    fake.disk_usage.return_value = SimpleNamespace(
        total=1024 * 1024 ** 3,
        used=512 * 1024 ** 3,
        free=512 * 1024 ** 3,
        percent=50.0,
    )
    fake.boot_time.return_value = 1_000_000.0 - 183_840  # 2d 3u 4m
    return fake


def _proces(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _runner_met(stdout="", returncode=0, stderr=""):
    """Fake subprocess.run die oproepen vastlegt."""

    oproepen = []

    def runner(argumenten, **kwargs):
        oproepen.append((argumenten, kwargs))
        return _proces(stdout=stdout, returncode=returncode, stderr=stderr)

    return runner, oproepen


def _vaste_tijd(monkeypatch, waarde=1_000_000.0):
    monkeypatch.setattr(telemetry, "time", SimpleNamespace(time=lambda: waarde))


# ---------------------------------------------------------------
# CPU / RAM / schijf / systeem / uptime — normale resultaten
# ---------------------------------------------------------------

def test_cpu_normale_gegevens(monkeypatch):
    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())

    resultaat = telemetry.cpu_telemetry()

    assert resultaat["ok"] is True
    assert resultaat["cores"] == 8
    assert resultaat["threads"] == 16
    assert resultaat["gebruik_percent"] == 12.5
    assert resultaat["snelheid_mhz"] == 3600.0
    assert isinstance(resultaat["naam"], str)


def test_ram_normale_gegevens(monkeypatch):
    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())

    resultaat = telemetry.ram_telemetry()

    assert resultaat["ok"] is True
    assert resultaat["totaal_gb"] == 32.0
    assert resultaat["gebruikt_gb"] == 16.0
    assert resultaat["vrij_gb"] == 16.0
    assert resultaat["percentage"] == 50.0


def test_schijf_normale_gegevens(monkeypatch):
    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())

    resultaat = telemetry.schijf_telemetry()

    assert resultaat["ok"] is True
    assert resultaat["totaal_gb"] == 1024.0
    assert resultaat["gebruikt_gb"] == 512.0
    assert resultaat["vrij_gb"] == 512.0
    assert resultaat["percentage"] == 50.0
    assert isinstance(resultaat["pad"], str)


def test_schijf_eigen_pad(monkeypatch):
    fake = _goede_psutil()
    monkeypatch.setattr(telemetry, "psutil", fake)

    resultaat = telemetry.schijf_telemetry("D:\\")

    assert resultaat["pad"] == "D:\\"
    fake.disk_usage.assert_called_with("D:\\")


def test_uptime_normale_gegevens(monkeypatch):
    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())
    _vaste_tijd(monkeypatch, 1_000_000.0)

    resultaat = telemetry.uptime_telemetry()

    assert resultaat["ok"] is True
    assert resultaat["seconden"] == 183_840
    assert resultaat["dagen"] == 2
    assert resultaat["uren"] == 3
    assert resultaat["minuten"] == 4


def test_uptime_negatief_wordt_nul(monkeypatch):
    fake = _goede_psutil()
    fake.boot_time.return_value = 2_000_000.0  # in de toekomst
    monkeypatch.setattr(telemetry, "psutil", fake)
    _vaste_tijd(monkeypatch, 1_000_000.0)

    resultaat = telemetry.uptime_telemetry()

    assert resultaat["ok"] is True
    assert resultaat["seconden"] == 0


def test_systeem_normale_gegevens():
    resultaat = telemetry.systeem_telemetry()

    assert resultaat["ok"] is True
    for sleutel in ("hostname", "os", "release", "versie", "machine"):
        assert sleutel in resultaat


# ---------------------------------------------------------------
# psutil-fouten -> fout-envelope (geen exception)
# ---------------------------------------------------------------

def test_cpu_fout_geeft_foutcode(monkeypatch):
    fake = _goede_psutil()
    fake.cpu_count.side_effect = RuntimeError("boom")
    monkeypatch.setattr(telemetry, "psutil", fake)

    resultaat = telemetry.cpu_telemetry()

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_CPU
    assert "melding" in resultaat["fout"]


def test_ram_fout_geeft_foutcode(monkeypatch):
    fake = _goede_psutil()
    fake.virtual_memory.side_effect = RuntimeError("boom")
    monkeypatch.setattr(telemetry, "psutil", fake)

    resultaat = telemetry.ram_telemetry()

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_RAM


def test_schijf_fout_geeft_foutcode(monkeypatch):
    fake = _goede_psutil()
    fake.disk_usage.side_effect = OSError("geen schijf")
    monkeypatch.setattr(telemetry, "psutil", fake)

    resultaat = telemetry.schijf_telemetry()

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_SCHIJF


def test_uptime_fout_geeft_foutcode(monkeypatch):
    fake = _goede_psutil()
    fake.boot_time.side_effect = RuntimeError("boom")
    monkeypatch.setattr(telemetry, "psutil", fake)

    resultaat = telemetry.uptime_telemetry()

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_UPTIME


def test_ontbrekende_data_wordt_none_of_nul(monkeypatch):
    """psutil mag None teruggeven; dat mag geen crash opleveren."""

    fake = MagicMock()
    fake.cpu_count.return_value = None
    fake.cpu_percent.return_value = 0.0
    fake.cpu_freq.return_value = None
    monkeypatch.setattr(telemetry, "psutil", fake)

    resultaat = telemetry.cpu_telemetry()

    assert resultaat["ok"] is True
    assert resultaat["cores"] == 0
    assert resultaat["threads"] == 0
    assert resultaat["snelheid_mhz"] is None


# ---------------------------------------------------------------
# GPU — beschikbaar
# ---------------------------------------------------------------

def test_gpu_beschikbaar(monkeypatch):
    runner, oproepen = _runner_met(
        stdout="NVIDIA GeForce RTX 4090, 45, 8192, 24576, 65\n"
    )

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner, timeout=5)

    assert resultaat["ok"] is True
    assert resultaat["aantal"] == 1

    gpu = resultaat["gpus"][0]
    assert gpu["naam"] == "NVIDIA GeForce RTX 4090"
    assert gpu["gebruik_percent"] == 45
    assert gpu["geheugen_gebruikt_mb"] == 8192
    assert gpu["geheugen_totaal_mb"] == 24576
    assert gpu["temperatuur_c"] == 65


def test_gpu_meerdere_kaarten():
    runner, _ = _runner_met(
        stdout=(
            "NVIDIA RTX 4090, 45, 8192, 24576, 65\n"
            "NVIDIA RTX 3060, 10, 1024, 12288, 50\n"
        )
    )

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert resultaat["ok"] is True
    assert resultaat["aantal"] == 2
    assert resultaat["gpus"][1]["naam"] == "NVIDIA RTX 3060"


def test_gpu_na_waarden_worden_none():
    runner, _ = _runner_met(stdout="NVIDIA RTX 4060, N/A, [N/A], 8192, 55\n")

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert resultaat["ok"] is True
    gpu = resultaat["gpus"][0]
    assert gpu["gebruik_percent"] is None
    assert gpu["geheugen_gebruikt_mb"] is None
    assert gpu["geheugen_totaal_mb"] == 8192
    assert gpu["temperatuur_c"] == 55


# ---------------------------------------------------------------
# GPU — ontbrekend / fouten / time-out
# ---------------------------------------------------------------

def test_gpu_nvidia_smi_ontbreekt():
    runner, oproepen = _runner_met(stdout="iets")

    resultaat = telemetry.gpu_telemetry(which=lambda naam: None, runner=runner)

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_NVIDIA_SMI_ONTBREEKT
    assert oproepen == [], "zonder nvidia-smi mag er niets worden gestart"


def test_gpu_timeout():
    def runner(argumenten, **kwargs):
        raise subprocess.TimeoutExpired(argumenten, kwargs.get("timeout", 5))

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner, timeout=3)

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_NVIDIA_SMI_TIMEOUT
    assert "3" in resultaat["fout"]["melding"]


def test_gpu_niet_startbaar():
    def runner(argumenten, **kwargs):
        raise FileNotFoundError("nvidia-smi.exe")

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_NVIDIA_SMI_ONTBREEKT


def test_gpu_met_foutcode_van_nvidia_smi():
    runner, _ = _runner_met(
        stdout="",
        returncode=9,
        stderr="NVIDIA-SMI has failed because it couldn't communicate\nmeer tekst",
    )

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_NVIDIA_SMI_MISLUKT
    assert "NVIDIA-SMI has failed" in resultaat["fout"]["melding"]


def test_gpu_ongeldige_uitvoer():
    runner, _ = _runner_met(stdout="NVIDIA RTX 4090, 45\n")  # te weinig kolommen

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_NVIDIA_SMI_ONJUIST


def test_gpu_lege_uitvoer_betekent_geen_gpu():
    runner, _ = _runner_met(stdout="", returncode=0)

    resultaat = telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert resultaat["ok"] is False
    assert resultaat["fout"]["code"] == telemetry.FOUT_GPU_NIET_BESCHIKBAAR


# ---------------------------------------------------------------
# Veiligheid van het externe proces
# ---------------------------------------------------------------

def test_gpu_gebruikt_vaste_argumenten_en_geen_shell():
    runner, oproepen = _runner_met(stdout="NVIDIA RTX 4090, 1, 2, 3, 4\n")

    telemetry.gpu_telemetry(smi_pad="nvidia-smi", runner=runner, timeout=7)

    argumenten, kwargs = oproepen[0]

    assert argumenten == [
        "nvidia-smi",
        "--query-gpu=" + telemetry.NVIDIA_SMI_QUERY,
        "--format=csv,noheader,nounits",
    ]
    assert kwargs["timeout"] == 7
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs.get("shell", False) is False


def test_gpu_standaard_which_en_runner_worden_gebruikt(monkeypatch):
    runner, oproepen = _runner_met(stdout="NVIDIA RTX 4090, 1, 2, 3, 4\n")
    monkeypatch.setattr(telemetry.shutil, "which", lambda naam: "C:\\nvidia-smi.exe")
    monkeypatch.setattr(telemetry.subprocess, "run", runner)

    resultaat = telemetry.gpu_telemetry()

    assert resultaat["ok"] is True
    assert oproepen[0][0][0] == "C:\\nvidia-smi.exe"


# ---------------------------------------------------------------
# collect_telemetry — structuur en foutafhandeling
# ---------------------------------------------------------------

def test_collect_structuur_en_alles_ok(monkeypatch):
    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())
    _vaste_tijd(monkeypatch)
    runner, _ = _runner_met(stdout="NVIDIA RTX 4090, 45, 8192, 24576, 65\n")

    resultaat = telemetry.collect_telemetry(smi_pad="nvidia-smi", runner=runner)

    assert set(resultaat) == {
        "ok", "tijdstip", "systeem", "cpu", "ram", "schijf", "uptime", "gpu", "fouten",
    }
    assert resultaat["ok"] is True
    assert resultaat["fouten"] == []
    assert resultaat["gpu"]["ok"] is True
    for onderdeel in ("systeem", "cpu", "ram", "schijf", "uptime"):
        assert resultaat[onderdeel]["ok"] is True


def test_collect_blijft_ok_zonder_gpu(monkeypatch):
    """Een ontbrekende GPU is normaal: de kern-telemetrie blijft ok."""

    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())
    _vaste_tijd(monkeypatch)

    resultaat = telemetry.collect_telemetry(which=lambda naam: None)

    assert resultaat["ok"] is True
    assert resultaat["gpu"]["ok"] is False
    assert len(resultaat["fouten"]) == 1
    assert resultaat["fouten"][0]["onderdeel"] == "gpu"
    assert resultaat["fouten"][0]["code"] == telemetry.FOUT_NVIDIA_SMI_ONTBREEKT


def test_collect_niet_ok_bij_kernfout(monkeypatch):
    fake = _goede_psutil()
    fake.virtual_memory.side_effect = RuntimeError("kapot")
    monkeypatch.setattr(telemetry, "psutil", fake)
    _vaste_tijd(monkeypatch)

    resultaat = telemetry.collect_telemetry(which=lambda naam: None)

    assert resultaat["ok"] is False
    onderdelen = {fout["onderdeel"] for fout in resultaat["fouten"]}
    assert "ram" in onderdelen


def test_collect_crasht_nooit(monkeypatch):
    fake = MagicMock()
    fake.cpu_count.side_effect = RuntimeError("x")
    fake.cpu_percent.side_effect = RuntimeError("x")
    fake.cpu_freq.side_effect = RuntimeError("x")
    fake.virtual_memory.side_effect = RuntimeError("x")
    fake.disk_usage.side_effect = RuntimeError("x")
    fake.boot_time.side_effect = RuntimeError("x")
    monkeypatch.setattr(telemetry, "psutil", fake)
    _vaste_tijd(monkeypatch)

    def kapotte_runner(argumenten, **kwargs):
        raise RuntimeError("ook kapot")

    resultaat = telemetry.collect_telemetry(smi_pad="nvidia-smi", runner=kapotte_runner)

    assert isinstance(resultaat, dict)
    assert resultaat["ok"] is False
    assert len(resultaat["fouten"]) >= 5


def test_elke_fout_heeft_onderdeel_code_en_melding(monkeypatch):
    monkeypatch.setattr(telemetry, "psutil", _goede_psutil())
    _vaste_tijd(monkeypatch)

    resultaat = telemetry.collect_telemetry(which=lambda naam: None)

    for fout in resultaat["fouten"]:
        assert set(fout) == {"onderdeel", "code", "melding"}
        assert fout["code"]
        assert fout["melding"]
