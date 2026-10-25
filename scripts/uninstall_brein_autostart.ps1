#Requires -Version 5.1
<#
.SYNOPSIS
    Verwijdert de auto-start van het JARVIS-brein (Fase 19, M2).

.DESCRIPTION
    Stopt en verwijdert ALLEEN de geplande taak "JARVIS Brein" (de waakhond
    stopt JARVIS daarbij mee). .env, memory/, logs/, config/, certificaten,
    de projectbestanden en andere taken worden niet aangeraakt.

    Herhaalbaar: staat de taak er niet (meer), dan meldt het dat.

.PARAMETER TaskName
    Naam van de taak die verwijderd moet worden.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\uninstall_brein_autostart.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "JARVIS Brein"
)

$ErrorActionPreference = "Stop"

function Write-Stap { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Cyan }
function Write-Goed { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Green }
function Write-Waarschuwing { param([string]$Tekst) Write-Host "[JARVIS] $Tekst" -ForegroundColor Yellow }

Write-Stap "Auto-start van het JARVIS-brein verwijderen."

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

Write-Host ""
Write-Goed "Klaar."
Write-Host "Niet aangeraakt: .env, memory/, logs/, config/, certificaten, projectbestanden en andere taken."
exit 0
