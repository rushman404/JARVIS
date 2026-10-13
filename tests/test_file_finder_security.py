"""Veilig zoeken/openen van bestanden: allowlist, gevaarlijke types,
fuzzy matching, genummerde keuze en zoeklimieten."""
import os
from unittest.mock import MagicMock, patch

import actions.file_finder as ff
from core import confirmation


def _touch(path, content=""):
    path.write_text(content, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------
# Allowlist: zonder extensie alleen document-/mediatypes
# ---------------------------------------------------------------

def test_allowlist_zonder_extensie(tmp_path):
    _touch(tmp_path / "rapport.txt")
    _touch(tmp_path / "data.bin")

    results = ff.find_file("rapport", [str(tmp_path)])
    assert [os.path.basename(p) for p in results] == ["rapport.txt"]
    assert ff.find_file("data", [str(tmp_path)]) == []


def test_uitvoerbaar_type_niet_gezocht_zonder_extensie(tmp_path):
    _touch(tmp_path / "geheim.exe")

    assert ff.find_file("geheim", [str(tmp_path)]) == []

    found = ff.find_file("geheim.exe", [str(tmp_path)])
    assert [os.path.basename(p) for p in found] == ["geheim.exe"]


# ---------------------------------------------------------------
# Gevaarlijke types: nooit zonder bevestiging openen
# ---------------------------------------------------------------

def test_exe_wordt_niet_geopend_zonder_bevestiging(tmp_path, monkeypatch):
    exe = _touch(tmp_path / "kwaad.exe")
    monkeypatch.setattr(ff, "find_file", lambda *args, **kwargs: ff.FileSearchResults([exe]))
    fake_pending = MagicMock()
    monkeypatch.setattr(ff, "set_pending", fake_pending)

    with patch("os.startfile", create=True) as m_start:
        result = ff.open_file("kwaad.exe")

    assert not m_start.called, "een .exe mag nooit zonder bevestiging openen"
    fake_pending.assert_called_once()
    assert fake_pending.call_args[0][0] == "file_open_confirm"
    payload = fake_pending.call_args[0][1]
    assert payload["name"] == "kwaad.exe"
    assert payload["folder"] == str(tmp_path)
    assert "kwaad.exe" in result


def test_bevestigd_bestand_wordt_geopend(tmp_path):
    exe = _touch(tmp_path / "kwaad.exe")

    with patch("os.startfile", create=True) as m_start:
        result = ff.open_confirmed(exe)

    assert m_start.called
    assert result.startswith("Ik open")


def test_file_open_confirm_is_gevaarlijk_file_choice_niet():
    assert confirmation.is_dangerous_kind("file_open_confirm")
    assert not confirmation.is_dangerous_kind("file_choice")


# ---------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------

def test_fuzzy_match_op_deel_van_de_naam(tmp_path):
    _touch(tmp_path / "factuur maart.pdf")
    _touch(tmp_path / "boodschappenlijst.txt")

    results = ff.find_file("factuur", [str(tmp_path)])

    assert [os.path.basename(p) for p in results] == ["factuur maart.pdf"]
    assert ff.find_file("jaarverslag", [str(tmp_path)]) == []


# ---------------------------------------------------------------
# Meerdere treffers: genummerde keuze (max drie)
# ---------------------------------------------------------------

def test_meerdere_treffers_genummerde_keuze(tmp_path, monkeypatch):
    a = _touch(tmp_path / "factuur maart.pdf")
    b = _touch(tmp_path / "factuur april.pdf")
    monkeypatch.setattr(ff, "find_file", lambda *args, **kwargs: ff.FileSearchResults([a, b]))
    fake_pending = MagicMock()
    monkeypatch.setattr(ff, "set_pending", fake_pending)

    with patch("os.startfile", create=True) as m_start:
        result = ff.open_file("factuur")

    assert not m_start.called
    assert "meerdere" in result
    assert "1:" in result and "2:" in result
    assert "factuur maart" in result and "factuur april" in result
    fake_pending.assert_called_once()
    assert fake_pending.call_args[0][0] == "file_choice"
    assert len(fake_pending.call_args[0][1]["matches"]) == 2


def test_maximaal_drie_keuzes(tmp_path, monkeypatch):
    paths = [_touch(tmp_path / f"notitie {i}.txt") for i in range(5)]
    monkeypatch.setattr(ff, "find_file", lambda *args, **kwargs: ff.FileSearchResults(paths))
    fake_pending = MagicMock()
    monkeypatch.setattr(ff, "set_pending", fake_pending)

    with patch("os.startfile", create=True):
        result = ff.open_file("notitie")

    assert len(fake_pending.call_args[0][1]["matches"]) == 3
    assert "3:" in result
    assert "4:" not in result


# ---------------------------------------------------------------
# Zoeklimieten: diepte, tijd en overgeslagen mappen
# ---------------------------------------------------------------

def test_diepte_limiet(tmp_path):
    _touch(tmp_path / "bovenaan.txt")

    deep = tmp_path
    for level in range(ff.FILE_MAX_DEPTH + 2):
        deep = deep / f"niveau{level}"
    deep.mkdir(parents=True)
    _touch(deep / "diep.txt")

    assert [os.path.basename(p) for p in ff.find_file("bovenaan", [str(tmp_path)])] == ["bovenaan.txt"]
    assert ff.find_file("diep", [str(tmp_path)]) == []


def test_skip_mappen(tmp_path):
    nm = tmp_path / "node_modules"
    nm.mkdir()
    _touch(nm / "pakket.txt")

    git = tmp_path / ".git"
    git.mkdir()
    _touch(git / "config.md")

    assert ff.find_file("pakket", [str(tmp_path)]) == []
    assert ff.find_file("config", [str(tmp_path)]) == []


def test_tijdslimiet(monkeypatch, tmp_path):
    _touch(tmp_path / "iets.txt")
    monkeypatch.setattr(ff, "FILE_SEARCH_TIMEOUT_SECONDS", -1)

    result = ff.find_file_detailed("iets", [str(tmp_path)])

    assert result["limit_reached"] is True
    assert result["matches"] == []


def test_limiet_melding_bij_openen(monkeypatch):
    monkeypatch.setattr(
        ff, "find_file", lambda *args, **kwargs: ff.FileSearchResults([], limit_reached=True)
    )

    result = ff.open_file("onvindbaar")

    assert "niet overal" in result


# ---------------------------------------------------------------
# Integratie met het pending-mechanisme (brain)
# ---------------------------------------------------------------

def test_brain_opent_na_bevestiging(tmp_path, monkeypatch):
    import core.brain as brain

    exe = _touch(tmp_path / "kwaad.exe")
    confirmation.set_pending(
        "file_open_confirm",
        {"path": exe, "name": "kwaad.exe", "folder": str(tmp_path)},
    )

    m = MagicMock(return_value="Ik open kwaad.exe.")
    monkeypatch.setattr(brain, "open_confirmed", m)

    out = brain.handle_pending_choice("ja")

    assert m.called and m.call_args[0][0] == exe
    assert out == "Ik open kwaad.exe."


def test_brain_opent_gekozen_bestand(tmp_path, monkeypatch):
    import core.brain as brain

    a = _touch(tmp_path / "factuur maart.pdf")
    b = _touch(tmp_path / "factuur april.pdf")
    confirmation.set_pending("file_choice", {"matches": [a, b], "query": "factuur"})

    m = MagicMock(return_value="Ik open factuur april.pdf.")
    monkeypatch.setattr(brain, "open_path", m)

    out = brain.handle_pending_choice("2")

    assert m.called and m.call_args[0][0] == b
    assert out == "Ik open factuur april.pdf."