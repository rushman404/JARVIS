"""Fase 19, M2 — hartslag, waakhond, exitcodes en brein-status op het dashboard."""

import json
import os
from types import SimpleNamespace

import pytest

import main
import status
from beheer import hartslag, waakhond


# ---------------------------------------------------------------
# Hartslag
# ---------------------------------------------------------------

def _hs(tijd, teken, fase="rust", pid=42):
    return {"tijd": tijd, "laatste_teken": teken, "fase": fase, "pid": pid}


def test_gezonde_hartslag():
    assert hartslag.vastgelopen(_hs(1000, 999), nu=1005, pid=42, gestart_op=0) is None


def test_geen_hartslag_binnen_gratie_is_goed_daarna_niet():
    assert hartslag.vastgelopen(None, nu=100, pid=42, gestart_op=0) is None
    assert "geen hartslag" in hartslag.vastgelopen(None, nu=hartslag.OPSTART_GRATIE + 1, pid=42, gestart_op=0)


def test_hartslag_van_vorig_proces_telt_niet():
    oud = _hs(1000, 1000, pid=7)
    assert hartslag.vastgelopen(oud, nu=1005, pid=42, gestart_op=1000) is None
    assert hartslag.vastgelopen(oud, nu=1000 + hartslag.OPSTART_GRATIE + 1, pid=42, gestart_op=1000)


def test_proces_staat_stil():
    reden = hartslag.vastgelopen(_hs(1000, 1000), nu=1000 + hartslag.MAX_STIL_SECONDEN + 1, pid=42, gestart_op=0)
    assert "geen hartslag meer" in reden


def test_audio_dood_in_rust():
    nu = 5000
    reden = hartslag.vastgelopen(_hs(nu, nu - hartslag.MAX_RUST_ZONDER_TEKEN - 1), nu=nu, pid=42, gestart_op=0)
    assert "geen audio" in reden


def test_lang_denken_mag_maar_niet_eindeloos():
    nu = 5000
    teken = nu - hartslag.MAX_RUST_ZONDER_TEKEN - 1
    assert hartslag.vastgelopen(_hs(nu, teken, fase="denkt"), nu=nu, pid=42, gestart_op=0) is None
    teken = nu - hartslag.MAX_BEZIG_ZONDER_TEKEN - 1
    assert "denkt" in hartslag.vastgelopen(_hs(nu, teken, fase="denkt"), nu=nu, pid=42, gestart_op=0)


def test_hartslagschrijver_schrijft_bestand(tmp_path):
    pad = str(tmp_path / "hs.json")
    schrijver = hartslag.HartslagSchrijver(pad=pad, fase_fn=lambda: "denkt", teken_fn=lambda: 123.0)
    schrijver._een_slag()
    data = json.loads(open(pad, encoding="utf-8").read())
    assert data["fase"] == "denkt" and data["laatste_teken"] == 123.0 and data["pid"] == os.getpid()
    assert hartslag.lees_json(str(tmp_path / "bestaat-niet.json")) is None


def test_status_tikt_bij_fasewissel(monkeypatch):
    monkeypatch.setattr(status.time, "time", lambda: 777.0)
    status.wacht()
    assert status.laatste_teken() == 777.0
    monkeypatch.setattr(status.time, "time", lambda: 888.0)
    status.luistert()
    assert status.laatste_teken() == 888.0
    status.wacht()


# ---------------------------------------------------------------
# Waakhond
# ---------------------------------------------------------------

class NepProces:
    def __init__(self, pid, codes):
        self.pid = pid
        self._codes = list(codes)  # wat poll() achtereenvolgens geeft
        self.gestopt = False

    def poll(self):
        if self.gestopt:
            return -1
        return self._codes.pop(0) if self._codes else None

    def terminate(self):
        self.gestopt = True

    def wait(self, timeout=None):
        return -1

    def kill(self):
        self.gestopt = True


