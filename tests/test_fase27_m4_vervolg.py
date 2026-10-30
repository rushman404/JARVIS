"""Fase 27, M4 — vervolgvragen: het antwoord op JARVIS' eigen wedervraag.

Melding 2026-10-30: "zet een deadline verslag" -> "Wanneer moet dit af?" ->
"morgen om 10 uur" werd een losse zin; "zet uit eten" sloot het
programma "eten". Elke plek met een wedervraag zet nu een open vraag klaar.

Er wordt nooit iets echt uitgevoerd: agenda, programma's en slim huis zijn nep.
"""

import time

import pytest

import core.brain as brain
from core import confirmation, icloud_agenda, vervolg


@pytest.fixture(autouse=True)
def schoon(monkeypatch):
    monkeypatch.setattr(icloud_agenda, "is_ingesteld", lambda: True)
    monkeypatch.setattr(brain, "ask_ai", lambda *a, **k: "AI-ANTWOORD")
    # Nooit echte acties: programma's, slim huis en tools zijn nep.
    monkeypatch.setattr(brain, "close_program_tool", lambda naam: f"SLUIT {naam}")
    monkeypatch.setattr(brain, "try_home_assistant", lambda c: "HA" if "lamp" in c else None)
    confirmation.clear_pending()
    yield
    confirmation.clear_pending()


def _zeg(*zinnen):
    antwoorden = [brain.process_command(z) for z in zinnen]
    return antwoorden[-1]


# ---------------------------------------------------------------------
# Het gemelde voorbeeld
# ---------------------------------------------------------------------

def test_deadline_wanneer_wordt_aangevuld():
    assert _zeg("zet een deadline verslag") == "Wanneer moet verslag af, sir?"
    vraag = _zeg("morgen om 10 uur")
    assert vraag.startswith("Deadline toevoegen: verslag, morgen")
    assert "van 10:00 tot 10:15" in vraag
    assert confirmation.get_pending()["afspraak"]["titel"] == "Deadline: Verslag"


def test_uit_eten_is_geen_sluit_opdracht():
    assert brain.has_intent("zet uit eten", brain.CLOSE_EXCLUDE_PATTERNS)
    _zeg("zet morgen om 10 uur in mijn agenda")
    vraag = _zeg("zet uit eten")
    assert vraag.startswith("Afspraak toevoegen: Uit eten, morgen")


def test_deadline_waarvoor():
    assert _zeg("deadline vrijdag") == "Waarvoor is de deadline, sir?"
    assert _zeg("verslag biologie").startswith("Deadline toevoegen: verslag biologie")


def test_deadline_alles_ontbreekt():
    assert _zeg("zet een deadline") == "Waarvoor is de deadline, en wanneer moet het af, sir?"
    assert _zeg("presentatie op maandag").startswith("Deadline toevoegen: presentatie")


def test_agenda_hoe_heet_hij():
    assert _zeg("zet morgen om 14 uur in mijn agenda") == "Hoe heet de afspraak, sir?"
    assert _zeg("tandarts").startswith("Afspraak toevoegen: Tandarts, morgen")


def test_agenda_wanneer():
    assert _zeg("zet tandarts in mijn agenda") == "Wanneer is Tandarts, sir?"
    assert _zeg("vrijdag om 9 uur").startswith("Afspraak toevoegen: Tandarts")


# ---------------------------------------------------------------------
# Een ander antwoord laat de wedervraag vervallen
# ---------------------------------------------------------------------

def test_nieuw_commando_gaat_gewoon_door():
    _zeg("zet een deadline verslag")
    assert _zeg("zet de lamp aan") == "HA"
    assert vervolg.open_vraag() is None


def test_bediening_is_geen_afspraaknaam():
    _zeg("zet morgen om 14 uur in mijn agenda")
    assert _zeg("zet de lamp aan") == "HA"
    assert confirmation.get_pending() is None


def test_vraag_is_geen_antwoord():
    _zeg("zet een deadline verslag")
    assert _zeg("wat is de hoofdstad van frankrijk") == "AI-ANTWOORD"


@pytest.mark.parametrize("zin", ["laat maar", "nee", "annuleer", "toch niet"])
def test_laat_maar(zin):
    _zeg("zet een deadline verslag")
    assert _zeg(zin) == vervolg.ANNULEER_ANTWOORD
    assert vervolg.open_vraag() is None


def test_een_beurt_geldig():
    _zeg("zet een deadline verslag")
    _zeg("wat is de hoofdstad van frankrijk")
    # De wedervraag is vervallen: "morgen om 10 uur" is nu een losse zin.
    assert _zeg("morgen om 10 uur") == "AI-ANTWOORD"


def test_verloopt_na_een_minuut(monkeypatch):
    _zeg("zet een deadline verslag")
    nu = time.monotonic() + vervolg.TTL + 1
    monkeypatch.setattr(vervolg.time, "monotonic", lambda: nu)
    assert vervolg.open_vraag() is None


