# 🤖 JARVIS — Roadmap & Checklist

**Doel:** één definitieve lijst zodat je altijd weet: *waar ben ik, wat moet ik nu
bouwen, en wanneer mag ik door naar de volgende fase?*

> ⚠️ **Belangrijk:** deze lijst is gebaseerd op de daadwerkelijke codebase
> (geverifieerd), niet op aannames. Elke fase heeft een check in `tests/`.

**Laatst bijgewerkt:** 2026-10-30 — controle van alle open punten tegen de code: Fase 16, 21, 23, 24 en 25 klaar (24 en 25 live getest); agenda en dagplanning (Fase 16) zitten in Fase 23. Eerder: Q&A-ronde 6 (2026-10-28); Fase 19: software klaar, installatie op de mini-pc open.
**Teststatus:** `python -m pytest -q` (met `JARVIS_OLLAMA_DISABLED=1`) → 4151 passed, 2 skipped (2026-10-30); de 98 remote-agent-tests falen alleen met de lokale `.env` van de game-pc (ingestelde IP-lijst), niet door code.

---

## ✅ Besluiten & verwachtingen (Q&A)

Vastgelegd zodat scope en non-scope altijd helder zijn. **[x]** = gebouwd, **[ ]** = nog open (met de fase waar het staat); punten zonder vakje zijn vaste uitgangspunten.

### Uitgangspunten
* **Alles even belangrijk:** pc, slim huis, web en media zijn gelijkwaardig.
* **Prioriteit:** betrouwbaarheid van het huidige eerst — audit + regressie vóór nieuwe fases.
* **Privacy:** cloud mag, maar per functie bewust kiezen wat waar draait; alleen delen als het nodig is voor de taak.
* **Privacy bij een cloudmodel (2026-10-28):** het cloudmodel krijgt alleen de vraag zelf plus naam en aanspreekvorm. Nooit naar de cloud: mail, agenda, DM's, het geheugen over u, bestanden, het scherm, gespreksgeschiedenis, locatie en reistijden. Dat werk doet Ollama lokaal.
* **Online/offline:** online is prima, geen harde offline-eis.
* **Remote toegang:** alleen lokaal; geen externe bereikbaarheid.
* **Gebruikers:** alleen jij — geen stemherkenning; anderen krijgen gewoon hetzelfde antwoord.
* **Ruimtes:** centraal (één speaker/microfoon in de kamer); geen headset nodig.
* **Gebruiksmomenten:** vooral tijdens gamen (hands-free), 's avonds slim-huis, dagelijkse routines.
* **Stemming en sfeer:** altijd dezelfde stijl, geen stemming-detectie; sfeer stel je zelf in (niet automatisch).
* **Menselijkheid:** professioneel + karakter, geen volledig menselijke emoties.
* **Nood:** alleen melden, niet zelf bellen.
* **Bewust niet:** per-kanaal Sonar-sturing; volledig autonoom handelen; shutters/klimaat/sensoren geen prioriteit; echte hologrammen; constant sarcasme; spelletjes; demo-modus; basis-beveiliging/camera's; fysieke knop; vakantiemodus; achtergrondgeluiden; muziek-herkenning; scripts/commando-bestanden; automatische dagstart of begroeting; stage/werk bijhouden en console-modding (3DS/Wii) (2026-10-28).

### Gebouwd
* [x] **Autonomie:** veilige acties direct, goedkeuring bij gevaarlijke/onomkeerbare acties (Fase 6)
* [x] **Goedkeuring via visuele popup** op dashboard/iPad, niet hardop vragen (Fase 18)
* [x] **Aanspreken:** gewoon "JARVIS" (wake word)
* [x] **Foutafhandeling:** eerst zelf een fallback, pas daarna uitleg (Fase 12)
* [x] **Reactiesnelheid:** acties direct, research mag even duren; tussendoor melden dat hij denkt (Fase 17)
* [x] **Dialoog:** streaming, onderbreken en natuurlijke wissels (Fase 17)
* [x] **Context-switch:** vloeiend wisselen tussen taken, context blijft behouden (Fase 17)
* [x] **Meertalig:** Nederlands standaard, Engels opvraagbaar en de taal volgt uw vraag (Fase 17)
* [x] **Game-pc op afstand** bediend via de agent (Fase 15)
* [x] **iPad = microfoon + interface** (Fase 18 + 20)
* [x] **Slaap/standby:** slapen na inactiviteit of op commando, wakker via wake word (Fase 16B + 19 M4)
* [x] **Updates semi-auto:** melden met de wijzigingen, installeren na uw ja; de game-pc werkt mee bij (Fase 19 M6 + 21)
* [x] **Logging:** samenvattend logbestand + auditlog van belangrijke acties (Fase 6 + 18)
* [x] **Offline:** vriendelijk melden bij weg en terug, doorgaan met wat kan (Fase 19 M6)
* [x] **Film-modus = praktisch + narratie:** tv en app klaarzetten, pc stil, kort vertellen; licht en sfeer bewust niet (Fase 21)
* [x] **Karakter (basis):** subtiele easter eggs en een begroeting met dagdeel op vraag (Fase 21 M4)
* [x] **Dagstart en dagafsluiting:** korte samenvatting of vriendelijk woord — op vraag (Fase 16B/16C)
* [x] **Nachtmodus:** 's nachts alleen op wake word, geen ongevraagde meldingen (Fase 16)
* [x] **'s Nachts zachter:** stemvolume automatisch omlaag 23:00–07:00 (Fase 16)
* [x] **Herinneringen:** geluid én visueel — gesproken, Windows-toast en banner op de iPad (Fase 16 + 20 M6)
* [x] **Zorg-coaching:** pauze na 90 min, eten, late-avond-nudge (Fase 16B)
* [x] **Muziek:** leert uw smaak via Spotify en stelt gericht voor (Fase 21 M5)
* [x] **Tijdzone:** volgt de Windows-klok, zomertijd gaat vanzelf
* [x] **Externe koppelingen:** Gmail, iCloud-agenda en Discord-DM's, semi-auto, plus paneel Vandaag (Fase 23); Spotify is al klaar, de rest bewust niet
* [x] **Commando-correctie:** "Bedoelde u…?" bij een tik- of spraakfout, leert van uw ja (Fase 24)
* [x] **School:** deadlines met de stem invoeren + focusmodus (Fase 26)
* [x] **Dagelijks gemak:** vervolgvragen, routines op de iPad, "wil je meer weten?" en welzijn (water, ogen, pauze) (Fase 27)
* [x] **Slimmer brein:** Gemini (gratis laag, `gemini-3.1-flash-lite`) met Ollama als terugval en een privacy-poort: persoonlijke data blijft lokaal (Fase 25)

### Nog open
* [ ] **Mini-pc als brein,** 24/7 aan, beste audio binnen de mini-pc — software klaar, nog niet gekocht (budget ±€400; stand 2026-10-30), installatie als hij er is (Fase 19)
* [ ] **Karakter film-getrouw:** droog en kalm, subtiel sarcasme, bijnamen, weer-spin (karaktervolle weerberichten) en coole vragen ("waarom is de lucht blauw?") (Toekomst: stem) — _deels: het groter model is er (Gemini, Fase 25) met een droge, kalme persona en goede antwoorden op coole vragen; nog niet: sarcasme, bijnamen en de weer-spin_
* [ ] **Lab-assistent:** meedenken, brononderzoek, oplossingen en eigen initiatief veilig doorzetten (Toekomst) — _het groter model is er nu (Gemini, Fase 25); de functie zelf nog niet_
* [ ] **Leren van u:** van fouten leren, gebruikspatronen, proactief verbeteringen voorstellen, zelf nieuwe diensten/skills ontdekken (Fase 29 en 30) — _deels: verkeerd gezegde commando's leert hij na uw ja (Fase 24 M5)_

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

**Status: ✅ KLAAR** (geverifieerd: `core/retry.py`, `core/result_validation.py`, `pytest.ini`, `tests/test_edge_cases_stress.py`)

* [x] Fake-success voorkomen
* [x] Tool-resultaten controleren
* [x] Verkeerde / onbekende tool weigeren
* [x] Gevaarlijke acties herkennen + approval
* [x] Centrale testrunner — oorspronkelijk `tests/run_all_tests.py`, nu `pytest` (`pytest.ini` + GitHub Actions `.github/workflows/tests.yml`)
* [x] Volledige stress-test `tests/test_all_tools_stress.py` + `tests/test_speech_stress_new.py`
* [x] Randgevallen & rare spraak `tests/test_edge_cases_stress.py` (lege input, nonsens, fuzzy, execute_tool slechte args)
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

**Status: ✅ KLAAR** (geverifieerd: `actions/web.py`, `tests/test_web_fetch.py`)

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
* [x] Tests: 49 checks in `tests/test_web_fetch.py` (gemockte HTTP)

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
* [x] Tests: `tests/test_ui_automation.py` (49 checks, mock-based, geen live UI)
* [x] Stress-test: `tests/test_fase10_stress.py` (55 checks: routing, ambiguïteit, rare input, veiligheid)
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
* [x] **Tests**: `tests/test_audio.py` (26/26) + stress-test `tests/test_fase10_stress.py` uitgebreid met audio-routing (66/66) + regressie 882/882 = 0 gefaald

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

