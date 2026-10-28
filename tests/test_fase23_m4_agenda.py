"""Fase 23, M4 — iCloud-agenda: CalDAV, vragen, toevoegen en verplaatsen na ja."""

from datetime import date, datetime, timedelta, timezone

import pytest

from core import agenda_tijd as tijd
from core import confirmation, icloud_agenda
from core import koppelingen as kp

WACHTWOORD = "abcd-efgh-ijkl-mnop"
VANDAAG = date(2026, 10, 28)  # woensdag
NU = datetime(2026, 10, 28, 12, 0)


def _utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _vevent(uid, titel, start, eind, plaats="", extra=""):
    regels = ["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{titel}", f"DTSTART:{_utc(start)}", f"DTEND:{_utc(eind)}"]
    if plaats:
        regels.append(f"LOCATION:{plaats}")
    if extra:
        regels.append(extra)
    regels += ["BEGIN:VALARM", "TRIGGER:-PT15M", "SUMMARY:alarm", "END:VALARM", "END:VEVENT"]
    return "\r\n".join(regels)


def _ics(*events):
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", *events, "END:VCALENDAR"]) + "\r\n"


class Antwoord:
    def __init__(self, status, tekst="", headers=None):
        self.status_code = status
        self.text = tekst
        self.content = tekst.encode("utf-8")
        self.headers = headers or {}


