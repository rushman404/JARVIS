# JARVIS-brein op Windows + agent op de game-pc

Dit is de **Windows-tegenhanger** van
[`ubuntu_vm_brein_setup.md`](ubuntu_vm_brein_setup.md). De opzet is hetzelfde:

- **Brein** = `main.py` + `remote/client.py` op een **Windows-pc**.
- **Agent** = `remote/server.py` op de **game-pc**.
- **Verbinding** = TLS + HMAC op poort **8765**.

> Deze handleiding gaat uit van **native Windows**, niet van WSL. Gebruik WSL
> alleen als u zeker weet dat audio en `pycaw` daar werken; dat is meestal
> niet zo.
>
> **Windows-VM:** zie [`windows_vm_brein_setup.md`](windows_vm_brein_setup.md).

---

## 0. Kies uw opstelling

| Opstelling | Brein | Agent | `PC_TARGET` |
|---|---|---|---|
| **A. Twee pc's** | Windows-laptop of tweede pc | game-pc | `game-pc` |
| **B. Eén pc** | de game-pc zelf | niet nodig | `local` |

- **A** is de opstelling met een apart brein: de laptop luistert, de game-pc
  voert uit.
- **B** is de eenvoudigste test: alles draait op de game-pc. U heeft dan geen
  agent, token of certificaat nodig. `main.py` bestuurt de pc lokaal.

In de voorbeelden:

- Game-pc: hostnaam `RushilPC`, LAN-IP `192.168.2.41`.
- Brein: `C:\JARVIS` op de Windows-laptop.

Vervang deze waarden door uw eigen namen en adressen.

---

## 1. Deel A — Game-pc als agent (alleen bij opstelling A)

Als u opstelling B gebruikt, sla dit deel over en ga naar **§2**.

De volledige uitleg staat in [`remote_agent.md`](remote_agent.md). De korte
versie:

### A1. Repo en Python

Open **PowerShell in `C:\JARVIS`**:

```powershell
cd C:\JARVIS
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements-dev.txt` is nodig voor `cryptography`, dat het
certificaatscript gebruikt.

> Blokkeert PowerShell het activeren? Gebruik eenmalig:
> `Set-ExecutionPolicy -Scope Process Bypass`

### A2. Token maken

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Bewaar het token. Hetzelfde token komt in de `.env` van de game-pc én van
het brein. Minimaal 16 tekens; gebruik de volledige 43 tekens.

### A3. Certificaat maken

```powershell
python scripts\gen_remote_cert.py --host RushilPC --ip 192.168.2.41
```

Resultaat:

- `certs\agent-cert.pem` — openbaar, mag naar het brein.
- `certs\agent-key.pem` — privésleutel, blijft op de game-pc.

Het IP in het certificaat moet het adres zijn dat het brein gebruikt om te
verbinden. Ander IP of andere hostnaam? Genereer opnieuw met de juiste
`--host` en `--ip`.

### A4. `.env` op de game-pc

```powershell
notepad C:\JARVIS\.env
```

Vul in:

```ini
REMOTE_SERVER_ENABLED=1
REMOTE_SERVER_HOST=0.0.0.0
REMOTE_SERVER_PORT=8765
REMOTE_SERVER_TOKEN=<het-token-uit-A2>
REMOTE_SERVER_CERT_FILE=certs/agent-cert.pem
REMOTE_SERVER_KEY_FILE=certs/agent-key.pem
REMOTE_SERVER_ALLOWED_IPS=
```

Controleer:

```powershell
python -c "import config; print(config.remote_server_security_errors())"
```

Verwacht: `[]`.

### A5. Firewall

Als administrator:

```powershell
New-NetFirewallRule -DisplayName "JARVIS Game-PC Agent" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private
```

Controleer het netwerkprofiel:

```powershell
Get-NetConnectionProfile
```

Staat het op **Openbaar**, zet het op **Privé**. Maak poort 8765 nooit open
naar internet.

### A6. Agent starten

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -m remote.server
```

Laat het venster open. Na elke codewijziging op de game-pc: **opnieuw
starten**.

---

## 2. Deel B — Windows-brein

### B1. Python installeren

Download **Python 3.11** van [python.org](https://www.python.org/downloads/)
en kies tijdens de installatie:

- **Add python.exe to PATH**
- **Install launcher for all users** (aanbevolen)

Controleer in een **nieuwe** PowerShell:

```powershell
py -3.11 --version
python --version
```

- `py -3.11` gebruikt de Python-launcher.
- Opent `python` de Microsoft Store? Gebruik `py -3.11`, of zet de
  App Execution Alias voor `python.exe` uit.

### B2. Repo en virtuele omgeving

```powershell
cd C:\
git clone https://github.com/rushman404/JARVIS.git C:\JARVIS
cd C:\JARVIS
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Aan het begin van de regel staat nu `(.venv)`. Zo niet, dan is de venv niet
actief.

