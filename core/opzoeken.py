"""Het aanbod "Wil je dat ik het opzoek?" met een ja/nee-pending (Fase 17).

Twijfelt het taalmodel over een feit, dan zegt het (via de zekerheidsregel in
``core/ai.py``) iets als "Dat weet ik niet zeker. Wil je dat ik het opzoek?".
Zonder deze module zou een "ja" daarop nergens landen. Nu zet het aanbod een
korte pending; pas na een expliciet "ja" gaat de zoekopdracht naar buiten,
met de oorspronkelijke vraag en met bronvermelding in het antwoord.

De pending staat alleen in het geheugen (zie ``core/confirmation.py``): na een
herstart of na de ttl doet een "ja" niets meer.
"""

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


def zoek_op(vraag):
    """Voert de opzoeking uit na een "ja" en geeft het antwoord met bron.

    Gebruikt dezelfde veilige zoekfunctie als het gewone zoekcommando
    (``actions.web.search_and_fetch``), zodat er niets nieuws naar buiten
    gaat. De bron staat in het antwoord (titel en URL per bron).
    """
    if not vraag:
        return "Ik weet niet meer wat ik moest opzoeken. Vraag het me nog eens."

    try:
        from actions.web import format_search_and_fetch, search_and_fetch

        resultaat = search_and_fetch(vraag, max_pages=1)
    except Exception:
        return "Het opzoeken lukte niet. Probeer het later nog eens."

    if not resultaat.get("ok"):
        return "Het opzoeken lukte niet. Probeer het later nog eens."

    return "Ik heb het opgezocht.\n\n" + format_search_and_fetch(resultaat)
