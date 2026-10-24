# Fase 18 — Dashboard (iPad) — Design

**Status:** ontwerp (nog niet gebouwd)
**Laatst bijgewerkt:** 2026-10-22
**Beveiliging:** herzien op 2026-10-22 — zie §10 (TLS + eenmalige
koppelcode, twee tokens, `id`+`nonce` per goedkeuring, strikte CSP).
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
`127.0.0.1` maar op het LAN (`0.0.0.0`), uitsluitend via **HTTPS** en met
beveiliging (zie §10). Daarom hergebruiken we het patroon uit Fase 15:
TLS-context, IP-allowlist (`_ip_toegestaan()`), rate-limit en lockout uit
`remote/server.py`.

## 4. Bestandstructuur (voorstel)

```text
dashboard/
  api.py               # DashboardAPI: alle logica, testbaar zonder HTTP (M1 ✅)
  server.py            # HTTP + SSE + TLS; alleen verpakking rond DashboardAPI
  static/
    index.html         # het dashboard (één scherm, uit de wireframe overgenomen)
    styles.css         # thema (in de wireframe nog inline; hier gesplitst)
    app.js             # laad data, EventSource, render widgets (alleen textContent)
    manifest.webmanifest
    sw.js              # offline-cache (PWA)
    icons/             # 192 / 512 px
    fonts/             # Orbitron + Rajdhani als woff2, LOKAAL gehost (§10.8)
config/
  dashboard.json       # welke widgets, welke volgorde, instellingen
  dashboard_devices.json  # gekoppelde apparaten: alleen hash van het token + rol
scripts/
  make_dashboard_cert.py  # zelfgetekend certificaat + .mobileconfig-profiel
tests/
  test_fase18_server.py
  test_fase18_dashboard.py
docs/
  fase18_dashboard_design.md      # dit document
  fase18_wireframes/              # HTML-wireframes (zie §8)
    index.html                    # HET dashboard (referentie-ontwerp)
    oud/                          # eerdere wireframe-schermen, ter referentie
```

**Scheiding:** `DashboardAPI` in `dashboard/api.py` bevat alle logica en is
direct te testen met pytest (net als `remote/server.py` → `RemoteAgent`). De
HTTP-handler is alleen verpakking. `config/dashboard.json` bevat de
widget-voorkeuren (geen code).

## 5. API-contract

Basis-URL: `https://<pc-ip>:8780` (poort via `DASHBOARD_PORT`; **TLS is
verplicht**, zie §10.2). De server bindt alleen op het LAN.

Alle endpoints geven JSON. Er zijn **twee tokens** (zie §10.4):

* **kijk-token** (`DASHBOARD_VIEW_TOKEN`) — alleen lezen;
* **bedien-token** (`DASHBOARD_CONTROL_TOKEN`) — lezen **én** schrijven.

Authorisatie kent twee vormen:

* `Authorization: Bearer <token>` — scripts, console en de vaste tokens;
* **sessiecookie** (`HttpOnly; Secure; SameSite=Strict`) — het apparaat dat
  via de koppelcode is gekoppeld. Die werkt ook voor `EventSource` (SSE),
  waar geen requestheader mee kan.

Een token staat **nooit** in een URL, in een query-string of in de body van
een GET, en wordt **nooit** in een respons teruggegeven — ook niet in
`/api/settings`; die meldt alleen of er een token ingesteld is.

**Host- en Origin-controle** (zie §10.7): elk verzoek moet een bekende
`Host` hebben, en elke schrijfactie moet een `Origin` uit de allowlist
meesturen. Er worden geen CORS-headers gezet.

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
| GET | `/api/settings` / PUT | `/api/settings` — thema, taal, meldingen. **Geen token:** de API toont alleen `token_ingesteld` en welke rollen aanwezig zijn |

### Koppelcode, tokens en goedkeuring

| Methode | Pad | Doet |
|---|---|---|
| POST | `/api/pair` | `{ code, rol }` → koppelt de iPad en geeft **één keer** een apparaattoken + sessiecookie. De code is 5 minuten geldig en één keer bruikbaar (§10.3) |
| GET | `/api/sessie` | `{ gekoppeld, rol, token_ingesteld }` — nooit het token zelf |
| POST | `/api/tokens/rotatie` | `{ huidig }` → nieuw token (eenmalig getoond). **Alleen met een kloppend huidig token** (§10.4) |
| GET | `/api/pending` | de openstaande goedkeuring: `{ id, nonce, soort, vraag, actie, argumenten, risico, verloopt_op, resterende_seconden }` of `null` |
| POST | `/api/goedkeuring` | `{ id, nonce, besluit: "ja" \| "nee" }` → voert de openstaande actie uit of annuleert hem |

