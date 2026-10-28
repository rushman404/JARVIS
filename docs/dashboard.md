# 📱 JARVIS-dashboard (Fase 18) — handleiding

Het dashboard is een web-app (PWA) voor de iPad: één scherm met de status
van JARVIS, timers, weer, nachtmodus, het gesprek, het auditlog, de
pc-meters, media en het slim huis. Gevaarlijke acties keurt u goed in een
oranje venster. Het werkt **alleen thuis** en **alleen via HTTPS**.

Ontwerp en beveiliging: [fase18_dashboard_design.md](fase18_dashboard_design.md).

---

## 1. Eenmalig instellen (op het brein / de laptop)

1. **Certificaat maken** (eigen CA + servercertificaat + iPad-profiel):

   ```bash
   python scripts/make_dashboard_cert.py
   ```

   Het script zoekt zelf het LAN-adres. Klopt dat niet, geef het mee met
   `--ip 192.168.x.x`. Verandert het IP-adres later, draai het opnieuw met
   `--force`: de CA blijft dezelfde, dus de iPad hoeft niets opnieuw te doen.

2. **Twee tokens maken** (kijken en bedienen, verschillend, ≥ 16 tekens):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. **`.env` invullen:**

   ```ini
   DASHBOARD_ENABLED=1
   DASHBOARD_VIEW_TOKEN=<token 1>
   DASHBOARD_CONTROL_TOKEN=<token 2>
   DASHBOARD_CERT_FILE=certs/dashboard-cert.pem
   DASHBOARD_KEY_FILE=certs/dashboard-key.pem
   JARVIS_WEER_PLAATS=Badhoevedorp
   ```

   Optioneel: `DASHBOARD_ALLOWED_IPS=<ip van de iPad>` voor een extra laag.

4. **Windows Firewall:** sta inkomend TCP-verkeer op poort **8780** toe,
   het liefst alleen vanaf het IP-adres van de iPad.

5. **JARVIS starten.** In de console verschijnt:

   ```text
   JARVIS-dashboard: open https://<laptop-ip>:8780 op de iPad.
      Koppelcode: 12345678  (5 minuten geldig, een keer bruikbaar)
      Nieuwe code (op deze pc): https://<laptop-ip>:8780/koppel.html
      iPad-profiel: https://<laptop-ip>:8780/profiel.mobileconfig
   ```

   De koppelcode komt **alleen in de console**, nooit in de log.

## 2. De iPad koppelen

1. Open in Safari `https://<laptop-ip>:8780/profiel.mobileconfig` en
   installeer het profiel (*Instellingen → Profiel gedownload*).
2. *Instellingen → Algemeen → Info → Instellingen voor certificaatvertrouwen*
   → zet **JARVIS Dashboard CA** op **Volledig vertrouwen**.
3. Open `https://<laptop-ip>:8780`, tik de koppelcode in en kies
   **Bedienen** of **Alleen kijken**.
4. *Delen → Zet op beginscherm* — dan opent het als app op volledig scherm.

Code verlopen? Open op de laptop `https://localhost:8780/koppel.html`
(werkt alleen op de pc zelf) voor een nieuwe.

## 3. Gebruik

