"""Tests voor drie restpunten van Fase 17 (aanvulling).

1. ``opzoeken_confirm`` en ``prijs_confirm`` zijn strikte soorten: alleen een
   echt "ja" start de zoekopdracht. Een gewoon commando ("ok zet de muziek
   harder") laat het aanbod vervallen en wordt daarna normaal verwerkt.
2. Meerdere programma's worden pas geopend als ELKE naam bestaat. Mappen,
   bestanden en huisapparaten gaan naar hun eigen handler.
3. Het dashboard gebruikt poort 8780 en niet de remote-poort 8765.
"""

import pytest

import config
from core import brain, confirmation
from remote import tools as remote_tools


ZOEK_KINDS = ("opzoeken_confirm", "prijs_confirm")

JA_WOORDEN = [
    "ja",
    "ja graag",
    "doe maar",
    "zoek maar op",
    "ja zoek maar op",
    "ja opzoeken",
    "ja doe maar",
    "yes",
    "yes please",
    "go ahead",
]

NEE_WOORDEN = [
    "ja maar niet nu",
    "nee",
    "nee dank je",
    "liever niet",
    "geen",
]

GEEN_JA_NEE = [
    "ok",
    "goed",
    "prima dat is goed",
    "oke wat is het weer",
    "ok zet de muziek harder",
]


@pytest.fixture(autouse=True)
def schone_pending():
    """Geen enkele test laat een bevestiging achter."""
    confirmation.clear_pending()
    yield
    confirmation.clear_pending()


class _Recorder:
    """Vervangt execute_tool en onthoudt welke tools zijn aangeroepen."""

    def __init__(self, vind_antwoord="done"):
        self.calls = []
        self.vind_antwoord = vind_antwoord

    def __call__(self, tool_name, arguments, question=None, **kwargs):
        self.calls.append((tool_name, arguments))
        if tool_name == "game_pc_find_program_location":
            return self.vind_antwoord
        return "done"


@pytest.fixture
def game_pc(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "game-pc")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    remote_tools._reset_client()
    yield
    remote_tools._reset_client()


# =============================================================
# 1. Strikte bevestiging voor het opzoek-aanbod
# =============================================================

@pytest.mark.parametrize("kind", ZOEK_KINDS)
@pytest.mark.parametrize("woord", JA_WOORDEN)
def test_ja_woorden_gelden_als_ja(kind, woord):
    confirmation.set_pending(
        kind, payload={"vraag": "wat is de hoofdstad van frankrijk?"}, ttl=60
    )

    assert confirmation.evaluate_answer(woord, kind) == "yes", woord


@pytest.mark.parametrize("kind", ZOEK_KINDS)
@pytest.mark.parametrize("woord", NEE_WOORDEN)
def test_ontkenning_is_nee(kind, woord):
    confirmation.set_pending(
        kind, payload={"vraag": "wat is de hoofdstad van frankrijk?"}, ttl=60
    )

    assert confirmation.evaluate_answer(woord, kind) == "no", woord


@pytest.mark.parametrize("zin", GEEN_JA_NEE)
def test_ander_antwoord_wist_het_aanbod(zin):
    confirmation.set_pending(
        "opzoeken_confirm",
        payload={"vraag": "wat is de hoofdstad van frankrijk?"},
        ttl=60,
    )

    assert confirmation.evaluate_answer(zin, "opzoeken_confirm") == "cancel", zin
    assert confirmation.get_pending() is None


def test_ander_commando_na_aanbod_zoekt_niets_op(monkeypatch):
    """'ok zet de muziek harder' mag geen zoekopdracht starten."""
    zoekacties = []

    def nep_zoek(query, max_pages=1):
        zoekacties.append(query)
        return {"ok": False}

    monkeypatch.setattr("actions.web.search_and_fetch", nep_zoek)

    confirmation.set_pending(
        "opzoeken_confirm",
        payload={"vraag": "wat is de hoofdstad van frankrijk?"},
        ttl=60,
    )

    # None = de zin gaat daarna als gewoon commando verder (muziek).
    assert brain.handle_pending_choice("ok zet de muziek harder") is None
    assert zoekacties == []
    assert confirmation.get_pending() is None


def test_ja_zoek_maar_op_na_aanbod_zoekt_wel(monkeypatch):
    from core import opzoeken

    monkeypatch.setattr(
        opzoeken, "zoek_op", lambda vraag: f"opgezocht: {vraag}"
    )

    confirmation.set_pending(
        opzoeken.KIND,
        payload={"vraag": "wat is de hoofdstad van frankrijk?"},
        ttl=60,
    )

    antwoord = brain.handle_pending_choice("ja zoek maar op")

    assert antwoord == "opgezocht: wat is de hoofdstad van frankrijk?"
    assert confirmation.get_pending() is None


# =============================================================
# 2. Alleen bestaande programma's openen
# =============================================================

GEEN_PROGRAMMA_ZINNEN = [
    "open de map downloads en documenten",
    "open het bestand rapport en factuur",
    "open de deur en de ramen",
    "start de wasmachine en de droger",
    "open de computer en de printer",
    "start een spelletje en een film",
    "start de game en de stream",
]


@pytest.mark.parametrize("zin", GEEN_PROGRAMMA_ZINNEN)
def test_gewone_zin_opent_geen_programma(monkeypatch, game_pc, zin):
    recorder = _Recorder(vind_antwoord="dat is niet gevonden.")
    monkeypatch.setattr(brain, "execute_tool", recorder)

    assert brain.try_multi_open_program(zin) is None, zin
    assert brain.try_open_program(zin) is None, zin

    geopend = [t for t, _ in recorder.calls if t == "game_pc_open_program"]
    assert geopend == [], zin


def test_map_gaat_naar_de_map_handler(monkeypatch, game_pc):
    """'open de map downloads en documenten' is geen programma-openlijst."""
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    zin = "open de map downloads en documenten"

    assert brain.is_multi_open_program(zin) is False
    assert brain.try_open_program(zin) is None
    assert recorder.calls == []


def test_meerdere_programmas_openen_na_bestaanscontrole(monkeypatch, game_pc):
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    antwoord = brain.try_open_program("open spotify en discord")

    assert antwoord is not None
    tools = [tool for tool, _ in recorder.calls]
    assert tools == [
        "game_pc_find_program_location",
        "game_pc_find_program_location",
        "game_pc_open_program",
        "game_pc_open_program",
    ], tools
    namen = [args.get("program") for _, args in recorder.calls]
    assert namen == ["spotify", "discord", "spotify", "discord"], namen


def test_een_ontbrekend_programma_opent_niets(monkeypatch, game_pc):
    recorder = _Recorder(vind_antwoord="zippie is niet gevonden.")
    monkeypatch.setattr(brain, "execute_tool", recorder)

    assert brain.try_open_program("open spotify en zippie") is None

    assert [t for t, _ in recorder.calls if t == "game_pc_open_program"] == []


# =============================================================
# 3. Dashboardpoort
# =============================================================

def test_dashboardpoort_is_8780_en_verschilt_van_remote():
    assert config.DASHBOARD_PORT == 8780
    assert config.DASHBOARD_PORT != config.REMOTE_SERVER_PORT
