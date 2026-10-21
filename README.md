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

### 🖥️ Game-PC Agent (remote)
- Een **gaming-pc op afstand** bedienen vanaf het brein (straks de mini-pc)
- Programma's en games **starten/sluiten**, status en **telemetrie**
  (CPU, geheugen, GPU-temperatuur), **media/volume** en **screenshots**
- Beveiligd met TLS, HMAC en een strikte allowlist (zie
  [docs/remote_agent.md](docs/remote_agent.md))

### 🧠 Geheugen & context
- Onthoudt de laatste actie en begrijpt vervolgopdrachten ("hem", "die")
- **Persistent geheugen** (herstart-proof): feiten, voorkeuren, apparaatnamen
- **Obsidian-koppeling**: je geheugen als Markdown-notities in je vault

### 📰 Externe bronnen (alleen op aanvraag)
- **Nieuws**: koppen van **NOS** en **Tweakers** (RSS-feeds)
- **Reistijd**: afstand en rijtijd via **OpenStreetMap/Nominatim** (plaatsen) +
  **OSRM** (route) — een schatting zonder live verkeer
- **Prijzen**: een prijsindicatie via **DuckDuckGo** + het lezen van de
  webpagina (Bol.com, Coolblue, Amazon.nl)
- JARVIS start deze zoekopdrachten **alleen** bij een echte vraag ("wat is het
  nieuws", "hoe lang doe ik erover van Amsterdam naar Utrecht", "wat kost een
  ipad"). Gewone zinnen en mededelingen starten niets. Bij twijfel stelt hij
  eerst een ja/nee-vraag.

### 🌙 Nachtmodus (tijdelijk of automatisch)
- Automatisch van **23:00 tot 07:00**; met "zet de nachtmodus aan" of
  "nachtmodus uit" zet u hem handmatig. Het werkwoord (zet, schakel, doe, ga)
  mag met "aan", "in" of "actief" én met "uit", "af", "weg" of "stop"
  gecombineerd worden. Zonder zo'n richting ("zet de nachtmodus") verandert er
  niets: u hoort alleen de huidige stand.
- Een handmatige stand **verloopt vanzelf** bij de eerstvolgende automatische
  overgang (07:00 of 23:00); daarna volgt JARVIS weer de vaste tijden. Met
  "nachtmodus automatisch", "auto", "normaal" of "reset de nachtmodus" gaat
  hij direct terug naar automatisch.
- Een **vraag** ("staat de nachtmodus aan") verandert niets; JARVIS noemt
  alleen de stand en tot wanneer die geldt.
- Gebruikerstimers en wekkers worden altijd uitgesproken, ook in de
  nachtmodus (dan zachter). Ze wachten nooit langer dan 30 minuten.

### 🎙️ Onderbreken (barge-in)
- JARVIS is midden in een antwoord te onderbreken: met uw stem (als er een
  headset aan de microfoon hangt) of met de sneltoets `Ctrl+Alt+J`.
- **Korte test:** laat JARVIS een lang antwoord geven; onderbreekt hij zichzelf,
  zet dan `BARGE_IN_MODE=sneltoets` in `.env`. U kunt dat ook zeggen:
  "zet onderbreken met stem uit" (alleen de sneltoets) of "zet onderbreken met
  stem aan" (weer met de stem).

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

## 🖥️ Game-PC Agent (remote)

JARVIS kan een **gaming-pc** op afstand bedienen (games starten/sluiten,
status & telemetrie, media/volume, screenshots) terwijl het brein op een
andere machine draait — de basis voor de mini-pc-architectuur (Fase 15).

- Op de **game-pc** draait de agent: `python -m remote.server`.
- Op het **brein** draait JARVIS met de remote-client.
- Alles gaat over **TLS** met **HMAC-ondertekende** verzoeken, een strikte
  **allowlist** en een **audit-log**. Zonder token en certificaat start de
  agent niet (fail-closed).

**Snel aan de slag:**

```powershell
# Op de game-pc:
python scripts\gen_remote_cert.py --host <ip-van-de-game-pc>
powershell -ExecutionPolicy Bypass -File scripts\install_game_pc_agent.ps1 -AddFirewallRule
python -m remote.server
```

Volledige handleiding — installatie, tokenbeheer, certificaatvertrouwen,
Windows Firewall, starten/stoppen, testen en verwijderen — staat in
**[docs/remote_agent.md](docs/remote_agent.md)**.

---

## ⚙️ Configuratie

Instellingen staan in `config.py` en worden deels via **omgevingsvariabelen**
of een lokaal `.env`-bestand overschreven (echte omgevingsvariabelen hebben
voorrang op `.env`).

| Variabele | Standaard | Betekenis |
|---|---|---|
| `AI_MODEL` | `qwen2.5:3b` | Ollama-model |
| `AI_NUM_CTX` | `8192` | Contextgrootte in tokens |
| `AI_TEMPERATURE_CHAT` | `0.3` | Temperatuur voor gesprekken |
| `AI_KEEP_ALIVE` | `30m` | Hoe lang het model in geheugen blijft |
| `HOME_ASSISTANT_URL` | *(leeg)* | URL van Home Assistant (optioneel) |
| `HOME_ASSISTANT_TOKEN` | *(leeg)* | HA long-lived access token |
| `HA_CONTROL_SAFETY_ON` | *(uit)* | `1` = alleen veilige HA-apparaten |
| `MIC_DEVICE` | *(standaard)* | Specifiek microfoonapparaat |
| `BARGE_IN_MODE` | *automatisch* | Onderbreken: `stem` (microfoon), `sneltoets` (alleen de toets) of `uit` |
| `BARGE_IN_ENABLED` | `1` (aan) | `0` = geen onderbreken |
| `BARGE_IN_HOTKEY` | `ctrl+alt+j` | Globale toets om JARVIS te onderbreken |
| `BARGE_IN_FRAMES` | `8` | Aantal spraakstukken (30 ms) voor een onderbreking |
| `BARGE_IN_MIN_RMS` | `1200` | Minimale geluidssterkte om als spraak te tellen |
| `BARGE_IN_ECHO_RATIO` | `1.8` | Hoeveel keer langer dan JARVIS' eigen stem het moet zijn |
| `BARGE_IN_GRACE_SECONDS` | `0.35` | Seconden aan het begin waarin de echo wordt geleerd |
| `BARGE_IN_ECHO_WINDOW_SECONDS` | `1.5` | Venster waarmee de echo-drempel doorlopend wordt gevolgd |
| `POWER_COUNTDOWN_SECONDS` | `20` | Wachttijd vóór afsluiten/herstarten |
| `JARVIS_OBSIDIAN_VAULT` | `~/JARVIS Memory` | Pad naar Obsidian-vault |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Adres van de Ollama-server |
| `PC_TARGET` | `local` | Standaarddoel voor pc-bediening: `local` (deze pc) of `game-pc` |
| `JARVIS_NIEUWS_BRONNEN` | `nos,tweakers` | Nieuwsbronnen voor het nieuwscommando (sleutels uit `actions.nieuws.FEEDS`) |
| `JARVIS_NIEUWS_MAX` | `5` | Hoeveel koppen JARVIS per nieuwsbron toont |
| `JARVIS_WEER_PLAATS` | `Amsterdam` | Plaats voor het weer in de dagstart-samenvatting |
| `TAAL_AUTOMATISCH` | `1` (aan) | `0` = JARVIS volgt de taal van uw vraag niet automatisch |
| `TAAL_AUTOMATISCH_DREMPEL` | `2` | Hoe streng de taaldetectie is (hoger = minder snel wisselen) |
| `DUCKING_ENABLED` | `1` (aan) | `0` = muziek/games niet automatisch dempen als JARVIS praat |
| `DUCKING_PERCENT` | `45` | Hoeveel procentpunten het volume omlaag gaat tijdens praten |
| `DUCKING_MIN_PERCENT` | `20` | Ondergrens: hieronder zakt het volume nooit |
| `ZEKERHEID_ENABLED` | `1` (aan) | `0` = geen voorbehoud meer bij onzekere informatie |
| `NIET_BEGREPEN_DREMPEL` | `2` | Aantal mislukte pogingen vóór de vriendelijke "ik laat het rusten"-melding |
| `NIET_BEGREPEN_MELDING` | *(tekst)* | Wat JARVIS dan zegt (leeg = alleen de vraag om herhaling) |

> **Taal volgt uw vraag (Fase 17).** Standaard antwoordt JARVIS in de taal van
> uw vraag: een overduidelijk Engelse vraag krijgt een Engels antwoord, een
> Nederlandse vraag een Nederlands antwoord. Die automatische wissel geldt
> alleen voor dát antwoord (taal én stem): de spraakherkenning blijft op de
> vaste taal, de wissel wordt niet bewaard en bij de volgende vraag die niet
> overduidelijk Engels is (of aan het einde van de sessie) is JARVIS weer
> Nederlands. Losse Engelse woorden in een Nederlandse zin ("zet even
> Spotify op") veranderen niets. Zet u een taal expliciet vast ("switch to
> English", "praat Engels"), dan wint die keuze altijd en luistert JARVIS
> ook in die taal; met **"taal mag automatisch"** geeft u die weer vrij. Uit
> te zetten met `TAAL_AUTOMATISCH=0`.
>
> **Terug naar Nederlands.** "please switch back to dutch", "ga terug naar
> nederlands" en "praat weer nederlands" zetten de taal terug (en worden
> onthouden).
>
> **Engelse stem (optioneel).** De Engelse antwoorden klinken standaard met de
> Nederlandse Piper-stem. Voor een echte Engelse stem haalt u één keer een
> Engels model op en zet u het in `.env`:
> ```powershell
> python scripts/download_piper_voice.py en_US-lessac-medium
> ```
> en `PIPER_VOICE_EN=en_US-lessac-medium`.

> **Standaarddoel (`PC_TARGET`).** Standaard bedient JARVIS **deze pc**
> (`local`). Wil je pc-commando's (programma's openen/sluiten/herstarten,
> volume, media, status, screenshot) op een **game-pc** laten uitvoeren, zet
> dan stap 1 eerst lokaal goed en zet pas daarna het doel om naar `game-pc`.
> Dat werkt alleen als de remote-client aan staat en compleet is
> geconfigureerd; anders meldt JARVIS dit bij het opstarten en falen
> game-pc-commando's met een duidelijke melding. Zie
> [docs/remote_agent.md](docs/remote_agent.md).

