"""Karakter (Fase 21, M4): statusbegroeting op vraag en easter eggs.

"JARVIS, status" of "systeemcheck" geeft een begroeting met het dagdeel en
noemt alleen echte problemen:

    "Goedenavond, sir. Alle systemen zijn operationeel."
    "Goedemorgen, sir. Alles draait, behalve de game-pc: die is offline."

Bewust alleen op vraag (besluit 2026-10-25): niet bij elke start.

Daarnaast een kleine, vaste set easter eggs ("ik ben Iron Man", "dank je,
JARVIS", "ben je daar?"). Subtiel: alleen bij precies die zinnen, nooit
grapjes tussen gewone antwoorden door.
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait

logger = logging.getLogger(__name__)

# Hoe lang een statuscontrole mag duren (samen, ze lopen parallel).
CHECK_SECONDEN = 4.0


def _schoon(tekst):
    t = str(tekst or "").lower().strip()
    t = re.sub(r"^\s*(hey\s+|ok\s+|okay\s+)?jarvis\b[,\s]*", "", t)
    t = re.sub(r"[,\s]*\bjarvis\s*[.!?]*$", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


# -----------------------------------------------------------------
# Statusbegroeting
# -----------------------------------------------------------------

STATUS_PATROON = re.compile(
    r"^(?:status|systeem\s*check|systeem\s*status|status\s*rapport|statusupdate|status\s+update"
    r"|geef\s+(?:me\s+)?(?:een\s+|de\s+)?(?:status|statusrapport|systeemcheck)"
    r"|wat\s+is\s+de\s+status|hoe\s+staat\s+alles\s+ervoor|hoe\s+staan\s+de\s+systemen(?:\s+ervoor)?"
    r"|zijn\s+alle\s+systemen\s+(?:operationeel|in\s+orde)|doe\s+een\s+systeemcheck)$"
)


def dagdeel(uur):
    if 6 <= uur < 12:
        return "Goedemorgen"
    if 12 <= uur < 18:
        return "Goedemiddag"
    if 18 <= uur < 24:
        return "Goedenavond"
    return "Goedenacht"


def _ha_ok():
    from core.home_assistant import _config_ok, _ha_get

    if not _config_ok():
        return None
    ok, _ = _ha_get("/api/")
    return bool(ok)


def _backup_ok():
    import config

    if not getattr(config, "BACKUP_ENABLED", False):
        return None
    from beheer import backup

    ok = backup.samenvatting().get("ok")
    return None if ok is None else bool(ok)


def standaard_checks():
    """``[(naam, probe, probleemzin)]``. Een probe geeft True (in orde),
    False (probleem) of None (niet van toepassing)."""

    from beheer import verbinding

    return [
        ("Home Assistant", _ha_ok, "Home Assistant reageert niet"),
        ("de game-pc", verbinding.game_pc_online, "de game-pc is offline"),
        ("het AI-model", verbinding.ollama_online, "het AI-model reageert niet"),
        ("internet", verbinding.internet_online, "er is geen internet"),
        ("de backup", _backup_ok, "de laatste backup is mislukt"),
    ]


def problemen(checks=None, timeout=CHECK_SECONDEN):
    """De probleemzinnen, in vaste volgorde. Te traag = probleem."""

    checks = standaard_checks() if checks is None else checks
    uit = []
    pool = ThreadPoolExecutor(max_workers=max(1, len(checks)), thread_name_prefix="jarvis-status")
    try:
        taken = [(naam, zin, pool.submit(probe)) for naam, probe, zin in checks]
        wait([t[2] for t in taken], timeout=timeout)
        for naam, zin, taak in taken:
            if not taak.done():
                uit.append(f"{naam} reageert niet")
                continue
            try:
                resultaat = taak.result()
            except Exception:
                resultaat = False
            if resultaat is False:
                uit.append(zin)
    finally:
        pool.shutdown(wait=False)
    return uit


def _extra():
    """Kleine toevoeging als de film-modus aanstaat."""

    try:
        from core import filmmodus

        if filmmodus.lees_toestand() is not None:
            return " De film-modus staat aan."
    except Exception:
        pass
    return ""


def statusrapport(checks=None, uur=None):
    uur = time.localtime().tm_hour if uur is None else uur
    groet = f"{dagdeel(uur)}, sir."
    lijst = problemen(checks)
    if not lijst:
        return f"{groet} Alle systemen zijn operationeel.{_extra()}"
    if len(lijst) == 1:
        zin = lijst[0]
        return f"{groet} Alles draait, op één ding na: {zin}.{_extra()}"
    opsomming = ", ".join(lijst[:-1]) + " en " + lijst[-1]
    return f"{groet} Er zijn {len(lijst)} problemen: {opsomming}.{_extra()}"


# -----------------------------------------------------------------
# Easter eggs
# -----------------------------------------------------------------

# patroon (na _schoon) -> antwoorden; ze wisselen elkaar af.
EASTER_EGGS = [
    (r"ik ben iron\s*man", ("Daar twijfelde ik geen moment aan, sir.",)),
    (r"(?:dank\s*(?:je|u)(?:\s+wel)?|bedankt|thanks|thank\s+you|merci)",
     ("Graag gedaan, sir.", "Altijd tot uw dienst, sir.", "Met genoegen, sir.")),
    (r"(?:ben\s+je\s+(?:daar|er|er\s+nog|wakker)|ben\s+je\s+er\s+nog)",
     ("Altijd, sir.", "Voor u altijd, sir.")),
    (r"(?:goed\s+gedaan|knap\s+gedaan)", ("Ik doe mijn best, sir.",)),
    (r"wat\s+zou\s+ik\s+zonder\s+(?:jou|je|u)\s+(?:moeten\s+)?(?:doen|moeten)",
     ("Daar denk ik liever niet aan, sir.",)),
    (r"(?:wie\s+ben\s+(?:jij|je)|waar\s+staat\s+jarvis\s+voor)",
     ("Just A Rather Very Intelligent System, sir. Tot uw dienst.",)),
    (r"(?:start\s+|activeer\s+)?(?:het\s+)?protocol\s+(?:huisfeest|house\s+party)",
     ("Het huisfeest-protocol vraagt om veertig harnassen, sir. Ik tel er nul.",)),
]
_EIEREN = [(re.compile(rf"^{p}$"), antwoorden) for p, antwoorden in EASTER_EGGS]
_teller = {}


def easter_egg(tekst):
    t = _schoon(tekst)
    if not t:
        return None
    for patroon, antwoorden in _EIEREN:
        if patroon.match(t):
            n = _teller.get(patroon.pattern, 0)
            _teller[patroon.pattern] = n + 1
            return antwoorden[n % len(antwoorden)]
    return None


def voer_uit(tekst):
    """Voor de brain-router: een antwoord, of None."""

    if STATUS_PATROON.match(_schoon(tekst)):
        return statusrapport()
    return easter_egg(tekst)
