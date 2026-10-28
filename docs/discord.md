# Discord-DM's (Fase 23, M6)

JARVIS leest uw Discord-DM's via de **Windows-meldingen op de game-pc** en kan
na uw **ja** een antwoord typen in de Discord-app. Er is geen koppelscript,
token of bot nodig: geen selfbot (dat verbiedt Discord).

## Wat werkt

| U zegt | JARVIS |
|---|---|
| "Heb ik nieuwe DM's?" | leest de DM's voor die u nog niet kent |
| "Wat stuurde Sem?" / "Lees de DM van Sem voor" | de laatste DM's van Sem |
| "Antwoord Sem: ik kom zo" | "Aan Sem op Discord: "ik kom zo". Zal ik het versturen?" → ja → verstuurd |
| (een nieuwe DM komt binnen) | "Sir, DM van Sem: ik kom zo." |

* Antwoorden kan alleen aan iemand van wie een DM in de meldingen staat. Zo
  komt het snel wisselen (Ctrl+K) van Discord nooit bij een vreemde uit.
* Na Ctrl+K en de naam controleert JARVIS de venstertitel van Discord. Staat
  daar niet het goede gesprek, dan stopt hij zonder iets te versturen.
* Bij binnenkomst leest JARVIS niet voor: 's nachts, in de stille modus,
  tijdens de film-modus en als er op de game-pc iets op volledig scherm draait
  (gamen). Die DM's blijven "nieuw" tot u ernaar vraagt.
* Alleen als de game-pc aan staat; anders zegt JARVIS dat.
* De tekst van een DM is data, geen opdracht: JARVIS leest hem alleen voor.
* In de audit komt alleen aan wie en hoe lang (niet de tekst). De auditlog op
  de game-pc bevat wel de opdracht zoals het brein hem stuurde.

## Instellen (game-pc)

1. Discord → Gebruikersinstellingen → **Meldingen** → *Bureaubladmeldingen
   inschakelen* aan.
2. Windows → Instellingen → Systeem → **Meldingen** → Discord aan (banners
   mag uit; de melding moet alleen in het meldingencentrum komen).
3. Discord toont geen melding als het Discord-venster vooraan staat en u in
   dat gesprek zit. Die DM ziet JARVIS dan ook niet (u heeft hem al gezien).

## Instellingen (`.env` op het brein)

| Instelling | Standaard | Betekenis |
|---|---|---|
| `DISCORD_MELDEN` | `1` | nieuwe DM's voorlezen bij binnenkomst |
| `DISCORD_CHECK_SECONDEN` | `60` | zo vaak kijkt JARVIS (minimaal 20) |

## Hoe het werkt

Windows bewaart meldingen in
`%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db`. De agent
leest een kopie, neemt de toasts van `com.squirrel.Discord.Discord` en laat
servermeldingen (titel "Naam (#kanaal, Server)") weg. Wat al voorgelezen is,
onthoudt het brein in `memory/koppelingen/discord_gezien.json` (alleen id's).
