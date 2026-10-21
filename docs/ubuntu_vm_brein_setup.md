# JARVIS-brein in een Ubuntu-VM + agent op de game-pc

Deze handleiding zet JARVIS vanaf nul op, in de opstelling die we hebben getest:

- **Brein** = `main.py` + `remote/client.py` in een **Ubuntu-VM**.
- **Agent** = `remote/server.py` op de **Windows game-pc**.
- **Verbinding** = TLS + HMAC op poort **8765**.

> Deze handleiding is geschreven na een eerste installatie waarbij een aantal
> dingen misging. De fouten en oplossingen staan in **§9**. Lees die sectie
> vooral als iets niet werkt.
>
> **Windows-variant:** zie [`windows_brein_setup.md`](windows_brein_setup.md).

---

## 0. Uitgangspunten

| Onderdeel | Machine | Rol |
|---|---|---|
| Brein | Ubuntu-VM | `main.py`, microfoon, LLM, `remote/client.py` |
| Agent | Windows game-pc | `remote/server.py`, voert pc-acties uit |
| Netwerk | zelfde LAN | VM moet de game-pc op poort 8765 kunnen bereiken |

Belangrijk:

- Op de **game-pc** draait alleen de **agent**, niet `main.py`.
- Op de **VM** draait het **brein**; daar zit de microfoon.
- De twee machines hebben **hetzelfde token** en de VM heeft **het servercertificaat**.
- De **privésleutel** (`agent-key.pem`) blijft altijd op de game-pc.
- `.env` en `certs/` staan in `.gitignore`; commit ze nooit.

In de voorbeelden gebruiken we:

- Game-pc: hostnaam `RushilPC`, LAN-IP `192.168.2.41`.
- VM: Ubuntu 24.04, gebruiker `Rushil`, project `/home/Rushil/JARVIS`.

Vervang die waarden door uw eigen namen en adressen.

---

## 1. Overzicht van de stappen

1. Game-pc: repo, Python, token, certificaat, `.env`, firewall, agent starten.
2. VM: Ubuntu, Python 3.11, dependencies, Ollama, wake word, Piper.
3. Certificaat naar de VM, client-`.env`, verbinding testen.
4. Microfoon in de VM.
5. JARVIS starten en alles testen.

---

## 2. Deel A — Game-pc (agent)

### A1. Repo en Python

Open PowerShell in de projectmap:

```powershell
cd C:\JARVIS
python --version
```

Python **3.11 of nieuwer** is nodig. Maak een virtuele omgeving:

```powershell
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

Het token is het **gedeelde wachtwoord** tussen de game-pc en de VM. Maak het
één keer aan:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Bewaar het veilig. Het moet **minimaal 16 tekens** zijn; gebruik bij voorkeur
de volledige 43 tekens. Hetzelfde token komt straks in:

- `C:\JARVIS\.env` → `REMOTE_SERVER_TOKEN`
- `/home/Rushil/JARVIS/.env` → `REMOTE_CLIENT_TOKEN`

Zet het **niet** in de repository en niet in een bestand dat u commit.

### A3. Certificaat maken

```powershell
cd C:\JARVIS
python scripts\gen_remote_cert.py --host RushilPC --ip 192.168.2.41
```

Resultaat:

- `certs\agent-cert.pem` — **openbaar** certificaat, mag naar de VM.
- `certs\agent-key.pem` — **privésleutel**, blijft op de game-pc.
- Een SHA-256-vingerafdruk, handig om te controleren.

Het IP-adres in het certificaat moet het adres zijn dat de VM gebruikt om te
verbinden. Gebruikt u een andere hostnaam of een ander IP, genereer dan
opnieuw met de juiste `--host` en `--ip`.

### A4. `.env` op de game-pc

Maak of open `C:\JARVIS\.env`:

```powershell
notepad C:\JARVIS\.env
```

Vul in (of vervang alleen de remote-regels):

```ini
REMOTE_SERVER_ENABLED=1
REMOTE_SERVER_HOST=0.0.0.0
REMOTE_SERVER_PORT=8765
REMOTE_SERVER_TOKEN=<het-token-uit-stap-A2>
REMOTE_SERVER_CERT_FILE=certs/agent-cert.pem
REMOTE_SERVER_KEY_FILE=certs/agent-key.pem
REMOTE_SERVER_ALLOWED_IPS=
```

`REMOTE_SERVER_ALLOWED_IPS=` leeg laten betekent: alleen privéadressen mogen
verbinden. Vul pas een lijst in als u zeker weet welk bron-IP de game-pc ziet.
Bij VirtualBox-NAT ziet de game-pc het LAN-IP van de host, niet het interne
VM-adres.

Controleer daarna:

```powershell
python -c "import config; print(config.remote_server_security_errors())"
```

Verwacht: een lege lijst `[]`. Krijgt u fouten, dan ontbreekt het token of
certificaat, of staat een pad verkeerd.

### A5. Firewall

Voer uit in een **administrator**-PowerShell:

```powershell
New-NetFirewallRule -DisplayName "JARVIS Game-PC Agent" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private
```

Controleer dat het netwerkprofiel **Privé** is:

```powershell
Get-NetConnectionProfile
```

Staat het op **Openbaar**, zet het dan op Privé. Maak poort 8765 nooit open
naar internet.

### A6. Agent starten

```powershell
cd C:\JARVIS
.\.venv\Scripts\Activate.ps1
python -m remote.server
```

Laat dit venster open. De agent moet blijven draaien zolang u hem wilt
gebruiken.

> Na elke codewijziging op de game-pc: **agent opnieuw starten** (Ctrl+C en
> opnieuw `python -m remote.server`). Anders draait de oude code.

### A7. Controle

- Draait het venster nog?
- Is `192.168.2.41` het juiste LAN-IP? (`ipconfig`)
- Is poort 8765 open? Vanaf de VM:

```bash
nc -vz 192.168.2.41 8765
```

Of zonder `nc`:

```bash
python3 -c "import socket; s=socket.create_connection(('192.168.2.41',8765),3); print('open'); s.close()"
```

---

## 3. Deel B — Ubuntu-VM (brein)

### B1. VM en netwerk

VirtualBox, VMware of Hyper-V is allemaal bruikbaar. De VM moet de game-pc
kunnen bereiken. **NAT** werkt voor uitgaand verkeer; **Bridged** geeft de VM
een eigen LAN-IP.

Controleer in de VM:

```bash
hostname -I
```

Gebruik het adres van de actieve netwerkkaart. Negeer:

- `127.0.0.1` (loopback)
- `inet6`-adressen
- `docker0`
- `192.168.56.1` (VirtualBox host-only adapter)

### B2. Systeempakketten

```bash
sudo apt update
sudo apt install -y git curl python3-venv portaudio19-dev libportaudio2 espeak-ng alsa-utils
```

- `portaudio` → microfoon via `sounddevice`
- `espeak-ng` → fallback-stem als Piper niet werkt
- `alsa-utils` → `aplay` om opnamen te beluisteren

### B3. Repo

```bash
git clone https://github.com/rushman404/JARVIS.git ~/JARVIS
cd ~/JARVIS
```

### B4. Python 3.11 via uv

Op Ubuntu 24.04 is de systeem-Python 3.12. `openwakeword` vraagt op Linux om
`tflite-runtime`, en daarvan bestaan alleen wheels voor Python 3.11. Gebruik
daarom **Python 3.11** in de venv.

De Deadsnakes-PPA is niet altijd bereikbaar (wij kregen een 503). `uv` is een
betrouwbare manier:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.11
```

Maak de venv:

```bash
cd ~/JARVIS
uv venv --python 3.11 .venv
source .venv/bin/activate
python --version
```

Verwacht: **Python 3.11.x**. Installeer dan:

```bash
uv pip install -r requirements.txt
```

> Elke nieuwe terminal: eerst `cd ~/JARVIS && source .venv/bin/activate`.
> Na `deactivate` kan `uv` uit PATH verdwijnen; gebruik dan opnieuw
> `export PATH="$HOME/.local/bin:$PATH"`.

### B5. Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl status ollama --no-pager
ollama pull qwen2.5:3b
ollama run qwen2.5:3b "Zeg hallo in het Nederlands"
```

- Draait de dienst niet: `sudo systemctl start ollama`.
- Alternatief: `ollama serve` in een tweede terminal.
- Uit `ollama run` gaat u met `Ctrl+D`.
- Controleer later met `ollama list`.

### B6. Wake word

```bash
cd ~/JARVIS
source .venv/bin/activate
python -c "from openwakeword.utils import download_models; download_models()"
```

Het wake word is **"Hey Jarvis"** (`hey_jarvis`).

### B7. Piper-stem

```bash
python scripts/download_piper_voice.py nl_NL-pim-medium
```

De stem komt in `voice/models`. Werkt Piper niet, zet dan in `.env`:

```ini
PIPER_ENABLED=0
```

Dan gebruikt JARVIS `pyttsx3` met `espeak-ng`.

### B8. Certificaat naar de VM

Kopieer **alleen** `agent-cert.pem`. Nooit `agent-key.pem`.

**Veilige manier (aanbevolen):** maak op de game-pc een tijdelijke map met
alleen het certificaat:

```powershell
New-Item -ItemType Directory -Force C:\JARVIS\public
Copy-Item C:\JARVIS\certs\agent-cert.pem C:\JARVIS\public\
cd C:\JARVIS\public
python -m http.server 8000
```

In de VM:

```bash
mkdir -p ~/JARVIS/certs
wget http://192.168.2.41:8000/agent-cert.pem -O ~/JARVIS/certs/agent-cert.pem
```

Daarna op de game-pc: `Ctrl+C` en de tijdelijke map opruimen.

> **Let op:** serve nooit de hele map `certs/`. Daar staat ook
> `agent-key.pem` in. Iedereen op het netwerk kan die dan downloaden.

Alternatief: `scp` (als SSH op Windows aanstaat) of een USB-stick.

### B9. `.env` op de VM

Open:

```bash
cd ~/JARVIS
nano .env
```

`.env` is een verborgen bestand. Bestaat het nog niet, dan toont `nano`
`[ New File ]`; dat is normaal. Vul in:

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

Opslaan: `Ctrl+O`, `Enter`, daarna `Ctrl+X`.

Controleer dat het bestand bestaat:

```bash
ls -la .env
```

### B10. Verbinding testen

```bash
cd ~/JARVIS
source .venv/bin/activate
python3 -m scripts.test_remote_lan_manual
```

Verwacht: **6 van 6 geslaagd**:

1. online-check
2. ondertekende health
3. verkeerd token → 401
4. verouderde tijd → 401
5. volume-opdracht
6. screenshot

Stap 5 en 6 hebben echt effect: het volume gaat naar 20% en er wordt een
screenshot op de game-pc gemaakt.

> Gebruik `python3 -m scripts.test_remote_lan_manual`, niet
> `python3 scripts/test_remote_lan_manual.py`. Anders kan Python `config`
> niet vinden en krijgt u `ModuleNotFoundError: No module named 'config'`.

---

## 4. Deel C — Microfoon in de VM

### C1. VirtualBox-audio aanzetten

1. Zet de VM **uit**.
2. VM → **Settings** → **Audio**.
3. Zet **Enable Audio** aan.
4. Zet **Enable Audio Input** aan.
5. Controller: **Intel HD Audio**; host-driver: **Windows**.
6. Start de VM.

### C2. Apparaat kiezen

In Ubuntu: **Settings → Sound → Input**. Kies de microfoon en praat; de
balk moet bewegen.

Gebruikt u een USB-microfoon of headset: **Devices → USB** in het
VirtualBox-menu, selecteer het apparaat, en kies het daarna in Sound → Input.

### C3. Apparaten bekijken

```bash
cd ~/JARVIS
source .venv/bin/activate
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Zoek een regel met `in: 1` of hoger. Is de standaard niet goed, zet dan in
`.env`:

```ini
MIC_DEVICE=2
```

Gebruik het nummer of een deel van de naam. Leeg laten = standaardapparaat.

### C4. Microfoontest

```bash
python scripts/test_mic_manual.py
```

Zeg **"Hey Jarvis"**, wacht op de piep en zeg een zin. Daarna:

```bash
aplay scripts/mic_manual_opname.wav
```

Zo hoort u wat er is opgenomen.

---

## 5. Deel D — JARVIS starten en testen

### D1. Starten

Zorg dat de agent op de game-pc draait. Start dan in de VM:

```bash
cd ~/JARVIS
source .venv/bin/activate
python main.py
```

Wacht tot "JARVIS gestart" verschijnt. Zeg **"Hey Jarvis"**, wacht op de piep
en geef een commando.

### D2. Testlijst

Doe deze één voor één:

| Test | Commando | Verwacht |
|---|---|---|
| LLM | "Wat kun je doen?" | Nederlands antwoord |
| Lokaal | "Hoe laat is het?" | tijd |
| Remote volume | "Zet het volume op 30" | volume game-pc |
| Remote screenshot | "Maak een screenshot" | bestand op game-pc |
| Remote programma | "Open Spotify" | Spotify start |
| Remote sluiten | "Sluit Spotify" | Spotify stopt |
| Barge-in | "stop" tijdens antwoord | JARVIS stopt |

Controle op de game-pc:

```powershell
Get-Content C:\JARVIS\logs\audit.jsonl -Tail 10
```

Daar ziet u welke acties zijn aangekomen en wat het resultaat was.

### D3. Stoppen

- JARVIS: `Ctrl+C` in de VM.
- Agent: `Ctrl+C` in het PowerShell-venster.

---

## 6. Wat is het token?

Het token is een **gedeeld geheim**, zoals een wachtwoord. Het wordt gebruikt
om elk verzoek te ondertekenen (HMAC). Beide kanten moeten exact hetzelfde
token hebben.

- Maken: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- Minimaal 16 tekens; gebruik de volledige 43 tekens.
- Staat alleen in `.env`, nooit in de repository.
- Komt het niet overeen? Dan geeft de agent **401**.

Het certificaat is iets anders: dat versleutelt de verbinding (TLS). De
client vertrouwt het zelfondertekende servercertificaat via
`REMOTE_CLIENT_CA_FILE`. De privésleutel blijft op de server.

---

## 7. Waarom deze volgorde?

- Eerst de **agent** laten draaien, anders kan de VM niets testen.
- Dan de **client** en het **certificaat**, anders is de verbinding niet
  veilig.
- Dan pas de **spraakstack**, want die heeft veel meer afhankelijkheden.
- Als laatste de **microfoon**, omdat dat per VM en per host verschilt.

---

## 8. Snelle checklist

### Game-pc

- [ ] Repo in `C:\JARVIS`
- [ ] Python 3.11+ en venv
- [ ] `pip install -r requirements.txt -r requirements-dev.txt`
- [ ] Token gemaakt
- [ ] Certificaat gemaakt met juiste host/IP
- [ ] `.env` met serverregels en hetzelfde token
- [ ] `config.remote_server_security_errors()` geeft `[]`
- [ ] Firewallregel voor TCP 8765 (Privé)
- [ ] Agent gestart: `python -m remote.server`

### VM

