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

Elke dienst heeft een eigen script op de laptop (het brein):
`python scripts/spotify_koppelen.py` (zie `docs/spotify.md`) en
`python scripts/gmail_koppelen.py` (zie `docs/gmail.md`). De iCloud-agenda
werkt met een app-specifiek wachtwoord in `.env`; `python
scripts/agenda_koppelen.py` controleert het (zie `docs/agenda.md`). Het
koppelscript van Spotify en Gmail:

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
