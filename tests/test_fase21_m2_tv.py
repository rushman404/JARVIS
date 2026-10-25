"""Fase 21, M2 — de tv bedienen met de stem."""

import pytest

from core import filmmodus, tv_bediening
from core.filmmodus import FilmModus
from core.tv_bediening import TvBediening, herken, zoek_bron

TV = "media_player.lg_webos_tv"
KNOP = "button.wake_on_lan_tv"
BRONNEN = ["Disney+", "HDMI 1", "HDMI 2", "Live TV", "Netflix", "Prime Video", "YouTube"]


class NepTv:
    def __init__(self, aan=True, volume=0.3, met_volume=True, werkt=True):
        self.aan = aan
        self.volume = volume
        self.met_volume = met_volume
        self.werkt = werkt
        self.bron = "Live TV"
        self.gedempt = False
        self.diensten = []

    def staten(self):
        return []

    def staat(self, entity_id):
        attrs = {"source_list": BRONNEN, "source": self.bron}
        if self.met_volume:
            attrs["volume_level"] = self.volume
        return {"entity_id": entity_id, "state": "on" if self.aan else "off", "attributes": attrs}

    def dienst(self, domein, dienst, data):
        self.diensten.append((domein, dienst, dict(data)))
        if not self.werkt:
            return False
        if dienst == "volume_set":
            self.volume = data["volume_level"]
        elif dienst == "volume_mute":
            self.gedempt = data["is_volume_muted"]
        elif dienst == "select_source":
            self.bron = data["source"]
        elif dienst == "turn_off":
            self.aan = False
        elif dienst == "press":
            self.aan = True
        return True


def _tv(**kw):
    ha = NepTv(**kw)
    film = FilmModus(ha=ha, pc_tool=lambda t, a: None, slaap=lambda s: None,
                     tv_entity=TV, tv_knop=KNOP)
    return TvBediening(film), ha


# -----------------------------------------------------------------
# Herkennen
# -----------------------------------------------------------------

@pytest.mark.parametrize("zin,verwacht", [
    ("zet de tv op 20", ("volume", "20")),
    ("zet het volume van de tv op 35 procent", ("volume", "35")),
    ("tv volume naar 10", ("volume", "10")),
    ("tv harder", ("harder", None)),
    ("zet de tv zachter", ("zachter", None)),
    ("demp de tv", ("demp", None)),
    ("tv geluid weer aan", ("ontdemp", None)),
    ("pauzeer de tv", ("pauze", None)),
    ("zet de tv op pauze", ("pauze", None)),
    ("speel de tv verder", ("verder", None)),
    ("volgende aflevering", ("volgende", None)),
    ("JARVIS, start de volgende aflevering", ("volgende", None)),
    ("open YouTube op de tv", ("app", "youtube")),
    ("schakel de tv naar HDMI 1", ("app", "hdmi 1")),
    ("zet de tv uit", ("uit", None)),
    ("zet de tv aan", ("aan", None)),
])
def test_herkent(zin, verwacht):
    assert herken(zin, film_aan=False) == verwacht


@pytest.mark.parametrize("zin", ["zet de tv op disney+", "zet netflix op de tv", "pauze",
                                 "speel verder", "zet het volume op 20", "zet de lamp uit"])
def test_niet_voor_de_tv_zonder_film(zin):
    # De eerste twee zijn de film-modus (M1); de rest blijft de pc of HA.
    assert herken(zin, film_aan=False) is None


def test_korte_zinnen_alleen_tijdens_de_film():
    assert herken("pauze", film_aan=True) == ("pauze", None)
    assert herken("speel verder", film_aan=True) == ("verder", None)
    assert herken("hervat de film", film_aan=True) == ("verder", None)
    assert herken("zet het volume op 20", film_aan=True) is None


def test_zoek_bron():
    assert zoek_bron("disney plus", BRONNEN) == "Disney+"
    assert zoek_bron("hdmi 2", BRONNEN) == "HDMI 2"
    assert zoek_bron("live tv", BRONNEN) == "Live TV"
    assert zoek_bron("you tube", BRONNEN) == "YouTube"
    assert zoek_bron("videoland", BRONNEN) is None


# -----------------------------------------------------------------
# Uitvoeren
# -----------------------------------------------------------------

