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

# Voorzetsels die een duur inleiden: "over 20 minuten", "in een uur".
_PREPOSITIE_PATROON = re.compile(r"\b(?:over|in|na)\s+", re.IGNORECASE)

# "van"/"voor" na een timerwoord: "zet een timer van 10 minuten".
_VAN_PATROON = re.compile(r"\b(?:van|voor)\s+", re.IGNORECASE)

# Timerwoorden: naast "timer" en "herinner" ook wekker, alarm en
# "waarschuw me".
_TIMER_WOORDEN = re.compile(
    r"\b(?:timer|herinner\w*|wekker|alarm|waarschuw|laat\s+me\s+weten|meld\s+me)\b",
    re.IGNORECASE,
)

# Naam-afsluiting: "om X", "voor X", "zodat X" na de duur.
_NAAM_PATROON = re.compile(
    r"(?:\s+(?:om|voor|zodat|wanneer)\s+)(.+)$",
    re.IGNORECASE,
)


def _duur_naar_seconden(tekst):
    """Zet een duur-fragment om in seconden (None als het niet lukt)."""

    return timers_module.parse_duur(tekst)


def _duur_na(tekst):
    """Pakt de duur uit ``tekst`` (of None).

    Alles na een naam-aankondiging ("om ...", "voor ...") telt niet mee.
    Lukt het niet vanaf het begin, dan worden voorloopwoorden ("zet een
    timer") overgeslagen.
    """

    naam_match = _NAAM_PATROON.search(tekst)
    if naam_match:
        tekst = tekst[:naam_match.start()]

    seconden = _duur_naar_seconden(tekst)
    if seconden:
        return seconden

    woorden = tekst.split()
    for start in range(1, len(woorden)):
        seconden = _duur_naar_seconden(" ".join(woorden[start:]))
        if seconden:
            return seconden

    return None


def _naam_uit(tekst):
    """Geeft de naam na "om/voor/zodat/wanneer", of None."""

    naam_match = _NAAM_PATROON.search(tekst)
    if naam_match:
        return naam_match.group(1).strip().strip(".!?")
    return None


def _extraheer_timer(command):
    """Probeer een timer-verzoek uit het commando te halen.

    Geeft (seconden, naam) terug, of None.
    """

    # Vraagzinnen ("hoe lang duurt een timer van 5 minuten op de oven",
    # "wat is een timer van 10 minuten") starten geen timer.
    if re.search(
        r"^\s*(?:hoe|hoelang|wat|waarom|wanneer|welke|wie)\b",
        command,
        re.IGNORECASE,
    ):
        return None

    # 1. Duur direct na "over/in/na" ("over een half uur").
    for match in _PREPOSITIE_PATROON.finditer(command):
        rest = command[match.end():]
        # Alleen starten als er ook een timerwoord in de zin staat
        if not _TIMER_WOORDEN.search(command):
            continue
        # Extra heuristiek: zinnen als vraag of beschrijving mogen geen timer starten
        if re.search(r"\b(hoe\s+lang|hoelang|duurt\s+het|wanneer|totdat|tot|is\s+het|begint|klaar|moet\s+ik|ben\s+ik)\b", command):
            continue
        # Vraagzinnen ("hoe lang duurt een timer van 5 minuten op de oven")
        # starten geen timer, ook niet als er een timerwoord in staat.
        if re.search(r"\b(hoe|wat|waarom|wanneer|welke|wie)\b", command):
            continue
        seconden = _duur_na(rest)
        if seconden:
            return (seconden, _naam_uit(rest) or "herinnering")

    # 2. Timerwoord met "van/voor" of een duur verderop in de zin.
    if _TIMER_WOORDEN.search(command):
        van_match = _VAN_PATROON.search(command)
        rest = command[van_match.end():] if van_match else command
        seconden = _duur_na(rest)
        if seconden:
            return (seconden, _naam_uit(rest) or "timer")

    return None


def _nachtmodus_stand_tekst():
    """Antwoord op de vraag wat de nachtmodus-stand nu is."""

    stand = proactive.get_nachtmodus_stand()
    if stand == "aan":
        basis = "De nachtmodus staat aan."
    elif stand == "uit":
        basis = "De nachtmodus staat uit."
    else:
        uur = datetime.now().strftime("%H:%M")
        nacht = proactive.is_nachtmodus()
        basis = (
            "De nachtmodus staat op automatisch "
            f"(23:00 tot 07:00); het is nu {uur} en de nachtmodus is "
            f"{'actief' if nacht else 'niet actief'}."
        )
    return f"{basis} {_nachtmodus_tot_tekst()}"


