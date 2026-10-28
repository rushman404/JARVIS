# iCloud-agenda (Fase 23, M4)

JARVIS leest uw **iCloud-agenda** (de Agenda-app op uw iPhone, iPad en Mac)
en kan na uw **"ja"** afspraken toevoegen of verplaatsen. Verwijderen kan hij
niet.

Apple laat een programma als JARVIS alleen bij uw agenda met een
**app-specifiek wachtwoord**: een apart wachtwoord dat alleen voor JARVIS
geldt. Uw gewone Apple-wachtwoord gebruikt u hier **nooit**.

## Eenmalig instellen (± 5 minuten)

1. Ga naar **https://account.apple.com** en log in met uw Apple ID.
   Twee-factor-authenticatie moet aan staan (dat is meestal al zo).
2. Ga naar **Inloggen en beveiliging → App-specifieke wachtwoorden**.
   Klik op **+** (of *Genereer een app-specifiek wachtwoord*), noem het
   `JARVIS` en klik **Maak aan**. U ziet een wachtwoord als
   `abcd-efgh-ijkl-mnop`. Kopieer het; Apple toont het maar één keer.
3. Zet in de `.env` op de laptop (zelf, niet in de chat plakken):
   ```
   ICLOUD_GEBRUIKER=<uw Apple ID-e-mailadres>
   ICLOUD_APP_WACHTWOORD=abcd-efgh-ijkl-mnop
   ```
   Optioneel, de agenda waarin JARVIS nieuwe afspraken zet (anders de eerste):
   ```
   ICLOUD_AGENDA=Thuis
   ```
4. Controleer het:
   ```
   python scripts/agenda_koppelen.py
   ```
   U ziet uw agenda's, in welke JARVIS nieuwe afspraken zet en hoeveel
   afspraken er vandaag zijn. Herstart daarna JARVIS.

## Vragen

* *"Wat staat er vandaag op de planning?"*, *"Wat heb ik morgen?"*,
  *"Wat staat er vrijdag in mijn agenda?"*, *"Mijn agenda"*:
  ```
  Vandaag heeft u 2 afspraken:
  Hele dag: Verjaardag oma.
  14:00 tot 15:00: Tandarts, in Breda.
  ```
* *"Wat heb ik deze week?"* → de komende zeven dagen, per dag.
* *"Wanneer is mijn volgende afspraak?"*
* *"Wanneer is de tandarts?"* / *"Wanneer moet ik naar voetbal?"* → de
  eerstvolgende afspraak met dat woord in de titel (de komende 90 dagen).

## Toevoegen en verplaatsen (na ja)

* *"Zet tandarts morgen om 14 uur in mijn agenda"*, *"Plan een afspraak voor
  de kapper vrijdag om half drie"*, *"Voeg verjaardag oma toe aan mijn agenda
  op 5 december"* (zonder tijd = de hele dag), *"Zet overleg morgen van 2 tot 4
  in mijn agenda"*. Zonder eindtijd duurt een afspraak een uur.
* *"Verplaats de tandarts naar vrijdag om 10 uur"*: de duur blijft gelijk.
  Alleen een dag (*"naar zaterdag"*) houdt dezelfde tijd.
* JARVIS leest het voorstel voor en vraagt het: *"Afspraak toevoegen:
  Tandarts, morgen (donderdag 29 oktober) van 14:00 tot 15:00. Zal ik hem in
  uw agenda zetten?"*. Alleen een duidelijk **"ja"** telt (stem of de oranje
  knop op het dashboard); "ok" of "prima" niet.
* Tijden: "om 14:00", "om 14 uur", "half drie", "kwart over negen",
  "'s avonds"; een losse "3 uur" is voor een afspraak 's middags (15:00).
  Datums: vandaag, morgen, overmorgen, een weekdag ("vrijdag", "volgende
  week dinsdag"), "3 november" of "3-11".
* Terugkerende afspraken en afspraken voor de hele dag verplaatst u in de
  Agenda-app zelf.

## Veiligheid

* Het app-specifieke wachtwoord staat alleen in `.env` (niet in git) en komt
  nooit in de log, het auditlog of een antwoord. In `memory/koppelingen/
  icloud_agenda.json` staan alleen de adressen van uw agenda's.
* Weigert iCloud het wachtwoord, dan ziet u in het Systeem-paneel
  *iCloud-agenda !*: maak een nieuw app-specifiek wachtwoord.
* Toevoegen en verplaatsen gaan altijd via een expliciete ja en komen in het
  auditlog. Is de afspraak intussen ergens anders gewijzigd, dan
  overschrijft JARVIS hem niet.
* Intrekken: verwijder het app-specifieke wachtwoord op account.apple.com.