class NepICloud:
    """Bootst caldav.icloud.com na (multistatus-XML, ETags, PUT)."""

    def __init__(self, events=None, wachtwoord=WACHTWOORD):
        self.events = dict(events or {})   # href -> (ics, etag)
        self.wachtwoord = wachtwoord
        self.verzoeken = []
        self.puts = []
        self.wijzig_na_get = False

    def request(self, methode, url, data=None, headers=None, auth=None, timeout=None, allow_redirects=True):
        body = (data or b"").decode("utf-8")
        self.verzoeken.append((methode, url, dict(headers or {}), body))
        assert allow_redirects is False
        if auth != ("rushil@icloud.com", self.wachtwoord):
            return Antwoord(401)
        if methode == "PROPFIND" and url == "https://caldav.icloud.com/":
            return Antwoord(302, headers={"Location": "https://p01-caldav.icloud.com/"})
        if methode == "PROPFIND" and url == "https://p01-caldav.icloud.com/":
            return Antwoord(207, '<multistatus xmlns="DAV:"><response><href>/</href><propstat><prop>'
                                 '<current-user-principal><href>/123/principal/</href></current-user-principal>'
                                 '</prop></propstat></response></multistatus>')
        if methode == "PROPFIND" and url.endswith("/123/principal/"):
            return Antwoord(207, '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                                 '<d:response><d:href>/123/principal/</d:href><d:propstat><d:prop>'
                                 '<c:calendar-home-set><d:href>https://p01-caldav.icloud.com/123/calendars/</d:href>'
                                 '</c:calendar-home-set></d:prop></d:propstat></d:response></d:multistatus>')
        if methode == "PROPFIND" and url.endswith("/123/calendars/"):
            assert headers["Depth"] == "1"
            return Antwoord(207, '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                                 '<d:response><d:href>/123/calendars/</d:href><d:propstat><d:prop>'
                                 '<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>'
                                 '<d:response><d:href>/123/calendars/home/</d:href><d:propstat><d:prop>'
                                 '<d:displayname>Thuis</d:displayname><d:resourcetype><d:collection/><c:calendar/>'
                                 '</d:resourcetype><c:supported-calendar-component-set><c:comp name="VEVENT"/>'
                                 '</c:supported-calendar-component-set></d:prop></d:propstat></d:response>'
                                 '<d:response><d:href>/123/calendars/taken/</d:href><d:propstat><d:prop>'
                                 '<d:displayname>Herinneringen</d:displayname><d:resourcetype><d:collection/>'
                                 '<c:calendar/></d:resourcetype><c:supported-calendar-component-set>'
                                 '<c:comp name="VTODO"/></c:supported-calendar-component-set></d:prop></d:propstat>'
                                 '</d:response></d:multistatus>')
        if methode == "REPORT" and url.endswith("/123/calendars/home/"):
            assert "<c:expand" in body and "<c:time-range" in body
            delen = []
            for href, (ics, etag) in self.events.items():
                delen.append(f'<d:response><d:href>{href}</d:href><d:propstat><d:prop><d:getetag>{etag}'
                             f'</d:getetag><c:calendar-data>{_xml(ics)}</c:calendar-data></d:prop></d:propstat>'
                             '</d:response>')
            return Antwoord(207, '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                                 + "".join(delen) + '</d:multistatus>')
        if methode == "GET":
            pad = url.replace("https://p01-caldav.icloud.com", "")
            ics, etag = self.events[pad]
            if self.wijzig_na_get:
                self.events[pad] = (ics, '"later"')
            return Antwoord(200, ics, {"ETag": etag})
        if methode == "PUT":
            pad = url.replace("https://p01-caldav.icloud.com", "")
            self.puts.append((pad, dict(headers), body))
            if headers.get("If-Match") and self.events.get(pad, ("", ""))[1] != headers["If-Match"]:
                return Antwoord(412)
            self.events[pad] = (body, '"nieuw"')
            return Antwoord(201)
        return Antwoord(404)


def _xml(tekst):
    return tekst.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@pytest.fixture(autouse=True)
def _instellingen(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "ICLOUD_GEBRUIKER", "rushil@icloud.com")
    monkeypatch.setattr(config, "ICLOUD_APP_WACHTWOORD", WACHTWOORD)
    monkeypatch.setattr(config, "ICLOUD_AGENDA", "")
    monkeypatch.setattr(config, "ICLOUD_CALDAV_URL", "https://caldav.icloud.com/")
    monkeypatch.setattr(icloud_agenda, "STATUS_FILE", str(tmp_path / "agenda.json"))
    audit = []
    monkeypatch.setattr("core.audit.log_audit", lambda **kw: audit.append(kw))
    confirmation.clear_pending()
    yield audit
    confirmation.clear_pending()


def _klant(server):
    return icloud_agenda.AgendaKlant(http=server)


def _standaard():
    return NepICloud({
        "/123/calendars/home/a.ics": (_ics(_vevent("a", "Tandarts", datetime(2026, 10, 28, 14), datetime(2026, 10, 28, 15),
                                                   "Breda")), '"e1"'),
        "/123/calendars/home/b.ics": (_ics(_vevent("b", "Voetbal", datetime(2026, 10, 30, 18, 30),
                                                   datetime(2026, 10, 30, 20))), '"e2"'),
        "/123/calendars/home/c.ics": (_ics("BEGIN:VEVENT\r\nUID:c\r\nSUMMARY:Verjaardag oma\r\n"
                                           "DTSTART;VALUE=DATE:20261028\r\nDTEND;VALUE=DATE:20261029\r\nEND:VEVENT"),
                                      '"e3"'),
    })


# -----------------------------------------------------------------
# Tijd
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,datum,begin,eind,titel", [
    ("tandarts morgen om 14:00", date(2026, 10, 29), (14, 0), None, "tandarts"),
    ("voetbal vrijdag om half drie", date(2026, 10, 30), (14, 30), None, "voetbal"),
    ("kapper op 3 november om 10 uur", date(2026, 11, 3), (10, 0), None, "kapper"),
    ("overleg van 2 tot 4 morgen", date(2026, 10, 29), (14, 0), (16, 0), "overleg"),
    ("sport volgende week dinsdag om 7 uur 's avonds", date(2026, 11, 3), (19, 0), None, "sport"),
    ("film om 20.30", None, (20, 30), None, "film"),
    ("les om kwart voor half negen", None, (8, 15), None, "les"),
    ("bellen om kwart over negen in de ochtend", None, (9, 15), None, "bellen"),
    ("training om 7:30", None, (7, 30), None, "training"),
    ("eten om 6 uur met 4 personen", None, (18, 0), None, "eten met 4 personen"),
    ("verjaardag 2 januari", date(2027, 1, 2), None, None, "verjaardag"),
    ("vergadering vandaag", date(2026, 10, 28), None, None, "vergadering"),
])
def test_lees_moment(zin, datum, begin, eind, titel):
    m = tijd.lees_moment(zin, VANDAAG)
    assert (m.datum, m.begin, m.eind, m.rest(zin)) == (datum, begin, eind, titel)


