# Spotify koppelen (Fase 21, M5)

JARVIS leert uw muzieksmaak uit uw Spotify-account, **alleen lezen**: toptracks,
topartiesten, recent afgespeeld en uw eigen playlists. Hij kan niets aan uw account
veranderen. Afspelen gaat gewoon via de Spotify-app op de game-pc.

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
   De browser opent de Spotify-pagina "JARVIS wil toegang tot…". Kijk of er alleen
   leesrechten staan en klik op **Akkoord**. Het venster zegt daarna
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
- Speelt het na het openen echt, dan zegt hij "Speelt nu: …". Opent Spotify alleen de
  pagina (bij een playlist gebeurt dat vaak), dan zegt hij eerlijk "… staat klaar in
  Spotify" en drukt u zelf op afspelen. Bewust: met alleen leesrechten kan JARVIS het
  afspelen niet via Spotify zelf starten.
- Het smaakprofiel wordt hooguit elke 6 uur ververst (`memory/spotify_smaak.json`).
- Tokens staan in `memory/spotify_token.json` (niet in git, wel in uw backup) en komen
  nooit in de log, een URL of het auditlog.

## Testlijst

- [ ] Stap 1–5 hierboven: het script zegt "Gekoppeld." met uw artiesten
- [ ] "Wat is mijn muzieksmaak?" → uw topartiesten
- [ ] "Stel muziek voor" → een voorstel; "ja" → het nummer opent in Spotify op de game-pc
- [ ] "Heb je een muziektip?" → "nee" → "Goed, een andere keer, sir."
- [ ] "Zet iets op wat ik leuk vind" → het nummer speelt (of staat klaar in Spotify)
- [ ] "Ik ga gamen" → na de stappen een muziekvoorstel; ja/nee werkt, ook via de popup op de iPad
- [ ] Zonder koppeling: "stel muziek voor" → JARVIS zegt dat Spotify nog niet gekoppeld is
