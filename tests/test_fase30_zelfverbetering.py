"""Fase 30 — Self-Evolution: JARVIS verbetert zijn eigen herkenning.

Gemini, de test-suite en de JARVIS-repo zelf worden nooit echt gebruikt:
git draait alleen in een tijdelijke repo met een eigen nep-"GitHub".
"""

import json
import os
import shutil
import subprocess
from datetime import datetime

import pytest

from core import commando_correctie as cc
from core import confirmation
from core import zelfverbetering as zv

DATA = {
    "_uitleg": "test",
    "opvulwoorden": ["even"],
    "korte_vormen": {"an": "aan"},
    "werkwoorden": ["zet", "doe", "open"],
    "basiswoorden": ["de", "aan", "uit", "muziek", "harder"],
    "namen": ["spotify"],
    "herkenners": {"media": ["zet de muziek harder"], "slim_huis": ["zet {naam} aan"]},
}


@pytest.fixture(autouse=True)
def schoon():
    confirmation.clear_pending()
    yield
    confirmation.clear_pending()


# ---------------------------------------------------------------------
# M1 — missers
# ---------------------------------------------------------------------

def _missers_data():
    return {
        "geleerd": {"zet spotie aan": {"commando": "open spotify"}},
        "missers": {
            "knal de muziek harder": {"keer": 3, "uitkomsten": {"onbekend": 3}},
            "zet spotie aan": {"keer": 4, "uitkomsten": {"onbekend": 4}},
            "doe de lamp an": {"keer": 2, "uitkomsten": {"direct": 2}},
            "een keer": {"keer": 1, "uitkomsten": {"onbekend": 1}},
            "bel mijn moeder": {"keer": 5, "uitkomsten": {"onbekend": 5}},
            "schreeuw de muziek harder": {"keer": 2, "uitkomsten": {"gevraagd": 1, "nee": 1},
                                          "bedoeld": "zet de muziek harder"},
        },
    }


def test_verzamel_missers():
    missers = zv.verzamel_missers(
        behandeld=["schreeuw de muziek harder"], lees_fn=_missers_data,
        privacy_fn=lambda z: "moeder" not in z)
    assert [m["zin"] for m in missers] == ["knal de muziek harder"]


def test_verzamel_missers_echte_privacy_poort():
    missers = zv.verzamel_missers(lees_fn=_missers_data)
    assert "bel mijn moeder" not in [m["zin"] for m in missers]


# ---------------------------------------------------------------------
# M1 — nakijken
# ---------------------------------------------------------------------

def test_valideer_schoon():
    aanvulling, fout = zv.valideer({
        "herkenners": {"media": ["Knal de muziek harder", "zet de muziek harder"]},
        "werkwoorden": ["knal", "zet"], "korte_vormen": {"ann": "aan", "an": "aan"},
        "uitleg": "  Voortaan  begrijp ik 'knal'. ",
    }, DATA)
    assert fout is None
    assert aanvulling == {"werkwoorden": ["knal"], "korte_vormen": {"ann": "aan"},
                          "herkenners": {"media": ["knal de muziek harder"]},
                          "uitleg": "Voortaan begrijp ik 'knal'."}


@pytest.mark.parametrize("ruw,stuk", [
    ([], "geen JSON"),
    ({"python": "import os"}, "onbekende velden"),
    ({"herkenners": {"nieuw_soort": ["x"]}}, "onbekende soort"),
    ({"werkwoorden": ["twee woorden"]}, "ongeldig item"),
    ({"werkwoorden": ["zet"]}, "geen nieuwe"),
    ({"herkenners": {"media": ["zet {pad} aan"]}}, "ongeldige voorbeeldzin"),
    ({"herkenners": {"media": ["x" * 61]}}, "ongeldige voorbeeldzin"),
    ({"herkenners": {"media": ["rm -rf /; echo"]}}, "ongeldige voorbeeldzin"),
    ({"namen": [f"naam{i}" for i in range(30)]}, "te veel"),
    ({"korte_vormen": {"a b": "c"}}, "ongeldige korte vorm"),
])
def test_valideer_weigert(ruw, stuk):
    aanvulling, fout = zv.valideer(ruw, DATA)
    assert aanvulling is None and stuk in fout


