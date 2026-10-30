"""Fase 25, M1 — Gemini-koppeling (core/gemini.py).

Er gaat nooit iets naar Google: elke test gebruikt een nep-``http``.
"""

import json

import pytest

from core import gemini
from core.gemini import GeminiFout

SLEUTEL = "test-sleutel-123"


class NepAntwoord:
    def __init__(self, status=200, data=None, regels=None, headers=None):
        self.status_code = status
        self._data = data
        self._regels = regels or []
        self.headers = headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("geen json")
        return self._data

    def iter_lines(self, decode_unicode=False):
        for regel in self._regels:
            if isinstance(regel, Exception):
                raise regel
            yield regel


class NepHttp:
    def __init__(self, *antwoorden, fout=None):
        self.antwoorden = list(antwoorden)
        self.fout = fout
        self.verzoeken = []

    def post(self, url, headers=None, json=None, timeout=None, stream=False):
        self.verzoeken.append({"url": url, "headers": headers, "json": json, "timeout": timeout, "stream": stream})
        if self.fout:
            raise self.fout
        return self.antwoorden.pop(0)


def _tekst(tekst, **extra):
    kandidaat = {"content": {"role": "model", "parts": [{"text": tekst}]}, "finishReason": "STOP"}
    kandidaat.update(extra)
    return {"candidates": [kandidaat], "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5}}


@pytest.fixture(autouse=True)
def geen_wachten(monkeypatch):
    monkeypatch.setattr(gemini, "HERHAAL_NA_503", 0)


def _chat(http, messages=None, **kw):
    kw.setdefault("sleutel", SLEUTEL)
    kw.setdefault("model", "gemini-test")
    kw.setdefault("timeout", 3)
    kw.setdefault("denkniveau", "")
    return gemini.chat(messages or [{"role": "user", "content": "hallo"}], http=http, **kw)


# ---------------------------------------------------------------------
# Verzoek
# ---------------------------------------------------------------------

def test_sleutel_alleen_in_header_niet_in_url():
    http = NepHttp(NepAntwoord(data=_tekst("Hoi.")))
    _chat(http)
    verzoek = http.verzoeken[0]
    assert verzoek["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert SLEUTEL not in verzoek["url"]
    assert verzoek["headers"]["x-goog-api-key"] == SLEUTEL
    assert SLEUTEL not in json.dumps(verzoek["json"])
    assert verzoek["timeout"] == 3


def test_berichten_worden_contents():
    verzoek = gemini.bouw_verzoek([
        {"role": "system", "content": "Je bent JARVIS."},
        {"role": "system", "content": "Spreek de gebruiker aan met u."},
        {"role": "user", "content": "Wat is de hoofdstad van Frankrijk?"},
        {"role": "assistant", "content": "Parijs."},
        {"role": "user", "content": "En van Duitsland?"},
    ])
    assert verzoek["systemInstruction"] == {"parts": [{"text": "Je bent JARVIS.\n\nSpreek de gebruiker aan met u."}]}
    assert verzoek["contents"] == [
        {"role": "user", "parts": [{"text": "Wat is de hoofdstad van Frankrijk?"}]},
        {"role": "model", "parts": [{"text": "Parijs."}]},
        {"role": "user", "parts": [{"text": "En van Duitsland?"}]},
    ]


def test_opeenvolgende_rollen_samengevoegd():
    verzoek = gemini.bouw_verzoek([
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ])
    assert verzoek["contents"] == [{"role": "user", "parts": [{"text": "a"}, {"text": "b"}]}]


def test_ollama_message_objecten_worden_gelezen():
    class Msg:
        role = "user"
        content = "hallo"
        tool_calls = None

    assert gemini.bouw_verzoek([Msg()])["contents"] == [{"role": "user", "parts": [{"text": "hallo"}]}]


def test_toolresultaat_gaat_nooit_naar_gemini():
    http = NepHttp(NepAntwoord(data=_tekst("x")))
    with pytest.raises(GeminiFout) as fout:
        _chat(http, [
            {"role": "user", "content": "open spotify"},
            {"role": "tool", "content": "C:\\Users\\rushi\\geheim.txt"},
        ])
    assert fout.value.soort == gemini.PRIVACY
    assert http.verzoeken == []  # er is niets verstuurd


def test_onbekende_rol_geweigerd():
    with pytest.raises(GeminiFout) as fout:
        gemini.bouw_verzoek([{"role": "geheim", "content": "x"}])
    assert fout.value.soort == gemini.PRIVACY


def test_leeg_verzoek_geweigerd():
    with pytest.raises(GeminiFout):
        gemini.bouw_verzoek([{"role": "system", "content": "alleen systeem"}])


def test_tools_worden_function_declarations():
    tools = [{
        "type": "function",
        "function": {
            "name": "open_program",
            "description": "  Open een\n   programma.  ",
            "parameters": {
                "type": "object",
                "properties": {
                    "program": {"type": "string", "description": "De naam.", "default": "x"},
                    "aantal": {"type": ["integer", "null"]},
                    "namen": {"type": "array", "items": {"type": "string", "minLength": 1}},
                },
                "required": ["program"],
                "additionalProperties": False,
            },
        },
    }, {"type": "function", "function": {"name": "pc_status", "description": "Status.",
                                         "parameters": {"type": "object", "properties": {}}}}]
    verzoek = gemini.bouw_verzoek([{"role": "user", "content": "open spotify"}], tools=tools)
    declaraties = verzoek["tools"][0]["functionDeclarations"]
    assert declaraties[0] == {
        "name": "open_program",
        "description": "Open een programma.",
        "parameters": {
            "type": "object",
            "properties": {
                "program": {"type": "string", "description": "De naam."},
                "aantal": {"type": "integer"},
                "namen": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["program"],
        },
    }
    assert declaraties[1] == {"name": "pc_status", "description": "Status."}


def test_zoeken_json_temperatuur_en_denkniveau():
    verzoek = gemini.bouw_verzoek([{"role": "user", "content": "x"}], zoeken=True, json_mode=True,
                                  temperature=0, denkniveau="low")
    assert verzoek["tools"] == [{"google_search": {}}]
    assert verzoek["generationConfig"] == {
        "temperature": 0.0,
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingLevel": "low"},
    }


def test_eerdere_tool_call_van_model_blijft_bewaard():
    verzoek = gemini.bouw_verzoek([
        {"role": "user", "content": "open spotify"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "open_program", "arguments": {"program": "spotify"}}}]},
        {"role": "user", "content": "en discord"},
    ])
    assert verzoek["contents"][1] == {"role": "model", "parts": [
        {"functionCall": {"name": "open_program", "args": {"program": "spotify"}}}]}