* [x] `tests/test_browser_reading.py` (10/10)
* [x] `tests/test_status_fallback.py` (9/9)
* [x] `tests/test_agent_recovery.py` (10/10)
* [x] Regressie: 865 legacy + 58 nieuw = **923/923 = 0 gefaald**

---

## 🟢 FASE 13 — Home Assistant 2.0

**Status: ✅ KLAAR** (923/0 legacy + 46/46 nieuw; suite laatste meting 1161 passed / 0 failed) — 2 items bewust open: Events, meer domains.

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

## 🟢 FASE 14 — Memory 2.0 + Obsidian

**Status: ✅ KLAAR** (geverifieerd: `memory/obsidian.py`, `memory/vault_import.py`, `memory/vault_export.py`, `memory/memory.py`, `core/context_memory.py` + 12 geheugen-tests)

> **NB:** export/import naar de Obsidian-vault is **handmatig** (bewust: geen watcher, geen timer, geen sync-lus — zie `memory/obsidian.py`).

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

## 🟢 FASE 15 — Game-PC Agent

**Status: ✅ KLAAR** — basis voor de mini-PC-architectuur.
(Suite laatste meting: 1545 passed, 2 skipped / 0 failed; `ruff check .` schoon.)
De LAN-verbinding is in de praktijk getest met de laptop als brein (Fase 18:
Game-PC-meters, media en toasts op de game-pc).

> **Architectuurbesluit (Q&A):** de game-pc is de huidige pc. De mini-pc
> (Fase 19) wordt het brein waar JARVIS + AI draaien; de game-pc wordt op
> afstand bediend.

* [x] Kleine server (commands ontvangen / uitvoeren / resultaat terug)
* [x] Authentication + veilige verbinding
* [x] PC-status online/offline
* [x] Auto-start met Windows
* [x] Alleen toegestane tools
* [x] Games & programma's remote starten/sluiten/zoeken
* [x] Status & telemetrie ophalen (temperatuur, GPU, systeeminfo)
* [x] IP-allowlist (`REMOTE_SERVER_ALLOWED_IPS`) + lockout na mislukte authenticaties
* [x] LAN-verbinding tussen brein en gaming-pc getest _(met de laptop als brein, Fase 18)_
* [x] Proactieve online/offline-meldingen (Fase 16A/16B: statuswijziging-triggers op HA + schijf)

---

## 🔵 FASE 16 — Proactive JARVIS

**Status: ✅ KLAAR** — 16A (kern: engine, meldingen, timers, quiet/nachtmodus), 16B (dagtaken & zorg-coaching) en 16C (externe bronnen: nieuws, reistijden, prijzen) zijn af; dagplanning en de agenda-koppeling zijn gebouwd in Fase 23 (M4/M5), de dashboard-badge in Fase 18.

* [x] Events ontvangen (PC- en HA-status monitoren — statuswijziging-triggers op HA-bereikbaarheid + schijfruimte)
* [x] Triggers + conditions (`config/proactive_rules.json`: tijd, interval, statuswijziging, actief; voorwaarden o.a. nachtmodus)
* [x] Proactieve suggesties/waarschuwingen (meldingenwachtrij met TTL, thread-safe)
* [x] **Timers & alarmen** (aftellen, herinneringen op de pc — gesproken + Windows-toast; iPad volgt in een latere fase)
* [x] **Dagplanning & vooruitkijken** — in Fase 23 M5: "wat staat er vandaag op de planning?" met afspraken, vertrektijd en belangrijke mail; herinnering kort vooraf met reistijd
* [x] **Agenda koppelen** (Google/iCloud): JARVIS kent je afspraken en mag daar reminders aan toevoegen — in Fase 23 M4: iCloud-agenda lezen, toevoegen en verplaatsen na ja
* [x] **Energie & dagtaken** (auto-sleep na 30 min inactiviteit; 'goedemorgen'-starttaken op aanvraag)
* [x] Automatic handling **alleen met toestemming** (16A stuurt uitsluitend meldingen; acties blijven via de bestaande confirmation-flow lopen)
* [x] Quiet mode + notifications (stille modus, auto-slaap, nachtmodus)
* [x] **Meldingsvormen:** gesproken meldingen + Windows-melding (toast); badge op het dashboard volgt in Fase 18
* [x] **Zorg-coaching:** pauze na 90 min achter de pc, lunch/diner-herinnering, late-avond-nudge
* [x] **Proactieve externe bronnen** (nieuws, reistijden, prijzen) - 16C: nieuws (NOS + Tweakers), reistijd (OpenStreetMap/Nominatim + OSRM) en prijzen (DuckDuckGo + Bol.com/Coolblue/Amazon.nl). Alleen op aanvraag: gewone zinnen en mededelingen starten niets; bij twijfel vraagt JARVIS eerst een ja/nee-vraag. Geen automatisch nieuws volgen (niet gewenst)
* [x] **Dagstart-samenvatting:** korte samenvatting van weer, openstaande herinneringen en (bij problemen) HA-status — op aanvraag
* [x] **Dagafsluiting:** overzicht van openstaande herinneringen + vriendelijk woord — op aanvraag
* [x] **Nachtmodus:** 's nachts alleen op wake word reageren, geen ongevraagde meldingen. Standen **auto/aan/uit** (handmatig, verloopt bij de volgende automatische overgang; "automatisch"/"auto"/"normaal"/"reset" zet hem terug). Een vraag naar de stand verandert niets en noemt alleen de stand + geldigheid.
* [x] **'s Nachts zachter:** stemvolume automatisch aanpassen (23:00–07:00)
* [x] **Gesprek-watchdog:** een blijven hangen gespreksvlag wordt na 10 minuten automatisch uitgezet; gebruikerstimers wachten nooit langer dan 30 minuten.

---

## 🔵 FASE 17 — Gesprek & Dialoog

**Status: ✅ KLAAR** — de 'film-dialoog': vloeiend praten, onderbreken, natuurlijke wissels. _Het chat-venster is gebouwd in Fase 18._

* [x] **Latency omlaag**: streaming TTS + streaming LLM-output (JARVIS begint te praten terwijl hij denkt)
* [x] **Barge-in**: je kunt JARVIS midden in een antwoord onderbreken, hij luistert meteen _(stem of sneltoets Ctrl+Alt+J)_
* [x] **Turn-taking**: JARVIS herkent het einde van je vraag en antwoordt zonder dat je elke beurt opnieuw "JARVIS" zegt — _deels: binnen één sessie luistert hij na het wake word tot ±15 s stilte door (`main.py`); tussen sessies is "JARVIS" nog nodig_
* [x] **Gespreksflow**: dialoog over meerdere beurten met context uit Memory 2.0 (Fase 14)
* [x] Luister-/denk-indicator (weten wanneer JARVIS actief is) _(console-statusregels, `status.py`)_
* [x] Testen: latency meten, onderbreek-tests, multi-beurt gesprekken
* [x] **Reactiesnelheid per taaksoort:** acties meteen, research mag langer duren
* [x] **Meertalig:** Nederlands standaard, Engels opvraagbaar ("switch to English", terug met "ga terug naar nederlands") en de taal volgt uw vraag (Fase 17)
* [x] **Vloeiende context-wissel:** snel wisselen tussen taken zonder context te verliezen _(context blijft over de taakwissel heen behouden)_
* [x] **Geluid:** automatisch dempen (ducking) van muziek/games als JARVIS praat
* [x] **Interface:** chat-venster om mee te lezen + logboek op het iPad-dashboard (Fase 18) _(zelf typen komt in Fase 20)_
* [x] **Meerdere taken:** sequentieel verwerken (niet parallel)
* [x] **Reactietijd:** altijd direct — tussendoor melden dat hij aan het denken is
* [x] **Niet begrepen:** blijven vragen tot het duidelijk is — _na een paar mislukkingen zegt hij vriendelijk dat het genoeg is; de sessie blijft open_
* [x] **Verkeerde info:** waarschuwen als hij denkt dat informatie onjuist is _(kort voorbehoud bij twijfel; bron noemen als het uit een webpagina kwam)_
* [x] **Taal per onderwerp:** automatisch schakelen afhankelijk van de vraag — _de wissel geldt alleen voor dát antwoord (taal én stem); de spraakherkenning blijft op de vaste taal, er wordt niets bewaard en bij de volgende vraag die niet overduidelijk Engels is (of aan het einde van de sessie) is JARVIS weer Nederlands. Standaard aan, uit te zetten met TAAL_AUTOMATISCH=0._

**Klaar als:** een natuurlijk gesprek voeren zonder onnatuurlijke pauzes of herhaald wake word.

---

## 🟢 FASE 18 — Dashboard (PWA voor de iPad)

**Status: ✅ KLAAR (2026-10-25)** — M1–M7 gebouwd en getest op de echte iPad. Een web-app (PWA)
voor de iPad, geen tweede AI: een interface naar het JARVIS-proces op het brein.
Design: `docs/fase18_dashboard_design.md` · handleiding + iPad-testlijst:
`docs/dashboard.md` · wireframe: `docs/fase18_wireframes/`.

> **Besloten:** PWA i.p.v. een native iOS-app (2026-10-20); één vast scherm met
> drie kolommen i.p.v. een vrij grid; slim-huis-status mét licht-presets i.p.v.
> "geen HA-tegels"; het auditlog + een meldingenbadge i.p.v. een losse
> notificatiehub; HTTPS + eenmalige koppelcode + kijk/bedien-rol (2026-10-22).

