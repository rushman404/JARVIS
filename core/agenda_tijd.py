"""Nederlandse datums en tijden uit gesproken tekst (Fase 23, M4).

Voor de agenda: "morgen om half drie", "vrijdag van 14 tot 15 uur",
"op 3 november om 10:00", "volgende week dinsdag om kwart over negen".

Alles werkt met "lokale" naïeve datetimes (de tijd van deze pc). Er wordt
nooit iets geraden dat niet in de zin staat: geen datum of tijd → ``None``.
De agenda leest het voorstel altijd eerst voor, dus een verkeerd begrepen
tijd wordt nooit zomaar opgeslagen.
"""

import re
from datetime import date, datetime, timedelta

DAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = {
    "januari": 1, "jan": 1, "februari": 2, "feb": 2, "maart": 3, "mrt": 3, "april": 4, "apr": 4,
    "mei": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "augustus": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
MAAND_NAMEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
               "september", "oktober", "november", "december"]
GETALLEN = {
    "een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7,
    "acht": 8, "negen": 9, "tien": 10, "elf": 11, "twaalf": 12,
}
STANDAARD_DUUR = timedelta(hours=1)

_GETAL = r"(?:\d{1,2}|" + "|".join(sorted(GETALLEN, key=len, reverse=True)) + r")"
_DAG = "|".join(DAGEN)
_MAAND = "|".join(sorted(MAANDEN, key=len, reverse=True))
_DAGDEEL = r"(?:\s+(?P<deel>'?s\s*ochtends|'?s\s*morgens|'?s\s*middags|'?s\s*avonds|'?s\s*nachts|"\
           r"in\s+de\s+ochtend|in\s+de\s+middag|in\s+de\s+avond|ochtend|middag|avond))?"
# Een los getal is alleen een tijd na "om", "van", "tot" enz., en niet als er
# ":30" of "uur" achter staat (dat pakken de andere vormen).
_LOS = r"(?![:.]\d)(?!\s*uur\b)(?!\s*(?:minuten|min|kwartier|dagen|weken|keer|personen)\b)"


def _getal(woord):
    woord = (woord or "").lower()
    return int(woord) if woord.isdigit() else GETALLEN.get(woord)


# -----------------------------------------------------------------
# Datum
# -----------------------------------------------------------------

_DATUM = re.compile(
    r"\b(?P<rel>vandaag|morgen|overmorgen)\b"
    r"|\b(?:(?P<volgende>volgende\s+week|volgende|aanstaande|komende)\s+)?(?P<dag>" + _DAG + r")\b"
    r"|\b(?P<d1>\d{1,2})(?:e|ste|de)?\s+(?P<maand>" + _MAAND + r")\b(?:\s+(?P<j1>\d{4}))?"
    r"|\b(?P<d2>\d{1,2})[-/](?P<m2>\d{1,2})(?:[-/](?P<j2>\d{2,4}))?\b",
    re.IGNORECASE,
)


def vind_datum(tekst, vandaag=None):
    """``(date, (begin, eind))`` van de eerste datum in de tekst, of ``None``."""

    vandaag = vandaag or date.today()
    for m in _DATUM.finditer(tekst or ""):
        datum = _datum_uit(m, vandaag)
        if datum is not None:
            # "op" of "voor" vlak ervoor hoort bij de datum.
            begin = m.start()
            voor = re.search(r"(?:\b(?:op|voor|aanstaande)\s+)$", tekst[:begin], re.IGNORECASE)
            if voor and not m.group("volgende"):
                begin = voor.start()
            return datum, (begin, m.end())
    return None


def _datum_uit(m, vandaag):
    rel = (m.group("rel") or "").lower()
    if rel:
        return vandaag + timedelta(days={"vandaag": 0, "morgen": 1, "overmorgen": 2}[rel])
    if m.group("dag"):
        doel = DAGEN.index(m.group("dag").lower())
        verschil = (doel - vandaag.weekday()) % 7
        volgende = (m.group("volgende") or "").lower()
        if volgende.startswith("volgende week"):
            # De dag in de week ná deze week.
            maandag = vandaag - timedelta(days=vandaag.weekday()) + timedelta(days=7)
            return maandag + timedelta(days=doel)
        if volgende and verschil == 0:
            verschil = 7
        return vandaag + timedelta(days=verschil)
    try:
        if m.group("maand"):
            dag, maand, jaar = int(m.group("d1")), MAANDEN[m.group("maand").lower()], m.group("j1")
        else:
            dag, maand, jaar = int(m.group("d2")), int(m.group("m2")), m.group("j2")
        if jaar:
            jaar = int(jaar)
            jaar = jaar + 2000 if jaar < 100 else jaar
            return date(jaar, maand, dag)
        kandidaat = date(vandaag.year, maand, dag)
        # Zonder jaar: een datum die al voorbij is, is volgend jaar.
        return kandidaat if kandidaat >= vandaag else date(vandaag.year + 1, maand, dag)
    except (ValueError, KeyError):
        return None


