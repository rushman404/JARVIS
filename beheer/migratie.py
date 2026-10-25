"""Het brein verhuizen naar een andere pc (Fase 19, M1).

``exporteer()`` pakt alle brein-bestanden (zie :mod:`beheer.data`) in één
zip met een ``manifest.json`` (pad, grootte, SHA-256 per bestand).
``importeer()`` zet zo'n pakket terug op de nieuwe pc.

Veiligheid bij het importeren
-----------------------------
* Alleen paden die volgens :mod:`beheer.data` bij het brein horen, nooit
  absolute paden of ``..`` (geen "zip slip").
* Elk bestand moet exact de SHA-256 uit het manifest hebben; anders wordt
  er **niets** geschreven.
* Bestanden die overschreven worden, gaan eerst in een veiligheidszip
  (``voor-import-<tijd>.zip``), zodat de import terug te draaien is.
* Niet terwijl JARVIS draait (die zou de bestanden meteen weer
  overschrijven).
"""

import hashlib
import io
import json
import os
import platform
import posixpath
import time
import zipfile
from dataclasses import dataclass, field

from beheer import data

FORMAAT = 1
SOORT = "jarvis-brein"
MANIFEST = "manifest.json"

# Grootste bestand dat we accepteren (auditlogs roteren bij 5 MB).
MAX_BESTAND = 50 * 1024 * 1024


class MigratieFout(Exception):
    """Het pakket is ongeldig of de import kan niet veilig doorgaan."""


@dataclass
class ImportPlan:
    """Wat een import zou doen (voor de controle vóór het schrijven)."""

    nieuw: list = field(default_factory=list)
    overschrijven: list = field(default_factory=list)
    gelijk: list = field(default_factory=list)
    bron_pc: str = ""
    gemaakt_op: str = ""


def _sha256(inhoud):
    return hashlib.sha256(inhoud).hexdigest()


def _tijdstempel(nu=None):
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(nu))


def standaard_exportmap():
    """Buiten de projectmap, zodat er nooit geheimen in git belanden."""

    return os.path.join(os.path.expanduser("~"), "JARVIS-export")


# ------------------------------------------------------------------
# Exporteren
# ------------------------------------------------------------------


def exporteer(doelmap=None, project=data.PROJECT, nu=None):
    """Maakt het migratiepakket en geeft ``(pad, aantal_bestanden)`` terug."""

    doelmap = doelmap or standaard_exportmap()
    os.makedirs(doelmap, exist_ok=True)
    naam = f"jarvis-brein-{platform.node() or 'pc'}-{_tijdstempel(nu)}.zip"
    pad = os.path.join(doelmap, naam)

    bestanden = data.verzamel(project)
    if not bestanden:
        raise MigratieFout("Er zijn geen brein-bestanden gevonden om te exporteren.")

    manifest = {
        "formaat": FORMAAT,
        "soort": SOORT,
        "gemaakt_op": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(nu)),
        "bron_pc": platform.node(),
        "bestanden": [],
    }

    with zipfile.ZipFile(pad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, geheim in bestanden:
            with open(os.path.join(project, rel), "rb") as f:
                inhoud = f.read()
            zf.writestr(rel, inhoud)
            manifest["bestanden"].append(
                {"pad": rel, "grootte": len(inhoud), "sha256": _sha256(inhoud), "geheim": geheim}
            )
        zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))

    return pad, len(bestanden)


# ------------------------------------------------------------------
# Importeren
# ------------------------------------------------------------------


def _veilig_pad(rel):
    """True als ``rel`` een relatief, schoon pad is dat bij het brein hoort."""

    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        return False
    if rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
        return False
    if posixpath.normpath(rel) != rel or any(deel in ("", ".", "..") for deel in rel.split("/")):
        return False
    return data.classificeer(rel) is not None


def lees_pakket(pakket):
    """Leest en controleert het pakket; geeft ``(manifest, {pad: inhoud})``.

    Gooit :class:`MigratieFout` bij het minste of geringste: dan wordt er
    niets geschreven.
    """

    try:
        zf = zipfile.ZipFile(pakket)
    except (OSError, zipfile.BadZipFile) as fout:
        raise MigratieFout(f"Geen geldig pakket: {fout}") from None

    with zf:
        try:
            manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError):
            raise MigratieFout("Het pakket heeft geen geldig manifest.json.") from None

        if manifest.get("soort") != SOORT or manifest.get("formaat") != FORMAAT:
            raise MigratieFout("Dit is geen JARVIS-breinpakket (of een onbekende versie).")

        lijst = manifest.get("bestanden")
        if not isinstance(lijst, list) or not lijst:
            raise MigratieFout("Het manifest noemt geen bestanden.")

        namen_in_zip = set(zf.namelist()) - {MANIFEST}
        verwacht = set()
        inhoud = {}
        for item in lijst:
            rel = item.get("pad") if isinstance(item, dict) else None
            if not _veilig_pad(rel):
                raise MigratieFout(f"Ongeldig of niet-toegestaan pad in het pakket: {rel!r}")
            if rel in verwacht:
                raise MigratieFout(f"Dubbel pad in het pakket: {rel}")
            verwacht.add(rel)
            info = zf.getinfo(rel) if rel in namen_in_zip else None
            if info is None:
                raise MigratieFout(f"Bestand ontbreekt in het pakket: {rel}")
            if info.file_size > MAX_BESTAND:
                raise MigratieFout(f"Bestand is te groot: {rel}")
            blob = zf.read(rel)
            if _sha256(blob) != item.get("sha256"):
                raise MigratieFout(f"Controlegetal klopt niet (beschadigd?): {rel}")
            inhoud[rel] = blob

        extra = namen_in_zip - verwacht
        if extra:
            raise MigratieFout("Het pakket bevat onbekende bestanden: " + ", ".join(sorted(extra)))

    return manifest, inhoud


