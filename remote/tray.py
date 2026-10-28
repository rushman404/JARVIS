"""Taakbalk-icoon voor de Game-PC Agent.

De geplande taak "JARVIS Game-PC Agent" start niet meer de agent zelf maar
dit programma, zonder consolevenster::

    pythonw -m remote.tray

Rechtsonder in de taakbalk (bij het pijltje) staat dan een JARVIS-icoon.
Rechtermuisknop geeft het menu:

* **Starten / Stoppen** — de agent aan- of uitzetten;
* **Herstarten** — stoppen en meteen weer starten;
* **Logboek openen** — ``logs/agent.log`` (wat eerst in het zwarte venster stond);
* **Afsluiten** — agent én icoon stoppen.

Linkermuisknop toont de status als melding.

Het icoon start de agent (``python -m remote.server``) als kindproces en
houdt hem in de gaten:

* **Exitcode 5** (na een zelf-update, zie :mod:`remote.zelf_update`):
  meteen opnieuw starten.
* **Andere onverwachte stop** (crash): opnieuw starten na een oplopende
  wachttijd; na ``MAX_HERSTARTS`` keer binnen ``HERSTART_VENSTER`` geeft
  het icoon het op en toont het een melding.
* **De agent stopt mee** met het icoon (Windows-jobobject), zodat
  ``Stop-ScheduledTask`` geen losse agent achterlaat.
"""

import logging
import os
import subprocess
import sys
import threading
import time

from beheer.waakhond import neem_slot

logger = logging.getLogger("jarvis.remote.tray")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_MAP = os.path.join(PROJECT, "logs")
AGENT_LOG = os.path.join(LOG_MAP, "agent.log")
TRAY_LOG = os.path.join(LOG_MAP, "agent-tray.log")
LOCK_FILE = os.path.join(LOG_MAP, "agent-tray.lock")
MAX_LOG_BYTES = 1_000_000

# Zelfde betekenis als bij de waakhond van het brein.
EXIT_HERSTART = 5
ENV_TRAY = "JARVIS_AGENT_TRAY"

WACHTTIJDEN = (5, 15, 30, 60, 120, 300)
STABIEL_NA = 600
MAX_HERSTARTS = 5
HERSTART_VENSTER = 900
CONTROLE_INTERVAL = 2

TOESTAND_DRAAIT = "draait"
TOESTAND_GESTOPT = "gestopt"
TOESTAND_HERSTART = "herstart"
TOESTAND_OPGEGEVEN = "opgegeven"

KLEUREN = {
    TOESTAND_DRAAIT: (46, 160, 67),
    TOESTAND_HERSTART: (230, 145, 30),
    TOESTAND_GESTOPT: (130, 130, 130),
    TOESTAND_OPGEGEVEN: (200, 50, 50),
}

TEKSTEN = {
    TOESTAND_DRAAIT: "De agent draait",
    TOESTAND_HERSTART: "De agent herstart",
    TOESTAND_GESTOPT: "De agent staat uit",
    TOESTAND_OPGEGEVEN: "De agent is te vaak gecrasht en staat uit",
}


def _geen_venster():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _roteer_log(pad=AGENT_LOG, max_bytes=MAX_LOG_BYTES):
    """Eén oude kopie (``agent.log.1``) bewaren, zodat het log niet blijft groeien."""

    try:
        if os.path.getsize(pad) > max_bytes:
            os.replace(pad, pad + ".1")
    except OSError:
        pass


def _kindprocessen(pid):
    """De processen die de agent zelf startte (de venv-starter start nog een python.exe)."""

    import psutil

    return psutil.Process(pid).children(recursive=True)


