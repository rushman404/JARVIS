"""Fase 25, M4 — bewijs: persoonlijke data blijft lokaal.

Klaar-als (ROADMAP): "een test bewijst dat persoonlijke data lokaal blijft".

Opzet: Gemini staat "aan" met een nep-Google op HTTP-niveau. Alles wat
JARVIS echt zou versturen (het JSON-lichaam, de URL en de headers) wordt
opgevangen. Het geheugen en de context zitten vol persoonlijke gegevens.
Daarna gaan tientallen vragen door de echte routes (``ask_ai``, de agent,
de commando-correctie, opzoeken) en controleert de test elk verzoek dat de
pc zou verlaten. Er wordt nooit iets uitgevoerd: tools zijn nep en het
nep-Google antwoordt alleen met tekst.

Daarnaast: dezelfde vragen met Gemini uit (zoals vóór Fase 25) en met een
Gemini-storing (terugval) geven gewoon een antwoord.
"""

import json
import types

import pytest

import config
from core import gemini, llm, privacy_poort

# ---------------------------------------------------------------------
# Persoonlijke gegevens die NOOIT in een Gemini-verzoek mogen staan
# ---------------------------------------------------------------------

GEHEIM = {
    "woonplaats": "Badhoevedorp",
    "adres": "Pruimenlaan 17",
    "opleiding": "Grafisch Lyceum Rotterdam",
    "werk": "Stagebureau Vlinderhof",
    "telefoon": "0687654321",
    "email": "rushil.geheim@voorbeeld.nl",
    "verjaardag": "14 maart",
}
NIET_GEHEIM = {"favoriete_game": "Valorant", "favoriete_muziek": "lo-fi"}

GEHEUGEN = {
    "algemeen": {k: {"value": v, "usage_count": 3} for k, v in GEHEIM.items()},
    "voorkeuren": {k: {"value": v, "usage_count": 1} for k, v in NIET_GEHEIM.items()},
    "pc": {"downloads_map": {"value": "C:\\Users\\rushi\\Downloads"}},
    "projecten": {}, "muziek": {}, "apparaten": {},
}

# Wat in een verzoek naar Google nooit mag voorkomen.
VERBODEN = list(GEHEIM.values()) + [
    "Pruimenlaan", "Vlinderhof", "Grafisch Lyceum",
    "C:\\\\Users", "C:\\Users", "\\\\Users\\\\",
    "JARVIS-CONTEXT EN GEHEUGEN\\n", "1. DIT GESPREK (", "JARVIS-GEHEUGEN (",
    "functionResponse", "nep-sleutel-geheim",
]

# Vragen die over iemands persoonlijke leven gaan: daar mag zelfs geen
# verzoek voor naar Google (de poort houdt ze lokaal).
PERSOONLIJK = [
    "waar woon ik?",
    "wat is mijn adres",
    "hoe oud ben ik",
    "welke opleiding doe ik",
    "waar werk ik",
    "wanneer ben ik jarig",
    "wat is mijn telefoonnummer",
    "wat is mijn e-mailadres",
    "heb ik nieuwe mail",
    "vat mijn mail samen",
    "wat staat er vandaag in mijn agenda",
    "wanneer is mijn volgende afspraak",
    "heb ik nieuwe dm's",
    "wat stuurde sem",
    "wat staat er in mijn downloads",
    "open het bestand cv.pdf",
    "wat zie je op mijn scherm",
    "wat weet je over mij",
    "weet je nog wat ik gisteren zei",
    "wat vroeg ik net",
    "hoe laat moet ik weg naar de tandarts",
    "wat is er hier in de buurt te doen",
    "hoe is het weer in badhoevedorp",
    "hoe ver is de pruimenlaan van amsterdam",
    "stuur een mail naar rushil.geheim@voorbeeld.nl",
    "bel 0687654321",
    "mijn postcode is 1171 ab",
    "wat vind je van mijn vriendin",
    "ik woon in haarlem",
    "onthoud dat ik van pizza hou",
]

# Gewone vragen en opdrachten: die mogen naar Gemini, maar zonder data.
GEWOON = [
    "waarom is de lucht blauw?",
    "wat is de hoofdstad van frankrijk?",
    "en van duitsland?",
    "hoeveel is 17 keer 23",
    "vertel een korte grap",
    "wie schreef de max havelaar",
    "leg uit hoe een zwart gat werkt",
    "zet de lampen in de woonkamer op rood",
    "zet mijn lampen aan",
    "speel muziek op mijn pc",
    "open spotify en discord",
    "maak het gezellig in de woonkamer",
    "sluit hem",
    "start valorant",
]


# ---------------------------------------------------------------------
# Nep-Google op HTTP-niveau
# ---------------------------------------------------------------------