def test_pas_toe_alleen_toevoegen():
    nieuw = zv.pas_toe(DATA, {"werkwoorden": ["knal"], "herkenners": {"media": ["knal de muziek harder"]},
                              "korte_vormen": {"ann": "aan"}})
    assert nieuw["werkwoorden"] == ["zet", "doe", "open", "knal"]
    assert nieuw["herkenners"]["media"] == ["zet de muziek harder", "knal de muziek harder"]
    assert nieuw["korte_vormen"] == {"an": "aan", "ann": "aan"}
    assert DATA["werkwoorden"] == ["zet", "doe", "open"]  # origineel onaangeroerd


def test_effect_meet_echt():
    missers = [{"zin": "knal de muziek harder", "keer": 3, "bedoeld": None}]
    nieuw = zv.pas_toe(DATA, {"korte_vormen": {"knal": "zet"}})
    verbeterd, slechter = zv.effect(missers, DATA, nieuw, namen=frozenset(["spotify"]))
    assert verbeterd == ["knal de muziek harder"] and slechter == []
    verbeterd, _ = zv.effect(missers, DATA, DATA, namen=frozenset(["spotify"]))
    assert verbeterd == []


def test_zoek_kandidaten_met_eigen_data_raakt_cache_niet():
    voor = cc.laad_voorbeelden()
    cc.zoek_kandidaten("knal de muziek harder", namen=["spotify"], data=zv.pas_toe(DATA, {"korte_vormen": {"knal": "zet"}}))
    assert cc.laad_voorbeelden() is voor


class NepGemini:
    def __init__(self, *antwoorden):
        self.antwoorden = list(antwoorden)
        self.berichten = []

    def __call__(self, berichten):
        self.berichten.append(berichten)
        a = self.antwoorden.pop(0)
        if isinstance(a, Exception):
            raise a
        return {"message": {"content": a if isinstance(a, str) else json.dumps(a)}}


MISSERS = [{"zin": "knal de muziek harder", "keer": 3, "bedoeld": None}]


def test_maak_voorstel_tweede_poging_goed():
    gem = NepGemini("dit is geen json", {"korte_vormen": {"knal": "zet"}, "uitleg": "Ik begrijp nu 'knal'."})
    voorstel, reden = zv.maak_voorstel(MISSERS, DATA, chat_fn=gem, beschikbaar_fn=lambda: True,
                                       namen=frozenset(["spotify"]))
    assert reden is None and voorstel["verbeterd"] == ["knal de muziek harder"]
    assert len(gem.berichten) == 2
    assert "niet bruikbaar" in gem.berichten[1][-1]["content"]


def test_maak_voorstel_hooguit_drie_verzoeken():
    gem = NepGemini("x", "y", "z", "nooit gevraagd")
    voorstel, reden = zv.maak_voorstel(MISSERS, DATA, chat_fn=gem, beschikbaar_fn=lambda: True)
    assert voorstel is None and len(gem.berichten) == zv.MAX_VERZOEKEN


def test_maak_voorstel_stopt_bij_limiet():
    from core import gemini

    gem = NepGemini(gemini.GeminiFout("limiet", gemini.LIMIET), {"korte_vormen": {"knal": "zet"}})
    voorstel, reden = zv.maak_voorstel(MISSERS, DATA, chat_fn=gem, beschikbaar_fn=lambda: True)
    assert voorstel is None and "limiet" in reden and len(gem.berichten) == 1