- [ ] Ubuntu, repo in `~/JARVIS`
- [ ] Python 3.11 via uv
- [ ] `uv pip install -r requirements.txt`
- [ ] Ollama + `qwen2.5:3b`
- [ ] openWakeWord-modellen
- [ ] Piper-stem `nl_NL-pim-medium`
- [ ] `certs/agent-cert.pem` aanwezig
- [ ] `.env` met clientregels, `PC_TARGET=game-pc`
- [ ] `python3 -m scripts.test_remote_lan_manual` → 6/6

### Spraak

- [ ] VirtualBox audio-input aan
- [ ] Juiste mic in Ubuntu
- [ ] `MIC_DEVICE` indien nodig
- [ ] `python scripts/test_mic_manual.py` werkt
- [ ] `python main.py` start
- [ ] "Hey Jarvis" wordt herkend
- [ ] LLM antwoordt
- [ ] Remote volume/screenshot/openen/sluiten werkt
- [ ] Barge-in werkt (of bewust uitgezet)

---

## 9. Fouten die tijdens de eerste installatie zijn gemaakt

### 9.1 Overzichtstabel

| Fout / melding | Oorzaak | Oplossing |
|---|---|---|
| `ModuleNotFoundError: No module named 'config'` | Script vanuit `scripts/` gestart; projectroot staat niet op `sys.path` | `python3 -m scripts.test_remote_lan_manual` of `PYTHONPATH=. python3 scripts/...` |
| `Doel: 127.0.0.1`, token/CA ontbreken | `python-dotenv` niet geïnstalleerd; `config.py` slaat `.env` dan stil over | `pip install python-dotenv` in de venv; daarna opnieuw testen |
| `python3 -m venv` faalt | `python3-venv` ontbreekt | `sudo apt install -y python3-venv` |
| `tflite-runtime` heeft geen wheel | Python 3.12; `openwakeword` vraagt `tflite-runtime`, alleen cp311 | Python 3.11 via `uv` gebruiken |
| `uv: command not found` | `~/.local/bin` niet in PATH na `deactivate` | `export PATH="$HOME/.local/bin:$PATH"` |
| `curl: command not found` | `curl` niet geïnstalleerd | `sudo apt install -y curl` |
| Deadsnakes-PPA geeft 503 | PPA tijdelijk niet bereikbaar | `uv python install 3.11` |
| `.env` "bestaat niet" | Dotfile is verborgen | `ls -la`; `nano .env` maakt hem aan |
| Token "niet gevonden" | Token bestaat nog niet; je moet hem eerst maken | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| Verkeerd IP gebruikt (`192.168.56.1`) | Dat is de VirtualBox host-only adapter | Gebruik het LAN-IP van de game-pc, bijv. `192.168.2.41` |
| `401` bij health | Token verschilt, of de klok loopt achter | Zelfde token aan beide kanten; tijd synchroniseren |
| `certificate verify failed` | Verkeerd CA-bestand, verkeerd IP/hostnaam, of certificaat niet gekopieerd | `agent-cert.pem` naar de VM; cert genereren met het juiste `--ip`/`--host` |
| Agent niet bereikbaar | Agent niet gestart, firewall, verkeerd IP/poort | Agent starten; firewallregel; `nc -vz <ip> 8765` |
| `De game-pc reageerde niet op tijd` | Agent traag, time-out te laag, of actie hangt | `REMOTE_CLIENT_TIMEOUT=10`; agent herstarten; audit-log bekijken |
| Volume: `COM-aanroep duurde langer dan 10 seconden` | Deadlock: `_get_volume_interface()` deed nóg een `run_on_com_thread` binnen de COM-thread | Fix in `actions/media.py`; agent herstarten |
| Volume werkt lokaal niet | Zelfde deadlock, niet netwerkgerelateerd | Zelfde fix; test met `python -c "from actions.media import get_volume; print(get_volume())"` |
| Oude code actief na fix | Agent niet herstart | Ctrl+C en `python -m remote.server` opnieuw |
| `PC_TARGET=local` | Commando's worden in de VM uitgevoerd | `PC_TARGET=game-pc` in `.env` |
| Geen microfoon | VM-audio-input staat uit, of verkeerd apparaat | VirtualBox Audio Input aan; `sounddevice.query_devices()`; `MIC_DEVICE` |
| `aplay: command not found` | `alsa-utils` ontbreekt | `sudo apt install -y alsa-utils` |
| Geen wake word | Modellen niet gedownload, mic te zacht, of verkeerd apparaat | `download_models()`; mic-volume; `MIC_DEVICE` |
| Piper doet niets | `piper-tts` of stemmodel ontbreekt | `PIPER_ENABLED=0` of stem downloaden |
| Barge-in-fout op Linux | `keyboard`/uinput werkt niet zonder rechten | `BARGE_IN_ENABLED=0` in `.env` |
| Ollama connection refused | Dienst niet gestart | `sudo systemctl start ollama`; `ollama list` |
| `python3 main.py` gebruikt 3.12 | Venv niet actief | `source .venv/bin/activate`; `python --version` |
| Tokenbestand in git | `token-voor-vm.txt` stond niet in `.gitignore` | Verwijderen na gebruik; nooit committen; eventueel aan `.gitignore` toevoegen |
| `certs/` geserveerd via HTTP | Map bevat ook `agent-key.pem` | Alleen `agent-cert.pem` in een tijdelijke map serveren |

