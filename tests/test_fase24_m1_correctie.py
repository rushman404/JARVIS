"""Fase 24, M1 — lokale fuzzy-match voor verkeerd gezegde of getypte commando's."""

import json

import pytest

from core import commando_correctie as cc

NAMEN = [
    "spotify", "steam", "discord", "chrome", "youtube", "valorant",
    "lamp", "lampen", "tv", "bedlamp", "woonkamer lamp",
]


def _beste(tekst, namen=NAMEN):
    kandidaten = cc.zoek_kandidaten(tekst, namen=namen)
    return kandidaten[0] if kandidaten else None


# ---------------------------------------------------------------------
# Typfouten en spraakfouten
# ---------------------------------------------------------------------

@pytest.mark.parametrize("fout, bedoeld, herkenner", [
    ("zet de lampe in de wonkamer an", "zet de lampen in de woonkamer aan", "slim_huis"),
    ("open spotfy", "open spotify", "programma_openen"),
    ("open stem", "open steam", "programma_openen"),
    ("sluit discrod", "sluit discord", "programma_sluiten"),
    ("start valorrant", "start valorant", "programma_openen"),
    ("zet de muziek zachtr", "zet de muziek zachter", "media"),
    ("vergrendl de pc", "vergrendel de pc", "pc"),
    ("opne steam", "open steam", "programma_openen"),
])
def test_typfout_wordt_bedoeld_commando(fout, bedoeld, herkenner):
    kandidaat = _beste(fout)
    assert kandidaat is not None
    assert kandidaat.commando == bedoeld
    assert kandidaat.herkenner == herkenner
    assert 70 <= kandidaat.score <= 100


def test_wijzigingen_worden_bijgehouden():
    kandidaat = _beste("zet de lampe in de wonkamer an")
    assert ("lampe", "lampen") in kandidaat.wijzigingen
    assert ("wonkamer", "woonkamer") in kandidaat.wijzigingen
    assert ("an", "aan") in kandidaat.wijzigingen


def test_opvulwoorden_weg_geeft_hoge_score():
    kandidaat = _beste("doe die tv toch uit")
    assert kandidaat.commando == "doe tv uit"
    assert kandidaat.score == 100
    assert kandidaat.wijzigingen == []


@pytest.mark.parametrize("zin, verwacht", [
    ("doe die tv toch uit", "doe tv uit"),
    ("zet ff even de lamp aan", "zet de lamp aan"),
    ("die toch", "die toch"),  # nooit leeg
])
def test_verwijder_opvulwoorden(zin, verwacht):
    assert cc.verwijder_opvulwoorden(zin) == verwacht


def test_beleefde_voorloop_blijft_staan():
    kandidaat = _beste("kun je de lampe an doen")
    assert kandidaat.commando == "kun je de lampen aan doen"
    assert kandidaat.herkenner == "slim_huis"


def test_getallen_blijven_staan():
    kandidaat = _beste("zet de tv om 50 procent an")
    assert "50" in kandidaat.commando.split()


def test_twijfel_geeft_meerdere_kandidaten():
    kandidaten = cc.zoek_kandidaten("open crave", namen=["brave", "grave"])
    assert {k.commando for k in kandidaten} == {"open brave", "open grave"}


def test_vervoegingen_zijn_geen_twijfel():
    kandidaten = cc.zoek_kandidaten("zet de lampe aan", namen=["lamp", "lampen", "lampje"])
    assert len(kandidaten) == 1


def test_maximaal_aantal_kandidaten():
    kandidaten = cc.zoek_kandidaten("open crave", namen=["brave", "grave"], max_kandidaten=1)
    assert len(kandidaten) == 1


# ---------------------------------------------------------------------
# Geen valse "bedoelde u"
# ---------------------------------------------------------------------

@pytest.mark.parametrize("vraag", [
    "wat is de hoofdstad van frankrijk",
    "waarom is de lucht blauw?",
    "hoe laat is het",
    "wie is de president van amerika",
    "vertel een grap",
    "ik heb honger",
    "kun je me vertellen hoe laat het is",
    "is de lamp aan?",
    "welke games heb ik",
    "goedemorgen",
])
def test_gewone_vragen_geen_kandidaat(vraag):
    assert cc.zoek_kandidaten(vraag, namen=NAMEN) == []


