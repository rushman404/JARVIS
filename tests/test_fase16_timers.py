"""Tests voor Fase 16A: timers en herinneringen (core/timers.py).

Alle verlooptests gebruiken een injecteerbare klok (fake clock); er wordt
niet geslapen.
"""

from datetime import datetime, timedelta

import pytest

from core import proactive
from core.proactive import ProactiveEngine
from core.proactive_commands import _extraheer_timer
from core.timers import TimerStore, parse_duur


# Vaste epoch-klok: 1_000_000.0 -> lokale tijd 1970-01-12 13:46:40.
# Tests kiezen zelf een tijdstip met `klok.op`.
EPOCH = 1_000_000.0


class FakeKlok:
    """Injecteerbare klok: vaste epoch-tijd die de test zelf vooruitzet."""

    def __init__(self, nu=EPOCH):
        self.nu = nu

    def __call__(self):
        return self.nu

    def vooruit(self, seconden):
        self.nu += seconden

    def op(self, jaar, maand, dag, uur, minuut=0, seconde=0):
        """Zet de klok op een lokaal tijdstip en geef de klok terug."""
        self.nu = datetime(
            jaar, maand, dag, uur, minuut, seconde
        ).timestamp()
        return self


class FakeEngineKlok:
    """Klok voor ProactiveEngine: levert zowel datetime als epoch-tijd.

    ``now_fn`` krijgt de lokale datetime (voor de nachtmodus) en ``time_fn``
    de bijbehorende epoch-seconden (voor timers en TTL's). Zo lopen beide
    klokken gegarandeerd gelijk.
    """

    def __init__(self, jaar=2026, maand=6, dag=1, uur=12, minuut=0):
        self.dt = datetime(jaar, maand, dag, uur, minuut, 0)

    def now(self):
        return self.dt

    def __call__(self):
        return self.dt.timestamp()

    def vooruit(self, seconden):
        self.dt = self.dt + timedelta(seconds=seconden)
        return self

    def op(self, jaar, maand, dag, uur, minuut=0, seconde=0):
        self.dt = datetime(jaar, maand, dag, uur, minuut, seconde)
        return self


@pytest.fixture(autouse=True)
def schone_proactieve_staat():
    """Reset de globale nacht-/stilte-/gespreksvlaggen voor elke test."""

    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    yield
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")


def _maak_engine(tmp_path, klok, **kwargs):
    """Bouwt een ProactiveEngine met fake klok en een verzamelende lever_fn.

    Standaard wordt een leeg regelbestand gebruikt, zodat alleen de timers
    meetellen en niet de voorbeeldregels uit config/proactive_rules.json.
    """

    store = kwargs.pop("store", None)
    if store is None:
        store = TimerStore(pad=str(tmp_path / "timers.json"), clock=klok)

    if "rules_pad" not in kwargs:
        leeg = tmp_path / "geen_regels.json"
        leeg.write_text("[]", encoding="utf-8")
        kwargs["rules_pad"] = str(leeg)

    geleverd = []
    engine = ProactiveEngine(
        store=store,
        now_fn=klok.now,
        time_fn=klok,
        lever_fn=geleverd.append,
        **kwargs,
    )
    return engine, store, geleverd


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


