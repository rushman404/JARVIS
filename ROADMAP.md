# 🤖 JARVIS — Roadmap & Checklist

**Doel:** één definitieve lijst zodat je altijd weet: *waar ben ik, wat moet ik nu
bouwen, en wanneer mag ik door naar de volgende fase?*

> ⚠️ **Belangrijk:** deze lijst is gebaseerd op de daadwerkelijke codebase
> (geverifieerd), niet op aannames. Elke fase heeft een check in `test/`.

---

## ✅ Besluiten & verwachtingen (Q&A)

Vastgelegd zodat scope en non-scope altijd helder zijn.

* **Alles even belangrijk:** pc, slim huis, web en media zijn gelijkwaardig.
* **Autonomie:** veilige acties direct, goedkeuring bij gevaarlijke/onomkeerbare acties.
* **Architectuur:** de game-pc (huidige pc) wordt op afstand bediend; de mini-pc wordt uiteindelijk het brein waar JARVIS + AI draaien.
* **Prioriteit:** betrouwbaarheid van het huidige eerst — audit + regressie vóór nieuwe fases.
* **Film-modus = volledige ervaring:** praktisch + sfeer + JARVIS vertelt live wat hij doet.
* **Karakter:** nu nog niet; later droog en kalm, film-getrouw (einddoel).
* **Dialoog:** later film-achtige gesprekken — streaming, onderbreken en natuurlijke wissels (Fase 17).
* **Reactiesnelheid:** acties ("open dit", "zet volume") moeten direct; research/vragen mogen even duren.
* **Privacy/lokaal vs cloud:** cloud-gebruik mag, maar bewust kiezen per functie wat waar draait.
* **Foutafhandeling:** eerst zelf een alternatief proberen (fallback), pas daarna uitleg.
* **Gebruikers:** alleen jij — geen stemherkenning van anderen.
* **Aanspreken:** gewoon "JARVIS".
* **Goedkeuring: via visuele popup** op dashboard/iPad, niet hardop vragen (tenzij jij erom vraagt).
* **Bewust niet:** per-kanaal Sonar-sturing; volledig autonoom handelen; shutters/klimaat/sensoren hebben geen prioriteit.

---

## 🟢 FASE 0 — Basis JARVIS

**Status: ✅ KLAAR** (geverifieerd: `main.py`, `core/ai.py`, `core/brain.py`, `core/tools.py`, `voice/`)

* [x] Wake word `voice/wakeword.py`
* [x] Microfoon + speech-to-text `voice/listen.py`
* [x] Text-to-speech (Nederlands) `voice/speak.py`
* [x] AI-model (Ollama) `core/ai.py`
* [x] AI → tool-call route
* [x] Brain / deterministische routing `core/brain.py`
* [x] Acties-structuur `actions/`

**Klaar als:** JARVIS luistert, begrijpt, antwoordt en eenvoudige acties uitvoert.

---

## 🟢 FASE 1 — PC Control 1.0

**Status: ✅ KLAAR** (geverifieerd: `actions/program_finder.py`, `actions/pc.py`)

* [x] Programma openen / zoeken / naar voren halen
* [x] Programma sluiten
* [x] Bestand zoeken `actions/file_finder.py`
* [x] Bestand openen / beheren
* [x] Vensters: vergroten, verkleinen, minimaliseren, maximaliseren
* [x] Screenshots `actions/screenshot.py`
* [x] Power-acties (lock, slaap, afsluiten, herstart) `actions/power.py`
* [x] Systeeminformatie `actions/system.py`

---

## 🟢 FASE 2 — Context & Memory 1.0

**Status: ✅ KLAAR** (geverifieerd: `memory/memory.py`, `memory.json`, `conversation.json`)

* [x] Laatste actie onthouden
* [x] `hem`, `het`, `die`, `opnieuw` vervolgopdrachten
* [x] Persistent geheugen (herstart-proof)
* [x] Conversation history

