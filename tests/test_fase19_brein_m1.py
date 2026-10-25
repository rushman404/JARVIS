"""Fase 19, M1 — dokter (brein_check) en migratie (export/import)."""

import json
import os
import zipfile
from types import SimpleNamespace

import pytest

from beheer import data, dokter, migratie


# ---------------------------------------------------------------
# Welke bestanden horen bij het brein
# ---------------------------------------------------------------

def test_classificeer_gegevens_en_geheimen():
    assert data.classificeer("memory/memory.json") is False
    assert data.classificeer("config/timers.json") is False
    assert data.classificeer("config/dashboard_devices.json") is False
    assert data.classificeer("logs/audit-202610.jsonl") is False
    assert data.classificeer("JARVIS Memory/Geheugen/Over Rushil.md") is False
    assert data.classificeer(".env") is True
    assert data.classificeer("certs/dashboard-ca-key.pem") is True


def test_niet_bij_het_brein():
    for rel in ("main.py", "core/ai.py", "logs/jarvis.log", "memory/memory.json.bak",
                "memory/memory.json.lock", "voice/models/nl.onnx", ".env.example",
                "JARVIS Memory/.trash/oud.md"):
        assert data.classificeer(rel) is None, rel


def test_privesleutel_agent_gaat_nooit_mee():
    assert data.classificeer("certs/agent-key.pem") is None
    assert data.classificeer("certs/agent-cert.pem") is True


def _maak_project(tmp_path):
    p = tmp_path / "project"
    (p / "memory").mkdir(parents=True)
    (p / "config").mkdir()
    (p / "certs").mkdir()
    (p / "logs").mkdir()
    (p / "JARVIS Memory" / "Geheugen").mkdir(parents=True)
    (p / "memory" / "memory.json").write_text('{"naam": "Rushil"}', encoding="utf-8")
    (p / "memory" / "memory.json.lock").write_text("", encoding="utf-8")
    (p / "config" / "timers.json").write_text('{"timers": []}', encoding="utf-8")
    (p / "certs" / "dashboard-ca.pem").write_text("CA", encoding="utf-8")
    (p / "certs" / "agent-key.pem").write_text("GEHEIM", encoding="utf-8")
    (p / "logs" / "audit.jsonl").write_text("{}\n", encoding="utf-8")
    (p / "logs" / "jarvis.log").write_text("log", encoding="utf-8")
    (p / "JARVIS Memory" / "Geheugen" / "Over Rushil.md").write_text("# Over", encoding="utf-8")
    (p / ".env").write_text(
        "DASHBOARD_LAN_IP=192.168.2.19\nDASHBOARD_CONTROL_TOKEN=supergeheimtoken123\n", encoding="utf-8"
    )
    (p / "main.py").write_text("", encoding="utf-8")
    return p


def test_verzamel_neemt_alleen_breinbestanden(tmp_path):
    p = _maak_project(tmp_path)
    namen = dict(data.verzamel(str(p)))
    assert set(namen) == {
        ".env", "certs/dashboard-ca.pem", "config/timers.json", "logs/audit.jsonl",
        "memory/memory.json", "JARVIS Memory/Geheugen/Over Rushil.md",
    }
    assert namen[".env"] is True and namen["memory/memory.json"] is False


# ---------------------------------------------------------------
# Export en import
# ---------------------------------------------------------------

def test_export_import_heen_en_terug(tmp_path):
    bron = _maak_project(tmp_path)
    pakket, aantal = migratie.exporteer(str(tmp_path / "uit"), project=str(bron))
    assert aantal == 6

    doel = tmp_path / "nieuw"
    doel.mkdir()
    plan, veiligheid = migratie.importeer(
        pakket, project=str(doel), backupmap=str(tmp_path / "bk"), controleer_draaien=False
    )
    assert len(plan.nieuw) == 6 and not plan.overschrijven and veiligheid is None
    assert (doel / "memory" / "memory.json").read_text(encoding="utf-8") == '{"naam": "Rushil"}'
    assert (doel / "JARVIS Memory" / "Geheugen" / "Over Rushil.md").is_file()
    assert not (doel / "certs" / "agent-key.pem").exists()

    # Opnieuw importeren: alles al gelijk.
    plan, _ = migratie.importeer(pakket, project=str(doel), backupmap=str(tmp_path / "bk"),
                                 controleer_draaien=False)
    assert len(plan.gelijk) == 6 and not plan.nieuw


def test_import_maakt_veiligheidszip_van_wat_overschreven_wordt(tmp_path):
    bron = _maak_project(tmp_path)
    pakket, _ = migratie.exporteer(str(tmp_path / "uit"), project=str(bron))
    doel = tmp_path / "nieuw"
    (doel / "memory").mkdir(parents=True)
    (doel / "memory" / "memory.json").write_text('{"oud": true}', encoding="utf-8")

    plan, veiligheid = migratie.importeer(pakket, project=str(doel), backupmap=str(tmp_path / "bk"),
                                          controleer_draaien=False)
    assert plan.overschrijven == ["memory/memory.json"]
    with zipfile.ZipFile(veiligheid) as zf:
        assert zf.read("memory/memory.json") == b'{"oud": true}'


