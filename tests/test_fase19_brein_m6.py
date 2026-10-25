"""Fase 19, M6 — verbindingsbewaking en updates met goedkeuring."""

import json
import os

import pytest

from beheer import updates, verbinding, waakhond
from core import confirmation, proactive


# ---------------------------------------------------------------
# Verbindingen
# ---------------------------------------------------------------

class Klok:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_wachter_probeert_met_oplopende_pauze():
    klok = Klok()
    pogingen = []

    def probe():
        pogingen.append(klok.t)
        return False

    w = verbinding.Wachter(probe, klok=klok, wachttijden=(30, 60))
    assert w() is False
    klok.t += 10
    assert w() is False and len(pogingen) == 1  # nog in de pauze
    klok.t += 25
    assert w() is False and len(pogingen) == 2
    klok.t += 40
    assert len(pogingen) == 2 and w() is False and len(pogingen) == 2  # nu 60 s pauze
    klok.t += 30
    w()
    assert len(pogingen) == 3


def test_wachter_herstelt_en_fout_is_offline():
    klok = Klok()
    status = {"online": False}
    w = verbinding.Wachter(lambda: status["online"], klok=klok, wachttijden=(30,))
    assert w() is False
    status["online"] = True
    klok.t += 31
    assert w() is True
    assert w() is True  # online: elke keer echt kijken

    def stuk():
        raise ConnectionError

    assert verbinding.Wachter(stuk, klok=klok)() is False
    assert verbinding.Wachter(lambda: None, klok=klok)() is None


def test_internet_controle_zonder_dns():
    gezien = []

    class Sok:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def verbind(adres, timeout):
        gezien.append(adres)
        if adres[0] == "1.1.1.1":
            raise OSError
        return Sok()

    assert verbinding.internet_online(verbind=verbind) is True
    assert gezien == [("1.1.1.1", 443), ("8.8.8.8", 443)]

    def nooit(adres, timeout):
        raise OSError

    assert verbinding.internet_online(verbind=nooit) is False


def test_game_pc_niet_van_toepassing_bij_lokaal(monkeypatch):
    import config

    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    assert verbinding.game_pc_online() is None


def test_engine_meldt_verbinding_weg_en_terug(tmp_path):
    regels = {"regels": [
        {"id": "x_off", "actief": True, "trigger": {"type": "statuswijziging", "bron": "ollama",
                                                    "verwacht": False, "herhaal_seconden": 0},
         "melding": "AI weg", "voorwaarden": {}},
        {"id": "x_on", "actief": True, "trigger": {"type": "statuswijziging", "bron": "ollama",
                                                   "verwacht": True, "herhaal_seconden": 0},
         "melding": "AI terug", "voorwaarden": {}},
    ]}
    pad = tmp_path / "regels.json"
    pad.write_text(json.dumps(regels), encoding="utf-8")
    status = {"v": True}
    engine = proactive.ProactiveEngine(rules_pad=str(pad), status_checks={"ollama": lambda: status["v"]})

    t = regels["regels"]
    assert not engine._check_statuswijziging("off", t[0]["trigger"], 1)  # eerste meting
    assert not engine._check_statuswijziging("on", t[1]["trigger"], 1)
    status["v"] = False
    assert engine._check_statuswijziging("off", t[0]["trigger"], 2)
    assert not engine._check_statuswijziging("on", t[1]["trigger"], 2)
    status["v"] = True
    assert not engine._check_statuswijziging("off", t[0]["trigger"], 3)
    assert engine._check_statuswijziging("on", t[1]["trigger"], 3)


def test_regels_bestand_heeft_verbindingsregels():
    pad = os.path.join(updates.PROJECT, "config", "proactive_rules.json")
    regels = {r["id"]: r for r in json.load(open(pad, encoding="utf-8"))["regels"]}
    for bron in ("game_pc", "ollama", "internet"):
        assert regels[f"{bron}_offline"]["trigger"]["bron"] == bron
        assert regels[f"{bron}_online"]["trigger"]["verwacht"] is True


# ---------------------------------------------------------------
# Updates zoeken
# ---------------------------------------------------------------

class NepGit:
    def __init__(self, achter=2, voor=0, lokaal=""):
        self.achter = achter
        self.voor = voor
        self.lokaal = lokaal
        self.aanroepen = []

    def __call__(self, *args):
        self.aanroepen.append(args)
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "jarvis-v1/main"
        if args[0] == "fetch":
            return ""
        if args[:2] == ("rev-list", "--count"):
            return str(self.achter if args[2] == "HEAD..@{u}" else self.voor)
        if args[0] == "rev-parse":
            return "abc123"
        if args[0] == "log":
            return "feat(fase19): M6 updates\nfix: kleine fout\n"
        if args[0] == "status":
            return self.lokaal
        if args[0] == "merge":
            return ""
        raise AssertionError(args)


