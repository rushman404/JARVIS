"""Fase 26, M2 — focusmodus: Discord gedempt, DM's stil, met of zonder duur."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import focusmodus
from core.focusmodus import FocusModus, FocusPlanner
from core.result_validation import ToolResult

NU = datetime(2026, 10, 30, 14, 0)
STATIC = Path(__file__).resolve().parent.parent / "dashboard" / "static"


class GamePc:
    """Nep-game-pc: Discord-sessie met een mute-stand."""

    def __init__(self, gedempt=False, bereikbaar=True):
        self.gedempt = gedempt
        self.bereikbaar = bereikbaar
        self.aanroepen = []

    def __call__(self, tool, args):
        self.aanroepen.append((tool, dict(args)))
        if not self.bereikbaar:
            return ToolResult(ok=False, message="niet bereikbaar", error_kind="remote_config")
        if tool == "audio_get_session_volume":
            return ToolResult(ok=True, message="", data={"volume": 80, "muted": self.gedempt})
        if tool == "audio_set_session_mute":
            self.gedempt = args["muted"]
            return ToolResult(ok=True, message="gezet")
        return ToolResult(ok=False, message="?")


class Klok:
    def __init__(self, nu=NU):
        self.nu = nu

    def __call__(self):
        return self.nu


@pytest.fixture
def focus(tmp_path):
    pc = GamePc()
    klok = Klok()
    dms = {"namen": []}
    f = FocusModus(pc_tool=pc, toestand_pad=str(tmp_path / "focus.json"), klok=klok,
                   dms_fn=lambda: dms["namen"])
    return f, pc, klok, dms


# ---------------------------------------------------------------------
# Herkennen
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin, verwacht", [
    ("focusmodus aan", ("aan", None)),
    ("zet de focusmodus aan", ("aan", None)),
    ("focus modus aan", ("aan", None)),
    ("start focusmodus", ("aan", None)),
    ("focusmodus voor 2 uur", ("aan", 120)),
    ("focusmodus aan voor anderhalf uur", ("aan", 90)),
    ("focus 45 minuten", ("aan", 45)),
    ("focusmodus voor een kwartier", ("aan", 15)),
    ("focusmodus voor een uur", ("aan", 60)),
    ("ik wil me even concentreren", ("aan", None)),
    ("focusmodus uit", ("uit", None)),
    ("zet de focusmodus uit", ("uit", None)),
    ("stop focus", ("uit", None)),
    ("focus klaar", ("uit", None)),
    ("ik ben klaar met de focus", ("uit", None)),
    ("staat de focusmodus aan?", ("status", None)),
    ("hoe lang nog focus", ("status", None)),
])
def test_herken(zin, verwacht):
    assert focusmodus.herken(zin) == verwacht


@pytest.mark.parametrize("zin", [
    "focus op de wedstrijd",
    "wat is focus",
    "zet de lamp aan",
    "film klaar",
    "focusmodus voor 30 jaar",
])
def test_geen_focus(zin):
    assert focusmodus.herken(zin) is None


def test_te_lange_duur_telt_niet():
    assert focusmodus.lees_duur("24 uur") is None
    assert focusmodus.lees_duur("12 uur") == 720


# ---------------------------------------------------------------------
# Aan en uit
# ---------------------------------------------------------------------

def test_aan_dempt_discord_en_onthoudt(focus):
    f, pc, klok, _ = focus
    assert f.aan() == "Focusmodus aan, sir. Discord is gedempt en nieuwe DM's lees ik niet voor."
    assert pc.gedempt is True
    toestand = focusmodus.lees_toestand(f.toestand_pad)
    assert toestand["discord_gedempt"] is True and toestand["tot"] is None
    assert focusmodus.is_aan(f.toestand_pad)


def test_aan_met_duur(focus):
    f, *_ = focus
    assert f.aan(120).startswith("Focusmodus aan voor 2 uur, tot 16:00, sir.")
    assert focusmodus.status(nu=NU + timedelta(minutes=30), pad=f.toestand_pad) == {
        "aan": True, "tot": "16:00", "resterend": 90 * 60}


def test_uit_zet_discord_terug_en_noemt_dms(focus):
    f, pc, _, dms = focus
    f.aan()
    dms["namen"] = ["Sem", "Daan", "Sem"]
    assert f.uit() == "Focusmodus uit, sir. Discord staat weer aan. U heeft 3 nieuwe DM's, van Sem en Daan."
    assert pc.gedempt is False
    assert not focusmodus.is_aan(f.toestand_pad)


def test_uit_zonder_dms(focus):
    f, *_ = focus
    f.aan()
    assert f.uit().endswith("Er kwamen geen nieuwe DM's binnen.")


def test_uit_als_dms_onbekend(focus):
    f, *_ = focus
    f.dms_fn = lambda: None
    f.aan()
    assert f.uit() == "Focusmodus uit, sir. Discord staat weer aan."


def test_discord_al_gedempt_blijft_gedempt(focus, tmp_path):
    pc = GamePc(gedempt=True)
    f = FocusModus(pc_tool=pc, toestand_pad=str(tmp_path / "f.json"), klok=Klok(), dms_fn=lambda: [])
    assert "Discord stond al stil" in f.aan()
    f.uit()
    assert pc.gedempt is True  # niet "terug" aangezet: hij stond al uit
    assert ("audio_set_session_mute", {"app_name": "Discord", "muted": False}) not in pc.aanroepen


def test_game_pc_onbereikbaar(focus, tmp_path):
    pc = GamePc(bereikbaar=False)
    f = FocusModus(pc_tool=pc, toestand_pad=str(tmp_path / "f.json"), klok=Klok(), dms_fn=lambda: None)
    assert f.aan() == "Focusmodus aan, sir. De game-pc is niet bereikbaar, dus Discord kon ik niet dempen."
    assert focusmodus.is_aan(f.toestand_pad)
    assert f.uit() == "Focusmodus uit, sir."


def test_terugzetten_mislukt(focus):
    f, pc, *_ = focus
    f.aan()
    pc.bereikbaar = False
    assert "Discord kon ik niet terugzetten" in f.uit()


def test_twee_keer_aan_past_alleen_duur_aan(focus):
    f, pc, *_ = focus
    f.aan()
    assert f.aan(60) == "De focus loopt nu nog 1 uur, tot 15:00, sir."
    assert f.aan() == "De focusmodus staat al aan; hij blijft aan tot u hem uitzet, sir."
    assert sum(1 for t, _ in pc.aanroepen if t == "audio_set_session_mute") == 1


def test_uit_als_niet_aan(focus):
    f, *_ = focus
    assert f.uit() == "De focusmodus staat niet aan, sir."


def test_herstart_vergeet_niets(focus, tmp_path):
    f, pc, klok, _ = focus
    f.aan(60)
    nieuw = FocusModus(pc_tool=pc, toestand_pad=f.toestand_pad, klok=klok, dms_fn=lambda: [])
    assert "Discord staat weer aan." in nieuw.uit()
    assert pc.gedempt is False


# ---------------------------------------------------------------------
# Vanzelf stoppen
# ---------------------------------------------------------------------

def test_planner_stopt_na_duur_en_meldt(focus):
    f, pc, klok, _ = focus
    meldingen = []
    planner = FocusPlanner(meld_fn=lambda tekst, bron: meldingen.append((tekst, bron)), focus_fn=lambda: f)
    f.aan(30)
    klok.nu = NU + timedelta(minutes=29)
    assert planner.stap() is None
    klok.nu = NU + timedelta(minutes=30)
    tekst = planner.stap()
    assert tekst.startswith("Uw focustijd is voorbij, sir. Discord staat weer aan.")
    assert meldingen == [(tekst, "focus")]
    assert pc.gedempt is False
    assert planner.stap() is None


def test_planner_zonder_eindtijd_doet_niets(focus):
    f, _, klok, _ = focus
    planner = FocusPlanner(meld_fn=lambda *a: pytest.fail("geen melding"), focus_fn=lambda: f)
    f.aan()
    klok.nu = NU + timedelta(hours=10)
    assert planner.stap() is None
    assert focusmodus.is_aan(f.toestand_pad)


# ---------------------------------------------------------------------
# Stem en DM's stil
# ---------------------------------------------------------------------

def test_voer_uit(focus):
    f, *_ = focus
    assert focusmodus.voer_uit("staat de focusmodus aan", focus=f) == "De focusmodus staat uit, sir."
    assert focusmodus.voer_uit("focusmodus voor 2 uur", focus=f).startswith("Focusmodus aan voor 2 uur")
    assert focusmodus.voer_uit("hoe lang nog focus", focus=f, nu=NU) == "De focus loopt nog tot 16:00, sir."
    assert focusmodus.voer_uit("focusmodus uit", focus=f).startswith("Focusmodus uit")
    assert focusmodus.voer_uit("zet de lamp aan", focus=f) is None


def test_dms_stil_tijdens_focus(monkeypatch, tmp_path):
    from core import discord_dms, filmmodus, proactive

    monkeypatch.setattr(focusmodus, "TOESTAND_FILE", str(tmp_path / "focus.json"))
    monkeypatch.setattr(filmmodus, "lees_toestand", lambda *a: None)
    monkeypatch.setattr(proactive, "is_nachtmodus", lambda *a: False)
    monkeypatch.setattr(proactive, "is_quiet", lambda: False)
    assert discord_dms._std_stil() is False
    focusmodus.schrijf_toestand({"gestart": "x", "tot": None, "discord_gedempt": False})
    assert discord_dms._std_stil() is True


def test_brein_routeert_focus(monkeypatch, tmp_path):
    import core.brain as brain

    pc = GamePc()
    monkeypatch.setattr(focusmodus, "_gedeeld", {"focus": FocusModus(
        pc_tool=pc, toestand_pad=str(tmp_path / "f.json"), dms_fn=lambda: [])})
    monkeypatch.setattr(brain, "ask_ai", lambda *a, **k: pytest.fail("geen AI"))
    assert brain.process_command("focusmodus aan").startswith("Focusmodus aan")
    assert pc.gedempt is True
    assert brain.process_command("focusmodus uit").startswith("Focusmodus uit")


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch, tmp_path):
    from dashboard.api import DashboardAPI

    pc = GamePc()
    monkeypatch.setattr(focusmodus, "TOESTAND_FILE", str(tmp_path / "focus.json"))
    monkeypatch.setattr(focusmodus, "_gedeeld", {"focus": FocusModus(pc_tool=pc, dms_fn=lambda: [])})
    regels = []
    return DashboardAPI(audit_fn=lambda **v: regels.append(v), widgets_pad=str(tmp_path / "d.json")), pc, regels


def test_api_focus_aan_en_uit(api):
    a, pc, regels = api
    status, antwoord = a.focus({"actie": "aan", "minuten": 60})
    assert status == 200
    assert antwoord["focus"]["aan"] is True and antwoord["focus"]["tot"]
    assert antwoord["tekst"].startswith("Focusmodus aan voor 1 uur")
    assert pc.gedempt is True
    assert regels[0]["tool"] == "focusmodus"
    status, antwoord = a.focus({"actie": "uit"})
    assert status == 200 and antwoord["focus"]["aan"] is False
    assert pc.gedempt is False


@pytest.mark.parametrize("body", [None, {}, {"actie": "half"}, {"actie": "aan", "minuten": 0},
                                  {"actie": "aan", "minuten": 721}, {"actie": "aan", "minuten": "60"},
                                  {"actie": "aan", "minuten": True}])
def test_api_focus_ongeldig(api, body):
    a, pc, _ = api
    status, _ = a.focus(body)
    assert status == 400
    assert pc.aanroepen == []


def test_status_bevat_focus(api):
    a, *_ = api
    _, s = a.status()
    assert s["focus"] == {"aan": False, "tot": None, "resterend": None}


def test_route_alleen_voor_bedienen():
    tekst = (Path(__file__).resolve().parent.parent / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("POST", "/api/focus"): (b, lambda i, d: self.api.focus(d)),' in tekst


def test_knop_onder_de_nachtmodus():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    nacht = html.index('data-widget="nachtmodus"')
    einde = html.index("</section>", nacht)
    assert nacht < html.index('id="focus"') < einde
    assert 'data-minuten="60"' in html and 'data-minuten="120"' in html
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function toonFocus" in js and "/api/focus" in js and "tekenFocus();" in js
