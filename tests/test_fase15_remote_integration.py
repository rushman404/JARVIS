"""Fase 15, stap 5 - integratie van de Game-PC Agent in JARVIS.

Deze tests dekken de brug (``remote/tools.py``), de toolregistratie
(schema + risico's), de goedkeuringsflow op het brein en de expliciete
routing in ``core/brain.py``. Er wordt GEEN echte server gebruikt: de
remote-client wordt vervangen door een nep-client.
"""
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import core.audit as audit_module
import core.brain as brain
import core.confirmation as confirmation
from core.tool_registry import TOOL_RISK, get_schema_tool_names, run_tool_guarded
from remote import tools as remote_tools
from remote.client import RemoteResult

REMOTE_TOOLS = {
    # Fase 15 - bestaand
    "game_pc_open_program",
    "game_pc_close_program",
    "game_pc_status",
    "game_pc_telemetry",
    "game_pc_screenshot",
    "game_pc_media",
    "game_pc_set_volume",
    "remote_command",
    # Fase 15B - bestanden lezen
    "game_pc_list_files",
    "game_pc_open_folder",
    "game_pc_open_file",
    "game_pc_search_files",
    "game_pc_recent_files",
    # Fase 15B - bestanden wijzigen
    "game_pc_create_folder",
    "game_pc_create_file",
    "game_pc_copy_file",
    "game_pc_move_file",
    "game_pc_rename_file",
    # Fase 15B - scherm
    "game_pc_ui_list_windows",
    "game_pc_ui_find_window",
    "game_pc_ui_activate_window",
    "game_pc_ui_list_elements",
    "game_pc_ui_find_element",
    "game_pc_ui_click_element",
    "game_pc_ui_type_text",
    "game_pc_ui_get_value",
    "game_pc_ui_set_value",
    "game_pc_ui_launch_app",
    # Fase 15B - verwijderen en power (hoog risico)
    "game_pc_recycle_file",
    "game_pc_empty_recycle_bin",
    "game_pc_power",
}

# Alleen deze wrappers zijn echt laag risico (alleen lezen / geen wijziging).
LEES_REMOTE_TOOLS = {
    "game_pc_list_files",
    "game_pc_open_folder",
    "game_pc_open_file",
    "game_pc_search_files",
    "game_pc_recent_files",
    "game_pc_ui_list_windows",
    "game_pc_ui_find_window",
    "game_pc_ui_activate_window",
    "game_pc_ui_list_elements",
    "game_pc_ui_find_element",
    "game_pc_ui_get_value",
}

# Fase 15B-wrappers die iets wijzigen of onomkeerbaar zijn: altijd goedkeuring.
WIJZIGENDE_REMOTE_TOOLS = {
    "game_pc_create_folder",
    "game_pc_create_file",
    "game_pc_copy_file",
    "game_pc_move_file",
    "game_pc_rename_file",
    "game_pc_ui_click_element",
    "game_pc_ui_type_text",
    "game_pc_ui_set_value",
    "game_pc_ui_launch_app",
    "game_pc_recycle_file",
    "game_pc_empty_recycle_bin",
    "game_pc_power",
}

TOKEN = "s" * 32


@pytest.fixture(autouse=True)
def isolatie(monkeypatch):
    """Eigen audit-log, schone pending en geen gecachte client."""

    map_ = tempfile.mkdtemp(prefix="jarvis_f15_int_")
    monkeypatch.setattr(audit_module, "AUDIT_FILE", os.path.join(map_, "audit.jsonl"))
    remote_tools._reset_client()
    confirmation.clear_pending()

    yield

    confirmation.clear_pending()
    remote_tools._reset_client()
    shutil.rmtree(map_, ignore_errors=True)


class NepClient:
    """Vervangt de echte RemoteClient in tests."""

    enabled = True

    def __init__(self, antwoord=None, telemetrie=None):
        self.antwoord = antwoord
        self.telemetrie_antwoord = telemetrie
        self.aanroepen = []

    def send_command(self, tool, arguments=None, idempotent=None):
        self.aanroepen.append((tool, arguments))
        if callable(self.antwoord):
            return self.antwoord(tool, arguments)
        return self.antwoord

    def telemetry(self):
        self.aanroepen.append(("telemetry", None))
        if callable(self.telemetrie_antwoord):
            return self.telemetrie_antwoord()
        return self.telemetrie_antwoord


def _met_client(monkeypatch, client):
    monkeypatch.setattr(remote_tools, "_get_client", lambda: client)


