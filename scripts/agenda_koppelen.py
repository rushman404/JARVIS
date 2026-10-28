"""iCloud-agenda controleren (Fase 23, M4).

Draai dit op de pc waar het brein van JARVIS draait (nu de laptop), nadat
u ICLOUD_GEBRUIKER en ICLOUD_APP_WACHTWOORD in .env hebt gezet (zie
docs/agenda.md):

    python scripts/agenda_koppelen.py

Het script logt in bij iCloud, toont uw agenda's, zegt in welke agenda
JARVIS nieuwe afspraken zet en hoeveel afspraken er vandaag zijn. Het
wachtwoord komt nooit op het scherm of in de log.
"""

import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core import icloud_agenda, koppelingen  # noqa: E402


def main():
    if not config.ICLOUD_GEBRUIKER or not config.ICLOUD_APP_WACHTWOORD:
        print("ICLOUD_GEBRUIKER of ICLOUD_APP_WACHTWOORD ontbreekt in .env. Zie docs/agenda.md, stap 1-3.")
        return 1
    klant = icloud_agenda.AgendaKlant()
    try:
        agendas = klant.agendas(vers=True)
        schrijf = klant.schrijf_agenda()
        van = datetime.combine(date.today(), datetime.min.time())
        vandaag = klant.afspraken(van, van + timedelta(days=1))
    except koppelingen.KoppelFout as fout:
        print(f"Verbinden mislukt: {fout}")
        if fout.status == 401:
            print("Controleer ICLOUD_GEBRUIKER (uw Apple ID-e-mailadres) en maak zo nodig een nieuw "
                  "app-specifiek wachtwoord op https://account.apple.com.")
        return 1
    print("Verbonden met iCloud. Uw agenda's:")
    for a in agendas:
        print(f"  - {a['naam'] or '(zonder naam)'}{'   <- hier zet JARVIS nieuwe afspraken' if a is schrijf else ''}")
    if config.ICLOUD_AGENDA and schrijf["naam"].lower() != config.ICLOUD_AGENDA.lower():
        print(f"Let op: de agenda '{config.ICLOUD_AGENDA}' (ICLOUD_AGENDA) bestaat niet; "
              f"JARVIS gebruikt '{schrijf['naam']}'.")
    print(f"Vandaag: {len(vandaag)} {'afspraak' if len(vandaag) == 1 else 'afspraken'}.")
    print("Vraag nu: 'wat staat er vandaag op de planning?'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