| Onderdeel | Wat het doet |
|---|---|
| Spraakstatus-orb | in rust / luistert / denkt na / spreekt / slaapt, live; tijdens het werk staat eronder wat JARVIS nu doet (bijv. "Spotify op 30% zetten") |
| Timers | aftellen; tik om te annuleren |
| Weer | eerst `weather.*` uit Home Assistant, anders Open-Meteo |
| Nachtmodus | Auto / Aan / Uit |
| Gesprek | live meelezen én **typen** (Fase 20): typ een opdracht en tik op ➜. De luidsprekerknop kiest **stil** (alleen tekst) of **hardop**; de keuze wordt op de server onthouden (bij de dashboard-instellingen). Eén opdracht tegelijk; alleen met de bedien-rol |
| Routines | gaming / film / slapen met één tik (Fase 20); het verloop staat in het gesprek, een stap die goedkeuring nodig heeft vraagt die gewoon |
| Vandaag | afspraken van vandaag (met vertrektijd), ongelezen belangrijke mail (afzender + onderwerp) en nieuwe Discord-DM's; ververst elke 2 minuten en markeert niets als gelezen (Fase 23, M7) |
| Auditlog | de laatste acties met risico en resultaat; sinds Fase 23 standaard uit (Vandaag staat op zijn plek), aan te zetten via ⚙ |
| Systeem | meters van deze pc en de game-pc; **Slaapstand…** (altijd met goedkeuring) |
| Media | Spotify-volumeschuif; vorige, play/pauze, volgende (volgt PC_TARGET) |
| Slim huis | status; lampen en scènes zijn tikbaar (een lamp die kan dimmen of kleuren opent een venster met helderheid, warm/neutraal/koel wit en kleuren, Fase 20); schakelaars en knoppen (bijv. Wake-on-LAN uit Home Assistant) vragen eerst goedkeuring; **+ Aanpassen** kiest welke apparaten er staan |
| Meldingen | badge rechtsboven; tik voor de lijst. Een **nieuwe** melding schuift bovenin als banner in beeld (8 s; tik = lijst) met een zacht geluidje — 's nachts stil, uit te zetten in ⚙. Het geluid werkt pas na de eerste tik op het scherm (regel van iOS). Echte pushmeldingen (met de app dicht) kunnen op iOS 12 niet |
| ☰ Overzicht | logboek, geheugen en routines (alleen lezen) |
| ⚙ Instellingen | panelen aan/uit en volgorde, meldingenbadge, token vernieuwen, ontkoppelen; onderaan de **versie** van JARVIS (commit + datum, en een melding als er een nieuwere versie gedownload is maar JARVIS nog niet herstart) |

**Goedkeuring:** wacht JARVIS op een ja/nee (stem of dashboard), dan
verschijnt een oranje venster met de vraag, de actie, het doel en het
risico, en een aftelbalk. *Ja* voert hem uit, *Annuleer* niet. Dezelfde
actie kan nooit twee keer worden uitgevoerd (stem én dashboard).

## 3b. Spraakproef: de iPad als microfoon (Fase 20, M3)

Een proef vóór de iPad echt de microfoon van JARVIS wordt. Op iOS 12 werkt de
microfoon **alleen in Safari**, niet in de app op het beginscherm.

1. Open in **Safari** `https://<laptop-ip>:8780/spraak-proef.html`. Bent u in
   Safari nog niet gekoppeld, open dan eerst het dashboard in Safari en koppel
   met de **bedien**-rol (de beginscherm-app heeft eigen cookies).
2. Onder *Ondersteuning* moeten vier vinkjes staan.
3. Tik *Start opname*, sta de microfoon toe en zeg rustig **"Hey JARVIS, hoe
   laat is het?"**. Na 6 seconden ziet u de uitslag:
   - hoeveel er aankwam en of er stukjes ontbraken;
   - het geluidsniveau en of het oversteurt;
   - de **"Hey JARVIS"-score** (vanaf 0,5 herkent JARVIS hem);
   - wat de spraakherkenning verstond.
4. Tik *Speel testzin*: u hoort JARVIS (rdh-butler) uit de iPad.

Doe de opname een paar keer: dichtbij, op 1-2 meter (zoals in de kamer) en
met muziek aan. Stuur de uitslagen door; daarop beslissen we over M4/M5.
De opname wordt nergens opgeslagen.

## 3c. Spraakpaneel: de iPad als microfoon en speaker (Fase 20, M4 + M5)

Zolang het spraakpaneel open is, is de iPad de microfoon van JARVIS: het
wake word en het luisteren gebeuren gewoon op het brein.

1. Zet op de iPad *Instellingen → Beeldscherm en helderheid → Automatische
   vergrendeling* op **Nooit** en leg de iPad aan de lader (iOS 12 stopt de
   microfoon als het scherm uitgaat).
