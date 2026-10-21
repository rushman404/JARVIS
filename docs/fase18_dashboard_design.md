# Fase 18 — Dashboard (iPad) — Design

**Status:** ontwerp (nog niet gebouwd)
**Laatst bijgewerkt:** 2026-10-20
**Bouwpakket (besloten):** server + dashboard samen
**Technologie (besloten):** PWA / web-app
**Design-vorm (besloten):** dit document + HTML-wireframes

> Deze ontwerpbeslissingen komen uit de Q&A met de gebruiker op 2026-10-20:
> PWA/web-app, "beide" design-vorm, en "server + dashboard samen".

---

## 1. Doel

Eén scherm op de iPad waarop u in één oogopslag ziet wat er speelt en met één
tik kunt bedienen: JARVIS-status, notificaties, timers, routines, media,
PC-status, logboek en instellingen. Geen tweede AI — het is een *interface*
 naar het bestaande JARVIS-proces.

## 2. Scope

### 2.1 In Fase 18 (dit pakket)

* **Eén scherm, geen navigatie:** drie vaste kolommen — links status/timers/
  weer/nachtmodus, midden gesprek + auditlog, rechts systeem/media/slim huis.
* **Widget-stijl:** panelen met dunne cyaan lijn, vaste inhoud per kolom.
* **Status:** kern (internet, HA-status, JARVIS-actief), zelf uitbreidbaar.
* **Spraakstatus-orb:** twee draaiende ringen met gloeiende kern; de status
  wisselt tussen in rust / luistert / denkt / spreekt.
* **Snelle actie-knoppen:** volume, slaapstand, lichten (presets).
* **Auditlog in plaats van een aparte notificatiehub:** tijd, actie,
  risico-label en resultaat per regel.
* **Basis media-besturing:** volume + play/pauze (geen playlist-beheer).
* **Slim huis-tegels:** tonen status en presets; volledige HA-bediening komt
  in Fase 20 (besluit: nu alleen status + licht-presets).
* **Goedkeuring-overlay:** gevaarlijke acties vragen hier bevestiging.
* **UI-thema:** altijd donker (dark mode, film-stijl).
* **Aanspreking:** formeel — JARVIS spreekt u aan als "Sir".
* **Aanpassen:** voorlopig vast; de widget-voorkeuren staan al in
  `config/dashboard.json` (instellingenscherm volgt later).
* **Logs, memory, routines, settings** via de API; alleen het auditlog is nu
  zichtbaar.
* **Lokale API-server** in het JARVIS-proces + live-updates (SSE).

### 2.2 Later (Fase 20 — iPad Interface)

* Chat/tekst met JARVIS, spraak via wake word op de iPad, push-to-talk.
* Volledige remote: routines starten, media & HA per zone/apparaat.
* Het dashboard blijft bestaan; Fase 20 voegt het chat/voice-gedeelte toe.

> **Belangrijk:** de server die in Fase 18 ontstaat, is *ook* de fundering voor
> Fase 20. Daarom houden we de API generiek (`/api/*`) en stoppen we de logica
> in een testbare klasse (zie §4), niet in de HTTP-handler.

## 3. Technologie & architectuur

### 3.1 Waarom een PWA

* Bouwen en testen kan **hier** (geen Mac/Xcode nodig).
* Op de iPad: Safari → "Toevoegen aan beginscherm" → volledig scherm, eigen
  icoon, lijkt op een native app.
* Eén codebase, direct te previewen in de browser tijdens het bouwen.
* Later desgewenst een native SwiftUI-app met hetzelfde ontwerp.

### 3.2 Diagram

```text
┌──────────────────────────┐      Wi-Fi / LAN       ┌───────────────────────────────┐
│  iPad — PWA              │  ────────────────────▶ │  JARVIS-proces (deze pc)      │
│  dashboard/static/       │   HTTP + SSE          │  dashboard/server.py          │
│   index.html             │ ◀────────────────────  │   /api/*  (JSON)              │
│   app.js  (EventSource)  │   JSON + events        │   /api/events (SSE)           │
│   manifest + sw.js       │                        │          │                    │
└──────────────────────────┘                        │          ▼                    │
                                                    │  core/  proactive, timers,    │
                                                    │         routines, media,      │
                                                    │         power, memory,        │
                                                    │         status, ha, executor  │
                                                    └───────────────────────────────┘
```

