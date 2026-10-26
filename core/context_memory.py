"""
JARVIS — Gecombineerde context + long-term memory laag (Fase 14, Stap 6)
======================================================================

Zorgt dat de AI/Agent bij het begrijpen van een opdracht zowel de
recente conversatie als de relevante langetermijn-memories ziet, en
dat in ÉÉN duidelijk blok.

Tot nu toe werden die als twee losse systeem-berichten meegegeven
("ACTUELE JARVIS-CONTEXT" en "JARVIS-GEHEUGEN"). De AI kon die
zonder regel naast elkaar negeren. Deze laag voegt ze samen en zegt
expliciet welke zwaarder weegt.

Wat er gebeurt bij een nieuwe opdracht:

  1. De contextvelden uit current_context worden gescoord op
     relevantie voor deze vraag (elk veld heeft een eigen gewicht).
  2. De relevante memories worden opgehaald met de bestaande
     relevance-scoring, dus inclusief priority, aging en usage.
  3. Memory die dezelfde informatie al in de context of het gesprek
     staat wordt weggelaten: zo komt niets dubbel in de prompt.
  4. Verwijst de gebruiker naar iets uit het directe gesprek
     ("hem", "die", "opnieuw", "nogmaals"), dan weegt de context
     zwaarder en staat dat er nadrukkelijk bij.
  5. De usage-tracking blijft draaien: wie een memory ziet, telt
     die als gebruikt (zoals voorheen).

Er wordt GEEN nieuwe opslag toegevoegd. Dit leest uitsluitend uit
de bestaande current_context, conversation.json en memory.json.
"""

import re

from memory.memory import (
    get_relevant_memory,
    memory_summary,
    beautify,
    touch_usage,
    _content_tokens,
)


# Maximaal aantal memories in het gecombineerde blok.
DEFAULT_CONTEXT_MEMORIES = 6

# Maximaal aantal contextvelden in het gecombineerde blok.
DEFAULT_CONTEXT_ITEMS = 5

# Maximaal aantal uitgewisselde berichten uit het recente gesprek.
DEFAULT_HISTORY_TURNS = 6

# =============================================================
# CONTEXT-VELDEN
#
# Elk veld uit current_context krijgt een gewicht. "Laatste actie"
# en "laatste opdracht" wegen het zwaarst, want daarnaar verwijst
# iemand met "opnieuw" of "nogmaals". De volgorde hier bepaalt ook
# de volgorde in het blok: het belangrijkste eerst.
# =============================================================

_CONTEXT_FIELDS = (
    ("last_action", "Laatste actie", 1.4),
    ("last_command", "Laatste opdracht", 1.3),
    ("last_program", "Laatste programma", 1.2),
    ("last_file", "Laatste bestand", 1.2),
    ("last_website", "Laatste website", 1.2),
    ("last_ha_entity", "Laatste HA-apparaat", 1.2),
    ("last_result", "Laatste resultaat", 1.0),
    ("last_calculation", "Laatste berekening", 1.0),
)

# =============================================================
# VERWIJZINGEN NAAR HET DIRECTE GESPREK
#
# Woorden waaruit blijkt dat de gebruiker iets uit het gesprek
# bedoelt in plaats van iets algemeens. Bij zo'n verwijzing telt
# de context zwaarder dan het langetermijngeheugen.
# =============================================================

_CONVERSATION_REFERENCES = frozenset({
    # voornaamwoorden
    "hem", "haar", "die", "dat", "dit", "het", "ze", "zich", "hen", "zeg",
    # aanwijzingen
    "daar", "daarin", "daaraan", "daarom", "ermee", "ertoe", "hierin",
    "hiermee", "hiervoor",
    # herhalen
    "opnieuw", "nogmaals", "herhaal", "herhalen", "nog", "weer",
    "dezelfde", "hetzelfde", "tweede", "nogmaal",
})

# Woorden waarmee de gebruiker expliciet naar het gesprek verwijst.
_STRONG_REFERENCES = frozenset({
    "opnieuw", "nogmaals", "nogmaal", "herhaal", "herhalen", "dezelfde",
    "nog", "weer",
})

# Het patroon "nog een keer" / "nog een keertje" is één signaal, geen losse woorden.
_AGAIN_PATTERN = re.compile(r"\bnog\s+een\s+keer(?:tje)?\b|\bnogmaal\b")


def detect_conversation_reference(question):
    """
    Geeft de verwijzingen terug die de gebruiker maakt naar het
    directe gesprek (een lijst van woorden, of leeg).

    "open hem opnieuw" -> ["hem", "opnieuw"]
    "wat is je gpu"     -> []
    """

    question = (question or "").lower()

    found = []

    for word in sorted(_CONVERSATION_REFERENCES):
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", question):
            found.append(word)

    if _AGAIN_PATTERN.search(question) and "opnieuw" not in found:
        found.append("opnieuw")

    return found


