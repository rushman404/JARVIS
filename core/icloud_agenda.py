"""iCloud-agenda via CalDAV (Fase 23, M4).

* **Instellen:** een app-specifiek wachtwoord van Apple in ``.env``
  (``ICLOUD_GEBRUIKER`` en ``ICLOUD_APP_WACHTWOORD``), daarna
  ``python scripts/agenda_koppelen.py`` om te testen (zie ``docs/agenda.md``).
* **Vragen:** "wat staat er vandaag/morgen/vrijdag op de planning?", "wat
  heb ik deze week?", "wanneer is mijn volgende afspraak?", "wanneer is de
  tandarts?".
* **Wijzigen (na ja):** "zet tandarts morgen om 14 uur in mijn agenda",
  "verplaats de tandarts naar vrijdag om 10 uur". JARVIS leest het voorstel
  voor en doet het pas na een expliciete ja (stem of dashboard).

Zonder extra bibliotheken: een paar CalDAV-verzoeken (PROPFIND, REPORT, GET,
PUT) en een kleine iCalendar-lezer. iCloud rekent terugkerende afspraken
zelf uit (``expand``) en geeft die tijden in UTC; deze pc rekent ze om naar
de lokale tijd. Het wachtwoord komt nooit in de log, een antwoord of een
bestand buiten ``.env``.
"""

import logging
import os
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

from core import agenda_tijd as tijd
from core import koppelingen

logger = logging.getLogger("jarvis.agenda")

HTTP_TIMEOUT = 15
STATUS_FILE = os.path.join(koppelingen.MAP, "icloud_agenda.json")
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
TOEVOEG_KIND = "agenda_toevoegen"
VERPLAATS_KIND = "agenda_verplaatsen"
VRAAG_TTL = 120
ZOEK_DAGEN = 90
PROBLEEM_WACHTWOORD = "wachtwoord geweigerd (maak een nieuw app-specifiek wachtwoord)"

NIET_INGESTELD = ("De iCloud-agenda is nog niet ingesteld, sir. Zet ICLOUD_GEBRUIKER en "
                  "ICLOUD_APP_WACHTWOORD in de .env op de laptop; de uitleg staat in docs/agenda.md.")


def _config():
    import config

    return config


class AgendaFout(koppelingen.KoppelFout):
    pass


# -----------------------------------------------------------------
# Status (zonder wachtwoord)
# -----------------------------------------------------------------

def _status(pad=None):
    return koppelingen.lees_json(pad or STATUS_FILE) or {}


def _bewaar_status(data, pad=None):
    koppelingen.schrijf_json(pad or STATUS_FILE, data)


def is_ingesteld():
    cfg = _config()
    return bool(cfg.ICLOUD_GEBRUIKER and cfg.ICLOUD_APP_WACHTWOORD)


def koppeling_status():
    """Voor :func:`core.koppelingen.overzicht`."""

    ingesteld = is_ingesteld()
    return {
        "id": "icloud_agenda",
        "naam": "iCloud-agenda",
        "gekoppeld": ingesteld,
        "rechten": ["lezen", "toevoegen"] if ingesteld else [],
        "probleem": _status().get("probleem") if ingesteld else None,
    }


# -----------------------------------------------------------------
# iCalendar lezen en schrijven
# -----------------------------------------------------------------

def _ontvouw(ics):
    return re.sub(r"\r?\n[ \t]", "", ics or "").splitlines()


def _eigenschap(regel):
    """``(naam, {param: waarde}, waarde)`` van één iCalendar-regel."""

    kop, _, waarde = regel.partition(":")
    delen = kop.split(";")
    params = {}
    for p in delen[1:]:
        sleutel, _, w = p.partition("=")
        params[sleutel.upper()] = w.strip('"')
    return delen[0].upper(), params, waarde


