# =============================================================
# HANDMATIGE TEST - "afsluiten" annuleren via JARVIS
# =============================================================
# Start een ECHTE afsluit-countdown en controleert of JARVIS die stopt
# wanneer je "annuleer afsluiten" zegt.
#
# VEILIGHEID
#   * Je hebt $Seconds seconden (standaard 60).
#   * Sla EERST je werk op.
#   * Draai dit script in een gewone PowerShell op DEZELFDE pc als JARVIS.
#   * Het script annuleert aan het einde altijd een nog lopende afsluiting
#     (shutdown /a), zodat de pc niet onbedoeld afsluit.
#
# GEBRUIK
#   Stem:   powershell -ExecutionPolicy Bypass -File scripts\test_power_cancel_manual.ps1
#   Tekst:  powershell -ExecutionPolicy Bypass -File scripts\test_power_cancel_manual.ps1 -Tekst
#
#   -Tekst slaat de microfoon over en stuurt "annuleer afsluiten" direct naar
#   de hersenen van JARVIS. Zo ziet u of het probleem in de spraak zit of in
#   de afhandeling zelf.
#
#   Meer tijd: ... -Seconds 120

param(
    [int]$Seconds = 60,
    [switch]$Tekst
)

$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "logs\jarvis.log"

Write-Host "=== JARVIS: handmatige test 'afsluiten annuleren' ===" -ForegroundColor Cyan
Write-Host "Er wordt een ECHTE afsluit-countdown gestart van $Seconds seconden." -ForegroundColor Yellow
if ($Tekst) {
    Write-Host "Modus: tekst (zonder microfoon)." -ForegroundColor Yellow
}
else {
    Write-Host "Zeg daarna tegen JARVIS: 'annuleer afsluiten'." -ForegroundColor Yellow
    Write-Host "Let op: JARVIS moet draaien (python main.py) en u moet na 'hey jarvis'" -ForegroundColor Yellow
    Write-Host "de pieptoon horen. Start JARVIS opnieuw als u net pas de wake word-" -ForegroundColor Yellow
    Write-Host "modellen heeft gedownload; een draaiend proces herkent ze niet." -ForegroundColor Yellow
}
Write-Host "Sla nu je werk op!" -ForegroundColor Yellow
$antwoord = Read-Host "Typ JA om te starten"

if ($antwoord -ne "JA") {
    Write-Host "Gestopt."
    exit 0
}

if (-not (Get-Command shutdown.exe -ErrorAction SilentlyContinue)) {
    Write-Host "shutdown.exe niet gevonden." -ForegroundColor Red
    exit 1
}

# 1) Start de countdown (dit is de actie die JARVIS normaal uitvoert).
shutdown.exe /s /t $Seconds /c "JARVIS handmatige test"
Write-Host "Afsluit-countdown gestart over $Seconds seconden." -ForegroundColor Green

# 2) Laat JARVIS annuleren (via de microfoon of direct via de hersenen).
if ($Tekst) {
    Write-Host "JARVIS krijgt nu 'annuleer afsluiten' via het tekstpad..." -ForegroundColor Cyan
    Push-Location $root
    try {
        & python -c "from core.brain import process_command; print(process_command('annuleer afsluiten'))"
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "Zeg nu tegen JARVIS: 'annuleer afsluiten'." -ForegroundColor Cyan
    Read-Host "Wacht tot JARVIS antwoordt en druk daarna op ENTER"
}

# 3) Controle.
#    Heeft JARVIS al geannuleerd, dan vindt 'shutdown /a' geen lopende
#    afsluiting meer -> exitcode != 0  => OK.
#    Vond het nog WEL een lopende afsluiting -> exitcode 0 => JARVIS heeft
#    het niet gestopt. Het script annuleert die dan als veiligheidsnet.
shutdown.exe /a | Out-Null
$code = $LASTEXITCODE

$logRegels = @()
if (Test-Path $log) {
    $logRegels = Get-Content $log -Tail 12 -ErrorAction SilentlyContinue
}

if ($code -eq 0) {
    Write-Host "RESULTAAT: FOUT - er liep nog een afsluiting; JARVIS heeft die niet gestopt." -ForegroundColor Red
    Write-Host "(Het script heeft de afsluiting nu geannuleerd als veiligheidsnet.)" -ForegroundColor Yellow
    if ($logRegels) {
        Write-Host ""
        Write-Host "Laatste regels uit logs\jarvis.log:" -ForegroundColor Cyan
        $logRegels | ForEach-Object { Write-Host "  $_" }
    }
    Write-Host ""
    Write-Host "Draai de test opnieuw met -Tekst om te zien of het tekstpad wel werkt." -ForegroundColor Yellow
    exit 2
}

Write-Host "RESULTAAT: OK - er liep geen afsluiting meer; JARVIS heeft 'afsluiten' geannuleerd." -ForegroundColor Green
exit 0
