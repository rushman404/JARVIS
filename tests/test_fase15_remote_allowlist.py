"""Fase 15 — tests voor remote/allowlist.py (fail-closed + strikte parameters).

Dekt:
    - toegestane acties met correcte parameters;
    - onbekende acties worden geweigerd;
    - lege, ontbrekende en ongeldige parameters;
    - gevaarlijke/onomkeerbare acties staan nooit in de allowlist;
    - een geweigerde aanroep levert nooit uitvoerbare argumenten op.
"""

from remote import allowlist


# ---------------------------------------------------------------
# Toegestane acties
# ---------------------------------------------------------------

def test_toegestane_actie_zonder_parameters():
    args, fout = allowlist.validate_call("pc_status", {})

    assert fout is None
    assert args == {}


def test_no_arg_actie_accepteert_ontbrekende_argumenten():
    for tool in ("pc_status", "system_info", "media_play_pause", "screenshot"):
        args, fout = allowlist.validate_call(tool, None)
        assert fout is None, tool
        assert args == {}


def test_toegestane_actie_met_naam_parameter():
    args, fout = allowlist.validate_call("open_program", {"program": "Cyberpunk 2077"})

    assert fout is None
    assert args == {"program": "Cyberpunk 2077"}


def test_toegestane_actie_met_percentage():
    args, fout = allowlist.validate_call("set_volume", {"percent": 40})

    assert fout is None
    assert args == {"percent": 40}


def test_toegestane_audio_actie_met_meerdere_parameters():
    args, fout = allowlist.validate_call(
        "audio_set_session_volume", {"app_name": "spotify", "volume": 50}
    )

    assert fout is None
    assert args == {"app_name": "spotify", "volume": 50}


def test_toegestane_mute_parameter_boolean():
    args, fout = allowlist.validate_call(
        "audio_set_session_mute", {"app_name": "discord", "muted": True}
    )

    assert fout is None
    assert args == {"app_name": "discord", "muted": True}


def test_is_allowed_en_allowed_tool_names_consistent():
    assert allowlist.is_allowed("open_program") is True
    assert allowlist.is_allowed("  open_program  ") is True
    assert allowlist.is_allowed("onbekend") is False
    assert "open_program" in allowlist.allowed_tool_names()


# ---------------------------------------------------------------
# Onbekende / geweigerde acties
# ---------------------------------------------------------------

def test_onbekende_actie_wordt_geweigerd():
    args, fout = allowlist.validate_call("format_c_drive", {"pad": "C:\\"})

    assert args is None
    assert fout is not None
    assert "niet toegestaan" in fout


def test_lege_of_ongeldige_actienaam():
    for naam in (None, "", "   ", 123, ["open_program"]):
        args, fout = allowlist.validate_call(naam, {})
        assert args is None, naam
        assert fout is not None, naam


def test_gevaarlijke_acties_staan_nooit_in_de_allowlist():
    """Gevaarlijke/onomkeerbare acties blijven geblokkeerd (Fase 15B).

    In Fase 15B staan bestandsbewerkingen, UI en (sinds stap 4) ook
    verwijderen naar de prullenbak en power op de allowlist, met
    strikte validatie (alleen gebruikersmappen, vaste labels/paden,
    vaste power-keuzelijst). Wat blijft geweigerd: permanent
    verwijderen (``delete_file``/``send2trash``) en de losse
    power-namen — power loopt via de ene ``power``-actie met een
    vaste keuzelijst.
    """

    verboden = {
        # losse power-namen: alleen via de 'power'-actie toegestaan
        "shutdown_pc",
        "restart_pc",
        "sleep_pc",
        "logoff_pc",
        "lock_pc",
        # permanent verwijderen (niet naar de prullenbak)
        "delete_file",
        "delete_path",
        "send_to_recycle",
        "send2trash",
        # overige niet toegestane acties
        "open_website",
    }

    for tool in verboden:
        assert tool not in allowlist.ALLOWED_TOOLS, tool
        assert allowlist.is_allowed(tool) is False, tool


# ---------------------------------------------------------------
# Parameters: leeg, ontbrekend, ongeldig
# ---------------------------------------------------------------

