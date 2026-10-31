"""Logica van het iPad-dashboard (Fase 18) — zonder HTTP.

``DashboardAPI`` bevat alles wat de dashboard-server doet: status
samenstellen, meldingen bijhouden, timers zetten en annuleren, de
openstaande goedkeuring tonen en beslissen, en de widget-config lezen en
schrijven. De HTTP-handler (``dashboard/server.py``, M2) is alleen
verpakking: hij controleert TLS, token, rol, Host en Origin, parseert de
JSON-body en roept daarna één methode hier aan.

Elke methode geeft ``(status, payload)`` terug, net als
``remote.server.RemoteAgent.process``: een HTTP-statuscode en een dict
(of lijst) die direct als JSON terug kan. Fouten gebruiken dezelfde
envelope ``{"ok": False, "fout": {"code", "melding"}}`` en bevatten nooit
een stacktrace of geheim.

Ontwerpregels
-------------
* **Testbaar zonder HTTP.** Engine, timer-store, klok en de functie die
  een besluit uitvoert zijn injecteerbaar.
* **Goedkeuring is aan één actie gebonden.** Een besluit werkt alleen met
  de ``id`` + ``nonce`` van de actie die nú openstaat
  (``core.confirmation.claim_voor_besluit``); dezelfde ttl en dezelfde
  strikte ja-semantiek als via de stem.
* **Gegevens blijven tekst.** De API geeft namen en meldingen ongewijzigd
  terug; de PWA zet ze alleen via ``textContent`` in de pagina.
"""

import collections
import json
import logging
import os
import re
import threading
import time
from datetime import datetime

from core import confirmation
from core import proactive

logger = logging.getLogger("jarvis.dashboard")

