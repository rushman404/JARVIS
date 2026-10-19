"""Tests voor Fase 16A: proactieve engine (core/proactive.py).

De engine wordt volledig met een fake klok aangestuurd (``now_fn`` en
``time_fn``); er wordt niet geslapen en er is geen echte achtergrondthread
nodig: tests roepen ``tick()`` direct aan.
"""

import json
from datetime import datetime, timedelta

import pytest

from core import proactive
from core.proactive import (
    Melding,
    Meldingswachtrij,
    ProactiveEngine,
    is_nachtmodus,
)
from core.timers import TimerStore


@pytest.fixture(autouse=True)
def schone_staat(monkeypatch):
    """Vaste nachtmodus-grenzen + schone quiet-/gesprek-vlaggen."""

    monkeypatch.setattr(proactive, "NACHTMODUS_START", 23)
    monkeypatch.setattr(proactive, "NACHTMODUS_EIND", 7)
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    yield
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    proactive.reset_engine(None)


class FakeKlok:
    """Datetime- én epoch-klok die de test zelf aanstuurt."""

    def __init__(self, uur=12, minuut=0, ts=0.0):
        self.dt = datetime(2026, 3, 2, uur, minuut)
        self.ts = ts

    def now(self):
        return self.dt

    def tijd(self):
        return self.ts

    def zet_dt(self, dt):
        self.dt = dt

    def vooruit(self, seconden):
        self.dt = self.dt + timedelta(seconds=seconden)
        self.ts += seconden


def _schrijf_regels(tmp_path, regels):
    pad = tmp_path / "proactive_rules.json"
    pad.write_text(
        json.dumps({"regels": regels}, ensure_ascii=False), encoding="utf-8"
    )
    return str(pad)


def _maak_engine(tmp_path, klok, regels, **kwargs):
    return ProactiveEngine(
        now_fn=klok.now,
        time_fn=klok.tijd,
        rules_pad=_schrijf_regels(tmp_path, regels),
        **kwargs,
    )


# ---------------------------------------------------------------
# Nachtmodus
# ---------------------------------------------------------------

def test_is_nachtmodus_grenzen():
    """Het nachtvenster 23:00-07:00 loopt door middernacht heen."""
    assert is_nachtmodus(datetime(2026, 1, 1, 23, 30), 23, 7) is True
    assert is_nachtmodus(datetime(2026, 1, 1, 23, 0), 23, 7) is True
    assert is_nachtmodus(datetime(2026, 1, 1, 6, 59), 23, 7) is True
    assert is_nachtmodus(datetime(2026, 1, 1, 7, 0), 23, 7) is False
    assert is_nachtmodus(datetime(2026, 1, 1, 12, 0), 23, 7) is False
    # Na middernacht (overloop).
    assert is_nachtmodus(datetime(2026, 1, 1, 0, 30), 23, 7) is True


def test_is_nachtmodus_start_gelijk_aan_eind():
    """Start == eind betekent: nachtmodus uit (altijd False)."""
    assert is_nachtmodus(datetime(2026, 1, 1, 12, 0), 12, 12) is False


def test_is_nachtmodus_zonder_argumenten(monkeypatch):
    """Zonder argumenten worden de configuratie-grenzen gebruikt."""
    monkeypatch.setattr(proactive, "NACHTMODUS_START", 23)
    monkeypatch.setattr(proactive, "NACHTMODUS_EIND", 7)
    assert is_nachtmodus(datetime(2026, 1, 1, 23, 15)) is True
    assert is_nachtmodus(datetime(2026, 1, 1, 8, 0)) is False


# ---------------------------------------------------------------
# Melding + wachtrij
# ---------------------------------------------------------------

def test_melding_ttl_verlopen():
    """De TTL wordt berekend vanaf de meegegeven basistijd (nu)."""
    m = Melding("ha", ttl=100, nu=1000.0)
    assert m.verloopt_op == 1100.0
    assert m.verlopen(1099.0) is False
    assert m.verlopen(1100.0) is True


def test_melding_zonder_ttl_verloopt_nooit():
    m = Melding("x", ttl=None, nu=0.0)
    assert m.verlopen(999999.0) is False