# ---------------------------------------------------------------------
# Antwoord
# ---------------------------------------------------------------------

def test_tekstantwoord_in_ollama_vorm():
    antwoord = _chat(NepHttp(NepAntwoord(data=_tekst("Parijs."))))
    assert antwoord.message.content == "Parijs."
    assert antwoord.message.tool_calls is None
    assert antwoord.message.role == "assistant"
    # Ook als dict, zoals sommige code het leest.
    assert antwoord.get("message", {}).get("content", "") == "Parijs."
    assert antwoord.prompt_eval_count == 12 and antwoord.eval_count == 5


def test_tool_call_in_ollama_vorm():
    data = {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "open_program", "args": {"program": "spotify"}}, "thoughtSignature": "abc"},
    ]}}]}
    antwoord = _chat(NepHttp(NepAntwoord(data=data)))
    call = antwoord.message.tool_calls[0]
    assert call.function.name == "open_program"
    assert call.function.arguments == {"program": "spotify"}
    assert antwoord.message.content == ""


def test_gedachten_worden_niet_uitgesproken():
    data = {"candidates": [{"content": {"parts": [
        {"text": "Eerst nadenken...", "thought": True},
        {"text": "Berlijn."},
    ]}}]}
    assert _chat(NepHttp(NepAntwoord(data=data))).message.content == "Berlijn."


