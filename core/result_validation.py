"""
Resultaatvalidatie (Fase 9, stap 4)

Classificeert het tekstresultaat van een tool-aanroep in drie
categorieën, puur op algemene signaalwoorden — zonder per-tool
hardcoded regels:

    "success"   : niets wijst op mislukking
    "failed"    : het resultaat meldt aantoonbaar een fout
    "uncertain" : het resultaat is onduidelijk (bv. een neveneffect
                  dat niet lukte, of een verduidelijkingsvraag);
                  mag NIET automatisch als succes gelden

Executor-statussen blijven leidend: deze classificatie bepaalt
alleen of een "done"-resultaat betrouwbaar geslaagd genoemd mag
worden.
"""

# Duidelijke neveneffect-meldingen: de hoofdactie lijkt gelukt,
# maar er is iets kleins misgegaan -> onzeker, niet blind "succes".
UNCERTAIN_PATTERNS = (
    "venster kon niet naar voren",
    "venster kon niet naar de voorgrond",
)

# Algemene Nederlandse fout-signaalwoorden zoals de bestaande
# actions/tools die teruggeven.
FAILED_PATTERNS = (
    "kon niet",
    "konden niet",
    "kan niet",
    "niet gevonden",
    "niet vinden",
    "niet te vinden",
    "nicht gevonden",
    "geen programma",
    "geen venster",
    "geen bestand",
    "geen map",
    "onbekende tool",
    "onbekende opdracht",
    "mist een argument",
    "argument ontbreekt",
    "ontbrak",
    "mislukt",
    "mislukte",
    "niet gelukt",
    "niet mogelijk",
    "niet beschikbaar",
    "niet ondersteund",
    "niet uitgevoerd",
    "geen toegang",
    "geweigerd",
    "afgebroken",
    "fout opgetreden",
)


def classify_tool_result(result):

    """
    Geeft "success", "failed" of "uncertain".

    Een resultaat dat zelf een vraag is (bv. "Welk programma wil je
    openen?") is per definitie onzeker: er is dan niets uitgevoerd.
    """

    text = str(result or "").strip().lower()

    if not text:
        return "uncertain"

    if text.endswith("?"):
        return "uncertain"

    for pattern in UNCERTAIN_PATTERNS:
        if pattern in text:
            return "uncertain"

    for pattern in FAILED_PATTERNS:
        if pattern in text:
            return "failed"

    return "success"