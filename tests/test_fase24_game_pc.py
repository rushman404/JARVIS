"""Fase 24 — fixes na de live test (2026-10-29).

* Op de game-pc ging "open spotfy" rechtstreeks naar de agent ("Ik kan
  spotfy niet vinden") en kwam nooit bij de correctie.
* "Welke commando's gaan vaak fout?" werd door spraakherkenning anders
  geschreven en niet herkend.
"""

import time

import pytest

import core.ai as ai
import core.audit as audit
import core.brain as brain
from core import commando_correctie as cc
from core import pc_target
from core.confirmation import clear_pending, get_pending

NAMEN = frozenset(["spotify", "steam", "discord", "lamp", "tv"])
OP_GAME_PC = {"spotify", "steam", "discord"}


@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONVERSATION_FILE", str(tmp_path / "conversation.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(cc, "_namen", NAMEN)
    monkeypatch.setattr(cc, "_namen_tijd", time.monotonic())
    monkeypatch.setattr(cc, "_standaard_llm", lambda berichten: "")
    clear_pending()
    yield
    clear_pending()


@pytest.fixture
def game_pc(monkeypatch):
    """Doel = game-pc; de agent kent alleen spotify, steam en discord."""

    aanroepen = []

    def execute_tool(tool, args, vraag):
        programma = args.get("program", "")
        aanroepen.append((tool, programma))
        if programma not in OP_GAME_PC:
            return f"Ik kan {programma} niet vinden."
        return f"Ik open {programma}." if tool == "game_pc_open_program" else f"Ik sluit {programma}."

    monkeypatch.setattr(pc_target, "is_remote", lambda command: True)
    monkeypatch.setattr(brain, "execute_tool", execute_tool)
    monkeypatch.setattr(brain, "ask_ai", lambda command, **_kw: "AI-antwoord")
    return aanroepen


def test_typfout_op_game_pc_direct(game_pc):
    antwoord = brain.process_command("open spotfy")
    assert antwoord == "Ik nam aan dat u 'open spotify' bedoelde. Ik open spotify."
    assert game_pc == [("game_pc_open_program", "spotfy"), ("game_pc_open_program", "spotify")]


def test_typfout_op_game_pc_vraagt(game_pc):
    assert brain.process_command("open stem") == "Bedoelde u: open steam?"
    assert brain.process_command("ja") == "Ik open steam."
    # Geleerd: de volgende keer meteen.
    assert brain.process_command("open stem") == "Ik nam aan dat u 'open steam' bedoelde. Ik open steam."


def test_sluiten_op_game_pc_vraagt_eerst(game_pc):
    assert brain.process_command("sluit discrod") == "Bedoelde u: sluit discord?"
    assert game_pc == [("game_pc_close_program", "discrod")]
    assert brain.process_command("ja") == "Ik sluit discord."


def test_echt_onbekend_blijft_niet_gevonden(game_pc):
    assert brain.process_command("open xyzabc") == "Ik kan xyzabc niet vinden."
    assert get_pending() is None


def test_gevonden_programma_geen_correctie(game_pc):
    assert brain.process_command("open steam") == "Ik open steam."
    assert len(game_pc) == 1


def test_verbeterd_maar_ook_onbekend_geen_rondjes(game_pc, monkeypatch):
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [
        cc.Kandidaat("open steem", 95, "programma_openen", [("stem", "steem")])])
    antwoord = brain.process_command("open stem")
    assert antwoord == "Ik nam aan dat u 'open steem' bedoelde. Ik kan steem niet vinden."
    assert len(game_pc) == 2


def test_toolresult_niet_gevonden(monkeypatch):
    from core.result_validation import ToolResult

    monkeypatch.setattr(brain, "try_commando_correctie", lambda c: "Bedoelde u: open steam?")
    niet = ToolResult(ok=False, message="Steem is niet gevonden.")
    assert brain._correctie_na_niet_gevonden("open steem", niet) == "Bedoelde u: open steam?"
    wel = ToolResult(ok=True, message="Ik open steam.")
    assert brain._correctie_na_niet_gevonden("open steam", wel) is wel


@pytest.mark.parametrize("zin", [
    "welke commando's gaan vaak fout",
    "welke commando’s gaan vaak fout?",
    "welke commandos gaan vaak fout",
    "welke commando s gaan vaak fout",
    "welke kommando's gaan het vaakst mis",
    "welke opdrachten gaan vaak fout",
    "wat voor commando's gaan er verkeerd",
    "welke commando's gaan niet goed",
    "welke commando's begrijp je vaak niet",
    "welke commando's versta je niet",
])
def test_vaak_fout_spraakvarianten(game_pc, zin):
    assert brain.process_command(zin) == "Er gaan nog geen commando's fout, sir."


@pytest.mark.parametrize("zin", [
    "vergeet de geleerde commando's",
    "vergeet de geleerde kommandos",
    "wis alle geleerde opdrachten",
])
def test_vergeet_spraakvarianten(game_pc, zin):
    assert brain.process_command(zin) == "Ik had nog geen commando's geleerd, sir."


@pytest.mark.parametrize("zin", [
    "welke games heb ik",
    "wat is er fout aan mijn pc",
    "vergeet mijn favoriete game",
])
def test_andere_zinnen_niet_naar_beheer(zin):
    assert brain.try_correctie_beheer(zin) is None
