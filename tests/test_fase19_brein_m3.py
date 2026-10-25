"""Fase 19, M3 — dagelijkse backups, rotatie, planner en herstellen."""

import json
import os
import zipfile
from datetime import datetime, timedelta

import pytest

from beheer import backup, dokter, migratie


def _project(tmp_path):
    p = tmp_path / "project"
    (p / "memory").mkdir(parents=True)
    (p / "config").mkdir()
    (p / "memory" / "memory.json").write_text('{"naam": "Rushil"}', encoding="utf-8")
    (p / "config" / "timers.json").write_text('{"timers": []}', encoding="utf-8")
    (p / ".env").write_text("DASHBOARD_CONTROL_TOKEN=supergeheimtoken123\n", encoding="utf-8")
    return p


def _ts(jaar, maand, dag, uur=4, minuut=0):
    return datetime(jaar, maand, dag, uur, minuut).timestamp()


# ---------------------------------------------------------------
# Map en maken
# ---------------------------------------------------------------

def test_map_binnen_project_wordt_geweigerd(tmp_path):
    p = _project(tmp_path)
    with pytest.raises(backup.BackupFout, match="projectmap"):
        backup.controleer_map(str(p / "backups"), project=str(p))
    with pytest.raises(backup.BackupFout):
        backup.controleer_map("  ", project=str(p))
    assert backup.controleer_map(str(tmp_path / "elders"), project=str(p)) == str(tmp_path / "elders")


def test_maak_backup_is_een_geldig_pakket(tmp_path):
    p = _project(tmp_path)
    info = backup.maak_backup(str(tmp_path / "bk"), project=str(p), nu=_ts(2026, 10, 25))
    assert info["naam"] == "jarvis-backup-20261025-040000.zip" and info["aantal"] == 3
    manifest, inhoud = migratie.lees_pakket(info["pad"])
    assert inhoud["memory/memory.json"] == b'{"naam": "Rushil"}'
    assert ".env" in inhoud
    assert not any(n.endswith(".tmp") for n in os.listdir(tmp_path / "bk"))


def test_halve_backup_bestaat_nooit_met_echte_naam(tmp_path, monkeypatch):
    p = _project(tmp_path)

    def stuk(*a, **k):
        raise OSError("schijf vol")

    monkeypatch.setattr(migratie.zipfile.ZipFile, "writestr", stuk)
    with pytest.raises(OSError):
        backup.maak_backup(str(tmp_path / "bk"), project=str(p), nu=_ts(2026, 10, 25))
    assert os.listdir(tmp_path / "bk") == []


# ---------------------------------------------------------------
# Rotatie
# ---------------------------------------------------------------

def _maak_lege_backups(map_, momenten):
    os.makedirs(map_, exist_ok=True)
    for m in momenten:
        naam = f"jarvis-backup-{m:%Y%m%d-%H%M%S}.zip"
        open(os.path.join(map_, naam), "wb").close()


def test_rotatie_dagen_en_weken(tmp_path):
    map_ = str(tmp_path / "bk")
    nu = datetime(2026, 10, 25, 12, 0)
    momenten = [nu - timedelta(days=d, hours=8) for d in range(0, 60)]
    momenten.append(nu - timedelta(hours=1))  # twee op vandaag
    _maak_lege_backups(map_, momenten)
    open(os.path.join(map_, "eigen-bestand.zip"), "wb").close()

    weg = backup.roteer(map_, nu=nu, dagen=7, weken=4)
    over = [naam for naam, _, _ in backup.lijst(map_)]

    dagen = {datetime.strptime(n[14:22], "%Y%m%d").date() for n in over}
    for d in range(7):
        assert (nu - timedelta(days=d)).date() in dagen
    # Van vandaag alleen de nieuwste.
    assert sum(1 for n in over if n.startswith("jarvis-backup-20261025")) == 1
    # Niets ouder dan 4 weken.
    oudste = min(datetime.strptime(n[14:29], "%Y%m%d-%H%M%S") for n in over)
    assert (nu - oudste).days < 28
    assert len(over) <= 7 + 4
    assert weg
    # Een bestand dat niet van ons is, blijft altijd staan.
    assert os.path.exists(os.path.join(map_, "eigen-bestand.zip"))


def test_nieuwste_blijft_altijd(tmp_path):
    map_ = str(tmp_path / "bk")
    nu = datetime(2026, 10, 25)
    _maak_lege_backups(map_, [nu - timedelta(days=400)])
    backup.roteer(map_, nu=nu, dagen=7, weken=4)
    assert len(backup.lijst(map_)) == 1