---

## 🟢 FASE 3 — Media Control

**Status: ✅ KLAAR** (geverifieerd: `actions/media.py`)

* [x] Play / pauze / volgende / vorige
* [x] Volume omhoog / omlaag / instellen
* [x] Media-apps openen

---

## 🟢 FASE 4 — Planner & Executor

**Status: ✅ KLAAR** (geverifieerd: `core/planner.py`, `core/executor.py`)

```text
Opdracht → Plan → Executor → Acties → Resultaat
```

* [x] Action plan
* [x] Dependencies / conditions / waits
* [x] Parallelle acties
* [x] Retry / failed / skipped
* [x] Approval (goedkeuring voor gevaarlijke acties)
* [x] Result validation `core/result_validation.py`

**Niet opnieuw bouwen.** Dit blijft het fundament.

---

## 🟢 FASE 5 — Multi-action

**Status: ✅ KLAAR** (geverifieerd: `core/planner.py` + Executor)

* [x] Meerdere acties herkennen `is_multi_step_goal`
* [x] Acties opdelen
* [x] Juiste tool per actie
* [x] Juiste volgorde (dependencies)
* [x] Fout per stap afhandelen

> "Open Discord en zet mijn volume op 30 procent." ✅

---

## 🟢 FASE 6 — Reliability & Safety

**Status: ✅ KLAAR** (geverifieerd: `core/retry.py`, `core/result_validation.py`, `tests/run_all_tests.py`, `test/test_edge_cases_stress.py`)

* [x] Fake-success voorkomen
* [x] Tool-resultaten controleren
* [x] Verkeerde / onbekende tool weigeren
* [x] Gevaarlijke acties herkennen + approval
* [x] Centrale testrunner `tests/run_all_tests.py`
* [x] Volledige stress-test `test/test_all_tools_stress.py` + `test/test_speech_stress_new.py`
* [x] Randgevallen & rare spraak `test/test_edge_cases_stress.py` (lege input, nonsens, fuzzy, execute_tool slechte args)
* [x] Input-guard in `process_command` (lege/whitespace/interpunctie → veilig deterministisch antwoord)
* [x] Volledige suite groen: 688 legacy + alle secties (speech-stress 11 PASS / 0 FAIL)

---

## 🟢 FASE 7 — Agent V1

**Status: ✅ KLAAR** (geverifieerd: `core/agent.py`)

* [x] Doel ontvangen
* [x] Plan genereren (via Planner)
* [x] Uitvoeren (via Executor)
* [x] Resultaten controleren
* [x] Één herplanning bij fouten
* [x] Nooit "succes" claimen zonder bevestigd resultaat
* [x] Eindantwoord samenstellen

---

## 🟢 FASE 7B — PC Control 2.0 (programma's, bestanden, vensters, browser)

**Status: ✅ KLAAR** (geverifieerd: `actions/browser.py`, `actions/pc.py`, `actions/file_manager.py`)

### Programma's
* [x] Open / sluit / **herstart** / **vind** / **status controleren**

### Bestanden
* [x] Zoeken `search_files`
* [x] Openen
* [x] Map openen `open_folder`
* [x] Kopiëren / verplaatsen
* [x] Hernoemen `rename_file`
* [x] Verwijderen → **altijd direct naar prullenbak**
* [x] Recente bestanden `get_recent_files`

### Windows
* [x] Vensters beheren
* [x] **Scherminformatie** `screen_info` (resolutie)
* [x] Volume / media / screenshots / systeeminfo

### Browser
* [x] Website openen (`open youtube`)
* [x] **Zoeken** (`zoek op youtube naar spider-man`) `browser_search`
* [x] Navigeren: terug / vooruit / verversen
* [x] Tabs: nieuw / sluiten

---

## 🔵 FASE 8 — Web Fetch ✅ KLAAR