def test_volume():
    tv, ha = _tv()
    assert tv.voer_uit("volume", "20") == "Tv-volume op 20."
    assert ha.diensten[-1] == ("media_player", "volume_set", {"entity_id": TV, "volume_level": 0.2})
    assert tv.voer_uit("volume", "250") == "Tv-volume op 100."


def test_harder_en_zachter():
    tv, ha = _tv(volume=0.3)
    assert tv.voer_uit("harder") == "Tv-volume op 35."
    assert tv.voer_uit("zachter") == "Tv-volume op 30."
    tv, ha = _tv(met_volume=False)
    assert tv.voer_uit("harder") == "Tv harder."
    assert ha.diensten[-1][1] == "volume_up"


def test_dempen_pauze_verder():
    tv, ha = _tv()
    assert tv.voer_uit("demp") == "Tv gedempt." and ha.gedempt is True
    assert tv.voer_uit("ontdemp") == "Tv-geluid staat weer aan." and ha.gedempt is False
    assert tv.voer_uit("pauze") == "Tv gepauzeerd."
    assert tv.voer_uit("verder") == "Tv speelt verder."
    assert [d[1] for d in ha.diensten[-2:]] == ["media_pause", "media_play"]


def test_volgende_aflevering():
    tv, ha = _tv()
    assert tv.voer_uit("volgende") == "Volgende aflevering, sir."
    assert ha.diensten[-1] == ("webostv", "button", {"entity_id": TV, "button": "ENTER"})


def test_app_openen():
    tv, ha = _tv()
    assert tv.voer_uit("app", "youtube") == "YouTube op de tv."
    assert tv.voer_uit("app", "hdmi 1") == "HDMI 1 op de tv."
    assert tv.voer_uit("app", "videoland") == "Videoland vind ik niet op de tv, sir."


def test_aan_en_uit():
    tv, ha = _tv(aan=False)
    assert tv.voer_uit("pauze") == "De tv staat uit, sir."
    assert tv.voer_uit("aan") == "Tv staat aan."
    assert ("button", "press", {"entity_id": KNOP}) in ha.diensten
    assert tv.voer_uit("aan") == "De tv staat al aan, sir."
    assert tv.voer_uit("uit") == "Tv uit." and ha.aan is False


def test_geen_tv_valt_terug_op_ha():
    film = FilmModus(ha=NepTv(), pc_tool=lambda t, a: None, slaap=lambda s: None)
    assert TvBediening(film).voer_uit("uit") is None


def test_mislukt():
    tv, _ = _tv(werkt=False)
    assert tv.voer_uit("pauze") == "Dat lukte niet op de tv, sir."


def test_nooit_licht():
    tv, ha = _tv()
    for soort, waarde in (("volume", "20"), ("demp", None), ("app", "netflix"), ("uit", None)):
        tv.voer_uit(soort, waarde)
    assert not [d for d in ha.diensten if d[0] in ("light", "cover", "scene")]


# -----------------------------------------------------------------
# Koppeling en HA-mogelijkheden
# -----------------------------------------------------------------

def test_brein_routeert_naar_de_tv(monkeypatch):
    from core import brain

    gezien = []
    monkeypatch.setattr(tv_bediening, "TvBediening",
                        lambda: type("N", (), {"voer_uit": lambda self, s, w=None: gezien.append((s, w)) or "ok"})())
    monkeypatch.setattr(filmmodus, "lees_toestand", lambda pad=None: None)
    assert brain.process_command("zet de tv op 20") == "ok"
    assert brain.process_command("volgende aflevering") == "ok"
    assert gezien == [("volume", "20"), ("volgende", None)]


def test_mediaspeler_bits_kloppen():
    """De echte bits van Home Assistant (de LG geeft 24509)."""

    from core.ha_registry import _extract_capabilities as registry_caps
    from core.home_assistant import _extract_capabilities

    caps = _extract_capabilities({"supported_features": 24509}, "media_player")
    for cap in ("pause", "play", "volume_set", "volume_mute", "previous", "next",
                "turn_on", "turn_off", "volume_up", "volume_down", "select_source", "stop"):
        assert cap in caps, cap
    assert "seek" not in caps
    reg = registry_caps({"supported_features": 24509}, "media_player")
    assert {"turn_off", "select_source", "volume_set", "stop"} <= set(reg)
