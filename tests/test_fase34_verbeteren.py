"""Fase 34 — "nee, ik bedoelde…" (terugdraaien, goed doen, onthouden) en de kon-niet-lijst."""

from pathlib import Path

import pytest

from core import brain, verbeteren, vervolg

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def keten(monkeypatch):
    """Een nep-brein: "open X" opent X (genoteerd), de rest wordt alleen gelogd."""

    uitgevoerd = []
    teruggedraaid = []

    def verwerk(commando):
        uitgevoerd.append(commando)
        if commando.startswith("open "):
            naam = commando[5:]
            verbeteren.noteer_actie("app", naam, ("close_program", {"program": naam}), f"{naam} weer gesloten")
            return f"Ik open {naam}."
        return f"Gedaan: {commando}."

    def beurt(zin):
        verbeteren.begin_beurt(zin)
        try:
            return verbeteren.probeer_commando(zin, verwerk, uitvoer=lambda t, a: teruggedraaid.append((t, a))) \
                or verwerk(verbeteren.vervang(zin))
        finally:
            verbeteren.einde_beurt()

    return beurt, uitgevoerd, teruggedraaid


# ---------------------------------------------------------------------
# M1 — herkennen en het goede commando
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin,verwacht", [
    ("nee, ik bedoelde discord", ("bedoelde", "discord")),
    ("Nee ik bedoel Discord.", ("bedoelde", "discord")),
    ("ik bedoelde eigenlijk de slaapkamer", ("bedoelde", "de slaapkamer")),
    ("nee, discord", ("nee", "discord")),
    ("nee niet spotify maar discord", ("nee", "discord")),
    ("verkeerde app", ("fout", None)),
    ("dat is fout", ("fout", None)),
    ("nee, dat bedoelde ik niet", ("fout", None)),
    ("nee, dank je", None),
    ("nee laat maar", None),
    ("open discord", None),
    ("ik bedoelde niks", None),
])
def test_herken(zin, verwacht):
    assert verbeteren.herken(zin) == verwacht


@pytest.mark.parametrize("vorige,bedoeld,verwacht", [
    ("open de kaart", "discord", "open discord"),
    ("zet de lamp in de woonkamer aan", "de slaapkamer", "zet de slaapkamer aan"),
    ("zet de lamp aan", "de bureaulamp uit", "zet de bureaulamp uit"),
    ("open discord", "sluit spotify", "sluit spotify"),
    ("hoe laat is het", "in tokio", "in tokio"),
])
def test_nieuw_commando(vorige, bedoeld, verwacht):
    assert verbeteren.nieuw_commando(vorige, bedoeld) == verwacht


# ---------------------------------------------------------------------
# M1 + M2 — verbeteren, terugdraaien en onthouden
# ---------------------------------------------------------------------

def test_nee_ik_bedoelde_draait_terug_doet_het_goede_en_onthoudt(keten):
    beurt, uitgevoerd, teruggedraaid = keten
    assert beurt("open de kaart") == "Ik open de kaart."
    antwoord = beurt("nee, ik bedoelde discord")
    assert teruggedraaid == [("close_program", {"program": "de kaart"})]
    assert uitgevoerd[-1] == "open discord"
    assert antwoord == "Ik heb de kaart weer gesloten. Ik open discord."
    assert verbeteren.verbeteringen()[0]["commando"] == "open discord"
    # Voortaan meteen goed.
    assert beurt("open de kaart") == "Ik open discord."


def test_terug_naar_zichzelf_vergeet_de_regel(keten):
    beurt, uitgevoerd, _ = keten
    beurt("open de kaart")
    beurt("nee, ik bedoelde discord")
    assert beurt("nee ik bedoelde de kaart") == "Ik heb discord weer gesloten. Ik open de kaart."
    assert verbeteren.verbeteringen() == []


def test_tweede_verbetering_hoort_bij_de_oorspronkelijke_zin(keten):
    beurt, _, _ = keten
    beurt("open de kaart")
    beurt("nee, ik bedoelde discord")
    beurt("nee, ik bedoelde spotify")
    rijen = verbeteren.verbeteringen()
    assert len(rijen) == 1 and rijen[0]["commando"] == "open spotify"


def test_fout_draait_terug_en_vraagt(keten):
    beurt, uitgevoerd, teruggedraaid = keten
    beurt("open de kaart")
    assert beurt("verkeerde app") == "Ik heb de kaart weer gesloten. Wat bedoelde u, sir?"
    assert teruggedraaid and vervolg.open_vraag() is not None
    verbeteren.begin_beurt("discord")
    try:
        antwoord = vervolg.beantwoord("discord", lambda c: pytest.fail("geen sjabloon"))
    finally:
        verbeteren.einde_beurt()
    assert antwoord == "Ik open discord." and uitgevoerd[-1] == "open discord"
    assert len(teruggedraaid) == 1  # niet twee keer terugdraaien
    assert verbeteren.verbeteringen()[0]["zin"] == "open de kaart"


