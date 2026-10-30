"""Het aanbod "Wil je dat ik het opzoek?" met een ja/nee-pending (Fase 17).

Twijfelt het taalmodel over een feit, dan zegt het (via de zekerheidsregel in
``core/ai.py``) iets als "Dat weet ik niet zeker. Wil je dat ik het opzoek?".
Zonder deze module zou een "ja" daarop nergens landen. Nu zet het aanbod een
korte pending; pas na een expliciet "ja" gaat de zoekopdracht naar buiten,
met de oorspronkelijke vraag en met bronvermelding in het antwoord.

De pending staat alleen in het geheugen (zie ``core/confirmation.py``): na een
herstart of na de ttl doet een "ja" niets meer.
"""

import json
import re

from config import OPZOEK_CONFIRM_TTL_SECONDS

# De soort pending die dit aanbod gebruikt.
KIND = "opzoeken_confirm"

# Het aanbod in het antwoord. Bewust smal: een gewone zin over opzoeken
# ("ik kan dat opzoeken") is geen vraag en zet dus geen pending.
_AANBOD = re.compile(
    r"(?:wil je dat ik|zal ik|moet ik)\b[^.!?\n]*\bopzoek"
    r"|(?:shall|should|can) i\b[^.!?\n]*\blook\b[^.!?\n]*\bup\b",
    re.IGNORECASE,
)


def _aanbodzinnen():
    """De ingestelde onbekend-zinnen die een aanbod bevatten."""
    import config

    zinnen = []
    for zin in (config.ZEKERHEID_ONBEKEND, config.ZEKERHEID_ONBEKEND_EN):
        if not zin:
            continue
        laag = zin.lower()
        if "opzoek" in laag or "look it up" in laag or "look that up" in laag:
            zinnen.append(zin.split("?")[0].strip())
    return zinnen


def bevat_aanbod(antwoord):
    """True als het antwoord de vraag stelt of JARVIS iets mag opzoeken."""
    if not antwoord:
        return False

    tekst = str(antwoord).lower()

    if _AANBOD.search(tekst):
        return True

    return any(zin and zin in tekst for zin in _aanbodzinnen())


def onthoud_aanbod(vraag, antwoord):
    """Zet een ja/nee-pending als het antwoord het aanbod bevat.

    ``vraag`` is de oorspronkelijke vraag; die gaat later mee de zoekopdracht
    in. Geeft de pending terug, of None als er niets te onthouden valt.
    """
    if not vraag or not bevat_aanbod(antwoord):
        return None

    from core import confirmation

    return confirmation.set_pending(
        KIND,
        payload={"vraag": vraag},
        ttl=OPZOEK_CONFIRM_TTL_SECONDS,
    )


ZOEK_INSTRUCTIE = (
    "Zoek dit op met Google Zoeken en geef een kort, actueel antwoord in één "
    "of twee zinnen. Noem geen URL's in de tekst; de bronnen worden apart getoond.\n\n"
)
MAX_BRONNEN = 2

# Hoeveel webpagina's JARVIS leest om de vraag te beantwoorden, en hoeveel
# tekst per pagina naar het model gaat.
SAMENVAT_PAGINAS = 2
MAX_BRON_TEKST = 1500

SAMENVAT_INSTRUCTIE = (
    "Je krijgt een vraag en een paar genummerde zoekresultaten van het web. "
    "Beantwoord de vraag in één of twee zinnen, ALLEEN met informatie uit die "
    "bronnen; gebruik niet je eigen kennis. Kies bij tegenstrijdige of oude "
    "informatie de meest recente. Staat het antwoord er niet in, zeg dat dan "
    "eerlijk. Antwoord alleen met JSON: "
    '{"antwoord": "...", "bron": <het nummer van de bron die je gebruikte, of null>}.'
)


def zoek_met_gemini(vraag):
    """Fase 25: Gemini zoekt zelf (Google Zoeken) en antwoordt met bron.

    Google Zoeken zit niet in de gratis laag (prijspagina, 2026-10-30), dus
    dit staat alleen aan met ``GEMINI_ZOEKEN=1`` (betaald account). Geeft
    het antwoord met "(Bron: …)", of None; dan :func:`zoek_en_vat_samen`.
    """
    try:
        from config import GEMINI_ZOEKEN
        from core import llm, privacy_poort

        if not GEMINI_ZOEKEN or not privacy_poort.naar_cloud(vraag):
            return None
        berichten = privacy_poort.cloud_berichten(vraag, instructies=ZOEK_INSTRUCTIE)
        antwoord = llm.chat(messages=berichten, cloud=True, zoeken=True, alleen_cloud=True)
    except Exception:
        return None
    if antwoord is None:
        return None
    tekst = str(antwoord.message.content or "").strip()
    if not tekst:
        return None
    bronnen = [b.get("titel") or b.get("url") for b in (getattr(antwoord, "bronnen", None) or [])]
    bronnen = [b for b in bronnen if b][:MAX_BRONNEN]
    if bronnen:
        tekst += f" (Bron: {', '.join(bronnen)})"
    return tekst


