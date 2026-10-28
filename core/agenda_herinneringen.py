"""Herinneringen, reistijd en de dagstart met de agenda (Fase 23, M5).

* :class:`HerinneringPlanner` kijkt elke minuut naar de afspraken van de
  komende uren en meldt ze ``AGENDA_HERINNERING_MINUTEN`` vooraf. Staat er een
  locatie bij, dan rekent hij de reistijd vanaf thuis uit (schatting zonder
  files, via OpenStreetMap) en meldt hij op tijd: "u moet over 15 minuten
  weg". Een afspraakherinnering telt als een wekker: hij klinkt ook in de
  stille modus.
* :func:`dagstart_delen` geeft de regels voor "goedemorgen" / "wat staat er
  vandaag op de planning?": de afspraken van vandaag, wanneer u weg moet en
  de ongelezen belangrijke mail.
"""

import logging
import os
import threading
from datetime import datetime, timedelta

from core import agenda_tijd as tijd
from core import koppelingen

logger = logging.getLogger("jarvis.agenda.herinneringen")

HERINNERD_FILE = os.path.join(koppelingen.MAP, "agenda_herinnerd.json")
VOORUIT_UREN = 6            # zo ver vooruit kijkt de planner
OPHAAL_INTERVAL = 5 * 60    # zo vaak haalt hij de agenda opnieuw op (seconden)
MAX_REISTIJD = 4 * 60       # langere "reistijden" zijn vast een verkeerde plaats


def _config():
    import config

    return config


def _thuis():
    cfg = _config()
    return (cfg.THUIS_ADRES or cfg.WEER_PLAATS or "").strip()


# -----------------------------------------------------------------
# Reistijd
# -----------------------------------------------------------------

def _plaats_kandidaten(plaats):
    """De locatie zoals hij in de agenda staat, en daarna steeds korter.

    Een iPhone zet vaak "Tandartspraktijk De Kies, Markt 1, 4811 Breda,
    Nederland" in de locatie; OpenStreetMap vindt de naam soms niet, het
    adres wel.
    """

    delen = [d.strip() for d in (plaats or "").replace("\n", ",").split(",") if d.strip()]
    uit = []
    for i in range(len(delen)):
        kandidaat = ", ".join(delen[i:])
        if kandidaat and kandidaat not in uit:
            uit.append(kandidaat)
    return uit


class Reistijden:
    """Reistijd vanaf thuis per locatie, met een geheugen per locatie."""

    def __init__(self, reken_fn=None, thuis_fn=None):
        self.reken_fn = reken_fn
        self.thuis_fn = thuis_fn or _thuis
        self._cache = {}

    def minuten(self, plaats):
        """Minuten rijden vanaf thuis, of ``None`` (onbekend of geen locatie)."""

        sleutel = (plaats or "").strip().lower()
        thuis = self.thuis_fn()
        if not sleutel or not thuis:
            return None
        if sleutel in self._cache:
            return self._cache[sleutel]
        reken = self.reken_fn
        if reken is None:
            from actions import reistijden

            reken = reistijden.bereken_reis
        uitkomst = None
        for kandidaat in _plaats_kandidaten(plaats):
            try:
                reis = reken(thuis, kandidaat)
            except Exception:
                logger.debug("Reistijd berekenen mislukte.", exc_info=True)
                reis = None
            if reis and reis.get("ok") and 0 < int(reis.get("minuten") or 0) <= MAX_REISTIJD:
                uitkomst = int(reis["minuten"])
                break
        self._cache[sleutel] = uitkomst
        return uitkomst