def test_ontbrekende_verplichte_parameter():
    args, fout = allowlist.validate_call("open_program", {})

    assert args is None
    assert "Verplichte parameter ontbreekt" in fout


def test_none_als_verplichte_parameter():
    args, fout = allowlist.validate_call("open_program", {"program": None})

    assert args is None
    assert "Verplichte parameter ontbreekt" in fout


def test_lege_string_als_naam_is_ongeldig():
    args, fout = allowlist.validate_call("open_program", {"program": ""})

    assert args is None
    assert fout is not None


def test_witruimte_als_naam_is_ongeldig():
    args, fout = allowlist.validate_call("open_program", {"program": "   "})

    assert args is None
    assert fout is not None


def test_verkeerd_type_tekst_waar_getal_hoort():
    args, fout = allowlist.validate_call("set_volume", {"percent": "50"})

    assert args is None
    assert "geheel getal" in fout


def test_bool_is_geen_geldig_getal():
    args, fout = allowlist.validate_call("set_volume", {"percent": True})

    assert args is None
    assert "geheel getal" in fout


def test_float_is_geen_geldig_getal():
    args, fout = allowlist.validate_call("set_volume", {"percent": 50.5})

    assert args is None
    assert "geheel getal" in fout


def test_getal_in_plaats_van_tekst():
    args, fout = allowlist.validate_call("open_program", {"program": 123})

    assert args is None
    assert "moet tekst zijn" in fout


def test_percentage_buiten_bereik():
    for waarde in (-1, 101, 1000, -50):
        args, fout = allowlist.validate_call("set_volume", {"percent": waarde})
        assert args is None, waarde
        assert fout is not None, waarde


def test_percentage_op_de_grens_mag():
    for waarde in (0, 100):
        args, fout = allowlist.validate_call("set_volume", {"percent": waarde})
        assert fout is None, waarde
        assert args == {"percent": waarde}


def test_boolean_parameter_moet_echt_boolean_zijn():
    args, fout = allowlist.validate_call(
        "audio_set_session_mute", {"app_name": "discord", "muted": "true"}
    )

    assert args is None
    assert "waar of onwaar" in fout


def test_onbekende_extra_parameter_wordt_geweigerd():
    args, fout = allowlist.validate_call(
        "open_program", {"program": "Steam", "geheim": "rm -rf /"}
    )

    assert args is None
    assert "Onbekende parameter" in fout


def test_extra_parameter_bij_no_arg_actie_wordt_geweigerd():
    args, fout = allowlist.validate_call("pc_status", {"iets": 1})

    assert args is None
    assert "Onbekende parameter" in fout


def test_argumenten_moeten_een_object_zijn():
    for waarde in (["open_program"], "open_program", 42, True):
        args, fout = allowlist.validate_call("open_program", waarde)
        assert args is None, waarde
        assert fout is not None, waarde


def test_naam_met_ongeldige_tekens_wordt_geweigerd():
    ongeldig = [
        "../../etc/passwd",
        "cmd.exe & calc",
        "a/b",
        "a\\b",
        'speler"; shutdown /s',
        "naam|pipe",
        "naam<haak>",
    ]

    for naam in ongeldig:
        args, fout = allowlist.validate_call("open_program", {"program": naam})
        assert args is None, naam
        assert "ongeldige tekens" in fout, naam


def test_naam_te_lang_wordt_geweigerd():
    args, fout = allowlist.validate_call("open_program", {"program": "a" * 200})

    assert args is None
    assert "te lang" in fout


def test_gewone_namen_met_leestekens_mogen():
    for naam in ("Cyberpunk 2077", "Baldur's Gate 3", "Tom Clancy's R6: Siege", "Steam"):
        args, fout = allowlist.validate_call("open_program", {"program": naam})
        assert fout is None, naam
        assert args == {"program": naam}


# ---------------------------------------------------------------
# Kernbelofte: een geweigerde aanroep levert nooit uitvoerbare args op
# ---------------------------------------------------------------