def _tekst(waarde):
    return (waarde.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\")).strip()


def _tijdstip(waarde, params):
    """Een DATE of DATE-TIME als lokale tijd: ``(datetime_of_date, hele_dag)``."""

    waarde = waarde.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", waarde):
        return datetime.strptime(waarde[:8], "%Y%m%d").date(), True
    moment = datetime.strptime(waarde[:15], "%Y%m%dT%H%M%S")
    if waarde.endswith("Z"):
        # UTC (zo geeft iCloud uitgerekende afspraken): naar de tijd van deze pc.
        moment = moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    # Met TZID: zonder tijdzonedatabase nemen we aan dat het de lokale tijd is.
    return moment, False


def _duur(waarde):
    m = re.fullmatch(r"(-)?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", waarde.strip())
    if not m:
        return None
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def lees_ics(ics):
    """De VEVENT's uit een iCalendar-tekst als lijst van dicts."""

    afspraken, huidig, diepte = [], None, 0
    for regel in _ontvouw(ics):
        naam, params, waarde = _eigenschap(regel)
        if naam == "BEGIN":
            if waarde.upper() == "VEVENT" and huidig is None:
                huidig, diepte = {"exdate": []}, 0
            elif huidig is not None:
                diepte += 1  # bijv. een VALARM binnen de afspraak
            continue
        if naam == "END":
            if huidig is not None and diepte:
                diepte -= 1
            elif huidig is not None and waarde.upper() == "VEVENT":
                afspraken.append(huidig)
                huidig = None
            continue
        if huidig is None or diepte:
            continue
        try:
            if naam == "SUMMARY":
                huidig["titel"] = _tekst(waarde)
            elif naam == "LOCATION":
                huidig["plaats"] = _tekst(waarde)
            elif naam == "UID":
                huidig["uid"] = waarde.strip()
            elif naam == "STATUS":
                huidig["status"] = waarde.strip().upper()
            elif naam == "DTSTART":
                huidig["start"], huidig["hele_dag"] = _tijdstip(waarde, params)
            elif naam == "DTEND":
                huidig["eind"], _ = _tijdstip(waarde, params)
            elif naam == "DURATION":
                huidig["duur"] = _duur(waarde)
            elif naam == "RRULE":
                huidig["rrule"] = waarde.strip()
            elif naam == "RECURRENCE-ID":
                huidig["herhaling"] = True
            elif naam == "EXDATE":
                for w in waarde.split(","):
                    huidig["exdate"].append(_tijdstip(w, params)[0])
        except ValueError:
            logger.debug("Onleesbare agendaregel overgeslagen: %s", naam)
    uit = []
    for a in afspraken:
        if "start" not in a or a.get("status") == "CANCELLED":
            continue
        if "eind" not in a:
            if a.get("duur") is not None:
                a["eind"] = a["start"] + a["duur"]
            else:
                a["eind"] = a["start"] + (timedelta(days=1) if a["hele_dag"] else timedelta(0))
        a.setdefault("titel", "(zonder titel)")
        a.setdefault("plaats", "")
        uit.append(a)
    return uit


_DAG_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _herhaal(afspraak, van, tot):
    """Eenvoudige terugval als de server niet zelf uitrekent (``expand``).

    Ondersteunt FREQ=DAILY/WEEKLY/MONTHLY/YEARLY met INTERVAL, COUNT, UNTIL,
    BYDAY (alleen wekelijks) en EXDATE. Andere regels: alleen de eerste keer.
    """

    regels = dict(d.split("=", 1) for d in afspraak["rrule"].split(";") if "=" in d)
    freq = regels.get("FREQ")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [afspraak]
    stap = max(1, int(regels.get("INTERVAL", "1") or 1))
    aantal = int(regels["COUNT"]) if regels.get("COUNT", "").isdigit() else None
    tot_regel = None
    if regels.get("UNTIL"):
        try:
            tot_regel, _ = _tijdstip(regels["UNTIL"], {})
        except ValueError:
            tot_regel = None
    start, duur = afspraak["start"], afspraak["eind"] - afspraak["start"]
    dagen = sorted(_DAG_CODES[c[-2:]] for c in regels.get("BYDAY", "").split(",") if c[-2:] in _DAG_CODES)

    def kandidaten():
        n = 0
        while n < 1500:
            if freq == "DAILY":
                yield start + timedelta(days=n * stap)
            elif freq == "WEEKLY":
                week = start - timedelta(days=start.weekday()) + timedelta(weeks=n * stap)
                for d in dagen or [start.weekday()]:
                    yield week + timedelta(days=d)
            elif freq == "MONTHLY":
                maand = start.month - 1 + n * stap
                try:
                    yield start.replace(year=start.year + maand // 12, month=maand % 12 + 1)
                except ValueError:
                    pass
            else:
                try:
                    yield start.replace(year=start.year + n * stap)
                except ValueError:
                    pass
            n += 1

    uit, geteld = [], 0
    for moment in kandidaten():
        if moment < start:
            continue
        if tot_regel is not None and _als_datetime(moment) > _als_datetime(tot_regel):
            break
        geteld += 1
        if aantal is not None and geteld > aantal:
            break
        if _als_datetime(moment) >= _als_datetime(tot):
            break
        if moment in afspraak["exdate"]:
            continue
        if _als_datetime(moment + duur) > _als_datetime(van):
            kopie = dict(afspraak, start=moment, eind=moment + duur, herhaling=True)
            uit.append(kopie)
    return uit


def _als_datetime(waarde):
    return waarde if isinstance(waarde, datetime) else datetime.combine(waarde, datetime.min.time())


def _utc(moment):
    """Lokale (naïeve) tijd → iCalendar-UTC ("20261029T130000Z")."""

    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_tekst(waarde):
    waarde = re.sub(r"[\x00-\x1f\x7f]+", " ", str(waarde or ""))
    return waarde.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")


def maak_ics(uid, titel, start, eind, hele_dag, nu=None):
    nu = nu or datetime.now()
    regels = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//Agenda//NL", "BEGIN:VEVENT",
              f"UID:{uid}", f"DTSTAMP:{_utc(nu)}", f"SUMMARY:{_ics_tekst(titel)}"]
    if hele_dag:
        dag = start.date() if isinstance(start, datetime) else start
        regels += [f"DTSTART;VALUE=DATE:{dag:%Y%m%d}", f"DTEND;VALUE=DATE:{dag + timedelta(days=1):%Y%m%d}"]
    else:
        regels += [f"DTSTART:{_utc(start)}", f"DTEND:{_utc(eind)}"]
    regels += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(regels) + "\r\n"


def verzet_ics(ics, start, eind, nu=None):
    """Zelfde afspraak, nieuwe tijden (alleen niet-terugkerende afspraken)."""

    nu = nu or datetime.now()
    regels, uit, in_event, diepte, sequence = _ontvouw(ics), [], False, 0, 0
    for regel in regels:
        naam, _, waarde = _eigenschap(regel)
        if naam == "BEGIN" and waarde.upper() == "VEVENT" and not in_event:
            in_event, diepte = True, 0
        elif naam == "BEGIN" and in_event:
            diepte += 1
        elif naam == "END" and in_event and diepte:
            diepte -= 1
        elif naam == "END" and in_event and waarde.upper() == "VEVENT":
            uit += [f"DTSTART:{_utc(start)}", f"DTEND:{_utc(eind)}", f"DTSTAMP:{_utc(nu)}",
                    f"SEQUENCE:{sequence + 1}"]
            in_event = False
        elif in_event and not diepte:
            if naam in ("RRULE", "RECURRENCE-ID"):
                raise AgendaFout("Dit is een terugkerende afspraak; verplaats die in de Agenda-app.")
            if naam in ("DTSTART", "DTEND", "DURATION", "DTSTAMP"):
                continue
            if naam == "SEQUENCE":
                sequence = int(waarde) if waarde.strip().isdigit() else 0
                continue
        uit.append(regel)
    return "\r\n".join(uit) + "\r\n"


# -----------------------------------------------------------------
# CalDAV
# -----------------------------------------------------------------

_PROP_PRINCIPAL = ('<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>')
_PROP_HOME = ('<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
              '<c:calendar-home-set/></d:prop></d:propfind>')
_PROP_AGENDAS = ('<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
                 '<d:displayname/><d:resourcetype/><c:supported-calendar-component-set/>'
                 '</d:prop></d:propfind>')


def _query(van, tot):
    s, e = _utc(van), _utc(tot)
    return ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f'<d:prop><d:getetag/><c:calendar-data><c:expand start="{s}" end="{e}"/></c:calendar-data></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{s}" end="{e}"/></c:comp-filter></c:comp-filter></c:filter>'
            '</c:calendar-query>')


