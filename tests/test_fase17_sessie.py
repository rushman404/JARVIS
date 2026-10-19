"""Tests voor Fase 17, B2: sessie-modus (doorlopend gesprek).

Binnen één sessie hoeft u niet bij elke beurt opnieuw "JARVIS" te zeggen;
de sessie eindigt pas na ``SESSIE_TIMEOUT_SECONDEN`` seconden zonder spraak
(of met een stopcommando). De wachttijd wordt via ``listen`` aan de
opname-laag doorgegeven.
"""

import pytest

import main
from voice import listen as listen_mod


@pytest.fixture(autouse=True)
def schone_staat():
    from core import proactive

    proactive.set_in_gesprek(False)
    yield
    proactive.set_in_gesprek(False)


# ---------------------------------------------------------------
# 1. listen geeft de wachttijd door aan de opname-laag
# ---------------------------------------------------------------

def test_listen_geeft_wacht_seconden_door(monkeypatch):
    gezien = {}

    monkeypatch.setattr(listen_mod, "get_audio_source", lambda: object())

    def fake_capture(start_ts=None, audio_source=None, wacht_seconden=None):
        gezien["start_ts"] = start_ts
        gezien["wacht_seconden"] = wacht_seconden
        return None

    monkeypatch.setattr(listen_mod, "_capture", fake_capture)

    # Geen audio (None) => "" (sessie verlopen).
    assert listen_mod.listen(start_ts=1.5, wacht_seconden=123) == ""
    assert gezien["start_ts"] == 1.5
    assert gezien["wacht_seconden"] == 123


def test_capture_geeft_wacht_seconden_door(monkeypatch):
    gezien = {}

    def fake_capture_from_source(source, start_ts, wacht_seconden=None):
        gezien["source"] = source
        gezien["start_ts"] = start_ts
        gezien["wacht_seconden"] = wacht_seconden
        return None

    monkeypatch.setattr(listen_mod, "_capture_from_source", fake_capture_from_source)

    bron = object()
    listen_mod._capture(start_ts=0.0, audio_source=bron, wacht_seconden=99)
    assert gezien["source"] is bron
    assert gezien["wacht_seconden"] == 99


# ---------------------------------------------------------------
# 2. De wachttijd-logica in _capture_from_source
# ---------------------------------------------------------------

class _StilleBron:
    """Bron die nooit audio levert (alleen read_frame)."""

    def __init__(self):
        self.aanroepen = 0

    def read_frame(self, after_ts=None, timeout=None):
        self.aanroepen += 1
        return None


class _FakeKlok:
    """Vervangt ``listen_mod.time`` zodat we de wachttijd kunnen sturen.

    We patchen alleen de naam in ``listen_mod`` (niet de echte ``time``-module),
    zodat logging en andere code gewoon blijven werken.
    """

    def __init__(self, waarden):
        self._waarden = iter(waarden)

    def time(self):
        return next(self._waarden)


def test_capture_from_source_standaard_wachttijd(monkeypatch):
    """Zonder wacht_seconden geldt WACHT_OP_SPRAAK_SECONDEN."""

    monkeypatch.setattr(listen_mod, "time", _FakeKlok([0.0, 50.0]))
    bron = _StilleBron()

    assert listen_mod._capture_from_source(bron, 0.0) is None
    # 50s > standaard 10s: na één lege read_frame stopt hij meteen.
    assert bron.aanroepen == 1


def test_capture_from_source_lange_sessie_wachttijd(monkeypatch):
    """Met een lange wachttijd blijft JARVIS veel langer luisteren."""

    monkeypatch.setattr(listen_mod, "time", _FakeKlok([0.0, 50.0, 2000.0]))
    bron = _StilleBron()

    assert listen_mod._capture_from_source(bron, 0.0, wacht_seconden=1000) is None
    # 50s < 1000s: hij wacht door; pas bij 2000s (> 1000) stopt hij.
    assert bron.aanroepen == 2


# ---------------------------------------------------------------
# 3. main.run_wake_cycle: doorlopend gesprek zonder herhaald wake word
# ---------------------------------------------------------------

def _basis_main(monkeypatch, opdrachten, gezien=None):
    """Zet main.run_wake_cycle klaar met een vaste reeks opdrachten."""
    gezien = gezien if gezien is not None else {}

    monkeypatch.setattr(main, "wait_for_wake_word", lambda: {"detected_at": 3.0})
    monkeypatch.setattr(main, "clear_pending", lambda: None)
    monkeypatch.setattr(main, "speak", lambda *a, **k: None)

    verwerkt = []

    def fake_process(cmd, on_tekst=None):
        verwerkt.append(cmd)
        return "ok"

    monkeypatch.setattr(main, "process_command", fake_process)

    reeks = iter(opdrachten)
    starts = []

    def fake_listen(start_ts=None, **kw):
        gezien.setdefault("wacht", []).append(kw.get("wacht_seconden"))
        starts.append(start_ts)
        return next(reeks)

    monkeypatch.setattr(main, "listen", fake_listen)
    gezien["verwerkt"] = verwerkt
    gezien["starts"] = starts
    return gezien


def test_sessie_meerdere_beurten_zonder_wake_word(monkeypatch):
    """Twee opdrachten in één sessie; pas daarna (stilte) eindigt de sessie."""

    gezien = _basis_main(monkeypatch, ["doe dit", "en doe dat", ""])

    assert main.run_wake_cycle() == "ok"

    assert gezien["verwerkt"] == ["doe dit", "en doe dat"]
    # Elke beurt gebruikt de lange sessie-wachttijd.
    assert gezien["wacht"] == [
        main.SESSIE_TIMEOUT_SECONDEN,
        main.SESSIE_TIMEOUT_SECONDEN,
        main.SESSIE_TIMEOUT_SECONDEN,
    ]
    # Alleen de eerste beurt begint bij de wake-word-detectie.
    assert gezien["starts"][0] == 3.0
    assert gezien["starts"][1] is None
    assert gezien["starts"][2] is None


def test_sessie_eindigt_met_stopcommando(monkeypatch):
    """Een stopcommando beëindigt de sessie meteen."""

    gezien = _basis_main(monkeypatch, ["stop jarvis"])

    assert main.run_wake_cycle() == "ok"

    # "stop jarvis" wordt niet verwerkt als commando, maar beëindigt de sessie.
    assert gezien["verwerkt"] == []


def test_sessie_beurt_na_onduidelijk_blijft_open(monkeypatch):
    """Na een onverstaanbare beurt blijft de sessie gewoon open."""

    gezien = _basis_main(monkeypatch, [None, "alsnog iets", ""])

    assert main.run_wake_cycle() == "ok"

    assert gezien["verwerkt"] == ["alsnog iets"]