class NepPopen:
    """Elke start geeft het volgende NepProces; onthoudt de env."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.starts = []

    def __call__(self, commando, cwd=None, env=None):
        self.starts.append(env)
        pid = 100 + len(self.starts)
        return NepProces(pid, self.scripts.pop(0) if self.scripts else [])


class Klok:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def slaap(self, s):
        self.t += s


def _waakhond(tmp_path, scripts, klok=None, melder=None):
    klok = klok or Klok()
    popen = NepPopen(scripts)
    wh = waakhond.Waakhond(
        commando=["python", "main.py"], werkmap=str(tmp_path),
        status_pad=str(tmp_path / "waakhond.json"), hartslag_pad=str(tmp_path / "hs.json"),
        popen=popen, klok=klok, slaap=klok.slaap, melder=melder,
    )
    wh._koppel_aan_job = lambda proces: None
    return wh, popen, klok


def _status(tmp_path):
    return json.loads((tmp_path / "waakhond.json").read_text(encoding="utf-8"))


def test_herstart_na_crash_en_stopt_bij_exit_0(tmp_path):
    wh, popen, _ = _waakhond(tmp_path, [[1], [0]])
    assert wh.draai(max_controles=20) == 0
    assert len(popen.starts) == 2
    assert popen.starts[0]["JARVIS_WAAKHOND"] == "1"
    assert "JARVIS_HERSTART_REDEN" not in popen.starts[0]
    assert popen.starts[1]["JARVIS_HERSTART_REDEN"] == "gecrasht (code 1)"
    st = _status(tmp_path)
    assert st["toestand"] == "gestopt" and st["herstarts"] == 1 and st["reden"] == "door u gestopt"


def test_geen_herstart_zonder_wake_word_model(tmp_path):
    meldingen = []
    wh, popen, _ = _waakhond(tmp_path, [[4]], melder=lambda t, m: meldingen.append(m))
    assert wh.draai(max_controles=20) == 0
    assert len(popen.starts) == 1
    assert meldingen and "wake-word" in meldingen[0]
    assert _status(tmp_path)["reden"] == "het wake-word-model ontbreekt"


def test_geeft_het_op_na_te_veel_herstarts(tmp_path):
    meldingen = []
    wh, popen, _ = _waakhond(tmp_path, [[1]] * 20, melder=lambda t, m: meldingen.append(m))
    assert wh.draai(max_controles=50) == 1
    assert len(popen.starts) == waakhond.MAX_HERSTARTS + 1
    assert _status(tmp_path)["toestand"] == "gestopt"
    assert meldingen and "herhaalde fouten" in meldingen[0]


def test_oplopende_wachttijd_en_reset_na_stabiel(tmp_path):
    wh, _, klok = _waakhond(tmp_path, [])
    wh.proces_gestart_op = klok()
    assert [wh._wachttijd() for _ in range(3)] == list(waakhond.WACHTTIJDEN[:3])
    klok.t += waakhond.STABIEL_NA
    assert wh._wachttijd() == waakhond.WACHTTIJDEN[0]


def test_crash_met_ntstatus_heet_afgebroken(tmp_path):
    assert "afgebroken" in waakhond._reden_exitcode(3221225477)
    assert "te veel fouten" in waakhond._reden_exitcode(3)


def test_vastloper_wordt_gestopt_en_herstart(tmp_path):
    wh, popen, klok = _waakhond(tmp_path, [[], [0]])
    wh._start()
    klok.t += hartslag.OPSTART_GRATIE + 10  # nooit een hartslag geschreven
    reden = wh.controleer()
    assert reden.startswith("vastgelopen") and wh.proces.gestopt


def test_status_bevat_geen_omgeving(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_CONTROL_TOKEN", "supergeheimtoken123")
    wh, _, _ = _waakhond(tmp_path, [[0]])
    wh.draai(max_controles=5)
    assert "supergeheim" not in (tmp_path / "waakhond.json").read_text(encoding="utf-8")


def test_slot_maar_een_waakhond(tmp_path):
    pad = str(tmp_path / "w.lock")
    eerste = waakhond.neem_slot(pad)
    try:
        assert eerste is not None
        assert waakhond.neem_slot(pad) is None
    finally:
        eerste.close()


# ---------------------------------------------------------------
# Brein-status (dashboard)
# ---------------------------------------------------------------

def test_brein_status_bewaakt(tmp_path):
    pad = tmp_path / "waakhond.json"
    pad.write_text(json.dumps({
        "jarvis_pid": 42, "herstarts": 2,
        "laatste_herstart": {"tijd": 1_792_900_000, "reden": "gecrasht (code 1)"},
    }), encoding="utf-8")
    b = waakhond.brein_status(nu=10_000, status_pad=str(pad), env={"JARVIS_WAAKHOND": "1"},
                              pid=42, proces_start=10_000 - 125 * 60)
    assert b["bewaakt"] and b["herstarts"] == 2 and b["actief_minuten"] == 125
    assert b["laatste_herstart"]["reden"] == "gecrasht (code 1)"
    assert len(b["laatste_herstart"]["tijd"]) == len("25-10 12:00")


def test_brein_status_niet_bewaakt(tmp_path):
    pad = tmp_path / "waakhond.json"
    pad.write_text(json.dumps({"jarvis_pid": 7, "herstarts": 9}), encoding="utf-8")
    zonder = waakhond.brein_status(nu=100, status_pad=str(pad), env={}, pid=42, proces_start=40)
    ander = waakhond.brein_status(nu=100, status_pad=str(pad), env={"JARVIS_WAAKHOND": "1"}, pid=42, proces_start=40)
    for b in (zonder, ander):
        assert not b["bewaakt"] and b["herstarts"] == 0 and b["laatste_herstart"] is None


def test_dashboard_pc_status_lokaal_heeft_brein():
    from dashboard.bronnen import Bronnen

    b = Bronnen(telemetrie_lokaal_fn=lambda: {}, telemetrie_game_pc_fn=lambda: None,
                brein_fn=lambda: {"actief_minuten": 5, "bewaakt": True, "herstarts": 0, "laatste_herstart": None})
    assert b.pc_status("local")["brein"]["actief_minuten"] == 5
    assert "brein" not in b.pc_status("game-pc")


def test_dashboard_brein_fout_breekt_meters_niet():
    from dashboard.bronnen import Bronnen

    def stuk():
        raise RuntimeError

    b = Bronnen(telemetrie_lokaal_fn=lambda: {}, brein_fn=stuk)
    assert b.pc_status("local")["doel"] == "local"


def test_pwa_toont_brein_regel():
    js = open(os.path.join(os.path.dirname(main.__file__), "dashboard", "static", "app.js"), encoding="utf-8").read()
    assert "function breinRegel(" in js and "innerHTML" not in js.split("function breinRegel(")[1][:800]


# ---------------------------------------------------------------
# main.py: exitcodes en herstartmelding
# ---------------------------------------------------------------

@pytest.fixture
def nep_jarvis(monkeypatch):
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.llm, "check_model_available", lambda: True)

    class _FakeAudio:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(main, "AudioSource", _FakeAudio)
    monkeypatch.setattr(main, "set_audio_source", lambda source: None)
    monkeypatch.setattr(main.atexit, "register", lambda *a, **k: None)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main, "_start_dashboard", lambda engine: None)

    gezegd = []
    monkeypatch.setattr(main, "speak", lambda *a, **k: gezegd.append(a[0] if a else ""))

    meldingen = []

    class FakeEngine:
        def start(self):
            pass

        def stop(self):
            pass

        def meld_activiteit(self):
            pass

        def meld(self, tekst, bron="systeem"):
            meldingen.append((tekst, bron))

    monkeypatch.setattr(main.proactive, "get_engine", lambda **kw: FakeEngine())
    monkeypatch.delenv("JARVIS_WAAKHOND", raising=False)
    monkeypatch.delenv("JARVIS_HERSTART_REDEN", raising=False)
    return SimpleNamespace(gezegd=gezegd, meldingen=meldingen)


def test_exitcode_zonder_wake_word_model(nep_jarvis, monkeypatch):
    monkeypatch.setattr(main, "run_wake_cycle", lambda: "geen_wake_word")
    assert main.start_jarvis() == main.EXIT_GEEN_WAKE_WORD == waakhond.EXIT_GEEN_WAKE_WORD
    assert nep_jarvis.gezegd[0] == "JARVIS is online."
    assert nep_jarvis.meldingen == []


def test_exitcode_na_te_veel_crashes(nep_jarvis, monkeypatch):
    def crash():
        raise RuntimeError("stuk")

    monkeypatch.setattr(main, "run_wake_cycle", crash)
    assert main.start_jarvis() == main.EXIT_TE_VEEL_CRASHES == 3


def test_herstartmelding_na_waakhond(nep_jarvis, monkeypatch):
    monkeypatch.setenv("JARVIS_HERSTART_REDEN", "gecrasht (code 1)")
    monkeypatch.setattr(main, "run_wake_cycle", lambda: "geen_wake_word")
    main.start_jarvis()
    assert nep_jarvis.gezegd[0] == "JARVIS is weer online."
    tekst, bron = nep_jarvis.meldingen[0]
    assert "opnieuw opgestart" in tekst and "gecrasht (code 1)" in tekst and bron == "herstart"
