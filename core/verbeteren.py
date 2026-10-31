"""Verbeteren: "nee, ik bedoelde…" en de kon-niet-lijst (Fase 34).

**M1 — Verbeteren.** Binnen :data:`VENSTER` seconden na een opdracht:

* "nee, ik bedoelde Discord" / "ik bedoel Discord" / "nee, Discord" → de
  vorige actie wordt teruggedraaid als dat kan (:func:`noteer_actie`), en
  het goede commando wordt uitgevoerd ("open de kaart" → "open discord");
* "verkeerde" / "dat is fout" / "dat bedoelde ik niet" → terugdraaien en
  "Wat bedoelde u?" vragen.

Terugdraaien kan alleen voor wat veilig is: een app die JARVIS net opende
weer sluiten (hier of op de game-pc) en een lamp terugzetten. Gevaarlijke
acties (afsluiten, verwijderen) worden nooit genoteerd en dus nooit vanzelf
teruggedraaid.

**M2 — Onthouden.** De oorspronkelijke zin wijst voortaan naar het goede
commando (``memory/verbeteringen.json``, lokaal; :func:`vervang`). Te
beheren op de iPad en met "vergeet die verbetering". Verbetert u een
geleerde zin terug naar zichzelf, dan verdwijnt de regel.

**M3 — Kon-niet-lijst.** Zegt JARVIS dat hij iets nog niet kan, dan wordt
de **soort vraag** (bijv. "WhatsApp-bericht sturen") lokaal samengevat met
Ollama en geteld in ``memory/kon_niet.json``. Nooit de letterlijke zin; lukt
samenvatten niet, dan wordt er niets bewaard.
"""

import json
import logging
import os
import re
import threading
import time

logger = logging.getLogger("jarvis.verbeteren")

_MAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory")
VERBETERINGEN_FILE = os.path.join(_MAP, "verbeteringen.json")
KON_NIET_FILE = os.path.join(_MAP, "kon_niet.json")

VENSTER = 60.0          # zo lang na een opdracht kan hij verbeterd worden
MAX_KON_NIET = 100
WAT_BEDOELDE_U = "Wat bedoelde u, sir?"

_lock = threading.Lock()
_beurt = {"huidig": None, "vorige": None}


# ---------------------------------------------------------------------
# Beurten en acties
# ---------------------------------------------------------------------

def begin_beurt(zin, nu=None):
    """Bij het begin van elk commando (``process_command``).

    False als er al een beurt loopt (een routine die commando's uitvoert):
    dan hoort alles bij die buitenste beurt.
    """

    with _lock:
        if _beurt["huidig"] is not None:
            return False
        _beurt["huidig"] = {"zin": " ".join(str(zin or "").lower().split()), "acties": [], "bron_zin": None,
                            "tijd": nu if nu is not None else time.monotonic()}
        return True


def noteer_actie(soort, doel, terug, beschrijving=None):
    """Een uitgevoerde actie met hoe hij terug kan: ``terug`` = (tool, argumenten).

    ``soort``: ``app`` of ``lamp``. Faalt stil.
    """

    try:
        with _lock:
            huidig = _beurt["huidig"]
            if huidig is not None:
                huidig["acties"].append({"soort": soort, "doel": doel, "terug": terug,
                                         "beschrijving": beschrijving or doel})
    except Exception:
        pass


def einde_beurt(nu=None):
    """Na elk commando: deze beurt wordt de vorige (alleen als er iets gebeurde)."""

    with _lock:
        huidig = _beurt["huidig"]
        _beurt["huidig"] = None
        if huidig is None:
            return
        if huidig["bron_zin"]:
            huidig["zin"] = huidig["bron_zin"]
        huidig["tijd"] = nu if nu is not None else time.monotonic()
        _beurt["vorige"] = huidig


def _vorige(nu=None):
    with _lock:
        vorige = _beurt["vorige"]
    if not vorige:
        return None
    nu = nu if nu is not None else time.monotonic()
    return vorige if nu - vorige["tijd"] <= VENSTER else None


def _wis_vorige():
    with _lock:
        _beurt["vorige"] = None


def _reset():
    with _lock:
        _beurt["huidig"] = None
        _beurt["vorige"] = None


# ---------------------------------------------------------------------
# Herkennen
# ---------------------------------------------------------------------

_BEDOELDE = re.compile(
    r"^(?:nee|neen|nee nee)?[,.!\s]*(?:sorry[,\s]+)?(?:ik\s+)?bedoel(?:de)?\s+(?:eigenlijk\s+)?(.+)$")
