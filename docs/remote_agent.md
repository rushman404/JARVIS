# 🖥️ Game-PC Agent (remote)

Met de Game-PC Agent kan JARVIS op afstand een **gaming-pc** bedienen terwijl
het brein (straks de mini-pc) ergens anders draait. Denk aan:

- games en programma's **starten, sluiten of opvragen**;
- **status en telemetrie** ophalen (CPU, geheugen, schijf, GPU-temperatuur);
- **media en volume** regelen;
- een **screenshot** maken.

> Dit is Fase 15 uit [ROADMAP.md](../ROADMAP.md): de basis voor de
> mini-pc-architectuur. De game-pc is de computer die op afstand wordt
> bediend; de mini-pc wordt later het brein.

---

## 1. Hoe het werkt

```text
   Mini-pc / brein (CLIENT)                    Game-pc (SERVER)
   ────────────────────────                    ────────────────
   JARVIS  ──►  remote/client.py  ──TLS/HMAC──►  remote/server.py
                                                     │
                                                     ├─ allowlist
                                                     ├─ audit-log
                                                     └─ voert de actie uit
```

- Op de **game-pc** draait `remote/server.py` als klein Windows-programma.
- Op het **brein** draait JARVIS met `remote/client.py`.
- Alle verzoeken gaan over **TLS** en zijn **HMAC-ondertekend**.

### Beveiliging in het kort

| Laag | Wat het doet |
|---|---|
| **TLS** | Zelfondertekend certificaat; de client controleert het expliciet (nooit uit). |
| **HMAC** | Elk verzoek is ondertekend met het gedeelde token + tijdstip + nonce + body. |
| **Replay-bescherming** | Verlopen tijdstippen en hergebruikte nonces worden geweigerd. |
| **Allowlist** | Alleen een vaste lijst acties mag draaien — nooit vrije shell/PowerShell. |
| **IP-allowlist** | Alleen privé-adressen (of een expliciete lijst) mogen verbinden; publieke adressen altijd geweigerd. |
| **Lockout** | Na 5 mislukte authenticaties binnen 60 seconden gaat dat IP 5 minuten op slot. |
| **Goedkeuring** | Risicovolle acties (`power`, `empty_recycle_bin`, `ui_launch_app`, `recycle_file`, bestanden wijzigen) vragen eerst goedkeuring op het brein. |
| **Audit** | Elke actie en elke weigering komt in het audit-log, zonder geheimen. |
| **Fail-closed** | Zonder token/certificaat start de server niet. |

---

## 2. Vereisten

- **Windows** op de game-pc (de agent gebruikt Windows-specifieke tools).
- **Python 3.11 of nieuwer** op beide machines.
- De JARVIS-projectmap op beide machines (`git clone` of kopiëren).
- Runtime-afhankelijkheden: `pip install -r requirements.txt`.
- Voor het genereren van het certificaat met het meegeleverde script:
  `pip install -r requirements-dev.txt` (bevat `cryptography`), of gebruik
  OpenSSL (zie §4).

---

## 3. Installatie op de game-pc (server)

1. **Zet het project op de game-pc** en installeer de afhankelijkheden:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Maak een token** (gedeeld geheim). Bewaar het veilig; het komt in het
   `.env`-bestand, nooit in de repository:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Het token moet **minimaal 16 tekens** zijn (`REMOTE_MIN_TOKEN_LENGTH`).

3. **Genereer het certificaat** (zie §4).

4. **Maak `.env`** op de game-pc (kopieer `.env.example`) en vul in:

   ```ini
   REMOTE_SERVER_ENABLED=1
   REMOTE_SERVER_HOST=0.0.0.0
   REMOTE_SERVER_PORT=8765
   REMOTE_SERVER_TOKEN=<hetzelfde-token-als-het-brein>
   REMOTE_SERVER_CERT_FILE=certs/agent-cert.pem
   REMOTE_SERVER_KEY_FILE=certs/agent-key.pem
   ```

5. **Start de agent** (zie §8) of zet de auto-start op (zie §7).

---

## 4. Certificaat genereren

### Optie A — meegeleverd Python-script (aanbevolen)

