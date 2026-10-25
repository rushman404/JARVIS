"""De 'dokter' van het brein (Fase 19, M1).

Eén overzicht van alles wat het brein nodig heeft om te werken: Python,
de pakketten, ``.env``, Ollama en het model, het wake word, de Piper-stem,
microfoon en speaker, de game-pc-agent, Home Assistant, het dashboard-
certificaat en de vrije schijfruimte.

Ontwerpregels
-------------
* **Alleen lezen.** Een controle verandert nooit iets; hij zegt hoogstens
  welk commando u kunt draaien.
* **Eén fout stopt de rest niet.** Elke controle wordt los uitgevoerd; een
  exception wordt zelf een ``FOUT`` met de reden.
* **Geen geheimen in de uitvoer.** Tokens en sleutels worden nooit getoond,
  alleen of ze er zijn.
"""

import importlib
import os
import shutil
import sys
from dataclasses import dataclass

OK = "ok"
LET_OP = "let_op"
FOUT = "fout"
OVERGESLAGEN = "overgeslagen"

SYMBOOL = {OK: "✅", LET_OP: "⚠️ ", FOUT: "❌", OVERGESLAGEN: "➖"}

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIN_PYTHON = (3, 11)

# Onder deze vrije ruimte (in GB) waarschuwt de dokter.
MIN_VRIJ_GB = 5

# Pakketten die het brein echt nodig heeft (importnaam, pip-naam).
PAKKETTEN = (
    ("ollama", "ollama"),
    ("dotenv", "python-dotenv"),
    ("requests", "requests"),
    ("sounddevice", "sounddevice"),
    ("numpy", "numpy"),
    ("openwakeword", "openwakeword"),
    ("onnxruntime", "onnxruntime"),
    ("webrtcvad", "webrtcvad-wheels"),
    ("piper", "piper-tts"),
    ("psutil", "psutil"),
    ("rapidfuzz", "rapidfuzz"),
)


@dataclass
class Controle:
    """Uitkomst van één controle."""

    naam: str
    status: str
    uitleg: str = ""
    advies: str = ""


# ------------------------------------------------------------------
# De controles
# ------------------------------------------------------------------


def controleer_python():
    versie = sys.version_info[:3]
    tekst = ".".join(map(str, versie))
    if versie[:2] >= MIN_PYTHON:
        return Controle("Python", OK, tekst)
    return Controle(
        "Python", FOUT, f"{tekst} is te oud",
        f"Installeer Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} of nieuwer.",
    )


def controleer_pakketten(importeer=importlib.import_module):
    ontbrekend = []
    for module, pip_naam in PAKKETTEN:
        try:
            importeer(module)
        except Exception:
            ontbrekend.append(pip_naam)
    if not ontbrekend:
        return Controle("Pakketten", OK, f"{len(PAKKETTEN)} aanwezig")
    return Controle(
        "Pakketten", FOUT, "ontbreekt: " + ", ".join(ontbrekend),
        "pip install -r requirements.txt",
    )


def controleer_env(pad=None):
    pad = pad or os.path.join(PROJECT, ".env")
    if os.path.isfile(pad):
        return Controle(".env", OK, "aanwezig")
    return Controle(
        ".env", FOUT, "niet gevonden",
        "Kopieer .env.example naar .env of zet het migratiepakket terug "
        "(scripts/brein_import.py).",
    )


def controleer_ollama(lijst_fn=None, model=None):
    import config

    model = model or config.AI_MODEL
    try:
        if lijst_fn is None:
            import ollama

            lijst_fn = ollama.list
        antwoord = lijst_fn()
    except Exception as fout:
        return Controle(
            "Ollama", FOUT, f"niet bereikbaar ({type(fout).__name__})",
            "Start Ollama (ollama serve) of installeer het van ollama.com.",
        )

    from core.llm import _model_names

    if model in _model_names(antwoord):
        return Controle("Ollama", OK, f"model {model} aanwezig")
    return Controle(
        "Ollama", FOUT, f"model {model} ontbreekt", f"ollama pull {model}",
    )


def controleer_wake_word(laad_fn=None):
    try:
        if laad_fn is None:
            from openwakeword.model import Model

            def laad_fn():
                return Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

        laad_fn()
    except Exception as fout:
        return Controle(
            "Wake word", FOUT, f"model 'hey_jarvis' niet te laden ({type(fout).__name__})",
            'python -c "from openwakeword.utils import download_models; download_models()"',
        )
    return Controle("Wake word", OK, "hey_jarvis")


def controleer_piper():
    import config
    from voice import piper_tts

    if not config.PIPER_ENABLED:
        return Controle("Piper-stem", LET_OP, "staat uit (PIPER_ENABLED=0); pyttsx3 wordt gebruikt")
    pad = piper_tts._resolve_model_path()
    if pad is None:
        return Controle(
            "Piper-stem", FOUT, "geen stemmodel gevonden",
            "python scripts/download_piper_voice.py",
        )
    return Controle("Piper-stem", OK, pad.name)


