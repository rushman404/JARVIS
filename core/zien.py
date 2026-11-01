"""Zien: vragen over het scherm van de game-pc (Fase 35, M2 en M3).

"Wat zie je op mijn scherm?", "wat betekent deze foutmelding?", "wie wint
dit potje?", "leg deze opgave uit", "vat deze pagina samen".

* Alleen **op uw vraag** (nooit vanzelf) en alleen het scherm van de
  **game-pc**: staat het doel op de game-pc, dan via de agent
  (``game_pc_kijk_scherm``); draait het brein zelf op de game-pc, dan lokaal.
* Het antwoord is kort; is er meer, dan "Wilt u meer weten?" (Fase 27).
* Privacy: de vraag is voor de privacy-poort altijd persoonlijk (scherm), dus
  deze beurt gaat nooit mee naar Gemini; het beeld blijft op de game-pc.
"""

import logging
import re

logger = logging.getLogger("jarvis.zien")

_VRAGEN = re.compile(
    r"^(?:(?:kun|kan|wil)\s+(?:je|u)\s+)?(?:(?:eens|even|nu)\s+)?(?:"
    r"wat\s+zie\s+(?:je|jij|u)(?:\s+(?:nu|eigenlijk))?(?:\s+op\s+(?:mijn|m'n|het|dit)\s+scherm)?"
    r"|kijk\w*\s+(?:eens\s+|even\s+|mee\s+)?(?:naar|op|mee\s+op)\s+(?:mijn|m'n|het)\s+scherm"
    r"|wat\s+(?:staat|gebeurt)\s+er\s+(?:nu\s+)?op\s+(?:mijn|m'n|het)\s+scherm"
    r"|(?:wat\s+betekent|leg\s+(?:eens\s+|even\s+)?uit\s+wat|wat\s+moet\s+ik\s+doen\s+(?:met|aan))\s+"
    r"(?:deze|die|dit|de)\s+(?:fout(?:melding)?|error|melding|foutcode)"
    r"|(?:leg|vertel)\s+(?:me\s+)?(?:eens\s+|even\s+)?(?:deze|dit|die)\s+(?:opgave|vraag|som|tekst|pagina)\s+uit"
    r"|leg\s+(?:me\s+)?(?:eens\s+|even\s+)?uit\s+wat\s+(?:hier|er)\s+staat"
    r"|vat\s+(?:deze|dit|die)\s+(?:pagina|tekst|artikel)\s+samen"
    r"|wie\s+(?:wint|staat\s+er\s+voor|is\s+er\s+aan\s+het\s+winnen)(?:\s+(?:dit|het)\s+(?:potje|spel|game|ronde|match))?"
    r"|wat\s+is\s+(?:mijn|de)\s+(?:score|stand)(?:\s+(?:nu|in\s+dit\s+potje))?"
    r"|lees\s+(?:eens\s+|even\s+)?(?:voor\s+)?wat\s+(?:er\s+)?(?:hier\s+|op\s+(?:mijn|het)\s+scherm\s+)?staat(?:\s+voor)?"
    r")\s*[?.!]*$"
)

_SCHERM_WOORD = re.compile(r"\b(?:op\s+(?:mijn|m'n|het)\s+scherm|deze\s+foutmelding|dit\s+potje)\b")


def herken(zin):
    tekst = " ".join(str(zin or "").lower().replace("jarvis", "").strip(" ,.!?").split())
    return bool(tekst) and (bool(_VRAGEN.match(tekst)) or (
        _SCHERM_WOORD.search(tekst) is not None and tekst.split()[0] in
        ("wat", "wie", "waarom", "hoe", "welke", "welk", "kun", "kan", "leg", "lees", "staat", "is", "zie")))


def _vraag_aan_pc(vraag):
    from core import pc_target

    if pc_target.get_pc_target() == pc_target.GAME_PC:
        from remote import tools as remote_tools

        return remote_tools.execute_remote_tool("game_pc_kijk_scherm", {"vraag": vraag[:300]},
                                                question="zien")
    from actions.zien import kijk_scherm

    return kijk_scherm(vraag)


def _lees(resultaat):
    """(ok, kort, meer, melding) uit een lokaal of remote ToolResult."""

    from core.discord_dms import _binnen_melding, _gegeven, _gelukt

    data = getattr(resultaat, "data", None) or {}
    if "resultaat" in data:  # via de agent
        ok = _gelukt(resultaat)
        kort, meer = _gegeven(resultaat, "kort"), _gegeven(resultaat, "meer")
    else:
        ok = bool(getattr(resultaat, "ok", False))
        kort, meer = data.get("kort"), data.get("meer")
    melding = _binnen_melding(resultaat) if "resultaat" in data else str(getattr(resultaat, "message", "") or "")
    return ok, str(kort or melding or ""), str(meer or ""), melding


def kijk(zin, pc_fn=None):
    """Het gesproken antwoord op een vraag over het scherm."""

    import status

    vraag = " ".join(str(zin or "").split())
    try:
        status.zet_taak("kijkt naar het scherm")
    except Exception:
        pass
    try:
        resultaat = (pc_fn or _vraag_aan_pc)(vraag)
    except Exception:
        logger.exception("Zien mislukte.")
        return "Het lukte niet om naar het scherm van de game-pc te kijken, sir."
    finally:
        try:
            status.zet_taak(None)
        except Exception:
            pass
    ok, kort, meer, melding = _lees(resultaat)
    if not ok:
        return melding or "Het lukte niet om naar het scherm van de game-pc te kijken, sir."
    if not meer:
        return kort
    from core import vervolg
    from core.ai import MEER_WETEN_AANBOD

    vervolg.zet(MEER_WETEN_AANBOD, verwerk=lambda _ja: meer, controle=vervolg.JA)
    return f"{kort} {MEER_WETEN_AANBOD}"


def probeer_commando(zin, pc_fn=None):
    if not herken(zin):
        return None
    return kijk(zin, pc_fn=pc_fn)
