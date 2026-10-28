"""Fase 23, M5 — herinneringen vooraf, reistijd en de dagstart met agenda en mail."""

from datetime import datetime, timedelta

import pytest

from core import agenda_herinneringen as ah
from core import koppelingen as kp

NU = datetime(2026, 10, 28, 13, 0)


def _afspraak(titel="Tandarts", start=datetime(2026, 10, 28, 14, 0), duur=60, plaats="", uid=None,
              hele_dag=False):
    return {"uid": uid or titel.lower(), "titel": titel, "start": start, "eind": start + timedelta(minutes=duur),
            "plaats": plaats, "hele_dag": hele_dag}


class NepAgenda:
    def __init__(self, afspraken=(), fout=None):
        self.lijst = list(afspraken)
        self.fout = fout
        self.opgehaald = 0

    def afspraken(self, van, tot):
        self.opgehaald += 1
        if self.fout:
            raise self.fout
        return [a for a in self.lijst
                if (a["eind"] if not a["hele_dag"] else datetime.combine(a["eind"], datetime.min.time())) > van
                and (a["start"] if not a["hele_dag"] else datetime.combine(a["start"], datetime.min.time())) < tot]


class Klok:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _ingesteld(monkeypatch):
    import config

    monkeypatch.setattr(config, "ICLOUD_GEBRUIKER", "rushil@icloud.com")
    monkeypatch.setattr(config, "ICLOUD_APP_WACHTWOORD", "abcd-efgh-ijkl-mnop")
    monkeypatch.setattr(config, "THUIS_ADRES", "Thuisstraat 1, Breda")
    monkeypatch.setattr(config, "GMAIL_BELANGRIJKE_AFZENDERS", ["school"])
    monkeypatch.setattr(config, "GMAIL_LABEL_BELANGRIJK", False)


def _reis(minuten_per_plaats):
    gevraagd = []

    def reken(van, naar):
        gevraagd.append((van, naar))
        m = minuten_per_plaats.get(naar)
        return {"ok": True, "minuten": m} if m else {"ok": False, "error": "niet gevonden"}

    return ah.Reistijden(reken_fn=reken), gevraagd


def _planner(tmp_path, agenda, klok, reistijden=None, minuten=15):
    meldingen = []
    planner = ah.HerinneringPlanner(
        meld_fn=lambda tekst, bron: meldingen.append((tekst, bron)), klant_fn=lambda: agenda,
        reistijden=reistijden or _reis({})[0], klok=klok, minuten=minuten,
        herinnerd_pad=str(tmp_path / "herinnerd.json"))
    return planner, meldingen


# -----------------------------------------------------------------
# Reistijd
# -----------------------------------------------------------------

def test_reistijd_probeert_steeds_korter_adres_en_onthoudt():
    reistijden, gevraagd = _reis({"Markt 1, Breda": 22})
    assert reistijden.minuten("Tandarts De Kies, Markt 1, Breda") == 22
    assert gevraagd == [("Thuisstraat 1, Breda", "Tandarts De Kies, Markt 1, Breda"),
                        ("Thuisstraat 1, Breda", "Markt 1, Breda")]
    assert reistijden.minuten("tandarts de kies, markt 1, breda") == 22
    assert len(gevraagd) == 2  # uit het geheugen


def test_reistijd_onzin_en_zonder_thuis(monkeypatch):
    import config

    reistijden, _ = _reis({"Tokio": 9000})
    assert reistijden.minuten("Tokio") is None  # meer dan 4 uur: vast een verkeerde plaats
    monkeypatch.setattr(config, "THUIS_ADRES", "")
    monkeypatch.setattr(config, "WEER_PLAATS", "")
    assert _reis({"Breda": 20})[0].minuten("Breda") is None


def test_vertrek_rondt_op_vijf_minuten_af():
    reistijden, _ = _reis({"Breda": 22})
    assert ah.vertrek(_afspraak(plaats="Breda"), reistijden) == (datetime(2026, 10, 28, 13, 35), 25)
    assert ah.vertrek(_afspraak(), reistijden) == (None, None)


