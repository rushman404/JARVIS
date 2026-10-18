"""Fase 15C — tests voor de uitgebreide denylist, typebeveiliging en serverprofiel.

Dekt:
    - alle Startmenu-namen van gevaarlijke programma's worden geweigerd;
    - alle nieuwe procesnamen op de denylist worden geweigerd;
    - weergavenaam-controle (bv. "Windows PowerShell (x86)");
    - fail-closed typebeveiliging: exception en onbekende procesnaam
      blokkeren ui_type_text, ui_click_element en ui_set_value;
    - "explorer" is alleen voor typen geweigerd, niet voor open_program;
    - profiel basis weigert werkstation-acties en staat basisacties toe
      (inclusief audio per app, dat risico medium blijft);
    - de geweigerde-actiemelding noemt REMOTE_SERVER_PROFILE=werkstation;
    - Discord, Spotify en games blijven starten;
    - gamenamen als "Idle Champions", "Terminal Velocity", "Python
      Tycoon", "Command & Conquer" en "Ratchet & Clank" worden toegestaan.
"""

import pytest

from remote import allowlist, server

TOKEN = "s" * 32


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _agent(dispatch=None, **kwargs):
    kwargs.setdefault("rate_limiter", server.RateLimiter(max_requests=0))
    kwargs.setdefault("audit", False)
    kwargs.setdefault("dispatch", dispatch)
    return server.RemoteAgent(TOKEN, **kwargs)


def _dispatch_tekst(resultaat="gedaan", teller=None):
    def dispatch(tool, argumenten, question):
        if teller is not None:
            teller.append((tool, argumenten, question))
        return resultaat

    return dispatch


def _commando(tool, arguments=None):
    import core.audit  # noqa: F401  (zorgt dat de module geladen is)
    from remote import protocol

    bericht = {"tool": tool}
    if arguments is not None:
        bericht["arguments"] = arguments

    body = protocol.encode_body(bericht)
    headers = protocol.signed_headers(
        TOKEN, "POST", server.ROUTE_COMMAND, body
    )
    return headers, body


# ---------------------------------------------------------------
# 1. Startmenu-namen worden geweigerd (validate_call / is_denied_program)
# ---------------------------------------------------------------

STARTMENU_NAMEN = [
    "Windows PowerShell",
    "Windows PowerShell (x86)",
    "PowerShell 7 (x64)",
    "Command Prompt",
    "Windows Terminal",
    "Terminal",
    "Git Bash",
    "Python 3.12 (64-bit)",
    "IDLE",
    "Registry Editor",
    "Windows Subsystem for Linux",
    "Task Scheduler",
    "Windows Script Host",
]


@pytest.mark.parametrize("naam", STARTMENU_NAMEN)
def test_startmenu_naam_wordt_geweigerd(naam):
    assert allowlist.is_denied_program(naam) is True


@pytest.mark.parametrize("naam", STARTMENU_NAMEN)
def test_startmenu_naam_in_open_program_wordt_geweigerd(naam):
    args, fout = allowlist.validate_call("open_program", {"program": naam})

    assert args is None
    assert fout is not None
    assert "niet toegestaan" in fout


# ---------------------------------------------------------------
# 2. Nieuwe procesnamen op de denylist
# ---------------------------------------------------------------

NIEUWE_PROCESNAMEN = [
    "windowsterminal",
    "wt",
    "conhost",
    "openconsole",
    "mintty",
    "git-bash",
    "powershell_ise",
    "wslhost",
    "wsl",
    "bash",
    "idle",
    "python3",
    "py",
    "wscript",
    "cscript",
    "regedit",
    "regedt32",
    "mmc",
    "msconfig",
    "diskpart",
    "cipher",
    "sc",
    "bcdedit",
    "eventvwr",
    "compmgmt",
    "lusrmgr",
]


@pytest.mark.parametrize("naam", NIEUWE_PROCESNAMEN)
def test_nieuwe_procesnaam_op_denylist(naam):
    assert naam in allowlist.DENIED_PROGRAMS
    assert allowlist.is_denied_program(naam) is True


# ---------------------------------------------------------------
# 3. Weergavenaam-controle (fragmenten)
# ---------------------------------------------------------------