class NepGoogle:
    """Vangt elk HTTP-verzoek naar Gemini op en antwoordt met tekst."""

    def __init__(self, tekst="Prima, sir."):
        self.tekst = tekst
        self.verzoeken = []
        self.storing = None  # HTTP-status om een storing na te bootsen

    def post(self, url, headers=None, json=None, timeout=None, stream=False):
        import json as _json

        self.verzoeken.append({"url": url, "headers": dict(headers or {}), "body": json})
        if self.storing:
            return _Antwoord(self.storing, {"error": {"message": "storing"}})
        data = {"candidates": [{"content": {"parts": [{"text": self._tekst_voor(json)}]}}]}
        if stream:
            return _Antwoord(200, None, ["data: " + _json.dumps(data)])
        return _Antwoord(200, data)

    def _tekst_voor(self, body):
        config_ = (body or {}).get("generationConfig") or {}
        if config_.get("responseMimeType") == "application/json":
            return '{"steps": [], "commando": "geen", "zekerheid": 0, "antwoord": "Prima, sir.", "bron": null}'
        return self.tekst

    def lichamen(self):
        return [json.dumps(v["body"], ensure_ascii=False) for v in self.verzoeken]


class _Antwoord:
    def __init__(self, status, data, regels=None):
        self.status_code = status
        self._data = data
        self._regels = regels or []
        self.headers = {}

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data

    def iter_lines(self, decode_unicode=False):
        yield from self._regels


@pytest.fixture
def google(monkeypatch, tmp_path):
    """Gemini aan (nep-sleutel), nep-Google, en een geheugen vol geheimen."""

    import memory.memory as mem

    nep = NepGoogle()
    monkeypatch.setattr(config, "GEMINI_API_KEY", "nep-sleutel-geheim")
    monkeypatch.setattr(config, "GEMINI_ZOEKEN", False)
    monkeypatch.setattr(config, "THUIS_ADRES", "Pruimenlaan 17, Badhoevedorp")
    monkeypatch.setattr(gemini, "_http", lambda http=None: nep)
    monkeypatch.setattr(gemini, "HERHAAL_NA_503", 0)
    monkeypatch.setattr(mem, "load_memory", lambda: json.loads(json.dumps(GEHEUGEN)))

    # Nooit iets echt uitvoeren: elke tool is nep.
    import core.ai as ai

    uitgevoerd = []
    monkeypatch.setattr(ai, "_dispatch_tool", lambda naam, args, vraag: uitgevoerd.append(naam) or "ok")
    monkeypatch.setattr(ai, "extract_personal_info", lambda *a, **k: None)

    # Lokale context met een bestandspad en een programma.
    ai.update_context(last_program="Discord", last_file="C:\\Users\\rushi\\Documents\\cv.pdf")

    llm._reset_brein()
    privacy_poort._reset()
    yield nep
    llm._reset_brein()
    privacy_poort._reset()


def _controleer_alles(nep):
    """Elk opgevangen verzoek: geen geheim, geen sleutel in URL of lichaam,
    geen toolresultaat, alleen toegestane tools."""

    for verzoek, lichaam in zip(nep.verzoeken, nep.lichamen()):
        for verboden in VERBODEN:
            assert verboden not in lichaam, f"{verboden!r} lekte naar Gemini:\n{lichaam[:600]}"
        assert "nep-sleutel-geheim" not in verzoek["url"]
        assert verzoek["headers"].get("x-goog-api-key") == "nep-sleutel-geheim"
        for content in (verzoek["body"] or {}).get("contents") or []:
            assert content["role"] in ("user", "model")
            for part in content["parts"]:
                assert "functionResponse" not in part
        for tool in (verzoek["body"] or {}).get("tools") or []:
            for declaratie in tool.get("functionDeclarations") or []:
                assert declaratie["name"] in privacy_poort.CLOUD_TOOLS, declaratie["name"]


# ---------------------------------------------------------------------
# Het bewijs
# ---------------------------------------------------------------------

@pytest.mark.parametrize("vraag", PERSOONLIJK)
def test_persoonlijke_vraag_verlaat_de_pc_niet(google, vraag):
    from core.ai import ask_ai

    ask_ai(vraag)
    assert google.verzoeken == [], f"{vraag!r} ging naar Gemini:\n{google.lichamen()}"