`/api/pending` en `/api/goedkeuring` bestaan **alleen** voor de actie die op
dat moment openstaat: een `id`/`nonce` van een gesloten, verlopen of
onbekende actie wordt geweigerd (§10.6).

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
* De overlay toont de **volledige actietekst** (vraag, tool, argumenten,
  risico) en stuurt bij *Ja* de `id` + `nonce` van díe ene openstaande actie
  mee. De server bindt de goedkeuring eraan: een `id` of `nonce` van een
  andere of verouderde actie wordt geweigerd (§10.6).

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

> **De wireframe is ontwerp, geen productiecode.** De inline scripts, de
> opbouw met `innerHTML` en de Google-Fonts-link worden *niet* overgenomen.
> In het echte dashboard staan CSS en JS in aparte bestanden, worden alle
> lettertypen lokaal gehost en lopen de gegevens via `textContent` (§10.8).

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
  letterspacing), **Rajdhani** voor broodtekst; labels uppercase. Beide
  worden **lokaal gehost** (`dashboard/static/fonts/*.woff2`) — niet vanaf
  Google Fonts (§10.8).
* **Aanspreking:** formeel. Statusmelding `Online · wake word "Hey JARVIS"`.
* **Beweging:** subtiele pulsen en langzame rotatie; geen afleiding tijdens
  gamen.
* **Schaling:** de 1180×820-stage schaalt met `transform: scale()` en blijft
  daarbij uitgerektvrij gecentreerd in elk venster.

> Referentie: Iron Man / Stark HUD, maar **rustiger**. Wireframe:
> `docs/fase18_wireframes/index.html`.

## 10. Beveiliging

*Besluit (Q&A 22-10-2026):* de iPad gebruikt **Safari** en u kunt een
certificaatprofiel installeren; het dashboard krijgt **TLS én een eenmalige
koppelcode**; het dashboard is **alleen thuis** bereikbaar — geen tunnel,
geen poort-forwarding, geen toegang van buiten huis.

### 10.1 Bedreigingsmodel

| Dreiging | Maatregel |
|---|---|
| Iemand leest het token mee op het Wi-Fi | TLS (§10.2) — het token is alleen binnen de tunnel leesbaar |
| Iemand krijgt het token in handen (apparaat kwijt, screenshot) | twee rollen (kijk/bedien) + apparaatbinding + intrekken + rotatie (§10.4) |
| Iemand benadert de server vanaf een ander netwerk | IP-allowlist, alleen privé-adressen (§10.5) |
| Brute-force op het token of de koppelcode | rate-limit + lockout (§10.6) |
| Een andere website doet een verzoek namens u (CSRF) | Origin-controle op elke schrijfactie + HttpOnly/SameSite=Strict-cookie (§10.7) |
| DNS-rebinding vanuit de browser | Host-controle op elk verzoek (§10.7) |
| Gevaarlijke actie zonder uw echte intentie | `id` + `nonce` per openstaande actie, strikte ja-semantiek, auditregel (§10.6) |
| Kwaadaardige tekst in het dashboard (nieuws, timernaam, geheugen) | alleen `textContent`/DOM-opbouw, strikte CSP, geen inline code (§10.8) |
| Derde partij leest mee (lettertypen, CDN) | alle assets lokaal, geen enkel extern verzoek (§10.8) |

### 10.2 Transport — TLS

De server bindt op het LAN (`DASHBOARD_HOST=0.0.0.0`) maar **alleen via
HTTPS**. Het patroon is letterlijk dat van Fase 15 (`remote/server.py`):

* `remote.server.build_ssl_context(cert_file, key_file)` — TLS 1.2 of hoger;
* `config.dashboard_security_errors()` — net als
  `remote_server_security_errors()` weigert de server te starten als een
  token ontbreekt of te kort is, of als het certificaat of de sleutel
  ontbreekt of ongeldig is;
* hetzelfde `ThreadingHTTPServer`-patroon met handshake-deadline en
  verbindingslimieten (`max_connections_per_ip`).

