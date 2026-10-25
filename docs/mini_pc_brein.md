# 🖥️ Het brein op de mini-pc (Fase 19) — handleiding

In Fase 19 verhuist het brein (JARVIS, de AI, het geheugen en het dashboard)
van de laptop naar een eigen Windows-mini-pc die 24/7 aan staat. De game-pc
blijft de agent die op afstand wordt bediend.

Deze handleiding groeit per mijlpaal mee. Klaar: **M1 — installatie en
migratie**, **M2 — auto-start en waakhond**, **M3 — backups**, **M4 —
slaapstand**, **M5 — stem kiezen** en **M6 — updates en verbindingen**. De handmatige basis staat in
[windows_brein_setup.md](windows_brein_setup.md).

---

## 1. Controle: `brein_check.py`

```powershell
python scripts\brein_check.py
```

Eén overzicht, één regel per onderdeel:

| Onderdeel | Wat er gecontroleerd wordt |
|---|---|
| Python | versie 3.11 of nieuwer |
| Pakketten | ollama, piper, openwakeword, sounddevice … |
| .env | aanwezig |
| Ollama | bereikbaar en `AI_MODEL` gedownload |
| Wake word | model `hey_jarvis` te laden |
| Piper-stem | een `.onnx`-stem gevonden |
| Microfoon / Speaker | apparaat aanwezig; `MIC_DEVICE` klopt |
| Game-pc-agent | configuratie compleet en online (bij `PC_TARGET=game-pc`) |
| Home Assistant | bereikbaar (als ingesteld) |
| Dashboard | beveiliging in orde en certificaat geldig voor het huidige IP |
| Schijfruimte | minstens 5 GB vrij |

✅ in orde · ⚠️ aandachtspunt · ❌ moet opgelost worden (met het commando
erbij) · ➖ niet van toepassing. Exitcode 0 als er geen ❌ is. Het script
verandert nooit iets en toont nooit tokens.

## 2. Verhuizen: van de laptop naar de mini-pc

### Op de laptop (oude brein)

1. Stop JARVIS.
2. Maak het pakket, het liefst direct op een usb-stick:

   ```powershell
   python scripts\brein_export.py --naar E:\
   ```

Wat er in het pakket zit:

| Soort | Bestanden |
|---|---|
| Gegevens | `memory/memory.json`, `memory/conversation.json`, `config/*.json` (timers, routines, scènes, regels, dashboard-indeling, **gekoppelde iPads**), `taal.json`, `logs/audit*.jsonl`, de Obsidian-vault `JARVIS Memory/` |
| Geheimen | `.env` en `certs/` (o.a. de **dashboard-CA**) |

Niet in het pakket: de code (die komt van GitHub), de stemmodellen (die haalt
de installatie opnieuw op) en `certs/agent-key.pem` (de privésleutel van de
agent blijft altijd op de game-pc).

> ⚠️ Het pakket bevat uw tokens en sleutels. Gebruik een usb-stick; niet
> mailen en niet in de cloud zetten. Verwijder het na de import.

### Op de mini-pc (nieuwe brein)

1. Installeer **Python 3.11+** (python.org, vink *Add to PATH* aan) en **Git**.
2. Haal de code op:

   ```powershell
   git clone <uw-repo-url> C:\JARVIS
   cd C:\JARVIS
   ```

3. Installeer alles en zet het pakket terug in één keer:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_brein.ps1 -InstallOllama -ImportPakket E:\jarvis-brein-LAPTOP-....zip
   ```

   Het script maakt `.venv`, installeert de pakketten, zet het pakket terug,
   haalt Ollama + het AI-model, het wake word en een Piper-stem op en draait
   tot slot `brein_check.py`. Herhaalbaar: wat al klaar is, slaat het over.
   Proberen zonder iets te wijzigen: voeg `-DryRun` toe.

4. **Nieuw IP-adres?** Maak alleen een nieuw servercertificaat. De CA komt
   mee uit het pakket, dus **de iPad hoeft niets opnieuw te doen**:

   ```powershell
   .\.venv\Scripts\python.exe scripts\make_dashboard_cert.py --force
   ```

5. Kijk de instellingen na die de import noemt (bijv. `DASHBOARD_LAN_IP`,
   `MIC_DEVICE`): die kunnen op de mini-pc anders zijn.
6. Firewall voor het dashboard (PowerShell als administrator):

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_brein.ps1 -AddFirewallRule -AllowedRemoteAddress <ip-van-de-ipad>
   ```

