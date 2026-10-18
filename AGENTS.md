# Project instructions

## Geheugen van de gebruiker (Obsidian)

Deze workspace heeft een persoonlijk geheugen over de gebruiker, opgeslagen in een Obsidian-vault:

- **Pad:** `JARVIS Memory/Geheugen/Over Rushil.md`
- **Lees dit bestand aan het begin van elke sessie** (vóór je eerste antwoord), zodat je weet wie de gebruiker is: naam, leeftijd, woonplaats, opleiding, hobby's en aanspreekvorm (spreek hem formeel aan met "u").
- Deze vault staat in `.gitignore` (persoonlijke data hoort niet in git, de repo is gekoppeld aan GitHub). Daardoor is de map **onzichtbaar voor glob/grep** vanaf de werkmap: zoek er dus niet naar met zoekopdrachten, maar gebruik het exacte pad hierboven.
- Het geheugen is met de hand te bewerken in Obsidian. Voeg nieuwe feiten toe in dat bestand; het bestand is de bron van waarheid.
- Naast dit leesbestand staan dezelfde feiten ook als losse **JARVIS-geheugens** in de vault (Memory 2.0-formaat):
  - Pad: `JARVIS Memory/<categorie>/<sleutel>.md`, met frontmatter `memory_key`, `category`, `value_type` en de waarde als `> ...`-regel in de body.
  - Categorieën (mappen): `voorkeuren`, `pc`, `projecten`, `muziek`, `algemeen`, `apparaten`.
  - JARVIS laadt ze met **"importeer alles uit mijn vault"** (één notitie: "zet <notitie> in mijn geheugen") en schrijft zijn eigen geheugen terug met **"exporteer mijn geheugen naar de vault"**. Er is geen automatische sync; alles gebeurt op verzoek.
- **Houd `Over Rushil.md` én de Memory 2.0-notities gelijk.** Nieuw feit? Zet het in allebei (of maak er een nieuwe notitie voor in de juiste categoriemap).

## Overig

- Reageer in het Nederlands, tenzij de gebruiker anders vraagt.
