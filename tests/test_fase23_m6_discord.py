"""Fase 23, M6 — Discord-DM's via de Windows-meldingen op de game-pc."""

import sqlite3

import pytest

from actions import discord_meldingen as dm
from core import confirmation, discord_dms
from core.result_validation import ToolResult


def _toast(titel, tekst):
    return (f'<toast><visual><binding template="ToastGeneric"><text>{titel}</text>'
            f'<text>{tekst}</text><image placement="appLogoOverride" src="x.png"/></binding></visual>'
            '<audio silent="true"/></toast>').encode("utf-8")


def _maak_db(pad, rijen):
    """Een mini-wpndatabase: alleen de kolommen die wij lezen."""

    con = sqlite3.connect(pad)
    con.execute("create table NotificationHandler (RecordId integer primary key, PrimaryId text)")
    con.execute('create table Notification (Id integer primary key, HandlerId integer, Type text, '
                'Payload blob, ArrivalTime integer)')
    con.execute("insert into NotificationHandler values (1, ?)", (dm.DISCORD_APP_ID,))
    con.execute("insert into NotificationHandler values (2, 'Microsoft.Andere!App')")
    for rij in rijen:
        con.execute("insert into Notification values (?, ?, ?, ?, ?)", rij)
    con.commit()
    con.close()
    return str(pad)


# 2026-10-28 18:54 UTC als FILETIME
FT = 134376836677816700
_ECHTE_KLANT = discord_dms.DiscordKlant


# -----------------------------------------------------------------
# Lezen op de game-pc
# -----------------------------------------------------------------

def test_lees_dms_alleen_discord_dms_nieuwste_eerst(tmp_path):
    pad = _maak_db(tmp_path / "wpn.db", [
        (1, 1, "toast", _toast("Sem", "ik kom zo"), FT),
        (2, 1, "toast", _toast("Lisa", "hoi &amp; doei"), FT + 10_000_000),
        (3, 1, "toast", _toast("Sem (#algemeen, Vrienden)", "servermelding"), FT + 20_000_000),
        (4, 2, "toast", _toast("Sem", "andere app"), FT + 30_000_000),
        (5, 1, "badge", b"<badge value='1'/>", FT + 40_000_000),
    ])
    dms = dm.lees_dms(pad)
    assert [(d["id"], d["van"], d["tekst"]) for d in dms] == [("2", "Lisa", "hoi & doei"), ("1", "Sem", "ik kom zo")]
    assert dms[0]["tijd"].startswith("2026-10-28T")


def test_lees_dms_zonder_database(tmp_path):
    assert dm.lees_dms(str(tmp_path / "bestaat_niet.db")) == []


@pytest.mark.parametrize("payload", [
    b'<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaa">]><toast><text>&a;</text><text>x</text></toast>',
    b"<toast><text>alleen titel</text></toast>",
    b"geen xml",
    b"<toast><text>kapot",
])
def test_rare_toasts_worden_overgeslagen(payload):
    assert dm.lees_toast(payload) is None


@pytest.mark.parametrize("titel,is_dm", [
    ("Sem", True),
    ("Sem de Vries", True),
    ("Sem (#algemeen, Vrienden)", False),
    ("Sem (Groepje)", False),
    ("  ", False),
])
def test_dm_titel(titel, is_dm):
    assert dm.is_dm_titel(titel) is is_dm


def test_tekst_wordt_schoongemaakt_en_begrensd(tmp_path):
    lang = "a" * 900
    pad = _maak_db(tmp_path / "wpn.db", [(1, 1, "toast", _toast("Sem", "regel1\nregel2 " + lang), FT)])
    tekst = dm.lees_dms(pad)[0]["tekst"]
    assert tekst.startswith("regel1 regel2 ") and len(tekst) == dm.MAX_TEKST


@pytest.mark.parametrize("titel,naam,past", [
    ("@Sem - Discord", "Sem", True),
    ("Discord | @sem", "Sem", True),
    ("Sem de Vries - Discord", "sem de vries", True),
    ("#algemeen | Vrienden - Discord", "Sem", False),
    ("Vrienden - Discord", "Sem", False),
    ("Sem - Kladblok", "Sem", False),
])
def test_titel_past(titel, naam, past):
    assert dm.titel_past(titel, naam) is past


def test_toetsen_worden_letterlijk_getypt():
    assert dm._escape_keys("1+1 = 2 ^_^ (100%) {x} ~") == "1{+}1 = 2 {^}_{^} {(}100{%}{)} {{}x{}} {~}"


