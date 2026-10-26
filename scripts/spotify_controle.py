"""Spotify-afspelen controleren (hulp bij het zoeken naar een fout).

Draai dit op de laptop (het brein), waar het Spotify-token staat:

    python scripts/spotify_controle.py

Het script laat zien welke Spotify-apparaten er zijn, wat er nu speelt,
probeert één nummer uit uw toptracks af te spelen op het apparaat dat
JARVIS zou kiezen, en laat zien wat Spotify daarna meldt. Er komt nooit
een token op het scherm.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import spotify_smaak as sp  # noqa: E402


def toon_speler(klant):
    nu = klant.get("/me/player") or {}
    if not nu:
        print("  Speler: niets actief (Spotify meldt geen speler).")
        return
    item = nu.get("item") or {}
    apparaat = nu.get("device") or {}
    print(f"  Speler: is_playing={nu.get('is_playing')}  apparaat={apparaat.get('name')!r} "
          f"(actief={apparaat.get('is_active')}, volume={apparaat.get('volume_percent')})")
    print(f"          nummer={item.get('name')!r}  uri={item.get('uri')}  "
          f"linked_from={(item.get('linked_from') or {}).get('uri')}")


def main():
    klant = sp.SpotifyKlant()
    if not klant.is_gekoppeld():
        print("Spotify is niet gekoppeld op deze pc.")
        return 1
    print(f"Afspeelrechten: {'ja' if klant.mag_afspelen() else 'NEE'}")
    apparaten = (klant.get("/me/player/devices") or {}).get("devices") or []
    print(f"Apparaten ({len(apparaten)}):")
    for a in apparaten:
        print(f"  - {a.get('name')!r}  type={a.get('type')}  actief={a.get('is_active')}  "
              f"beperkt={a.get('is_restricted')}  volume={a.get('volume_percent')}")
    print("Nu:")
    toon_speler(klant)

    keuze = sp.kies_nummer(sp.profiel(klant, vers=True))
    apparaat = sp.kies_apparaat(apparaten)
    if not keuze or not apparaat:
        print("Geen nummer of geen apparaat om te testen.")
        return 1
    print(f"\nTest: {sp.label(keuze)} ({keuze['uri']}) op {apparaat.get('name')!r}")
    try:
        if not apparaat.get("is_active"):
            klant.put("/me/player", None, {"device_ids": [apparaat["id"]], "play": False})
            print("  Overzetten naar dit apparaat: ok")
            time.sleep(1)
        body = sp.afspeel_body(klant, keuze)
        print(f"  Opdracht: {body}")
        klant.put("/me/player/play", {"device_id": apparaat["id"]}, body)
        print("  Afspeelopdracht: ok (Spotify nam hem aan)")
    except sp.SpotifyFout as fout:
        print(f"  Spotify weigerde: {fout}")
        return 1
    for i in range(5):
        time.sleep(1)
        print(f"Na {i + 1} s:")
        toon_speler(klant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
