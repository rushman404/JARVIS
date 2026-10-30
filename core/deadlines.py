"""Deadlines (Fase 26, M1): met de stem invoeren, opvragen en herinneren.

Een deadline is een gewone afspraak in de iCloud-agenda (Fase 23, M4) met
"Deadline: " voor de titel; zo ziet u hem ook op uw telefoon en raakt
JARVIS uw andere afspraken niet aan.

* "zet een deadline: verslag op vrijdag" → hele dag op vrijdag (met een tijd,
  "vrijdag om 17 uur", een korte afspraak op dat tijdstip). Altijd eerst een
  ja/nee-vraag, net als bij afspraken.
* "welke deadlines heb ik deze week?", "wanneer moet het verslag af?"
* Herinneringen: de avond ervoor (19:00) en de ochtend zelf (08:00). Het zijn
  gewone systeemmeldingen: 's nachts en in de stille modus wachten ze.
* Het paneel Vandaag toont de deadlines van de komende dagen.

Besluiten 2026-10-28/30: alleen met de stem invoeren (niet uit de mail
halen), hele-dag-afspraak in de gewone agenda, herinneren de avond ervoor
en de ochtend zelf, tonen in het paneel Vandaag (niet bij de dagstart).
"""

import logging
import os
import re
import threading
from datetime import date, datetime, timedelta

from core import agenda_tijd as tijd
from core import koppelingen

logger = logging.getLogger("jarvis.deadlines")

PREFIX = "Deadline: "
DUUR_MET_TIJD = timedelta(minutes=15)   # een deadline om 17:00 is geen afspraak van een uur
STANDAARD_DAGEN = 14                    # "welke deadlines heb ik?" kijkt zo ver vooruit
WEEK_DAGEN = 7
PANEEL_DAGEN = 7
MAX_PANEEL = 4

AVOND_UUR = 19     # herinnering de avond ervoor
OCHTEND_UUR = 8    # en de ochtend zelf

HERINNERD_FILE = os.path.join(koppelingen.MAP, "deadline_herinnerd.json")


def is_deadline(afspraak):
    return str(afspraak.get("titel") or "").strip().lower().startswith("deadline")


def naam(afspraak):
    """"Deadline: verslag" → "verslag"."""

    titel = str(afspraak.get("titel") or "").strip()
    return re.sub(r"^deadline\s*[:\-–]?\s*", "", titel, flags=re.IGNORECASE) or titel


def _dag(afspraak):
    start = afspraak["start"]
    return start.date() if isinstance(start, datetime) else start


def _wanneer(afspraak, vandaag):
    woord = tijd.dag_woord(_dag(afspraak), vandaag)
    if afspraak.get("hele_dag") or not isinstance(afspraak["start"], datetime):
        return woord
    return f"{woord} om {tijd.klok(afspraak['start'])}"


# -----------------------------------------------------------------
# Herkennen
# -----------------------------------------------------------------

_AANLOOP = re.compile(r"^(?:jarvis[, ]+)?(?:kun\s+je|kan\s+je|wil\s+je)\s+", re.IGNORECASE)
_TOEVOEGEN = re.compile(
    r"^(?:(?:zet|maak|noteer|plan|voeg)\s+(?:een\s+)?(?:nieuwe\s+)?deadline(?:\s+(?:toe|aan))?"
    r"|nieuwe\s+deadline|deadline)\s*(?:[:,\-]|\s(?:voor|aan|toe))?\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_ALLEEN_TOEVOEGEN = re.compile(
    r"^(?:(?:zet|maak|noteer|plan|voeg)\s+(?:een\s+)?(?:nieuwe\s+)?deadline(?:\s+(?:toe|aan|in))?"
    r"|nieuwe\s+deadline|deadline\s+toevoegen)$",
    re.IGNORECASE,
)
_LIJST = re.compile(
    r"^(?:welke|wat\s+(?:zijn|voor))\s+(?:mijn\s+)?deadlines?\b(?P<rest>.*)$"
    r"|^(?:heb\s+ik\s+(?:nog\s+)?(?:deadlines?|iets\s+in\s+te\s+leveren))\b(?P<rest2>.*)$"
    r"|^(?:mijn\s+)?deadlines?(?P<rest3>(?:\s+(?:voor\s+)?(?:deze\s+week|vandaag|morgen|de\s+komende\s+(?:dagen|week)))?)$",
    re.IGNORECASE,
)
_ZOEK = re.compile(
    r"^wanneer\s+(?:moet|is)\s+(?:ik\s+)?(?:de\s+deadline\s+(?:van|voor)\s+)?(?:mijn\s+|het\s+|de\s+|een\s+)?"
    r"(?P<wat>.+?)(?:\s+(?:af|inleveren|ingeleverd|klaar|af\s+zijn|ingeleverd\s+worden))?$",
    re.IGNORECASE,
)


