"""Openstaande bevestigingen (pending-keuzes) met een verlooptijd.

De state staat alleen in het geheugen van dit proces: hij wordt NOOIT
naar de schijf geschreven en overleeft een herstart van JARVIS dus niet.
Zonder verlooptijd zou een "ja" uren later alsnog een afsluiting uitvoeren.
"""

import re
import time

from config import CONFIRM_TTL_SECONDS

# Sleutels die deze module zelf aan een pending hangt.
EXPIRES_KEY = "_expires_at"
REASKED_KEY = "_reasked"

# Exacte ja-match voor gevaarlijke bevestigingen (power, delete, empty, overwrite)
STRICT_YES = frozenset([
    "ja",
    "ja doe maar",
    "doe maar",
    "ja graag",
    "bevestig",
])

# Woorden die een ontkenning aangeven — bij aanwezigheid is het ALTIJD "nee",
# ook als er "ja" in voor komt (bijv. "ja maar niet nu").
DENIAL_WORDS = frozenset([
    "niet",
    "nee",
    "stop",
    "laat maar",
    "annuleer",
    "cancel",
    "geen",
    "liever niet",
    "stoppen",
])

# Voor onschuldige keuzes (nummer, locatie) mag de losse matching blijven.
LOOSE_YES_WORDS = frozenset([
    "ja", "jep", "jup", "jawel", "ja hoor", "ja doe maar", "ja doe het",
    "doe maar", "doe het", "doe maar hoor", "ga door", "ga je gang",
    "prima", "goed", "oke", "ok", "oké", "okee", "klopt",
    "bevestig", "bevestigen", "tuurlijk", "natuurlijk", "jazeker",
    "yep", "yes", "ja graag", "doen", "doe het maar",
])

LOOSE_NO_WORDS = frozenset([
    "nee", "nope", "niet doen", "doe maar niet", "laat maar",
    "laat maar zitten", "niet", "stop", "annuleer", "cancel",
    "nee hoor", "geen prullenbak", "liever niet", "stoppen",
])


def _normalize(text: str) -> str:
    """Normaliseer voor strikte matching: kleine letters, leestekens weg."""
    return re.sub(r"[^\w\s]", "", text.lower().strip())


def is_strict_yes(text: str) -> bool:
    """True als de tekst na normalisatie exact op een strict-ja lijkt."""
    return _normalize(text) in STRICT_YES


def contains_denial(text: str) -> bool:
    """True als de tekst een ontkennend woord bevat."""
    norm = _normalize(text)
    return any(w in norm for w in DENIAL_WORDS)


def is_loose_yes(text: str) -> bool:
    """Losse matching voor onschuldige keuzes (nummer/locatie)."""
    t = text.lower().strip().strip(" .!?")
    if t in LOOSE_YES_WORDS:
        return True
    return bool(re.match(r"^(ja|jazeker|jawel|jep|jup|yep|yes|tuurlijk|natuurlijk|prima|goed|oke|ok)\b", t))


def is_loose_no(text: str) -> bool:
    """Losse matching voor onschuldige keuzes."""
    t = text.lower().strip().strip(" .!?")
    if t in LOOSE_NO_WORDS:
        return True
    return bool(re.match(r"^(nee|nope|niet)\b", t))


# --- gevaarlijke soorten ---
DANGEROUS_KINDS = frozenset([
    "power_confirm",
    "delete_confirm",
    "empty_confirm",
    "memory_update",  # overschrijven geheugen/export
    "tool_approval",  # een medium/high tool-aanroep via de bewaakte poort
])


def is_dangerous_kind(kind: str) -> bool:
    return kind in DANGEROUS_KINDS


def _current_context():
    # Late import om een circulaire import met core.ai te voorkomen;
    # op het moment van aanroepen is core.ai altijd al geladen.
    from core.ai import current_context
    return current_context


def set_pending(kind, payload=None, ttl=None):
    """Zet een nieuwe openstaande bevestiging met verlooptijd.

    kind   — soort bevestiging, bijv. "power_confirm"
    payload — overige velden van de pending (action, matches, ...)
    ttl    — hoeveel seconden de vraag geldig blijft; standaard komt
             uit config.CONFIRM_TTL_SECONDS
    """

    if ttl is None:
        ttl = CONFIRM_TTL_SECONDS

    data = dict(payload or {})
    data["kind"] = kind
    data[EXPIRES_KEY] = time.time() + ttl
    data[REASKED_KEY] = False
    data.pop("_answered", None)

    _current_context()["pending_choice"] = data

    return data


def get_pending():
    """Geeft de openstaande bevestiging, of None als er geen is.

    Is de ttl verlopen, dan wordt de state gewist en teruggegeven None.
    Een pending zonder verlooptijd (gezet vóór deze module, bijvoorbeeld
    direct in tests) geldt alleen voor deze sessie en verloopt niet.
    """

    pending = _current_context().get("pending_choice")

    if not pending:
        return None

    expires_at = pending.get(EXPIRES_KEY)

    if expires_at is not None and time.time() >= expires_at:
        clear_pending()
        return None

    return pending


def clear_pending():
    """Wist de openstaande bevestiging."""

    _current_context()["pending_choice"] = None


def evaluate_answer(text: str, kind: str) -> str:
    """Evalueert een gebruikersantwoord op een pending bevestiging.

    Returns: "yes", "no", "unclear", "expired", "cancel"
    """
    if not text:
        return "unclear"

    pending = get_pending()
    if not pending:
        return "expired"

    # Check of al een keer hergevraagd is
    reasked = pending.get(REASKED_KEY, False)

    # Gevaarlijke soorten: strikte matching, denial = altijd nee
    if is_dangerous_kind(kind):
        # Ontkenning check eerst (ook als "ja" in zit)
        if contains_denial(text):
            return "no"
        # Dan strikte ja-check
        if is_strict_yes(text):
            return "yes"
    else:
        # Onschuldige soorten: losse matching
        if is_loose_no(text):
            return "no"
        if is_loose_yes(text):
            return "yes"

    # Geen duidelijke ja/nee
    if reasked:
        # Tweede keer onduidelijk -> annuleer de flow, verwerk commando als nieuw
        return "cancel"
    else:
        # Eerste keer -> markeer als hergevraagd en vraag opnieuw
        pending[REASKED_KEY] = True
        return "unclear"


def get_reask_prompt(kind: str) -> str:
    """Geeft de prompt voor herhaling van de vraag."""
    if kind == "tool_approval":
        return "Zeg duidelijk 'ja' om door te gaan, of 'nee' om af te breken."
    if is_dangerous_kind(kind):
        return "Zeg duidelijk 'ja' of 'nee'. Je kunt ook 'annuleer afsluiten' of 'annuleer herstart' zeggen."
    return "Zeg 'ja' of 'nee'."