@pytest.mark.parametrize(
    "tekst,verwacht",
    [
        # De 21 zinnen uit de opdracht (inclusief de negen die eerst
        # fout gingen).
        ("anderhalf uur", 5400),
        ("1,5 uur", 5400),
        ("1.5 uur", 5400),
        ("drie kwartier", 2700),
        ("2 en een half uur", 9000),
        ("anderhalve minuut", 90),
        ("twintig minuten", 1200),
        ("vijftien minuten", 900),
        ("dertig seconden", 30),
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
        # Minimaal twintig extra varianten.
        ("in 3 uur", 10800),
        ("5 uur", 18000),
        ("5 u", 18000),
        ("1,5 minuten", 90),
        ("1.5 minuten", 90),
        ("2,5 uur", 9000),
        ("0,5 uur", 1800),
        ("kwart", 900),
        ("twee kwartier", 1800),
        ("vier kwartier", 3600),
        ("een half uur", 1800),
        ("1 uur en 30 minuten", 5400),
        ("1 uur 30 minuten 15 seconden", 5415),
        ("2 minuten en 30 seconden", 150),
        ("twintig seconden", 20),
        ("honderd seconden", 100),
        ("honderd minuten", 6000),
        ("vijfentwintig minuten", 1500),
        ("eenentwintig minuten", 1260),
        ("negenennegentig seconden", 99),
        ("tien minuten", 600),
        ("elf minuten", 660),
        ("twaalf minuten", 720),
        ("dertien minuten", 780),
        ("veertien minuten", 840),
        ("zestien minuten", 960),
        ("zeventien minuten", 1020),
        ("achttien minuten", 1080),
        ("negentien minuten", 1140),
        ("dertig minuten", 1800),
        ("veertig minuten", 2400),
        ("vijftig seconden", 50),
        ("zestig seconden", 60),
        ("zeventig seconden", 70),
        ("tachtig seconden", 80),
        ("negentig seconden", 90),
        ("10 sec", 10),
        ("3 min", 180),
        ("2 uur", 7200),
        ("2 uren", 7200),
        ("1 uur en een kwartier", 4500),
        ("twee en een half minuten", 150),
        ("anderhalf uur en 15 minuten", 6300),
        # Diakritische tekens en samengestelde getalwoorden.
        ("één uur", 3600),
        ("tweeëntwintig minuten", 1320),
        ("drieëndertig minuten", 1980),
        ("vijfenveertig minuten", 2700),
        ("negenennegentig minuten", 5940),
    ],
)
def test_parse_duur_uitgebreide_grammatica(tekst, verwacht):
    """De volledige duur-grammatica rekent alle varianten correct om."""
    assert parse_duur(tekst) == verwacht


@pytest.mark.parametrize(
    "tekst",
    [
        "1 uur 30",          # los getal zonder eenheid: dubbelzinnig
        "twee half uur",     # geen standaard-Nederlands
        "anderhalf",         # zonder eenheid
        "half",              # zonder eenheid
        "twintig",           # zonder eenheid
        "kwart over drie",   # kloktijd, geen duur
        "drie kwart over",   # kloktijd, geen duur
        "1:30 uur",          # kloktijd, geen duur
    ],
)
def test_parse_duur_dubbelzinnig_is_none(tekst):
    """Onvolledige of dubbelzinnige invoer levert None op (geen gok)."""
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


# ===============================================================
# Engine-tick met nepklok (Fase 16A: meldingen komen altijd aan)
# ===============================================================


def test_extraheer_timer_herkent_wekker_met_duur():
    """'zet een wekker over een half uur' is een timer van 1800 seconden."""
    gevonden = _extraheer_timer("zet een wekker over een half uur")

    assert gevonden is not None
    seconden, naam = gevonden
    assert seconden == 1800
    assert naam


def test_tick_overdag_levert_timer(tmp_path):
    """Overdag: een afgelopen timer wordt via lever_fn uitgesproken."""
    klok = FakeEngineKlok(uur=12)
    engine, store, geleverd = _maak_engine(tmp_path, klok)

    store.zet("oven", 60)
    klok.vooruit(61)

    aantal = engine.tick()

    assert aantal == 1
    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst
    assert geleverd[0].prioriteit == "gebruiker"


def test_tick_nachtmodus_levert_timer(tmp_path):
    """Nachtmodus (23:00-07:00): de timer wordt alsnog uitgesproken."""
    klok = FakeEngineKlok(uur=23, minuut=30)
    volumes = []
    engine, store, geleverd = _maak_engine(
        tmp_path, klok, volume_fn=volumes.append
    )

    store.zet("oven", 60)
    klok.vooruit(61)

    aantal = engine.tick()

    assert aantal == 1
    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst
    # 's nachts spreekt JARVIS zachter (nachtvolume is ingesteld).
    assert volumes and volumes[-1] == proactive.NACHTMODUS_VOLUME


