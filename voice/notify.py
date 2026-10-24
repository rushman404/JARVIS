"""Windows-meldingen (Fase 16A — proactieve JARVIS).

Toont een korte Windows 10/11-toast via PowerShell (geen extra pip-
afhankelijkheid). Faalt de toast (bijv. op een systeem zonder Windows
Runtime-notificaties), dan geeft de functie False terug en logt hij een
waarschuwing: de aanroeper kan dan terugvallen op alleen spraak/beep.

Ontwerpregels
-------------
* **Nooit crashen.** Elke fout wordt gevangen; een mislukte toast mag een
  proactieve melding nooit laten stranden.
* **Veilig extern proces.** PowerShell krijgt een vaste argumentenlijst
  (nooit ``shell=True``) en een harde time-out; de meldingstekst gaat via
  een omgevingsvariabele zodat er niets in het commando wordt geïnjecteerd.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Harde time-out (seconden) voor het PowerShell-proces.
TOAST_TIMEOUT_SECONDS = 10

# App-ID waaronder de toast verschijnt. CreateToastNotifier() zonder app-ID
# faalt op veel Windows-installaties met 0x80070490 ("Kan element niet
# vinden"); de app-ID van Windows PowerShell zelf is altijd geregistreerd.
TOAST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# PowerShell-script: bouwt een tweeregelige toast (titel + tekst) via de
# Windows Runtime en toont die met de ingebouwde notifier. De tekst komt
# uit de omgevingsvariabelen JARVIS_TOAST_TITLE / JARVIS_TOAST_MESSAGE,
# zodat er geen tekst in het script zelf wordt geïnjecteerd.
_TOAST_SCRIPT = (
    "$ErrorActionPreference = 'Stop'\n"
    "[void][Windows.UI.Notifications.ToastNotificationManager, "
    "Windows.UI.Notifications, ContentType = WindowsRuntime]\n"
    "$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02\n"
    "$xml = [Windows.UI.Notifications.ToastNotificationManager]"
    "::GetTemplateContent($template)\n"
    "$texts = $xml.GetElementsByTagName('text')\n"
    "[void]$texts.Item(0).AppendChild($xml.CreateTextNode("
    "$env:JARVIS_TOAST_TITLE))\n"
    "[void]$texts.Item(1).AppendChild($xml.CreateTextNode("
    "$env:JARVIS_TOAST_MESSAGE))\n"
    "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)\n"
    "[Windows.UI.Notifications.ToastNotificationManager]"
    "::CreateToastNotifier($env:JARVIS_TOAST_APP_ID).Show($toast)\n"
)


def windows_beschikbaar():
    """True als we een Windows-systeem zijn waarop de toast kan werken."""
    return os.name == "nt" and shutil.which("powershell") is not None


def toon_toast(titel, tekst):
    """Toont een Windows-toast met ``titel`` en ``tekst``.

    Geeft True bij succes en False als de toast niet getoond kon worden
    (bijv. geen PowerShell of een Windows Runtime-fout). De aanroeper
    beslist dan of hij terugvalt op alleen spraak.
    """

    if not windows_beschikbaar():
        logger.debug("Geen Windows/PowerShell beschikbaar voor toast.")
        return False

    if not titel and not tekst:
        return False

    env = os.environ.copy()
    env["JARVIS_TOAST_TITLE"] = str(titel or "JARVIS")
    env["JARVIS_TOAST_MESSAGE"] = str(tekst or "")
    env["JARVIS_TOAST_APP_ID"] = TOAST_APP_ID

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _TOAST_SCRIPT],
            env=env,
            capture_output=True,
            timeout=TOAST_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        logger.warning("Windows-toast duurde te lang en is overgeslagen.")
        return False
    except OSError as error:
        logger.warning("Windows-toast kon niet worden gestart: %s", error)
        return False

    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.warning(
            "Windows-toast mislukt (code %s)%s",
            result.returncode,
            f": {stderr}" if stderr else "",
        )
        return False

    return True
