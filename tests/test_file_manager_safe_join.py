"""Veilig samenstellen van bestandsnamen en paden (safe_join + callers)."""
import os

import pytest

import actions.file_manager as fm


# ---------------------------------------------------------------
# safe_join: onveilige namen/paden
# ---------------------------------------------------------------

@pytest.mark.parametrize("naam", [
    "../Desktop2/evil.txt",
    "..\\x",
    "sub/evil.txt",
    "C:\\x",
    "C:x",
    "CON",
    "con.txt",
    "NUL.log",
    "factuur:2026.txt",
    "a<b>.txt",
    "ster*retje.txt",
])
def test_safe_join_weigert_onveilige_namen(tmp_path, naam):
    with pytest.raises(ValueError):
        fm.safe_join(str(tmp_path), naam)


def test_safe_join_weigert_absoluut_pad(tmp_path):
    with pytest.raises(ValueError):
        fm.safe_join(str(tmp_path), str(tmp_path / "elders.txt"))


def test_safe_join_weigert_lege_naam(tmp_path):
    with pytest.raises(ValueError):
        fm.safe_join(str(tmp_path), "")


def test_safe_join_weigert_symlink_buiten_basis(tmp_path):
    basis = tmp_path / "basis"
    basis.mkdir()
    buiten = tmp_path / "buiten"
    buiten.mkdir()

    link = basis / "link"
    try:
        link.symlink_to(buiten, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks zijn hier niet beschikbaar")

    with pytest.raises(ValueError):
        fm.safe_join(str(basis), "link")


def test_safe_join_staat_gewone_naam_toe(tmp_path):
    result = fm.safe_join(str(tmp_path), "verslag.txt")

    basis_real = os.path.realpath(str(tmp_path))
    assert result == os.path.join(basis_real, "verslag.txt")
    assert os.path.commonpath([basis_real, result]) == basis_real


# ---------------------------------------------------------------
# create_folder / create_file gebruiken safe_join
# ---------------------------------------------------------------

def test_create_file_weigert_ontsnapping(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "resolve_location", lambda text: str(tmp_path))
    ontsnapt = tmp_path.parent / "ontsnapt.txt"

    result = fm.create_file("../ontsnapt", "")

    assert result == "Die naam kan ik niet gebruiken."
    assert not ontsnapt.exists()


def test_create_folder_weigert_gereserveerde_naam(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "resolve_location", lambda text: str(tmp_path))

    result = fm.create_folder("CON", "")

    assert result == "Die naam kan ik niet gebruiken."
    assert not (tmp_path / "CON").exists()


def test_create_file_maakt_gewone_naam(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "resolve_location", lambda text: str(tmp_path))

    result = fm.create_file("notitie", "")

    assert (tmp_path / "notitie.txt").is_file()
    assert "notitie.txt" in result


# ---------------------------------------------------------------
# rename_file gebruikt safe_join voor de nieuwe naam
# ---------------------------------------------------------------

def test_rename_file_weigert_ontsnapping(tmp_path, monkeypatch):
    bron = tmp_path / "oud.txt"
    bron.write_text("x", encoding="utf-8")
    monkeypatch.setattr(fm, "find_item", lambda name, max_depth=0: [str(bron)])

    result = fm.rename_file("oud", "..\\nieuw")

    assert result == "Die naam kan ik niet gebruiken."
    assert bron.exists()


# ---------------------------------------------------------------
# move_path overschrijft nooit stil
# ---------------------------------------------------------------

def test_move_path_bestaande_bestemming(tmp_path, monkeypatch):
    bron = tmp_path / "bron"
    bron.mkdir()
    bestand = bron / "rapport.txt"
    bestand.write_text("nieuw", encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "rapport.txt").write_text("bestaand", encoding="utf-8")

    monkeypatch.setattr(fm, "resolve_location", lambda text: str(dest))

    result = fm.move_path(str(bestand), "")

    assert "staat al" in result
    assert bestand.exists(), "het bronbestand mag niet verdwijnen"
    assert (dest / "rapport.txt").read_text(encoding="utf-8") == "bestaand"


def test_move_path_verplaatst_naar_vrije_bestemming(tmp_path, monkeypatch):
    bron = tmp_path / "bron"
    bron.mkdir()
    bestand = bron / "rapport.txt"
    bestand.write_text("inhoud", encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()

    monkeypatch.setattr(fm, "resolve_location", lambda text: str(dest))

    result = fm.move_path(str(bestand), "")

    assert not bestand.exists()
    assert (dest / "rapport.txt").read_text(encoding="utf-8") == "inhoud"
    assert "verplaatst" in result