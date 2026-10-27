"""Spotify eenmalig koppelen (Fase 21, M5).

Draai dit op de pc waar het brein van JARVIS draait (nu de laptop):

    python scripts/spotify_koppelen.py

Het script opent de inlogpagina van Spotify in uw browser. U logt daar
zelf in en geeft toestemming (lezen: toptracks, topartiesten, recent
afgespeeld en uw playlists; afspelen: apparaten zien en muziek starten).
Al eerder gekoppeld? Draai het gewoon opnieuw: dan krijgt JARVIS ook de
afspeelrechten. Spotify stuurt de browser terug naar
dit script op http://127.0.0.1:8888/callback; het script ruilt de code om
voor tokens en bewaart die in memory/spotify_token.json (niet in git).

Er komt nergens een wachtwoord of geheime sleutel aan te pas (PKCE). Een
token komt nooit op het scherm of in de log.

Ontkoppelen: verwijder memory/spotify_token.json en haal de toegang weg op
https://www.spotify.com/account/apps/.
"""

import os
import secrets
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core import koppelingen, spotify_smaak  # noqa: E402


def main():
    client_id = config.SPOTIFY_CLIENT_ID
    if not client_id:
        print("SPOTIFY_CLIENT_ID ontbreekt in .env. Zie docs/spotify.md, stap 1-4.")
        return 1
    redirect = config.SPOTIFY_REDIRECT_URI
    verifier = spotify_smaak.maak_verifier()
    state = secrets.token_urlsafe(16)
    url = spotify_smaak.autorisatie_url(client_id, verifier, state, redirect)

    def openen():
        print("De inlogpagina van Spotify gaat open in uw browser.")
        print("Gaat hij niet open? Kopieer dan deze link naar de browser:\n")
        print(url + "\n")
        webbrowser.open(url)

    try:
        code = koppelingen.ontvang_code(redirect, state, openen, naam="Spotify")
    except koppelingen.KoppelFout as fout:
        print(fout)
        return 1
    try:
        spotify_smaak.wissel_code(code, verifier, client_id, redirect)
        prof = spotify_smaak.profiel(vers=True)
    except spotify_smaak.SpotifyFout as fout:
        print(f"Koppelen mislukt: {fout}")
        return 1
    print("Gekoppeld. " + spotify_smaak.beschrijf_smaak(prof))
    if spotify_smaak.SpotifyKlant().mag_afspelen():
        print("Afspelen: ja. JARVIS kan nu zelf muziek laten spelen.")
    else:
        print("Afspelen: NEE. Spotify gaf alleen leesrechten. Haal de nieuwste versie op "
              "(git pull) en draai dit script opnieuw.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
