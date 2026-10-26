"""Updates van JARVIS (Fase 19, M6).

Semi-automatisch, zoals afgesproken: JARVIS **kijkt** zelf of er op GitHub
een nieuwe versie staat en **meldt** dat met de wijzigingen (de
commitberichten). **Installeren gebeurt alleen na uw "ja"** in het oranje
venster (dashboard) of met de stem.

Installeren is voorzichtig:

* alleen een *fast-forward* (``git merge --ff-only``): uw eigen commits
  worden nooit overschreven of samengevoegd;
* niet als er lokale wijzigingen in de code zijn;
* eerst een backup (:mod:`beheer.backup`);
* daarna, alleen als ``requirements.txt`` veranderde, ``pip install``;
* tot slot een herstart via de waakhond (exitcode ``EXIT_HERSTART``).

Git draait met een vaste argumentenlijst (nooit een shell) en een
time-out.
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from beheer import data, hartslag

logger = logging.getLogger("jarvis.updates")

PROJECT = data.PROJECT
STATUS_FILE = os.path.join(PROJECT, "logs", "updates.json")

# main.py stopt met deze code; de waakhond start hem dan meteen opnieuw.
EXIT_HERSTART = 5

GIT_TIMEOUT = 60
PIP_TIMEOUT = 900
MAX_WIJZIGINGEN = 10
EERSTE_CHECK_NA = 600
CHECK_INTERVAL = 24 * 3600
HERSTART_VERTRAGING = 8
VEREISTEN = ("requirements.txt",)

UPDATE_KIND = "update_confirm"


class UpdateFout(Exception):
    """De update kon niet (veilig) gezocht of geïnstalleerd worden."""


# ------------------------------------------------------------------
# Git
# ------------------------------------------------------------------


def _git(*args, project=PROJECT, timeout=GIT_TIMEOUT):
    git = shutil.which("git")
    if not git:
        raise UpdateFout("Git is niet geïnstalleerd.")
    try:
        uit = subprocess.run(
            [git, *args], cwd=project, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise UpdateFout(f"git {args[0]} duurde te lang.") from None
    if uit.returncode != 0:
        melding = (uit.stderr or uit.stdout or "").strip().splitlines()
        raise UpdateFout(f"git {args[0]} mislukt: {melding[-1] if melding else uit.returncode}")
    return uit.stdout.strip()


def zoek_updates(git=_git):
    """Haalt de nieuwste stand op en vergelijkt. Geeft een info-dict.

    ``{"upstream", "sha", "aantal", "wijzigingen"}``; gooit
    :class:`UpdateFout` als het niet lukt.
    """

    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    remote = upstream.split("/", 1)[0]
    git("fetch", "--quiet", remote)
    aantal = int(git("rev-list", "--count", "HEAD..@{u}") or 0)
    sha = git("rev-parse", "@{u}")
    wijzigingen = []
    if aantal:
        log = git("log", "--format=%s", f"-n{MAX_WIJZIGINGEN}", "HEAD..@{u}")
        wijzigingen = [regel.strip() for regel in log.splitlines() if regel.strip()]
    return {"upstream": upstream, "sha": sha, "aantal": aantal, "wijzigingen": wijzigingen}


def kan_installeren(git=_git):
    """``None`` als installeren veilig is, anders de reden."""

    gewijzigd = git("status", "--porcelain", "--untracked-files=no")
    if gewijzigd:
        namen = [regel[3:].strip() for regel in gewijzigd.splitlines() if len(regel) > 3]
        lijst = ", ".join(namen[:3]) + (f" en nog {len(namen) - 3}" if len(namen) > 3 else "")
        return f"er zijn lokale wijzigingen in de code ({lijst}); die overschrijf ik niet."
    if int(git("rev-list", "--count", "@{u}..HEAD") or 0):
        return "deze pc heeft eigen commits die nog niet op GitHub staan."
    if not int(git("rev-list", "--count", "HEAD..@{u}") or 0):
        return "er is geen nieuwe versie."
    return None


def _vingerafdruk(project=PROJECT):
    h = hashlib.sha256()
    for naam in VEREISTEN:
        try:
            with open(os.path.join(project, naam), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()


def _pip_install(project=PROJECT):
    try:
        uit = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
            cwd=project, capture_output=True, text=True, timeout=PIP_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise UpdateFout("pip install duurde te lang.") from None
    if uit.returncode != 0:
        regels = (uit.stderr or uit.stdout or "").strip().splitlines()
        raise UpdateFout(f"pip install mislukt: {regels[-1] if regels else uit.returncode}")


def installeer(git=_git, backup_fn=None, pip_fn=_pip_install, project=PROJECT):
    """Installeert de update. Geeft het aantal nieuwe wijzigingen terug.

    Gooit :class:`UpdateFout` als het niet veilig kan of mislukt; dan is er
    niets aan de code veranderd (de backup blijft gewoon staan).
    """

    reden = kan_installeren(git)
    if reden:
        raise UpdateFout(reden)
    aantal = int(git("rev-list", "--count", "HEAD..@{u}") or 0)

    if backup_fn is None:
        from beheer import backup

        def backup_fn():
            return backup.voer_uit()
    ok, info = backup_fn()
    if not ok:
        raise UpdateFout(f"de backup vooraf is mislukt ({info}); ik installeer niets.")

    voor = _vingerafdruk(project)
    git("merge", "--ff-only", "@{u}")
    if _vingerafdruk(project) != voor:
        pip_fn(project)
    return aantal


# ------------------------------------------------------------------
# Status (dashboard) en melden
# ------------------------------------------------------------------


def lees_status(pad=STATUS_FILE):
    return hartslag.lees_json(pad) or {}


def _schrijf_status(status, pad=STATUS_FILE):
    try:
        hartslag.schrijf_atomair(pad, status)
    except OSError:
        logger.debug("Kon de updatestatus niet schrijven.", exc_info=True)


def controleer(nu=None, status_pad=STATUS_FILE, zoek_fn=zoek_updates):
    """Zoekt updates en werkt de status bij. Gooit nooit.

    Geeft de status-dict terug; ``nieuw_te_melden`` is True als er een
    update is die nog niet gemeld werd.
    """

    nu = time.time() if nu is None else nu
    status = lees_status(status_pad)
    status["laatste_check"] = nu
    try:
        info = zoek_fn()
    except (UpdateFout, OSError, ValueError) as fout:
        status["fout"] = str(fout)[:200]
        _schrijf_status(status, status_pad)
        status["nieuw_te_melden"] = False
        return status

    status.update({"fout": None, "aantal": info["aantal"], "wijzigingen": info["wijzigingen"][:MAX_WIJZIGINGEN],
                   "sha": info["sha"]})
    nieuw = bool(info["aantal"]) and status.get("gemeld_sha") != info["sha"]
    if nieuw:
        status["gemeld_sha"] = info["sha"]
    _schrijf_status(status, status_pad)
    status["nieuw_te_melden"] = nieuw
    return status


def melding_tekst(status):
    aantal = status.get("aantal") or 0
    wijzigingen = status.get("wijzigingen") or []
    kort = "; ".join(_kort(w) for w in wijzigingen[:3])
    meer = f" en nog {aantal - 3}" if aantal > 3 else ""
    return (f"Sir, er is een update van JARVIS met {aantal} "
            f"{'wijziging' if aantal == 1 else 'wijzigingen'}: {kort}{meer}. "
            "Zeg 'installeer de update' of keur hem goed op het dashboard.")


def _kort(bericht):
    # "feat(fase19): M6 updates" -> "M6 updates"
    return re.sub(r"^[a-z]+(\([^)]*\))?!?:\s*", "", bericht)[:80]


def samenvatting(status_pad=STATUS_FILE):
    """Voor het Systeem-paneel: zonder paden of sha's."""

    import config

    status = lees_status(status_pad)
    laatste = status.get("laatste_check")
    return {
        "ingeschakeld": bool(getattr(config, "UPDATES_ENABLED", True)),
        "beschikbaar": int(status.get("aantal") or 0),
        "wijzigingen": [_kort(w) for w in (status.get("wijzigingen") or [])[:MAX_WIJZIGINGEN]],
        "laatste_check": time.strftime("%d-%m %H:%M", time.localtime(laatste)) if isinstance(laatste, (int, float)) else None,
        "fout": status.get("fout"),
    }


