# =============================================================
# HANDMATIGE TEST - "afsluiten" annuleren via JARVIS
# =============================================================
# Start een ECHTE afsluit-countdown en controleert of JARVIS die stopt
# wanneer je "annuleer afsluiten" zegt.
#
# VEILIGHEID
#   * De countdown loopt op DEZE pc (de pc waarop u dit script start).
#   * Sla EERST je werk op en sluit dit venster niet tijdens de test.
#   * Het script annuleert de afsluiting ZELF ruim voordat de tijd om is
#     (15 seconden voor het einde). U hoeft dus niet op een toets te drukken
#     om uw pc te redden; de test faalt alleen als JARVIS niets deed.
#   * Daarna controleert het script of er nog een afsluiting liep: liep die
#     er nog, dan heeft JARVIS niet gereageerd (FOUT) en is hij nu geannuleerd.
#
# GEBRUIK
#   Stem:   powershell -ExecutionPolicy Bypass -File scripts\test_power_cancel_manual.ps1
#   Tekst:  powershell -ExecutionPolicy Bypass -File scripts\test_power_cancel_manual.ps1 -Tekst
#
#   -Tekst slaat de microfoon over en stuurt "annuleer afsluiten" direct naar
#   de hersenen van JARVIS. Zo ziet u of het probleem in de spraak zit of in
#   de afhandeling zelf. JARVIS vraagt voor een stroomactie om bevestiging;
#   het script antwoordt dan automatisch "ja" (in hetzelfde proces, zodat de
#   openstaande bevestiging blijft bestaan).
#
#   BELANGRIJK: JARVIS voert stroomacties standaard uit op het doel uit
#   PC_TARGET (meestal de game-pc). Deze test start de countdown op DEZE pc.
#   Het tekstpad zet daarom voor die ene aanroep PC_TARGET=local. Voor de
#   stemtest moet PC_TARGET in .env "local" zijn en main.py daarna herstart.
#
#   Meer tijd: ... -Seconds 120

param(
    [int]$Seconds = 60,
    [switch]$Tekst
)

$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "logs\jarvis.log"

# Ruimte voor de veiligheidsmarge: het script annuleert altijd 15 seconden
# voor het einde van de countdown.
$marge = 15
$controleNa = [Math]::Max(10, $Seconds - $marge)

Write-Host "=== JARVIS: handmatige test 'afsluiten annuleren' ===" -ForegroundColor Cyan
Write-Host "Er wordt een ECHTE afsluit-countdown gestart van $Seconds seconden op DEZE pc." -ForegroundColor Yellow
Write-Host "Dit script annuleert die zelf na $controleNa seconden; uw pc blijft dus aan." -ForegroundColor Yellow
Write-Host "Sluit dit venster niet voordat de uitslag er staat." -ForegroundColor Yellow

if ($Tekst) {
    Write-Host "Modus: tekst (zonder microfoon)." -ForegroundColor Yellow
}
else {
    $pcTarget = ""
    try {
        Push-Location $root
        $pcTarget = (& python -c "import config; print(config.PC_TARGET or 'local')" 2>$null | Select-Object -First 1)
    }
    finally {
        Pop-Location
    }
    $pcTarget = "$pcTarget".Trim().ToLower()
    if ($pcTarget -and $pcTarget -ne "local") {
        Write-Host ""
        Write-Host "WAARSCHUWING: PC_TARGET staat op '$pcTarget'." -ForegroundColor Red
        Write-Host "JARVIS annuleert dan de afsluiting op die pc, niet op deze. Zet" -ForegroundColor Red
        Write-Host "PC_TARGET=local in .env en herstart 'python main.py' voor deze test." -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Zeg daarna tegen JARVIS: 'annuleer afsluiten'." -ForegroundColor Yellow
    Write-Host "JARVIS moet daarvoor draaien (python main.py) en u moet na 'hey jarvis'" -ForegroundColor Yellow
    Write-Host "de pieptoon horen. Herstart JARVIS als u net de wake word-modellen hebt" -ForegroundColor Yellow
    Write-Host "gedownload; een draaiend proces herkent ze niet." -ForegroundColor Yellow
}

if (-not $Tekst) {
    $jarvisProces = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' }
    if (-not $jarvisProces) {
        Write-Host ""
        Write-Host "WAARSCHUWING: er lijkt geen 'python main.py' te draaien." -ForegroundColor Red
        Write-Host "Zonder draaiende JARVIS kan de stemtest niet slagen." -ForegroundColor Red
    }
}

Write-Host ""
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
    $vorigeTarget = $env:PC_TARGET
    # Deze test start de countdown op DEZE pc; laat JARVIS dus ook lokaal
    # annuleren, ongeacht het doel in .env (meestal de game-pc).
    $env:PC_TARGET = "local"
    try {
        & python (Join-Path $root "scripts\cancel_power_text.py")
    }
    finally {
        if ($null -eq $vorigeTarget) {
            Remove-Item Env:\PC_TARGET -ErrorAction SilentlyContinue
        }
        else {
            $env:PC_TARGET = $vorigeTarget
        }
        Pop-Location
    }
}
else {
    Write-Host ""
    Write-Host "Zeg nu tegen JARVIS: 'annuleer afsluiten'." -ForegroundColor Cyan
    Write-Host "Het script controleert automatisch over $controleNa seconden." -ForegroundColor Cyan
    Write-Host "(Druk op een toets om eerder te controleren.)" -ForegroundColor DarkGray

    $einde = (Get-Date).AddSeconds($controleNa)
    $toetsOk = $true
    while ((Get-Date) -lt $einde) {
        $over = [int][Math]::Ceiling(($einde - (Get-Date)).TotalSeconds)
        Write-Host ("`rNog {0,3} s voor de automatische controle... " -f $over) -NoNewline
        if ($toetsOk) {
            try {
                if ([Console]::KeyAvailable) {
                    [Console]::ReadKey($true) | Out-Null
                    break
                }
            }
            catch {
                # Ingevoer omgeleid (bv. vanuit een andere host): geen toetsen.
                $toetsOk = $false
            }
        }
        Start-Sleep -Milliseconds 200
    }
    Write-Host ""
}

# 3) Controle: eerst zelf annuleren, daarna kijken of dat nog nodig was.
#    Heeft JARVIS al geannuleerd, dan vindt 'shutdown /a' geen lopende
#    afsluiting meer -> exitcode != 0  => OK.
#    Vond het nog WEL een lopende afsluiting -> exitcode 0 => JARVIS heeft
#    het niet gestopt. Die is nu geannuleerd, dus de pc blijft aan.
shutdown.exe /a | Out-Null
$code = $LASTEXITCODE

$logRegels = @()
if (Test-Path $log) {
    $logRegels = Get-Content $log -Tail 12 -ErrorAction SilentlyContinue
}

if ($code -eq 0) {
    Write-Host "RESULTAAT: FOUT - er liep nog een afsluiting; JARVIS heeft die niet gestopt." -ForegroundColor Red
    Write-Host "(Het script heeft de afsluiting nu geannuleerd; uw pc blijft aan.)" -ForegroundColor Yellow
    if ($logRegels) {
        Write-Host ""
        Write-Host "Laatste regels uit logs\jarvis.log:" -ForegroundColor Cyan
        $logRegels | ForEach-Object { Write-Host "  $_" }
    }
    Write-Host ""
    Write-Host "Draai de test opnieuw met -Tekst om te zien of het tekstpad wel werkt." -ForegroundColor Yellow
    exit 2
}

Write-Host "RESULTAAT: OK - JARVIS heeft de afsluiting gestopt voordat de controle kwam." -ForegroundColor Green
exit 0
