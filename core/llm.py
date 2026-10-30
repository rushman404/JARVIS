"""Eén centrale plek voor alle LLM-aanroepen (Ollama).

Alle modules praten via :func:`chat` met Ollama, zodat model,
contextgrootte, temperatuur en ``keep_alive`` uit ``config.py`` overal
hetzelfde zijn en elke aanroep gelogd wordt (duur + tokengebruik).

- Aanroepen met tools of JSON gebruiken ``AI_TEMPERATURE_TOOLS`` (0).
- Gewone gesprekken gebruiken ``AI_TEMPERATURE_CHAT`` (standaard 0.3).

Fase 17 (Gesprek & Dialoog): :func:`chat_stream` levert het antwoord token
voor token, zodat JARVIS al kan beginnen met praten terwijl het model nog
genereert.
"""
import logging
import threading
import time

import ollama

from config import (
    AI_KEEP_ALIVE,
    AI_MODEL,
    AI_NUM_CTX,
    AI_TEMPERATURE_TOOLS,
)

try:
    from config import AI_TEMPERATURE_CHAT
except ImportError:  # pragma: no cover - config hoort dit te hebben
    AI_TEMPERATURE_CHAT = 0.3

logger = logging.getLogger(__name__)


def _model_names(list_response):
    """Modelnamen uit een ollama.list()-antwoord (oud dict of nieuw object)."""
    if isinstance(list_response, dict):
        models = list_response.get("models", []) or []
    else:
        models = getattr(list_response, "models", []) or []

    names = set()
    for item in models:
        if isinstance(item, dict):
            name = item.get("model") or item.get("name")
        else:
            name = getattr(item, "model", None) or getattr(item, "name", None)
        if name:
            names.add(name)
            names.add(name.split(":")[0])
    return names


def check_model_available():
    """Controleer eenmalig bij het opstarten of AI_MODEL in Ollama staat.

    Geeft True/False terug. Ontbreekt het model, dan wordt een duidelijke
    melding gelogd ("draai ollama pull ..."). Is Ollama niet bereikbaar,
    dan volgt een waarschuwing.
    """
    try:
        listing = ollama.list()
    except Exception as error:
        logger.warning("Kon Ollama niet bereiken: %s", error)
        return False

    if AI_MODEL in _model_names(listing):
        logger.info("Model '%s' gevonden in Ollama.", AI_MODEL)
        return True

    logger.error(
        "Het model '%s' is niet gevonden, draai: ollama pull %s",
        AI_MODEL,
        AI_MODEL,
    )
    return False


def laad_model():
    """Laadt het AI-model alvast in het geheugen (Fase 19, M4).

    Na het wakker worden: terwijl u uw opdracht inspreekt, staat het model
    al klaar. Met dezelfde ``num_ctx`` als bij ``chat``, anders laadt
    Ollama het bij de eerste vraag nog een keer opnieuw.
    """
    ollama.generate(
        model=AI_MODEL, prompt="", keep_alive=AI_KEEP_ALIVE, options={"num_ctx": AI_NUM_CTX}
    )


def ontlaad_model():
    """Haalt het AI-model uit het geheugen (keep_alive 0) als JARVIS slaapt."""
    ollama.generate(model=AI_MODEL, prompt="", keep_alive=0)


def op_achtergrond(fn, naam="jarvis-llm"):
    """Voert ``fn`` uit in een achtergrondthread; een fout wordt alleen gelogd.

    Zo wacht het slapen of wakker worden nooit op Ollama.
    """

    def _draai():
        try:
            fn()
        except Exception as fout:
            logger.info("%s overgeslagen: %s", getattr(fn, "__name__", "LLM-actie"), fout)

    thread = threading.Thread(target=_draai, name=naam, daemon=True)
    thread.start()
    return thread


