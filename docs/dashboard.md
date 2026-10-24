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
| Spraakstatus-orb | in rust / luistert / denkt na / spreekt, live |
| Timers | aftellen; tik om te annuleren |
| Weer | eerst `weather.*` uit Home Assistant, anders Open-Meteo |
| Nachtmodus | Auto / Aan / Uit |
| Gesprek | live meelezen (typen komt in Fase 20) |
| Auditlog | de laatste acties met risico en resultaat |
| Systeem | meters van deze pc en de game-pc; **Slaapstand…** (altijd met goedkeuring) |
| Media | Spotify/Discord-volume; vorige, play/pauze, volgende (volgt PC_TARGET) |
| Slim huis | status; lampen en scènes zijn tikbaar; schakelaars en knoppen (bijv. Wake-on-LAN uit Home Assistant) vragen eerst goedkeuring; **+ Aanpassen** kiest welke apparaten er staan |
| Meldingen | badge rechtsboven; tik voor de lijst |
| ☰ Overzicht | logboek, geheugen en routines (alleen lezen) |
| ⚙ Instellingen | panelen aan/uit en volgorde, meldingenbadge, token vernieuwen, ontkoppelen |

**Goedkeuring:** wacht JARVIS op een ja/nee (stem of dashboard), dan
verschijnt een oranje venster met de vraag, de actie, het doel en het
risico, en een aftelbalk. *Ja* voert hem uit, *Annuleer* niet. Dezelfde
actie kan nooit twee keer worden uitgevoerd (stem én dashboard).

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
| Game-PC-meters: "agent staat niet aan" | `REMOTE_CLIENT_ENABLED=1` en de game-pc-agent moet draaien. |

## 5. iPad-testlijst (M7)

Loop deze lijst één keer door op de echte iPad en vink af.

**Verbinding en koppelen**
- [ ] Na het profiel en *Volledig vertrouwen*: geen certificaatwaarschuwing meer
- [ ] Koppelen met de code lukt; een foute code geeft een nette melding
- [ ] Na een herstart van JARVIS blijft de iPad gekoppeld
- [ ] *Zet op beginscherm* opent op volledig scherm met het JARVIS-icoon
- [ ] Met JARVIS uit: de app opent nog (offline-cache) en meldt "Verbinding verbroken"
- [ ] Vaak herladen: de pagina blijft bereikbaar (geen blokkade)

**Live**
- [ ] De orb volgt "Hey JARVIS" (luistert → denkt na → spreekt → in rust)
- [ ] De tekst "JARVIS / AI ASSISTANT" staat midden in de orb
- [ ] Het gesprek verschijnt live; het auditlog vult zich na een actie
- [ ] Een timer via de stem verschijnt meteen en telt af
- [ ] Een proactieve melding geeft een badge

**Bedienen (bedien-rol)**
- [ ] Een lamp aan/uit en *Avondmodus* werken
- [ ] Vorige / play-pauze / volgende werken op de juiste pc
- [ ] Nachtmodus Auto/Aan/Uit
- [ ] Timer annuleren
- [ ] *Slaapstand…* → oranje venster → *Annuleer* doet niets; *Ja* zet de pc in slaapstand
- [ ] Een goedkeuring via de stem ("ja") sluit het venster op de iPad

**Instellingen en overzicht**
- [ ] Een paneel verbergen en de volgorde wijzigen; blijft na herladen
- [ ] Meldingenbadge uit
- [ ] Overzicht: logboek, geheugen en routines laden
- [ ] Token vernieuwen; daarna werkt alles nog
- [ ] Ontkoppelen → koppelscherm; opnieuw koppelen lukt

**Alleen kijken (optioneel, tweede apparaat)**
- [ ] Alles zichtbaar, maar bedienen en goedkeuren kan niet