def test_antwoord_typen():
    gestuurd = []

    def stuur(naam, tekst):
        gestuurd.append((naam, tekst))
        return True, None

    r = dm.discord_antwoord("Sem", "ik kom\nzo", stuur_fn=stuur)
    assert r.ok and gestuurd == [("Sem", "ik kom zo")]


def test_antwoord_verkeerd_gesprek_verstuurt_niets():
    r = dm.discord_antwoord("Sem", "hoi", stuur_fn=lambda n, t: (False, "verkeerd_gesprek"))
    assert not r.ok and r.error_kind == "verkeerd_gesprek" and "niets verstuurd" in r.message


def test_antwoord_zonder_tekst():
    assert not dm.discord_antwoord("Sem", "  ", stuur_fn=lambda n, t: (True, None)).ok


def test_toolresultaat_bevat_geen_inhoud_in_de_melding(monkeypatch):
    monkeypatch.setattr(dm, "lees_dms", lambda: [{"id": "1", "van": "Sem", "tekst": "geheim", "tijd": None}])
    monkeypatch.setattr(dm, "_volledig_scherm", lambda: True)
    r = dm.discord_dms()
    assert r.ok and "geheim" not in r.message and "Sem" not in r.message
    assert r.data["volledig_scherm"] is True and r.data["dms"][0]["tekst"] == "geheim"


# -----------------------------------------------------------------
# Allowlist en routering
# -----------------------------------------------------------------

def test_allowlist_en_twins():
    from core import pc_target
    from remote import allowlist
    from remote import tools as remote_tools

    assert allowlist.validate_call("discord_dms", {})[0] == {}
    goed = {"naam": "Sem", "tekst": "ik kom zo"}
    assert allowlist.validate_call("discord_antwoord", goed)[0] == goed
    for slecht in ({"naam": "Sem"}, {"naam": "Sem", "tekst": "a\nb"}, {"naam": "x" * 41, "tekst": "hoi"},
                   {"naam": "Sem", "tekst": "x" * 501}):
        assert allowlist.validate_call("discord_antwoord", slecht)[0] is None, slecht
    assert allowlist.is_allowed_in_profiel("discord_dms", allowlist.PROFIEL_BASIS)
    assert allowlist.is_allowed_in_profiel("discord_antwoord", allowlist.PROFIEL_BASIS)
    assert pc_target.remote_variant("discord_dms") == "game_pc_discord_dms"
    assert "game_pc_discord_antwoord" in remote_tools.REMOTE_TOOL_NAMES
    assert remote_tools.LANGE_ACTIES["discord_antwoord"] >= 20


def test_antwoord_krijgt_een_ruimere_timeout():
    from remote import tools as remote_tools

    class Client:
        timeout = 5.0

        def send_command(self, tool, args):
            self.gezien = self.timeout
            from remote.client import RemoteResult

            return RemoteResult(True, 200, resultaat={"ok": True})

    c = Client()
    remote_tools._command_resultaat(c, "discord_antwoord", {"naam": "Sem", "tekst": "hoi"}, "x")
    assert c.gezien == 50.0 and c.timeout == 5.0


# -----------------------------------------------------------------
# Het brein
# -----------------------------------------------------------------

def _dm(id_, van, tekst):
    return {"id": str(id_), "van": van, "tekst": tekst, "tijd": "2026-10-28T19:54:00"}


class PC:
    """Neppe game-pc: geeft DM's terug en onthoudt wat er getypt is."""

    def __init__(self, dms=None, online=True, volledig_scherm=False, stuur="geslaagd"):
        self.lijst = list(dms or [])
        self.online = online
        self.volledig_scherm = volledig_scherm
        self.stuur_status = stuur
        self.getypt = []

    def __call__(self, tool, args):
        if not self.online:
            return ToolResult(False, "niet bereikbaar", data={"status": "mislukt"})
        if tool == "game_pc_discord_dms":
            return ToolResult(True, "ok", data={"resultaat": {
                "ok": True, "data": {"dms": self.lijst, "volledig_scherm": self.volledig_scherm}}})
        if tool == "game_pc_discord_antwoord":
            self.getypt.append((args["naam"], args["tekst"]))
            if self.stuur_status == "geslaagd":
                return ToolResult(True, "verstuurd", data={"status": "geslaagd"})
            return ToolResult(False, "Discord staat niet open op de game-pc.",
                              data={"status": self.stuur_status})
        raise AssertionError(tool)

    def klant(self):
        return _ECHTE_KLANT(pc_fn=self)


@pytest.fixture(autouse=True)
def _schoon(monkeypatch, tmp_path):
    monkeypatch.setattr(discord_dms, "GEZIEN_FILE", str(tmp_path / "discord_gezien.json"))
    audit = []
    monkeypatch.setattr("core.audit.log_audit", lambda **kw: audit.append(kw))
    confirmation.clear_pending()
    yield audit
    confirmation.clear_pending()