def maak_plan(manifest, inhoud, project=data.PROJECT):
    plan = ImportPlan(bron_pc=str(manifest.get("bron_pc", "")), gemaakt_op=str(manifest.get("gemaakt_op", "")))
    for rel, blob in sorted(inhoud.items()):
        doel = os.path.join(project, *rel.split("/"))
        if not os.path.exists(doel):
            plan.nieuw.append(rel)
            continue
        with open(doel, "rb") as f:
            if _sha256(f.read()) == _sha256(blob):
                plan.gelijk.append(rel)
            else:
                plan.overschrijven.append(rel)
    return plan


def jarvis_draait(project=data.PROJECT, processen=None):
    """True als ``main.py`` van dit project nu draait (via psutil)."""

    if processen is None:
        try:
            import psutil
        except ImportError:
            return False
        processen = psutil.process_iter(["pid", "cmdline"])

    eigen_pid = os.getpid()
    doel = os.path.normcase(os.path.join(project, "main.py"))
    for proc in processen:
        try:
            info = proc.info if hasattr(proc, "info") else proc
            if info.get("pid") == eigen_pid:
                continue
            for arg in info.get("cmdline") or ():
                arg = os.path.normcase(str(arg))
                if arg == doel or (arg.endswith("main.py") and os.path.normcase(os.path.abspath(arg)) == doel):
                    return True
        except Exception:
            continue
    return False


def _veiligheidszip(plan, project, backupmap, nu=None):
    if not plan.overschrijven:
        return None
    os.makedirs(backupmap, exist_ok=True)
    pad = os.path.join(backupmap, f"voor-import-{_tijdstempel(nu)}.zip")
    with zipfile.ZipFile(pad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in plan.overschrijven:
            zf.write(os.path.join(project, *rel.split("/")), rel)
    return pad


def _schrijf_atomair(doel, blob):
    os.makedirs(os.path.dirname(doel), exist_ok=True)
    tijdelijk = doel + ".import-tmp"
    with open(tijdelijk, "wb") as f:
        f.write(blob)
    os.replace(tijdelijk, doel)


def importeer(pakket, project=data.PROJECT, backupmap=None, controleer_draaien=True, nu=None):
    """Zet het pakket terug. Geeft ``(plan, pad_veiligheidszip_of_None)``."""

    if controleer_draaien and jarvis_draait(project):
        raise MigratieFout("JARVIS draait nog. Stop JARVIS eerst en probeer het opnieuw.")

    manifest, inhoud = lees_pakket(pakket)
    plan = maak_plan(manifest, inhoud, project)
    backupmap = backupmap or standaard_exportmap()
    veiligheid = _veiligheidszip(plan, project, backupmap, nu=nu)

    for rel in plan.nieuw + plan.overschrijven:
        _schrijf_atomair(os.path.join(project, *rel.split("/")), inhoud[rel])

    return plan, veiligheid


def env_nakijken(env_inhoud):
    """Sleutels uit ``.env`` die op een nieuwe pc kunnen verschillen.

    Geeft een lijst met ``(sleutel, reden)``. Waarden worden nooit
    teruggegeven (er kunnen tokens tussen zitten).
    """

    try:
        from dotenv import dotenv_values

        waarden = dotenv_values(stream=io.StringIO(env_inhoud.decode("utf-8", errors="replace")))
    except Exception:
        return []

    nakijken = []
    for sleutel in data.PC_GEBONDEN_SLEUTELS:
        if waarden.get(sleutel):
            nakijken.append((sleutel, "per pc verschillend"))
    for sleutel, waarde in waarden.items():
        if sleutel in data.PC_GEBONDEN_SLEUTELS or not waarde:
            continue
        if len(waarde) > 2 and waarde[1] == ":" and waarde[2] in "\\/":
            nakijken.append((sleutel, "absoluut pad"))
    if str(waarden.get("REMOTE_SERVER_ENABLED", "")).strip().lower() in ("1", "true", "ja", "yes", "on"):
        nakijken.append(("REMOTE_SERVER_ENABLED", "de agent hoort op de game-pc, niet op het brein"))
    return nakijken