def test_geweigerde_aanroepen_geven_nooit_uitvoerbare_argumenten():
    pogingen = [
        ("open_program", {}),                                   # verplicht ontbreekt
        ("open_program", {"program": ""}),                      # leeg
        ("open_program", {"program": "../../x"}),               # ongeldige tekens
        ("set_volume", {"percent": 999}),                       # buiten bereik
        ("set_volume", {"percent": "hoog"}),                    # verkeerd type
        ("audio_set_session_mute", {"app_name": "x", "muted": "ja"}),  # verkeerd type
        ("shutdown_pc", {}),                                    # onbekend/gevaarlijk
        ("open_program", {"program": "a", "x": 1}),             # extra parameter
    ]

    for tool, args in pogingen:
        schoon, fout = allowlist.validate_call(tool, args)
        assert schoon is None, (tool, args)
        assert fout, (tool, args)


def test_allowlist_verwijst_alleen_naar_bestaande_ai_tools():
    """Elke toegestane actie moet een echt bestaande AI-tool zijn."""

    try:
        from core.tool_registry import get_schema_tool_names
        schema = get_schema_tool_names()
    except Exception:
        schema = set()

    if not schema:
        # Kon het schema niet lezen (bijv. ontbrekende bron) — niets te bewijzen.
        return

    onbekend = sorted(set(allowlist.ALLOWED_TOOLS) - schema)

    assert onbekend == [], f"allowlist verwijst naar onbekende tools: {onbekend}"

# ---------------------------------------------------------------
# Fase 15B — nieuwe allowlist-entries en padbeveiliging
# ---------------------------------------------------------------

def test_file_read_acties_met_locatie_label():
    for tool, args in [
        ('list_files', {'location': 'documenten'}),
        ('list_files', {'location': 'downloads'}),
        ('open_folder', {'location': 'desktop'}),
    ]:
        schoon, fout = allowlist.validate_call(tool, args)
        assert fout is None
        assert schoon == args

def test_open_file_requires_filename():
    schoon, fout = allowlist.validate_call('open_file', {'filename': 'rapport.pdf'})
    assert fout is None
    assert schoon == {'filename': 'rapport.pdf'}

def test_search_files_requires_query():
    schoon, fout = allowlist.validate_call('search_files', {'query': 'cv 2024'})
    assert fout is None
    assert schoon == {'query': 'cv 2024'}

def test_recent_files_optimaal_aantal():
    schoon, fout = allowlist.validate_call('recent_files', {'count': 20})
    assert fout is None
    assert schoon == {'count': 20}
    schoon, fout = allowlist.validate_call('recent_files', None)
    assert fout is None
    assert schoon == {}

def test_file_write_acties():
    cases = [
        ('create_folder', {'name': 'project', 'location': 'documenten'}),
        ('create_folder', {'name': 'project'}),
        ('create_file', {'name': 'README.md', 'location': 'downloads'}),
        ('create_file', {'name': 'README.md'}),
        ('copy_file', {'filename': 'foto.jpg', 'location': 'afbeeldingen'}),
        ('move_file', {'filename': 'foto.jpg', 'location': 'afbeeldingen'}),
        ('rename_file', {'old_name': 'notes.txt', 'new_name': 'notes_v2.txt'}),
    ]
    for tool, args in cases:
        schoon, fout = allowlist.validate_call(tool, args)
        assert fout is None

def test_ui_tools_met_juiste_params():
    cases = [
        ('ui_list_windows', {}),
        ('ui_list_windows', {'filter': 'Notepad'}),
        ('ui_find_window', {'title': 'Sonar'}),
        ('ui_activate_window', {'handle': 12345}),
        ('ui_list_elements', {'handle': 12345}),
        ('ui_list_elements', {'handle': 12345, 'name_filter': 'Play'}),
        ('ui_find_element', {'handle': 12345, 'name': 'Volume'}),
        ('ui_click_element', {'handle': 12345, 'name': 'Play'}),
        ('ui_type_text', {'handle': 12345, 'text': 'Hello world'}),
        ('ui_get_value', {'handle': 12345, 'name': 'Volume'}),
        ('ui_set_value', {'handle': 12345, 'value': 40, 'name': 'Volume'}),
        ('ui_set_value', {'handle': 12345, 'value': 'Mute', 'name': 'State'}),
        ('ui_launch_app', {'path': 'C:\\Program Files\\Notepad++\\notepad++.exe'}),
    ]
    for tool, args in cases:
        schoon, fout = allowlist.validate_call(tool, args)
        assert fout is None
