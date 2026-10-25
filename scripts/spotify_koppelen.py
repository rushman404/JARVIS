"""Spotify eenmalig koppelen (Fase 21, M5).

Draai dit op de pc waar het brein van JARVIS draait (nu de laptop):

    python scripts/spotify_koppelen.py

Het script opent de inlogpagina van Spotify in uw browser. U logt daar
zelf in en geeft toestemming (alleen lezen: toptracks, topartiesten,
recent afgespeeld en uw playlists). Spotify stuurt de browser terug naar
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
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from core import spotify_smaak  # noqa: E402

WACHT_SECONDEN = 300


def main():
    client_id = config.SPOTIFY_CLIENT_ID
    if not client_id:
        print("SPOTIFY_CLIENT_ID ontbreekt in .env. Zie docs/spotify.md, stap 1-4.")
        return 1
    redirect = config.SPOTIFY_REDIRECT_URI
    deel = urllib.parse.urlparse(redirect)
    if deel.hostname not in ("127.0.0.1", "localhost") or not deel.port:
        print(f"SPOTIFY_REDIRECT_URI moet http://127.0.0.1:<poort>/... zijn, niet {redirect}.")
        return 1

    verifier = spotify_smaak.maak_verifier()
    state = secrets.token_urlsafe(16)
    uitkomst = {}
    klaar = threading.Event()

    class Terug(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != deel.path:
                self.send_response(404)
                self.end_headers()
                return
            vraag = urllib.parse.parse_qs(url.query)
            if vraag.get("state", [""])[0] != state:
                uitkomst["fout"] = "De controlecode klopte niet (state). Probeer het opnieuw."
            elif "error" in vraag:
                uitkomst["fout"] = f"Spotify gaf geen toestemming ({vraag['error'][0]})."
            else:
                uitkomst["code"] = vraag.get("code", [""])[0]
            tekst = ("Spotify is gekoppeld aan JARVIS. U kunt dit venster sluiten."
                     if "code" in uitkomst else "Koppelen is niet gelukt. Kijk in het venster van het script.")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(tekst.encode("utf-8"))
            klaar.set()

        def log_message(self, *args):
            pass  # de URL bevat de code: niet loggen

    server = HTTPServer(("127.0.0.1", deel.port), Terug)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = spotify_smaak.autorisatie_url(client_id, verifier, state, redirect)
    print("De inlogpagina van Spotify gaat open in uw browser.")
    print("Gaat hij niet open? Kopieer dan deze link naar de browser:\n")
    print(url + "\n")
    webbrowser.open(url)

    if not klaar.wait(WACHT_SECONDEN):
        server.shutdown()
        print("Geen antwoord van Spotify binnen 5 minuten. Probeer het opnieuw.")
        return 1
    server.shutdown()
    if "fout" in uitkomst:
        print(uitkomst["fout"])
        return 1
    try:
        spotify_smaak.wissel_code(uitkomst["code"], verifier, client_id, redirect)
        prof = spotify_smaak.profiel(vers=True)
    except spotify_smaak.SpotifyFout as fout:
        print(f"Koppelen mislukt: {fout}")
        return 1
    print("Gekoppeld. " + spotify_smaak.beschrijf_smaak(prof))
    return 0


if __name__ == "__main__":
    sys.exit(main())