class AgentBeheer:
    """Start, stopt en bewaakt het agent-proces (zonder icoon, dus testbaar)."""

    def __init__(self, commando=None, werkmap=PROJECT, popen=subprocess.Popen, klok=time.monotonic,
                 log_pad=AGENT_LOG, bij_wijziging=None, melder=None, kinderen=None):
        self.commando = commando or [sys.executable, "-m", "remote.server"]
        self.werkmap = werkmap
        self.popen = popen
        self.kinderen = kinderen or _kindprocessen
        self.klok = klok
        self.log_pad = log_pad
        self.bij_wijziging = bij_wijziging
        self.melder = melder
        self.proces = None
        self.toestand = TOESTAND_GESTOPT
        self.gestart_op = None
        self.herstarts = []
        self._stap = 0
        self._volgende_start = None
        self._lock = threading.RLock()
        self._job = None

    # ----- toestand -----

    def _zet(self, toestand):
        if toestand == self.toestand:
            return
        self.toestand = toestand
        logger.info("Toestand: %s", toestand)
        if self.bij_wijziging is not None:
            try:
                self.bij_wijziging(toestand)
            except Exception:
                logger.debug("Icoon bijwerken mislukt.", exc_info=True)

    def draait(self):
        return self.proces is not None and self.proces.poll() is None

    def _meld(self, tekst):
        if self.melder is None:
            return
        try:
            self.melder(tekst)
        except Exception:
            logger.debug("Melding mislukt.", exc_info=True)

    # ----- starten en stoppen -----

    def start(self):
        """Start de agent (doet niets als hij al draait). Door de gebruiker:
        de crashteller begint opnieuw."""

        with self._lock:
            self.herstarts.clear()
            self._stap = 0
            self._volgende_start = None
            self._start()

    def _start(self):
        if self.draait():
            self._zet(TOESTAND_DRAAIT)
            return
        self._koppel_aan_job()
        os.makedirs(os.path.dirname(self.log_pad), exist_ok=True)
        _roteer_log(self.log_pad)
        env = os.environ.copy()
        env[ENV_TRAY] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # Anders blijven prints in een buffer en ziet het logboek ze pas laat.
        env["PYTHONUNBUFFERED"] = "1"
        with open(self.log_pad, "ab") as log:
            self.proces = self.popen(
                self.commando, cwd=self.werkmap, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, creationflags=_geen_venster(),
            )
        self.gestart_op = self.klok()
        logger.info("Agent gestart (pid %s).", self.proces.pid)
        self._zet(TOESTAND_DRAAIT)

    def stop(self):
        """Stopt de agent; hij start niet vanzelf opnieuw."""

        with self._lock:
            self._volgende_start = None
            self._stop_proces()
            self._zet(TOESTAND_GESTOPT)

    def herstart(self):
        with self._lock:
            self._stop_proces()
            self.start()

    def _stop_proces(self):
        """Stopt de agent én de processen die hij startte (de venv-starter
        start zelf nog een python.exe)."""

        if self.proces is None:
            return
        proces, self.proces = self.proces, None
        try:
            kinderen = self.kinderen(proces.pid)
        except Exception:
            kinderen = []
        if proces.poll() is None:
            try:
                proces.terminate()
                proces.wait(timeout=10)
            except Exception:
                try:
                    proces.kill()
                except Exception:
                    pass
        for kind in kinderen:
            try:
                kind.kill()
            except Exception:
                pass
        logger.info("Agent gestopt.")

    def _koppel_aan_job(self):
        """Zorgt dat de agent meestopt als het icoon stopt (alleen Windows)."""

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
            logger.debug("Jobobject niet beschikbaar; de agent stopt niet vanzelf mee.", exc_info=True)

    # ----- bewaking -----

    def _wachttijd(self):
        if self.gestart_op is not None and self.klok() - self.gestart_op >= STABIEL_NA:
            self._stap = 0
        wacht = WACHTTIJDEN[min(self._stap, len(WACHTTIJDEN) - 1)]
        self._stap += 1
        return wacht

    def controleer(self):
        """Eén controle; de bewakingsthread roept dit elke paar seconden aan."""

        with self._lock:
            nu = self.klok()
            if self._volgende_start is not None:
                if nu >= self._volgende_start:
                    self._volgende_start = None
                    self._start()
                return
            if self.proces is None:
                return
            code = self.proces.poll()
            if code is None:
                return
            self.proces = None
            if code == EXIT_HERSTART:
                logger.info("Agent herstart na een update.")
                self._start()
                return
            logger.warning("Agent onverwacht gestopt (code %s).", code)
            self.herstarts = [t for t in self.herstarts if nu - t < HERSTART_VENSTER]
            if len(self.herstarts) >= MAX_HERSTARTS:
                self._zet(TOESTAND_OPGEGEVEN)
                self._meld("De Game-PC Agent is te vaak gecrasht en staat nu uit. Kijk in het logboek.")
                return
            self.herstarts.append(nu)
            self._volgende_start = nu + self._wachttijd()
            self._zet(TOESTAND_HERSTART)

    def bewaak(self, stop_event):
        while not stop_event.wait(CONTROLE_INTERVAL):
            try:
                self.controleer()
            except Exception:
                logger.exception("Fout in de bewaking van de agent.")