def _schoon(command):
    tekst = re.sub(r"\s+", " ", (command or "").strip()).rstrip(" ?!.")
    return _AANLOOP.sub("", tekst)


def herken(command, vandaag=None):
    """``(soort, gegevens)`` of ``None``.

    soort: toevoegen (titel, Moment), lijst (dagen) of zoek (term).
    """

    vandaag = vandaag or date.today()
    tekst = _schoon(command)

    m = _LIJST.match(tekst)
    if m:
        rest = (m.group("rest") or m.group("rest2") or m.group("rest3") or "").lower()
        if re.search(r"\bvandaag\b", rest):
            return "lijst", 1
        if re.search(r"\bmorgen\b", rest):
            return "lijst", 2
        if re.search(r"\b(?:deze|komende)\s+week|\bde\s+komende\s+dagen\b", rest):
            return "lijst", WEEK_DAGEN
        return "lijst", STANDAARD_DAGEN

    if _ALLEEN_TOEVOEGEN.match(tekst):
        # "Zet een deadline" zonder meer: JARVIS vraagt waarvoor en wanneer.
        return "toevoegen", ("", tijd.lees_moment("", vandaag))

    m = _TOEVOEGEN.match(tekst)
    if m and not tekst.lower().startswith(("deadlines", "deadline van", "deadline voor de")):
        rest = m.group("rest").strip()
        moment = tijd.lees_moment(rest, vandaag)
        titel = moment.rest(rest)
        titel = re.sub(r"\s+(?:op|voor|vóór|uiterlijk|tot)$", "", titel, flags=re.IGNORECASE)
        titel = re.sub(r"^(?:voor\s+|van\s+|het\s+|de\s+|mijn\s+)+", "", titel, flags=re.IGNORECASE).strip(" ,.:")
        return "toevoegen", (titel[:1].upper() + titel[1:], moment)

    if "deadline" in tekst.lower() or re.search(r"\b(af|inleveren|ingeleverd|klaar)\b", tekst.lower()):
        m = _ZOEK.match(tekst)
        if m and m.group("wat").strip():
            return "zoek", m.group("wat").strip()
    return None


# -----------------------------------------------------------------
# Antwoorden
# -----------------------------------------------------------------

def komende(klant, nu, dagen):
    """Deadlines vanaf vandaag, de komende ``dagen`` dagen, op datum."""

    van = datetime.combine(nu.date(), datetime.min.time())
    lijst = [a for a in klant.afspraken(van, van + timedelta(days=dagen)) if is_deadline(a)]
    return sorted(lijst, key=lambda a: (_dag(a), a["start"] if isinstance(a["start"], datetime) else
                                        datetime.combine(a["start"], datetime.min.time())))


def lijst_antwoord(klant, nu, dagen):
    lijst = komende(klant, nu, dagen)
    periode = {1: "vandaag", 2: "vandaag en morgen", WEEK_DAGEN: "deze week"}.get(dagen, f"de komende {dagen} dagen")
    if not lijst:
        return f"Geen deadlines {periode}, sir."
    delen = [f"{naam(a)} ({_wanneer(a, nu.date())})" for a in lijst]
    kop = "1 deadline" if len(lijst) == 1 else f"{len(lijst)} deadlines"
    return f"U heeft {periode} {kop}: " + ", ".join(delen) + "."