def test_na_de_minuut_geen_verbetering(keten):
    beurt, _, _ = keten
    verbeteren.begin_beurt("open de kaart", nu=0.0)
    verbeteren.noteer_actie("app", "de kaart", ("close_program", {"program": "de kaart"}))
    verbeteren.einde_beurt(nu=0.0)
    assert verbeteren._vorige(nu=verbeteren.VENSTER + 1) is None
    assert verbeteren.probeer_commando("nee, ik bedoelde discord", lambda c: c) is None


def test_nee_x_zonder_actie_is_geen_verbetering(keten):
    beurt, uitgevoerd, _ = keten
    beurt("hoe laat is het")
    assert verbeteren.probeer_commando("nee, discord", lambda c: c) is None


def test_zonder_vorige_beurt_niets():
    assert verbeteren.probeer_commando("nee, ik bedoelde discord", lambda c: c) is None


def test_routine_binnen_een_beurt():
    assert verbeteren.begin_beurt("goedemorgen") is True
    assert verbeteren.begin_beurt("open spotify") is False  # binnen de routine
    verbeteren.einde_beurt()


def test_vergeet_met_de_stem(keten):
    beurt, _, _ = keten
    beurt("open de kaart")
    beurt("nee, ik bedoelde discord")
    assert "Vergeten" in verbeteren.probeer_beheer("vergeet die verbetering")
    assert verbeteren.verbeteringen() == []
    assert verbeteren.probeer_beheer("vergeet alle verbeteringen").startswith("Ik ben 0")
    assert verbeteren.probeer_beheer("open discord") is None


# ---------------------------------------------------------------------
# Acties noteren
# ---------------------------------------------------------------------

def test_open_program_tool_noteert_alleen_echt_openen(monkeypatch):
    from core import tools

    monkeypatch.setattr(tools, "open_program", lambda p: f"Ik open {p}.")
    verbeteren.begin_beurt("open discord")
    tools.open_program_tool("Discord")
    monkeypatch.setattr(tools, "open_program", lambda p: f"{p} stond al open en staat nu vooraan.")
    tools.open_program_tool("Spotify")
    acties = verbeteren._beurt["huidig"]["acties"]
    verbeteren.einde_beurt()
    assert [a["doel"] for a in acties] == ["Discord"]
    assert acties[0]["terug"] == ("close_program", {"program": "Discord"})


def test_game_pc_open_noteert(monkeypatch):
    from core import tool_registry

    verbeteren.begin_beurt("open discord op de game-pc")
    tool_registry._noteer_voor_verbeteren("game_pc_open_program", {"program": "Discord"}, "Ik open Discord.")
    tool_registry._noteer_voor_verbeteren("game_pc_close_program", {"program": "Discord"}, "Ik sluit Discord.")
    acties = verbeteren._beurt["huidig"]["acties"]
    verbeteren.einde_beurt()
    assert [a["terug"][0] for a in acties] == ["game_pc_close_program"]


def test_lamp_noteert_alleen_als_hij_anders_stond():
    from core import home_assistant as ha

    verbeteren.begin_beurt("zet de lamp aan")
    # Sinds Fase 35B: (domein, entity, naam, service, service_data, vorige stand).
    ha._noteer_verbeteren("light", "light.bureau", "Bureaulamp", "turn_on", None, {"state": "off"})
    ha._noteer_verbeteren("light", "light.bank", "Banklamp", "turn_on", None, {"state": "on"})
    ha._noteer_verbeteren("media_player", "media_player.tv", "Tv", "turn_on", None, {"state": "off"})
    acties = verbeteren._beurt["huidig"]["acties"]
    verbeteren.einde_beurt()
    assert [a["doel"] for a in acties] == ["Bureaulamp"]
    assert acties[0]["terug"][1]["service"] == "turn_off"
    assert acties[0]["beschrijving"] == "Bureaulamp weer uitgezet"


def test_terugdraaien_fout_breekt_niets():
    beurt = {"acties": [{"doel": "x", "terug": ("close_program", {"program": "x"}), "beschrijving": "x"}]}

    def kapot(t, a):
        raise RuntimeError("weg")

    assert verbeteren.draai_terug(beurt, kapot) == []


# ---------------------------------------------------------------------
# In het echte brein
# ---------------------------------------------------------------------