### 3.3 Live-updates

De iPad is een *client*. Voor live-gedrag (bol klopt, meldingen verschijnen,
timer tikt mee) gebruiken we **SSE** (Server-Sent Events, `EventSource`):

* Eén lange verbinding: `GET /api/events`.
* De server pusht events: `status`, `melding`, `timer`, `media`, `pc`, `ha`.
* Veiliger en eenvoudiger dan WebSocket (éénrichting, werkt over HTTP, geen
  extra dependency).
* Browsers die SSE niet willen: terugval op polling van `/api/status` elke 2 s.

### 3.4 De iPad bereikt het LAN

De iPad zit op hetzelfde Wi-Fi als de pc. De server bindt dus **niet** op
`127.0.0.1` maar op het LAN (`0.0.0.0`), met beveiliging (zie §10). Daarom
hergebruiken we de patroon uit Fase 15 (`remote/allowlist.py` + token).

## 4. Bestandstructuur (voorstel)

```text
dashboard/
  server.py            # HTTP + SSE; logica in DashboardAPI (testbaar zonder HTTP)
  static/
    index.html         # het dashboard (één scherm, uit de wireframe overgenomen)
    styles.css         # thema (in de wireframe nog inline; hier gesplitst)
    app.js             # laad data, EventSource, render widgets
    manifest.webmanifest
    sw.js              # offline-cache (PWA)
    icons/             # 192 / 512 px
config/
  dashboard.json       # welke widgets, welke volgorde, instellingen
tests/
  test_fase18_server.py
  test_fase18_dashboard.py
docs/
  fase18_dashboard_design.md      # dit document
  fase18_wireframes/              # HTML-wireframes (zie §8)
    index.html                    # HET dashboard (referentie-ontwerp)
    oud/                          # eerdere wireframe-schermen, ter referentie
```

**Scheiding:** `DashboardAPI` in `dashboard/server.py` bevat alle logica en is
direct te testen met pytest (net als `remote/server.py` → `RemoteAgent`). De
HTTP-handler is alleen verpakking. `config/dashboard.json` bevat de
widget-voorkeuren (geen code).

## 5. API-contract

Basis-URL: `http://<pc-ip>:8765` (poort via `DASHBOARD_PORT`).
Alle endpoints geven JSON. Authorisatie: `Authorization: Bearer <DASHBOARD_TOKEN>`
(alleen als token ingesteld; zie §10).

### Status & health

| Methode | Pad | Geeft |
|---|---|---|
| GET | `/api/health` | `{ ok, versie }` |
| GET | `/api/status` | `{ tijd, actief, luistert, denkt, spreekt, in_gesprek, nachtmodus, auto_slaap, quiet, pc_target }` |

### Notificaties

| Methode | Pad | Geeft/doet |
|---|---|---|
| GET | `/api/notifications` | `{ aantal, ongelezen, meldingen:[{ id, tekst, bron, prioriteit, aangemaakt_op, verloopt_op, gelezen }] }` |
| POST | `/api/notifications/lees` | `{ ids?: [..] }` → markeer gelezen |
| POST | `/api/notifications/legen` | wis de hub |

### Timers

| Methode | Pad | Geeft/doet |
|---|---|---|
| GET | `/api/timers` | `[{ id, naam, resterend_seconden, af_loopt_op }]` |
| POST | `/api/timers` | `{ naam, seconden }` → nieuwe timer |
| DELETE | `/api/timers/{id}` | annuleer |

### Routines & PC-status

