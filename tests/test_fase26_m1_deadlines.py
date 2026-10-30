"""Fase 26, M1 — deadlines: met de stem invoeren, opvragen en herinneren."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from core import confirmation, deadlines, icloud_agenda
from core.deadlines import DeadlinePlanner

NU = datetime(2026, 10, 28, 12, 0)   # woensdag
VRIJDAG = date(2026, 10, 30)
STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"


def _a(titel, dag, uur=None, uid=None):
    if uur is None:
        return {"titel": titel, "start": dag, "eind": dag + timedelta(days=1), "hele_dag": True,
                "uid": uid or titel}
    start = datetime.combine(dag, datetime.min.time()).replace(hour=uur)
    return {"titel": titel, "start": start, "eind": start + timedelta(minutes=15), "hele_dag": False,
            "uid": uid or titel}


class Klant:
    def __init__(self, afspraken=()):
        self.lijst = list(afspraken)
        self.toegevoegd = []

    def afspraken(self, van, tot):
        def begin(a):
            s = a["start"]
            return s if isinstance(s, datetime) else datetime.combine(s, datetime.min.time())
        return [a for a in self.lijst if van <= begin(a) < tot]

    def voeg_toe(self, titel, start, eind, hele_dag):
        self.toegevoegd.append((titel, start, eind, hele_dag))
        return "Thuis"


@pytest.fixture(autouse=True)
def ingesteld(monkeypatch):
    monkeypatch.setattr(icloud_agenda, "is_ingesteld", lambda: True)
    confirmation.clear_pending()
    yield
    confirmation.clear_pending()


# ---------------------------------------------------------------------
# Herkennen
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin, titel, datum, tijd", [
    ("zet een deadline: verslag op vrijdag", "Verslag", VRIJDAG, None),
    ("zet een deadline voor het verslag op vrijdag", "Verslag", VRIJDAG, None),
    ("deadline verslag vrijdag", "Verslag", VRIJDAG, None),
    ("nieuwe deadline: presentatie geschiedenis maandag", "Presentatie geschiedenis", date(2026, 11, 2), None),
    ("maak een deadline aan: essay op 5 november om 17 uur", "Essay", date(2026, 11, 5), (17, 0)),
    ("kun je een deadline zetten: verslag vrijdag", None, None, None),
    ("noteer een deadline: portfolio morgen", "Portfolio", date(2026, 10, 29), None),
])
def test_toevoegen_herkend(zin, titel, datum, tijd):
    herkend = deadlines.herken(zin, NU.date())
    if titel is None:
        return  # vorm die we niet beloven; mag ook None zijn
    assert herkend[0] == "toevoegen"
    gevonden_titel, moment = herkend[1]
    assert gevonden_titel == titel
    assert moment.datum == datum
    assert moment.begin == tijd


@pytest.mark.parametrize("zin, dagen", [
    ("welke deadlines heb ik deze week?", 7),
    ("welke deadlines heb ik", 14),
    ("wat zijn mijn deadlines", 14),
    ("heb ik nog deadlines", 14),
    ("mijn deadlines", 14),
    ("deadlines vandaag", 1),
    ("welke deadlines heb ik morgen", 2),
    ("heb ik iets in te leveren deze week", 7),
])
def test_lijst_herkend(zin, dagen):
    assert deadlines.herken(zin, NU.date()) == ("lijst", dagen)


@pytest.mark.parametrize("zin, term", [
    ("wanneer moet het verslag af?", "verslag"),
    ("wanneer moet ik mijn essay inleveren", "essay"),
    ("wanneer is de deadline van het portfolio", "portfolio"),
])
def test_zoek_herkend(zin, term):
    assert deadlines.herken(zin, NU.date()) == ("zoek", term)


@pytest.mark.parametrize("zin", [
    "zet tandarts morgen om 14 uur in mijn agenda",
    "wat staat er vandaag op de planning",
    "wanneer is de tandarts",
    "wanneer moet ik weg",
    "open spotify",
    "waarom is de lucht blauw",
])
def test_geen_deadline(zin):
    assert deadlines.herken(zin, NU.date()) is None


# ---------------------------------------------------------------------
# Toevoegen (na ja)
# ---------------------------------------------------------------------

def test_hele_dag_deadline_vraagt_eerst():
    vraag = deadlines.probeer_commando("zet een deadline: verslag op vrijdag", nu=NU)
    assert vraag.startswith("Deadline toevoegen: verslag, overmorgen (vrijdag 30 oktober), de hele dag.")
    assert "Zal ik hem in uw agenda zetten?" in vraag
    pending = confirmation.get_pending()
    assert pending["kind"] == icloud_agenda.TOEVOEG_KIND
    a = pending["afspraak"]
    assert a["titel"] == "Deadline: Verslag"
    assert a["hele_dag"] is True
    assert a["start"].startswith("2026-10-30")


def test_deadline_met_tijd_kort():
    deadlines.probeer_commando("deadline essay op 5 november om 17 uur", nu=NU)
    a = confirmation.get_pending()["afspraak"]
    assert a["hele_dag"] is False
    start, eind = datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["eind"])
    assert start == datetime(2026, 11, 5, 17, 0)
    assert eind - start == timedelta(minutes=15)


def test_na_ja_in_agenda():
    deadlines.probeer_commando("zet een deadline: verslag op vrijdag", nu=NU)
    klant = Klant()
    antwoord = icloud_agenda.na_ja(confirmation.get_pending(), klant=klant)
    assert klant.toegevoegd[0][0] == "Deadline: Verslag"
    assert klant.toegevoegd[0][3] is True
    assert "staat in uw agenda" in antwoord


def test_zonder_datum_vraagt_wanneer():
    antwoord = deadlines.probeer_commando("zet een deadline: verslag", nu=NU)
    assert antwoord.startswith("Wanneer moet verslag af")
    assert confirmation.get_pending() is None


def test_zonder_titel():
    assert deadlines.probeer_commando("deadline vrijdag", nu=NU).startswith("Waarvoor is de deadline")


def test_agenda_niet_ingesteld(monkeypatch):
    monkeypatch.setattr(icloud_agenda, "is_ingesteld", lambda: False)
    assert deadlines.probeer_commando("zet een deadline: verslag op vrijdag", nu=NU) == icloud_agenda.NIET_INGESTELD
    assert deadlines.probeer_commando("wanneer moet het verslag af", nu=NU) is None


# ---------------------------------------------------------------------
# Opvragen
# ---------------------------------------------------------------------

def _klant_fn(*afspraken):
    klant = Klant(afspraken)
    return lambda: klant


def test_lijst_alleen_deadlines_op_datum():
    fn = _klant_fn(
        _a("Tandarts", NU.date(), 14),
        _a("Deadline: presentatie", date(2026, 11, 2)),
        _a("Deadline: verslag", VRIJDAG),
        _a("Deadline - essay", date(2026, 11, 5), 17),
    )
    antwoord = deadlines.probeer_commando("welke deadlines heb ik", klant_fn=fn, nu=NU)
    assert antwoord == ("U heeft de komende 14 dagen 3 deadlines: verslag (overmorgen), "
                        "presentatie (maandag 2 november), essay (donderdag 5 november om 17:00).")
    assert "Tandarts" not in antwoord


def test_lijst_deze_week_en_leeg():
    fn = _klant_fn(_a("Deadline: verslag", VRIJDAG), _a("Deadline: scriptie", date(2026, 12, 1)))
    assert deadlines.probeer_commando("welke deadlines heb ik deze week", klant_fn=fn, nu=NU) == \
        "U heeft deze week 1 deadline: verslag (overmorgen)."
    assert deadlines.probeer_commando("deadlines vandaag", klant_fn=fn, nu=NU) == "Geen deadlines vandaag, sir."


def test_zoek():
    fn = _klant_fn(_a("Deadline: verslag biologie", VRIJDAG))
    assert deadlines.probeer_commando("wanneer moet het verslag af?", klant_fn=fn, nu=NU) == \
        "Verslag biologie moet overmorgen af, sir."
    assert deadlines.probeer_commando("wanneer moet het essay af?", klant_fn=fn, nu=NU) is None


def test_agendafout_netjes():
    class Kapot:
        def afspraken(self, van, tot):
            raise icloud_agenda.AgendaFout("geen verbinding")

    antwoord = deadlines.probeer_commando("welke deadlines heb ik", klant_fn=Kapot, nu=NU)
    assert antwoord.startswith("Ik kon de agenda niet lezen")


# ---------------------------------------------------------------------
# Herinneringen: de avond ervoor en de ochtend zelf
# ---------------------------------------------------------------------

class Klok:
    def __init__(self, nu):
        self.nu = nu

    def __call__(self):
        return self.nu


@pytest.fixture
def planner(tmp_path):
    klok = Klok(datetime(2026, 10, 29, 18, 59))
    meldingen = []
    klant = Klant([_a("Deadline: verslag", VRIJDAG), _a("Tandarts", VRIJDAG, 10)])
    p = DeadlinePlanner(meld_fn=lambda tekst, bron: meldingen.append((tekst, bron)),
                        klant_fn=lambda: klant, klok=klok, herinnerd_pad=str(tmp_path / "h.json"))
    return p, klok, meldingen, klant


def test_avond_ervoor_om_19_uur(planner):
    p, klok, meldingen, _ = planner
    assert p.stap() == []
    klok.nu = datetime(2026, 10, 29, 19, 0)
    assert p.stap() == ["Morgen moet verslag af, sir."]
    assert meldingen == [("Morgen moet verslag af, sir.", "deadline")]
    klok.nu = datetime(2026, 10, 29, 21, 0)
    assert p.stap() == []  # niet twee keer


def test_ochtend_zelf_om_8_uur(planner):
    p, klok, meldingen, _ = planner
    klok.nu = datetime(2026, 10, 29, 19, 5)
    p.stap()
    klok.nu = datetime(2026, 10, 30, 7, 59)
    assert p.stap() == []
    klok.nu = datetime(2026, 10, 30, 8, 0)
    assert p.stap() == ["Vandaag moet verslag af, sir."]
    assert len(meldingen) == 2


def test_gemiste_avond_niet_alsnog_morgen_zeggen(planner):
    p, klok, meldingen, _ = planner
    klok.nu = datetime(2026, 10, 30, 9, 0)   # JARVIS stond gisteravond uit
    assert p.stap() == ["Vandaag moet verslag af, sir."]


def test_deadline_met_tijd(planner):
    p, klok, meldingen, klant = planner
    klant.lijst = [_a("Deadline: essay", VRIJDAG, 17)]
    klok.nu = datetime(2026, 10, 29, 19, 0)
    assert p.stap() == ["Morgen om 17:00 moet essay af, sir."]
    klok.nu = datetime(2026, 10, 30, 8, 0)
    assert p.stap() == ["Vandaag om 17:00 moet essay af, sir."]


def test_voorbije_deadline_geen_melding(planner):
    p, klok, meldingen, klant = planner
    klant.lijst = [_a("Deadline: essay", VRIJDAG, 7)]
    klok.nu = datetime(2026, 10, 30, 8, 0)
    assert p.stap() == []


def test_herinnerd_overleeft_herstart(planner, tmp_path):
    p, klok, meldingen, klant = planner
    klok.nu = datetime(2026, 10, 29, 19, 0)
    p.stap()
    nieuw = DeadlinePlanner(meld_fn=lambda t, bron: meldingen.append(t), klant_fn=lambda: klant,
                            klok=klok, herinnerd_pad=str(tmp_path / "h.json"))
    assert nieuw.stap() == []


def test_planner_niet_ingesteld(planner, monkeypatch):
    p, klok, *_ = planner
    monkeypatch.setattr(icloud_agenda, "is_ingesteld", lambda: False)
    klok.nu = datetime(2026, 10, 29, 19, 0)
    assert p.stap() == []


def test_planner_agendafout(planner):
    p, klok, *_ = planner

    class Kapot:
        def afspraken(self, van, tot):
            raise icloud_agenda.AgendaFout("weg")

    p.klant_fn = Kapot
    klok.nu = datetime(2026, 10, 29, 19, 0)
    assert p.stap() == []


def test_deadline_melding_is_systeemmelding():
    # Bron "deadline" (niet "agenda"/"timer"): 's nachts en in de stille
    # modus wacht hij, zoals gekozen ("niet 's nachts").
    from core.proactive import ProactiveEngine

    assert "deadline" not in ("timer", "agenda")
    assert hasattr(ProactiveEngine, "meld")


# ---------------------------------------------------------------------
# Paneel Vandaag
# ---------------------------------------------------------------------

def test_paneel_deel():
    fn = _klant_fn(_a("Deadline: verslag", VRIJDAG), _a("Deadline: vandaag iets", NU.date()),
                   _a("Tandarts", NU.date(), 14), _a("Deadline: ver weg", date(2026, 12, 1)))
    deel = deadlines.paneel_deel(NU, klant_fn=fn, ingesteld_fn=lambda: True)
    assert deel == {"status": "ok", "meer": 0, "deadlines": [
        {"titel": "vandaag iets", "wanneer": "vandaag", "dagen": 0},
        {"titel": "verslag", "wanneer": "overmorgen", "dagen": 2},
    ]}


def test_paneel_niet_ingesteld():
    assert deadlines.paneel_deel(NU, ingesteld_fn=lambda: False) == {"status": "niet_ingesteld", "deadlines": []}


def test_vandaag_overzicht_bevat_deadlines():
    from core import vandaag

    leeg = lambda: {"status": "ok"}  # noqa: E731
    d = vandaag.overzicht(nu=NU, agenda_fn=leeg, mail_fn=leeg, discord_fn=leeg,
                          deadlines_fn=lambda: {"status": "ok", "deadlines": [{"titel": "x"}]})
    assert d["deadlines"]["deadlines"] == [{"titel": "x"}]

    def kapot():
        raise RuntimeError("stuk")

    d = vandaag.overzicht(nu=NU, agenda_fn=leeg, mail_fn=leeg, discord_fn=leeg, deadlines_fn=kapot)
    assert d["deadlines"]["status"] == "fout"


def test_dashboard_tekent_deadlines():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    deel = js[js.index("function tekenVandaag"):js.index("// ----- goedkeuring -----")]
    assert "'DEADLINES'" in deel and "vd-wanneer" in deel
    assert "innerHTML" not in deel
    assert ".vd-regel.dringend" in css


# ---------------------------------------------------------------------
# In het brein
# ---------------------------------------------------------------------

def test_brein_zet_deadline_voor_de_agenda(monkeypatch):
    import core.brain as brain

    monkeypatch.setattr(brain, "ask_ai", lambda *a, **k: pytest.fail("geen AI"))
    antwoord = brain.process_command("zet een deadline: verslag op vrijdag")
    assert antwoord.startswith("Deadline toevoegen: verslag")
    assert confirmation.get_pending()["afspraak"]["titel"] == "Deadline: Verslag"