WEERGAVENAMEN = [
    "Windows PowerShell (x86)",
    "PowerShell 7 (x64)",
    "Command Prompt",
    "Windows Terminal",
    "Git Bash here",
    "Python 3.12 (64-bit)",
    "IDLE (Python 3.12)",
    "Registry Editor",
    "Windows Subsystem for Linux",
    "Task Scheduler",
    "Windows Script Host",
]


@pytest.mark.parametrize("naam", WEERGAVENAMEN)
def test_weergavenaam_bevat_verboden_fragment(naam):
    assert allowlist.is_denied_program(naam) is True


def test_normale_programmas_niet_geweigerd():
    for naam in ("Discord", "Spotify", "Valorant", "Cyberpunk 2077", "Steam"):
        assert allowlist.is_denied_program(naam) is False


# ---------------------------------------------------------------
# 4. Fail-closed typebeveiliging
# ---------------------------------------------------------------

def test_is_denied_for_typing_onbekende_procesnaam():
    """Onbekende procesnaam ('') moet worden geweigerd."""
    # programma_van_handle geeft '' terug als de naam niet bepaald kan
    # worden; is_denied_for_typing moet dan True retourneren.
    resultaat = allowlist.is_denied_for_typing(12345)
    # Op een testmachine zonder Windows-API's geeft dit '' → True.
    # Op een echte Windows-machine met een ongeldige handle ook '' → True.
    assert resultaat is True


def test_is_denied_for_typing_bestaand_toegestaan_venster(monkeypatch):
    """Een venster van een toegestaan programma mag wél getypt worden."""
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "spotify")
    assert allowlist.is_denied_for_typing(1) is False


def test_is_denied_for_typing_denylist_proces(monkeypatch):
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "powershell")
    assert allowlist.is_denied_for_typing(1) is True


def test_is_denied_for_typing_explorer(monkeypatch):
    """explorer is alleen voor typen geweigerd."""
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "explorer")
    assert allowlist.is_denied_for_typing(1) is True
    # maar open_program mag explorer wél
    assert allowlist.is_denied_program("explorer") is False


def test_server_weigert_typen_bij_exception(monkeypatch):
    """Een exception in de vensterchecker moet het typen blokkeren."""

    def foutieve_checker(handle):
        raise RuntimeError("Windows API kapot")

    monkeypatch.setattr(allowlist, "programma_van_handle", foutieve_checker)

    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="werkstation"
    )
    headers, body = _commando("ui_type_text", {"handle": 1, "text": "hallo"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 403
    assert teller == []


def test_server_weigert_typen_bij_onbekende_procesnaam(monkeypatch):
    """Een onbekende procesnaam ('') moet het typen blokkeren."""
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "")

    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="werkstation"
    )
    headers, body = _commando("ui_type_text", {"handle": 1, "text": "hallo"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 403
    assert teller == []


def test_server_weigert_klikken_bij_onbekende_procesnaam(monkeypatch):
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "")

    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="werkstation"
    )
    headers, body = _commando("ui_click_element", {"handle": 1, "name": "Knop"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 403
    assert teller == []


def test_server_weigert_set_value_bij_onbekende_procesnaam(monkeypatch):
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "")

    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="werkstation"
    )
    headers, body = _commando(
        "ui_set_value", {"handle": 1, "value": 40, "name": "Volume"}
    )

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 403
    assert teller == []