def test_afspraak_tijden():
    m = tijd.lees_moment("om 10 uur", VANDAAG)
    assert tijd.afspraak_tijden(m, NU)[0] == datetime(2026, 10, 29, 10)  # 10:00 is vandaag al voorbij
    m = tijd.lees_moment("om 15 uur", VANDAAG)
    assert tijd.afspraak_tijden(m, NU)[:2] == (datetime(2026, 10, 28, 15), datetime(2026, 10, 28, 16))
    m = tijd.lees_moment("vrijdag", VANDAAG)
    assert tijd.afspraak_tijden(m, NU) == (datetime(2026, 10, 30), None, True)
    assert tijd.afspraak_tijden(tijd.lees_moment("zomaar", VANDAAG), NU) is None


def test_dag_woord():
    assert tijd.dag_woord(VANDAAG, VANDAAG) == "vandaag"
    assert tijd.dag_woord(date(2026, 10, 29), VANDAAG) == "morgen"
    assert tijd.dag_woord(date(2026, 11, 3), VANDAAG) == "dinsdag 3 november"


# -----------------------------------------------------------------
# iCalendar
# -----------------------------------------------------------------

def test_lees_ics_met_alarm_hele_dag_en_geannuleerd():
    ics = _ics(
        _vevent("x", "Tandarts\\, controle", datetime(2026, 10, 28, 14), datetime(2026, 10, 28, 15), "Breda\\; centrum"),
        "BEGIN:VEVENT\r\nUID:y\r\nSUMMARY:Vrij\r\nDTSTART;VALUE=DATE:20261030\r\nEND:VEVENT",
        "BEGIN:VEVENT\r\nUID:z\r\nSUMMARY:Weg\r\nSTATUS:CANCELLED\r\nDTSTART:20261028T100000Z\r\nEND:VEVENT",
        "BEGIN:VEVENT\r\nUID:w\r\nSUMMARY:Lan\r\n g party\r\nDTSTART:20261029T100000Z\r\nDURATION:PT1H30M\r\n"
        "END:VEVENT",
    )
    lijst = icloud_agenda.lees_ics(ics)
    assert [a["titel"] for a in lijst] == ["Tandarts, controle", "Vrij", "Lang party"]
    assert lijst[0]["plaats"] == "Breda; centrum" and lijst[0]["start"] == datetime(2026, 10, 28, 14)
    assert lijst[1]["hele_dag"] and lijst[1]["eind"] == date(2026, 10, 31)
    assert lijst[2]["eind"] - lijst[2]["start"] == timedelta(minutes=90)


def test_terugval_herhaling_zonder_expand():
    a = icloud_agenda.lees_ics(_ics(_vevent("r", "Training", datetime(2026, 10, 20, 19), datetime(2026, 10, 20, 20),
                                            extra="RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=6")))[0]
    a["exdate"] = [datetime(2026, 10, 29, 19)]
    keren = icloud_agenda._herhaal(a, datetime(2026, 10, 26), datetime(2026, 11, 9))
    assert [k["start"] for k in keren] == [datetime(2026, 10, 27, 19), datetime(2026, 11, 3, 19),
                                          datetime(2026, 11, 5, 19)]