```powershell
python scripts\gen_remote_cert.py --host <naam-of-ip-van-de-game-pc> --ip <ip-van-de-game-pc>
```

Het script zet `agent-cert.pem` en `agent-key.pem` in `certs/` (staat in
`.gitignore`). Standaard worden `localhost` en `127.0.0.1` altijd in de
certificaat-SAN opgenomen, zodat lokale tests blijven werken.

Handige opties:

| Optie | Betekenis |
|---|---|
| `--out-dir <map>` | Andere map dan `certs/`. |
| `--host <naam>` | Extra DNS-naam (herhaalbaar). |
| `--ip <adres>` | Extra IP-adres (herhaalbaar). |
| `--days <n>` | Geldigheid in dagen (standaard 825). |
| `--bits <2048\|3072\|4096>` | RSA-sleutellengte. |
| `--force` | Bestaande bestanden overschrijven. |

> De **privésleutel** wordt nooit naar het scherm of een log geschreven; het
> script print alleen de paden en de SHA-256-vingerafdruk.

### Optie B — OpenSSL

Geen `cryptography` nodig:

```powershell
openssl req -x509 -newkey rsa:2048 -nodes `
    -keyout agent-key.pem -out agent-cert.pem -days 825 `
    -subj "/CN=jarvis-game-pc-agent" `
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:<ip-van-de-game-pc>"
```

Zet daarna `REMOTE_SERVER_CERT_FILE` / `REMOTE_SERVER_KEY_FILE` op de
gemaakte bestanden.

---

## 5. Configuratie op de mini-pc (brein / client)

Kopieer het **certificaat** (`agent-cert.pem`) naar het brein — **niet** de
sleutel — en vul de client-instellingen in:

```ini
REMOTE_CLIENT_ENABLED=1
REMOTE_CLIENT_HOST=<ip-of-hostnaam-van-de-game-pc>
REMOTE_CLIENT_PORT=8765
REMOTE_CLIENT_TOKEN=<hetzelfde-token-als-de-game-pc>
REMOTE_CLIENT_CA_FILE=certs/agent-cert.pem
REMOTE_CLIENT_TIMEOUT=5
```

- `REMOTE_CLIENT_HOST` moet **het LAN-IP of de hostnaam van de game-pc** zijn.
  `127.0.0.1` is alleen bedoeld voor lokale tests; de client waarschuwt in
  het log als je loopback gebruikt.
- De hostnaam of het IP moet in de **SAN** van het certificaat staan
  (daarom geef je die mee aan `gen_remote_cert.py`).

### Overzicht client-instellingen

| Variabele | Standaard | Betekenis |
|---|---|---|
| `REMOTE_CLIENT_ENABLED` | `0` | `1` = client aan. |
| `REMOTE_CLIENT_HOST` | `127.0.0.1` | Adres van de game-pc. |
| `REMOTE_CLIENT_PORT` | `8765` | Poort van de agent. |
| `REMOTE_CLIENT_TOKEN` | *(leeg)* | Gedeeld geheim (min. 16 tekens). |
| `REMOTE_CLIENT_CA_FILE` | *(leeg)* | Vertrouwd certificaat van de game-pc. |
| `REMOTE_CLIENT_TIMEOUT` | `5` | Time-out per verzoek in seconden. |

### Standaarddoel: eerst lokaal, dan omzetten (`PC_TARGET`)

JARVIS bedient standaard **deze pc** (`PC_TARGET=local`). Zo werkt alle
pc-bediening meteen, ook zonder game-pc. Zet het doel pas om als de agent
draait en de client hierboven compleet is ingevuld.

**Stap 1 — eerst lokaal werkend.** Laat `PC_TARGET` op `local` staan (de
standaard). Test op deze pc bijvoorbeeld:

```
"open spotify"
"zet het volume op 30"
"pauzeer de muziek"
```

Deze commando's gaan via de snelle (deterministische) handlers en hebben
geen LLM nodig.

**Stap 2 — het doel omzetten naar de game-pc.** Vul de client-instellingen
hierboven in (`REMOTE_CLIENT_ENABLED=1`, host, token en certificaat) en zet
daarna:

```ini
PC_TARGET=game-pc
```

Vanaf dan gaan dezelfde zinnen naar de **game-pc** in plaats van naar deze
pc. Je kunt altijd nog per zin terug naar deze pc door hem expliciet te
noemen ("op de mini-pc" of "op de server").

Staat `PC_TARGET=game-pc` terwijl de client uit of onvolledig is, dan meldt
JARVIS dit bij het opstarten (in het log én gesproken) en **falen**
game-pc-commando's met een duidelijke melding. JARVIS voert een opdracht voor
de game-pc **nooit** stilletjes lokaal uit.

### Overzicht server-instellingen

| Variabele | Standaard | Betekenis |
|---|---|---|
| `REMOTE_SERVER_ENABLED` | `0` | `1` = server aan. |
| `REMOTE_SERVER_HOST` | `0.0.0.0` | Bind-adres. |
| `REMOTE_SERVER_PORT` | `8765` | Poort. |
| `REMOTE_SERVER_TOKEN` | *(leeg)* | Gedeeld geheim (min. 16 tekens). |
| `REMOTE_SERVER_CERT_FILE` | *(leeg)* | Pad naar het certificaat. |
| `REMOTE_SERVER_KEY_FILE` | *(leeg)* | Pad naar de privésleutel. |
| `REMOTE_SERVER_ALLOWED_IPS` | *(leeg)* | Komma-gescheiden lijst van toegestane client-IP's (vul hier het IP van de mini-pc in). Leeg = alleen privé-adressen. |
| `REMOTE_REPLAY_WINDOW_SECONDS` | `30` | Hoe oud een ondertekend verzoek mag zijn. |

---

## 6. Certificaatvertrouwen en tokenbeheer

- **Certificaatvertrouwen.** De client vertrouwt precies het certificaat dat
  je in `REMOTE_CLIENT_CA_FILE` zet. Het is zelfondertekend, dus er is geen
  certificaatautoriteit nodig. Klopt het niet (verlopen, verkeerde host,
  ander bestand), dan weigert de client de verbinding — dat is de bedoeling.
- **Sleutel geheim.** Alleen de game-pc heeft `agent-key.pem`. Deel **nooit**
  de sleutel; deel alleen het certificaat met het brein.
- **Token roteren.** Genereer een nieuw token, zet het op **beide** machines
  in `.env` en herstart de agent. Zonder geldig token weigert de server elk
  verzoek (`401`).
- **Geen geheimen in de repo.** `.env`, `certs/`, `*.pem` en `*.key` staan in
  `.gitignore`. Tokens en handtekeningen komen niet in het audit-log of in
  de server-log.

---

## 7. Windows Firewall

De agent bindt standaard op het hele LAN (`0.0.0.0:8765`). Beperk inkomende
verbindingen het liefst tot **het IP-adres van de mini-pc**, in het
**privé-profiel**:

```powershell
New-NetFirewallRule -DisplayName "JARVIS Game-PC Agent" `
    -Direction Inbound -Action Allow -Protocol TCP `
    -Profile Private `
    -LocalPort 8765 -RemoteAddress <ip-van-de-mini-pc>
```