def test_maak_voorstel_zonder_effect_is_geen_voorstel():
    gem = NepGemini({"namen": ["netflix"]}, {"namen": ["netflix"]}, {"namen": ["netflix"]})
    voorstel, reden = zv.maak_voorstel(MISSERS, DATA, chat_fn=gem, beschikbaar_fn=lambda: True,
                                       namen=frozenset(["spotify"]))
    assert voorstel is None and "geen enkele misser" in reden


def test_zonder_gemini_geen_verzoek():
    gem = NepGemini()
    assert zv.maak_voorstel(MISSERS, DATA, chat_fn=gem, beschikbaar_fn=lambda: False)[0] is None
    assert gem.berichten == []


def test_naar_gemini_gaat_alleen_bestand_en_missers():
    berichten = zv.bouw_berichten(DATA, MISSERS)
    tekst = json.dumps(berichten, ensure_ascii=False)
    assert "knal de muziek harder" in tekst and '"_uitleg"' not in tekst
    from core import privacy_poort

    assert privacy_poort.controleer(berichten) == (True, "")


# ---------------------------------------------------------------------
# M2 + M3 — echte git in een tijdelijke repo
# ---------------------------------------------------------------------

def _run(*args, cwd):
    uit = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if uit.returncode != 0:
        raise zv.VerbeterFout(uit.stderr.strip() or uit.stdout.strip())
    return uit.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git ontbreekt")
    remote = tmp_path / "github.git"
    werk = tmp_path / "jarvis"
    _run("init", "-q", "--bare", str(remote), cwd=tmp_path)
    _run("init", "-q", "-b", "main", str(werk), cwd=tmp_path)
    os.makedirs(werk / "config")
    (werk / "config" / "commando_voorbeelden.json").write_text(json.dumps(DATA), encoding="utf-8")
    for a in (("config", "user.name", "Test"), ("config", "user.email", "t@t"),
              ("add", "."), ("commit", "-q", "-m", "begin"),
              ("remote", "add", "origin", str(remote)), ("push", "-q", "-u", "origin", "main")):
        _run(*a, cwd=werk)

    def git(*args, cwd=str(werk), timeout=60):
        return _run(*args, cwd=cwd)

    git.werk = werk
    git.remote = remote
    return git


def _tests(fouten_voor=(), fouten_na=()):
    teller = {"n": 0}

    def draai(map_):
        teller["n"] += 1
        assert os.path.isfile(os.path.join(map_, zv.VOORBEELDEN_PAD))
        return True, set(fouten_voor if teller["n"] == 1 else fouten_na)

    draai.teller = teller
    return draai


NIEUW = zv.pas_toe(DATA, {"werkwoorden": ["knal"]})


def test_maak_branch_test_en_commit(repo):
    tests = _tests(fouten_voor={"t::oud"}, fouten_na={"t::oud"})
    info = repo_branch = zv.maak_branch(NIEUW, "Ik begrijp nu 'knal'.", git=repo, tests_fn=tests,
                                        nu=datetime(2026, 11, 1, 3, 5))
    assert tests.teller["n"] == 2
    assert repo_branch["branch"] == "jarvis/verbetering-20261101-0305" and info["commit"]
    inhoud = repo("show", f"{info['branch']}:config/commando_voorbeelden.json")
    assert "knal" in inhoud
    assert "knal" not in (repo.werk / "config" / "commando_voorbeelden.json").read_text(encoding="utf-8")
    assert repo("worktree", "list").count("\n") == 0  # worktree opgeruimd


def test_maak_branch_nieuwe_fout_gooit_weg(repo):
    info = zv.maak_branch(NIEUW, "x", git=repo, tests_fn=_tests(fouten_na={"t::nieuw"}))
    assert info["commit"] is None and info["nieuw_fout"] == ["t::nieuw"]
    assert "verbetering" not in repo("branch")


