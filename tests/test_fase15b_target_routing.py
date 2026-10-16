"""Fase 15B — Stap 5: standaarddoel-routing voor de game-pc."""

import importlib
import sys

from core import pc_target


class DummyExec:
    def __init__(self):
        self.calls = []

    def __call__(self, tool, args, question):
        self.calls.append((tool, args))
        return f"OK:{tool}"


def test_mentions_local_pc():
    assert pc_target.mentions_local_pc("maak een map op de mini-pc")
    assert pc_target.mentions_local_pc("minipc")
    assert pc_target.mentions_local_pc("op de server")
    assert not pc_target.mentions_local_pc("op de game-pc")
    assert not pc_target.mentions_local_pc("hier")


def test_is_remote_default_local(monkeypatch):
    monkeypatch.delenv("PC_TARGET", raising=False)
    cfg = importlib.import_module("config")
    if hasattr(cfg, "PC_TARGET"):
        monkeypatch.delattr(cfg, "PC_TARGET", raising=False)
    assert pc_target.is_remote("maak een map test") is False


def test_is_remote_explicit_game_pc(monkeypatch):
    cfg = importlib.import_module("config")
    monkeypatch.setenv("PC_TARGET", "game-pc")
    if hasattr(cfg, "PC_TARGET"):
        monkeypatch.delattr(cfg, "PC_TARGET", raising=False)
    assert pc_target.is_remote("maak een map test") is True


def test_is_remote_hier_maakt_game_pc(monkeypatch):
    monkeypatch.setenv("PC_TARGET", "game-pc")
    cfg = importlib.import_module("config")
    if hasattr(cfg, "PC_TARGET"):
        monkeypatch.delattr(cfg, "PC_TARGET", raising=False)
    assert pc_target.is_remote("hier heb ik een map nodig") is True  # "hier" = game-pc, doel remote


def test_is_remote_mini_pc_wint(monkeypatch):
    monkeypatch.setenv("PC_TARGET", "game-pc")
    cfg = importlib.import_module("config")
    if hasattr(cfg, "PC_TARGET"):
        monkeypatch.delattr(cfg, "PC_TARGET", raising=False)
    assert pc_target.is_remote("maak een map op de mini-pc") is False


def test_dispatch_tool_routes_to_game_pc(monkeypatch):
    from core import ai

    monkeypatch.setenv("PC_TARGET", "game-pc")
    cfg = importlib.import_module("config")
    if hasattr(cfg, "PC_TARGET"):
        monkeypatch.delattr(cfg, "PC_TARGET", raising=False)

    from remote import tools as remote_tools

    client = __import__("tests.test_fase15_remote_integration", fromlist=[""]).NepClient(
        antwoord=__import__("tests.test_fase15_remote_integration", fromlist=[""])._ok()
    )
    __import__("tests.test_fase15_remote_integration", fromlist=[""])._met_client(monkeypatch, client)
    result = ai._dispatch_tool("create_folder", {"name": "test"}, "maak een map test")
    assert client.aanroepen
    # client voert agent-toolnaam door (create_folder), wrapper is game_pc_create_folder
    assert client.aanroepen[-1][0] == "create_folder"


def test_local_to_remote_mapping_omvat_power_en_bestanden():
    assert pc_target.LOCAL_TO_REMOTE["power"] == "game_pc_power"
    assert pc_target.LOCAL_TO_REMOTE["create_folder"] == "game_pc_create_folder"
    assert pc_target.LOCAL_TO_REMOTE["recycle_file"] == "game_pc_recycle_file"