# ---------------------------------------------------------------------
# Programma's, mappen, scènes en Discord
# ---------------------------------------------------------------------

def test_sluiten_zonder_naam(monkeypatch):
    monkeypatch.setitem(brain.current_context, "last_program", None)
    assert _zeg("sluit") == "Welk programma wil je sluiten?"
    assert _zeg("spotify") == "SLUIT spotify."


@pytest.mark.parametrize("vraag, sjabloon, antwoord, verwacht", [
    ("Welk programma wil je openen?", "open {antwoord}", "spotify", "open spotify"),
    ("Van welk programma wil je de status weten?", "draait {antwoord}", "discord", "draait discord"),
    ("Welke naam moet de map krijgen?", "maak een map genaamd {antwoord}", "foto's 2026",
     "maak een map genaamd foto's 2026"),
    ("Welke scene wil je verwijderen?", "verwijder scene {antwoord}", "film", "verwijder scene film"),
    ("Wat wilt u Sem terugsturen, sir?", "antwoord Sem: {antwoord}", "ik kom zo", "antwoord Sem: ik kom zo"),
])
def test_sjablonen(vraag, sjabloon, antwoord, verwacht):
    controle = vervolg.TEKST if "terugsturen" in vraag else vervolg.NAAM
    vervolg.zet(vraag, sjabloon=sjabloon, controle=controle)
    uitgevoerd = []
    vervolg.beantwoord(antwoord, lambda c: uitgevoerd.append(c) or "ok")
    assert uitgevoerd == [verwacht]


def test_naam_vervolg_vanuit_brein(monkeypatch):
    vraag = brain._vervolg_naam("map", "bureaublad")
    assert vraag == "Welke naam moet de map krijgen?"
    assert vervolg.open_vraag()["sjabloon"] == "maak een map genaamd {antwoord} in bureaublad"
    brain._vervolg_naam("bestand", None, " op de game-pc")
    assert vervolg.open_vraag()["sjabloon"] == "maak een bestand genaamd {antwoord} op de game-pc"


def test_programma_vervolg_vanuit_tools():
    from core import ai

    assert ai._vervolg_programma("Welk programma wil je openen?", "open {antwoord}") == "Welk programma wil je openen?"
    assert vervolg.open_vraag()["sjabloon"] == "open {antwoord}"


def test_discord_vervolg():
    from core import discord_dms

    class Klant:
        def dms(self):
            return []

    assert discord_dms.antwoord(Klant(), "Sem", "") == "Wat wilt u Sem terugsturen, sir?"
    assert vervolg.open_vraag()["sjabloon"] == "antwoord Sem: {antwoord}"


# ---------------------------------------------------------------------
# Wat past bij welke vraag
# ---------------------------------------------------------------------

@pytest.mark.parametrize("tekst, controle, verwacht", [
    ("morgen om 10 uur", vervolg.MOMENT, True),
    ("vrijdag", vervolg.MOMENT, True),
    ("om half drie", vervolg.MOMENT, True),
    ("zet uit eten", vervolg.MOMENT, False),
    ("geen idee eigenlijk", vervolg.MOMENT, False),
    ("spotify", vervolg.NAAM, True),
    ("euro truck simulator 2", vervolg.NAAM, True),
    ("open spotify", vervolg.NAAM, False),
    ("wat is het weer", vervolg.NAAM, False),
    ("verslag op vrijdag", vervolg.ZIN, True),
    ("zet de lamp aan", vervolg.ZIN, False),
    ("ik kom zo, wacht even", vervolg.TEKST, True),
    ("", vervolg.TEKST, False),
])
def test_past(tekst, controle, verwacht):
    assert vervolg.past(tekst, controle) is verwacht


@pytest.mark.parametrize("tekst, verwacht", [
    ("zet uit eten", "uit eten"),
    ("noteer tandarts", "tandarts"),
    ("zet er maar een afspraak tandarts", "tandarts"),
    ("zet de lamp aan", "zet de lamp aan"),
    ("zet het volume op 50%", "zet het volume op 50%"),
    ("tandarts", "tandarts"),
])
def test_notitie_werkwoord(tekst, verwacht):
    assert vervolg._zonder_notitie_werkwoord(tekst) == verwacht


def test_zet_vraagt_sjabloon_of_verwerk():
    with pytest.raises(ValueError):
        vervolg.zet("x")
    with pytest.raises(ValueError):
        vervolg.zet("x", sjabloon="a", verwerk=lambda t: t)


# ---------------------------------------------------------------------
# De vorige beurt als context
# ---------------------------------------------------------------------

def test_vorige_beurt_wordt_onthouden():
    _zeg("zet een deadline verslag")
    assert vervolg.vorige_beurt() == ("zet een deadline verslag", "Wanneer moet verslag af, sir?")


