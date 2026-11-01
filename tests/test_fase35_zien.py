"""Fase 35 — zien: vragen over het scherm van de game-pc (lokaal beeldmodel)."""

from pathlib import Path

import pytest

from actions import zien as zien_actie
from core import brain, vervolg, zien
from core.result_validation import ToolResult

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------
# M1 — kijken (agent-tool)
# ---------------------------------------------------------------------

class NepBeeld:
    """PIL is in de tests een nepmodule (conftest); dit beeld houdt bij wat er gebeurt."""

    def __init__(self, log):
        self.log = log

    def convert(self, modus):
        self.log.append(("convert", modus))
        return self

    def thumbnail(self, maat):
        self.log.append(("thumbnail", maat))

    def save(self, buffer, format=None, quality=None):
        self.log.append(("save", format))
        buffer.write(b"JPEG-data")


def test_maak_beeld_actief_scherm_klein_en_jpeg():
    log = []

    def grab(bbox=None, all_screens=False):
        log.append(("grab", bbox, all_screens))
        return NepBeeld(log)

    data = zien_actie.maak_beeld(grab=grab, kader_fn=lambda: (1920, 0, 5760, 2160))
    assert data == b"JPEG-data"
    assert log == [("grab", (1920, 0, 5760, 2160), True), ("convert", "RGB"),
                   ("thumbnail", (zien_actie.MAX_ZIJDE, zien_actie.MAX_ZIJDE)), ("save", "JPEG")]


def test_maak_beeld_zonder_kader_pakt_alles():
    log = []
    assert zien_actie.maak_beeld(grab=lambda: NepBeeld(log), kader_fn=lambda: None) == b"JPEG-data"


@pytest.mark.parametrize("tekst,kort,meer", [
    ("KORT: U ziet Discord.\nMEER: GEEN", "U ziet Discord.", ""),
    ("**KORT:** Een foutmelding van Steam.\n**MEER:** Herstart Steam. Kijk dan opnieuw.",
     "Een foutmelding van Steam.", "Herstart Steam. Kijk dan opnieuw."),
    ("KORT: Rood wint.\nMEER: -", "Rood wint.", ""),
    ("Zonder formaat. Tweede zin. Derde zin.", "Zonder formaat. Tweede zin.", "Derde zin."),
])
def test_lees_antwoord(tekst, kort, meer):
    assert zien_actie.lees_antwoord(tekst) == (kort, meer)


def test_kijk_scherm_geeft_kort_en_meer():
    gezien = []

    def model(vraag, beeld):
        gezien.append((vraag, beeld))
        return "KORT: Een foutmelding.\nMEER: Start opnieuw op."

    r = zien_actie.kijk_scherm("wat betekent deze foutmelding", beeld_fn=lambda: b"jpeg", model_fn=model)
    assert r.ok and r.message == "Een foutmelding." and r.data == {"kort": "Een foutmelding.", "meer": "Start opnieuw op."}
    assert gezien == [("wat betekent deze foutmelding", b"jpeg")]
    assert zien_actie.kijk_scherm("", beeld_fn=lambda: b"x", model_fn=lambda v, b: "KORT: ok")
    assert gezien[0][0] != zien_actie.STANDAARD_VRAAG


def test_kijk_scherm_fouten():
    def kapot(*a):
        raise RuntimeError("weg")

    assert zien_actie.kijk_scherm("x", beeld_fn=kapot).error_kind == "screenshot"
    assert zien_actie.kijk_scherm("x", beeld_fn=lambda: b"x", model_fn=kapot).error_kind == "model"
    assert zien_actie.kijk_scherm("x", beeld_fn=lambda: b"x", model_fn=lambda v, b: "").error_kind == "leeg"


def test_model_krijgt_beeld_en_keep_alive(monkeypatch):
    import ollama

    aanroepen = []

    def chat(**kw):
        aanroepen.append(kw)
        return type("A", (), {"message": type("M", (), {"content": "KORT: hoi"})()})()

    monkeypatch.setattr(ollama, "chat", chat)
    assert zien_actie._vraag_model("wat zie je", b"jpeg") == "KORT: hoi"
    kw = aanroepen[0]
    assert kw["model"] == "gemma3:4b" and kw["keep_alive"] == "5m"
    assert kw["messages"][1]["images"] == [b"jpeg"]


# ---------------------------------------------------------------------
# M2 — vragen
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin", [
    "wat zie je op mijn scherm", "Jarvis, wat zie je?", "kijk eens naar mijn scherm",
    "wat staat er op mijn scherm", "wat betekent deze foutmelding", "wat moet ik doen met deze error",
    "wie wint dit potje", "wie staat er voor", "wat is mijn score", "leg deze opgave uit",
    "vat deze pagina samen", "lees voor wat er staat", "kun je eens kijken naar mijn scherm",
    "waarom staat dit op mijn scherm",
])
def test_herken_ja(zin):
    assert zien.herken(zin)


@pytest.mark.parametrize("zin", [
    "maak een screenshot", "open discord", "zet het scherm uit", "wat is de score van ajax",
    "hoe laat is het", "wat zie je er mooi uit vandaag", "wie wint de verkiezingen",
])
def test_herken_nee(zin):
    assert not zien.herken(zin)


