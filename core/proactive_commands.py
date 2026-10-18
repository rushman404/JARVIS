"""Spraak-commando's voor proactieve JARVIS (Fase 16A/16B).

Hier zitten de deterministische commando's voor:
  * timers/herinneringen: "herinner me over 20 minuten om de oven uit te
    zetten", "zet een timer van 10 minuten", "welke timers", "annuleer
    timer"
  * nachtmodus: "nachtmodus aan/uit", "ga in nachtmodus"
  * stille modus (quiet): "stille modus aan/uit", "wees stil"
  * dagstart/dagafsluiting (Fase 16B, alleen op aanvraag): "goedemorgen",
    "wat staat er vandaag", "dagafsluiting"

Elke handler geeft een antwoord-string terug, of None als het commando
niet over proactieve functies gaat (zoals de andere try_*-routers in
core/brain.py).
"""

import re
from datetime import datetime

from config import USER_NAME, WEER_PLAATS
from core import proactive
from core import timers as timers_module

# Dagstart / dagafsluiting (Fase 16B) — alleen op aanvraag.
_DAGSTART_PATROON = re.compile(
    r"\b(goedemorgen|goeiemorgen|dagstart"
    r"|start\s+(?:de|mijn)\s+dag"
    r"|begin\s+(?:de|mijn)\s+dag"
    r"|wat\s+staat\s+er\s+vandaag"
    r"|overzicht\s+van\s+(?:de|mijn)\s+dag)\b"
)
_DAGAFSLUITING_PATROON = re.compile(
    r"\b(dagafsluiting"
    r"|sluit\s+(?:de|mijn)\s+dag\s+af"
    r"|einde\s+van\s+(?:de|mijn)\s+dag"
    r"|afsluiten\s+voor\s+vandaag"
    r"|goede\s+nacht)\b"
)


def _actieve_timers():
    """Geeft de actieve timers terug (of een lege lijst bij een fout)."""

    try:
        return timers_module.get_store().lijst()
    except Exception:
        return []


def _dagstart_tekst():
    """Korte ochtend-/dagsamenvatting: groet, weer, herinneringen en HA."""

    uur = datetime.now().hour
    if uur < 12:
        groet = "Goedemorgen"
    elif uur < 18:
        groet = "Goedemiddag"
    else:
        groet = "Goedenavond"

    delen = [f"{groet}, {USER_NAME}."]

    try:
        from actions.web import get_weather, format_weather
        weer = format_weather(get_weather(WEER_PLAATS))
        if weer:
            delen.append(weer.strip())
    except Exception:
        pass

    timers = _actieve_timers()
    if timers:
        namen = ", ".join(t.get("naam", "herinnering") for t in timers)
        meervoud = "herinneringen" if len(timers) != 1 else "herinnering"
        delen.append(f"U hebt {len(timers)} openstaande {meervoud}: {namen}.")
    else:
        delen.append("U hebt geen openstaande herinneringen.")

    try:
        from core.home_assistant import _config_ok, _ha_get
        if _config_ok():
            ok, _data = _ha_get("/api/")
            if not ok:
                delen.append("Let op: Home Assistant lijkt niet bereikbaar.")
    except Exception:
        pass

    return " ".join(delen)


def _dagafsluiting_tekst():
    """Korte avondafsluiting: openstaande herinneringen en een vriendelijk woord."""

    delen = []
    timers = _actieve_timers()
    if timers:
        namen = ", ".join(t.get("naam", "herinnering") for t in timers)
        meervoud = "herinneringen" if len(timers) != 1 else "herinnering"
        delen.append(f"U hebt nog {len(timers)} openstaande {meervoud}: {namen}.")
    delen.append(
        f"De dag zit erop, {USER_NAME}. Rust even goed uit — ik ben er morgen weer."
    )
    return " ".join(delen)

# Duur-patroon: "20 minuten", "een uur", "half uur", "kwartier",
# "1 uur 30 minuten", "30 seconden".
_Duur_PATROON = re.compile(
    r"(?:over|in|na)\s+"
    r"((?:\d+\s*(?:uur|uren|u|minuten|min|seconden|sec|kwartier)"
    r"|half\s+uur|kwartier"
    r"|(?:een|eën|twee|drie|vier|vijf|zes|zeven|acht|negen|tien)"
    r"\s*(?:uur|minuten|min|seconden|sec)"
    r"|(?:\d+\s*uur\s+\d+\s*minuten)"
    r")(?:\s+en\s+\d+\s*(?:minuten|min|seconden|sec))?)",
    re.IGNORECASE,
)