7. **Game-pc:** de agent accepteert alleen het brein. Staat
   `REMOTE_SERVER_ALLOWED_IPS` op de game-pc ingevuld, zet daar het IP van de
   mini-pc in, en pas de firewallregel van de agent aan
   (`install_game_pc_agent.ps1 -AddFirewallRule -AllowedRemoteAddress <ip-mini-pc>`).
8. Start JARVIS: `.\.venv\Scripts\python.exe main.py`, en test de LAN-verbinding
   met de game-pc: `python scripts\test_remote_lan_manual.py`.

### Importeren met de hand

```powershell
python scripts\brein_import.py <pakket> --alleen-controle   # alleen kijken
python scripts\brein_import.py <pakket>                     # terugzetten (vraagt 'ja')
```

Veiligheid bij het importeren:

- alleen bestanden die bij het brein horen, nooit paden buiten de projectmap;
- elk bestand moet het controlegetal (SHA-256) uit het manifest hebben,
  anders wordt er **niets** geschreven;
- wat overschreven wordt, gaat eerst in `voor-import-<tijd>.zip` in
  `%USERPROFILE%\JARVIS-export`;
- niet terwijl JARVIS draait.

## 3. Altijd aan: auto-start en waakhond (M2)

### De waakhond

De geplande taak start niet JARVIS zelf, maar de **waakhond**
(`python -m beheer.waakhond`). Die start `main.py` en let op:

| Wat er gebeurt | Wat de waakhond doet |
|---|---|
| JARVIS crasht (exitcode ≠ 0) | herstart na 5 s, dan 15 s, 30 s, 1, 2 en 5 min; na 10 minuten stabiel begint het weer bij 5 s |
| JARVIS hangt: geen hartslag meer (90 s) of 5 min geen microfoonaudio in rust | stopt hem en herstart |
| Lang nadenken (een zware AI-vraag) | mag tot 15 minuten |
| 5 herstarts binnen 15 minuten | geeft het op, met een Windows-melding (dan is er iets structureel mis) |
| U stopt JARVIS (Ctrl+C, exitcode 0) | stopt ook |
| Het wake-word-model ontbreekt (exitcode 4) | stopt ook, met een melding (herstarten helpt niet) |

Na een herstart zegt JARVIS *"JARVIS is weer online."* en komt er een melding
op het dashboard met het tijdstip en de reden. In het **Systeem**-paneel
(*Deze pc*) ziet u hoe lang JARVIS al draait, of hij bewaakt wordt en hoe
vaak hij herstart is.

Bestanden (in `logs/`, niet in git): `hartslag.json` (de hartslag van
JARVIS, elke 15 s), `waakhond.json` (de status) en `waakhond.log`. Er kan
maar één waakhond tegelijk draaien, en JARVIS stopt mee als de waakhond
stopt.

### Auto-start instellen

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_brein_autostart.ps1 -StartNu
```

Dat maakt de taak **"JARVIS Brein"** (start bij inloggen, in uw eigen sessie
zodat de microfoon en speaker werken). Daarna:

```powershell
Start-ScheduledTask -TaskName 'JARVIS Brein'   # starten
Stop-ScheduledTask  -TaskName 'JARVIS Brein'   # stoppen (JARVIS stopt mee)
Get-Content logs\waakhond.json                 # status
```

Verwijderen: `scripts\uninstall_brein_autostart.ps1`.

### Automatisch inloggen (zelf instellen)

Zonder auto-login start JARVIS pas als u inlogt, dus na een stroomstoring of
Windows-update niet. De veiligste manier is **Autologon** van Microsoft
Sysinternals: die bewaart het wachtwoord versleuteld (niet als leesbare tekst
in het register).

1. Download *Autologon* van learn.microsoft.com (Sysinternals) en start het.
2. Vul gebruikersnaam, domein (de pc-naam) en wachtwoord in → **Enable**.
3. Herstart de mini-pc: hij logt zelf in en de taak start JARVIS.

Gebruikt u een Microsoft-account met Windows Hello (pincode)? Zet dan eerst
*Instellingen → Accounts → Aanmeldingsopties → "Alleen aanmelden met Windows
Hello toestaan"* uit, anders werkt automatisch inloggen niet.

> Auto-login betekent: wie de mini-pc aanzet, zit in uw account. Zet hem op
> een plek waar dat geen probleem is, en vergrendel het scherm gerust
> (Win+L): JARVIS blijft gewoon werken.

### Nooit slapen (zelf instellen)

PowerShell als administrator:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10
```