Het certificaat wordt door JARVIS zelf gegenereerd voor het LAN-adres
(`scripts/make_dashboard_cert.py`, zelfgetekend, geldig voor de LAN-IP en
`localhost`). Het bijbehorende `.mobileconfig`-profiel installeert u op de
iPad; daarna zet u bij *Instellingen → Algemeen → Info → Instellingen voor
certificaatvertrouwen* op **Volledig vertrouwen**. Zonder die stap blijft de
PWA in Safari onder de veiligheidsdrempel (geen service worker) en waarschuwt
Safari bij elke verbinding.

> Het zelfgetekende certificaat is *vertrouwd op uw eigen apparaten*, niet
> door een externe partij. Dat is voldoende om verkeer op het LAN te
> versleutelen, maar geen garantie in een vijandig netwerk.

### 10.3 Koppelcode — eenmalig, lokaal, kort geldig

Aan het token zit geen handmatig over te typen geheim: dat belandt in een
bericht, een screenshot of een notitie. In plaats daarvan:

1. JARVIS genereert bij het starten een **koppelcode** van 8 cijfers, geldig
   **5 minuten** en **één keer bruikbaar**. De code verschijnt alleen op de
   pc zelf: in de console/log en als QR op een lokaal venster op de pc
   (`http://127.0.0.1:8780/koppel`, alleen bereikbaar vanaf de pc zelf). De
   code wordt dus nooit over het netwerk verstuurd.
2. Op de iPad tikt u de code in (of scant u de QR). `POST /api/pair` met
   `{ code, rol }` levert een **apparaattoken** op en zet een sessiecookie:
   `HttpOnly; Secure; SameSite=Strict`.
3. De server bewaart alleen de **hash** van het apparaattoken
   (`config/dashboard_devices.json`), plus rol, apparaatnaam, IP-adres en
   aanmaakdatum. Het token zelf is één keer zichtbaar.
4. Een fout of verlopen code telt mee in de lockout (§10.6). De code wordt
   nooit gelogd.

De rol die u bij het koppelen kiest (`kijk` of `bedien`) bepaalt de rechten
van dat apparaat (§10.4).

### 10.4 Tokens: een kijk-token en een apart bedien-token

| Token | Wat het mag | Waar |
|---|---|---|
| **kijk-token** (`DASHBOARD_VIEW_TOKEN`) | alleen lezen: status, timers, media, pc-status, logs, memory, routines | `.env` |
| **bedien-token** (`DASHBOARD_CONTROL_TOKEN`) | lezen **én** schrijven: timers zetten, media bedienen, licht-presets, routines starten, en goedkeuringen geven | `.env` |

Regels:

* De vaste tokens en de gekoppelde apparaten gebruiken dezelfde rollen: een
  apparaat met rol `bedien` mag precies wat het bedien-token mag.
* **Het bedien-token is nodig voor de gevaarlijke dingen**: de pc
  afsluiten of herstarten, een routine starten en een openstaande actie
  goedkeuren. Dat laatste gaat altijd nog via de goedkeuringspoort (§10.6):
  een bedien-token alléén is géén toestemming om zonder meer de pc af te
  sluiten.
* **Een token staat nooit in een URL, query-string of GET-respons** — alleen
  in de `Authorization: Bearer`-header of in de sessiecookie.
* **Een token wijzigen kan alleen met het oude token.**
  `POST /api/tokens/rotatie` vraagt het huidige token mee; zonder kloppend
  huidig token is er geen rotatie mogelijk. Het nieuwe token wordt één keer
  getoond, het oude is daarna meteen ongeldig, en alle sessies van dat
  token worden ingetrokken.
* `/api/settings` toont **nooit** een token, alleen `token_ingesteld: true`
  en welke rollen aanwezig zijn.
* Tokens komen nooit in een logregel of in het auditlog — dezelfde regel als
  in `remote/server.py` ("wordt nooit gelogd of verstuurd").

### 10.5 IP-allowlist

`DASHBOARD_ALLOWED_IPS` volgt het patroon van `_ip_toegestaan()` uit
`remote/server.py`: publieke adressen worden **altijd** geweigerd, en
zonder expliciete lijst mogen alleen privé-adressen (LAN, localhost) contact
nemen. Vul het IP-adres van de iPad in voor een extra laag.