def test_nieuwe_afspraak_in_utc_en_veilig():
    ics = icloud_agenda.maak_ics("u1", "Tandarts; Bcc\r\nEND:VEVENT", datetime(2026, 10, 29, 14),
                                 datetime(2026, 10, 29, 15), False, nu=NU)
    assert f"DTSTART:{_utc(datetime(2026, 10, 29, 14))}" in ics
    assert "SUMMARY:Tandarts\\; Bcc END:VEVENT" in ics
    # De tekst staat op één regel; er komt geen tweede END:VEVENT-regel bij.
    assert ics.split("\r\n").count("END:VEVENT") == 1
    hele = icloud_agenda.maak_ics("u2", "Vrij", datetime(2026, 10, 30), None, True, nu=NU)
    assert "DTSTART;VALUE=DATE:20261030" in hele and "DTEND;VALUE=DATE:20261031" in hele


def test_verzet_ics():
    oud = _ics(_vevent("a", "Tandarts", datetime(2026, 10, 28, 14), datetime(2026, 10, 28, 15), extra="SEQUENCE:2"))
    nieuw = icloud_agenda.verzet_ics(oud, datetime(2026, 10, 30, 10), datetime(2026, 10, 30, 11), nu=NU)
    a = icloud_agenda.lees_ics(nieuw)[0]
    assert (a["start"], a["eind"], a["titel"]) == (datetime(2026, 10, 30, 10), datetime(2026, 10, 30, 11), "Tandarts")
    assert "SEQUENCE:3" in nieuw and nieuw.count("DTSTART") == 1 and "TRIGGER:-PT15M" in nieuw
    with pytest.raises(icloud_agenda.AgendaFout, match="terugkerende"):
        icloud_agenda.verzet_ics(_ics(_vevent("r", "x", NU, NU, extra="RRULE:FREQ=DAILY")), NU, NU)


# -----------------------------------------------------------------
# CalDAV
# -----------------------------------------------------------------

def test_ontdekken_volgt_omleiding_en_slaat_herinneringen_over(tmp_path):
    server = _standaard()
    agendas = _klant(server).agendas()
    assert agendas == [{"url": "https://p01-caldav.icloud.com/123/calendars/home/", "naam": "Thuis"}]
    # Na de 302 blijft het een PROPFIND (requests zou er een GET van maken).
    assert [v[0] for v in server.verzoeken[:2]] == ["PROPFIND", "PROPFIND"]
    # Gecachet, en zonder wachtwoord in het bestand.
    assert WACHTWOORD not in (tmp_path / "agenda.json").read_text(encoding="utf-8")
    aantal = len(server.verzoeken)
    _klant(server).agendas()
    assert len(server.verzoeken) == aantal


def test_fout_wachtwoord_wordt_probleem():
    import config

    server = NepICloud(wachtwoord="iets-anders")
    with pytest.raises(icloud_agenda.AgendaFout) as fout:
        _klant(server).agendas()
    assert fout.value.status == 401 and WACHTWOORD not in str(fout.value)
    status = icloud_agenda.koppeling_status()
    assert status["probleem"] == icloud_agenda.PROBLEEM_WACHTWOORD and status["gekoppeld"]
    assert config.ICLOUD_APP_WACHTWOORD not in str(status)


def test_status_niet_ingesteld(monkeypatch):
    import config

    monkeypatch.setattr(config, "ICLOUD_APP_WACHTWOORD", "")
    assert icloud_agenda.koppeling_status() == {"id": "icloud_agenda", "naam": "iCloud-agenda", "gekoppeld": False,
                                                "rechten": [], "probleem": None}
    assert "icloud_agenda" in kp._STANDAARD


# -----------------------------------------------------------------
# Vragen
# -----------------------------------------------------------------

def _vraag(zin, server=None):
    server = server or _standaard()
    return icloud_agenda.probeer_commando(zin, klant_fn=lambda: _klant(server), nu=NU)


def test_vandaag():
    # "Wat staat er vandaag op de planning?" is sinds M5 de dagstart.
    assert _vraag("wat staat er vandaag op de planning?") is None
    assert _vraag("wat heb ik vandaag?") == (
        "Vandaag heeft u 2 afspraken:\n"
        "Hele dag: Verjaardag oma.\n"
        "14:00 tot 15:00: Tandarts, in Breda.")