def test_server_staat_typen_toe_in_toegestaan_venster(monkeypatch):
    """Typen in een venster van Spotify mag wél (werkstation-profiel)."""
    monkeypatch.setattr(allowlist, "programma_van_handle", lambda h: "spotify")

    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="werkstation"
    )
    headers, body = _commando("ui_type_text", {"handle": 1, "text": "hallo"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 200
    assert len(teller) == 1


# ---------------------------------------------------------------
# 5. Serverprofiel: basis vs werkstation
# ---------------------------------------------------------------

WERKSTATION_ACTIES = [
    ("create_folder", {"name": "testmap"}),
    ("create_file", {"name": "test.txt"}),
    ("copy_file", {"filename": "a.txt", "location": "downloads"}),
    ("move_file", {"filename": "a.txt", "location": "downloads"}),
    ("rename_file", {"old_name": "a.txt", "new_name": "b.txt"}),
    ("recycle_file", {"filename": "a.txt"}),
    ("empty_recycle_bin", {}),
    ("ui_click_element", {"handle": 1, "name": "Knop"}),
    ("ui_type_text", {"handle": 1, "text": "hallo"}),
    ("ui_set_value", {"handle": 1, "value": 40, "name": "Volume"}),
    ("ui_launch_app", {"path": "C:\\test\\app.exe"}),
    ("power", {"action": "shutdown"}),
    ("open_website", {"url": "https://example.com"}),
    ("browser_search", {"query": "test"}),
    ("list_files", {"location": "downloads"}),
    ("open_folder", {"location": "downloads"}),
    ("open_file", {"filename": "a.txt"}),
    ("search_files", {"query": "rapport"}),
    ("recent_files", {}),
    ("restart_program", {"program": "spotify"}),
    ("ui_list_windows", {}),
    ("ui_get_value", {"handle": 1, "name": "Volume"}),
]


@pytest.mark.parametrize("tool,args", WERKSTATION_ACTIES)
def test_basis_profiel_weigert_werkstation_acties(tool, args):
    """In profiel basis worden bestands-/UI-/power-/browseracties geweigerd."""
    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="basis"
    )
    headers, body = _commando(tool, args)

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 403, f"{tool} moet geweigerd worden in basis"
    assert payload["fout"]["code"] == "niet_toegestaan"
    assert teller == []


BASIS_ACTIES = [
    ("open_program", {"program": "Discord"}),
    ("close_program", {"program": "Discord"}),
    ("program_status", {"program": "Discord"}),
    ("find_program_location", {"program": "Discord"}),
    ("minimize_window", {"program": "Discord"}),
    ("maximize_window", {"program": "Discord"}),
    ("restore_window", {"program": "Discord"}),
    ("media_play_pause", {}),
    ("media_next", {}),
    ("media_previous", {}),
    ("media_stop", {}),
    ("media_mute", {}),
    ("volume_up", {}),
    ("volume_down", {}),
    ("set_volume", {"percent": 40}),
    ("audio_list_sessions", {}),
    ("audio_get_session_volume", {"app_name": "spotify"}),
    ("audio_list_outputs", {}),
    ("audio_get_default_output", {}),
    # Audio per app bedienen mag ook in basis (blijft risico medium).
    ("audio_set_session_volume", {"app_name": "spotify", "volume": 50}),
    ("audio_set_session_mute", {"app_name": "spotify", "muted": True}),
    ("audio_toggle_session_mute", {"app_name": "spotify"}),
    ("system_info", {}),
    ("pc_status", {}),
    ("screenshot", {}),
]


@pytest.mark.parametrize("tool,args", BASIS_ACTIES)
def test_basis_profiel_staat_basisacties_toe(tool, args):
    """In profiel basis werken programma's, media, vensters en status wél."""
    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="basis"
    )
    headers, body = _commando(tool, args)

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 200, f"{tool} moet in basis toegestaan zijn"
    assert len(teller) == 1