# ---------------------------------------------------------------
# Uitvoeren en status
# ---------------------------------------------------------------

def test_voer_uit_schrijft_status(tmp_path):
    p = _project(tmp_path)
    status_pad = str(tmp_path / "backup.json")
    ok, info = backup.voer_uit(nu=_ts(2026, 10, 25), project=str(p), status_pad=status_pad,
                               map_=str(tmp_path / "bk"))
    assert ok
    st = json.loads(open(status_pad, encoding="utf-8").read())
    assert st["ok"] is True and st["naam"] == info["naam"] and st["aantal_bestanden"] == 3
    assert "supergeheim" not in json.dumps(st) and str(tmp_path) not in json.dumps(st)


def test_voer_uit_fout_gooit_niet(tmp_path):
    p = _project(tmp_path)
    status_pad = str(tmp_path / "backup.json")
    ok, fout = backup.voer_uit(project=str(p), status_pad=status_pad, map_=str(p / "binnen"))
    assert not ok and "projectmap" in fout
    st = json.loads(open(status_pad, encoding="utf-8").read())
    assert st["ok"] is False and "projectmap" in st["fout"]


def test_samenvatting(tmp_path):
    pad = tmp_path / "backup.json"
    nu = _ts(2026, 10, 25, 12)
    pad.write_text(json.dumps({"ok": True, "laatste_geslaagd": _ts(2026, 10, 25, 4)}), encoding="utf-8")
    s = backup.samenvatting(nu=nu, status_pad=str(pad))
    assert s["laatste"] == "25-10 04:00" and not s["verouderd"] and s["ok"] is True
    s = backup.samenvatting(nu=nu + 3 * 86400, status_pad=str(pad))
    assert s["verouderd"]
    leeg = backup.samenvatting(nu=nu, status_pad=str(tmp_path / "geen.json"))
    assert leeg["laatste"] is None


# ---------------------------------------------------------------
# Planner
# ---------------------------------------------------------------

def test_parse_tijd():
    assert backup.parse_tijd("04:00") == (4, 0)
    assert backup.parse_tijd("23:59") == (23, 59)
    assert backup.parse_tijd("25:00") == (4, 0)
    assert backup.parse_tijd("onzin") == (4, 0)


def test_is_nodig():
    start = _ts(2026, 10, 24, 20)
    gisteren = {"laatste_geslaagd": _ts(2026, 10, 24, 4)}
    # 03:59: de ronde van gisteren is al gedaan.
    assert not backup.is_nodig(_ts(2026, 10, 25, 3, 59), gisteren, "04:00", start)
    # 04:01: tijd voor de nieuwe.
    assert backup.is_nodig(_ts(2026, 10, 25, 4, 1), gisteren, "04:00", start)
    vandaag = {"laatste_geslaagd": _ts(2026, 10, 25, 4, 1)}
    assert not backup.is_nodig(_ts(2026, 10, 25, 9), vandaag, "04:00", start)


def test_is_nodig_wacht_na_opstarten_en_na_fout():
    nu = _ts(2026, 10, 25, 10)
    assert not backup.is_nodig(nu, {}, "04:00", gestart_op=nu - 60)
    assert backup.is_nodig(nu, {}, "04:00", gestart_op=nu - backup.OPSTART_VERTRAGING)
    net_mislukt = {"laatste_poging": nu - 600, "ok": False}
    assert not backup.is_nodig(nu, net_mislukt, "04:00", gestart_op=0)
    assert backup.is_nodig(nu + backup.OPNIEUW_NA_FOUT, net_mislukt, "04:00", gestart_op=0)


def test_planner_meldt_fout_een_keer_per_dag(tmp_path):
    nu = {"t": _ts(2026, 10, 25, 10)}
    meldingen = []
    pad = str(tmp_path / "backup.json")

    def uitvoer(t):
        backup._schrijf_status({"laatste_poging": t, "ok": False, "fout": "schijf vol"}, pad)
        return False, "schijf vol"

    planner = backup.BackupPlanner(
        meld_fn=lambda tekst, bron: meldingen.append((tekst, bron)),
        klok=lambda: nu["t"], status_pad=pad, uitvoer_fn=uitvoer, tijd="04:00",
    )
    planner.gestart_op = 0
    assert planner.controleer()
    nu["t"] += backup.OPNIEUW_NA_FOUT
    assert planner.controleer()
    assert meldingen == [("Sir, de backup is mislukt: schijf vol", "backup")]
    assert not planner.controleer()  # binnen het uur: niet opnieuw


