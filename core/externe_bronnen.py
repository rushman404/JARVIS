"""Op-aanvraag-commando's voor externe bronnen (Fase 16C).

Deterministisch pad voor:
  * nieuws   — "wat is het nieuws", "nieuws van Tweakers"
  * reistijd — "hoe lang duurt het van Amsterdam naar Utrecht"
  * prijzen  — "wat kost een IPad bij bol.com"

Zelfde patroon als ``core.proactive_commands``: JARVIS probeert dit vóór
het Agent/LLM-pad, zodat deze vragen zonder AI-hallucinaties worden
beantwoord. Geeft een antwoord-string terug, of None als het commando
niets met een externe bron te maken heeft.
"""
import re

from actions import nieuws
from actions import prijzen
from actions import reistijden

# --- Reistijden ---------------------------------------------------------

_REIS_PATROON = re.compile(
    r"\b(hoe\s+lang|hoelang|hoe\s+ver|reistijd|rijtijd|reis\s+tijd|route)\b",
    re.IGNORECASE,
)
_VAN_NAAR_PATROON = re.compile(
    r"\b(?:van|vanaf)\s+(?P<van>.+?)\s+naar\s+(?P<naar>.+)$",
    re.IGNORECASE,
)
_VERVOER_STAART = re.compile(
    r"\s+(?:met\s+de\s+|met\s+|per\s+)?"
    r"(?:auto|fiets|trein|bus|motor|lopend|te\s+voet)\s*[?.!]*$",
    re.IGNORECASE,
)

# --- Nieuws -------------------------------------------------------------

_NIEUWS_PATROON = re.compile(
    r"\b(nieuws|headlines|nieuwsberichten|voorpagina)\b",
    re.IGNORECASE,
)
_BRON_PATROON = re.compile(r"\b(nos|tweakers)\b", re.IGNORECASE)

# --- Prijzen ------------------------------------------------------------

_PRIJS_PATROON = re.compile(
    r"\b(prijs(?:je)?|kost(?:en)?|hoeveel\s+kost|wat\s+kost(?:en)?)\b",
    re.IGNORECASE,
)
_PRODUCT_PATROON = re.compile(
    r"(?:prijs(?:je)?\s+van|hoeveel\s+kost(?:en)?|wat\s+kost(?:en)?|"
    r"prijs(?:je)?|kost(?:en)?)\s+(?P<product>.+)$",
    re.IGNORECASE,
)
_WINKEL_STAART = re.compile(
    r"\s+(?:bij|op|van)\s+(?:bol(?:\.com)?|coolblue|amazon(?:\.nl)?)\s*[?.!]*$",
    re.IGNORECASE,
)
_LIDWOORD_STAART = re.compile(
    r"^(?:een|de|het|mijn|die|dat|dit|deze)\s+",
    re.IGNORECASE,
)


def _schoon_plaats(tekst):
    """Haalt vervoermiddel en leestekens van een plaatsnaam af."""

    tekst = _VERVOER_STAART.sub("", tekst or "")
    return tekst.strip().strip("?.!").strip()


def _verwerk_reistijd(command):
    """Verwerkt een reistijd-vraag; None als het geen reistijd-vraag is."""

    match = _VAN_NAAR_PATROON.search(command)
    if not match:
        return None
    if not _REIS_PATROON.search(command):
        return None

    van = _schoon_plaats(match.group("van"))
    naar = _schoon_plaats(match.group("naar"))
    if not van or not naar:
        return None
    return reistijden.format_reis(reistijden.bereken_reis(van, naar))


def _verwerk_nieuws(command):
    """Verwerkt een nieuws-vraag; None als het geen nieuws-vraag is."""

    if not _NIEUWS_PATROON.search(command):
        return None

    bron_match = _BRON_PATROON.search(command)
    bronnen = [bron_match.group(1).lower()] if bron_match else None

    return nieuws.format_nieuws(nieuws.haal_nieuws(bronnen))


def _verwerk_prijs(command):
    """Verwerkt een prijs-vraag; None als het geen prijs-vraag is."""

    if not _PRIJS_PATROON.search(command):
        return None

    match = _PRODUCT_PATROON.search(command)
    if not match:
        return None

    product = _WINKEL_STAART.sub("", match.group("product"))
    product = _LIDWOORD_STAART.sub("", product.strip())
    product = product.strip().strip("?.!")
    if not product:
        return None

    winkels = prijzen._winkels_uit_tekst(command)
    return prijzen.format_prijs(prijzen.zoek_prijs(product, winkels=winkels))


def try_externe_bron_command(command):
    """Verwerkt commando's voor externe bronnen (nieuws/reistijden/prijzen).

    Geeft een antwoord-string, of None als het commando hier niet bij hoort.
    """

    if not command:
        return None

    command = command.lower().strip()

    for verwerker in (_verwerk_reistijd, _verwerk_nieuws, _verwerk_prijs):
        resultaat = verwerker(command)
        if resultaat is not None:
            return resultaat

    return None
