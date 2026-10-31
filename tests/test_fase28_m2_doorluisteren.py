"""Fase 28, M2 — na het laatste antwoord één minuut doorluisteren."""

from pathlib import Path

import config


def test_standaard_een_minuut(monkeypatch):
    monkeypatch.delenv("SESSIE_TIMEOUT_SECONDEN", raising=False)
    assert config._env_int("SESSIE_TIMEOUT_SECONDEN", 60) == 60
    tekst = (Path(config.__file__).resolve()).read_text(encoding="utf-8")
    assert '_env_int("SESSIE_TIMEOUT_SECONDEN", 60)' in tekst


def test_sessie_gebruikt_de_wachttijd():
    root = Path(__file__).resolve().parent.parent
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "listen(start_ts=next_ts, wacht_seconden=SESSIE_TIMEOUT_SECONDEN)" in main
    assert "SESSIE_TIMEOUT_SECONDEN=60" in (root / ".env.example").read_text(encoding="utf-8")
