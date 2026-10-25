#Requires -Version 5.1
<#
.SYNOPSIS
    Installeert het JARVIS-brein op deze pc (Fase 19, M1).

.DESCRIPTION
    Zet alles klaar wat het brein nodig heeft, in deze volgorde:

      1. Projectmap en Python (3.11 of nieuwer) controleren.
      2. Virtuele omgeving .venv maken en de pakketten installeren.
      3. Ollama controleren en het AI-model ophalen (AI_MODEL uit .env).
      4. De wake-word-modellen (hey_jarvis) ophalen.
      5. Een Piper-stem ophalen als er nog geen is.
      6. .env: terugzetten uit een migratiepakket (-ImportPakket) of
         aanmaken uit .env.example.
      7. Optioneel: een firewallregel voor het dashboard (poort 8780).
      8. De controle draaien (scripts\brein_check.py).

    Het script is herhaalbaar: wat al klaar is, wordt overgeslagen. Het
    print nooit tokens of sleutels. Auto-start bij inloggen volgt in M2.

.PARAMETER ProjectDir
    De map met main.py (standaard de bovenliggende map van dit script).

.PARAMETER ImportPakket
    Een pakket van scripts\brein_export.py (van de oude pc). Wordt na de
    installatie van de pakketten teruggezet.

.PARAMETER InstallOllama
    Installeer Ollama met winget als het ontbreekt.

.PARAMETER SkipModel
    Haal het AI-model niet op (handig bij een trage verbinding).

.PARAMETER AddFirewallRule
    Maakt (of werkt bij) een inkomende firewallregel voor het dashboard.

.PARAMETER AllowedRemoteAddress
    Verplicht bij -AddFirewallRule: het IP van de iPad. Er is bewust geen
    standaardwaarde, zodat u nooit per ongeluk het hele subnet opent.

.PARAMETER DryRun
    Laat alleen zien wat er zou gebeuren; wijzigt niets.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_brein.ps1 -ImportPakket E:\jarvis-brein-LAPTOP-20261025-120000.zip
#>
[CmdletBinding()]
param(
    [string]$ProjectDir = "",
    [string]$ImportPakket = "",
    [switch]$InstallOllama,
    [switch]$SkipModel,
    [int]$DashboardPort = 8780,
    [switch]$AddFirewallRule,
    [string]$AllowedRemoteAddress = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$FirewallRuleName = "JARVIS Dashboard"

# $PSScriptRoot is in Windows PowerShell 5.1 nog leeg binnen param(),
# dus de standaardmap pas hier bepalen.
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $scriptMap = $PSScriptRoot
    if (-not $scriptMap) { $scriptMap = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $ProjectDir = Split-Path -Parent $scriptMap
}

function Write-Stap { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Cyan }
function Write-Goed { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Green }
function Write-Waarschuwing { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Yellow }
function Stop-Met-Fout { param([string]$Tekst) Write-Host "[JARVIS] FOUT: $Tekst" -ForegroundColor Red; exit 1 }

function Invoke-Stap {
    # Voert een commando uit, of toont het alleen bij -DryRun.
    param([string]$Omschrijving, [scriptblock]$Blok)
    if ($DryRun) {
        Write-Waarschuwing "DryRun: $Omschrijving"
        return
    }
    & $Blok
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        Stop-Met-Fout "$Omschrijving is mislukt (code $LASTEXITCODE)."
    }
}

Write-Stap "JARVIS-brein installeren."

# --- 1. Projectmap en Python -----------------------------------------------
if (-not (Test-Path (Join-Path $ProjectDir "main.py"))) {
    Stop-Met-Fout "Geen main.py gevonden in '$ProjectDir'. Geef -ProjectDir op."
}
$ProjectDir = (Resolve-Path $ProjectDir).Path
Set-Location $ProjectDir
Write-Goed "Projectmap: $ProjectDir"

$venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$basisPython = $null
foreach ($kandidaat in @("py", "python")) {
    $opdracht = Get-Command $kandidaat -ErrorAction SilentlyContinue
    if ($opdracht) { $basisPython = $opdracht.Source; break }
}
if (-not (Test-Path $venvPython) -and -not $basisPython) {
    Stop-Met-Fout "Python ontbreekt. Installeer Python 3.11+ van python.org (vink 'Add to PATH' aan)."
}
$versieCheck = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
$teControleren = $venvPython
if (-not (Test-Path $venvPython)) { $teControleren = $basisPython }
& $teControleren -c $versieCheck
if ($LASTEXITCODE -ne 0) { Stop-Met-Fout "Python is ouder dan 3.11. Installeer een nieuwere versie." }
Write-Goed "Python: $teControleren"

# --- 2. Virtuele omgeving en pakketten -------------------------------------
if (-not (Test-Path $venvPython)) {
    Write-Stap "Virtuele omgeving .venv maken."
    Invoke-Stap "python -m venv .venv" { & $basisPython -m venv (Join-Path $ProjectDir ".venv") }
}
$Python = $venvPython
if ($DryRun -and -not (Test-Path $Python)) { $Python = $basisPython }

