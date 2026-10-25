"""De waakhond van het brein (Fase 19, M2).

Start ``main.py``, houdt hem in de gaten en start hem opnieuw als hij
crasht of vastloopt. De geplande taak "JARVIS Brein" start niet JARVIS
zelf maar deze waakhond::

    python -m beheer.waakhond

Regels
------
* **Exitcode 0** (u stopte JARVIS) of **4** (geen wake-word-model):
  niet herstarten, want dat helpt niet.
* **Elke andere exitcode** of een **vastloper** (zie
  :mod:`beheer.hartslag`): herstarten na een oplopende wachttijd
  (``WACHTTIJDEN``). Draaide JARVIS langer dan ``STABIEL_NA`` seconden,
  dan begint de wachttijd weer bij de eerste stap.
* **Te vaak achter elkaar** (``MAX_HERSTARTS`` binnen ``HERSTART_VENSTER``):
  de waakhond stopt, toont een Windows-melding en schrijft de reden in
  ``logs/waakhond.json``. Dan is er iets structureel mis.
* **Eén waakhond tegelijk** (een slot op ``logs/waakhond.lock``).
* **JARVIS stopt mee** met de waakhond (Windows-jobobject), zodat
  ``Stop-ScheduledTask`` geen losse JARVIS achterlaat.

``logs/waakhond.json`` is de status voor het dashboard: sinds wanneer
JARVIS draait, hoe vaak hij herstart is en waarom.
"""

import logging
import os
import secrets
import subprocess
import sys
import time

from beheer import hartslag

logger = logging.getLogger("jarvis.waakhond")

PROJECT = hartslag.PROJECT
STATUS_FILE = os.path.join(PROJECT, "logs", "waakhond.json")
LOCK_FILE = os.path.join(PROJECT, "logs", "waakhond.lock")

EXIT_GESTOPT = 0
EXIT_GEEN_WAKE_WORD = 4
# Na een geïnstalleerde update (beheer/updates.py): meteen herstarten,
# zonder wachttijd en zonder dat het als crash telt.
EXIT_HERSTART = 5
NIET_HERSTARTEN = frozenset({EXIT_GESTOPT, EXIT_GEEN_WAKE_WORD})

WACHTTIJDEN = (5, 15, 30, 60, 120, 300)
STABIEL_NA = 600
MAX_HERSTARTS = 5
HERSTART_VENSTER = 900
CONTROLE_INTERVAL = 5

TOESTAND_DRAAIT = "draait"
TOESTAND_HERSTART = "herstart"
TOESTAND_GESTOPT = "gestopt"


def _reden_exitcode(code):
    if code == 3:
        return "te veel fouten achter elkaar"
    if code < 0 or code > 255:
        # Een negatieve code (signaal) of een Windows-NTSTATUS zoals
        # 0xC0000005: het proces is hard afgebroken.
        return f"afgebroken (code {code})"
    return f"gecrasht (code {code})"