def _pakket(tmp_path, bestanden, manifest_extra=None, extra_in_zip=None):
    pad = tmp_path / "pakket.zip"
    lijst = []
    with zipfile.ZipFile(pad, "w") as zf:
        for rel, inhoud in bestanden.items():
            zf.writestr(rel, inhoud)
            lijst.append({"pad": rel, "sha256": migratie._sha256(inhoud), "grootte": len(inhoud)})
        for rel, inhoud in (extra_in_zip or {}).items():
            zf.writestr(rel, inhoud)
        manifest = {"formaat": 1, "soort": "jarvis-brein", "bestanden": lijst}
        manifest.update(manifest_extra or {})
        zf.writestr("manifest.json", json.dumps(manifest))
    return str(pad)


@pytest.mark.parametrize("rel", [
    "../buiten.json", "/etc/passwd", "C:/Windows/x.json", "memory/../../x.json",
    "main.py", "core/ai.py", "memory\\memory.json", "./memory/memory.json",
])
def test_import_weigert_gevaarlijke_paden(tmp_path, rel):
    pakket = _pakket(tmp_path, {rel: b"x"})
    with pytest.raises(migratie.MigratieFout):
        migratie.lees_pakket(pakket)


def test_import_weigert_beschadigd_bestand(tmp_path):
    pakket = tmp_path / "p.zip"
    with zipfile.ZipFile(pakket, "w") as zf:
        zf.writestr("memory/memory.json", b"veranderd")
        zf.writestr("manifest.json", json.dumps({
            "formaat": 1, "soort": "jarvis-brein",
            "bestanden": [{"pad": "memory/memory.json", "sha256": migratie._sha256(b"origineel")}],
        }))
    with pytest.raises(migratie.MigratieFout, match="Controlegetal"):
        migratie.lees_pakket(str(pakket))


def test_import_weigert_onbekende_extra_bestanden(tmp_path):
    pakket = _pakket(tmp_path, {"memory/memory.json": b"{}"}, extra_in_zip={"core/ai.py": b"kwaad"})
    with pytest.raises(migratie.MigratieFout, match="onbekende"):
        migratie.lees_pakket(pakket)


def test_import_weigert_vreemd_pakket(tmp_path):
    pakket = _pakket(tmp_path, {"memory/memory.json": b"{}"}, manifest_extra={"soort": "iets-anders"})
    with pytest.raises(migratie.MigratieFout):
        migratie.lees_pakket(pakket)
    kapot = tmp_path / "kapot.zip"
    kapot.write_bytes(b"geen zip")
    with pytest.raises(migratie.MigratieFout):
        migratie.lees_pakket(str(kapot))


def test_geen_schrijfactie_als_een_bestand_fout_is(tmp_path):
    pakket = tmp_path / "p.zip"
    with zipfile.ZipFile(pakket, "w") as zf:
        zf.writestr("memory/memory.json", b"goed")
        zf.writestr("config/timers.json", b"fout")
        zf.writestr("manifest.json", json.dumps({
            "formaat": 1, "soort": "jarvis-brein",
            "bestanden": [
                {"pad": "memory/memory.json", "sha256": migratie._sha256(b"goed")},
                {"pad": "config/timers.json", "sha256": migratie._sha256(b"anders")},
            ],
        }))
    doel = tmp_path / "doel"
    doel.mkdir()
    with pytest.raises(migratie.MigratieFout):
        migratie.importeer(str(pakket), project=str(doel), controleer_draaien=False)
    assert not (doel / "memory").exists()


def test_import_weigert_als_jarvis_draait(tmp_path, monkeypatch):
    monkeypatch.setattr(migratie, "jarvis_draait", lambda project: True)
    with pytest.raises(migratie.MigratieFout, match="draait"):
        migratie.importeer(str(tmp_path / "x.zip"), project=str(tmp_path))


def test_jarvis_draait_herkent_main_py(tmp_path):
    main = os.path.join(str(tmp_path), "main.py")
    assert migratie.jarvis_draait(str(tmp_path), processen=[{"pid": -1, "cmdline": ["python", main]}])
    assert not migratie.jarvis_draait(str(tmp_path), processen=[{"pid": -1, "cmdline": ["python", "ander.py"]}])
    eigen = {"pid": os.getpid(), "cmdline": ["python", main]}
    assert not migratie.jarvis_draait(str(tmp_path), processen=[eigen])