> Heeft u de repo al in `C:\JARVIS`? Sla `git clone` over en ga direct naar
> `cd C:\JARVIS`.

### B3. Ollama

Installeer Ollama voor Windows:

```powershell
winget install Ollama.Ollama
```

Geen `winget`? Download de installer van [ollama.com](https://ollama.com).

Controleer:

```powershell
ollama --version
ollama pull qwen2.5:3b
ollama list
```

Ollama start normaal automatisch en luistert op `127.0.0.1:11434`. Draait
hij niet? Start **Ollama** via het Startmenu, of voer in een apart venster
`ollama serve` uit.

### B4. Wake word

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -c "from openwakeword.utils import download_models; download_models()"
```

Het wake word is **"Hey Jarvis"**.

### B5. Piper-stem

```powershell
python scripts\download_piper_voice.py nl_NL-pim-medium
```

De stem komt in `voice\models`. Werkt Piper niet, zet dan in `.env`:

```ini
PIPER_ENABLED=0
```

JARVIS gebruikt dan `pyttsx3` met de Windows-stem. Voor een Nederlandse
SAPI-stem: **Instellingen → Tijd en taal → Spraak → Stemmen toevoegen**.

### B6. `.env` op het brein

Open:

```powershell
notepad C:\JARVIS\.env
```

**Opstelling A (twee pc's):**

```ini
REMOTE_CLIENT_ENABLED=1
REMOTE_CLIENT_HOST=192.168.2.41
REMOTE_CLIENT_PORT=8765
REMOTE_CLIENT_TOKEN=<hetzelfde-token-als-de-game-pc>
REMOTE_CLIENT_CA_FILE=certs/agent-cert.pem
REMOTE_CLIENT_TIMEOUT=10
PC_TARGET=game-pc
AI_MODEL=qwen2.5:3b
OLLAMA_HOST=127.0.0.1:11434
```

**Opstelling B (alles op één pc):**

```ini
PC_TARGET=local
AI_MODEL=qwen2.5:3b
OLLAMA_HOST=127.0.0.1:11434
```

Bij B heeft u geen `REMOTE_CLIENT_*` nodig en start u geen agent.

### B7. Certificaat naar het brein (alleen A)

Kopieer **alleen** `agent-cert.pem`. Nooit `agent-key.pem`.

**Veilige manier:** maak op de game-pc een tijdelijke map met alleen het
certificaat:

```powershell
New-Item -ItemType Directory -Force C:\JARVIS\public
Copy-Item C:\JARVIS\certs\agent-cert.pem C:\JARVIS\public\
cd C:\JARVIS\public
python -m http.server 8000
```

Op het brein:

```powershell
mkdir C:\JARVIS\certs -Force
Invoke-WebRequest http://192.168.2.41:8000/agent-cert.pem `
  -OutFile C:\JARVIS\certs\agent-cert.pem
```

Daarna op de game-pc: `Ctrl+C` en de tijdelijke map opruimen.

> **Let op:** serve nooit de hele map `certs/`. Daar staat ook
> `agent-key.pem` in; iedereen op het netwerk kan die dan downloaden.
> Alternatief: USB-stick of `scp`.

### B8. Verbinding testen (alleen A)

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -m scripts.test_remote_lan_manual
```

Verwacht: **6 van 6 geslaagd**. Stap 5 zet het volume van de game-pc op 20%;
stap 6 maakt een screenshot.

> Gebruik `python -m scripts.test_remote_lan_manual`, niet
> `python scripts\test_remote_lan_manual.py`. Anders kan Python `config`
> niet vinden.

---

## 3. Deel C — Microfoon op Windows

### C1. Toegang tot de microfoon

**Instellingen → Privacy en beveiliging → Microfoon**:

- **Microfoontoegang** aan.
- **Apps toestaan toegang te krijgen tot uw microfoon** aan.
- **Desktop-apps toegang geven** aan.

### C2. Apparaat kiezen

**Instellingen → Systeem → Geluid → Invoer**:

- Kies de juiste microfoon.
- Praat; de balk moet bewegen.
- Zet het volume op een redelijk niveau.

Gebruikt u een headset of een virtueel audio-apparaat (SteelSeries Sonar,
HyperX, fifine)? Kies dan bewust de **microfoon** en niet de virtuele
uitgang.

### C3. Apparaten bekijken

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Zoek een regel met `in: 1` of hoger. Is de standaard niet goed, zet dan in
`.env`:

```ini
MIC_DEVICE=2
```

Gebruik het nummer of een deel van de naam. Leeg laten = standaardapparaat.

### C4. Microfoontest

```powershell
python scripts\test_mic_manual.py
```

Zeg **"Hey Jarvis"**, wacht op de piep en zeg een zin. Daarna:

```powershell
start scripts\mic_manual_opname.wav
```

Beluister de opname. Hoort u niets, controleer dan C1 en C2.

---

## 4. Deel D — JARVIS starten en testen

### D1. Starten

Bij opstelling A: laat de agent op de game-pc draaien. Start dan op het
brein:

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python main.py
```

Bij opstelling B: start alleen `main.py` op de game-pc; er is geen agent
nodig.

Wacht tot "JARVIS gestart" verschijnt. Zeg **"Hey Jarvis"**, wacht op de
piep en geef een commando.

### D2. Testlijst

| Test | Commando | Verwacht |
|---|---|---|
| LLM | "Wat kun je doen?" | Nederlands antwoord |
| Lokaal | "Hoe laat is het?" | tijd |
| Remote volume (A) | "Zet het volume op 30" | volume game-pc |
| Remote screenshot (A) | "Maak een screenshot" | bestand op game-pc |
| Remote programma (A) | "Open Spotify" | Spotify start |
| Remote sluiten (A) | "Sluit Spotify" | Spotify stopt |
| Barge-in | "stop" tijdens antwoord | JARVIS stopt |

Controle op de game-pc:

```powershell
Get-Content C:\JARVIS\logs\audit.jsonl -Tail 10
```

### D3. Stoppen

- JARVIS: `Ctrl+C`.
- Agent: `Ctrl+C` in het agent-venster.

---

## 5. Wat is anders dan de Ubuntu-versie?

| Onderdeel | Ubuntu-VM | Windows |
|---|---|---|
| Python 3.11 | via `uv` | via python.org / `py -3.11` |
| Audio | `portaudio19-dev` | zit in de `sounddevice`-wheel |
| `tflite-runtime` | nodig voor `openwakeword` | niet nodig op Windows |
| TTS-fallback | `espeak-ng` | SAPI5 via `pyttsx3` |
| Firewall | `ufw`/nftables | Windows Defender Firewall |
| Schelp | bash | PowerShell |
| Agent | `python -m remote.server` | `python -m remote.server` |

De rest van de architectuur, het token, het certificaat en de remote-acties
zijn identiek.

---

## 6. Windows-valkuilen

| Fout / melding | Oorzaak | Oplossing |
|---|---|---|
| `python` opent de Microsoft Store | App Execution Alias | Gebruik `py -3.11`, of zet de alias uit |
| `Activate.ps1 cannot be loaded` | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process Bypass` |
| `pip` is not recognized | `pip` niet op PATH | `python -m pip install ...` |
| `ModuleNotFoundError` | Venv niet actief | `.\.venv\Scripts\Activate.ps1`; controleer `(.venv)` |
| `No module named 'win32api'` | `pywin32` niet goed geïnstalleerd | `pip install pywin32`; daarna `python .\.venv\Scripts\pywin32_postinstall.py -install` |
| `pycaw`/`comtypes`-fout | Verkeerde omgeving of WSL | Draai native Windows, in de venv |
| `Ollama connection refused` | Ollama draait niet | Start Ollama; `ollama list` |
| `qwen2.5:3b` ontbreekt | Model niet opgehaald | `ollama pull qwen2.5:3b` |
| Geen microfoon | Privacy-instelling of verkeerd apparaat | C1/C2; `sounddevice.query_devices()`; `MIC_DEVICE` |
| Geen wake word | Modellen niet gedownload of mic te zacht | `download_models()`; mic-volume |
| Piper zegt niets | `piper-tts` of stem ontbreekt | `PIPER_ENABLED=0`, of stem downloaden |
| Barge-in werkt niet in een game | Game draait als administrator | Start JARVIS ook als administrator |
| `401` bij health | Token verschilt of klok loopt achter | Zelfde token; tijd synchroniseren |
| `certificate verify failed` | Verkeerd CA-bestand of verkeerd IP | `agent-cert.pem` kopiëren; cert met juiste `--ip` |
| Agent niet bereikbaar | Agent uit, firewall, verkeerd IP | Agent starten; firewallregel; `Test-NetConnection` |
| `De game-pc reageerde niet op tijd` | Time-out te laag of actie hangt | `REMOTE_CLIENT_TIMEOUT=10`; agent herstarten |
| Volume time-out | Deadlock in `actions/media.py` | Fix toepassen; agent herstarten |
| `PC_TARGET=local` | Commando's worden lokaal uitgevoerd | `PC_TARGET=game-pc` bij opstelling A |
| Token in git | `token-voor-vm.txt` niet genegeerd | Verwijderen; nooit committen |
| `certs/` via HTTP | Privésleutel wordt mee geserveerd | Alleen `agent-cert.pem` serveren |
| Lange paden/OneDrive | Sync of padlimiet | Gebruik `C:\JARVIS` |

### 6.1 Volume-deadlock

Dezelfde fout als in de Ubuntu-handleiding: `_get_volume_interface()` in
`actions/media.py` mag **geen** nieuwe `run_on_com_thread` aanroepen, want de
functie draait al binnen de COM-thread. Anders wacht de thread op zichzelf en
volgt na 10 seconden een time-out.

Controleer op de game-pc:

```powershell
python -c "from actions.media import get_volume, set_volume; print('huidig:', get_volume()); print(set_volume(20)); print('nu:', get_volume())"
```

Verwacht: een getal, `Volume staat nu op 20%.`, en daarna `20`.

---

## 7. Checklist

### Opstelling A — game-pc (agent)

- [ ] Repo in `C:\JARVIS`
- [ ] Python 3.11+ en venv
- [ ] `pip install -r requirements.txt -r requirements-dev.txt`
- [ ] Token gemaakt
- [ ] Certificaat met juiste host/IP
- [ ] `.env` met serverregels en hetzelfde token
- [ ] `config.remote_server_security_errors()` geeft `[]`
- [ ] Firewallregel voor TCP 8765 (Privé)
- [ ] Agent gestart

### Opstelling A — brein

- [ ] Windows-pc met Python 3.11
- [ ] Repo in `C:\JARVIS`
- [ ] Venv en `pip install -r requirements.txt`
- [ ] Ollama + `qwen2.5:3b`
- [ ] openWakeWord-modellen
- [ ] Piper-stem
- [ ] `certs\agent-cert.pem`
- [ ] `.env` met clientregels, `PC_TARGET=game-pc`
- [ ] `python -m scripts.test_remote_lan_manual` → 6/6

### Spraak

- [ ] Microfoontoegang in Windows
- [ ] Juiste invoerapparaat
- [ ] `MIC_DEVICE` indien nodig
- [ ] `python scripts\test_mic_manual.py` werkt
- [ ] `python main.py` start
- [ ] "Hey Jarvis" wordt herkend
- [ ] LLM antwoordt
- [ ] Remote-acties werken (A)
- [ ] Barge-in werkt (of bewust uitgezet)

---

## 8. Beveiliging

- **Token** = wachtwoord. Niet delen, niet committen.
- **`agent-key.pem`** verlaat de game-pc nooit.
- **`agent-cert.pem`** mag naar het brein.
- **`.env`** en **`certs/`** staan in `.gitignore`.
- **Poort 8765** alleen op het privénetwerk; geen port-forwarding.
- **`REMOTE_SERVER_ALLOWED_IPS`** leeg = alleen privéadressen.
- **Profiel `basis`** is de veilige standaard.
- **Audit-log** `C:\JARVIS\logs\audit.jsonl` toont wat er is uitgevoerd.

---

## 9. Onderhoud

- Na een codewijziging op de game-pc: **agent herstarten**.
- Na een `.env`-wijziging: **JARVIS opnieuw starten**.
- Na een IP-wijziging: **certificaat opnieuw genereren** of het nieuwe IP
  toevoegen, en de client-`.env` bijwerken.
- Controleer af en toe:

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -m scripts.test_remote_lan_manual
```

- Bij problemen: `ollama list` en
  `Get-Content C:\JARVIS\logs\audit.jsonl -Tail 10`.