2. Open in **Safari** `https://<laptop-ip>:8780/spraak.html` (gekoppeld met de
   bedien-rol, net als bij de spraakproef) en tik **Start luisteren**.
3. Zeg **"Hey JARVIS"**. Het paneel toont wat JARVIS doet; **de piep en het
   antwoord klinken uit de iPad** (M5), net als timers en andere meldingen.
   Vinkje *Antwoord van JARVIS op de iPad laten horen* uit = het antwoord komt
   weer uit de speaker van het brein. Is het paneel dicht, dan altijd daar.

Onder de status toont het paneel waar JARVIS nu luistert en spreekt
("Microfoon: iPad ✓ · Speaker: iPad ✓"); `logs/jarvis.log` noemt per antwoord
"Antwoord via de iPad" of "… via de speaker van het brein".

Terwijl JARVIS uit de iPad praat, stuurt het paneel geen microfoongeluid en
is de microfoon op het brein gedempt: JARVIS hoort zichzelf niet.

| `MIC_BRON` (`.env`) | Wat luistert |
|---|---|
| `auto` (standaard) | de pc-microfoon, behalve zolang het spraakpaneel geluid stuurt |
| `ipad` | alleen de iPad (de pc-microfoon wordt niet geopend) |
| `pc` | alleen de pc-microfoon; de iPad mag niet verbinden |

Het geluid gaat over één beveiligde verbinding (WebSocket, alleen vanaf het
eigen dashboard; het paneel haalt eerst een eenmalig kaartje van 30 s op met
de bedien-rol en stuurt dat als eerste bericht, omdat Safari de cookie niet
altijd meestuurt met een WebSocket) en komt alleen in de
ringbuffer van ±3 s, net als bij de pc-microfoon. Er wordt niets opgeslagen.
Onderbreken met de stem (barge-in) werkt via de iPad nog niet; de sneltoets wel.

## 4. Problemen oplossen

