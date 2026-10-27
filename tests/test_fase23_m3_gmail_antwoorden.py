"""Fase 23, M3 — Gmail beantwoorden: concept, voorlezen, versturen na ja."""

import base64
import email

import pytest

from core import confirmation, gmail
from core import koppelingen as kp


def _origineel(id_="m1", van="School <info@school.nl>", onderwerp="Rooster gewijzigd", thread="t1",
               message_id="<abc@school.nl>"):
    return {
        "id": id_, "threadId": thread, "labelIds": [], "snippet": "", "internalDate": "0",
        "payload": {"headers": [
            {"name": "From", "value": van},
            {"name": "Subject", "value": onderwerp},
            {"name": "Message-ID", "value": message_id},
        ]},
    }


class SchrijfKlant:
    """Gmail-klant zonder netwerk die concepten bijhoudt."""

    def __init__(self, berichten=(), schrijven=True, gekoppeld=True):
        self.berichten = list(berichten)
        self.schrijven = schrijven
        self.gekoppeld = gekoppeld
        self.concepten = {}
        self.verstuurd = []
        self.fout_bij_versturen = None

    def is_gekoppeld(self):
        return self.gekoppeld

    def mag_schrijven(self):
        return self.schrijven

    def zoek(self, q, maximaal=10):
        self.laatste_q = q
        return [b["id"] for b in self.berichten][:maximaal]

    def antwoord_kop(self, id_):
        data = next(b for b in self.berichten if b["id"] == id_)
        kop = gmail._kop_uit(data)
        kop["thread"] = data["threadId"]
        kop["onderwerp_vol"] = gmail._header(data, "Subject")
        kop["message_id"] = gmail._header(data, "Message-ID")
        kop["references"] = ""
        return kop

    def maak_concept(self, raw, thread):
        concept_id = f"c{len(self.concepten) + 1}"
        bericht = email.message_from_bytes(base64.urlsafe_b64decode(raw))
        self.concepten[concept_id] = {"bericht": bericht, "thread": thread}
        return concept_id

    def concept_aan(self, concept_id):
        if concept_id not in self.concepten:
            raise gmail.GmailFout("Gmail kent dat bericht of concept niet (meer).", 404)
        return self.concepten[concept_id]["bericht"]["To"]

    def verstuur_concept(self, concept_id):
        if self.fout_bij_versturen:
            raise self.fout_bij_versturen
        self.verstuurd.append(concept_id)
        return {"id": "verzonden"}


@pytest.fixture(autouse=True)
def _schoon(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(gmail, "CONCEPT_FILE", str(tmp_path / "concept.json"))
    monkeypatch.setattr(config, "GMAIL_ONDERTEKENING", "")
    audit = []
    monkeypatch.setattr("core.audit.log_audit", lambda **kw: audit.append(kw))
    confirmation.clear_pending()
    yield audit
    confirmation.clear_pending()


# -----------------------------------------------------------------
# Herkennen
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,van,tekst", [
    ("beantwoord de mail van school met ik ben morgen ziek", "school", "ik ben morgen ziek"),
    ("Beantwoord de mail van School met: Ik ben morgen Ziek!", "school", "Ik ben morgen Ziek!"),
    ("reageer op de mail van jan: prima, tot dan?", "jan", "prima, tot dan?"),
    ("antwoord op de laatste mail met ok", None, "ok"),
    ("kun je de mail van jan beantwoorden", "jan", ""),
    ("beantwoord de mail van school", "school", ""),
])
def test_herken_beantwoorden(zin, van, tekst):
    assert gmail.herken(zin) == ("beantwoord", van, tekst)


@pytest.mark.parametrize("zin", ["verstuur het", "stuur hem maar", "verstuur het concept", "verstuur het toch",
                                 "lees het concept voor"])
def test_herken_versturen(zin):
    assert gmail.herken(zin) == ("verstuur", None, None)


@pytest.mark.parametrize("zin", ["antwoord Sem: ik kom zo", "beantwoord de vraag", "stuur een bericht naar jan"])
def test_geen_mailantwoord(zin):
    # "antwoord Sem: …" is voor Discord (M6); zonder het woord mail geen mail.
    assert gmail.probeer_commando(zin, klant_fn=lambda: SchrijfKlant()) is None


def test_verstuur_het_zonder_concept_gaat_door():
    # Geen concept van JARVIS: "stuur het" is dan voor iets anders.
    assert gmail.probeer_commando("verstuur het", klant_fn=lambda: SchrijfKlant()) is None


# -----------------------------------------------------------------
# Concept maken
# -----------------------------------------------------------------