_NEE_X = re.compile(r"^nee[,.!\s]+(?:niet\s+\S+(?:\s+\S+)?[,\s]+)?(?:maar\s+)?(.+)$")
_FOUT = re.compile(
    r"^(?:nee[,.!\s]*)?(?:dat\s+(?:is|was)\s+)?(?:(?:helemaal\s+)?fout|verkeerd|(?:de\s+)?verkeerde(?:\s+\w+)?|"
    r"het\s+verkeerde(?:\s+\w+)?|niet\s+goed|dat\s+bedoel(?:de)?\s+ik\s+niet|niet\s+(?:die|dat|deze)(?:\s+\w+)?)$")

# "nee, …" dat geen verbetering is.
_GEEN_VERBETERING = re.compile(
    r"^(?:dank\s*je(?:\s+wel)?|bedankt|laat\s+maar(?:\s+zitten)?|hoeft\s+niet|niks|niets|stop|"
    r"toch\s+niet|is\s+goed|prima|klopt|oké?|ok|dat\s+is\s+(?:alles|goed)|nu\s+niet|later)$")

_AFSLUIT = re.compile(r"\s+(aan|uit|af|open|dicht|op|in)$")


def _norm(tekst):
    return " ".join(str(tekst or "").lower().strip().strip(" .!?").replace(",", " ").split())


def herken(zin):
    """("bedoelde", X) / ("fout", None) / None."""

    tekst = " ".join(str(zin or "").lower().strip().strip(" .!?").split())
    if not tekst:
        return None
    if _FOUT.match(tekst):
        return ("fout", None)
    m = _BEDOELDE.match(tekst)
    if m:
        x = _norm(m.group(1))
        if x and not _GEEN_VERBETERING.match(x) and not _FOUT.match(x):
            return ("bedoelde", x)
        return None
    m = _NEE_X.match(tekst)
    if m:
        x = _norm(m.group(1))
        if x and not _GEEN_VERBETERING.match(x) and len(x.split()) <= 6:
            return ("nee", x)
    return None


def _werkwoorden():
    try:
        from core import commando_correctie

        return set(commando_correctie.laad_voorbeelden().get("werkwoorden") or [])
    except Exception:
        return {"zet", "doe", "open", "start", "sluit", "speel", "stop", "maak", "dim"}


def nieuw_commando(vorige_zin, bedoeld):
    """Het goede commando: ``bedoeld`` in de vorm van de vorige opdracht.

    "open de kaart" + "discord" → "open discord";
    "zet de lamp in de woonkamer aan" + "de slaapkamer" → "zet de slaapkamer aan";
    "open discord" + "sluit spotify" → "sluit spotify" (al een heel commando).
    """

    bedoeld = _norm(bedoeld)
    woorden = _norm(vorige_zin).split()
    werkwoorden = _werkwoorden()
    if not bedoeld or bedoeld.split()[0] in werkwoorden or not woorden or woorden[0] not in werkwoorden:
        return bedoeld
    werkwoord = woorden[0]
    rest = " ".join(woorden[1:])
    m = _AFSLUIT.search(rest)
    achter = m.group(1) if m and not _AFSLUIT.search(bedoeld) else ""
    return " ".join(f"{werkwoord} {bedoeld} {achter}".split())


# ---------------------------------------------------------------------
# Terugdraaien
# ---------------------------------------------------------------------

def _standaard_uitvoer(tool, argumenten):
    if tool == "close_program":
        from core.tools import close_program_tool

        return close_program_tool(argumenten["program"])
    if tool == "home_assistant":
        from core.home_assistant import control_home_assistant_tool

        return control_home_assistant_tool(**argumenten)
    if tool.startswith("game_pc_"):
        from core.ai import execute_tool

        return execute_tool(tool, argumenten, "verbeteren: terugdraaien")
    raise ValueError(tool)


def draai_terug(beurt, uitvoer=None):
    """Draait de acties van ``beurt`` terug (laatste eerst); geeft beschrijvingen terug."""

    uitvoer = uitvoer or _standaard_uitvoer
    gedaan = []
    for actie in reversed(beurt.get("acties") or []):
        terug = actie.get("terug")
        if not terug:
            continue
        try:
            uitvoer(terug[0], dict(terug[1]))
            gedaan.append(actie.get("beschrijving") or actie.get("doel"))
        except Exception:
            logger.warning("Terugdraaien van %s lukte niet.", actie.get("doel"), exc_info=True)
    return gedaan


# ---------------------------------------------------------------------
# M2 — onthouden
# ---------------------------------------------------------------------

def _sleutel(zin):
    try:
        from core import commando_correctie

        return commando_correctie._sleutel(zin)
    except Exception:
        return _norm(zin)


