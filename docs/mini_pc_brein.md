# 🖥️ Het brein op de mini-pc (Fase 19) — handleiding

In Fase 19 verhuist het brein (JARVIS, de AI, het geheugen en het dashboard)
van de laptop naar een eigen Windows-mini-pc die 24/7 aan staat. De game-pc
blijft de agent die op afstand wordt bediend.

Deze handleiding groeit per mijlpaal mee. Klaar: **M1 — installatie en
migratie**. De handmatige basis staat in
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

## 3. Testlijst M1 (op de mini-pc)

- [ ] `install_brein.ps1 -DryRun` loopt zonder fouten door
- [ ] Na de installatie: `brein_check.py` zonder ❌
- [ ] JARVIS kent na de import uw geheugen ("wat weet je over mij?")
- [ ] De iPad verbindt zonder opnieuw te koppelen (na `make_dashboard_cert.py --force`)
- [ ] De game-pc reageert ("zet Spotify op 30 procent")
