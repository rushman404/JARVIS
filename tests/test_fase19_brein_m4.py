"""Fase 19, M4 — de slaapstand van JARVIS."""

import re

import main
from core import llm, proactive


# ---------------------------------------------------------------
# Slaapstand zelf
# ---------------------------------------------------------------

def test_slapen_zet_stille_modus_en_wakker_zet_hem_terug():
    proactive.set_quiet(False)
    assert proactive.ga_slapen() is True
    assert proactive.slaapt() and proactive.is_quiet()
    assert proactive.slaap_reden() == proactive.SLAAP_COMMANDO
    assert proactive.word_wakker() is True
    assert not proactive.slaapt() and not proactive.is_quiet()


def test_handmatige_stille_modus_blijft_na_wakker_worden():
    proactive.set_quiet(True)
    proactive.ga_slapen()
    proactive.word_wakker()
    assert proactive.is_quiet() is True
    proactive.set_quiet(False)


def test_dubbel_slapen_en_auto_wordt_commando():
    assert proactive.ga_slapen(proactive.SLAAP_AUTO) is True
    assert proactive.ga_slapen(proactive.SLAAP_AUTO) is False
    assert proactive.slaap_reden() == proactive.SLAAP_AUTO
    assert proactive.ga_slapen(proactive.SLAAP_COMMANDO) is False
    assert proactive.slaap_reden() == proactive.SLAAP_COMMANDO
    assert proactive.word_wakker() is True
    assert proactive.word_wakker() is False


def test_luisteraars_en_fout_in_luisteraar():
    gebeurd = []

    def stuk():
        raise RuntimeError

    proactive.bij_slaap(stuk)
    proactive.bij_slaap(lambda: gebeurd.append("slaap"))
    proactive.bij_wakker(lambda: gebeurd.append("wakker"))
    proactive.ga_slapen()
    proactive.ga_slapen()  # al slapend: geen tweede keer
    proactive.word_wakker()
    assert gebeurd == ["slaap", "wakker"]


# ---------------------------------------------------------------
# Engine: auto-slaap en meldingen
# ---------------------------------------------------------------

def _engine(tmp_path, **kw):
    kw.setdefault("rules_pad", str(tmp_path / "regels.json"))
    return proactive.ProactiveEngine(**kw)


def test_activiteit_wekt_alleen_de_auto_slaap(tmp_path):
    engine = _engine(tmp_path)
    proactive.ga_slapen(proactive.SLAAP_AUTO)
    assert engine.is_auto_slaap()
    engine.meld_activiteit()
    assert not proactive.slaapt()

    proactive.ga_slapen(proactive.SLAAP_COMMANDO)
    engine.meld_activiteit()
    assert proactive.slaapt(), "na 'ga slapen' maakt alleen het wake word hem wakker"
    assert not engine.is_auto_slaap()


def test_auto_slaap_gaat_niet_over_commando_slaap_heen(tmp_path):
    engine = _engine(tmp_path, actief_check_fn=lambda: False, inactiviteit_seconden=10)
    engine._laatste_activiteit = 0
    proactive.ga_slapen(proactive.SLAAP_COMMANDO)
    engine._check_auto_slaap(1000)
    assert proactive.slaap_reden() == proactive.SLAAP_COMMANDO


def test_slapend_alleen_timers(tmp_path):
    geleverd = []
    engine = _engine(tmp_path, lever_fn=lambda m: geleverd.append(m.tekst))
    proactive.ga_slapen()
    engine._verstuur("Sir, uw timer 'thee' is afgelopen.", bron="timer")
    engine._verstuur("Tijd voor een pauze.", bron="regel")
    engine._lever_op()
    assert geleverd == ["Sir, uw timer 'thee' is afgelopen."]
    proactive.word_wakker()
    engine._lever_op()
    assert geleverd[-1] == "Tijd voor een pauze."


# ---------------------------------------------------------------
# AI-model uit en in het geheugen
# ---------------------------------------------------------------