### 10.6 Rate-limit, lockout en de goedkeuringspoort

* **Rate-limit:** `RateLimiter` uit `remote/server.py` (standaard 60
  verzoeken per 60 seconden per IP). Voor `/api/pair` en
  `/api/tokens/rotatie` geldt een **strengere** limiet: 5 pogingen per 10
  minuten per IP.
* **Lockout:** `AuthLockout` uit `remote/server.py` — 5 fouten binnen 60
  seconden betekent dat het IP 300 seconden wordt geweigerd. Elke mislukte
  authenticatie telt mee; na een geslaagde authenticatie begint de teller
  opnieuw. Een geblokkeerd IP krijgt `403` zonder uitleg.
* **Goedkeuring is aan één specifieke actie gebonden.** De openstaande
  bevestiging in `core/confirmation.py` krijgt daarom een **`id` en een
  `nonce`** — vandaag heeft de pending alleen `kind`, `_expires_at` en
  `_reasked`, dus een goedkeuring vanuit het dashboard zou niet aan één
  openstaande actie te binden zijn (zie §11).
  * `GET /api/pending` toont de openstaande actie: `id`, `nonce`, soort,
    **de volledige actietekst** (vraag, tool, argumenten, risico) en de
    resterende tijd. Is er geen openstaande actie, dan is het antwoord
    `null`.
  * `POST /api/goedkeuring` met `{ id, nonce, besluit }` werkt **alleen** als
    `id` en `nonce` horen bij de actie die op dat moment openstaat. Een
    verlopen, al beantwoorde of onbekende `id` wordt geweigerd (`409` /
    `410`) en de pending wordt niet gewijzigd.
  * **Dezelfde ttl** als via de stem (`CONFIRM_TTL_SECONDS`); het dashboard
    verkort of verlengt die tijd niet.
  * **Dezelfde strikte ja-semantiek** als `core/confirmation.py`:
    `is_strict_yes()` (exact "ja", "ja doe maar", "doe maar", "ja graag",
    "bevestig") en `contains_denial()` (bij twijfel altijd "nee"). "Ja,
    misschien" is dus géén goedkeuring; de knop *Ja* in de overlay telt als
    die strikte bevestiging en niet als een losse "ja".
  * **Auditregel met herkomst:** `core.audit.log_audit()` krijgt
    `handler="dashboard"` of `handler="stem"`, de volledige actietekst, het
    risico, het resultaat en de reden. Er staat dus altijd *wie* goedkeurde.
  * Een tweede goedkeuring van dezelfde actie doet niets: na afhandelen is
    de pending gewist.

### 10.7 Host- en Origin-controle

* **Host:** elk verzoek moet een `Host`-header hebben die in
  `DASHBOARD_ALLOWED_HOSTS` staat (standaard `<lan-ip>:8780` en
  `localhost:8780`). Zo kan een aanval via DNS-rebinding niet op
  `127.0.0.1` in de browser van de iPad terechtkomen.
* **Origin:** elke schrijfactie (POST/PUT/DELETE) moet een `Origin` hebben
  die in `DASHBOARD_ALLOWED_ORIGINS` staat (standaard
  `https://<lan-ip>:8780` en `https://localhost:8780`). Ontbreekt `Origin`
  of staat hij er niet in, dan is het `403`. Uitzondering: `POST /api/pair`
  mag zonder `Origin`, want daar is de koppelcode zelf het geheim — die
  beschermt tegen CSRF op zichzelf.
* Er worden **geen CORS-headers** gezet; de browser blokkeert
  cross-origin verzoeken dan zelf.
* API-responsen krijgen `Cache-Control: no-store` en `Referrer-Policy:
  no-referrer`, zodat een token of een URL met gegevens niet in een cache
  of in de referrer belandt.

### 10.8 Rendering, CSP en assets

De pagina kan gevaarlijke acties goedkeuren; daarom geldt de strengste
regel: **gegevens uit de API worden nooit als HTML behandeld.**

* In `dashboard/static/app.js` zijn `innerHTML`, `insertAdjacentHTML`,
  `outerHTML` en `document.write` **verboden**. Tekst gaat via
  `textContent`, elementen via `document.createElement`. Alleen vaste,
  zelfgeschreven HTML-fragmenten (iconen, statische labels) mogen via
  `innerHTML`, en die bevatten nooit API-gegevens.
