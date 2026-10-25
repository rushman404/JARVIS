"""Proactieve engine (Fase 16A — proactieve JARVIS).

De engine draait als achtergrondthread en controleert elke tick of er
iets te melden valt: timers die afgelopen zijn, regels uit
``config/proactive_rules.json`` (tijd, interval, statuswijziging) en
overgangen van de nachtmodus.

Ontwerpregels
-------------
* **Los van de hoofdlus.** ``main.py`` blijft de blokkerende wake-word-
  lus; de engine levert meldingen aan via ``Meldingswachtrij``. De
  brain kan de status beïnvloeden met ``set_in_gesprek()`` zodat JARVIS
  nooit midden in een gesprek uitvalt.
* **Deterministisch testbaar.** De klok (``now_fn``) en de leverancier
  van meldingen zijn injecteerbaar; tests roepen ``tick()`` direct aan
  zonder te slapen.
* **Nooit crashen.** Elke regel-check zit in zijn eigen ``try/except``:
  een slechte regel logt een waarschuwing en wordt overgeslagen.
* **Meldingen alleen met stilte-respect.** In de nachtmodus spreekt de
  engine niets uit; meldingen blijven in de wachtrij (tot hun TTL) en
  worden gelogd.
"""

import itertools
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

from config import (
    NACHTMODUS_START,
    NACHTMODUS_EIND,
    NACHTMODUS_VOLUME,
    DAGVOLUME,
    PROACTIVE_TICK_SECONDEN,
    AUTOSLAAP_MINUTEN,
)

logger = logging.getLogger(__name__)

RULES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "proactive_rules.json",
)

# Standaard-TTL voor een proactieve melding (seconden). Lukt het een
# melding niet om binnen dit venster geleverd te worden (bv. JARVIS was
# in gesprek), dan vervalt hij: te late meldingen worden weggegooid.
DEFAULT_MELDING_TTL = 120

# Gebruikersmeldingen (timers en wekkers) blijven maximaal 30 minuten
# in de wachtrij staan. Ze mogen niet stil verloren gaan, maar een half
# uur te laat melden is ook niet meer zinvol.
GEBRUIKER_MELDING_TTL = 30 * 60

# Binnen zoveel seconden na het aflopen heet een timer "afgelopen"; later
# (JARVIS stond uit of was bezig) noemt de melding het tijdstip.
TIMER_OP_TIJD_SECONDEN = 60

# Standaard-dedupe voor statuswijzigingen (seconden).
STATUS_DEDUPE_SECONDEN = 300

# Maximaal aantal meldingen in de wachtrij (voorkomt geheugenproblemen
# bij een storing).
MAX_WACHTRIJ = 50

# Standaard-cooldown (seconden) voor het 'actief'-triggertype: hoe lang
# een zorg-regel niet opnieuw mag afgaan na een pauze-herinnering.
ACTIEF_HERHAAL_SECONDEN = 3600

# Hoeveel later een 'tijd'-regel nog mag afgaan. Start JARVIS om 18:34,
# dan hoort "tijd om te eten" (18:30) nog te komen. Start hij om 20:39,
# dan niet meer: zonder deze grens meldde hij bij elke start alle
# tijd-regels van de afgelopen 12 uur ("tijd voor de lunch" om 20:39).
TIJD_GRACE = timedelta(minutes=5)

# Stille modus (handmatig aan/uit gezet door de gebruiker); dit is
# níét de nachtmodus (die is tijdgestuurd).
_quiet_aan = threading.Event()

# Nachtmodus override: "auto", "aan", "uit". Een handmatige stand geldt
# niet eeuwig: hij verloopt bij de eerstvolgende overgang van de
# automatische tijden (zie ``set_nachtmodus``).
_nachtmodstand = "auto"
_nachtmodus_verloopt = None  # epoch-seconden, of None als er geen geldt

# "In gesprek"-vlag: gezet door main.py rond een wake-word-sessie, zodat
# de engine weet dat hij JARVIS niet mag storen.
_in_gesprek = threading.Event()

# Wachttijd waarna een blijven hangen gespreksvlag vervalt (seconden).
# Zonder watchdog zou een vastgelopen opdracht de vlag eeuwig aan laten
# staan en zouden gebruikersmeldingen nooit meer worden uitgesproken.
GESPREK_WATCHDOG_SECONDEN = 10 * 60

# Oplopende teller voor melding-id's (uniek binnen dit proces), zodat het
# dashboard elke melding als eigen kaartje kan tonen en gelezen markeren.
_MELDING_ID = itertools.count(1)


def set_quiet(aan):
    """Zet de handmatige stille modus aan of uit."""

    if aan:
        _quiet_aan.set()
    else:
        _quiet_aan.clear()


def is_quiet():
    """True als de handmatige stille modus aan staat."""

    return _quiet_aan.is_set()


def set_in_gesprek(aan):
    """Zet de 'in gesprek'-vlag (main.py rond een wake-word-sessie)."""

    if aan:
        _in_gesprek.set()
    else:
        _in_gesprek.clear()


def is_in_gesprek():
    """True als JARVIS midden in een wake-word-sessie zit."""

    return _in_gesprek.is_set()


