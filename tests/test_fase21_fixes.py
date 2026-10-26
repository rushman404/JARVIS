"""Fase 21 — reparaties na de eerste test op de iPad (2026-10-26)."""

import json
import os

import pytest

from core.result_validation import ToolResult

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -----------------------------------------------------------------
# Tv uit is laag risico; de slaaproutine vraagt niets meer
# -----------------------------------------------------------------

def test_tv_via_ha_is_laag_risico():
    from core.tool_registry import get_tool_risk

    args = {"domain": "media_player", "service": "turn_off", "entity_id": "media_player.tv"}
    assert get_tool_risk("control_home_assistant", args) == "low"
    # Stekkers en gordijnen blijven medium.
    assert get_tool_risk("control_home_assistant", {"domain": "switch"}) == "medium"
    assert get_tool_risk("control_home_assistant", {"domain": "cover"}) == "medium"


def test_slaaproutine_zonder_goedkeuring_en_zonder_tv_stekker():
    from core.tool_registry import get_tool_risk

    sleep = json.load(open(os.path.join(PROJECT, "config", "routines.json"), encoding="utf-8"))["sleep"]
    assert "switch.tv_switch" not in json.dumps(sleep)
    tv = [s for s in sleep["steps"] if (s.get("arguments") or {}).get("domain") == "media_player"]
    assert tv and tv[0]["arguments"]["service"] == "turn_off"
    for stap in sleep["steps"]:
        assert get_tool_risk(stap["tool_name"], stap.get("arguments")) == "low", stap


# -----------------------------------------------------------------
# Dashboard: routines hardop, resultaat van een ja/nee in de chat
# -----------------------------------------------------------------

def _api(**kw):
    from dashboard.api import DashboardAPI

    return DashboardAPI(fase_fn=lambda: "rust", spreekt_fn=lambda: False, audit_fn=lambda **k: None, **kw)


class NepRunner:
    def __init__(self):
        self.gestart = []

    def start_routine(self, naam, hardop=False, herkomst="dashboard"):
        self.gestart.append((naam, hardop))
        return True, None


def test_routine_vanaf_dashboard_standaard_hardop():
    api = _api()
    api.opdrachten = NepRunner()
    api._bronnen = type("B", (), {"routines_fn": staticmethod(lambda: {"gaming": {}})})()
    assert api.routine_start({"naam": "gaming"})[0] == 202
    assert api.routine_start({"naam": "gaming", "hardop": False})[0] == 202
    assert api.opdrachten.gestart == [("gaming", True), ("gaming", False)]


@pytest.mark.parametrize("besluit,verwacht", [("ja", "Speelt nu: x."), ("nee", "Goed, een andere keer, sir.")])
def test_resultaat_van_goedkeuring_komt_in_de_chat(besluit, verwacht):
    from core import confirmation

    gemeld = []
    api = _api(uitvoerder=lambda p, ja: "Speelt nu: x." if ja else "Goed, een andere keer, sir.",
               besluit_fn=gemeld.append)
    p = confirmation.set_pending("muziek_voorstel", {"keuze": {"uri": "u"}, "question": "Zal ik?"})
    status, data = api.goedkeuring({"id": p[confirmation.ID_KEY], "nonce": p[confirmation.NONCE_KEY],
                                    "besluit": besluit})
    assert status == 200 and data["resultaat"] == verwacht
    assert gemeld == [verwacht]


def test_server_geeft_de_melder_mee():
    import inspect

    from dashboard import server

    assert "besluit_fn=dashboard_api.meld_besluit" in inspect.getsource(server)


def test_meld_besluit_zet_het_in_het_gesprek(monkeypatch):
    import status
    from dashboard import api as dapi

    genoteerd = []
    monkeypatch.setattr(status, "noteer_gesprek", lambda wie, tekst: genoteerd.append((wie, tekst)))
    monkeypatch.setattr(dapi.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    dapi.meld_besluit("Bed lamp uit.")
    assert genoteerd == [("ai", "Bed lamp uit.")]


# -----------------------------------------------------------------
# "pauze" / "speel verder" gaan naar de pc als de tv uit is
# -----------------------------------------------------------------

def test_pauze_met_tv_uit_gaat_naar_de_pc(monkeypatch):
    from core import filmmodus, tv_bediening

    class TvUit:
        def staten(self):
            return []

        def staat(self, eid):
            return {"state": "off", "attributes": {}}

        def dienst(self, *a):
            raise AssertionError("niets naar de tv sturen")

    film = filmmodus.FilmModus(ha=TvUit(), pc_tool=lambda t, a: None, tv_entity="media_player.tv",
                               tv_knop="button.tv")
    monkeypatch.setattr(filmmodus, "_film", film)
    monkeypatch.setattr(filmmodus, "lees_toestand", lambda pad=None: {"tv": "media_player.tv"})
    assert tv_bediening.voer_uit("pauze") is None
    assert tv_bediening.voer_uit("speel verder") is None
    # Met "tv" erin blijft het eerlijke antwoord staan.
    assert tv_bediening.voer_uit("pauzeer de tv") == "De tv staat uit, sir."


# -----------------------------------------------------------------
# Protocollen: ook de naam vóór het woord
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,routine", [
    ("slaap protocol", "sleep"),
    ("slaapprotocol", "sleep"),
    ("start het filmavond protocol", "movie"),
    ("gamen protocol activeren", "gaming"),
    ("protocol slaap", "sleep"),
])
def test_protocol_beide_volgordes(zin, routine):
    from core.routines import _manager

    r = _manager.resolve_protocol(zin)
    assert r[0] == "start" and r[1] == routine