# Naam-afsluiting: "om X", "voor X", "zodat X" na de duur.
_NAAM_PATROON = re.compile(
    r"(?:\s+(?:om|voor|zodat|wanneer)\s+)(.+)$",
    re.IGNORECASE,
)

# Simpeler duur-vormen zonder "over/in/na": "zet een timer van 10 minuten".
_DUUR_ZONDER_VOORZETSEL = re.compile(
    r"((?:\d+\s*(?:uur|uren|u|minuten|min|seconden|sec|kwartier)"
    r"|half\s+uur|kwartier"
    r"|(?:een|eën|twee|drie|vier|vijf|zes|zeven|acht|negen|tien)"
    r"\s*(?:uur|minuten|min|seconden|sec)"
    r"|(?:\d+\s*uur\s+\d+\s*minuten)"
    r")(?:\s+en\s+\d+\s*(?:minuten|min|seconden|sec))?)",
    re.IGNORECASE,
)


def _duur_naar_seconden(tekst):
    """Zet een duur-fragment om in seconden (None als het niet lukt)."""

    return timers_module.parse_duur(tekst)


def _extraheer_timer(command):
    """Probeer een timer-verzoek uit het commando te halen.

    Geeft (seconden, naam) terug, of None.
    """

    match = _Duur_PATROON.search(command)
    if match:
        seconden = _duur_naar_seconden(match.group(1))
        if seconden:
            naam = "herinnering"
            naam_match = _NAAM_PATROON.search(command[match.end():])
            if naam_match:
                naam = naam_match.group(1).strip().strip(".!?")
            return (seconden, naam)

    # "zet een timer van 10 minuten [voor X]"
    if re.search(r"\btimer\b|herinner", command):
        match = _DUUR_ZONDER_VOORZETSEL.search(command)
        if match:
            seconden = _duur_naar_seconden(match.group(1))
            if seconden:
                naam = "timer"
                naam_match = _NAAM_PATROON.search(command[match.end():])
                if naam_match:
                    naam = naam_match.group(1).strip().strip(".!?")
                return (seconden, naam)

    return None


def try_proactive_command(command):
    """Verwerkt proactieve commando's (timers, nachtmodus, stille modus,
    dagstart/dagafsluiting).

    Geeft een antwoord-string, of None als het commando niet over
    proactieve functies gaat. Een herkend commando geldt als activiteit:
    een eventuele auto-slaap wordt dan uitgezet.
    """

    resultaat = _verwerk_proactief(command)
    if resultaat is not None:
        proactive.markeer_activiteit()
    return resultaat


