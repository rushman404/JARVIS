"""Tests voor automatische geluidsducking (Fase 17, G).

JARVIS moet het systeemvolume tijdelijk verlagen zodra hij praat, en het
daarna automatisch terugzetten — zonder ooit vast te lopen als het volume
niet leesbaar is. Ducking gebeurt op de achtergrond, dus de tests wachten
kort op de ducking-thread.
"""

import pytest

import actions.media as media
import voice.ducking as ducking
from config import DUCKING_MIN_PERCENT


class _NepVolume:
    """Vervangt actions.media.get_volume/set_volume met een namaakvolume."""

    def __init__(self, waarde=60):
        self.waarde = waarde
        self.gezet = []

    def get_volume(self):
        return self.waarde

    def set_volume(self, percent):
        self.waarde = percent
        self.gezet.append(percent)
        return f"Volume staat nu op {percent}%."


def _wacht_op_duck(timeout=3.0):
    """Wacht tot een lopende achtergrond-ducking klaar is."""
    draad = ducking._bezig
    if draad is not None:
        draad.join(timeout=timeout)


@pytest.fixture
def nep_volume(monkeypatch):
    """Verse ducking-staat plus een namaak-systeemvolume voor actions.media."""
    ducking.reset()
    nep = _NepVolume()
    monkeypatch.setattr(media, "get_volume", nep.get_volume)
    monkeypatch.setattr(media, "set_volume", nep.set_volume)
    yield nep
    _wacht_op_duck()
    ducking.reset()


def test_duck_verlaagt_volume(nep_volume):
    nep_volume.waarde = 60

    ducking.duck()
    _wacht_op_duck()

    # 60 - 45 = 15, maar het minimum is 20 → 20%.
    assert nep_volume.waarde == DUCKING_MIN_PERCENT
    assert ducking.is_geduckt()


def test_duck_verlaagt_volume_boven_minimum(nep_volume):
    nep_volume.waarde = 80

    ducking.duck()
    _wacht_op_duck()

    assert nep_volume.waarde == 80 - 45
    assert ducking.is_geduckt()


def test_herstel_zet_origineel_terug(nep_volume):
    nep_volume.waarde = 60

    ducking.duck()
    _wacht_op_duck()
    ducking.herstel()

    assert nep_volume.waarde == 60
    assert not ducking.is_geduckt()


def test_duck_twee_keer_bewerkt_niets_de_tweede_keer(nep_volume):
    nep_volume.waarde = 70

    ducking.duck()
    _wacht_op_duck()
    eerste = list(nep_volume.gezet)
    ducking.duck()
    _wacht_op_duck()

    assert nep_volume.gezet == eerste, "tweede duck() mag niet opnieuw dempen"


def test_duck_doet_niets_als_volume_al_op_minimum_staat(nep_volume):
    nep_volume.waarde = DUCKING_MIN_PERCENT

    ducking.duck()
    _wacht_op_duck()

    assert nep_volume.gezet == [], "volume op het minimum wordt niet geduckt"
    assert not ducking.is_geduckt()


def test_duck_doet_niets_als_volume_onder_minimum_staat(nep_volume):
    nep_volume.waarde = DUCKING_MIN_PERCENT - 10

    ducking.duck()
    _wacht_op_duck()

    assert nep_volume.gezet == []
    assert not ducking.is_geduckt()


def test_duck_doet_niets_bij_leesfout(nep_volume, monkeypatch):
    monkeypatch.setattr(media, "get_volume", lambda: None)

    ducking.duck()
    _wacht_op_duck()

    assert not ducking.is_geduckt()


def test_duck_uit_doet_niets(nep_volume, monkeypatch):
    nep_volume.waarde = 60
    monkeypatch.setattr(ducking, "DUCKING_ENABLED", False)

    ducking.duck()
    _wacht_op_duck()

    assert nep_volume.gezet == []
    assert not ducking.is_geduckt()


def test_duck_duurt_niet_lang(nep_volume):
    """duck() mag het praten niet ophouden: het volume werk gebeurt op de
    achtergrond."""
    nep_volume.waarde = 60

    import time

    start = time.monotonic()
    ducking.duck()
    verstreken = time.monotonic() - start

    assert verstreken < 0.1, "duck() moet direct terugkeren"
    _wacht_op_duck()


def test_herstel_zonder_duck_doet_niets(nep_volume):
    ducking.herstel()

    assert not ducking.is_geduckt()


def test_herstel_laat_zelf_aangepast_volume_staan(nep_volume):
    nep_volume.waarde = 60

    ducking.duck()
    _wacht_op_duck()
    nep_volume.waarde = 35  # gebruiker past zelf het volume aan tijdens praten
    ducking.herstel()

    assert nep_volume.waarde == 35
    assert not ducking.is_geduckt()
