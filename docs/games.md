# Games starten met de stem (Fase 21, M6)

"Start Valorant", "ik wil BeamNG spelen", "laten we een potje League spelen",
"open Assetto Corsa op de game-pc", "welke games heb ik?".

## Hoe het werkt

- JARVIS kent de games op de game-pc:
  - **Steam:** alle bibliotheekmappen (`libraryfolders.vdf`) en per game het
    `appmanifest`. Geen Steam-account of sleutel nodig. Hulppakketten (Proton,
    Steamworks, soundtracks) tellen niet mee.
  - **Riot:** Valorant en League of Legends, als ze geïnstalleerd zijn (via de Riot Client).
- De lijst staat in `memory/games.json` (niet in git) en wordt hooguit één keer per dag
  ververst, of meteen als u een game noemt die er (nog) niet in staat.
- JARVIS neemt "start/open/speel …" alleen over als de naam echt een game is. "Open
  Spotify" blijft dus een programma. Hij verstaat ook benaderingen ("beam ng",
  "asseto", "taxi life", "league").
- Starten: Steam via `steam://rungameid/<id>`, Riot via de Riot Client
  (`--launch-product=valorant`). De game-pc-agent start alleen games uit zijn eigen
  lijst, nooit een pad of commando. Laag risico: geen ja/nee-vraag, wel een auditregel.

## Staat de game-pc uit?

JARVIS drukt op de Wake-on-LAN-knop van de game-pc in Home Assistant
(`button.kamer_game_pc`, "Game-Pc") en zegt:

> "De game-pc wordt opgestart, sir. Ik start Valorant zodra hij er is."

Op de achtergrond wacht hij tot de agent er is (max. 3 minuten), start dan de game en
meldt *"VALORANT wordt gestart, sir. De game-pc is er."* (stem en dashboard). Komt de
game-pc niet online, dan zegt hij dat ook.

Daarvoor moet Wake-on-LAN aanstaan in de BIOS/UEFI van de game-pc en bij de netwerkkaart
in Windows ("Wake on Magic Packet"), en moet de game-pc-agent automatisch starten bij het
inloggen (zie `docs/remote_agent.md`).

## Instellingen (`.env` op het brein, optioneel)

```
GAME_PC_AAN_KNOP=button.kamer_game_pc     # anders zoekt JARVIS een knop met "game pc" in de naam
GAME_PC_OPSTART_SECONDEN=180
```

## Game-pc bijwerken

`game_lijst` en `game_start` zijn nieuwe agent-acties: `git pull` op de game-pc en de
agent herstarten.

## Testlijst

- [ ] "Welke games heb ik?" → de lijst met Steam-games, Valorant en League
- [ ] Game-pc aan → "start Valorant" → de Riot Client start Valorant
- [ ] "Ik wil BeamNG spelen" → BeamNG.drive start via Steam
- [ ] "Open Spotify" → Spotify opent gewoon (geen game)
- [ ] Game-pc uit (slaapstand of uit) → "start Assetto Corsa" → "De game-pc wordt opgestart…";
      na het opstarten start de game en hoort u de melding
- [ ] Nieuwe Steam-game geïnstalleerd → meteen te starten met de stem
