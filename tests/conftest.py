import ipaddress
import os
import socket
import sys
import types
from unittest.mock import MagicMock

import pytest

# Zorg dat de projectroot op sys.path staat (voor `import core`, `import actions`, ...)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Fase-15B: forceer de suite op lokale PC-target vóórdat config wordt geïmporteerd.
# Zonder dit leest core/pc_target.py de .env-waarde PC_TARGET=game-pc en wordt elk
# PC-commando ('open spotify', 'zet het volume op 50', ...) naar de (niet-draaiende)
# game-pc-agent gerouteerd i.p.v. naar de lokale tools die de tests mocken.
# config.py doet load_dotenv() dat bestaande env-waarden niet overschrijft, dus
# dit wint van de .env. Fase-15b-tests zetten PC_TARGET zelf via monkeypatch.
os.environ["PC_TARGET"] = "local"

# Fase 19 (M3): tests die start_jarvis() draaien, starten anders de
# backupplanner, die een echte backup in de thuismap zou kunnen maken.
os.environ["BACKUP_ENABLED"] = "0"
# Fase 19 (M6): idem voor de updateplanner (die zou git fetch doen).
os.environ["UPDATES_ENABLED"] = "0"
# Fase 23 (M2): idem voor het melden van nieuwe Gmail.
os.environ["GMAIL_MELDEN"] = "0"
# Fase 23 (M5): idem voor de agendaherinneringen.
os.environ["AGENDA_HERINNERINGEN"] = "0"
os.environ["DISCORD_MELDEN"] = "0"

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


def _ollama_available():
    """Controleert of een lokale Ollama-server bereikbaar is.

    Op CI (of bij JARVIS_OLLAMA_DISABLED=1) is dat niet het geval; dan
    stuben we ollama.chat zodat tests niet crashen op een netwerkoproep.
    """
    if os.environ.get("JARVIS_OLLAMA_DISABLED") == "1":
        return False
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    host = host.split("://")[-1]
    host, _, port = host.partition(":")
    try:
        port = int(port or 11434)
    except ValueError:
        port = 11434
    try:
        with socket.create_connection((host or "127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


_OLLAMA_UP = _ollama_available()


@pytest.fixture(autouse=True)
def _stub_ollama_when_unavailable(monkeypatch):
    """Voorkomt echte netwerkoproepen naar Ollama als er geen server draait."""
    if _OLLAMA_UP:
        return

    def _fake_chat(*args, **kwargs):
        message = types.SimpleNamespace(
            content="Ik heb je opdracht verwerkt.", tool_calls=None,
        )
        return types.SimpleNamespace(message=message)

    try:
        monkeypatch.setattr("ollama.chat", _fake_chat)
    except Exception:
        pass


# --- Hermetische DNS --------------------------------------------------------
# Geen echte DNS-resolutie in tests: bekende testdomeinen lossen op naar een
# publiek test-IP, al het andere geeft een duidelijke fout. Zo falen de tests
# niet (of juist wel) afhankelijk van of de machine internet heeft. Een test
# die bewust een prive-adres onderzoekt kan deze fixture overschrijven (zie
# bijv. ``test_web_fetch.fake_dns``).
TEST_PUBLIC_IP = "93.184.216.34"
_TEST_DNS_HOSTS = {
    "example.com",
    "www.example.com",
    "example.org",
    "example.net",
    "example.nl",
    "www.example.nl",
    "test.nl",
}


@pytest.fixture(autouse=True)
def _mock_dns(monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):
        name = (host or "").lower()
        if name in _TEST_DNS_HOSTS:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (TEST_PUBLIC_IP, port))]
        # Numerieke IP's hebben geen DNS nodig; laat de echte resolver die doen.
        try:
            ipaddress.ip_address(name)
        except ValueError:
            raise socket.gaierror(f"Echte DNS staat uit in tests (onbekende host: {host!r})") from None
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


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

    _BRAIN_ORIG = {}
    for _attr in ("ask_ai",):
        try:
            _BRAIN_ORIG[_attr] = getattr(_brain, _attr)
        except Exception:
            pass
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

# Het auditlog: tests mogen nooit in het echte logs/audit.jsonl schrijven
# (dat toont het dashboard). Standaard gaat het naar een tijdelijke map;
# tests die zelf AUDIT_FILE patchen, blijven dat gewoon doen.
try:
    import core.audit as _audit
    import tempfile as _tempfile_audit

    _audit.AUDIT_FILE = os.path.join(
        _tempfile_audit.mkdtemp(prefix="jarvis-tests-audit-"), "audit.jsonl"
    )