def test_tick_wekker_0630_gezet_om_2200(tmp_path):
    """Een wekker die om 22:00 op 06:30 staat, gaat om 06:30 af."""
    klok = FakeEngineKlok(jaar=2026, maand=6, dag=1, uur=22)
    engine, store, geleverd = _maak_engine(tmp_path, klok)

    store.zet("wekker", 8 * 3600 + 1800)  # 22:00 -> 06:30 = 8,5 uur

    # Ruim vóór 06:30 mag er nog niets klinken.
    klok.op(2026, 6, 2, 6, 0)
    assert engine.tick() == 0
    assert geleverd == []

    # Om 06:30 gaat de wekker af.
    klok.op(2026, 6, 2, 6, 30)
    assert engine.tick() == 1
    assert len(geleverd) == 1
    assert "wekker" in geleverd[0].tekst
    assert "06:30" in geleverd[0].tekst


def test_tick_stille_modus_levert_timer(tmp_path):
    """Stille modus: gebruikersmeldingen (timers) worden altijd uitgesproken."""
    klok = FakeEngineKlok(uur=12)
    engine, store, geleverd = _maak_engine(tmp_path, klok)

    proactive.set_quiet(True)
    store.zet("oven", 60)
    klok.vooruit(61)

    assert engine.tick() == 1
    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst


def test_tick_auto_slaap_levert_timer(tmp_path):
    """Auto-slaap (geen pc-activiteit): de timer wordt alsnog uitgesproken."""
    klok = FakeEngineKlok(uur=12)
    engine, store, geleverd = _maak_engine(
        tmp_path, klok, actief_check_fn=lambda: False
    )

    store.zet("oven", 60)
    # Ruim voorbij de inactiviteitsgrens: auto-slaap treedt in.
    klok.vooruit(61)
    engine._laatste_activiteit = klok.dt.timestamp() - 10_000

    assert engine.is_auto_slaap() is False  # nog niet getickt
    aantal = engine.tick()

    assert engine.is_auto_slaap() is True
    assert aantal == 1
    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst


def test_verlate_melding_noemt_tijdstip(tmp_path):
    """Een tijdens stilstand verlopen timer wordt één keer gemeld, met tijd."""
    klok = FakeEngineKlok(jaar=2026, maand=6, dag=1, uur=17, minuut=44)
    pad = str(tmp_path / "timers.json")
    store = TimerStore(pad=pad, clock=klok)
    store.zet("oven", 60)  # loopt af om 17:45

    # JARVIS stond uit; bij de volgende start is de timer al verlopen.
    klok.op(2026, 6, 1, 18, 0)
    engine, _store, geleverd = _maak_engine(
        tmp_path, klok, store=TimerStore(pad=pad, clock=klok)
    )

    assert engine.tick() == 1
    assert "oven" in geleverd[0].tekst
    assert "17:45" in geleverd[0].tekst

    # Niet nog een keer: de timer is verbruikt.
    assert engine.tick() == 0
    assert len(geleverd) == 1


def test_timer_ouder_dan_24_uur_stil_verwijderd(tmp_path):
    """Een timer die > 24 uur geleden afliep, verdwijnt zonder melding."""
    klok = FakeEngineKlok(jaar=2026, maand=6, dag=1, uur=12)
    pad = str(tmp_path / "timers.json")
    store = TimerStore(pad=pad, clock=klok)
    store.zet("oud", 60)

    # Meer dan een dag later: de timer is niet meer relevant.
    klok.op(2026, 6, 3, 12, 0)
    verse_store = TimerStore(pad=pad, clock=klok)
    engine, _store, geleverd = _maak_engine(tmp_path, klok, store=verse_store)

    assert engine.tick() == 0
    assert geleverd == []
    # Wel uit de store verdwenen (zonder melding).
    assert verse_store.lijst() == []
    assert verse_store.verlopen_timers() == []