def zoek_antwoord(klant, term, nu):
    term = term.lower()
    for a in komende(klant, nu, 60):
        if term in naam(a).lower():
            return f"{naam(a)[:1].upper() + naam(a)[1:]} moet {_wanneer(a, nu.date())} af, sir."
    return None


def _titel(tekst):
    tekst = re.sub(r"^(?:voor\s+|van\s+|het\s+|de\s+|mijn\s+)+", "", str(tekst).strip(), flags=re.IGNORECASE)
    return tekst[:1].upper() + tekst[1:]


def _deadline_tijden(moment, nu):
    start, eind, hele_dag = tijd.afspraak_tijden(moment, nu)
    if not hele_dag:
        eind = start + DUUR_MET_TIJD
    return start, eind, hele_dag


def _vraag_deadline(titel, start, eind, hele_dag, nu):
    from core import icloud_agenda

    return icloud_agenda.vraag_toevoegen(
        PREFIX + titel, start, eind, hele_dag, vandaag=nu.date(),
        soort="Deadline", tonen=titel.lower(),
    )


def probeer_commando(command, klant_fn=None, nu=None):
    """``None`` als het geen deadline-opdracht is, anders het antwoord."""

    from core import icloud_agenda

    nu = nu or datetime.now()
    herkend = herken(command, nu.date())
    if herkend is None:
        return None
    soort, gegevens = herkend
    if not icloud_agenda.is_ingesteld():
        return None if soort == "zoek" else icloud_agenda.NIET_INGESTELD
    try:
        if soort == "toevoegen":
            from core import vervolg

            titel, moment = gegevens
            heeft_moment = moment.datum is not None or moment.begin is not None
            if not titel and heeft_moment:
                # "Deadline vrijdag" -> "Waarvoor?" -> "verslag" (Fase 27, M4).
                start, eind, hele_dag = _deadline_tijden(moment, nu)
                return vervolg.zet(
                    "Waarvoor is de deadline, sir?",
                    verwerk=lambda wat: _vraag_deadline(_titel(wat), start, eind, hele_dag, nu),
                    controle=vervolg.ZIN, inhoud=True,
                )
            if not titel:
                return vervolg.zet(
                    "Waarvoor is de deadline, en wanneer moet het af, sir?",
                    sjabloon="zet een deadline: {antwoord}", controle=vervolg.ZIN, inhoud=True,
                )
            if not heeft_moment:
                # "Zet een deadline verslag" -> "Wanneer?" -> "morgen om 10 uur".
                return vervolg.zet(
                    f"Wanneer moet {titel.lower()} af, sir?",
                    sjabloon=f"zet een deadline: {titel} {{antwoord}}", controle=vervolg.MOMENT,
                )
            start, eind, hele_dag = _deadline_tijden(moment, nu)
            return _vraag_deadline(titel, start, eind, hele_dag, nu)
        klant = (klant_fn or icloud_agenda.AgendaKlant)()
        if soort == "lijst":
            return lijst_antwoord(klant, nu, gegevens)
        return zoek_antwoord(klant, gegevens, nu)
    except koppelingen.KoppelFout as fout:
        logger.warning("Deadlines: %s", fout)
        return f"Ik kon de agenda niet lezen: {fout}"


# -----------------------------------------------------------------
# Paneel Vandaag
# -----------------------------------------------------------------

def paneel_deel(nu, klant_fn=None, ingesteld_fn=None):
    """Deadlines van vandaag en de komende dagen, voor het paneel Vandaag."""

    from core import icloud_agenda

    if not (ingesteld_fn or icloud_agenda.is_ingesteld)():
        return {"status": "niet_ingesteld", "deadlines": []}
    lijst = komende((klant_fn or icloud_agenda.AgendaKlant)(), nu, PANEEL_DAGEN)
    return {
        "status": "ok",
        "deadlines": [
            {
                "titel": naam(a)[:60],
                "wanneer": _wanneer(a, nu.date()),
                "dagen": (_dag(a) - nu.date()).days,
            }
            for a in lijst[:MAX_PANEEL]
        ],
        "meer": max(0, len(lijst) - MAX_PANEEL),
    }