def _met_voorstel(repo, tmp_path):
    pad = str(tmp_path / "status.json")
    info = zv.maak_branch(NIEUW, "Ik begrijp nu 'knal'.", git=repo, tests_fn=_tests())
    status = zv.lees_status(pad)
    status["voorstel"] = {"id": info["commit"][:10], "branch": info["branch"], "commit": info["commit"],
                          "basis": info["basis"], "uitleg": "Ik begrijp nu 'knal'.", "wijzigingen": [],
                          "verbeterd": ["knal de muziek harder"], "missers": ["knal de muziek harder"],
                          "gemaakt": "2026-11-01T03:10"}
    zv.schrijf_status(status, pad)
    return pad, info


def test_installeer_merge_push_herlaad(repo, tmp_path):
    pad, info = _met_voorstel(repo, tmp_path)
    herladen = []
    tekst = zv.installeer(pad, git=repo, herlaad_fn=lambda: herladen.append(1))
    assert tekst.startswith("Geïnstalleerd, sir.")
    assert herladen == [1]
    assert "knal" in (repo.werk / "config" / "commando_voorbeelden.json").read_text(encoding="utf-8")
    assert _run("rev-parse", "main", cwd=repo.remote) == info["commit"]  # op "GitHub"
    status = zv.lees_status(pad)
    assert status["voorstel"] is None and status["geschiedenis"][-1]["stand"] == "geïnstalleerd"
    assert "knal de muziek harder" in status["behandeld"]
    assert "verbetering" not in repo("branch")


def test_installeer_push_mislukt_zet_terug(repo, tmp_path):
    pad, info = _met_voorstel(repo, tmp_path)
    repo("remote", "set-url", "origin", str(tmp_path / "bestaat-niet.git"))
    tekst = zv.installeer(pad, git=repo, herlaad_fn=lambda: None)
    assert "Pushen naar GitHub lukte niet" in tekst
    assert repo("rev-parse", "HEAD") == info["basis"]
    assert zv.lees_status(pad)["voorstel"] is not None


def test_installeer_na_update_verlopen(repo, tmp_path):
    pad, _ = _met_voorstel(repo, tmp_path)
    (repo.werk / "ander.txt").write_text("x", encoding="utf-8")
    repo("add", "ander.txt")
    repo("commit", "-q", "-m", "update")
    assert "intussen bijgewerkt" in zv.installeer(pad, git=repo, herlaad_fn=lambda: None)
    assert zv.lees_status(pad)["voorstel"] is None


def test_installeer_niet_met_lokale_wijzigingen(repo, tmp_path):
    pad, _ = _met_voorstel(repo, tmp_path)
    (repo.werk / "config" / "commando_voorbeelden.json").write_text("{}", encoding="utf-8")
    assert "lokale wijzigingen" in zv.installeer(pad, git=repo, herlaad_fn=lambda: None)


def test_weiger(repo, tmp_path):
    pad, _ = _met_voorstel(repo, tmp_path)
    assert zv.weiger(pad, git=repo) == "Goed, sir; die verbetering gooi ik weg."
    status = zv.lees_status(pad)
    assert status["voorstel"] is None and status["geschiedenis"][-1]["stand"] == "geweigerd"
    assert "verbetering" not in repo("branch")


def test_draai_terug(repo, tmp_path):
    pad, info = _met_voorstel(repo, tmp_path)
    zv.installeer(pad, git=repo, herlaad_fn=lambda: None)
    tekst = zv.draai_terug(pad, git=repo, herlaad_fn=lambda: None)
    assert tekst.startswith("Teruggedraaid")
    assert "knal" not in (repo.werk / "config" / "commando_voorbeelden.json").read_text(encoding="utf-8")
    assert zv.lees_status(pad)["geschiedenis"][-1]["stand"] == "teruggedraaid"
    assert zv.draai_terug(pad, git=repo) == "Ik heb nog geen verbetering geïnstalleerd, sir."


# ---------------------------------------------------------------------
# Een ronde, de planner en de stem
# ---------------------------------------------------------------------

