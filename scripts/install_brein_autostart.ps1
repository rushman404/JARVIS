#Requires -Version 5.1
<#
.SYNOPSIS
    Laat het JARVIS-brein automatisch starten bij inloggen (Fase 19, M2).

.DESCRIPTION
    Maakt (of werkt bij) de geplande taak "JARVIS Brein". Die start niet
    JARVIS zelf, maar de waakhond (python -m beheer.waakhond). De waakhond
    start main.py en herstart hem na een crash of vastloper.

    De taak draait in de ingelogde sessie (Interactive), want JARVIS
    gebruikt de microfoon en de speaker. Wilt u dat JARVIS ook na een
    stroomstoring of Windows-update vanzelf terugkomt, zet dan het
    automatisch inloggen aan (zie docs\mini_pc_brein.md, hoofdstuk 3).

    Herhaalbaar: dezelfde taaknaam wordt bijgewerkt. Er komen geen
    geheimen in de taak; JARVIS leest alles uit .env.

.PARAMETER ProjectDir
    De map met main.py (standaard de bovenliggende map van dit script).

.PARAMETER PythonPath
    Pad naar python.exe. Standaard .venv\Scripts\python.exe, anders de
    'python' op het PATH.

.PARAMETER TaskName
    Naam van de geplande taak.

.PARAMETER User
    De gebruiker waaronder de taak bij inloggen start (standaard: huidige).

.PARAMETER StartNu
    Start de taak meteen na het installeren.

.PARAMETER DryRun
    Laat alleen zien wat er zou gebeuren; wijzigt niets.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_brein_autostart.ps1 -StartNu
#>
[CmdletBinding()]
param(
    [string]$ProjectDir = "",
    [string]$PythonPath = "",
    [string]$TaskName = "JARVIS Brein",
    [string]$User = $env:USERNAME,
    [switch]$StartNu,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Stap { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Cyan }
function Write-Goed { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Green }
function Write-Waarschuwing { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Yellow }
function Stop-Met-Fout { param([string]$Tekst) Write-Host "[JARVIS] FOUT: $Tekst" -ForegroundColor Red; exit 1 }

# $PSScriptRoot is in Windows PowerShell 5.1 nog leeg binnen param().
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $scriptMap = $PSScriptRoot
    if (-not $scriptMap) { $scriptMap = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $ProjectDir = Split-Path -Parent $scriptMap
}

Write-Stap "Auto-start van het JARVIS-brein instellen."

# --- 1. Projectmap ----------------------------------------------------------
if (-not (Test-Path (Join-Path $ProjectDir "beheer\waakhond.py"))) {
    Stop-Met-Fout "Geen beheer\waakhond.py gevonden in '$ProjectDir'. Geef -ProjectDir op."
}
$ProjectDir = (Resolve-Path $ProjectDir).Path
Write-Goed "Projectmap: $ProjectDir"

# --- 2. Python --------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $kandidaat = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $kandidaat) {
        $PythonPath = $kandidaat
    } else {
        $opdracht = Get-Command python -ErrorAction SilentlyContinue
        if ($opdracht) { $PythonPath = $opdracht.Source }
    }
}
if ([string]::IsNullOrWhiteSpace($PythonPath)) { Stop-Met-Fout "Geen python.exe gevonden. Geef -PythonPath op." }
if (-not (Test-Path $PythonPath)) {
    $opdracht = Get-Command $PythonPath -ErrorAction SilentlyContinue
    if (-not $opdracht) { Stop-Met-Fout "python.exe niet gevonden op '$PythonPath'." }
    $PythonPath = $opdracht.Source
}
Write-Goed "Python: $PythonPath"

# --- 3. Eerst de controle ---------------------------------------------------
Write-Stap "Controle van het brein (scripts\brein_check.py)."
Push-Location $ProjectDir
try {
    & $PythonPath scripts\brein_check.py
    $gezond = ($LASTEXITCODE -eq 0)
} finally {
    Pop-Location
}
if (-not $gezond) {
    Write-Waarschuwing "Er staan nog kruisjes in de controle. De taak wordt wel ingesteld, maar"
    Write-Waarschuwing "JARVIS werkt pas goed als die zijn opgelost."
}

# --- 4. De geplande taak ----------------------------------------------------
$actie = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "-m beheer.waakhond" `
    -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User

# De waakhond herstart JARVIS zelf; de taak herstart alleen de waakhond als
# die onverwacht stopt.
$instellingen = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited

Write-Stap "Geplande taak: '$TaskName'"
Write-Host "    Actie  : $PythonPath -m beheer.waakhond"
Write-Host "    Trigger: bij inloggen van $User"
Write-Host "    Werkmap: $ProjectDir"

if ($DryRun) {
    Write-Waarschuwing "DryRun: er wordt geen taak aangemaakt of gewijzigd."
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $actie `
        -Trigger $trigger `
        -Settings $instellingen `
        -Principal $principal `
        -Description "Start de JARVIS-waakhond (beheer\waakhond.py), die JARVIS start en bewaakt." `
        -Force | Out-Null
    Write-Goed "Geplande taak geregistreerd/bijgewerkt."

    if ($StartNu) {
        Start-ScheduledTask -TaskName $TaskName
        Write-Goed "Taak gestart."
    }
}

# --- 5. Volgende stappen ----------------------------------------------------
Write-Host ""
Write-Goed "Klaar."
Write-Host "  * Nu starten : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  * Stoppen    : Stop-ScheduledTask -TaskName '$TaskName'  (JARVIS stopt mee)"
Write-Host "  * Status     : Get-Content logs\waakhond.json"
Write-Host "  * Verwijderen: powershell -ExecutionPolicy Bypass -File scripts\uninstall_brein_autostart.ps1"
Write-Host "  * Auto-login en energie-instellingen: zie docs\mini_pc_brein.md, hoofdstuk 3."
exit 0
