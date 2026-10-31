"""Fase 27, M3 — welzijn: water, ogen en pauze, hooguit één melding per uur.

Alles met een nep-klok en nep-invoer: een "minuut" is één stap.
"""

import json
from pathlib import Path

import pytest

from core import welzijn
from core.welzijn import WelzijnPlanner


class Wereld:
    def __init__(self):
        self.nu = 0.0
        self.idle = 10.0     # seconden sinds de laatste invoer
        self.stil = False
        self.meldingen = []


@pytest.fixture
def w():
    wereld = Wereld()
    planner = WelzijnPlanner(
        meld_fn=lambda tekst, bron: wereld.meldingen.append((tekst, bron)),
        klok=lambda: wereld.nu, idle_fn=lambda: wereld.idle, stil_fn=lambda: wereld.stil,
    )
    wereld.planner = planner
    return wereld


def _minuten(w, n):
    """n minuten achter de pc; geeft de meldingen in die tijd."""

    voor = len(w.meldingen)
    for _ in range(n):
        w.nu += 60
        w.planner.stap()
    return [t for t, _ in w.meldingen[voor:]]


def test_ogen_na_45_minuten(w):
    w.planner.stap()  # beginpunt
    assert _minuten(w, 44) == []
    assert _minuten(w, 1) == [welzijn.ZIN_OGEN]
    assert w.meldingen[-1][1] == "welzijn"


def test_hooguit_een_melding_per_uur(w):
    w.planner.stap()
    assert _minuten(w, 45) == [welzijn.ZIN_OGEN]
    # Na 60 min zou water aan de beurt zijn, maar de vorige melding is pas
    # een kwartier oud: wachten tot het uur om is. Dan (105 min achter de pc)
    # is ook de pauze aan de beurt, en die zin omvat water en ogen.
    assert _minuten(w, 59) == []
    assert _minuten(w, 1) == [welzijn.ZIN_PAUZE]


def test_pauze_na_anderhalf_uur_omvat_alles(w):
    w.planner.stap()
    meldingen = _minuten(w, 200)
    assert welzijn.ZIN_PAUZE in meldingen
    assert len(meldingen) <= 4  # 200 minuten: nooit vaker dan eens per uur


def test_samen_in_een_zin():
    p = WelzijnPlanner(klok=lambda: 0, idle_fn=lambda: 0, stil_fn=lambda: False)
    p.water, p.ogen = 61, 50
    assert p.tekst() == welzijn.ZIN_WATER_OGEN
    assert (p.water, p.ogen) == (0, 0)
    p.pauze, p.water = 95, 70
    assert p.tekst() == welzijn.ZIN_PAUZE
    assert (p.water, p.ogen, p.pauze) == (0, 0, 0)
    assert p.tekst() is None


def test_niet_achter_de_pc_telt_niet(w):
    w.planner.stap()
    w.idle = welzijn.AANWEZIG_SECONDEN + 1   # weg, maar nog geen pauze
    assert _minuten(w, 120) == []
    assert w.planner.water == 0


def test_tien_minuten_weg_is_pauze_voor_de_ogen(w):
    w.planner.stap()
    _minuten(w, 40)
    w.idle = welzijn.KORTE_PAUZE
    _minuten(w, 1)
    assert w.planner.ogen == 0 and w.planner.pauze == 0
    assert w.planner.water > 0  # water telt door


def test_half_uur_weg_begint_alles_opnieuw(w):
    w.planner.stap()
    _minuten(w, 40)
    w.idle = welzijn.LANG_WEG
    _minuten(w, 1)
    assert (w.planner.water, w.planner.ogen, w.planner.pauze) == (0, 0, 0)


def test_stil_tijdens_potje_focus_film_of_nacht(w):
    w.planner.stap()
    w.stil = True
    assert _minuten(w, 50) == []
    w.stil = False
    # Na het potje komt de melding die bleef staan.
    assert _minuten(w, 1) == [welzijn.ZIN_OGEN]


def test_onbekende_invoer_zegt_niets(w):
    w.idle = None
    w.planner.stap()
    assert _minuten(w, 120) == []


def test_meld_fout_breekt_niets():
    def kapot(*a, **k):
        raise RuntimeError("stuk")

    tijd = {"nu": 0.0}
    p = WelzijnPlanner(meld_fn=kapot, klok=lambda: tijd["nu"], idle_fn=lambda: 0, stil_fn=lambda: False)
    p.stap()
    p.ogen = 50
    tijd["nu"] = 60
    assert p.stap() == welzijn.ZIN_OGEN


# ---------------------------------------------------------------------
# Stil-signalen en aansluiting
# ---------------------------------------------------------------------

@pytest.mark.parametrize("wat", ["nacht", "stil", "film", "focus", "potje_hier", "potje_gamepc"])
def test_std_stil(monkeypatch, wat):
    from actions import discord_meldingen
    from core import discord_dms, filmmodus, focusmodus, proactive

    monkeypatch.setattr(proactive, "is_nachtmodus", lambda *a: wat == "nacht")
    monkeypatch.setattr(proactive, "is_quiet", lambda: wat == "stil")
    monkeypatch.setattr(filmmodus, "lees_toestand", lambda *a: {} if wat == "film" else None)
    monkeypatch.setattr(focusmodus, "is_aan", lambda *a: wat == "focus")
    monkeypatch.setattr(discord_meldingen, "_volledig_scherm", lambda: wat == "potje_hier")
    monkeypatch.setattr(discord_dms, "game_pc_volledig_scherm", lambda: wat == "potje_gamepc")
    assert welzijn._std_stil() is True


def test_std_stil_normaal(monkeypatch):
    from actions import discord_meldingen
    from core import discord_dms, filmmodus, focusmodus, proactive

    monkeypatch.setattr(proactive, "is_nachtmodus", lambda *a: False)
    monkeypatch.setattr(proactive, "is_quiet", lambda: False)
    monkeypatch.setattr(filmmodus, "lees_toestand", lambda *a: None)
    monkeypatch.setattr(focusmodus, "is_aan", lambda *a: False)
    monkeypatch.setattr(discord_meldingen, "_volledig_scherm", lambda: False)
    monkeypatch.setattr(discord_dms, "game_pc_volledig_scherm", lambda: False)
    assert welzijn._std_stil() is False


def test_game_pc_volledig_scherm_verloopt(monkeypatch):
    from core import discord_dms
    from core.result_validation import ToolResult

    klant = discord_dms.DiscordKlant(pc_fn=lambda tool, args: ToolResult(
        ok=True, message="", data={"dms": [], "volledig_scherm": True}))
    klant.dms()
    assert discord_dms.game_pc_volledig_scherm() is True
    nu = discord_dms._time.monotonic() + discord_dms.SCHERM_GELDIG + 1
    monkeypatch.setattr(discord_dms._time, "monotonic", lambda: nu)
    assert discord_dms.game_pc_volledig_scherm() is False


def test_oude_pauze_regel_staat_uit():
    pad = Path(__file__).resolve().parent.parent / "config" / "proactive_rules.json"
    regels = {r["id"]: r for r in json.loads(pad.read_text(encoding="utf-8"))["regels"]}
    assert regels["pauze_herinnering"]["actief"] is False
    assert regels["lunch"]["actief"] is True and regels["late_avond"]["actief"] is True


def test_opstart_en_instelling():
    root = Path(__file__).resolve().parent.parent
    assert "WelzijnPlanner(meld_fn=" in (root / "main.py").read_text(encoding="utf-8")
    assert "WELZIJN_MELDEN=1" in (root / ".env.example").read_text(encoding="utf-8")
