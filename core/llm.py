"""Eén centrale plek voor alle LLM-aanroepen (Ollama).

Alle modules praten via :func:`chat` met Ollama, zodat model,
contextgrootte, temperatuur en ``keep_alive`` uit ``config.py`` overal
hetzelfde zijn en elke aanroep gelogd wordt (duur + tokengebruik).

- Aanroepen met tools of JSON gebruiken ``AI_TEMPERATURE_TOOLS`` (0).
- Gewone gesprekken gebruiken ``AI_TEMPERATURE_CHAT`` (standaard 0.3).
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


def chat(messages, tools=None, json_mode=False, **opties):
    """Roep ``ollama.chat`` aan met de instellingen uit config.py.

    - ``tools`` of ``json_mode=True`` -> temperatuur AI_TEMPERATURE_TOOLS.
    - Gewone gesprekken -> temperatuur AI_TEMPERATURE_CHAT.
    - Extra Ollama-opties kunnen via ``options={...}`` of losse kwargs.
    Duur en tokengebruik (prompt_eval_count/eval_count) worden gelogd.
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

    started = time.perf_counter()
    response = ollama.chat(**kwargs)
    duration = time.perf_counter() - started

    logger.info(
        "LLM chat model=%s duur=%.2fs prompt_tokens=%s eval_tokens=%s "
        "tools=%s json=%s",
        AI_MODEL,
        duration,
        getattr(response, "prompt_eval_count", None),
        getattr(response, "eval_count", None),
        bool(tools),
        json_mode,
    )

    return response
