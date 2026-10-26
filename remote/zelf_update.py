"""De Game-PC Agent werkt zichzelf bij (Fase 21).

Het brein roept na zijn eigen update (na uw "ja") de ondertekende route
``/update`` aan. De agent doet dan precies wat het brein ook doet
(:mod:`beheer.updates`): alleen een *fast-forward* naar GitHub, nooit als er
lokale wijzigingen of eigen commits zijn. Daarna start hij zichzelf opnieuw
op, zodat de nieuwe code meteen draait.

Een backup is hier niet nodig: op de game-pc staat geen breindata, en een
fast-forward verandert niets aan uw eigen bestanden.
"""

import logging
import os
import subprocess
import sys
import threading
import time

from beheer import updates

logger = logging.getLogger("jarvis.remote.update")

# Even wachten zodat het antwoord eerst bij het brein aankomt.
HERSTART_VERTRAGING = 2


def voer_uit(zoek_fn=None, installeer_fn=None, herstart_fn=None):
    """Zoekt en installeert de update. Geeft het antwoord voor het brein."""

    zoek_fn = zoek_fn or updates.zoek_updates
    installeer_fn = installeer_fn or updates.installeer
    herstart_fn = herstart_fn or plan_herstart
    pip_nodig = []
    try:
        if not zoek_fn()["aantal"]:
            return {"ok": True, "status": "actueel", "aantal": 0}
        # pip pas na het antwoord: dat kan minuten duren.
        aantal = installeer_fn(backup_fn=lambda: (True, ""), pip_fn=pip_nodig.append)
    except updates.UpdateFout as fout:
        logger.warning("Agent niet bijgewerkt: %s", fout)
        return {"ok": False, "fout": {"code": "update_fout", "melding": str(fout)[:200]}}
    herstart_fn(bool(pip_nodig))
    return {"ok": True, "status": "bijgewerkt", "aantal": aantal}


def plan_herstart(pip=False, vertraging=HERSTART_VERTRAGING, exit_fn=os._exit, popen=subprocess.Popen):
    """Start een nieuwe agent en stopt deze, na ``vertraging`` seconden."""

    def _herstart():
        time.sleep(vertraging)
        if pip:
            try:
                updates._pip_install(updates.PROJECT)
            except updates.UpdateFout as fout:
                logger.warning("pip install na de update mislukte: %s", fout)
        vlaggen = 0
        for naam in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
            vlaggen |= getattr(subprocess, naam, 0)
        logger.info("Agent herstart na de update.")
        popen([sys.executable, "-m", "remote.server"], cwd=updates.PROJECT,
              creationflags=vlaggen, close_fds=True)
        exit_fn(0)

    threading.Thread(target=_herstart, name="agent-herstart", daemon=True).start()