def has_conversation_reference(question, context=None):
    """
    True als de gebruiker naar het directe gesprek verwijst.

    Sterke signalen ("opnieuw", "nogmaals", "dezelfde") tellen
    altijd. Zwakkere signalen ("hem", "die", "daar") tellen alleen
    als er ook context beschikbaar is, anders zou "die prijs is te
    hoog" ten onrechte als gespreksverwijzing gelden.
    """

    found = detect_conversation_reference(question)

    if not found:
        return False

    if any(word in _STRONG_REFERENCES for word in found):
        return True

    return bool(context) and _has_any_context(context or {})


def _score_context_item(question, label, value, weight):
    """
    Relevantie van één contextveld voor deze vraag.
    Geeft 0.0 als er geen woord overlap is.

    Het label telt mee in de vergelijking, zodat "open het programma
    opnieuw" het veld "Laatste programma" vindt, ook al staat er in de
    waarde zelf ("kladblok") geen woord uit de vraag.
    """

    value = str(value or "").strip()

    if not value:
        return 0.0

    tokens_q = _content_tokens(question)
    tokens_v = _content_tokens(value) | _content_tokens(label)

    if not tokens_v:
        return 0.0

    overlap = tokens_q & tokens_v

    if not overlap:
        return 0.0

    score = 2.0 * len(overlap) * weight

    # De waarde letterlijk in de vraag is een sterk signaal.
    if value.lower() in (question or "").lower():
        score += 3.0

    return round(score, 2)


def rank_context_items(question, context=None, max_items=DEFAULT_CONTEXT_ITEMS):
    """
    De contextvelden uit current_context, gesorteerd op relevantie
    voor deze vraag.

    Geeft een lijst van dicts terug:
        label, value, score, field

    Alleen velden met een score > 0, dus een lege of niet-passende
    context levert niets op.
    """

    context = context or {}

    ranked = []

    for field, label, weight in _CONTEXT_FIELDS:

        value = context.get(field)

        # Lege strings en None tellen niet mee.
        if value is None or str(value).strip() == "":
            continue

        score = _score_context_item(question, label, value, weight)

        if score <= 0:
            continue

        text = str(value)

        # Bij een HA-apparaat is de domeinnaam nuttige extra info.
        if field == "last_ha_entity":
            domain = context.get("last_ha_domain")

            if domain:
                text = f"{text} ({domain})"

        ranked.append({
            "field": field,
            "label": label,
            "value": text,
            "score": score,
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)

    return ranked[:max_items]


def _recent_context_items(context, max_items=DEFAULT_CONTEXT_ITEMS):
    """
    De meest recente contextvelden, in gewichtsorde.

    Wordt alleen gebruikt als de gebruiker naar het gesprek verwijst maar
    geen enkel veld op woorden matcht ("en dat dan?", "sluit hem"). Zo
    houdt blok 1 toch iets om naar te verwijzen. Alleen gevulde velden.
    """

    context = context or {}

    items = []

    for field, label, weight in _CONTEXT_FIELDS:

        value = context.get(field)

        if value is None or str(value).strip() == "":
            continue

        text = str(value)

        if field == "last_ha_entity":
            domain = context.get("last_ha_domain")

            if domain:
                text = f"{text} ({domain})"

        items.append({
            "field": field,
            "label": label,
            "value": text,
            "score": round(weight, 2),
        })

        if len(items) >= max_items:
            break

    return items


def _memory_items(question, max_memories=DEFAULT_CONTEXT_MEMORIES):
    """
    De relevante memories, inclusief het bijtellen van het gebruik
    (zoals voorheen gebeurde in ask_ai en _generate_plan).
    """

    items = get_relevant_memory(question, max_items=max_memories)

    for item in items:
        touch_usage(item["key"], item.get("category"))

    return items


def _normalize(text):
    """Kleine letters, alleen alfanumeriek, dubbele spaties weg."""

    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text).lower())).strip()


