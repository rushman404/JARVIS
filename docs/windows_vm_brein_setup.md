# JARVIS-brein in een Windows-VM

Deze handleiding is een **aanvulling** op
[`windows_brein_setup.md`](windows_brein_setup.md). Uitgangspunt:

- **Brein** = `main.py` + `remote/client.py` in een **Windows-VM** op de
  laptop.
- **Agent** = `remote/server.py` op de **game-pc** (blijft ongewijzigd).
- **Verbinding** = TLS + HMAC op poort **8765**.

De Windows-commando's zelf staan in de Windows-handleiding. Hieronder staan
de stappen die **specifiek voor een VM** gelden, plus de virtuele
hardware-instellingen.

> **Let op:** dit is devariant waarbij alleen het **brein** in de VM draait.
> Wilt u ook de agent in de VM draaien, dan kan de VM de game-pc niet
> bedienen; dan test u alleen lokaal. Zeg het als u dat bedoelt.

---

## 0. Is een Windows-VM verstandig?

**Voordelen**

- Dezelfde commando's als op de game-pc.
- Geen Linux-gedoe met `portaudio`, `tflite-runtime` of `uv`.
- De VM is een veilige speelomgeving: u kunt hem terugzetten met een
  snapshot.

**Nadelen**

- Zwaarder dan een Ubuntu-VM: minimaal 8 GB RAM aanbevolen.
- Ollama draait in de VM op de **CPU**; er is geen GPU-doorgifte. Het
  antwoord is dus trager dan op de host.
- De microfoon gaat via de virtuele audio van de VM; dat werkt meestal,
  maar niet altijd even stabiel.

**VM-software**

| Software | Geschikt voor mic? | Opmerking |
|---|---|---|
| **VirtualBox 7.x** | Ja, met Audio Input | Aanbevolen; eenvoudig en gratis |
| VMware Workstation | Ja | Vaak betere audio, maar zwaarder |
| Hyper-V | Beperkt | Audio-input werkt vaak niet goed |

Gebruik bij voorkeur **VirtualBox**. Installeer op de host ook de
**Extension Pack** als u USB-apparaten (microfoon/headset) wilt doorgeven.

---

## 1. Specificaties van de VM

| Onderdeel | Minimaal | Aanbevolen |
|---|---|---|
| RAM | 4 GB | **8 GB** |
| CPU's | 2 | **4** |
| Virtuele schijf | 40 GB | **64 GB** |
| Audio | input aan | input aan |
| Netwerk | NAT | NAT |
| EFI/TPM | nodig voor Windows 11 | aan |
| Video | 128 MB | 128 MB |

- **Windows 11** heeft TPM 2.0, EFI en Secure Boot nodig. VirtualBox 7 kan
  dat.
- **Windows 10** is lichter, maar krijgt sinds oktober 2025 geen gewone
  updates meer. Gebruik bij voorkeur Windows 11.
- Gebruik een **legale Windows-ISO en licentie**.

---

## 2. VirtualBox-VM maken

1. Open VirtualBox → **Nieuw**.
2. Naam: `JARVIS-Brein`.
3. Type: **Microsoft Windows**. Versie: **Windows 11 (64-bit)** of
   **Windows 10 (64-bit)**.
4. Geheugen: **8192 MB**. CPU's: **4**.
5. Virtuele schijf: **64 GB**, dynamisch.
6. Maak de VM aan en open **Instellingen**.

Daarna:

### Systeem

- **Moederbord**: 8192 MB, 4 CPU's, **EFI inschakelen**.
- **TPM**: versie **2.0**, **Secure Boot** aan (voor Windows 11).
- **Processor**: PAE/NX aan; nested virtualization alleen als u dat nodig
  hebt (niet nodig voor Ollama op CPU).

### Audio

- **Audio inschakelen** aan.
- Host-audiostuurprogramma: **Windows**.
- Audiocontroller: **Intel HD Audio**.
- **Audio-invoer inschakelen** aan.

Deze laatste optie is essentieel voor de microfoon. Zet de VM **uit**
voordat u dit wijzigt.

### Netwerk

