"""Tests voor Fase 16A: timers en herinneringen (core/timers.py).

Alle verlooptests gebruiken een injecteerbare klok (fake clock); er wordt
niet geslapen.
"""

import pytest

from core.timers import TimerStore, parse_duur


class FakeKlok:
    """Injecteerbare klok: vaste epoch-tijd die de test zelf vooruitzet."""

    def __init__(self, nu=1_000_000.0):
        self.nu = nu

    def __call__(self):
        return self.nu

    def vooruit(self, seconden):
        self.nu += seconden


# ---------------------------------------------------------------
# parse_duur
# ---------------------------------------------------------------

@pytest.mark.parametrize(
    "tekst,verwacht",
    [
        ("10 minuten", 600),
        ("10 min", 600),
        ("2 min", 120),
        ("een uur", 3600),
        ("half uur", 1800),
        ("halve uur", 1800),
        ("kwartier", 900),
        ("een kwartier", 900),
        ("30 seconden", 30),
        ("twee minuten", 120),
        ("1 uur 30 minuten", 5400),
        ("over 5 minuten", 300),
        ("in 3 uur", 10800),
    ],
)
def test_parse_duur_varianten(tekst, verwacht):
    """Nederlandse duur-varianten worden correct omgerekend naar seconden."""
    assert parse_duur(tekst) == verwacht


@pytest.mark.parametrize("tekst", [None, "", "  ", "bla bla", "morgen"])
def test_parse_duur_zonder_duur(tekst):
    """Zonder herkenbare duur geeft parse_duur None (geen crash)."""
    assert parse_duur(tekst) is None


# ---------------------------------------------------------------
# TimerStore
# ---------------------------------------------------------------

def test_store_zet_en_lijst(tmp_path):
    """Een nieuwe timer staat in de lijst met absoluut afloop-tijdstip."""
    klok = FakeKlok()
    store = TimerStore(pad=str(tmp_path / "timers.json"), clock=klok)

    timer = store.zet("koffie", 60)

    assert timer["naam"] == "koffie"
    assert timer["af_loopt_op"] == klok.nu + 60
    assert timer["duur_seconden"] == 60
    assert len(timer["id"]) == 12

    lijst = store.lijst()
    assert len(lijst) == 1
    assert lijst[0]["naam"] == "koffie"

    # Verlopen timers verdwijnen uit de lijst.
    klok.vooruit(61)
    assert store.lijst() == []


def test_store_zet_ongeldige_duur(tmp_path):
    """Ongeldige duur (0, negatief, niet-numeriek) geeft None."""
    store = TimerStore(pad=str(tmp_path / "timers.json"), clock=FakeKlok())

    assert store.zet("x", 0) is None
    assert store.zet("x", -5) is None
    assert store.zet("x", "abc") is None
    assert store.lijst() == []


def test_store_annuleer(tmp_path):
    """Annuleren werkt met en zonder naam (hoofdletterongevoelig)."""
    store = TimerStore(pad=str(tmp_path / "timers.json"), clock=FakeKlok())
    store.zet("thee", 60)
    store.zet("koffie", 60)

    assert store.annuleer("THEE") == 1
    assert [t["naam"] for t in store.lijst()] == ["koffie"]

    assert store.annuleer() == 1  # alles
    assert store.lijst() == []
    assert store.annuleer() == 0


def test_store_verlopen_timers(tmp_path):
    """Verlopen timers worden verwijderd én teruggegeven; actieve blijven."""
    klok = FakeKlok()
    store = TimerStore(pad=str(tmp_path / "timers.json"), clock=klok)
    store.zet("kort", 10)
    store.zet("lang", 100)

    klok.vooruit(11)
    verlopen = store.verlopen_timers()

    assert [t["naam"] for t in verlopen] == ["kort"]
    assert [t["naam"] for t in store.lijst()] == ["lang"]
    assert store.verlopen_timers() == []


def test_timers_overleven_herstart(tmp_path):
    """Een herstart van JARVIS laadt de bestaande timers opnieuw in."""
    pad = str(tmp_path / "timers.json")
    klok = FakeKlok()
    store1 = TimerStore(pad=pad, clock=klok)
    store1.zet("oven", 60)

    # Alsof JARVIS opnieuw gestart is: nieuwe store, zelfde bestand.
    klok2 = FakeKlok(klok.nu + 30)
    store2 = TimerStore(pad=pad, clock=klok2)
    assert [t["naam"] for t in store2.lijst()] == ["oven"]

    # Na afloop wordt de timer alsnog als verlopen afgehandeld.
    klok2.vooruit(31)
    verlopen = store2.verlopen_timers()
    assert verlopen and verlopen[0]["naam"] == "oven"
    assert store2.lijst() == []


def test_corrupt_bestand_geeft_lege_lijst(tmp_path):
    """Corrupt JSON levert een lege lijst op (nooit een crash)."""
    pad = tmp_path / "timers.json"
    pad.write_text("{dit is geen json", encoding="utf-8")

    store = TimerStore(pad=str(pad), clock=FakeKlok())

    assert store.lijst() == []


def test_bak_wordt_gebruikt_bij_corruptie(tmp_path):
    """Valt het hoofdbestand weg, dan leest de store de .bak-backup."""
    pad = str(tmp_path / "timers.json")
    klok = FakeKlok()
    store = TimerStore(pad=pad, clock=klok)
    store.zet("eerste", 3600)   # eerste schrijven: nog geen .bak
    store.zet("tweede", 7200)   # tweede: .bak bevat de staat na "eerste"

    with open(pad, "w", encoding="utf-8") as f:
        f.write("{kapot")

    hersteld = TimerStore(pad=pad, clock=klok)
    assert [t["naam"] for t in hersteld.lijst()] == ["eerste"]