# ------------------------------------------------------------------
# Het icoon
# ------------------------------------------------------------------


def maak_afbeelding(toestand, grootte=64):
    """Een rond icoon met een "J"; de kleur toont de toestand."""

    from PIL import Image, ImageDraw, ImageFont

    beeld = Image.new("RGBA", (grootte, grootte), (0, 0, 0, 0))
    teken = ImageDraw.Draw(beeld)
    teken.ellipse((2, 2, grootte - 2, grootte - 2), fill=KLEUREN[toestand] + (255,))
    try:
        letter = ImageFont.truetype("segoeuib.ttf", int(grootte * 0.62))
    except OSError:
        letter = ImageFont.load_default()
    teken.text((grootte / 2, grootte / 2), "J", fill=(255, 255, 255, 255), font=letter, anchor="mm")
    return beeld


def _open_bestand(pad):
    if not os.path.exists(pad):
        open(pad, "a").close()
    os.startfile(pad)  # noqa: S606 - eigen logbestand in de projectmap


def _log_instellen():
    from logging.handlers import RotatingFileHandler

    os.makedirs(LOG_MAP, exist_ok=True)
    handler = RotatingFileHandler(TRAY_LOG, maxBytes=MAX_LOG_BYTES, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False


def main():
    _log_instellen()
    slot = neem_slot(LOCK_FILE)
    if slot is None:
        logger.info("Er draait al een agent-icoon; ik start geen tweede.")
        return 2

    import pystray

    icoon = pystray.Icon("jarvis-game-pc-agent", maak_afbeelding(TOESTAND_GESTOPT), "JARVIS Game-PC Agent")

    def bij_wijziging(toestand):
        icoon.icon = maak_afbeelding(toestand)
        icoon.title = f"JARVIS Game-PC Agent - {TEKSTEN[toestand].lower()}"
        icoon.update_menu()

    beheer = AgentBeheer(bij_wijziging=bij_wijziging,
                         melder=lambda tekst: icoon.notify(tekst, "JARVIS Game-PC Agent"))
    stop_event = threading.Event()

    def afsluiten(icon, _item):
        stop_event.set()
        beheer.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda _item: TEKSTEN[beheer.toestand], None, enabled=False),
        pystray.MenuItem("Status", lambda icon, _item: icon.notify(TEKSTEN[beheer.toestand]),
                         default=True, visible=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Starten", lambda _icon, _item: beheer.start(),
                         enabled=lambda _item: beheer.toestand != TOESTAND_DRAAIT),
        pystray.MenuItem("Stoppen", lambda _icon, _item: beheer.stop(),
                         enabled=lambda _item: beheer.toestand != TOESTAND_GESTOPT),
        pystray.MenuItem("Herstarten", lambda _icon, _item: beheer.herstart()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Logboek openen", lambda _icon, _item: _open_bestand(AGENT_LOG)),
        pystray.MenuItem("Afsluiten", afsluiten),
    )
    icoon.menu = menu

    def bij_start(icon):
        icon.visible = True
        beheer.start()
        threading.Thread(target=beheer.bewaak, args=(stop_event,), name="agent-bewaking", daemon=True).start()

    try:
        icoon.run(setup=bij_start)
    finally:
        stop_event.set()
        beheer.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
