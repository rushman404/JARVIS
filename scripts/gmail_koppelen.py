"""Gmail eenmalig koppelen (Fase 23, M2).

Draai dit op de pc waar het brein van JARVIS draait (nu de laptop):

    python scripts/gmail_koppelen.py

Eerst een eigen Google Cloud-app maken en GMAIL_CLIENT_ID en
GMAIL_CLIENT_SECRET in .env zetten: zie docs/gmail.md.

Het script opent de inlogpagina van Google in uw browser. U logt daar zelf
in en geeft JARVIS het recht om uw mail te LEZEN (niet versturen, niet
verwijderen). Google stuurt de browser terug naar dit script op
http://127.0.0.1:8889/callback; het script ruilt de code om voor tokens en
bewaart die in memory/koppelingen/gmail.json (niet in git). Een token komt
nooit op het scherm of in de log.

Ontkoppelen: verwijder memory/koppelingen/gmail.json en haal de toegang weg
op https://myaccount.google.com/permissions.
"""

import os
import secrets
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core import gmail, koppelingen  # noqa: E402


def main():
    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET:
        print("GMAIL_CLIENT_ID of GMAIL_CLIENT_SECRET ontbreekt in .env. Zie docs/gmail.md, stap 1-6.")
        return 1
    koppeling = gmail.koppeling()
    verifier = koppelingen.maak_verifier()
    state = secrets.token_urlsafe(16)
    url = koppeling.autorisatie_url(verifier, state)

    def openen():
        print("De inlogpagina van Google gaat open in uw browser.")
        print("Gaat hij niet open? Kopieer dan deze link naar de browser:\n")
        print(url + "\n")
        webbrowser.open(url)

    try:
        code = koppelingen.ontvang_code(config.GMAIL_REDIRECT_URI, state, openen, naam="Gmail")
        koppeling.wissel_code(code, verifier)
        klant = gmail.GmailKlant(koppeling)
        aantal = klant.ongelezen_aantal()
    except koppelingen.KoppelFout as fout:
        print(f"Koppelen mislukt: {fout}")
        return 1
    if not koppeling.gegevens().get("refresh_token"):
        print("Let op: Google gaf geen vernieuwingstoken. Haal de toegang weg op "
              "https://myaccount.google.com/permissions en draai dit script opnieuw.")
        return 1
    print(f"Gekoppeld. JARVIS mag uw mail lezen; er staan {aantal} ongelezen mails in uw inbox.")
    print("Vraag nu: 'heb ik nieuwe mail?'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
