import os
import sys
from unittest.mock import MagicMock

import pytest

# Zorg dat de projectroot op sys.path staat (voor `import core`, `import actions`, ...)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Mock Windows-specifieke en externe modules zodat de suite ook op Linux draait
# (en zonder echte hardware/audio/UI). Ongeacht het platform: deze modules worden
# door de tests zelf via patch() van gedrag voorzien.
_modules_to_stub = [
    "pycaw",
    "pycaw.pycaw",
    "pywinauto",
    "pywinauto.Desktop",
    "pywinauto.keyboard",
    "win32gui",
    "win32process",
    "win32con",
    "win32api",
    "win32com",
    "win32com.client",
    "pythoncom",
    "msvcrt",
    "sounddevice",
    "pyttsx3",
    "keyboard",
    "mouse",
    "pynput",
    "cv2",
    "PIL",
    "PIL.Image",
    "PIL.ImageGrab",
]
for _mod in _modules_to_stub:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# ctypes.windll bestaat alleen op Windows; op Linux niet.
try:
    import ctypes

    if not hasattr(ctypes, "windll"):
        ctypes.windll = MagicMock()
except Exception:
    pass


@pytest.fixture
def mock_ollama(monkeypatch):
    mock = MagicMock()
    try:
        monkeypatch.setattr("ollama.chat", mock)
    except Exception:
        pass
    return mock


@pytest.fixture
def mock_requests(monkeypatch):
    mock = MagicMock()
    try:
        monkeypatch.setattr("requests.get", mock.get)
        monkeypatch.setattr("requests.post", mock.post)
    except Exception:
        pass
    return mock


# --- Isolatie van globale state -------------------------------------------
# Sommige (oudere) tests monkeypatchen module-attributen met unittest.patch en
# herstellen die pas aan het einde van de test. Faalt zo'n test halverwege, dan
# lekt de patch en beinvloedt die alle volgende tests. We bewaren hier de
# oorspronkelijke waarden en zetten die na ELKE test terug.
try:
    import copy
    import core.ai as _ai

    _AI_ORIG = {}
    for _attr in (
        "CONVERSATION_FILE",
        "_save_conversation",
        "_load_conversation",
    ):
        try:
            _AI_ORIG[_attr] = getattr(_ai, _attr)
        except Exception:
            pass
    try:
        _AI_CTX_ORIG = copy.deepcopy(_ai.current_context)
    except Exception:
        _AI_CTX_ORIG = None
    try:
        _AI_HIST_ORIG = list(_ai.conversation_history)
    except Exception:
        _AI_HIST_ORIG = None
except Exception:
    _ai = None

# Executor-journaal + agent-stappen zijn ook globale state die tussen
# tests lekt (bijv. "bewaar dit als routine x" gebruikt de laatst
# uitgevoerde acties). Reset die na elke test.
try:
    import core.executor as _executor
except Exception:
    _executor = None

try:
    import core.brain as _brain
except Exception:
    _brain = None

try:
    from core.confirmation import clear_pending as _clear_pending
except Exception:
    _clear_pending = None

try:
    import core.ha_registry as _ha_registry
except Exception:
    _ha_registry = None


@pytest.fixture(autouse=True)
def _restore_global_state():
    yield
    if _ai is not None:
        for _attr, _val in _AI_ORIG.items():
            try:
                setattr(_ai, _attr, _val)
            except Exception:
                pass
        if _AI_CTX_ORIG is not None:
            try:
                _ai.current_context.clear()
                _ai.current_context.update(_AI_CTX_ORIG)
            except Exception:
                pass
        if _AI_HIST_ORIG is not None:
            try:
                _ai.conversation_history[:] = _AI_HIST_ORIG
            except Exception:
                pass
    if _executor is not None:
        try:
            _executor._LAST_DONE_ACTIONS = []
            _executor._LAST_EXECUTION_TS = 0.0
        except Exception:
            pass
    if _brain is not None:
        try:
            _brain.agent.last_executed_steps = []
        except Exception:
            pass
    if _clear_pending is not None:
        try:
            _clear_pending()
        except Exception:
            pass
    if _ha_registry is not None:
        try:
            _ha_registry._registry._snapshot = None
            _ha_registry._registry._last_refresh = 0.0
        except Exception:
            pass