# Versie van het dashboard. Staat ook in static/app.js (VERSIE), in de
# ?v=-adressen van static/index.html en koppel.html en in static/sw.js; een
# test bewaakt dat ze gelijk zijn. Verhoog bij elke wijziging aan static/.
API_VERSIE = "29.1"

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lees_git_versie(project=_PROJECT, run=None):
    """``{"commit", "datum", "omschrijving"}`` van de laatste commit, of None.

    Alleen lezen (git log); nooit fetch of iets dat het netwerk op gaat.
    """

    import subprocess

    run = run or subprocess.run
    try:
        uit = run(["git", "log", "-1", "--format=%h%x1f%cI%x1f%s"], cwd=project,
                  capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if getattr(uit, "returncode", 1) != 0 or not uit.stdout.strip():
        return None
    commit, datum, omschrijving = (uit.stdout.strip().split("\x1f") + ["", "", ""])[:3]
    try:
        datum = datetime.fromisoformat(datum).strftime("%d-%m-%Y %H:%M")
    except ValueError:
        pass
    return {"commit": commit, "datum": datum, "omschrijving": omschrijving[:120]}


# De versie waarmee DEZE JARVIS gestart is (Fase 21). Na een git pull zonder
# herstart draait nog de oude code; dat ziet het dashboard aan het verschil.
_GESTART_MET = None

# Het dashboard schrijft zijn indeling (panelen, apparaten, hardop) naar een
# eigen bestand BUITEN git. config/dashboard.json (in git) is alleen het
# sjabloon. Schreef het dashboard in het bestand uit git, dan zag de
# update-functie (Fase 19, M6) altijd "lokale wijzigingen" en weigerde hij.
_CONFIG_MAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
WIDGETS_FILE = os.path.join(_CONFIG_MAP, "dashboard.local.json")
WIDGETS_SJABLOON = os.path.join(_CONFIG_MAP, "dashboard.json")

# Hoeveel meldingen de hub onthoudt (oudste vallen eraf).
MAX_HUB_MELDINGEN = 50

# Grenzen voor een timer vanaf het dashboard.
MAX_TIMER_NAAM = 60
MAX_TIMER_SECONDEN = 7 * 24 * 3600

# Widgets die in config/dashboard.json mogen staan (zie het design, §6/§7).
BEKENDE_WIDGETS = frozenset([
    "spraakstatus", "timers", "weer", "nachtmodus",
    "gesprek", "auditlog",
    "systeem", "media", "slim_huis",
    "notificaties", "routines", "logboek", "memory",
    "vandaag",
])
KOLOMMEN = ("links", "midden", "rechts")
# "hardop": antwoord op een getypte opdracht ook uitspreken (Fase 20, M1).
# "meldgeluid": geluidje bij een nieuwe melding (Fase 20, M6).
INSTELLING_TYPES = {"thema": str, "taal": str, "meldingen": bool, "hardop": bool, "meldgeluid": bool}
MAX_WIDGETS_BYTES = 16 * 1024

STANDAARD_WIDGETS = {
    "versie": 3,
    "kolommen": {
        "links": ["spraakstatus", "timers", "weer", "nachtmodus"],
        # Fase 23, M7: Vandaag op de plek van de auditlog (die blijft aan te
        # zetten in de instellingen).
        "midden": ["gesprek", "routines", "vandaag"],
        "rechts": ["systeem", "media", "slim_huis"],
    },
    "instellingen": {"thema": "donker", "taal": "nl", "meldingen": True},
}

# Foutmeldingen van lamp_instellen die aan de invoer liggen (400, geen 502).
_LAMP_INVOERFOUTEN = frozenset([
    "Kies één ding: helderheid, kleur of warmte.",
    "Helderheid moet tussen 1 en 100 procent liggen.",
    "Deze lamp kan niet dimmen.",
    "Onbekende kleur.",
    "Deze lamp kan geen kleur.",
    "Onbekende warmte.",
    "Deze lamp kan geen warm of koel wit.",
])

# De enige twee besluiten die de overlay mag sturen. De knop "Ja" telt
# als een strikte bevestiging; alles daarbuiten ("ja, misschien",
# "misschien", "ok") wordt geweigerd.
BESLUIT_JA = "ja"
BESLUIT_NEE = "nee"

# claim-uitkomst -> (HTTP-status, foutcode, melding)
_CLAIM_FOUTEN = {
    confirmation.CLAIM_GEEN: (409, "geen_actie", "Deze actie staat niet open."),
    confirmation.CLAIM_AFGEHANDELD: (409, "al_afgehandeld", "Deze actie is al afgehandeld."),
    confirmation.CLAIM_SOORT: (409, "geen_ja_nee", "Deze vraag kan niet vanaf het dashboard beantwoord worden."),
    confirmation.CLAIM_VERLOPEN: (410, "verlopen", "De goedkeuring is verlopen."),
    confirmation.CLAIM_NONCE: (403, "ongeldige_nonce", "Deze goedkeuring hoort niet bij de openstaande actie."),
}


def _fout(status, code, melding):
    return status, {"ok": False, "fout": {"code": code, "melding": melding}}


def _beurt(b):
    """Eén gespreksbeurt zoals de PWA hem krijgt (tijd in epoch-seconden)."""

    tijd = b.get("tijd")
    return {
        "id": b.get("id"),
        "wie": b.get("wie"),
        "tekst": str(b.get("tekst") or ""),
        "tijd": tijd if isinstance(tijd, (int, float)) and not isinstance(tijd, bool) else None,
    }


# =============================================================
# Meldingenhub
# =============================================================

class MeldingenHub:
    """Thread-safe overzicht van recente meldingen voor het dashboard.

    De proactieve engine meldt elke nieuwe melding via zijn observer-hook;
    de wachtrij van de engine blijft daarbij ongemoeid. De hub onthoudt
    per melding of hij op het dashboard gelezen is.
    """

    def __init__(self, max_meldingen=MAX_HUB_MELDINGEN):
        self._lock = threading.Lock()
        self._items = collections.OrderedDict()  # id -> dict
        self._max = max_meldingen

    def voeg_toe(self, melding):
        """Neemt een ``proactive.Melding`` (of gelijkvormig object) op en
        geeft het kaartje terug (of None)."""

        mid = getattr(melding, "id", None)
        if mid is None:
            return None
        item = {
            "id": mid,
            "tekst": str(getattr(melding, "tekst", "") or ""),
            "bron": str(getattr(melding, "bron", "") or ""),
            "prioriteit": str(getattr(melding, "prioriteit", "") or ""),
            "aangemaakt_op": getattr(melding, "aangemaakt_op", None),
            "verloopt_op": getattr(melding, "verloopt_op", None),
            "gelezen": False,
        }
        with self._lock:
            self._items[mid] = item
            self._items.move_to_end(mid)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return dict(item)

    def lijst(self):
        """Alle meldingen, nieuwste eerst (kopieën)."""

        with self._lock:
            return [dict(m) for m in reversed(self._items.values())]

    def markeer_gelezen(self, ids=None):
        """Markeert de meldingen met deze id's (of alle) als gelezen."""

        with self._lock:
            doel = self._items.keys() if ids is None else [i for i in ids if i in self._items]
            aantal = 0
            for mid in list(doel):
                if not self._items[mid]["gelezen"]:
                    self._items[mid]["gelezen"] = True
                    aantal += 1
            return aantal

    def legen(self):
        with self._lock:
            aantal = len(self._items)
            self._items.clear()
            return aantal


# =============================================================
# Widget-config
# =============================================================

def _valideer_widgets(data):
    """Geeft een foutmelding (str) of None als de widget-config klopt."""

    if not isinstance(data, dict):
        return "De widget-config moet een object zijn."

    onbekend = set(data) - {"versie", "kolommen", "instellingen", "slim_huis"}
    if onbekend:
        return "Onbekende velden in de widget-config."

    if "slim_huis" in data:
        from dashboard.bronnen import valideer_slim_huis

        fout = valideer_slim_huis(data["slim_huis"])
        if fout:
            return fout

    kolommen = data.get("kolommen")
    if not isinstance(kolommen, dict) or set(kolommen) - set(KOLOMMEN):
        return "kolommen moet links, midden en/of rechts bevatten."

    gezien = set()
    for naam in kolommen.values():
        if not isinstance(naam, list):
            return "Elke kolom moet een lijst met widgets zijn."
        for widget in naam:
            if not isinstance(widget, str) or widget not in BEKENDE_WIDGETS:
                return "Onbekende widget in de config."
            if widget in gezien:
                return "Een widget mag maar één keer voorkomen."
            gezien.add(widget)

    instellingen = data.get("instellingen", {})
    if not isinstance(instellingen, dict):
        return "instellingen moet een object zijn."
    for sleutel, waarde in instellingen.items():
        verwacht = INSTELLING_TYPES.get(sleutel)
        if verwacht is None or type(waarde) is not verwacht:
            return "Ongeldige instelling."
        if verwacht is str and len(waarde) > 20:
            return "Ongeldige instelling."

    versie = data.get("versie", 1)
    if type(versie) is not int:
        return "versie moet een getal zijn."

    return None


def lees_widgets(pad=WIDGETS_FILE):
    """Leest de indeling; bij een ontbrekend of kapot bestand de
    standaardconfig (het dashboard mag hier nooit op stuklopen).

    Bestaat het eigen bestand (``dashboard.local.json``) nog niet, dan geldt
    het sjabloon ``config/dashboard.json``.
    """

    if not os.path.exists(pad) and os.path.abspath(pad) == os.path.abspath(WIDGETS_FILE):
        pad = WIDGETS_SJABLOON
    try:
        with open(pad, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(STANDAARD_WIDGETS))

    if _valideer_widgets(data) is not None:
        logger.warning("config/dashboard.json is ongeldig; standaardconfig gebruikt.")
        return json.loads(json.dumps(STANDAARD_WIDGETS))
    return _werk_widgets_bij(data)


def _werk_widgets_bij(data):
    """Een oudere indeling krijgt nieuwe panelen er vanzelf bij.

    Versie 2 (Fase 20, M2): het paneel "routines" komt in het midden, onder
    het gesprek, tenzij het al ergens staat.
    Versie 3 (Fase 23, M7): het paneel "vandaag" komt in het midden op de
    plek van de auditlog (of onderaan het midden), tenzij het al ergens staat.
    """

    versie = data.get("versie") if isinstance(data.get("versie"), int) else 1
    if versie >= 3:
        return data
    kolommen = dict(data.get("kolommen") or {})

    def alles():
        return [w for lijst in kolommen.values() if isinstance(lijst, list) for w in lijst]

    if versie < 2 and "routines" not in alles():
        midden = list(kolommen.get("midden") or [])
        plek = midden.index("gesprek") + 1 if "gesprek" in midden else len(midden)
        midden.insert(plek, "routines")
        kolommen["midden"] = midden
    if "vandaag" not in alles():
        midden = list(kolommen.get("midden") or [])
        if "auditlog" in midden:
            midden[midden.index("auditlog")] = "vandaag"
        else:
            midden.append("vandaag")
        kolommen["midden"] = midden
    return dict(data, versie=3, kolommen=kolommen)


def zorg_voor_lokale_widgets(pad=None, sjabloon=None):
    """Bij het starten: maak het eigen bestand als het er nog niet is.

    Het krijgt de inhoud van ``config/dashboard.json``. Op een pc waar het
    dashboard daar al in schreef (vóór Fase 20), gaan uw apparaten en
    keuzes zo mee; daarna kan dat bestand weer gelijk aan git worden
    (``git checkout -- config/dashboard.json``). Geeft True als er een
    bestand is gemaakt.
    """

    pad = pad or WIDGETS_FILE
    sjabloon = sjabloon or WIDGETS_SJABLOON
    if os.path.exists(pad):
        return False
    try:
        with open(sjabloon, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if _valideer_widgets(data) is not None:
        return False
    try:
        schrijf_widgets(_werk_widgets_bij(data), pad)
    except OSError:
        logger.warning("Kon %s niet maken.", os.path.basename(pad))
        return False
    logger.info("Dashboard-indeling overgezet naar %s (buiten git).", os.path.basename(pad))
    return True


def schrijf_widgets(data, pad=WIDGETS_FILE):
    """Schrijft de widget-config atomair (tijdelijk bestand + vervangen)."""

    tmp = pad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, pad)


# =============================================================
# DashboardAPI
# =============================================================

def _standaard_spreekt():
    try:
        from voice.speak import is_speaking

        return bool(is_speaking())
    except Exception:
        return False


def _ipad_staat():
    """Waar JARVIS luistert en spreekt (Fase 20, M4/M5)."""

    try:
        from voice.ipad_microfoon import peek_ipad_microfoon

        ipad = peek_ipad_microfoon()
        return ipad.staat() if ipad is not None else {"microfoon": False, "speaker": False}
    except Exception:
        return {"microfoon": False, "speaker": False}


def _standaard_taak():
    import status

    return status.taak()


def _standaard_fase():
    try:
        import status

        return status.fase()
    except Exception:
        return "rust"


def _standaard_pc_target():
    try:
        from core import pc_target

        return pc_target.get_pc_target()
    except Exception:
        return "local"


def meld_besluit(tekst):
    """Het antwoord na een ja/nee via het dashboard: in het gesprek-paneel
    en uitgesproken (op de achtergrond, zodat het verzoek niet wacht)."""

    import status

    status.noteer_gesprek("ai", tekst)

    def _spreek():
        try:
            from voice.speak import speak

            speak(tekst)
        except Exception:
            logger.exception("Kon het resultaat van de goedkeuring niet uitspreken.")

    threading.Thread(target=_spreek, name="jarvis-besluit", daemon=True).start()


def _standaard_uitvoerder(pending, goedgekeurd):
    # Late import: core.brain is zwaar en importeert dit pakket niet.
    from core.brain import voer_besluit_uit

    return voer_besluit_uit(pending, goedgekeurd)


def _standaard_audit(**velden):
    from core.audit import log_audit

    log_audit(**velden)


def _standaard_gesprek():
    try:
        import status

        return status.gesprek()
    except Exception:
        return []


def _standaard_gesprek_ouder(voor_id, aantal):
    import status

    return status.gesprek_ouder(voor_id, aantal)


def _standaard_gesprek_wis():
    import status

    status.wis_gesprek()


def _standaard_power_doel():
    try:
        from core import pc_target

        return pc_target.resolve_target("")
    except Exception:
        return "local"


def _standaard_wek_game_pc():
    from core import games_stem

    return games_stem.get_starter().wek()


def _standaard_annuleer(doel):
    if doel == "game-pc":
        from core.ai import _dispatch_tool

        return _dispatch_tool("game_pc_power", {"action": "cancel"}, "annuleer afsluiten")
    from actions.power import cancel_shutdown

    return cancel_shutdown()


def _standaard_aftel_seconden():
    try:
        from config import POWER_COUNTDOWN_SECONDS

        return POWER_COUNTDOWN_SECONDS
    except Exception:
        return 20


# Nachtmodus-standen die het dashboard mag zetten.
NACHT_STANDEN = ("auto", "aan", "uit")


def _focus_status(nu):
    """De focusmodus voor het dashboard (Fase 26, M2); nooit een fout."""

    try:
        from core import focusmodus

        return focusmodus.status(nu=datetime.fromtimestamp(nu))
    except Exception:
        logger.debug("Focusstatus lezen mislukt.", exc_info=True)
        return {"aan": False, "tot": None, "resterend": None}
# Power-acties vanaf het dashboard -> actie in core.brain.POWER_ACTIONS.
# Ze lopen allemaal via de goedkeuringspoort (nooit direct).
POWER_ACTIES = {"slaap": "sleep", "uit": "shutdown", "herstart": "restart"}
POWER_VRAGEN = {
    "sleep": "{waar} in slaapstand zetten?",
    "shutdown": "{waar} afsluiten?",
    "restart": "{waar} herstarten?",
}
# Aanzetten (Wake-on-LAN) en een lopende afsluiting annuleren zijn
# onschuldig: die gaan direct, met een auditregel.
POWER_DIRECT = ("aan", "annuleer")
POWER_DOELEN = ("local", "game-pc")
# Hoeveel oudere gespreksbeurten het dashboard per keer ophaalt.
GESPREK_PAGINA = 30


class DashboardAPI:
    """Alle dashboardlogica, los van HTTP (zie de moduledocstring)."""

    def __init__(self, engine=None, timer_store=None, widgets_pad=WIDGETS_FILE,
                 clock=None, spreekt_fn=None, fase_fn=None, pc_target_fn=None,
                 uitvoerder=None, audit_fn=None, bronnen=None, gesprek_fn=None,
                 power_doel_fn=None, besluit_fn=None, gesprek_ouder_fn=None,
                 gesprek_wis_fn=None, wek_fn=None, annuleer_fn=None, aftel_fn=None):
        self.engine = None
        # Wat JARVIS na een ja/nee via het dashboard deed: in de chat en
        # hardop (Fase 21). None = niets (tests); de server geeft hem mee.
        self.besluit_fn = besluit_fn
        self.hub = MeldingenHub()
        self._timer_store = timer_store
        self.widgets_pad = widgets_pad
        self.clock = clock if clock is not None else time.time
        self.spreekt_fn = spreekt_fn or _standaard_spreekt
        self.taak_fn = _standaard_taak
        self.opdrachten = None  # OpdrachtRunner, lazy (Fase 20, M1)
        self._spraakproef = None  # SpraakProef, lazy (Fase 20, M3)
        self.fase_fn = fase_fn or _standaard_fase
        self.pc_target_fn = pc_target_fn or _standaard_pc_target
        self.uitvoerder = uitvoerder or _standaard_uitvoerder
        self.audit_fn = audit_fn or _standaard_audit
        self._bronnen = bronnen
        self.gesprek_fn = gesprek_fn or _standaard_gesprek
        self.gesprek_ouder_fn = gesprek_ouder_fn or _standaard_gesprek_ouder
        self.gesprek_wis_fn = gesprek_wis_fn or _standaard_gesprek_wis
        self.power_doel_fn = power_doel_fn or _standaard_power_doel
        self.wek_fn = wek_fn or _standaard_wek_game_pc
        self.annuleer_fn = annuleer_fn or _standaard_annuleer
        self.aftel_fn = aftel_fn or _standaard_aftel_seconden
        # Een afsluiting/herstart die via het dashboard is goedgekeurd en
        # nog geannuleerd kan worden: {"doel", "actie", "tot"} of None.
        self._afsluiting = None
        self._widgets_lock = threading.Lock()
        # Wie nieuwe meldingen meteen wil zien (de SSE-waarnemer).
        self.melding_luisteraars = []
        if engine is not None:
            self.koppel_engine(engine)

    # ----- koppelingen -----

    def koppel_engine(self, engine):
        """Laat de hub elke nieuwe melding van de engine zien."""

        self.engine = engine
        engine.set_melding_observer(self._nieuwe_melding)

    def _nieuwe_melding(self, melding):
        item = self.hub.voeg_toe(melding)
        if item is None:
            return
        for luisteraar in list(self.melding_luisteraars):
            try:
                luisteraar(item)
            except Exception:
                logger.debug("Meldingluisteraar gaf een fout.", exc_info=True)

    def ontkoppel(self):
        if self.engine is not None:
            self.engine.set_melding_observer(None)

    @property
    def timer_store(self):
        if self._timer_store is None:
            from core.timers import get_store

            self._timer_store = get_store()
        return self._timer_store

    # ----- status & health -----

    def health(self):
        return 200, {"ok": True, "versie": API_VERSIE}

    def versie(self, lees_fn=None):
        """Welke versie van JARVIS draait (commit + datum), voor ⚙ Instellingen."""

        global _GESTART_MET
        lees_fn = lees_fn or lees_git_versie
        if _GESTART_MET is None:
            _GESTART_MET = lees_fn() or {}
        nu = lees_fn() or {}
        return 200, {
            "commit": _GESTART_MET.get("commit") or "onbekend",
            "datum": _GESTART_MET.get("datum") or "",
            "omschrijving": _GESTART_MET.get("omschrijving") or "",
            "dashboard": API_VERSIE,
            # Nieuwere code op schijf (git pull) dan waarmee JARVIS draait.
            "herstart_nodig": bool(nu.get("commit") and _GESTART_MET.get("commit")
                                   and nu["commit"] != _GESTART_MET["commit"]),
            "op_schijf": nu.get("commit") or "",
        }

    def status(self):
        """Status voor de header, de orb en de kern-tegels."""

        nu = self.clock()
        spreekt = self.spreekt_fn()
        fase = "spreekt" if spreekt else self.fase_fn()
        if fase not in ("rust", "luistert", "denkt", "spreekt"):
            fase = "rust"
        if fase == "spreekt" and not spreekt:
            # Vangnet: "spreekt" alleen tonen zolang hij echt praat; anders
            # bleef de orb hangen als niemand de fase terugzette.
            fase = "rust"

        # Slaapstand (Fase 19, M4): in rust toont de orb "slaapt".
        try:
            slaapt = bool(proactive.slaapt())
        except Exception:
            slaapt = False
        if slaapt and fase == "rust":
            fase = "slaapt"

        auto_slaap = False
        if self.engine is not None:
            try:
                auto_slaap = bool(self.engine.is_auto_slaap())
            except Exception:
                auto_slaap = False

        try:
            nachtmodus = bool(proactive.is_nachtmodus(datetime.fromtimestamp(nu)))
        except Exception:
            nachtmodus = False

        return 200, {
            "tijd": datetime.fromtimestamp(nu).isoformat(timespec="seconds"),
            "actief": True,
            "fase": fase,
            "luistert": fase == "luistert",
            "denkt": fase == "denkt",
            "spreekt": fase == "spreekt",
            "in_gesprek": proactive.is_in_gesprek(),
            "nachtmodus": nachtmodus,
            "nachtmodus_stand": proactive.get_nachtmodus_stand(nu=nu),
            "auto_slaap": auto_slaap,
            "slaapt": slaapt,
            "taak": self.taak_fn(),
            "ipad": _ipad_staat(),
            "quiet": proactive.is_quiet(),
            "pc_target": self.pc_target_fn(),
            "afsluiting": self._lopende_afsluiting(nu),
            "focus": _focus_status(nu),
        }

    def _lopende_afsluiting(self, nu):
        """De afsluiting die nog te annuleren is, of None (daarna vergeten)."""

        a = self._afsluiting
        if a is None:
            return None
        if nu >= a["tot"]:
            self._afsluiting = None
            return None
        return {"doel": a["doel"], "actie": a["actie"]}

    # ----- notificaties -----

    def notificaties(self):
        meldingen = self.hub.lijst()
        return 200, {
            "aantal": len(meldingen),
            "ongelezen": sum(1 for m in meldingen if not m["gelezen"]),
            "meldingen": meldingen,
        }

    def notificaties_lees(self, body):
        body = body if isinstance(body, dict) else {}
        ids = body.get("ids")
        if ids is not None:
            if not isinstance(ids, list) or not all(type(i) is int for i in ids):
                return _fout(400, "ongeldige_invoer", "ids moet een lijst met getallen zijn.")
        aantal = self.hub.markeer_gelezen(ids)
        self._audit("meldingen_lezen", {"aantal": aantal}, "meldingen gelezen", goedgekeurd=True)
        return 200, {"ok": True, "gelezen": aantal}

    def testmelding(self):
        """Een testmelding door dezelfde keten als een echte (Fase 20, M6):
        hub + live-verbinding, zodat banner en geluid te testen zijn. Hij
        wordt niet uitgesproken (hij gaat niet via de wachtrij van de engine)."""

        from core.proactive import Melding

        self._nieuwe_melding(Melding("Dit is een testmelding van JARVIS.", bron="test"))
        return 200, {"ok": True}

    def notificaties_legen(self):
        aantal = self.hub.legen()
        self._audit("meldingen_legen", {"aantal": aantal}, "meldingen gewist", goedgekeurd=True)
        return 200, {"ok": True, "gewist": aantal}

    # ----- timers -----

    def _timer_view(self, timer, nu):
        af = float(timer.get("af_loopt_op", 0) or 0)
        return {
            "id": str(timer.get("id", "")),
            "naam": str(timer.get("naam", "")),
            "resterend_seconden": max(0, int(af - nu)),
            "af_loopt_op": af,
        }

    def timers(self):
        nu = self.clock()
        return 200, [self._timer_view(t, nu) for t in self.timer_store.lijst()]

    def timer_zet(self, body):
        if not isinstance(body, dict):
            return _fout(400, "ongeldige_invoer", "Stuur een object met naam en seconden.")

        naam = body.get("naam", "herinnering")
        seconden = body.get("seconden")

        if not isinstance(naam, str) or not naam.strip() or len(naam) > MAX_TIMER_NAAM:
            return _fout(400, "ongeldige_invoer", f"naam moet tekst zijn van 1 tot {MAX_TIMER_NAAM} tekens.")
        if type(seconden) is not int or not 0 < seconden <= MAX_TIMER_SECONDEN:
            return _fout(400, "ongeldige_invoer", "seconden moet een geheel getal van 1 tot 7 dagen zijn.")

        timer = self.timer_store.zet(naam.strip(), seconden)
        if timer is None:
            return _fout(400, "ongeldige_invoer", "De timer kon niet gezet worden.")

        self._audit("timer_zet", {"naam": timer["naam"], "seconden": seconden},
                    f"timer '{timer['naam']}' gezet", goedgekeurd=True)
        return 201, self._timer_view(timer, self.clock())

    def timer_annuleer(self, timer_id):
        if not isinstance(timer_id, str) or not timer_id or len(timer_id) > 64:
            return _fout(404, "niet_gevonden", "Deze timer bestaat niet.")
        if not self.timer_store.annuleer_id(timer_id):
            return _fout(404, "niet_gevonden", "Deze timer bestaat niet.")
        self._audit("timer_annuleer", {"id": timer_id}, "timer geannuleerd", goedgekeurd=True)
        return 200, {"ok": True}

    # ----- goedkeuring -----

    def pending(self):
        """De openstaande ja/nee-actie (volledige tekst), of None."""

        return 200, confirmation.beschrijf_pending(nu=self.clock())

    def goedkeuring(self, body):
        """Beslist over de openstaande actie: ``{ id, nonce, besluit }``.

        Werkt alleen met de ``id`` + ``nonce`` van de actie die nu openstaat.
        Een verlopen (410), al afgehandelde of onbekende (409) actie, of
        een verkeerde nonce (403), verandert niets.
        """

        if not isinstance(body, dict):
            return _fout(400, "ongeldige_invoer", "Stuur een object met id, nonce en besluit.")

        # Alleen exact "ja" of "nee": strenger dan de stem, want daar
        # telt "ja doe maar" ook. "ja, misschien" of "ok" is nooit goed.
        besluit = body.get("besluit")
        if besluit not in (BESLUIT_JA, BESLUIT_NEE):
            return _fout(400, "ongeldig_besluit", "besluit moet precies 'ja' of 'nee' zijn.")
        goedgekeurd = besluit == BESLUIT_JA

        # "Bedoelde u…?" met meerdere kandidaten (Fase 24): welke knop.
        keuze = body.get("keuze", 0)
        if isinstance(keuze, bool) or not isinstance(keuze, int) or not 0 <= keuze < 10:
            return _fout(400, "ongeldige_keuze", "keuze moet een nummer van 0 tot 9 zijn.")

        uitkomst, pending = confirmation.claim_voor_besluit(
            body.get("id"), body.get("nonce"), herkomst="dashboard"
        )
        if uitkomst != confirmation.CLAIM_OK:
            status, code, melding = _CLAIM_FOUTEN.get(
                uitkomst, (409, "geen_actie", "Deze actie staat niet open.")
            )
            logger.info("Dashboard-goedkeuring geweigerd (%s).", code)
            return _fout(status, code, melding)

        kind = pending.get("kind")
        if kind == confirmation.CORRECTIE_KIND:
            pending["keuze"] = keuze
        try:
            resultaat = self.uitvoerder(pending, goedgekeurd)
        except Exception:
            logger.exception("Uitvoeren na dashboard-goedkeuring mislukt.")
            self._audit_besluit(pending, goedgekeurd, "fout bij uitvoeren")
            return _fout(500, "uitvoeren_mislukt", "De actie kon niet worden uitgevoerd.")

        # Een tool-goedkeuring schrijft zijn eigen auditregel (met
        # herkomst "dashboard") in de bewaakte poort; de rest hier.
        if kind != "tool_approval":
            self._audit_besluit(pending, goedgekeurd, resultaat)

        if kind == "power_confirm" and goedgekeurd:
            self._onthoud_afsluiting(pending)

        if self.besluit_fn is not None and resultaat:
            try:
                self.besluit_fn(str(resultaat))
            except Exception:
                logger.debug("Resultaat van de goedkeuring melden mislukt.", exc_info=True)

        return 200, {
            "ok": True,
            "id": pending.get(confirmation.ID_KEY),
            "besluit": besluit,
            "uitgevoerd": goedgekeurd,
            "resultaat": str(resultaat or ""),
        }

    def _audit_besluit(self, pending, goedgekeurd, resultaat):
        kind = pending.get("kind") or ""
        tool = pending.get("tool_name") or kind
        argumenten = pending.get("arguments")
        if not isinstance(argumenten, dict):
            beschrijving = {}
            for sleutel in ("action", "target", "path", "name"):
                if pending.get(sleutel) not in (None, ""):
                    beschrijving[sleutel] = pending.get(sleutel)
            argumenten = beschrijving
        self._audit(
            tool, argumenten, resultaat, goedgekeurd=goedgekeurd,
            gehoord=pending.get("question") or "",
            risico=pending.get("risk") or ("high" if confirmation.is_dangerous_kind(kind) else "low"),
            reden=None if goedgekeurd else "afgewezen via het dashboard",
        )

    def _audit(self, tool, argumenten, resultaat, goedgekeurd, gehoord="",
               risico="low", reden=None):
        try:
            self.audit_fn(
                gehoord=gehoord,
                handler="dashboard",
                tool=tool,
                argumenten=argumenten,
                risico=risico,
                resultaat=str(resultaat or ""),
                goedgekeurd=goedgekeurd,
                reden=reden,
                herkomst="dashboard",
            )
        except Exception:
            logger.debug("Auditregel schrijven mislukt.", exc_info=True)

    # ----- tegels (M4) -----

    @property
    def bronnen(self):
        if self._bronnen is None:
            from dashboard.bronnen import Bronnen

            self._bronnen = Bronnen()
        return self._bronnen

    def audit(self):
        return 200, self.bronnen.audit()

    def gesprek(self):
        """De laatste beurten (live via SSE); oudere via ``gesprek_ouder``."""

        return 200, [_beurt(b) for b in self.gesprek_fn()[-GESPREK_PAGINA:]]

    def gesprek_ouder(self, body):
        """``{ voor }`` -> ``{ beurten, meer }``: de pagina vóór beurt ``voor``."""

        voor = body.get("voor") if isinstance(body, dict) else None
        if isinstance(voor, bool) or not isinstance(voor, int) or voor < 1:
            return _fout(400, "ongeldige_invoer", "voor moet het id van een beurt zijn.")
        beurten, meer = self.gesprek_ouder_fn(voor, GESPREK_PAGINA)
        return 200, {"beurten": [_beurt(b) for b in beurten], "meer": bool(meer)}

    def gesprek_wissen(self):
        """Vergeet het hele gesprek (de PWA vraagt eerst of u het zeker weet)."""

        self.gesprek_wis_fn()
        self._audit("gesprek_wissen", {}, "gesprek gewist", goedgekeurd=True)
        return 200, {"ok": True}

    def logboek(self):
        return 200, self.bronnen.logboek()

    def geheugen(self):
        return 200, self.bronnen.geheugen()

    def routines(self):
        return 200, self.bronnen.routines()

    def media(self):
        return 200, self.bronnen.media()

    def media_actie(self, body):
        if not isinstance(body, dict):
            return _fout(400, "ongeldige_invoer", "Stuur een object met actie.")
        actie = body.get("actie")
        if not isinstance(actie, str):
            return _fout(400, "ongeldige_invoer", "actie ontbreekt.")
        if actie == "app_volume":
            ok, melding = self.bronnen.app_volume(body.get("app"), body.get("waarde"))
        else:
            ok, melding = self.bronnen.media_actie(actie, body.get("waarde"))
        if not ok and melding in ("Onbekende media-actie.", "volume moet een geheel getal van 0 tot 100 zijn.",
                                  "Deze app kan niet vanaf het dashboard."):
            return _fout(400, "ongeldige_invoer", melding)
        if not ok:
            return _fout(502, "uitvoeren_mislukt", melding or "De media-actie is mislukt.")
        return 200, {"ok": True, "melding": melding}

    def _gekozen_apparaten(self):
        with self._widgets_lock:
            gekozen = lees_widgets(self.widgets_pad).get("slim_huis")
        return gekozen if isinstance(gekozen, list) else None

    def slim_huis(self):
        return 200, self.bronnen.slim_huis(self._gekozen_apparaten())

    def ha_apparaten(self):
        return 200, self.bronnen.ha_apparaten(self._gekozen_apparaten())

    def ha_apparaten_opslaan(self, body):
        """Welke apparaten op het dashboard staan (alleen tonen; bedienen
        blijft beperkt tot lampen)."""

        from dashboard.bronnen import valideer_slim_huis

        lijst = body.get("apparaten") if isinstance(body, dict) else None
        fout = valideer_slim_huis(lijst)
        if fout:
            return _fout(400, "ongeldige_invoer", fout)
        with self._widgets_lock:
            config = lees_widgets(self.widgets_pad)
            config["slim_huis"] = lijst
            try:
                schrijf_widgets(config, self.widgets_pad)
            except OSError:
                logger.exception("Kon de dashboard-indeling niet schrijven.")
                return _fout(500, "opslaan_mislukt", "De lijst kon niet worden opgeslagen.")
        self._audit("slim_huis_aanpassen", {"aantal": len(lijst)}, "apparaten op het dashboard aangepast",
                    goedgekeurd=True)
        return 200, {"ok": True, "apparaten": lijst}

    def slim_huis_actie(self, body):
        """Tik op een tegel: een lamp wisselen of een scène starten."""

        tegel = body.get("id") if isinstance(body, dict) else None
        if not isinstance(tegel, str) or len(tegel) > 100:
            return _fout(400, "ongeldige_invoer", "id ontbreekt.")
        if tegel.startswith("scene:"):
            ok, melding = self.bronnen.scene_start(tegel[len("scene:"):])
        else:
            ok, melding = self.bronnen.lamp_wissel(tegel, self._gekozen_apparaten())
        if not ok and melding in ("Deze lamp staat niet in de lijst van het dashboard.", "Deze scène bestaat niet."):
            return _fout(404, "niet_gevonden", melding)
        if not ok:
            return _fout(502, "uitvoeren_mislukt", melding or "De actie is mislukt.")
        return 200, {"ok": True, "melding": melding}

    def lamp(self, body):
        """Een lamp dimmen of kleuren (Fase 20, M2)."""

        if not isinstance(body, dict):
            return _fout(400, "ongeldige_invoer", "Verwacht een JSON-object.")
        onbekend = set(body) - {"id", "helderheid", "kleur", "warmte"}
        if onbekend:
            return _fout(400, "ongeldige_invoer", "Onbekende velden.")
        ok, melding = self.bronnen.lamp_instellen(
            body.get("id"), self._gekozen_apparaten(),
            helderheid=body.get("helderheid"), kleur=body.get("kleur"), warmte=body.get("warmte"),
        )
        if not ok and melding == "Deze lamp staat niet in de lijst van het dashboard.":
            return _fout(404, "niet_gevonden", melding)
        if not ok and melding in _LAMP_INVOERFOUTEN:
            return _fout(400, "ongeldige_invoer", melding)
        if not ok:
            return _fout(502, "uitvoeren_mislukt", melding or "De lamp kon niet worden ingesteld.")
        return 200, {"ok": True, "melding": melding}

    # ----- routines bewerken (Fase 27, M1) -----

    def routines_bewerken(self):
        """Alle routines in de vorm van de editor."""

        from core import routine_bewerken

        return 200, {"routines": routine_bewerken.lijst()}

    def routine_opslaan(self, body):
        from core import routine_bewerken

        try:
            routine = routine_bewerken.opslaan(body)
        except routine_bewerken.RoutineFout as fout:
            return _fout(400, "ongeldige_invoer", str(fout))
        self._na_routinewijziging()
        oud = body.get("oude_naam") if isinstance(body, dict) else None
        self._audit("routine_opslaan", {"naam": routine["naam"], "oude_naam": oud,
                                        "stappen": len(routine["stappen"])},
                    "routine opgeslagen", goedgekeurd=True)
        return 200, {"ok": True, "routine": routine}

    def patronen(self):
        """Fase 29, M4: wat JARVIS van u geleerd heeft (alleen lokaal)."""

        from core import patronen

        return 200, {"patronen": patronen.overzicht()}

    def patroon_beheer(self, body):
        """``{id, actie: "aan"|"uit"|"wissen"}``."""

        from core import patronen

        pid = body.get("id") if isinstance(body, dict) else None
        actie = body.get("actie") if isinstance(body, dict) else None
        if not isinstance(pid, str) or not re.fullmatch(r"[0-9a-f]{10}", pid):
            return _fout(400, "ongeldige_invoer", "Onbekend patroon.")
        if actie not in ("aan", "uit", "wissen"):
            return _fout(400, "ongeldige_invoer", "actie moet aan, uit of wissen zijn.")
        if not patronen.beheer(pid, actie):
            return _fout(404, "niet_gevonden", "Dit patroon bestaat niet (meer).")
        self._audit("patroon_" + actie, {"id": pid}, "patroon " + actie, goedgekeurd=True)
        return 200, {"ok": True, "patronen": patronen.overzicht()}

    def routine_verwijder(self, body):
        from core import routine_bewerken

        naam = body.get("naam") if isinstance(body, dict) else None
        try:
            bestond = routine_bewerken.verwijder(naam)
        except routine_bewerken.RoutineFout as fout:
            return _fout(400, "ongeldige_invoer", str(fout))
        if not bestond:
            return _fout(404, "niet_gevonden", "Deze routine bestaat niet.")
        self._na_routinewijziging()
        self._audit("routine_verwijder", {"naam": naam}, "routine verwijderd", goedgekeurd=True)
        return 200, {"ok": True}

    def _na_routinewijziging(self):
        # Het routinepaneel meteen bijwerken (anders pas na 5 s).
        try:
            self.bronnen.cache.vergeet("routines")
        except Exception:
            logger.debug("Routine-cache legen mislukt.", exc_info=True)

    def routine_start(self, body):
        """Een routine starten (Fase 20, M2). Draait als opdracht op de
        achtergrond; stappen die goedkeuring nodig hebben, vragen die."""

        naam = body.get("naam") if isinstance(body, dict) else None
        if not isinstance(naam, str) or not naam or len(naam) > 40:
            return _fout(400, "ongeldige_invoer", "naam ontbreekt.")
        routines = self.bronnen.routines_fn()
        if not isinstance(routines, dict) or naam not in routines:
            return _fout(404, "niet_gevonden", "Deze routine bestaat niet.")
        if self.opdrachten is None:
            from core.opdrachten import OpdrachtRunner

            self.opdrachten = OpdrachtRunner()
        # Een routine is iets dat u hoort gebeuren: standaard hardop
        # (Fase 21: anders bleef JARVIS stil bij een routine vanaf de iPad).
        hardop = body.get("hardop", True)
        ok, reden = self.opdrachten.start_routine(naam, hardop=hardop is not False)
        if ok:
            return 202, {"ok": True}
        if reden == "bezig":
            return _fout(409, "bezig", "JARVIS is nog bezig met de vorige opdracht.")
        return _fout(404, "niet_gevonden", "Deze routine bestaat niet.")

    def weer(self):
        return 200, self.bronnen.weer()

    def vandaag(self):
        return 200, self.bronnen.vandaag()

    def pc_status(self, doel):
        data = self.bronnen.pc_status(doel)
        if data is None:
            return _fout(404, "niet_gevonden", "Onbekende pc.")
        return 200, data

    def focus(self, body):
        """Focusmodus (Fase 26, M2): ``{actie: "aan"|"uit", minuten?: 1-720}``."""

        from core import focusmodus

        actie = body.get("actie") if isinstance(body, dict) else None
        if actie not in ("aan", "uit"):
            return _fout(400, "ongeldige_invoer", "actie moet aan of uit zijn.")
        minuten = body.get("minuten")
        if minuten is not None and (isinstance(minuten, bool) or not isinstance(minuten, int)
                                    or not 1 <= minuten <= focusmodus.MAX_MINUTEN):
            return _fout(400, "ongeldige_invoer", "minuten moet een geheel getal van 1 tot 720 zijn.")
        modus = focusmodus.get_focusmodus()
        tekst = modus.aan(minuten) if actie == "aan" else modus.uit()
        self._audit("focusmodus", {"actie": actie, "minuten": minuten}, tekst, goedgekeurd=True)
        return 200, {"ok": True, "tekst": tekst, "focus": _focus_status(self.clock())}

    def nachtmodus(self, body):
        stand = body.get("stand") if isinstance(body, dict) else None
        if stand not in NACHT_STANDEN:
            return _fout(400, "ongeldige_invoer", "stand moet auto, aan of uit zijn.")
        proactive.set_nachtmodus(stand)
        self._audit("nachtmodus", {"stand": stand}, f"nachtmodus {stand}", goedgekeurd=True)
        return 200, {"ok": True, "stand": proactive.get_nachtmodus_stand()}

    def power(self, body):
        """Een power-actie: ``{ actie, doel? }``.

        Uit, herstart en slaap worden NOOIT direct uitgevoerd: er komt een
        openstaande goedkeuring (overlay, id + nonce). Aan (Wake-on-LAN,
        alleen de game-pc) en annuleren gaan direct. ``doel`` is de pc die
        in het Systeem-paneel gekozen is; zonder doel de standaard-pc.
        """

        if not isinstance(body, dict):
            return _fout(400, "ongeldige_invoer", "Stuur een object met actie.")
        actie = body.get("actie")
        if actie not in POWER_ACTIES and actie not in POWER_DIRECT:
            return _fout(400, "ongeldige_invoer", "actie moet uit, aan, herstart, slaap of annuleer zijn.")
        doel = body.get("doel")
        if doel is None:
            doel = self.power_doel_fn()
        elif doel not in POWER_DOELEN:
            return _fout(400, "ongeldige_invoer", "doel moet local of game-pc zijn.")

        if actie == "aan":
            return self._power_aan(doel)
        if actie == "annuleer":
            return self._power_annuleer()

        waar = "de game-pc" if doel == "game-pc" else "deze pc"
        pending = confirmation.set_pending("power_confirm", {
            "action": POWER_ACTIES[actie],
            "target": doel,
            "question": POWER_VRAGEN[POWER_ACTIES[actie]].format(waar=waar).capitalize(),
            "source": "dashboard",
        })
        self._audit("power_aanvraag", {"actie": actie, "doel": doel}, "wacht op goedkeuring",
                    goedgekeurd=False, risico="high", reden="wacht op goedkeuring")
        return 202, {"ok": True, "id": pending[confirmation.ID_KEY]}

    def _power_aan(self, doel):
        """Zet de game-pc aan met de Wake-on-LAN-knop in Home Assistant.
        Deze pc kan niet: die draait het dashboard zelf."""

        if doel != "game-pc":
            return _fout(400, "ongeldige_invoer", "Alleen de game-pc kan vanaf het dashboard aan.")
        try:
            ok = bool(self.wek_fn())
        except Exception:
            logger.exception("De game-pc wekken mislukt.")
            ok = False
        self._audit("power_aan", {"doel": doel}, "game-pc gewekt" if ok else "wekken mislukt",
                    goedgekeurd=ok, reden=None if ok else "geen Wake-on-LAN-knop of HA niet bereikbaar")
        if not ok:
            return _fout(502, "wekken_mislukt",
                         "De game-pc kon ik niet aanzetten (geen Wake-on-LAN-knop in Home Assistant?).")
        return 200, {"ok": True}

    def _power_annuleer(self):
        """Annuleert de afsluiting/herstart die via het dashboard loopt."""

        a = self._lopende_afsluiting(self.clock())
        if a is None:
            return _fout(409, "geen_afsluiting", "Er loopt geen afsluiting of herstart.")
        try:
            resultaat = self.annuleer_fn(a["doel"])
        except Exception:
            logger.exception("Afsluiting annuleren mislukt.")
            return _fout(502, "annuleren_mislukt", "Annuleren is niet gelukt.")
        tekst = str(getattr(resultaat, "message", None) or resultaat or "")
        self._afsluiting = None
        self._audit("power_annuleer", {"doel": a["doel"], "actie": a["actie"]}, tekst or "geannuleerd",
                    goedgekeurd=True)
        if self.besluit_fn is not None and tekst:
            try:
                self.besluit_fn(tekst)
            except Exception:
                logger.debug("Annuleren melden mislukt.", exc_info=True)
        return 200, {"ok": True, "resultaat": tekst}

    def _onthoud_afsluiting(self, pending):
        """Na een ja op uit/herstart: de Annuleren-knop tot het aftellen klaar is."""

        payload = pending.get("payload") or pending
        actie = payload.get("action")
        if actie not in ("shutdown", "restart"):
            return
        doel = pending.get("target") or payload.get("target") or "local"
        try:
            seconden = int(self.aftel_fn())
        except Exception:
            seconden = 20
        self._afsluiting = {"doel": doel, "actie": actie, "tot": self.clock() + seconden}

    def opdracht(self, body):
        """Een getypte opdracht (Fase 20, M1). Draait op de achtergrond;
        het antwoord komt live in het gesprek-paneel."""

        if not isinstance(body, dict):
            return _fout(400, "ongeldige_invoer", "Verwacht een JSON-object.")
        hardop = body.get("hardop", False)
        if not isinstance(hardop, bool):
            return _fout(400, "ongeldige_invoer", "hardop moet true of false zijn.")
        if self.opdrachten is None:
            from core.opdrachten import OpdrachtRunner

            self.opdrachten = OpdrachtRunner()
        ok, reden = self.opdrachten.start(body.get("tekst"), hardop=hardop)
        if ok:
            return 202, {"ok": True}
        if reden == "bezig":
            return _fout(409, "bezig", "JARVIS is nog bezig met de vorige opdracht.")
        return _fout(400, "ongeldige_invoer", "Typ een opdracht van 1 tot 300 tekens.")

    # ----- spraakproef (Fase 20, M3) -----

    @property
    def spraakproef(self):
        if self._spraakproef is None:
            from dashboard.spraakproef import SpraakProef

            self._spraakproef = SpraakProef()
        return self._spraakproef

    def proef_start(self):
        return self.spraakproef.start()

    def proef_stuk(self, body):
        return self.spraakproef.stuk(body)

    def proef_klaar(self, body):
        status, uitslag = self.spraakproef.klaar(body)
        if status == 200:
            self._audit("spraakproef", {"seconden": uitslag.get("seconden")}, uitslag.get("oordeel", ""),
                        goedgekeurd=True)
        return status, uitslag

    def proef_testzin(self):
        """``(200, wav_bytes)`` of een JSON-fout."""

        wav, fout = self.spraakproef.testzin()
        if wav is None:
            return _fout(503, "geen_stem", fout)
        return 200, wav

    def update(self, body=None):
        """Vraagt een update aan (Fase 19, M6). Die wordt NOOIT direct
        geïnstalleerd: er komt een openstaande goedkeuring (overlay)."""

        from beheer import updates

        pending, tekst = updates.vraag_goedkeuring()
        if pending is None:
            return _fout(409, "geen_update", tekst)
        self._audit("update_aanvraag", {}, "wacht op goedkeuring",
                    goedgekeurd=False, risico="high", reden="wacht op goedkeuring")
        return 202, {"ok": True, "id": pending[confirmation.ID_KEY]}

    # ----- widgets -----

    def widgets(self):
        with self._widgets_lock:
            return 200, lees_widgets(self.widgets_pad)

    def widgets_opslaan(self, body):
        try:
            grootte = len(json.dumps(body))
        except (TypeError, ValueError):
            return _fout(400, "ongeldige_invoer", "De widget-config is geen geldige JSON.")
        if grootte > MAX_WIDGETS_BYTES:
            return _fout(413, "te_groot", "De widget-config is te groot.")

        fout = _valideer_widgets(body)
        if fout is not None:
            return _fout(400, "ongeldige_invoer", fout)

        with self._widgets_lock:
            # Stuurt een opslag geen slim-huisknoppen mee (bijv. ⚙ Opslaan in
            # een oudere app), dan blijven de bestaande staan in plaats van
            # te verdwijnen (fix 2026-10-26).
            if "slim_huis" not in body:
                bestaand = lees_widgets(self.widgets_pad).get("slim_huis")
                if bestaand is not None:
                    body = dict(body, slim_huis=bestaand)
            try:
                schrijf_widgets(body, self.widgets_pad)
            except OSError:
                logger.exception("Kon de dashboard-indeling niet schrijven.")
                return _fout(500, "opslaan_mislukt", "De widget-config kon niet worden opgeslagen.")

        self._audit("widgets_opslaan", {}, "widget-config opgeslagen", goedgekeurd=True)
        return 200, {"ok": True}
