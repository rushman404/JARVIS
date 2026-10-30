"""Het dashboardpaneel "Vandaag" (Fase 23, M7).

Eén overzicht voor de iPad: de afspraken van vandaag (met vertrektijd als er
een locatie bij staat), de ongelezen belangrijke mail (afzender + onderwerp)
en de nieuwe Discord-DM's. Elke bron staat los: een fout of een ontbrekende
koppeling laat de andere gewoon staan.

Alleen lezen. Het paneel markeert niets als gelezen: DM's blijven "nieuw"
voor "heb ik nieuwe DM's?" en mail blijft ongelezen in Gmail.
"""

import logging
from datetime import datetime, timedelta

from core import agenda_tijd as tijd

logger = logging.getLogger("jarvis.vandaag")

MAX_AFSPRAKEN = 6
MAX_MAILS = 3
MAX_DMS = 3


def _kort(waarde, maximaal):
    tekst = " ".join(str(waarde or "").split())
    return tekst if len(tekst) <= maximaal else tekst[: maximaal - 1] + "…"


# -----------------------------------------------------------------
# Agenda
# -----------------------------------------------------------------

_GEDEELD = {}


def _reistijden():
    """Eén gedeelde reistijdcache: het paneel ververst elke 2 minuten."""

    if "r" not in _GEDEELD:
        from core.agenda_herinneringen import Reistijden

        _GEDEELD["r"] = Reistijden()
    return _GEDEELD["r"]


def agenda_deel(nu, klant_fn=None, reistijden=None, ingesteld_fn=None):
    from core import agenda_herinneringen, icloud_agenda

    if not (ingesteld_fn or icloud_agenda.is_ingesteld)():
        return {"status": "niet_ingesteld", "afspraken": [], "vertrek": None}
    begin = datetime.combine(nu.date(), datetime.min.time())
    lijst = (klant_fn or icloud_agenda.AgendaKlant)().afspraken(begin, begin + timedelta(days=1))
    afspraken = []
    for a in lijst[:MAX_AFSPRAKEN]:
        afspraken.append({
            "tijd": None if a.get("hele_dag") else tijd.klok(a["start"]),
            "eind": None if a.get("hele_dag") else tijd.klok(a["eind"]),
            "titel": _kort(a.get("titel") or "(zonder titel)", 60),
            "plaats": _kort(a.get("plaats"), 60) or None,
            "hele_dag": bool(a.get("hele_dag")),
            "voorbij": not a.get("hele_dag") and a["eind"] <= nu,
        })
    vertrek = None
    for a in lijst:
        if a.get("hele_dag") or a["start"] <= nu:
            continue
        om, reis = agenda_herinneringen.vertrek(a, reistijden or _reistijden())
        if om is not None and om > nu:
            vertrek = {"titel": _kort(a["titel"], 60), "om": tijd.klok(om), "minuten": reis}
            break
    return {"status": "ok", "afspraken": afspraken, "meer": max(0, len(lijst) - MAX_AFSPRAKEN),
            "vertrek": vertrek}


# -----------------------------------------------------------------
# Mail
# -----------------------------------------------------------------

def mail_deel(klant_fn=None):
    from core import gmail

    klant = (klant_fn or gmail.GmailKlant)()
    if not klant.is_gekoppeld():
        return {"status": "niet_gekoppeld", "aantal": 0, "mails": []}
    belangrijk = gmail.belangrijke_ongelezen(klant)
    return {
        "status": "ok",
        "aantal": len(belangrijk),
        "mails": [{"van": _kort(k["van"], 40), "onderwerp": _kort(k["onderwerp"], 80)}
                  for k in belangrijk[:MAX_MAILS]],
    }


# -----------------------------------------------------------------
# Discord
# -----------------------------------------------------------------

def discord_deel(klant_fn=None, online_fn=None):
    from core import discord_dms

    online = (online_fn or discord_dms._std_online)()
    if online is None:
        return {"status": "niet_gebruikt", "aantal": 0, "dms": []}
    if online is False:
        return {"status": "uit", "aantal": 0, "dms": []}
    dms = (klant_fn or discord_dms.DiscordKlant)().dms()
    if dms is None:
        return {"status": "uit", "aantal": 0, "dms": []}
    nieuw = list(reversed(discord_dms.ongelezen(dms)))  # oudste eerst
    return {
        "status": "ok",
        "aantal": len(nieuw),
        "dms": [{"van": _kort(d["van"], 40), "tekst": _kort(d.get("tekst"), 80)} for d in nieuw[-MAX_DMS:]],
    }


# -----------------------------------------------------------------
# Samen
# -----------------------------------------------------------------

def _veilig(naam, maak, leeg):
    try:
        return maak()
    except Exception:
        logger.warning("Vandaag: %s ophalen mislukte.", naam, exc_info=True)
        return dict(leeg, status="fout")


def overzicht(nu=None, agenda_fn=None, mail_fn=None, discord_fn=None, deadlines_fn=None):
    """Alles voor het paneel; ``*_fn`` zijn voor de tests."""

    nu = nu or datetime.now()

    def _deadlines():
        from core import deadlines

        return deadlines.paneel_deel(nu)

    return {
        "datum": nu.date().isoformat(),
        "agenda": _veilig("agenda", agenda_fn or (lambda: agenda_deel(nu)),
                          {"afspraken": [], "vertrek": None}),
        # Fase 26, M1: deadlines van vandaag en de komende dagen.
        "deadlines": _veilig("deadlines", deadlines_fn or _deadlines, {"deadlines": []}),
        "mail": _veilig("mail", mail_fn or mail_deel, {"aantal": 0, "mails": []}),
        "discord": _veilig("discord", discord_fn or discord_deel, {"aantal": 0, "dms": []}),
    }
