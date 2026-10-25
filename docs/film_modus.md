# Film-modus (Fase 21)

"JARVIS, filmavond" of "zet Disney+ op de tv" maakt de kamer klaar voor een film.
Licht en gordijnen blijven bewust zoals ze zijn.

## Wat er gebeurt (M1)

1. **Tv aan:** JARVIS drukt in Home Assistant op de Wake-on-LAN-knop van de tv
   (een LG webOS gaat alleen zo aan) en wacht tot hij aan is (max. 30 s).
2. **App:** de gevraagde dienst opent via de bronkeuze van de tv. Zonder dienst: Netflix.
3. **Pc stil** (op de game-pc): Discord gedempt en Spotify gepauzeerd, maar alleen
   als Spotify echt speelt (JARVIS start nooit per ongeluk muziek).
   Staat de game-pc uit, dan slaat JARVIS dit over en zegt hij dat.
4. **Onthouden:** hoe het was staat in `memory/film_toestand.json` (niet in git).

"Film klaar" zet alles terug: Discord weer aan (alleen als JARVIS hem dempte),
de tv terug naar de vorige bron, of uit als hij uit stond. Spotify gaat niet
vanzelf verder.

JARVIS vertelt elke stap kort ("Tv wordt geactiveerd… Netflix geladen…").

## Zinnen

| Zeg | Wat |
|---|---|
| "filmavond", "ik ga een film kijken", "start de film" | film-modus met Netflix (routine `movie`) |
| "zet Netflix / Disney plus / Prime Video / YouTube op de tv" | film-modus met die app |
| "zet de tv op Disney+", "ik wil YouTube kijken", "filmavond met Prime Video" | idem |
| "film klaar", "einde film", "de film is afgelopen", "zet filmmodus uit" | alles terug |

"Open Netflix" blijft Netflix op de pc openen.

## Instellingen (`.env`, optioneel)

JARVIS zoekt de tv en de aan-knop zelf in Home Assistant (een webOS-/tv-mediaspeler
en een `wake_on_lan`-knop met de naam "Tv"). Vindt hij de verkeerde, zet dan:

```
FILM_TV_ENTITY=media_player.lg_webos_tv_ua75006la
FILM_TV_AAN_KNOP=button.wake_on_lan_60_75_6c_70_15_12
```

## Game-pc-agent bijwerken

Spotify pauzeren is een nieuwe agent-actie (`media_pause_app`). Werk daarom ook de
game-pc bij (`git pull`) en herstart de agent; anders doet alleen het Discord-dempen
het en slaat JARVIS de pauze stil over.

## Testlijst

- [ ] Tv uit → "JARVIS, filmavond" → tv gaat aan, Netflix opent, u hoort de stappen
- [ ] Spotify speelt op de game-pc → na de film-modus staat hij op pauze; Discord is gedempt
- [ ] Spotify staat al op pauze → de film-modus start hem **niet**
- [ ] "Film klaar" → Discord weer aan, tv gaat uit
- [ ] Tv aan op Live TV → "zet YouTube op de tv" → YouTube; "film klaar" → terug naar Live TV, tv blijft aan
- [ ] De lampen veranderen nergens
- [ ] Game-pc uit → "filmavond" → tv en app werken, JARVIS meldt dat de game-pc is overgeslagen
- [ ] Dashboard → Routines → film → zelfde film-modus (antwoord in de chat)