| Methode | Pad | Geeft |
|---|---|---|
| GET | `/api/routines` | `[{ naam, beschrijving, usage_count, laatst_gebruikt }]` |
| GET | `/api/scenes` | `[{ naam, beschrijving }]` |
| GET | `/api/pc-status` | systeem/audio/browser (van `actions/status.get_pc_status()`) |

### Media & acties

| Methode | Pad | Doet |
|---|---|---|
| GET | `/api/media` | `{ volume, gedempt, speelt }` |
| POST | `/api/media` | `{ actie, waarde? }` — `volume`, `dempen`, `play_pauze`, `volgende`, `vorige`, `stop` |
| POST | `/api/power` | `{ actie }` — `slaap`, `vergrendel`, `afsluiten`, `herstart` |

### Home Assistant (alleen status in Fase 18)

| Methode | Pad | Geeft |
|---|---|---|
| GET | `/api/ha/status` | `{ beschikbaar, aantal_entiteiten, problemen }` |

> HA-bediening (aan/uit, dimmen) is **Fase 20**. In Fase 18 toont de app alleen
> of HA bereikbaar is.

### Overige tegels

| Methode | Pad | Geeft |
|---|---|---|
| GET | `/api/memory` | overzicht van memory (categorieën + recent) |
| GET | `/api/logs?regels=200` | laatste logregels uit `logs/jarvis.log` |
| GET | `/api/widgets` | huidige widget-config |
| PUT | `/api/widgets` | sla widget-config op (`config/dashboard.json`) |
| GET | `/api/settings` / PUT | `/api/settings` — thema, taal, token, meldingen |

### Live

| Methode | Pad | Betekenis |
|---|---|---|
| GET | `/api/events` | SSE-stream: `status`, `melding`, `timer`, `media`, `pc`, `ha` |

### Later (Fase 20, nu al gereserveerd)

| Methode | Pad | Betekenis |
|---|---|---|
| POST | `/api/command` | stuur een tekstopdracht naar `core.brain.process_command` |

## 6. Widget-catalogus

| # | Tegel | Toont | Bron (huidige code) | Tik-actie |
|---|---|---|---|---|
| 1 | **Spraakstatus-orb** | 2 draaiende ringen + gloeiende kern; status rust/luistert/denkt/spreekt | `/api/status` (`speak.is_speaking()`, `proactive.is_in_gesprek()`) | status wisselen (demo) |
| 2 | **Status (kern)** | internet, HA-status, JARVIS-actief | `/api/status`, `/api/ha/status` | – |
| 3 | **Snelle acties** | volume-slider, slaapstand, licht-presets, play/pauze | `/api/media`, `/api/power` | direct uitvoeren |
| 4 | **Notificaties** | laatste 3 meldingen | `/api/notifications` | open hub |
| 5 | **Media** | volume + play/pauze | `/api/media` | bedienen |
| 6 | **Timers** | actieve timers + aftellen | `/api/timers` | toevoegen/annuleren |
| 7 | **Routines** | gaming / movie / sleep | `/api/routines` | starten (Fase 20) |
| 8 | **PC-status** | cpu / ram / schijf | `/api/pc-status` | verversen |
| 9 | **Logboek** | laatste regels | `/api/logs` | open volledig log |
| 10 | **Memory** | recent/onlangs gebruikt | `/api/memory` | open overzicht |
| 11 | **Instellingen** | widgets, thema, taal | `/api/settings` | open instellingen |

**Herschikken:** het grid is een 2-koloms grid (portret) / 3–4 koloms
(landschap). Tegels zijn sleepbaar (drag & drop) en de volgorde wordt opgeslagen
in `config/dashboard.json` (instellingenscherm volgt later; staat nu niet in de
wireframe — zie §7.6).

## 7. Schermontwerp

### 7.1 Hoofdscherm (één scherm, 3 kolommen)

* Bovenaan een **header**: JARVIS-logo (Orbitron), statuspil
  `● Online · wake word "Hey JARVIS"`, rechts de **klok** (live, elk
  kwartier ververst) met de datum eronder.