@pytest.mark.parametrize("zin", ["wat is een protocol", "welk protocol", "protocol"])
def test_geen_protocol(zin):
    from core.routines import _manager

    r = _manager.resolve_protocol(zin)
    assert r is None or r[0] != "start"


def test_huisfeest_ook_achteraan():
    from core.karakter import easter_egg

    assert easter_egg("huisfeest protocol").startswith("Het huisfeest-protocol")


# -----------------------------------------------------------------
# Spotify: "speelt" alleen als er echt iets nieuws speelt
# -----------------------------------------------------------------

URI = "spotify:track:" + "A" * 22


def test_al_spelend_nummer_telt_niet_als_speelt():
    from actions.media import open_spotify

    # Spotify speelde al "Queen - Bohemian Rhapsody" en opent alleen de pagina.
    r = open_spotify(URI, opener=lambda u: None,
                     vensters_fn=lambda n: [(1, "Queen - Bohemian Rhapsody")], wacht=0)
    assert r.ok and r.data["speelt"] is False


def test_nieuw_nummer_telt_wel():
    from actions.media import open_spotify

    titel = {"t": "Spotify Premium"}

    def openen(uri):
        titel["t"] = "Avicii - Levels"

    r = open_spotify(URI, opener=openen, vensters_fn=lambda n: [(1, titel["t"])], wacht=0)
    assert r.ok and r.data["speelt"] is True


def test_staat_klaar_tekst():
    from core import spotify_smaak as sp

    keuze = {"naam": "Levels", "artiest": "Avicii", "uri": URI}
    pc = lambda t, a: ToolResult(True, "ok", data={"speelt": False})  # noqa: E731
    assert sp.speel(keuze, pc) == "'Levels' van Avicii staat klaar in Spotify."


# -----------------------------------------------------------------
# Het contextblok komt nooit in een antwoord (2026-10-26)
# -----------------------------------------------------------------

LEK = """1. DIT GESPREK
  - Laatste actie: bestand jarvis_lag_streepje_test.txt geopend
  - Laatste opdracht: typ test in kladblok
  - Laatste programma: geen programma

Wil je een wekker zetten?"""


def test_contextlek_weg():
    from core.context_memory import verwijder_contextlek

    assert verwijder_contextlek(LEK) == "Wil je een wekker zetten?"
    assert verwijder_contextlek("JARVIS-CONTEXT EN GEHEUGEN\n=====\n1. DIT GESPREK (actueel)\n   - x: y") \
        == "Dat begreep ik niet helemaal, sir. Kunt u het anders zeggen?"


@pytest.mark.parametrize("gewoon", ["Parijs.", "1. Open Spotify\n2. Zet het volume op 30",
                                    "- melk\n- brood", "Het is 12 graden."])
def test_gewone_antwoorden_blijven(gewoon):
    from core.context_memory import verwijder_contextlek

    assert verwijder_contextlek(gewoon) == gewoon


def test_stream_filter_letter_voor_letter():
    from core.context_memory import ContextLekFilter

    f = ContextLekFilter()
    uit = "".join(f.feed(c) for c in LEK) + f.flush()
    assert uit.strip() == "Wil je een wekker zetten?"
    f = ContextLekFilter()
    assert f.feed("Het") == "Het", "een gewone zin gaat meteen door (live spraak)"


def test_ask_ai_stream_spreekt_het_lek_niet_uit(monkeypatch):
    from core import ai

    monkeypatch.setattr(ai.llm, "chat_stream", lambda messages: iter([LEK[:20], LEK[20:60], LEK[60:]]))
    gehoord = []
    antwoord = ai._stream_answer([], gehoord.append)
    assert antwoord == "Wil je een wekker zetten?"
    assert "DIT GESPREK" not in "".join(gehoord) and "wekker" in "".join(gehoord)