# =============================================================
# Slaapstand (Fase 19, M4)
# =============================================================
# Eén slaapstand voor "ga slapen" (reden "commando") en de auto-slaap na
# inactiviteit (reden "auto"). Slapend:
#   * reageert JARVIS alleen op het wake word;
#   * zegt hij niets uit zichzelf, behalve timers en wekkers (hij zet de
#     stille modus aan en zet bij het wakker worden de vorige stand terug);
#   * kan het AI-model uit het geheugen (zie bij_slaap / bij_wakker).
# Een commando-slaap gaat alleen weg met het wake word; de auto-slaap ook
# bij activiteit (een commando of pc-gebruik).

SLAAP_COMMANDO = "commando"
SLAAP_AUTO = "auto"

_slaap_lock = threading.Lock()
_slaap = None  # {"sinds": epoch, "reden": ..., "quiet_was": bool}
_slaap_luisteraars = []
_wakker_luisteraars = []


def bij_slaap(fn):
    """Laat ``fn()`` aanroepen zodra JARVIS gaat slapen."""

    _slaap_luisteraars.append(fn)


def bij_wakker(fn):
    """Laat ``fn()`` aanroepen zodra JARVIS wakker wordt."""

    _wakker_luisteraars.append(fn)


def _roep_aan(luisteraars):
    for fn in list(luisteraars):
        try:
            fn()
        except Exception:
            logger.debug("Slaap-luisteraar gaf een fout.", exc_info=True)


def ga_slapen(reden=SLAAP_COMMANDO, nu=None):
    """Zet JARVIS in de slaapstand. True als hij nu pas ging slapen.

    Slaapt hij al door de auto-slaap en vraagt u "ga slapen", dan wordt
    het een commando-slaap (die alleen het wake word opheft).
    """

    global _slaap
    with _slaap_lock:
        if _slaap is not None:
            if reden == SLAAP_COMMANDO:
                _slaap["reden"] = SLAAP_COMMANDO
            return False
        _slaap = {
            "sinds": time.time() if nu is None else nu,
            "reden": reden,
            "quiet_was": is_quiet(),
        }
        set_quiet(True)
    logger.info("JARVIS gaat slapen (%s).", reden)
    _roep_aan(_slaap_luisteraars)
    return True


def word_wakker():
    """Haalt JARVIS uit de slaapstand. True als hij sliep."""

    global _slaap
    with _slaap_lock:
        if _slaap is None:
            return False
        quiet_was = _slaap.get("quiet_was", False)
        _slaap = None
        set_quiet(quiet_was)
    logger.info("JARVIS is wakker.")
    _roep_aan(_wakker_luisteraars)
    return True


def slaapt():
    """True als JARVIS in de slaapstand staat."""

    return _slaap is not None


def slaap_reden():
    """``"commando"``, ``"auto"`` of ``None`` (wakker)."""

    slaap = _slaap
    return slaap.get("reden") if slaap else None


def _reset_slaap():
    """Alleen voor tests: slaapstand en luisteraars wissen."""

    global _slaap
    with _slaap_lock:
        if _slaap is not None:
            set_quiet(_slaap.get("quiet_was", False))
        _slaap = None
    _slaap_luisteraars.clear()
    _wakker_luisteraars.clear()


# =============================================================
# Nachtmodus
# =============================================================

def set_nachtmodus(stand="auto", nu=None):
    """Zet de nachtmodus-stand: "auto", "aan" of "uit".

    Een handmatige stand ("aan"/"uit") geldt tot de eerstvolgende
    overgang van de automatische tijden: "uit" gezet om 23:30 geldt tot
    07:00, "aan" gezet om 14:00 geldt tot 07:00 de volgende ochtend.
    Daarna valt de stand terug naar "auto". Zo blijft een override niet
    dagenlang staan op een pc die altijd aan staat.
    """

    global _nachtmodstand, _nachtmodus_verloopt

    if stand not in ("auto", "aan", "uit"):
        stand = "auto"

    _nachtmodstand = stand
    _nachtmodus_verloopt = (
        _volgende_nachtmodus_overgang(nu) if stand != "auto" else None
    )


def _volgende_nachtmodus_overgang(now=None):
    """Epoch-seconden waarop de automatische nachtmodus van stand wisselt.

    Dat is het eerstvolgende tijdstip (07:00 of 23:00) dat het
    automatische venster in- of uitgaat. Geeft None als er geen
    bruikbare overgang te bepalen is.
    """

    if now is None:
        now = datetime.now()
    elif isinstance(now, (int, float)):
        now = datetime.fromtimestamp(now)

    overgangen = []
    for uur in (NACHTMODUS_EIND, NACHTMODUS_START):
        if not isinstance(uur, int) or not (0 <= uur <= 23):
            continue
        kandidaat = now.replace(
            hour=uur, minute=0, second=0, microsecond=0
        )
        if kandidaat.timestamp() <= now.timestamp():
            kandidaat = kandidaat + timedelta(days=1)
        overgangen.append(kandidaat)

    if not overgangen:
        return None
    return min(overgangen).timestamp()


def get_nachtmodus_stand(nu=None):
    """Geeft de actuele nachtmodus-stand terug ("auto", "aan" of "uit").

    Een verlopen handmatige override wordt hier meteen naar "auto"
    teruggezet, zodat de stand altijd de werkelijkheid weerspiegelt.
    """

    global _nachtmodstand, _nachtmodus_verloopt

    if _nachtmodus_verloopt is not None:
        if nu is None:
            nu = datetime.now().timestamp()
        if nu >= _nachtmodus_verloopt:
            _nachtmodstand = "auto"
            _nachtmodus_verloopt = None

    return _nachtmodstand


