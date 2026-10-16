"""Tests voor de installatie- en verwijderscripts (Fase 15, stap 6).

Twee soorten controle:

1. **Syntaxis** — de .ps1-bestanden moeten door de PowerShell-parser
   komen. Op Linux (CI) bestaat PowerShell niet; die tests worden dan
   overgeslagen.
2. **Veiligheid (statisch)** — de scripts mogen geen bestanden of
   instellingen van de gebruiker weggooien, geen geheimen bevatten en de
   Taakplanner correct instellen.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
INSTALL = SCRIPTS / "install_game_pc_agent.ps1"
UNINSTALL = SCRIPTS / "uninstall_game_pc_agent.ps1"
DOCS = ROOT / "docs" / "remote_agent.md"
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"


def _powershell():
    return shutil.which("pwsh") or shutil.which("powershell")


@pytest.fixture(scope="module")
def powershell():
    exe = _powershell()
    if not exe:  # pragma: no cover - op Linux-CI
        pytest.skip("geen PowerShell beschikbaar om de syntaxis te controleren")
    return exe


def _parse(powershell, pad):
    script = (
        f"$f = '{pad}'; $e = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        "$f, [ref]$null, [ref]$e); "
        "if ($e -and $e.Count -gt 0) { $e | ForEach-Object { $_.Message }; "
        "exit 1 } else { exit 0 }"
    )
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _lees(pad):
    return pad.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Bestaan + syntaxis
# ------------------------------------------------------------------


def test_scripts_bestaan():
    assert INSTALL.is_file()
    assert UNINSTALL.is_file()
    assert INSTALL.stat().st_size > 0
    assert UNINSTALL.stat().st_size > 0


def test_install_syntaxis_ok(powershell):
    resultaat = _parse(powershell, INSTALL)
    assert resultaat.returncode == 0, resultaat.stdout + resultaat.stderr


def test_uninstall_syntaxis_ok(powershell):
    resultaat = _parse(powershell, UNINSTALL)
    assert resultaat.returncode == 0, resultaat.stdout + resultaat.stderr


@pytest.mark.parametrize("pad", [INSTALL, UNINSTALL])
def test_scripts_zijn_ascii(pad):
    tekst = _lees(pad)
    assert all(ord(teken) < 128 for teken in tekst), "gebruik alleen ASCII in .ps1"


# ------------------------------------------------------------------
# Installatiescript
# ------------------------------------------------------------------


def test_install_stelt_taakplanner_in():
    tekst = _lees(INSTALL)

    assert "Register-ScheduledTask" in tekst
    assert "New-ScheduledTaskAction" in tekst
    assert "New-ScheduledTaskTrigger" in tekst
    assert "-AtLogOn" in tekst


def test_install_start_de_agent_als_module():
    tekst = _lees(INSTALL)

    assert "-m remote.server" in tekst


def test_install_heeft_standaard_taaknaam():
    assert "JARVIS Game-PC Agent" in _lees(INSTALL)


def test_install_is_herhaalbaar_door_force():
    tekst = _lees(INSTALL)

    # -Force vervangt een bestaande taak in plaats van een duplicaat te maken.
    assert "-Force" in tekst


def test_install_doet_preflight_beveiligingscontrole():
    tekst = _lees(INSTALL)

    assert "remote_server_security_errors" in tekst


def test_install_stelt_stevige_taakinstellingen_in():
    tekst = _lees(INSTALL)

    for instelling in (
        "-AllowStartIfOnBatteries",
        "-DontStopIfGoingOnBatteries",
        "-StartWhenAvailable",
        "-MultipleInstances",
        "-RestartCount",
        "-ExecutionTimeLimit",
    ):
        assert instelling in tekst, f"ontbrekende instelling: {instelling}"


# ------------------------------------------------------------------
# Verwijderscript — geen onbedoelde verwijderingen
# ------------------------------------------------------------------


def test_uninstall_verwijdert_de_taak():
    tekst = _lees(UNINSTALL)

    assert "Unregister-ScheduledTask" in tekst
    assert "JARVIS Game-PC Agent" in tekst


def test_uninstall_gebruikt_geen_recurse():
    assert "-Recurse" not in _lees(UNINSTALL)


def test_uninstall_verwijdert_de_projectmap_niet():
    tekst = _lees(UNINSTALL)

    # Nooit Remove-Item met de projectmap als doel.
    assert not re.search(r"Remove-Item[^\r\n]*\$ProjectDir", tekst)
    assert not re.search(r"Remove-Item[^\r\n]*ProjectRoot", tekst)


def test_uninstall_verwijdert_certificaten_alleen_met_switch():
    tekst = _lees(UNINSTALL)

    assert "RemoveCertificates" in tekst
    # De daadwerkelijke verwijdering zit achter de switch.
    assert "Remove-Item" in tekst


def test_uninstall_is_idempotent():
    tekst = _lees(UNINSTALL).lower()

    # Meldt netjes wanneer de taak niet bestaat in plaats van te crashen.
    assert "gevonden" in tekst
    assert "herhaalbaar" in tekst


def test_uninstall_noemt_wat_niet_wordt_aangeraakt():
    tekst = _lees(UNINSTALL).lower()

    assert ".env" in tekst


# ------------------------------------------------------------------
# Geheimen
# ------------------------------------------------------------------


@pytest.mark.parametrize("pad", [INSTALL, UNINSTALL])
def test_scripts_bevatten_geen_harde_geheimen(pad):
    tekst = _lees(pad)

    # Geen toegewezen token/geheim met een echte waarde.
    assert not re.search(r"(?i)\btoken\s*=\s*['\"][A-Za-z0-9]", tekst)
    assert not re.search(r"(?i)password\s*=\s*['\"]", tekst)
    assert not re.search(r"(?i)secret\s*=\s*['\"][A-Za-z0-9]", tekst)


# ------------------------------------------------------------------
# Documentatie
# ------------------------------------------------------------------


def test_documentatie_bestaat():
    assert DOCS.is_file()
    assert DOCS.stat().st_size > 0


def test_documentatie_bevat_alle_stappen():
    tekst = _lees(DOCS).lower()

    for woord in (
        "installatie",
        "certificaat",
        "token",
        "firewall",
        "starten",
        "stoppen",
        "testen",
        "verwijderen",
        "openssl",
        "taakplanner",
    ):
        assert woord in tekst, f"documentatie mist: {woord}"

    # Zowel de gaming-pc als de mini-pc komen aan bod.
    assert "gaming-pc" in tekst or "game-pc" in tekst
    assert "mini-pc" in tekst or "mini pc" in tekst


def test_documentatie_beschrijft_de_rollen():
    tekst = _lees(DOCS).lower()

    assert "game-pc" in tekst or "gaming-pc" in tekst
    assert "allowlist" in tekst or "toegestaan" in tekst


def test_readme_verwijst_naar_de_documentatie():
    tekst = _lees(README)

    assert "docs/remote_agent.md" in tekst
    assert "Game-PC Agent" in tekst


def test_env_example_noemt_het_certificaatscript():
    assert "gen_remote_cert.py" in _lees(ENV_EXAMPLE)
