# Spotify koppelen (Fase 21, M5)

JARVIS leert uw muzieksmaak uit uw Spotify-account (toptracks, topartiesten, recent
afgespeeld en uw eigen playlists) en mag het **afspelen bedienen** (sinds 2026-10-26,
Spotify Premium nodig). Hij verandert niets aan uw playlists, volgers of account.

**Al gekoppeld vóór 26 oktober?** Draai `python scripts/spotify_koppelen.py` nog één keer
en klik op **Akkoord**: dan krijgt JARVIS ook de afspeelrechten. Tot die tijd opent hij
het nummer alleen in Spotify (het staat dan klaar) en zegt hij dat u opnieuw kunt koppelen.

Er is geen wachtwoord of geheime sleutel nodig: JARVIS gebruikt alleen de *client-id*
(die is niet geheim) en logt in via de officiële Spotify-pagina, waar u zelf inlogt.

## Eenmalig: de Spotify-app aanmaken (± 5 minuten)

1. Ga op de laptop (het brein) naar **https://developer.spotify.com/dashboard** en log
   in met uw gewone Spotify-account. De eerste keer vraagt Spotify om de voorwaarden
   voor ontwikkelaars te accepteren; dat doet u zelf.
2. Klik op **Create app** en vul in:
   - **App name:** `JARVIS`
   - **App description:** `Persoonlijke assistent, alleen lezen`
   - **Website:** leeg laten
   - **Redirect URIs:** precies `http://127.0.0.1:8888/callback` en klik op **Add**
     (let op: `127.0.0.1`, niet `localhost`; Spotify accepteert `localhost` niet meer)
   - **Which API/SDKs are you planning to use?** vink **Web API** aan
   - vink de voorwaarden aan en klik op **Save**
3. Open de app en ga naar **Settings**. Kopieer de **Client ID** (32 tekens).
   Het *Client secret* hebt u **niet** nodig; laat dat staan.
4. Zet in de `.env` op de laptop:
   ```
   SPOTIFY_CLIENT_ID=<de client-id>
   ```
5. Draai op de laptop:
   ```
   python scripts/spotify_koppelen.py
   ```
   De browser opent de Spotify-pagina "JARVIS wil toegang tot…": uw smaak en playlists
   lezen, en zien wat er speelt en het afspelen bedienen. Klik op **Akkoord**. Het venster zegt daarna
   "Spotify is gekoppeld aan JARVIS", en het script noemt uw meest beluisterde artiesten.
6. Herstart JARVIS. Werk ook de **game-pc** bij (`git pull` + de agent herstarten):
   het openen van een Spotify-nummer is een nieuwe agent-actie (`spotify_open`).

Spotify kan voor ontwikkelaarsapps eigen voorwaarden stellen (bijvoorbeeld welk soort
account u nodig hebt). Ziet u zo'n melding in het dashboard of bij stap 5, dan is dat
een regel van Spotify; laat het mij weten, dan zoeken we het samen uit.

**Ontkoppelen:** verwijder `memory/spotify_token.json` en haal JARVIS weg op
https://www.spotify.com/account/apps/.

## Wat JARVIS ermee doet

| Zeg | Wat |
|---|---|
| "zet iets op wat ik leuk vind", "verras me met muziek" | een nummer uit uw smaak opent in Spotify |
| "stel muziek voor", "heb je een muziektip?", "wat zal ik luisteren?" | een voorstel + "Zal ik hem opzetten?" (ja/nee, ook in de popup) |
| "wat is mijn muzieksmaak?", "naar wie luister ik het meest?" | uw topartiesten van de laatste weken |
| "ik ga gamen" | na de gamemodus: "Muziek erbij? Wat dacht u van uw playlist '…'?" |

- JARVIS kiest uit uw toptracks van de laatste weken (die tellen dubbel) en van de
  laatste maanden, en slaat over wat u net nog draaide.
- Bij de gamemodus kiest hij een eigen playlist met *game*, *gaming*, *focus*, *hype*,
  *energy* of *workout* in de naam; anders een nummer.
- **Afspelen:** JARVIS start het nummer of de playlist via Spotify zelf, op het apparaat
  dat nu actief is, anders op een computer (de game-pc). Draait Spotify nergens, dan opent
  hij de app op de game-pc en wacht hij tot die er is (max. 15 s). Vast een apparaat kiezen:
  `SPOTIFY_APPARAAT=<deel van de naam>` in `.env`, bijv. de naam van de game-pc.
- Lukt dat niet (geen apparaat, of nog oude koppeling), dan opent hij de `spotify:`-link in
  de app en zegt hij eerlijk "… staat klaar in Spotify". Zonder Premium zegt Spotify nee;
  dat zegt JARVIS dan ook.
- Het smaakprofiel wordt hooguit elke 6 uur ververst (`memory/spotify_smaak.json`).
- Tokens staan in `memory/spotify_token.json` (niet in git, wel in uw backup) en komen
  nooit in de log, een URL of het auditlog.

## Testlijst

- [ ] Stap 1–5 hierboven: het script zegt "Gekoppeld." met uw artiesten
- [ ] "Wat is mijn muzieksmaak?" → uw topartiesten
- [ ] "Stel muziek voor" → een voorstel; "ja" → het nummer opent in Spotify op de game-pc
- [ ] "Heb je een muziektip?" → "nee" → "Goed, een andere keer, sir."
- [ ] Opnieuw koppelen (afspeelrechten) → "Zet iets op wat ik leuk vind" → het nummer **speelt** op de game-pc
- [ ] Spotify dicht op de game-pc → "zet iets op wat ik leuk vind" → Spotify opent en het nummer speelt
- [ ] Gamemodus → muziekvoorstel → "ja" → de playlist speelt
- [ ] "Ik ga gamen" → na de stappen een muziekvoorstel; ja/nee werkt, ook via de popup op de iPad
- [ ] Zonder koppeling: "stel muziek voor" → JARVIS zegt dat Spotify nog niet gekoppeld is