def _lees(pad):
    try:
        with open(pad, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _schrijf(pad, data):
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    tijdelijk = pad + ".tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tijdelijk, pad)


def leer(zin, commando):
    """``zin`` betekent voortaan ``commando``; terug naar zichzelf = vergeten."""

    sleutel = _sleutel(zin)
    commando = _norm(commando)
    if not sleutel or not commando:
        return
    with _lock:
        data = _lees(VERBETERINGEN_FILE)
        if _sleutel(commando) == sleutel:
            if data.pop(sleutel, None) is not None:
                _schrijf(VERBETERINGEN_FILE, data)
            return
        data[sleutel] = {"commando": commando, "sinds": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _schrijf(VERBETERINGEN_FILE, data)
    logger.info("Verbetering onthouden: %r → %r", sleutel, commando)


def vervang(zin):
    """Het geleerde commando voor ``zin``, of ``zin`` zelf."""

    sleutel = _sleutel(zin)
    if not sleutel:
        return zin
    with _lock:
        regel = _lees(VERBETERINGEN_FILE).get(sleutel)
    if isinstance(regel, dict) and isinstance(regel.get("commando"), str) and regel["commando"]:
        logger.info("Geleerde verbetering: %r → %r", sleutel, regel["commando"])
        return regel["commando"]
    return zin


def verbeteringen():
    with _lock:
        data = _lees(VERBETERINGEN_FILE)
    rijen = [{"zin": z, "commando": r.get("commando"), "sinds": r.get("sinds")}
             for z, r in data.items() if isinstance(r, dict)]
    return sorted(rijen, key=lambda r: str(r.get("sinds") or ""), reverse=True)


def vergeet(zin=None):
    """Eén verbetering (of alles zonder ``zin``) vergeten; geeft het aantal terug."""

    with _lock:
        data = _lees(VERBETERINGEN_FILE)
        if zin is None:
            aantal = len(data)
            data = {}
        else:
            aantal = 1 if data.pop(zin, None) is not None or data.pop(_sleutel(zin), None) is not None else 0
        _schrijf(VERBETERINGEN_FILE, data)
    return aantal


# ---------------------------------------------------------------------
# M1 — de verbetering uitvoeren
# ---------------------------------------------------------------------

def _terug_zin(gedaan):
    if not gedaan:
        return ""
    return "Ik heb " + " en ".join(gedaan) + ". "


def corrigeer(bedoeld, verwerk, vorige=None, uitvoer=None):
    """Terugdraaien, het goede commando uitvoeren en het onthouden."""

    vorige = vorige or _vorige()
    if vorige is None:
        return None
    gedaan = draai_terug(vorige, uitvoer)
    commando = nieuw_commando(vorige["zin"], bedoeld)
    _wis_vorige()
    with _lock:
        if _beurt["huidig"] is not None:
            # Een volgende verbetering hoort weer bij de oorspronkelijke zin.
            _beurt["huidig"]["bron_zin"] = vorige["zin"]
    leer(vorige["zin"], commando)
    antwoord = verwerk(commando)
    return (_terug_zin(gedaan) + (antwoord or "")).strip()


def probeer_commando(zin, verwerk, uitvoer=None):
    """De verbetering afhandelen, of None als het geen verbetering is."""

    soort = herken(zin)
    if soort is None:
        return None
    vorige = _vorige()
    if vorige is None:
        return None
    if soort[0] == "nee" and not vorige.get("acties"):
        return None
    if soort[0] == "fout":
        gedaan = draai_terug(vorige, uitvoer)
        vorige = dict(vorige, acties=[])
        from core import vervolg

        def antwoord_op_vraag(bedoeld):
            with _lock:
                _beurt["huidig"] = _beurt["huidig"] or {"zin": bedoeld, "acties": [], "bron_zin": None,
                                                          "tijd": time.monotonic()}
            return corrigeer(bedoeld, verwerk, vorige=vorige, uitvoer=uitvoer)

        vervolg.zet(WAT_BEDOELDE_U, verwerk=antwoord_op_vraag, controle=vervolg.TEKST)
        return (_terug_zin(gedaan) + WAT_BEDOELDE_U).strip()
    return corrigeer(soort[1], verwerk, vorige=vorige, uitvoer=uitvoer)


_VERGEET = re.compile(r"^vergeet\s+(?:die|deze|de\s+laatste|mijn)\s+verbetering(?:en)?$")
_VERGEET_ALLES = re.compile(r"^vergeet\s+(?:alle|al\s+mijn)\s+verbeteringen$")


def probeer_beheer(zin):
    """ "vergeet die verbetering" / "vergeet alle verbeteringen"."""

    tekst = _norm(zin)
    if _VERGEET_ALLES.match(tekst):
        aantal = vergeet()
        return f"Ik ben {aantal} verbetering{'en' if aantal != 1 else ''} vergeten, sir."
    if _VERGEET.match(tekst):
        rijen = verbeteringen()
        if not rijen:
            return "Ik heb geen verbeteringen onthouden, sir."
        vergeet(rijen[0]["zin"])
        return f"Vergeten: '{rijen[0]['zin']}' betekent niet langer '{rijen[0]['commando']}'."
    return None


# ---------------------------------------------------------------------
# M3 — kon-niet-lijst
# ---------------------------------------------------------------------

_KAN_NIET = re.compile(
    r"\b(?:dat\s+kan\s+ik\s+(?:nog\s+)?niet|kan\s+ik\s+(?:nog\s+)?niet\s+(?:doen|sturen|openen|regelen|bedienen)|"
    r"daar\s+heb\s+ik\s+(?:nog\s+)?geen\s+(?:functie|tool|mogelijkheid|koppeling)|"
    r"ik\s+(?:heb|kan)\s+(?:nog\s+)?geen\s+(?:toegang|functie|tool|koppeling)\s+(?:tot|om|voor|met))",
    re.IGNORECASE)


def kon_niet(antwoord):
    return bool(_KAN_NIET.search(str(antwoord or "")))


_VOORBEELDEN = (
    ("stuur een whatsapp naar Lisa dat ik later ben", "WhatsApp-bericht sturen"),
    ("hoe laat gaat mijn bus naar Amsterdam", "Vertrektijden openbaar vervoer"),
    ("bestel sushi bij de Japanner om de hoek", "Eten bestellen"),
    ("zet de wasmachine aan", "Wasmachine bedienen"),
)


def _standaard_samenvatter(zin):
    from core import llm

    berichten = [{"role": "system", "content": (
        "Je vat een verzoek samen als SOORT verzoek: 2 tot 4 gewone Nederlandse woorden, "
        "zonder namen, plaatsen, tijden of persoonlijke details. Antwoord alleen met de samenvatting.")}]
    for vraag, soort in _VOORBEELDEN:
        berichten.append({"role": "user", "content": vraag})
        berichten.append({"role": "assistant", "content": soort})
    berichten.append({"role": "user", "content": zin})
    antwoord = llm.chat(messages=berichten, options={"temperature": 0})  # nooit cloud=True: blijft lokaal
    return str(getattr(antwoord.message, "content", "") or "")


def _schoon_soort(tekst, zin):
    soort = " ".join(str(tekst or "").strip().strip("'\".").split())
    if not soort or len(soort.split()) > 6 or len(soort) > 60:
        return None
    # Nooit (een stuk van) de letterlijke zin bewaren.
    if soort.lower() in _norm(zin) and len(soort.split()) > 2:
        return None
    return soort[0].upper() + soort[1:]


def noteer_kon_niet(zin, samenvatter=None, nu=None):
    """Telt de soort vraag; geeft de soort terug (of None)."""

    try:
        soort = _schoon_soort((samenvatter or _standaard_samenvatter)(zin), zin)
    except Exception:
        logger.debug("Kon-niet samenvatten lukte niet.", exc_info=True)
        return None
    if not soort:
        return None
    from rapidfuzz import fuzz

    with _lock:
        data = _lees(KON_NIET_FILE)
        sleutel = next((s for s in data if fuzz.ratio(s.lower(), soort.lower()) >= 85), soort)
        regel = data.get(sleutel) if isinstance(data.get(sleutel), dict) else {"keer": 0}
        regel["keer"] = int(regel.get("keer", 0)) + 1
        regel["laatst"] = nu or time.strftime("%Y-%m-%dT%H:%M:%S")
        data[sleutel] = regel
        if len(data) > MAX_KON_NIET:
            for s in sorted(data, key=lambda s: str(data[s].get("laatst", "")))[:len(data) - MAX_KON_NIET]:
                del data[s]
        _schrijf(KON_NIET_FILE, data)
    return sleutel


def kon_niet_lijst():
    with _lock:
        data = _lees(KON_NIET_FILE)
    rijen = [{"soort": s, "keer": r.get("keer", 0), "laatst": r.get("laatst")}
             for s, r in data.items() if isinstance(r, dict)]
    return sorted(rijen, key=lambda r: (-int(r["keer"] or 0), r["soort"]))


def wis_kon_niet(soort=None):
    with _lock:
        data = _lees(KON_NIET_FILE)
        if soort is None:
            data = {}
        else:
            data.pop(soort, None)
        _schrijf(KON_NIET_FILE, data)


def na_beurt(zin, antwoord, achtergrond=True):
    """Na elk commando: kon hij het niet, dan (op de achtergrond) noteren."""

    if not isinstance(antwoord, str) or not kon_niet(antwoord):
        return
    with _lock:
        huidig = _beurt["huidig"]
        if huidig and huidig["acties"]:
            return
    if achtergrond:
        threading.Thread(target=noteer_kon_niet, args=(zin,), name="kon-niet", daemon=True).start()
    else:
        noteer_kon_niet(zin)
