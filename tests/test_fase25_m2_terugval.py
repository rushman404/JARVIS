"""Fase 25, M2 — Gemini eerst, Ollama als terugval (core/llm.py).

Geen echte Gemini of Ollama: beide worden vervangen door nep-functies.
"""

import types

import pytest

import config
from core import gemini, llm, proactive
from core.gemini import GeminiFout


def _ollama_antwoord(tekst="lokaal antwoord"):
    return types.SimpleNamespace(message=types.SimpleNamespace(content=tekst, tool_calls=None),
                                 prompt_eval_count=1, eval_count=1)


class Omgeving:
    def __init__(self, monkeypatch):
        self.nu = 1000.0
        self.gemini_fout = None
        self.gemini_aanroepen = []
        self.ollama_aanroepen = []
        self.meldingen = []
        self.stream_fout_na = None  # fout na zoveel stukjes

        monkeypatch.setattr(config, "GEMINI_API_KEY", "test-sleutel")
        monkeypatch.setattr(llm, "_klok", lambda: self.nu)
        monkeypatch.setattr(llm, "_wandklok", lambda: 1_700_000_000.0 + self.nu)
        monkeypatch.setattr(gemini, "chat", self._gemini_chat)
        monkeypatch.setattr(gemini, "chat_stream", self._gemini_stream)
        monkeypatch.setattr(llm.ollama, "chat", self._ollama_chat)
        engine = types.SimpleNamespace(meld=lambda tekst, bron="systeem": self.meldingen.append((tekst, bron)))
        monkeypatch.setattr(proactive, "peek_engine", lambda: engine)
        llm._reset_brein()

    def _gemini_chat(self, messages, **kw):
        self.gemini_aanroepen.append((messages, kw))
        if self.gemini_fout:
            raise self.gemini_fout
        return gemini.Antwoord("gemini antwoord")

    def _gemini_stream(self, messages, **kw):
        self.gemini_aanroepen.append((messages, kw))
        if self.gemini_fout:
            raise self.gemini_fout
        yield "Gemini "
        yield "praat."

    def _ollama_chat(self, **kwargs):
        self.ollama_aanroepen.append(kwargs)
        if kwargs.get("stream"):
            return iter([{"message": {"content": "Ollama "}}, {"message": {"content": "praat."}}])
        return _ollama_antwoord()


@pytest.fixture
def om(monkeypatch):
    omgeving = Omgeving(monkeypatch)
    yield omgeving
    llm._reset_brein()


VRAAG = [{"role": "user", "content": "waarom is de lucht blauw?"}]


# ---------------------------------------------------------------------
# Standaard nooit naar de cloud
# ---------------------------------------------------------------------

def test_zonder_cloud_altijd_ollama(om):
    assert llm.chat(VRAAG).message.content == "lokaal antwoord"
    assert "".join(llm.chat_stream(VRAAG)) == "Ollama praat."
    assert om.gemini_aanroepen == []