class Waakhond:
    """Bewaakt één JARVIS-proces. Alles is injecteerbaar voor de tests."""

    def __init__(
        self,
        commando=None,
        werkmap=PROJECT,
        status_pad=STATUS_FILE,
        hartslag_pad=hartslag.HARTSLAG_FILE,
        popen=subprocess.Popen,
        klok=time.time,
        slaap=time.sleep,
        melder=None,
    ):
        self.commando = commando or [sys.executable, os.path.join(PROJECT, "main.py")]
        self.werkmap = werkmap
        self.status_pad = status_pad
        self.hartslag_pad = hartslag_pad
        self.popen = popen
        self.klok = klok
        self.slaap = slaap
        self.melder = melder
        self.proces = None
        self.proces_gestart_op = None
        self.herstarts = []          # tijdstippen van herstarts (venster)
        self.totaal_herstarts = 0
        self.laatste_herstart = None  # {"tijd", "reden"}
        self.gestart_op = klok()
        self._stap = 0
        self._job = None
        self.laatste_code = None
        # Unieke code per start; JARVIS zet hem in zijn hartslag. Zo
        # herkent de waakhond "zijn" JARVIS, ook als de venv-starter een
        # tweede proces met een ander pid maakt.
        self.sessie = None

    # ----- status -----

    def _schrijf_status(self, toestand, reden=None):
        gegevens = {
            "waakhond_pid": os.getpid(),
            "gestart_op": self.gestart_op,
            "toestand": toestand,
            "sessie": self.sessie,
            "starter_pid": getattr(self.proces, "pid", None),
            "jarvis_gestart_op": self.proces_gestart_op,
            "herstarts": self.totaal_herstarts,
            "laatste_herstart": self.laatste_herstart,
            "bijgewerkt_op": self.klok(),
        }
        if reden:
            gegevens["reden"] = reden
        try:
            hartslag.schrijf_atomair(self.status_pad, gegevens)
        except OSError:
            logger.debug("Kon de waakhondstatus niet schrijven.", exc_info=True)

    # ----- starten en stoppen -----

    def _start(self, herstart_reden=None):
        self.sessie = secrets.token_hex(8)
        env = os.environ.copy()
        env["JARVIS_WAAKHOND"] = "1"
        env["JARVIS_WAAKHOND_SESSIE"] = self.sessie
        env.pop("JARVIS_HERSTART_REDEN", None)
        if herstart_reden:
            env["JARVIS_HERSTART_REDEN"] = herstart_reden
        # Vóór het starten: dan valt ook het tweede proces van de
        # venv-starter vanzelf onder het jobobject.
        self._koppel_aan_job(None)
        self.proces = self.popen(self.commando, cwd=self.werkmap, env=env)
        self.proces_gestart_op = self.klok()
        logger.info("JARVIS gestart (starter-pid %s).", self.proces.pid)
        self._schrijf_status(TOESTAND_DRAAIT)

    def _koppel_aan_job(self, proces):
        """Zorgt dat JARVIS meestopt als de waakhond stopt (alleen Windows).

        De waakhond zet zichzelf (één keer) in een jobobject met
        KILL_ON_JOB_CLOSE. Elk proces dat hij daarna start, en elk proces
        dát weer start (de venv-starter!), hoort automatisch bij die job.
        Stopt de waakhond, dan sluit Windows de job en stopt alles mee.
        """

        if os.name != "nt" or self._job is not None:
            return
        try:
            import win32api
            import win32job

            job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
            win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
            self._job = job
        except Exception:
            logger.debug("Jobobject niet beschikbaar; JARVIS stopt niet vanzelf mee.", exc_info=True)

    def _jarvis_pids(self):
        """De processen van deze JARVIS naast de starter: zijn kinderen en
        het pid uit de hartslag (als die bij deze start hoort)."""

        pids = []
        try:
            import psutil

            if self.proces is not None:
                try:
                    pids += [c.pid for c in psutil.Process(self.proces.pid).children(recursive=True)]
                except psutil.Error:
                    pass
        except ImportError:
            pass
        hs = hartslag.lees_json(self.hartslag_pad)
        if hs and self.sessie and hs.get("sessie") == self.sessie and isinstance(hs.get("pid"), int):
            pids.append(hs["pid"])
        eigen = {os.getpid(), getattr(self.proces, "pid", None)}
        return [p for p in dict.fromkeys(pids) if p not in eigen]

    def _stop_pids(self, pids):
        if not pids:
            return
        try:
            import psutil
        except ImportError:
            return
        for pid in pids:
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                proc.wait(timeout=10)
            except psutil.TimeoutExpired:
                try:
                    proc.kill()
                except psutil.Error:
                    pass
            except psutil.Error:
                pass

    def _stop_proces(self):
        """Stopt JARVIS helemaal: de starter én het echte JARVIS-proces."""

        if self.proces is None:
            return
        restanten = self._jarvis_pids()
        if self.proces.poll() is None:
            try:
                self.proces.terminate()
                self.proces.wait(timeout=10)
            except Exception:
                try:
                    self.proces.kill()
                except Exception:
                    pass
        self._stop_pids(restanten)

    def _meld(self, tekst):
        if self.melder is None:
            return
        try:
            self.melder("JARVIS-waakhond", tekst)
        except Exception:
            logger.debug("Melding van de waakhond mislukt.", exc_info=True)

    # ----- de beslissingen -----

    def _wachttijd(self):
        if self.proces_gestart_op is not None and self.klok() - self.proces_gestart_op >= STABIEL_NA:
            self._stap = 0
        wacht = WACHTTIJDEN[min(self._stap, len(WACHTTIJDEN) - 1)]
        self._stap += 1
        return wacht

    def _mag_herstarten(self):
        nu = self.klok()
        self.herstarts = [t for t in self.herstarts if nu - t <= HERSTART_VENSTER]
        return len(self.herstarts) < MAX_HERSTARTS

    def controleer(self):
        """Eén controle. Geeft de reden om te herstarten, ``"stop"`` of ``None``."""

        code = self.proces.poll()
        self.laatste_code = code
        if code is not None:
            # Stopte alleen de starter (bijv. in Taakbeheer afgeschoten),
            # dan kan het echte JARVIS-proces nog draaien: eerst opruimen,
            # anders draaien er straks twee.
            self._stop_pids(self._jarvis_pids())
            if code in NIET_HERSTARTEN:
                return "stop"
            if code == EXIT_HERSTART:
                return "update"
            return _reden_exitcode(code)

        reden = hartslag.vastgelopen(
            hartslag.lees_json(self.hartslag_pad), self.klok(), self.sessie, self.proces_gestart_op
        )
        if reden:
            logger.warning("JARVIS lijkt vast te zitten: %s", reden)
            self._stop_proces()
            return f"vastgelopen: {reden}"
        return None

    def draai(self, max_controles=None):
        """De hoofdlus. Geeft de exitcode voor de waakhond zelf terug."""

        self._start()
        controles = 0
        while max_controles is None or controles < max_controles:
            controles += 1
            self.slaap(CONTROLE_INTERVAL)
            uitkomst = self.controleer()
            if uitkomst is None:
                continue

            if uitkomst == "stop":
                code = self.laatste_code
                reden = "door u gestopt" if code == EXIT_GESTOPT else "het wake-word-model ontbreekt"
                logger.info("JARVIS is gestopt (%s); de waakhond stopt ook.", reden)
                self._schrijf_status(TOESTAND_GESTOPT, reden)
                if code == EXIT_GEEN_WAKE_WORD:
                    self._meld("JARVIS is gestopt: het wake-word-model ontbreekt. Draai scripts\\brein_check.py.")
                return 0

            if uitkomst == "update":
                logger.info("JARVIS is bijgewerkt; meteen opnieuw starten.")
                self.laatste_herstart = {"tijd": self.klok(), "reden": "update geïnstalleerd"}
                self._start(herstart_reden="update geïnstalleerd")
                continue

            if not self._mag_herstarten():
                reden = f"{MAX_HERSTARTS} herstarts binnen {HERSTART_VENSTER // 60} minuten; laatste: {uitkomst}"
                logger.error("Waakhond geeft het op: %s", reden)
                self._schrijf_status(TOESTAND_GESTOPT, reden)
                self._meld("JARVIS is gestopt na herhaalde fouten. Bekijk logs\\jarvis.log.")
                return 1

            wacht = self._wachttijd()
            self.herstarts.append(self.klok())
            self.totaal_herstarts += 1
            self.laatste_herstart = {"tijd": self.klok(), "reden": uitkomst}
            logger.warning("JARVIS %s; herstart over %d s.", uitkomst, wacht)
            self._schrijf_status(TOESTAND_HERSTART, uitkomst)
            self.slaap(wacht)
            self._start(herstart_reden=uitkomst)
        return 0