def test_wachtrij_toevoegen_en_ophalen():
    w = Meldingswachtrij(max_wachtrij=5)
    assert w.stop(Melding("hallo", nu=0.0)) is True
    assert w.lengte() == 1

    items = w.neem_alle()
    assert [m.tekst for m in items] == ["hallo"]
    assert w.lengte() == 0


def test_wachtrij_slaat_dubbele_tekst_af():
    w = Meldingswachtrij()
    assert w.stop(Melding("melding", nu=0.0)) is True
    assert w.stop(Melding("melding", nu=0.0)) is False
    assert w.lengte() == 1


def test_wachtrij_vol():
    w = Meldingswachtrij(max_wachtrij=2)
    w.stop(Melding("a", nu=0.0))
    w.stop(Melding("b", nu=0.0))
    assert w.stop(Melding("c", nu=0.0)) is False
    assert w.lengte() == 2


def test_wachtrij_lege_tekst():
    w = Meldingswachtrij()
    assert w.stop(Melding("", nu=0.0)) is False
    assert w.lengte() == 0


def test_wachtrij_gooit_verlopen_weg():
    w = Meldingswachtrij()
    w.stop(Melding("oud", ttl=10, nu=0.0))
    w.stop(Melding("vers", ttl=1000, nu=0.0))

    assert w.verlopen_weggooien(500.0) == 1
    assert w.lengte() == 1
    assert w.neem_alle()[0].tekst == "vers"


# ---------------------------------------------------------------
# Engine: trigger-typen
# ---------------------------------------------------------------

def test_tijd_regel_gaat_een_keer_per_dag_af(tmp_path):
    """Een tijd-regel vuurt één keer per dag, binnen het tick-venster."""
    klok = FakeKlok(uur=7, minuut=59)
    regels = [{
        "id": "goedemorgen",
        "actief": True,
        "trigger": {"type": "tijd", "tijd": "08:00"},
        "melding": "Goedemorgen!",
    }]
    engine = _maak_engine(tmp_path, klok, regels)

    # Voor het doelmoment: nog niets.
    engine.tick()
    assert engine.wachtrij.lengte() == 0

    # Na het doelmoment (binnen het venster): melding.
    klok.zet_dt(datetime(2026, 3, 2, 8, 0, 30))
    engine.tick()
    assert engine.wachtrij.lengte() == 1

    # Tweede tick dezelfde dag: niet opnieuw.
    klok.vooruit(60)
    engine.tick()
    assert engine.wachtrij.lengte() == 1


def test_inactieve_regel_gaat_niet_af(tmp_path):
    """Regels met actief:false worden overgeslagen."""
    klok = FakeKlok(uur=8, minuut=1)
    regels = [{
        "id": "goedemorgen",
        "actief": False,
        "trigger": {"type": "tijd", "tijd": "08:00"},
        "melding": "Goedemorgen!",
    }]
    engine = _maak_engine(tmp_path, klok, regels)

    engine.tick()
    assert engine.wachtrij.lengte() == 0


def test_interval_regel(tmp_path):
    """Een interval-regel gaat af zodra het interval verstreken is."""
    klok = FakeKlok(ts=0.0)
    regels = [{
        "id": "pauze",
        "actief": True,
        "trigger": {"type": "interval", "seconden": 3600},
        "melding": "Tijd voor een pauze.",
    }]
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, regels, lever_fn=lambda m: geleverd.append(m.tekst)
    )

    engine.tick()                      # eerste keer: gaat af
    assert geleverd == ["Tijd voor een pauze."]

    klok.vooruit(100)                  # te vroeg
    engine.tick()
    assert len(geleverd) == 1

    klok.vooruit(3600)                 # voorbij het interval
    engine.tick()
    assert len(geleverd) == 2