def test_zonder_sleutel_altijd_ollama(om, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert llm.chat(VRAAG, cloud=True).message.content == "lokaal antwoord"
    assert om.gemini_aanroepen == []
    assert om.meldingen == []
    assert llm.brein_status()["reden"] == "geen Gemini-sleutel"


# ---------------------------------------------------------------------
# Gemini eerst
# ---------------------------------------------------------------------

def test_cloud_gebruikt_gemini(om):
    tool = {"type": "function", "function": {"name": "open_program"}}
    antwoord = llm.chat(VRAAG, cloud=True, tools=[tool], json_mode=True, zoeken=True, temperature=0)
    assert antwoord.message.content == "gemini antwoord"
    messages, kw = om.gemini_aanroepen[0]
    assert messages == VRAAG
    assert kw == {"tools": [tool], "json_mode": True, "zoeken": True, "temperature": 0}
    assert llm.laatste_brein() == "gemini"
    assert om.ollama_aanroepen == []
    assert llm.brein_status()["brein"] == "gemini"


def test_stream_via_gemini(om):
    assert list(llm.chat_stream(VRAAG, cloud=True)) == ["Gemini ", "praat."]
    assert om.ollama_aanroepen == []


def test_stream_met_tools_of_json_blijft_ollama(om):
    "".join(llm.chat_stream(VRAAG, cloud=True, json_mode=True))
    assert om.gemini_aanroepen == []


# ---------------------------------------------------------------------
# Terugval
# ---------------------------------------------------------------------

@pytest.mark.parametrize("soort, pauze", [
    (gemini.NETWERK, 30),
    (gemini.SERVER, 60),
    (gemini.LIMIET, 300),
    (gemini.SLEUTEL, 3600),
])
def test_storing_valt_terug_en_pauzeert(om, soort, pauze):
    om.gemini_fout = GeminiFout("mis", soort)
    assert llm.chat(VRAAG, cloud=True).message.content == "lokaal antwoord"
    assert len(om.gemini_aanroepen) == 1

    # Tijdens de pauze wordt Gemini niet eens geprobeerd (geen time-outs).
    om.nu += pauze - 1
    llm.chat(VRAAG, cloud=True)
    assert len(om.gemini_aanroepen) == 1
    assert llm.brein_status()["brein"] == "ollama"

    # Na de pauze weer Gemini.
    om.nu += 2
    om.gemini_fout = None
    assert llm.chat(VRAAG, cloud=True).message.content == "gemini antwoord"
    assert llm.brein_status()["brein"] == "gemini"


@pytest.mark.parametrize("soort", [gemini.WEIGERING, gemini.LEEG, gemini.PRIVACY])
def test_fout_van_dit_verzoek_zonder_pauze_of_melding(om, soort):
    om.gemini_fout = GeminiFout("mis", soort)
    assert llm.chat(VRAAG, cloud=True).message.content == "lokaal antwoord"
    om.gemini_fout = None
    assert llm.chat(VRAAG, cloud=True).message.content == "gemini antwoord"
    assert om.meldingen == []


def test_limiet_met_wachttijd_van_google(om):
    om.gemini_fout = GeminiFout("mis", gemini.LIMIET, 429, wacht=45)
    llm.chat(VRAAG, cloud=True)
    om.nu += 44
    llm.chat(VRAAG, cloud=True)
    assert len(om.gemini_aanroepen) == 1
    om.nu += 2
    llm.chat(VRAAG, cloud=True)
    assert len(om.gemini_aanroepen) == 2


def test_model_niet_gratis_lange_pauze(om):
    om.gemini_fout = GeminiFout("limiet. Google: Quota exceeded ... limit: 0", gemini.LIMIET, 429)
    llm.chat(VRAAG, cloud=True)
    om.nu += 3600
    llm.chat(VRAAG, cloud=True)
    assert len(om.gemini_aanroepen) == 1


def test_onverwachte_fout_valt_terug(om):
    om.gemini_fout = KeyError("bug")
    assert llm.chat(VRAAG, cloud=True).message.content == "lokaal antwoord"


def test_stream_valt_terug_voor_eerste_tekst(om):
    om.gemini_fout = GeminiFout("weg", gemini.NETWERK)
    assert "".join(llm.chat_stream(VRAAG, cloud=True)) == "Ollama praat."
    assert len(om.ollama_aanroepen) == 1
    assert om.ollama_aanroepen[0]["stream"] is True


# ---------------------------------------------------------------------
# Eén keer melden
# ---------------------------------------------------------------------

def test_een_keer_gemeld_bij_weg_en_bij_terug(om):
    om.gemini_fout = GeminiFout("weg", gemini.NETWERK)
    llm.chat(VRAAG, cloud=True)
    om.nu += 31
    llm.chat(VRAAG, cloud=True)  # nog steeds weg: niet opnieuw melden
    assert om.meldingen == [(llm.MELDING_GEMINI_WEG, "brein")]

    om.nu += 31
    om.gemini_fout = None
    llm.chat(VRAAG, cloud=True)
    llm.chat(VRAAG, cloud=True)
    assert om.meldingen == [(llm.MELDING_GEMINI_WEG, "brein"), (llm.MELDING_GEMINI_TERUG, "brein")]


def test_limiet_eigen_melding(om):
    om.gemini_fout = GeminiFout("op", gemini.LIMIET)
    llm.chat(VRAAG, cloud=True)
    assert om.meldingen == [(llm.MELDING_GEMINI_LIMIET, "brein")]


def test_geen_melding_als_alles_goed_gaat(om):
    llm.chat(VRAAG, cloud=True)
    assert om.meldingen == []


def test_zonder_engine_geen_crash(om, monkeypatch):
    monkeypatch.setattr(proactive, "peek_engine", lambda: None)
    om.gemini_fout = GeminiFout("weg", gemini.NETWERK)
    assert llm.chat(VRAAG, cloud=True).message.content == "lokaal antwoord"


# ---------------------------------------------------------------------
# Status voor het dashboard
# ---------------------------------------------------------------------

def test_brein_status_tijdens_storing(om):
    om.gemini_fout = GeminiFout("op", gemini.LIMIET)
    llm.chat(VRAAG, cloud=True)
    status = llm.brein_status()
    assert status["brein"] == "ollama"
    assert status["reden"] == "Gemini-limiet bereikt"
    assert status["model"] == config.AI_MODEL
    assert status["tot"] and len(status["tot"]) == 5  # "HH:MM"


def test_brein_status_gemini(om, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-test")
    assert llm.brein_status() == {"brein": "gemini", "model": "gemini-test", "reden": "", "tot": None}


def test_systeempaneel_toont_ai_brein():
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
    assert "b.ai_brein" in js and "'AI: Gemini" in js
    bronnen = (Path(__file__).resolve().parent.parent / "dashboard" / "bronnen.py").read_text(encoding="utf-8")
    assert 'status["ai_brein"] = llm.brein_status()' in bronnen
