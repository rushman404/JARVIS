"""
Resultaatbeoordeling (Fase 9, stap 4 — betrouwbaar, niet op losse woorden)

In plaats van zinnen te raden op losse signaalwoorden, wordt elk
toolresultaat gestandaardiseerd naar een ToolResult met een harde
ok-vlag en (optioneel) een error_kind:

    ToolResult(ok=True,  message="...")       -> betrouwbaar geslaagd
    ToolResult(ok=False, message="...", error_kind="network_error")
                                              -> aantoonbaar mislukt

classify_tool_result() wordt ALLEEN nog gebruikt in de adapter
to_tool_result() voor legacy-stringresultaten, en is strenger gemaakt:
    - een bestandsnaam als "afgebroken_verslag.docx" telt niet als fout
    - "geen toegang ... nodig" telt niet als fout (er is géén toegang nodig)
    - "Dat lukt helaas niet." telt wél als fout (ontkenning ná het werkwoord)

Uitleg van de rollen:
    Executor : "Voer het plan uit."      (verdict via to_tool_result)
    Retry    : "Probeer alleen veilige tools opnieuw." (adapter + idempotentie)
    Actions  : "Hoe voer ik de actie uit?"   (audio/browser/ui: ToolResult)
"""

from dataclasses import dataclass, field
import ast
import json
import re


@dataclass
class ToolResult:
    """Standaard resultaat van een tool-aanroep.

    ok        : of de actie echt (helemaal) geslaagd is
    message   : wat JARVIS erover zegt (wordt voorgelezen)
    data      : optionele structuur (lijsten, gevonden objecten, enz.)
    error_kind: machine-leesbare foutsoort (bijv. "network_error")
    partial   : de tool deed een DIEPERE/ANDERE actie dan gevraagd
                (bijv. fallback die niet klikt maar alleen vindt)
    """

    ok: bool
    message: str = ""
    data: dict | None = None
    error_kind: str | None = None
    partial: bool = False

    def __str__(self):
        """Wat String(str) geeft is de zachte boodschap, niet het object."""
        if self.message:
            return str(self.message)
        return "Dat is gelukt." if self.ok else "Dat is niet gelukt."

    # --- Compatibiliteit met het oudere dict-resultaat --------------------
    # Sommige (oudere) aanroepers/tests behandelen het resultaat als een
    # dict (r['ok'], r.get('windows'), ...). We bieden daarom een dunne,
    # niet-destructieve mapping-laag bovenop de dataclass.

    def _as_mapping(self):
        base = {
            "ok": self.ok,
            "message": self.message,
            "error": self.message,
            "data": self.data,
            "error_kind": self.error_kind,
            "error_type": self.error_kind,
            "partial": self.partial,
        }
        if isinstance(self.data, dict):
            for key, value in self.data.items():
                base.setdefault(key, value)
        return base

    def __getitem__(self, key):
        return self._as_mapping()[key]

    def get(self, key, default=None):
        return self._as_mapping().get(key, default)

    def __contains__(self, key):
        return key in self._as_mapping()

    def keys(self):
        return self._as_mapping().keys()

    def items(self):
        return self._as_mapping().items()



# =========================================================
# classify_tool_result (Alleen voor legacy-strings)
# =========================================================

# Duidelijke neveneffect-meldingen: de hoofdactie lijkt gelukt,
# maar er is iets kleins misgegaan -> onzeker, niet blind "succes".
UNCERTAIN_PATTERNS = (
    "venster kon niet naar voren",
    "venster kon niet naar de voorgrond",
    "maar de status blijft",
    "ik stuurde",
)

# Bestandsnaam met extensie: woorden erin mogen nooit als signaal
# geteld worden ("Gevonden: afgebroken_verslag.docx" is geen fout).
_FILENAME_RE = re.compile(
    r"\b[\w\-]{1,120}\.(?:docx?|txt|pdf|png|jpe?g|gif|bmp|webp|mp3|mp4|wav|flac|m4a|"
    r"exe|msi|zip|rar|7z|tar|gz|json|csv|xml|xsd|bat|cmd|ps1|ini|cfg|conf|log|"
    r"sys|dll|drv|sql|db|sqlite|xlsx?|pptx?|docm|pdfx|html?|htm|md|py|js|ts|cs|"
    r"java|cpp|c|h|jpg|mov|avi|mkv)\b",
    re.IGNORECASE,
)

# "geen X nodig" / "niet nodig" / "hoeft niet" draaien de betekenis om:
# er is juist géén probleem.
_NEGATION_FRAMES = (
    re.compile(r"\bgeen\b[^.;!?]{0,80}\bnodig\b"),
    re.compile(r"\bniet\b[^.;!?]{0,40}\b(?:nodig|vereist|noodzakelijk)\b"),
    re.compile(r"\b(?:hoeft|hoef|hoeven)\b[^.;!?]{0,40}\bniet\b"),
    re.compile(r"\bis\b[^.;!?]{0,40}\b(?:geen|niet)\b[^.;!?]{0,40}\b(?:nodig|vereist|noodzakelijk)\b"),
)