def drop_duplicate_memories(memories, context_items=None, history=None):
    """
    Haalt memories weg die dezelfde informatie al in de context of in
    het recente gesprek staat.

    Er wordt alleen op de WAARDE vergeleken, nooit op de sleutel. Een
    vraag als "wat is mijn gpu" in de geschiedenis is namelijk geen
    dubbeling van de memory die zegt welke gpu je hebt; dat is juist
    de memory die het antwoord geeft.

    De usage-telling gebeurt al eerder, dus een weggelaten memory
    telt gewoon mee als gebruikt.
    """

    haystack = _normalize(
        " ".join(
            [str(item.get("value", "")) for item in (context_items or [])]
            + [
                str(entry.get("content", ""))
                for entry in (history or [])
                if isinstance(entry, dict)
            ]
        )
    )

    if not haystack:
        return list(memories)

    kept = []

    for item in memories:

        value = _normalize(item.get("value", ""))

        # Kort genoeg om geen betekenis te hebben als zoekterm.
        if len(value) < 3:
            kept.append(item)
            continue

        if value in haystack:
            continue

        kept.append(item)

    return kept


def _format_memory_line(item):
    """Eén memory als leesbare regel."""

    text = beautify(item.get("value", ""))

    if item.get("category") == "voorkeuren":
        return f"Je {str(item.get('key', '')).replace('_', ' ')} is {text}."

    return f"[{item.get('category', 'algemeen')}] {str(item.get('key', '')).replace('_', ' ')}: {text}."


def build_memory_context(
    question,
    context=None,
    history=None,
    max_memories=DEFAULT_CONTEXT_MEMORIES,
    max_context_items=DEFAULT_CONTEXT_ITEMS,
    max_history=DEFAULT_HISTORY_TURNS,
):
    """
    Eén tekstblok met context + memories, klaar voor de AI/Agent.

    Geeft een lege string terug als er niets te zeggen valt, zodat
    de prompt dan alleen het gecombineerde blok overslaat.

    Blokken:
        1. DIT GESPREK      — de relevante contextvelden
        2. RECENTE GESPREK  — de laatste uitgewisselde berichten
        3. LANGETERMIJN     — de relevante memories
        plus regels over welke zwaarder weegt
    """

    context = context or {}
    history = history or []

    references = detect_conversation_reference(question)

    # Verwijst de gebruiker naar het gesprek? Dan weegt de context
    # zwaarder.
    conversation_reference = has_conversation_reference(question, context)

    context_items = rank_context_items(
        question, context, max_items=max_context_items
    )

    # Verwijst de gebruiker naar iets ("hem", "die", "en dat dan?") maar
    # raakt geen enkel woord de contextvelden? Dan zou blok 1 leeg blijven
    # en heeft de AI niets om naar te verwijzen. Vul blok 1 dan met de
    # meest recente contextvelden, op gewicht.
    if not context_items and conversation_reference:
        context_items = _recent_context_items(context, max_items=max_context_items)

    memories = _memory_items(question, max_memories=max_memories)

    memories = drop_duplicate_memories(memories, context_items, history)

    pending = context.get("pending_choice")

    recent = _recent_history(history, max_history)

    # Niets te combineren: geef een lege string terug zodat de
    # aanroepende prompt net als voorheen leeg blijft.
    if not context_items and not memories and not recent and not pending:
        return ""

    lines = []

    lines.append("JARVIS-CONTEXT EN GEHEUGEN")
    lines.append("=" * 46)
    lines.append("")

    # ---- 1. DIT GESPREK ----
    if context_items or pending:

        lines.append("1. DIT GESPREK (actueel)")

        for item in context_items:
            lines.append(f"   - {item['label']}: {item['value']}")

        if pending:
            lines.append(
                "   - Er staat nog een vraag open waar je antwoord op wacht."
            )

        lines.append("")

    # ---- 2. RECENTE GESPREK ----
    if recent:

        lines.append("2. RECENTE GESPREK")

        for role, content in recent:
            who = "gebruiker" if role == "user" else "jarvis"
            lines.append(f"   {who}: {content}")

        lines.append("")

    # ---- 3. LANGETERMIJNGEHEUGEN ----
    if memories:

        lines.append("3. WAT IK OVER JOU WEET (langetermijngeheugen)")

        for item in memories:
            lines.append(f"   - {_format_memory_line(item)}")

        lines.append("")

    elif not context_items and not recent:
        lines.append("3. WAT IK OVER JOU WEET (langetermijngeheugen)")
        lines.append("   - (niets relevant gevonden)")
        lines.append("")

    # ---- REGELS ----
    lines.append("HOE JE DIT GEBRUIKT")

    if conversation_reference:
        lines.append(
            "- De gebruiker verwijst naar iets uit dit gesprek"
            f" ({', '.join(references)})."
        )
        lines.append(
            "- Daarom weegt BLOK 1 (dit gesprek) ZWAARDER dan het"
            " langetermijngeheugen. Gebruik blok 1 als het onderwerp"
            " daar staat."
        )
    else:
        lines.append(
            "- Blok 1 gaat over het directe gesprek, blok 3 over"
            " langetermijnfeiten. Gebruik allebei, maar blok 3 gaat"
            " over jou als persoon (voorkeuren, pc, projecten)."
        )

    if context_items and memories:
        lines.append(
            "- Staat iets in beide blokken? Gebruik dan blok 1; dat"
            " is actueler."
        )

    lines.append("- Verzin niets dat er niet staat.")
    lines.append("- Gebruik de context of het geheugen alleen als ze passen bij de vraag.")

    return "\n".join(lines).rstrip()