# -----------------------------------------------------------------
# Herinneren
# -----------------------------------------------------------------

def test_herinnering_kwartier_vooraf_een_keer(tmp_path):
    agenda = NepAgenda([_afspraak()])
    klok = Klok(datetime(2026, 10, 28, 13, 44))
    planner, meldingen = _planner(tmp_path, agenda, klok)
    assert planner.stap() == []
    klok.t = datetime(2026, 10, 28, 13, 45)
    planner.stap()
    assert meldingen == [("Sir, over 15 minuten: Tandarts (om 14:00).", "agenda")]
    klok.t = datetime(2026, 10, 28, 13, 50)
    planner.stap()
    # Ook na een herstart niet nog eens (onthouden in een bestand).
    planner2, meldingen2 = _planner(tmp_path, agenda, klok)
    planner2.stap()
    assert len(meldingen) == 1 and meldingen2 == []


def test_herinnering_met_reistijd(tmp_path):
    agenda = NepAgenda([_afspraak(plaats="Breda")])
    reistijden, _ = _reis({"Breda": 22})
    klok = Klok(datetime(2026, 10, 28, 13, 19))
    planner, meldingen = _planner(tmp_path, agenda, klok, reistijden)
    planner.stap()
    assert meldingen == []
    klok.t = datetime(2026, 10, 28, 13, 20)
    planner.stap()
    assert meldingen == [("Sir, om 14:00 heeft u Tandarts in Breda.\n"
                          "Het is ongeveer 25 minuten rijden; u moet over 15 minuten weg (om 13:35).", "agenda")]


def test_te_laat_gestart_zegt_nu_weg(tmp_path):
    agenda = NepAgenda([_afspraak(plaats="Breda")])
    reistijden, _ = _reis({"Breda": 22})
    planner, meldingen = _planner(tmp_path, agenda, Klok(datetime(2026, 10, 28, 13, 40)), reistijden)
    planner.stap()
    assert meldingen[0][0].endswith("u moet nu weg.")


def test_geen_herinnering_voor_hele_dag_of_voorbij(tmp_path):
    agenda = NepAgenda([_afspraak("Vrij", start=datetime(2026, 10, 28), hele_dag=True),
                        _afspraak("Al geweest", start=datetime(2026, 10, 28, 12, 50))])
    agenda.lijst[0]["start"] = agenda.lijst[0]["start"].date()
    agenda.lijst[0]["eind"] = agenda.lijst[0]["start"] + timedelta(days=1)
    planner, meldingen = _planner(tmp_path, agenda, Klok(NU))
    planner.stap()
    assert meldingen == []


def test_uit_of_niet_ingesteld(tmp_path, monkeypatch):
    import config

    agenda = NepAgenda([_afspraak(start=datetime(2026, 10, 28, 13, 5))])
    planner, meldingen = _planner(tmp_path, agenda, Klok(NU), minuten=0)
    planner.stap()
    monkeypatch.setattr(config, "ICLOUD_APP_WACHTWOORD", "")
    planner2, meldingen2 = _planner(tmp_path, agenda, Klok(NU))
    planner2.stap()
    assert meldingen == meldingen2 == [] and agenda.opgehaald == 0


def test_agenda_niet_elke_minuut_opgehaald_en_fout_eenmalig(tmp_path, caplog):
    agenda = NepAgenda([_afspraak(start=datetime(2026, 10, 28, 18))])
    klok = Klok(NU)
    planner, _ = _planner(tmp_path, agenda, klok)
    for minuut in range(4):
        klok.t = NU + timedelta(minutes=minuut)
        planner.stap()
    assert agenda.opgehaald == 1
    klok.t = NU + timedelta(minutes=6)
    agenda.fout = kp.KoppelFout("iCloud reageerde niet (Timeout).", "netwerk")
    planner.stap()
    klok.t = NU + timedelta(minutes=12)
    planner.stap()
    assert sum("Agenda ophalen" in r.message for r in caplog.records) == 1


