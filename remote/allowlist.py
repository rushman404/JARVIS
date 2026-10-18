"""Fase 15 — Game-PC Agent: de lijst met remote toegestane acties.

Fail-closed: alleen wat hier expliciet staat mag de game-pc op afstand
uitvoeren. Alles daarbuiten wordt geweigerd.

Sinds Fase 15B (de game-pc is het werkstation) staan hier ook in:

* **bestanden lezen** — ``list_files``, ``open_folder``, ``open_file``,
  ``search_files`` en ``recent_files`` (laag risico, geen vraag);
* **bestanden wijzigen** — ``create_folder``, ``create_file``,
  ``copy_file``, ``move_file`` en ``rename_file`` (middel);
* **het scherm bedienen** — de ``ui_*``-tools, inclusief
  ``ui_launch_app`` (middel/hoog).

Sinds stap 4 van Fase 15B staan hier ook **verwijderen en power** in:
``recycle_file`` (naar de prullenbak, nooit definitief), 
``empty_recycle_bin`` en ``power`` (afsluiten, herstarten, slapen,
sluimerstand, vergrendelen, uitloggen). Die hebben een hoog risico en
gaan aan de brein-kant daarom altijd langs de goedkeuringspoort.

Bewust NIET toegestaan op afstand blijft: definitief verwijderen
(``delete_file``/``send2trash``) en de losse namen ``shutdown_pc``,
``restart_pc``, ``sleep_pc``, ``lock_pc`` en ``logoff_pc`` — power loopt
altijd via de ene ``power``-actie met een vaste keuzelijst.

**Alleen de gebruikersmappen.** ``location`` mag uitsluitend één van de
vaste map-labels zijn (bureaublad, desktop, downloads, documenten,
afbeeldingen, pictures, foto's, muziek, video's). Elk pad —
scheidingstekens, stationsletter, ``..``, ``~``, UNC — wordt met een
duidelijke melding geweigerd. ``ui_launch_app`` is de enige tool die
een pad krijgt; dat moet een absoluut pad zijn zonder ``..``, ``%`` of
netwerksleutels.

Medium/high-acties komen remote wél door deze lijst, maar ze gaan aan
de brein-kant altijd door ``core.tool_registry.run_tool_guarded``: die
vraagt op basis van de risicotabel om goedkeuring vóórdat er iets naar
de game-pc gaat.

Parameters worden strikt gevalideerd:

* het moet een JSON-object (dict) zijn, of ontbreken bij acties zonder
  parameters;
* onbekende/extra parameters worden geweigerd;
* verplichte parameters moeten aanwezig zijn;
* types en bereiken worden gecontroleerd (geen ``True`` als getal,
  geen tekst waar een getal hoort);
* locaties zijn vaste labels en nooit paden;
* naam-achtige waarden moeten aan een conservatief tekenpatroon
  voldoen, zodat rare paden of injecties geen kans krijgen.

``validate_call()`` geeft NOOIT iets terug dat uitgevoerd kan worden
als de actie niet is toegestaan: in dat geval is het resultaat
``(None, reden)``.
"""

import re

# Gebruikersnaam-achtige waarden (programma's, games, apps, apparaten).
# Bewust conservatief: letters/cijfers, spatie en een klein setje
# leestekens. Geen slashes, backslashes, quotes, punt-komma's of
# pijp/aanhalingstekens. '&' en de apostrof mogen wél: er wordt nooit
# een shell gebruikt, dus "Command & Conquer" en "Baldur's Gate 3"
# moeten als programmanaam kunnen.
NAME_PATTERN = r"^[\w .\-+'&():!]{1,120}$"

# URL's voor open_website: optioneel schema, geen spaties of stuurtekens.
URL_PATTERN = r"^(?:https?://)?[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]{1,400}$"

STRING = "string"
INTEGER = "integer"
BOOLEAN = "boolean"

MAX_NAME_LENGTH = 120


def _name_param(required=True):
    """Parameter voor een programma-, game-, app- of apparaatnaam."""

    return {
        "type": STRING,
        "required": required,
        "min_length": 1,
        "max_length": MAX_NAME_LENGTH,
        "pattern": NAME_PATTERN,
    }


def _percent_param():
    """Parameter voor een volume-percentage (0-100)."""

    return {
        "type": INTEGER,
        "required": True,
        "min_value": 0,
        "max_value": 100,
    }