# -----------------------------------------------------------------
# Tijd
# -----------------------------------------------------------------

_TIJD = re.compile(
    r"(?P<kv>kwart\s+(?P<kvr>over|voor)\s+)?(?P<half>half\s+)(?P<hh>" + _GETAL + r")\b" + _DAGDEEL
    + r"|kwart\s+(?P<kr>over|voor)\s+(?P<kh>" + _GETAL + r")\b" + _DAGDEEL.replace("deel", "deel2")
    + r"|\b(?P<u>\d{1,2})[:.](?P<m>\d{2})\b(?:\s*uur)?" + _DAGDEEL.replace("deel", "deel3")
    + r"|\b(?P<uu>" + _GETAL + r")\s+uur(?:\s+(?P<um>\d{1,2}))?\b" + _DAGDEEL.replace("deel", "deel4")
    + r"|\b(?:om|van|vanaf|tot|tussen)\s+(?P<om>" + _GETAL + r")\b" + _LOS
    + _DAGDEEL.replace("deel", "deel5"),
    re.IGNORECASE,
)


def _dagdeel(m):
    for naam in ("deel", "deel2", "deel3", "deel4", "deel5"):
        if m.group(naam):
            return m.group(naam).lower()
    return ""


def _pas_dagdeel_toe(uur, deel, expliciet_24):
    if "middag" in deel or "avond" in deel:
        return uur + 12 if uur < 12 else uur
    if "nacht" in deel:
        return 0 if uur == 12 else uur
    if "ochtend" in deel or "morgens" in deel:
        return 0 if uur == 12 else uur
    if not expliciet_24 and 1 <= uur <= 6:
        # "om 3 uur" voor een afspraak is bijna altijd 's middags.
        return uur + 12
    return uur


def _tijd_uit(m):
    deel = _dagdeel(m)
    if m.group("half"):
        uur = _getal(m.group("hh"))
        if uur is None:
            return None
        minuut = 30
        if m.group("kv"):
            minuut = 45 if m.group("kvr").lower() == "over" else 15
        uur = (uur - 1) % 12 or 12
        return _pas_dagdeel_toe(uur, deel, False), minuut
    if m.group("kh"):
        uur = _getal(m.group("kh"))
        if uur is None:
            return None
        if m.group("kr").lower() == "over":
            return _pas_dagdeel_toe(uur, deel, False), 15
        uur = (uur - 1) % 12 or 12
        return _pas_dagdeel_toe(uur, deel, False), 45
    if m.group("u"):
        uur, minuut = int(m.group("u")), int(m.group("m"))
        return _pas_dagdeel_toe(uur, deel, uur >= 13 or m.group("u").startswith("0")), minuut
    if m.group("uu"):
        uur = _getal(m.group("uu"))
        minuut = int(m.group("um") or 0)
        if uur is None:
            return None
        return _pas_dagdeel_toe(uur, deel, uur >= 13), minuut
    uur = _getal(m.group("om"))
    if uur is None:
        return None
    return _pas_dagdeel_toe(uur, deel, uur >= 13), 0


def vind_tijden(tekst):
    """Alle kloktijden in de tekst: lijst van ``((uur, minuut), (begin, eind))``."""

    uit = []
    for m in _TIJD.finditer(tekst or ""):
        tijd = _tijd_uit(m)
        if tijd is None:
            continue
        uur, minuut = tijd
        if 0 <= uur <= 23 and 0 <= minuut <= 59:
            uit.append(((uur, minuut), (m.start(), m.end())))
    return uit


# -----------------------------------------------------------------
# Samen: een moment of een afspraak
# -----------------------------------------------------------------

_HELE_DAG = re.compile(r"\b(?:de\s+)?hele\s+dag\b", re.IGNORECASE)
_TUSSENWOORD = re.compile(r"\b(?:om|van|tot|vanaf|tussen|en)\s*$", re.IGNORECASE)