def test_statuswijziging_eerste_meting_stil(tmp_path):
    """De eerste meting legt alleen status vast; melding komt bij transitie."""
    klok = FakeKlok(ts=0.0)
    ha = {"waarde": True}
    regels = [{
        "id": "ha_offline",
        "actief": True,
        "trigger": {
            "type": "statuswijziging",
            "bron": "ha",
            "verwacht": False,
            "herhaal_seconden": 0,
        },
        "melding": "Home Assistant is offline.",
    }]
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, regels,
        ha_check_fn=lambda: ha["waarde"],
        lever_fn=lambda m: geleverd.append(m.tekst),
    )

    engine.tick()                      # eerste meting: stil
    assert geleverd == []

    ha["waarde"] = False               # naar offline (verwacht False)
    klok.vooruit(10)
    engine.tick()
    assert len(geleverd) == 1

    klok.vooruit(10)                   # blijft offline: geen herhaling
    engine.tick()
    assert len(geleverd) == 1

    ha["waarde"] = True                # terug online: 'verwacht' blokkeert
    klok.vooruit(10)
    engine.tick()
    assert len(geleverd) == 1


def test_statuswijziging_zonder_verwacht_meldt_elke_transitie(tmp_path):
    """Zonder 'verwacht' meldt de regel bij elke verandering."""
    klok = FakeKlok(ts=0.0)
    ha = {"waarde": True}
    regels = [{
        "id": "ha_wissel",
        "actief": True,
        "trigger": {
            "type": "statuswijziging",
            "bron": "ha",
            "herhaal_seconden": 0,
        },
        "melding": "De HA-status is veranderd.",
    }]
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, regels,
        ha_check_fn=lambda: ha["waarde"],
        lever_fn=lambda m: geleverd.append(m.tekst),
    )

    engine.tick()                      # eerste meting: stil
    assert geleverd == []

    ha["waarde"] = False
    klok.vooruit(10)
    engine.tick()
    ha["waarde"] = True
    klok.vooruit(10)
    engine.tick()
    assert len(geleverd) == 2


def test_schijf_drempel(tmp_path):
    """Schijf-regel meldt bij een statuswissel onder de drempel."""
    klok = FakeKlok(ts=0.0)
    vrij = {"waarde": 50.0}
    regels = [{
        "id": "schijf_vol",
        "actief": True,
        "trigger": {
            "type": "statuswijziging",
            "bron": "schijf",
            "drempel_percent": 10,
            "herhaal_seconden": 0,
        },
        "melding": "De schijf is bijna vol.",
    }]
    engine = _maak_engine(
        tmp_path, klok, regels, schijf_check_fn=lambda: vrij["waarde"]
    )

    engine.tick()                      # 50% vrij: eerste meting, stil
    assert engine.wachtrij.lengte() == 0

    vrij["waarde"] = 5.0               # onder de drempel: verandering
    klok.vooruit(10)
    engine.tick()
    assert engine.wachtrij.lengte() == 1


def test_voorwaarde_nachtmodus_blokkeert(tmp_path):
    """Een regel met voorwaarde nachtmodus gaat niet 's nachts af."""
    klok = FakeKlok(uur=23, minuut=30, ts=0.0)  # in de nacht
    regels = [{
        "id": "pauze",
        "actief": True,
        "trigger": {"type": "interval", "seconden": 1},
        "voorwaarden": {"nachtmodus": True},
        "melding": "Tijd voor een pauze.",
    }]
    engine = _maak_engine(tmp_path, klok, regels)

    engine.tick()
    assert engine.wachtrij.lengte() == 0

    # Overdag gaat hij wel af.
    klok.zet_dt(datetime(2026, 3, 2, 12, 0))
    klok.vooruit(60)
    engine.tick()
    assert engine.wachtrij.lengte() == 1


# ---------------------------------------------------------------
# Engine: afleveren, stilte, volume
# ---------------------------------------------------------------

def test_lever_fn_wacht_tot_in_gesprek_voorbij(tmp_path):
    """Tijdens een gesprek wordt niet afgeleverd; daarna wel."""
    klok = FakeKlok(uur=12, ts=0.0)
    gesprek = {"waarde": True}
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [],
        lever_fn=lambda m: geleverd.append(m.tekst),
        in_gesprek_fn=lambda: gesprek["waarde"],
    )

    engine._verstuur("Iets te melden.")

    engine.tick()
    assert geleverd == []
    assert engine.wachtrij.lengte() == 1

    gesprek["waarde"] = False
    engine.tick()
    assert geleverd == ["Iets te melden."]
    assert engine.wachtrij.lengte() == 0


