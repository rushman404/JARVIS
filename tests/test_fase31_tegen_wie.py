"""Fase 31 — tegen wie praat u? Gesprekken met anderen herkennen.

Ollama, Discord en de microfoon-stand van Windows zijn altijd nep.
"""

import pytest

import main
from core import confirmation, gericht, gespreksmodus, vervolg


@pytest.fixture(autouse=True)
def schoon():
    from core import proactive

    confirmation.clear_pending()
    proactive.set_in_gesprek(False)
    yield
    confirmation.clear_pending()
    proactive.set_in_gesprek(False)


# ---------------------------------------------------------------------
# M1 — vaste regels
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin", [
    "zet de bedlamp aan", "open spotify", "volgende", "pauzeer de muziek",
    "kun je de lamp uitzetten", "wil je de muziek harder zetten",
    "en morgen", "en in amsterdam", "hoe laat is het", "hoeveel graden is het",
    "heb ik nog nieuwe mails", "wat voor weer wordt het", "jarvis wat is dat",
])
def test_regels_voor_jarvis(zin):
    assert gericht.regels(zin) == gericht.VOOR_JARVIS


@pytest.mark.parametrize("zin", [
    "hahaha", "haha nee joh", "hoi", "doei", "tot straks", "mam ik kom zo",
    "kom je zo eten", "ga je mee naar buiten", "heb jij mijn oplader gezien",
    "nee dat klopt niet man", "ja joh",
])
def test_regels_anders(zin):
    assert gericht.regels(zin) == gericht.ANDERS


@pytest.mark.parametrize("zin", ["ik denk het niet", "dat was echt grappig", "wat is er",
                                 "zet je de pizza in de oven"])  # werkwoord + je: Ollama beslist
def test_regels_twijfel(zin):
    assert gericht.regels(zin) == gericht.TWIJFEL


def test_open_vraag_altijd_voor_jarvis():
    assert gericht.regels("haha ja", open_vraag=True) == gericht.VOOR_JARVIS
    assert gericht.regels("de keukenlamp", open_vraag=True) == gericht.VOOR_JARVIS


def test_open_vraag_ziet_pending_en_wedervraag():
    assert gericht._open_vraag() is False
    confirmation.set_pending("muziek_voorstel", {"question": "x"})
    assert gericht._open_vraag() is True
    confirmation.clear_pending()
    vervolg.zet("Welk programma wil je sluiten?", sjabloon="sluit {antwoord}")
    assert gericht._open_vraag() is True


# ---------------------------------------------------------------------
# M1 — Ollama bij twijfel, lokaal en met een tijdslimiet
# ---------------------------------------------------------------------

def test_ai_beslist_bij_twijfel():
    gezien = []

    def ai(berichten):
        gezien.append(berichten)
        return "ANDERS"

    assert gericht.beoordeel("ik denk het niet", "Het is 14:00, sir.", open_vraag=False, ai_fn=ai) is False
    assert 'JARVIS zei net: "Het is 14:00, sir."' in gezien[0][1]["content"]
    assert gericht.beoordeel("dat wil ik weten", open_vraag=False, ai_fn=lambda b: "JARVIS") is True


def test_ai_niet_nodig_bij_duidelijke_regel():
    def ai(berichten):
        raise AssertionError("niet aanroepen")

    assert gericht.beoordeel("zet de lamp aan", open_vraag=False, ai_fn=ai) is True
    assert gericht.beoordeel("hahaha", open_vraag=False, ai_fn=ai) is False


@pytest.mark.parametrize("antwoord", [None, "", "misschien", RuntimeError("weg")])
def test_bij_twijfel_niets_doen(antwoord):
    def ai(berichten):
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    assert gericht.beoordeel("ik denk het niet", open_vraag=False, ai_fn=ai) is False


def test_ai_te_traag_is_twijfel():
    import time

    assert gericht.vraag_ai("ik denk het niet", ai_fn=lambda b: time.sleep(0.5) or "JARVIS",
                            timeout=0.05) == gericht.TWIJFEL


def test_std_ai_nooit_naar_de_cloud(monkeypatch):
    from core import llm

    gezien = {}

    def chat(messages=None, **kw):
        gezien.update(kw)
        return type("A", (), {"message": type("M", (), {"content": "JARVIS"})()})()

    monkeypatch.setattr(llm, "chat", chat)
    assert gericht._std_ai([{"role": "user", "content": "x"}]) == "JARVIS"
    assert not gezien.get("cloud")