> **Game-PC Agent (remote).** De `REMOTE_SERVER_*`- en `REMOTE_CLIENT_*`-
> instellingen voor het op afstand bedienen van een gaming-pc staan uitgebreid
> beschreven in [docs/remote_agent.md](docs/remote_agent.md). Ze staan
> standaard **uit** en zijn fail-closed.

> **Externe bronnen (Fase 16C).** Nieuws, reistijd en prijzen werken **alleen
> op aanvraag** en zijn best-effort (fail-closed). Nieuws komt van de
> RSS-feeds van **NOS** en **Tweakers** (te kiezen met `JARVIS_NIEUWS_BRONNEN`).
> Reistijd gebruikt **OpenStreetMap/Nominatim** voor het omzetten van plaatsen
> naar coördinaten en **OSRM** voor de route — een schatting zonder live
> verkeersinformatie. Prijzen zoekt JARVIS via **DuckDuckGo** en het lezen van
> de webpagina van **Bol.com**, **Coolblue** en **Amazon.nl**; dat is een
> indicatie en kan afwijken of ontbreken. Gewone zinnen en mededelingen
> starten geen van deze zoekopdrachten; bij twijfel vraagt JARVIS eerst
> "wil je dat ik dit opzoek?" (ja/nee).

> **Contextgrootte (`AI_NUM_CTX`):** JARVIS stuurt systeemtekst +
> toolbeschrijvingen naar Ollama. Staat dit te laag, dan kapt Ollama de
> prompt af en ziet het model de tools niet meer. JARVIS waarschuwt in het
> log (`Prompt vult de context`) zodra de prompt de grens nadert.
>
> - **Hoger** (bijv. `16384`): model ziet meer, maar kost meer geheugen en
>   is wat trager.
> - **Lager** (bijv. `4096`): zuiniger en sneller, maar minder ruimte voor
>   tools/gesprek.
>
> Aanpassen: zet `AI_NUM_CTX` in `.env` of als omgevingsvariabele. JARVIS
> kiest per vraag al een kleine set tools (max. 12), dus meestal is 8192
> ruim voldoende.

