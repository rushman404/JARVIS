"""Reistijden berekenen (Fase 16C) — keyless via OSRM + Nominatim.

Er is geen API-sleutel nodig:

  * Nominatim (OpenStreetMap) zoekt de coördinaten van een plaatsnaam.
  * OSRM (router.project-osrm.org) berekent de auto-route en -tijd.

Let op: dit is een schatting op basis van afstand en wegtype. Er wordt
geen live verkeersinformatie gebruikt (file-informatie zit hier dus niet
in). Alle functies zijn fail-closed en crashen nooit.
"""
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
# Nominatim vereist een herkenbare User-Agent.
USER_AGENT = "JARVIS/1.0 (persoonlijke assistent)"
TIMEOUT = (3, 10)

# Plaatsnamen die al eens opgezocht zijn (beperkt het aantal Nominatim-
# aanroepen). Sleutel is de kleine-letter-versie van de plaatsnaam.
_geocode_cache = {}


def reset_cache():
    """Leegt de geocode-cache (handig voor tests)."""

    _geocode_cache.clear()


def geocode(plaats, timeout=TIMEOUT, get_fn=None):
    """Zoekt de coördinaten van ``plaats``; (lat, lon) of None."""

    sleutel = (plaats or "").strip().lower()
    if not sleutel:
        return None
    if sleutel in _geocode_cache:
        return _geocode_cache[sleutel]

    ophalen = get_fn or requests.get
    try:
        response = ophalen(
            NOMINATIM_URL,
            params={"q": plaats, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:  # noqa: BLE001 - fail-closed
        return None

    if not data:
        return None
    try:
        punt = (float(data[0]["lat"]), float(data[0]["lon"]))
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    _geocode_cache[sleutel] = punt
    return punt


def bereken_reis(van, naar, timeout=TIMEOUT, get_fn=None):
    """Berekent de auto-afstand en -tijd van ``van`` naar ``naar``.

    Geeft ``{"ok", "van", "naar", "afstand_km", "minuten"}`` terug, of
    ``{"ok": False, "error": ...}`` als een plaats niet gevonden wordt of
    de route niet te berekenen is.
    """

    van = (van or "").strip()
    naar = (naar or "").strip()
    if not van or not naar:
        return {
            "ok": False,
            "error": "Ik heb zowel een vertrekpunt als een bestemming nodig.",
        }

    start = geocode(van, get_fn=get_fn)
    eind = geocode(naar, get_fn=get_fn)
    if start is None or eind is None:
        return {
            "ok": False,
            "van": van,
            "naar": naar,
            "error": "Ik kon een van de plaatsen niet vinden.",
        }

    ophalen = get_fn or requests.get
    coordinaten = f"{start[1]},{start[0]};{eind[1]},{eind[0]}"
    url = f"{OSRM_URL}/{coordinaten}"
    try:
        response = ophalen(
            url,
            params={"overview": "false"},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        route = data["routes"][0]
        afstand_km = round(float(route["distance"]) / 1000.0, 1)
        minuten = max(1, int(round(float(route["duration"]) / 60.0)))
    except Exception as error:  # noqa: BLE001 - fail-closed
        return {
            "ok": False,
            "van": van,
            "naar": naar,
            "error": f"Route berekenen mislukte: {error}",
        }

    return {
        "ok": True,
        "van": van,
        "naar": naar,
        "afstand_km": afstand_km,
        "minuten": minuten,
    }


def format_reis(resultaat):
    """Zet het resultaat van :func:`bereken_reis` om in spreekbare tekst."""

    if not resultaat or not resultaat.get("ok"):
        fout = (resultaat or {}).get("error") or "Ik kon de reistijd niet berekenen."
        return fout

    van = resultaat.get("van", "")
    naar = resultaat.get("naar", "")
    minuten = resultaat.get("minuten", 0)
    afstand = resultaat.get("afstand_km", 0)

    if minuten >= 60:
        uren, rest = divmod(minuten, 60)
        duur = f"{uren} uur" + (f" en {rest} minuten" if rest else "")
    else:
        duur = f"{minuten} minuten"

    return (
        f"Van {van} naar {naar} is ongeveer {afstand} kilometer en duurt "
        f"ongeveer {duur} met de auto. Let op: dit is een schatting zonder "
        f"live verkeersinformatie."
    )