def _chat_kwargs(messages, tools, json_mode, opties):
    """Bouwt de kwargs voor ``ollama.chat`` uit config.py + losse opties.

    Gedeeld door :func:`chat` (volledig antwoord) en :func:`chat_stream`
    (token voor token), zodat beide exact dezelfde instellingen gebruiken.
    """
    temperature = opties.pop("temperature", None)
    if temperature is None:
        temperature = AI_TEMPERATURE_TOOLS if (tools or json_mode) else AI_TEMPERATURE_CHAT

    options = {"num_ctx": AI_NUM_CTX, "temperature": temperature}
    options.update(opties.pop("options", None) or {})

    kwargs = {
        "model": AI_MODEL,
        "messages": messages,
        "options": options,
        "keep_alive": AI_KEEP_ALIVE,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if json_mode:
        kwargs["format"] = "json"
    kwargs.update(opties)
    return kwargs


def _warn_if_prompt_near_limit(prompt_tokens):
    """Waarschuw als de prompt de contextgrens nadert (tools vallen anders af).

    De prompt (systeemtekst + tools) mag niet tegen de contextgrens
    aanlopen: dan kapt Ollama af en ziet het model de tools niet meer.
    """
    if (
        isinstance(prompt_tokens, (int, float))
        and not isinstance(prompt_tokens, bool)
        and prompt_tokens >= 0.9 * AI_NUM_CTX
    ):
        logger.warning(
            "Prompt vult de context; tools worden mogelijk afgekapt "
            "(prompt_tokens=%s van num_ctx=%s). Verhoog AI_NUM_CTX of "
            "stuur minder tools mee.",
            prompt_tokens,
            AI_NUM_CTX,
        )


def chat(messages, tools=None, json_mode=False, cloud=False, zoeken=False,
         terugval_messages=None, terugval_tools=None, alleen_cloud=False, **opties):
    """Roep ``ollama.chat`` aan met de instellingen uit config.py.

    Met ``cloud=True`` (Fase 25) probeert JARVIS eerst Gemini en valt hij bij
    elk probleem terug op Ollama. Alleen een aanroeper die de privacy-poort
    al gepasseerd is, zet ``cloud=True``; standaard gaat er niets naar de
    cloud. Vlak voor verzending controleert de poort het hele verzoek nog
    eens (``privacy_poort.controleer``); faalt dat, dan doet Ollama het.

    - ``terugval_messages`` / ``terugval_tools``: wat Ollama krijgt als Gemini
      het niet doet (bijv. de lokale berichten mét geheugen en context);
      standaard dezelfde als voor Gemini.
    - ``zoeken=True`` zet bij Gemini Google Zoeken aan.
    - ``alleen_cloud=True``: geen Ollama-terugval; None als Gemini het niet
      deed (bijv. opzoeken: dan zoekt de aanroeper zelf via DuckDuckGo).
    - ``tools`` of ``json_mode=True`` -> temperatuur AI_TEMPERATURE_TOOLS.
    - Gewone gesprekken -> temperatuur AI_TEMPERATURE_CHAT.
    - Extra Ollama-opties kunnen via ``options={...}`` of losse kwargs.
    Duur en tokengebruik (prompt_eval_count/eval_count) worden gelogd.
    """
    if cloud and _verzoek_veilig(messages, tools):
        antwoord = _probeer_gemini(
            lambda gemini: gemini.chat(
                messages, tools=tools, json_mode=json_mode, zoeken=zoeken,
                temperature=opties.get("temperature"),
            )
        )
        if antwoord is not None:
            _zet_bron("gemini")
            return antwoord
    if alleen_cloud:
        return None

    _zet_bron("ollama")
    if terugval_messages is not None:
        messages = terugval_messages
    if terugval_tools is not None:
        tools = terugval_tools
    kwargs = _chat_kwargs(messages, tools, json_mode, opties)

    started = time.perf_counter()
    response = ollama.chat(**kwargs)
    duration = time.perf_counter() - started

    prompt_tokens = getattr(response, "prompt_eval_count", None)

    logger.info(
        "LLM chat model=%s duur=%.2fs prompt_tokens=%s eval_tokens=%s "
        "tools=%s json=%s",
        AI_MODEL,
        duration,
        prompt_tokens,
        getattr(response, "eval_count", None),
        bool(tools),
        json_mode,
    )

    _warn_if_prompt_near_limit(prompt_tokens)

    return response


def _stream_text(chunk):
    """Nieuwe tekst uit één stream-chunk (oud dict- of nieuw object-formaat)."""
    message = chunk.get("message") if isinstance(chunk, dict) else getattr(chunk, "message", None)
    if message is None:
        return ""
    if isinstance(message, dict):
        return message.get("content") or ""
    return getattr(message, "content", None) or ""


def _stream_tool_calls(chunk):
    """Tool-calls uit één stream-chunk (leeg als er geen zijn)."""
    message = chunk.get("message") if isinstance(chunk, dict) else getattr(chunk, "message", None)
    if message is None:
        return []
    if isinstance(message, dict):
        return message.get("tool_calls") or []
    return getattr(message, "tool_calls", None) or []


def chat_stream(messages, tools=None, json_mode=False, cloud=False,
                terugval_messages=None, **opties):
    """Stream een Ollama-antwoord en yield de tekst per chunk (generator).

    Gebruikt dezelfde config-instellingen als :func:`chat`, maar met
    ``stream=True``. Elke ``yield`` is het stukje tekst dat in die chunk
    nieuw binnenkomt, zodat de aanroeper (Fase 17: spraak) direct kan
    beginnen terwijl het model nog genereert.

    Let op: dit is de gespreksroute. Voor tool-calls en JSON-modus is
    :func:`chat` de juiste keuze; komen er in de stream tóch tool-calls
    voor, dan wordt dat gelogd en gaat de (lege) tekst gewoon door.

    Na de laatste chunk worden de tijd tot de eerste token (latency) en
    het tokengebruik gelogd.

    Met ``cloud=True`` (Fase 25, alleen tekst): eerst Gemini, na de
    privacy-controle. Mislukt die vóór de eerste tekst, dan streamt Ollama
    het antwoord (met ``terugval_messages`` als die er zijn).
    """
    if cloud and tools is None and not json_mode and _verzoek_veilig(messages, None):
        stream = _gemini_stream(messages, opties.get("temperature"))
        if stream is not None:
            _zet_bron("gemini")
            yield from stream
            return

    _zet_bron("ollama")
    if terugval_messages is not None:
        messages = terugval_messages

    kwargs = _chat_kwargs(messages, tools, json_mode, opties)
    kwargs["stream"] = True

    started = time.perf_counter()
    first_at = None
    last_chunk = None
    gezien_tool_call = False

    for chunk in ollama.chat(**kwargs):
        if first_at is None:
            first_at = time.perf_counter()
        last_chunk = chunk

        if _stream_tool_calls(chunk):
            gezien_tool_call = True

        text = _stream_text(chunk)
        if text:
            yield text

    duration = time.perf_counter() - started
    first_latency = (first_at - started) if first_at is not None else duration

    logger.info(
        "LLM stream model=%s eerste_token=%.2fs duur=%.2fs prompt_tokens=%s "
        "eval_tokens=%s tools=%s json=%s",
        AI_MODEL,
        first_latency,
        duration,
        getattr(last_chunk, "prompt_eval_count", None),
        getattr(last_chunk, "eval_count", None),
        bool(tools),
        json_mode,
    )

    if gezien_tool_call:
        logger.warning(
            "Tool-call in stream ontvangen; gebruik chat() voor tool-aanroepen "
            "(tekst-streaming levert dan mogelijk niets op)."
        )

    _warn_if_prompt_near_limit(getattr(last_chunk, "prompt_eval_count", None))


# =========================================================
# Gemini eerst, Ollama als terugval (Fase 25, M2)
# =========================================================

# Na zo'n fout slaat JARVIS Gemini zoveel seconden over, zodat niet elke
# vraag eerst op een time-out wacht. Een fout die alleen bij dit verzoek
# hoort (weigering, leeg antwoord, privacy) valt alleen voor die ene vraag
# terug, zonder pauze.
GEMINI_PAUZE = {
    "netwerk": 30,
    "server": 60,
    "limiet": 300,
    "sleutel": 3600,
}
# "limit: 0": dit model zit niet in de gratis laag; opnieuw proberen heeft
# pas zin na een andere instelling of een herstart.
GEMINI_PAUZE_GEEN_GRATIS = 6 * 3600

MELDING_GEMINI_WEG = "Gemini is even niet bereikbaar, sir; ik gebruik het lokale model."
MELDING_GEMINI_LIMIET = "De gratis limiet van Gemini is op, sir; ik gebruik even het lokale model."
MELDING_GEMINI_TERUG = "Gemini werkt weer, sir."

_brein_lock = threading.Lock()
_brein = {
    "pauze_tot": 0.0,   # time.monotonic() waarop Gemini weer geprobeerd mag worden
    "reden": "",        # waarom Gemini nu niet gebruikt wordt
    "soort": "",        # soort van de laatste fout
    "tot": None,        # zelfde moment, als wandklok (voor het dashboard)
    "gemeld": False,    # is de gebruiker al verteld dat Ollama het overneemt?
}


def _klok():
    return time.monotonic()


def _wandklok():
    return time.time()


def _meld(tekst):
    """Een korte gesproken melding via de proactieve engine (indien actief).

    Net als andere systeemmeldingen: in de nacht- of stille modus wacht hij.
    """
    try:
        from core import proactive

        engine = proactive.peek_engine()
        if engine is not None:
            engine.meld(tekst, bron="brein")
    except Exception:
        logger.debug("Melding over het AI-brein mislukt", exc_info=True)


def _gemini_sleutel():
    try:
        from config import GEMINI_API_KEY
    except ImportError:
        return ""
    return GEMINI_API_KEY


def gemini_beschikbaar():
    """True als Gemini nu geprobeerd mag worden (sleutel en geen pauze)."""

    if not _gemini_sleutel():
        return False
    with _brein_lock:
        return _klok() >= _brein["pauze_tot"]


def _gemini_gelukt():
    with _brein_lock:
        was_gemeld = _brein["gemeld"]
        _brein.update(pauze_tot=0.0, reden="", soort="", tot=None, gemeld=False)
    if was_gemeld:
        logger.info("Gemini werkt weer.")
        _meld(MELDING_GEMINI_TERUG)


def _gemini_mislukt(fout):
    from core import gemini

    soort = getattr(fout, "soort", gemini.NETWERK)
    pauze = GEMINI_PAUZE.get(soort)
    if soort == gemini.LIMIET:
        if "limit: 0" in str(fout):
            pauze = GEMINI_PAUZE_GEEN_GRATIS
        elif getattr(fout, "wacht", None):
            pauze = max(1.0, float(fout.wacht))

    if soort == gemini.PRIVACY:
        logger.warning("Verzoek niet naar Gemini gestuurd (privacy): %s", fout)
    else:
        logger.warning("Gemini mislukt (%s): %s; Ollama neemt het over.", soort, fout)

    melden = False
    with _brein_lock:
        if pauze:
            _brein.update(
                pauze_tot=_klok() + pauze,
                reden=str(fout),
                soort=soort,
                tot=_wandklok() + pauze,
            )
            if not _brein["gemeld"]:
                _brein["gemeld"] = melden = True
    if melden:
        _meld(MELDING_GEMINI_LIMIET if soort == gemini.LIMIET else MELDING_GEMINI_WEG)


def _probeer_gemini(aanroep):
    """``aanroep(gemini)`` als Gemini mag; None = doe het met Ollama."""

    if not gemini_beschikbaar():
        return None
    from core import gemini

    try:
        antwoord = aanroep(gemini)
    except gemini.GeminiFout as fout:
        _gemini_mislukt(fout)
        return None
    except Exception as fout:  # een programmeerfout mag nooit een antwoord kosten
        logger.exception("Onverwachte fout bij Gemini; Ollama neemt het over.")
        _gemini_mislukt(gemini.GeminiFout(type(fout).__name__, gemini.WEIGERING))
        return None
    _gemini_gelukt()
    return antwoord


def _gemini_stream(messages, temperature):
    """Een Gemini-stream waarvan de eerste tekst al binnen is, of None."""

    def _start(gemini):
        stream = gemini.chat_stream(messages, temperature=temperature)
        return stream, next(stream)

    begin = _probeer_gemini(_start)
    if begin is None:
        return None
    stream, eerste = begin

    def _rest():
        yield eerste
        yield from stream

    return _rest()


def brein_status():
    """Welk AI-brein nu werkt, voor het Systeem-paneel."""

    from config import GEMINI_MODEL

    if not _gemini_sleutel():
        return {"brein": "ollama", "model": AI_MODEL, "reden": "geen Gemini-sleutel", "tot": None}
    with _brein_lock:
        pauze = _klok() < _brein["pauze_tot"]
        tot = _brein["tot"]
        soort = _brein["soort"]
    if pauze:
        return {
            "brein": "ollama",
            "model": AI_MODEL,
            "reden": "Gemini-limiet bereikt" if soort == "limiet" else "Gemini niet bereikbaar",
            "tot": time.strftime("%H:%M", time.localtime(tot)) if tot else None,
        }
    return {"brein": "gemini", "model": GEMINI_MODEL, "reden": "", "tot": None}


def _verzoek_veilig(messages, tools):
    """De laatste privacy-controle vóór Gemini (``privacy_poort.controleer``).

    Faalt die, dan gaat er niets naar buiten en doet Ollama het; dat hoort
    nooit te gebeuren, dus het staat als waarschuwing in de log.
    """
    try:
        from core import privacy_poort

        veilig, reden = privacy_poort.controleer(messages, tools)
    except Exception:
        logger.exception("Privacy-controle mislukt; niets naar Gemini.")
        return False
    if not veilig:
        logger.warning("Verzoek niet naar Gemini gestuurd (privacy: %s); Ollama doet het.", reden)
    return veilig


# Wie gaf het laatste antwoord in deze thread ("gemini" of "ollama")? Zo
# weet de aanroeper of een beurt in de Gemini-geschiedenis mag.
_bron = threading.local()


def _zet_bron(naam):
    _bron.naam = naam


def laatste_brein():
    """"gemini" of "ollama": wie beantwoordde de laatste aanroep (deze thread)."""

    return getattr(_bron, "naam", "ollama")


def _reset_brein():
    """Voor tests: Gemini weer beschikbaar, niets gemeld."""

    with _brein_lock:
        _brein.update(pauze_tot=0.0, reden="", soort="", tot=None, gemeld=False)