# ---------------------------------------------------------------------
# De sessielus
# ---------------------------------------------------------------------

def _sessie(monkeypatch, opdrachten, antwoorden=None):
    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 3.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    gesproken = []
    monkeypatch.setattr(main, "speak", lambda *a, **k: gesproken.append((a, k)))
    verwerkt = []

    def proces(cmd, on_tekst=None):
        verwerkt.append(cmd)
        return (antwoorden or {}).get(cmd, "Prima, sir.")

    monkeypatch.setattr(main, "process_command", proces)
    reeks = iter(opdrachten)
    gelezen = []

    def luister(start_ts=None, **kw):
        waarde = next(reeks)
        gelezen.append(waarde)
        return waarde

    monkeypatch.setattr(main, "listen", luister)
    monkeypatch.setattr(main, "spreek_antwoord", lambda *a, **k: True)
    return verwerkt, gelezen, gesproken


def test_gesprek_met_ander_stopt_stil(monkeypatch):
    monkeypatch.setattr(gericht, "vraag_ai", lambda *a, **k: gericht.ANDERS)
    verwerkt, gelezen, gesproken = _sessie(monkeypatch, ["hoe laat is het", "kom je zo eten", "zet de lamp aan"])
    assert main.run_wake_cycle() == "ok"
    assert verwerkt == ["hoe laat is het"]
    assert gelezen == ["hoe laat is het", "kom je zo eten"]   # daarna niet verder geluisterd
    assert all(not a for a, k in gesproken[1:])                # niets gezegd na het antwoord


def test_eerste_zin_na_wake_word_altijd(monkeypatch):
    verwerkt, _, _ = _sessie(monkeypatch, ["haha zet de lamp aan", ""])
    main.run_wake_cycle()
    assert verwerkt == ["haha zet de lamp aan"]


def test_vervolg_en_commando_gaan_door(monkeypatch):
    verwerkt, _, _ = _sessie(monkeypatch, ["wat is het weer", "en morgen", "zet de lamp aan", ""])
    main.run_wake_cycle()
    assert verwerkt == ["wat is het weer", "en morgen", "zet de lamp aan"]


def test_jarvis_erbij_altijd(monkeypatch):
    monkeypatch.setattr(gericht, "vraag_ai", lambda *a, **k: gericht.ANDERS)
    monkeypatch.setattr(main, "strip_wake_phrase", lambda t: t.replace("jarvis ", ""))
    verwerkt, _, _ = _sessie(monkeypatch, ["hoe laat is het", "jarvis haha wat grappig", ""])
    main.run_wake_cycle()
    assert verwerkt == ["hoe laat is het", "haha wat grappig"]


def test_onverstaanbaar_na_antwoord_stopt_stil(monkeypatch):
    verwerkt, gelezen, gesproken = _sessie(monkeypatch, ["hoe laat is het", None, "zet de lamp aan"])
    main.run_wake_cycle()
    assert verwerkt == ["hoe laat is het"] and gelezen == ["hoe laat is het", None]


def test_uit_te_zetten(monkeypatch):
    monkeypatch.setattr(main, "GESPREK_HERKENNEN", False)
    verwerkt, _, _ = _sessie(monkeypatch, ["hoe laat is het", "kom je zo eten", ""])
    main.run_wake_cycle()
    assert verwerkt == ["hoe laat is het", "kom je zo eten"]


# ---------------------------------------------------------------------
# M2 — knop "In gesprek"
# ---------------------------------------------------------------------

def test_knop_aan_uit():
    assert gespreksmodus.status() == {"aan": False, "knop": False, "discord": False, "bron": None}
    assert gespreksmodus.zet(True)["bron"] == "knop"
    assert gespreksmodus.is_actief()
    assert gespreksmodus.zet(False)["aan"] is False


def test_in_gesprek_geen_doorluisteren(monkeypatch):
    gespreksmodus.zet(True)
    verwerkt, gelezen, _ = _sessie(monkeypatch, ["zet de lamp aan", "zet de lamp uit"])
    main.run_wake_cycle()
    assert verwerkt == ["zet de lamp aan"] and gelezen == ["zet de lamp aan"]


