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

Het installatiescript maakt een taak die de agent **na inloggen** start:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_game_pc_agent.ps1
```

- Herhaalbaar: dezelfde taaknaam (`JARVIS Game-PC Agent`) wordt **bijgewerkt**
  in plaats van gedupliceerd.
- Het script controleert **eerst** de beveiligingsconfiguratie (token +
  certificaat) en breekt af als die niet compleet is.
- Er staan **geen geheimen** in de taak: de agent leest ze uit `.env`.
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

**Handmatig starten** (in de projectmap op de game-pc):

```powershell
python -m remote.server
```

**Via de geplande taak:**

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

---

## 11. Wat mag er op afstand?

Alleen de acties uit de allowlist (`remote/allowlist.py`) mogen draaien —
nooit vrije shell- of PowerShell-commando's. De lijst telt **57 acties**,
gegroepeerd op risico. De risicoklasse bepaalt of het brein eerst om
goedkeuring vraagt (hoog/medium) of de actie direct uitvoert (laag).

### Serverprofiel: basis of werkstation

De server heeft twee profielen (`REMOTE_SERVER_PROFILE`):

- **basis** (standaard) — alleen programma's en games starten/sluiten,
  vensterbediening, media/volume, audio uitlezen, systeemstatus en
  screenshot. Bestanden wijzigen, UI-automatisering, power en browser
  zijn hier uitgesloten. Dit is de veilige standaard.
- **werkstation** — alles: ook bestanden lezen/wijzigen, scherm
  bedienen (klikken/typen), power en browser. Alleen als je dit
  expliciet aanzet.

Zet je `REMOTE_SERVER_PROFILE=werkstation`, dan gelden de risicoklassen
hieronder volledig. In basis-profiel wordt alles buiten de basislijst
geweigerd ongeacht de risicoklasse.

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
procesnamen, weergavenamen) en blokkeert typen/klikken in vensters van
onbekende processen (fail-closed). Beschouw het als een extra laag,
niet als de enige beveiliging.

> ⚠️ **Wat er gebeurt als je token lekt.** Wie het token én een geldig
> privé-adres heeft, kan **alles in het actieve profiel** op de game-pc
> doen. In basis: games sluiten, apps starten, media bedienen, status
> uitlezen, screenshot maken. In werkstation: ook bestanden kopiëren,
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
- **Audio per app:** `audio_set_session_volume`, `audio_set_session_mute`,
  `audio_toggle_session_mute`, `audio_set_default_output`.

#### Laag risico (direct uitvoeren, geen vraag)

- **Programma's/games:** `open_program`, `close_program`, `program_status`,
  `find_program_location`.
- **Vensters:** `minimize_window`, `maximize_window`, `restore_window`.
- **Systeem/status:** `system_info`, `pc_status`, `screenshot`.
- **Media/volume:** `media_play_pause`, `media_next`, `media_previous`,
  `media_stop`, `media_mute`, `volume_up`, `volume_down`, `set_volume`.
- **Audio uitlezen:** `audio_list_sessions`, `audio_get_session_volume`,
  `audio_list_outputs`, `audio_get_default_output`.
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
