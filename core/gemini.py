"""Gemini-koppeling (Fase 25, M1): het slimme brein in de cloud.

Praat met de Gemini API (``generateContent``) via ``requests``, zonder extra
bibliotheek. Het antwoord heeft dezelfde vorm als een Ollama-antwoord
(``antwoord.message.content`` en ``antwoord.message.tool_calls`` met
``.function.name`` / ``.function.arguments``), zodat de bestaande code in
``core/ai.py`` en ``core/agent.py`` niet hoeft te veranderen.

Deze module beslist NIET wat er naar Gemini mag: dat doet de privacy-poort
(M3). Twee harde grenzen zitten wel hier:

* een toolresultaat (rol ``tool``) gaat nooit naar Gemini; herstel na een
  mislukte actie doet Ollama lokaal (besluit 2026-10-30);
* de API-sleutel gaat alleen in de header ``x-goog-api-key``, nooit in de
  URL of een log.

Fouten worden een :class:`GeminiFout` met een ``soort``, zodat de
terugval (M2) weet of het zin heeft het straks opnieuw te proberen.

Snel proberen met uw sleutel in ``.env``::

    python -m core.gemini "waarom is de lucht blauw?"
    python -m core.gemini --zoek "wie won gisteren de Formule 1?"
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/"

# Soorten fouten (GeminiFout.soort).
GEEN_SLEUTEL = "geen_sleutel"  # GEMINI_API_KEY ontbreekt
SLEUTEL = "sleutel"            # sleutel ongeldig of ingetrokken
NETWERK = "netwerk"            # geen internet, time-out
LIMIET = "limiet"              # 429: gratis limiet bereikt
SERVER = "server"              # 5xx bij Google
WEIGERING = "weigering"        # ander 4xx-antwoord (verkeerd verzoek, model onbekend)
LEEG = "leeg"                  # geen antwoord (bijv. geblokkeerd)
PRIVACY = "privacy"            # verzoek bevat iets dat nooit naar Gemini mag

# Velden van een tool-schema die Gemini begrijpt; de rest valt weg.
_SCHEMA_VELDEN = ("type", "description", "properties", "required", "items", "enum")


class GeminiFout(Exception):
    def __init__(self, melding, soort, status=None, wacht=None):
        super().__init__(melding)
        self.soort = soort
        self.status = status
        self.wacht = wacht  # seconden tot opnieuw proberen (bij een limiet), of None


# ---------------------------------------------------------------------
# Antwoord in Ollama-vorm
# ---------------------------------------------------------------------

class _Functie:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, name, arguments):
        self.function = _Functie(name, arguments)


class _Bericht(dict):
    """Als ``ollama.Message``: attributen én ``bericht.get("content")``."""

    def __init__(self, content, tool_calls):
        super().__init__(role="assistant", content=content, tool_calls=tool_calls)

    @property
    def role(self):
        return self["role"]

    @property
    def content(self):
        return self["content"]

    @property
    def tool_calls(self):
        return self["tool_calls"]


class Antwoord(dict):
    """Als ``ollama.ChatResponse``, plus de bronnen van Google Zoeken."""

    def __init__(self, content, tool_calls=None, bronnen=None, model="", tokens=None):
        super().__init__(message=_Bericht(content, tool_calls or None), model=model)
        self.bronnen = bronnen or []
        tokens = tokens or {}
        self.prompt_eval_count = tokens.get("promptTokenCount")
        self.eval_count = tokens.get("candidatesTokenCount")

    @property
    def message(self):
        return self["message"]

    @property
    def model(self):
        return self["model"]


# ---------------------------------------------------------------------
# Verzoek opbouwen
# ---------------------------------------------------------------------

def _veld(bericht, naam, standaard=None):
    if isinstance(bericht, dict):
        return bericht.get(naam, standaard)
    return getattr(bericht, naam, standaard)


def _argumenten(arguments):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return {}
    return dict(arguments or {})


def _naar_contents(messages):
    """(systeemtekst, contents) uit berichten in Ollama-vorm."""

    systeem = []
    contents = []
    for bericht in messages or []:
        rol = _veld(bericht, "role")
        tekst = str(_veld(bericht, "content") or "")
        if rol == "system":
            if tekst.strip():
                systeem.append(tekst.strip())
            continue
        if rol == "tool":
            raise GeminiFout("Een toolresultaat gaat nooit naar Gemini.", PRIVACY)
        if rol not in ("user", "assistant"):
            raise GeminiFout(f"Onbekende rol in het verzoek: {rol!r}.", PRIVACY)

        parts = [{"text": tekst}] if tekst else []
        if rol == "assistant":
            for call in _veld(bericht, "tool_calls") or []:
                functie = _veld(call, "function")
                parts.append({"functionCall": {
                    "name": _veld(functie, "name"),
                    "args": _argumenten(_veld(functie, "arguments")),
                }})
        if not parts:
            continue
        gemini_rol = "model" if rol == "assistant" else "user"
        if contents and contents[-1]["role"] == gemini_rol:
            contents[-1]["parts"].extend(parts)  # Gemini wil afwisselende rollen
        else:
            contents.append({"role": gemini_rol, "parts": parts})

    if not contents:
        raise GeminiFout("Er staat geen vraag in het verzoek.", WEIGERING)
    return "\n\n".join(systeem), contents


def _schema(schema):
    """Een tool-schema (JSON Schema) teruggebracht tot wat Gemini kent."""

    if not isinstance(schema, dict):
        return {"type": "string"}
    uit = {}
    for sleutel in _SCHEMA_VELDEN:
        if sleutel not in schema:
            continue
        waarde = schema[sleutel]
        if sleutel == "type":
            if isinstance(waarde, list):
                waarde = next((t for t in waarde if t != "null"), "string")
            waarde = str(waarde).lower()
        elif sleutel == "properties":
            waarde = {naam: _schema(sub) for naam, sub in (waarde or {}).items()}
        elif sleutel == "items":
            waarde = _schema(waarde)
        elif sleutel == "description":
            waarde = " ".join(str(waarde).split())
        uit[sleutel] = waarde
    if uit.get("type") == "object" and not uit.get("properties"):
        uit.pop("required", None)
    return uit


def _naar_tools(tools, zoeken):
    declaraties = []
    for tool in tools or []:
        functie = tool.get("function", tool) if isinstance(tool, dict) else {}
        naam = functie.get("name")
        if not naam:
            continue
        declaratie = {"name": naam, "description": " ".join(str(functie.get("description") or "").split())}
        parameters = functie.get("parameters")
        if isinstance(parameters, dict) and parameters.get("properties"):
            declaratie["parameters"] = _schema(parameters)
        declaraties.append(declaratie)
    uit = []
    if declaraties:
        uit.append({"functionDeclarations": declaraties})
    if zoeken:
        uit.append({"google_search": {}})
    return uit


def bouw_verzoek(messages, tools=None, json_mode=False, zoeken=False,
                 temperature=None, denkniveau=None):
    """Het JSON-lichaam voor ``generateContent`` (los te testen)."""

    systeem, contents = _naar_contents(messages)
    verzoek = {"contents": contents}
    if systeem:
        verzoek["systemInstruction"] = {"parts": [{"text": systeem}]}
    gemini_tools = _naar_tools(tools, zoeken)
    if gemini_tools:
        verzoek["tools"] = gemini_tools
    config = {}
    if temperature is not None:
        config["temperature"] = float(temperature)
    if json_mode:
        config["responseMimeType"] = "application/json"
    if denkniveau:
        config["thinkingConfig"] = {"thinkingLevel": denkniveau}
    if config:
        verzoek["generationConfig"] = config
    return verzoek


# ---------------------------------------------------------------------
# Antwoord lezen
# ---------------------------------------------------------------------

def _bronnen(kandidaat):
    bronnen = []
    for chunk in ((kandidaat.get("groundingMetadata") or {}).get("groundingChunks") or []):
        web = chunk.get("web") or {}
        if web.get("uri") and not any(b["url"] == web["uri"] for b in bronnen):
            bronnen.append({"url": web["uri"], "titel": web.get("title") or ""})
    return bronnen


def lees_antwoord(data, model=""):
    """Een ``GenerateContentResponse`` (dict) als :class:`Antwoord`."""

    kandidaten = (data or {}).get("candidates") or []
    if not kandidaten:
        reden = ((data or {}).get("promptFeedback") or {}).get("blockReason") or "geen antwoord"
        raise GeminiFout(f"Gemini gaf geen antwoord ({reden}).", LEEG)
    kandidaat = kandidaten[0]
    teksten = []
    calls = []
    for part in ((kandidaat.get("content") or {}).get("parts") or []):
        if part.get("thought"):
            continue  # de "gedachten" van het model spreken we niet uit
        if part.get("functionCall"):
            call = part["functionCall"]
            calls.append(_ToolCall(call.get("name") or "", _argumenten(call.get("args"))))
        elif part.get("text"):
            teksten.append(part["text"])
    if not teksten and not calls:
        reden = kandidaat.get("finishReason") or "leeg"
        raise GeminiFout(f"Gemini gaf geen antwoord ({reden}).", LEEG)
    return Antwoord("".join(teksten), calls, _bronnen(kandidaat), model,
                    (data or {}).get("usageMetadata"))


def _fout_uit_antwoord(r):
    try:
        melding = str(((r.json() or {}).get("error") or {}).get("message") or "")
    except ValueError:
        melding = ""
    melding = melding[:200]
    status = r.status_code
    if status == 429:
        wacht = None
        try:
            wacht = float(r.headers.get("Retry-After"))
        except (TypeError, ValueError):
            pass
        return GeminiFout("De gratis limiet van Gemini is bereikt.", LIMIET, status, wacht)
    if status >= 500:
        return GeminiFout(f"Gemini had een storing (HTTP {status}).", SERVER, status)
    if status in (401, 403) or "api key" in melding.lower():
        return GeminiFout("De Gemini-sleutel is ongeldig of ingetrokken.", SLEUTEL, status)
    return GeminiFout(f"Gemini weigerde het verzoek (HTTP {status}): {melding}", WEIGERING, status)


# ---------------------------------------------------------------------
# Aanroepen
# ---------------------------------------------------------------------

def _instellingen(sleutel, model, timeout, denkniveau):
    from config import GEMINI_API_KEY, GEMINI_DENKNIVEAU, GEMINI_MODEL, GEMINI_TIMEOUT

    sleutel = sleutel if sleutel is not None else GEMINI_API_KEY
    if not sleutel:
        raise GeminiFout("Er staat geen GEMINI_API_KEY in .env.", GEEN_SLEUTEL)
    return (sleutel, model or GEMINI_MODEL, GEMINI_TIMEOUT if timeout is None else timeout,
            GEMINI_DENKNIVEAU if denkniveau is None else denkniveau)


def _http(http):
    if http is not None:
        return http
    import requests

    return requests


def _post(http, url, sleutel, verzoek, timeout, stream=False):
    try:
        return http.post(
            url,
            headers={"x-goog-api-key": sleutel, "Content-Type": "application/json"},
            json=verzoek,
            timeout=timeout,
            stream=stream,
        )
    except Exception as fout:
        # De melding van requests kan de URL bevatten; die laten we weg.
        raise GeminiFout(f"Gemini reageerde niet ({type(fout).__name__}).", NETWERK) from None


def _met_denkterugval(stuur, verzoek):
    """Kent het model ``thinkingConfig`` niet (400), dan één keer zonder."""

    r = stuur(verzoek)
    if r.status_code == 400 and "generationConfig" in verzoek and "thinkingConfig" in verzoek["generationConfig"]:
        try:
            melding = json.dumps(r.json())
        except ValueError:
            melding = ""
        if "thinking" in melding.lower():
            logger.info("Gemini: model kent het denkniveau niet; opnieuw zonder.")
            verzoek = dict(verzoek, generationConfig={
                k: v for k, v in verzoek["generationConfig"].items() if k != "thinkingConfig"})
            r = stuur(verzoek)
    return r


def chat(messages, tools=None, json_mode=False, zoeken=False, temperature=None,
         sleutel=None, model=None, timeout=None, denkniveau=None, http=None):
    """Eén volledig antwoord van Gemini, als :class:`Antwoord` (Ollama-vorm).

    ``zoeken=True`` zet Google Zoeken aan; de gebruikte bronnen staan dan in
    ``antwoord.bronnen``. Gooit :class:`GeminiFout` bij elk probleem.
    """

    sleutel, model, timeout, denkniveau = _instellingen(sleutel, model, timeout, denkniveau)
    verzoek = bouw_verzoek(messages, tools, json_mode, zoeken, temperature, denkniveau)
    http = _http(http)
    url = f"{API}{model}:generateContent"

    begin = time.perf_counter()
    r = _met_denkterugval(lambda v: _post(http, url, sleutel, v, timeout), verzoek)
    if r.status_code != 200:
        raise _fout_uit_antwoord(r)
    try:
        data = r.json()
    except ValueError:
        raise GeminiFout("Gemini gaf een onleesbaar antwoord.", SERVER, r.status_code) from None
    antwoord = lees_antwoord(data, model)
    logger.info(
        "Gemini chat model=%s duur=%.2fs prompt_tokens=%s eval_tokens=%s tools=%s json=%s zoeken=%s",
        model, time.perf_counter() - begin, antwoord.prompt_eval_count, antwoord.eval_count,
        bool(tools), json_mode, zoeken,
    )
    return antwoord


def chat_stream(messages, zoeken=False, temperature=None, sleutel=None, model=None,
                timeout=None, denkniveau=None, http=None):
    """Het antwoord van Gemini stukje voor stukje (generator), zoals
    ``core.llm.chat_stream``. Alleen tekst; tools horen bij :func:`chat`.

    Een fout vóór de eerste tekst wordt een :class:`GeminiFout`, zodat de
    terugval (M2) het gewoon met Ollama kan doen.
    """

    sleutel, model, timeout, denkniveau = _instellingen(sleutel, model, timeout, denkniveau)
    verzoek = bouw_verzoek(messages, None, False, zoeken, temperature, denkniveau)
    http = _http(http)
    url = f"{API}{model}:streamGenerateContent?alt=sse"

    begin = time.perf_counter()
    r = _met_denkterugval(lambda v: _post(http, url, sleutel, v, timeout, stream=True), verzoek)
    if r.status_code != 200:
        raise _fout_uit_antwoord(r)

    eerste = None
    iets = False
    try:
        for regel in r.iter_lines(decode_unicode=True):
            if not regel or not regel.startswith("data:"):
                continue
            try:
                data = json.loads(regel[5:].strip())
            except ValueError:
                continue
            for kandidaat in data.get("candidates") or []:
                for part in ((kandidaat.get("content") or {}).get("parts") or []):
                    if part.get("thought") or not part.get("text"):
                        continue
                    if eerste is None:
                        eerste = time.perf_counter() - begin
                    iets = True
                    yield part["text"]
    except GeminiFout:
        raise
    except Exception as fout:
        if not iets:
            raise GeminiFout(f"Gemini-stream brak af ({type(fout).__name__}).", NETWERK) from None
        logger.warning("Gemini-stream brak af na de eerste tekst: %s", type(fout).__name__)
    if not iets:
        raise GeminiFout("Gemini gaf geen tekst terug in de stream.", LEEG)
    logger.info("Gemini stream model=%s eerste_tekst=%.2fs totaal=%.2fs",
                model, eerste or 0.0, time.perf_counter() - begin)


# ---------------------------------------------------------------------
# Proberen vanaf de opdrachtregel
# ---------------------------------------------------------------------

def _main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Stel Gemini één vraag (test van de koppeling).")
    parser.add_argument("vraag")
    parser.add_argument("--zoek", action="store_true", help="met Google Zoeken")
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    try:
        antwoord = chat([{"role": "user", "content": args.vraag}], zoeken=args.zoek, model=args.model)
    except GeminiFout as fout:
        print(f"Mislukt ({fout.soort}): {fout}")
        return 1
    print(antwoord.message.content)
    for bron in antwoord.bronnen:
        print(f"- {bron['titel']}: {bron['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
