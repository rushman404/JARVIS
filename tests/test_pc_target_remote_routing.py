"""PC_TARGET: game-pc-routing voor alle pc-bedienende functies.

Dekt:
    - elke functie uit actions.* die brain.py importeert is in pc_target.PC_ACTIES
    - bij doel game-pc en opgenomen aanroepen mag geen enkele pc-bedienende functie lokaal worden uitgevoerd
    - de 13 commando's uit Taak F lopen rechtstreeks naar de juiste game_pc_*-twin zonder LLM
    - scherm/batterij geven een duidelijke blokkade-melding
"""
import pytest
import config
from core import brain, pc_target
from remote import tools as remote_tools


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, tool_name, arguments, question=None, **kwargs):
        self.calls.append((tool_name, arguments, question))
        return "done"


def _geen_llm(monkeypatch):
    from core import llm

    def _fout(*a, **k):
        raise AssertionError("het LLM-pad mag bij dit commando niet worden gebruikt")

    monkeypatch.setattr(llm, "chat", _fout)


@pytest.fixture
def game_pc(monkeypatch):
    monkeypatch.setattr(config, "PC_TARGET", "game-pc")
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    remote_tools._reset_client()
    yield
    remote_tools._reset_client()


@pytest.mark.parametrize(
    "zin, handler, verwacht_tool, verwachte_args",
    [
        ("herstart spotify", "try_restart_program", "game_pc_restart_program", {"program": "spotify"}),
        ("waar staat spotify", "try_find_program", "game_pc_find_program_location", {"program": "spotify"}),
        ("zet spotify op 20 procent", "try_audio_command", "game_pc_audio_set_session_volume", {"app_name": "spotify", "volume": 20}),
        ("hoeveel geheugen en schijfruimte", "try_system_info", "game_pc_system_info", {}),
        ("minimaliseer spotify", "try_window_command", "game_pc_minimize_window", {"program": "spotify"}),
        ("maximaliseer spotify", "try_window_command", "game_pc_maximize_window", {"program": "spotify"}),
        ("herstel spotify", "try_window_command", "game_pc_restore_window", {"program": "spotify"}),
        ("ga terug in de browser", "try_browser_command", "game_pc_browser_back", {}),
        ("ververs de pagina", "try_browser_command", "game_pc_browser_refresh", {}),
        ("open een nieuw tabblad", "try_browser_command", "game_pc_browser_new_tab", {}),
        ("zoek op google naar katten", "try_browser_search", "game_pc_browser_search", {"query": "katten", "site": "google"}),
        ("open youtube", "try_open_known_site", "game_pc_open_website", {"url": "https://www.youtube.com"}),
        ("annuleer afsluiten", "try_power_command", "game_pc_power", {"action": "cancel"}),
    ],
)
def test_de_13_commando_s_routes(monkeypatch, game_pc, zin, handler, verwacht_tool, verwachte_args):
    _geen_llm(monkeypatch)

    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    # Laat lokale acties falen
    for naam in (
        "open_program_tool", "close_program_tool", "pc_status_tool", "take_screenshot",
        "set_volume", "play_pause", "next_track", "previous_track", "volume_up", "volume_down", "toggle_mute",
        "get_program_status", "restart_program", "find_program_location",
        "minimize_program", "maximize_program", "restore_window",
        "browser_search", "browser_back", "browser_forward", "browser_refresh", "browser_new_tab", "browser_close_tab",
        "open_website", "get_browser_content", "get_browser_url", "get_browser_title",
        "audio_list_sessions", "audio_get_session_volume", "audio_set_session_volume", "audio_set_session_mute", "audio_toggle_session_mute", "audio_list_outputs", "audio_get_default_output", "audio_set_default_output",
        "system_summary", "cpu_info", "ram_info", "gpu_names", "disk_info", "battery_info", "os_info", "uptime", "screen_info",
        "cancel_shutdown",
    ):
        try:
            monkeypatch.setattr(brain, naam, _fout_bij_aanroep(f"lokaal '{naam}' mag niet bij doel game-pc"))
        except AttributeError:
            pass

    # Hulpstukken voor parsing
    monkeypatch.setattr(brain, "find_program", lambda naam, exact_only=False: True)
    monkeypatch.setattr(brain, "_extract_window_program", lambda q: "spotify")
    monkeypatch.setattr(brain, "_looks_like_app_volume", lambda q: True)

    resultaat = getattr(brain, handler)(zin)
    assert resultaat is not None, f"{handler} gaf niets terug voor {zin!r}"
    assert recorder.calls, f"{handler} riep execute_tool niet aan voor {zin!r}"
    tool, args, vraag = recorder.calls[-1]
    assert tool == verwacht_tool, f"verwacht {verwacht_tool}, kreeg {tool}"
    assert args == verwachte_args, f"verwacht args {verwachte_args}, kreeg {args}"


@pytest.mark.parametrize("zin", ["annuleer afsluiten", "annuleer herstart"])
def test_annuleren_gaat_naar_game_pc_power_cancel(monkeypatch, game_pc, zin):
    """Zowel 'annuleer afsluiten' als 'annuleer herstart' annuleert op de game-pc."""

    _geen_llm(monkeypatch)

    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    try:
        monkeypatch.setattr(brain, "cancel_shutdown", _fout_bij_aanroep("cancel_shutdown mag niet lokaal"))
    except AttributeError:
        pass

    resultaat = brain.try_power_command(zin)

    assert resultaat is not None, f"try_power_command gaf niets terug voor {zin!r}"
    tool, args, _ = recorder.calls[-1]
    assert tool == "game_pc_power"
    assert args == {"action": "cancel"}


def _fout_bij_aanroep(boodschap):
    def _fout(*args, **kwargs):
        raise AssertionError(boodschap)
    return _fout