### 9.2 De volume-deadlock in detail

In `actions/media.py` draaien `get_volume()`, `set_volume()` en
`toggle_mute()` al binnen `run_on_com_thread(...)`. De hulpfunctie
`_get_volume_interface()` deed **nog een keer** `run_on_com_thread(...)`.
Daardoor wachtte de enige COM-thread op zichzelf en volgde na 10 seconden
een time-out.

De juiste vorm is direct aanroepen:

```python
def _get_volume_interface():
    """Haal de volume-interface op. Moet op de COM-thread draaien.

    Deze functie wordt zelf al binnen run_on_com_thread uitgevoerd.
    Geen nieuwe run_on_com_thread aanroepen: dat geeft een deadlock.
    """
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume
```

Test daarna op de game-pc:

```powershell
python -c "from actions.media import get_volume, set_volume; print('huidig:', get_volume()); print(set_volume(20)); print('nu:', get_volume())"
```

Verwacht: een getal, `Volume staat nu op 20%.`, en daarna `20`.

---

## 10. Beveiliging

- **Token** = wachtwoord. Niet delen, niet committen, niet in logs zetten.
- **`agent-key.pem`** verlaat de game-pc nooit.
- **`agent-cert.pem`** mag naar de VM; het is het openbare certificaat.
- **`.env`** en **`certs/`** staan in `.gitignore`. Controleer met
  `git status` dat ze niet als nieuw bestand verschijnen.
- **Poort 8765** alleen op het privénetwerk openzetten; geen port-forwarding
  naar internet.
- **`REMOTE_SERVER_ALLOWED_IPS`** leeg laten = alleen privéadressen. Vul hem
  alleen als u het bron-IP zeker weet.
- **Profiel `basis`** is de veilige standaard. `werkstation` geeft meer
  rechten; gebruik dat alleen als u het nodig hebt.
- **Audit-log** `C:\JARVIS\logs\audit.jsonl` laat zien wat er is uitgevoerd.

---

## 11. Onderhoud

- Na een codewijziging op de game-pc: **agent herstarten**.
- Na een `.env`-wijziging: **JARVIS opnieuw starten**.
- Na een IP-wijziging van de game-pc: **certificaat opnieuw genereren** of
  het nieuwe IP aan het certificaat toevoegen, en de client-`.env` bijwerken.
- Controleer af en toe:

```bash
cd ~/JARVIS
source .venv/bin/activate
python3 -m scripts.test_remote_lan_manual
```

- Houd `ollama list` en `Get-Content C:\JARVIS\logs\audit.jsonl -Tail 10`
  in de gaten bij problemen.