def _verwerk_proactief(command):
    """Interne verwerking van de proactieve commando's."""

    if not command:
        return None

    command = command.lower().strip()

    # =========================================================
    # DAGSTART / DAGAFSLUITING (Fase 16B) — alleen op aanvraag
    # =========================================================

    if _DAGSTART_PATROON.search(command):
        return _dagstart_tekst()

    if _DAGAFSLUITING_PATROON.search(command):
        return _dagafsluiting_tekst()

    # =========================================================
    # NACHTMODUS
    # =========================================================

    if re.search(
        r"(nachtmodus\s+(aan|activeren|inschakelen|zet\s+aan)"
        r"|zet\s+(?:de\s+)?nachtmodus\s+(?:aan|in)"
        r"|ga\s+(?:in\s+)?nachtmodus"
        r"|start\s+(?:de\s+)?nachtmodus)",
        command,
    ):
        proactive.set_quiet(False)  # nachtmodus vervangt geen quiet-state
        return (
            "De nachtmodus staat aan. Ik praat alleen nog als je me "
            "roept, en dan zachter."
        )

    if re.search(
        r"(nachtmodus\s+(?:uit|uitschakelen|stoppen|deactiveren|zet\s+uit)"
        r"|zet\s+(?:de\s+)?nachtmodus\s+uit"
        r"|stop\s+(?:de\s+)?nachtmodus"
        r"|eindig\s+(?:de\s+)?nachtmodus)",
        command,
    ):
        return "De nachtmodus is uitgeschakeld. Ik praat weer zoals overdag."

    # =========================================================
    # STILLE MODUS (quiet)
    # =========================================================

    if re.search(
        r"((?:stille|stilte|quiet)\s*(?:modus|mode)\s+"
        r"(?:aan|activeren|inschakelen|zet\s+aan)"
        r"|wees\s+stil"
        r"|hou\s+je\s+stil"
        r"|spreek\s+(?:maar\s+)?niet\s+(?:meer|nu))",
        command,
    ):
        proactive.set_quiet(True)
        return (
            "De stille modus staat aan. Ik zeg niets meer uit mezelf; "
            "spreek me maar aan als je me nodig hebt."
        )

    if re.search(
        r"((?:stille|stilte|quiet)\s*(?:modus|mode)\s+"
        r"(?:uit|uitschakelen|stoppen|deactiveren|zet\s+uit)"
        r"|spreek\s+weer"
        r"|praat\s+weer)",
        command,
    ):
        proactive.set_quiet(False)
        return "De stille modus is uitgeschakeld. Ik meld me weer als er iets is."

    # =========================================================
    # TIMERS
    # =========================================================

    # Annuleren (moet vóór "zet een timer" komen).
    if re.search(r"\b(annuleer|verwijder|wis|stop|vergeet)\b.*\btimer\b", command) or \
       re.search(r"\btimer\b.*\b(annuleren|verwijderen|wissen)\b", command):
        store = timers_module.get_store()
        # Naam proberen te vinden na het werkwoord.
        naam_match = re.search(
            r"(?:annuleer|verwijder|wis|stop|vergeet)\s+(?:de\s+|mijn\s+)?timer"
            r"(?:\s+(?:voor|van|genaamd|met\s+de\s+naam)\s+(.+))?$",
            command,
        )
        naam = None
        if naam_match and naam_match.group(1):
            naam = naam_match.group(1).strip().strip(".!?")
        aantal = store.annuleer(naam)
        if aantal == 0:
            if naam:
                return f"Er is geen timer met de naam '{naam}'."
            return "Er zijn geen actieve timers."
        if naam:
            return f"Timer '{naam}' is geannuleerd."
        return f"{aantal} timer(s) geannuleerd."

    # Lijst met timers.
    if re.search(
        r"(welke|hoeveel|toon|laat|overzicht)\s+(?:zijn\s+|is\s+|heb\s+ik\s+)?"
        r"(?:mijn\s+|je\s+)?(?:timers?|herinneringen?)",
        command,
    ) or re.search(r"\btimers?\s+(tonen|overzicht|lijst)", command):
        store = timers_module.get_store()
        lijst = store.lijst()
        if not lijst:
            return "Er zijn geen actieve timers."
        regels = []
        for t in lijst:
            rest = int(t["af_loopt_op"] - store.clock())
            if rest >= 3600:
                beschrijving = f"over {rest // 3600} uur"
            elif rest >= 60:
                beschrijving = f"over {rest // 60} minuten"
            else:
                beschrijving = f"over {rest} seconden"
            regels.append(f"'{t['naam']}' {beschrijving}")
        return "Je timers: " + "; ".join(regels) + "."

    # Nieuwe timer.
    gevonden = _extraheer_timer(command)
    if gevonden:
        seconden, naam = gevonden
        store = timers_module.get_store()
        timer = store.zet(naam, seconden)
        if timer is None:
            return "Ik kon die duur niet verstaan. Zeg bijvoorbeeld 'herinner me over 20 minuten'."
        if seconden >= 3600:
            uren = seconden // 3600
            rest_min = (seconden % 3600) // 60
            beschrijving = f"{uren} uur"
            if rest_min:
                beschrijving += f" en {rest_min} minuten"
        elif seconden >= 60:
            beschrijving = f"{seconden // 60} minuten"
        else:
            beschrijving = f"{seconden} seconden"
        return f"Oké, ik zet een timer van {beschrijving} voor '{naam}'."

    return None