def test_morgen_niets_en_vrijdag():
    assert _vraag("wat heb ik morgen") == "Morgen staat er niets in uw agenda, sir."
    assert _vraag("wat staat er vrijdag in mijn agenda") == \
        "Overmorgen heeft u 1 afspraak:\n18:30 tot 20:00: Voetbal."


def test_deze_week():
    assert _vraag("wat heb ik deze week") == (
        "Vandaag:\nHele dag: Verjaardag oma.\n14:00 tot 15:00: Tandarts, in Breda.\n"
        "Overmorgen:\n18:30 tot 20:00: Voetbal.")


def test_volgende_en_zoeken():
    assert _vraag("wanneer is mijn volgende afspraak") == "Uw volgende afspraak is vandaag om 14:00: Tandarts, in Breda."
    assert _vraag("wanneer moet ik naar voetbal") == "Voetbal is overmorgen om 18:30."
    # Niets gevonden: dan is het geen agendavraag ("wanneer is pasen?").
    assert _vraag("wanneer is pasen") is None


@pytest.mark.parametrize("zin", ["heb ik nieuwe mail", "wat heb ik vandaag gegeten", "zet de lamp aan",
                                 "verplaats het bestand rapport naar documenten", "wat heb ik"])
def test_geen_agendavraag(zin):
    assert icloud_agenda.herken(zin, VANDAAG) is None


def test_niet_ingesteld(monkeypatch):
    import config

    monkeypatch.setattr(config, "ICLOUD_GEBRUIKER", "")
    assert _vraag("wanneer is mijn volgende afspraak") == icloud_agenda.NIET_INGESTELD
    # "Wat staat er vandaag?" gaat dan naar de gewone dagstart.
    assert _vraag("wat staat er vandaag") is None


# -----------------------------------------------------------------
# Toevoegen en verplaatsen na ja
# -----------------------------------------------------------------

def test_toevoegen_vraagt_eerst_en_zet_na_ja(_instellingen):
    server = _standaard()
    vraag = _vraag("zet tandarts morgen om 14:00 in mijn agenda", server)
    assert vraag == ("Afspraak toevoegen: Tandarts, morgen (donderdag 29 oktober) van 14:00 tot 15:00.\n"
                     "Zal ik hem in uw agenda zetten?")
    assert server.puts == []
    pending = confirmation.get_pending()
    assert pending["kind"] == "agenda_toevoegen"
    assert confirmation.is_strict_kind("agenda_toevoegen") and "agenda_toevoegen" in confirmation.JA_NEE_KINDS
    assert icloud_agenda.na_ja(pending, klant=_klant(server)) == "Tandarts staat in uw agenda (Thuis), sir."
    pad, headers, body = server.puts[0]
    assert pad.startswith("/123/calendars/home/") and pad.endswith("@jarvis.ics")
    assert headers["If-None-Match"] == "*"
    a = icloud_agenda.lees_ics(body)[0]
    assert (a["titel"], a["start"], a["eind"]) == ("Tandarts", datetime(2026, 10, 29, 14), datetime(2026, 10, 29, 15))
    assert _instellingen[-1]["tool"] == "agenda_toevoegen" and _instellingen[-1]["goedgekeurd"]


def test_toevoegen_hele_dag_en_vragen_bij_ontbrekend():
    assert _vraag("voeg verjaardag oma toe aan mijn agenda op 5 december").startswith(
        "Afspraak toevoegen: Verjaardag oma, zaterdag 5 december, de hele dag.")
    assert _vraag("zet tandarts in mijn agenda").startswith("Wanneer is Tandarts")
    assert _vraag("zet morgen om 3 uur in mijn agenda").startswith("Hoe heet de afspraak")


def test_eigen_agenda_kiezen(monkeypatch):
    import config

    server = _standaard()
    monkeypatch.setattr(config, "ICLOUD_AGENDA", "thuis")
    assert _klant(server).schrijf_agenda()["naam"] == "Thuis"
    monkeypatch.setattr(config, "ICLOUD_AGENDA", "bestaat-niet")
    assert _klant(server).schrijf_agenda()["naam"] == "Thuis"