def test_nachtmodus_levert_niet_af(tmp_path):
    """'s Nachts spreekt de engine niets uit; overdag alsnog (binnen TTL)."""
    klok = FakeKlok(uur=23, minuut=30, ts=0.0)
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], lever_fn=lambda m: geleverd.append(m.tekst)
    )

    engine._verstuur("Nachtmelding.")

    engine.tick()
    assert geleverd == []
    assert engine.wachtrij.lengte() == 1

    klok.zet_dt(datetime(2026, 3, 3, 8, 0))
    klok.vooruit(60)
    engine.tick()
    assert geleverd == ["Nachtmelding."]


def test_stille_modus_levert_niet_af(tmp_path):
    """In de stille modus wordt niet afgeleverd; zodra hij uit staat wel."""
    klok = FakeKlok(uur=12, ts=0.0)
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], lever_fn=lambda m: geleverd.append(m.tekst)
    )

    proactive.set_quiet(True)
    engine._verstuur("Stille melding.")

    engine.tick()
    assert geleverd == []

    proactive.set_quiet(False)
    engine.tick()
    assert geleverd == ["Stille melding."]


def test_volume_bij_nachtmodus_overgang(tmp_path):
    """Het volume volgt de nachtmodus-overgang (dag <-> nacht), eenmalig."""
    klok = FakeKlok(uur=12, minuut=0)
    aangeroepen = []
    engine = _maak_engine(tmp_path, klok, [], volume_fn=aangeroepen.append)

    engine.tick()                      # eerste tick: dag
    assert aangeroepen == [proactive.DAGVOLUME]

    engine.tick()                      # nog steeds dag: geen herhaling
    assert aangeroepen == [proactive.DAGVOLUME]

    klok.zet_dt(datetime(2026, 3, 2, 23, 30))
    engine.tick()                      # nachtmodus in
    assert aangeroepen == [
        proactive.DAGVOLUME, proactive.NACHTMODUS_VOLUME,
    ]

    klok.zet_dt(datetime(2026, 3, 3, 10, 0))
    engine.tick()                      # nachtmodus uit
    assert aangeroepen == [
        proactive.DAGVOLUME,
        proactive.NACHTMODUS_VOLUME,
        proactive.DAGVOLUME,
    ]


# ---------------------------------------------------------------
# Engine: timers
# ---------------------------------------------------------------

def test_verloopte_timer_wordt_gemeld(tmp_path):
    """Een verlopen timer levert een melding op en verdwijnt uit de store."""
    klok = FakeKlok(uur=12, ts=0.0)
    store = TimerStore(
        pad=str(tmp_path / "timers.json"), clock=lambda: klok.ts
    )
    store.zet("koffie", 60)
    engine = _maak_engine(tmp_path, klok, [], store=store)

    engine.tick()
    assert engine.wachtrij.lengte() == 0          # nog niet verlopen

    klok.vooruit(61)
    engine.tick()
    assert engine.wachtrij.lengte() == 1
    melding = engine.wachtrij.neem_alle()[0]
    assert "koffie" in melding.tekst
    assert store.lijst() == []


# ---------------------------------------------------------------
# Engine: gebruikersmeldingen (timers en wekkers)
# ---------------------------------------------------------------

def _tijd_ts(uur, minuut):
    """Epoch-tijd die hoort bij de datum van FakeKlok."""

    return datetime(2026, 3, 2, uur, minuut).timestamp()


def _timer_scenario(tmp_path, klok, **kwargs):
    """Zet een timer van 60 seconden en laat hem precies verlopen."""

    store = TimerStore(
        pad=str(tmp_path / "timers.json"), clock=klok.tijd
    )
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], store=store,
        lever_fn=lambda m: geleverd.append(m), **kwargs,
    )
    store.zet("oven", 60)
    engine.tick()               # nog niet verlopen
    klok.vooruit(61)            # nu verlopen
    engine.tick()
    return geleverd


