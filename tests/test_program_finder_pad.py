"""Programma's zonder startmenu-snelkoppeling vinden via PATH.

Kladblok, Rekenmachine en Paint hebben op Windows 11 geen snelkoppeling
meer in het startmenu. Zonder terugval naar PATH meldde de agent
"ik kan notepad niet vinden".
"""

import actions.program_finder as finder


def test_via_pad_zoekt_eerst_met_exe(monkeypatch):
    gevraagd = []

    def nep_which(naam):
        gevraagd.append(naam)
        return r"C:\Windows\System32\notepad.exe" if naam == "notepad.exe" else None

    monkeypatch.setattr(finder.shutil, "which", nep_which)

    assert finder._via_pad("notepad") == r"C:\Windows\System32\notepad.exe"
    assert gevraagd == ["notepad.exe"]


def test_via_pad_valt_terug_op_de_naam(monkeypatch):
    monkeypatch.setattr(
        finder.shutil,
        "which",
        lambda naam: "/usr/bin/notepad" if naam == "notepad" else None,
    )

    assert finder._via_pad("notepad") == "/usr/bin/notepad"


def test_via_pad_geeft_none_zonder_treffer(monkeypatch):
    monkeypatch.setattr(finder.shutil, "which", lambda naam: None)

    assert finder._via_pad("bestaatniet") is None


def test_via_pad_vangt_oserror(monkeypatch):
    def kapot(naam):
        raise OSError("geen toegang")

    monkeypatch.setattr(finder.shutil, "which", kapot)

    assert finder._via_pad("notepad") is None


def test_find_program_gebruikt_pad_bij_geen_snelkoppeling(monkeypatch):
    """Geen treffer in het startmenu: het PATH-pad geldt als exacte match."""

    monkeypatch.setattr(finder.os.path, "exists", lambda pad: False)
    monkeypatch.setattr(
        finder, "_via_pad", lambda naam: r"C:\Windows\System32\notepad.exe"
    )

    assert finder.find_program("notepad", exact_only=True) == [
        r"C:\Windows\System32\notepad.exe"
    ]


def test_find_program_zonder_treffer_blijft_leeg(monkeypatch):
    monkeypatch.setattr(finder.os.path, "exists", lambda pad: False)
    monkeypatch.setattr(finder, "_via_pad", lambda naam: None)

    assert finder.find_program("bestaatniet", exact_only=True) == []


def test_find_program_zoekt_pad_ook_zonder_exact_only(monkeypatch):
    monkeypatch.setattr(finder.os.path, "exists", lambda pad: False)
    monkeypatch.setattr(finder, "_via_pad", lambda naam: r"C:\Windows\System32\calc.exe")

    assert finder.find_program("calc") == [r"C:\Windows\System32\calc.exe"]
