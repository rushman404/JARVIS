"""Openstaande bevestigingen (pending-keuzes) met een verlooptijd.

De state staat alleen in het geheugen van dit proces: hij wordt NOOIT
naar de schijf geschreven en overleeft een herstart van JARVIS dus niet.
Zonder verlooptijd zou een "ja" uren later alsnog een afsluiting uitvoeren.

Fase 18: elke openstaande bevestiging krijgt een ``id`` (uniek per
pending) en een ``nonce`` (willekeurig, geheim). Het dashboard mag een
besluit alleen geven voor de actie die op dat moment openstaat, met
precies die ``id`` + ``nonce``. Stem en dashboard kunnen tegelijk
antwoorden; daarom loopt alles via één lock en neemt ``claim_pending()``
de pending in één stap over: één actie wordt nooit twee keer uitgevoerd.
"""

import hmac
import itertools
import re
import secrets
import threading
import time
from collections import OrderedDict

from config import CONFIRM_TTL_SECONDS

# Sleutels die deze module zelf aan een pending hangt.
EXPIRES_KEY = "_expires_at"
REASKED_KEY = "_reasked"
ID_KEY = "_id"
NONCE_KEY = "_nonce"
HERKOMST_KEY = "herkomst"

# Eén lock voor alle pending-bewerkingen (stem-thread + dashboard-thread).
_LOCK = threading.RLock()

# Oplopende teller voor de pending-id's (uniek binnen dit proces).
_ID_TELLER = itertools.count(1)

# Recent gesloten pendings: id -> reden ("afgehandeld", "verlopen",
# "gewist", "vervangen"). Zo kan het dashboard een verlopen actie (410)
# onderscheiden van een al afgehandelde of onbekende (409).
_GESLOTEN = OrderedDict()
_MAX_GESLOTEN = 100

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
    "muziek_voorstel",  # "Zal ik hem opzetten?" (Fase 21, M5)
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
    "update_confirm",  # JARVIS bijwerken (Fase 19, M6)
    "mail_versturen",  # een mail versturen (Fase 23, M3)
    "agenda_toevoegen",  # afspraak in de iCloud-agenda (Fase 23, M4)
    "agenda_verplaatsen",
    "discord_versturen",  # een Discord-DM versturen (Fase 23, M6)
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


# "Bedoelde u…?" na een verkeerd gezegd commando (Fase 24, M2). Met één
# kandidaat een gewone ja/nee, met meer een keuze uit ``kandidaten``.
CORRECTIE_KIND = "commando_correctie"

# Soorten die met een gewoon ja of nee beantwoord worden (de rest is een
# keuze uit een lijst). Alleen deze kan het dashboard beslissen.
JA_NEE_KINDS = frozenset([
    "delete_confirm",
    "empty_confirm",
    "power_confirm",
    "memory_update",
    "scene_save_suggest",
    "memory_key_confirm",
    "tool_approval",
    "file_open_confirm",
    "prijs_confirm",
    "opzoeken_confirm",
    "update_confirm",
    "muziek_voorstel",
    "mail_versturen",
    "agenda_toevoegen",
    "agenda_verplaatsen",
    "discord_versturen",
    CORRECTIE_KIND,
])


def _current_context():
    # Late import om een circulaire import met core.ai te voorkomen;
    # op het moment van aanroepen is core.ai altijd al geladen.
    from core.ai import current_context
    return current_context


def _nieuw_id():
    return f"p{next(_ID_TELLER)}"


def _zorg_voor_id(pending):
    """Geeft een pending zonder id/nonce (direct via update_context gezet)
    alsnog een id en nonce. Moet onder ``_LOCK`` worden aangeroepen."""

    if not pending.get(ID_KEY):
        pending[ID_KEY] = _nieuw_id()
    if not pending.get(NONCE_KEY):
        pending[NONCE_KEY] = secrets.token_urlsafe(16)


def _markeer_gesloten(pending, reden):
    """Onthoudt dat de pending met deze id dicht is. Onder ``_LOCK``."""

    pid = pending.get(ID_KEY) if pending else None
    if not pid:
        return
    _GESLOTEN[pid] = reden
    _GESLOTEN.move_to_end(pid)
    while len(_GESLOTEN) > _MAX_GESLOTEN:
        _GESLOTEN.popitem(last=False)


def set_pending(kind, payload=None, ttl=None):
    """Zet een nieuwe openstaande bevestiging met verlooptijd.

    kind   — soort bevestiging, bijv. "power_confirm"
    payload — overige velden van de pending (action, matches, ...)
    ttl    — hoeveel seconden de vraag geldig blijft; standaard komt
             uit config.CONFIRM_TTL_SECONDS

    De pending krijgt altijd een nieuwe ``id`` en ``nonce``; een id of
    nonce uit de payload wordt nooit overgenomen.
    """

    if ttl is None:
        ttl = CONFIRM_TTL_SECONDS

    data = dict(payload or {})
    data["kind"] = kind
    data[EXPIRES_KEY] = time.time() + ttl
    data[REASKED_KEY] = False
    data[ID_KEY] = _nieuw_id()
    data[NONCE_KEY] = secrets.token_urlsafe(16)
    data.pop("_answered", None)
    data.pop(HERKOMST_KEY, None)

    with _LOCK:
        ctx = _current_context()
        vorige = ctx.get("pending_choice")
        if vorige:
            _markeer_gesloten(vorige, "vervangen")
        ctx["pending_choice"] = data

    return data