def _ok(bericht="Uitgevoerd"):
    return RemoteResult(True, 200, resultaat={"ok": True, "message": bericht})


# =========================================================
# 1. Schema en risicotabel
# =========================================================


def test_schema_bevat_alle_remote_tools():
    namen = set(get_schema_tool_names())
    assert REMOTE_TOOLS.issubset(namen)


def test_remote_tools_staan_in_de_risicotabel():
    for naam in REMOTE_TOOLS:
        assert naam in TOOL_RISK, naam


def test_remote_command_is_medium_en_niet_idempotent():
    assert TOOL_RISK["remote_command"] == ("medium", False)


def test_lees_remote_tools_zijn_laag_risico():
    for naam in LEES_REMOTE_TOOLS:
        assert TOOL_RISK[naam][0] == "low", naam


def test_wijzigende_remote_tools_vragen_goedkeuring():
    from core.tool_registry import APPROVAL_REQUIRED_RISKS

    for naam in WIJZIGENDE_REMOTE_TOOLS:
        assert TOOL_RISK[naam][0] in APPROVAL_REQUIRED_RISKS, naam


def test_game_pc_media_is_niet_idempotent():
    assert TOOL_RISK["game_pc_media"][1] is False


def test_elke_remote_tool_zit_in_een_categorie():
    from core.tool_select import BASE_TOOLS, CATEGORIES

    in_categorie = set(BASE_TOOLS)
    for tools in CATEGORIES.values():
        in_categorie.update(tools)

    ontbreekt = REMOTE_TOOLS - in_categorie
    assert ontbreekt == set(), f"zonder categorie: {sorted(ontbreekt)}"


# =========================================================
# 2. Goedkeuring op het brein
# =========================================================


def test_remote_command_vraagt_eerst_goedkeuring():
    aangeroepen = []

    def dispatch(naam, argumenten, vraag):
        aangeroepen.append(naam)
        return "uitgevoerd"

    bericht = run_tool_guarded(
        "remote_command", {"tool": "media_next"}, source="test", dispatch=dispatch
    )

    assert aangeroepen == []  # nog niets uitgevoerd
    pending = confirmation.get_pending()
    assert pending is not None
    assert pending.get("kind") == "tool_approval"
    assert pending.get("tool_name") == "remote_command"
    assert "akkoord" in bericht.lower()


def test_game_pc_status_laag_risico_voert_direct_uit():
    def dispatch(naam, argumenten, vraag):
        return "Game-pc is online"

    uit = run_tool_guarded("game_pc_status", {}, source="test", dispatch=dispatch)
    assert uit == "Game-pc is online"


# =========================================================
# 3. De brug: geslaagd / mislukt / onzeker
# =========================================================


def test_open_program_geslaagd(monkeypatch):
    nep = NepClient(antwoord=_ok("Discord gestart"))
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool(
        "game_pc_open_program", {"program": "discord"}
    )

    assert resultaat.ok is True
    assert resultaat.data["status"] == "geslaagd"
    assert "Discord gestart" in resultaat.message
    assert nep.aanroepen == [("open_program", {"program": "discord"})]