def _nachtmodus_tot_tekst():
    """Vertelt tot wanneer een handmatige nachtmodus-stand geldt."""

    verloopt = proactive.get_nachtmodus_verloopt()
    if not verloopt:
        return ""
    try:
        moment = datetime.fromtimestamp(verloopt)
    except (OSError, OverflowError, ValueError):
        return ""
    return (
        "Deze stand geldt tot "
        f"{moment.strftime('%H:%M')} ({moment.strftime('%d-%m')}), "
        "daarna volg ik weer de automatische tijden."
    )


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

    # Een opdracht heeft een werkwoordsvorm nodig ("zet ... aan", "schakel
    # ... in", "nachtmodus aan"). Een vraag ("staat de nachtmodus aan",
    # "is het nachtmodus") verandert niets.
    _OPDRACHT_AAN = (
        r"\b(?:zet|schakel|doe|activeer|start|ga|neem)\b"
        r"[^.?!]*\bnachtmodus\b"
    )
    _OPDRACHT_UIT = (
        r"\b(?:zet|schakel|doe|stop|beëindig|beeindig|eindig|deactiveer)\b"
        r"[^.?!]*\bnachtmodus\b"
    )
    _OPDRACHT_AUTO = (
        r"\b(?:zet|schakel|doe|laat)\b[^.?!]*\bnachtmodus\b"
        r"[^.?!]*\b(?:auto|automatisch|normaal)\b"
    )
    # "reset de nachtmodus", "zet de nachtmodus op automatisch".
    _OPDRACHT_AUTOWERKWOORD = (
        r"\breset\b[^.?!]*\bnachtmodus\b"
        r"|\bnachtmodus\b[^.?!]*\breset\b"
        r"|\bzet\b[^.?!]*\bnachtmodus\b[^.?!]*\bop\s+automatisch\b"
    )
    _KAAL_AAN = r"\bnachtmodus\s+(?:aan|in)\b"
    _KAAL_UIT = r"\bnachtmodus\s+uit\b"
    _KAAL_AUTO = (
        r"\bnachtmodus\s+(?:auto|automatisch|normaal)\b"
    )

    vraag_naar_stand = bool(re.search(
        r"\b(?:staat|is|heet|geldt|werkt|actief|aan\s+of\s+uit)\b"
        r"[^.?!]*\bnachtmodus\b"
        r"|\bnachtmodus\b[^.?!]*\?",
        command,
    ))

    # Vraag naar de stand: alleen antwoorden, niets veranderen.
    if vraag_naar_stand and not re.search(
        r"\b(?:zet|schakel|doe|laat|reset|activeer|start|ga|neem|stop|"
        r"beëindig|beeindig|eindig|deactiveer)\b[^.?!]*\bnachtmodus\b",
        command,
    ):
        return _nachtmodus_stand_tekst()

    # Stand "auto" terugzetten: automatisch, auto, normaal of reset.
    if (
        re.search(_OPDRACHT_AUTO, command)
        or re.search(_KAAL_AUTO, command)
        or re.search(_OPDRACHT_AUTOWERKWOORD, command)
    ):
        proactive.set_nachtmodus("auto")
        return (
            "De nachtmodus staat weer op automatisch: ik volg de vaste "
            "tijden van 23:00 tot 07:00."
        )

    if not vraag_naar_stand and (
        re.search(_OPDRACHT_AAN, command) or re.search(_KAAL_AAN, command)
    ):
        proactive.set_nachtmodus("aan")
        verloopt = _nachtmodus_tot_tekst()
        return (
            "De nachtmodus staat aan. Ik praat alleen nog als je me roept, "
            f"en dan zachter. {verloopt}"
        )

    if not vraag_naar_stand and (
        re.search(_OPDRACHT_UIT, command) or re.search(_KAAL_UIT, command)
    ):
        proactive.set_nachtmodus("uit")
        verloopt = _nachtmodus_tot_tekst()
        return (
            f"De nachtmodus is uitgeschakeld. Ik praat weer zoals overdag. "
            f"{verloopt}"
        )

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