# -----------------------------------------------------------------
# Herinneringen
# -----------------------------------------------------------------

def _sleutel(afspraak, wanneer):
    return f"{afspraak.get('uid') or afspraak.get('titel')}|{_dag(afspraak).isoformat()}|{wanneer}"


def herinnering_tekst(afspraak, wanneer):
    wat = naam(afspraak)
    if wanneer == "avond":
        tijdstip = "" if afspraak.get("hele_dag") or not isinstance(afspraak["start"], datetime) \
            else f" om {tijd.klok(afspraak['start'])}"
        return f"Morgen{tijdstip} moet {wat} af, sir."
    if afspraak.get("hele_dag") or not isinstance(afspraak["start"], datetime):
        return f"Vandaag moet {wat} af, sir."
    return f"Vandaag om {tijd.klok(afspraak['start'])} moet {wat} af, sir."


class DeadlinePlanner:
    """Meldt een deadline de avond ervoor en de ochtend zelf."""

    def __init__(self, meld_fn=None, klant_fn=None, klok=None, herinnerd_pad=None,
                 avond_uur=AVOND_UUR, ochtend_uur=OCHTEND_UUR):
        self.meld_fn = meld_fn
        self.klant_fn = klant_fn
        self.klok = klok or datetime.now
        self.herinnerd_pad = herinnerd_pad or HERINNERD_FILE
        self.avond_uur = avond_uur
        self.ochtend_uur = ochtend_uur
        self._stop = threading.Event()
        self._thread = None
        self._fout_gemeld = False

    def _klant(self):
        if self.klant_fn is not None:
            return self.klant_fn()
        from core.icloud_agenda import AgendaKlant

        return AgendaKlant()

    def _gedaan(self):
        return dict((koppelingen.lees_json(self.herinnerd_pad) or {}).get("gedaan") or {})

    def stap(self):
        """Eén controle; geeft de verstuurde meldingen terug."""

        from core.icloud_agenda import is_ingesteld

        if not is_ingesteld():
            return []
        nu = self.klok()
        try:
            lijst = komende(self._klant(), nu, 2)
            self._fout_gemeld = False
        except koppelingen.KoppelFout as fout:
            if not self._fout_gemeld:
                logger.warning("Deadlines ophalen voor herinneringen mislukt: %s", fout)
                self._fout_gemeld = True
            return []

        gedaan = self._gedaan()
        verstuurd = []
        for a in lijst:
            dag = _dag(a)
            momenten = (
                ("avond", datetime.combine(dag - timedelta(days=1), datetime.min.time()).replace(hour=self.avond_uur)),
                ("ochtend", datetime.combine(dag, datetime.min.time()).replace(hour=self.ochtend_uur)),
            )
            for wanneer, moment in momenten:
                sleutel = _sleutel(a, wanneer)
                if sleutel in gedaan or nu < moment:
                    continue
                if wanneer == "avond" and nu.date() >= dag:
                    continue  # te laat voor "morgen"; de ochtendmelding volgt
                if isinstance(a["start"], datetime) and nu >= a["start"]:
                    continue  # al voorbij
                gedaan[sleutel] = dag.isoformat()
                tekst = herinnering_tekst(a, wanneer)
                if self.meld_fn is not None:
                    try:
                        # Gewone systeemmelding: wacht 's nachts en in de stille modus.
                        self.meld_fn(tekst, bron="deadline")
                    except Exception:
                        logger.debug("Kon de deadlineherinnering niet versturen.", exc_info=True)
                verstuurd.append(tekst)
        if verstuurd:
            grens = (nu.date() - timedelta(days=2)).isoformat()
            koppelingen.schrijf_json(self.herinnerd_pad,
                                     {"gedaan": {k: v for k, v in gedaan.items() if v >= grens}})
        return verstuurd

    def _lus(self):
        while not self._stop.wait(60):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout in de deadlineherinneringen.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-deadlines", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