@pytest.mark.parametrize("vraag", PERSOONLIJK)
def test_persoonlijk_ook_niet_via_agent_correctie_of_opzoeken(google, vraag):
    import core.agent as agent_mod
    from core import commando_correctie, opzoeken

    agent_mod.Agent()._generate_plan(vraag)
    commando_correctie.ai_kandidaat(vraag, namen=["spotify", "discord"])
    opzoeken.zoek_met_gemini(vraag)
    opzoeken.zoek_en_vat_samen(vraag, zoek=lambda v, max_pages=2: {
        "ok": True, "pages": [{"title": "t", "url": "https://x.nl", "text": "tekst"}]})
    assert google.verzoeken == [], f"{vraag!r} ging naar Gemini:\n{google.lichamen()}"


def test_gewone_vragen_naar_gemini_zonder_persoonlijke_data(google):
    from core.ai import ask_ai

    for vraag in GEWOON:
        ask_ai(vraag)
    assert google.verzoeken, "Gemini werd nooit gebruikt"
    _controleer_alles(google)


def test_gewone_vragen_ook_met_streaming(google):
    from core.ai import ask_ai

    for vraag in GEWOON[:7]:
        ask_ai(vraag, on_tekst=lambda stuk: None)
    assert any("streamGenerateContent" in v["url"] for v in google.verzoeken)
    _controleer_alles(google)


def test_gewone_opdrachten_via_agent_correctie_en_opzoeken(google):
    import core.agent as agent_mod
    from core import commando_correctie, opzoeken

    for opdracht in ("open spotify en zet muziek aan", "zet de lampen op rood en open discord"):
        agent_mod.Agent()._generate_plan(opdracht)
    commando_correctie.ai_kandidaat("open dat chat programma", namen=["spotify", "discord"])
    opzoeken.zoek_en_vat_samen("wie won de laatste formule 1 race", zoek=lambda v, max_pages=2: {
        "ok": True, "pages": [{"title": "F1", "url": "https://f1.nl/a", "text": "Norris won."}]})
    assert len(google.verzoeken) >= 4
    _controleer_alles(google)


def test_verwijzing_stuurt_alleen_de_programmanaam(google):
    from core.ai import ask_ai

    ask_ai("open het opnieuw")
    lichamen = google.lichamen()
    if lichamen:  # de vaste routes kunnen het al afhandelen
        assert any("Laatste programma in dit gesprek: Discord" in b for b in lichamen)
        assert all("cv.pdf" not in b for b in lichamen)
    _controleer_alles(google)


def test_geschiedenis_bevat_alleen_gemini_beurten(google):
    from core.ai import ask_ai

    ask_ai("waar woon ik?")                 # lokaal
    ask_ai("wat is de hoofdstad van frankrijk?")
    ask_ai("en van duitsland?")
    laatste = google.lichamen()[-1]
    assert "wat is de hoofdstad van frankrijk?" in laatste
    assert "waar woon ik" not in laatste
    _controleer_alles(google)


# ---------------------------------------------------------------------
# Regressie: Gemini uit, aan en met storing
# ---------------------------------------------------------------------

def _ollama(monkeypatch, gezien):
    def chat(**kw):
        gezien.append(kw.get("messages"))
        if kw.get("stream"):
            return iter([{"message": {"content": "Lokaal antwoord."}}])
        return types.SimpleNamespace(message=types.SimpleNamespace(content="Lokaal antwoord.", tool_calls=None))

    monkeypatch.setattr(llm.ollama, "chat", chat)


@pytest.mark.parametrize("vraag", GEWOON[:7] + PERSOONLIJK[:5])
def test_zonder_gemini_zoals_voor_fase_25(google, monkeypatch, vraag):
    from core.ai import ask_ai

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    gezien = []
    _ollama(monkeypatch, gezien)
    assert ask_ai(vraag)
    assert google.verzoeken == []
    assert gezien


@pytest.mark.parametrize("status", [429, 500, 503])
def test_storing_valt_terug_op_ollama_met_lokale_context(google, monkeypatch, status):
    from core.ai import ask_ai

    google.storing = status
    gezien = []
    _ollama(monkeypatch, gezien)
    assert ask_ai("waarom is de lucht blauw?") == "Lokaal antwoord."
    # Ollama kreeg de lokale berichten (met het context- en geheugenblok).
    assert any("JARVIS-CONTEXT EN GEHEUGEN" in json.dumps(m, ensure_ascii=False, default=str) for m in gezien)
    _controleer_alles(google)
    # Tijdens de pauze wordt Gemini niet opnieuw geprobeerd.
    aantal = len(google.verzoeken)
    ask_ai("wat is de hoofdstad van frankrijk?")
    assert len(google.verzoeken) == aantal


def test_storing_tijdens_streaming(google, monkeypatch):
    from core.ai import ask_ai

    google.storing = 500
    gezien = []
    _ollama(monkeypatch, gezien)
    stukken = []
    assert ask_ai("waarom is de lucht blauw?", on_tekst=stukken.append) == "Lokaal antwoord."
    assert stukken
