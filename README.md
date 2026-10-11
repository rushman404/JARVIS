# 🤖 JARVIS

> Een persoonlijke, sprekende AI-assistent in film-stijl.

JARVIS is een spraakgestuurde assistent in de stijl van Iron Man. Je praat
gewoon tegen hem, hij begrijpt de opdracht, maakt een plan, voert het uit,
controleert het resultaat en antwoordt. Hij bestuurt je pc, je slimme huis
(Home Assistant), het web en je media — allemaal hands-free.

---

## 🎯 Doel

JARVIS is een **persoonlijke, sprekende AI-assistent in film-stijl** die mijn
game-pc, slim huis (Home Assistant), het web en media bestuurt. Ik praat gewoon
tegen hem; hij begrijpt, plant, voert uit, controleert en antwoordt.

**Einddoel:** een volwaardige *film-JARVIS* die op een mini-pc draait en via een
iPad werkt — droog, kalm en film-getrouw, met karakter en droge humor.

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
- Overzicht: welke apps maken geluid, welke audio-apparaten heb ik

### 🌐 Web & browser
- Websites openen, in de browser zoeken, navigeren (terug/vooruit/verversen),
  tabs openen en sluiten
- Webpagina's **lezen** (URL, titel, zichtbare inhoud)
- **Zoeken op internet** (DuckDuckGo) en de top-bronnen **lezen en vergelijken**

### 🏠 Slim huis (Home Assistant)
- Lichten, schakelaars, covers/shutters, media_players, klimaat en sensoren
- Slimme **apparaatherkenning** via aliassen en capabilities — geen code per apparaat
- **Scènes** opslaan en activeren ("activeer scene filmavond")
- **TV/media**: volume, play/pauze, volgende nummer, bron kiezen
- JARVIS stelt na een multi-actie automatisch voor om er een scène van te maken

### 🧠 Geheugen & context
- Onthoudt de laatste actie en begrijpt vervolgopdrachten
  ("hem", "het", "die", "opnieuw")
- **Persistent geheugen** (herstart-proof): feiten, voorkeuren, apparaatnamen
- **Obsidian-koppeling**: je geheugen als Markdown-notities in je vault
- Prioriteit, veroudering en conflictoplossing

### 🛡️ Betrouwbaarheid & veiligheid
- **Agent**: doel → plan → uitvoeren → controleren → antwoorden
- **Nooit "succes" claimen** zonder bevestigd resultaat
- Automatische **fallbacks** en één herplanning bij fouten
- **Goedkeuring** bij gevaarlijke of onomkeerbare acties
- **Audit-log** van wat JARVIS doet
- Volledige statische **test-suite**

---

## 🚀 Installatie

**Vereisten**
- Windows (voor pc-besturing, audio-routing en UI-automatisering)
- Python **3.11+**
- [Ollama](https://ollama.com) met het model `qwen2.5:3b`
- Internet (voor spraakherkenning en webzoekopdrachten)

**Stappen**

1. Installeer Python 3.11+ en Ollama.
2. Installeer de Python-afhankelijkheden (inclusief wake word, spraak en `.env`):
   ```powershell
   pip install -r requirements.txt
   ```
3. Start Ollama en haal het model op:
   ```powershell
   ollama pull qwen2.5:3b
   ollama serve
   ```
4. Installeer een **Nederlandse stem** in Windows (Instellingen → Tijd en taal
   → Spraak) zodat JARVIS Nederlands kan praten. Optioneel: kopieer
   `.env.example` naar `.env` en vul je waarden in.

---

## ⚙️ Configuratie

Instellingen staan in `config.py` en worden deels via **omgevingsvariabelen**
overschreven:

| Variabele | Standaard | Betekenis |
|---|---|---|
| `AI_MODEL` | `qwen2.5:3b` | Ollama-model |
| `AI_NUM_CTX` | `4096` | Contextgrootte |
| `AI_KEEP_ALIVE` | `30m` | Hoe lang het model in het geheugen blijft |
| `HOME_ASSISTANT_URL` | *(leeg)* | URL van je Home Assistant (optioneel) |
| `HOME_ASSISTANT_TOKEN` | *(leeg)* | Long-lived access token (optioneel) |
| `JARVIS_OBSIDIAN_VAULT` | `C:\JARVIS\JARVIS Memory` | Pad naar je Obsidian-vault |

Er staat een `.env.example` als voorbeeld. Kopieer die naar `.env` en vul je
waarden in: JARVIS laadt `.env` automatisch bij het opstarten (via
`python-dotenv`). Echte omgevingsvariabelen hebben voorrang op `.env`.

In `config.py` pas je ook je **naam** (`USER_NAME`) aan, zodat JARVIS je zo
aanspreekt.

---

## ▶️ Starten

```powershell
python main.py
```

JARVIS zegt *"JARVIS is online."* en wacht daarna op zijn wake word.

---

## 🗣️ Zo gebruik je het

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
"Zet de woonkamerlamp op 40 procent."
"Zet Spotify op 50 en demp Discord."
"Zoek de GTX 5080 specificaties op en vergelijk twee bronnen."
"Maak een screenshot."
"Onthoud dat ik van warm licht hou."
```

> ⚠️ Gevaarlijke of onomkeerbare acties (afsluiten, herstarten, verwijderen)
> vraagt JARVIS eerst om **bevestiging**. Je geverifieerde resultaat is pas
> "klaar" als JARVIS het echt bevestigd heeft.

---

## 🧪 Testen & lint

De volledige suite draait zonder microfoon of Ollama (externe modules worden
gemockt):

```powershell
pytest -v          # volledige test-suite
ruff check .       # lint
```

Op CI draait hetzelfde op Windows én Linux (`.github/workflows/tests.yml`).

---

## 🗂️ Projectstructuur

```text
JARVIS/
├─ main.py         # startpunt: wake word → luisteren → uitvoeren (loop)
├─ config.py       # instellingen (naam, AI-model, Home Assistant, tijden)
├─ actions/        # uitvoerbare acties (pc, browser, audio, media, systeem, ...)
├─ core/           # brein: ai, brain, planner, executor, agent, HA, memory, ...
├─ voice/          # wake word, spraakherkenning (STT) en spraak (TTS)
├─ memory/         # geheugen + Obsidian-koppeling
├─ config/         # Home Assistant-aliassen, scènes en routines (json)
├─ tests/          # pytest-suite
└─ scripts/        # debug- en hulpscripts
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
