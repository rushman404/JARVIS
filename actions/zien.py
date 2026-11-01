"""Zien: wat staat er op het scherm? (Fase 35, M1)

Draait op de **game-pc** (agent-tool ``kijk_scherm``): een screenshot van het
scherm waar het actieve venster staat gaat naar een **lokaal** beeldmodel
(Ollama, standaard Gemma 3 4B) op deze pc. Het beeld wordt nooit bewaard en
verlaat de pc niet; alleen de tekst-uitleg gaat terug naar het brein.

Het model blijft ``ZIEN_KEEP_ALIVE`` (5 minuten) geladen voor vervolgvragen
en gaat daarna uit het videogeheugen (voor games).
"""

import io
import logging
import re

from core.result_validation import ToolResult

logger = logging.getLogger("jarvis.zien")

MAX_ZIJDE = 1600  # langste zijde van het beeld voor het model

INSTRUCTIE = (
    "Je bent JARVIS, een Nederlandse assistent. Je krijgt een beeld van het scherm van de "
    "gebruiker en een vraag. Kijk goed, lees tekst letterlijk waar nodig en verzin niets wat je "
    "niet ziet. Zeg 'op uw scherm', niet 'op de screenshot'. Spreek de gebruiker aan met 'u', in "
    "gewone spreektaal, zonder Markdown of opsommingen.\n"
    "Antwoord in precies dit formaat:\n"
    "KORT: <het antwoord in één of twee zinnen>\n"
    "MEER: <alleen bij een foutmelding, opgave of iets dat echt uitleg nodig heeft: drie tot vijf "
    "zinnen extra, bijvoorbeeld wat u eraan kunt doen. Anders precies: GEEN>"
)

STANDAARD_VRAAG = "Wat zie je op mijn scherm?"


def _scherm_van_actief_venster():
    """(links, boven, rechts, onder) van de monitor met het actieve venster, of None."""

    try:
        import win32api
        import win32gui

        venster = win32gui.GetForegroundWindow()
        monitor = win32api.MonitorFromWindow(venster, 2)  # MONITOR_DEFAULTTONEAREST
        return tuple(win32api.GetMonitorInfo(monitor)["Monitor"])
    except Exception:
        return None


def maak_beeld(grab=None, kader_fn=None):
    """JPEG-bytes van het actieve scherm (alleen in het geheugen)."""

    if grab is None:
        from PIL import ImageGrab

        grab = ImageGrab.grab
    kader = (kader_fn or _scherm_van_actief_venster)()
    beeld = grab(bbox=kader, all_screens=True) if kader else grab()
    beeld = beeld.convert("RGB")
    beeld.thumbnail((MAX_ZIJDE, MAX_ZIJDE))
    buffer = io.BytesIO()
    beeld.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _vraag_model(vraag, beeld):
    import ollama

    from config import ZIEN_KEEP_ALIVE, ZIEN_MODEL

    antwoord = ollama.chat(
        model=ZIEN_MODEL,
        messages=[
            {"role": "system", "content": INSTRUCTIE},
            {"role": "user", "content": vraag, "images": [beeld]},
        ],
        keep_alive=ZIEN_KEEP_ALIVE,
        options={"temperature": 0.2},
    )
    return str(antwoord.message.content or "")


_KORT = re.compile(r"KORT\s*:\s*(.*?)(?:\n\s*MEER\s*:\s*(.*))?$", re.IGNORECASE | re.DOTALL)
_LEEG_MEER = re.compile(r"^[\s\-–—.<>]*(?:leeg|niets|geen|n\.?v\.?t\.?)?[\s\-–—.<>]*$", re.IGNORECASE)


def lees_antwoord(tekst):
    """(kort, meer) uit het modelantwoord; ``meer`` kan leeg zijn."""

    tekst = str(tekst or "").replace("**", "").strip()
    m = _KORT.search(tekst)
    if m:
        kort, meer = m.group(1).strip(), (m.group(2) or "").strip()
    else:
        zinnen = re.split(r"(?<=[.!?])\s+", tekst)
        kort, meer = " ".join(zinnen[:2]).strip(), " ".join(zinnen[2:]).strip()
    if _LEEG_MEER.match(meer):
        meer = ""
    return " ".join(kort.split()), " ".join(meer.split())


def kijk_scherm(vraag="", beeld_fn=None, model_fn=None):
    """Beantwoordt ``vraag`` over het scherm. ``data``: ``kort`` en ``meer``."""

    vraag = " ".join(str(vraag or "").split()) or STANDAARD_VRAAG
    try:
        beeld = (beeld_fn or maak_beeld)()
    except Exception as e:
        logger.warning("Screenshot voor zien lukte niet: %s", e)
        return ToolResult(False, "Ik kon geen screenshot van het scherm maken.", error_kind="screenshot")
    try:
        kort, meer = lees_antwoord((model_fn or _vraag_model)(vraag, beeld))
    except Exception as e:
        logger.warning("Beeldmodel gaf geen antwoord: %s", e)
        return ToolResult(False, "Het beeldmodel op de game-pc gaf geen antwoord. Draait Ollama daar?",
                          error_kind="model")
    finally:
        beeld = None
    if not kort:
        return ToolResult(False, "Ik kon niet goed zien wat er op het scherm staat.", error_kind="leeg")
    return ToolResult(True, kort, data={"kort": kort, "meer": meer})