def test_planner_maakt_echte_backup(tmp_path, monkeypatch):
    p = _project(tmp_path)
    pad = str(tmp_path / "backup.json")
    planner = backup.BackupPlanner(
        klok=lambda: _ts(2026, 10, 25, 10), status_pad=pad, tijd="04:00",
        uitvoer_fn=lambda t: backup.voer_uit(nu=t, project=str(p), status_pad=pad, map_=str(tmp_path / "bk")),
    )
    planner.gestart_op = 0
    assert planner.controleer()
    assert len(backup.lijst(str(tmp_path / "bk"))) == 1
    assert not planner.controleer()  # vandaag al gedaan


# ---------------------------------------------------------------
# Herstellen, dokter, dashboard
# ---------------------------------------------------------------

def test_backup_terugzetten_via_veilige_import(tmp_path):
    p = _project(tmp_path)
    info = backup.maak_backup(str(tmp_path / "bk"), project=str(p), nu=_ts(2026, 10, 25))
    (p / "memory" / "memory.json").write_text('{"kapot": true}', encoding="utf-8")
    plan, veiligheid = migratie.importeer(info["pad"], project=str(p), backupmap=str(tmp_path / "vh"),
                                          controleer_draaien=False)
    assert plan.overschrijven == ["memory/memory.json"]
    assert (p / "memory" / "memory.json").read_text(encoding="utf-8") == '{"naam": "Rushil"}'
    with zipfile.ZipFile(veiligheid) as zf:
        assert zf.read("memory/memory.json") == b'{"kapot": true}'


def test_restore_script_vindt_laatste(tmp_path, monkeypatch):
    import importlib.util

    import config

    p = _project(tmp_path)
    map_ = tmp_path / "bk"
    backup.maak_backup(str(map_), project=str(p), nu=_ts(2026, 10, 24))
    backup.maak_backup(str(map_), project=str(p), nu=_ts(2026, 10, 25))
    monkeypatch.setattr(config, "BACKUP_MAP", str(map_))

    spec = importlib.util.spec_from_file_location(
        "brein_restore", os.path.join(backup.data.PROJECT, "scripts", "brein_restore.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    gezien = []

    class NepImport:
        @staticmethod
        def main(argv):
            gezien.append(argv)
            return 0

    monkeypatch.setattr(mod, "_brein_import", lambda: NepImport)
    assert mod.main(["--laatste", "--alleen-controle"]) == 0
    assert gezien[0][0].endswith("jarvis-backup-20261025-040000.zip")
    assert gezien[0][1:] == ["--alleen-controle"]
    assert mod.main([]) == 2


def test_dokter_backup(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "BACKUP_ENABLED", True)
    monkeypatch.setattr(config, "BACKUP_MAP", str(tmp_path / "bk"))
    pad = tmp_path / "backup.json"
    nu = _ts(2026, 10, 25, 12)

    assert dokter.controleer_backup(nu=nu, status_pad=str(pad)).status == dokter.LET_OP
    pad.write_text(json.dumps({"ok": False, "fout": "schijf vol"}), encoding="utf-8")
    assert dokter.controleer_backup(nu=nu, status_pad=str(pad)).status == dokter.FOUT
    pad.write_text(json.dumps({"ok": True, "laatste_geslaagd": _ts(2026, 10, 25, 4)}), encoding="utf-8")
    assert dokter.controleer_backup(nu=nu, status_pad=str(pad)).status in (dokter.OK, dokter.LET_OP)

    monkeypatch.setattr(config, "BACKUP_MAP", os.path.join(backup.data.PROJECT, "backups"))
    assert dokter.controleer_backup(nu=nu, status_pad=str(pad)).status == dokter.FOUT

    monkeypatch.setattr(config, "BACKUP_ENABLED", False)
    assert dokter.controleer_backup(nu=nu, status_pad=str(pad)).status == dokter.LET_OP


def test_dashboard_brein_bevat_backup(monkeypatch):
    from dashboard import bronnen

    monkeypatch.setattr(backup, "samenvatting", lambda: {"ingeschakeld": True, "laatste": "25-10 04:00",
                                                         "ok": True, "fout": None, "verouderd": False})
    status = bronnen._std_brein()
    assert status["backup"]["laatste"] == "25-10 04:00"


def test_tests_maken_geen_echte_backups():
    import config

    assert config.BACKUP_ENABLED is False