class AgendaKlant:
    """CalDAV-toegang tot de iCloud-agenda (Basic-auth met een app-wachtwoord)."""

    def __init__(self, gebruiker=None, wachtwoord=None, basis=None, http=None, status_pad=None):
        cfg = _config()
        self.gebruiker = cfg.ICLOUD_GEBRUIKER if gebruiker is None else gebruiker
        self.wachtwoord = cfg.ICLOUD_APP_WACHTWOORD if wachtwoord is None else wachtwoord
        self.basis = basis or cfg.ICLOUD_CALDAV_URL
        self.http = http
        self.status_pad = status_pad or STATUS_FILE

    def is_ingesteld(self):
        return bool(self.gebruiker and self.wachtwoord)

    # -- HTTP --------------------------------------------------------

    def _verzoek(self, methode, url, body=None, headers=None, ok=(200, 207)):
        http = self.http or koppelingen._requests()
        kop = {"Content-Type": "application/xml; charset=utf-8"}
        kop.update(headers or {})
        for _ in range(4):
            r = koppelingen.verzoek(http.request, methode, url, data=body.encode("utf-8") if body else None,
                                    headers=kop, auth=(self.gebruiker, self.wachtwoord),
                                    timeout=HTTP_TIMEOUT, allow_redirects=False, dienst="iCloud")
            if r.status_code in (301, 302, 307, 308) and r.headers.get("Location"):
                # Zelf volgen: requests maakt van een PROPFIND na 302 een GET.
                url = urljoin(url, r.headers["Location"])
                continue
            break
        if r.status_code == 401:
            status = _status(self.status_pad)
            status["probleem"] = PROBLEEM_WACHTWOORD
            _bewaar_status(status, self.status_pad)
            raise AgendaFout("iCloud weigerde het wachtwoord; maak een nieuw app-specifiek wachtwoord.", 401)
        if r.status_code == 412:
            raise AgendaFout("De afspraak is intussen ergens anders gewijzigd; probeer het opnieuw.", 412)
        if r.status_code not in ok:
            raise AgendaFout(f"iCloud antwoordde met HTTP {r.status_code}.", r.status_code)
        return r, url

    def _multistatus(self, methode, url, body, diepte):
        r, url = self._verzoek(methode, url, body, {"Depth": str(diepte)})
        try:
            return ET.fromstring(r.content), url
        except ET.ParseError:
            raise AgendaFout("iCloud gaf een onleesbaar antwoord.") from None

    # -- ontdekken ---------------------------------------------------

    def agendas(self, vers=False):
        """``[{"url", "naam"}]`` van de agenda's met afspraken (gecachet)."""

        status = _status(self.status_pad)
        if status.get("agendas") and not vers:
            return status["agendas"]
        boom, url = self._multistatus("PROPFIND", self.basis, _PROP_PRINCIPAL, 0)
        href = boom.find(".//d:current-user-principal/d:href", NS)
        if href is None or not href.text:
            raise AgendaFout("iCloud gaf geen account terug; klopt ICLOUD_GEBRUIKER?")
        principal = urljoin(url, href.text.strip())
        boom, url = self._multistatus("PROPFIND", principal, _PROP_HOME, 0)
        href = boom.find(".//c:calendar-home-set/d:href", NS)
        if href is None or not href.text:
            raise AgendaFout("iCloud gaf geen agenda-map terug.")
        thuis = urljoin(url, href.text.strip())
        boom, url = self._multistatus("PROPFIND", thuis, _PROP_AGENDAS, 1)
        lijst = []
        for antwoord in boom.findall("d:response", NS):
            href = antwoord.find("d:href", NS)
            if href is None or antwoord.find(".//d:resourcetype/c:calendar", NS) is None:
                continue
            soorten = [c.get("name") for c in antwoord.findall(".//c:supported-calendar-component-set/c:comp", NS)]
            if soorten and "VEVENT" not in soorten:
                continue  # bijv. de herinneringen (VTODO)
            naam = antwoord.find(".//d:displayname", NS)
            lijst.append({"url": urljoin(url, href.text.strip()),
                          "naam": (naam.text or "").strip() if naam is not None else ""})
        if not lijst:
            raise AgendaFout("Er staan geen agenda's in dit iCloud-account.")
        status.update({"agendas": lijst, "probleem": None})
        _bewaar_status(status, self.status_pad)
        return lijst

    def schrijf_agenda(self):
        """De agenda waarin JARVIS nieuwe afspraken zet (ICLOUD_AGENDA of de eerste)."""

        lijst = self.agendas()
        wens = (_config().ICLOUD_AGENDA or "").strip().lower()
        if wens:
            for a in lijst:
                if a["naam"].lower() == wens:
                    return a
        return lijst[0]

    # -- lezen -------------------------------------------------------

    def afspraken(self, van, tot):
        """Alle afspraken die (deels) tussen ``van`` en ``tot`` vallen, gesorteerd."""

        uit = []
        for agenda in self.agendas():
            try:
                boom, url = self._multistatus("REPORT", agenda["url"], _query(van, tot), 1)
            except AgendaFout as fout:
                if fout.status == 404:
                    # Agenda verdwenen: de volgende keer opnieuw ontdekken.
                    _bewaar_status({}, self.status_pad)
                raise
            for antwoord in boom.findall("d:response", NS):
                href = antwoord.find("d:href", NS)
                data = antwoord.find(".//c:calendar-data", NS)
                etag = antwoord.find(".//d:getetag", NS)
                if data is None or not data.text:
                    continue
                for a in lees_ics(data.text):
                    lijst = _herhaal(a, van, tot) if a.get("rrule") else [a]
                    for kopie in lijst:
                        kopie.update({"href": urljoin(url, href.text.strip()) if href is not None else "",
                                      "etag": etag.text if etag is not None else "",
                                      "agenda": agenda["naam"],
                                      "herhaalt": bool(a.get("rrule") or a.get("herhaling"))})
                        s, e = _als_datetime(kopie["start"]), _als_datetime(kopie["eind"])
                        # Overlapt met de periode (een afspraak zonder duur: begint erin).
                        if (e > van and s < tot) or (s == e and van <= s < tot):
                            uit.append(kopie)
        uit.sort(key=lambda a: (_als_datetime(a["start"]), not a["hele_dag"], a["titel"]))
        return uit

    def lees_ruw(self, href):
        r, _ = self._verzoek("GET", href, ok=(200,))
        return r.text, r.headers.get("ETag", "")

    # -- schrijven ---------------------------------------------------

    def zet(self, href, ics, etag=None):
        kop = {"Content-Type": "text/calendar; charset=utf-8"}
        kop["If-Match" if etag else "If-None-Match"] = etag or "*"
        self._verzoek("PUT", href, ics, kop, ok=(200, 201, 204))

    def voeg_toe(self, titel, start, eind, hele_dag):
        agenda = self.schrijf_agenda()
        uid = f"{uuid.uuid4()}@jarvis"
        href = agenda["url"].rstrip("/") + f"/{uid}.ics"
        self.zet(href, maak_ics(uid, titel, start, eind, hele_dag))
        return agenda["naam"]

    def verplaats(self, afspraak, start, eind):
        ics, etag = self.lees_ruw(afspraak["href"])
        self.zet(afspraak["href"], verzet_ics(ics, start, eind), etag or afspraak.get("etag"))