def get_nachtmodus_verloopt():
    """Epoch-seconden waarop de handmatige stand verloopt (of None)."""

    return _nachtmodus_verloopt


def is_nachtmodus(now=None, start=None, eind=None):
    """True als nachtmodus geldt. Bij override wordt die gevolgd.

    ``start`` en ``eind`` zijn uren (0-23); het venster mag door
    middernacht heen lopen. Een verlopen override valt terug op de
    automatische tijden.
    """

    if now is None:
        now = datetime.now()
    elif isinstance(now, (int, float)):
        now = datetime.fromtimestamp(now)

    stand = get_nachtmodus_stand(nu=now.timestamp())
    if stand == "aan":
        return True
    if stand == "uit":
        return False

    if start is None:
        start = NACHTMODUS_START
    if eind is None:
        eind = NACHTMODUS_EIND

    if start == eind:
        return False

    uur = now.hour + now.minute / 60.0

    if start < eind:
        return start <= uur < eind
    # Venster loopt door middernacht heen (bijv. 23 -> 7)
    return uur >= start or uur < eind


# =============================================================
# Meldingen (wachtrij met TTL)
# =============================================================

class Melding:
    """Eén proactieve melding.

    ``id`` is uniek binnen dit proces en ``aangemaakt_op`` is het
    tijdstip (epoch) waarop de melding ontstond; het dashboard toont
    daarmee tijd + kaartje (Fase 18). ``bron`` is de soort melding.
    """

    __slots__ = ("id", "tekst", "verloopt_op", "bron", "prioriteit",
                 "aangemaakt_op")

    def __init__(self, tekst, ttl=DEFAULT_MELDING_TTL, bron="regel",
                 nu=None, prioriteit=None):
        self.id = next(_MELDING_ID)
        self.tekst = tekst
        self.bron = bron
        if nu is None:
            nu = time.time()
        self.aangemaakt_op = nu
        # Meldingen van gebruikerstimers en wekkers (prioriteit
        # "gebruiker") mogen nooit stil verloren gaan: ze blijven tot
        # maximaal 30 minuten in de wachtrij staan.
        if prioriteit is None:
            prioriteit = "gebruiker" if bron == "timer" else "systeem"
        self.prioriteit = prioriteit
        if prioriteit == "gebruiker":
            ttl = GEBRUIKER_MELDING_TTL
        # ttl=None betekent: geen TTL (blijft staan tot geleverd).
        # ``nu`` is de basis-tijd voor de TTL; tests geven hier een
        # vaste epoch-tijd mee zodat verlopen deterministisch is.
        if ttl is None:
            self.verloopt_op = None
        else:
            self.verloopt_op = nu + ttl

    def verlopen(self, nu=None):
        if self.verloopt_op is None:
            return False
        if nu is None:
            nu = time.time()
        return nu >= self.verloopt_op


class Meldingswachtrij:
    """Thread-safe wachtrij van proactieve meldingen met TTL.

    De engine stopt meldingen hierin; ``neem_alle()`` levert ze (in de
    juiste volgorde) zolang JARVIS niet in gesprek is. Verlopen
    meldingen worden weggegooid: te laat melden is irritanter dan
    niet melden.
    """

    def __init__(self, max_wachtrij=MAX_WACHTRIJ):
        self._lock = threading.Lock()
        self._items = []
        self._max = max_wachtrij

    def stop(self, melding):
        """Voegt een melding toe; geeft True bij succes."""

        if not melding or not getattr(melding, "tekst", None):
            return False

        with self._lock:
            # Dubbele meldingen (zelfde tekst) overslaan.
            if any(m.tekst == melding.tekst for m in self._items):
                return False
            if len(self._items) >= self._max:
                logger.warning(
                    "Meldingswachtrij zit vol; melding '%s' overgeslagen.",
                    melding.tekst,
                )
                return False
            self._items.append(melding)
        return True

    def verlopen_weggooien(self, nu=None):
        """Gooit verlopen meldingen weg; geeft het aantal weggegooiden."""

        with self._lock:
            voor = len(self._items)
            self._items = [m for m in self._items if not m.verlopen(nu)]
            return voor - len(self._items)

    def neem_alle(self):
        """Neemt alle meldingen over (leegt de wachtrij)."""

        with self._lock:
            items, self._items = self._items, []
        return items

    def lengte(self):
        with self._lock:
            return len(self._items)


# =============================================================
# Regels (config/proactive_rules.json)
# =============================================================

def _laad_regels(pad=RULES_FILE):
    """Laadt de proactieve regels; corruptie => lege lijst."""

    try:
        with open(pad, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("regels"), list):
                return [r for r in data["regels"] if isinstance(r, dict)]
    except (OSError, json.JSONDecodeError):
        pass

    try:
        bak = pad + ".bak"
        if os.path.exists(bak):
            with open(bak, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("regels"), list):
                    return [r for r in data["regels"] if isinstance(r, dict)]
    except Exception:
        pass

    return []