Write-Stap "Pakketten installeren (requirements.txt + requirements-dev.txt)."
Invoke-Stap "pip install" {
    & $Python -m pip install --upgrade pip --quiet
    & $Python -m pip install -r requirements.txt -r requirements-dev.txt --quiet
}

# --- 3. Migratiepakket terugzetten (vóór .env-controle en Ollama) ----------
if ($ImportPakket) {
    if (-not (Test-Path $ImportPakket)) { Stop-Met-Fout "Pakket niet gevonden: $ImportPakket" }
    Write-Stap "Migratiepakket terugzetten."
    Invoke-Stap "brein_import.py" { & $Python scripts\brein_import.py $ImportPakket --ja }
}

# --- 4. .env ----------------------------------------------------------------
$envPad = Join-Path $ProjectDir ".env"
if (Test-Path $envPad) {
    Write-Goed ".env is aanwezig."
} else {
    Write-Waarschuwing ".env ontbreekt: ik maak er een uit .env.example. Vul hem daarna in."
    Invoke-Stap "copy .env.example .env" { Copy-Item (Join-Path $ProjectDir ".env.example") $envPad }
}

# --- 5. Ollama en het AI-model ---------------------------------------------
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    if ($InstallOllama) {
        Write-Stap "Ollama installeren met winget."
        Invoke-Stap "winget install Ollama.Ollama" { winget install --id Ollama.Ollama -e --accept-package-agreements }
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    }
    if (-not $ollama) {
        Write-Waarschuwing "Ollama ontbreekt. Installeer het van ollama.com of draai dit script met -InstallOllama."
    }
}
if ($ollama -and -not $SkipModel) {
    $model = (& $Python -c "import config; print(config.AI_MODEL)").Trim()
    $aanwezig = (& ollama list 2>$null) -match [regex]::Escape($model)
    if ($aanwezig) {
        Write-Goed "AI-model $model is aanwezig."
    } else {
        Write-Stap "AI-model $model ophalen (kan even duren)."
        Invoke-Stap "ollama pull $model" { & ollama pull $model }
    }
}

# --- 6. Wake word -----------------------------------------------------------
$wakeCheck = "from beheer import dokter; import sys; sys.exit(0 if dokter.controleer_wake_word().status == dokter.OK else 1)"
& $Python -c $wakeCheck 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Goed "Wake-word-model hey_jarvis is aanwezig."
} else {
    Write-Stap "Wake-word-modellen ophalen."
    Invoke-Stap "openwakeword download_models" { & $Python -c "from openwakeword.utils import download_models; download_models()" }
}

# --- 7. Piper-stem ----------------------------------------------------------
$stemmen = Get-ChildItem -Path (Join-Path $ProjectDir "voice\models") -Filter *.onnx -ErrorAction SilentlyContinue
if ($stemmen) {
    Write-Goed "Piper-stem aanwezig: $($stemmen[0].Name)"
} else {
    Write-Stap "Piper-stem ophalen."
    Invoke-Stap "download_piper_voice.py" { & $Python scripts\download_piper_voice.py }
}

# --- 8. Optionele firewallregel voor het dashboard -------------------------
if ($AddFirewallRule) {
    if (-not $AllowedRemoteAddress) {
        Stop-Met-Fout "Geef -AllowedRemoteAddress op (het IP van de iPad). Zonder deze waarde zou de regel het hele subnet openstellen."
    }
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if (-not $isAdmin) {
        Write-Waarschuwing "Firewallregel overslaan: start PowerShell als administrator."
    } elseif ($DryRun) {
        Write-Waarschuwing "DryRun: firewallregel '$FirewallRuleName' wordt niet aangepast."
    } else {
        if (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue) {
            Remove-NetFirewallRule -DisplayName $FirewallRuleName
        }
        New-NetFirewallRule `
            -DisplayName $FirewallRuleName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -Profile Private `
            -LocalPort $DashboardPort `
            -RemoteAddress $AllowedRemoteAddress | Out-Null
        Write-Goed "Firewallregel '$FirewallRuleName' actief voor poort $DashboardPort (profiel: prive, bron: $AllowedRemoteAddress)."
    }
}

# --- 9. Controle ------------------------------------------------------------
Write-Host ""
Write-Stap "Controle van het brein:"
& $Python scripts\brein_check.py
$gezond = ($LASTEXITCODE -eq 0)

Write-Host ""
if ($gezond) {
    Write-Goed "Klaar: het brein is geinstalleerd."
} else {
    Write-Waarschuwing "Geinstalleerd, maar los eerst de punten met een kruisje op en draai dan opnieuw: python scripts\brein_check.py"
}
Write-Host "Starten: .\.venv\Scripts\python.exe main.py"
if (-not $AddFirewallRule) {
    Write-Host "Dashboard-firewall: draai dit script als administrator met -AddFirewallRule -AllowedRemoteAddress <ip-van-de-ipad>"
}
exit 0