# ------------------------------------------------------------------
# Goedkeuren en uitvoeren
# ------------------------------------------------------------------


def vraag_goedkeuring(status_pad=STATUS_FILE):
    """Zet de ja/nee-vraag klaar. Geeft ``(pending_of_None, tekst)``."""

    from core import confirmation

    status = lees_status(status_pad)
    aantal = int(status.get("aantal") or 0)
    if not aantal:
        return None, "Er is geen nieuwe versie van JARVIS, sir."
    pending = confirmation.set_pending(UPDATE_KIND, {
        "action": "JARVIS bijwerken",
        "target": f"{aantal} {'wijziging' if aantal == 1 else 'wijzigingen'}",
        "question": f"JARVIS bijwerken naar de nieuwste versie ({aantal} "
                    f"{'wijziging' if aantal == 1 else 'wijzigingen'})? Ik maak eerst een backup "
                    "en start daarna opnieuw op.",
    }, ttl=120)
    return pending, pending["question"]


def werk_game_pc_bij(client_fn=None):
    """Laat de agent op de game-pc zichzelf bijwerken (Fase 21).

    Geeft één zin voor de gebruiker, of ``""`` als er geen game-pc is
    ingesteld. Gooit nooit.
    """

    import config

    if client_fn is None:
        if not getattr(config, "REMOTE_CLIENT_ENABLED", False):
            return ""

        def client_fn():
            from remote.client import RemoteClient

            return RemoteClient()
    try:
        r = client_fn().update()
    except Exception as fout:
        logger.warning("Game-pc bijwerken mislukte: %s", fout)
        return "De game-pc kon ik niet bijwerken; zeg later 'werk de game-pc bij'."
    if r.ok:
        data = r.resultaat if isinstance(r.resultaat, dict) else {}
        if data.get("status") == "bijgewerkt":
            return "De game-pc is ook bijgewerkt; zijn agent start opnieuw op."
        return "De game-pc was al bij."
    if r.fout_code == "onbekende_route":
        return ("De agent op de game-pc is te oud om zichzelf bij te werken: doe daar één keer "
                "git pull en herstart de agent.")
    if r.fout_code == "update_fout":
        return f"De game-pc is niet bijgewerkt: {r.fout_melding}"
    if getattr(r, "lokaal", False):
        return "De game-pc was niet bereikbaar; zeg later 'werk de game-pc bij'."
    return f"De game-pc is niet bijgewerkt: {r.samenvatting()}"