def _apparaten(sd=None):
    if sd is None:
        import sounddevice as sd
    return sd, list(sd.query_devices())


def controleer_microfoon(sd=None):
    import config

    sd, apparaten = _apparaten(sd)
    ingangen = [(i, a) for i, a in enumerate(apparaten) if a.get("max_input_channels", 0) > 0]
    if not ingangen:
        return Controle(
            "Microfoon", FOUT, "geen opname-apparaat gevonden",
            "Sluit een microfoon aan en geef Windows toegang (Privacy → Microfoon).",
        )

    gekozen = config.MIC_DEVICE
    if gekozen is None:
        try:
            standaard = sd.default.device[0]
        except Exception:
            standaard = None
        if standaard is None or standaard < 0:
            return Controle(
                "Microfoon", LET_OP, "geen standaard-microfoon ingesteld",
                "Kies er een in Windows of zet MIC_DEVICE in .env.",
            )
        return Controle("Microfoon", OK, f"standaard: {apparaten[standaard].get('name', standaard)}")

    if isinstance(gekozen, int):
        if 0 <= gekozen < len(apparaten) and apparaten[gekozen].get("max_input_channels", 0) > 0:
            return Controle("Microfoon", OK, f"MIC_DEVICE={gekozen}: {apparaten[gekozen].get('name')}")
        return Controle(
            "Microfoon", FOUT, f"MIC_DEVICE={gekozen} is geen opname-apparaat",
            "Bekijk de lijst met: python -m sounddevice",
        )

    namen = [a.get("name", "") for _, a in ingangen]
    if any(str(gekozen).lower() in n.lower() for n in namen):
        return Controle("Microfoon", OK, f"MIC_DEVICE={gekozen}")
    return Controle(
        "Microfoon", FOUT, f"MIC_DEVICE='{gekozen}' niet gevonden",
        "Bekijk de lijst met: python -m sounddevice",
    )


def controleer_speaker(sd=None):
    sd, apparaten = _apparaten(sd)
    try:
        standaard = sd.default.device[1]
    except Exception:
        standaard = None
    if standaard is None or standaard < 0 or standaard >= len(apparaten):
        if any(a.get("max_output_channels", 0) > 0 for a in apparaten):
            return Controle(
                "Speaker", LET_OP, "geen standaard-uitvoer ingesteld",
                "Kies een standaard-uitvoerapparaat in Windows.",
            )
        return Controle("Speaker", FOUT, "geen uitvoerapparaat gevonden", "Sluit een speaker aan.")
    return Controle("Speaker", OK, str(apparaten[standaard].get("name", standaard)))


def controleer_game_pc(client_fn=None):
    import config
    from core import pc_target

    if pc_target.get_pc_target() != pc_target.GAME_PC and not config.REMOTE_CLIENT_ENABLED:
        return Controle("Game-pc-agent", OVERGESLAGEN, "PC_TARGET=local")

    fout = pc_target.remote_client_configuratie_fout()
    if fout:
        return Controle("Game-pc-agent", FOUT, fout, "Zie docs/windows_brein_setup.md §B6–B7.")

    if client_fn is None:
        from remote.client import RemoteClient

        client_fn = RemoteClient
    if client_fn().is_online():
        return Controle("Game-pc-agent", OK, f"online ({config.REMOTE_CLIENT_HOST}:{config.REMOTE_CLIENT_PORT})")
    return Controle(
        "Game-pc-agent", FOUT, f"niet bereikbaar ({config.REMOTE_CLIENT_HOST}:{config.REMOTE_CLIENT_PORT})",
        "Staat de game-pc aan en draait de taak 'JARVIS Game-PC Agent'? "
        "Klopt REMOTE_CLIENT_HOST en het token?",
    )


def controleer_home_assistant(get_fn=None):
    from core import home_assistant

    if not home_assistant._config_ok():
        return Controle("Home Assistant", OVERGESLAGEN, "niet ingesteld")
    get_fn = get_fn or home_assistant._ha_get
    ok, _ = get_fn("/api/")
    if ok:
        return Controle("Home Assistant", OK, "bereikbaar")
    return Controle(
        "Home Assistant", FOUT, "niet bereikbaar",
        "Klopt HOME_ASSISTANT_URL en is het token nog geldig?",
    )


def controleer_dashboard(lan_ip=None):
    import config

    if not config.DASHBOARD_ENABLED:
        return Controle("Dashboard", OVERGESLAGEN, "DASHBOARD_ENABLED=0")

    fouten = config.dashboard_security_errors()
    if fouten:
        return Controle("Dashboard", FOUT, "; ".join(fouten), "Zie docs/dashboard.md §1.")

    from dashboard.server import controleer_certificaat, detecteer_lan_ip

    lan_ip = lan_ip or config.DASHBOARD_LAN_IP or detecteer_lan_ip()
    cert = config.DASHBOARD_CERT_FILE
    if not os.path.isabs(cert):
        cert = os.path.join(PROJECT, cert)
    waarschuwingen = controleer_certificaat(cert, lan_ip)
    if waarschuwingen:
        return Controle(
            "Dashboard", FOUT, " ".join(waarschuwingen),
            "python scripts/make_dashboard_cert.py --force  (de CA blijft, de iPad hoeft niets te doen)",
        )
    return Controle("Dashboard", OK, f"certificaat geldig voor {lan_ip}")


