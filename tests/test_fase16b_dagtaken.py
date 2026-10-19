"""Tests voor Fase 16B: dagtaken & zorg-coaching.

Dekt drie nieuwe onderdelen:
* ``core.pc_activiteit`` — is de pc recent in gebruik?
* auto-slaap en de ``actief``-trigger in de proactieve engine;
* dagstart-/dagafsluiting-commando's (alleen op aanvraag).

Net als in 16A wordt alles met fake klokken aangestuurd: er wordt niet
geslapen en er draait geen echte achtergrondthread.
"""

import json
from datetime import datetime, timedelta

import pytest

from core import pc_activiteit
from core import proactive
from core import timers as timers_module
from core.proactive import ProactiveEngine
from core.proactive_commands import (
    _DAGAFSLUITING_PATROON,
    _DAGSTART_PATROON,
    try_proactive_command,
)
from core.timers import TimerStore


@pytest.fixture(autouse=True)
def schone_staat(monkeypatch, tmp_path):
    """Vaste nachtmodus-grenzen, schone vlaggen en een lege timerstore."""

    monkeypatch.setattr(proactive, "NACHTMODUS_START", 23)
    monkeypatch.setattr(proactive, "NACHTMODUS_EIND", 7)
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    timers_module.reset_store(
        TimerStore(pad=str(tmp_path / "timers.json"), clock=lambda: 1_000_000.0)
    )
    yield
    proactive.set_quiet(False)
    proactive.set_in_gesprek(False)
    proactive.set_nachtmodus("auto")
    proactive.reset_engine(None)
    timers_module.reset_store(None)


class FakeKlok:
    """Datetime- én epoch-klok die de test zelf aanstuurt."""

    def __init__(self, uur=12, minuut=0, ts=0.0):
        self.dt = datetime(2026, 3, 2, uur, minuut)
        self.ts = ts

    def now(self):
        return self.dt

    def tijd(self):
        return self.ts

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
# pc-activiteit
# ---------------------------------------------------------------

def test_is_actief_bij_recente_invoer():
    """Recente invoer (< drempel) betekent dat de pc in gebruik is."""

    assert pc_activiteit.is_actief(drempel_seconden=300, idle_fn=lambda: 10.0) is True


def test_is_actief_niet_bij_lange_inactiviteit():
    """Inactiviteit ruim boven de drempel betekent dat er niemand is."""

    assert pc_activiteit.is_actief(drempel_seconden=300, idle_fn=lambda: 400.0) is False


def test_is_actief_grens_is_strak():
    """Precies op de drempel telt als niet meer actief (< in plaats van <=)."""

    assert pc_activiteit.is_actief(drempel_seconden=300, idle_fn=lambda: 300.0) is False


def test_is_actief_onbekend_bij_geen_meting():
    """Zonder meting is het antwoord ``None`` en niet ``False``."""

    assert pc_activiteit.is_actief(idle_fn=lambda: None) is None


def test_is_actief_onbekend_bij_ongeldige_waarde():
    """Een onleesbare meting levert ``None`` op, geen fout."""

    assert pc_activiteit.is_actief(drempel_seconden=300, idle_fn=lambda: "onzin") is None


def test_is_actief_gebruikt_standaard_drempel(monkeypatch):
    """Zonder eigen drempel wordt de configuratiewaarde gebruikt."""

    monkeypatch.setattr(pc_activiteit, "PC_IDLE_DREMPEL_SECONDEN", 60)
    assert pc_activiteit.is_actief(idle_fn=lambda: 30.0) is True
    assert pc_activiteit.is_actief(idle_fn=lambda: 90.0) is False


def test_is_actief_zonder_idle_fn(monkeypatch):
    """Zonder eigen ``idle_fn`` wordt de echte meting aangeroepen."""

    monkeypatch.setattr(pc_activiteit, "idle_seconden", lambda: 5.0)
    assert pc_activiteit.is_actief(drempel_seconden=300) is True