| Probleem | Oplossing |
|---|---|
| "Safari kan de pagina niet openen" | Draait JARVIS? Klopt het IP? Staat poort 8780 open in de firewall? Na 5 foute inlogpogingen is het IP 5 minuten geblokkeerd (de console meldt dat). |
| Certificaatwaarschuwing blijft | Stap 2.2 (Volledig vertrouwen) is nog niet gedaan, of het certificaat is voor een ander IP gemaakt (`--force --ip ...`). |
| Oude versie na een update | Vanaf versie 18.2 ververst de app zichzelf: hij vergelijkt zijn versie met de server en ruimt bij een verschil zijn cache op. Bij een app van vóór 18.2: zie hieronder (eenmalig). |
| Beginscherm-app blijft op een oude versie (iOS 12, eenmalig) | 1) Verwijder het icoon. 2) *Instellingen → Safari → Geavanceerd → Websitegegevens* → zoek het IP-adres van de laptop → veeg naar links → *Verwijder*. 3) Sluit Safari helemaal af (dubbelklik op de thuisknop, veeg Safari omhoog). 4) Open het dashboard opnieuw in Safari, kies *Zet op beginscherm* en koppel de app één keer. |
| Geen icoon op het beginscherm | Verwijder het icoon, zorg dat stap 2.2 (*Volledig vertrouwen*) gedaan is, open de pagina opnieuw in Safari en kies dan pas *Zet op beginscherm*. iOS haalt het icoon buiten Safari om op en lukt dat alleen met een vertrouwd certificaat. |
| Safari werkt, de app op het beginscherm toont "Geen verbinding met JARVIS" | Het certificaat wordt niet echt vertrouwd. Safari onthoudt een eerdere "Bezoek deze website", de app niet. Controleer *Instellingen → Algemeen → Info → Instellingen voor certificaatvertrouwen*: **JARVIS Dashboard CA** moet aan staan. Staat hij er niet, installeer dan eerst het profiel (stap 2.1). Toets: open het dashboard in een nieuw Safari-tabblad; krijgt u een waarschuwing, dan is het nog niet vertrouwd. Meldt de console van JARVIS "LET OP: het certificaat geldt niet voor …", maak dan een nieuw certificaat met het commando dat erbij staat. |
| Log: "TLS-handshake mislukt … van <ip-van-de-iPad>" | De iPad keurt het certificaat af. Maak een nieuw servercertificaat (de CA en het profiel op de iPad blijven gelijk): `python scripts/make_dashboard_cert.py --force` en herstart JARVIS. Blijft het, stuur dan de **Reden:** uit die logregel mee (bijv. `TLSV1_ALERT_UNKNOWN_CA` = CA niet vertrouwd, `SSLV3_ALERT_BAD_CERTIFICATE` = certificaat afgekeurd). |
| Beginscherm-app vraagt opnieuw om de koppelcode | Normaal op iOS 12: de app op het beginscherm heeft eigen cookies, los van Safari. Koppel hem één keer. |
| iPad Air 1 / iOS 12 | Ondersteund: het scherm vult de 4:3-iPad en oudere Safari krijgt dezelfde tussenruimtes via marges. |
| "LET OP: iPad-profiel niet gevonden" | Draai `scripts/make_dashboard_cert.py`; het profiel komt naast het certificaat. |
| Update weigert: "lokale wijzigingen (config/dashboard.json)" | Sinds Fase 20 bewaart het dashboard uw indeling in `config/dashboard.local.json` (buiten git). Na de eerste start met de nieuwe versie is uw indeling daarheen gekopieerd; zet het oude bestand dan één keer terug met `git checkout -- config/dashboard.json`. |
| Spraakpaneel: "Verbinding weg; opnieuw proberen…" | Het paneel toont de foutcode. *Code 1008*: kaartje geweigerd (opnieuw koppelen in Safari met de bedien-rol). *Code 1006*: de verbinding kwam niet tot stand; kijk in `logs/jarvis.log` naar regels met "Spraakstroom". |
| Game-PC-meters: "agent staat niet aan" | `REMOTE_CLIENT_ENABLED=1` en de game-pc-agent moet draaien. |

## 5. iPad-testlijst (M7)

Doorlopen en goedgekeurd op 2026-10-25 (iPad Air 1, iOS 12.5.8). Loop hem opnieuw door na grote wijzigingen.

**Verbinding en koppelen**
- [x] Na het profiel en *Volledig vertrouwen*: geen certificaatwaarschuwing meer
- [x] Koppelen met de code lukt; een foute code geeft een nette melding
- [x] Na een herstart van JARVIS blijft de iPad gekoppeld
- [x] *Zet op beginscherm* opent op volledig scherm met het JARVIS-icoon
- [x] Met JARVIS uit: de app opent nog (offline-cache) en meldt "Verbinding verbroken"
- [x] Vaak herladen: de pagina blijft bereikbaar (geen blokkade)

**Live**
- [x] De orb volgt "Hey JARVIS" (luistert → denkt na → spreekt → in rust)
- [x] De tekst "JARVIS / AI ASSISTANT" staat midden in de orb
- [x] Het gesprek verschijnt live; het auditlog vult zich na een actie
- [x] Een timer via de stem verschijnt meteen en telt af
- [x] Een proactieve melding geeft een badge

**Bedienen (bedien-rol)**
- [x] Een lamp aan/uit en *Avondmodus* werken
- [x] Vorige / play-pauze / volgende werken op de juiste pc
- [x] Nachtmodus Auto/Aan/Uit
- [x] Timer annuleren
- [x] *Slaapstand…* → oranje venster → *Annuleer* doet niets; *Ja* zet de pc in slaapstand
- [x] Een goedkeuring via de stem ("ja") sluit het venster op de iPad

**Instellingen en overzicht**
- [x] Een paneel verbergen en de volgorde wijzigen; blijft na herladen
- [x] Meldingenbadge uit
- [x] Overzicht: logboek, geheugen en routines laden
- [x] Token vernieuwen; daarna werkt alles nog
- [x] Ontkoppelen → koppelscherm; opnieuw koppelen lukt

