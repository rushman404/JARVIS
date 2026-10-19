"""Tests voor proactieve meldingen, microfoon-mute en nachtmodus-override.

Dekt de vier gevraagde gedragingen:

1. Een melding tijdens een gesprek wordt pas ná het gesprek uitgesproken;
   tijdens het idle wachten op het wake word wél.
2. Twee gelijktijdige ``speak()``-aanroepen houden de microfoon bij beide
   gedempt (refcount in ``AudioSource``).
3. De handmatige nachtmodus-override (auto/aan/uit) verandert
   ``is_nachtmodus`` echt, en "nachtmodus aan" raakt de stille modus niet.
4. ``main.py`` koppelt de "in gesprek"-vlag aan de proactieve engine en zet
   die alleen vanaf de wake-word-detectie tot het einde van de sessie.
"""

import json
import threading
from datetime import datetime

import pytest

import main
from core import proactive
from core import timers as timers_module
from core.proactive import ProactiveEngine
from core.proactive_commands import try_proactive_command
from voice.audio_stream import AudioSource, set_audio_source


@pytest.fixture(autouse=True)
def schone_staat(monkeypatch):
    """Vaste nachtmodus-grenzen en schone globale vlaggen."""

    monkeypatch.setattr(proactive, "NACHTMODUS_START", 23)
    monkeypatch.setattr(proactive, "NACHTMODUS_EIND", 7)
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    yield
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    proactive.reset_engine(None)
    set_audio_source(None)
    timers_module.reset_store(None)


class FakeKlok:
    """Datetime- én epoch-klok die de test zelf aanstuurt."""

    def __init__(self, uur=12, minuut=0, ts=0.0):
        self.dt = datetime(2026, 3, 2, uur, minuut)
        self.ts = ts

    def now(self):
        return self.dt

    def tijd(self):
        return self.ts


def _schrijf_regels(tmp_path, regels):
    pad = tmp_path / "proactive_rules.json"
    pad.write_text(
        json.dumps({"regels": regels}, ensure_ascii=False), encoding="utf-8"
    )
    return str(pad)


# =============================================================
# 2. Microfoon blijft gedempt zolang een spreker actief is
# =============================================================

def test_mute_is_referentiegeteld():
    """mute()/unmute() tellen: pas bij de laatste unmute gaat de mic open."""

    bron = AudioSource()
    assert bron.is_muted() is False

    bron.mute()
    bron.mute()
    assert bron.is_muted() is True

    bron.unmute()
    assert bron.is_muted() is True, "een spreker is nog bezig"

    bron.unmute()
    assert bron.is_muted() is False

    # Een overtollige unmute mag de teller niet negatief maken.
    bron.unmute()
    assert bron.is_muted() is False


def test_twee_speak_aanroepen_laten_microfoon_gedempt(monkeypatch):
    """Twee gelijktijdige speak() houden de mic bij beide gedempt."""

    from voice import speak as speak_mod

    bron = AudioSource()
    set_audio_source(bron)

    class FakeEngine:
        def __init__(self):
            self.calls = []
            self._n = 0
            self.eerste_bezig = threading.Event()
            self.eerste_vrij = threading.Event()
            self.tweede_bezig = threading.Event()
            self.tweede_vrij = threading.Event()

        def say(self, text):
            self.calls.append(text)

        def runAndWait(self):
            self._n += 1
            if self._n == 1:
                self.eerste_bezig.set()
                self.eerste_vrij.wait(timeout=5)
            else:
                self.tweede_bezig.set()
                self.tweede_vrij.wait(timeout=5)

        def setProperty(self, *args, **kwargs):  # pragma: no cover - no-op
            pass

    engine = FakeEngine()
    monkeypatch.setattr(speak_mod, "engine", engine)

    een = threading.Thread(target=speak_mod.speak, args=("een",))
    twee = threading.Thread(target=speak_mod.speak, args=("twee",))

    een.start()
    assert engine.eerste_bezig.wait(timeout=5), "eerste spreker startte niet"
    assert bron.is_muted() is True

    twee.start()
    # Laat T1 afronden; T2 neemt de lock over en gaat spreken.
    engine.eerste_vrij.set()
    assert engine.tweede_bezig.wait(timeout=5), "tweede spreker startte niet"

    # De kern: terwijl de tweede spreker praat, mag de unmute van de eerste
    # de microfoon niet hebben geopend.
    assert bron.is_muted() is True, "eerste unmute mocht de mic niet openen"

    engine.tweede_vrij.set()
    een.join(timeout=5)
    twee.join(timeout=5)

    assert not een.is_alive() and not twee.is_alive()
    assert bron.is_muted() is False, "na beide sprekers gaat de mic weer open"
    assert engine.calls == ["een", "twee"]


