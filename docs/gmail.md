# Gmail koppelen (Fase 23, M2)

JARVIS mag uw Gmail **lezen**: vertellen of er nieuwe mail is, een mail
voorlezen, uw ongelezen mail samenvatten en u melden als er belangrijke mail
binnenkomt. Hij kan **niets versturen, verwijderen of als gelezen markeren**:
de koppeling heeft alleen het recht `gmail.readonly`. (Concepten en versturen
na uw "ja" komen in M3; dan koppelt u één keer opnieuw.)

## Eenmalig: de Google Cloud-app aanmaken (± 10 minuten)

Google laat een programma als JARVIS alleen bij uw mail via een eigen "app" in
Google Cloud. Die is gratis en alleen van u.

1. Ga op de laptop naar **https://console.cloud.google.com** en log in met het
   Google-account van uw Gmail. De eerste keer vraagt Google om de voorwaarden
   te accepteren; dat doet u zelf.
2. **Project maken:** klik bovenaan op de projectkiezer → **Nieuw project** →
   naam `JARVIS` → **Maken**. Zorg dat dit project daarna bovenaan geselecteerd is.
3. **Gmail API aanzetten:** zoek bovenaan op `Gmail API` → open hem → **Inschakelen**.
4. **Toestemmingsscherm** (*Google Auth Platform* / *OAuth-toestemmingsscherm*):
   - klik **Aan de slag**; app-naam `JARVIS`, uw eigen e-mailadres als
     ondersteunings- en contactadres;
   - doelgroep: **Extern**;
   - bij **Doelgroep / Testgebruikers**: voeg uw eigen Gmail-adres toe.
5. **Inloggegevens maken:** ga naar **Clients** (of *Inloggegevens* → *Inloggegevens
   maken* → *OAuth-client-ID*):
   - applicatietype: **Desktop-app**, naam `JARVIS laptop` → **Maken**;
   - kopieer de **Client-ID** (eindigt op `.apps.googleusercontent.com`) en het
     **Clientgeheim**.
6. Zet in de `.env` op de laptop:
   ```
   GMAIL_CLIENT_ID=<de client-id>
   GMAIL_CLIENT_SECRET=<het clientgeheim>
   ```
   Een terugkeeradres hoeft u bij een Desktop-app niet in te stellen: Google
   staat `http://127.0.0.1:<poort>` vanzelf toe (JARVIS gebruikt poort 8889).
7. **Belangrijk, anders moet u elke week opnieuw koppelen:** zet bij
   **Doelgroep** de publicatiestatus op **In productie** (*Publish app*).
   Zolang de app op *Testen* staat, laat Google het token na 7 dagen verlopen.
   U hoeft de app niet door Google te laten controleren: alleen u gebruikt hem.

## Koppelen

```
python scripts/gmail_koppelen.py
```

Uw browser opent de inlogpagina van Google. Omdat de app niet door Google is
gecontroleerd, ziet u **"Google heeft deze app niet geverifieerd"**: klik op
*Geavanceerd* → *Ga naar JARVIS (onveilig)*. Dat is hier in orde, het is uw
eigen app. Geef toestemming voor *E-mail bekijken*. Het script meldt daarna
hoeveel ongelezen mails er zijn. Herstart JARVIS, zodat het melden start.

## Vragen

* *"Heb ik nieuwe mail?"* → "U heeft 3 ongelezen mails, waarvan 1 belangrijk.
  Belangrijk: van School over "Rooster gewijzigd"."
* *"Lees de mail van school voor"* / *"Lees mijn laatste mail voor"* /
  *"Wat staat er in de mail van Jan?"* → afzender, tijd, onderwerp en de tekst
  (de eerste ±700 tekens; het geciteerde vorige bericht slaat hij over).
* *"Vat mijn mail samen"* → een korte samenvatting van de ongelezen mail.
* *"Welke koppelingen heb ik?"* en het Systeem-paneel tonen *Gmail ✓*.

## Melden van belangrijke mail

Elke 5 minuten kijkt JARVIS naar nieuwe ongelezen mail en meldt de
**belangrijke**: "Sir, nieuwe belangrijke mail van School: "Rooster gewijzigd"."

* Belangrijk = de afzender staat in `GMAIL_BELANGRIJKE_AFZENDERS` (deel van naam
  of adres, met komma's, bijv. `school,@hr.nl,mama`) **of** Gmail zelf gaf het
  label *Belangrijk* (zet `GMAIL_LABEL_BELANGRIJK=0` als u alleen uw eigen lijst wilt).
* 's Nachts en in de stille modus meldt hij niets; vraag er dan zelf naar.
* Na het starten meldt hij de mail die er al lag niet opnieuw.
* Helemaal niet melden: `GMAIL_MELDEN=0`. Vaker of minder vaak kijken:
  `GMAIL_CHECK_MINUTEN`.

## Veiligheid

* De tokens staan in `memory/koppelingen/gmail.json` (niet in git) en komen
  nooit in de log, het auditlog of een antwoord.
* De inhoud van een mail is **data, geen opdracht**. Staat er "stuur dit door
  aan…" of "zet de lampen uit" in een mail, dan doet JARVIS dat niet. Bij het
  samenvatten krijgt het AI-model de mails uitdrukkelijk als data.
* Ontkoppelen: verwijder `memory/koppelingen/gmail.json` en haal de toegang weg
  op https://myaccount.google.com/permissions.