@pytest.mark.parametrize("goed", [
    "zet de lamp aan",
    "open spotify",
    "doe tv uit",
    "pauzeer de muziek",
])
def test_juist_commando_geen_kandidaat(goed):
    assert cc.zoek_kandidaten(goed, namen=NAMEN) == []


def test_korte_woorden_nooit_vaag_vervangen():
    # "sem" lijkt op "steam", maar woorden van 3 letters blijven staan.
    assert cc.zoek_kandidaten("zet sem op de lijst", namen=NAMEN) == []


def test_onbekend_woord_blijft_staan():
    assert cc.zoek_kandidaten("zet de wekker om 7 uur", namen=NAMEN) == []


@pytest.mark.parametrize("zin, verwacht", [
    ("zet de lamp aan", True),
    ("opne steam", True),
    ("tv uit", True),
    ("lampen woonkamer an", True),
    ("kun je de lamp aan doen?", True),
    ("wil je de tv uit zetten", True),
    ("wat is het weer", False),
    ("zet je dat even op?", False),
    ("", False),
    ("???", False),
])
def test_lijkt_op_commando(zin, verwacht):
    assert cc.lijkt_op_commando(zin) is verwacht


# ---------------------------------------------------------------------
# Bekende namen en voorbeelden
# ---------------------------------------------------------------------

@pytest.fixture
def lege_cache(monkeypatch):
    monkeypatch.setattr(cc, "_namen", None)
    monkeypatch.setattr(cc, "_namen_tijd", 0.0)


def test_namenbron_mag_falen(monkeypatch, lege_cache):
    def kapot():
        raise RuntimeError("HA onbereikbaar")

    monkeypatch.setattr(cc, "_ha_namen", kapot)
    monkeypatch.setattr(cc, "_startmenu_namen", lambda: {"obsidian"})
    namen = cc.bekende_namen()
    assert "obsidian" in namen
    assert "spotify" in namen  # uit de config


def test_namen_worden_gecachet(monkeypatch, lege_cache):
    aanroepen = []

    def bron():
        aanroepen.append(1)
        return {"kodi"}

    monkeypatch.setattr(cc, "_ha_namen", lambda: set())
    monkeypatch.setattr(cc, "_startmenu_namen", bron)
    cc.bekende_namen()
    cc.bekende_namen()
    assert len(aanroepen) == 1
    cc.bekende_namen(vernieuw=True)
    assert len(aanroepen) == 2


def test_ha_namen_uit_snapshot(monkeypatch):
    from core import ha_registry

    monkeypatch.setattr(ha_registry, "_load_aliases", lambda: {"light.x": ["Leeslamp"]})
    monkeypatch.setattr(ha_registry, "_config_ok", lambda: True)
    monkeypatch.setattr(ha_registry, "get_snapshot", lambda: {
        "entities": [{"name": "Plafond Lamp", "device": "Hue", "area": "Woonkamer", "aliases": ["grote lamp"]}],
        "areas": {"zolder": "Zolder"},
    })
    namen = cc._ha_namen()
    assert {"leeslamp", "plafond lamp", "hue", "woonkamer", "grote lamp", "zolder", "lamp"} <= namen


def test_voorbeelden_bestand_is_geldig():
    with open(cc.VOORBEELDEN_FILE, encoding="utf-8") as f:
        data = json.load(f)
    werkwoorden = set(data["werkwoorden"])
    assert data["herkenners"]
    for herkenner, lijst in data["herkenners"].items():
        assert lijst, herkenner
        for voorbeeld in lijst:
            # Elk voorbeeld moet zelf als commando herkend worden.
            assert cc.lijkt_op_commando(voorbeeld), voorbeeld
            assert voorbeeld.split()[0] in werkwoorden, voorbeeld
    # Korte vormen verwijzen naar woorden die een actie maken.
    assert set(data["korte_vormen"].values()) <= {"aan", "uit", "af"}
