# Koppelingen (Fase 23)

JARVIS gebruikt een paar accounts van u: nu Spotify, straks Gmail en de
iCloud-agenda. Alle koppelingen lopen via één basis: `core/koppelingen.py`.

## Vragen

* *"Welke koppelingen heb ik?"* / *"Zijn mijn koppelingen in orde?"*
  → bijvoorbeeld: "Gekoppeld: Spotify (lezen en afspelen). Nog niet gekoppeld: …"
* Het **Systeem-paneel** op het dashboard toont een regel *Koppelingen:
  Spotify ✓*. Een **!** (oranje) betekent dat er iets mis is, meestal
  "opnieuw koppelen nodig": de toegang is ingetrokken of verlopen. Draai dan
  het koppelscript van die dienst opnieuw. Een **–** betekent: nog niet gekoppeld.

## Koppelen

Elke dienst heeft een eigen script op de laptop (het brein), bijvoorbeeld
`python scripts/spotify_koppelen.py`. Het script:

1. opent de inlogpagina van de dienst in uw browser; u logt daar **zelf** in;
2. vangt het antwoord op via `http://127.0.0.1:<poort>/...` (alleen op deze pc);
3. bewaart de tokens en meldt wat JARVIS mag (bijv. "Afspelen: ja").

## Veiligheid

* Tokens staan in `memory/koppelingen/` (Spotify nog in
  `memory/spotify_token.json`); beide staan in `.gitignore`.
* Een token komt nooit in de log, het auditlog, een URL of een antwoord. De
  status laat alleen zien *of* er gekoppeld is en *welke rechten* er zijn.
* Koppelen gebruikt PKCE en een willekeurige controlecode (state): een
  antwoord dat niet bij uw eigen inlogpoging hoort, wordt geweigerd.
* Ontkoppelen: verwijder het tokenbestand en haal de toegang weg in de
  accountinstellingen van de dienst.