def test_zoek_updates():
    git = NepGit()
    info = updates.zoek_updates(git=git)
    assert info == {"upstream": "jarvis-v1/main", "sha": "abc123", "aantal": 2,
                    "wijzigingen": ["feat(fase19): M6 updates", "fix: kleine fout"]}
    assert ("fetch", "--quiet", "jarvis-v1") in git.aanroepen


def test_controleer_meldt_een_keer_per_versie(tmp_path):
    pad = str(tmp_path / "updates.json")
    zoek = lambda: updates.zoek_updates(git=NepGit())  # noqa: E731
    eerste = updates.controleer(nu=1, status_pad=pad, zoek_fn=zoek)
    tweede = updates.controleer(nu=2, status_pad=pad, zoek_fn=zoek)
    assert eerste["nieuw_te_melden"] and not tweede["nieuw_te_melden"]
    tekst = updates.melding_tekst(eerste)
    assert "2 wijzigingen" in tekst and "M6 updates" in tekst and "feat(" not in tekst


def test_controleer_fout_gooit_niet(tmp_path):
    def stuk():
        raise updates.UpdateFout("geen internet")

    st = updates.controleer(nu=1, status_pad=str(tmp_path / "u.json"), zoek_fn=stuk)
    assert st["fout"] == "geen internet" and not st["nieuw_te_melden"]


# ---------------------------------------------------------------
# Installeren
# ---------------------------------------------------------------

def test_kan_installeren():
    assert updates.kan_installeren(NepGit()) is None
    assert "lokale wijzigingen" in updates.kan_installeren(NepGit(lokaal=" M main.py"))
    assert "eigen commits" in updates.kan_installeren(NepGit(voor=1))
    assert "geen nieuwe versie" in updates.kan_installeren(NepGit(achter=0))


def test_installeer_maakt_eerst_backup_en_alleen_fast_forward(tmp_path):
    git = NepGit()
    volgorde = []
    aantal = updates.installeer(git=lambda *a: (volgorde.append(a[0]), git(*a))[1],
                                backup_fn=lambda: (volgorde.append("backup"), (True, {}))[1],
                                pip_fn=lambda p: volgorde.append("pip"), project=str(tmp_path))
    assert aantal == 2
    assert volgorde.index("backup") < volgorde.index("merge")
    assert ("merge", "--ff-only", "@{u}") in git.aanroepen
    assert "pip" not in volgorde  # requirements niet veranderd


