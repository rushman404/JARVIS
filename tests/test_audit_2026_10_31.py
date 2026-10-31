"""Audit na Fase 27–31 (2026-10-31): testisolatie en kleine robuustheidsfixes."""

import os

import pytest

from core import confirmation


def test_tests_lezen_de_env_niet():
    assert os.environ.get("JARVIS_GEEN_DOTENV") == "1"
    import config

    # Op een pc met de game-pc-agent in .env stond dit op True; de tests
    # moeten overal de standaard zien.
    assert config.REMOTE_SERVER_ENABLED is False


def test_zelfverbetering_test_run_zonder_env_waarden(monkeypatch, tmp_path):
    from core import zelfverbetering as zv

    (tmp_path / ".env").write_text("REMOTE_SERVER_ENABLED=1\nGEHEIM_TOKEN=x\n", encoding="utf-8")
    monkeypatch.setattr(zv, "PROJECT", str(tmp_path))
    monkeypatch.setenv("REMOTE_SERVER_ENABLED", "1")
    monkeypatch.setenv("GEHEIM_TOKEN", "x")
    env = zv._schone_env()
    assert "REMOTE_SERVER_ENABLED" not in env and "GEHEIM_TOKEN" not in env
    assert env["JARVIS_GEEN_DOTENV"] == "1" and env["JARVIS_OLLAMA_DISABLED"] == "1"


def test_zelfverbetering_bezig_na_herstart_gewist(tmp_path):
    from core import zelfverbetering as zv

    pad = str(tmp_path / "s.json")
    status = zv.lees_status(pad)
    status["bezig"] = True
    zv.schrijf_status(status, pad)
    try:
        zv.zet_meld(lambda *a, **k: None, pad=pad)
        assert zv.lees_status(pad)["bezig"] is False
    finally:
        zv.zet_meld(None, pad=pad)


def test_herstart_aanbod_overschrijft_geen_andere_vraag():
    from core import game_pc_klaar

    confirmation.clear_pending()
    confirmation.set_pending("muziek_voorstel", {"question": "x"})
    try:
        assert game_pc_klaar.bied_herstart_aan(stil_fn=lambda: False) == game_pc_klaar.HERSTART_HINT
        assert confirmation.get_pending()["kind"] == "muziek_voorstel"
    finally:
        confirmation.clear_pending()


@pytest.mark.parametrize("zin,uitkomst", [
    ("kun je me vertellen hoe laat het is", "jarvis"),
    ("weet je hoe laat het is", "jarvis"),
    ("kun je even komen", "twijfel"),
    ("weet jij waar mijn sleutels zijn", "twijfel"),
    ("harder", "jarvis"),
    ("herhaal dat", "jarvis"),
    ("kom je zo eten", "anders"),
])
def test_gericht_beleefde_vragen(zin, uitkomst):
    from core import gericht

    assert gericht.regels(zin) == uitkomst