def test_gegevens_ook_direct_in_data():
    """De lokale variant (zonder agent) zet de DM's direct in data."""

    klant = discord_dms.DiscordKlant(pc_fn=lambda t, a: ToolResult(True, "ok", data={"dms": [_dm(1, "Sem", "x")]}))
    assert klant.dms()[0]["van"] == "Sem"


@pytest.mark.parametrize("zin,verwacht", [
    ("heb ik nieuwe dm's?", ("nieuw", None, None)),
    ("Heb ik nieuwe DM's", ("nieuw", None, None)),
    ("zijn er nieuwe discord berichten", ("nieuw", None, None)),
    ("heb ik berichten op discord", ("nieuw", None, None)),
    ("lees mijn dm's voor", ("nieuw", None, None)),
    ("wat stuurde Sem?", ("lees", "sem", None)),
    ("wat stuurde sem me op discord", ("lees", "sem", None)),
    ("lees de dm van sem voor", ("lees", "sem", None)),
    ("antwoord Sem: ik kom zo", ("antwoord", "Sem", "ik kom zo")),
    ("Antwoord Sem op Discord: Ik kom zo!", ("antwoord", "Sem", "Ik kom zo!")),
    ("stuur Lisa via discord: tot straks", ("antwoord", "Lisa", "tot straks")),
    ("beantwoord de dm van Sem met prima", ("antwoord", "Sem", "prima")),
    ("kun je Sem antwoorden", None),
    ("antwoord op de vraag: 42", None),
    ("beantwoord de mail van school met ik ben ziek", None),
    ("antwoord op de mail van jan: prima", None),
    ("wat zegt het weer", None),
    ("heb ik nieuwe mail", None),
])
def test_herken(zin, verwacht):
    assert discord_dms.herken(zin) == verwacht


def test_nieuwe_dms_en_daarna_geen():
    pc = PC([_dm(2, "Lisa", "hoi"), _dm(1, "Sem", "ik kom zo")])
    assert discord_dms.probeer_commando("heb ik nieuwe dm's", pc.klant) == (
        "2 nieuwe DM's:\nSem: ik kom zo.\nLisa: hoi.")
    assert discord_dms.probeer_commando("heb ik nieuwe dm's", pc.klant) == "Geen nieuwe DM's, sir."
    pc.lijst.insert(0, _dm(3, "Sem", "ben er!"))
    assert discord_dms.probeer_commando("heb ik nieuwe dm's", pc.klant) == "Eén nieuwe DM, van Sem: ben er!"


def test_veel_nieuwe_dms_worden_ingekort():
    pc = PC([_dm(i, "Sem", f"bericht {i}") for i in range(6, 0, -1)])
    tekst = discord_dms.probeer_commando("heb ik nieuwe dm's", pc.klant)
    assert tekst.splitlines() == ["6 nieuwe DM's:", "Sem: bericht 4.", "Sem: bericht 5.", "Sem: bericht 6.",
                                  "En nog 3 eerder."]


def test_game_pc_uit():
    pc = PC(online=False)
    assert discord_dms.probeer_commando("heb ik nieuwe dm's", pc.klant) == discord_dms.GAME_PC_UIT
    assert discord_dms.probeer_commando("antwoord Sem: hoi", pc.klant) == discord_dms.GAME_PC_UIT


def test_lees_van():
    pc = PC([_dm(3, "Lisa", "hoi"), _dm(2, "Sem de Vries", "kom je?"), _dm(1, "Sem de Vries", "hallo")])
    assert discord_dms.probeer_commando("wat stuurde sem", pc.klant) == (
        "De laatste 2 DM's van Sem de Vries:\nSem de Vries: hallo.\nSem de Vries: kom je?")
    assert discord_dms.probeer_commando("wat stuurde Piet", pc.klant) == "Ik zie geen recente DM van piet, sir."


def test_antwoord_vraagt_eerst_en_verstuurt_na_ja(_schoon):
    pc = PC([_dm(1, "Sem", "kom je?")])
    vraag = discord_dms.probeer_commando("antwoord sem: ik kom zo", pc.klant)
    assert vraag == 'Aan Sem op Discord:\n"ik kom zo"\nZal ik het versturen?'
    assert pc.getypt == []
    pending = confirmation.get_pending()
    assert pending["kind"] == "discord_versturen" and confirmation.is_dangerous_kind("discord_versturen")
    assert discord_dms.na_ja(pending, klant=pc.klant()) == "Verstuurd aan Sem, sir."
    assert pc.getypt == [("Sem", "ik kom zo")]
    regel = _schoon[-1]
    assert regel["tool"] == "discord_versturen" and regel["goedgekeurd"] is True
    assert "ik kom zo" not in str(regel["argumenten"]) and regel["argumenten"]["aan"] == "Sem"