* Daaronder drie kolommen in een 1180×820 iPad-frame:
  * **Links (290px):** Spraakstatus-orb → Timers & wekkers → Weer → Nachtmodus.
  * **Midden (flex):** Gesprek (chatlog + invoerveld + mic) → Auditlog.
  * **Rechts (290px):** Systeem (Deze pc / Game-PC + meters) → Media & volume →
    Slim huis.
* **Geen zijbalk-navigatie en geen aparte schermen** — alles zit op dit ene
  overzicht (besluit; zie §7.6 en §8).
* Achtergrond bijna-zwart; panelen met dunne cyaan lijn en ronde hoeken.

### 7.2 Spraakstatus-orb (linksboven)

* 160px **JARVIS-AI-reactor**: kern met **"JARVIS"** / **"AI ASSISTANT"** en
  een audiogolf, omringd door **4 concentrische ringen** met draaiende
  boogsegmenten (22 / 14 / 9 / 6 s, afwisselend linksom en rechtsom) plus
  1 fijn doorlopend ringetje. Overgenomen uit de eerdere versie, verkleind
  van 340px naar 160px zodat hij in het linkerpaneel past.
* **Kloppen bij activiteit:** bij LUISTERT en SPREEKT versnellen de ringen
  naar 8 / 5 / 3,5 / 2,2 s, klopt de kern (scale 1 → 1,05) en danst de
  audiogolf; bij DENKT NA 14 / 9 / 6 / 4 s met een langzamere klop.
* Alles in **currentColor**, dus de kleur volgt automatisch de status.
* Vier statussen, elk met eigen kleur en ondertitel:
  * **IN RUST** (`#5f93ab`) — "Wacht op "Hey JARVIS""
  * **LUISTERT** (cyaan) — "Spreek je opdracht in"
  * **DENKT NA** (oranje) — "Plan maken en uitvoeren"
  * **SPREEKT** (`#bff3ff`) — bijv. "Muziek is tijdelijk gedempt"
* In de wireframe wisselt **tikken op de orb** de status (demo); in het echte
  dashboard komt dit uit `speak.is_speaking()`, `proactive.is_in_gesprek()`
  en `status.is_gestart()` / `heeft_gepraat()`.

### 7.3 Gesprek & auditlog (midden)

* **Gesprek:** chatlog — gebruikersberichten rechts (cyaan vlak), JARVIS-
  antwoorden links (neutraal vlak), met **bevestigings-tag**
  (`✓ BEVESTIGD · 2 ACTIES`). Onderaan een invoerveld
  ("Zeg "Hey JARVIS" of typ een opdracht…") met ronde mic-knop.
* **Auditlog:** vaste hoogte (196px), rijen van
  **tijd · actie · risico-label (LOW/HIGH) · resultaat**
  (✓ gelukt / wacht… / geannuleerd). Vervangt in Fase 18 de losse
  notificatiehub; bron is het auditlog (`core.audit`) + laatste meldingen.

### 7.4 Rechterkolom

* **Systeem:** segmentknoppen *Deze pc* / *Game-PC* + meters **Processor**,
  **Geheugen** en **GPU-temperatuur**; balk wordt oranje boven de drempel
  (80% / 80% / 75 °C).
* **Media & volume:** Spotify- en Discord-balk met waarde, plus
  vorige / play-pauze / volgende.
* **Slim huis:** 2-koloms tegelraster (Woonkamer, Bureau, Rolluik, Klimaat,
  Televisie, Filmavond) met aan/uit-label; lampen in oranje, rest in cyaan.

### 7.5 Goedkeuring-overlay

* Oranje modal midden op het scherm: **GOEDKEURING NODIG**, de vraag
  ("De game-pc afsluiten?"), toelichting met **actie + risico**, een
  **aftellijn (0:20)** en de knoppen *Annuleer* / *Ja, afsluiten*.
* Koppelt aan `core.confirmation.get_pending()` + `evaluate_answer()` en
  `executor.resume_approved_plan()` (zie §5 en §11).

### 7.6 Buiten de wireframe (voorlopig)