def controleer_backup(nu=None, status_pad=None, gebruik_fn=shutil.disk_usage):
    import config
    from beheer import backup

    if not config.BACKUP_ENABLED:
        return Controle("Backup", LET_OP, "staat uit (BACKUP_ENABLED=0)")
    try:
        map_ = backup.controleer_map(config.BACKUP_MAP)
    except backup.BackupFout as fout:
        return Controle("Backup", FOUT, str(fout), "Zet BACKUP_MAP in .env op een map buiten het project.")

    samen = backup.samenvatting(nu=nu, status_pad=status_pad or backup.STATUS_FILE)
    if samen["ok"] is False:
        return Controle("Backup", FOUT, f"laatste poging mislukt: {samen['fout']}", "python scripts/brein_backup.py")
    if not samen["laatste"]:
        return Controle("Backup", LET_OP, f"nog geen backup in {map_}",
                        "Komt vannacht vanzelf, of nu: python scripts/brein_backup.py")
    if samen["verouderd"]:
        return Controle("Backup", LET_OP, f"laatste is van {samen['laatste']} (te oud)", "python scripts/brein_backup.py")

    tekst = f"laatste {samen['laatste']}"
    try:
        schijf_project = os.path.splitdrive(os.path.abspath(PROJECT))[0].lower()
        schijf_backup = os.path.splitdrive(map_)[0].lower()
        if schijf_project and schijf_project == schijf_backup:
            return Controle("Backup", LET_OP, tekst + "; staat op dezelfde schijf als JARVIS",
                            "Zet BACKUP_MAP liever op een andere schijf (bijv. D:).")
    except (TypeError, ValueError):
        pass
    return Controle("Backup", OK, tekst)


def controleer_schijf(pad=PROJECT, gebruik_fn=shutil.disk_usage):
    vrij_gb = gebruik_fn(pad).free / 1024 ** 3
    if vrij_gb >= MIN_VRIJ_GB:
        return Controle("Schijfruimte", OK, f"{vrij_gb:.0f} GB vrij")
    return Controle(
        "Schijfruimte", LET_OP, f"nog maar {vrij_gb:.1f} GB vrij",
        "Ruim oude backups of logbestanden op.",
    )


STANDAARD_CONTROLES = (
    controleer_python,
    controleer_pakketten,
    controleer_env,
    controleer_ollama,
    controleer_wake_word,
    controleer_piper,
    controleer_microfoon,
    controleer_speaker,
    controleer_game_pc,
    controleer_home_assistant,
    controleer_dashboard,
    controleer_backup,
    controleer_schijf,
)


# ------------------------------------------------------------------
# Uitvoeren en tonen
# ------------------------------------------------------------------


def _naam_van(functie):
    naam = getattr(functie, "__name__", "controle")
    return naam.removeprefix("controleer_").replace("_", " ").capitalize()


def voer_uit(controles=STANDAARD_CONTROLES):
    """Voert alle controles uit; een exception wordt een ``FOUT``."""

    uitkomsten = []
    for functie in controles:
        try:
            uitkomst = functie()
        except Exception as fout:
            uitkomst = Controle(_naam_van(functie), FOUT, f"controle mislukt: {type(fout).__name__}: {fout}")
        uitkomsten.append(uitkomst)
    return uitkomsten


def is_gezond(uitkomsten):
    """True als geen enkele controle ``FOUT`` gaf."""

    return all(u.status != FOUT for u in uitkomsten)


def als_tekst(uitkomsten):
    """Het overzicht als tekst, één regel per controle (+ advies)."""

    breedte = max((len(u.naam) for u in uitkomsten), default=0)
    regels = []
    for u in uitkomsten:
        regels.append(f"{SYMBOOL.get(u.status, '?')} {u.naam.ljust(breedte)}  {u.uitleg}".rstrip())
        if u.advies and u.status in (FOUT, LET_OP):
            regels.append(f"   {' ' * breedte}  → {u.advies}")
    fouten = sum(u.status == FOUT for u in uitkomsten)
    let_op = sum(u.status == LET_OP for u in uitkomsten)
    regels.append("")
    if fouten:
        regels.append(f"{fouten} fout(en), {let_op} aandachtspunt(en). Los de ❌ eerst op.")
    elif let_op:
        regels.append(f"Alles werkt; {let_op} aandachtspunt(en).")
    else:
        regels.append("Alles in orde: het brein is klaar.")
    return "\n".join(regels)