except Exception:
    _audit = None

# De taalkeuze (Fase 17) is globale state die tussen tests lekt en die bij
# het importeren van core.ai uit het echte taal.json wordt gelezen. Isoleer
# het bestand naar een tijdelijk pad en reset de taal na elke test.
try:
    import taal as _taal
    import tempfile as _tempfile

    _TAAL_BESTAND_ORIG = _taal.TAAL_BESTAND
    _taal.TAAL_BESTAND = os.path.join(
        _tempfile.gettempdir(), "jarvis-tests-taal.json"
    )
except Exception:
    _taal = None


try:
    import core.proactive as _proactive
except Exception:
    _proactive = None


@pytest.fixture(autouse=True)
def _geen_echte_games(tmp_path, monkeypatch):
    """Fase 21 (M6): de suite kent geen games en leest nooit de echte
    Steam-map; de gamelijst komt in een tijdelijke map."""

    try:
        from core import games_stem
        from core.result_validation import ToolResult
    except Exception:
        yield
        return
    monkeypatch.setattr(games_stem, "_starter", games_stem.GameStarter(
        pc_tool=lambda tool, args: ToolResult(True, "", data={"games": []}),
        cache_pad=str(tmp_path / "games.json"), online_fn=lambda: None))
    yield


@pytest.fixture(autouse=True)
def _geen_echt_gesprekslog(tmp_path, monkeypatch):
    """Het gesprek (dashboard) gaat nooit naar het echte
    memory/gesprekken.jsonl; elke test begint met een leeg gesprek."""

    try:
        import status
    except Exception:
        yield
        return
    monkeypatch.setattr(status, "GESPREK_LOG", str(tmp_path / "gesprekken.jsonl"))
    status._reset_gesprek()
    yield
    status._reset_gesprek()


@pytest.fixture(autouse=True)
def _geen_echte_commando_correcties(tmp_path, monkeypatch):
    """Fase 24 (M5): geleerde verbeteringen en het logboek gaan nooit naar
    het echte memory/commando_correcties.json."""

    try:
        from core import commando_correctie
    except Exception:
        yield
        return
    monkeypatch.setattr(commando_correctie, "LEER_FILE", str(tmp_path / "commando_correcties.json"))
    yield


@pytest.fixture(autouse=True)
def _geen_open_wedervraag():
    """Fase 27 (M4): een open wedervraag of de vorige beurt lekt niet van
    de ene test naar de volgende."""

    try:
        from core import vervolg
    except Exception:
        yield
        return
    vervolg._reset()
    yield
    vervolg._reset()


@pytest.fixture(autouse=True)
def _geen_echte_gemini(monkeypatch):
    """Fase 25: tests sturen nooit iets naar de echte Gemini, ook niet op de
    laptop met een GEMINI_API_KEY in .env. Zonder sleutel gebruikt het
    brein gewoon Ollama (of de Ollama-stub). Een test die Gemini nodig heeft,
    zet zelf een nep-sleutel en vervangt core.gemini.chat."""

    try:
        import config
        from core import llm
    except Exception:
        yield
        return
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    llm._reset_brein()
    yield
    llm._reset_brein()


@pytest.fixture(autouse=True)
def _geen_echte_game_pc_of_spotify(tmp_path, monkeypatch):
    """Tests praten nooit met de echte game-pc-agent of de echte Spotify-
    koppeling, ook niet op de laptop waar die wel ingesteld zijn. "Zet de
    muziek zachter" probeert sinds 2026-10-30 de Web API en de andere pc.
    Een test die een client nodig heeft, zet zelf ``_get_client``."""

    try:
        from core import spotify_smaak
        from remote import tools as remote_tools
    except Exception:
        yield
        return

    def _uit():
        raise ValueError("de game-pc-agent staat uit in de tests.")

    monkeypatch.setattr(remote_tools, "_get_client", _uit)
    monkeypatch.setattr(spotify_smaak, "TOKEN_FILE", str(tmp_path / "spotify_token.json"))
    yield


@pytest.fixture(autouse=True)
def _restore_global_state():
    # Fase 19 (M4): de slaapstand is globale state; elke test begint wakker.
    if _proactive is not None:
        try:
            _proactive._reset_slaap()
        except Exception:
            pass
    if _taal is not None:
        try:
            _taal.reset()
        except Exception:
            pass
    yield
    if _taal is not None:
        try:
            _taal.reset()
        except Exception:
            pass
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
        for _attr, _val in _BRAIN_ORIG.items():
            try:
                setattr(_brain, _attr, _val)
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