class Moment:
    """Wat er uit een zin kwam: datum, begin- en eindtijd en de gebruikte stukken."""

    def __init__(self, datum=None, begin=None, eind=None, hele_dag=False, stukken=()):
        self.datum = datum
        self.begin = begin          # (uur, minuut) of None
        self.eind = eind            # (uur, minuut) of None
        self.hele_dag = hele_dag
        self.stukken = list(stukken)

    def leeg(self):
        return self.datum is None and self.begin is None and not self.hele_dag

    def rest(self, tekst):
        """De tekst zonder de datum- en tijdstukken (voor de titel)."""

        delen, vorige = [], 0
        for begin, eind in sorted(self.stukken):
            if begin < vorige:
                continue
            delen.append(tekst[vorige:begin])
            vorige = eind
        delen.append(tekst[vorige:])
        schoon = []
        for deel in delen:
            schoon.append(_TUSSENWOORD.sub("", deel))
        return re.sub(r"\s+", " ", " ".join(schoon)).strip(" ,.-:")


def lees_moment(tekst, vandaag=None):
    """Datum en tijden uit een zin (zie :class:`Moment`)."""

    stukken = []
    datum = None
    gevonden = vind_datum(tekst, vandaag)
    if gevonden:
        datum, stuk = gevonden
        stukken.append(stuk)
    hele_dag = False
    m = _HELE_DAG.search(tekst or "")
    if m:
        hele_dag = True
        stukken.append((m.start(), m.end()))
    tijden = [t for t in vind_tijden(tekst) if not any(b <= t[1][0] < e for b, e in stukken)]
    begin = eind = None
    if tijden and not hele_dag:
        begin = tijden[0][0]
        stukken.append(_met_voorzetsel(tekst, tijden[0][1]))
        if len(tijden) > 1:
            eind = tijden[1][0]
            stukken.append(_met_voorzetsel(tekst, tijden[1][1]))
            # "van 2 tot 4": als begin al 's middags is, eind ook.
            if eind < begin and eind[0] + 12 <= 23:
                eind = (eind[0] + 12, eind[1])
    return Moment(datum, begin, eind, hele_dag, stukken)


def _met_voorzetsel(tekst, stuk):
    begin, eind = stuk
    voor = re.search(r"\b(?:om|van|vanaf|tot|tussen|en)\s+$", tekst[:begin], re.IGNORECASE)
    return (voor.start() if voor else begin, eind)


def afspraak_tijden(moment, nu=None):
    """``(start, eind, hele_dag)`` voor een nieuwe afspraak, of ``None``.

    Alleen een tijd: vandaag als die nog komt, anders morgen. Alleen een
    datum: een afspraak voor de hele dag.
    """

    nu = nu or datetime.now()
    if moment.leeg():
        return None
    datum = moment.datum
    if moment.hele_dag or moment.begin is None:
        datum = datum or nu.date()
        return datetime.combine(datum, datetime.min.time()), None, True
    if datum is None:
        kandidaat = datetime.combine(nu.date(), datetime.min.time()).replace(
            hour=moment.begin[0], minute=moment.begin[1])
        datum = nu.date() if kandidaat > nu else nu.date() + timedelta(days=1)
    start = datetime.combine(datum, datetime.min.time()).replace(hour=moment.begin[0], minute=moment.begin[1])
    if moment.eind:
        eind = start.replace(hour=moment.eind[0], minute=moment.eind[1])
        if eind <= start:
            eind = start + STANDAARD_DUUR
    else:
        eind = start + STANDAARD_DUUR
    return start, eind, False


# -----------------------------------------------------------------
# Uitspreken
# -----------------------------------------------------------------

def dag_woord(datum, vandaag=None):
    """"vandaag", "morgen", "vrijdag" (deze week) of "dinsdag 3 november"."""

    vandaag = vandaag or date.today()
    verschil = (datum - vandaag).days
    if verschil == 0:
        return "vandaag"
    if verschil == 1:
        return "morgen"
    if verschil == 2:
        return "overmorgen"
    if verschil == -1:
        return "gisteren"
    return f"{DAGEN[datum.weekday()]} {datum.day} {MAAND_NAMEN[datum.month - 1]}"


def klok(tijd):
    return tijd.strftime("%H:%M")
