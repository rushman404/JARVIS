"""Tests voor actions/paths.py: bekendemappenbepaling via Windows API.

De pywin32- en ctypes-achterwegen worden gemockt; de cache wordt per
test leeggegooid zodat gemockte resultaten ook écht terugkomen.
"""
import ctypes
import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest

import actions.paths as paths


@pytest.fixture(autouse=True)
def _lege_cache():
    paths._cache.clear()
    paths._warned.clear()
    yield
    paths._cache.clear()
    paths._warned.clear()


def _misluk_pywin32(name):
    raise ImportError("pywin32 niet geïnstalleerd")


def _misluk_windll():
    raise AttributeError("ctypes.windll bestaat niet (geen Windows)")


# ---------------------------------------------------------------
# Fallback (Linux / geen Windows)
# ---------------------------------------------------------------

def test_valt_terug_op_expanduser(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(paths, "_pywin32_path", _misluk_pywin32)
    monkeypatch.setattr(paths, "_windll", _misluk_windll)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    resultaat = paths.get_known_folder("Desktop")

    assert resultaat == os.path.expanduser("~/Desktop")
    uitvoer = capsys.readouterr().out
    assert "Desktop" in uitvoer and "waarschuwing" not in uitvoer.lower()
    assert "Desktop" in uitvoer


def test_onbekende_map_valt_ook_terug():
    assert paths.get_known_folder("AppData") == os.path.expanduser("~/AppData")


# ---------------------------------------------------------------
# pywin32-route geeft het gemockte pad (werkt op Windows)
# ---------------------------------------------------------------

def test_pywin32_route_geeft_gemockt_pad(monkeypatch):
    onedrive_pad = r"C:\Users\Jos\OneDrive\Documenten"
    monkeypatch.setattr(paths, "_pywin32_path", lambda name: onedrive_pad)

    resultaat = paths.get_known_folder("Documents")

    assert resultaat == onedrive_pad


# ---------------------------------------------------------------
# ctypes/windll-route geeft het gemockte pad
# ---------------------------------------------------------------

class _FakeWindll:
    def __init__(self, pad):
        self.ole32 = MagicMock()
        self.shell32 = MagicMock()
        self.shell32.SHGetKnownFolderPath = MagicMock(side_effect=self._shget)
        self._pad = pad

    def _shget(self, guid_ptr, flags, token, path_byref):
        # via byref() komt de c_wchar_p zelf door als ._obj
        path_byref._obj.value = self._pad
        return 0


def test_ctypes_route_geeft_gemockt_pad(monkeypatch):
    onedrive_pad = r"C:\Users\Jos\OneDrive\Bureaublad"
    fake = _FakeWindll(onedrive_pad)
    monkeypatch.setattr(paths, "_pywin32_path", _misluk_pywin32)
    monkeypatch.setattr(paths, "_windll", lambda: fake)

    resultaat = paths.get_known_folder("Desktop")

    assert resultaat == onedrive_pad
    assert fake.shell32.SHGetKnownFolderPath.called


# ---------------------------------------------------------------
# GUID-structuur: juiste 16 bytes voor de Desktop-GUID
# ---------------------------------------------------------------

def test_guid_heeft_de_juiste_16_bytes():
    verwacht = uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641").bytes_le
    assert paths._guid_bytes("Desktop") == verwacht

    struct = paths._guid_struct("Desktop")
    buffer = (ctypes.c_ubyte * 16)()
    ctypes.memmove(buffer, ctypes.byref(struct), 16)
    assert bytes(buffer) == verwacht


# ---------------------------------------------------------------
# Caching voor de duur van het proces (mock wordt één keer geroepen)
# ---------------------------------------------------------------

def test_resultaat_wordt_gecached(monkeypatch):
    aanroepen = []

    def nep(name):
        aanroepen.append(name)
        return r"C:\Muziek"

    monkeypatch.setattr(paths, "_pywin32_path", nep)

    assert paths.get_known_folder("Music") == r"C:\Muziek"
    assert paths.get_known_folder("Music") == r"C:\Muziek"
    assert aanroepen == ["Music"]