# -----------------------------------------------------------------
# Antwoorden
# -----------------------------------------------------------------

def _dag_bereik(dag):
    van = datetime.combine(dag, datetime.min.time())
    return van, van + timedelta(days=1)


def _regel(a):
    plaats = f", in {a['plaats']}" if a.get("plaats") else ""
    if a["hele_dag"]:
        return _punt(f"Hele dag: {a['titel']}{plaats}")
    return _punt(f"{tijd.klok(a['start'])} tot {tijd.klok(a['eind'])}: {a['titel']}{plaats}")


def _punt(tekst):
    return tekst if tekst.endswith((".", "!", "?")) else tekst + "."


def op_dag(klant, dag, vandaag=None):
    vandaag = vandaag or date.today()
    van, tot = _dag_bereik(dag)
    lijst = klant.afspraken(van, tot)
    woord = tijd.dag_woord(dag, vandaag)
    if not lijst:
        return f"{woord.capitalize()} staat er niets in uw agenda, sir."
    kop = f"{woord.capitalize()} {'heeft u 1 afspraak' if len(lijst) == 1 else f'heeft u {len(lijst)} afspraken'}:"
    return "\n".join([kop] + [_regel(a) for a in lijst])


def deze_week(klant, vandaag=None):
    vandaag = vandaag or date.today()
    van = datetime.combine(vandaag, datetime.min.time())
    lijst = klant.afspraken(van, van + timedelta(days=7))
    if not lijst:
        return "De komende zeven dagen staat er niets in uw agenda, sir."
    regels, vorige = [], None
    for a in lijst:
        dag = a["start"].date() if isinstance(a["start"], datetime) else a["start"]
        dag = max(dag, vandaag)
        if dag != vorige:
            regels.append(tijd.dag_woord(dag, vandaag).capitalize() + ":")
            vorige = dag
        regels.append(_regel(a))
    return "\n".join(regels)


