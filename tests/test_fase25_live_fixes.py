"""Fase 25 — fixes na de live test (2026-10-30).

* "Waar woon ik?" vond de geheugensleutel ``woonplaats`` niet.
* Na twee vragen een pauze van 5 minuten: Google's eigen wachttijd werd niet
  gelezen.
* "Zoek op…" gaf een verkeerde bron en een verkeerd antwoord: Google Zoeken
  zit niet in de gratis laag, en de eerste DuckDuckGo-hit werd letterlijk
  voorgelezen. Nu leest JARVIS een paar pagina's en vat Gemini samen.
"""

import json
import types

import pytest

import config
from core import gemini, llm, opzoeken, privacy_poort
from memory.memory import relevance_score


# ---------------------------------------------------------------------
# Geheugen: "waar woon ik?"
# ---------------------------------------------------------------------

@pytest.mark.parametrize("vraag, sleutel", [
    ("waar woon ik?", "woonplaats"),
    ("in welke plaats woon ik", "woonplaats"),
    ("waar woont rushil", "woonplaats"),
    ("hoe oud ben ik?", "leeftijd"),
    ("hoe heet ik", "naam"),
    ("welke opleiding doe ik", "opleiding"),
    ("waar werk ik", "werk"),
    ("wanneer ben ik jarig", "verjaardag"),
])
def test_vraag_vindt_sleutel(vraag, sleutel):
    assert relevance_score(vraag, "algemeen", sleutel, "x") > 0


@pytest.mark.parametrize("vraag", [
    "zet de woonkamer lamp aan",
    "open spotify",
    "wat is de hoofdstad van frankrijk",
])
def test_geen_valse_treffer_op_woonplaats(vraag):
    assert relevance_score(vraag, "algemeen", "woonplaats", "Badhoevedorp") == 0


def test_stam_telt_mee():
    # "woon" is het begin van "woonplaats" (ook als het woord niet helemaal klopt).
    assert relevance_score("waar woon ik", "algemeen", "woonplaats", "x") > 0
    assert relevance_score("favoriete game", "voorkeuren", "favoriete_game", "x") > 0


# ---------------------------------------------------------------------
# Limiet: de wachttijd van Google
# ---------------------------------------------------------------------

class Antwoord429:
    status_code = 429

    def __init__(self, fout, headers=None):
        self._fout = fout
        self.headers = headers or {}

    def json(self):
        return {"error": self._fout}


def _fout(fout, headers=None):
    return gemini._fout_uit_antwoord(Antwoord429(fout, headers))


def test_retry_delay_uit_details():
    fout = _fout({"code": 429, "message": "Quota exceeded.", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "34s"},
    ]})
    assert fout.soort == gemini.LIMIET
    assert fout.wacht == 34.0
    assert fout.per_dag is False
    assert "limiet" in str(fout)


def test_retry_uit_melding():
    assert _fout({"message": "Quota exceeded. Please retry in 12.5s."}).wacht == 12.5
    assert _fout({"message": "Please retry in 900ms."}).wacht == 0.9


def test_retry_after_header():
    assert _fout({"message": "x"}, {"Retry-After": "7"}).wacht == 7.0


def test_daglimiet_herkend():
    fout = _fout({"message": "Quota exceeded.", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
    ]})
    assert fout.per_dag is True
    assert fout.wacht is None
    assert "daglimiet" in str(fout)


@pytest.fixture
def klok(monkeypatch):
    staat = {"nu": 1000.0, "pogingen": 0}
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(llm, "_klok", lambda: staat["nu"])
    monkeypatch.setattr(llm, "_wandklok", lambda: 1_700_000_000.0 + staat["nu"])
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: types.SimpleNamespace(
        message=types.SimpleNamespace(content="lokaal", tool_calls=None)))
    llm._reset_brein()
    yield staat
    llm._reset_brein()


def _pauze_na(klok, monkeypatch, fout):
    def kapot(messages, **kw):
        klok["pogingen"] += 1
        raise fout

    monkeypatch.setattr(gemini, "chat", kapot)
    llm.chat([{"role": "user", "content": "x"}], cloud=True)
    stap = 0
    while not llm.gemini_beschikbaar():
        klok["nu"] += 1
        stap += 1
    return stap


def test_pauze_volgt_wachttijd_van_google(klok, monkeypatch):
    fout = gemini.GeminiFout("limiet", gemini.LIMIET, 429, wacht=34)
    assert _pauze_na(klok, monkeypatch, fout) == 35  # wachttijd + 1 s marge


def test_pauze_zonder_wachttijd_een_minuut(klok, monkeypatch):
    assert _pauze_na(klok, monkeypatch, gemini.GeminiFout("limiet", gemini.LIMIET, 429)) == 60


def test_pauze_daglimiet_een_uur(klok, monkeypatch):
    fout = gemini.GeminiFout("daglimiet", gemini.LIMIET, 429)
    fout.per_dag = True
    assert _pauze_na(klok, monkeypatch, fout) == llm.GEMINI_PAUZE_DAG


# ---------------------------------------------------------------------
# Zoek op: DuckDuckGo + kort antwoord met de juiste bron
# ---------------------------------------------------------------------