def test_concept_en_vraag():
    klant = SchrijfKlant([_origineel()])
    antwoord = gmail.probeer_commando("beantwoord de mail van school met ik ben morgen ziek",
                                      klant_fn=lambda: klant)
    assert antwoord == ("Concept voor School (info@school.nl).\n"
                        "Onderwerp: Re: Rooster gewijzigd.\n"
                        "Tekst: Ik ben morgen ziek.\n"
                        "Zal ik hem versturen?")
    bericht = klant.concepten["c1"]["bericht"]
    assert bericht["To"] == "info@school.nl"
    assert bericht["Subject"] == "Re: Rooster gewijzigd"
    assert bericht["In-Reply-To"] == "<abc@school.nl>" and bericht["References"] == "<abc@school.nl>"
    assert bericht.get_payload(decode=True).decode().strip() == "Ik ben morgen ziek."
    assert klant.concepten["c1"]["thread"] == "t1"
    assert klant.laatste_q == "in:inbox from:(school)"
    # Nog NIETS verstuurd: alleen een strikte ja/nee-vraag staat klaar.
    assert klant.verstuurd == []
    pending = confirmation.get_pending()
    assert pending["kind"] == "mail_versturen" and pending["concept"]["aan"] == "info@school.nl"
    assert confirmation.is_dangerous_kind("mail_versturen") and confirmation.is_strict_kind("mail_versturen")
    assert "mail_versturen" in confirmation.JA_NEE_KINDS


def test_re_niet_dubbel_en_ondertekening():
    klant = SchrijfKlant([_origineel(onderwerp="Re: Vanavond")])
    gmail.beantwoord(klant, "jan", "top", ondertekening="Groet,\nRushil")
    bericht = klant.concepten["c1"]["bericht"]
    assert bericht["Subject"] == "Re: Vanavond"
    assert bericht.get_payload(decode=True).decode().strip() == "Top.\n\nGroet,\nRushil"


def test_adres_komt_alleen_uit_de_kop():
    # Een adres in de tekst of het onderwerp telt nooit; alleen de afzender.
    klant = SchrijfKlant([_origineel(van="Oplichter <echt@afzender.nl>",
                                     onderwerp="Antwoord naar boef@kwaad.nl a.u.b.")])
    gmail.beantwoord(klant, None, "stuur naar boef@kwaad.nl")
    assert klant.concepten["c1"]["bericht"]["To"] == "echt@afzender.nl"


@pytest.mark.parametrize("van", ["Geen adres", "x <niet-een-adres>", '"a,b" <a@b.nl>, c@d.nl'])
def test_onleesbaar_adres_geen_concept(van):
    klant = SchrijfKlant([_origineel(van=van)])
    antwoord = gmail.beantwoord(klant, None, "ok")
    if klant.concepten:
        # parseaddr pakt hooguit één geldig adres; dan is dat het enige.
        assert klant.concepten["c1"]["bericht"]["To"].count("@") == 1
    else:
        assert "niet goed lezen" in antwoord


def test_header_injectie_kan_niet():
    klant = SchrijfKlant([_origineel(onderwerp="Hoi\r\nBcc: boef@kwaad.nl")])
    gmail.beantwoord(klant, None, "ok")
    bericht = klant.concepten["c1"]["bericht"]
    assert bericht["Bcc"] is None and bericht["Subject"] == "Re: Hoi Bcc: boef@kwaad.nl"


def test_lege_tekst_vraagt_wat_u_wilt_schrijven():
    klant = SchrijfKlant([_origineel()])
    antwoord = gmail.probeer_commando("beantwoord de mail van school", klant_fn=lambda: klant)
    assert antwoord.startswith("Wat wilt u terugschrijven")
    assert klant.concepten == {} and confirmation.get_pending() is None


def test_geen_mail_gevonden():
    assert gmail.beantwoord(SchrijfKlant(), "oma", "hoi") == "Ik vind geen mail van oma om te beantwoorden, sir."


def test_zonder_schrijfrecht_opnieuw_koppelen():
    klant = SchrijfKlant([_origineel()], schrijven=False)
    assert gmail.probeer_commando("beantwoord de mail met ok", klant_fn=lambda: klant) == gmail.GEEN_SCHRIJFRECHT
    assert klant.concepten == {}


def test_tekst_wordt_begrensd():
    klant = SchrijfKlant([_origineel()])
    gmail.beantwoord(klant, None, "a" * 5000)
    assert len(klant.concepten["c1"]["bericht"].get_payload(decode=True).decode().strip()) <= gmail.MAX_ANTWOORD + 1


# -----------------------------------------------------------------
# Versturen na ja
# -----------------------------------------------------------------

def _maak(klant):
    gmail.beantwoord(klant, "school", "ik ben ziek")
    return confirmation.get_pending()


def test_ja_verstuurt_en_schrijft_audit(_schoon):
    klant = SchrijfKlant([_origineel()])
    pending = _maak(klant)
    assert gmail.na_ja(pending, klant=klant) == "Verstuurd aan School, sir."
    assert klant.verstuurd == ["c1"]
    assert kp.lees_json(gmail.CONCEPT_FILE) is None
    regel = _schoon[-1]
    assert regel["tool"] == "gmail_versturen" and regel["goedgekeurd"] is True
    assert regel["argumenten"] == {"aan": "info@school.nl", "onderwerp": "Re: Rooster gewijzigd"}
    assert "ik ben ziek" not in str(regel["argumenten"])