JARVIS kiest per vraag een kleine, passende set tools in plaats van alle
~65 tegelijk (zie `core/tool_select.py`). Dat houdt de prompt klein én
zorgt dat het model de juiste tool vindt. Vraag je niets herkenbaars, dan
krijgt het model een basisset plus de twee meest waarschijnlijke
categorieën.

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
├─ remote/              # Game-PC Agent: protocol, allowlist, server, client, tools
├─ voice/               # wake word, spraakherkenning (STT) en spraak (TTS)
├─ memory/              # geheugen + Obsidian-koppeling
├─ config/              # Home Assistant-aliassen, scènes en routines (json)
├─ scripts/             # hulpscripts (certificaat, installatie) en handmatige tests
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
| 15 | Game-PC Agent (remote) | ✅ klaar |
| 16 | Proactive JARVIS (timers, agenda, welzijn) | 🟡 in ontwikkeling |
| 17 | Gesprek & dialoog (streaming, barge-in) | 🟡 kern klaar |
| 18 | Dashboard (chat, tiles, goedkeurings-popup) | ⬜ gepland |
| 19 | Mini-PC (het brein) | ⬜ gepland |
| 20 | iPad-interface | ⬜ gepland |
| 21 | Film-JARVIS (volledige ervaring) | 🔴 einddoel |

De volledige, per-fase checklist met besluiten staat in **[ROADMAP.md](ROADMAP.md)**.

> **Fase 16 (Proactive JARVIS):** 16A (kern: engine, meldingen, timers),
> 16B (dagtaken en auto-slaap) en 16C (externe bronnen: nieuws via NOS en
> Tweakers, reistijd via **OpenStreetMap/Nominatim** + OSRM, prijzen via
> **DuckDuckGo** en de webpagina's van Bol.com, Coolblue en Amazon.nl) zijn
> klaar. De nachtmodus heeft standen auto/aan/uit (een handmatige stand
> verloopt vanzelf) en een gesprek-watchdog zet een blijven hangen vlag na
> 10 minuten uit. Dagplanning en de agenda-koppeling volgen later.