def voer_uit_na_goedkeuring(installeer_fn=installeer, herstart_fn=None, status_pad=STATUS_FILE,
                            game_pc_fn=werk_game_pc_bij):
    """Na "ja": installeren, de game-pc bijwerken en herstarten.

    Geeft de gesproken tekst terug.
    """

    try:
        aantal = installeer_fn()
    except UpdateFout as fout:
        logger.warning("Update niet geïnstalleerd: %s", fout)
        return f"De update is niet geïnstalleerd: {fout}"

    status = lees_status(status_pad)
    status.update({"aantal": 0, "wijzigingen": [], "geinstalleerd_op": time.time()})
    _schrijf_status(status, status_pad)

    # Zelfde versie op de game-pc, anders kent zijn agent nieuwe acties niet.
    pc = game_pc_fn() if game_pc_fn else ""
    pc = f" {pc}" if pc else ""

    if os.environ.get("JARVIS_WAAKHOND") != "1":
        return (f"De update is geïnstalleerd ({aantal} wijzigingen).{pc} "
                "Herstart JARVIS om hem te gebruiken.")
    (herstart_fn or plan_herstart)()
    return f"De update is geïnstalleerd ({aantal} wijzigingen).{pc} Ik start zo opnieuw op, sir."


def plan_herstart(vertraging=HERSTART_VERTRAGING, exit_fn=os._exit):
    """Stopt JARVIS na ``vertraging`` seconden met ``EXIT_HERSTART``.

    De vertraging laat JARVIS eerst zijn antwoord uitspreken. De waakhond
    start hem daarna direct opnieuw (geen wachttijd, telt niet als crash).
    """

    def _stop():
        time.sleep(vertraging)
        logger.info("Herstart na de update.")
        exit_fn(EXIT_HERSTART)

    threading.Thread(target=_stop, name="jarvis-herstart", daemon=True).start()


