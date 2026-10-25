"""Dagelijkse backups van het brein (Fase 19, M3).

Een backup is hetzelfde soort pakket als bij de verhuizing
(:mod:`beheer.migratie`): een zip met ``manifest.json`` en een SHA-256 per
bestand. Terugzetten gaat dus via dezelfde veilige import
(``scripts/brein_restore.py``).

* **Wanneer:** elke dag om ``BACKUP_TIJD`` (standaard 04:00). Stond de pc
  toen uit, dan haalt JARVIS hem kort na het starten in. Mislukt hij,
  dan probeert hij het elk uur opnieuw en meldt hij het één keer per dag.
* **Waar:** ``BACKUP_MAP``, nooit binnen de projectmap (dan zou hij met
  alle geheimen in git kunnen belanden).
* **Hoe lang:** de laatste backup per dag voor ``BACKUP_DAGEN`` dagen en
  de laatste per week voor ``BACKUP_WEKEN`` weken. De nieuwste blijft
  altijd. Alleen bestanden met onze eigen naam worden ooit verwijderd.
* **Gecontroleerd:** elke nieuwe backup wordt meteen teruggelezen en tegen
  het manifest gecontroleerd.
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta

from beheer import data, hartslag, migratie

logger = logging.getLogger("jarvis.backup")

PREFIX = "jarvis-backup-"
NAAM_PATROON = re.compile(r"^jarvis-backup-(\d{8})-(\d{6})\.zip$")
STATUS_FILE = os.path.join(data.PROJECT, "logs", "backup.json")

# Na het starten eerst even wachten, zodat de backup het opstarten niet
# vertraagt (AI-model en stem laden).
OPSTART_VERTRAGING = 300
OPNIEUW_NA_FOUT = 3600
CONTROLE_INTERVAL = 60
# Ouder dan dit (uren) en de dokter/het dashboard waarschuwt.
VEROUDERD_UREN = 36


class BackupFout(Exception):
    """De backup kon niet (veilig) gemaakt worden."""


# ------------------------------------------------------------------
# Instellingen
# ------------------------------------------------------------------


def _config():
    import config

    return config


def backup_map():
    return _config().BACKUP_MAP


def controleer_map(map_, project=data.PROJECT):
    """Geeft het absolute pad terug, of gooit :class:`BackupFout`."""

    if not map_ or not str(map_).strip():
        raise BackupFout("BACKUP_MAP is leeg.")
    pad = os.path.abspath(os.path.expanduser(str(map_).strip()))
    proj = os.path.abspath(project)
    try:
        binnen = os.path.commonpath([os.path.normcase(pad), os.path.normcase(proj)]) == os.path.normcase(proj)
    except ValueError:
        binnen = False  # andere schijf
    if binnen:
        raise BackupFout(
            "BACKUP_MAP ligt binnen de projectmap; dan kunnen de geheimen in git belanden. "
            "Kies een map erbuiten, bij voorkeur op een andere schijf."
        )
    return pad


def parse_tijd(tekst):
    """``"04:00"`` -> ``(4, 0)``; ongeldig -> 04:00."""

    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(tekst or ""))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)), int(m.group(2))
    return 4, 0


# ------------------------------------------------------------------
# Maken, opsommen en opruimen
# ------------------------------------------------------------------


def maak_backup(map_=None, project=data.PROJECT, nu=None):
    """Maakt één backup en controleert hem. Geeft een info-dict terug."""

    map_ = controleer_map(map_ or backup_map(), project)
    os.makedirs(map_, exist_ok=True)
    nu = time.time() if nu is None else nu
    naam = f"{PREFIX}{time.strftime('%Y%m%d-%H%M%S', time.localtime(nu))}.zip"
    pad = os.path.join(map_, naam)
    try:
        aantal = migratie.schrijf_pakket(pad, project, nu=nu)
        migratie.lees_pakket(pad)
    except migratie.MigratieFout as fout:
        raise BackupFout(str(fout)) from None
    return {"naam": naam, "pad": pad, "aantal": aantal, "grootte": os.path.getsize(pad), "tijd": nu}


def lijst(map_=None):
    """Alle backups in de map: ``[(naam, datetime, pad)]``, nieuwste eerst."""

    map_ = map_ or backup_map()
    try:
        namen = os.listdir(map_)
    except OSError:
        return []
    uit = []
    for naam in namen:
        m = NAAM_PATROON.match(naam)
        if not m:
            continue
        try:
            moment = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            continue
        uit.append((naam, moment, os.path.join(map_, naam)))
    return sorted(uit, key=lambda x: x[1], reverse=True)


def te_bewaren(backups, nu, dagen, weken):
    """Welke namen blijven staan (zie de moduledocumentatie)."""

    vandaag = nu.date()
    bewaar = set()
    if backups:
        bewaar.add(backups[0][0])  # de nieuwste altijd

    gezien_dag = set()
    gezien_week = set()
    for naam, moment, _pad in backups:  # nieuwste eerst
        dag = moment.date()
        if dagen > 0 and (vandaag - dag).days < dagen and dag not in gezien_dag:
            gezien_dag.add(dag)
            bewaar.add(naam)
        week = moment.isocalendar()[:2]
        if weken > 0 and (vandaag - dag).days < weken * 7 and week not in gezien_week:
            gezien_week.add(week)
            bewaar.add(naam)
    return bewaar


def roteer(map_=None, nu=None, dagen=None, weken=None):
    """Verwijdert oude backups; geeft de verwijderde namen terug."""

    cfg = _config()
    map_ = map_ or backup_map()
    nu = nu or datetime.now()
    dagen = cfg.BACKUP_DAGEN if dagen is None else dagen
    weken = cfg.BACKUP_WEKEN if weken is None else weken

    backups = lijst(map_)
    bewaar = te_bewaren(backups, nu, dagen, weken)
    weg = []
    for naam, _moment, pad in backups:
        if naam in bewaar:
            continue
        try:
            os.remove(pad)
            weg.append(naam)
        except OSError:
            logger.warning("Kon oude backup %s niet verwijderen.", naam)

    # Halve backups van een eerdere stroomstoring opruimen.
    try:
        for naam in os.listdir(map_):
            if naam.startswith(PREFIX) and naam.endswith(".zip.tmp"):
                pad = os.path.join(map_, naam)
                if time.time() - os.path.getmtime(pad) > 3600:
                    os.remove(pad)
    except OSError:
        pass
    return weg


# ------------------------------------------------------------------
# Status (voor het dashboard en de dokter)
# ------------------------------------------------------------------


def lees_status(pad=STATUS_FILE):
    return hartslag.lees_json(pad) or {}


def _schrijf_status(status, pad=STATUS_FILE):
    try:
        hartslag.schrijf_atomair(pad, status)
    except OSError:
        logger.debug("Kon de backupstatus niet schrijven.", exc_info=True)


def voer_uit(nu=None, project=data.PROJECT, status_pad=STATUS_FILE, map_=None):
    """Maakt een backup, ruimt op en werkt de status bij. Gooit nooit.

    Geeft ``(ok, info_of_foutmelding)`` terug.
    """

    nu = time.time() if nu is None else nu
    status = lees_status(status_pad)
    status["laatste_poging"] = nu
    try:
        info = maak_backup(map_, project, nu=nu)
        verwijderd = roteer(os.path.dirname(info["pad"]), nu=datetime.fromtimestamp(nu))
    except (BackupFout, OSError) as fout:
        melding = str(fout) or type(fout).__name__
        logger.error("Backup mislukt: %s", melding)
        status["ok"] = False
        status["fout"] = melding[:200]
        _schrijf_status(status, status_pad)
        return False, melding

    logger.info("Backup gemaakt: %s (%d bestanden, %d oude opgeruimd).",
                info["naam"], info["aantal"], len(verwijderd))
    status.update({
        "ok": True,
        "fout": None,
        "laatste_geslaagd": nu,
        "naam": info["naam"],
        "aantal_bestanden": info["aantal"],
        "grootte": info["grootte"],
    })
    _schrijf_status(status, status_pad)
    return True, info


def samenvatting(nu=None, status_pad=STATUS_FILE):
    """Kort overzicht voor het Systeem-paneel; zonder paden of geheimen."""

    nu = time.time() if nu is None else nu
    cfg = _config()
    status = lees_status(status_pad)
    laatste = status.get("laatste_geslaagd")
    uit = {
        "ingeschakeld": bool(cfg.BACKUP_ENABLED),
        "laatste": None,
        "ok": status.get("ok"),
        "fout": status.get("fout"),
        "verouderd": True,
    }
    if isinstance(laatste, (int, float)):
        uit["laatste"] = time.strftime("%d-%m %H:%M", time.localtime(laatste))
        uit["verouderd"] = nu - laatste > VEROUDERD_UREN * 3600
    return uit


# ------------------------------------------------------------------
# De planner (draait in JARVIS)
# ------------------------------------------------------------------


def is_nodig(nu, status, tijd, gestart_op):
    """True als er nu een backup gemaakt moet worden."""

    uur, minuut = parse_tijd(tijd)
    moment = datetime.fromtimestamp(nu)
    gepland = moment.replace(hour=uur, minute=minuut, second=0, microsecond=0)
    if moment < gepland:
        gepland -= timedelta(days=1)
    gepland_ts = gepland.timestamp()

    laatste = status.get("laatste_geslaagd")
    if isinstance(laatste, (int, float)) and laatste >= gepland_ts:
        return False  # deze ronde al gedaan

    if nu - gestart_op < OPSTART_VERTRAGING:
        return False

    poging = status.get("laatste_poging")
    if isinstance(poging, (int, float)) and poging >= gepland_ts and nu - poging < OPNIEUW_NA_FOUT:
        return False  # net mislukt: over een uur opnieuw
    return True


class BackupPlanner:
    """Achtergrondthread: maakt de dagelijkse backup op het geplande uur."""

    def __init__(self, meld_fn=None, klok=time.time, status_pad=STATUS_FILE, uitvoer_fn=None, tijd=None):
        self.meld_fn = meld_fn
        self.klok = klok
        self.status_pad = status_pad
        self.uitvoer_fn = uitvoer_fn or (lambda nu: voer_uit(nu=nu, status_pad=status_pad))
        self.tijd = tijd
        self.gestart_op = klok()
        self._gemeld_op = None
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def controleer(self):
        """Eén controle; geeft True als er een backup is geprobeerd."""

        with self._lock:
            nu = self.klok()
            tijd = self.tijd or _config().BACKUP_TIJD
            if not is_nodig(nu, lees_status(self.status_pad), tijd, self.gestart_op):
                return False
            ok, info = self.uitvoer_fn(nu)
            if not ok:
                self._meld_fout(info, nu)
            return True

    def _meld_fout(self, fout, nu):
        dag = time.strftime("%Y-%m-%d", time.localtime(nu))
        if self.meld_fn is None or self._gemeld_op == dag:
            return
        self._gemeld_op = dag
        try:
            self.meld_fn(f"Sir, de backup is mislukt: {fout}", bron="backup")
        except Exception:
            logger.debug("Kon de backupmelding niet versturen.", exc_info=True)

    def _lus(self):
        while not self._stop.wait(CONTROLE_INTERVAL):
            try:
                self.controleer()
            except Exception:
                logger.exception("Onverwachte fout in de backupplanner.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-backup", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