def test_ronde_voorstel(tmp_path):
    pad = str(tmp_path / "s.json")
    uitkomst = zv.ronde(
        pad, missers_fn=lambda b: MISSERS, data_fn=lambda: DATA,
        voorstel_fn=lambda m, d: ({"aanvulling": {"werkwoorden": ["knal"], "uitleg": "Uitleg."},
                                    "data": NIEUW, "verbeterd": ["knal de muziek harder"]}, None),
        branch_fn=lambda data, uitleg, nu=None: {"branch": "jarvis/verbetering-x", "commit": "a" * 40,
                                                  "basis": "b" * 40, "nieuw_fout": []})
    assert uitkomst == "voorstel"
    v = zv.lees_status(pad)["voorstel"]
    assert v["wijzigingen"] == ["Werkwoorden: knal"] and v["uitleg"] == "Uitleg."
    assert "installeer de verbetering" in zv.melding_voor("voorstel", pad)
    assert zv.ronde(pad, missers_fn=lambda b: 1 / 0) == "wacht"


def test_ronde_niets_en_lijstje(tmp_path):
    pad = str(tmp_path / "s.json")
    assert zv.ronde(pad, missers_fn=lambda b: []) == "niets"
    assert zv.ronde(pad, missers_fn=lambda b: MISSERS, data_fn=lambda: DATA,
                    voorstel_fn=lambda m, d: (None, "Gemini: limiet")) == "lijstje"
    lijstje = zv.lees_status(pad)["lijstje"]
    assert '"knal de muziek harder" (3x)' in lijstje["tekst"] and "limiet" in lijstje["tekst"]


def test_ronde_tests_falen_wordt_lijstje(tmp_path):
    pad = str(tmp_path / "s.json")
    uitkomst = zv.ronde(
        pad, missers_fn=lambda b: MISSERS, data_fn=lambda: DATA,
        voorstel_fn=lambda m, d: ({"aanvulling": {"uitleg": "x"}, "data": NIEUW, "verbeterd": ["a"]}, None),
        branch_fn=lambda *a, **k: {"branch": "b", "commit": None, "basis": "c", "nieuw_fout": ["t::x"]})
    assert uitkomst == "lijstje"
    assert "tests faalden" in zv.lees_status(pad)["lijstje"]["reden"]


def test_start_ronde_meldt_en_geen_dubbel(tmp_path):
    pad = str(tmp_path / "s.json")
    meldingen = []
    zv.zet_meld(lambda t, bron: meldingen.append(t))
    try:
        assert zv.start_ronde(pad, ronde_fn=lambda p: "niets", achtergrond=False)
        assert meldingen == [zv.UITKOMST_ZIN["niets"]]
        status = zv.lees_status(pad)
        status["bezig"] = True
        zv.schrijf_status(status, pad)
        assert zv.start_ronde(pad, ronde_fn=lambda p: "niets", achtergrond=False) is False
    finally:
        zv.zet_meld(None)


def test_planner_zondagnacht_een_keer(tmp_path):
    pad = str(tmp_path / "s.json")
    gestart = []
    klok = {"nu": datetime(2026, 11, 1, 2, 50)}  # zondag
    planner = zv.ZelfverbeterPlanner(klok=lambda: klok["nu"], pad=pad, start_fn=lambda p: gestart.append(p) or True)
    assert planner.stap() is False
    klok["nu"] = datetime(2026, 11, 1, 3, 5)
    assert planner.stap() is True
    status = zv.lees_status(pad)
    status["laatste_ronde"] = "2026-11-01"
    zv.schrijf_status(status, pad)
    assert planner.stap() is False
    klok["nu"] = datetime(2026, 11, 2, 3, 5)  # maandag
    assert planner.stap() is False


def test_stem_verbeter_jezelf(tmp_path):
    pad = str(tmp_path / "s.json")
    gestart = []
    antwoord = zv.probeer_commando("JARVIS verbeter jezelf".split(" ", 1)[1], pad=pad,
                                   start_fn=lambda p: gestart.append(p) or True)
    assert antwoord.startswith("Ik ga aan de slag") and gestart == [pad]