def test_antwoord_alleen_aan_een_bekende_afzender():
    pc = PC([_dm(1, "Sem", "kom je?")])
    assert "geen recente DM van Piet" in discord_dms.probeer_commando("antwoord Piet: hoi", pc.klant)
    assert confirmation.get_pending() is None


def test_antwoord_twee_namen_vraagt_welke():
    pc = PC([_dm(2, "Sem de Vries", "a"), _dm(1, "Sem Jansen", "b")])
    assert discord_dms.probeer_commando("antwoord sem: hoi", pc.klant).startswith(
        "Bedoelt u Sem de Vries of Sem Jansen")
    assert confirmation.get_pending() is None


def test_antwoord_te_lang():
    pc = PC([_dm(1, "Sem", "a")])
    assert "te lang" in discord_dms.probeer_commando("antwoord sem: " + "x" * 501, pc.klant)


@pytest.mark.parametrize("zin,naam,tekst", [
    ("antwoord Sem ik kom zo", "Sem", "ik kom zo"),
    ("Antwoord Sem, ik kom zo.", "Sem", "ik kom zo."),
    ("antwoord sem met prima", "Sem", "prima"),
    ("stuur Sem terug dat ik zo kom", "Sem", "ik zo kom"),
    ("antwoord Sem op discord tot straks", "Sem", "tot straks"),
    ("reageer op lisa de vries ja hoor", "Lisa de Vries", "ja hoor"),
    ("beantwoord lisa oké", "Lisa de Vries", "oké"),
    ("jarvis kun je sem antwoorden", None, None),
])
def test_antwoord_zonder_dubbele_punt(zin, naam, tekst):
    pc = PC([_dm(2, "Lisa de Vries", "kom je?"), _dm(1, "Sem", "hoi")])
    uit = discord_dms.probeer_commando(zin, pc.klant, online_fn=lambda: True)
    if naam is None:
        assert uit is None or "Zal ik" not in uit
        return
    assert uit == discord_dms.vraag_tekst(naam, tekst)
    assert pc.getypt == []


@pytest.mark.parametrize("zin", [
    "antwoord op de vraag 42", "stuur een mail naar school", "stuur Piet ik kom zo",
    "antwoord in het Engels", "beantwoord de mail van school ik ben ziek",
])
def test_vrij_antwoord_laat_andere_zinnen_door(zin):
    pc = PC([_dm(1, "Sem", "hoi")])
    assert discord_dms.probeer_commando(zin, pc.klant, online_fn=lambda: True) is None
    assert confirmation.get_pending() is None


def test_vrij_antwoord_met_game_pc_uit():
    def klant():
        raise AssertionError("niet aanroepen")

    uit = lambda: False  # noqa: E731
    assert discord_dms.probeer_commando("antwoord Sem ik kom zo", klant, online_fn=uit) is None
    assert discord_dms.probeer_commando("antwoord Sem op discord hoi", klant, online_fn=uit) == (
        discord_dms.GAME_PC_UIT)


def test_versturen_onzeker_en_mislukt(_schoon):
    for status, deel in (("onzeker", "niet zeker"), ("mislukt", "Discord staat niet open")):
        pc = PC([_dm(1, "Sem", "a")], stuur=status)
        discord_dms.probeer_commando("antwoord sem: hoi", pc.klant)
        assert deel in discord_dms.na_ja(confirmation.get_pending(), klant=pc.klant())


def test_mislukt_binnen_een_geslaagd_agentantwoord():
    """De agent zegt altijd ok; de echte uitkomst zit in resultaat.ok."""

    binnen = ToolResult(True, "ok", data={"status": "geslaagd", "resultaat": {
        "ok": False, "message": "Ik kon het gesprek niet zeker openen; er is niets verstuurd.", "data": None}})
    klant = discord_dms.DiscordKlant(pc_fn=lambda t, a: binnen)
    assert klant.stuur("Sem", "hoi") == ("mislukt", "Ik kon het gesprek niet zeker openen; er is niets verstuurd.")
    assert klant.dms() is None


def test_nee_verstuurt_niets(_schoon):
    pc = PC([_dm(1, "Sem", "a")])
    discord_dms.probeer_commando("antwoord sem: hoi", pc.klant)
    assert discord_dms.na_nee(confirmation.get_pending()) == "Oké, ik verstuur het niet."
    assert pc.getypt == [] and _schoon[-1]["goedgekeurd"] is False