# ------------------------------------------------------------------
# Status voor het dashboard
# ------------------------------------------------------------------


def _proces_start():
    try:
        import psutil

        return psutil.Process(os.getpid()).create_time()
    except Exception:
        return None


_PROCES_START = _proces_start() or time.time()


def brein_status(nu=None, status_pad=STATUS_FILE, env=None, proces_start=None):
    """Hoe het met het brein gaat, voor het Systeem-paneel.

    ``bewaakt`` is alleen True als deze JARVIS echt door de waakhond is
    gestart (en de status over dít proces gaat). Er staan geen paden,
    tokens of foutteksten uit de log in; alleen de reden van de waakhond.
    """

    nu = time.time() if nu is None else nu
    env = os.environ if env is None else env
    start = _PROCES_START if proces_start is None else proces_start

    sessie = env.get("JARVIS_WAAKHOND_SESSIE")
    status = hartslag.lees_json(status_pad) if env.get("JARVIS_WAAKHOND") == "1" and sessie else None
    bewaakt = bool(status) and status.get("sessie") == sessie
    laatste = status.get("laatste_herstart") if bewaakt else None
    if isinstance(laatste, dict) and laatste.get("tijd"):
        try:
            laatste = {
                "tijd": time.strftime("%d-%m %H:%M", time.localtime(float(laatste["tijd"]))),
                "reden": str(laatste.get("reden") or "onbekend")[:120],
            }
        except (TypeError, ValueError, OverflowError):
            laatste = None
    else:
        laatste = None

    herstarts = 0
    if bewaakt:
        try:
            herstarts = int(status.get("herstarts") or 0)
        except (TypeError, ValueError):
            herstarts = 0

    return {
        "actief_minuten": max(0, int((nu - start) // 60)),
        "bewaakt": bewaakt,
        "herstarts": herstarts,
        "laatste_herstart": laatste,
    }


# ------------------------------------------------------------------
# Eén waakhond tegelijk
# ------------------------------------------------------------------


def neem_slot(pad=LOCK_FILE):
    """Een open bestand met slot, of ``None`` als er al een waakhond draait.

    Het slot verdwijnt vanzelf als het proces stopt (ook bij een crash).
    """

    os.makedirs(os.path.dirname(pad), exist_ok=True)
    f = open(pad, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def _log_instellen():
    """Een eigen logbestand: JARVIS zelf roteert ``jarvis.log``, en twee
    processen die hetzelfde bestand roteren botsen op Windows."""

    from logging.handlers import RotatingFileHandler

    os.makedirs(os.path.join(PROJECT, "logs"), exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(PROJECT, "logs", "waakhond.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    vorm = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(vorm)
    console = logging.StreamHandler()
    console.setFormatter(vorm)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.addHandler(console)
    logger.propagate = False


def main():
    _log_instellen()
    slot = neem_slot()
    if slot is None:
        print("Er draait al een JARVIS-waakhond; ik start geen tweede.")
        return 2

    from voice.notify import toon_toast

    return Waakhond(melder=toon_toast).draai()


if __name__ == "__main__":
    sys.exit(main())