def test_verplaatsen_houdt_duur_en_gebruikt_etag(_instellingen):
    server = _standaard()
    vraag = _vraag("verplaats de tandarts naar vrijdag om 10 uur", server)
    assert vraag == ("Tandarts verplaatsen?\nNu: vandaag (woensdag 28 oktober) van 14:00 tot 15:00.\n"
                     "Nieuw: overmorgen (vrijdag 30 oktober) van 10:00 tot 11:00.\nZal ik hem verplaatsen?")
    pending = confirmation.get_pending()
    assert icloud_agenda.na_ja(pending, klant=_klant(server)) == "Tandarts is verplaatst, sir."
    pad, headers, body = server.puts[0]
    assert pad == "/123/calendars/home/a.ics" and headers["If-Match"] == '"e1"'
    a = icloud_agenda.lees_ics(body)[0]
    assert (a["start"], a["eind"], a["plaats"]) == (datetime(2026, 10, 30, 10), datetime(2026, 10, 30, 11), "Breda")


def test_verplaatsen_alleen_dag_houdt_tijd():
    server = _standaard()
    vraag = _vraag("verplaats voetbal naar zaterdag", server)
    assert "Nieuw: zaterdag 31 oktober van 18:30 tot 20:00." in vraag


def test_verplaatsen_conflict_en_onbekend():
    server = _standaard()
    _vraag("verplaats de tandarts naar vrijdag om 10 uur", server)
    pending = confirmation.get_pending()
    # Iemand wijzigt de afspraak tussen het lezen en het opslaan: 412, niets overschreven.
    server.wijzig_na_get = True
    assert "ergens anders gewijzigd" in icloud_agenda.na_ja(pending, klant=_klant(server))
    assert icloud_agenda.lees_ics(server.events["/123/calendars/home/a.ics"][0])[0]["start"] == \
        datetime(2026, 10, 28, 14)
    assert _vraag("verplaats de kapper naar morgen", server) == \
        "Ik vind geen afspraak 'kapper' in de komende twee maanden, sir."


def test_nee_doet_niets():
    server = _standaard()
    _vraag("zet tandarts morgen om 14:00 in mijn agenda", server)
    assert icloud_agenda.na_nee(confirmation.get_pending()) == "Oké, ik zet hem er niet in."
    assert server.puts == []


def test_brein_routeert(monkeypatch):
    from core import brain

    # Het brein gebruikt de echte klok: afspraken vanaf morgen.
    morgen = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())
    server = NepICloud({
        "/123/calendars/home/a.ics": (_ics(_vevent("a", "Tandarts", morgen.replace(hour=14),
                                                   morgen.replace(hour=15))), '"e1"'),
        "/123/calendars/home/b.ics": (_ics(_vevent("b", "Voetbal", morgen.replace(hour=18),
                                                   morgen.replace(hour=19))), '"e2"'),
    })
    echte = icloud_agenda.AgendaKlant
    monkeypatch.setattr(icloud_agenda, "AgendaKlant", lambda *a, **k: echte(http=server))
    assert brain.process_command("wanneer moet ik naar voetbal") == "Voetbal is morgen om 18:00."
    vraag = brain.process_command("zet kapper overmorgen om 11 uur in mijn agenda")
    assert vraag.endswith("Zal ik hem in uw agenda zetten?")
    assert brain.process_command("ok") is not None and server.puts == []  # "ok" is geen ja
    brain.process_command("zet kapper overmorgen om 11 uur in mijn agenda")
    assert brain.process_command("ja").startswith("Kapper staat in uw agenda")
    assert len(server.puts) == 1
    vraag = brain.process_command("verplaats de tandarts naar overmorgen om 10 uur")
    assert vraag.endswith("Zal ik hem verplaatsen?")
    assert brain.process_command("nee") == "Oké, de afspraak blijft staan zoals hij stond."
