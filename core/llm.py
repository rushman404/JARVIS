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


def chat(messages, tools=None, json_mode=False, **opties):
    """Roep ``ollama.chat`` aan met de instellingen uit config.py.

    - ``tools`` of ``json_mode=True`` -> temperatuur AI_TEMPERATURE_TOOLS.
    - Gewone gesprekken -> temperatuur AI_TEMPERATURE_CHAT.
    - Extra Ollama-opties kunnen via ``options={...}`` of losse kwargs.
    Duur en tokengebruik (prompt_eval_count/eval_count) worden gelogd.
    """
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


def chat_stream(messages, tools=None, json_mode=False, **opties):
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
    """
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