def test_in_gesprek_maar_vraag_open_luistert_wel(monkeypatch):
    gespreksmodus.zet(True)
    monkeypatch.setattr(gericht, "_open_vraag", lambda: True)
    verwerkt, _, _ = _sessie(monkeypatch, ["sluit", "spotify", ""])
    main.run_wake_cycle()
    assert verwerkt == ["sluit", "spotify"]


def test_dashboard_knop():
    from dashboard.api import DashboardAPI

    api = DashboardAPI(audit_fn=lambda **k: None)
    assert api.gespreksmodus({"aan": "ja"})[0] == 400
    status, data = api.gespreksmodus({"aan": True})
    assert status == 200 and data["gespreksmodus"]["knop"] is True
    assert api.status()[1]["gespreksmodus"]["aan"] is True
    api.gespreksmodus({"aan": False})


def test_dashboard_aansluiting():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert '("POST", "/api/gespreksmodus"): (b,' in (root / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert 'id="gesprekKnop"' in (root / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    assert "GESPREK_HERKENNEN=1" in (root / ".env.example").read_text(encoding="utf-8")
    assert "memory/gespreksmodus.json" in (root / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# M3 — Discord-call
# ---------------------------------------------------------------------

def test_discord_call_game_pc_telt(monkeypatch):
    from core import discord_dms
    from core.result_validation import ToolResult

    klant = discord_dms.DiscordKlant(pc_fn=lambda tool, args: ToolResult(
        ok=True, message="", data={"dms": [], "volledig_scherm": False, "in_call": True}))
    klant.dms()
    assert discord_dms.game_pc_in_call() is True
    assert gespreksmodus.status() == {"aan": True, "knop": False, "discord": True, "bron": "discord"}
    nu = discord_dms._time.monotonic() + discord_dms.SCHERM_GELDIG + 1
    monkeypatch.setattr(discord_dms._time, "monotonic", lambda: nu)
    assert discord_dms.game_pc_in_call() is False


def test_discord_in_call_leest_microfoon_stand(monkeypatch):
    import sys
    import types

    from actions import discord_meldingen

    sleutels = {
        "C:#Users#x#AppData#Local#Discord#app-1.0.9260#Discord.exe": (134356226822129503, 0),
        "C:#Program Files#Steam#steam.exe": (1, 0),
        "C:#Users#x#AppData#Local#Discord#app-1.0.9259#Discord.exe": (1, 2),
    }
    namen = list(sleutels)
    nep = types.SimpleNamespace(
        HKEY_CURRENT_USER=0,
        EnumKey=lambda k, i: namen[i] if i < len(namen) else (_ for _ in ()).throw(OSError()),
        QueryValueEx=lambda k, n: (k[0] if n == "LastUsedTimeStart" else k[1], 4),
    )
    monkeypatch.setitem(sys.modules, "winreg", nep)

    def openen(pad):
        naam = pad.rsplit("\\", 1)[-1]
        return sleutels.get(naam, "hoofd")

    import importlib

    module = importlib.reload(discord_meldingen)
    try:
        assert module.discord_in_call(openen) is True
        sleutels[namen[0]] = (134356226822129503, 134356226999999999)
        assert module.discord_in_call(openen) is False
    finally:
        monkeypatch.delitem(sys.modules, "winreg")
        importlib.reload(discord_meldingen)


def test_agent_stuurt_in_call_mee(monkeypatch):
    from actions import discord_meldingen

    monkeypatch.setattr(discord_meldingen, "lees_dms", lambda: [])
    monkeypatch.setattr(discord_meldingen, "_volledig_scherm", lambda: False)
    monkeypatch.setattr(discord_meldingen, "discord_in_call", lambda: True)
    assert discord_meldingen.discord_dms().data["in_call"] is True


def test_app_js_geen_dubbele_functienamen():
    """Fix 2026-10-31: een tweede ``toonGesprek`` overschreef die van het
    chatpaneel (JavaScript neemt stilletjes de laatste), waardoor de knop
    "In gesprek" bleef hangen op "Even geduld…"."""

    import collections
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    namen = collections.Counter(re.findall(r"^\s*function\s+(\w+)\s*\(", js, re.MULTILINE))
    assert [n for n, keer in namen.items() if keer > 1] == []