* [x] **Eén scherm**, drie kolommen; panelen aan/uit en volgorde via ⚙ (M5)
* [x] **JARVIS-status-orb:** 4-ring reactor, versnelt en klopt bij luisteren/spreken/denken, live via SSE
* [x] **Kernstatus:** verbinding/online-pil, nachtmodus, HA-bereikbaarheid
* [x] **Snelle acties:** media (vorige, play/pauze, volgende), slaapstand (altijd via goedkeuring), lampen en scènes
* [x] **Goedkeuring-popup:** oranje overlay met id + nonce, aftellen, strikte ja/nee; stem en dashboard nooit dubbel
* [x] **Meldingen:** badge + lijst met tijdstip en soort; gesproken melding + toast blijven bestaan (de toast verschijnt op PC_TARGET, dus op de game-pc)
* [x] **Basis media:** Spotify-volumeschuif + vorige/play-pauze/volgende, volgt PC_TARGET (alle uitvoerapparaten, ook Sonar)
* [x] **Slim huis:** status van de HA-apparaten; lampen en scènes tikbaar; schakelaars, mediaspelers (tv aan/uit) en knoppen (Wake-on-LAN) met goedkeuring; **+ Aanpassen** kiest de apparaten
* [x] **Timers, weer (HA `weather.*` of Open-Meteo), nachtmodus auto/aan/uit, gesprek meelezen, auditlog, pc-meters deze pc / game-pc**
* [x] **UI-thema:** altijd donker, film-stijl; lettertypen lokaal
* [x] **Aanspreking:** formeel ("Sir")
* [x] **Logs, memory, routines:** overzicht met tabbladen (alleen lezen) (M6)
* [x] **Beveiliging:** TLS met eigen CA + iPad-profiel, koppelcode, kijk/bedien-rol, Host/Origin-controle, rate-limit + lockout, strikte CSP, geen `innerHTML`, geen geheimen in log of audit
* [x] **Tests:** 2789 passed, 2 skipped, 0 failed (regressie groen); end-to-end over TLS + grep-controle op geheimen
* [x] **Test op de echte iPad** (lijst in `docs/dashboard.md` §5) — iPad Air 1, iOS 12.5.8, Safari én beginscherm-app

---

## 🔵 FASE 19 — Mini-PC

**Status: 🟡 software klaar (M1–M6), installatie op de mini-pc open** — Mini-PC wordt **het brein**. Handleiding: `docs/mini_pc_brein.md`.

> **Besloten (2026-10-25):** nieuwe Windows-mini-pc (nog niet gekocht: eerst op
> de laptop bouwen en testen); auto-login mag; dagelijkse backup bevat alles,
> ook geheimen, alleen op de eigen schijf; stem = bestaande Piper-stem afstellen.

* [x] **M1 — installatie en migratie:** `install_brein.ps1`, `brein_check.py` (dokter), `brein_export.py` / `brein_import.py` (CA gaat mee, iPad hoeft niets opnieuw)
* [ ] JARVIS + AI + memory + agent installeren _(op de echte mini-pc)_
* [x] **M2 — auto-start + monitoring + auto-recovery:** geplande taak "JARVIS Brein" met waakhond (herstart na crash of vastloper via hartslag, opgeven na 5x in 15 min), brein-status in het Systeem-paneel, melding na herstart
* [x] **M3 — backups:** elke nacht (04:00, ingehaald na uitval) een gecontroleerde zip met gegevens en geheimen naar `BACKUP_MAP`, 7 dagen + 4 weken bewaard, `brein_backup.py` / `brein_restore.py`, status in het Systeem-paneel en in `brein_check.py`
* [x] **M4 — JARVIS-slaapstand:** "ga slapen" en de auto-slaap zijn één slaapstand (alleen wake word, alleen timers/wekkers, AI-model uit het geheugen); wakker met "Hey JARVIS" ("Tot uw dienst, sir."); orb "SLAAPT"
* [x] **M5 — stem:** geen eigen training maar een bestaande Piper-stem afgesteld: `stem_proef.py` (pim, ronnie, rdh × 4 presets), `PIPER_NOISE_SCALE` / `PIPER_NOISE_W` / `PIPER_SPEAKER` instelbaar; **gekozen: `nl_BE-rdh-medium` met preset butler** (2026-10-25)
* [x] **M6 — updates:** dagelijks op GitHub kijken en melden met de wijzigingen; installeren alleen na uw ja (backup, fast-forward, pip alleen bij nieuwe requirements, herstart via de waakhond)
* [x] **M6 — verbinding verbroken:** game-pc-agent, Ollama en internet; melding bij weg en terug, opnieuw proberen met oplopende pauze (30 s → 5 min)

---

## 🔵 FASE 20 — iPad Interface

**Status: ✅ software klaar (M1–M6)** — een **interface**, geen tweede AI. Laatste iPad-check: meldingen (M6).

> **Besloten (2026-10-25):** spraak via een apart spraakpaneel in een Safari-tab
> (iOS 12 kan de microfoon niet in de beginscherm-app); het antwoord klinkt op de
> iPad (terugval: speaker van het brein); typen stil of hardop (instelbaar);
> extra bediening = lampen dimmen + kleur en routines starten.