def test_idle_seconden_geeft_none_bij_fout(monkeypatch):
    """Als de systeem-API niet beschikbaar is, geeft meten ``None``."""

    import ctypes

    monkeypatch.setattr(ctypes, "windll", None, raising=False)
    assert pc_activiteit.idle_seconden() is None


# ---------------------------------------------------------------
# auto-slaap
# ---------------------------------------------------------------

def test_auto_slaap_zonder_activiteitsbron(tmp_path):
    """Zonder pc-meting blijft JARVIS wakker, ook na lange stilte."""

    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(tmp_path, klok, [], inactiviteit_seconden=100)

    engine.tick()
    klok.vooruit(500)
    engine.tick()

    assert engine.is_auto_slaap() is False
    assert proactive.is_quiet() is False


def test_auto_slaap_na_inactiviteit(tmp_path):
    """Na de inactiviteitsdrempel gaat de stille modus automatisch aan."""

    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(
        tmp_path,
        klok,
        [],
        actief_check_fn=lambda: False,
        inactiviteit_seconden=100,
    )

    engine.tick()
    klok.vooruit(150)
    engine.tick()

    assert engine.is_auto_slaap() is True
    assert proactive.is_quiet() is True


def test_auto_slaap_voor_nog_niet_voldoende_inactiviteit(tmp_path):
    """Binnen de drempel blijft alles gewoon aan."""

    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(
        tmp_path,
        klok,
        [],
        actief_check_fn=lambda: False,
        inactiviteit_seconden=100,
    )

    engine.tick()
    klok.vooruit(99)
    engine.tick()

    assert engine.is_auto_slaap() is False
    assert proactive.is_quiet() is False


def test_auto_slaap_wordt_wakker_bij_activiteit(tmp_path):
    """Een commando (meld_activiteit) zet de automatische stilte weer uit."""

    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(
        tmp_path,
        klok,
        [],
        actief_check_fn=lambda: False,
        inactiviteit_seconden=100,
    )
    engine.tick()
    klok.vooruit(150)
    engine.tick()
    assert engine.is_auto_slaap() is True

    engine.meld_activiteit()

    assert engine.is_auto_slaap() is False
    assert proactive.is_quiet() is False


def test_pc_gebruik_voorkomt_auto_slaap(tmp_path):
    """Zolang de pc actief is, wordt de inactiviteitsklok steeds bijgewerkt."""

    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(
        tmp_path,
        klok,
        [],
        actief_check_fn=lambda: True,
        inactiviteit_seconden=100,
    )

    engine.tick()
    klok.vooruit(500)
    engine.tick()

    assert engine.is_auto_slaap() is False
    assert proactive.is_quiet() is False
    assert engine._actief_sinds == 0.0


def test_handmatige_stille_modus_blijft_staan(tmp_path):
    """Auto-slaap grijpt niet in op een zelf aangezette stille modus."""

    proactive.set_quiet(True)
    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(
        tmp_path,
        klok,
        [],
        actief_check_fn=lambda: False,
        inactiviteit_seconden=100,
    )

    engine.tick()
    klok.vooruit(500)
    engine.tick()

    # Wij zetten alleen uit wat wij zelf aanzetten: dit was handmatig.
    assert engine.is_auto_slaap() is False
    assert proactive.is_quiet() is True


def test_auto_slaap_uit_bij_nul_drempel(tmp_path):
    """Een drempel van nistelt uit: dan wordt er nooit stilgezet."""

    klok = FakeKlok(ts=0.0)
    engine = _maak_engine(
        tmp_path,
        klok,
        [],
        actief_check_fn=lambda: False,
        inactiviteit_seconden=0,
    )

    engine.tick()
    klok.vooruit(10_000)
    engine.tick()

    assert engine.is_auto_slaap() is False
    assert proactive.is_quiet() is False


# ---------------------------------------------------------------
# 'actief'-trigger (zorg-coaching)
# ---------------------------------------------------------------

