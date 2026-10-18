"""PC_TARGET=game-pc: de blokkademelding mag alleen browser-leesvragen raken.

Deze regressietest dekt de bug waarbij try_browser_read de remote-controle
VÓÓR de zinsherkenning zette en daardoor elk commando opat dat hem bereikte
met PC_TARGET=game-pc ("open spotify", "zet de lamp aan", ...).

Dekt:
    - ≥40 gewone commando's geven NOOIT de blokkademelding
    - browser-leesvragen geven WEL de blokkademelding
    - "open spotify" -> game_pc_open_program (geen LLM)
    - "sluit discord" -> game_pc_close_program (geen LLM)
    - "zet de lamp aan" -> HA-route (geen LLM)
    - "zet discord op 20 procent" -> game_pc_audio_set_session_volume
      zonder ENKELE lokale find_program-aanroep
"""
import pytest
import config
from core import brain, pc_target
from remote import tools as remote_tools

BLOKKADE = "Dat kan ik nog niet op de game-pc."


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


# ---------------------------------------------------------------------------
# 1. Regressietest: ≥40 gewone commando's mogen de blokkademelding NOOIT krijgen
# ---------------------------------------------------------------------------

GEWONE_COMMMANDO_S = [
    # Programma's (8)
    "open spotify",
    "sluit discord",
    "herstart spotify",
    "waar staat spotify",
    "is spotify open",
    "open chrome",
    "sluit notepad",
    "draait spotify",
    # Volume / media (8)
    "zet het volume op 50",
    "zet discord op 20 procent",
    "maak discord zachter",
    "volume harder",
    "speel muziek af",
    "pauzeer",
    "volgende nummer",
    "demp alles",
    # Lamp / Home Assistant (8)
    "zet de lamp aan",
    "zet de lamp uit",
    "zet de verwarming op 20",
    "is het licht aan",
    "zet de stekker aan",
    "hoe warm is het",
    "zet de zonwering omlaag",
    "schakel de tv aan",
    # Rekenen (4)
    "wat is 2 plus 2",
    "bereken 10 maal 5",
    "wat is 100 gedeeld door 4",
    "hoeveel is 3 macht 2",
    # Weer (2)
    "wat is het weer in Amsterdam",
    "hoe wordt het weer morgen",
    # Geheugen (4)
    "onthoud dat mijn lievelingskleur blauw is",
    "wat is mijn lievelingskleur",
    "vergeet mijn lievelingskleur",
    "wat weet je van mij",
    # Bestanden (6)
    "zoek naar documenten",
    "maak een map test",
    "open de map downloads",
    "welke bestanden zitten in downloads",
    "kopieer bestand.txt naar desktop",
    "verplaats bestand.txt naar documenten",
    # Telemetrie (4)
    "hoeveel geheugen gebruik ik",
    "wat is mijn cpu-belasting",
    "hoeveel schijfruimte heb ik",
    "wat is mijn gpu-belasting",
    # Vensters (4)
    "welke vensters zijn open",
    "minimaliseer spotify",
    "maximaliseer spotify",
    "breng discord naar voren",
]

BROWSER_LEESVRAGEN = [
    "wat staat er op mijn browser",
    "welke pagina heb ik open",
    "wat is de titel van mijn browser",
]


def test_gewone_commando_krijgen_nooit_blokkade(monkeypatch, game_pc):
    """Met PC_TARGET=game-pc mag de blokkademelding NOOIT komen voor
    gewone commando's — alleen voor browser-leesvragen."""
    # Sommige commando's (bijv. HA-vragen) lopen via ask_ai/llm.chat.
    # Dat is legitiem; deze test controleert alleen dat de blokkade
    # niet verschijnt. Daarom geven we het LLM een onschuldig antwoord.
    from types import SimpleNamespace
    from core import llm

    def _onschuldig(*a, **k):
        return SimpleNamespace(
            message=SimpleNamespace(content="ok", tool_calls=None),
        )

    monkeypatch.setattr(llm, "chat", _onschuldig)

    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    # Lokale acties die kunnen falen op een testmachine: laat ze een
    # dummy-antwoord geven zodat process_command niet crasht.
    for naam in (
        "open_program_tool", "close_program_tool", "pc_status_tool",
        "set_volume", "play_pause", "next_track", "previous_track",
        "volume_up", "volume_down", "toggle_mute",
        "get_program_status", "restart_program", "find_program_location",
        "minimize_program", "maximize_program", "restore_window",
        "audio_list_sessions", "audio_get_session_volume",
        "audio_set_session_volume", "audio_list_outputs",
        "audio_get_default_output", "audio_set_default_output",
        "system_summary", "cpu_info", "ram_info", "gpu_names",
        "disk_info", "battery_info", "os_info", "uptime", "screen_info",
        "open_folder", "search_files", "rename_file", "create_folder",
        "create_file", "list_folder", "copy_path", "move_path",
        "get_recent_files", "take_screenshot",
        "get_browser_content", "get_browser_url", "get_browser_title",
        "browser_search", "browser_back", "browser_forward",
        "browser_refresh", "browser_new_tab", "browser_close_tab",
        "open_website", "cancel_shutdown",
    ):
        try:
            monkeypatch.setattr(brain, naam, lambda *a, **k: "ok")
        except AttributeError:
            pass

    # Voldoende commando's?
    assert len(GEWONE_COMMMANDO_S) >= 40, (
        f"Er staan maar {len(GEWONE_COMMMANDO_S)} gewone commando's in de lijst; "
        "minstens 40 zijn vereist."
    )

    overtredingen = []
    for cmdo in GEWONE_COMMMANDO_S:
        resultaat = brain.process_command(cmdo)
        if isinstance(resultaat, str) and BLOKKADE in resultaat:
            overtredingen.append(cmdo)

    assert not overtredingen, (
        "De blokkademelding kwam onterecht voor deze commando's: "
        f"{overtredingen}"
    )