def get_pending():
    """Geeft de openstaande bevestiging, of None als er geen is.

    Is de ttl verlopen, dan wordt de state gewist en teruggegeven None.
    Een pending zonder verlooptijd (gezet vóór deze module, bijvoorbeeld
    direct in tests) geldt alleen voor deze sessie en verloopt niet.
    """

    with _LOCK:
        pending = _current_context().get("pending_choice")

        if not pending:
            return None

        expires_at = pending.get(EXPIRES_KEY)

        if expires_at is None or time.time() < expires_at:
            _zorg_voor_id(pending)
            return pending

        _markeer_gesloten(pending, "verlopen")
        _current_context()["pending_choice"] = None

    # Buiten de lock loggen: schrijven naar schijf mag de lock niet vasthouden.
    _log_expired_approval(pending)
    return None


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

    with _LOCK:
        ctx = _current_context()
        vorige = ctx.get("pending_choice")
        if vorige:
            _markeer_gesloten(vorige, "gewist")
        ctx["pending_choice"] = None


def claim_pending(pending, herkomst=None):
    """Neemt precies déze pending over om hem af te handelen.

    Geeft True als ``pending`` op dit moment nog de openstaande
    bevestiging is; die wordt dan in dezelfde stap gewist, zodat geen
    tweede antwoord (stem of dashboard) hem nog kan uitvoeren. Geeft
    False als de pending inmiddels vervangen, gewist of afgehandeld is.

    ``herkomst`` ("stem" of "dashboard") komt in de pending te staan, zodat
    de auditregel laat zien wie het besluit gaf.
    """

    with _LOCK:
        ctx = _current_context()
        huidige = ctx.get("pending_choice")
        if huidige is None or huidige is not pending:
            return False
        if herkomst:
            pending[HERKOMST_KEY] = herkomst
        _markeer_gesloten(pending, "afgehandeld")
        ctx["pending_choice"] = None
        return True


# Uitkomsten van claim_voor_besluit().
CLAIM_OK = "ok"
CLAIM_GEEN = "geen"                # geen openstaande actie met deze id (409)
CLAIM_AFGEHANDELD = "afgehandeld"  # al beantwoord, gewist of vervangen (409)
CLAIM_VERLOPEN = "verlopen"        # ttl voorbij (410)
CLAIM_NONCE = "nonce"              # id klopt, nonce niet (403)
CLAIM_SOORT = "soort"              # geen ja/nee-vraag (409)


def claim_voor_besluit(pending_id, nonce, herkomst):
    """Neemt de openstaande actie over als ``pending_id`` + ``nonce`` kloppen.

    Geeft ``(uitkomst, pending)``. Alleen bij ``CLAIM_OK`` is de pending
    overgenomen (en gewist); in alle andere gevallen verandert er niets.
    Dezelfde ttl als via de stem: een verlopen pending is weg.
    """

    if not isinstance(pending_id, str) or not isinstance(nonce, str):
        return CLAIM_GEEN, None

    with _LOCK:
        pending = get_pending()

        if pending is None or pending.get(ID_KEY) != pending_id:
            reden = _GESLOTEN.get(pending_id)
            if reden == "verlopen":
                return CLAIM_VERLOPEN, None
            if reden is not None:
                return CLAIM_AFGEHANDELD, None
            return CLAIM_GEEN, None

        if not hmac.compare_digest(
            str(pending.get(NONCE_KEY) or "").encode(), nonce.encode()
        ):
            return CLAIM_NONCE, None

        if pending.get("kind") not in JA_NEE_KINDS:
            return CLAIM_SOORT, None

        claim_pending(pending, herkomst=herkomst)
        return CLAIM_OK, pending


# Velden die voor een niet-tool-bevestiging als "argumenten" getoond worden.
_TOON_VELDEN = (
    "action", "target", "path", "name", "product", "vraag",
    "memory_key", "memory_value",
)


def beschrijf_pending(nu=None):
    """De openstaande ja/nee-actie als volledige tekst (voor het dashboard).

    Geeft None als er niets openstaat of als de openstaande keuze geen
    ja/nee-vraag is (bijv. een keuze uit een lijst bestanden).
    """

    pending = get_pending()
    if not pending or pending.get("kind") not in JA_NEE_KINDS:
        return None

    if nu is None:
        nu = time.time()

    kind = pending.get("kind")
    payload = pending.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    tool = pending.get("tool_name") or ""
    if tool:
        argumenten = dict(pending.get("arguments") or {})
        try:
            from core.tool_registry import describe_tool_action

            actie = describe_tool_action(tool, argumenten)
        except Exception:
            actie = tool
    else:
        argumenten = {}
        for sleutel in _TOON_VELDEN:
            waarde = pending.get(sleutel, payload.get(sleutel))
            if waarde not in (None, ""):
                argumenten[sleutel] = waarde
        actie = pending.get("action") or payload.get("action") or kind

    risico = pending.get("risk") or ("high" if is_dangerous_kind(kind) else "low")
    verloopt_op = pending.get(EXPIRES_KEY)
    resterend = None
    if verloopt_op is not None:
        resterend = max(0, int(verloopt_op - nu))

    # "Bedoelde u…?": de vraag zelf als actie, de kandidaten als knoppen.
    keuzes = []
    if kind == CORRECTIE_KIND:
        keuzes = [str(k) for k in pending.get("kandidaten") or []]
        actie = pending.get("bedoelde_vraag") or actie

    return {
        "keuzes": keuzes,
        "id": pending.get(ID_KEY),
        "nonce": pending.get(NONCE_KEY),
        "soort": kind,
        "vraag": str(pending.get("question") or ""),
        "tool": tool,
        "actie": str(actie),
        "argumenten": argumenten,
        "risico": str(risico),
        "verloopt_op": verloopt_op,
        "resterende_seconden": resterend,
    }


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