def _site(url):
    from urllib.parse import urlparse

    host = urlparse(str(url or "")).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _lees_json(inhoud):
    try:
        data = json.loads(inhoud)
    except (TypeError, ValueError):
        m = re.search(r"\{.*\}", str(inhoud or ""), re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return {}
    return data if isinstance(data, dict) else {}


def zoek_en_vat_samen(vraag, zoek=None, pagina_s=SAMENVAT_PAGINAS):
    """DuckDuckGo zoekt en leest een paar pagina's; het model geeft daaruit
    een kort antwoord en zegt welke bron het gebruikte (fix 2026-10-30:
    "verkeerde bron en antwoord" bij het letterlijk voorlezen van de eerste
    hit).

    Mag de vraag naar de cloud, dan vat Gemini samen (openbare pagina's +
    de vraag); anders Ollama lokaal. Geeft "antwoord (Bron: site)", of None
    als er niets gevonden of samengevat kon worden. Zonder Gemini (geen
    sleutel of een storing) blijft alles zoals vóór Fase 25.
    """
    from core import llm

    if not llm.gemini_beschikbaar():
        return None
    try:
        if zoek is None:
            from actions.web import search_and_fetch as zoek

        resultaat = zoek(vraag, max_pages=pagina_s)
    except Exception:
        return None
    resultaat = resultaat or {}
    paginas = [p for p in resultaat.get("pages") or [] if (p.get("text") or p.get("snippet"))]
    if not resultaat.get("ok") or not paginas:
        return None

    delen = []
    for i, pagina in enumerate(paginas, 1):
        titel = pagina.get("title") or pagina.get("search_title") or _site(pagina.get("url"))
        tekst = str(pagina.get("text") or pagina.get("snippet") or "")[:MAX_BRON_TEKST]
        delen.append(f"[{i}] {titel} ({_site(pagina.get('url'))})\n{tekst}")

    try:
        from core import llm, privacy_poort

        berichten = [
            {"role": "system", "content": privacy_poort.persona() + "\n\n" + SAMENVAT_INSTRUCTIE},
            {"role": "user", "content": f"Vraag: {vraag}\n\nBronnen:\n\n" + "\n\n".join(delen)},
        ]
        if privacy_poort.naar_cloud(vraag):
            antwoord = llm.chat(messages=berichten, json_mode=True, cloud=True)
        else:
            antwoord = llm.chat(messages=berichten, json_mode=True)
    except Exception:
        return None

    data = _lees_json(getattr(antwoord.message, "content", "") or "")
    tekst = str(data.get("antwoord") or "").strip()
    if not tekst:
        return None
    bron = data.get("bron")
    if isinstance(bron, bool) or not isinstance(bron, int) or not 1 <= bron <= len(paginas):
        return tekst
    return f"{tekst} (Bron: {_site(paginas[bron - 1].get('url'))})"


def zoek_op(vraag):
    """Voert de opzoeking uit na een "ja" en geeft het antwoord met bron.

    Eerst Gemini met Google Zoeken (alleen betaald), dan DuckDuckGo met een
    kort samengevat antwoord; lukt dat niet, dan het letterlijke resultaat
    zoals voorheen. De bron staat in het antwoord.
    """
    if not vraag:
        return "Ik weet niet meer wat ik moest opzoeken. Vraag het me nog eens."

    kort = zoek_met_gemini(vraag) or zoek_en_vat_samen(vraag)
    if kort:
        return kort

    try:
        from actions.web import format_search_and_fetch, search_and_fetch

        resultaat = search_and_fetch(vraag, max_pages=1)
    except Exception:
        return "Het opzoeken lukte niet. Probeer het later nog eens."

    if not resultaat.get("ok"):
        return "Het opzoeken lukte niet. Probeer het later nog eens."

    return "Ik heb het opgezocht.\n\n" + format_search_and_fetch(resultaat)