Notificatiehub, instellingen en een apart mediascherm staan **niet** in het
wireframe (besluit: "weglaten voor nu"). Ze blijven wel gereserveerd in het
API-contract (§5) en de widget-catalogus (§6) voor latere fases. Eerdere
wireframe-schermen staan ter referentie in `docs/fase18_wireframes/oud/`.

## 8. Wireframes

Het wireframe staat in `docs/fase18_wireframes/`:

| Bestand | Scherm |
|---|---|
| `index.html` | **Het volledige dashboard** — header, 3 kolommen, goedkeuring-overlay |
| `oud/` | eerdere wireframe-schermen, alleen ter referentie |

`index.html` is één zelfstandig bestand (inline CSS + JS, Google Fonts
Orbitron/Rajdhani) met een stage van 1180×820 die via JS met
`transform: scale()` naar elk venster schaalt — dus meteen bruikbaar als
iPad- en desktopweergave.

Voorbeeldgedrag dat nu al werkt:

* orb tikken → status wisselt (in rust / luistert / denkt / spreekt);
* *Deze pc* ↔ *Game-PC* → andere meterwaarden;
* nachtmodus-segmenten en slim-huis-tegels onthouden hun stand;
* opdracht intypen → bericht verschijnt in het gesprek;
* goedkeuring-overlay telt 20 seconden af → *Annuleer* of *Ja, afsluiten*.

## 9. Thema & stijl

**Stijl: futuristisch HUD (Iron Man / Stark), maar rustig.** Dunne gloeiende
lijnen op bijna-zwart, veel negatieve ruimte, cirkelvormige vormen.

* **Achtergrond:** bijna-zwart (`#04090e`).
* **Panelen:** `rgba(9,22,33,.78)` met 1px cyaan rand
  (`rgba(79,216,255,.26)`), radius 12, padding 14.
* **Kleuren:** cyaan `#4fd8ff` als basis; **oranje `#ff9a4d`** voor
  waarschuwingen, risico en goedkeuring; groen `#6fe3b0` voor "gelukt";
  tekst `#dff6ff`, secundair `#8fb4c8`.
* **Orb:** cyaan ringen met zachte puls; oranje zodra JARVIS "denkt na".
* **Meters:** horizontale balkjes die van cyaan naar oranje kleuren zodra de
  drempel wordt overschreden.
* **Typografie:** **Orbitron** voor koppen, klok en cijfers (ruime
  letterspacing), **Rajdhani** voor broodtekst; labels uppercase.
* **Aanspreking:** formeel. Statusmelding `Online · wake word "Hey JARVIS"`.
* **Beweging:** subtiele pulsen en langzame rotatie; geen afleiding tijdens
  gamen.
* **Schaling:** de 1180×820-stage schaalt met `transform: scale()` en blijft
  daarbij uitgerektvrij gecentreerd in elk venster.

> Referentie: Iron Man / Stark HUD, maar **rustiger**. Wireframe:
> `docs/fase18_wireframes/index.html`.

## 10. Beveiliging

* De server bindt op het LAN (`DASHBOARD_HOST=0.0.0.0`) zodat de iPad hem
  bereikt; de pc blijft lokaal (geen externe bereikbaarheid, Q&A-besluit).
* **Token** (`DASHBOARD_TOKEN`): verplicht zodra de server op het LAN luistert.
* **IP-allowlist** (`DASHBOARD_ALLOWED_IPS`): hergebruik `remote/allowlist.py`.
* **Geen schrijfacties zonder goedkeuring:** gevaarlijke acties (afsluiten,
  HA-schrijven) blijven via de bestaande `core/confirmation.py`-flow lopen.
* HTTPS is niet nodig op een vertrouwd thuisnetwerk; de token + allowlist zijn
  de bescherming. (Indien gewenst later: self-signed certificaat, patroon uit
  `remote/server.py`.)

## 11. Benodigde kleine backend-wijzigingen

Deze bestaan al bijna; het zijn aanvullingen, geen nieuwe subsystemen:

1. **`core/proactive.py` — `Melding`:** voeg `id` en `aangemaakt_op` toe, zodat de
   hub tijdstip + uniek kaartje kan tonen. `bron` is de "soort".
2. **`core/proactive.py` — `ProactiveEngine`:** voeg een observer-hook toe
   (bijv. `set_melding_observer(fn)`) zodat de server meldingen kan *zien* zonder
   de wachtrij leeg te halen (`neem_meldingen()` draint nu).
3. **`config.py`:** nieuwe `DASHBOARD_*` variabelen (enabled, host, port, token,
   allowed IP's).
4. **`main.py`:** start/stop `dashboard/server.py` als daemon-thread in
   `start_jarvis()` (naast `engine.start()`), met `atexit`-cleanup.
5. **`core/brain.py` / `core/executor.py`:** `POST /api/command` (Fase 20) roept
   `process_command` aan; `resume_approved_plan` voor goedkeuring vanuit het
   dashboard.

## 12. Testplan

* **`tests/test_fase18_server.py`** — `DashboardAPI` zonder HTTP:
  status samenstellen, notificaties serialiseren, timers aan/annuleren, media-
  en power-dispatch (gepatcht), widget-config lezen/schrijven (tmp-bestand).
* **`tests/test_fase18_dashboard.py`** — endpoint-niveau met een test-HTTP-client
  (of `http.server`-test): auth, JSON-vorm, 404's, SSE-events.
* **Lint:** `ruff check .` schoon (CI draait dit al).
* **Regressie:** `python -m pytest -q` volledig groen vóór en ná Fase 18.

## 13. Bouwvolgorde (mijlpalen)

1. **M1 — Fundering:** `DashboardAPI` + `config/dashboard.json` + tests voor
   status/notifications/timers. (Nog geen UI.)
2. **M2 — Server + auth:** HTTP + SSE + token/allowlist + start/stop in
   `main.py`.
3. **M3 — PWA-skelet:** `static/` met manifest + `sw.js`, thema uit de wireframe
   (inline CSS/JS splitsen naar `styles.css` + `app.js`), status-orb.
4. **M4 — Widgets:** kolommen vullen met echte data — auditlog, media, timers,
   pc-status, slim-huis-status.
5. **M5 — Aanpassen:** persistentie + (later) instellingenscherm.
6. **M6 — Logs/memory/routines:** overzichtstegels.
7. **M7 — Regressie + preview:** hele suite groen, op de iPad testen.

Na elke mijlpaal: `python -m pytest -q` + `ruff check .`.

## 14. Open besluiten / notities

* **Notificaties buiten het dashboard:** gesproken melding + Windows-toast
  blijven bestaan (Q&A). De hub is *extra*, niet vervangend.
* **HA in Fase 18:** alleen status. Bediening (aan/uit/dimmen) is Fase 20, tenzij
  anders besloten.
* **Licht-presets:** welke lampen/scènes als snelle knop? (`config/ha_scenes.json`
  bevat nu `avondmodus`.) Aan u om te kiezen bij M4.
* **Offline op iPad:** de `sw.js` cachet de shell; live data werkt alleen met
  verbinding. Netwerkuitval → vriendelijke melding, niet crashen.
* **Wireframe = gebruikersontwerp (besluit 21-10-2026):**
  `docs/fase18_wireframes/index.html` is overgenomen uit `jarvis-dashboard.html`
  en is de enige referentie. **Bewust niet** in het ontwerp: het aparte
  systeemstatus-panel met online-stippen, de 8 snelle acties, het voice-paneel
  met push-to-talk, de navigatie en de routines. De eerdere wireframe-schermen
  staan in `oud/`. Dit is een later uitbreidingspunt, geen fout.
* **Bol = oude reactor (bijgesteld):** het eerdere besluit ("zo laten als nu")
  is ingetrokken. De 4-ring reactor uit de vorige versie is verkleind naar
  160px overgenomen in het linkerpaneel, inclusief versnellen en kloppen bij
  luisteren/spreken/denken.