def test_speak_dempt_en_ontdempt_sequentieel(monkeypatch):
    """Eén speak() laat de microfoon gedempt tijdens en open na het spreken."""

    from voice import speak as speak_mod

    bron = AudioSource()
    set_audio_source(bron)

    toestand = {}

    class FakeEngine:
        def say(self, text):
            toestand["tekst"] = text

        def runAndWait(self):
            toestand["tijdens"] = bron.is_muted()

        def setProperty(self, *args, **kwargs):  # pragma: no cover - no-op
            pass

    monkeypatch.setattr(speak_mod, "engine", FakeEngine())

    speak_mod.speak("hallo")

    assert toestand["tekst"] == "hallo"
    assert toestand["tijdens"] is True, "tijdens het spreken is de mic dicht"
    assert bron.is_muted() is False, "na het spreken gaat de mic weer open"


# =============================================================
# 3. Nachtmodus-override (auto/aan/uit)
# =============================================================

def test_nachtmodus_stand_staat_standaard_op_auto():
    assert proactive.get_nachtmodus_stand() == "auto"


def test_nachtmodus_override_aan_negeert_de_klok():
    """'aan' betekent nachtmodus, ook midden op de dag."""

    proactive.set_nachtmodus("aan")
    assert proactive.get_nachtmodus_stand() == "aan"
    assert proactive.is_nachtmodus(datetime(2026, 1, 1, 14, 0)) is True


def test_nachtmodus_override_uit_negeert_de_klok():
    """'uit' betekent géén nachtmodus, ook midden in de nacht."""

    proactive.set_nachtmodus("uit")
    assert proactive.get_nachtmodus_stand() == "uit"
    assert proactive.is_nachtmodus(datetime(2026, 1, 1, 23, 30)) is False


def test_nachtmodus_auto_volgt_de_klok():
    proactive.set_nachtmodus("auto")
    assert proactive.is_nachtmodus(datetime(2026, 1, 1, 23, 30)) is True
    assert proactive.is_nachtmodus(datetime(2026, 1, 1, 12, 0)) is False


def test_nachtmodus_ongeldige_stand_valt_terug_op_auto():
    proactive.set_nachtmodus("aan")
    proactive.set_nachtmodus("onzin")
    assert proactive.get_nachtmodus_stand() == "auto"


def test_commando_nachtmodus_aan_zet_override_en_laat_stille_modus():
    """'zet de nachtmodus aan' zet de override écht en raakt quiet niet."""

    proactive.set_quiet(True)

    antwoord = try_proactive_command("zet de nachtmodus aan")

    assert antwoord is not None
    assert proactive.get_nachtmodus_stand() == "aan"
    assert proactive.is_nachtmodus(datetime(2026, 1, 1, 14, 0)) is True
    assert proactive.is_quiet() is True, "nachtmodus mag de stille modus niet raken"


def test_commando_nachtmodus_uit_zet_override():
    antwoord = try_proactive_command("nachtmodus uit")

    assert antwoord is not None
    assert proactive.get_nachtmodus_stand() == "uit"
    assert proactive.is_nachtmodus(datetime(2026, 1, 1, 23, 30)) is False


def test_commando_nachtmodus_aan_dan_uit():
    try_proactive_command("ga in nachtmodus")
    assert proactive.get_nachtmodus_stand() == "aan"

    try_proactive_command("stop nachtmodus")
    assert proactive.get_nachtmodus_stand() == "uit"


# =============================================================
# 1 + 4. "In gesprek"-vlag: main.py wiring en engine-gedrag
# =============================================================