def _bool_param():
    """Parameter voor een waar/onwaar-vlag."""

    return {"type": BOOLEAN, "required": True}


# =============================================================
# BESTANDEN EN SCHERM (FASE 15B)
# =============================================================
# Alleen de gebruikersmappen van de game-pc mogen op afstand worden
# bediend. ``location`` is daarom geen pad maar een vast label; elk
# pad (scheidingstekens, stationsletter, '..', '~', UNC) wordt met
# een duidelijke melding geweigerd.

LOCATION = "location"
TEXT = "text"
SCALAR = "scalar"
PATH = "path"

# Exact de labels die actions/file_manager.py resolve_location() kent,
# zodat de allowlist en de lokale uitvoering dezelfde mappen bedoelen.
LOCATION_LABELS = (
    "bureaublad",
    "desktop",
    "downloads",
    "documenten",
    "afbeeldingen",
    "pictures",
    "foto's",
    "fotos",
    "muziek",
    "video's",
    "videos",
    "movies",
)

# Voor foutmeldingen: de AI kan hier direct op herstellen.
LOCATION_HULP = (
    "bureaublad, desktop, downloads, documenten, afbeeldingen, "
    "pictures, foto's, muziek, video's"
)

# Bestands-/programmanamen: als NAME_PATTERN, maar zonder ':' (die
# hoort bij schijfpaden) en zonder '&' of andere shell-tekens.
BESTANDSNAAM_PATTERN = r"^[\w .\-+'()!]{1,120}$"

# Bovengrens voor UI-handles en voor 'getal of tekst'-waarden.
MAX_HANDLE = 2 ** 63 - 1
MAX_SCALAR = 10 ** 9

# =============================================================
# Server-denylist van programma's (Fase 15C)
# =============================================================
# Programma's die nooit op de game-pc gestart mogen worden via
# ui_launch_app of open_program. Op naam én op uitvoerbaar bestand,
# hoofdletterongevoelig, ook wanneer er een pad voor staat.
DENIED_PROGRAMS = frozenset(
    {
        "cmd",
        "powershell",
        "pwsh",
        "wscript",
        "cscript",
        "mshta",
        "regedit",
        "regedt32",
        "reg",
        "rundll32",
        "regsvr32",
        "msiexec",
        "schtasks",
        "taskkill",
        "net",
        "netsh",
        "curl",
        "bitsadmin",
        "certutil",
        "wmic",
        "mmc",
        "bash",
        "wsl",
        "wslhost",
        "terminal",
        "python",
        "pythonw",
        "python3",
        "py",
        "idle",
        "windowsterminal",
        "wt",
        "conhost",
        "openconsole",
        "mintty",
        "git-bash",
        "powershell_ise",
        "msconfig",
        "diskpart",
        "cipher",
        "sc",
        "bcdedit",
        "eventvwr",
        "compmgmt",
        "lusrmgr",
    }
)

# Controle op de weergavenaam (bv. "Windows PowerShell (x86)").
# Alleen bekende gevaarlijke combinaties, gematcht op HELE WOORDEN.
# Losse korte stukjes als "idle", "terminal" of "bash" staan hier
# bewust NIET in: een gamenaam als "Idle Champions of the Forgotten
# Realms", "Terminal Velocity" of "Python Tycoon" moet blijven werken.
# Exacte procesnamen (cmd, wt, bash, python, idle, terminal) vallen
# wel op DENIED_PROGRAMS.
DENIED_NAME_COMBINATIONS = (
    "windows powershell",
    "powershell",
    "command prompt",
    "windows terminal",
    "git bash",
    "registry editor",
    "task scheduler",
    "windows script host",
    "subsystem for linux",
    "python 3",
    "idle (python",
)

# Programma's die extra alleen voor typen (ui_type_text, ui_click_element,
# ui_set_value) geweigerd worden. "explorer" mag wél geopend worden via
# open_program, maar je mag er niet intypen of in klikken.
DENIED_TYPING_PROGRAMS = frozenset({"explorer"})


