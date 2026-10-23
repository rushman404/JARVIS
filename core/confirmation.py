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

# Exacte ja-match voor gevaarlijke bevestigingen (power, delete, empty, overwrite).
# Bewust GEEN "ok", "prima" of "goed": dat zijn instemmingen zonder expliciet
# ja, en die mogen geen onomkeerbare actie starten.
STRICT_YES = frozenset([
    "ja",
    "ja hoor",
    "jawel",
    "jep",
    "jup",
    "yep",
    "zeker",
    "jazeker",
    "natuurlijk",
    "tuurlijk",
    "akkoord",
    "ja doe maar",
    "doe maar",
    "doe het",
    "doe het maar",
    "ja doe het",
    "ja doe het maar",
    "voer maar uit",
    "ja voer maar uit",
    "ja graag",
    "bevestig",
    "bevestigd",
])

# Een korte zin die met een duidelijk ja-woord begint en geen ontkenning
# bevat ("ja doe het dan", "ja hoor, doe maar") geldt ook als ja. Zo hoeft
# u niet precies de woorden uit de lijst hierboven te gebruiken.
_JA_START = re.compile(
    r"^(ja|jawel|jep|jup|yep|zeker|jazeker|natuurlijk|tuurlijk|akkoord)\b"
)
MAX_JA_WOORDEN = 6

# "Ja, maar waarom?" is geen bevestiging: vraagwoorden en twijfel woorden
# laten de zin dus onduidelijk blijven.
_JA_VETO = ("waarom", "wat", "hoe", "wanneer", "welke", "wie", "misschien")

# Extra ja-varianten voor het opzoek-aanbod ("Wil je dat ik het opzoek?").
# Bewust een eigen lijst: "zoek maar op" hoeft geen delete of power-off te
# bevestigen. "ok", "prima" en "goed" horen hier NIET bij: dat zijn geen
# expliciete ja's en mogen geen zoekopdracht starten.
STRICT_SEARCH_YES = STRICT_YES | frozenset([
    "zoek maar op",
    "ja zoek maar op",
    "ja opzoeken",
    "yes",
    "yes please",
    "go ahead",
])

# De bevestigingen waar die extra ja-varianten voor gelden.
ZOEK_KINDS = frozenset([
    "opzoeken_confirm",
    "prijs_confirm",
])

# Woorden die een ontkenning aangeven — bij aanwezigheid is het ALTIJD "nee",
# ook als er "ja" in voor komt (bijv. "ja maar niet nu").
DENIAL_WORDS = frozenset([
    "niet",
    "nope",
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


def is_strict_yes(text: str, kind: str = None) -> bool:
    """True als de tekst na normalisatie exact op een strict-ja lijkt.

    Voor de opzoek-bevestigingen (``kind`` is "opzoeken_confirm" of
    "prijs_confirm") gelden ook "zoek maar op", "ja opzoeken", "yes
    please" en "go ahead".
    """
    norm = _normalize(text)
    if norm in STRICT_YES:
        return True
    if kind in ZOEK_KINDS and norm in STRICT_SEARCH_YES:
        return True

    # Korte, duidelijke zin die met een ja begint: "ja doe het dan".
    woorden = norm.split()
    if (
        "?" not in text
        and 0 < len(woorden) <= MAX_JA_WOORDEN
        and not any(w in woorden for w in _JA_VETO)
        and _JA_START.match(norm)
    ):
        return True

    return False


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
    "file_open_confirm",  # een uitvoerbaar/gevaarlijk bestand openen
])


def is_dangerous_kind(kind: str) -> bool:
    return kind in DANGEROUS_KINDS


# Soorten waarbij alleen een expliciete ja of nee geldt. "ja maar niet nu",
# "ok", "prima" en "goed" mogen hier nooit een actie starten.
STRICT_KINDS = DANGEROUS_KINDS | ZOEK_KINDS

# Soorten waarbij een antwoord dat geen ja/nee is gewoon als nieuw commando
# telt: het aanbod vervalt en de zin gaat door de normale keten. Zo blijft
# het aanbod niet hangen en slikt het geen commando in.
PASS_THROUGH_KINDS = ZOEK_KINDS


def is_strict_kind(kind: str) -> bool:
    return kind in STRICT_KINDS


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
        _log_expired_approval(pending)
        clear_pending()
        return None

    return pending


def _log_expired_approval(pending):
    """Logt een verlopen tool-goedkeuring in het auditlog (goedgekeurd False)."""

    if not pending or pending.get("kind") != "tool_approval":
        return

    try:
        from core.audit import log_audit

        log_audit(
            gehoord=pending.get("question", ""),
            handler=pending.get("source") or "onbekend",
            tool=pending.get("tool_name") or "",
            argumenten=pending.get("arguments") or {},
            risico=pending.get("risk") or "medium",
            resultaat="goedkeuring verlopen",
            goedgekeurd=False,
            reden="goedkeuring verlopen",
        )
    except Exception:
        pass


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

    # Strikte soorten: geen losse "ok"/"prima", en elke ontkenning is nee.
    if is_strict_kind(kind):
        # Ontkenning check eerst (ook als "ja" in zit)
        if contains_denial(text):
            return "no"
        # Dan strikte ja-check
        if is_strict_yes(text, kind):
            return "yes"
        # Een gewoon commando na het opzoek-aanbod ("ok zet de muziek
        # harder"): het aanbod vervalt en de zin gaat als nieuw commando
        # verder. Anders zou het aanbod blijven hangen en het commando
        # opslokken.
        if kind in PASS_THROUGH_KINDS:
            clear_pending()
            return "cancel"
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