def test_melding_timer_krijgt_prioriteit_en_ttl_30_minuten():
    """Timers/wekkers zijn gebruikersmeldingen met een TTL van 30 minuten."""
    melding = Melding(
        "Je timer 'oven' is om 17:45 afgegaan.", bron="timer", nu=0.0
    )
    assert melding.prioriteit == "gebruiker"
    assert melding.verloopt_op == proactive.GEBRUIKER_MELDING_TTL
    assert melding.verlopen(proactive.GEBRUIKER_MELDING_TTL - 1) is False
    assert melding.verlopen(proactive.GEBRUIKER_MELDING_TTL) is True

    systeem = Melding("Tijd voor een pauze.", bron="pauze", nu=0.0)
    assert systeem.prioriteit == "systeem"
    assert systeem.verloopt_op == proactive.DEFAULT_MELDING_TTL


def test_verstuur_geeft_timer_prioriteit_gebruiker(tmp_path):
    """_verstuur kent timers prioriteit 'gebruiker' toe, regels 'systeem'."""
    klok = FakeKlok(uur=12, ts=0.0)
    engine = _maak_engine(tmp_path, klok, [])

    engine._verstuur("timer", bron="timer", nu_ts=0.0)
    engine._verstuur("regel", bron="pauze", nu_ts=0.0)

    items = {m.tekst: m for m in engine.wachtrij.neem_alle()}
    assert items["timer"].prioriteit == "gebruiker"
    assert items["regel"].prioriteit == "systeem"
    assert items["timer"].verloopt_op == proactive.GEBRUIKER_MELDING_TTL
    assert items["regel"].verloopt_op == proactive.DEFAULT_MELDING_TTL


def test_timer_wordt_overdag_uitgesproken(tmp_path):
    """Overdag wordt een verlopen timer gewoon uitgesproken."""
    klok = FakeKlok(uur=12, ts=_tijd_ts(12, 0))

    geleverd = _timer_scenario(tmp_path, klok)

    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst
    assert geleverd[0].prioriteit == "gebruiker"


def test_timer_wordt_s_nachts_uitgesproken(tmp_path):
    """In de nachtmodus wordt een timer toch uitgesproken (nachtvolume)."""
    klok = FakeKlok(uur=23, minuut=30, ts=_tijd_ts(23, 30))
    volume = []

    geleverd = _timer_scenario(tmp_path, klok, volume_fn=volume.append)

    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst
    # Het bestaande nachtvolume is toegepast voordat de timer klinkt.
    assert proactive.NACHTMODUS_VOLUME in volume


def test_wekker_0630_wordt_uitgesproken_en_noemt_de_tijd(tmp_path):
    """Een wekker die om 06:30 afloopt, klinkt en noemt 06:30."""
    klok = FakeKlok(uur=6, minuut=29, ts=_tijd_ts(6, 29))
    store = TimerStore(
        pad=str(tmp_path / "timers.json"), clock=klok.tijd
    )
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], store=store,
        lever_fn=lambda m: geleverd.append(m),
    )

    store.zet("wekker", 60)
    engine.tick()
    klok.vooruit(60)            # 06:30
    engine.tick()

    assert len(geleverd) == 1
    assert "06:30" in geleverd[0].tekst


def test_timer_wordt_in_stille_modus_uitgesproken(tmp_path):
    """De stille modus houdt systeemmeldingen tegen, maar geen timers."""
    klok = FakeKlok(uur=12, ts=_tijd_ts(12, 0))
    proactive.set_quiet(True)

    geleverd = _timer_scenario(tmp_path, klok)

    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst


def test_timer_wordt_tijdens_auto_slaap_uitgesproken(tmp_path):
    """Ook tijdens auto-slaap wordt een verlopen timer uitgesproken."""
    klok = FakeKlok(uur=12, ts=_tijd_ts(12, 0))
    store = TimerStore(
        pad=str(tmp_path / "timers.json"), clock=klok.tijd
    )
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], store=store,
        lever_fn=lambda m: geleverd.append(m),
        actief_check_fn=lambda: False,
        inactiviteit_seconden=60,
    )

    store.zet("oven", 120)
    engine.tick()               # activiteitsklok start
    klok.vooruit(61)
    engine.tick()               # auto-slaap aan, timer nog niet verlopen
    assert engine.is_auto_slaap() is True

    klok.vooruit(60)            # totaal 121: timer verlopen
    engine.tick()

    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst


def test_systeemmelding_blijft_stil_maar_timer_klinkt(tmp_path):
    """In de nachtmodus wacht een systeemmelding; een timer klinkt direct."""
    klok = FakeKlok(uur=23, minuut=30, ts=_tijd_ts(23, 30))
    store = TimerStore(
        pad=str(tmp_path / "timers.json"), clock=klok.tijd
    )
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], store=store,
        lever_fn=lambda m: geleverd.append(m),
    )

    engine._verstuur("Tijd voor een pauze.", bron="pauze")
    store.zet("oven", 60)
    engine.tick()               # systeem wacht, timer nog niet verlopen
    klok.vooruit(61)
    engine.tick()               # timer klinkt, systeem wacht nog

    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst
    assert engine.wachtrij.lengte() == 1


def test_gebruiker_melding_vervalt_niet_na_120_seconden(tmp_path):
    """Een timermelding blijft staan tot 30 minuten, niet tot 120 seconden."""
    klok = FakeKlok(uur=23, minuut=30, ts=0.0)
    store = TimerStore(
        pad=str(tmp_path / "timers.json"), clock=klok.tijd
    )
    engine = _maak_engine(tmp_path, klok, [], store=store)

    store.zet("oven", 60)
    klok.vooruit(61)
    engine.tick()
    assert engine.wachtrij.lengte() == 1

    klok.vooruit(120)           # systeem-TTL zou nu verstreken zijn
    engine.tick()
    assert engine.wachtrij.lengte() == 1

    klok.vooruit(1800)          # na 30 minuten vervalt hij alsnog
    engine.tick()
    assert engine.wachtrij.lengte() == 0


def test_verlate_timer_na_herstart_noemt_de_tijd(tmp_path):
    """Een timer die afliep terwijl JARVIS uit stond, wordt één keer gemeld."""
    pad = str(tmp_path / "timers.json")
    eerste_klok = FakeKlok(uur=17, minuut=45, ts=_tijd_ts(17, 45))
    eerste_store = TimerStore(pad=pad, clock=eerste_klok.tijd)
    eerste_store.zet("oven", 60)        # afloop 17:46

    # JARVIS start opnieuw om 18:15.
    klok = FakeKlok(uur=18, minuut=15, ts=_tijd_ts(18, 15))
    store = TimerStore(pad=pad, clock=klok.tijd)
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], store=store,
        lever_fn=lambda m: geleverd.append(m),
    )

    engine.tick()
    assert len(geleverd) == 1
    assert "oven" in geleverd[0].tekst
    assert "17:46" in geleverd[0].tekst
    assert store.lijst() == []

    engine.tick()               # niet nog een keer
    assert len(geleverd) == 1


def test_timer_ouder_dan_24_uur_wordt_stil_verwijderd(tmp_path):
    """Een timer die meer dan 24 uur geleden afliep, meldt niets meer."""
    pad = str(tmp_path / "timers.json")
    eerste_klok = FakeKlok(uur=17, ts=_tijd_ts(17, 0))
    eerste_store = TimerStore(pad=pad, clock=eerste_klok.tijd)
    eerste_store.zet("oud", 60)         # afloop 17:01 op dag 1

    klok = FakeKlok(uur=18, ts=_tijd_ts(17, 0) + 25 * 3600)
    klok.zet_dt(datetime(2026, 3, 3, 18, 0))
    store = TimerStore(pad=pad, clock=klok.tijd)
    geleverd = []
    engine = _maak_engine(
        tmp_path, klok, [], store=store,
        lever_fn=lambda m: geleverd.append(m),
    )

    engine.tick()

    assert geleverd == []
    assert store.lijst() == []


# ---------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------

def test_module_engine_singleton():
    """get_engine geeft altijd dezelfde engine tot reset_engine."""
    eigen = ProactiveEngine()
    proactive.reset_engine(eigen)
    try:
        assert proactive.get_engine() is eigen
    finally:
        proactive.reset_engine(None)