def test_browser_leesvragen_wel_blokkade(monkeypatch, game_pc):
    """Echte browser-leesvragen mogen wél de blokkademelding geven."""
    _geen_llm(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    for cmdo in BROWSER_LEESVRAGEN:
        resultaat = brain.try_browser_read(cmdo)
        assert isinstance(resultaat, str) and BLOKKADE in resultaat, (
            f"try_browser_read gaf geen blokkademelding voor {cmdo!r}, "
            f"kreeg: {resultaat!r}"
        )


def test_browser_read_gaat_none_bij_geen_match(monkeypatch, game_pc):
    """Zonder browser-patroon geeft try_browser_read None terug (geen blokkade)."""
    for cmdo in ("open spotify", "zet de lamp aan", "hoeveel cpu gebruik ik"):
        assert brain.try_browser_read(cmdo) is None, (
            f"try_browser_read gaf geen None voor {cmdo!r}"
        )


# ---------------------------------------------------------------------------
# 2. Routingtests: open spotify / sluit discord / zet de lamp aan
# ---------------------------------------------------------------------------

def test_open_spotify_gaat_naar_game_pc_open_program(monkeypatch, game_pc):
    """"Open spotify" moet game_pc_open_program aanroepen, zonder LLM."""
    _geen_llm(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    # Lokale open_program mag niet worden aangeroepen
    monkeypatch.setattr(
        brain, "open_program_tool",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("lokaal open_program_tool mag niet bij game-pc")),
    )
    # Vind-programma-lookup: spotify bestaat lokaal niet, maar de naam
    # moet toch naar de game-pc gaan.
    monkeypatch.setattr(brain, "find_program", lambda naam, exact_only=False: True)

    resultaat = brain.process_command("open spotify")

    assert recorder.calls, "execute_tool werd niet aangeroepen voor 'open spotify'"
    tool, args, _ = recorder.calls[-1]
    assert tool == "game_pc_open_program", f"verwacht game_pc_open_program, kreeg {tool}"


def test_sluit_discord_gaat_naar_game_pc_close_program(monkeypatch, game_pc):
    """"Sluit discord" moet game_pc_close_program aanroepen, zonder LLM."""
    _geen_llm(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    monkeypatch.setattr(
        brain, "close_program_tool",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("lokaal close_program_tool mag niet bij game-pc")),
    )
    monkeypatch.setattr(brain, "find_program", lambda naam, exact_only=False: True)

    resultaat = brain.process_command("sluit discord")

    assert recorder.calls, "execute_tool werd niet aangeroepen voor 'sluit discord'"
    tool, args, _ = recorder.calls[-1]
    assert tool == "game_pc_close_program", f"verwacht game_pc_close_program, kreeg {tool}"


def test_zet_de_lamp_aan_gaat_naar_ha_route(monkeypatch, game_pc):
    """"Zet de lamp aan" moet bij Home Assistant uitkomen, zonder LLM."""
    _geen_llm(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    # try_ha_direct deterministisch laten slagen zodat ask_ai (en dus
    # llm.chat) niet wordt aangeroepen.
    monkeypatch.setattr(
        brain, "try_ha_direct",
        lambda cmdo: "De lamp is aangezet.",
    )

    resultaat = brain.process_command("zet de lamp aan")

    assert resultaat is not None
    assert BLOKKADE not in resultaat, (
        f"'zet de lamp aan' kreeg onterecht de blokkademelding: {resultaat!r}"
    )
    # llm.chat is niet aangeroepen (anders was _geen_llm al gefaald)


# ---------------------------------------------------------------------------
# 3. Audio: "zet discord op 20 procent" -> game-pc zonder lokale find_program
# ---------------------------------------------------------------------------

def test_discord_volume_gaat_naar_game_pc_zonder_lokale_lookup(monkeypatch, game_pc):
    """"Zet discord op 20 procent" stuurt de programmanaam naar de game-pc
    zonder ENKELE lokale find_program-aanroep."""
    _geen_llm(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(brain, "execute_tool", recorder)

    # find_program mag NOOIT worden aangeroepen bij game-pc-doel
    def _vind_program_fout(naam, exact_only=False):
        raise AssertionError(
            f"find_program('{naam}') mag niet lokaal worden aangeroepen "
            "bij doel game-pc"
        )

    monkeypatch.setattr(brain, "find_program", _vind_program_fout)

    resultaat = brain.try_audio_command("zet discord op 20 procent")

    assert recorder.calls, (
        "execute_tool werd niet aangeroepen voor 'zet discord op 20 procent'"
    )
    tool, args, _ = recorder.calls[-1]
    assert tool == "game_pc_audio_set_session_volume", (
        f"verwacht game_pc_audio_set_session_volume, kreeg {tool}"
    )
    assert args == {"app_name": "discord", "volume": 20}, (
        f"verwacht app_name=discord volume=20, kreeg {args}"
    )