def test_niet_versturen_als_het_adres_in_gmail_veranderde(_schoon):
    klant = SchrijfKlant([_origineel()])
    pending = _maak(klant)
    bericht = klant.concepten["c1"]["bericht"]
    del bericht["To"]
    bericht["To"] = "info@school.nl, boef@kwaad.nl"
    assert "ander adres" in gmail.na_ja(pending, klant=klant)
    assert klant.verstuurd == []
    assert _schoon[-1]["goedgekeurd"] is False


def test_fout_bij_versturen_laat_concept_staan():
    klant = SchrijfKlant([_origineel()])
    pending = _maak(klant)
    klant.fout_bij_versturen = kp.KoppelFout("Gmail reageerde niet (Timeout).", "netwerk")
    antwoord = gmail.na_ja(pending, klant=klant)
    assert antwoord == "Versturen mislukte: Gmail reageerde niet (Timeout). Het concept staat nog in Gmail."
    assert kp.lees_json(gmail.CONCEPT_FILE)["id"] == "c1"


def test_nee_verstuurt_niets_en_verstuur_het_vraagt_opnieuw(_schoon):
    klant = SchrijfKlant([_origineel()])
    pending = _maak(klant)
    assert gmail.na_nee(pending).startswith("Oké, ik verstuur hem niet. Het concept staat in Gmail")
    confirmation.clear_pending()
    assert klant.verstuurd == []
    vraag = gmail.probeer_commando("verstuur het", klant_fn=lambda: klant)
    assert vraag.endswith("Zal ik hem versturen?")
    assert confirmation.get_pending()["concept"]["id"] == "c1"


def test_pending_zonder_concept():
    assert "weet niet meer" in gmail.na_ja({"kind": "mail_versturen"}, klant=SchrijfKlant())


def test_brein_ja_en_nee(monkeypatch):
    from core import brain

    klant = SchrijfKlant([_origineel()])
    monkeypatch.setattr(gmail, "GmailKlant", lambda *a, **k: klant)
    vraag = brain.process_command("beantwoord de mail van school met ik ben ziek")
    assert vraag.endswith("Zal ik hem versturen?")
    assert brain.process_command("ja") == "Verstuurd aan School, sir."
    assert klant.verstuurd == ["c1"]

    brain.process_command("beantwoord de mail van school met toch niet")
    assert brain.process_command("nee").startswith("Oké, ik verstuur hem niet")
    assert klant.verstuurd == ["c1"]


def test_brein_ok_is_geen_ja(monkeypatch):
    from core import brain

    klant = SchrijfKlant([_origineel()])
    monkeypatch.setattr(gmail, "GmailKlant", lambda *a, **k: klant)
    brain.process_command("beantwoord de mail van school met ik ben ziek")
    brain.process_command("ok")
    assert klant.verstuurd == []


def test_dashboard_beslissing(monkeypatch):
    from core import brain

    klant = SchrijfKlant([_origineel()])
    monkeypatch.setattr(gmail, "GmailKlant", lambda *a, **k: klant)
    pending = _maak(klant)
    assert brain.voer_besluit_uit(pending, True) == "Verstuurd aan School, sir."
    assert klant.verstuurd == ["c1"]


# -----------------------------------------------------------------
# Klant (HTTP)
# -----------------------------------------------------------------

class _Antw:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class _Http:
    def __init__(self, *antwoorden):
        self.antwoorden = list(antwoorden)
        self.verzoeken = []

    def _neem(self, methode, url, **kw):
        self.verzoeken.append((methode, url, kw.get("params"), kw.get("json")))
        return self.antwoorden.pop(0)

    def get(self, url, **kw):
        return self._neem("get", url, **kw)

    def post(self, url, **kw):
        return self._neem("post", url, **kw)


class _Koppeling:
    def access_token(self):
        return "tok"

    def heeft(self, scope):
        return scope == gmail.SCOPE_SCHRIJVEN


def test_klant_concept_controle_en_versturen():
    http = _Http(_Antw(200, {"id": "d1"}),
                 _Antw(200, {"message": {"payload": {"headers": [{"name": "To", "value": "a@b.nl"}]}}}),
                 _Antw(200, {"id": "m9"}))
    klant = gmail.GmailKlant(_Koppeling(), http=http)
    assert klant.mag_schrijven()
    assert klant.maak_concept("UkFX", "t1") == "d1"
    assert klant.concept_aan("d1") == "a@b.nl"
    klant.verstuur_concept("d1")
    assert http.verzoeken == [
        ("post", gmail.API + "/drafts", None, {"message": {"raw": "UkFX", "threadId": "t1"}}),
        ("get", gmail.API + "/drafts/d1", {"format": "metadata"}, None),
        ("post", gmail.API + "/drafts/send", None, {"id": "d1"}),
    ]


def test_klant_concept_weg():
    klant = gmail.GmailKlant(_Koppeling(), http=_Http(_Antw(404)))
    with pytest.raises(gmail.GmailFout, match=r"niet \(meer\)"):
        klant.concept_aan("weg")