# Ontkenning na het werkwoord: "Dat lukt helaas niet.", "Het werkt niet meer."
_POSSITIVE_WORD_FAILS = (
    re.compile(r"\b(?:lukt|werkt|klopt|gaat|kan|kon|zal|zou|wilde|moet)\b[^.;!?]{0,40}\bniet\b"),
)

# Algemene Nederlandse fout-signaalwoorden zoals de bestaande
# actions/tools die teruggeven.
FAILED_PATTERNS = (
    "kon niet",
    "konden niet",
    "kan niet",
    "niet bereiken",
    "niet gevonden",
    "niet kunnen vinden",
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


def _contains_pattern(text):
    """Zoekt de vaste foutpatronen met woordinformatie (niet in bestandsnamen)."""

    for pattern in FAILED_PATTERNS:
        if re.search(r"\b" + re.escape(pattern) + r"\b", text):
            return True

    return False


def classify_tool_result(result):
    """
    Geeft "success", "failed" of "uncertain" voor LEGACY-STRINGS.

    Regels (strenger dan vroeger):
      - bestandsnamen tellen niet mee (afgebroken_verslag.docx ≠ fout)
      - "geen ... nodig" / "niet nodig" / "hoeft niet" ≠ fout
      - ontkenning ná het werkwoord ("Dat lukt helaas niet.") = fout
      - een resultaat dat zelf een vraag is, is per definitie onzeker
    """

    text = str(result or "").strip().lower()

    if not text:
        return "uncertain"

    if text.endswith("?"):
        return "uncertain"

    for pattern in UNCERTAIN_PATTERNS:
        if pattern in text:
            return "uncertain"

    # Bestandsnamen weghalen zodat "afgebroken" in een bestandsnaam
    # niet als foutsignaal telt.
    text = _FILENAME_RE.sub(" ", text)

    # Betekenis-omkering weghalen: "geen toegang ... nodig" is juist goed.
    for frame in _NEGATION_FRAMES:
        text = frame.sub(" ", text)

    # Ontkenning na het werkwoord: "Dat lukt helaas niet."
    for word_fail in _POSSITIVE_WORD_FAILS:
        if word_fail.search(text):
            return "failed"

    if _contains_pattern(text):
        return "failed"

    return "success"


# =========================================================
# Adapter: elk ruw resultaat -> ToolResult
# =========================================================

def to_tool_result(raw):
    """
    Zet een ruw toolresultaat om naar een betrouwbaar ToolResult.

    Ondersteunt:
        - ToolResult                        -> zoals het is
        - dict met "ok"                     -> vlag + message + data
        - dict zonder "ok" (legacy)         -> via classify op str()
        - stringified dict ("{'ok': False}")-> geparsed, dan dict-regels
        - legacy-string                     -> via classify_tool_result
        - None                              -> mislukt (niet classificeerbaar)
    """

    if isinstance(raw, ToolResult):
        return raw

    if raw is None:
        return ToolResult(ok=False, message="", error_kind="empty")

    if isinstance(raw, dict):
        return _tool_result_from_dict(raw)

    text = str(raw or "").strip()

    # Legacy "str(dict)"-representatie: parse terug zodat {"ok": False}
    # ook door de string heen betrouwbaar wordt herkend.
    if text.startswith("{") and text.endswith("}"):
        parsed = _parse_dict_string(text)
        if isinstance(parsed, dict):
            return _tool_result_from_dict(parsed)

    verdict = classify_tool_result(text)

    if verdict == "failed":
        return ToolResult(ok=False, message=text, error_kind="failed")

    if verdict == "uncertain":
        return ToolResult(ok=False, message=text, error_kind="uncertain")

    return ToolResult(ok=True, message=text)


def _parse_dict_string(text):
    """Probeert een stringified dict terug te lezen (json, anders literal)."""

    try:
        return json.loads(text)
    except Exception:
        try:
            return ast.literal_eval(text)
        except Exception:
            return None


def _tool_result_from_dict(raw):
    """Dict met "ok" (of legacy-foutvelden) -> ToolResult."""

    if raw.get("ok") is not None:

        ok = bool(raw.get("ok"))
        message = (
            raw.get("message")
            or raw.get("error")
            or raw.get("result")
            or str(raw)
        )

        # Bewaar de rest in data zodat niemand informatie verliest.
        data = raw.get("data")
        if not isinstance(data, dict):
            data = {
                key: value
                for key, value in raw.items()
                if key not in ("ok", "status", "message", "error", "result",
                               "error_type", "error_kind", "partial")
            }

        return ToolResult(
            ok=ok,
            message=str(message),
            data=data,
            error_kind=raw.get("error_kind") or raw.get("error_type"),
            partial=bool(raw.get("partial", False)),
        )

    # Legacy-dict zonder "ok"
    error_type = raw.get("error_type") or raw.get("error_kind")
    error = raw.get("error")

    if error_type or error:
        return ToolResult(
            ok=False,
            message=str(raw.get("message") or error or raw),
            error_kind=error_type,
        )

    # Zonder ok-vlag en zonder foutvelden: drie wegen
    if "message" in raw:
        verdict = classify_tool_result(str(raw.get("message")))
        return ToolResult(
            ok=(verdict != "failed"),
            message=str(raw.get("message")),
            error_kind=None if verdict != "failed" else "failed",
        )

    return ToolResult(ok=True, message=str(raw), data=raw)