(Administrator-rechten nodig.) Draai je het installatiescript met
`-AddFirewallRule`, dan wordt deze regel automatisch aangemaakt — met
verplichte `-AllowedRemoteAddress`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_game_pc_agent.ps1 `
    -AddFirewallRule -AllowedRemoteAddress <ip-van-de-mini-pc>
```

> Los daarvan weigert de server zelf ook verbindingen van buiten
> `REMOTE_SERVER_ALLOWED_IPS` (en publieke adressen altijd), nog vóór de
> handtekeningcontrole. De firewall is dus een tweede slot op de deur, niet
> het enige.

---

## 8. Auto-start met Windows Taakplanner

Het installatiescript maakt een taak die na **inloggen** het
**taakbalk-icoon** van de agent start (zie §9):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_game_pc_agent.ps1
```

- Herhaalbaar: dezelfde taaknaam (`JARVIS Game-PC Agent`) wordt **bijgewerkt**
  in plaats van gedupliceerd.
- Het script controleert **eerst** de beveiligingsconfiguratie (token +
  certificaat) en breekt af als die niet compleet is.
- Er staan **geen geheimen** in de taak: de agent leest ze uit `.env`.
- De taak start `pythonw -m remote.tray`, dus **zonder zwart venster**. Het
  icoon start op zijn beurt de agent (`python -m remote.server`). Daarvoor
  is `pystray` nodig (staat in `requirements.txt`).
- Met `-DryRun` zie je alleen wat er gebeurt; met `-PythonPath` kies je een
  specifieke `python.exe`.

### Handmatig (zonder script)

```powershell
$actie = New-ScheduledTaskAction -Execute "C:\pad\naar\python.exe" `
    -Argument "-m remote.server" -WorkingDirectory "C:\pad\naar\JARVIS"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "JARVIS Game-PC Agent" `
    -Action $actie -Trigger $trigger -Force