def test_agenda_herinnering_klinkt_ook_in_stille_modus():
    from core import proactive

    melding = proactive.Melding("x", bron="agenda")
    assert melding.prioriteit == "gebruiker"


# -----------------------------------------------------------------
# Dagstart
# -----------------------------------------------------------------

class NepGmail:
    def __init__(self, koppen=(), gekoppeld=True):
        self.koppen = list(koppen)
        self.gekoppeld = gekoppeld

    def is_gekoppeld(self):
        return self.gekoppeld

    def zoek(self, q, maximaal=10):
        return [k["id"] for k in self.koppen][:maximaal]

    def kop(self, id_):
        return next(k for k in self.koppen if k["id"] == id_)


def _mailkop(id_, van, adres, onderwerp):
    return {"id": id_, "van": van, "adres": adres, "onderwerp": onderwerp, "labels": [], "fragment": ""}


def test_dagstart_met_afspraken_vertrek_en_mail():
    agenda = NepAgenda([_afspraak(plaats="Breda"), _afspraak("Voetbal", start=datetime(2026, 10, 28, 19))])
    mail = NepGmail([_mailkop("1", "School", "info@school.nl", "Rooster gewijzigd"),
                     _mailkop("2", "Shop", "deals@shop.nl", "Korting")])
    reistijden, _ = _reis({"Breda": 22})
    regels = ah.dagstart_delen(datetime(2026, 10, 28, 8, 0), agenda_fn=lambda: agenda, gmail_fn=lambda: mail,
                               reistijden=reistijden)
    assert regels == [
        "Vandaag heeft u 2 afspraken:",
        "14:00 tot 15:00: Tandarts, in Breda.",
        "19:00 tot 20:00: Voetbal.",
        "Voor Tandarts moet u om 13:35 weg (ongeveer 25 minuten rijden).",
        "Er is 1 belangrijke mail:",
        "Van School: Rooster gewijzigd.",
    ]


def test_dagstart_zonder_koppelingen_en_bij_fouten(monkeypatch):
    import config

    leeg = ah.dagstart_delen(NU, agenda_fn=lambda: NepAgenda(), gmail_fn=lambda: NepGmail())
    assert leeg == ["Vandaag staat er niets in uw agenda.", "Geen nieuwe belangrijke mail."]
    kapot = ah.dagstart_delen(NU, agenda_fn=lambda: NepAgenda(fout=kp.KoppelFout("weg")),
                              gmail_fn=lambda: NepGmail(gekoppeld=False))
    assert kapot == ["Uw agenda kon ik nu niet bereiken."]
    monkeypatch.setattr(config, "ICLOUD_APP_WACHTWOORD", "")
    assert ah.dagstart_delen(NU, gmail_fn=lambda: NepGmail(gekoppeld=False)) == []


def test_dagstart_tekst_bevat_de_agenda(monkeypatch):
    from core import proactive_commands

    monkeypatch.setattr(ah, "dagstart_delen", lambda: ["Vandaag heeft u 1 afspraak:", "14:00 tot 15:00: Tandarts."])
    tekst = proactive_commands._dagstart_tekst()
    assert "\nVandaag heeft u 1 afspraak:\n14:00 tot 15:00: Tandarts.\n" in tekst


def test_wat_staat_er_vandaag_op_de_planning_is_de_dagstart(monkeypatch):
    from core import brain, icloud_agenda

    monkeypatch.setattr(ah, "dagstart_delen", lambda: ["AGENDA-REGEL"])
    monkeypatch.setattr(icloud_agenda, "AgendaKlant", lambda *a, **k: NepAgenda())
    assert "AGENDA-REGEL" in brain.process_command("wat staat er vandaag op de planning?")
    assert "AGENDA-REGEL" in brain.process_command("goedemorgen")