def _wanneer(a, nu):
    start = a["start"]
    dag = start.date() if isinstance(start, datetime) else start
    woord = tijd.dag_woord(dag, nu.date())
    return woord if a["hele_dag"] else f"{woord} om {tijd.klok(start)}"


def volgende(klant, nu=None):
    nu = nu or datetime.now()
    for a in klant.afspraken(nu, nu + timedelta(days=30)):
        if _als_datetime(a["start"]) >= nu or a["hele_dag"] and a["start"] > nu.date():
            plaats = f", in {a['plaats']}" if a.get("plaats") else ""
            return f"Uw volgende afspraak is {_wanneer(a, nu)}: {a['titel']}{plaats}."
    return "De komende 30 dagen staat er niets in uw agenda, sir."


def zoek(klant, term, nu=None, dagen=ZOEK_DAGEN):
    """De eerstvolgende afspraak met ``term`` in de titel (of None)."""

    nu = nu or datetime.now()
    term = term.lower().strip()
    for a in klant.afspraken(nu - timedelta(hours=1), nu + timedelta(days=dagen)):
        if term and term in a["titel"].lower():
            return a
    return None


# -----------------------------------------------------------------
# Wijzigen na ja
# -----------------------------------------------------------------

def _omschrijf(start, eind, hele_dag, vandaag):
    dag = start.date() if isinstance(start, datetime) else start
    woord = tijd.dag_woord(dag, vandaag)
    if woord in ("vandaag", "morgen", "overmorgen"):
        woord += f" ({tijd.DAGEN[dag.weekday()]} {dag.day} {tijd.MAAND_NAMEN[dag.month - 1]})"
    if hele_dag:
        return f"{woord}, de hele dag"
    return f"{woord} van {tijd.klok(start)} tot {tijd.klok(eind)}"