def _has_any_context(context):
    """True als er in current_context iets bruikbaars staat."""

    return any(
        str(context.get(field) or "").strip()
        for field, _, _ in _CONTEXT_FIELDS
    )


def _recent_history(history, max_turns):
    """
    De laatste uitgewisselde berichten als (role, content)-paren.
    Afgekapte inhoud, zodat het blok niet de hele prompt vult.
    """

    if not history:
        return []

    pairs = []

    for entry in history:

        if not isinstance(entry, dict):
            continue

        role = entry.get("role")
        content = entry.get("content")

        if not role or content is None:
            continue

        content = str(content).strip()

        if not content:
            continue

        # Zeer lange berichten afkappen: het gaat om de intentie.
        if len(content) > 160:
            content = content[:157].rstrip() + "..."

        pairs.append((role, content))

    return pairs[-max_turns:]


# =========================================================
# CONTEXTLEK UIT HET ANTWOORD HALEN (Fase 21-fix, 2026-10-26)
#
# Het kleine model plakt het contextblok hierboven soms letterlijk in zijn
# antwoord ("1. DIT GESPREK - Laatste actie: ..."). Dit filter haalt zulke
# regels eruit, ook tijdens het streamen (regel voor regel; een gewone
# regel gaat meteen door, alleen een mogelijk kopje wacht even).
# =========================================================

CONTEXT_KOPPEN = (
    "JARVIS-CONTEXT", "=====", "1. DIT GESPREK", "2. RECENTE GESPREK",
    "3. WAT IK OVER JOU WEET", "HOE JE DIT GEBRUIKT", "JARVIS-GEHEUGEN",
)
_BLOKREGEL = re.compile(r"^(?:-|•|\*|(?:gebruiker|jarvis)\s*:)", re.IGNORECASE)
LEK_TERUGVAL = "Dat begreep ik niet helemaal, sir. Kunt u het anders zeggen?"


class ContextLekFilter:
    """Filtert gestreamde tekst: ``feed(stuk)`` en aan het eind ``flush()``."""

    def __init__(self):
        self.buf = ""
        self.begin = True
        self.blok = False
        self.weg = False
        self.geschrapt = False

    def _is_lek(self, kaal):
        if any(kaal.startswith(k) for k in CONTEXT_KOPPEN):
            return True
        return self.blok and (not kaal or bool(_BLOKREGEL.match(kaal)))

    def _wachten(self, kaal):
        if self.blok:
            return True
        return not kaal or any(k.startswith(kaal) for k in CONTEXT_KOPPEN)

    def feed(self, stuk):
        self.buf += stuk or ""
        uit = []
        while self.buf:
            if self.begin:
                nl = self.buf.find("\n")
                kaal = (self.buf if nl < 0 else self.buf[:nl]).strip()
                if nl < 0 and self._wachten(kaal):
                    break
                if self._is_lek(kaal):
                    self.geschrapt = True
                    self.blok = True
                    if nl < 0:
                        self.buf, self.begin, self.weg = "", False, True
                        break
                    self.buf = self.buf[nl + 1:]
                    continue
                self.blok = False
                self.begin, self.weg = False, False
            nl = self.buf.find("\n")
            if nl < 0:
                if not self.weg:
                    uit.append(self.buf)
                self.buf = ""
                break
            if not self.weg:
                uit.append(self.buf[:nl + 1])
            self.buf = self.buf[nl + 1:]
            self.begin = True
        return "".join(uit)

    def flush(self):
        rest, self.buf = self.buf, ""
        if not rest:
            return ""
        if self.begin:
            if self._is_lek(rest.strip()):
                self.geschrapt = True
                return ""
            return rest
        return "" if self.weg else rest


def verwijder_contextlek(tekst):
    """Het antwoord zonder een meegeplakt contextblok."""

    if not isinstance(tekst, str) or not tekst:
        return tekst
    f = ContextLekFilter()
    schoon = (f.feed(tekst) + f.flush()).strip()
    if not f.geschrapt:
        return tekst
    return schoon or LEK_TERUGVAL
