"""Tests voor spraaknormalisatie en de terugval bij het openen van bestanden.

Spraakherkenning schrijft bestandsnamen fonetisch ("jarvis laag streepje
test.txt" en "en download"). Deze tests bewaken dat zulke opdrachten weer
bruikbaar worden, zonder gewone zinnen aan te tasten.
"""

from unittest.mock import patch

from actions.file_finder import _bevat_alle_woorden, _kale_zoekterm, open_file
from core.spraak_normaliseer import normaliseer_spraak


def test_underscore_en_downloads_worden_gerepareerd():
    ruw = "open het bestand jarvis laag streepje test.txt en download"
    assert normaliseer_spraak(ruw) == "open het bestand jarvis_test.txt in downloads"


def test_lag_streepje_en_punt_extensie():
    ruw = "open rapport lag streepje 2026 punt txt"
    assert normaliseer_spraak(ruw) == "open rapport_2026.txt"


def test_onderstreping_en_underscore():
    assert normaliseer_spraak("open a onderstreping b") == "open a_b"
    assert normaliseer_spraak("open a underscore b") == "open a_b"


def test_gewone_zin_blijft_ongemoeid():
    assert normaliseer_spraak("wat is het punt van deze vraag") == (
        "wat is het punt van deze vraag"
    )
    assert normaliseer_spraak("download het bestand") == "download het bestand"


def test_lege_invoer():
    assert normaliseer_spraak("") == ""
    assert normaliseer_spraak(None) is None


def test_kale_zoekterm_laat_opvulwoorden_weg():
    # "txt" is een extensie, geen naamwoord: find_file() zoekt dan in alle
    # toegestane types en de strikte filter kiest het juiste bestand.
    assert _kale_zoekterm("open het bestand jarvis_test.txt in downloads") == (
        "jarvis test"
    )


def test_bevat_alle_woorden_filtert_zwakke_treffers():
    assert _bevat_alle_woorden(
        r"C:\Users\rushi\Downloads\jarvis_test.txt", ["jarvis", "test"]
    )
    assert not _bevat_alle_woorden(
        r"C:\Users\rushi\Downloads\Test.txt", ["jarvis", "test"]
    )
    assert not _bevat_alle_woorden(r"C:\Users\rushi\Desktop\JARVIS.zip", ["jarvis", "test"])


def test_open_file_probeert_opnieuw_met_kale_zoekterm():
    gevonden = [r"C:\Users\rushi\Downloads\jarvis_test.txt"]

    with patch(
        "actions.file_finder.find_file", side_effect=[[], gevonden]
    ) as zoek, patch("os.startfile", create=True) as start:
        resultaat = open_file("open het bestand jarvis_test.txt in downloads")

    assert zoek.call_count == 2
    assert start.called
    assert "niet vinden" not in resultaat
