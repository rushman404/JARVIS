"""Fase 23, M7 — dashboardpaneel Vandaag: agenda, belangrijke mail, nieuwe DM's."""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import discord_dms, vandaag
from core.result_validation import ToolResult

STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"
NU = datetime(2026, 10, 28, 12, 0)


def _afspraak(titel, uur, duur=1, plaats=None, hele_dag=False):
    start = NU.replace(hour=uur, minute=0)
    return {"titel": titel, "start": start, "eind": start + timedelta(hours=duur), "plaats": plaats,
            "hele_dag": hele_dag, "uid": titel}


class AgendaKlant:
    def __init__(self, lijst):
        self.lijst = lijst
        self.gevraagd = None

    def afspraken(self, van, tot):
        self.gevraagd = (van, tot)
        return self.lijst


class Reis:
    def minuten(self, plaats):
        return 23 if plaats else None


class MailKlant:
    def __init__(self, koppen, gekoppeld=True):
        self.koppen = {k["id"]: k for k in koppen}
        self.gekoppeld = gekoppeld

    def is_gekoppeld(self):
        return self.gekoppeld

    def zoek(self, q, maximaal=10):
        return list(self.koppen)[:maximaal]

    def kop(self, id_):
        return self.koppen[id_]


def _kop(id_, van, onderwerp, belangrijk=True):
    return {"id": id_, "van": van, "adres": f"{van.lower()}@x.nl", "onderwerp": onderwerp,
            "labels": ["IMPORTANT"] if belangrijk else [], "fragment": "", "ontvangen": 0}


# -----------------------------------------------------------------
# Agenda
# -----------------------------------------------------------------

def test_agenda_van_vandaag_met_vertrek():
    klant = AgendaKlant([_afspraak("Wiskunde", 9), _afspraak("Tandarts", 14, plaats="Breda"),
                         _afspraak("Verjaardag", 0, hele_dag=True)])
    deel = vandaag.agenda_deel(NU, klant_fn=lambda: klant, reistijden=Reis(), ingesteld_fn=lambda: True)
    assert klant.gevraagd == (datetime(2026, 10, 28), datetime(2026, 10, 29))
    assert deel["status"] == "ok" and deel["meer"] == 0
    assert [(a["tijd"], a["titel"], a["voorbij"]) for a in deel["afspraken"]] == [
        ("09:00", "Wiskunde", True), ("14:00", "Tandarts", False), (None, "Verjaardag", False)]
    assert deel["afspraken"][1]["plaats"] == "Breda"
    assert deel["vertrek"] == {"titel": "Tandarts", "om": "13:35", "minuten": 25}


def test_agenda_niet_ingesteld_en_te_veel():
    assert vandaag.agenda_deel(NU, ingesteld_fn=lambda: False)["status"] == "niet_ingesteld"
    klant = AgendaKlant([_afspraak(f"A{i}", 13 + i % 10) for i in range(9)])
    deel = vandaag.agenda_deel(NU, klant_fn=lambda: klant, reistijden=Reis(), ingesteld_fn=lambda: True)
    assert len(deel["afspraken"]) == vandaag.MAX_AFSPRAKEN and deel["meer"] == 3
    assert deel["vertrek"] is None


# -----------------------------------------------------------------
# Mail
# -----------------------------------------------------------------

def test_mail_alleen_belangrijk_en_ingekort(monkeypatch):
    import config

    monkeypatch.setattr(config, "GMAIL_BELANGRIJKE_AFZENDERS", [])
    monkeypatch.setattr(config, "GMAIL_LABEL_BELANGRIJK", True)
    klant = MailKlant([_kop("1", "School", "Rooster " + "x" * 200), _kop("2", "Reclame", "Korting", False),
                       _kop("3", "Mama", "Eten"), _kop("4", "Coach", "Training"), _kop("5", "Bank", "Pas")])
    deel = vandaag.mail_deel(lambda: klant)
    assert deel["status"] == "ok" and deel["aantal"] == 4
    assert [m["van"] for m in deel["mails"]] == ["School", "Mama", "Coach"]
    assert len(deel["mails"][0]["onderwerp"]) == 80 and deel["mails"][0]["onderwerp"].endswith("…")


def test_mail_niet_gekoppeld():
    assert vandaag.mail_deel(lambda: MailKlant([], gekoppeld=False))["status"] == "niet_gekoppeld"


# -----------------------------------------------------------------
# Discord
# -----------------------------------------------------------------

def _dm(id_, van, tekst):
    return {"id": str(id_), "van": van, "tekst": tekst, "tijd": None}


@pytest.fixture
def gezien(monkeypatch, tmp_path):
    pad = str(tmp_path / "discord_gezien.json")
    monkeypatch.setattr(discord_dms, "GEZIEN_FILE", pad)
    return pad


def _dc_klant(dms):
    return discord_dms.DiscordKlant(pc_fn=lambda t, a: ToolResult(True, "ok", data={"dms": dms}))


def test_discord_nieuw_en_niets_gemarkeerd(gezien):
    dms = [_dm(4, "Lisa", "d"), _dm(3, "Sem", "c"), _dm(2, "Sem", "b"), _dm(1, "Sem", "a")]
    discord_dms.markeer_gelezen([dms[3]], gezien)
    deel = vandaag.discord_deel(klant_fn=lambda: _dc_klant(dms), online_fn=lambda: True)
    assert deel["status"] == "ok" and deel["aantal"] == 3
    assert [(d["van"], d["tekst"]) for d in deel["dms"]] == [("Sem", "b"), ("Sem", "c"), ("Lisa", "d")]
    # Het paneel leest niets "voor": de vraag geeft ze nog steeds als nieuw.
    assert [d["id"] for d in discord_dms.ongelezen(dms, gezien)] == ["4", "3", "2"]