def test_in_process_command(monkeypatch):
    geopend, gesloten = [], []

    def open_(naam, *a, **k):
        geopend.append(naam)
        verbeteren.noteer_actie("app", naam, ("close_program", {"program": naam}), f"{naam} weer gesloten")
        return f"Ik open {naam}."

    monkeypatch.setattr(brain, "try_open_program",
                        lambda c: open_(c[5:]) if c.startswith("open ") else None)
    monkeypatch.setattr(verbeteren, "_standaard_uitvoer", lambda t, a: gesloten.append(a["program"]))
    assert brain.process_command("open de kaart") == "Ik open de kaart."
    antwoord = brain.process_command("nee, ik bedoelde discord")
    assert gesloten == ["de kaart"] and geopend[-1] == "discord"
    assert "discord" in antwoord.lower()
    assert brain.process_command("open de kaart") == "Ik open discord."


# ---------------------------------------------------------------------
# M3 — kon-niet-lijst
# ---------------------------------------------------------------------

@pytest.mark.parametrize("antwoord,verwacht", [
    ("Dat kan ik nog niet, sir. Ik kan wel een mail sturen.", True),
    ("Daar heb ik geen functie voor.", True),
    ("Ik heb geen toegang tot WhatsApp.", True),
    ("Het is 14:05.", False),
    ("Ik open Discord.", False),
])
def test_kon_niet_herkennen(antwoord, verwacht):
    assert verbeteren.kon_niet(antwoord) is verwacht


def test_noteer_kon_niet_soort_en_samenvoegen():
    assert verbeteren.noteer_kon_niet("stuur een whatsapp naar mam", samenvatter=lambda z: "WhatsApp-bericht sturen")
    verbeteren.noteer_kon_niet("app mijn vriend", samenvatter=lambda z: "Whatsapp-bericht sturen.")
    lijst = verbeteren.kon_niet_lijst()
    assert lijst == [{"soort": "WhatsApp-bericht sturen", "keer": 2, "laatst": lijst[0]["laatst"]}]
    assert "mam" not in str(lijst)


def test_kon_niet_nooit_de_letterlijke_zin():
    zin = "stuur een whatsapp naar mam"
    assert verbeteren.noteer_kon_niet(zin, samenvatter=lambda z: "stuur een whatsapp") is None
    assert verbeteren.noteer_kon_niet(zin, samenvatter=lambda z: "") is None

    def kapot(z):
        raise RuntimeError("ollama weg")

    assert verbeteren.noteer_kon_niet(zin, samenvatter=kapot) is None
    assert verbeteren.kon_niet_lijst() == []


def test_na_beurt_alleen_als_niets_gebeurde(monkeypatch):
    gezien = []
    monkeypatch.setattr(verbeteren, "noteer_kon_niet", lambda zin: gezien.append(zin))
    verbeteren.na_beurt("stuur een whatsapp", "Dat kan ik nog niet, sir.", achtergrond=False)
    verbeteren.na_beurt("hoe laat", "Het is 14:05.", achtergrond=False)
    verbeteren.begin_beurt("open x")
    verbeteren.noteer_actie("app", "x", None)
    verbeteren.na_beurt("open x", "Dat kan ik nog niet.", achtergrond=False)
    verbeteren.einde_beurt()
    assert gezien == ["stuur een whatsapp"]


def test_ai_instructie_zegt_dat_kan_ik_nog_niet():
    assert 'begin dan met "Dat kan ik nog niet"' in (ROOT / "core" / "ai.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# iPad
# ---------------------------------------------------------------------

def test_dashboard_api():
    from dashboard.api import DashboardAPI

    verbeteren.leer("open de kaart", "open discord")
    verbeteren.noteer_kon_niet("x", samenvatter=lambda z: "Pakket volgen")
    api = DashboardAPI(audit_fn=lambda **k: None)
    status, data = api.verbeteren()
    assert status == 200 and data["verbeteringen"][0]["commando"] == "open discord"
    assert data["kon_niet"][0]["soort"] == "Pakket volgen"
    status, data = api.verbeteren_actie({"actie": "vergeet", "zin": "open de kaart"})
    assert status == 200 and data["verbeteringen"] == []
    status, data = api.verbeteren_actie({"actie": "wis_kon_niet", "soort": "Pakket volgen"})
    assert data["kon_niet"] == []
    assert api.verbeteren_actie({"actie": "sloop"})[0] == 400
    assert api.verbeteren_actie(None)[0] == 400


def test_dashboard_aansluiting():
    server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("GET", "/api/verbeteren"): (k,' in server and '("POST", "/api/verbeteren"): (b,' in server
    html = (ROOT / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="instVerbeteringen"' in html and 'id="instKonNiet"' in html
    git = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "memory/verbeteringen.json" in git and "memory/kon_niet.json" in git


def test_gericht_ziet_verbetering_als_voor_jarvis(keten):
    from core import gericht

    beurt, _, _ = keten
    assert gericht.regels("nee, ik bedoelde discord") == gericht.TWIJFEL  # nog geen opdracht
    beurt("open de kaart")
    assert gericht.regels("nee, ik bedoelde discord") == gericht.VOOR_JARVIS
    assert gericht.regels("verkeerde app") == gericht.VOOR_JARVIS