def _rond_op(minuten, stap=5):
    """Reistijd naar boven afronden op 5 minuten (het is toch een schatting)."""

    return ((int(minuten) + stap - 1) // stap) * stap


def vertrek(afspraak, reistijden):
    """``(vertrektijd, reisminuten)`` of ``(None, None)``."""

    if afspraak.get("hele_dag") or not afspraak.get("plaats"):
        return None, None
    reis = reistijden.minuten(afspraak["plaats"])
    if not reis:
        return None, None
    reis = _rond_op(reis)
    return afspraak["start"] - timedelta(minutes=reis), reis


# -----------------------------------------------------------------
# Herinneren
# -----------------------------------------------------------------

def _sleutel(afspraak):
    return f"{afspraak.get('uid') or afspraak.get('titel')}|{afspraak['start'].isoformat()}"


def herinnering_tekst(afspraak, nu, vertrek_om=None, reis=None):
    plaats = f" in {afspraak['plaats']}" if afspraak.get("plaats") else ""
    om = tijd.klok(afspraak["start"])
    if vertrek_om is not None:
        over = max(0, int((vertrek_om - nu).total_seconds() // 60))
        wanneer = "nu weg" if over <= 1 else f"over {over} minuten weg (om {tijd.klok(vertrek_om)})"
        return (f"Sir, om {om} heeft u {afspraak['titel']}{plaats}.\n"
                f"Het is ongeveer {reis} minuten rijden; u moet {wanneer}.")
    over = max(1, int((afspraak["start"] - nu).total_seconds() // 60))
    return f"Sir, over {over} minuten: {afspraak['titel']}{plaats} (om {om})."


class HerinneringPlanner:
    """Meldt afspraken kort vooraf, met reistijd als er een locatie bij staat."""

    def __init__(self, meld_fn=None, klant_fn=None, reistijden=None, klok=None, minuten=None,
                 herinnerd_pad=None):
        self.meld_fn = meld_fn
        self.klant_fn = klant_fn
        self.reistijden = reistijden or Reistijden()
        self.klok = klok or datetime.now
        self.minuten = _config().AGENDA_HERINNERING_MINUTEN if minuten is None else minuten
        self.herinnerd_pad = herinnerd_pad or HERINNERD_FILE
        self._afspraken = []
        self._opgehaald = None
        self._stop = threading.Event()
        self._thread = None
        self._fout_gemeld = False

    def _klant(self):
        if self.klant_fn is not None:
            return self.klant_fn()
        from core.icloud_agenda import AgendaKlant

        return AgendaKlant()

    def _haal_op(self, nu):
        if self._opgehaald is not None and (nu - self._opgehaald).total_seconds() < OPHAAL_INTERVAL:
            return self._afspraken
        try:
            lijst = self._klant().afspraken(nu - timedelta(minutes=5), nu + timedelta(hours=VOORUIT_UREN))
            self._fout_gemeld = False
        except koppelingen.KoppelFout as fout:
            if not self._fout_gemeld:
                logger.warning("Agenda ophalen voor herinneringen mislukt: %s", fout)
                self._fout_gemeld = True
            return self._afspraken
        self._afspraken = [a for a in lijst if not a.get("hele_dag")]
        self._opgehaald = nu
        return self._afspraken

    def _herinnerd(self):
        return dict((koppelingen.lees_json(self.herinnerd_pad) or {}).get("gedaan") or {})

    def stap(self):
        """Eén controle; geeft de verstuurde meldingen terug."""

        from core.icloud_agenda import is_ingesteld

        if not self.minuten or not is_ingesteld():
            return []
        nu = self.klok()
        gedaan = self._herinnerd()
        verstuurd = []
        for a in self._haal_op(nu):
            if a["start"] <= nu or _sleutel(a) in gedaan:
                continue
            vertrek_om, reis = vertrek(a, self.reistijden)
            moment = (vertrek_om or a["start"]) - timedelta(minutes=self.minuten)
            if nu < moment:
                continue
            tekst = herinnering_tekst(a, nu, vertrek_om, reis)
            gedaan[_sleutel(a)] = a["start"].isoformat()
            if self.meld_fn is not None:
                try:
                    self.meld_fn(tekst, bron="agenda")
                except Exception:
                    logger.debug("Kon de agendaherinnering niet versturen.", exc_info=True)
            verstuurd.append(tekst)
        if verstuurd:
            # Oude herinneringen (van gisteren en eerder) opruimen.
            grens = (nu - timedelta(days=1)).isoformat()
            koppelingen.schrijf_json(self.herinnerd_pad,
                                     {"gedaan": {k: v for k, v in gedaan.items() if v >= grens}})
        return verstuurd

    def _lus(self):
        while not self._stop.wait(60):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout in de agendaherinneringen.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-agenda", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()


# -----------------------------------------------------------------
# Dagstart
# -----------------------------------------------------------------

def _agenda_delen(nu, klant, reistijden):
    from core import icloud_agenda

    van = datetime.combine(nu.date(), datetime.min.time())
    lijst = klant.afspraken(van, van + timedelta(days=1))
    if not lijst:
        return ["Geen afspraken vandaag."]
    regels = ["1 afspraak vandaag:" if len(lijst) == 1 else f"{len(lijst)} afspraken vandaag:"]
    regels += [icloud_agenda._regel(a) for a in lijst]
    for a in lijst:
        if a.get("hele_dag") or a["start"] <= nu:
            continue
        vertrek_om, reis = vertrek(a, reistijden)
        if vertrek_om is not None and vertrek_om > nu:
            regels.append(f"Vertrek voor {a['titel']} om {tijd.klok(vertrek_om)} ({reis} minuten rijden).")
            break
    return regels


def _mail_delen(klant):
    """Alleen als er belangrijke mail is; "geen mail" is geen nieuws."""

    from core import gmail

    koppen = [klant.kop(i) for i in klant.zoek(gmail.Q_ONGELEZEN, maximaal=10)]
    belangrijk = [k for k in koppen if gmail.is_belangrijk(k)]
    if not belangrijk:
        return []
    if len(belangrijk) == 1:
        k = belangrijk[0]
        return [gmail._punt(f"1 belangrijke mail, van {k['van']}: {k['onderwerp']}")]
    regels = [f"{len(belangrijk)} belangrijke mails:"]
    return regels + [gmail._regel(k) for k in belangrijk[:gmail.MAX_NOEMEN]]


def dagstart_delen(nu=None, agenda_fn=None, gmail_fn=None, reistijden=None):
    """Extra regels voor de dagstart; leeg als agenda en Gmail niet gekoppeld zijn.

    Een fout in de ene bron laat de andere gewoon staan.
    """

    nu = nu or datetime.now()
    regels = []
    try:
        from core import icloud_agenda

        if icloud_agenda.is_ingesteld():
            klant = (agenda_fn or icloud_agenda.AgendaKlant)()
            regels += _agenda_delen(nu, klant, reistijden or Reistijden())
    except Exception:
        logger.warning("Agenda voor de dagstart ophalen mislukte.", exc_info=True)
        regels.append("Uw agenda kon ik nu niet bereiken.")
    try:
        from core import gmail

        klant = (gmail_fn or gmail.GmailKlant)()
        if klant.is_gekoppeld():
            regels += _mail_delen(klant)
    except Exception:
        logger.warning("Mail voor de dagstart ophalen mislukte.", exc_info=True)
        regels.append("Uw mail kon ik nu niet bereiken.")
    return regels