En in het BIOS/UEFI van de mini-pc: **"Restore on AC power loss"** (of
*After Power Loss*) op **Power On**, zodat hij na een stroomstoring zelf
aangaat.

## 4. Backups (M3)

JARVIS maakt **elke nacht om 04:00** zelf een backup. Stond de pc toen uit,
dan haalt hij hem 5 minuten na het starten in. Mislukt hij, dan probeert hij
het elk uur opnieuw en meldt hij het één keer per dag ("Sir, de backup is
mislukt: …"). In het **Systeem**-paneel (*Deze pc*) staat de laatste backup;
oranje als hij mislukt is of ouder dan 36 uur.

| Instelling (`.env`) | Standaard | Betekenis |
|---|---|---|
| `BACKUP_MAP` | `%USERPROFILE%\JARVIS-backups` | waar de backups komen; **liefst een andere schijf** (bijv. `D:\JARVIS-backups`), nooit in de projectmap |
| `BACKUP_TIJD` | `04:00` | tijdstip van de dagelijkse backup |
| `BACKUP_DAGEN` | `7` | de laatste backup per dag, zoveel dagen terug |
| `BACKUP_WEKEN` | `4` | de laatste backup per week, zoveel weken terug |
| `BACKUP_ENABLED` | `1` | `0` = geen automatische backups |

Een backup bevat precies hetzelfde als het verhuispakket (§2): gegevens én
geheimen (`.env`, `certs/`). Hij wordt na het maken meteen gecontroleerd. De
nieuwste blijft altijd staan, en alleen bestanden met de naam
`jarvis-backup-….zip` worden ooit opgeruimd.

```powershell
python scripts\brein_backup.py            # nu een backup maken
python scripts\brein_backup.py --lijst    # bestaande backups
```

### Terugzetten

```powershell
Stop-ScheduledTask -TaskName 'JARVIS Brein'
python scripts\brein_restore.py --laatste --alleen-controle   # eerst kijken
python scripts\brein_restore.py --laatste                    # terugzetten
Start-ScheduledTask -TaskName 'JARVIS Brein'
```

Of een bepaalde: `python scripts\brein_restore.py jarvis-backup-20261025-040000.zip`.
Terugzetten gebruikt dezelfde veilige import als de verhuizing: wat
overschreven wordt, gaat eerst in een veiligheidszip.

> Een backup op dezelfde schijf beschermt tegen fouten (een kapot
> `memory.json`, iets per ongeluk gewist), niet tegen een kapotte schijf.
> `brein_check.py` waarschuwt daarom als de backup op dezelfde schijf staat.

## 4b. Slaapstand (M4)

| | "Ga slapen" | Auto-slaap |
|---|---|---|
| Hoe | zeg *"ga slapen"*, *"ga maar slapen"*, *"welterusten"* of *"slaap lekker"* | na `AUTOSLAAP_MINUTEN` (standaard 30) zonder commando én zonder pc-gebruik |
| Wakker | alleen met *"Hey JARVIS"*; hij zegt *"Tot uw dienst, sir."* | met *"Hey JARVIS"* (piep) of zodra u de pc weer gebruikt |

Slapend:

- reageert JARVIS alleen op het wake word;
- zegt hij niets uit zichzelf, **behalve timers en wekkers**; andere meldingen
  wachten tot hij wakker is;
- haalt hij het AI-model uit het geheugen (minder stroom en geheugen). Bij
  het wakker worden laadt hij het alvast, terwijl u uw opdracht inspreekt;
- toont de orb op het dashboard **SLAAPT** (gedimd, langzaam).

Een stille modus die u zelf aanzette, blijft na het wakker worden aan.
*"Ik ga slapen"* blijft de slaaproutine (lampen uit enz.), en *"zet de pc in
slaapstand"* gaat over de pc zelf, niet over JARVIS. *"Stop jarvis"* of
*"tot ziens"* beëindigt alleen het gesprek.

## 4c. Stem kiezen (M5)

Geen eigen getraind model, maar een bestaande Piper-stem goed afgesteld.
`scripts\stem_proef.py` spreekt dezelfde vier JARVIS-zinnen uit met elke
stem en vier instellingen, en bewaart ze in `%USERPROFILE%\JARVIS-stemproef`
(`<stem>__<preset>.wav`):

| Preset | Tempo (`length_scale`) | Klank (`noise_scale`) | Ritme (`noise_w`) |
|---|---|---|---|
| standaard | 1.0 | van het model | van het model |
| kalm | 1.1 | 0.5 | 0.6 |
| droog | 1.05 | 0.35 | 0.5 |
| butler | 1.15 | 0.4 | 0.4 |

Hoger tempo-getal = langzamer. Lagere klank- en ritmevariatie = vlakker en
gelijkmatiger (droger, kalmer). Stemmen: `nl_NL-pim-medium` (de huidige),
`nl_NL-ronnie-medium` en `nl_BE-rdh-medium` (Vlaams).

```powershell
python scripts\stem_proef.py --download     # de extra stemmen (eenmalig, ±60 MB per stem)
python scripts\stem_proef.py                # alle proeven naar .wav
python scripts\stem_proef.py --stem nl_NL-ronnie-medium --preset kalm --speel
python scripts\stem_proef.py --kies nl_NL-ronnie-medium kalm   # regels voor .env
```

`--kies` geeft de regels `PIPER_VOICE`, `PIPER_LENGTH_SCALE`,
`PIPER_NOISE_SCALE`, `PIPER_NOISE_W` en `PIPER_SPEAKER`; zet ze in `.env`
en herstart JARVIS.

**Meersprekermodel** `nl_NL-mls-medium` (52 Nederlandse sprekers): met
`--sprekers` maakt het script per spreker een korte proef in
`%USERPROFILE%\JARVIS-stemproef\nl_NL-mls-medium\` en sorteert ze op toonhoogte,
het dichtst bij een voorbeeldstem eerst:

```powershell
python scripts\stem_proef.py --sprekers nl_NL-mls-medium --preset butler --zoals nl_BE-rdh-medium
python scripts\stem_proef.py --kies nl_NL-mls-medium butler --spreker 36
```

De proefstemmen staan in `voice/models/proef/`, zodat ze de huidige stem niet
vervangen zolang u niets kiest. Op de mini-pc: kopieer de gekozen stem mee
(`voice/models/` gaat niet mee in het verhuispakket) of draai daar
`stem_proef.py --download`.

## 4d. Updates en verbindingen (M6)

### Updates

Kort na het starten (na 10 minuten) en daarna elke dag kijkt JARVIS op
GitHub of er een nieuwe versie is. Is die er, dan meldt hij dat één keer per
versie, met de belangrijkste wijzigingen. In het Systeem-paneel (*Deze pc*)
staat dan **Update: N wijzigingen** met een knop **Installeren…**.

**Installeren gebeurt alleen na uw "ja"**: tik op *Installeren…* of zeg
*"installeer de update"*, en keur het goed in het oranje venster (of zeg
"ja"). Dan:

1. maakt JARVIS eerst een backup (mislukt die, dan installeert hij niets);
2. haalt hij de nieuwe versie op, maar alleen als *fast-forward*: heeft deze
   pc eigen commits of lokale wijzigingen in de code, dan weigert hij;
3. installeert hij nieuwe pakketten, alleen als `requirements.txt` veranderde;
4. start hij opnieuw op via de waakhond (zonder wachttijd; telt niet als
   crash). Zonder waakhond vraagt hij u JARVIS zelf te herstarten.

Weigert hij met "lokale wijzigingen (…)", dan noemt hij de bestanden; voor `config/dashboard.json` zie `docs/dashboard.md` (§4). Zelf vragen: *"zijn er updates?"*. Uitzetten: `UPDATES_ENABLED=0` in `.env`.
De game-pc-agent wordt níet op afstand bijgewerkt; doe daar zelf `git pull`
en herstart de taak *JARVIS Game-PC Agent*.

### Verbinding verbroken

JARVIS houdt drie verbindingen in de gaten en meldt één keer als er een
wegvalt, en één keer als hij terug is:

| Verbinding | Gecontroleerd met | Wat er dan nog werkt |
|---|---|---|
| Game-pc-agent | de health-check van de agent (alleen bij `PC_TARGET=game-pc`) | alles behalve de game-pc bedienen |
| AI-model (Ollama) | de modellenlijst van Ollama | vaste opdrachten (timers, lampen, media, routines) |
| Internet | een verbinding met 1.1.1.1 / 8.8.8.8 (poort 443, geen DNS, er wordt niets verstuurd) | alles wat lokaal is |

Is een verbinding weg, dan probeert hij het opnieuw na 30 s, 1, 2 en daarna
elke 5 minuten. De meldingen zijn gewone regels in
`config/proactive_rules.json` (`game_pc_offline`, `ollama_online`, …): zet
`"actief": false` om er een uit te zetten, bijvoorbeeld als u de game-pc vaak
uitzet. In de nacht- en stille modus wachten ze tot de ochtend.

## 5. Testlijst M1 (op de mini-pc)

- [ ] `install_brein.ps1 -DryRun` loopt zonder fouten door
- [ ] Na de installatie: `brein_check.py` zonder ❌
- [ ] JARVIS kent na de import uw geheugen ("wat weet je over mij?")
- [ ] De iPad verbindt zonder opnieuw te koppelen (na `make_dashboard_cert.py --force`)
- [ ] De game-pc reageert ("zet Spotify op 30 procent")

## 6. Testlijst M2 (op de mini-pc)

- [ ] `install_brein_autostart.ps1 -StartNu`: JARVIS start en zegt "JARVIS is online."
- [ ] Het Systeem-paneel (Deze pc) toont "JARVIS actief … · bewaakt · 0 herstarts"
- [ ] Het JARVIS-proces afschieten in Taakbeheer → na ±5 s zegt hij "JARVIS is weer online." en het dashboard toont de melding
- [ ] `Stop-ScheduledTask -TaskName 'JARVIS Brein'` → JARVIS is echt weg (geen python.exe meer in Taakbeheer)
- [ ] Herstart van de mini-pc → logt zelf in en JARVIS start vanzelf

## 7. Testlijst M3 (op de mini-pc)

- [ ] `BACKUP_MAP` op een andere schijf gezet; `brein_check.py` toont ✅ bij Backup na de eerste backup
- [ ] `python scripts\brein_backup.py` maakt een backup; `--lijst` toont hem
- [ ] De volgende ochtend: het Systeem-paneel toont "Backup <datum> 04:00 ✓"
- [ ] `brein_restore.py --laatste --alleen-controle` toont "al gelijk" voor alles

## 8. Testlijst M4 (op de mini-pc)

- [ ] "Hey JARVIS" → "ga slapen": hij zegt dat hij gaat slapen en de orb toont SLAAPT
- [ ] Een timer gaat tijdens het slapen gewoon af
- [ ] "Hey JARVIS": "Tot uw dienst, sir." en de volgende vraag krijgt meteen antwoord
- [ ] Tijdens het slapen: `ollama ps` toont geen geladen model

## 9. Testlijst M5

- [ ] De proeven in `%USERPROFILE%\JARVIS-stemproef` beluisterd en een stem + preset gekozen
- [ ] De regels van `--kies` in `.env` gezet; na een herstart klinkt JARVIS zo

## 10. Testlijst M6 (op de mini-pc)

- [ ] "Zijn er updates?" → "JARVIS is up-to-date, sir." (of de wijzigingen)
- [ ] Na een nieuwe push naar GitHub: binnen een dag een melding en de knop *Installeren…*
- [ ] *Installeren…* → oranje venster → *Annuleer* doet niets; *Ja* maakt een backup, werkt bij en JARVIS zegt na de herstart "JARVIS is weer online."
- [ ] De game-pc uitzetten → melding "De game-pc is niet meer bereikbaar"; weer aan → "weer bereikbaar"
- [ ] Ollama stoppen → melding; "zet een timer van een minuut" werkt nog; Ollama starten → "Mijn AI-model werkt weer."
