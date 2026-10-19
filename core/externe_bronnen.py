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
_NIEUWS_PATROON_OPDRACHT = re.compile(
    r"^(?:(?:hey\s+|ok(?:é)?\s+|jarvis[,\s]+))*"
    r"(?:wat\s+is\s+(?:er\s+in\s+)?het\s+(?:laatste\s+|actuele\s+|nieuwste\s+)?"
    r"nieuws"
    r"|wat\s+is\s+het\s+(?:tech|technologie)[\s-]*nieuws"
    r"|geef\s+(?:me|mij)?\s*(?:het\s+)?(?:laatste\s+|actuele\s+|nieuwste\s+)?"
    r"nieuws"
    r"|lees\s+(?:het\s+)?(?:laatste\s+|actuele\s+|nieuwste\s+)?nieuws"
    r"(?:\s+voor)?"
    r"|toon\s+(?:het\s+)?(?:laatste\s+|actuele\s+|nieuwste\s+)?nieuws"
    r"|vertel\s+(?:me|mij)?\s*(?:het\s+)?(?:laatste\s+|actuele\s+|nieuwste\s+)?"
    r"nieuws"
    r"|laat\s+me\s+het\s+(?:laatste\s+|actuele\s+|nieuwste\s+)?nieuws\s+zien"
    r"|hoe\s+is\s+het\s+(?:laatste\s+|actuele\s+|nieuwste\s+)?nieuws"
    r"|(?:het\s+)?(?:laatste|actuele|nieuwste)\s+nieuws"
    r"|nieuws\s+van\b"
    r"|nieuws\s*$)",
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

# Alledaagse producten (geen merk, geen model): hiervoor start JARVIS geen
# prijsopzoek. Twijfelgevallen uit deze lijst geven dus rustig None terug.
ALLEDAAGSE_PRODUCTEN = frozenset([
    "brood", "broden", "jas", "jassen", "fiets", "fietsen", "auto", "autos",
    "parkeren", "parkeerplaats", "koffie", "thee", "melk", "boter", "kaas",
    "appel", "appels", "sinaasappel", "telefoon", "laptop", "pc", "stoel",
    "tafel", "deur", "raam", "melkpak", "boodschappen", "benzine", "benzine",
])

# Merk-/modelnamen waarvan een prijsopzoek direct mag starten.
MERK_EN_MODEL_PATROON = re.compile(
    r"\b(rtx|gtx|rx\s?\d|ps\d|xbox|iphone|ipad|macbook|samsung|pixel|galaxy"
    r"|lenovo|huawei|oneplus|asus|acer|msi|sony|nintendo)\b",
    re.IGNORECASE,
)

# Modelwoorden die een productnaam concreet genoeg maken.
MODEL_WOORDEN_PATROON = re.compile(
    r"\b(rog|strix|tuf|pro|max|plus|ultra|mini|air|oled|qled|amoled|5g|wifi"
    r"|bluetooth|smart|wireless|rgb|mechanical)\b",
    re.IGNORECASE,
)

# Twijfelgevallen (geen merk, geen cijfercode): JARVIS vraagt eerst om
# bevestiging met een korte TTL voordat hij iets naar DuckDuckGo stuurt.
PRIJS_CONFIRM_TTL_SECONDS = 15

# Vulwoorden en bijwoorden: zo'n woord in de productnaam betekent dat de
# zin een mededeling is ("de prijs is hoog"), geen productvraag.
_PRIJS_VULWOORDEN = re.compile(
    r"\b(is|was|waren|blijft|blijven|wordt|worden|gestegen|gedaald|hoog"
    r"|laag|duur|duurder|goedkoop|goedkoper|belachelijk|te|veel|weinig"
    r"|ongeveer|hier|daar|niets|niks|alles|nogal|erg|heel|zeer"
    r"|tegenwoordig|vroeger|me|mij|ons|je|jij|hem|haar|dat|dit|die"
    r"|deze|euro|euros|cent|eigenlijk|eerst|even|maar)\b",
    re.IGNORECASE,
)

# Onbepaalde woorden die een zinsdeel (geen product) verraden.
_ALGEMENE_WOORDEN = frozenset([
    "mens", "mensen", "keer", "stuk", "ding", "iets", "niets", "euro",
    "euros", "cent", "geld", "bedrag", "prijs", "wij", "ik", "jullie",
])


def _schoon_plaats(tekst):
    """Haalt vervoermiddel en leestekens van een plaatsnaam af."""

    tekst = _VERVOER_STAART.sub("", tekst or "")
    return tekst.strip().strip("?.!").strip()


def _is_plaatsnaam_algemeen(tekst):
    """Schat of een plaatsnaam een algemeen begrip is (geen echte plaats)."""
    t = (tekst or "").lower().strip()
    # Alledaagse, vage begrippen die geen reisdoel zijn
    if not t:
        return True
    for zwak in ("mijn huis", "het huis", "huis", "de winkel", "winkel",
                 "school", "de school", "werk", "het werk", "mijn werk",
                 "thuis", "kantoor", "de supermarkt", "supermarkt"):
        if t == zwak or t.startswith(zwak + " ") or t.endswith(" " + zwak):
            return True
    return False


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
    if _is_plaatsnaam_algemeen(van) or _is_plaatsnaam_algemeen(naar):
        return None
    return reistijden.format_reis(reistijden.bereken_reis(van, naar))


def _is_alledaags_product(product):
    """True voor alledaagse, onbepaalde producten (brood, jas, parkeren ...).

    Hiervoor start JARVIS geen prijsopzoek: het is geen concrete
    productvraag en de uitkomst zou toch niets bruikbaars opleveren.
    """

    t = (product or "").lower().strip()
    if not t:
        return True
    if t in ALLEDAAGSE_PRODUCTEN:
        return True
    # "nieuwe fiets", "die jas", "een nieuw brood" -> kernwoord alledaags.
    kern = t.split()[-1]
    return kern in ALLEDAAGSE_PRODUCTEN


def _twijfel_product(product):
    """True als JARVIS eerst moet vragen voordat hij een prijs opzoekt.

    Concrete producten (merk, cijfercode, modelwoord, langere merkachtige
    naam) mogen direct; kaal onbekend (bijv. "koptelefoon") eerst vragen.
    """

    p_low = (product or "").lower().strip()
    if not p_low:
        return False
    if MERK_EN_MODEL_PATROON.search(p_low):
        return False
    if re.search(r"\d", p_low):
        return False
    if MODEL_WOORDEN_PATROON.search(p_low):
        return False
    if p_low in ALLEDAAGSE_PRODUCTEN:
        return False
    return True


def _verwerk_nieuws(command):
    """Verwerkt een nieuws-vraag; None als het geen nieuws-vraag is."""

    if not _NIEUWS_PATROON_OPDRACHT.search(command):
        return None

    bron_match = _BRON_PATROON.search(command)
    bronnen = [bron_match.group(1).lower()] if bron_match else None

    return nieuws.format_nieuws(nieuws.haal_nieuws(bronnen))


def _lijkt_mededeling(product):
    """True als de "productnaam" eigenlijk een mededeling is.

    "de prijs is hoog", "een auto kost veel geld", "dat kost me te veel"
    zijn geen productvragen: er zit een werkwoordsvorm, bijwoord of
    prijsaanduiding in de naam in plaats van een concreet product.
    """

    if _PRIJS_VULWOORDEN.search(product or ""):
        return True
    # Losse, onbekende, lange zinsdelen ("mens tegenwoordig") zijn geen
    # productnaam als ze uit meerdere alledaagse woorden bestaan.
    woorden = (product or "").lower().split()
    return len(woorden) >= 2 and all(
        w in ALLEDAAGSE_PRODUCTEN or w in _ALGEMENE_WOORDEN for w in woorden
    )


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

    if _is_alledaags_product(product):
        # Brood, jas, parkeren: dit is geen productvraag. Rustig niets doen.
        return None

    # "wat kost een stoel bij de kringloop": de staart noemt een winkel,
    # dus de vraag is concreet genoeg — geen twijfel-flow.
    match_winkel = re.search(
        r"\b(?:bij|op)\s+(?:de\s+|het\s+)?"
        r"(kringloop|kringloopwinkel|markt|beurs|outlet|action|kruidvat|"
        r"mediamarkt|marktplaats|aliexpress|intertoys|blokker)\b",
        command.lower(),
    )
    if match_winkel:
        # Laat de winkellaart uit de productnaam ("stoel bij de kringloop").
        schoon = re.sub(
            r"\s+(?:bij|op)\s+(?:de\s+|het\s+)?"
            r"(kringloop|kringloopwinkel|markt|beurs|outlet|action|kruidvat|"
            r"mediamarkt|marktplaats|aliexpress|intertoys|blokker)\s*$",
            "",
            product,
            flags=re.IGNORECASE,
        ).strip()
        product = schoon or product
        winkels = prijzen._winkels_uit_tekst(command)
        return prijzen.format_prijs(prijzen.zoek_prijs(product, winkels=winkels))

    if _lijkt_mededeling(product):
        # "de prijs is hoog", "dat kost me te veel": een mededeling.
        return None

    if _twijfel_product(product):
        # Geen merk, geen cijfercode: eerst vragen voor JARVIS iets opzoekt.
        try:
            from core import confirmation

            confirmation.set_pending(
                "prijs_confirm",
                payload={"product": product},
                ttl=PRIJS_CONFIRM_TTL_SECONDS,
            )
            return (
                f"Wil je dat ik de prijs van '{product}' opzoek? "
                "Zeg 'ja' of 'nee'."
            )
        except Exception:
            # Zonder pending-state liever niets opzoeken dan stil zoeken.
            return None

    winkels = prijzen._winkels_uit_tekst(command)
    return prijzen.format_prijs(prijzen.zoek_prijs(product, winkels=winkels))


def zoek_product_prijs(product, vraag=None):
    """Zoekt de prijs van een bevestigd product (na een 'ja').

    Wordt aangeroepen vanuit de pending-flow in core/brain.py, zodat de
    zoekopdracht pas vertrekt nadat de gebruiker expliciet 'ja' zei.
    """

    winkels = prijzen._winkels_uit_tekst(vraag or product or "")
    return prijzen.format_prijs(
        prijzen.zoek_prijs(product, winkels=winkels)
    )


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