* **Content-Security-Policy** (als responsheader, vanaf de server):
  `default-src 'self'; script-src 'self'; style-src 'self';
  img-src 'self' data:; font-src 'self'; connect-src 'self';
  object-src 'none'; base-uri 'none'; frame-ancestors 'none';
  form-action 'self'`.
  **Geen `'unsafe-inline'` en geen `'unsafe-eval'`** — dus in de productie
  staan geen inline `<script>`, geen inline `<style>` en geen
  `style="..."`-attributen; CSS en JS staan in aparte bestanden.
* **Alle lettertypen lokaal**: Orbitron en Rajdhani worden als `woff2` in
  `dashboard/static/fonts/` geplaatst en via `@font-face` geladen. Er gaat
  **geen enkel verzoek** naar een externe host (geen Google Fonts, geen
  CDN) — dat lekt bezoekgegevens en zou de CSP sowieso breken.
* De wireframe (`docs/fase18_wireframes/index.html`) is **alleen referentie**:
  de inline scripts, de `innerHTML`-opbouw en de Google-Fonts-link worden
  overgenomen als ontwerp, niet als code.

### 10.9 Wat níet gebeurt

* Geen tunnel, geen poort-forwarding, geen bereikbaarheid van buiten huis.
* Geen publieke certificaten, geen accounts, geen cloud.
* Geen enkel geheim in een URL, in de HTML of in een logregel.

## 11. Benodigde kleine backend-wijzigingen

Deze bestaan al bijna; het zijn aanvullingen, geen nieuwe subsystemen:

1. **`core/proactive.py` — `Melding`:** voeg `id` en `aangemaakt_op` toe, zodat de
   hub tijdstip + uniek kaartje kan tonen. `bron` is de "soort".
2. **`core/proactive.py` — `ProactiveEngine`:** voeg een observer-hook toe
   (bijv. `set_melding_observer(fn)`) zodat de server meldingen kan *zien* zonder
   de wachtrij leeg te halen (`neem_meldingen()` draint nu).
3. **`config.py`:** nieuwe `DASHBOARD_*` variabelen (enabled, host, port,
   **kijk-token**, **bedien-token**, certificaat/sleutel, allowed IP's,
   allowed hosts, allowed origins, rate-limit, koppelcode-ttl, apparaatbestand)
   plus `dashboard_security_errors()` in de stijl van
   `remote_server_security_errors()`: zonder token of zonder certificaat
   start de server niet.
4. **`main.py`:** start/stop `dashboard/server.py` als daemon-thread in
   `start_jarvis()` (naast `engine.start()`), met `atexit`-cleanup; bij het
   starten éénmalig een koppelcode genereren en die alleen lokaal tonen.
5. **`core/brain.py` / `core/executor.py`:** `POST /api/command` (Fase 20) roept
   `process_command` aan; `resume_approved_plan` voor goedkeuring vanuit het
   dashboard.
6. **`core/confirmation.py` — `id` en `nonce`:** elke openstaande bevestiging
   krijgt een `id` (uniek per pending) en een `nonce` (willekeurig, geheim).
   Vandaag heeft de pending alleen `kind`, `_expires_at` en `_reasked`, dus een
   goedkeuring vanuit het dashboard zou niet aan één specifieke openstaande
   actie te binden zijn. Er komt bij:
   * `id` en `nonce` in de pending (zie §10.6);
   * een manier om de openstaande actie als **volledige tekst** op te halen
     (vraag, tool, argumenten, risico) voor de overlay;
   * een functie om een besluit (`ja`/`nee`) te verwerken **uitsluitend** met
     een kloppende `id` + `nonce`, met dezelfde ttl en dezelfde strikte
     ja-semantiek (`is_strict_yes`, `contains_denial`);
   * de herkomst (`dashboard` of `stem`) in de auditregel.
7. **`core/audit.py`:** het veld `handler` bestaat al; daar komt de herkomst
   in (`dashboard` of `stem`). Het token komt er nooit in.
8. **`dashboard/server.py`:** TLS met `remote.server.build_ssl_context()`; de
   koppelcode-route; sessiecookies (`HttpOnly; Secure; SameSite=Strict`); de
   Host- en Origin-controle; de CSP- en overige security-headers; de
   statische bestanden met de juiste MIME-types.