def test_env_nakijken_noemt_sleutels_maar_nooit_waarden():
    env = (b"DASHBOARD_LAN_IP=192.168.2.19\nMIC_DEVICE=3\n"
           b"PIPER_VOICE=C:\\stemmen\\pim.onnx\nREMOTE_SERVER_ENABLED=1\n"
           b"DASHBOARD_CONTROL_TOKEN=supergeheimtoken123\n")
    uit = migratie.env_nakijken(env)
    sleutels = {s for s, _ in uit}
    assert {"DASHBOARD_LAN_IP", "MIC_DEVICE", "PIPER_VOICE", "REMOTE_SERVER_ENABLED"} <= sleutels
    assert "DASHBOARD_CONTROL_TOKEN" not in sleutels
    assert "supergeheim" not in repr(uit) and "192.168" not in repr(uit)


def test_standaard_exportmap_ligt_buiten_het_project():
    assert not os.path.abspath(migratie.standaard_exportmap()).startswith(data.PROJECT)


# ---------------------------------------------------------------
# Dokter
# ---------------------------------------------------------------

def test_voer_uit_vangt_exceptions():
    def kapot():
        raise RuntimeError("stuk")

    def goed():
        return dokter.Controle("Goed", dokter.OK, "prima")

    uit = dokter.voer_uit((goed, kapot))
    assert [u.status for u in uit] == [dokter.OK, dokter.FOUT]
    assert "stuk" in uit[1].uitleg
    assert not dokter.is_gezond(uit)


def test_als_tekst_toont_advies_bij_fout():
    tekst = dokter.als_tekst([
        dokter.Controle("Ollama", dokter.FOUT, "model ontbreekt", "ollama pull x"),
        dokter.Controle("Python", dokter.OK, "3.11"),
    ])
    assert "❌ Ollama" in tekst and "→ ollama pull x" in tekst and "1 fout" in tekst


def test_pakketten_controle():
    def importeer(naam):
        if naam == "piper":
            raise ImportError
        return object()

    uit = dokter.controleer_pakketten(importeer=importeer)
    assert uit.status == dokter.FOUT and "piper-tts" in uit.uitleg


def test_ollama_controle():
    lijst = {"models": [{"model": "qwen2.5:3b"}]}
    assert dokter.controleer_ollama(lambda: lijst, model="qwen2.5:3b").status == dokter.OK
    uit = dokter.controleer_ollama(lambda: lijst, model="llama3:8b")
    assert uit.status == dokter.FOUT and uit.advies == "ollama pull llama3:8b"

    def weg():
        raise ConnectionError

    assert dokter.controleer_ollama(weg, model="x").status == dokter.FOUT


def _sd(apparaten, standaard=(0, 1)):
    return SimpleNamespace(query_devices=lambda: apparaten, default=SimpleNamespace(device=standaard))


def test_microfoon_en_speaker(monkeypatch):
    import config

    apparaten = [
        {"name": "Mic", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Speaker", "max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setattr(config, "MIC_DEVICE", None)
    assert dokter.controleer_microfoon(_sd(apparaten)).status == dokter.OK
    assert dokter.controleer_speaker(_sd(apparaten)).status == dokter.OK

    monkeypatch.setattr(config, "MIC_DEVICE", 1)
    assert dokter.controleer_microfoon(_sd(apparaten)).status == dokter.FOUT
    monkeypatch.setattr(config, "MIC_DEVICE", "mic")
    assert dokter.controleer_microfoon(_sd(apparaten)).status == dokter.OK

    zonder = [{"name": "Speaker", "max_input_channels": 0, "max_output_channels": 2}]
    assert dokter.controleer_microfoon(_sd(zonder)).status == dokter.FOUT


def test_schijf_waarschuwt_bij_weinig_ruimte():
    def weinig(_pad):
        return SimpleNamespace(free=2 * 1024 ** 3)

    assert dokter.controleer_schijf(gebruik_fn=weinig).status == dokter.LET_OP


def test_game_pc_overgeslagen_bij_lokaal(monkeypatch):
    import config

    monkeypatch.setattr(config, "PC_TARGET", "local", raising=False)
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    assert dokter.controleer_game_pc().status == dokter.OVERGESLAGEN


def test_game_pc_offline_en_online(monkeypatch):
    import config
    from core import pc_target

    monkeypatch.setattr(config, "PC_TARGET", "game-pc", raising=False)
    monkeypatch.setattr(pc_target, "remote_client_configuratie_fout", lambda: None)
    uit = dokter.controleer_game_pc(client_fn=lambda: SimpleNamespace(is_online=lambda: False))
    assert uit.status == dokter.FOUT
    uit = dokter.controleer_game_pc(client_fn=lambda: SimpleNamespace(is_online=lambda: True))
    assert uit.status == dokter.OK


def test_brein_check_exitcode(monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "brein_check", os.path.join(data.PROJECT, "scripts", "brein_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(dokter, "voer_uit", lambda: [dokter.Controle("X", dokter.OK, "goed")])
    assert mod.main([]) == 0
    monkeypatch.setattr(dokter, "voer_uit", lambda: [dokter.Controle("X", dokter.FOUT, "stuk")])
    assert mod.main(["--json"]) == 1
    assert '"status": "fout"' in capsys.readouterr().out
