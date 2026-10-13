# 🤖 JARVIS

> Een persoonlijke, sprekende AI-assistent in film-stijl.

JARVIS is een spraakgestuurde assistent in de stijl van Iron Man. Je praat
gewoon tegen hem, hij begrijpt de opdracht, maakt een plan, voert het uit,
controleert het resultaat en antwoordt. Hij bestuurt je pc, je slimme huis
(Home Assistant), het web en je media — allemaal hands-free.

---

## ✨ Wat JARVIS kan

### 💻 PC-besturing
- Programma's **openen, sluiten, herstarten, zoeken** en status opvragen
- **Bestanden** zoeken, openen, mappen openen, kopiëren, verplaatsen,
  hernoemen en verwijderen (altijd naar de prullenbak)
- **Vensters** beheren: vergroten, verkleinen, minimaliseren, maximaliseren
- **Screenshots** maken, systeeminformatie en schermresolutie opvragen
- **Power-acties**: vergrendelen, slaapstand, afsluiten, herstarten
  (met bevestiging)

### 🎵 Media & audio
- Afspelen, pauzeren, volgende/vorige, volume omhoog/omlaag/instellen
- **Volume per app** (bv. "zet Spotify op 50", "maak Discord zachter")
- Apps **dempen / ontgrendelen**, **audio-uitvoer wisselen**
  (headset ↔ speakers ↔ SteelSeries Sonar)

### 🌐 Web & browser
- Websites openen, in de browser zoeken, navigeren (terug/vooruit/verversen),
  tabs openen en sluiten
- Webpagina's **lezen** (URL, titel, zichtbare inhoud)
- **Zoeken op internet** (DuckDuckGo) en de top-bronnen **lezen en vergelijken**

### 🏠 Slim huis (Home Assistant, optioneel)
- Lichten, schakelaars, covers/shutters, media_players, klimaat en sensoren
- Slimme **apparaatherkenning** via aliassen en capabilities
- **Scènes** opslaan en activeren ("activeer scene filmavond")

### 🧠 Geheugen & context
- Onthoudt de laatste actie en begrijpt vervolgopdrachten ("hem", "die")
- **Persistent geheugen** (herstart-proof): feiten, voorkeuren, apparaatnamen
- **Obsidian-koppeling**: je geheugen als Markdown-notities in je vault

### 🛡️ Betrouwbaarheid & veiligheid
- **Agent**: doel → plan → uitvoeren → controleren → antwoorden
- **Nooit "succes" claimen** zonder bevestigd resultaat
- **Goedkeuring** bij gevaarlijke of onomkeerbare acties
- **Audit-log** van wat JARVIS doet

---

## 🚀 Vereisten

- **Windows 11** — pc-besturing, audio-routing en UI-automatisering zijn
  Windows-specifiek (de assistent zelf start ook op andere systemen, maar
  pc-acties werken alleen op Windows).
- **Python 3.11 of nieuwer**.
- **[Ollama](https://ollama.com)** met het model `qwen2.5:3b` (of een eigen
  model via `AI_MODEL`).
- **Home Assistant** — *optioneel*, voor het slimme huis.
- **Internet** — voor spraakherkenning (Google STT) en webzoekopdrachten.
- Op Windows een **Nederlandse stem** (Instellingen → Tijd en taal → Spraak).

---

## 🚀 Installatie

1. **Installeer Python 3.11+ en Ollama.**
   Controleer: `python --version` en `ollama --version`.

2. **Open de projectmap** in PowerShell en maak een virtuele omgeving:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Installeer de afhankelijkheden:**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
   > **Waarom `webrtcvad-wheels` en niet `webrtcvad`?** `webrtcvad-wheels`
   > is een drop-in vervanger met dezelfde import (`import webrtcvad`),
   > maar heeft géén C++ build tools nodig zoals het originele
   > `webrtcvad` op Windows (en werkt ook zonder de verouderde
   > `pkg_resources`).

4. **Start Ollama en haal het model op:**
   ```powershell
   ollama pull qwen2.5:3b
   ollama serve
   ```
   (Laat `ollama serve` draaien, of gebruik de Ollama-app op de achtergrond.)

5. **openWakeWord-modellen downloaden.** Het pip-pakket bevat de
   modelbestanden **niet**: die haal je één keer op. Het wake word
   **"Hey JARVIS"** (`hey_jarvis`) zit in de standaardset.
   ```powershell
   python -c "from openwakeword.utils import download_models; download_models()"
   ```