9. **`scripts/make_dashboard_cert.py` (nieuw):** maakt het zelfgetekende
   certificaat voor het LAN-adres én het `.mobileconfig`-profiel voor de
   iPad, met de instructie voor *Volledig vertrouwen*.
10. **`dashboard/static/fonts/` (nieuw):** Orbitron en Rajdhani als `woff2`,
    lokaal gehost; de CSS gebruikt `@font-face` in plaats van een
    Google-Fonts-link.

## 12. Testplan

* **`tests/test_fase18_server.py`** — `DashboardAPI` zonder HTTP:
  status samenstellen, notificaties serialiseren, timers aan/annuleren, media-
  en power-dispatch (gepatcht), widget-config lezen/schrijven (tmp-bestand).
* **`tests/test_fase18_dashboard.py`** — endpoint-niveau met een test-HTTP-client
  (of `http.server`-test): auth, JSON-vorm, 404's, SSE-events.
* **Lint:** `ruff check .` schoon (CI draait dit al).
* **Regressie:** `python -m pytest -q` volledig groen vóór en ná Fase 18.

### 12.1 Beveiligingstestplan

**Authenticatie en autorisatie**

| Test | Verwachting |
|---|---|
| Verzoek zonder token en zonder cookie | `401`, geen data |
| Alleen de kijk-token op een schrijf-endpoint (`POST /api/media`) | `403` |
| De bedien-token op een schrijf-endpoint | werkt, en komt in het auditlog |
| Gekoppeld apparaat met rol `kijk` op een schrijf-endpoint | `403` |
| Gekoppeld apparaat met rol `bedien` op een schrijf-endpoint | werkt |
| Gevaarlijke actie (power) met alleen de kijk-token | `403` |
| `GET /api/settings` | bevat **geen** tokenwaarde, alleen `token_ingesteld` |
| Token in de URL (`?token=…`) | wordt genegeerd; er is geen query-token |

**Verkeerde token, ratelimit en lockout**

| Test | Verwachting |
|---|---|
| Vijf keer een verkeerd token | na de vijfde: `403` en het IP is geblokkeerd (lockout) |
| Na afloop van de lockout | het IP mag weer proberen; de teller is opnieuw gestart |
| Een geslaagde authenticatie | reset de lockout-teller |
| Meer verzoeken dan de limiet per minuut | `429` |
| Vijf pogingen op `/api/pair` | eigen, strengere limiet + lockout |
| Verkeerde of verlopen koppelcode | `401`, de code blijft onbruikbaar, er komt geen token terug |
| Hergebruikte koppelcode | `401` (eenmalig) |

**Host en Origin**

| Test | Verwachting |
|---|---|
| `Host: evil.example` | `403` |
| `Host` met verkeerde poort | `403` |
| `POST` zonder `Origin` | `403` |
| `POST` met `Origin: https://evil.example` | `403` |
| `POST` met de eigen `Origin` | toegestaan |
| `GET` (SSE) met de eigen `Origin` | toegestaan |
| CORS-headers in de respons | er staan géén `Access-Control-*`-headers in |

**Goedkeuring**

| Test | Verwachting |
|---|---|
| `POST /api/goedkeuring` met de `id` van een **niet**-openstaande actie | `409`/`410`, er wordt niets uitgevoerd |
| Idem, met een juiste `id` maar een **verkeerde** `nonce` | `403`, er wordt niets uitgevoerd |
| Goedkeuren na het verlopen van de ttl | `410`, er wordt niets uitgevoerd |
| Goedkeuren met `besluit: "misschien"` | afgewezen — alleen de strikte ja-semantiek telt |
| Goedkeuren met `besluit: "ja, misschien"` | afgewezen (strikte ja-semantiek) |
| Goedkeuren met `besluit: "nee"` | actie geannuleerd, auditregel met `goedgekeurd=false` |
| Goedkeuren met `besluit: "ja"` | actie uitgevoerd, auditregel met `handler="dashboard"` |
| Tweede goedkeuring van dezelfde actie | `409`, de eerste is al afgehandeld |
| `GET /api/pending` | toont de volledige actietekst: vraag, tool, argumenten, risico |
| Stem-goedkeuring | auditregel met `handler="stem"`, id/nonce ongewijzigd bruikbaar |
| Goedkeuren met een oude/verouderde `nonce` | `403` |

**XSS en rendering**