```

Of via de opdrachtregel:

```powershell
schtasks /Create /TN "JARVIS Game-PC Agent" ^
    /TR "\"C:\pad\naar\python.exe\" -m remote.server" /SC ONLOGON
```

---

## 9. Starten, stoppen en status

### Het taakbalk-icoon

Rechtsonder in de taakbalk (bij het pijltje `^`) staat een rond
**J**-icoon. De kleur toont de toestand:

| Kleur | Betekenis |
|---|---|
| groen | de agent draait |
| oranje | de agent is gecrasht en start zo opnieuw |
| grijs | de agent staat uit |
| rood | de agent is te vaak gecrasht en staat uit (kijk in het logboek) |

**Rechtermuisknop** op het icoon geeft het menu:

- **Starten** / **Stoppen**: de agent aan- of uitzetten. Het icoon blijft staan.
- **Herstarten**: stoppen en meteen weer starten.
- **Logboek openen**: `logs/agent.log`, met wat eerst in het zwarte venster stond.
- **Afsluiten**: agent én icoon stoppen. Opnieuw starten gaat dan via de
  geplande taak (hieronder) of door opnieuw in te loggen.

**Linkermuisknop** toont de status als melding.

Het icoon bewaakt de agent ook. Na een zelf-update start het hem meteen
opnieuw. Na een crash wacht het eerst even (5 s, dan 15 s, 30 s, ...).
Na 5 crashes binnen 15 minuten geeft het het op en toont het een melding.
Stopt het icoon, dan stopt de agent mee.

Het pijltje verbergt het icoon standaard. Wilt u het altijd zien, zet het
dan aan via *Instellingen → Persoonlijke instellingen → Taakbalk → Andere
systeemvakpictogrammen* ("JARVIS Game-PC Agent" of "pythonw").

### Handmatig

**Handmatig starten** (in de projectmap op de game-pc):

```powershell
python -m remote.server
```

Dan draait de agent in het consolevenster en is er geen icoon; sluit u
dat venster, dan stopt de agent.

**Via de geplande taak** (start/stopt het icoon, en daarmee de agent):

```powershell
Start-ScheduledTask  -TaskName "JARVIS Game-PC Agent"
Stop-ScheduledTask   -TaskName "JARVIS Game-PC Agent"
Get-ScheduledTask    -TaskName "JARVIS Game-PC Agent"
```

De server logt op welk adres hij luistert en herinnert aan de firewallregel.

---

## 10. Testen

**Is de agent online?** (op het brein)

```powershell
python -c "from remote.client import RemoteClient; print(RemoteClient().is_online())"
```

**Een eenvoudige opdracht** (bijvoorbeeld status opvragen):

```powershell
python -c "from remote.client import RemoteClient; print(RemoteClient().send_command('pc_status').samenvatting())"
```

**Vanuit JARVIS** zeg je gewoon bijvoorbeeld:

```text
"Open Discord op de game-pc."
"Maak een screenshot op de game-pc."
"Wat is de temperatuur van de game-pc?"
"Zet het volume op de game-pc op 30."
```

**De testsuite** (op elke machine, zonder netwerk):

```powershell
pip install -r requirements-dev.txt
pytest
ruff check .
```

**De echte LAN-verbinding** test je op de mini-pc met:

```powershell
python scripts/test_remote_lan_manual.py
```

Dat script loopt zes stappen langs en drukt per stap "geslaagd" of
"mislukt" af:

1. online-check — is de poort van de agent bereikbaar?
2. ondertekende health — kloppen token en certificaat?
3. verkeerd token — hoort netjes 401 te geven;
4. verouderde tijd — een oude handtekening hoort geweigerd te worden;
5. volume-opdracht — een echte opdracht naar de game-pc;
6. screenshot — een echte schermafbeelding op de game-pc.

Stap 5 en 6 hebben echt effect op de game-pc: zet daar eerst het volume
goed en zorg dat een screenshot maken mag. Het script gebruikt de
`REMOTE_CLIENT_*`-instellingen uit `.env`; die moeten naar het LAN-adres
van de game-pc wijzen (niet naar `127.0.0.1`). Alles geslaagd betekent dat
de mini-pc de game-pc volledig op afstand kan bedienen.

**Alle functies in één keer** (op de mini-pc / laptop):

```powershell
python -m scripts.test_alle_functies_manual
```

Dat script test elke game-pc-tool die JARVIS kent: verbinding en
beveiliging (health, verkeerd token, oude handtekening), status en
systeem, programma's, volume en audio, vensters, bestanden, browser,
stroomacties en Home Assistant. Zonder vlaggen doet het alleen
leesacties (status opvragen, screenshot, Discord naar voren halen).
Zwaardere testen zet je aan met een vlag:

| Vlag | Wat het test | Let op |
|---|---|---|
| `--acties` | volume, media (incl. mute en volume op/neer), vensters, Discord herstarten, Notepad openen en sluiten | zichtbaar op de game-pc |
| `--bestanden` | list/recent/search en create/rename/move/recycle | maakt testbestanden aan en ruimt ze op |
| `--browser` | website openen, tabbladen, zoeken | opent tabbladen op de game-pc |
| `--ui` | vensters uitlezen, elementen zoeken en waarden lezen, venster naar voren halen | er wordt nooit geklikt of getypt |
| `--zinnen` | Nederlandse zinnen via het brein | opent Spotify en zet het volume op 50% |
| `--power ACTIE` | stroomactie: lock, sleep, restart of shutdown | vraagt een getypte bevestiging |
| `--ha-actie light.slaapkamer` | Home Assistant-toggle | verandert een echt apparaat |

Het script drukt per test `GESLAAGD`, `MISLUKT`, `LET OP` of
`OVERGESLAGEN` af, schrijft een JSON-rapport naar `logs/` en eindigt met
een samenvatting. Exitcode 0 betekent alles goed, 1 betekent dat een
test mislukte. Het script blijft onder de limiet van de agent (60
opdrachten per minuut) en probeert het bij een 429 vanzelf opnieuw.

### Verwachte aantallen

Het script rekent zelf uit wat er bij de gekozen vlaggen uit moet komen.
Vóór de run print het een tabel `VERWACHTING BIJ DEZE VLAGGEN` met per
sectie het aantal geslaagde en overgeslagen tests; na de run komt
dezelfde tabel als `CONTROLE OP DE VERWACHTING`, met de werkelijke
aantallen en per sectie `ok` of `WIJKT AF`. In het JSON-rapport staat
de verwachting onder `"verwachting"`.

Vuistregels:

- **`mislukt` moet altijd 0 zijn.** Elke mislukte test is een echt probleem.
- **`overgeslagen` hoort precies op de verwachting te staan.** Elke extra
  overgeslagen test betekent meestal een verkeerd profiel (`basis` in
  plaats van `werkstation`) of een ontbrekende app (Spotify/Discord).
- **`let op`** betekent: uitgevoerd, maar met een kanttekening. Telt niet
  als fout, maar is wel het bekijken waard.
- De audio-sectie hangt af van de situatie: 19 tests met een bestaande
  audio-sessie, 22 als het script Spotify of Discord eerst moet starten.
- Home Assistant telt 2 geslaagd + 1 overgeslagen zonder `--ha-actie`, en
  3 geslaagd met. Is HA op de laptop niet ingesteld, dan meldt de
  controle `n.v.t. (HA niet ingesteld)`.

De volledige run met alle vlaggen behalve `--power` (dus
`--acties --bestanden --browser --ui --zinnen --ha-actie ...`) gaf op
22-10-2026: **72 geslaagd, 0 mislukt, 0 let op, 1 overgeslagen** (de
stroomactie). De verwachtingstabel noemt **72-75 geslaagd en 1
overgeslagen**: die drie extra tests zijn de audio-sessie die het script
zo nodig eerst opwekt. Met `--power lock` erbij wordt dat **73-76
geslaagd en 0 overgeslagen**. Zonder ingestelde Home Assistant zakt het
aantal geslaagde tests met 2 en komt er 1 overgeslagen bij.

| Uitzondering | Waarom niet automatisch |
|---|---|
| `game_pc_ui_click_element`, `ui_type_text`, `ui_set_value` | klikt of typt in een onbekend venster |
| `game_pc_ui_launch_app` | start een willekeurig programma op een pad |
| `game_pc_open_file` | opent een bestand in een willekeurig programma |
| `game_pc_audio_set_default_output` | verandert het standaard audio-apparaat |
| `game_pc_empty_recycle_bin` | leegt de prullenbak van de game-pc |
| `game_pc_power` | vraagt `--power` en een getypte bevestiging |

Staat de agent op profiel `basis`, dan weigert hij bestands-, browser-,
UI- en stroomacties. Het script meldt die als "overgeslagen" met de
reden erbij. Voor een volledige test zet je op de game-pc
`REMOTE_SERVER_PROFILE=werkstation`, herstart je de agent, en zet je hem
daarna terug op `basis`.

---

## 11. Wat mag er op afstand?

Alleen de acties uit de allowlist (`remote/allowlist.py`) mogen draaien —
nooit vrije shell- of PowerShell-commando's. De lijst telt **57 acties**,
gegroepeerd op risico. De risicoklasse bepaalt of het brein eerst om
goedkeuring vraagt (hoog/medium) of de actie direct uitvoert (laag).

### Serverprofiel: basis of werkstation

De server heeft twee profielen (`REMOTE_SERVER_PROFILE`):

- **basis** (standaard) — alleen programma's en games starten/sluiten,
  vensterbediening, media/volume, audio uitlezen én audio per app
  bedienen (`audio_set_session_volume`, `audio_set_session_mute`,
  `audio_toggle_session_mute` — die blijven risico medium en vragen dus
  goedkeuring op het brein), systeemstatus en screenshot. Bestanden
  wijzigen, UI-automatisering, power en browser zijn hier uitgesloten.
  Dit is de veilige standaard.
- **werkstation** — alles: ook bestanden lezen/wijzigen, scherm
  bedienen (klikken/typen), power en browser. Alleen als je dit
  expliciet aanzet.

Zet je `REMOTE_SERVER_PROFILE=werkstation`, dan gelden de risicoklassen
hieronder volledig. In basis-profiel wordt alles buiten de basislijst
geweigerd ongeacht de risicoklasse; die melding laat zien hoe je het
werkstation-profiel aanzet (`REMOTE_SERVER_PROFILE=werkstation`).

### Denylist: een vangnet, geen grens

De denylist voor programma's (cmd, PowerShell, regedit, Windows Terminal,
Python, ...) is een **naamgebaseerd vangnet**. Het is geen harde grens:
een proces dat zich anders noemt of een pad dat niet lijkt op de denylist,
kan er doorheen glippen. De **echte grens** bestaat uit:

1. het **token** (geheim, ≥ 32 tekens);
2. **TLS** (certificaat verplicht, geen plaintext);
3. de **IP-allowlist** (alleen je mini-pc);
4. het **profiel** (basis blokkeert gevaarlijke acties structureel);
5. de **goodkeuringspoort** op het brein (risicovolle acties vragen om
   bevestiging).

De denylist vangt de meest voorkomende gevallen (Startmenu-namen,
procesnamen, weergavenaam-combinaties op hele woorden zoals "command
prompt", "git bash" of "python 3") en blokkeert typen/klikken in
vensters van onbekende processen (fail-closed). Omdat er op hele
woorden wordt gematcht, blijven gamenamen als "Idle Champions of the
Forgotten Realms", "Terminal Velocity" en "Python Tycoon" gewoon
werken; een exacte procesnaam als `cmd`, `wt`, `bash`, `python`,
`terminal` of `idle` blijft geweigerd. Beschouw het als een extra
laag, niet als de enige beveiliging.

> ⚠️ **Wat er gebeurt als je token lekt.** Wie het token én een geldig
> privé-adres heeft, kan **alles in het actieve profiel** op de game-pc
> doen. In basis: games sluiten, apps starten, media bedienen, audio
> per app regelen, status uitlezen, screenshot maken. In werkstation: ook bestanden kopiëren,
> verplaatsen, hernoemen, naar de prullenbak sturen, de prullenbak
> legen, het scherm bedienen (klikken en typen) en de pc **afsluiten,
> herstarten, in slaapstand zetten, vergrendelen of uitloggen**. De
> goedkeuringsvraag is een drempel op het brein — bij een rechtstreeks
> ondertekend verzoek (buiten JARVIS om) vervalt die. Bewaar het token
> daarom als een wachtwoord.

### Acties per risicoklasse (werkstation-profiel)

#### Hoog risico (vraagt altijd eerst goedkeuring)

- `power` — afsluiten, herstarten, slapen, sluimerstand, vergrendelen,
  uitloggen en een lopende afsluiting annuleren.
- `empty_recycle_bin` — de prullenbak leegmaken.
- `ui_launch_app` — een willekeurige app via de interface starten.

#### Middel risico (vraagt eerst goedkeuring)

- **Bestanden wijzigen:** `move_file`, `copy_file`, `rename_file`,
  `create_folder`, `create_file`.
- **Verwijderen (naar de prullenbak, nooit definitief):** `recycle_file`.
- **Programma's:** `restart_program`.
- **Scherm bedienen:** `ui_click_element`, `ui_type_text`, `ui_set_value`.
- **Audio-uitvoer:** `audio_set_default_output`.

#### Laag risico (direct uitvoeren, geen vraag)

- **Programma's/games:** `open_program`, `close_program`, `program_status`,
  `find_program_location`.
- **Vensters:** `minimize_window`, `maximize_window`, `restore_window`.
- **Systeem/status:** `system_info`, `pc_status`, `screenshot`.
- **Meldingen:** `show_notification` (titel + tekst als Windows-toast;
  het brein toont zo timers en herinneringen op de game-pc).
- **Media/volume:** `media_play_pause`, `media_next`, `media_previous`,
  `media_stop`, `media_mute`, `volume_up`, `volume_down`, `set_volume`.
- **Eén app pauzeren:** `media_pause_app` (Fase 21, film-modus): pauzeert
  bijv. Spotify alleen als die speelt (de venstertitel toont dan een nummer),
  zodat JARVIS nooit per ongeluk muziek start.
- **Spotify-link openen:** `spotify_open` (Fase 21, M5): alleen
  `spotify:track|album|playlist|artist:<22 tekens>`, geen andere links of bestanden.
- **Games:** `game_lijst` (Steam-bibliotheek + Riot: Valorant/League) en
  `game_start` (Fase 21, M6): alleen een id uit die eigen lijst (`steam:<id>` of
  `riot:<product>`), nooit een pad of commando.
- **Audio uitlezen:** `audio_list_sessions`, `audio_get_session_volume`,
  `audio_list_outputs`, `audio_get_default_output`.
- **Audio per app:** `audio_set_session_volume`, `audio_set_session_mute`,
  `audio_toggle_session_mute` (sinds Fase 20 laag risico, net als `set_volume`).
- **Bestanden lezen:** `list_files`, `open_folder`, `open_file`,
  `search_files`, `recent_files`.
- **Scherm uitlezen:** `ui_list_windows`, `ui_find_window`,
  `ui_activate_window`, `ui_list_elements`, `ui_find_element`, `ui_get_value`.
- **Browser & websites:** `open_website`, `browser_search`, `browser_back`,
  `browser_forward`, `browser_refresh`, `browser_new_tab`, `browser_close_tab`.

**Bewust NIET toegestaan** (fail-closed): definitief verwijderen
(`delete_file`, `send2trash`) en de losse power-namen `shutdown_pc`,
`restart_pc`, `sleep_pc`, `lock_pc` en `logoff_pc`. Vraagt JARVIS zoiets voor
de game-pc, dan weigert hij met een veiligheidsreden. Alles wat niet in de
lijst hierboven staat, wordt geweigerd.

**Bijwerken (Fase 21):** naast `/command` kent de agent de ondertekende route
`POST /update` (zelfde HMAC, tijdstempel en nonce). Die staat buiten de
allowlist: het is onderhoud, geen actie voor de LLM. Het brein stuurt hem
alleen na uw "ja" op een update, of als u zegt *"werk de game-pc bij"*. De
agent doet alleen een fast-forward naar GitHub (`beheer.updates`), weigert
bij lokale wijzigingen of eigen commits, en start daarna een nieuwe agent en
stopt zichzelf. Elke aanroep komt in de auditlog (`agent_update`).

---

## 12. Verwijderen

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_game_pc_agent.ps1
```