def _parse_tijd(tijd):
    """Zet 'HH:MM' om in (uur, minuut); geeft None bij ongeldige invoer."""

    try:
        uur, minuut = str(tijd).split(":")
        h, m = int(uur), int(minuut)
    except (ValueError, TypeError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return (h, m)


# =============================================================
# Engine
# =============================================================

class ProactiveEngine:
    """Achtergrond-thread die regels, timers en de nachtmodus bewaakt.

    Parameters zijn injecteerbaar voor tests:

    * ``now_fn``          — geeft de huidige ``datetime`` terug
    * ``time_fn``         — geeft de huidige epoch-tijd (float) terug;
                            wordt overal gebruikt waar ``time.time()``
                            stond (TTL's, interval/status-dedupe) zodat
                            tests de klok volledig kunnen sturen
    * ``store``           — TimerStore (timers)
    * ``rules_pad``       — pad naar het regelbestand
    * ``tick_seconden``   — hoe vaak de engine controleert (thread)
    * ``volume_fn``       — aanroep met (volume) voor nacht/dag-volume
    * ``ha_check_fn``     — aanroep zonder argumenten, geeft True als
                            Home Assistant bereikbaar is, False als niet
                            bereikbaar, None als onbekend/niet geconfigureerd
    * ``schijf_check_fn`` — aanroep zonder argumenten, geeft het vrije
                            schijf-percentage (float) of None
    * ``in_gesprek_fn``   — aanroep zonder argumenten; True als JARVIS
                            midden in een gesprek zit (dan niet storen)
    * ``actief_check_fn`` — aanroep zonder argumenten; True als de pc
                            recent is gebruikt, False als niet, None als
                            onbekend. Wordt gebruikt voor de auto-slaap en
                            het 'actief'-triggertype (zorg-coaching)
    * ``inactiviteit_seconden`` — na zoveel seconden zonder activiteit
                            gaat JARVIS automatisch in de stille modus
                            (auto-slaap); 0 of None = uit
    * ``lever_fn``        — aanroep met (tekst) om een melding daadwerkelijk
                            te versturen (spraak + toast); standaard None
                            = alleen wachtrij (tests leveren zelf af)

    Meldingen worden niet direct uitgesproken maar in ``wachtrij``
    gestopt; ``tick()`` levert ze af met ``lever_fn`` zolang JARVIS niet
    in gesprek is.
    """

    def __init__(self, store=None, now_fn=None, rules_pad=RULES_FILE,
                 tick_seconden=None, volume_fn=None, ha_check_fn=None,
                 schijf_check_fn=None, in_gesprek_fn=None, lever_fn=None,
                 time_fn=None, actief_check_fn=None,
                 inactiviteit_seconden=None, status_checks=None):

        self.store = store
        self.now_fn = now_fn if now_fn is not None else datetime.now
        self.time_fn = time_fn if time_fn is not None else time.time
        self.rules_pad = rules_pad
        self.tick_seconden = (
            tick_seconden if tick_seconden is not None
            else PROACTIVE_TICK_SECONDEN
        )
        self.volume_fn = volume_fn
        self.ha_check_fn = ha_check_fn
        self.schijf_check_fn = schijf_check_fn
        # Extra statusbronnen (Fase 19, M6): {bron: fn} met fn() -> True
        # (online), False (offline) of None (niet van toepassing). Zie
        # beheer/verbinding.py voor game_pc, ollama en internet.
        self.status_checks = dict(status_checks or {})
        self.in_gesprek_fn = in_gesprek_fn
        self.lever_fn = lever_fn
        self.actief_check_fn = actief_check_fn

        if inactiviteit_seconden is None:
            inactiviteit_seconden = AUTOSLAAP_MINUTEN * 60
        self.inactiviteit_seconden = inactiviteit_seconden

        self.wachtrij = Meldingswachtrij()

        self._regels = _laad_regels(rules_pad)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        # Laatst bekende status per regel-id (voor statuswijzigingen).
        self._status = {}
        # Laatst afgevuurde 'tijd'-regel per regel-id (datumstring).
        self._laatste_tijd = {}
        # Laatst afgevuurde 'interval'-regel per regel-id (epoch).
        self._laatste_interval = {}

        # Nachtmodus-overgang bijhouden zodat het volume maar één keer
        # wordt aangepast.
        self._vorige_nachtmodus = None

        # Activiteit / auto-slaap: wanneer was er voor het laatst een
        # commando of pc-gebruik? Bij te lange stilte gaat JARVIS in de
        # slaapstand met reden "auto", zodat de eerstvolgende activiteit
        # hem weer wakker maakt (zie ga_slapen / word_wakker).
        self._laatste_activiteit = None

        # 'actief'-trigger: sinds wanneer is de pc aaneengesloten in
        # gebruik, en wanneer ging een zorg-regel voor het laatst af.
        self._actief_sinds = None
        self._laatste_actief = {}

        # Watchdog op de gespreksvlag: sinds wanneer staat die aan?
        self._gesprek_sinds = None

        # Waarnemer van nieuwe meldingen (het dashboard). Die ziet elke
        # melding zonder de wachtrij leeg te halen; zie set_melding_observer.
        self._melding_observer = None

        # Wekker voor de achtergrond-thread: een nieuwe timer maakt de
        # engine meteen wakker, zodat hij precies op tijd afloopt.
        self._wek = threading.Event()
        if store is not None and hasattr(store, "bij_wijziging"):
            store.bij_wijziging(self._wek.set)

    # ----- waarnemer (dashboard) -----

    def set_melding_observer(self, fn):
        """Laat ``fn(melding)`` elke nieuwe melding zien (of None: uit).

        De wachtrij blijft daarbij ongemoeid: ``neem_meldingen()`` levert
        nog steeds alles af. Een fout in de waarnemer stopt de engine niet.
        """

        self._melding_observer = fn

    # ----- activiteit / auto-slaap -----

    def is_auto_slaap(self):
        """True als JARVIS door inactiviteit automatisch slaapt."""

        return slaap_reden() == SLAAP_AUTO

    def meld_activiteit(self, nu_ts=None):
        """Registreert gebruikersactiviteit (commando of pc-gebruik).

        Zet de inactiviteitsklok terug en haalt een eventuele auto-slaap
        er weer af (maar laat een handmatig gezette stille modus staan:
        wij zetten alleen uit wat wij zelf aanzetten).
        """

        if nu_ts is None:
            nu_ts = self.time_fn()
        self._laatste_activiteit = nu_ts

        if slaap_reden() == SLAAP_AUTO:
            # Alleen de auto-slaap wijkt voor activiteit; "ga slapen"
            # heft alleen het wake word op.
            word_wakker()
            logger.info("Activiteit: auto-slaap uitgezet, JARVIS is weer wakker.")

    def _werk_activiteit_bij(self, nu_ts):
        """Leest pc-activiteit uit en werkt de inactiviteitsklok bij."""

        if self._laatste_activiteit is None:
            self._laatste_activiteit = nu_ts

        if self.actief_check_fn is None:
            self._actief_sinds = None
            return

        try:
            actief = self.actief_check_fn()
        except Exception:
            logger.debug("Kon de pc-activiteit niet bepalen.", exc_info=True)
            actief = None

        if actief:
            if self._actief_sinds is None:
                self._actief_sinds = nu_ts
            self.meld_activiteit(nu_ts)
        else:
            self._actief_sinds = None

    def _check_auto_slaap(self, nu_ts):
        """Zet JARVIS stil als er te lang geen activiteit was.

        Auto-slaap heeft een activiteitsbron nodig (``actief_check_fn``):
        zonder pc-meting weten we niet of de gebruiker nog aan het werk is
        en zou JARVIS onterecht stilvallen. Zonder bron blijft hij wakker.
        """

        if slaapt() or not self.inactiviteit_seconden:
            return
        if self.actief_check_fn is None:
            return
        # Een handmatig gezette stille modus laten we met rust.
        if is_quiet():
            return
        if self._laatste_activiteit is None:
            return
        if nu_ts - self._laatste_activiteit >= self.inactiviteit_seconden:
            ga_slapen(SLAAP_AUTO, nu=nu_ts)
            logger.info(
                "Geen activiteit gedurende %d seconden: auto-slaap aan.",
                self.inactiviteit_seconden,
            )

    # ----- regels -----

    def herlaad_regels(self):
        """Leest het regelbestand opnieuw in (bijv. na een wijziging)."""
        with self._lock:
            self._regels = _laad_regels(self.rules_pad)

    # ----- melding -----

    def meld(self, tekst, bron="systeem"):
        """Zet een systeemmelding in de wachtrij (bijv. na een herstart).

        Net als andere systeemmeldingen: in de nacht- of stille modus wacht
        hij; het dashboard ziet hem meteen.
        """

        self._verstuur(tekst, bron=bron)

    def _verstuur(self, tekst, bron="regel", nu_ts=None):
        """Stopt een melding in de wachtrij."""

        if nu_ts is None:
            nu_ts = self.time_fn()

        prioriteit = "gebruiker" if bron == "timer" else "systeem"
        melding = Melding(
            tekst, bron=bron, nu=nu_ts, prioriteit=prioriteit
        )

        if prioriteit == "gebruiker":
            # Timers en wekkers worden altijd uitgesproken, ook in de
            # nachtmodus, de stille modus en de auto-slaap.
            logger.info("Gebruikersmelding (timer/wekker): %s", tekst)
        elif is_nachtmodus(self.now_fn()):
            logger.info(
                "Nachtmodus: systeemmelding bewaard (niet uitgesproken): %s",
                tekst,
            )
        elif is_quiet():
            logger.info(
                "Stille modus: systeemmelding bewaard (niet uitgesproken): %s",
                tekst,
            )

        if self.wachtrij.stop(melding):
            self._meld_aan_observer(melding)

    def _meld_aan_observer(self, melding):
        observer = self._melding_observer
        if observer is None:
            return
        try:
            observer(melding)
        except Exception:
            logger.debug("Meldingwaarnemer gaf een fout.", exc_info=True)

    def _meld_timer(self, timer, nu_ts):
        """Meldt een verlopen timer, ook als JARVIS uit stond.

        Timers die langer dan 24 uur geleden afliepen, worden zonder
        melding verwijderd (ze zijn niet meer relevant). Bij een
        (verlate) melding noemt JARVIS het tijdstip waarop de timer had
        moeten afgaan.
        """

        try:
            af_loopt_op = float(timer.get("af_loopt_op"))
        except (TypeError, ValueError):
            return

        if nu_ts - af_loopt_op > 24 * 3600:
            logger.info(
                "Timer '%s' is ouder dan 24 uur; zonder melding verwijderd.",
                timer.get("naam", "herinnering"),
            )
            return

        naam = timer.get("naam", "herinnering")
        tijd = datetime.fromtimestamp(af_loopt_op).strftime("%H:%M")
        if nu_ts - af_loopt_op <= TIMER_OP_TIJD_SECONDEN:
            # Op tijd: in de "nu"-vorm (een wekker noemt zo ook de tijd).
            tekst = f"Sir, het is {tijd}: uw timer '{naam}' is afgelopen."
        else:
            # Echt te laat (bijv. JARVIS stond uit): dat zeggen we erbij.
            tekst = f"Sir, uw timer '{naam}' is om {tijd} afgegaan."
        self._verstuur(tekst, bron="timer", nu_ts=nu_ts)

    # ----- tick -----

    def tick(self):
        """Eén controleslag. Geeft het aantal afgeleverde meldingen terug.

        Dit is de kern die de achtergrond-thread elke ``tick_seconden``
        aanroept; tests roepen hem direct aan met een fake klok.
        """

        nu_dt = self.now_fn()
        nu_ts = self.time_fn()

        # 1. Verlopen meldingen weggooien (te laat = afmelden).
        self.wachtrij.verlopen_weggooien(nu_ts)

        # 2. Nachtmodus-volume bijwerken bij overgang.
        self._pas_volume_aan(nu_dt)

        # 2b. Activiteit bijwerken (pc-gebruik) en auto-slaap bewaken.
        self._werk_activiteit_bij(nu_ts)
        self._check_auto_slaap(nu_ts)

        # 2c. Watchdog: hangt de gespreksvlag te lang, zet hem zelf uit.
        self._check_gespreksvlag_watchdog(nu_ts)

        # 3. Regels evalueren.
        for regel in list(self._regels):
            try:
                self._evalueer_regel(regel, nu_dt, nu_ts)
            except Exception:
                logger.exception(
                    "Fout bij het evalueren van regel %s",
                    regel.get("id", "?"),
                )

        # 4. Verlopen timers afhandelen.
        if self.store is not None:
            try:
                for timer in self.store.verlopen_timers():
                    self._meld_timer(timer, nu_ts)
            except Exception:
                logger.exception("Fout bij het afhandelen van timers.")

        # 5. Meldingen afleveren als JARVIS niet in gesprek is.
        return self._lever_op()

    def _check_gespreksvlag_watchdog(self, nu_ts):
        """Zet een blijven hangen gespreksvlag na verloop van tijd uit.

        Een vastgelopen opdracht mag JARVIS niet oneindig laten zwijgen:
        blijft de vlag langer dan ``GESPREK_WATCHDOG_SECONDEN`` aan zonder
        dat er iets nieuws gebeurt, dan zetten we hem zelf uit (met een
        waarschuwing in het log). Daarna worden wachtende meldingen weer
        afgeleverd; gebruikersmeldingen wachten sowieso nooit langer dan
        hun TTL van 30 minuten.
        """

        watchdog = GESPREK_WATCHDOG_SECONDEN
        if not watchdog:
            return
        if not self.in_gesprek():
            self._gesprek_sinds = None
            return
        if self._gesprek_sinds is None:
            self._gesprek_sinds = nu_ts
            return
        if (nu_ts - self._gesprek_sinds) >= watchdog:
            logger.warning(
                "Gespreksvlag stond %d seconden aan zonder nieuwe "
                "commando's; ik zet hem zelf uit.",
                int(nu_ts - self._gesprek_sinds),
            )
            set_in_gesprek(False)
            self._gesprek_sinds = None

    def _pas_volume_aan(self, nu_dt):
        if self.volume_fn is None:
            return
        nacht = is_nachtmodus(nu_dt)
        if nacht == self._vorige_nachtmodus:
            return
        self._vorige_nachtmodus = nacht
        try:
            self.volume_fn(NACHTMODUS_VOLUME if nacht else DAGVOLUME)
        except Exception:
            logger.exception("Kon het spreekvolume niet aanpassen.")

    def _evalueer_regel(self, regel, nu_dt, nu_ts):
        if not regel.get("actief", True):
            return

        trigger = regel.get("trigger") or {}
        soort = str(trigger.get("type", "")).lower()
        tekst = regel.get("melding") or ""
        if not tekst:
            return

        # Voorwaarden
        voorwaarden = regel.get("voorwaarden") or {}
        if voorwaarden.get("nachtmodus", False) and is_nachtmodus(nu_dt):
            # Regel mag niet in de nachtmodus; wacht tot overdag.
            return

        regel_id = str(regel.get("id", tekst))

        if soort == "tijd":
            if self._check_tijd(regel_id, trigger, nu_dt):
                self._verstuur(tekst, bron=regel_id, nu_ts=nu_ts)

        elif soort == "interval":
            if self._check_interval(regel_id, trigger, nu_ts):
                self._verstuur(tekst, bron=regel_id, nu_ts=nu_ts)

        elif soort == "statuswijziging":
            if self._check_statuswijziging(regel_id, trigger, nu_ts):
                self._verstuur(tekst, bron=regel_id, nu_ts=nu_ts)

        elif soort == "actief":
            if self._check_actief(regel_id, trigger, nu_ts):
                self._verstuur(tekst, bron=regel_id, nu_ts=nu_ts)

        else:
            logger.warning(
                "Onbekend trigger-type '%s' in regel %s; overgeslagen.",
                soort, regel_id,
            )

    def _check_tijd(self, regel_id, trigger, nu_dt):
        """True als de regel nu zou moeten afgaan (dagelijks, één keer)."""

        doel = _parse_tijd(trigger.get("tijd"))
        if doel is None:
            logger.warning(
                "Ongeldige tijd '%s' in regel %s.",
                trigger.get("tijd"), regel_id,
            )
            return False

        vandaag = nu_dt.date().isoformat()
        if self._laatste_tijd.get(regel_id) == vandaag:
            return False

        doel_h, doel_m = doel
        doel_moment = nu_dt.replace(
            hour=doel_h, minute=doel_m, second=0, microsecond=0
        )

        # Nog niet aan de beurt.
        if nu_dt < doel_moment:
            return False

        # Te laat: de melding is niet meer zinvol (JARVIS startte uren
        # later). De regel is voor vandaag afgehandeld, zodat hij niet bij
        # elke tick opnieuw wordt bekeken.
        if nu_dt > doel_moment + TIJD_GRACE:
            self._laatste_tijd[regel_id] = vandaag
            return False

        self._laatste_tijd[regel_id] = vandaag
        return True

    def _check_interval(self, regel_id, trigger, nu_ts):
        """True als het interval sinds het laatst afgaan voorbij is."""

        try:
            seconden = int(trigger.get("seconden", 0))
        except (TypeError, ValueError):
            seconden = 0
        if seconden <= 0:
            logger.warning(
                "Ongeldig interval in regel %s; overgeslagen.", regel_id
            )
            return False

        laatste = self._laatste_interval.get(regel_id)
        if laatste is None:
            self._laatste_interval[regel_id] = nu_ts
            return True
        if (nu_ts - laatste) < seconden:
            return False
        self._laatste_interval[regel_id] = nu_ts
        return True

    def _check_statuswijziging(self, regel_id, trigger, nu_ts):
        """True als de gecontroleerde status is veranderd.

        Ondersteunde bronnen:
        * ``bron: "ha"``      — Home Assistant bereikbaarheid
        * ``bron: "schijf"``  — vrij schijf-percentage onder drempel
        * elke bron uit ``status_checks`` (bijv. ``"game_pc"``,
          ``"ollama"``, ``"internet"``) — bereikbaar of niet

        Optioneel ``verwacht`` (bool): meld alleen als de status naar
        díe waarde veranderd is (bijv. alleen bij offline gaan). Zonder
        ``verwacht`` meldt de regel bij elke verandering.

        De check wordt niet vaker dan ``herhaal_seconden`` gedaan
        (standaard STATUS_DEDUPE_SECONDEN) om niet elke tick te
        raadplegen; statuswijzigingen mogen dus tot die tijd later
        gemeld worden.
        """

        bron = str(trigger.get("bron", "")).lower()
        herhaal = trigger.get("herhaal_seconden")
        try:
            herhaal = int(herhaal) if herhaal is not None else STATUS_DEDUPE_SECONDEN
        except (TypeError, ValueError):
            herhaal = STATUS_DEDUPE_SECONDEN

        laatste = self._status.get(regel_id)
        if laatste is not None and (nu_ts - laatste["ts"]) < herhaal:
            return False

        if bron == "ha":
            if self.ha_check_fn is None:
                return False
            try:
                bereikbaar = self.ha_check_fn()
            except Exception:
                logger.exception("HA-check mislukt voor regel %s.", regel_id)
                return False
            if bereikbaar is None:
                return False
        elif bron == "schijf":
            if self.schijf_check_fn is None:
                return False
            try:
                vrij = self.schijf_check_fn()
            except Exception:
                logger.exception("Schijf-check mislukt voor regel %s.", regel_id)
                return False
            if vrij is None:
                return False
            try:
                drempel = float(trigger.get("drempel_percent", 10))
            except (TypeError, ValueError):
                drempel = 10.0
            # "Bereikbaar" = voldoende vrije ruimte (boven de drempel).
            bereikbaar = float(vrij) >= drempel
        elif bron in self.status_checks:
            try:
                bereikbaar = self.status_checks[bron]()
            except Exception:
                logger.exception("Controle van '%s' mislukt voor regel %s.", bron, regel_id)
                return False
            if bereikbaar is None:
                return False
        else:
            logger.warning(
                "Onbekende status-bron '%s' in regel %s.", bron, regel_id
            )
            return False

        self._status[regel_id] = {"ts": nu_ts, "waarde": bereikbaar}

        if laatste is None:
            # Eerste meting: geen melding, alleen vastleggen.
            return False

        verandering = bool(laatste["waarde"]) != bool(bereikbaar)
        if not verandering:
            return False

        # Alleen melden als de nieuwe status overeenkomt met 'verwacht'
        # (als dat veld er is).
        if "verwacht" in trigger:
            return bool(bereikbaar) == bool(trigger["verwacht"])

        return True

    def _check_actief(self, regel_id, trigger, nu_ts):
        """True als de pc lang genoeg aaneengesloten in gebruik is (zorg).

        Werkt alleen als ``actief_check_fn`` bekend is; de eerste keer dat
        de pc actief wordt gezet, start de telling. Na een melding geldt
        een cooldown (``herhaal_seconden``, standaard 3600).
        """

        if self._actief_sinds is None:
            return False

        minuten = trigger.get("minuten")
        seconden = trigger.get("seconden")
        if seconden is not None:
            try:
                drempel = float(seconden)
            except (TypeError, ValueError):
                drempel = 0.0
        else:
            if minuten is None:
                minuten = 90
            try:
                drempel = float(minuten) * 60.0
            except (TypeError, ValueError):
                drempel = 0.0

        if drempel <= 0 or (nu_ts - self._actief_sinds) < drempel:
            return False

        try:
            herhaal = float(trigger.get("herhaal_seconden", ACTIEF_HERHAAL_SECONDEN))
        except (TypeError, ValueError):
            herhaal = float(ACTIEF_HERHAAL_SECONDEN)

        laatste = self._laatste_actief.get(regel_id)
        if laatste is not None and (nu_ts - laatste) < herhaal:
            return False

        self._laatste_actief[regel_id] = nu_ts
        return True

    # ----- afleveren -----

    def _lever_op(self):
        """Levert wachtrij-meldingen af zolang JARVIS niet in gesprek is.

        Gebruikersmeldingen (timers en wekkers) worden altijd afgeleverd,
        ook in de nachtmodus, de stille modus en de auto-slaap.
        Systeemmeldingen (pauze, lunch, schijf) blijven daarin stil en
        wachten in de wachtrij.

        Geeft het aantal afgeleverde meldingen terug. Zonder ``lever_fn``
        wordt er niets afgeleverd (tests gebruiken dan ``neem_meldingen()``).
        """

        if self.lever_fn is None:
            return 0

        if self.in_gesprek():
            # JARVIS is in gesprek: wachten. De TTL zorgt dat te late
            # systeemmeldingen vanzelf vervallen.
            return 0

        nacht = is_nachtmodus(self.now_fn())
        stil = is_quiet()

        afgeleverd = 0
        bewaren = []
        for melding in self.neem_meldingen():
            # Alleen systeemmeldingen respecteren nacht-/stille modus.
            if melding.prioriteit != "gebruiker" and (nacht or stil):
                bewaren.append(melding)
                continue
            try:
                self.lever_fn(melding)
                afgeleverd += 1
            except Exception:
                logger.exception(
                    "Kon melding niet afleveren: %s", melding.tekst
                )
                if melding.prioriteit == "gebruiker":
                    # Niet stil verloren laten gaan: volgende tick opnieuw.
                    bewaren.append(melding)

        # Systeemmeldingen (en mislukte gebruikersmeldingen) terugzetten.
        for melding in bewaren:
            self.wachtrij.stop(melding)
        return afgeleverd

    def neem_meldingen(self, max_aantal=None):
        """Neemt de wachtrij-meldingen over voor levering.

        Geeft een lijst van ``Melding``-objecten terug (misschien leeg).
        Meldingen die inmiddels verlopen zijn, worden niet meegegeven.
        """

        nu = self.time_fn()
        self.wachtrij.verlopen_weggooien(nu)
        items = self.wachtrij.neem_alle()
        if max_aantal is not None:
            items = items[:max_aantal]
        return items

    # ----- status van JARVIS -----

    def in_gesprek(self):
        """True als JARVIS midden in een gesprek zit (niet storen)."""

        if self.in_gesprek_fn is None:
            return is_in_gesprek()
        try:
            return bool(self.in_gesprek_fn())
        except Exception:
            return False

    # ----- thread -----

    def start(self):
        """Start de achtergrond-thread (idempotent)."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="proactive-engine", daemon=True
        )
        self._thread.start()
        logger.info("Proactieve engine gestart (tick elke %ds).",
                    self.tick_seconden)

    def stop(self, timeout=5.0):
        """Stopt de achtergrond-thread en wacht tot hij gestopt is."""

        self._stop.set()
        self._wek.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        logger.info("Proactieve engine gestopt.")

    def wachttijd(self):
        """Hoe lang de thread mag slapen: tot de volgende tick, maar nooit
        voorbij het aflopen van de eerstvolgende timer.

        Eerder sliep hij altijd ``tick_seconden`` (30 s), waardoor een timer
        van 20 seconden pas tot een halve minuut later werd gemeld.
        """

        wacht = float(self.tick_seconden)
        if self.store is None:
            return wacht
        try:
            timers = self.store.lijst()
        except Exception:
            return wacht
        if not timers:
            return wacht
        try:
            eerste = min(float(t.get("af_loopt_op", 0)) for t in timers)
        except (TypeError, ValueError):
            return wacht
        return max(0.05, min(wacht, eerste - self.time_fn() + 0.05))

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Onverwachte fout in de proactieve engine.")
            self._wek.clear()
            if self._stop.is_set():
                break
            self._wek.wait(self.wachttijd())


# =============================================================
# Module-level engine (zoals core/routines.py een module-level
# manager heeft). Tests maken hun eigen engine met een fake klok.
# =============================================================

_engine = None
_engine_lock = threading.Lock()


def get_engine(store=None, **kwargs):
    """Geeft de gedeelde engine terug (lazy init)."""

    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ProactiveEngine(store=store, **kwargs)
        return _engine


def reset_engine(engine=None):
    """Vervangt de gedeelde engine (voor tests)."""

    global _engine
    with _engine_lock:
        _engine = engine


def peek_engine():
    """Geeft de gedeelde engine terug zonder er een aan te maken."""

    with _engine_lock:
        return _engine


def markeer_activiteit(nu_ts=None):
    """Meldt gebruikersactiviteit aan de gedeelde engine (indien aanwezig).

    Handig voor de commando-laag: een commando betekent activiteit, dus
    een eventuele auto-slaap moet wijken.
    """

    engine = peek_engine()
    if engine is not None:
        try:
            engine.meld_activiteit(nu_ts)
        except Exception:
            logger.debug("Kon activiteit niet doorgeven.", exc_info=True)