def test_actief_regel_meldt_na_te_lang_zitten(tmp_path):
    """Een zorgregel gaat af zodra de pc lang genoeg aaneengesloten actief was."""

    klok = FakeKlok(ts=0.0)
    geleverd = []

    def _lever(tekst):
        geleverd.append(tekst)
        return True

    regels = [
        {
            "id": "pauze",
            "actief": True,
            "trigger": {
                "type": "actief",
                "minuten": 90,
                "herhaal_seconden": 3600,
            },
            "melding": "U zit al anderhalf uur achter de pc; even pauze.",
        }
    ]
    engine = _maak_engine(
        tmp_path,
        klok,
        regels,
        lever_fn=_lever,
        actief_check_fn=lambda: True,
        inactiviteit_seconden=100_000,
    )

    # Nog geen 90 minuten: geen melding.
    engine.tick()
    klok.vooruit(5_000)
    engine.tick()
    assert geleverd == []

    # Voorbij de drempel: nu wel.
    klok.vooruit(500)
    engine.tick()
    assert len(geleverd) == 1
    assert "anderhalf uur" in geleverd[0].tekst


def test_actief_regel_heeft_cooldown(tmp_path):
    """Na een melding geldt een rusttijd (herhaal_seconden)."""

    klok = FakeKlok(ts=0.0)
    geleverd = []

    def _lever(tekst):
        geleverd.append(tekst)
        return True

    regels = [
        {
            "id": "pauze",
            "actief": True,
            "trigger": {
                "type": "actief",
                "seconden": 60,
                "herhaal_seconden": 3600,
            },
            "melding": "Even pauze.",
        }
    ]
    engine = _maak_engine(
        tmp_path,
        klok,
        regels,
        lever_fn=_lever,
        actief_check_fn=lambda: True,
        inactiviteit_seconden=100_000,
    )

    engine.tick()               # tellen start op ts=0
    klok.vooruit(61)
    engine.tick()               # eerste melding
    klok.vooruit(61)
    engine.tick()               # te snel na de vorige
    assert len(geleverd) == 1

    klok.vooruit(3600)
    engine.tick()               # cooldown voorbij
    assert len(geleverd) == 2


def test_actief_regel_stopt_bij_onbekende_activiteit(tmp_path):
    """Onbekende pc-status (``None``) start de telling niet."""

    klok = FakeKlok(ts=0.0)
    geleverd = []

    regels = [
        {
            "id": "pauze",
            "actief": True,
            "trigger": {"type": "actief", "seconden": 60},
            "melding": "Even pauze.",
        }
    ]
    engine = _maak_engine(
        tmp_path,
        klok,
        regels,
        lever_fn=lambda t: geleverd.append(t) or True,
        actief_check_fn=lambda: None,
        inactiviteit_seconden=100_000,
    )

    engine.tick()
    klok.vooruit(600)
    engine.tick()

    assert engine._actief_sinds is None
    assert geleverd == []


# ---------------------------------------------------------------
# dagstart / dagafsluiting (alleen op aanvraag)
# ---------------------------------------------------------------

def _fake_weer(monkeypatch):
    """Vervangt het echte weerbericht door een vaste tekst."""

    import actions.web

    monkeypatch.setattr(actions.web, "get_weather", lambda plaats: {"plaats": plaats})
    monkeypatch.setattr(actions.web, "format_weather", lambda data: "Het is 12 graden.")


def _geen_ha(monkeypatch):
    """Voorkomt dat een echte Home Assistant-config de test beïnvloedt."""

    import core.home_assistant as ha

    monkeypatch.setattr(ha, "_config_ok", lambda: False)


def test_dagstart_toont_timers_en_weer(monkeypatch):
    """De dagstart groet, toont het weer en de openstaande herinneringen."""

    from config import USER_NAME
    from core.proactive_commands import _dagstart_tekst

    _fake_weer(monkeypatch)
    _geen_ha(monkeypatch)
    timers_module.get_store().zet("wandelen", 30 * 60)

    tekst = _dagstart_tekst()

    assert USER_NAME in tekst
    assert "Het is 12 graden." in tekst
    assert "wandelen" in tekst
    assert "openstaande herinnering" in tekst