def test_run_wake_cycle_zet_gesprek_alleen_tijdens_de_sessie(monkeypatch):
    """Tijdens het wachten op het wake word géén gesprek; daarna wel."""

    gezien = {}

    def fake_wait():
        gezien["tijdens_wachten"] = proactive.is_in_gesprek()
        return {"detected_at": 5.0}

    monkeypatch.setattr(main, "wait_for_wake_word", fake_wait)
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)

    def fake_process(cmd):
        gezien["tijdens_commando"] = proactive.is_in_gesprek()
        return None

    monkeypatch.setattr(main, "process_command", fake_process)

    opdrachten = iter(["doe iets", ""])
    monkeypatch.setattr(main, "listen", lambda start_ts=None: next(opdrachten))

    proactive.set_in_gesprek(False)
    resultaat = main.run_wake_cycle()

    assert resultaat == "ok"
    assert gezien["tijdens_wachten"] is False, "idle wachten is geen gesprek"
    assert gezien["tijdens_commando"] is True, "tijdens de sessie is het gesprek"
    assert proactive.is_in_gesprek() is False, "na de sessie weer vrij"


def test_run_wake_cycle_zonder_wake_word_zet_gesprek_niet(monkeypatch):
    """Zonder wake word wordt de vlag nooit gezet."""

    monkeypatch.setattr(
        main,
        "wait_for_wake_word",
        lambda: {"detected_at": None, "status": "geen_model"},
    )

    proactive.set_in_gesprek(False)
    resultaat = main.run_wake_cycle()

    assert resultaat == "geen_wake_word"
    assert proactive.is_in_gesprek() is False


def test_engine_levert_tijdens_idle_wel(tmp_path):
    """Buiten een gesprek levert de engine gewoon af (ook een timer)."""

    klok = FakeKlok(uur=12, ts=0.0)
    geleverd = []
    engine = ProactiveEngine(
        now_fn=klok.now,
        time_fn=klok.tijd,
        rules_pad=_schrijf_regels(tmp_path, []),
        lever_fn=lambda m: geleverd.append(m.tekst),
        in_gesprek_fn=proactive.is_in_gesprek,
    )

    proactive.set_in_gesprek(False)
    engine._verstuur("Je timer is afgelopen.", bron="timer")
    engine.tick()

    assert geleverd == ["Je timer is afgelopen."]


def test_engine_wacht_tijdens_gesprek_en_levert_daarna(tmp_path):
    """Een melding tijdens een gesprek komt pas ná het gesprek."""

    klok = FakeKlok(uur=12, ts=0.0)
    geleverd = []
    engine = ProactiveEngine(
        now_fn=klok.now,
        time_fn=klok.tijd,
        rules_pad=_schrijf_regels(tmp_path, []),
        lever_fn=lambda m: geleverd.append(m.tekst),
        in_gesprek_fn=proactive.is_in_gesprek,
    )

    proactive.set_in_gesprek(True)
    engine._verstuur("Je timer is afgelopen.", bron="timer")
    engine.tick()

    assert geleverd == [], "tijdens het gesprek wordt niets uitgesproken"
    assert engine.wachtrij.lengte() == 1

    proactive.set_in_gesprek(False)
    engine.tick()

    assert geleverd == ["Je timer is afgelopen."]


def test_start_jarvis_koppelt_in_gesprek_fn(monkeypatch):
    """main.py bouwt de engine met in_gesprek_fn=proactive.is_in_gesprek."""

    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.llm, "check_model_available", lambda: True)
    monkeypatch.setattr(
        main.pc_target, "remote_client_configuratie_fout", lambda: None
    )

    class FakeAudio:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(main, "AudioSource", FakeAudio)
    monkeypatch.setattr(main, "set_audio_source", lambda source: None)
    monkeypatch.setattr(main.atexit, "register", lambda *a, **k: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    gezien = {}

    class FakeEngine:
        def start(self):
            pass

        def stop(self):
            pass

        def meld_activiteit(self):
            pass

    def fake_get_engine(**kwargs):
        gezien.update(kwargs)
        return FakeEngine()

    monkeypatch.setattr(main.proactive, "get_engine", fake_get_engine)
    monkeypatch.setattr(main, "run_wake_cycle", lambda: "geen_wake_word")

    main.start_jarvis()

    assert gezien.get("in_gesprek_fn") is proactive.is_in_gesprek


def test_gesprek_vlag_beeindigt_ook_bij_een_fout(monkeypatch):
    """Een crash in de sessie laat de vlag niet per ongeluk aan staan."""

    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 1.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)
    monkeypatch.setattr(main, "listen", lambda start_ts=None: "doe iets")

    def val_om(cmd):
        raise RuntimeError("kapot")

    monkeypatch.setattr(main, "process_command", val_om)

    proactive.set_in_gesprek(False)
    with pytest.raises(RuntimeError):
        main.run_wake_cycle()

    assert proactive.is_in_gesprek() is False, "de vlag moet altijd opgeruimd worden"
