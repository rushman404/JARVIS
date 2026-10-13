"""Tests voor actions/power.py: countdown uit config en annuleren.

os.system is gemockt; er wordt niets echt afgesloten.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import actions.power as power


def test_shutdown_gebruikt_countdown_uit_config(monkeypatch):
    calls = []
    monkeypatch.setattr(power.os, "system", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(config, "POWER_COUNTDOWN_SECONDS", 25)

    message = power.shutdown_pc()

    assert calls == ["shutdown /s /t 25"]
    assert "25" in message


def test_restart_gebruikt_countdown_uit_config(monkeypatch):
    calls = []
    monkeypatch.setattr(power.os, "system", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(config, "POWER_COUNTDOWN_SECONDS", 7)

    message = power.restart_pc()

    assert calls == ["shutdown /r /t 7"]
    assert "7" in message


def test_standaard_countdown_is_20():
    assert config.POWER_COUNTDOWN_SECONDS == 20


def test_cancel_power_action_roept_shutdown_a(monkeypatch):
    calls = []
    monkeypatch.setattr(power.os, "system", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(power.os, "name", "nt")

    message = power.cancel_power_action()

    assert "shutdown /a" in calls
    assert "geannuleerd" in message.lower()


def test_cancel_power_action_niet_op_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(power.os, "system", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(power.os, "name", "posix")

    message = power.cancel_power_action()

    assert calls == []
    assert "Windows" in message


def test_cancel_shutdown_delegeert_naar_cancel_power_action(monkeypatch):
    called = []

    def fake_cancel():
        called.append(True)
        return "ok"

    monkeypatch.setattr(power, "cancel_power_action", fake_cancel)

    assert power.cancel_shutdown() == "ok"
    assert called == [True]