6. **Instellingen (optioneel).** Kopieer het voorbeeld en vul je waarden in:
   ```powershell
   copy .env.example .env
   ```
   Zonder `.env` werkt JARVIS met de standaardwaarden uit `config.py`.
   Zie het overzicht onder [⚙️ Configuratie](#️-configuratie).

---

## ▶️ Starten

```powershell
python main.py
```

JARVIS zegt *"JARVIS is online."* en wacht daarna op zijn wake word.

### Zo gebruik je het
1. **Wek JARVIS** met het wake word: **"Hey JARVIS"**.
2. Hij piept kort ten teken dat hij luistert.
3. **Spreek je opdracht** in het Nederlands.
4. JARVIS begrijpt, voert uit en antwoordt.
5. **Stop met luisteren** met: *"ga slapen"*, *"stop jarvis"*, *"tot ziens"*,
   *"welterusten"*, *"rustig aan"*, *"ga weg"*.

**Voorbeelden**
```text
"Open Discord en zet mijn volume op 30 procent."
"Zoek op YouTube naar spider-man."
"Wat staat er op mijn browser?"
"Zet de woonkamerlamp op 50."
"Vergelijk de RTX 4070 en 4060."
"Maak een screenshot."
```

---

## ⚙️ Configuratie

Instellingen staan in `config.py` en worden deels via **omgevingsvariabelen**
of een lokaal `.env`-bestand overschreven (echte omgevingsvariabelen hebben
voorrang op `.env`).

| Variabele | Standaard | Betekenis |
|---|---|---|
| `AI_MODEL` | `qwen2.5:3b` | Ollama-model |
| `AI_NUM_CTX` | `4096` | Contextgrootte |
| `AI_TEMPERATURE_CHAT` | `0.3` | Temperatuur voor gesprekken |
| `AI_KEEP_ALIVE` | `30m` | Hoe lang het model in geheugen blijft |
| `HOME_ASSISTANT_URL` | *(leeg)* | URL van Home Assistant (optioneel) |
| `HOME_ASSISTANT_TOKEN` | *(leeg)* | HA long-lived access token |
| `HA_CONTROL_SAFETY_ON` | *(uit)* | `1` = alleen veilige HA-apparaten |
| `MIC_DEVICE` | *(standaard)* | Specifiek microfoonapparaat |
| `POWER_COUNTDOWN_SECONDS` | `20` | Wachttijd vóór afsluiten/herstarten |
| `JARVIS_OBSIDIAN_VAULT` | `~/JARVIS Memory` | Pad naar Obsidian-vault |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Adres van de Ollama-server |

---

## 🛡️ Veiligheid

JARVIS claimt **nooit** succes zonder bevestigd resultaat. Daarvoor gelden
een paar regels:

- **Bevestigingen.** Gevaarlijke of onomkeerbare acties (afsluiten,
  herstarten, bestanden verwijderen, pc-uitzetten) worden pas uitgevoerd
  nadat je expliciet *"ja"* zegt. Bevestigingen verlopen na 20 seconden
  (`CONFIRM_TTL_SECONDS`) en je kunt ze annuleren.
- **Risicotabel.** Elke tool heeft een risiconiveau in `core/tool_registry.py`:
  `low` wordt automatisch uitgevoerd, `medium`/`high` vragen om goedkeuring.
  Een onbekende tool is fail-safe `medium`. Zo kan een nieuw domein nooit
  stilzwijgend gevaarlijk werk doen.
- **Auditlog.** Elke geregistreerde actie komt in `logs/audit.jsonl`
  (tijd, gehoorde tekst, tool, argumenten, risico, resultaat, goedgekeurd).
  Geheimen zoals tokens worden vervangen door `***`. Het log roteert
  automatisch zodra het groter is dan 5 MB.

---

## 🧪 Tests en lint

De test-suite werkt volledig **zonder microfoon of internet**: hardware en
netwerk worden gemockt.

```powershell
pip install -r requirements-dev.txt
pytest
ruff check .
```

De CI (`.github/workflows/tests.yml`) draait de tests op **Windows én Linux**
met Python 3.11.

---

## 🗂️ Projectstructuur

```text
JARVIS/
├─ main.py              # startpunt: wake word → luisteren → uitvoeren (loop)
├─ config.py            # instellingen (naam, AI-model, Home Assistant, tijden)
├─ requirements.txt     # runtime-afhankelijkheden
├─ requirements-dev.txt # test- en lint-tools (pytest, ruff)
├─ .env.example         # voorbeeld van de omgevingsvariabelen
├─ actions/             # uitvoerbare acties (pc, browser, audio, media, web, ...)
├─ core/                # brein: ai, brain, planner, executor, agent, HA, audit, ...
├─ voice/               # wake word, spraakherkenning (STT) en spraak (TTS)
├─ memory/              # geheugen + Obsidian-koppeling
├─ config/              # Home Assistant-aliassen, scènes en routines (json)
├─ scripts/             # debug- en handmatige testscripts
├─ tests/               # pytest-suite
└─ docs/                # documentatie en roadmap
```

---

## 🧭 Status & roadmap

| Fase | Onderwerp | Status |
|---|---|---|
| 0 | Basis JARVIS (wake word, STT, TTS, AI, acties) | ✅ klaar |
| 1 | PC Control 1.0 | ✅ klaar |
| 2 | Context & Memory 1.0 | ✅ klaar |
| 3 | Media Control | ✅ klaar |
| 4–5 | Planner, Executor & multi-acties | ✅ klaar |
| 6 | Reliability & Safety | ✅ klaar |
| 7–7B | Agent & PC Control 2.0 | ✅ klaar |
| 8–9 | Web Fetch & Web Agent | ✅ klaar |
| 10 | UI Automation | ✅ klaar |
| 11 | Sonar / audio-routing | ✅ klaar |
| 12 | PC Control compleet (browser lezen, fallbacks) | ✅ klaar |
| 13 | Home Assistant 2.0 (scènes, media, automations) | ✅ klaar |
| 14 | Memory 2.0 + Obsidian | 🟡 basis bestaat |
| 15 | Game-PC Agent (remote) | ⬜ gepland |
| 16 | Proactive JARVIS (timers, agenda, welzijn) | ⬜ gepland |
| 17 | Gesprek & dialoog (streaming, barge-in) | ⬜ gepland |
| 18 | Dashboard (chat, tiles, goedkeurings-popup) | ⬜ gepland |
| 19 | Mini-PC (het brein) | ⬜ gepland |
| 20 | iPad-interface | ⬜ gepland |
| 21 | Film-JARVIS (volledige ervaring) | 🔴 einddoel |

De volledige, per-fase checklist met besluiten staat in **[ROADMAP.md](ROADMAP.md)**.