* [x] **M1 — typen:** invoerveld in het gesprek-paneel, stil/hardop, één opdracht tegelijk (zelfde slot als de stem), `POST /api/command` (bedien-rol, max 300 tekens, audit); onder de orb wat JARVIS nu doet
* [x] **M3 — spraakproef:** `spraak-proef.html` in Safari: microfoon → 16 kHz → in stukjes naar het brein, dat niveau, haperingen, de wake-word-score en de spraakherkenning meet; testzin met de JARVIS-stem afspelen _(uitslag op de echte iPad bepaalt M4/M5)_
* [x] **M4 — iPad als microfoon:** spraakpaneel `spraak.html` (Safari) stuurt 16 kHz-geluid via één WebSocket naar het brein; wake word en luisteren ongewijzigd; `MIC_BRON` auto/ipad/pc; nooit twee microfoons door elkaar _(gemeten: wake word ±0,3 s na het uitspreken)_
* [x] **M5 — antwoord op de iPad:** de stem gaat over dezelfde WebSocket naar het spraakpaneel (naadloos per zin, ook de piep en meldingen); intussen geen microfoongeluid (geen echo); terugval op de speaker van het brein; onderbreken stopt ook de iPad
* [x] Verbinding, chat + voice _(M1 typen, M4 microfoon, M5 speaker)_
* [x] **iPad als microfoon + interface** (alleen jij gebruikt JARVIS) _(M4/M5: spraakpaneel in Safari)_
* [x] **Spraak via wake word op iPad** — geen push-to-talk; het wake word draait op het brein
* [x] Status-dashboard (AI, pc, HA, lopende taak) _(Fase 18 + M1: taak onder de orb)_
* [x] **M2 — routines starten:** paneel *Routines* (gaming / film / slapen) via `POST /api/routines/start`; stappen met goedkeuring vragen die
* [x] **M2 — lampen dimmen + kleur:** lampvenster met helderheid, warm/neutraal/koel wit en 8 kleuren, alleen wat de lamp kan (`POST /api/ha/lamp`); volume per app nu zonder ja/nee-vraag _(zones bewust niet)_
* [x] **M6 — notificaties ontvangen:** banner bovenin + zacht geluidje bij een nieuwe melding in de app (geluid na de eerste tik, 's nachts stil, uit te zetten); spraakpaneel spreekt meldingen uit _(echte push kan niet op iOS 12)_

---

## 🔵 FASE 21 — Film-JARVIS

**Status: ✅ KLAAR (2026-10-26)** — M1–M6 gebouwd en getest op de echte tv, game-pc, iPad en Spotify (testlijsten: `docs/film_modus.md`, `docs/spotify.md`, `docs/games.md`).

> "JARVIS, maak mijn kamer klaar voor een film."

→ begrijpen → context → routine → plan → PC/HA/Web/UI → uitvoeren → controleren → klaar.

> **Besloten (2026-10-25):** films kijken op de LG-tv (webOS, app op de tv) met
> Netflix, Disney+, Prime Video en YouTube. Film-modus = tv aan met de juiste app
> en de pc stil (Discord dempen, Spotify pauzeren); **niets met licht of
> gordijnen**; na de film alles terug zoals het was. Alleen starten als ik het
> zeg (geen automatische herkenning). Narratie film-achtig en kort per stap;
> karakter subtiel. Spotify lezen + afspelen (Premium, herzien 2026-10-26). Games via Steam en Riot (Valorant),
> zo nodig eerst de game-pc wekken (Wake-on-LAN). Begroeting alleen op vraag.

* [x] **M1 — film-modus 2.0:** tv aan (via HA, zo nodig Wake-on-LAN) en de juiste app openen; Discord dempen + Spotify pauzeren op de game-pc; vorige toestand onthouden en "film klaar" zet alles terug (Spotify niet vanzelf verder); de huidige routine `movie` raakt de lampen niet meer aan; narratie per stap
* [x] **M2 — tv bedienen met de stem:** pauze/verder, volume ("zet de tv op 20"), dempen, volgende aflevering (zo goed als de app toelaat), andere app openen, tv uit; laag risico, ook via chat en dashboard
* [x] **M3 — narratie + protocollen:** korte zinnen per stap bij álle routines (aan/uit te zetten, mislukte stap kort melden); eigen namen als "start protocol filmavond" in `config/routines.json`
* [x] **M4 — karakter:** "JARVIS, status" / "systeemcheck" geeft een begroeting met dagdeel en alleen echte problemen; een kleine set subtiele easter eggs ("ik ben Iron Man", "dank je, JARVIS")
* [x] **M5 — muzieksmaak via Spotify:** account koppelen (Web API, PKCE: toptracks, topartiesten, recent afgespeeld; sinds 2026-10-26 ook afspelen op de game-pc); tokens buiten git en nooit in de log; voorstellen op vraag en bij een modus, uit eigen smaak en playlists _(de aanbevelingsfunctie van Spotify is dicht voor nieuwe apps)_
* [x] **M6 — games met de stem:** Steam-bibliotheek lezen op de game-pc en starten ("start Euro Truck Simulator", ook bij een benaderde naam); Valorant via de Riot Client; staat de game-pc uit → Wake-on-LAN, wachten op de agent, dan starten
* [x] **Na de tests (2026-10-26):** routines vanaf het dashboard hardop; tv uit laag risico; "pauze" gaat naar de pc als de tv uit is; "slaap protocol" in beide volgordes; ja/nee-uitkomst in de chat; Spotify echt afspelen (apparaat wekken, nummer binnen zijn album); contextblok nooit in een antwoord; versie (commit + datum) in ⚙; ⚙ Opslaan wist de slim-huisknoppen niet meer
* [x] **Game-pc mee bijwerken:** na "installeer de update" werkt de agent op de game-pc zichzelf bij (alleen fast-forward, ondertekende route `/update`) en start opnieuw; ook los met "werk de game-pc bij"

**Bewust niet (2026-10-25):**
* ❌ Licht dimmen, lampkleur en sfeerverlichting bij een film of bij het gamen (geen automatisch dimmen)
* ❌ Automatisch herkennen dat een film of game begint; geen automatische gamemodus
* ❌ Begroeting bij elke start van JARVIS (alleen op vraag)
* ❌ Epic Games (nu niet gebruikt)

---

## 🟣 FASE 22 — Gewenste Ervaring (Q&A-wensen)

**Status: ⬜ WENSEN** — wensen uit de Q&A-rondes 3-5 voor fases die **al klaar zijn** (✅). Omdat die fases niet meer worden omgezet, staan deze hier als verbeteren-later.

### Web & antwoorden (→ Fase 9 ✅)

* [x] (gewenst, gebouwd in Fase 27 M2) **Antwoordstijl:** kort antwoord + "wil je meer weten?" als optie; geen lange uitleg tenzij gevraagd — _deels: "blijf kort: één of twee zinnen" zit al in de prompts (`core/ai.py`, `core/agent.py`); de "wil je meer weten?"-formule nog niet_
* [x] (gewenst) **Bronnen:** alleen noemen bij belangrijke feiten (vergelijkingen, specs, weetjes) — _sinds Fase 25: een gewoon antwoord noemt geen bron; "zoek op…" en vergelijkingen geven één korte bron ("(Bron: formule1.nl)")_

### iPad (→ Fase 20 ✅)

* [x] (gewenst, gebouwd in Fase 27 M1) **Routines maken en aanpassen in de instellingen:** in ⚙ op het dashboard snel een nieuwe routine maken (naam, protocolnaam, stappen kiezen zoals "open Discord", "lamp op 30%", "tv uit") of een bestaande aanpassen: naam, wat hij doet, de volgorde, de start- en eindzin en of hij vertrouwd is (zonder ja/nee). _Wens 2026-10-26; nu kan dat alleen in `config/routines.json` of met "bewaar dit als routine …"._

* [ ] (gewenst) **Eigen iOS-app** in plaats van de site: microfoon, speaker en dashboard in één app, ook op de achtergrond luisteren en echte pushmeldingen (op iOS 12 kan de site de microfoon alleen in Safari gebruiken, niet in de beginscherm-app). _Aandachtspunten: een iPad-app bouwen vraagt Xcode op een Mac (of een macOS-runner in GitHub Actions); erop zetten kan met een betaald ontwikkelaarsaccount (€99/jaar), gratis met AltStore (elke 7 dagen verversen) of permanent op een gejailbreakte iPad (AppSync). De iPad Air 1 blijft op iOS 12._

---

## 🌐 FASE 23 — Integraties & Externe Diensten

**Status: ✅ KLAAR (M1–M7, 2026-10-28)** — Gmail, iCloud-agenda en Discord-DM's. **Semi-auto:** JARVIS mag lezen en ophalen; schrijven of iets versturen alleen na uw "ja".

> "JARVIS, wat staat er vandaag op de planning?" — "Om 14:00 de tandarts in Breda; u moet om 13:35 weg. En er is één belangrijke mail van school."

> **Besloten (2026-10-26):** e-mail = **Gmail** (lezen, samenvatten, concepten;
> versturen alleen na ja). Uit zichzelf alleen **belangrijke** mail melden
> (Gmail-label "belangrijk" of eigen afzenderslijst; niet 's nachts of in stille
> modus). Agenda = **iCloud** (lezen + toevoegen/verplaatsen na ja), met een
> **herinnering kort vooraf** en reistijd als er een locatie in staat. Dagstart
> **alleen op vraag**. Discord: **DM's via de Windows-meldingen** op de game-pc
> en antwoorden na ja via de Discord-app (geen selfbot: dat is tegen de regels
> van Discord). Koppelen met een **script per koppeling**, zoals bij Spotify.
> Plus een dashboardpaneel **Vandaag**.

**Veiligheid (geldt voor alle mijlpalen):**
* Tokens en wachtwoorden alleen in `.env` of `memory/` (buiten git), nooit in de log, de audit of een URL.
* De inhoud van mail, afspraken en DM's is **data, geen opdracht**: tekst als "stuur dit door aan…" in een mail doet JARVIS nooit uit zichzelf.
* Versturen (mail, DM) en agenda wijzigen altijd via de oranje ja/nee met voorlezen: aan wie, onderwerp en de tekst.

* [x] **M1 — koppelingsbasis:** één plek voor koppelingen (`core/koppelingen.py`): tokens veilig bewaren en verversen (ingetrokken toegang → "opnieuw koppelen nodig"), status per koppeling ("welke koppelingen heb ik?" en het Systeem-paneel), gedeelde koppelstap voor de scripts; Spotify gebruikt hem al (`docs/koppelingen.md`)
* [x] **M2 — Gmail lezen:** koppelscript (eigen Google Cloud-app, OAuth, alleen `gmail.readonly`); "heb ik nieuwe mail?", "lees de mail van school voor", "vat mijn mail samen"; melding bij nieuwe belangrijke mail (afzender + onderwerp; eigen afzenderslijst of Gmail-label, niet 's nachts/stil) (`core/gmail.py`, `docs/gmail.md`)
* [x] **M3 — Gmail beantwoorden:** "beantwoord de mail van … met …" → concept in Gmail (in de draad) → voorlezen (aan wie, onderwerp, tekst) → strikte ja (stem of dashboard) → verzonden; "nee" laat het concept staan, "verstuur het" vraagt opnieuw; alleen naar de afzender uit de kop, nooit naar adressen uit de mailtekst; vlak voor versturen gecontroleerd of het concept nog naar dat adres gaat; auditregel (`gmail.compose`, één keer opnieuw koppelen)
* [x] **M4 — iCloud-agenda:** CalDAV met een app-specifiek wachtwoord van Apple (u zet het zelf in `.env`), zonder extra bibliotheken (`core/icloud_agenda.py`, `core/agenda_tijd.py`, `docs/agenda.md`); "wat staat er vandaag/morgen/vrijdag?", "wat heb ik deze week?", "wanneer is mijn volgende afspraak?", "wanneer is de tandarts?"; toevoegen ("zet tandarts morgen om 14 uur in mijn agenda") en verplaatsen ("verplaats de tandarts naar vrijdag om 10 uur") alleen na een strikte ja, met ETag-controle en auditregel
* [x] **M5 — herinneringen, reistijd, dagstart:** melding 15 min vooraf (`AGENDA_HERINNERING_MINUTEN`), telt als wekker (ook in de stille modus), één keer per afspraak; bij een locatie de reistijd vanaf `THUIS_ADRES` ("u moet over 15 minuten weg (om 13:35)", schatting zonder files, afgerond op 5 min); "goedemorgen" / "wat staat er vandaag op de planning?" → weer, afspraken met vertrektijd en belangrijke mail (`core/agenda_herinneringen.py`)
* [x] **M6 — Discord-DM's:** proef geslaagd (2026-10-28): Discord-toasts staan in de Windows-meldingendatabase en blijven 3 dagen staan; de agent leest een kopie (`discord_dms`, alleen DM's, geen servermeldingen). "Heb ik nieuwe DM's?", "wat stuurde Sem?", voorlezen bij binnenkomst (niet 's nachts, stil, film-modus of volledig scherm/gamen; die blijven "nieuw"), "antwoord Sem: ik kom zo" → strikte ja → getypt in de Discord-app (`discord_antwoord`: Ctrl+K, naam, controle venstertitel, anders niets versturen); alleen aan een afzender uit de meldingen; het taalmodel krijgt deze tools nooit (`ALLEEN_INTERN`); alleen als de game-pc aan staat (`core/discord_dms.py`, `actions/discord_meldingen.py`, `docs/discord.md`)
* [x] **M7 — dashboardpaneel Vandaag:** afspraken van vandaag (met vertrektijd), ongelezen belangrijke mail (afzender + onderwerp) en nieuwe Discord-DM's op de iPad; `GET /api/vandaag` (kijk-rol, cache 2 min, elke bron los), markeert niets als gelezen; in het midden op de plek van de auditlog (indeling versie 3, auditlog aan te zetten via ⚙; uitgezette panelen verdwijnen nu ook echt) (`core/vandaag.py`, dashboard 23.5)

**Bewust niet (2026-10-26):**
* ❌ Outlook, WhatsApp, Telegram, Slack, Reddit en extra nieuwsbronnen (nu niet nodig)
* ❌ Discord-bot in servers en kanalen lezen; een selfbot met uw account-token (verboden door Discord)
* ❌ Automatische dagstart bij de eerste opdracht of op een vaste tijd
* ❌ Koppelen via het dashboard (scripts op de laptop zijn veiliger)

---

## 🧩 FASE 24 — Commando-correctie ("Bedoelde u…?")

**Status: ✅ KLAAR (M1–M5, live getest 2026-10-29/30)** — een verkeerd gezegd of getypt commando wordt niet meer een gewone chatvraag. JARVIS snapt wat u bedoelde en vraagt het na.

> **Besloten (2026-10-28):** de correctie werkt vóór de laatste `ask_ai` **én**
> in de slim-huis-route (die geeft "lampe" al zelf aan de AI). Een gevaarlijke
> verbeterde actie krijgt **één samengevoegde vraag** met een strikte ja ("Bedoelde
> u: pc afsluiten? Dat sluit de pc nu af."), geen tweede bevestiging. Het
> AI-vangnet komt **nu op Ollama** (met tijdslimiet) en gebruikt in Fase 25
> vanzelf Gemini. Meerdere kandidaten: op de iPad **een knop per kandidaat** plus
> "Geen van deze".

> "JARVIS, zet de lampe in de wonkamer an." — "Bedoelde u: lampen in de woonkamer aan?" — "Ja." — "Gedaan, sir."

**Nu:** `process_command` (`core/brain.py`) loopt alle herkenners na; matcht er geen, dan gaat het commando naar `ask_ai` en krijgt u een praatje in plaats van de actie.

**Aanpak (combinatie):** vlak vóór `ask_ai` een extra stap, alleen als de zin op een commando lijkt (zet, open, speel, doe…), zodat gewone vragen nooit een "bedoelde u" krijgen.

* [x] **M1 — lokale fuzzy-match:** alleen bij een zin die op een commando lijkt (werkwoord vooraan, of kort en eindigend op aan/uit; vraagwoorden en "?" nooit); opvulwoorden weg ("doe die tv toch uit" → "doe tv uit"), korte spraakvormen terug ("an" → "aan"), elk onbekend woord vaag vergeleken (`rapidfuzz`, ook omgedraaide letters) met de woorden uit de voorbeeldcommando's en bekende namen (config, HA-apparaten/kamers/aliassen, startmenu; 5 min gecachet); woorden van 3 letters nooit vaag; daarna een score tegen de voorbeelden per herkenner; twijfel → meerdere kandidaten. Beslist en voert nog niets uit (`core/commando_correctie.py`, `config/commando_voorbeelden.json`)
* [x] **M2 — "Bedoelde u…?" via ja/nee:** pending-soort `commando_correctie` in `core/confirmation.py` (gewone verlooptijd, ook via het dashboard); vóór de laatste `ask_ai` en in de slim-huis-route (daar alleen bij echte tik-/spraakfouten, niet om opvulwoorden); vanaf score 70. "Ja" → het verbeterde commando gaat opnieuw door de keten (zonder nieuwe "bedoelde u": geen rondjes), "nee"/"geen van deze" → "Wat bedoelde u dan?", een ander commando laat de vraag vervallen; bij meerdere kandidaten een genummerd lijstje ("2", "de tweede"), op de iPad een knop per kandidaat plus "Geen van deze" (dashboard 24.2). Een gevaarlijk verbeterd commando krijgt sinds M4 één samengevoegde vraag
* [x] **M3 — AI-vangnet:** vindt M1 niets bij een zin die op een commando lijkt, dan kiest het taalmodel (via `core/llm.py`, nu Ollama; in Fase 25 vanzelf Gemini) het commando uit de voorbeelden plus de 40 namen die het meest op de zin lijken, als JSON met een zekerheid; alleen vóór de laatste `ask_ai`, niet in de slim-huis-route. Het antwoord telt alleen als het op een voorbeeld lijkt (≥ 85) en uitsluitend bekende woorden en namen bevat; tijdslimiet 4 s (`COMMANDO_CORRECTIE_AI_TIMEOUT`, uit te zetten met `COMMANDO_CORRECTIE_AI=0`). Een AI-gok wordt **nooit meteen uitgevoerd**, altijd eerst "Bedoelde u…?" (proef: qwen2.5:3b noemde "open dat chat programma" → "open chrome" 100% zeker). Het verzoek bevat alleen de zin, voorbeelden en namen van programma's/apparaten — bij Fase 25 M3 (privacy-poort) meenemen
* [x] **M4 — drempels en veiligheid:** één kandidaat, onschuldig, score ≥ 90 en hooguit één verbeterd woord → meteen doen met "Ik nam aan dat u 'open spotify' bedoelde." (alleen opvulwoorden weg → zonder die zin); twijfel, meerdere kandidaten of te veel gegok → "Bedoelde u…?"; onder 70 → gewone chat. Programma sluiten, typen, installeren en vergeten vragen altijd eerst. Afsluiten/herstarten/vergrendelen, verwijderen, prullenbak, mail, DM en agenda: **één samengevoegde vraag** — de route zet zijn eigen strikte ja/nee met alle details klaar en voert nog niets uit, met "Bedoelde u: herstart de pc?" ervoor; één strikte ja voert het uit (`risico()`/`beslis()` in `core/commando_correctie.py`)
* [x] **M5 — leren en logboek:** na een "ja" (stem of dashboard) onthoudt JARVIS de fout → het gekozen commando (zonder opvulwoorden en beleefde voorloop, dus ook "kun je ff open stem"); de volgende keer gaat het direct met "Ik nam aan dat u … bedoelde" — gevoelige en gevaarlijke commando's vragen nog steeds. Logboek per zin: hoe vaak, wat u bedoelde en de uitkomst (direct, geleerd, gevraagd, ja, nee, onbekend), hooguit 300 zinnen. "Welke commando's gaan vaak fout?" en "vergeet de geleerde commando's". Staat in `memory/commando_correcties.json` (buiten git)
* [x] **Testen:** typfouten, spraakfouten, gewone vragen (geen valse "bedoelde u"), gevaarlijke acties altijd met één strikte bevestiging, dashboardknoppen, AI-vangnet met nep-model, leren en logboek (`tests/test_fase24_m*.py`). Live met de stem getest; daarna gefixt: correctie ook op de game-pc ("Ik kan … niet vinden"), ruimere herkenning van het logboek en "open spotie" → spotify (`tests/test_fase24_game_pc.py`)

**Klaar als:** een commando met een tik- of spraakfout leidt tot de juiste actie (direct of na één "ja"), zonder dat gewone vragen er last van hebben.

---

## 🧠 FASE 25 — Gemini-brein

**Status: ✅ KLAAR (M1–M4, live getest 2026-10-30)** — de grootste sprong richting film-JARVIS: `qwen2.5:3b` is klein, dus gesprekken, meedenken en research blijven beperkt. Gemini wordt het brein, Ollama de terugval.

> **Besloten (2026-10-28):** Gemini met de gratis laag (geen Claude, geen
> wisselschakelaar nodig). **Slim gaat boven snel:** een seconde extra wachten
> mag als het antwoord beter is. **Privacy strikt:** Gemini krijgt alleen de vraag
> zelf plus uw naam en aanspreekvorm ("sir", formeel). Mail, agenda, DM's, het
> geheugen over u, bestanden, het scherm, gespreksgeschiedenis, locatie en
> reistijden gaan **nooit** naar Gemini; dat werk doet Ollama lokaal.

> **Besloten (2026-10-30):** Gemini doet **het meeste werk** (gesprek, kennis,
> research, acties en tools, het eerste agent-plan, de commando-correctie);
> Ollama doet alleen wat persoonlijke data nodig heeft en is de terugval.
> Gemini krijgt als geschiedenis **alleen eerdere Gemini-beurten**; bij "sluit
> hem" alleen de regel "laatste programma: X". Gemini kiest **alleen
> bedien-tools**; vragen die lees-tools nodig hebben (mail, agenda, DM's,
> bestanden, scherm, geheugen) gaan naar Ollama. **Geen toolresultaat gaat
> ooit naar Gemini**: herstel na een mislukte actie en herplannen doet Ollama.
> Research met **Google Zoeken** (na de daglimiet DuckDuckGo). Gratis laag
> akkoord, ook al mag Google die (niet-persoonlijke) vragen gebruiken.

* [x] **M1 — Gemini-koppeling:** `core/gemini.py` via `requests` (`generateContent` + streaming via SSE), antwoord in dezelfde vorm als Ollama (tekst en tool-calls), tools als `functionDeclarations`, JSON-modus, Google Zoeken met bronnen, denkniveau (standaard "low", valt terug als het model het niet kent); sleutel `GEMINI_API_KEY` alleen in `.env` en in de header (nooit URL of log); een toolresultaat weigert hij altijd; fouten per soort (geen sleutel, sleutel, netwerk, limiet, server, weigering, leeg) voor de terugval; model `gemini-3.8-flash` (in te stellen). Proberen: `python -m core.gemini "hallo"`. Nog nergens aangesloten
* [x] **M2 — terugval:** `core/llm.py` met `cloud=True`: eerst Gemini, bij elk probleem Ollama met precies dezelfde berichten (ook bij streaming, zolang er nog geen tekst is); zonder `cloud=True` gaat er nooit iets naar de cloud. Na een storing een pauze zodat niet elke vraag op een time-out wacht: netwerk 30 s, storing 60 s, limiet 5 min (of de wachttijd van Google), "limit: 0" (model niet gratis) 6 uur, sleutel 1 uur; een fout van alleen dit verzoek (weigering, leeg, privacy) zonder pauze. Eén gesproken melding bij uitval ("Gemini is even niet bereikbaar…" / "De gratis limiet van Gemini is op…") en één bij herstel; het Systeem-paneel toont "AI: Gemini ✓" of "AI: Ollama (reden, tot HH:MM)" (dashboard 24.4). Proefscript toont nu ook Google's eigen melding en de duur. Tests sturen nooit iets naar de echte Gemini
* [x] **M3 — privacy-poort en aansluiten:** `core/privacy_poort.py` beslist per vraag: mail, agenda, DM's, bestanden, scherm, geheugen ("wat is mijn…", "onthoud"), eerdere gesprekken, locatie/reistijd, "mijn …" (behalve bedienbare dingen als lampen of muziek), e-mail/postcode/telefoon en gevoelige geheugenwaarden (woonplaats, adres, school, werk, …) blijven lokaal; de rest gaat naar Gemini. Vlak vóór elke Gemini-aanroep controleert `core/llm.py` het hele verzoek nog eens (geen lokaal geheugenblok, bestandspad, e-mailadres, gevoelige waarde, toolresultaat of lees-tool, ook niet in toolbeschrijvingen); faalt dat, dan gaat er niets weg. Gemini krijgt een persona met alleen naam + aanspreekvorm en als geschiedenis alleen eerdere Gemini-beurten (max. 6, 15 min). Aangesloten: gewone vragen (ook streaming), de toolkeuze in `ask_ai` (alleen bedien-tools; bij "sluit hem" alleen de laatste programmanaam), het eerste agent-plan (zonder geheugen en zonder de live slim-huis-lijst), de commando-correctie, het vergelijken van twee bronnen, "zoek op…" en het opzoek-aanbod (Gemini met Google Zoeken en bron; anders DuckDuckGo). Herstel na een fout en herplannen blijven Ollama. Zonder sleutel of tijdens een storing werkt alles zoals vóór Fase 25. Standaardmodel nu `gemini-3.6-flash` (proef: 2,7 s), en bij een 503 één snelle herhaling
* [x] **M4 — testen:** bewijstest (`tests/test_fase25_m4_bewijs.py`) met een nep-Google op HTTP-niveau die elk verzoek opvangt en een geheugen vol geheimen (woonplaats, adres, school, werk, telefoon, e-mail, verjaardag, een bestandspad): 30 persoonlijke vragen veroorzaken via `ask_ai`, de agent, de commando-correctie en opzoeken **geen enkel** verzoek; gewone vragen en opdrachten (ook streaming, vervolgvragen en "sluit hem") wel, maar zonder geheim, sleutel in de URL, toolresultaat of niet-toegestane tool. Regressie: dezelfde vragen zonder Gemini (zoals vóór Fase 25) en met een storing (429/500/503, ook bij streaming) geven gewoon een antwoord via Ollama met de lokale context. De test vond twee fouten, nu opgelost: de eigen naam in een e-mailadres blokkeerde elk Gemini-verzoek, en vragen als "waar werk ik" of "wanneer ben ik jarig" gingen naar Gemini

**Klaar als:** gesprekken en research merkbaar slimmer zijn, JARVIS zonder internet gewoon doorwerkt op Ollama, en een test bewijst dat persoonlijke data lokaal blijft.

---

## 🎓 FASE 26 — School & Gaming

**Status: ✅ KLAAR (M1–M2, live getest 2026-10-30)** — kleine, direct nuttige functies voor de HBO-voorbereiding.

> **Besloten (2026-10-30):** deadlines als **hele-dag-afspraak** in de gewone
> iCloud-agenda, herinnering **de avond ervoor en de ochtend zelf**, tonen in het
> paneel **Vandaag** (niet bij de dagstart). Focusmodus met **optionele duur**,
> alleen Discord + DM's stil (JARVIS' eigen meldingen gaan door), met een
> **knop op het dashboard onder de nachtmodus**. "Wie is er online" **geschrapt**.
>
> **Besloten (2026-10-28):** deadlines **alleen met de stem invoeren** (niet uit
> de mail halen); focusmodus = **Discord dempen + DM's stil**, verder niets
> (geen games blokkeren, geen pomodoro, geen muziek). Vrienden online **alleen op
> vraag**, Steam (Riot heeft er geen open API voor). Stage/werk en
> console-modding bewust niet.

* [x] **M1 — deadlines:** "zet een deadline: verslag op vrijdag" (ook "deadline verslag vrijdag", "maak een deadline aan: …") → na een ja een hele-dag-afspraak "Deadline: Verslag" in de gewone iCloud-agenda; met een tijd ("vrijdag om 17 uur") een korte afspraak op dat tijdstip. "Welke deadlines heb ik (deze week / vandaag / morgen)?" en "wanneer moet het verslag af?". Herinnering de avond ervoor om 19:00 en de ochtend zelf om 08:00 (gewone meldingen: 's nachts en in de stille modus wachten ze). Het paneel Vandaag toont de deadlines van de komende 7 dagen, oranje als het vandaag of morgen af moet (dashboard 26.1) (`core/deadlines.py`)
* [x] **M2 — focusmodus:** "focusmodus aan" (tot "focusmodus uit") of "focusmodus voor 2 uur / anderhalf uur / 45 minuten" (stopt vanzelf en zegt dat). Discord op de game-pc gedempt (alleen als hij nog aan stond) en nieuwe DM's niet voorgelezen; ze blijven "nieuw". Bij uit: Discord terug zoals het was en "U heeft 3 nieuwe DM's, van Sem en Daan". JARVIS' eigen meldingen gaan door. Overleeft een herstart (`memory/focus_toestand.json`). "Staat de focusmodus aan?" / "hoe lang nog focus". Dashboard: knoppen Uit / Aan / 1 uur / 2 uur onder de nachtmodus met de resterende tijd (`POST /api/focus`, dashboard 26.2) (`core/focusmodus.py`)
* ~~**M3 — vrienden online**~~ — geschrapt (2026-10-30): hoeft niet meer

---

## 🧰 FASE 27 — Dagelijks gemak

**Status: ✅ KLAAR (M1–M4, live getest 2026-10-31)** — kleine dingen die elke dag helpen. Volgorde: M4 → M1 → M2 → M3.

> **Besloten (Q&A 2026-10-30):** volgorde "klein eerst". Welzijn **kort
> gesproken**, niet tijdens een film, een potje (volledig scherm), de
> focusmodus of 's nachts, en alleen als u achter de pc zit. Details per
> mijlpaal vragen we bij de start van de fase.
>
> **Besloten (Fase 27-vragen, 2026-10-30):** routines met een **vaste lijst én een
> vrije stap** ("zeg tegen JARVIS: …"), **verwijderen na bevestiging**. "Wil je
> meer weten?" **alleen als er meer te vertellen is**. Welzijn **hooguit één
> melding per uur** (water, ogen en pauze samen). Een vervolgvraag op een lokaal
> antwoord mag naar Gemini als dat antwoord **niet persoonlijk** is.

* [x] **M1 — routines op de iPad:** ⚙ → Routines: een lijst met "Bewerken" en "Nieuwe routine". In het venster: naam, protocolnamen, start- en eindzin, "vertrouwd" (zonder ja/nee) en de stappen, met ↑ ↓ ✕. Stappen: programma openen of sluiten, volume, lamp, tv aan/uit, Spotify, scène en "zeg tegen JARVIS…" (een zin die door de gewone keten gaat, met al zijn eigen bevestigingen; nieuwe interne tool `jarvis_opdracht`, nooit voor het taalmodel, en een routinestap start geen andere routinestap). Stappen uit oude routines (bijv. een slim-huis-tool) blijven precies zoals ze waren en kunnen alleen verplaatst of weggehaald worden; het dashboard kan nooit een willekeurige tool toevoegen. Verwijderen na "Zeker verwijderen?"; vóór elke wijziging een backup `routines.json.bak`. Alleen een bedien-apparaat mag wijzigen; elke wijziging staat in de auditlog (`core/routine_bewerken.py`, `GET /api/routines/bewerken`, `POST /api/routines/opslaan` en `/verwijder`, dashboard 27.1). Fix na de live test (dashboard 27.2): het instellingenvenster werd te lang en Opslaan/Annuleren vielen van het scherm; nu scrollt het venster zelf en blijven de knoppen onderin zichtbaar. Fix 2 (dashboard 27.3): alleen lange vensters (Instellingen en Routine) scrollen, en dan alleen het middenstuk, met een dunne scrollbalk in de JARVIS-kleur; gewone pop-ups scrollen niet. _Fase 22-wens "routines maken en aanpassen" hiermee klaar._
* [x] **M2 — "wil je meer weten?":** Gemini krijgt de instructie om alleen bij een kennis- of uitlegvraag waar het korte antwoord iets weglaat te eindigen met "Wilt u meer weten?" (niet bij acties, simpele feiten of een compleet antwoord; het kleine lokale model krijgt die instructie niet). Dat aanbod zet een open vervolgvraag klaar (M4): "ja", "graag", "vertel maar" of "leg het uit" geeft een uitleg van vier tot zes zinnen (via Gemini als de vraag dat mag, anders lokaal, met de vraag en het korte antwoord als context); "nee" laat het, een andere vraag laat het aanbod vervallen. "Vertel meer" werkt ook zonder aanbod. _Fase 22-wens "Antwoordstijl" hiermee klaar._
* [x] **M3 — welzijn compleet:** water na een uur, ogen na 45 minuten ("kijk even twintig seconden in de verte") en pauze na anderhalf uur aaneengesloten, **samen hooguit één melding per uur**; is er meer tegelijk aan de beurt, dan in één zin (de pauze omvat water en ogen). Alleen als u achter de pc zit (invoer in de laatste 5 minuten); tien minuten weg telt als pauze, een half uur weg begint alles opnieuw. Niet in een potje (volledig scherm op deze pc of, laatst gezien, op de game-pc), de focus- of film-modus, de stille modus of 's nachts. De oude pauze-regel in `config/proactive_rules.json` staat uit; welzijn doet de pauze nu. Uit te zetten met `WELZIJN_MELDEN=0` (`core/welzijn.py`)
* [x] **M4 — vervolgvragen beter afhandelen:** _melding 2026-10-30: "zet een deadline verslag" → "Wanneer moet dit af?" → "morgen om 10 uur" werd een losse zin, en "zet uit eten" sloot het programma "eten"._ Oorzaak: JARVIS koppelde zijn eigen wedervraag niet aan het volgende antwoord. Nu zet elke wedervraag een **open vraag** klaar (één beurt, hooguit een minuut) die het commando aanvult (`core/vervolg.py`): deadline (wanneer / waarvoor / allebei), agenda (hoe heet hij / wanneer), programma openen, sluiten, herstarten en status, map en bestand (ook op de game-pc), scène verwijderen en het Discord-antwoord. Een antwoord dat er niet bij past (een vraag, een nieuw commando) laat hem vervallen; "laat maar" annuleert. Bij een agenda- of deadlinenaam valt "zet"/"noteer" weg ("zet uit eten" → "Uit eten"), maar niet bij bediening ("zet de lamp aan"); "uit eten" is geen sluit-opdracht meer. Ook een kaal "sluit" of "open" vraagt nu terug, ook op de game-pc (fix na de live test: daar ging het eerst naar de AI en werd "Spotify" daarna een losse zin; "sluit het" sluit nog steeds het laatste programma). De vorige beurt van een vaste route (weer, zoeken, een actie) gaat mee als context: naar Ollama altijd, naar Gemini alleen als hij niet persoonlijk is

---

## ⏳ FASE 28 — Op de achtergrond en doorlopend gesprek

**Status: ✅ KLAAR (M1–M2, live getest 2026-10-31)**

> **Besloten (Q&A 2026-10-30):** als achtergrondtaak **alleen** "laat het weten
> als de game-pc klaar is met updaten / downloaden" (geen prijzen, pagina's of
> programma's in de gaten houden). Doorluisteren: **1 minuut** na het laatste
> antwoord, daarna weer het wake word.
>
> **Besloten (start Fase 28, 2026-10-31):** letten op Windows Update, Steam-downloads
> en Riot/Valorant (best effort). Wil Windows na de updates herstarten, dan meldt
> JARVIS dat en biedt hij de herstart aan (pas na uw ja). Melden zoals andere
> meldingen: gesproken + banner op de iPad, 's nachts en stil bewaard. Doorluisteren:
> hij luisterde te lang door (10 minuten) → terug naar 1 minuut.

* [x] **M1 — game-pc klaar:** "laat het me weten als de game-pc klaar is met updaten" kijkt meteen op de game-pc (nieuwe agent-actie `achtergrond_status`, alleen lezen): Windows Update (installeert? wil herstarten?), lopende Steam-downloads (appmanifest, met procent) en Riot (best effort: lokale API, anders schrijft de Riot Client veel naar schijf). Loopt er iets, dan kijkt een wachter elke minuut (`GAMEPC_KLAAR_CHECK_SECONDEN`) en meldt hij één keer als twee controles achter elkaar niets meer zien; na Windows Update met herstart: "Zal ik dat doen?" (power_confirm, pas na ja; 's nachts/stil alleen een hint). Ook: Steam, Riot/Valorant of Windows apart noemen, "is de game-pc al klaar met updaten?" en "stop met wachten op de game-pc". Overleeft een herstart van de game-pc; stopt na een uur onbereikbaar of zes uur bezig (`core/game_pc_klaar.py`, `actions/achtergrond.py`). _Riot is niet live getest tijdens een echte patch._
* [x] **M2 — doorlopend gesprek:** na een antwoord nog 1 minuut luisteren zonder "JARVIS"; daarna weer het wake word (`SESSIE_TIMEOUT_SECONDEN` standaard 60 in plaats van 600)

---

## 🧠 FASE 29 — Leren van u

**Status: ✅ KLAAR (M1–M4, 2026-10-31; voorstellen verschijnen na een paar dagen gebruik)** — dagelijkse gebruikspatronen leren en vooraf voorstellen; altijd een voorstel, nooit vanzelf doen. _Al gebouwd: verkeerd gezegde commando's leert hij na uw ja (Fase 24 M5)._

> **Besloten (start Fase 29, 2026-10-31):** alleen **lampen/slim huis** (op tijdstip)
> en **muziek** (Spotify-playlists op tijdstip en bij de focusmodus). Een patroon
> is **3 keer in 2 weken** rond hetzelfde tijdstip (±30 min), apart voor
> doordeweeks en weekend. Voorstel **gesproken + iPad, ja/nee**, een paar
> minuten vóór het gewone tijdstip; niet 's nachts, stil, in focus, film of een
> potje. **2 keer nee = 2 weken stil**; "stel dat nooit meer voor" zet het
> voorgoed uit. Beheer **met de stem** ("wat heb je van mij geleerd?") en als
> **lijst op de iPad**. Alles blijft lokaal; niets hiervan gaat naar de cloud.

* [x] **M1 — gebruikslog:** lokaal bijhouden wanneer u een lamp bedient (entiteit, aan/uit, helderheid in stappen van 10; elke gelukte lampactie via Home Assistant, ook vanaf de iPad), welke Spotify-playlist u draait (elk half uur "recent afgespeeld"; dezelfde playlist binnen een uur telt één keer) en wanneer u de focus aanzet; 30 dagen bewaard in `memory/patronen.json` (niet in git). Uit te zetten met `PATRONEN_LEREN=0` (`core/patronen.py`)
* [x] **M2 — voorstellen op tijdstip:** patronen vinden (3× in 2 weken, ±30 min, doordeweeks/weekend) en ±5 min vooraf vragen: "Rond deze tijd zet u meestal de bedlamp op 30 procent. Zal ik dat doen?"; ja voert uit, nee telt mee (2× nee = 2 weken stil). Eén keer per dag per patroon, niet als u het al deed of er al een vraag loopt; een ander commando laat het voorstel vallen
* [x] **M3 — muziek bij focus:** zet u de focus aan en draaide u daarbij vaker dezelfde playlist, dan: "Zal ik uw playlist … opzetten?"
* [x] **M4 — beheer:** "wat heb je van mij geleerd?", "stel dat nooit meer voor" / "vergeet dat patroon", en een lijst "Geleerde gewoontes" in Instellingen op de iPad (aan/uit, wissen na "Zeker wissen?"; `GET/POST /api/patronen`, dashboard 29.1)

---

## 🧬 FASE 30 — Self-Evolution

**Status: ✅ KLAAR (M1–M4, live getest 2026-10-31)**

> **Besloten (Q&A 2026-10-30):** JARVIS mag zelf een **branch maken en de tests
> draaien**, en installeert een verbetering **pas na uw ja**. Nooit direct op
> de hoofdversie.
>
> **Besloten (start Fase 30, 2026-10-31):** JARVIS past **alleen zinnen en
> herkenning** aan: `config/commando_voorbeelden.json` (voorbeeldzinnen,
> opvulwoorden, korte spraakvormen, namen), nooit Python-code of beveiliging.
> **Gemini** schrijft de wijziging ('s nachts, **hooguit 3 verzoeken** per ronde;
> bij een limiet of fout wordt het alleen een verbeterlijstje). Naar Gemini gaan
> alleen het voorbeeldenbestand en missers die de privacy-poort doorlaat.
> **Wekelijks** (zondagnacht) **en op verzoek** ("verbeter jezelf").
> Goedkeuren op de **iPad met uitleg + de wijziging** (met de stem een korte uitleg).

* [x] **M1 — voorstel maken:** de missers die vaker misgingen (commando-correctie, Fase 24) verzamelen, persoonlijke zinnen eruit (privacy-poort), Gemini om alleen aanvullingen op het voorbeeldenbestand vragen, die streng nakijken (alleen toevoegen, vaste velden, korte zinnen) en controleren dat minstens één misser er echt beter van wordt (en geen enkele slechter). Gebleken: alleen voorbeeldzinnen toevoegen helpt niet; de winst zit in `korte_vormen` (woord → bekend woord, ook spreektaal: "knal" → "zet") en opvulwoorden. Daarom past de commando-correctie korte vormen nu ook toe op het eerste woord (`core/zelfverbetering.py`)
* [x] **M2 — branch en tests:** de wijziging in een eigen git-worktree op een branch `jarvis/verbetering-…`, de volledige test-suite vóór en na; alleen bij geen nieuwe fouten wordt het een voorstel. Eén run duurt ±2,5 min (proef 2026-10-31: 0 fouten in een losse worktree)
* [x] **M3 — goedkeuren en installeren:** melding + iPad-venster (wat ging mis, welke zinnen erbij komen, tests geslaagd) met Installeren/Weigeren, ook "ja" met de stem; installeren = de branch samenvoegen, pushen en de voorbeelden opnieuw laden (geen herstart); "draai de laatste verbetering terug" (revert + push). Alleen fast-forward vanaf dezelfde versie; lukt pushen niet, dan wordt er niets geïnstalleerd. Commits staan op naam van JARVIS. Strikte ja (zoals afsluiten); "nee" laat hem wachten, "weiger de verbetering" gooit hem weg. iPad: Instellingen → Zelfverbetering (dashboard 30.1)
* [x] **M4 — wanneer:** zondagnacht vanzelf en "JARVIS, verbeter jezelf"; gaat er niets vaak mis, dan niets; lukt het niet, dan een verbeterlijstje op de iPad (om aan Claude Code te geven)

---

## 🗣️ FASE 31 — Tegen wie praat u?

**Status: 🟡 SOFTWARE KLAAR (M1–M3, 2026-10-31); live testen open**

> **Aanleiding:** binnen de minuut doorluisteren (Fase 28, M2) ziet JARVIS alles
> wat hij hoort als een opdracht. Praat u in uw kamer met iemand anders, dan
> moet hij dat snappen en niets doen.
>
> **Besloten (start Fase 31, 2026-10-31):** hoort hij in die minuut een zin voor
> iemand anders, dan **stopt hij meteen en helemaal stil** met doorluisteren
> (daarna is "JARVIS" weer nodig). Beslissen met **vaste regels + lokaal AI**
> (Ollama) bij twijfel; niets naar de cloud; bij twijfel niets doen. Zelf
> "uit" zetten met een **knop op de iPad** ("In gesprek": alleen nog met
> "JARVIS" ervoor) en **vanzelf tijdens een Discord-call** op de game-pc.

* [x] **M1 — gericht aan JARVIS?** Elke zin zonder "JARVIS" ná de eerste in de sessie eerst beoordelen: opdracht, vervolgvraag of antwoord op zijn vraag → uitvoeren; gesprek met iemand anders → stil stoppen. Regels eerst (commando-werkwoord, "en morgen?", open vraag of ja/nee → voor JARVIS; "haha", "kom je…", "mam" → niet), Ollama bij twijfel (lokaal, 3 s), daarna niets doen. Ook onverstaanbaar ná een antwoord stopt stil. Uit te zetten met `GESPREK_HERKENNEN=0` (`core/gericht.py`)
* [x] **M2 — "In gesprek" op de iPad:** een knop onder Focus; zolang hij aan staat, luistert JARVIS na een antwoord niet door (alleen met "JARVIS" ervoor); een open vraag of ja/nee van JARVIS gaat wel voor (`core/gespreksmodus.py`, dashboard 31.1)
* [x] **M3 — Discord-call:** gebruikt Discord op de game-pc (of deze pc) nu de microfoon (Windows houdt dat bij), dan geldt "In gesprek" vanzelf; de iPad laat het zien. Bron: `CapabilityAccessManager\ConsentStore\microphone` (`LastUsedTimeStop = 0`), alleen lezen; de game-pc meldt het mee bij de Discord-controle van elke minuut (`DISCORD_MELDEN`), 3 minuten geldig

---

## 🚀 TOEKOMST & ONDERZOEK

**Status: ⬜ IDEEËN**

> **Q&A 2026-10-28:** Gemini als brein is een eigen fase geworden (Fase 25).
> **Q&A 2026-10-30:** routines op de iPad, "wil je meer weten?", welzijn,
> achtergrondtaken, doorlopend gesprek, leren van patronen en Self-Evolution
> zijn Fase 27–30 geworden. De ideeën hieronder zijn gewenst tenzij anders vermeld.

**Gewenst**
*   [ ] **Lokale spraakherkenning:** Whisper (faster-whisper) op de mini-pc in plaats van Google STT: vaak beter in het Nederlands, privé en een voorspelbare snelheid.
*   [ ] **Zien (scherm begrijpen):** met een **lokaal** vision-model (op de mini-pc) kijken wat er op het scherm staat: "wat zie je op mijn scherm?", "wat betekent deze foutmelding?", "wie wint dit potje?". _Het scherm gaat nooit naar de cloud (privacybesluit 2026-10-28); camera's blijven bewust buiten de scope._
*   **Taken op de achtergrond** → Fase 28 (alleen "game-pc klaar"); prijzen en pagina's in de gaten houden: niet gekozen
*   **Welzijn compleet** → Fase 27
*   **Routines maken op de iPad** → Fase 27
*   **Leren van u** → Fase 29
*   **Self-Evolution** → Fase 30 (branch + tests, na uw ja)
*   [ ] **Eigen iOS-app:** zie Fase 22. _Nog open: AltStore, jailbreak + AppSync of een ontwikkelaarsaccount._

**Nog niet gekozen (laten staan)**
*   [ ] **Authentieke JARVIS-stem:** Piper lokaal met eigen getraind model voor een film-getrouwe stem — droog en kalm, zoals in de film. _ElevenLabs valt af (stem/tekst naar de cloud)._
*   [ ] **Autonomous Optimization:** Zelflerende algoritmes voor betere tool-selectie en snellere planning.
*   **Echt doorlopend gesprek** → Fase 28 (1 minuut doorluisteren); gesprekken met anderen negeren → Fase 31
*   [ ] **Karakter film-getrouw** en **Lab-assistent:** niet gekozen in de Q&A van 2026-10-30; laten staan.

> **Mini-pc en lokaal werk:** met Ollama (terugval), Whisper en een lokaal
> vision-model op één apparaat is 32 GB RAM verstandig; binnen ±€400 krap maar
> haalbaar met een Ryzen-mini-pc. Keuze bij de aankoop (Fase 19).

---

## 🧭 De te volgen volgorde

```text
✅ 0-15   Basis (0), PC (1), Context (2), Media (3), Planner/Executor (4-5),
          Reliability (6), Agent (7/7B), Web (8-9), UI (10), Sonar (11),
          PC Control compleet (12), HA 2.0 (13), Memory 2.0 + Obsidian (14),
          Game-PC Agent (15)
✅ 16     Proactive (dagplanning en agenda via Fase 23)
✅ 17     Gesprek & Dialoog: streaming, barge-in, turn-taking
✅ 18     Dashboard (PWA voor de iPad)
🟡 19     Mini-PC (brein) — software klaar, binnenkort kopen (±€400), installatie open
✅ 20     iPad Interface — M1–M6 klaar (typen, routines, lampen, iPad als microfoon en speaker, meldingen)
✅ 21     Film-JARVIS — film-modus, tv, narratie, karakter, Spotify, games (getest 2026-10-26)
🟣 22     Gewenste Ervaring (Q&A-wensen voor afgeronde fases, zoals Fase 9)
✅ 23     Integraties — Gmail, iCloud-agenda, herinneringen, Discord-DM's, paneel Vandaag
✅ 24     Commando-correctie: "Bedoelde u…?" bij een verkeerd commando
✅ 25     Gemini-brein met Ollama-terugval en strikte privacy-poort
✅ 26     School: deadlines en focusmodus
✅ 27     Dagelijks gemak: vervolgvragen, routines op de iPad, "wil je meer weten?", welzijn
✅ 28     Op de achtergrond (game-pc klaar) en doorlopend gesprek (1 min)
✅ 29     Leren van u (lampen en muziek, alleen voorstellen)
✅ 30     Self-Evolution (zinnen en herkenning; branch + tests, na uw ja)
🟡 31     Tegen wie praat u? (gesprekken met anderen negeren) — software klaar
```

**Eerst (Q&A-prioriteit):** audit + fixes + volledige regressietest van het
huidige (`python -m pytest -q`) vóór nieuwe fases.

**Na elke grote groep functies → audit + fixes + volledige regressietest**
(`python -m pytest -q`; CI draait ruff + pytest via `.github/workflows/tests.yml`).