PAGINAS = {
    "ok": True,
    "pages": [
        {"title": "F1 kalender 2024", "url": "https://www.oud-nieuws.nl/f1-2024",
         "text": "In 2024 won Verstappen de race in Abu Dhabi."},
        {"title": "Uitslag GP Mexico 2026", "url": "https://www.formule1.nl/uitslag",
         "text": "Norris won zondag de Grand Prix van Mexico 2026."},
    ],
}


@pytest.fixture
def samenvatter(monkeypatch):
    verzoeken = []
    staat = {"antwoord": json.dumps({"antwoord": "Norris won de laatste race, in Mexico.", "bron": 2})}

    def chat(messages, **kw):
        verzoeken.append({"messages": messages, **kw})
        return gemini.Antwoord(staat["antwoord"])

    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(config, "GEMINI_ZOEKEN", False)
    monkeypatch.setattr(gemini, "chat", chat)
    llm._reset_brein()
    privacy_poort._reset()
    yield types.SimpleNamespace(verzoeken=verzoeken, staat=staat)
    llm._reset_brein()


def _zoek(vraag, max_pages=2):
    _zoek.gevraagd = (vraag, max_pages)
    return PAGINAS


def test_kort_antwoord_met_juiste_bron(samenvatter):
    antwoord = opzoeken.zoek_en_vat_samen("wie won de laatste formule 1 race", zoek=_zoek)
    assert antwoord == "Norris won de laatste race, in Mexico. (Bron: formule1.nl)"
    assert _zoek.gevraagd == ("wie won de laatste formule 1 race", 2)
    verzoek = samenvatter.verzoeken[0]
    assert verzoek["json_mode"] is True
    tekst = verzoek["messages"][1]["content"]
    assert "[1] F1 kalender 2024 (oud-nieuws.nl)" in tekst and "[2] Uitslag GP Mexico 2026 (formule1.nl)" in tekst
    assert "ALLEEN met informatie uit die bronnen" in verzoek["messages"][0]["content"]


@pytest.mark.parametrize("antwoord, verwacht", [
    (json.dumps({"antwoord": "Norris.", "bron": None}), "Norris."),
    (json.dumps({"antwoord": "Norris.", "bron": 7}), "Norris."),
    (json.dumps({"antwoord": "Norris.", "bron": True}), "Norris."),
    ('Hier: {"antwoord": "Norris.", "bron": 1} klaar', "Norris. (Bron: oud-nieuws.nl)"),
    (json.dumps({"antwoord": ""}), None),
    ("geen json", None),
])
def test_rare_antwoorden(samenvatter, antwoord, verwacht):
    samenvatter.staat["antwoord"] = antwoord
    assert opzoeken.zoek_en_vat_samen("wie won", zoek=_zoek) == verwacht


def test_niets_gevonden(samenvatter):
    assert opzoeken.zoek_en_vat_samen("x", zoek=lambda v, max_pages=2: {"ok": False, "pages": []}) is None
    assert opzoeken.zoek_en_vat_samen("x", zoek=lambda v, max_pages=2: {"ok": True, "pages": [{"url": "u"}]}) is None
    assert samenvatter.verzoeken == []


def test_zonder_gemini_zoals_voorheen(samenvatter, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert opzoeken.zoek_en_vat_samen("wie won", zoek=_zoek) is None


def test_persoonlijke_zoekvraag_lokaal_samengevat(samenvatter, monkeypatch):
    lokaal = []
    monkeypatch.setattr(llm.ollama, "chat", lambda **kw: lokaal.append(kw) or types.SimpleNamespace(
        message=types.SimpleNamespace(content=json.dumps({"antwoord": "Lokaal.", "bron": 1}), tool_calls=None)))
    assert opzoeken.zoek_en_vat_samen("wat staat er in mijn agenda", zoek=_zoek) == "Lokaal. (Bron: oud-nieuws.nl)"
    assert samenvatter.verzoeken == [] and lokaal


def test_zoek_op_gebruikt_samenvatting(samenvatter, monkeypatch):
    import actions.web as web

    monkeypatch.setattr(web, "search_and_fetch", _zoek)
    assert opzoeken.zoek_op("wie won de laatste race") == "Norris won de laatste race, in Mexico. (Bron: formule1.nl)"


def test_zoekcommando_gebruikt_samenvatting(samenvatter, monkeypatch):
    import core.brain as brain

    monkeypatch.setattr(brain, "search_and_fetch", lambda *a, **k: pytest.fail("geen letterlijk resultaat"))
    import actions.web as web

    monkeypatch.setattr(web, "search_and_fetch", _zoek)
    antwoord = brain.try_web_search("zoek op wie de laatste formule 1 race won")
    assert antwoord == "Norris won de laatste race, in Mexico. (Bron: formule1.nl)"


def test_standaardmodel_en_zoeken_uit():
    from pathlib import Path

    tekst = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    assert "GEMINI_MODEL=gemini-3.1-flash-lite" in tekst
    assert "GEMINI_ZOEKEN=0" in tekst
