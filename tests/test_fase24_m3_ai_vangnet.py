"""Fase 24, M3 — AI-vangnet: het taalmodel kiest het bedoelde commando.

Het model wordt hier altijd vervangen door een nep-functie; er gaat niets
naar Ollama.
"""

import json
import time

import pytest

import config
import core.ai as ai
import core.audit as audit
import core.brain as brain
from core import commando_correctie as cc
from core.confirmation import CORRECTIE_KIND, clear_pending, get_pending

NAMEN = frozenset(["spotify", "steam", "discord", "chrome", "lamp", "lampen", "tv", "riot client"])


def _model(commando, zekerheid=90):
    """Nep-model dat altijd dit JSON-antwoord geeft en de aanroepen telt."""

    def fn(berichten):
        fn.aanroepen.append(berichten)
        return json.dumps({"commando": commando, "zekerheid": zekerheid})

    fn.aanroepen = []
    return fn


@pytest.fixture(autouse=True)
def schone_staat(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONVERSATION_FILE", str(tmp_path / "conversation.json"))
    monkeypatch.setattr(audit, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(cc, "_namen", NAMEN)
    monkeypatch.setattr(cc, "_namen_tijd", time.monotonic())
    monkeypatch.setattr(config, "COMMANDO_CORRECTIE_AI", True)
    clear_pending()
    yield
    clear_pending()


# ---------------------------------------------------------------------
# ai_kandidaat
# ---------------------------------------------------------------------

def test_geldig_antwoord_wordt_kandidaat():
    model = _model("zet de muziek zachter", 88)
    k = cc.ai_kandidaat("doe die herrie ff zachter", namen=NAMEN, llm_fn=model)
    assert k.commando == "zet de muziek zachter"
    assert k.bron == "ai"
    assert k.herkenner == "media"
    assert k.score == 88
    assert k.wijzigingen == [("doe die herrie ff zachter", "zet de muziek zachter")]


def test_naam_ingevuld():
    k = cc.ai_kandidaat("open dat chat programma", namen=NAMEN, llm_fn=_model("open discord", 80))
    assert k.commando == "open discord"
    assert k.herkenner == "programma_openen"


@pytest.mark.parametrize("antwoord", [
    "Ik heb je opdracht verwerkt.",          # geen JSON (de test-stub van Ollama)
    "[]",
    json.dumps({"commando": "geen", "zekerheid": 90}),
    json.dumps({"commando": "", "zekerheid": 90}),
    json.dumps({"commando": "open {naam}", "zekerheid": 90}),
    json.dumps({"commando": "open steam", "zekerheid": "heel zeker"}),
    json.dumps({"commando": "open steam", "zekerheid": True}),
    json.dumps({"commando": ["open steam"], "zekerheid": 90}),
    json.dumps({"zekerheid": 90}),
])
def test_onbruikbaar_antwoord_geeft_niets(antwoord):
    assert cc.ai_kandidaat("open dat ding", namen=NAMEN, llm_fn=lambda b: antwoord) is None


def test_verzonnen_naam_valt_af():
    # "photoshop" staat niet in de bekende namen.
    assert cc.ai_kandidaat("open dat tekenprogramma", namen=NAMEN, llm_fn=_model("open photoshop")) is None


def test_verzonnen_commando_valt_af():
    # Alle woorden bekend, maar het lijkt op geen enkel voorbeeld.
    assert cc.ai_kandidaat("doe de tv ding", namen=NAMEN, llm_fn=_model("de tv de tv de tv")) is None


def test_zelfde_zin_terug_geeft_niets():
    assert cc.ai_kandidaat("open steam nu", namen=NAMEN, llm_fn=_model("open steam nu")) is None


def test_zekerheid_wordt_begrensd():
    k = cc.ai_kandidaat("doe die herrie ff zachter", namen=NAMEN, llm_fn=_model("zet de muziek zachter", 250))
    assert k.score <= 100


def test_gewone_vraag_roept_model_niet_aan():
    model = _model("open steam")
    assert cc.ai_kandidaat("wat is de hoofdstad van frankrijk", namen=NAMEN, llm_fn=model) is None
    assert model.aanroepen == []


def test_uitgezet_roept_model_niet_aan(monkeypatch):
    monkeypatch.setattr(config, "COMMANDO_CORRECTIE_AI", False)
    model = _model("open steam")
    assert cc.ai_kandidaat("open dat ding", namen=NAMEN, llm_fn=model) is None
    assert model.aanroepen == []


def test_tijdens_herhaling_geen_model():
    model = _model("open steam")
    with cc.herhaling():
        assert cc.ai_kandidaat("open dat ding", namen=NAMEN, llm_fn=model) is None
    assert model.aanroepen == []


def test_tijdslimiet():
    def traag(_berichten):
        time.sleep(1)
        return json.dumps({"commando": "open steam", "zekerheid": 99})

    begin = time.monotonic()
    assert cc.ai_kandidaat("open dat ding", namen=NAMEN, llm_fn=traag, timeout=0.05) is None
    assert time.monotonic() - begin < 0.5


def test_fout_van_model_geeft_niets():
    def kapot(_berichten):
        raise ConnectionError("Ollama is uit")

    assert cc.ai_kandidaat("open dat ding", namen=NAMEN, llm_fn=kapot) is None


def test_prompt_bevat_lijst_namen_en_zin():
    model = _model("open steam")
    veel_namen = NAMEN | {f"programma{i}" for i in range(200)}
    cc.ai_kandidaat("open dat spel ding", namen=veel_namen, llm_fn=model)
    systeem, gebruiker = model.aanroepen[0]
    assert systeem["role"] == "system" and "JSON" in systeem["content"]
    tekst = gebruiker["content"]
    assert "open {naam}" in tekst
    assert "pauzeer de muziek" in tekst
    assert '"open dat spel ding"' in tekst
    namen_regel = next(r for r in tekst.splitlines() if r.startswith("Namen: "))
    assert len(namen_regel[len("Namen: "):].split(", ")) <= cc.AI_MAX_NAMEN


def test_prompt_bevat_geen_geheugen_of_geschiedenis(monkeypatch):
    # Alleen de zin, de voorbeelden en namen: geen gesprek of geheugen.
    model = _model("open steam")
    cc.ai_kandidaat("open dat ding", namen=NAMEN, llm_fn=model)
    assert len(model.aanroepen[0]) == 2


# ---------------------------------------------------------------------
# Beslissen en te_vragen
# ---------------------------------------------------------------------

def test_ai_gok_is_nooit_direct():
    k = cc.Kandidaat("open chrome", 100, "programma_openen", [("open dat chat programma", "open chrome")], bron="ai")
    assert cc.beslis([k]) == cc.VRAGEN


def test_ai_gok_gevaarlijk_blijft_samengevoegd():
    k = cc.Kandidaat("herstart de pc", 95, "pc", [("x", "herstart de pc")], bron="ai")
    assert cc.beslis([k]) == cc.GEVAARLIJK


def test_te_vragen_ai_alleen_als_lokaal_niets_vond(monkeypatch):
    model = _model("open steam")
    monkeypatch.setattr(cc, "_standaard_llm", model)
    kandidaten = cc.te_vragen("open stem", namen=NAMEN, met_ai=True)
    assert [k.bron for k in kandidaten] == ["lokaal"]
    assert model.aanroepen == []


def test_te_vragen_zonder_met_ai_geen_model(monkeypatch):
    model = _model("open steam")
    monkeypatch.setattr(cc, "_standaard_llm", model)
    assert cc.te_vragen("open dat ding", namen=NAMEN) == []
    assert model.aanroepen == []


def test_te_vragen_lage_ai_score_valt_af(monkeypatch):
    monkeypatch.setattr(cc, "_standaard_llm", _model("open steam", cc.DREMPEL_VRAGEN - 1))
    assert cc.te_vragen("open dat ding", namen=NAMEN, met_ai=True) == []


# ---------------------------------------------------------------------
# In het brein
# ---------------------------------------------------------------------

@pytest.fixture
def keten(monkeypatch):
    log = {"ai": [], "geopend": []}

    def ask_ai(command, **_kw):
        log["ai"].append(command)
        return "AI-antwoord"

    def open_program(command):
        delen = command.split()
        if len(delen) == 2 and delen[0] == "open" and delen[1] in ("discord", "steam"):
            log["geopend"].append(delen[1])
            return f"Ik open {delen[1]}."
        return None

    monkeypatch.setattr(brain, "ask_ai", ask_ai)
    monkeypatch.setattr(brain, "try_open_program", open_program)
    return log


def test_brein_ai_vangnet_vraagt_en_voert_uit(keten, monkeypatch):
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [])
    monkeypatch.setattr(cc, "_standaard_llm", _model("open discord", 100))

    assert brain.process_command("open dat chat programma") == "Bedoelde u: open discord?"
    assert get_pending()["kind"] == CORRECTIE_KIND
    assert keten["geopend"] == []

    assert brain.process_command("ja") == "Ik open discord."
    assert keten["geopend"] == ["discord"]
    assert keten["ai"] == []


def test_brein_ai_niets_gevonden_wordt_chat(keten, monkeypatch):
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [])
    monkeypatch.setattr(cc, "_standaard_llm", _model("geen"))
    assert brain.process_command("open dat chat programma") == "AI-antwoord"
    assert get_pending() is None


def test_slim_huis_route_gebruikt_geen_ai_vangnet(keten, monkeypatch):
    model = _model("zet de lamp aan")
    monkeypatch.setattr(cc, "_standaard_llm", model)
    monkeypatch.setattr(brain, "try_ha_direct", lambda c: None)
    assert brain.process_command("zet die lamp even op rood") == "AI-antwoord"
    assert model.aanroepen == []


def test_ollama_stub_breekt_niets(keten, monkeypatch):
    # Zonder nep-model: de conftest-stub (of een echte Ollama) mag nooit
    # tot een verkeerde actie leiden.
    monkeypatch.setattr(cc, "zoek_kandidaten", lambda *_a, **_kw: [])
    antwoord = brain.process_command("open dat chat programma")
    assert keten["geopend"] == []
    assert antwoord == "AI-antwoord" or antwoord.startswith("Bedoelde u")