**Alleen kijken (optioneel, tweede apparaat)**
- [x] Alles zichtbaar, maar bedienen en goedkeuren kan niet

**Typen (Fase 20, M1)**
- [ ] Tik in het invoerveld: het toetsenbord blijft open en het veld verspringt niet
- [ ] "hoe laat is het" + ➜ → het antwoord verschijnt in het gesprek, stil
- [ ] Luidsprekerknop aan → volgende opdracht wordt ook hardop gezegd; na herladen (en in de andere app/Safari) staat hij nog aan
- [ ] "zet spotify op 30 procent" → onder de orb staat even "Spotify op 30% zetten"
- [ ] "zet de pc in slaapstand" → het oranje venster verschijnt; *Annuleer* doet niets
- [ ] Met het kijk-token: het veld is grijs ("Alleen kijken")

**Routines en lampen (Fase 20, M2)**
- [ ] Het paneel *Routines* staat onder het gesprek (ook in een eerder opgeslagen indeling)
- [ ] *Gaming* → in het gesprek "Routine 'gaming' starten" en daarna het resultaat
- [ ] Tik op een dimbare lamp → venster met helderheid; schuif loslaten past de lamp aan
- [ ] *Warm* / *Koel* en een kleur werken (alleen zichtbaar als de lamp dat kan)
- [ ] *Uitzetten* / *Aanzetten* in het venster werkt; een gewone schakelaar wisselt nog direct

**Vandaag (Fase 23, M7)**
- [ ] Het paneel *Vandaag* staat in het midden onder *Routines* (ook in een eerder opgeslagen indeling); de auditlog is weg en via ⚙ weer aan te zetten
- [ ] Afspraken van vandaag met tijd en plaats; voorbije in grijs, "Vertrek 13:35 · 25 min rijden" in oranje
- [ ] Belangrijke ongelezen mail en nieuwe DM's met afzender; daarna "heb ik nieuwe DM's?" geeft ze nog steeds
- [ ] Game-pc uit → "Game-pc staat uit" bij Discord; agenda/mail niet gekoppeld → "Niet gekoppeld"

**Spraakpaneel (Fase 20, M4)**
- [ ] `spraak.html` in Safari → *Start luisteren* → "● Luistert via de iPad"
- [ ] "Hey JARVIS" op 1-2 m → de piep (van het brein) en JARVIS luistert
- [ ] "Hey JARVIS, hoe laat is het?" → juist antwoord
- [ ] Wifi even uit en aan → het paneel verbindt vanzelf opnieuw
- [ ] *Stop luisteren* → de pc-microfoon neemt het weer over (`MIC_BRON=auto`)

**Antwoord op de iPad (Fase 20, M5)**
- [ ] "Hey JARVIS" → de piep komt uit de iPad
- [ ] "hoe laat is het?" → het antwoord (rdh-butler) komt uit de iPad, niet uit de laptop
- [ ] Een lang antwoord ("vertel iets over Mars") speelt zonder haperingen tussen de zinnen
- [ ] Een timer van 1 minuut → de melding klinkt uit de iPad
- [ ] Vinkje *Antwoord … op de iPad* uit → het antwoord komt weer uit de laptop
- [ ] Spraakpaneel dicht → het antwoord komt uit de laptop

**Meldingen (Fase 20, M6)**
- [ ] Tik één keer ergens in de app → bovenin "Geluid voor meldingen staat aan." met een geluidje
- [ ] ⚙ → *Testmelding sturen* → banner "Dit is een testmelding van JARVIS." met geluid
- [ ] Zet een timer van 1 minuut → bovenin de banner "…timer…" met een geluidje
- [ ] Tik op de banner → de meldingenlijst opent
- [ ] ⚙ → *Geluid bij een nieuwe melding* uit → volgende melding: wel banner, geen geluid
- [ ] Nachtmodus *Aan* → banner zonder geluid
