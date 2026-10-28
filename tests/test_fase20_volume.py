"""Fase 20 — "zet het geluid op 100" zet het volume op 100 (niet +5)."""

import pytest

import core.brain as brain
from core import pc_target


@pytest.fixture
def lokaal(monkeypatch):
    gezien = []
    monkeypatch.setattr(pc_target, "get_pc_target", lambda: pc_target.LOCAL)
    monkeypatch.setattr(brain, "set_volume", lambda p: gezien.append(("set", p)) or f"Volume op {p}%.")
    monkeypatch.setattr(brain, "volume_up", lambda: gezien.append(("up",)) or "Harder.")
    monkeypatch.setattr(brain, "volume_down", lambda: gezien.append(("down",)) or "Zachter.")
    return gezien


@pytest.mark.parametrize("zin, procent", [
    ("zet geluid op 100", 100),
    ("zet het geluid op 100", 100),
    ("zet het geluid op 30 procent", 30),
    ("zet het geluid op 100%", 100),
    ("geluid op 50", 50),
    ("zet het geluid naar 0", 0),
    ("zet het volume op 100", 100),
    ("zet het geluidsvolume op 40", 40),
])
def test_geluid_op_een_getal(lokaal, zin, procent):
    brain.process_command(zin)
    assert lokaal == [("set", procent)]


def test_buiten_bereik_geeft_melding(lokaal):
    antwoord = brain.process_command("zet het geluid op 150")
    assert lokaal == [] and "0 tot 100" in antwoord


@pytest.mark.parametrize("zin", ["zet het geluid op", "geluid harder", "zet het geluid omhoog"])
def test_zonder_getal_blijft_harder(lokaal, zin):
    brain.process_command(zin)
    assert lokaal == [("up",)]


def test_op_de_game_pc(monkeypatch):
    gezien = []
    monkeypatch.setattr(pc_target, "get_pc_target", lambda: pc_target.GAME_PC)
    monkeypatch.setattr(brain, "execute_tool", lambda naam, args, cmd: gezien.append((naam, args)) or "ok")
    brain.process_command("zet het geluid op 100")
    assert gezien == [("game_pc_set_volume", {"percent": 100})]


# ---------------------------------------------------------------
# Dashboard-indeling buiten git (zodat updates niet steeds weigeren)
# ---------------------------------------------------------------

def test_indeling_staat_buiten_git():
    import os
    import subprocess

    from dashboard import api

    assert os.path.basename(api.WIDGETS_FILE) == "dashboard.local.json"
    assert os.path.basename(api.WIDGETS_SJABLOON) == "dashboard.json"
    rel = os.path.relpath(api.WIDGETS_FILE, os.path.dirname(os.path.dirname(api.__file__)))
    uit = subprocess.run(["git", "check-ignore", "-q", rel.replace(os.sep, "/")],
                         cwd=os.path.dirname(os.path.dirname(api.__file__)))
    assert uit.returncode == 0, "dashboard.local.json moet in .gitignore staan"


def test_eigen_bestand_neemt_oude_indeling_over(tmp_path):
    import json

    from dashboard import api

    sjabloon = tmp_path / "dashboard.json"
    lokaal = tmp_path / "dashboard.local.json"
    oud = {"versie": 1, "kolommen": {"midden": ["gesprek", "auditlog"]},
           "instellingen": {"hardop": True}, "slim_huis": ["light.bed"]}
    sjabloon.write_text(json.dumps(oud), encoding="utf-8")

    assert api.zorg_voor_lokale_widgets(str(lokaal), str(sjabloon)) is True
    nieuw = json.loads(lokaal.read_text(encoding="utf-8"))
    assert nieuw["slim_huis"] == ["light.bed"] and nieuw["instellingen"]["hardop"] is True
    assert nieuw["kolommen"]["midden"] == ["gesprek", "routines", "vandaag"]
    # Een tweede keer verandert er niets.
    assert api.zorg_voor_lokale_widgets(str(lokaal), str(sjabloon)) is False


def test_kapot_sjabloon_maakt_geen_bestand(tmp_path):
    from dashboard import api

    (tmp_path / "dashboard.json").write_text("{kapot", encoding="utf-8")
    assert api.zorg_voor_lokale_widgets(str(tmp_path / "x.json"), str(tmp_path / "dashboard.json")) is False
    assert not (tmp_path / "x.json").exists()


def test_lezen_valt_terug_op_sjabloon(tmp_path, monkeypatch):
    import json

    from dashboard import api

    sjabloon = tmp_path / "dashboard.json"
    sjabloon.write_text(json.dumps({"versie": 2, "kolommen": {"midden": ["gesprek"]}}), encoding="utf-8")
    monkeypatch.setattr(api, "WIDGETS_FILE", str(tmp_path / "dashboard.local.json"))
    monkeypatch.setattr(api, "WIDGETS_SJABLOON", str(sjabloon))
    assert api.lees_widgets(api.WIDGETS_FILE)["kolommen"]["midden"] == ["gesprek", "vandaag"]


def test_update_weigering_noemt_de_bestanden():
    from beheer import updates

    def git(*args):
        if args[0] == "status":
            return " M config/dashboard.json\n M config/routines.json"
        return "0"

    reden = updates.kan_installeren(git)
    assert "config/dashboard.json" in reden and "config/routines.json" in reden
