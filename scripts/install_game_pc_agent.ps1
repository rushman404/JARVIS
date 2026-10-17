#Requires -Version 5.1
<#
.SYNOPSIS
    Installeert de JARVIS Game-PC Agent als geplande taak (auto-start).

.DESCRIPTION
    Maakt (of werkt bij) een Windows Taakplanner-taak die de remote-agent
    automatisch start wanneer de gebruiker inlogt. Draai dit script op de
    GAME-PC.

    Het script is herhaalbaar: dezelfde taaknaam wordt bijgewerkt in plaats
    van een tweede taak aan te maken. Er worden geen geheimen in de taak
    opgeslagen: de agent leest zijn token en certificaat uit het .env-bestand
    van het project.

.PARAMETER ProjectDir
    De map met daarin remote\server.py (standaard de bovenliggende map van
    dit script).

.PARAMETER PythonPath
    Pad naar python.exe. Standaard wordt .venv\Scripts\python.exe of de
    'python' op het PATH gebruikt.

.PARAMETER TaskName
    Naam van de geplande taak.

.PARAMETER User
    De gebruiker waaronder de taak bij inloggen start (standaard: huidige).

.PARAMETER AddFirewallRule
    Maakt (of werkt bij) een inkomende firewallregel voor de agent-poort.

.PARAMETER AllowedRemoteAddress
    Verplicht bij -AddFirewallRule: beperk de firewallregel tot dit adres
    (bijv. het IP van de mini-pc). Er is bewust geen standaardwaarde, zodat
    je nooit per ongeluk het hele subnet opent.

.PARAMETER DryRun
    Laat alleen zien wat er zou gebeuren; wijzigt niets.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_game_pc_agent.ps1
#>
[CmdletBinding()]
param(
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "",
    [string]$TaskName = "JARVIS Game-PC Agent",
    [string]$User = $env:USERNAME,
    [int]$Port = 8765,
    [switch]$AddFirewallRule,
    [string]$AllowedRemoteAddress = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$FirewallRuleName = "JARVIS Game-PC Agent"

function Write-Stap { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Cyan }
function Write-Goed { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Green }
function Write-Waarschuwing { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Yellow }
function Stop-Met-Fout { param([string]$Tekst) Write-Host "[JARVIS] FOUT: $Tekst" -ForegroundColor Red; exit 1 }

Write-Stap "JARVIS Game-PC Agent installeren."

# --- 1. Projectmap controleren ---------------------------------------------
if (-not (Test-Path (Join-Path $ProjectDir "remote\server.py"))) {
    Stop-Met-Fout "Geen remote\server.py gevonden in '$ProjectDir'. Geef -ProjectDir op."
}
$ProjectDir = (Resolve-Path $ProjectDir).Path
Write-Goed "Projectmap: $ProjectDir"

# --- 2. Python vinden -------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $kandidaat = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $kandidaat) {
        $PythonPath = $kandidaat
    } else {
        $opdracht = Get-Command python -ErrorAction SilentlyContinue
        if ($opdracht) { $PythonPath = $opdracht.Source }
    }
}
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    Stop-Met-Fout "Geen python.exe gevonden. Geef -PythonPath op."
}
if (-not (Test-Path $PythonPath)) {
    $opdracht = Get-Command $PythonPath -ErrorAction SilentlyContinue
    if (-not $opdracht) { Stop-Met-Fout "python.exe niet gevonden op '$PythonPath'." }
    $PythonPath = $opdracht.Source
}
Write-Goed "Python: $PythonPath"

# --- 3. Beveiligingsconfiguratie vooraf controleren -------------------------
#    De agent start alleen met een token en een geldig certificaat. We laten
#    config.py dat hier alvast controleren, zodat de taak niet stilletjes
#    blijft falen. Er worden geen geheimen geprint.
Write-Stap "Beveiligingsconfiguratie controleren (token + certificaat)."
$controle = "import sys`nimport config`nfouten = config.remote_server_security_errors()`nprint(chr(10).join(fouten))`nsys.exit(1 if fouten else 0)"
Push-Location $ProjectDir
try {
    & $PythonPath -c $controle
    $controleCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($controleCode -ne 0) {
    Write-Waarschuwing "De beveiligingsconfiguratie is nog niet compleet:"
    Write-Waarschuwing "Vul in het .env-bestand op de game-pc REMOTE_SERVER_ENABLED=1,"
    Write-Waarschuwing "REMOTE_SERVER_TOKEN, REMOTE_SERVER_CERT_FILE en REMOTE_SERVER_KEY_FILE in."
    Write-Waarschuwing "Genereer het certificaat met: python scripts\gen_remote_cert.py"
    if (-not $DryRun) {
        Stop-Met-Fout "Installatie afgebroken: eerst de beveiligingsconfiguratie compleet maken."
    }
}

# --- 4. De geplande taak samenstellen --------------------------------------
$actie = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "-m remote.server" `
    -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User

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
Write-Host "    Actie  : $PythonPath -m remote.server"
Write-Host "    Trigger: bij inloggen van $User"
Write-Host "    Werkmap: $ProjectDir"

if ($DryRun) {
    Write-Waarschuwing "DryRun: er wordt geen taak aangemaakt of gewijzigd."
} else {
    # Register-ScheduledTask met -Force werkt een bestaande taak bij, zodat
    # opnieuw draaien nooit een tweede taak oplevert.
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $actie `
        -Trigger $trigger `
        -Settings $instellingen `
        -Principal $principal `
        -Description "Start de JARVIS Game-PC Agent (remote/server.py) na inloggen." `
        -Force | Out-Null
    Write-Goed "Geplande taak geregistreerd/bijgewerkt."
}

# --- 5. Optionele firewallregel --------------------------------------------
if ($AddFirewallRule) {
    if (-not $AllowedRemoteAddress) {
        Stop-Met-Fout "Geef -AllowedRemoteAddress op (bijv. het IP van de mini-pc). Zonder deze waarde zou de regel het hele subnet openstellen."
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
            -LocalPort $Port `
            -RemoteAddress $AllowedRemoteAddress | Out-Null
        Write-Goed "Firewallregel '$FirewallRuleName' actief voor poort $Port (profiel: prive, bron: $AllowedRemoteAddress)."
    }
}

# --- 6. Volgende stappen ----------------------------------------------------
Write-Host ""
Write-Goed "Klaar."
Write-Host "Volgende stappen:"
Write-Host "  * Nu starten : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  * Stoppen    : Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  * Status     : Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  * Verwijderen: powershell -ExecutionPolicy Bypass -File scripts\uninstall_game_pc_agent.ps1"
if (-not $AddFirewallRule) {
    Write-Host "  * Firewall   : draai dit script met -AddFirewallRule -AllowedRemoteAddress <ip-van-de-mini-pc>"
    Write-Host "                 (of stel de regel handmatig in; zie docs\remote_agent.md)."
}
exit 0