**Status: ✅ KLAAR** (geverifieerd: `actions/web.py`, `test/test_web_fetch.py`)

JARVIS kan sites **openen én lezen**.

* [x] `web_fetch(url)` tool
* [x] URL ophalen, HTTP-status controleren (404 / 500 / timeout / verbindingsfout)
* [x] HTML → leesbare tekst (scripts/styles/nav weg) zonder extra libs
* [x] Titel + metadata (og-description) uitlezen
* [x] Grote pagina's afkappen (4000 tekens, token-limiet)
* [x] Timeout (15s) + grootte-begrenzing (2 MB)
* [x] Veilige URL-validatie (alleen http/https; geen file://, javascript:, onzin)
* [x] Executor: `execute_tool("web_fetch")` in `core/ai.py`
* [x] Agent: `web_fetch` in `VALID_TOOL_NAMES` + `TOOL_LIST_TEXT`
* [x] Brain-routing: "lees deze pagina <url>", "wat staat er op <url>"
* [x] Tests: 49 checks in `test/test_web_fetch.py` (gemockte HTTP)

**Klaar als:** JARVIS een webpagina kan ophalen, lezen en de informatie betrouwbaar kan gebruiken. ✅

---

## 🔵 FASE 9 — Web Agent

**Status: ✅**

```text
Web zoeken (DuckDuckGo) + Web fetch + Browser + Agent
```

* [x] Zoekresultaten begrijpen (DuckDuckGo HTML-parser: titel/snippet/URL)
* [x] Relevante pagina kiezen (search_and_fetch leest top-bron)
* [x] Meerdere pagina's vergelijken (max_pages=2, bronnen bijhouden)
* [x] Agent bepaalt zelf welke webactie nodig is (web_search / web_search_and_fetch tools)
* [x] Web-fouten afhandelen + resultaat controleren (timeout/404/geen resultaten)

**Klaar als:** "Zoek de GTX 5080 requirements op en vergelijk twee bronnen" werkt. ✅
**Getest:** web-fetch (51) + web-search (48) = 99 web-check specifiek; suite 831/0.

---

## 🟣 FASE 10 — UI Automation

**Status: ✅** — algemene Windows-app-bediening via pywinauto + UI Automation.

* [x] Library kiezen (Windows Accessibility / UIA) — pywinauto + UIA backend
* [x] Vensters & applicaties vinden — `list_windows`, `find_window`, `activate_window`
* [x] UI-elementen lezen: type, naam, automation ID, parent/child — `list_elements`, `find_element`
* [x] Buttons activeren, text typen, sliders bedienen, selecties maken — `click_element`, `type_text`, `set_value`, `get_value`
* [x] UI-wachten + timeouts + foutafhandeling + validatie — `TIMEOUT` constanten + `error_type` op elke fout
* [x] Algemene functies: `find_window`, `find_element`, `click_element`, `set_value`, `get_value`, `type_text`
* [x] Tool-definities in `core/ai.py` (11 ui_* tools) + dispatch in `execute_tool`
* [x] Brain-routing voor eenvoudige venster-commando's (`try_ui_automation`)
* [x] Agent-whitelist + planning-prompt aangevuld
* [x] Tests: `test/test_ui_automation.py` (49 checks, mock-based, geen live UI)
* [x] Stress-test: `test/test_fase10_stress.py` (55 checks: routing, ambiguïteit, rare input, veiligheid)
* [x] Live smoke-test: vensters zoeken + elementen lezen (read-only) + NVIDIA-venster geverifieerd
* [x] Ambiguïteit opgelost: "zet het volume van <app> op 50" → Agent/ui-tools, NOOIT Windows-volume
* [x] Volledige regressie: 799 legacy + 46 nieuw, 0 gefaald

**Belangrijk: `actions/ui_automation.py` blijft algemeen. Geen Sonar-code hierin.** ✅

---

## 🟣 FASE 11 — Sonar Integration

**Status: 🟢 VOLTOOID (Audio-laag)** — Windows output-routing + per-app volume werkt.

### Voltooid ✅

* [x] **pycaw verifiëren + audio-laag** (`actions/audio.py`)
  * `list_sessions()` — welke apps maken geluid (procesnaam, volume, mute)
  * `get_session_volume()` / `set_session_volume()` — per-app volume (0-100)
  * `set_session_mute()` / `toggle_session_mute()` — per-app dempen
  * `list_output_devices()` — alle actieve output-apparaten (headset, speakers, Sonar virtual)
  * `get_default_output()` / `set_default_output()` — output-apparaat wisselen
  * Aliassen: `headset` → Hoofdtelefoon, `speakers` → Luidsprekers, `sonar gaming` → SteelSeries Sonar
* [x] **Brain-routing** (`try_audio_command`) — volledig deterministisch:
  * "zet Spotify op 50" → `audio_set_session_volume` (per-app!)
  * "maak Discord zachter/harder" → per-app volume ±10%
  * "demp Discord" / "zet Discord geluid aan" → per-app mute
  * "zet output naar headset" → `audio_set_default_output`
  * "welke apps maken geluid" → `audio_list_sessions`
  * "welke audio-apparaten heb ik" → `audio_list_outputs`
  * "waar gaat mijn geluid naartoe" → `audio_get_default_output`
* [x] **Live bevestigd**: alle sessies, mute, output-wisseling (headset↔Sonar↔speakers) werkt daadwerkelijk op jouw pc
* [x] **Tests**: `test/test_audio.py` (26/26) + stress-test `test_fase10_stress.py` uitgebreid met audio-routing (66/66) + regressie 882/882 = 0 gefaald

### Afgerond / Niet nodig ❌

* [x] **Sonar-kanaalspecifieke output (Game/Chat/Media)** — **Onderzocht en bewust niet gebouwd.**
  * Reden: SteelSeries GG-API is niet publiek/reverse-engineerbaar; Sonar luistert al naar het Windows default-apparaat.
  * **Huidige oplossing werkt beter**: `"zet output naar headset"` wisselt het Windows default → Sonar volgt automatisch → alle Sonar-configs (Bass Boost, EQ, Surround) blijven actief.

---

## 🔵 FASE 12 — PC Control Compleet (browser lezen, fallbacks, status, recovery) ✅

**Status: 🟢 KLAAR** — Viewing status: browser reading + fallbacks + unified status + Agent-recovery.

### Voltooid ✅

* [x] **Browser Content Reading** (`actions/browser.py` — Fase 12)
  * `get_browser_url()` — leest de URL van de actieve browser via UIA Edit-control
  * `get_browser_title()` — leest de paginatitel via venstertitel
  * `get_browser_content(max_items)` — leest alle zichtbare tekst via UIA Text-elements
  * Werkt met alle Chromium-browsers (Brave, Chrome, Edge, Opera, Vivaldi) + Firefox
* [x] **Brain-routing** voor contextuele browser-vragen:
  * "wat staat er op mijn browser?" → `get_browser_content()`
  * "welke pagina heb ik open?" → `get_browser_url()`
  * "wat is de titel van mijn browser?" → `get_browser_title()`
* [x] **Tool-integratie**: browser_get_url, browser_get_title, browser_get_content + pc_status in ai.py + tools.py + agent-whitelist
* [x] **Live bevestigd**: browser-leesfuncties werken op jouw Brave-browser

### Fallback Chains (Fase 12)

* [x] `core/retry.py` uitgebreid met `FALLBACK_MAP`:
  * `ui_click_element` → `ui_find_element` (eerst zoeken, dan klikken)
  * `ui_type_text` → `ui_find_element`
  * `browser_search` → `web_search` (DuckDuckGo fallback)
* [x] **Logische mislukking-detectie**: een `{"ok": False}` retour (ook als
  stringified dict) telt nu óók als falen → fallback-chain wordt getriggerd,
  niet alleen bij exceptions
* [x] Transform-args per fallback; `fallback_used` in het resultaat
* [x] Executor geeft `fallback_used` door aan het record

### Unified PC Status (Fase 12)

* [x] **`actions/status.py`** — `get_pc_status()`:
  * Systeem (CPU/RAM/disk/batterij/uptime)
  * Audio (huidige output + actieve sessions)
  * Browser (URL + titel)
  * Eén opdracht: "geef me een overzicht van de pc", "pc status"
* [x] Foutbestendig: audio- of browser-fout breekt het overzicht niet op

### Agent kiest beste methode + recovery (Fase 12, Optie B)

* [x] **Planner-prompt** kent nu expliciet de methode-keuze:
  * "wat staat er op mijn browser" → browser_get_content, NIET web_search
  * "zoek op internet" → web_search, NIET browser_search
  * "open een website" → browser_search
  * Per-app-volume → audio_set_session_volume
* [x] **Herplan-prompt** kiest bewust een ANDERE methode bij mislukte stappen:
  * browser_get_* leest niets → web_fetch / open_program
  * ui_click_element mislukt → eerst ui_list_elements opnieuw lezen
  * nooit dezelfde tool met dezelfde argumenten
* [x] **Herplanning weet wat al geprobeerd is**: `fallback_used` wordt
  meegestuurd als "AL GEPROBEERD via fallback: X"

### Tests ✅

* [x] `test/test_browser_reading.py` (10/10)
* [x] `test/test_status_fallback.py` (9/9)
* [x] `test/test_agent_recovery.py` (10/10)
* [x] Regressie: 865 legacy + 58 nieuw = **923/923 = 0 gefaald**

---

## 🟢 FASE 13 — Home Assistant 2.0

**Status: ✅ VOLTOOID** (923/0 legacy + 46/46 nieuw)

* [x] Discovery / entity resolution / aliases / capabilities
* [x] `light`, `switch`, `cover`, `media_player`, `climate`, `sensor`, **`scene`**
* [x] Brightness / kleur / status
* [x] **Media & TV uitbreiden** — volume_up/down, media_play/pause/stop, volgende/vorige nummer, volume_set (0.0–1.0), select_source. Brain herkent "tv harder", "pauzeer op tv", "volgende nummer op tv", "zet tv op 40%"
* [x] **Scènes & routines bedienen** — `core/scenes.py` (SceneManager) slaat benoemde combinaties van tool-acties op in `config/ha_scenes.json`. Scene-activering via "activeer scene X", "zet X aan". Opgeslagen scenes uitgevoerd via Executor
* [x] **Automations voorstellen** — JARVIS stelt na een multi-actie automatisch voor om een scene op te slaan (`pending_choice` kind="scene_save_suggest"). Handmatig via "sla dit op als scene X"
* [x] **Shutters volledig** — `set_cover_position` toegevoegd aan cover defaults (niet meer alleen open/sluít, maar ook positie 0–100)
* [x] **`scene` domein** — SERVICE_DEFAULTS + SUPPORTED_DOMAINS + AI-tool-definitie + _extract_capabilities (ha_registry + home_assistant)
* [ ] Events
* [ ] Meer domains — lage prioriteit

**Regel:** geen aparte code per apparaat. Alles via registry + capabilities.

---

🟡 FASE 14 — Memory 2.0 + Obsidian

**Status: 🟡 BASIS BESTAAT**

* [x] Persistente memory, categorieën, update/delete
* [x] Memory Manager / veilige opslag
* [x] Usage tracking
* [x] Slim ophalen van relevante memory
* [x] Prioriteit + veroudering / decay
* [x] Conflicten oplossen
* [x] Context + long-term memory combineren
* [x] Obsidian Vault integratie
* [x] Bestaande memory migreren naar Obsidian
* [x] Memory-relaties en metadata
* [x] Memory 2.0 volledig testen

---

## 🔵 FASE 15 — Game-PC Agent

**Status: ⬜** — basis voor de mini-PC-architectuur.

> **Architectuurbesluit (Q&A):** de game-pc is de huidige pc. De mini-pc
> (Fase 19) wordt het brein waar JARVIS + AI draaien; de game-pc wordt op
> afstand bediend.

* [ ] Kleine server (commands ontvangen / uitvoeren / resultaat terug)
* [ ] Authentication + veilige verbinding
* [ ] PC-status online/offline
* [ ] Auto-start met Windows
* [ ] Alleen toegestane tools
* [ ] Games & programma's remote starten/sluiten/zoeken
* [ ] Status & telemetrie ophalen (temperatuur, GPU, systeeminfo)

---

## 🔵 FASE 16 — Proactive JARVIS

**Status: ⬜**

* [ ] Events ontvangen (PC- en HA-status monitoren)
* [ ] Triggers + conditions
* [ ] Proactieve suggesties/waarschuwingen
* [ ] **Timers & alarmen** (aftellen, herinneringen, melding op pc/iPad)
* [ ] **Dagplanning & vooruitkijken**
* [ ] **Agenda koppelen** (Google/iCloud): JARVIS kent je afspraken en mag daar reminders aan toevoegen
* [ ] **Energie & dagtaken** (auto-sleep na inactiviteit, 'goedemorgen'-starttaken)
* [ ] Automatisch handelen **alleen met toestemming**
* [ ] Quiet mode + notifications
* [ ] **Meldingsvormen:** gesproken meldingen + kort geluidje/badge op het dashboard

---

## 🔵 FASE 17 — Gesprek & Dialoog

**Status: ⬜** — de 'film-dialoog': vloeiend praten, onderbreken, natuurlijke wissels.

* [ ] **Latency omlaag**: streaming TTS + streaming LLM-output (JARVIS begint te praten terwijl hij denkt)
* [ ] **Barge-in**: je kunt JARVIS midden in een antwoord onderbreken, hij luistert meteen
* [ ] **Turn-taking**: JARVIS herkent het einde van je vraag en antwoordt zonder dat je elke beurt opnieuw "JARVIS" zegt
* [ ] **Gespreksflow**: dialoog over meerdere beurten met context uit Memory 2.0 (Fase 14)
* [ ] Luister-/denk-indicator (weten wanneer JARVIS actief is)
* [ ] Testen: latency meten, onderbreek-tests, multi-beurt gesprekken
* [ ] **Reactiesnelheid per taaksoort:** acties meteen, research mag langer duren
* [ ] **Meertalig:** Nederlands standaard, Engels opvraagbaar ("switch to English")
* [ ] **Vloeiende context-wissel:** snel wisselen tussen taken zonder context te verliezen

**Klaar als:** een natuurlijk gesprek voeren zonder onnatuurlijke pauzes of herhaald wake word.

---

## 🔵 FASE 18 — Dashboard

**Status: ⬜**

* [ ] Chat + voice
* [ ] **Status-tiles:** AI, PC, HA, lopende taak in één oogopslag
* [ ] **Bedieningsknoppen:** zelf programma's, scènes en volume bedienen
* [ ] **Activiteit-logboek:** wat JARVIS heeft uitgevoerd + resultaat
* [ ] **Visuele goedkeurings-popup:** gevaarlijke acties eerst goedkeuren via popup in plaats van hardop
* [ ] Logs, memory, routines, settings

---

## 🔵 FASE 19 — Mini-PC

**Status: ⬜** — pas als de software stabiel is. Mini-PC wordt **het brein**.

* [ ] JARVIS + AI + memory + agent installeren
* [ ] Auto-start + monitoring + backups + auto-recovery
* [ ] **JARVIS-slaapstand:** gaat zelf "slapen" na inactiviteit of op commando; wakker via wake word
* [ ] **Stem:** Piper lokaal met eigen getraind model (droog en kalm, film-getrouw)

---

## 🔵 FASE 20 — iPad Interface

**Status: ⬜** — wordt een **interface**, geen tweede AI.

* [ ] Verbinding, chat + voice
* [ ] **iPad als microfoon + interface** (alleen jij gebruikt JARVIS)
* [ ] **Spraak via wake word op iPad** — geen altijd-luisteren, geen push-to-talk
* [ ] Status-dashboard (AI, pc, HA, lopende taak)
* [ ] Routines starten
* [ ] Media & HA remote (volume, zones, apparaten)
* [ ] Notificaties ontvangen

---

## 🔴 FASE 21 — Film-JARVIS

**Status: ⬜ UITEINDELIJK DOEL**

> "JARVIS, maak mijn kamer klaar voor een film."

→ begrijpen → context → routine → plan → PC/HA/Web/UI → uitvoeren → controleren → klaar.

**Volledige ervaring (Q&A-besluit):**
* [ ] Praktisch: lichten dimmen, TV/Beam klaarzetten, volume goed, shutters dicht
* [ ] Sfeer: lampkleur passend, muziek op laag, sfeerverlichting
* [ ] Live narratie: JARVIS vertelt wat hij doet terwijl het gebeurt

---

## 🟣 FASE 22 — Gewenste Ervaring (Q&A-wensen)

**Status: ⬜ WENSEN** — wensen uit de Q&A-rondes 3-5 voor fases die **al klaar zijn** (✅). Omdat die fases niet meer worden omgezet, staan deze hier als verbeteren-later.

### Web & antwoorden (→ Fase 9 ✅)

* [ ] (gewenst) **Antwoordstijl:** kort antwoord + "wil je meer weten?" als optie; geen lange uitleg tenzij gevraagd
* [ ] (gewenst) **Bronnen:** alleen noemen bij belangrijke feiten (vergelijkingen, specs, weetjes)

---

## 🚀 TOEKOMST & ONDERZOEK

**Status: ⬜ IDEEËN**

*   [ ] **Authentieke JARVIS-stem:** Piper lokaal met eigen getraind model (of ElevenLabs) voor een film-getrouwe stem en persoonlijkheid — droog en kalm, zoals in de film.
*   [ ] **Self-Evolution:** Mogelijkheid voor JARVIS om zijn eigen code te analyseren, bugs te fixen of nieuwe functies te schrijven (met menselijke goedkeuring).
*   [ ] **Autonomous Optimization:** Zelflerende algoritmes voor betere tool-selectie en snellere planning.

---

## 🧭 De te volgen volgorde

```text
✅ 0-12   Basis (0), PC (1), Context (2), Media (3), Planner/Executor (4-5),
          Reliability (6), Agent (7/7B), Web (8-9), UI (10), Sonar (11),
          PC Control compleet (12)
🟡 13     HA 2.0: scenes, media, automations-voorstellen   ⬅ VOLGENDE
🟡 14     Memory 2.0
🔵 15     Game-PC Agent (game-pc = huidige pc; mini-pc = brein)
🔵 16     Proactive: timers, alarmen, dagplanning
🔵 17     Gesprek & Dialoog: streaming, barge-in, turn-taking
🔵 18     Dashboard
🔵 19     Mini-PC (brein)
🔵 20     iPad Interface
🔴 21     Film-JARVIS
🟣 22     Gewenste Ervaring (Q&A-wensen voor afgeronde fases, zoals Fase 9)
```

**Eerst (Q&A-prioriteit):** audit + fixes + volledige regressietest van het
huidige (`python tests/run_all_tests.py --all`) vóór nieuwe fases.

**Na elke grote groep functies → audit + fixes + volledige regressietest**
(`python tests/run_all_tests.py --all`).