def test_installeer_pip_als_requirements_veranderen(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("a==1\n", encoding="utf-8")
    git = NepGit()

    def git_met_wijziging(*args):
        if args[0] == "merge":
            req.write_text("a==2\n", encoding="utf-8")
        return git(*args)

    pip = []
    updates.installeer(git=git_met_wijziging, backup_fn=lambda: (True, {}),
                       pip_fn=lambda p: pip.append(p), project=str(tmp_path))
    assert pip == [str(tmp_path)]


def test_installeer_niet_zonder_backup():
    git = NepGit()
    with pytest.raises(updates.UpdateFout, match="backup"):
        updates.installeer(git=git, backup_fn=lambda: (False, "schijf vol"), pip_fn=lambda p: None)
    assert not any(a[0] == "merge" for a in git.aanroepen)


def test_voer_uit_na_goedkeuring(tmp_path, monkeypatch):
    pad = str(tmp_path / "u.json")
    herstart = []
    monkeypatch.setenv("JARVIS_WAAKHOND", "1")
    tekst = updates.voer_uit_na_goedkeuring(installeer_fn=lambda: 3, herstart_fn=lambda: herstart.append(1),
                                           status_pad=pad)
    assert "geïnstalleerd" in tekst and herstart == [1]
    assert json.loads(open(pad, encoding="utf-8").read())["aantal"] == 0

    monkeypatch.delenv("JARVIS_WAAKHOND")
    tekst = updates.voer_uit_na_goedkeuring(installeer_fn=lambda: 3, herstart_fn=lambda: herstart.append(2),
                                           status_pad=pad)
    assert "Herstart JARVIS" in tekst and herstart == [1]

    def weigert():
        raise updates.UpdateFout("er zijn lokale wijzigingen")

    assert "niet geïnstalleerd" in updates.voer_uit_na_goedkeuring(installeer_fn=weigert, status_pad=pad)


def test_plan_herstart_gebruikt_exitcode():
    codes = []
    import threading

    klaar = threading.Event()
    updates.plan_herstart(vertraging=0, exit_fn=lambda c: (codes.append(c), klaar.set()))
    klaar.wait(2)
    assert codes == [5]
    assert updates.EXIT_HERSTART == waakhond.EXIT_HERSTART == 5


# ---------------------------------------------------------------
# Goedkeuring, spraak en waakhond
# ---------------------------------------------------------------

def test_update_vraagt_altijd_een_ja(tmp_path, monkeypatch):
    pad = str(tmp_path / "u.json")
    monkeypatch.setattr(updates, "STATUS_FILE", pad)
    updates._schrijf_status({"aantal": 2, "wijzigingen": ["fix: x"]}, pad)
    pending, vraag = updates.vraag_goedkeuring(status_pad=pad)
    assert pending["kind"] == "update_confirm" and "2 wijzigingen" in vraag
    assert confirmation.is_dangerous_kind("update_confirm")
    assert "update_confirm" in confirmation.JA_NEE_KINDS
    beschrijving = confirmation.beschrijf_pending()
    assert beschrijving["soort"] == "update_confirm" and beschrijving["risico"] == "high"
    confirmation.clear_pending()

    updates._schrijf_status({"aantal": 0}, pad)
    pending, vraag = updates.vraag_goedkeuring(status_pad=pad)
    assert pending is None and "geen nieuwe versie" in vraag


def test_besluit_ja_en_nee(monkeypatch):
    from core import brain

    gedaan = []
    monkeypatch.setattr(updates, "voer_uit_na_goedkeuring", lambda: gedaan.append(1) or "klaar")
    assert brain.voer_besluit_uit({"kind": "update_confirm"}, True) == "klaar"
    assert "niet" in brain.voer_besluit_uit({"kind": "update_confirm"}, False)
    assert gedaan == [1]


def test_spraakcommandos(monkeypatch):
    monkeypatch.setattr(updates, "vraag_goedkeuring", lambda: (None, "VRAAG"))
    assert updates.probeer_commando("installeer de update") == "VRAAG"
    assert updates.probeer_commando("update jarvis") == "VRAAG"
    monkeypatch.setattr(updates, "controleer",
                        lambda zoek_fn=None: {"aantal": 0, "fout": None})
    assert "up-to-date" in updates.probeer_commando("zijn er updates?")
    assert updates.probeer_commando("zet een timer van vijf minuten") is None
    assert updates.probeer_commando("update de lampen") is None


def test_waakhond_herstart_meteen_na_update(tmp_path):
    from tests.test_fase19_brein_m2 import _waakhond

    wh, popen, klok = _waakhond(tmp_path, [[5], [0]])
    begin = klok.t
    assert wh.draai(max_controles=10) == 0
    assert len(popen.starts) == 2
    assert popen.starts[1]["JARVIS_HERSTART_REDEN"] == "update geïnstalleerd"
    assert wh.totaal_herstarts == 0  # telt niet als crash
    assert klok.t - begin < 3 * waakhond.CONTROLE_INTERVAL  # geen wachttijd


# ---------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------

def test_dashboard_update_aanvraag(monkeypatch):
    from dashboard.api import DashboardAPI

    api = DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False, audit_fn=lambda **k: None)
    monkeypatch.setattr(updates, "vraag_goedkeuring", lambda: ({confirmation.ID_KEY: "p9"}, "vraag"))
    assert api.update({}) == (202, {"ok": True, "id": "p9"})
    monkeypatch.setattr(updates, "vraag_goedkeuring", lambda: (None, "Er is geen nieuwe versie van JARVIS, sir."))
    assert api.update({})[0] == 409


def test_dashboard_route_alleen_bedienen():
    import inspect

    from dashboard.server import DashboardServer

    # b = de bedien-rol: met alleen het kijk-token kan niemand een update aanvragen.
    assert '("POST", "/api/update"): (b,' in inspect.getsource(DashboardServer)


def test_pwa_update_knop():
    js = open(os.path.join(updates.PROJECT, "dashboard", "static", "app.js"), encoding="utf-8").read()
    assert "function vraagUpdate(" in js and "'/api/update'" in js
    assert "knop alleen-bedien', 'Installeren…'" in js