def test_close_program_stuurt_juiste_actie(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool("game_pc_close_program", {"program": "steam"})
    assert nep.aanroepen == [("close_program", {"program": "steam"})]


def test_status_stuurt_pc_status(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool("game_pc_status", {})
    assert nep.aanroepen == [("pc_status", {})]


def test_screenshot_stuurt_screenshot(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool("game_pc_screenshot", {})
    assert nep.aanroepen == [("screenshot", {})]


def test_media_stuurt_mediatoets(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool("game_pc_media", {"action": "next"})
    assert nep.aanroepen == [("media_next", {})]


def test_set_volume_stuurt_percentage(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool("game_pc_set_volume", {"percent": 25})
    assert nep.aanroepen == [("set_volume", {"percent": 25})]


def test_telemetrie_wordt_uitgepakt(monkeypatch):
    telemetrie = {
        "cpu": {"gebruik_percent": 12},
        "ram": {"percentage": 40},
        "gpu": {"gpus": [{"naam": "RTX 4070", "gebruik_percent": 30, "temperatuur_c": 55}]},
    }
    nep = NepClient(
        telemetrie=RemoteResult(True, 200, resultaat={"ok": True, "telemetrie": telemetrie})
    )
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("game_pc_telemetry", {})

    assert resultaat.ok is True
    assert resultaat.data["status"] == "geslaagd"
    assert resultaat.data["telemetrie"] == telemetrie
    assert "CPU 12%" in resultaat.message
    assert "RTX 4070" in resultaat.message


def test_niet_bereikbaar_is_mislukt(monkeypatch):
    nep = NepClient(
        antwoord=RemoteResult(False, 0, fout_code="niet_bereikbaar", fout_melding="geen verbinding")
    )
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("game_pc_status", {})

    assert resultaat.ok is False
    assert resultaat.data["status"] == "mislukt"
    assert resultaat.error_kind == "remote_mislukt"


@pytest.mark.parametrize("code", ["timeout", "verbinding_verbroken"])
def test_timeout_en_verbroken_zijn_onzeker(monkeypatch, code):
    nep = NepClient(antwoord=RemoteResult(False, 0, fout_code=code, fout_melding="weggevallen"))
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("game_pc_status", {})

    assert resultaat.ok is False
    assert resultaat.data["status"] == "onzeker"
    assert resultaat.error_kind == "remote_onzeker"


# =========================================================
# 4. remote_command: gecontroleerde fallback
# =========================================================


def test_remote_command_met_toegestane_actie(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool("remote_command", {"tool": "media_next"})
    assert nep.aanroepen == [("media_next", {})]


@pytest.mark.parametrize(
    "actie", ["shutdown_pc", "delete_file", "send2trash", "format_disk"]
)
def test_remote_command_weigert_niet_toegestane_actie(monkeypatch, actie):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("remote_command", {"tool": actie})

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_niet_toegestaan"
    assert nep.aanroepen == []  # nooit naar de server gestuurd


def test_remote_command_argumenten_moet_object_zijn(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool(
        "remote_command", {"tool": "open_program", "arguments": ["steam"]}
    )

    assert resultaat.error_kind == "remote_argumenten"
    assert nep.aanroepen == []


# =========================================================
# 5. Randgevallen en fail-closed
# =========================================================


def test_ontbrekend_argument_wordt_geweigerd(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("game_pc_open_program", {})

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_argumenten"
    assert nep.aanroepen == []


def test_onbekende_remote_tool(monkeypatch):
    resultaat = remote_tools.execute_remote_tool("game_pc_bestaat_niet", {})
    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_onbekend"


def test_client_uit_is_fail_closed(monkeypatch):
    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    monkeypatch.setattr(config, "REMOTE_CLIENT_TOKEN", "")
    monkeypatch.setattr(config, "REMOTE_CLIENT_CA_FILE", "")
    remote_tools._reset_client()

    resultaat = remote_tools.execute_remote_tool("game_pc_status", {})

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_config"


def test_is_remote_tool():
    assert remote_tools.is_remote_tool("game_pc_status") is True
    assert remote_tools.is_remote_tool("open_program") is False


# =========================================================
# 6. Expliciete routing in core/brain.py
# =========================================================


ROUTING = [
    ("open discord op de game-pc", "game_pc_open_program", {"program": "discord"}),
    ("start elden ring op de game-pc", "game_pc_open_program", {"program": "elden ring"}),
    ("sluit steam op de game-pc", "game_pc_close_program", {"program": "steam"}),
    ("maak een screenshot op de game-pc", "game_pc_screenshot", {}),
    ("wat is de temperatuur van de game-pc", "game_pc_telemetry", {}),
    ("hoeveel geheugen heeft de gaming-pc", "game_pc_telemetry", {}),
    ("is de game-pc online", "game_pc_status", {}),
    ("wat is de status van de game-pc", "game_pc_status", {}),
    ("zet het volume op 30 op de game-pc", "game_pc_set_volume", {"percent": 30}),
    ("pauzeer de muziek op de game-pc", "game_pc_media", {"action": "play_pause"}),
    ("volgende nummer op de game-pc", "game_pc_media", {"action": "next"}),
]


@pytest.mark.parametrize("zin,tool,argumenten", ROUTING)
def test_brain_routeert_game_pc(monkeypatch, zin, tool, argumenten):
    gevangen = []
    monkeypatch.setattr(
        brain, "execute_tool", lambda t, a, q: gevangen.append((t, a)) or "ok"
    )

    brain.try_game_pc_command(zin)

    assert gevangen == [(tool, argumenten)]


@pytest.mark.parametrize(
    "zin",
    [
        "open kladblok",
        "maak een screenshot",
        "zet het volume op 30",
        "hoeveel geheugen heb ik",
        "zet de lamp aan",
        "onthoud dat de game-pc in de woonkamer staat",
    ],
)
def test_geen_game_pc_opdracht_wordt_niet_gekaapt(monkeypatch, zin):
    gevangen = []
    monkeypatch.setattr(
        brain, "execute_tool", lambda t, a, q: gevangen.append((t, a)) or "ok"
    )

    assert brain.try_game_pc_command(zin) is None
    assert gevangen == []


@pytest.mark.parametrize(
    "zin",
    [
        "zet de game-pc uit",
        "herstart de game-pc",
        "zet de game-pc in slaapstand",
        "schakel de game-pc uit",
    ],
)
def test_game_pc_power_wordt_veilig_geweigerd(monkeypatch, zin):
    gevangen = []
    monkeypatch.setattr(
        brain, "execute_tool", lambda t, a, q: gevangen.append((t, a)) or "ok"
    )

    antwoord = brain.try_game_pc_command(zin)

    assert gevangen == []
    assert antwoord is not None
    assert "veiligheidsredenen" in antwoord


def test_process_command_routeert_game_pc_open(monkeypatch):
    gevangen = []
    monkeypatch.setattr(
        brain,
        "execute_tool",
        lambda t, a, q: gevangen.append((t, a)) or "Discord gestart op de game-pc",
    )

    antwoord = brain.process_command("open discord op de game-pc")

    assert gevangen == [("game_pc_open_program", {"program": "discord"})]
    assert "game-pc" in antwoord


# =========================================================
# 6. Fase 15B — nieuwe wrappers (bestanden + scherm)
# =========================================================


NIEUWE_WRAPPERS = {
    # bestanden lezen
    "game_pc_list_files",
    "game_pc_open_folder",
    "game_pc_open_file",
    "game_pc_search_files",
    "game_pc_recent_files",
    # bestanden wijzigen
    "game_pc_create_folder",
    "game_pc_create_file",
    "game_pc_copy_file",
    "game_pc_move_file",
    "game_pc_rename_file",
    # scherm
    "game_pc_ui_list_windows",
    "game_pc_ui_find_window",
    "game_pc_ui_activate_window",
    "game_pc_ui_list_elements",
    "game_pc_ui_find_element",
    "game_pc_ui_click_element",
    "game_pc_ui_type_text",
    "game_pc_ui_get_value",
    "game_pc_ui_set_value",
    "game_pc_ui_launch_app",
}


def test_nieuwe_wrappers_zitten_in_remote_tool_names():
    ontbrekend = sorted(NIEUWE_WRAPPERS - remote_tools.REMOTE_TOOL_NAMES)

    assert ontbrekend == []
    for naam in NIEUWE_WRAPPERS:
        assert remote_tools.is_remote_tool(naam) is True, naam


@pytest.mark.parametrize(
    "wrapper, argumenten, agent_tool, verwacht",
    [
        (
            "game_pc_list_files",
            {"location": "documenten"},
            "list_files",
            {"location": "documenten"},
        ),
        (
            "game_pc_open_folder",
            {"location": "downloads"},
            "open_folder",
            {"location": "downloads"},
        ),
        (
            "game_pc_open_file",
            {"filename": "rapport.pdf"},
            "open_file",
            {"filename": "rapport.pdf"},
        ),
        (
            "game_pc_search_files",
            {"query": "cv"},
            "search_files",
            {"query": "cv"},
        ),
        ("game_pc_recent_files", {}, "recent_files", {}),
    ],
)
def test_single_param_wrappers_bij_een_agent(
    monkeypatch, wrapper, argumenten, agent_tool, verwacht
):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool(wrapper, argumenten)

    assert nep.aanroepen == [(agent_tool, verwacht)]


@pytest.mark.parametrize(
    "wrapper, argumenten, agent_tool, verwacht",
    [
        (
            "game_pc_create_folder",
            {"name": "project", "location": "documenten"},
            "create_folder",
            {"name": "project", "location": "documenten"},
        ),
        (
            "game_pc_copy_file",
            {"filename": "foto.jpg", "location": "afbeeldingen"},
            "copy_file",
            {"filename": "foto.jpg", "location": "afbeeldingen"},
        ),
        (
            "game_pc_rename_file",
            {"old_name": "a.txt", "new_name": "b.txt"},
            "rename_file",
            {"old_name": "a.txt", "new_name": "b.txt"},
        ),
        (
            "game_pc_ui_type_text",
            {"handle": 12345, "text": "hallo"},
            "ui_type_text",
            {"handle": 12345, "text": "hallo"},
        ),
        (
            "game_pc_ui_launch_app",
            {"path": "C:\\Program Files\\Notepad++\\notepad++.exe"},
            "ui_launch_app",
            {"path": "C:\\Program Files\\Notepad++\\notepad++.exe"},
        ),
    ],
)
def test_multi_param_wrappers_bij_een_agent(
    monkeypatch, wrapper, argumenten, agent_tool, verwacht
):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool(wrapper, argumenten)

    assert nep.aanroepen == [(agent_tool, verwacht)]


@pytest.mark.parametrize(
    "wrapper, argumenten",
    [
        # pad in plaats van gebruikersmap
        ("game_pc_list_files", {"location": "C:\\Windows"}),
        ("game_pc_open_folder", {"location": "..\\Windows"}),
        # padverwijzing in een bestandsnaam
        ("game_pc_create_file", {"name": "..\\evil.txt"}),
        # onveilig programma-pad
        ("game_pc_ui_launch_app", {"path": "..\\..\\evil.exe"}),
    ],
)
def test_onveilige_wrapper_wordt_in_de_brug_geweigerd(
    monkeypatch, wrapper, argumenten
):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool(wrapper, argumenten)

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_niet_toegestaan"
    assert nep.aanroepen == []  # nooit naar de game-pc gestuurd


def test_single_param_wrapper_zonder_argument_vraagt_remote_argumenten(monkeypatch):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("game_pc_list_files", {})

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_argumenten"
    assert nep.aanroepen == []


def test_multi_param_wrapper_zonder_argument_wordt_door_allowlist_geweigerd(
    monkeypatch,
):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool("game_pc_create_folder", {})

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_niet_toegestaan"
    assert nep.aanroepen == []


def test_process_command_raakt_lokale_power_niet_aan(monkeypatch):
    def _verboden(*args, **kwargs):
        raise AssertionError("lokale power mocht niet draaien")

    monkeypatch.setattr(brain, "try_power_command", _verboden)

    antwoord = brain.process_command("zet de game-pc uit")

    assert "veiligheidsredenen" in antwoord


# =========================================================
# 7. Fase 15B - verwijderen naar de prullenbak en power
# =========================================================


@pytest.mark.parametrize(
    "wrapper, argumenten, agent_tool, verwacht",
    [
        (
            "game_pc_recycle_file",
            {"filename": "oud.txt"},
            "recycle_file",
            {"filename": "oud.txt"},
        ),
        ("game_pc_empty_recycle_bin", {}, "empty_recycle_bin", {}),
        ("game_pc_power", {"action": "shutdown"}, "power", {"action": "shutdown"}),
        ("game_pc_power", {"action": "hibernate"}, "power", {"action": "hibernate"}),
        ("game_pc_power", {"action": "lock"}, "power", {"action": "lock"}),
    ],
)
def test_prullenbak_en_power_wrappers_bij_een_agent(
    monkeypatch, wrapper, argumenten, agent_tool, verwacht
):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    remote_tools.execute_remote_tool(wrapper, argumenten)

    assert nep.aanroepen == [(agent_tool, verwacht)]


@pytest.mark.parametrize(
    "wrapper, argumenten",
    [
        ("game_pc_power", {"action": "explode"}),
        ("game_pc_power", {"action": "format"}),
        ("game_pc_recycle_file", {"filename": "..\\evil.txt"}),
        ("game_pc_recycle_file", {"filename": "C:\\Windows\\x.txt"}),
    ],
)
def test_prullenbak_en_power_weigeren_onveilige_waarde(monkeypatch, wrapper, argumenten):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool(wrapper, argumenten)

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_niet_toegestaan"
    assert nep.aanroepen == []  # nooit naar de game-pc gestuurd


@pytest.mark.parametrize(
    "wrapper",
    ["game_pc_power", "game_pc_recycle_file"],
)
def test_prullenbak_en_power_zonder_verplicht_argument(monkeypatch, wrapper):
    nep = NepClient(antwoord=_ok())
    _met_client(monkeypatch, nep)

    resultaat = remote_tools.execute_remote_tool(wrapper, {})

    assert resultaat.ok is False
    assert resultaat.error_kind == "remote_argumenten"
    assert nep.aanroepen == []


def test_prullenbak_en_power_risico():
    assert TOOL_RISK["game_pc_recycle_file"][0] == "medium"
    assert TOOL_RISK["game_pc_empty_recycle_bin"][0] == "high"
    assert TOOL_RISK["game_pc_power"][0] == "high"