def _programma_naam_uit_waarde(waarde):
    """Haalt de naam van het uitvoerbare bestand uit een pad of naam.

    Geeft de naam zonder pad en zonder extensie, in kleine letters.
    Voor een losse naam zoals "PowerShell" geeft dat "powershell".
    """
    if not isinstance(waarde, str):
        return ""

    tekst = waarde.strip().replace("/", "\\")
    base = tekst.rsplit("\\", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.strip().lower()


def _extra_toegestane_programmas():
    """De uitzonderingslijst uit de serverconfig (standaard leeg)."""
    try:
        import config

        return getattr(config, "REMOTE_EXTRA_ALLOWED_PROGRAMS", ())
    except Exception:
        return ()


def is_denied_program(waarde):
    """True als het programma op de denylist staat en NIET is vrijgesteld."""
    naam = _programma_naam_uit_waarde(waarde)

    if not naam:
        return False

    if naam in _extra_toegestane_programmas():
        return False

    # "alles met uninstall"
    if "uninstall" in str(waarde).lower():
        if naam not in _extra_toegestane_programmas():
            return True

    if naam in DENIED_PROGRAMS:
        return True

    # Controle op de weergavenaam: alleen bekende gevaarlijke combinaties
    # op hele woorden, bv. "Windows PowerShell (x86)" of "Python 3.12
    # (64-bit)". Een los woord als "terminal" in "Terminal Velocity"
    # of "idle" in "Idle Champions" matcht niet.
    tekst = str(waarde).lower()
    for combinatie in DENIED_NAME_COMBINATIONS:
        if re.search(r"\b" + re.escape(combinatie) + r"\b", tekst):
            return True

    return False


def _location_param(required=True):
    """Gebruikersmap: alleen een vast label, nooit een pad."""

    return {
        "type": LOCATION,
        "required": required,
        "allow_empty": not required,
    }


def _bestandsnaam_param():
    """Eén bestands- of mapnaam (geen pad, geen '..')."""

    return {
        "type": STRING,
        "required": True,
        "min_length": 1,
        "max_length": MAX_NAME_LENGTH,
        "pattern": BESTANDSNAAM_PATTERN,
        "reject": ("..",),
    }


def _tekst_param(required=True, max_length=200):
    """Vrije tekst voor schermbediening (venster-/elementnamen, tekst)."""

    return {
        "type": TEXT,
        "required": required,
        "max_length": max_length,
        "allow_empty": not required,
    }


def _zoekvraag_param():
    """Zoekterm voor bestanden: tekst zonder pad-achtige stukken."""

    return {
        "type": TEXT,
        "required": True,
        "max_length": MAX_NAME_LENGTH,
        "reject": ("/", "\\", ".."),
    }


def _handle_param():
    """Venster-handle van een ui_*-tool."""

    return {
        "type": INTEGER,
        "required": True,
        "min_value": 1,
        "max_value": MAX_HANDLE,
    }


def _count_param():
    """Aantal resultaten (bijv. recent_files)."""

    return {
        "type": INTEGER,
        "required": False,
        "min_value": 1,
        "max_value": 100,
    }


def _scalar_param():
    """Tekst óf getal (voor ui_set_value)."""

    return {
        "type": SCALAR,
        "required": True,
        "max_length": 200,
    }


def _pad_param():
    """Absoluut programma-pad (alleen voor ui_launch_app)."""

    return {
        "type": PATH,
        "required": True,
        "max_length": 300,
    }


def _url_param():
    """Een http(s)-URL voor open_website (geen spaties/stuurtekens)."""

    return {
        "type": STRING,
        "required": True,
        "min_length": 1,
        "max_length": 400,
        "pattern": URL_PATTERN,
    }


# =============================================================
# DE ALLOWLIST
# =============================================================
# toolnaam -> {"description": ..., "params": {naam: specificatie}}
#
# De toolnamen komen overeen met de namen in het AI-schema
# (core/ai.py) en de risicotabel (core/tool_registry.py).

ALLOWED_TOOLS = {
    # ---- Games & programma's ----
    "open_program": {
        "description": "Zoek een programma of game en start het.",
        "params": {"program": _name_param()},
    },
    "close_program": {
        "description": "Sluit een draaiend programma of game.",
        "params": {"program": _name_param()},
    },
    "restart_program": {
        "description": "Herstart een programma of game.",
        "params": {"program": _name_param()},
    },
    "program_status": {
        "description": "Controleer of een programma draait.",
        "params": {"program": _name_param()},
    },
    "find_program_location": {
        "description": "Zoek het pad van een geïnstalleerd programma.",
        "params": {"program": _name_param()},
    },

    # ---- Vensters ----
    "minimize_window": {
        "description": "Minimaliseer het venster van een programma.",
        "params": {"program": _name_param()},
    },
    "maximize_window": {
        "description": "Maximaliseer het venster van een programma.",
        "params": {"program": _name_param()},
    },
    "restore_window": {
        "description": "Herstel het venster van een programma.",
        "params": {"program": _name_param()},
    },

    # ---- Status & telemetrie ----
    "system_info": {
        "description": "Systeeminformatie: CPU, GPU, RAM, schijf, uptime.",
        "params": {},
    },
    "pc_status": {
        "description": "Volledige pc-status in één overzicht.",
        "params": {},
    },

    # ---- Media (systeembreed) ----
    "media_play_pause": {
        "description": "Afspelen of pauzeren (wisselt).",
        "params": {},
    },
    "media_next": {
        "description": "Naar het volgende nummer.",
        "params": {},
    },
    "media_previous": {
        "description": "Naar het vorige nummer.",
        "params": {},
    },
    "media_stop": {
        "description": "Media volledig stoppen.",
        "params": {},
    },
    "media_mute": {
        "description": "Het systeemgeluid dempen of ontdempen (wisselt).",
        "params": {},
    },
    "volume_up": {
        "description": "Het volume iets omhoog zetten.",
        "params": {},
    },
    "volume_down": {
        "description": "Het volume iets omlaag zetten.",
        "params": {},
    },
    "set_volume": {
        "description": "Het systeemvolume op een percentage zetten.",
        "params": {"percent": _percent_param()},
    },

    # ---- Audio per app ----
    "audio_list_sessions": {
        "description": "Lijst apps die nu audio afspelen.",
        "params": {},
    },
    "audio_get_session_volume": {
        "description": "Lees het volume van één app.",
        "params": {"app_name": _name_param()},
    },
    "audio_set_session_volume": {
        "description": "Zet het volume van één app (0-100).",
        "params": {"app_name": _name_param(), "volume": _percent_param()},
    },
    "audio_set_session_mute": {
        "description": "Demp of ontdemp één app.",
        "params": {"app_name": _name_param(), "muted": _bool_param()},
    },
    "audio_toggle_session_mute": {
        "description": "Draai de mute-status van één app om.",
        "params": {"app_name": _name_param()},
    },
    "audio_list_outputs": {
        "description": "Lijst audio-uitvoerapparaten.",
        "params": {},
    },
    "audio_get_default_output": {
        "description": "Het huidige standaard audio-uitvoerapparaat.",
        "params": {},
    },
    "audio_set_default_output": {
        "description": "Wissel het standaard audio-uitvoerapparaat.",
        "params": {"device_name": _name_param()},
    },

    # ---- Scherm ----
    "screenshot": {
        "description": "Maak een screenshot van het scherm.",
        "params": {},
    },

    # ---- Bestanden lezen (Fase 15B, laag risico) ----
    "list_files": {
        "description": "Toon de inhoud van een gebruikersmap.",
        "params": {"location": _location_param()},
    },
    "open_folder": {
        "description": "Open een gebruikersmap in Windows Verkenner.",
        "params": {"location": _location_param()},
    },
    "open_file": {
        "description": "Zoek een bestand in de gebruikersmappen en open het.",
        "params": {"filename": _bestandsnaam_param()},
    },
    "search_files": {
        "description": "Zoek een bestand in de gebruikersmappen.",
        "params": {"query": _zoekvraag_param()},
    },
    "recent_files": {
        "description": "Toon de recent geopende bestanden.",
        "params": {"count": _count_param()},
    },

    # ---- Bestanden wijzigen (Fase 15B, middel: vraagt goedkeuring) ----
    "create_folder": {
        "description": "Maak een nieuwe map in een gebruikersmap.",
        "params": {
            "name": _bestandsnaam_param(),
            "location": _location_param(required=False),
        },
    },
    "create_file": {
        "description": "Maak een nieuw bestand in een gebruikersmap.",
        "params": {
            "name": _bestandsnaam_param(),
            "location": _location_param(required=False),
        },
    },
    "copy_file": {
        "description": "Kopieer een bestand naar een gebruikersmap.",
        "params": {
            "filename": _bestandsnaam_param(),
            "location": _location_param(),
        },
    },
    "move_file": {
        "description": "Verplaats een bestand naar een gebruikersmap.",
        "params": {
            "filename": _bestandsnaam_param(),
            "location": _location_param(),
        },
    },
    "rename_file": {
        "description": "Hernoem een bestand of map in de gebruikersmappen.",
        "params": {
            "old_name": _bestandsnaam_param(),
            "new_name": _bestandsnaam_param(),
        },
    },

    # ---- Het scherm bedienen (Fase 15B, middel/hoog) ----
    "ui_list_windows": {
        "description": "Lijst de open vensters op.",
        "params": {"filter": _tekst_param(required=False)},
    },
    "ui_find_window": {
        "description": "Zoek een venster op (een deel van) de titel.",
        "params": {"title": _tekst_param()},
    },
    "ui_activate_window": {
        "description": "Breng een venster naar de voorgrond.",
        "params": {"handle": _handle_param()},
    },
    "ui_list_elements": {
        "description": "Lijst de bedienbare elementen van een venster.",
        "params": {
            "handle": _handle_param(),
            "name_filter": _tekst_param(required=False),
        },
    },
    "ui_find_element": {
        "description": "Vind een element in een venster op naam of type.",
        "params": {
            "handle": _handle_param(),
            "name": _tekst_param(),
            "control_type": _tekst_param(required=False),
        },
    },
    "ui_click_element": {
        "description": "Klik op een element (knop) in een venster.",
        "params": {
            "handle": _handle_param(),
            "name": _tekst_param(),
            "control_type": _tekst_param(required=False),
        },
    },
    "ui_type_text": {
        "description": "Typ tekst in een venster of invoerveld.",
        "params": {
            "handle": _handle_param(),
            "text": _tekst_param(max_length=2000),
            "element_name": _tekst_param(required=False),
        },
    },
    "ui_get_value": {
        "description": "Lees de waarde van een element uit.",
        "params": {
            "handle": _handle_param(),
            "name": _tekst_param(),
        },
    },
    "ui_set_value": {
        "description": "Stel de waarde van een element in.",
        "params": {
            "handle": _handle_param(),
            "value": _scalar_param(),
            "name": _tekst_param(),
        },
    },
    "ui_launch_app": {
        "description": "Start een applicatie via een absoluut pad.",
        "params": {"path": _pad_param()},
    },

    # ---- Browser & websites (Taak F, laag risico) ----
    "open_website": {
        "description": "Open een website in de standaardbrowser.",
        "params": {"url": _url_param()},
    },
    "browser_search": {
        "description": "Zoek op een website en open de zoekresultaten.",
        "params": {
            "query": _tekst_param(required=True, max_length=200),
            "site": _tekst_param(required=False, max_length=50),
        },
    },
    "browser_back": {
        "description": "Ga terug in de browser.",
        "params": {},
    },
    "browser_forward": {
        "description": "Ga vooruit in de browser.",
        "params": {},
    },
    "browser_refresh": {
        "description": "Ververs de pagina in de browser.",
        "params": {},
    },
    "browser_new_tab": {
        "description": "Open een nieuw tabblad in de browser.",
        "params": {},
    },
    "browser_close_tab": {
        "description": "Sluit het huidige tabblad in de browser.",
        "params": {},
    },

    # ---- Verwijderen + power (Fase 15B, hoog: vraagt goedkeuring) ----
    "recycle_file": {
        "description": "Stuur een bestand in een gebruikersmap naar de prullenbak.",
        "params": {"filename": _bestandsnaam_param()},
    },
    "empty_recycle_bin": {
        "description": "Maak de prullenbak leeg.",
        "params": {},
    },
    "power": {
        "description": "Een stroomactie: afsluiten, herstarten, slapen, sluimerstand, vergrendelen, uitloggen of een lopende afsluiting annuleren.",
        "params": {
            "action": {
                "type": STRING,
                "required": True,
                "pattern": r"^(shutdown|restart|sleep|hibernate|lock|logoff|cancel)$",
            },
        },
    },
}


def allowed_tool_names():
    """Alle remote toegestane toolnamen."""

    return frozenset(ALLOWED_TOOLS)


def is_allowed(tool_name):
    """True als de actie remote mag worden uitgevoerd."""

    return isinstance(tool_name, str) and tool_name.strip() in ALLOWED_TOOLS


# =============================================================
# SERVERPROFIEL (Fase 15C)
# =============================================================
# Standaard staat de server op het basisprofiel: alleen programma's,
# games, vensters, media/volume, audio (uitlezen én per app bedienen),
# status en screenshot.
# Wie meer wil (bestanden wijzigen, UI-automatisering, power, browser)
# zet REMOTE_SERVER_PROFILE=werkstation.

PROFIEL_BASIS = "basis"
PROFIEL_WERKSTATION = "werkstation"

# De acties die in het basisprofiel zijn toegestaan.
BASIS_TOOLS = frozenset(
    {
        # Programma's en games
        "open_program",
        "close_program",
        "program_status",
        "find_program_location",
        # Vensteracties
        "minimize_window",
        "maximize_window",
        "restore_window",
        # Media en volume
        "media_play_pause",
        "media_next",
        "media_previous",
        "media_stop",
        "media_mute",
        "volume_up",
        "volume_down",
        "set_volume",
        # Audio uitlezen
        "audio_list_sessions",
        "audio_get_session_volume",
        "audio_list_outputs",
        "audio_get_default_output",
        # Audio per app bedienen ("zet discord op 20 procent"). Blijft
        # risico medium op het brein: het vraagt dus goedkeuring.
        "audio_set_session_volume",
        "audio_set_session_mute",
        "audio_toggle_session_mute",
        # Systeem en status
        "system_info",
        "pc_status",
        "screenshot",
    }
)


def profiel_voor_naam(naam):
    """Zet een profielnaam om in een bekende constante.

    Onbekende waarden vallen terug op basis (fail-closed).
    """

    if isinstance(naam, str) and naam.strip().lower() == PROFIEL_WERKSTATION:
        return PROFIEL_WERKSTATION
    return PROFIEL_BASIS


def is_allowed_in_profiel(tool_name, profiel):
    """True als de actie binnen het gegeven profiel is toegestaan."""

    if profiel_voor_naam(profiel) == PROFIEL_WERKSTATION:
        return True

    return isinstance(tool_name, str) and tool_name.strip() in BASIS_TOOLS


def _check_string(value, spec, name):
    if not isinstance(value, str):
        return f"Parameter '{name}' moet tekst zijn."

    if "min_length" in spec and len(value) < spec["min_length"]:
        return f"Parameter '{name}' is te kort."

    if "max_length" in spec and len(value) > spec["max_length"]:
        return f"Parameter '{name}' is te lang."

    if value.strip() == "":
        return f"Parameter '{name}' mag niet leeg zijn."

    choices = spec.get("choices")
    if choices and value not in choices:
        return f"Parameter '{name}' is geen toegestane waarde."

    pattern = spec.get("pattern")
    if pattern and not re.match(pattern, value):
        return f"Parameter '{name}' bevat ongeldige tekens."

    return _rejecteren(value, spec, name)


def _check_integer(value, spec, name):
    # bool is in Python een subklasse van int: True/False mag geen getal zijn.
    if isinstance(value, bool) or not isinstance(value, int):
        return f"Parameter '{name}' moet een geheel getal zijn."

    if "min_value" in spec and value < spec["min_value"]:
        return f"Parameter '{name}' moet minimaal {spec['min_value']} zijn."

    if "max_value" in spec and value > spec["max_value"]:
        return f"Parameter '{name}' mag maximaal {spec['max_value']} zijn."

    return None


def _check_boolean(value, spec, name):
    if not isinstance(value, bool):
        return f"Parameter '{name}' moet waar of onwaar zijn."

    return None


def _rejecteren(value, spec, name):
    """Weigert waarden die een verboden stuk bevatten (case-insensitief)."""

    for stuk in spec.get("reject", ()):
        if str(stuk).lower() in value.lower():
            return f"Parameter '{name}' mag '{stuk}' niet bevatten."

    return None


def _check_location(value, spec, name):
    """Alleen een gebruikersmap-label — nooit een pad.

    Wijst scheidingstekens, stationsletters, '..', '~' en UNC-paden af
    met een melding waar de AI direct op kan herstellen.
    """

    if not isinstance(value, str):
        return f"Parameter '{name}' moet tekst zijn."

    tekst = value.strip()

    if not tekst:
        if spec.get("allow_empty"):
            return None
        return f"Parameter '{name}' mag niet leeg zijn."

    laag = tekst.lower()

    if laag.startswith("\\\\") or laag.startswith("//"):
        return (
            f"Parameter '{name}' mag geen netwerkpad (UNC) zijn. "
            f"Gebruik een gebruikersmap: {LOCATION_HULP}."
        )

    if ".." in laag or laag.startswith("~"):
        return (
            f"Parameter '{name}' mag geen padverwijzing ('..') bevatten. "
            f"Gebruik een gebruikersmap: {LOCATION_HULP}."
        )

    if "\\" in laag or "/" in laag:
        return (
            f"Parameter '{name}' mag geen padscheidingstekens bevatten. "
            f"Gebruik een gebruikersmap: {LOCATION_HULP}."
        )

    if ":" in laag:
        return (
            f"Parameter '{name}' mag geen stationsletter of schijfpad bevatten. "
            f"Gebruik een gebruikersmap: {LOCATION_HULP}."
        )

    if laag not in LOCATION_LABELS:
        return (
            f"Parameter '{name}' is geen toegestane gebruikersmap. "
            f"Kies uit: {LOCATION_HULP}."
        )

    return None


def _check_text(value, spec, name):
    """Vrije tekst: begrensd, niet leeg en zonder stuurtekens."""

    if not isinstance(value, str):
        return f"Parameter '{name}' moet tekst zijn."

    if "min_length" in spec and len(value) < spec["min_length"]:
        return f"Parameter '{name}' is te kort."

    if "max_length" in spec and len(value) > spec["max_length"]:
        return f"Parameter '{name}' is te lang."

    if value.strip() == "" and not spec.get("allow_empty"):
        return f"Parameter '{name}' mag niet leeg zijn."

    for teken in value:
        code = ord(teken)
        if code == 127 or (code < 32 and teken not in ("\t", "\n")):
            return f"Parameter '{name}' bevat ongeldige tekens."

    return _rejecteren(value, spec, name)


def _check_scalar(value, spec, name):
    """Tekst óf getal (voor ui_set_value)."""

    if isinstance(value, bool):
        return f"Parameter '{name}' moet tekst of een getal zijn (geen waar/onwaar)."

    if isinstance(value, (int, float)):
        # abs(NaN) <= x en abs(inf) <= x zijn beide onwaar -> geweigerd.
        if not abs(value) <= MAX_SCALAR:
            return f"Parameter '{name}' ligt buiten het toegestane bereik."
        return None

    if isinstance(value, str):
        return _check_text(value, spec, name)

    return f"Parameter '{name}' moet tekst of een getal zijn."


def _check_path(value, spec, name):
    """Absoluut programma-pad: geen '..', geen UNC, geen '%'.

    Accepteert een absoluut pad met stationsletter ('C:\\...') of een
    losse programmanaam zonder padscheidingstekens.
    """

    if not isinstance(value, str):
        return f"Parameter '{name}' moet tekst zijn."

    pad = value.strip()

    if not pad:
        return f"Parameter '{name}' mag niet leeg zijn."

    if len(pad) > spec.get("max_length", 300):
        return f"Parameter '{name}' is te lang."

    laag = pad.lower()

    if laag.startswith("\\\\") or laag.startswith("//"):
        return f"Parameter '{name}' mag geen netwerkpad (UNC) bevatten."

    if ".." in laag:
        return f"Parameter '{name}' mag geen padverwijzing ('..') bevatten."

    if "%" in pad:
        return f"Parameter '{name}' mag geen omgevingsvariabele (%) bevatten."

    # Server-denylist: geweigerde programma's (ook met pad).
    if is_denied_program(pad):
        return f"Parameter '{name}' verwijst naar een programma dat niet is toegestaan op de game-pc."

    for teken in pad:
        code = ord(teken)
        if code < 32 or code == 127 or teken in '"<>|&^;':
            return f"Parameter '{name}' bevat ongeldige tekens."

    schijf = re.match(r"^[A-Za-z]:[\\/](.*)$", pad, re.DOTALL)

    if schijf:
        rest = schijf.group(1)
        if ":" in rest:
            return f"Parameter '{name}' bevat ongeldige tekens."
        if not rest.strip():
            return f"Parameter '{name}' verwijst naar een map, niet naar een programma."
        return None

    # Geen stationsletter: dan mag het alleen een losse programmanaam zijn.
    if "\\" in pad or "/" in pad or ":" in pad:
        return (
            f"Parameter '{name}' moet een absoluut pad zijn (begint met een "
            f"stationsletter, bijv. 'C:\\Program Files\\app.exe')."
        )

    if not re.match(BESTANDSNAAM_PATTERN, pad):
        return f"Parameter '{name}' bevat ongeldige tekens."

    return None


_CHECKERS = {
    STRING: _check_string,
    INTEGER: _check_integer,
    BOOLEAN: _check_boolean,
    LOCATION: _check_location,
    TEXT: _check_text,
    SCALAR: _check_scalar,
    PATH: _check_path,
}


def validate_call(tool_name, arguments=None):
    """Valideert een remote aanroep.

    Geeft ``(schone_argumenten, None)`` terug als de actie is toegestaan
    en alle parameters kloppen. Anders ``(None, reden)``.

    Er wordt hier niets uitgevoerd; de aanroeper mag alleen doorgaan
    als het eerste element niet ``None`` is.
    """

    if not isinstance(tool_name, str) or not tool_name.strip():
        return None, "Geen geldige actienaam opgegeven."

    tool_name = tool_name.strip()

    spec = ALLOWED_TOOLS.get(tool_name)

    if spec is None:
        return None, f"Actie '{tool_name}' is niet toegestaan."

    if arguments is None:
        arguments = {}

    if not isinstance(arguments, dict):
        return None, "Argumenten moeten een JSON-object zijn."

    params = spec.get("params", {})

    extra = [key for key in arguments if key not in params]
    if extra:
        return None, (
            "Onbekende parameter(s): " + ", ".join(sorted(map(str, extra))) + "."
        )

    cleaned = {}

    for name, pspec in params.items():

        if name not in arguments or arguments[name] is None:
            if pspec.get("required"):
                return None, f"Verplichte parameter ontbreekt: '{name}'."
            continue

        value = arguments[name]
        checker = _CHECKERS.get(pspec.get("type"))

        if checker is None:
            return None, f"Parameter '{name}' heeft een onbekend type."

        error = checker(value, pspec, name)
        if error:
            return None, error

        if pspec.get("type") in (LOCATION, PATH):
            cleaned[name] = value.strip()
        else:
            cleaned[name] = value

    # Server-denylist voor programma's die gestart mogen worden.
    if tool_name == "open_program":
        programma = cleaned.get("program")
        if isinstance(programma, str) and is_denied_program(programma):
            return None, f"Programma '{programma}' is niet toegestaan op de game-pc."

    return cleaned, None


def programma_van_handle(handle):
    """Probeert de procesnaam (basename, lowercase, zonder extensie) van een
    venster-handle op te halen. Geeft '' terug als dat niet lukt."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        pid = wintypes.DWORD()
        try:
            user32.GetWindowThreadProcessId(int(handle), ctypes.byref(pid))
        except Exception:
            return ""

        if not pid.value:
            return ""

        # PROCESS_QUERY_LIMITED_INFORMATION werkt ook voor processen van
        # andere gebruikers; val terug op de ruimere vlag.
        hproc = kernel32.OpenProcess(0x1000, False, pid.value)
        if not hproc:
            hproc = kernel32.OpenProcess(0x0410, False, pid.value)
        if not hproc:
            return ""

        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                return _programma_naam_uit_waarde(buf.value)
        finally:
            kernel32.CloseHandle(hproc)
    except Exception:
        return ""

    return ""


def is_denied_window(handle):
    """True als het venster bij een geweigerd programma hoort.

    Fail-closed: kan de procesnaam niet bepaald worden, dan wordt
    geweigerd (we laten alleen door wat we zeker weten).
    """
    naam = programma_van_handle(handle)

    if not naam:
        return True

    if naam in _extra_toegestane_programmas():
        return False

    if "uninstall" in naam:
        return True

    return naam in DENIED_PROGRAMS


def is_denied_for_typing(handle):
    """True als typen/klikken in dit venster niet mag.

    Fail-closed bij onbekende procesnaam én bij exception.
    Daarnaast geldt de extra denylist voor typen (o.a. explorer).
    """
    naam = programma_van_handle(handle)

    if not naam:
        return True

    if naam in _extra_toegestane_programmas():
        return False

    if "uninstall" in naam:
        return True

    if naam in DENIED_PROGRAMS:
        return True

    return naam in DENIED_TYPING_PROGRAMS