def test_bronnen_van_google_zoeken():
    data = _tekst("Verstappen won.", groundingMetadata={"groundingChunks": [
        {"web": {"uri": "https://a.nl/x", "title": "a.nl"}},
        {"web": {"uri": "https://a.nl/x", "title": "a.nl"}},
        {"web": {"uri": "https://b.com/y", "title": "b.com"}},
    ]})
    antwoord = _chat(NepHttp(NepAntwoord(data=data)), zoeken=True)
    assert antwoord.bronnen == [{"url": "https://a.nl/x", "titel": "a.nl"}, {"url": "https://b.com/y", "titel": "b.com"}]


@pytest.mark.parametrize("data", [
    {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}},
    {},
    {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]},
])
def test_geen_antwoord_is_leeg(data):
    with pytest.raises(GeminiFout) as fout:
        _chat(NepHttp(NepAntwoord(data=data)))
    assert fout.value.soort == gemini.LEEG


# ---------------------------------------------------------------------
# Fouten
# ---------------------------------------------------------------------

def test_geen_sleutel(monkeypatch):
    import config

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    http = NepHttp()
    with pytest.raises(GeminiFout) as fout:
        gemini.chat([{"role": "user", "content": "x"}], http=http)
    assert fout.value.soort == gemini.GEEN_SLEUTEL
    assert http.verzoeken == []


@pytest.mark.parametrize("status, data, soort", [
    (429, {"error": {"message": "Resource has been exhausted"}}, gemini.LIMIET),
    (500, None, gemini.SERVER),
    (503, {"error": {"message": "overloaded"}}, gemini.SERVER),
    (400, {"error": {"message": "API key not valid. Please pass a valid API key."}}, gemini.SLEUTEL),
    (403, {"error": {"message": "Permission denied"}}, gemini.SLEUTEL),
    (404, {"error": {"message": "models/gemini-x is not found"}}, gemini.WEIGERING),
    (400, {"error": {"message": "Invalid argument"}}, gemini.WEIGERING),
])
def test_http_fouten(status, data, soort):
    # Bij 503 komt er één herhaling: die mislukt hier ook.
    http = NepHttp(NepAntwoord(status=status, data=data), NepAntwoord(status=status, data=data))
    with pytest.raises(GeminiFout) as fout:
        _chat(http)
    assert fout.value.soort == soort
    assert fout.value.status == status


def test_503_een_keer_opnieuw_en_dan_goed():
    http = NepHttp(NepAntwoord(status=503, data={"error": {"message": "overloaded"}}), NepAntwoord(data=_tekst("Hoi.")))
    assert _chat(http).message.content == "Hoi."
    assert len(http.verzoeken) == 2


def test_andere_fout_niet_herhaald():
    http = NepHttp(NepAntwoord(status=500, data={}), NepAntwoord(data=_tekst("Hoi.")))
    with pytest.raises(GeminiFout):
        _chat(http)
    assert len(http.verzoeken) == 1


def test_limiet_met_wachttijd():
    with pytest.raises(GeminiFout) as fout:
        _chat(NepHttp(NepAntwoord(status=429, data={}, headers={"Retry-After": "30"})))
    assert fout.value.wacht == 30.0


def test_netwerkfout_zonder_url_of_sleutel():
    fout_in = ConnectionError(f"https://x/?key={SLEUTEL} geweigerd")
    with pytest.raises(GeminiFout) as fout:
        _chat(NepHttp(fout=fout_in))
    assert fout.value.soort == gemini.NETWERK
    assert SLEUTEL not in str(fout.value)


def test_onleesbaar_antwoord():
    with pytest.raises(GeminiFout) as fout:
        _chat(NepHttp(NepAntwoord(status=200, data=None)))
    assert fout.value.soort == gemini.SERVER