def test_vorige_beurt_verloopt(monkeypatch):
    vervolg.onthoud_beurt("hoe is het weer morgen", "Morgen 12 graden.")
    nu = time.monotonic() + vervolg.BEURT_TTL + 1
    monkeypatch.setattr(vervolg.time, "monotonic", lambda: nu)
    assert vervolg.vorige_beurt() is None


@pytest.mark.parametrize("beurt, mag", [
    (("zoek op wie de laatste race won", "Norris won. (Bron: f1.nl)"), True),
    (("hoe is het weer morgen", "Morgen in Badhoevedorp 12 graden."), False),
    (("wat staat er in mijn agenda", "Om 14:00 de tandarts."), False),
    (("heb ik nieuwe mail", "Eén mail van school."), False),
    (None, False),
])
def test_vorige_beurt_naar_cloud(monkeypatch, beurt, mag):
    import memory.memory as mem

    monkeypatch.setattr(mem, "get_all_memory", lambda: {"woonplaats": "Badhoevedorp"})
    from core import privacy_poort

    privacy_poort._reset()
    assert vervolg.mag_naar_cloud(beurt) is mag


def test_vorige_beurt_in_lokale_berichten(monkeypatch):
    from core import ai

    monkeypatch.setattr(ai, "conversation_history", [])
    vervolg.onthoud_beurt("hoe is het weer morgen", "Morgen 12 graden en zon.")
    assert ai._vorige_beurt_lokaal() == [
        {"role": "user", "content": "hoe is het weer morgen"},
        {"role": "assistant", "content": "Morgen 12 graden en zon."},
    ]
    # Staat hij al in de geschiedenis (een gewone AI-beurt), dan niet dubbel.
    monkeypatch.setattr(ai, "conversation_history", [
        {"role": "user", "content": "hoe is het weer morgen"},
        {"role": "assistant", "content": "Morgen 12 graden en zon."},
    ])
    assert ai._vorige_beurt_lokaal() == []


def test_vorige_beurt_in_cloud_berichten():
    from core import privacy_poort

    privacy_poort._reset()
    berichten = privacy_poort.cloud_berichten(
        "wanneer was dat?", vorige_beurt=("zoek op wie de laatste race won", "Norris won."))
    assert [b["content"] for b in berichten[1:]] == ["zoek op wie de laatste race won", "Norris won.", "wanneer was dat?"]


def test_vorige_beurt_niet_dubbel_in_cloud():
    from core import privacy_poort

    privacy_poort._reset()
    privacy_poort.onthoud_cloud_beurt("wie won", "Norris.")
    berichten = privacy_poort.cloud_berichten("wanneer?", vorige_beurt=("wie won", "Norris."))
    assert [b["content"] for b in berichten[1:]] == ["wie won", "Norris.", "wanneer?"]


# ---------------------------------------------------------------------
# Fix 2026-10-30: alleen "sluit" / "open", ook op de game-pc
# ---------------------------------------------------------------------

@pytest.mark.parametrize("op_game_pc", [True, False])
def test_kaal_sluit_en_open_vragen_terug(monkeypatch, op_game_pc):
    from core import pc_target

    uitgevoerd = []
    monkeypatch.setattr(pc_target, "is_remote", lambda c: op_game_pc)
    monkeypatch.setattr(brain, "execute_tool", lambda tool, args, q: uitgevoerd.append((tool, args)) or "ok")
    monkeypatch.setattr(brain, "close_program_tool", lambda n: uitgevoerd.append(("sluit", n)) or "ok")
    monkeypatch.setattr(brain, "open_program_tool", lambda n: uitgevoerd.append(("open", n)) or "ok")
    monkeypatch.setattr(brain, "find_program", lambda n, exact_only=False: [f"C:/x/{n}.exe"])

    assert _zeg("sluit") == "Welk programma wil je sluiten?"
    _zeg("spotify")
    assert _zeg("open") == "Welk programma wil je openen?"
    _zeg("discord")
    if op_game_pc:
        assert uitgevoerd == [("game_pc_close_program", {"program": "spotify"}),
                              ("game_pc_open_program", {"program": "discord"})]
    else:
        assert uitgevoerd == [("sluit", "spotify"), ("open", "discord")]


@pytest.mark.parametrize("zin", ["sluit", "sluit het programma", "afsluiten", "open", "start een app"])
def test_kale_werkwoorden(zin):
    assert brain._KAAL_SLUITEN.match(zin) or brain._KAAL_OPENEN.match(zin)


@pytest.mark.parametrize("zin", ["stop", "sluit spotify", "open discord", "zet de muziek uit", "start valorant"])
def test_geen_kale_werkwoorden(zin):
    assert not brain._KAAL_SLUITEN.match(zin) and not brain._KAAL_OPENEN.match(zin)