def test_model_ontladen_en_laden(monkeypatch):
    aanroepen = []
    monkeypatch.setattr(llm.ollama, "generate", lambda **kw: aanroepen.append(kw))
    llm.ontlaad_model()
    llm.laad_model()
    assert aanroepen[0]["keep_alive"] == 0 and aanroepen[0]["model"] == llm.AI_MODEL
    assert aanroepen[1]["keep_alive"] == llm.AI_KEEP_ALIVE
    assert aanroepen[1]["options"]["num_ctx"] == llm.AI_NUM_CTX


def test_op_achtergrond_slikt_fouten():
    def stuk():
        raise ConnectionError("ollama weg")

    thread = llm.op_achtergrond(stuk)
    thread.join(2)
    assert not thread.is_alive() and thread.daemon


# ---------------------------------------------------------------
# Spraak: "ga slapen" en wakker worden
# ---------------------------------------------------------------

def _sessie(monkeypatch, opdrachten):
    gezegd = []
    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 3.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: gezegd.append(a[0] if a else ("piep" if k.get("beep_only") else "")))
    verwerkt = []
    monkeypatch.setattr(main, "process_command", lambda cmd, on_tekst=None: verwerkt.append(cmd) or "ok")
    reeks = iter(opdrachten)
    monkeypatch.setattr(main, "listen", lambda start_ts=None, **kw: next(reeks))
    return gezegd, verwerkt


def test_ga_slapen_zet_slaapstand(monkeypatch):
    gezegd, verwerkt = _sessie(monkeypatch, ["ga slapen"])
    main.run_wake_cycle()
    assert proactive.slaapt() and proactive.slaap_reden() == proactive.SLAAP_COMMANDO
    assert gezegd == ["piep", main.SLAAP_MELDING]
    assert verwerkt == []


def test_wake_word_wekt_met_groet(monkeypatch):
    proactive.ga_slapen(proactive.SLAAP_COMMANDO)
    gezegd, verwerkt = _sessie(monkeypatch, ["hoe laat is het", ""])
    main.run_wake_cycle()
    assert not proactive.slaapt()
    assert gezegd[0] == main.WAKKER_MELDING
    assert verwerkt == ["hoe laat is het"]


def test_wake_word_na_auto_slaap_alleen_piep(monkeypatch):
    proactive.ga_slapen(proactive.SLAAP_AUTO)
    gezegd, _ = _sessie(monkeypatch, [""])
    main.run_wake_cycle()
    assert not proactive.slaapt()
    assert gezegd[0] == "piep"


def test_slaapzinnen_raken_routine_en_power_niet():
    def raakt(zin):
        return any(re.match(p, zin) for p in main.SLAAP_PATTERNS)

    for zin in ("ga slapen", "ga maar slapen", "welterusten", "welterusten jarvis", "slaap lekker"):
        assert raakt(zin), zin
    for zin in ("ik ga slapen", "zet de pc in slaapstand", "slaapstand", "ga slapen over tien minuten"):
        assert not raakt(zin), zin


def test_stop_jarvis_blijft_gewone_standby(monkeypatch):
    gezegd, _ = _sessie(monkeypatch, ["stop jarvis"])
    main.run_wake_cycle()
    assert not proactive.slaapt()


# ---------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------

def _api():
    from dashboard.api import DashboardAPI

    return DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False)


def test_dashboard_status_slaapt():
    api = _api()
    assert api.status()[1]["fase"] == "rust" and api.status()[1]["slaapt"] is False
    proactive.ga_slapen()
    s = api.status()[1]
    assert s["fase"] == "slaapt" and s["slaapt"] is True
    api.fase_fn = lambda: "luistert"
    assert api.status()[1]["fase"] == "luistert"


def test_pwa_kent_slaapt():
    import os

    js = open(os.path.join(os.path.dirname(main.__file__), "dashboard", "static", "app.js"), encoding="utf-8").read()
    css = open(os.path.join(os.path.dirname(main.__file__), "dashboard", "static", "styles.css"), encoding="utf-8").read()
    assert "slaapt: { label: 'SLAAPT'" in js
    assert ".fase-slaapt" in css and ".ai-reactor.sleeping" in css
