"""Telemetrie: temperatuur- en gebruiksvragen bereiken de telemetrie.

Dekt:
    - bij doel game-pc gaan de vragen rechtstreeks naar ``game_pc_telemetry``,
      ook zonder dat de zin "game-pc" bevat;
    - bij doel local geven ze de lokale pc-status als gesproken zin;
    - de vragen schrijven nooit iets naar het geheugen (geen remember).
"""
import pytest

import config
from core import brain
from remote import tools as remote_tools


# De zinnen uit de opdracht: deterministische telemetrievragen.
TELEMETRIE_ZINNEN = [
    "hoe warm is mijn gpu",
    "hoe warm is mijn cpu",
    "hoe zwaar is mijn pc belast",
    "hoeveel vram",
    "hoeveel gebruik ik",
]


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, tool_name, arguments, question=None, **kwargs):
        self.calls.append((tool_name, arguments, question))
        return "De game-pc: CPU 23 procent, geheugen 45 procent."


@pytest.fixture
def game_pc(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "game-pc")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    remote_tools._reset_client()
    yield
    remote_tools._reset_client()


def _fout(*args, **kwargs):
    raise AssertionError("deze functie mag hier niet lokaal worden uitgevoerd")


@pytest.mark.parametrize("zin", TELEMETRIE_ZINNEN)
def test_telemetrievraag_gaat_naar_game_pc_telemetry(monkeypatch, game_pc, zin):
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)
    monkeypatch.setattr(brain, "pc_status_tool", _fout)

    resultaat = brain.try_system_info(zin)

    assert isinstance(resultaat, str) and resultaat, f"geen gesproken antwoord voor {zin!r}"
    assert recorder.calls, f"execute_tool niet aangeroepen voor {zin!r}"
    assert recorder.calls[-1][0] == "game_pc_telemetry"


@pytest.mark.parametrize("zin", TELEMETRIE_ZINNEN)
def test_telemetrievraag_lokaal_geeft_gesproken_zin(monkeypatch, zin):
    monkeypatch.setattr(config, "PC_TARGET", "local")
    monkeypatch.setattr(
        brain,
        "pc_status_tool",
        lambda: {
            "ok": True,
            "systeem": {
                "os": "Windows 11",
                "cpu": "AMD Ryzen 7",
                "ram_totaal": 16,
                "ram_vrij": 8,
                "disk_vrij": 120,
                "disk_totaal": 500,
                "batterij": {},
                "uptime_dagen": 0,
                "uptime_uren": 1,
                "uptime_minuten": 2,
            },
            "pc_draait": True,
        },
    )

    resultaat = brain.try_system_info(zin)

    assert isinstance(resultaat, str) and resultaat, f"geen gesproken antwoord voor {zin!r}"


@pytest.mark.parametrize("zin", TELEMETRIE_ZINNEN)
def test_telemetrievraag_schrijft_niets_naar_geheugen(monkeypatch, zin):
    """Een vraag mag nooit als geheugen worden opgeslagen."""

    aanroepen = []
    monkeypatch.setattr(brain, "remember", lambda *a, **k: aanroepen.append((a, k)))

    assert brain.auto_remember(zin) in (None, "")
    assert brain.try_remember_device(zin) is None
    assert aanroepen == [], f"wel iets opgeslagen voor {zin!r}"


def test_apparaatnaam_bij_statement_blijft_werken(monkeypatch):
    """Bestaande apparaten-namen blijven werken ('X is mijn brok' -> opslaan)."""

    opgeslagen = []
    monkeypatch.setattr(
        brain, "remember", lambda *a, **k: opgeslagen.append((a, k))
    )

    # "deurbel is mijn voordeur": 'voordeur' is een bekend apparaat.
    resultaat = brain.try_remember_device("deurbel is mijn voordeur")
    assert resultaat is not None
    assert opgeslagen, "statement met bekend apparaat moet worden opgeslagen"


def test_onbekend_tweede_deel_bij_is_mijn_wordt_niet_opgeslagen(monkeypatch):
    """'<naam> is mijn <onbekend>' slaat niets op (geen aankoppeling)."""

    opgeslagen = []
    monkeypatch.setattr(
        brain, "remember", lambda *a, **k: opgeslagen.append((a, k))
    )

    assert brain.try_remember_device("mijn bureaubladachtergrond is mijn pc") is None or not opgeslagen
    assert opgeslagen == []


def test_pc_specificatie_statement_blijft_werken(monkeypatch):
    """'mijn gpu is een rtx 4070' is geen vraag en blijft worden onthouden."""

    opgeslagen = []
    monkeypatch.setattr(
        brain, "remember", lambda *a, **k: opgeslagen.append((a, k)) or {}
    )

    resultaat = brain.auto_remember("mijn gpu is een rtx 4070")

    assert resultaat is not None
    assert opgeslagen, "pc-specificatie moet worden opgeslagen"