def vraag_toevoegen(titel, start, eind, hele_dag, vandaag=None, soort="Afspraak", tonen=None):
    """Zet de ja/nee-vraag klaar. ``soort`` en ``tonen`` (de naam in de vraag)
    zijn voor deadlines (Fase 26): "Deadline toevoegen: verslag, …"."""

    from core import confirmation

    vandaag = vandaag or date.today()
    vraag = (f"{soort} toevoegen: {tonen or titel}, {_omschrijf(start, eind, hele_dag, vandaag)}.\n"
             "Zal ik hem in uw agenda zetten?")
    confirmation.set_pending(TOEVOEG_KIND, {
        "afspraak": {"titel": titel, "start": start.isoformat(), "eind": eind.isoformat() if eind else None,
                     "hele_dag": hele_dag},
        "question": vraag, "action": f"{soort} toevoegen", "target": titel,
    }, ttl=VRAAG_TTL)
    return vraag


def vraag_verplaatsen(afspraak, start, eind, vandaag=None):
    from core import confirmation

    vandaag = vandaag or date.today()
    oud = _omschrijf(afspraak["start"], afspraak["eind"], False, vandaag)
    vraag = (f"{afspraak['titel']} verplaatsen?\nNu: {oud}.\n"
             f"Nieuw: {_omschrijf(start, eind, False, vandaag)}.\nZal ik hem verplaatsen?")
    confirmation.set_pending(VERPLAATS_KIND, {
        "afspraak": {"titel": afspraak["titel"], "href": afspraak["href"], "etag": afspraak.get("etag", ""),
                     "start": start.isoformat(), "eind": eind.isoformat()},
        "question": vraag, "action": "Afspraak verplaatsen", "target": afspraak["titel"],
    }, ttl=VRAAG_TTL)
    return vraag


def _audit(pending, tool, argumenten, resultaat, goedgekeurd, reden=None):
    try:
        from core.audit import log_audit

        log_audit(gehoord=pending.get("question", ""), handler="agenda", tool=tool, argumenten=argumenten,
                  risico="medium", resultaat=resultaat, goedgekeurd=goedgekeurd, reden=reden,
                  herkomst=pending.get("herkomst"))
    except Exception:
        logger.debug("Auditregel voor de agenda mislukte.", exc_info=True)


def _gegevens(pending):
    return pending.get("afspraak") or (pending.get("payload") or {}).get("afspraak")


def na_ja(pending, klant=None):
    a = _gegevens(pending)
    if not isinstance(a, dict) or not a.get("titel") or not a.get("start"):
        return "Ik weet niet meer welke afspraak het was, sir."
    klant = klant or AgendaKlant()
    start = datetime.fromisoformat(a["start"])
    eind = datetime.fromisoformat(a["eind"]) if a.get("eind") else None
    kind = pending.get("kind")
    args = {"titel": a["titel"], "start": a["start"]}
    try:
        if kind == VERPLAATS_KIND:
            klant.verplaats({"href": a["href"], "etag": a.get("etag")}, start, eind)
            _audit(pending, "agenda_verplaatsen", args, "verplaatst", True)
            return f"{a['titel']} is verplaatst, sir."
        naam = klant.voeg_toe(a["titel"], start, eind, a.get("hele_dag"))
    except koppelingen.KoppelFout as fout:
        _audit(pending, kind or "agenda", args, "mislukt", False, str(fout))
        return f"Dat lukte niet: {fout}"
    _audit(pending, "agenda_toevoegen", args, "toegevoegd", True)
    return f"{a['titel']} staat in uw agenda{f' ({naam})' if naam else ''}, sir."