@pytest.mark.parametrize("online,status", [(None, "niet_gebruikt"), (False, "uit")])
def test_discord_game_pc_niet_beschikbaar(online, status):
    def klant():
        raise AssertionError("niet aanroepen")

    assert vandaag.discord_deel(klant_fn=klant, online_fn=lambda: online)["status"] == status


def test_discord_agent_antwoordt_niet(gezien):
    klant = discord_dms.DiscordKlant(pc_fn=lambda t, a: ToolResult(False, "weg"))
    assert vandaag.discord_deel(klant_fn=lambda: klant, online_fn=lambda: True)["status"] == "uit"


# -----------------------------------------------------------------
# Samen, cache, API
# -----------------------------------------------------------------

def test_een_fout_raakt_de_andere_bronnen_niet():
    def kapot():
        raise RuntimeError("weg")

    d = vandaag.overzicht(NU, agenda_fn=kapot, mail_fn=lambda: {"status": "ok", "aantal": 0, "mails": []},
                          discord_fn=lambda: {"status": "uit", "aantal": 0, "dms": []})
    assert d["datum"] == "2026-10-28"
    assert d["agenda"] == {"status": "fout", "afspraken": [], "vertrek": None}
    assert d["mail"]["status"] == "ok" and d["discord"]["status"] == "uit"


def test_bronnen_cachen_vandaag():
    from dashboard.bronnen import TTL_VANDAAG, Bronnen

    tijd = [1000.0]
    aanroepen = []
    b = Bronnen(vandaag_fn=lambda: aanroepen.append(1) or {"n": len(aanroepen)}, clock=lambda: tijd[0])
    assert b.vandaag() == {"n": 1} and b.vandaag() == {"n": 1}
    tijd[0] += TTL_VANDAAG + 1
    assert b.vandaag() == {"n": 2}


def test_api_vandaag():
    from dashboard.api import DashboardAPI

    class B:
        def vandaag(self):
            return {"datum": "2026-10-28"}

    api = DashboardAPI(bronnen=B(), spreekt_fn=lambda: False, fase_fn=lambda: "rust",
                       pc_target_fn=lambda: "local", audit_fn=lambda **v: None)
    assert api.vandaag() == (200, {"datum": "2026-10-28"})


def test_dagstart_gebruikt_dezelfde_mailselectie(monkeypatch):
    from core import agenda_herinneringen, gmail

    monkeypatch.setattr(gmail, "belangrijke_ongelezen", lambda klant: [_kop("1", "School", "Rooster")])
    assert agenda_herinneringen._mail_delen(object()) == ["1 belangrijke mail, van School: Rooster."]


# -----------------------------------------------------------------
# Indeling
# -----------------------------------------------------------------

@pytest.mark.parametrize("oud,midden", [
    ({"versie": 1, "kolommen": {"midden": ["gesprek", "auditlog"]}}, ["gesprek", "routines", "vandaag"]),
    ({"versie": 2, "kolommen": {"midden": ["gesprek", "routines", "auditlog"]}}, ["gesprek", "routines", "vandaag"]),
    ({"versie": 2, "kolommen": {"midden": ["auditlog", "gesprek"]}}, ["vandaag", "gesprek"]),
    ({"versie": 2, "kolommen": {"midden": ["gesprek"]}}, ["gesprek", "vandaag"]),
    ({"versie": 2, "kolommen": {"links": ["vandaag"], "midden": ["auditlog"]}}, ["auditlog"]),
    ({"versie": 3, "kolommen": {"midden": ["auditlog"]}}, ["auditlog"]),
])
def test_oude_indeling_krijgt_vandaag(oud, midden):
    from dashboard.api import _valideer_widgets, _werk_widgets_bij

    nieuw = _werk_widgets_bij(oud)
    assert nieuw["versie"] == 3 and nieuw["kolommen"]["midden"] == midden
    assert _valideer_widgets(nieuw) is None


def test_paneel_in_de_frontend():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert 'data-widget="vandaag"' in html and 'id="vandaag"' in html
    assert "['vandaag', 'Vandaag']" in app and "'/api/vandaag'" in app
    # Uitgezette panelen verdwijnen echt (display:flex won eerst van [hidden]).
    assert ".panel.audit[hidden], .panel.vandaag[hidden] { display: none; }" in css
    # Geen HTML uit data in het nieuwe paneel.
    deel = app[app.index("function tekenVandaag"):app.index("// ----- goedkeuring -----")]
    assert "innerHTML" not in deel


def test_versie_is_overal_gelijk_aan_api():
    from dashboard.api import API_VERSIE

    assert API_VERSIE == "24.2"
    for naam in ("index.html", "koppel.html", "spraak.html", "spraak-proef.html", "sw.js"):
        tekst = (STATIC / naam).read_text(encoding="utf-8")
        assert set(re.findall(r"\?v=([\d.]+)", tekst)) <= {"24.2"}, naam
    assert "var VERSIE = '24.2';" in (STATIC / "app.js").read_text(encoding="utf-8")
    assert "jarvis-shell-24.2" in (STATIC / "sw.js").read_text(encoding="utf-8")