| Test | Verwachting |
|---|---|
| Timernaam `<img src=x onerror="…">` | de API geeft de tekst ongewijzigd terug; in de DOM staat **geen** `img`-element en geen foutmelding |
| Geheugenitem `<script>alert(1)</script>` | komt als tekst in de DOM, wordt niet uitgevoerd |
| Nieuwskop met HTML-tags | idem |
| Melding met `"><img onerror=…>` | idem |
| Broncode-controle | `dashboard/static/*.js` bevat geen `innerHTML`, `insertAdjacentHTML`, `outerHTML` of `document.write` op API-gegevens |
| CSP-header | aanwezig, `default-src 'self'`, **zonder** `'unsafe-inline'`/`'unsafe-eval'` |
| Productiebestanden | geen inline `<script>`/`<style>`; CSS en JS in aparte bestanden |
| Lettertypen | `dashboard/static/fonts/*.woff2` aanwezig; geen enkele verwijzing naar een externe host |
| Netwerk | de pagina doet geen enkel verzoek naar een extern domein |

**Audit en geheimen**

| Test | Verwachting |
|---|---|
| Elke schrijfactie | er komt een auditregel met `handler="dashboard"` |
| Elke mislukte authenticatie | idem, met de reden, zonder het token |
| Token in `logs/jarvis.log` of het auditlog | komt nergens voor (grep-controle) |
| Tokenrotatie zonder het oude token | `401`, er verandert niets |
| Tokenrotatie mét het oude token | nieuw token, het oude werkt niet meer, sessies ingetrokken |

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

### 13.1 Uitvoeringsregels voor elke mijlpaal

Deze regels gelden vanaf M2 (server) en zeker vanaf M3 (PWA). Ze zijn geen
extraatje maar onderdeel van "af":

1. **Geen API-gegevens als HTML.** In `dashboard/static/app.js` zijn
   `innerHTML`, `insertAdjacentHTML`, `outerHTML` en `document.write`
   verboden. Tekst via `textContent`, elementen via `document.createElement`.
   Alleen vaste, zelfgeschreven fragmenten (iconen) mogen `innerHTML`
   gebruiken, en nooit met data erin.
2. **Strikte CSP vanaf M3.** `default-src 'self'`, geen `'unsafe-inline'`,
   geen `'unsafe-eval'`, `object-src 'none'`, `frame-ancestors 'none'`.
   Daarom staan er in de productiebestanden geen inline `<script>`, geen
   inline `<style>` en geen `style="..."`-attributen: CSS en JS staan in
   `styles.css` en `app.js`. De wireframe is geen uitzondering.
3. **Alle assets lokaal.** Lettertypen als `woff2` in
   `dashboard/static/fonts/`; geen enkele `<link>` of `@import` naar een
   externe host. De pagina doet geen verzoeken buiten de eigen origin.
4. **Elke schrijfactie is gebonden en herleidbaar.** Schrijfacties vragen de
   bedien-token (of een sessie met rol `bedien`); gevaarlijke acties gaan
   via de goedkeuringspoort met `id` + `nonce`; elke schrijfactie en elke
   mislukte authenticatie levert een auditregel met de herkomst.
5. **Elk nieuw endpoint krijgt zijn auth-tests.** Bij het toevoegen van een
   endpoint komen er tests bij voor: zonder token (`401`), met de verkeerde
   rol (`403`), met de juiste rol (werkt), plus de XSS- en auditcontrole uit
   §12.1.
6. **Elke mijlpaal:** `python -m pytest -q` + `ruff check .` + de
   beveiligingstests uit §12.1 groen. Wijzigt de API, dan ook de UI
   controleren op `innerHTML`-gebruik en op ontbrekende `textContent`.

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
* **Beveiliging herzien (22-10-2026):** §10 is herschreven. Besluiten:
  Safari met een geïnstalleerd certificaatprofiel, **TLS én een eenmalige
  koppelcode**, een **kijk-token en een apart bedien-token**, en het dashboard
  alleen thuis bereikbaar. De eerdere regel "HTTPS is niet nodig op een
  vertrouwd thuisnetwerk" is **ingetrokken** — het token kan anders
  meegelezen worden en dan zijn gevaarlijke acties goed te keuren.
  Nieuw in het ontwerp: `id` + `nonce` per openstaande actie, Host- en
  Origin-controle, strikte CSP, lokaal gehoste lettertypen en een
  beveiligingstestplan (§12.1).