def test_denkniveau_onbekend_dan_opnieuw_zonder():
    http = NepHttp(
        NepAntwoord(status=400, data={"error": {"message": "Unknown name \"thinkingLevel\" at 'generation_config.thinking_config'"}}),
        NepAntwoord(data=_tekst("Hoi.")),
    )
    antwoord = _chat(http, denkniveau="low")
    assert antwoord.message.content == "Hoi."
    assert "thinkingConfig" in http.verzoeken[0]["json"]["generationConfig"]
    assert "thinkingConfig" not in http.verzoeken[1]["json"].get("generationConfig", {})


def test_andere_400_niet_opnieuw():
    http = NepHttp(NepAntwoord(status=400, data={"error": {"message": "Invalid argument"}}), NepAntwoord(data=_tekst("x")))
    with pytest.raises(GeminiFout):
        _chat(http, denkniveau="low")
    assert len(http.verzoeken) == 1


# ---------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------

def _sse(tekst, thought=False):
    part = {"text": tekst}
    if thought:
        part["thought"] = True
    return "data: " + json.dumps({"candidates": [{"content": {"parts": [part]}}]})


def _stream(http, **kw):
    return list(gemini.chat_stream([{"role": "user", "content": "vertel iets"}], sleutel=SLEUTEL,
                                   model="gemini-test", timeout=3, denkniveau="", http=http, **kw))


def test_stream_geeft_stukjes():
    http = NepHttp(NepAntwoord(regels=["", _sse("denk", thought=True), _sse("Het is "), ": keepalive", _sse("blauw.")]))
    assert _stream(http) == ["Het is ", "blauw."]
    verzoek = http.verzoeken[0]
    assert verzoek["url"].endswith(":streamGenerateContent?alt=sse")
    assert verzoek["stream"] is True
    assert SLEUTEL not in verzoek["url"]


def test_stream_fout_voor_eerste_tekst():
    http = NepHttp(NepAntwoord(regels=[ConnectionError("weg")]))
    with pytest.raises(GeminiFout) as fout:
        _stream(http)
    assert fout.value.soort == gemini.NETWERK


def test_stream_fout_na_eerste_tekst_houdt_tekst():
    http = NepHttp(NepAntwoord(regels=[_sse("Het is "), ConnectionError("weg")]))
    assert _stream(http) == ["Het is "]


def test_stream_zonder_tekst_is_leeg():
    with pytest.raises(GeminiFout) as fout:
        _stream(NepHttp(NepAntwoord(regels=[_sse("x", thought=True)])))
    assert fout.value.soort == gemini.LEEG


def test_stream_http_fout():
    with pytest.raises(GeminiFout) as fout:
        _stream(NepHttp(NepAntwoord(status=429, data={})))
    assert fout.value.soort == gemini.LIMIET


# ---------------------------------------------------------------------
# Opdrachtregel en instellingen
# ---------------------------------------------------------------------

def test_main_meldt_fout_zonder_sleutel(monkeypatch, capsys):
    import config

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert gemini._main(["hallo"]) == 1
    assert "geen_sleutel" in capsys.readouterr().out


def test_main_toont_antwoord_en_bronnen(monkeypatch, capsys):
    monkeypatch.setattr(gemini, "chat", lambda *a, **kw: gemini.Antwoord(
        "Verstappen.", bronnen=[{"url": "https://a.nl", "titel": "a.nl"}]))
    assert gemini._main(["--zoek", "wie won?"]) == 0
    uit = capsys.readouterr().out
    assert "Verstappen." in uit and "https://a.nl" in uit


def test_instellingen_in_env_example():
    from pathlib import Path

    tekst = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    for naam in ("GEMINI_API_KEY=", "GEMINI_MODEL=", "GEMINI_DENKNIVEAU=", "GEMINI_TIMEOUT="):
        assert naam in tekst
    regel = next(r for r in tekst.splitlines() if r.startswith("GEMINI_API_KEY="))
    assert regel == "GEMINI_API_KEY="  # nooit een echte sleutel in het voorbeeld


def test_env_staat_buiten_git():
    from pathlib import Path

    regels = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in regels
