"""Tests voor de centrale LLM-config (core/llm.py) en de crash-limiet (main.py).

Alles is gemockt: er wordt geen echte Ollama of microfoon gebruikt.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import core.llm as llm
import main


def _fake_response():
    response = MagicMock()
    response.prompt_eval_count = 12
    response.eval_count = 34
    return response


# ---------------------------------------------------------------------------
# core/llm.chat: config-instellingen gaan door naar ollama.chat
# ---------------------------------------------------------------------------

def test_chat_gebruikt_config_en_tool_temperatuur():
    tools = [{"type": "function", "function": {"name": "open_file"}}]
    with patch.object(llm.ollama, "chat", return_value=_fake_response()) as m:
        llm.chat(messages=[{"role": "user", "content": "hoi"}], tools=tools)

    kwargs = m.call_args.kwargs
    assert kwargs["model"] == config.AI_MODEL
    assert kwargs["keep_alive"] == config.AI_KEEP_ALIVE
    assert kwargs["options"]["num_ctx"] == config.AI_NUM_CTX
    assert kwargs["options"]["temperature"] == config.AI_TEMPERATURE_TOOLS
    assert kwargs["tools"] is tools
    assert kwargs["messages"][0]["content"] == "hoi"


def test_chat_gebruikt_chat_temperatuur_zonder_tools():
    with patch.object(llm.ollama, "chat", return_value=_fake_response()) as m:
        llm.chat(messages=[{"role": "user", "content": "vertel een verhaal"}])

    kwargs = m.call_args.kwargs
    assert kwargs["options"]["temperature"] == config.AI_TEMPERATURE_CHAT
    assert "tools" not in kwargs
    assert "format" not in kwargs


def test_chat_json_mode_gebruikt_tool_temperatuur_en_format():
    with patch.object(llm.ollama, "chat", return_value=_fake_response()) as m:
        llm.chat(messages=[{"role": "user", "content": "plan"}], json_mode=True)

    kwargs = m.call_args.kwargs
    assert kwargs["format"] == "json"
    assert kwargs["options"]["temperature"] == config.AI_TEMPERATURE_TOOLS


def test_chat_expliciete_temperatuur_overschrijft():
    with patch.object(llm.ollama, "chat", return_value=_fake_response()) as m:
        llm.chat(messages=[{"role": "user", "content": "x"}], temperature=0.9)

    assert m.call_args.kwargs["options"]["temperature"] == 0.9


def test_chat_extra_opties_gaan_mee():
    with patch.object(llm.ollama, "chat", return_value=_fake_response()) as m:
        llm.chat(messages=[{"role": "user", "content": "x"}], options={"top_p": 0.5})

    options = m.call_args.kwargs["options"]
    assert options["top_p"] == 0.5
    assert options["num_ctx"] == config.AI_NUM_CTX


def test_check_model_available_gevonden_en_ontbrekend():
    with patch.object(llm.ollama, "list", return_value={"models": [{"name": config.AI_MODEL}]}):
        assert llm.check_model_available() is True

    with patch.object(llm.ollama, "list", return_value={"models": [{"name": "ander:1b"}]}):
        assert llm.check_model_available() is False

    with patch.object(llm.ollama, "list", side_effect=RuntimeError("geen ollama")):
        assert llm.check_model_available() is False


def test_config_heeft_temperatuur_chat():
    assert hasattr(config, "AI_TEMPERATURE_CHAT")
    assert config.AI_TEMPERATURE_CHAT == float(config.AI_TEMPERATURE_CHAT)


# ---------------------------------------------------------------------------
# Crash-limiet & hoofdlus-bescherming (main.py)
# ---------------------------------------------------------------------------

def test_exception_wordt_opgevangen_en_lus_gaat_door():
    limiter = main.CrashLimiter()
    calls = []

    def action():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom in process_command")

    outcomes = [main.run_protected(action, limiter) for _ in range(3)]

    assert outcomes == ["continue", "ok", "ok"]
    assert len(calls) == 3


def test_crash_limiet_stopt_na_max():
    limiter = main.CrashLimiter(max_crashes=5, window_seconds=60, clock=lambda: 0.0)

    def boom():
        raise RuntimeError("altijd stuk")

    outcomes = [main.run_protected(boom, limiter) for _ in range(7)]

    assert outcomes[:5] == ["continue"] * 5
    assert outcomes[5] == "stop"
    assert outcomes[6] == "stop"


def test_crash_venster_verloopt():
    now = [0.0]
    limiter = main.CrashLimiter(max_crashes=5, window_seconds=60, clock=lambda: now[0])

    for _ in range(5):
        assert limiter.register_crash() is True

    now[0] = 61.0  # de vorige crashes vallen buiten het venster
    assert limiter.register_crash() is True


def test_on_continue_woordt_uitgesproken():
    limiter = main.CrashLimiter()
    said = []

    def boom():
        raise RuntimeError("stuk")

    outcome = main.run_protected(boom, limiter, on_continue=lambda: said.append("Er ging iets mis"))

    assert outcome == "continue"
    assert said == ["Er ging iets mis"]


def test_keyboard_interrupt_wordt_doorgegeven():
    limiter = main.CrashLimiter()

    def stop():
        raise KeyboardInterrupt

    raised = False
    try:
        main.run_protected(stop, limiter)
    except KeyboardInterrupt:
        raised = True
    assert raised, "KeyboardInterrupt moet doorgegeven worden"


# ---------------------------------------------------------------------------
# Waarschuwing als de prompt de context vult (tools worden mogelijk afgekapt)
# ---------------------------------------------------------------------------

def _fake_response_met(prompt_tokens):
    response = MagicMock()
    response.prompt_eval_count = prompt_tokens
    response.eval_count = 1
    return response


def test_chat_waarschuwt_bij_bijna_volle_context(caplog):
    tokens = int(config.AI_NUM_CTX * 0.95)
    with caplog.at_level("WARNING"):
        with patch.object(llm.ollama, "chat", return_value=_fake_response_met(tokens)):
            llm.chat(messages=[{"role": "user", "content": "hoi"}])
    assert "Prompt vult de context" in caplog.text


def test_chat_waarschuwt_niet_bij_kleine_prompt(caplog):
    with caplog.at_level("WARNING"):
        with patch.object(llm.ollama, "chat", return_value=_fake_response_met(10)):
            llm.chat(messages=[{"role": "user", "content": "hoi"}])
    assert "Prompt vult de context" not in caplog.text


def test_chat_waarschuwt_niet_zonder_prompt_eval_count(caplog):
    response = MagicMock()
    response.prompt_eval_count = None
    response.eval_count = 1
    with caplog.at_level("WARNING"):
        with patch.object(llm.ollama, "chat", return_value=response):
            llm.chat(messages=[{"role": "user", "content": "hoi"}])
    assert "Prompt vult de context" not in caplog.text


def test_config_default_num_ctx_ruim_genoeg():
    # Standaard moet ruim genoeg zijn voor systeemtekst + tools.
    assert config.AI_NUM_CTX >= 8192