- Adapter 1: **NAT**. Hiermee kan de VM de game-pc bereiken.
- Bridged is alleen nodig als de game-pc de VM moet kunnen bereiken; voor
  deze opzet is dat niet nodig.

### Weergave

- Videogeheugen: **128 MB**.
- 3D-versnelling: mag aan, maar is niet nodig.

### Gedeelde map (optioneel)

- **Gedeelde mappen** → map toevoegen.
- Hostmap: bijvoorbeeld `C:\JARVIS\public` (alleen het certificaat).
- Naam: `public`, **Automatisch koppelen** aan.
- In de VM verschijnt de map onder `\\VBoxSvr\public`.

> Deel nooit de map `certs/` van de game-pc: daar staat ook
> `agent-key.pem` in.

---

## 3. Windows installeren

1. Koppel de Windows-ISO aan het optische station.
2. Start de VM en doorloop de installatie.
3. Kies **Ik heb geen productcode** als u die nog niet hebt; u kunt later
   activeren.
4. Kies **Aangepaste installatie** en gebruik de hele virtuele schijf.
5. Na de installatie: **Guest Additions** installeren:
   - Menu **Apparaten → Guest Additions-CD invoegen**.
   - In de VM: open de CD en start `VBoxWindowsAdditions.exe`.
   - Herstart de VM.
6. Zet de tijdzone goed en synchroniseer de tijd:
   ```powershell
   w32tm /resync
   ```
   Een scheve klok geeft later **401 verouderde tijd** bij de agent.

> Windows 11 weigert de installatie ("This PC can't run Windows 11")?
> Controleer EFI, TPM 2.0, Secure Boot, 4 GB RAM, 2 CPU's en 64 GB schijf.

---

## 4. Basissoftware in de VM

Installeer in deze volgorde:

1. **Python 3.11** van [python.org](https://www.python.org/downloads/).
   Vink **Add python.exe to PATH** aan.
2. **Git** (optioneel, voor `git clone`).
3. **Ollama** voor Windows:
   ```powershell
   winget install Ollama.Ollama
   ```
   Geen `winget`? Download de installer van
   [ollama.com](https://ollama.com).
4. **7-Zip** (optioneel).

Controleer in een nieuwe PowerShell:

```powershell
py -3.11 --version
git --version
ollama --version
```

---

## 5. JARVIS in de VM

### 5.1 Repo

```powershell
cd C:\
git clone https://github.com/rushman404/JARVIS.git C:\JARVIS
cd C:\JARVIS
```

Geen Git? Download de ZIP van GitHub en pak hem uit naar `C:\JARVIS`.

> De lokale fixes op de game-pc (`actions/media.py`,
> `scripts/test_remote_lan_manual.py`) staan mogelijk nog niet op GitHub.
> Voor **remote** volume maakt dat niet uit: die actie draait op de agent.
> Gebruik voor de test `python -m scripts.test_remote_lan_manual`.

### 5.2 Python-omgeving

```powershell
cd C:\JARVIS
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Blokkeert PowerShell het activeren?

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

Aan het begin van de regel moet `(.venv)` staan.

### 5.3 Ollama

```powershell
ollama pull qwen2.5:3b
ollama list
```

Ollama start normaal automatisch. Draait hij niet? Start **Ollama** via het
Startmenu of voer `ollama serve` uit in een apart venster.

> In een VM zonder GPU draait het model op de CPU. Het werkt, maar het
> eerste antwoord kan 10-30 seconden duren. Met 8 GB RAM is
> `qwen2.5:3b` de juiste keuze; grotere modellen passen meestal niet.

### 5.4 Wake word en Piper

```powershell
python -c "from openwakeword.utils import download_models; download_models()"
python scripts\download_piper_voice.py nl_NL-pim-medium
```

### 5.5 `.env`

```powershell
notepad C:\JARVIS\.env
```

Vul in:

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

Let op:

- `REMOTE_CLIENT_HOST` = het **LAN-IP van de game-pc**, niet `127.0.0.1`
  en niet het VirtualBox-host-only adres.
- Het token moet **exact** gelijk zijn aan `REMOTE_SERVER_TOKEN` op de
  game-pc.
- `PC_TARGET=game-pc`, anders voert JARVIS de opdrachten lokaal in de VM
  uit.

---

## 6. Certificaat naar de VM

Kopieer **alleen** `agent-cert.pem`. Nooit `agent-key.pem`.

### Optie A — tijdelijke HTTP-server op de game-pc

Op de game-pc:

```powershell
New-Item -ItemType Directory -Force C:\JARVIS\public
Copy-Item C:\JARVIS\certs\agent-cert.pem C:\JARVIS\public\
cd C:\JARVIS\public
python -m http.server 8000
```

In de VM:

```powershell
mkdir C:\JARVIS\certs -Force
Invoke-WebRequest http://192.168.2.41:8000/agent-cert.pem `
  -OutFile C:\JARVIS\certs\agent-cert.pem
```

Daarna op de game-pc: `Ctrl+C` en `C:\JARVIS\public` opruimen.

### Optie B — gedeelde map

- Zet op de host een map `C:\JARVIS\public` met alleen het certificaat.
- Koppel die als gedeelde map `public`.
- Kopieer in de VM vanuit `\\VBoxSvr\public` naar
  `C:\JARVIS\certs\agent-cert.pem`.

Controleer:

```powershell
Get-Content C:\JARVIS\certs\agent-cert.pem -TotalCount 1
```

Verwacht: `-----BEGIN CERTIFICATE-----`.

---

## 7. Netwerk testen

Op de game-pc moet de agent draaien:

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -m remote.server
```

In de VM:

```powershell
Test-NetConnection 192.168.2.41 -Port 8765
```

Verwacht: `TcpTestSucceeded : True`.

Daarna:

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -m scripts.test_remote_lan_manual
```

Verwacht: **6 van 6 geslaagd**.

- **NAT**: de game-pc ziet het verkeer van het host-IP. Dat is een
  privéadres, dus de standaard allowlist staat het toe.
- **Bridged**: de VM krijgt een eigen `192.168.2.x`-adres. Ook goed.
- **Firewall**: staat de game-pc op **Openbaar**, dan wordt poort 8765
  geblokkeerd. Zet het netwerk op **Privé** of voeg de firewallregel toe.

---

## 8. Microfoon in de VM

1. Zet de VM **uit**.
2. VirtualBox → Instellingen → **Audio**:
   - Audio aan.
   - **Audio-invoer inschakelen** aan.
   - Controller: **Intel HD Audio**.
3. Start de VM.
4. Windows: **Instellingen → Privacy en beveiliging → Microfoon**:
   - microfoontoegang aan;
   - desktop-apps toegang geven.
5. **Instellingen → Systeem → Geluid → Invoer**: kies de microfoon en
   test of de balk beweegt.

Apparaten bekijken:

```powershell
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Is de standaard niet goed, zet dan in `.env`:

```ini
MIC_DEVICE=2
```

Test:

```powershell
python scripts\test_mic_manual.py
start scripts\mic_manual_opname.wav
```

**Geen microfoon in de VM?**

- USB-microfoon of headset: installeer de **Extension Pack** op de host,
  zet de VM uit, kies **USB 3.0**, start de VM en koppel het apparaat via
  **Apparaten → USB**.
- Gebruikt u SteelSeries Sonar of een andere virtuele audio-app? Kies in de
  VM de echte microfoon, niet de virtuele uitgang.
- Werkt VirtualBox-audio niet? Probeer VMware Workstation of een USB-mic.

---

## 9. Starten en testen

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python main.py
```

Zeg **"Hey Jarvis"**, wacht op de piep en test:

- "Wat kun je doen?" → LLM.
- "Hoe laat is het?" → lokale actie.
- "Zet het volume op 30" → game-pc.
- "Maak een screenshot" → game-pc.
- "Open Spotify" → game-pc.
- "Sluit Spotify" → game-pc.
- "Stop" tijdens een antwoord → barge-in.

Controle op de game-pc:

```powershell
Get-Content C:\JARVIS\logs\audit.jsonl -Tail 10
```

---

## 10. VM-valkuilen

| Probleem | Oorzaak | Oplossing |
|---|---|---|
| Windows 11-installatie weigert | Geen TPM/EFI/Secure Boot | TPM 2.0, EFI en Secure Boot aan; 4 GB+ RAM, 2+ CPU's, 64 GB |
| VM is erg traag | Te weinig RAM/CPU | 8 GB RAM, 4 CPU's; VM niet tegelijk met zware games |
| Ollama antwoordt traag | CPU-only in de VM | Normaal; gebruik `qwen2.5:3b`, houd de VM licht |
| Ollama connection refused | Ollama draait niet | Start Ollama; `ollama list` |
| Geen microfoon | Audio-invoer staat uit | VM uit, Audio Input aan; Windows-privacy |
| Mic klinkt slecht | Virtuele audio | USB-mic doorgeven of VMware proberen |
| 401 verouderde tijd | VM-klok loopt achter | `w32tm /resync`; Guest Additions; tijdsynchronisatie |
| Agent niet bereikbaar | NAT/firewall/verkeerd IP | `Test-NetConnection`; firewall Privé; juist LAN-IP |
| `certificate verify failed` | Verkeerd cert of IP | `agent-cert.pem` opnieuw kopiëren; cert met juiste `--ip` |
| `PC_TARGET` vergeten | Opdrachten lokaal in de VM | `PC_TARGET=game-pc` in `.env` |
| Token verschilt | Kopieerfout | Zelfde token aan beide kanten |
| `python` opent Microsoft Store | App Execution Alias | `py -3.11` gebruiken |
| `Activate.ps1` geblokkeerd | Execution policy | `Set-ExecutionPolicy -Scope Process Bypass` |
| `ModuleNotFoundError` | Venv niet actief | `(.venv)` controleren |
| `win32api` ontbreekt | `pywin32` niet geregistreerd | `pip install pywin32` en `pywin32_postinstall.py -install` |
| Volume time-out | COM-deadlock op de agent | Fix op de game-pc; agent herstarten |
| Token in git | `token-voor-vm.txt` niet genegeerd | Verwijderen; nooit committen |

---

## 11. Checklist

### VM

- [ ] Windows 11 (of 10) geïnstalleerd
- [ ] 8 GB RAM, 4 CPU's, 64 GB schijf
- [ ] EFI/TPM/Secure Boot (Windows 11)
- [ ] Guest Additions geïnstalleerd
- [ ] Audio + **Audio Input** aan
- [ ] NAT-netwerk
- [ ] Tijd gesynchroniseerd

### Brein

- [ ] Python 3.11 + venv
- [ ] `pip install -r requirements.txt`
- [ ] Ollama + `qwen2.5:3b`
- [ ] openWakeWord-modellen
- [ ] Piper-stem
- [ ] `certs\agent-cert.pem`
- [ ] `.env` met clientregels en `PC_TARGET=game-pc`
- [ ] `Test-NetConnection` → `True`
- [ ] `python -m scripts.test_remote_lan_manual` → 6/6

### Spraak

- [ ] Microfoon zichtbaar in Windows
- [ ] `MIC_DEVICE` indien nodig
- [ ] `test_mic_manual.py` werkt
- [ ] `main.py` start
- [ ] "Hey Jarvis" wordt herkend
- [ ] LLM antwoordt
- [ ] Remote-acties werken

---

## 12. Snelle volgorde

```powershell
# 1. VM: Windows + Guest Additions + audio input
# 2. Python 3.11 en Git installeren
# 3. Repo
cd C:\
git clone https://github.com/rushman404/JARVIS.git C:\JARVIS
cd C:\JARVIS

# 4. Venv
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 5. Ollama
winget install Ollama.Ollama
ollama pull qwen2.5:3b

# 6. Wake word + stem
python -c "from openwakeword.utils import download_models; download_models()"
python scripts\download_piper_voice.py nl_NL-pim-medium

# 7. Certificaat + .env
#    (zie §6 en §5.5)

# 8. Testen
python -m scripts.test_remote_lan_manual
python scripts\test_mic_manual.py
python main.py
```