Dit verwijdert **alleen** de geplande taak. Het laat met rust:

- je `.env` (inclusief token),
- `memory/`, `logs/`, `config/`,
- alle projectbestanden,
- andere JARVIS-taken.

Wil je ook het certificaat en de sleutel weghalen (met bevestiging):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_game_pc_agent.ps1 -RemoveCertificates
```

En de firewallregel:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_game_pc_agent.ps1 -RemoveFirewallRule
```

Daarna kun je op het brein `REMOTE_CLIENT_ENABLED=0` zetten.

---

## 13. Probleemoplossing

| Melding | Oorzaak / oplossing |
|---|---|
| `Onveilige remote-configuratie; server start niet` | Token ontbreekt/te kort of certificaat/sleutel ontbreekt. Vul `.env` aan. |
| `Certificaat of sleutel is ongeldig; server start niet` | Verkeerd bestand of verlopen certificaat. Genereer opnieuw (§4). |
| Client: `niet_bereikbaar` | Verkeerd IP/host, agent uit of firewall blokkeert. |
| Client: `tls_fout` | Verkeerd certificaat in `REMOTE_CLIENT_CA_FILE` of host niet in de SAN. |
| Client: `niet_geautoriseerd` (401) | Token verschilt tussen de twee machines. |
| Client: `niet_geautoriseerd` (403) | Je IP staat niet in `REMOTE_SERVER_ALLOWED_IPS`, het is een publiek adres, of dit IP is tijdelijk geblokkeerd (lockout). |
| Client: `onzeker` / time-out | Verbinding viel weg; de actie is **niet** bevestigd. Probeer opnieuw. |
| Log: `Per-IP verbindingslimiet (…) bereikt` | Te veel gelijktijdige verbindingen vanaf één IP. IP's in `REMOTE_SERVER_ALLOWED_IPS` krijgen standaard 12 plekken (`REMOTE_MAX_CONNECTIONS_PER_ALLOWED_IP`), andere IP's 4 (`REMOTE_MAX_CONNECTIONS_PER_IP`); bij een lege allowlist geldt voor iedereen minimaal `EXECUTOR_MAX_WORKERS + 4`. |
| `cryptography is niet geïnstalleerd` | `pip install -r requirements-dev.txt`, of gebruik OpenSSL (§4). |

---

## 14. Beveiligingschecklist

- [ ] Sterk, uniek token (≥ 32 tekens) op **beide** machines.
- [ ] Certificaat met de juiste hostnaam/IP in de SAN.
- [ ] Alleen het **certificaat** gedeeld met het brein, nooit de sleutel.
- [ ] `certs/` en `.env` staan in `.gitignore` en zijn **niet** gecommit.
- [ ] `REMOTE_SERVER_ALLOWED_IPS` gevuld met het IP van de mini-pc (of leeg
      laten om alleen privé-adressen toe te staan).
- [ ] `REMOTE_SERVER_PROFILE` bewust gekozen: `basis` (standaard, veilig)
      of `werkstation` (alleen als je bestanden/UI/power echt nodig hebt).
- [ ] Firewall beperkt poort 8765 tot het IP van de mini-pc, in het
      **privé-profiel**.
- [ ] `REMOTE_CLIENT_ENABLED=0` zodra je de agent niet meer gebruikt.