def test_kijk_kort_zonder_meer():
    r = ToolResult(True, "U ziet Discord.", data={"kort": "U ziet Discord.", "meer": ""})
    assert zien.kijk("wat zie je", pc_fn=lambda v: r) == "U ziet Discord."
    assert vervolg.open_vraag() is None


def test_kijk_met_meer_weten():
    r = ToolResult(True, "Een foutmelding.", data={"kort": "Een foutmelding.", "meer": "Herstart Steam."})
    assert zien.kijk("wat betekent deze foutmelding", pc_fn=lambda v: r) == "Een foutmelding. Wilt u meer weten?"
    assert vervolg.beantwoord("ja", lambda c: pytest.fail("geen commando")) == "Herstart Steam."


def test_kijk_via_de_agent():
    r = ToolResult(True, "ok", data={"status": "ok", "resultaat": {"ok": True, "message": "Rood wint.",
                                                                     "data": {"kort": "Rood wint.", "meer": ""}}})
    assert zien.kijk("wie wint dit potje", pc_fn=lambda v: r) == "Rood wint."
    mislukt = ToolResult(True, "ok", data={"status": "ok", "resultaat": {"ok": False, "message": "Geen model."}})
    assert zien.kijk("wat zie je", pc_fn=lambda v: mislukt) == "Geen model."


def test_kijk_fout_en_niet_bereikbaar():
    def kapot(v):
        raise ConnectionError("game-pc uit")

    assert "lukte niet" in zien.kijk("wat zie je", pc_fn=kapot)
    assert zien.kijk("wat zie je", pc_fn=lambda v: ToolResult(False, "De game-pc is niet bereikbaar.")) == \
        "De game-pc is niet bereikbaar."


def test_kiest_game_pc_of_lokaal(monkeypatch):
    from core import pc_target
    from remote import tools as remote_tools

    gebruikt = []
    monkeypatch.setattr(remote_tools, "execute_remote_tool",
                        lambda tool, args, question="": gebruikt.append((tool, args)) or ToolResult(True, "x"))
    monkeypatch.setattr(zien_actie, "kijk_scherm", lambda v: gebruikt.append(("lokaal", v)) or ToolResult(True, "y"))
    monkeypatch.setattr(pc_target, "get_pc_target", lambda: pc_target.GAME_PC)
    zien._vraag_aan_pc("wat zie je")
    monkeypatch.setattr(pc_target, "get_pc_target", lambda: pc_target.LOCAL)
    zien._vraag_aan_pc("wat zie je")
    assert gebruikt == [("game_pc_kijk_scherm", {"vraag": "wat zie je"}), ("lokaal", "wat zie je")]


def test_in_process_command(monkeypatch):
    gevraagd = []
    monkeypatch.setattr(zien, "_vraag_aan_pc", lambda v: gevraagd.append(v) or ToolResult(
        True, "U ziet Discord.", data={"kort": "U ziet Discord.", "meer": ""}))
    assert brain.process_command("wat zie je op mijn scherm") == "U ziet Discord."
    assert gevraagd == ["wat zie je op mijn scherm"]


def test_trage_eerste_keer_krijgt_een_melding():
    import status

    assert status.taaksoort("wat betekent deze foutmelding") == status.TAAK_ACTIE


# ---------------------------------------------------------------------
# M3 — privacy en aansluiting
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin", [
    "wat zie je op mijn scherm", "wat betekent deze foutmelding", "wie wint dit potje",
    "leg deze opgave uit", "vat deze pagina samen", "wat is mijn score",
])
def test_nooit_naar_gemini(zin):
    from core import privacy_poort

    assert privacy_poort.beslis(zin).cloud is False


def test_registratie_compleet():
    from core import pc_target, tool_registry, tool_select
    from remote import allowlist
    from remote import tools as remote_tools

    assert "kijk_scherm" in allowlist.ALLOWED_TOOLS and "kijk_scherm" in allowlist.BASIS_TOOLS
    assert allowlist.ALLOWED_TOOLS["kijk_scherm"]["params"]["vraag"]["required"] is True
    assert "game_pc_kijk_scherm" in remote_tools.REMOTE_TOOL_NAMES
    assert remote_tools.LANGE_ACTIES["kijk_scherm"] >= 60
    assert pc_target.LOCAL_TO_REMOTE["kijk_scherm"] == "game_pc_kijk_scherm"
    assert tool_registry.get_tool_risk("kijk_scherm", {}) == "low"
    assert "kijk_scherm" in tool_select.ALLEEN_INTERN
    assert "kijk_scherm" in (ROOT / "docs" / "remote_agent.md").read_text(encoding="utf-8")


def test_dispatch_lokaal(monkeypatch):
    from core import ai

    monkeypatch.setattr(zien_actie, "kijk_scherm", lambda v: ToolResult(True, f"gezien: {v}"))
    uit = ai._dispatch_local_tool("kijk_scherm", {"vraag": "wat zie je"}, "wat zie je")
    assert "gezien: wat zie je" in str(uit)