def na_nee(pending):
    a = _gegevens(pending) or {}
    _audit(pending, pending.get("kind") or "agenda", {"titel": a.get("titel", "")}, "niet gedaan", False,
           "geweigerd door de gebruiker")
    if pending.get("kind") == VERPLAATS_KIND:
        return "Oké, de afspraak blijft staan zoals hij stond."
    return "Oké, ik zet hem er niet in."


# -----------------------------------------------------------------
# Spraakopdrachten
# -----------------------------------------------------------------

_LEZEN = re.compile(
    r"^(?:wat\s+(?:staat\s+er|heb\s+ik|is\s+er|zijn\s+mijn\s+afspraken|is\s+mijn\s+(?:planning|agenda))"
    r"|heb\s+ik|welke\s+afspraken\s+heb\s+ik|(?:mijn\s+)?(?:agenda|planning))\b(?P<rest>.*)$"
)
# Wat er na de vraag mag staan behalve de datum; al het andere = geen agendavraag.
_VULWOORDEN = re.compile(
    r"\b(?:op|in|de|het|mijn|voor|van|planning|agenda|afspraken?|gepland|ingepland|staan|staat|er|nog|iets|"
    r"allemaal|wat|ik|zoal|zoals)\b"
)
_WEEK = re.compile(r"\b(?:deze\s+week|de\s+komende\s+(?:dagen|week)|komende\s+week)\b")
_VOLGENDE = re.compile(
    r"^(?:wanneer|wat)\s+is\s+(?:mijn|de)\s+(?:volgende|eerstvolgende)\s+afspraak$|^(?:mijn\s+)?volgende\s+afspraak$"
)
_ZOEK = re.compile(
    r"^wanneer\s+(?:is|heb\s+ik|moet\s+ik\s+naar)\s+(?:de|het|mijn|een)?\s*(?:afspraak\s+(?:met|bij|van)\s+)?"
    r"(?P<wat>.+?)$"
)
_TOEVOEGEN = re.compile(
    r"^(?:zet|plan|voeg|maak|noteer)\s+(?:een\s+)?(?:afspraak\s+)?(?:voor\s+)?(?P<rest>.+?)\s+"
    r"(?:in|aan|toe\s+aan)\s+(?:mijn|de)\s+agenda(?:\s+toe)?(?P<rest2>.*)$"
    r"|^(?:maak|plan)\s+een\s+afspraak\s+(?:voor\s+|met\s+|bij\s+)?(?P<rest3>.+)$",
    re.IGNORECASE,
)
_VERPLAATS = re.compile(
    r"^(?:verplaats|verzet|schuif)\s+(?:de|mijn|het)?\s*(?:afspraak\s+(?:met|bij|van|voor)?\s*)?"
    r"(?P<wat>.+?)\s+naar\s+(?P<wanneer>.+)$",
    re.IGNORECASE,
)
_AANLOOP = re.compile(r"^(?:jarvis[, ]+)?(?:kun\s+je|kan\s+je|wil\s+je)\s+", re.IGNORECASE)


def _schoon(command):
    tekst = re.sub(r"\s+", " ", (command or "").strip())
    return _AANLOOP.sub("", tekst)


def herken(command, vandaag=None):
    """``(soort, gegevens)`` of ``None``.

    soort: dag (gegevens = date), week, volgende, zoek (term), toevoegen
    (Moment + titel) of verplaats (term + Moment).
    """

    vandaag = vandaag or date.today()
    origineel = _schoon(command).rstrip(" ?!.")
    tekst = origineel.lower()

    m = _VERPLAATS.match(origineel)
    if m:
        moment = tijd.lees_moment(m.group("wanneer"), vandaag)
        if not moment.leeg() and not moment.rest(m.group("wanneer")):
            return "verplaats", (m.group("wat").strip(), moment)
        return None
    m = _TOEVOEGEN.match(origineel)
    if m:
        rest = " ".join(x for x in (m.group("rest"), m.group("rest2"), m.group("rest3")) if x).strip()
        moment = tijd.lees_moment(rest, vandaag)
        titel = re.sub(r"^(?:een\s+afspraak\s+|afspraak\s+)?(?:voor\s+|met\s+|bij\s+)?(?:de\s+|het\s+)?", "",
                       moment.rest(rest), flags=re.IGNORECASE).strip(" ,.:")
        return "toevoegen", (titel[:1].upper() + titel[1:], moment)
    if _VOLGENDE.match(tekst):
        return "volgende", None
    m = _LEZEN.match(tekst)
    if m:
        rest = m.group("rest")
        if _WEEK.search(rest) and not _VULWOORDEN.sub("", _WEEK.sub("", rest)).strip():
            return "week", None
        gevonden = tijd.vind_datum(rest, vandaag)
        over = rest
        if gevonden:
            b, e = gevonden[1]
            over = rest[:b] + rest[e:]
        over = _VULWOORDEN.sub("", over).strip()
        agenda_woord = re.search(r"\b(?:planning|agenda|afspraken?|gepland)\b", tekst)
        if not over and (gevonden or agenda_woord):
            return "dag", gevonden[0] if gevonden else vandaag
        return None
    m = _ZOEK.match(tekst)
    if m and not tijd.vind_datum(m.group("wat"), vandaag):
        return "zoek", m.group("wat").strip()
    return None