def test_stem_installeer_vraagt_strikte_ja(tmp_path, monkeypatch):
    from core import brain

    monkeypatch.setattr(zv, "STATUS_FILE", str(tmp_path / "s.json"))
    status = zv.lees_status()
    status["voorstel"] = {"commit": "c" * 40, "uitleg": "Ik begrijp nu 'knal'.", "branch": "b", "basis": "d"}
    zv.schrijf_status(status)
    vraag = brain.process_command("installeer de verbetering")
    assert vraag.endswith("Zal ik hem installeren?")
    assert confirmation.is_strict_kind(zv.KIND) and confirmation.is_dangerous_kind(zv.KIND)
    geinstalleerd = []
    monkeypatch.setattr(zv, "installeer", lambda pad=None: geinstalleerd.append(1) or "Geïnstalleerd, sir.")
    assert brain.process_command("ja") == "Geïnstalleerd, sir."
    assert geinstalleerd == [1]


def test_stem_nee_laat_wachten(tmp_path, monkeypatch):
    from core import brain

    monkeypatch.setattr(zv, "STATUS_FILE", str(tmp_path / "s.json"))
    status = zv.lees_status()
    status["voorstel"] = {"commit": "c" * 40, "uitleg": "x", "branch": "b", "basis": "d"}
    zv.schrijf_status(status)
    zv.vraag_installeren()
    assert "blijft wachten" in brain.process_command("nee")
    assert zv.lees_status()["voorstel"] is not None


@pytest.mark.parametrize("zin,soort", [
    ("verbeter jezelf", "start"), ("upgrade jezelf", "start"),
    ("installeer de verbetering", "installeer"), ("weiger de verbetering", "weiger"),
    ("draai de laatste verbetering terug", "terug"), ("wat is je laatste verbetering", "wat"),
])
def test_stem_herkent(zin, soort, tmp_path):
    pad = str(tmp_path / "s.json")
    antwoord = zv.probeer_commando(zin, pad=pad, start_fn=lambda p: True)
    assert antwoord is not None


@pytest.mark.parametrize("zin", ["verbeter mijn verslag", "installeer spotify", "draai de muziek terug"])
def test_stem_niet_voor_ons(zin, tmp_path):
    assert zv.probeer_commando(zin, pad=str(tmp_path / "s.json"), start_fn=lambda p: True) is None


# ---------------------------------------------------------------------
# Dashboard en opstart
# ---------------------------------------------------------------------

def test_dashboard_api(tmp_path, monkeypatch):
    from dashboard.api import DashboardAPI

    monkeypatch.setattr(zv, "STATUS_FILE", str(tmp_path / "s.json"))
    api = DashboardAPI(audit_fn=lambda **k: None)
    status, data = api.verbetering()
    assert status == 200 and data["voorstel"] is None
    assert api.verbetering_actie({"actie": "rm"})[0] == 400
    monkeypatch.setattr(zv, "weiger", lambda: "Goed, sir; die verbetering gooi ik weg.")
    status, data = api.verbetering_actie({"actie": "weiger"})
    assert status == 200 and data["tekst"].startswith("Goed")


def test_aansluiting():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "zelfverbetering.ZelfverbeterPlanner().start()" in main
    assert "ZELFVERBETERING=1" in (root / ".env.example").read_text(encoding="utf-8")
    assert "memory/zelfverbetering.json" in (root / ".gitignore").read_text(encoding="utf-8")
    server = (root / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("POST", "/api/verbetering"): (b,' in server


def test_alleen_het_voorbeeldenbestand():
    assert zv.VOORBEELDEN_PAD == os.path.join("config", "commando_voorbeelden.json")
    bron = open(zv.__file__, encoding="utf-8").read()
    assert ".py\"" not in bron.split("def schrijf_voorbeelden")[1].split("def maak_branch")[0]