def test_werkstation_profiel_staat_alles_toe():
    """Profiel werkstation staat ook bestands-/UI-/poweracties toe."""
    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="werkstation"
    )
    headers, body = _commando("create_folder", {"name": "testmap"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 200
    assert len(teller) == 1


def test_onbekend_profiel_valt_terug_op_basis():
    """Een onbekende profielnaam wordt als basis behandeld (fail-closed)."""
    assert allowlist.profiel_voor_naam("onbekend") == allowlist.PROFIEL_BASIS
    assert allowlist.profiel_voor_naam("") == allowlist.PROFIEL_BASIS
    assert allowlist.profiel_voor_naam(None) == allowlist.PROFIEL_BASIS
    assert allowlist.profiel_voor_naam("werkstation") == allowlist.PROFIEL_WERKSTATION
    assert allowlist.profiel_voor_naam("basis") == allowlist.PROFIEL_BASIS


def test_is_allowed_in_profiel():
    assert allowlist.is_allowed_in_profiel("open_program", "basis") is True
    assert allowlist.is_allowed_in_profiel("power", "basis") is False
    assert allowlist.is_allowed_in_profiel("power", "werkstation") is True
    assert allowlist.is_allowed_in_profiel("onbekend", "basis") is False


# ---------------------------------------------------------------
# 6. Discord, Spotify en games blijven starten (ook in basis)
# ---------------------------------------------------------------

VEILIGE_PROGRAMMAS = ["Discord", "Spotify", "Valorant", "Cyberpunk 2077", "Steam"]


@pytest.mark.parametrize("naam", VEILIGE_PROGRAMMAS)
def test_veilig_programma_start_in_basis(naam):
    teller = []
    agent = _agent(
        dispatch=_dispatch_tekst("gedaan", teller), profiel="basis"
    )
    headers, body = _commando("open_program", {"program": naam})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 200
    assert len(teller) == 1
    assert teller[0][0] == "open_program"
    assert teller[0][1] == {"program": naam}


# ---------------------------------------------------------------
# 7. Gamenamen die per ongeluk op de denylist liepen
# ---------------------------------------------------------------

GAMENAMEN = [
    "Idle Champions of the Forgotten Realms",
    "Terminal Velocity",
    "Python Tycoon",
    "Command & Conquer",
    "Ratchet & Clank",
]


@pytest.mark.parametrize("naam", GAMENAMEN)
def test_gamenaam_wordt_toegestaan(naam):
    """Woorden als 'idle', 'terminal' of 'python' in een gamenaam mogen
    niet als denylist-match tellen; '&' moet als teken kunnen."""
    assert allowlist.is_denied_program(naam) is False

    args, fout = allowlist.validate_call("open_program", {"program": naam})
    assert fout is None, naam
    assert args == {"program": naam}


@pytest.mark.parametrize("naam", STARTMENU_NAMEN)
def test_startmenu_naam_blijft_geweigerd(naam):
    """De gevaarlijke Startmenu-namen blijven geweigerd na de
    hele-woorden-matching, óók als de procesnaam niet exact matcht."""
    assert allowlist.is_denied_program(naam) is True

    args, fout = allowlist.validate_call("open_program", {"program": naam})
    assert args is None, naam


@pytest.mark.parametrize("naam", ["cmd", "wt", "bash", "python", "idle", "terminal"])
def test_exacte_procesnaam_blijft_geweigerd(naam):
    """Een exacte programma- of procesnaam blijft geweigerd."""
    assert naam in allowlist.DENIED_PROGRAMS
    assert allowlist.is_denied_program(naam) is True


def test_extra_allowed_programmas_werkt_nog(monkeypatch):
    """De uitzonderingslijst blijft vóór de denylist-matching werken."""
    import config

    assert allowlist.is_denied_program("PowerShell") is True

    monkeypatch.setattr(config, "REMOTE_EXTRA_ALLOWED_PROGRAMS", ("powershell",))
    assert allowlist.is_denied_program("PowerShell") is False

    assert allowlist.DENIED_TYPING_PROGRAMS == frozenset({"explorer"})


# ---------------------------------------------------------------
# 8. Melding bij een geweigerde actie in basis noemt het werkstation-
#    profiel, en audio per app hoort bij het basisprofiel
# ---------------------------------------------------------------

def test_basis_weigert_met_werkstation_hint():
    """De geweigerde actie laat zien hoe je het werkstation-profiel
    aanzet."""
    teller = []
    agent = _agent(dispatch=_dispatch_tekst("gedaan", teller), profiel="basis")
    headers, body = _commando("power", {"action": "shutdown"})

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 403
    assert teller == []
    melding = payload["fout"]["melding"]
    assert "REMOTE_SERVER_PROFILE=werkstation" in melding
    assert "power" in melding


def test_audio_per_app_staat_in_basisprofiel():
    for tool in (
        "audio_set_session_volume",
        "audio_set_session_mute",
        "audio_toggle_session_mute",
    ):
        assert allowlist.is_allowed_in_profiel(tool, "basis") is True


def test_audio_per_app_blijft_risico_medium():
    """De acties blijven risico medium: het brein vraagt nog steeds
    goedkeuring vóór uitvoering."""
    from core.tool_registry import TOOL_RISK

    for tool in (
        "audio_set_session_volume",
        "audio_set_session_mute",
        "audio_toggle_session_mute",
    ):
        risico, _goedkeuring = TOOL_RISK[tool]
        assert risico == "medium", tool


def test_zet_discord_op_20_procent_werkt_in_basis():
    """Een veelgebruikt gamecommando komt door de basis-profielcheck."""
    teller = []
    agent = _agent(dispatch=_dispatch_tekst("gedaan", teller), profiel="basis")
    headers, body = _commando(
        "audio_set_session_volume", {"app_name": "discord", "volume": 20}
    )

    status, payload = agent.process(
        "POST", server.ROUTE_COMMAND, headers, body, client_ip="192.168.1.10"
    )

    assert status == 200
    assert teller[0][1] == {"app_name": "discord", "volume": 20}