def probeer_commando(command, klant_fn=None, nu=None):
    """``None`` als het geen agendavraag is, anders het gesproken antwoord."""

    nu = nu or datetime.now()
    soort = herken(command, nu.date())
    if soort is None:
        return None
    if soort[0] == "dag":
        from core.proactive_commands import _DAGSTART_PATROON

        if _DAGSTART_PATROON.search((command or "").lower()):
            # "Wat staat er vandaag (op de planning)?" is de dagstart (M5):
            # weer, afspraken met vertrektijd en belangrijke mail.
            return None
    soort, gegevens = soort
    if not is_ingesteld():
        # "Wanneer is pasen?" mag dan gewoon naar het taalmodel, en "wat staat
        # er vandaag?" naar de bestaande dagstart.
        return None if soort in ("zoek", "dag") else NIET_INGESTELD
    klant = (klant_fn or AgendaKlant)()
    try:
        if soort == "dag":
            return op_dag(klant, gegevens, nu.date())
        if soort == "week":
            return deze_week(klant, nu.date())
        if soort == "volgende":
            return volgende(klant, nu)
        if soort == "zoek":
            a = zoek(klant, gegevens, nu)
            if a is None:
                return None
            plaats = f", in {a['plaats']}" if a.get("plaats") else ""
            return f"{a['titel']} is {_wanneer(a, nu)}{plaats}."
        if soort == "toevoegen":
            from core import vervolg

            titel, moment = gegevens
            tijden = tijd.afspraak_tijden(moment, nu)
            if not titel and tijden is not None:
                # "Zet morgen om 14 uur iets in mijn agenda" -> "Hoe heet hij?" (Fase 27, M4).
                return vervolg.zet(
                    "Hoe heet de afspraak, sir?",
                    verwerk=lambda wat: vraag_toevoegen(wat[:1].upper() + wat[1:], *tijden, vandaag=nu.date()),
                    controle=vervolg.ZIN, inhoud=True,
                )
            if not titel:
                return vervolg.zet(
                    "Wat wilt u in uw agenda zetten, en wanneer, sir?",
                    sjabloon="zet {antwoord} in mijn agenda", controle=vervolg.ZIN, inhoud=True,
                )
            if tijden is None:
                return vervolg.zet(
                    f"Wanneer is {titel}, sir?",
                    sjabloon=f"zet {titel} {{antwoord}} in mijn agenda", controle=vervolg.MOMENT,
                )
            return vraag_toevoegen(titel, *tijden, vandaag=nu.date())
        term, moment = gegevens
        a = zoek(klant, term, nu, dagen=60)
        if a is None:
            return f"Ik vind geen afspraak '{term}' in de komende twee maanden, sir."
        if a["hele_dag"] or a.get("herhaalt"):
            return (f"{a['titel']} is een afspraak voor de hele dag of een terugkerende afspraak; "
                    "die verplaatst u beter in de Agenda-app.")
        start = a["start"]
        nieuwe_dag = moment.datum or start.date()
        begin = moment.begin or (start.hour, start.minute)
        nieuw_start = datetime.combine(nieuwe_dag, datetime.min.time()).replace(hour=begin[0], minute=begin[1])
        duur = a["eind"] - a["start"]
        nieuw_eind = nieuw_start + duur
        if moment.eind:
            nieuw_eind = nieuw_start.replace(hour=moment.eind[0], minute=moment.eind[1])
            if nieuw_eind <= nieuw_start:
                nieuw_eind = nieuw_start + duur
        return vraag_verplaatsen(a, nieuw_start, nieuw_eind, nu.date())
    except koppelingen.KoppelFout as fout:
        logger.warning("Agenda: %s", fout)
        return f"Dat lukte niet: {fout}"