# ------------------------------------------------------------------
# Spraakcommando's
# ------------------------------------------------------------------

_INSTALLEER = re.compile(
    r"^(?:installeer|instaleer)\s+(?:de\s+)?(?:nieuwe\s+)?update$"
    r"|^update\s+jarvis$|^werk\s+jarvis\s+bij$|^installeer\s+de\s+nieuwe\s+versie$"
)
_ZOEK = re.compile(
    r"^(?:zijn\s+er|is\s+er\s+een|heb\s+je|heeft\s+jarvis)\s+(?:nieuwe\s+)?updates?(?:\s+voor\s+jarvis)?$"
    r"|^zoek\s+(?:naar\s+)?updates?$"
)


_GAME_PC = re.compile(
    r"^(?:update|werk)\s+(?:de\s+)?(?:agent\s+(?:op|van)\s+de\s+)?game[\s-]?pc(?:\s+bij)?$"
    r"|^(?:de\s+)?game[\s-]?pc\s+(?:bijwerken|updaten)$"
)


def probeer_commando(command, zoek_fn=None, game_pc_fn=None):
    """``None`` als het geen updatecommando is, anders het antwoord."""

    tekst = (command or "").strip().lower().rstrip(" ?.!")
    if _GAME_PC.match(tekst):
        return (game_pc_fn or werk_game_pc_bij)() or "Er is geen game-pc ingesteld, sir."
    if _INSTALLEER.match(tekst):
        _pending, vraag = vraag_goedkeuring()
        return vraag
    if _ZOEK.match(tekst):
        status = controleer(zoek_fn=zoek_fn) if zoek_fn else controleer()
        if status.get("fout"):
            return f"Ik kon niet op updates controleren: {status['fout']}"
        if status.get("aantal"):
            return melding_tekst(status)
        return "JARVIS is up-to-date, sir."
    return None


# ------------------------------------------------------------------
# Planner (draait in JARVIS)
# ------------------------------------------------------------------


class UpdatePlanner:
    """Kijkt kort na het starten en daarna elke dag of er een update is."""

    def __init__(self, meld_fn=None, klok=time.time, controleer_fn=None, status_pad=STATUS_FILE):
        self.meld_fn = meld_fn
        self.klok = klok
        self.controleer_fn = controleer_fn or (lambda nu: controleer(nu=nu, status_pad=status_pad))
        self.status_pad = status_pad
        self.gestart_op = klok()
        self._stop = threading.Event()
        self._thread = None

    def is_nodig(self, nu):
        if nu - self.gestart_op < EERSTE_CHECK_NA:
            return False
        laatste = lees_status(self.status_pad).get("laatste_check")
        return not isinstance(laatste, (int, float)) or nu - laatste >= CHECK_INTERVAL

    def stap(self):
        nu = self.klok()
        if not self.is_nodig(nu):
            return False
        status = self.controleer_fn(nu)
        if status.get("nieuw_te_melden") and self.meld_fn is not None:
            try:
                self.meld_fn(melding_tekst(status), bron="update")
            except Exception:
                logger.debug("Kon de updatemelding niet versturen.", exc_info=True)
        return True

    def _lus(self):
        while not self._stop.wait(60):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout in de updateplanner.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-updates", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
