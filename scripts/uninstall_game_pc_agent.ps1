#Requires -Version 5.1
<#
.SYNOPSIS
    Verwijdert de JARVIS Game-PC Agent-taak netjes.

.DESCRIPTION
    Dit script verwijdert ALLEEN de geplande taak van de Game-PC Agent.
    Het raakt bewust niets anders aan:

      * het .env-bestand blijft staan;
      * memory/, logs/, config/ en de projectbestanden blijven staan;
      * andere JARVIS-taken worden niet aangeraakt;
      * certificaten worden ALLEEN verwijderd met -RemoveCertificates, en
        dan nog alleen de twee bekende bestanden in de cert-map - nooit de
        hele map of recursief.

    Het script is herhaalbaar: staat de taak er niet (meer), dan meldt het
    dat en gaat het verder.

.PARAMETER TaskName
    Naam van de taak die verwijderd moet worden.

.PARAMETER ProjectDir
    Projectmap (standaard de bovenliggende map van dit script).

.PARAMETER RemoveCertificates
    Verwijder ook het certificaat en de sleutel uit de cert-map. Alleen
    deze twee bestanden, nooit recursief.

.PARAMETER CertDir
    Map met het certificaat en de sleutel (standaard <ProjectDir>\certs).

.PARAMETER RemoveFirewallRule
    Verwijder ook de door de installer gemaakte firewallregel.

.PARAMETER Force
    Sla de bevestigingsvraag over.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\uninstall_game_pc_agent.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "JARVIS Game-PC Agent",
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot),
    [string]$CertDir = "",
    [string]$CertName = "agent-cert.pem",
    [string]$KeyName = "agent-key.pem",
    [switch]$RemoveCertificates,
    [switch]$RemoveFirewallRule,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$FirewallRuleName = "JARVIS Game-PC Agent"

function Write-Stap { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Cyan }
function Write-Goed { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Green }
function Write-Waarschuwing { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Yellow }

if ([string]::IsNullOrWhiteSpace($CertDir)) {
    $CertDir = Join-Path $ProjectDir "certs"
}

Write-Stap "JARVIS Game-PC Agent verwijderen."

# --- 1. De geplande taak ------------------------------------------------
$taak = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($taak) {
    if ($taak.State -eq "Running") {
        try { Stop-ScheduledTask -TaskName $TaskName } catch { }
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Goed "Geplande taak '$TaskName' verwijderd."
} else {
    Write-Waarschuwing "Geen geplande taak gevonden met de naam '$TaskName'."
}

# --- 2. Optioneel: firewallregel ---------------------------------------
if ($RemoveFirewallRule) {
    if (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue) {
        Remove-NetFirewallRule -DisplayName $FirewallRuleName
        Write-Goed "Firewallregel '$FirewallRuleName' verwijderd."
    } else {
        Write-Waarschuwing "Geen firewallregel '$FirewallRuleName' gevonden."
    }
}

# --- 3. Optioneel: certificaat en sleutel ------------------------------
#    Alleen de twee bekende bestanden, nooit recursief en nooit de map.
if ($RemoveCertificates) {
    $certPad = Join-Path $CertDir $CertName
    $keyPad = Join-Path $CertDir $KeyName

    $teVerwijderen = @()
    foreach ($pad in @($certPad, $keyPad)) {
        if (Test-Path -LiteralPath $pad -PathType Leaf) { $teVerwijderen += $pad }
    }

    if ($teVerwijderen.Count -eq 0) {
        Write-Waarschuwing "Geen certificaat/sleutel gevonden in '$CertDir'."
    } else {
        Write-Host "Deze bestanden worden verwijderd:"
        $teVerwijderen | ForEach-Object { Write-Host "    $_" }

        $doorgaan = $Force
        if (-not $doorgaan) {
            $antwoord = Read-Host "Weet je het zeker? Typ JA"
            $doorgaan = ($antwoord -eq "JA")
        }

        if ($doorgaan) {
            foreach ($pad in $teVerwijderen) {
                Remove-Item -LiteralPath $pad -Force
                Write-Goed "Verwijderd: $pad"
            }
        } else {
            Write-Waarschuwing "Certificaat/sleutel NIET verwijderd."
        }
    }
}

Write-Host ""
Write-Goed "Klaar."
Write-Host "Niet aangeraakt: .env, memory/, logs/, config/, projectbestanden en andere taken."
Write-Host "Wil je de certificaten ook weg, draai dan met -RemoveCertificates."
exit 0