def test_brein_ja_en_ok(monkeypatch):
    from core import brain

    pc = PC([_dm(1, "Sem", "kom je?")])
    monkeypatch.setattr(discord_dms, "DiscordKlant", pc.klant)
    assert brain.process_command("antwoord Sem: ik kom zo").endswith("Zal ik het versturen?")
    brain.process_command("ok")
    assert pc.getypt == []
    brain.process_command("antwoord Sem: ik kom zo")
    assert brain.process_command("ja") == "Verstuurd aan Sem, sir."
    assert pc.getypt == [("Sem", "ik kom zo")]


def test_dashboard_beslissing(monkeypatch):
    from core import brain

    pc = PC([_dm(1, "Sem", "kom je?")])
    monkeypatch.setattr(discord_dms, "DiscordKlant", pc.klant)
    discord_dms.probeer_commando("antwoord Sem: hoi", pc.klant)
    pending = confirmation.get_pending()
    assert "discord_versturen" in confirmation.JA_NEE_KINDS
    assert brain.voer_besluit_uit(pending, False) == "Oké, ik verstuur het niet."
    assert pc.getypt == []


# -----------------------------------------------------------------
# Voorlezen bij binnenkomst
# -----------------------------------------------------------------

def _planner(pc, tmp_path, stil=False, online=True):
    gemeld = []
    planner = discord_dms.DiscordPlanner(
        meld_fn=lambda tekst, bron: gemeld.append((tekst, bron)), klant_fn=pc.klant, interval=60,
        pad=str(tmp_path / "gezien.json"), stil_fn=lambda: stil, online_fn=lambda: online)
    return planner, gemeld


def test_planner_eerste_ronde_stil_daarna_voorlezen(tmp_path):
    pc = PC([_dm(1, "Sem", "oud")])
    planner, gemeld = _planner(pc, tmp_path)
    assert planner.stap() == [] and gemeld == []
    pc.lijst.insert(0, _dm(2, "Sem", "ik kom zo"))
    assert len(planner.stap()) == 1
    assert gemeld == [("Sir, DM van Sem: ik kom zo.", "discord")]
    assert planner.stap() == []
    # Voorgelezen telt als gelezen; de oude van vóór de start niet.
    assert [d["id"] for d in discord_dms.ongelezen(pc.lijst, planner.pad)] == ["1"]


def test_planner_niet_tijdens_nacht_film_of_game(tmp_path):
    for stil, volledig in ((True, False), (False, True)):
        pc = PC([_dm(1, "Sem", "oud")], volledig_scherm=volledig)
        planner, gemeld = _planner(pc, tmp_path / f"{stil}{volledig}", stil=stil)
        (tmp_path / f"{stil}{volledig}").mkdir()
        planner._eerste = False
        assert planner.stap() == [] and gemeld == []
        # Later niet alsnog voorlezen, maar wel "nieuw" bij de vraag.
        pc.volledig_scherm = False
        planner.stil_fn = lambda: False
        assert planner.stap() == []
        assert discord_dms.nieuwe_dms(pc.klant(), planner.pad) == "Eén nieuwe DM, van Sem: oud."


def test_planner_doet_niets_als_de_game_pc_uit_staat(tmp_path):
    pc = PC([_dm(1, "Sem", "x")])
    planner, gemeld = _planner(pc, tmp_path, online=None)
    planner._eerste = False
    assert planner.stap() == [] and gemeld == []


def test_het_taalmodel_krijgt_de_discord_tools_nooit():
    from core.agent import VALID_TOOL_NAMES
    from core.tool_registry import get_tool_risk
    from core.tool_select import BASE_TOOLS, CATEGORIES, VOORRANG_TOOLS

    aangeboden = set(BASE_TOOLS) | {t for _, t in VOORRANG_TOOLS}
    for tools in CATEGORIES.values():
        aangeboden |= set(tools)
    for naam in ("discord_dms", "discord_antwoord", "game_pc_discord_dms", "game_pc_discord_antwoord"):
        assert naam not in aangeboden and naam not in VALID_TOOL_NAMES, naam
    assert get_tool_risk("discord_antwoord", {}) == "high"


def test_select_tools_laat_interne_tools_nooit_door():
    from core.tool_select import select_tools

    schema = [{"type": "function", "function": {"name": n}} for n in ("discord_dms", "discord_antwoord", "recall")]
    gekozen = {t["function"]["name"] for t in select_tools("antwoord sem op discord: hoi, lees mijn dm", schema)}
    assert gekozen == {"recall"}