def test_dagstart_zonder_timers(monkeypatch):
    """Zonder timers zegt hij dat er niets openstaat."""

    from core.proactive_commands import _dagstart_tekst

    _fake_weer(monkeypatch)
    _geen_ha(monkeypatch)

    assert "geen openstaande herinneringen" in _dagstart_tekst()


def test_dagstart_groet_is_tijdafhankelijk(monkeypatch):
    """Overdag volgt de groet het tijdstip (goedemorgen/-middag/-avond)."""

    from core import proactive_commands as pc
    from core.proactive_commands import _dagstart_tekst

    _fake_weer(monkeypatch)
    _geen_ha(monkeypatch)
    monkeypatch.setattr(pc, "datetime", type("FakeDatum", (), {
        "now": staticmethod(lambda: datetime(2026, 3, 2, 7, 0)),
    }))

    assert _dagstart_tekst().startswith("Goedemorgen,")


def test_dagafsluiting_met_timer(monkeypatch):
    """De dagafsluiting noemt wat er nog openstaat en sluit vriendelijk af."""

    from config import USER_NAME
    from core.proactive_commands import _dagafsluiting_tekst

    _geen_ha(monkeypatch)
    timers_module.get_store().zet("wandelen", 30 * 60)

    tekst = _dagafsluiting_tekst()

    assert "U hebt nog 1 openstaande herinnering: wandelen." in tekst
    assert f"De dag zit erop, {USER_NAME}." in tekst


def test_dagafsluiting_zonder_timers(monkeypatch):
    """Zonder timers alleen het afsluitende woord."""

    from config import USER_NAME
    from core.proactive_commands import _dagafsluiting_tekst

    tekst = _dagafsluiting_tekst()

    assert "openstaande" not in tekst
    assert f"De dag zit erop, {USER_NAME}." in tekst


def test_patronen_herkennen_commando_s():
    """De commandopatronen herkennen de vragen die de gebruiker kan stellen."""

    assert _DAGSTART_PATROON.search("goedemorgen")
    assert _DAGSTART_PATROON.search("wat staat er vandaag")
    assert _DAGSTART_PATROON.search("start mijn dag")
    assert _DAGAFSLUITING_PATROON.search("sluit de dag af")
    assert _DAGAFSLUITING_PATROON.search("goede nacht")
    assert _DAGAFSLUITING_PATROON.search("dagafsluiting")

    assert not _DAGSTART_PATROON.search("wat is het weer")
    assert not _DAGAFSLUITING_PATROON.search("ga slapen")


def test_commando_dagstart_geeft_tekst(monkeypatch):
    """Het commando levert direct een samenvatting op (geen aparte tijdregel)."""

    _fake_weer(monkeypatch)
    _geen_ha(monkeypatch)

    antwoord = try_proactive_command("wat staat er vandaag")

    assert isinstance(antwoord, str)
    assert antwoord


def test_commando_dagafsluiting_geeft_tekst(monkeypatch):
    """Ook de afsluiting werkt op aanvraag en niet automatisch."""

    _geen_ha(monkeypatch)

    antwoord = try_proactive_command("sluit de dag af")

    assert isinstance(antwoord, str)
    assert "De dag zit erop" in antwoord


def test_dagstart_regeltjes_staan_niet_in_regelbestand():
    """Dagstart/dagafsluiting zijn bewust geen automatische tijdregels."""

    from core.proactive import RULES_FILE

    with open(RULES_FILE, encoding="utf-8") as bestand:
        regels = json.load(bestand)["regels"]

    assert regels, "het regelbestand hoort regels te hebben"
    for regel in regels:
        regel_tekst = json.dumps(regel, ensure_ascii=False).lower()
        assert "dagstart" not in regel_tekst
        assert "dagafsluiting" not in regel_tekst
        assert "goedemorgen" not in regel_tekst


def test_ongerelateerd_commando_blijft_none():
    """Andere commando's blijft de proactieve laag met rust."""

    assert try_proactive_command("wat is het weer") is None
    assert try_proactive_command("speel muziek") is None
