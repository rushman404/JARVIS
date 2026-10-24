"""Live-updates voor het dashboard via SSE (Fase 18, §3.3).

``EventBus`` verdeelt events over de open ``/api/events``-verbindingen.
Elke verbinding krijgt een eigen begrensde wachtrij; een client die niet
bijhoudt (wachtrij vol) wordt losgekoppeld in plaats van de rest op te
houden.

``Waarnemer`` is een achtergrondthread die elke seconde de status, de
timers en de openstaande goedkeuring van ``DashboardAPI`` bekijkt en
alleen bij een wijziging een event stuurt. Meldingen komen direct binnen
via de melding-luisteraar van ``DashboardAPI``.

Eventtypes: ``status``, ``timer``, ``pending``, ``audit``, ``gesprek`` en
``melding``.
"""

import json
import logging
import queue
import threading

logger = logging.getLogger("jarvis.dashboard.events")

# Ruimte voor een paar oude streams die na herladen nog even openstaan.
MAX_ABONNEES = 8
# Per apparaat (IP) hooguit zoveel live-streams: een nieuwe stream sluit de
# oudste. Gaat de iPad op slot of naar de achtergrond, dan blijft zijn oude
# verbinding aan deze kant "half open" (Windows merkt dat pas na minuten).
# Zonder deze grens liepen zo alle verbindingsplekken van de iPad vol en
# sloot de server elke nieuwe verbinding ("de server reageert niet").
MAX_PER_IP = 2
MAX_WACHTRIJ = 200
# Een dode stream (iPad herladen of weg) wordt bij de volgende hartslag
# opgemerkt en opgeruimd.
HARTSLAG_SECONDEN = 10
# Een stream sluit na zoveel seconden zelf; de PWA verbindt binnen 3 s
# opnieuw. Zo blijft er nooit lang een dode verbinding hangen.
MAX_STREAM_SECONDEN = 300


class Abonnement:
    def __init__(self, ip=None):
        self.ip = ip
        self.wachtrij = queue.Queue(maxsize=MAX_WACHTRIJ)
        self.overgelopen = False
        # Wordt bij elk bericht en elke hartslag opnieuw gevraagd: is het
        # apparaat nog gekoppeld (niet ingetrokken, token niet vernieuwd)?
        self.nog_geldig = lambda: True


class EventBus:
    """Thread-safe verdeling van events over SSE-abonnees."""

    def __init__(self, max_abonnees=MAX_ABONNEES, max_per_ip=MAX_PER_IP):
        self._lock = threading.Lock()
        self._abonnees = []
        self._max = max_abonnees
        self._max_per_ip = max_per_ip
        self._laatste = {}
        self.gesloten = threading.Event()

    def abonneer(self, ip=None):
        """Nieuw abonnement, of None als het maximum bereikt is.

        Heeft dit IP al ``max_per_ip`` streams, dan wordt de oudste gesloten:
        die is vrijwel zeker dood (vorige keer openen van de app).
        """

        with self._lock:
            if self.gesloten.is_set():
                return None
            if ip is not None:
                eigen = [a for a in self._abonnees if a.ip == ip]
                while len(eigen) >= self._max_per_ip:
                    self._stop(eigen.pop(0))
                # Alles vol? Dan maakt een apparaat dat opnieuw verbindt
                # plaats door zijn eigen oudste (dode) stream te sluiten.
                if eigen and len(self._abonnees) >= self._max:
                    self._stop(eigen.pop(0))
            if len(self._abonnees) >= self._max:
                return None
            ab = Abonnement(ip)
            self._abonnees.append(ab)
            # Nieuwe abonnees krijgen meteen de laatst bekende stand.
            for soort, data in self._laatste.items():
                ab.wachtrij.put_nowait((soort, data))
            return ab

    def _stop(self, ab):
        """Sluit één stream (onder de lock): de handler stopt en geeft zijn
        verbinding vrij."""

        ab.overgelopen = True
        if ab in self._abonnees:
            self._abonnees.remove(ab)
        try:
            ab.wachtrij.put_nowait(None)
        except queue.Full:
            pass

    def zeg_op(self, ab):
        with self._lock:
            if ab in self._abonnees:
                self._abonnees.remove(ab)

    def aantal(self):
        with self._lock:
            return len(self._abonnees)

    def publiceer(self, soort, data, onthoud=True):
        with self._lock:
            if onthoud:
                self._laatste[soort] = data
            for ab in list(self._abonnees):
                try:
                    ab.wachtrij.put_nowait((soort, data))
                except queue.Full:
                    ab.overgelopen = True
                    self._abonnees.remove(ab)

    def sluit(self):
        self.gesloten.set()
        with self._lock:
            abonnees, self._abonnees = self._abonnees, []
        for ab in abonnees:
            try:
                ab.wachtrij.put_nowait(None)
            except queue.Full:
                pass


def sse_bericht(soort, data):
    """Eén SSE-bericht als bytes. ``soort`` is een vast, eigen woord."""

    tekst = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # json.dumps zet nooit een echte regeleinde in de uitvoer, dus één
    # data-regel is genoeg en kan het SSE-formaat niet breken.
    return f"event: {soort}\ndata: {tekst}\n\n".encode("utf-8")


HARTSLAG = b": ping\n\n"


class Waarnemer:
    """Pollt de DashboardAPI en publiceert alleen wijzigingen."""

    def __init__(self, api, bus, interval=1.0):
        self.api = api
        self.bus = bus
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._vorige = {}
        api.melding_luisteraars.append(self._nieuwe_melding)

    def _nieuwe_melding(self, item):
        self.bus.publiceer("melding", item, onthoud=False)

    def _momentopname(self):
        status = dict(self.api.status()[1])
        status.pop("tijd", None)
        timers = [
            {"id": t["id"], "naam": t["naam"], "af_loopt_op": t["af_loopt_op"]}
            for t in self.api.timers()[1]
        ]
        pending = self.api.pending()[1]
        return {
            "status": status,
            "timer": timers,
            "pending": pending,
            "audit": self.api.audit()[1],
            "gesprek": self.api.gesprek()[1],
        }

    def stap(self):
        """Eén controle; geeft de gepubliceerde soorten terug (voor tests)."""

        nu = self._momentopname()
        gepubliceerd = []
        for soort, data in nu.items():
            vergelijk = data
            if soort == "pending" and data is not None:
                # De resterende tijd telt elke seconde af; de PWA telt zelf.
                vergelijk = {k: v for k, v in data.items() if k != "resterende_seconden"}
            if self._vorige.get(soort, object()) != vergelijk:
                self._vorige[soort] = vergelijk
                self.bus.publiceer(soort, data)
                gepubliceerd.append(soort)
        return gepubliceerd

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="dashboard-waarnemer", daemon=True)
        self._thread.start()

    def stop(self, timeout=3.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.stap()
            except Exception:
                logger.exception("Dashboard-waarnemer: fout bij het verversen.")
            self._stop.wait(self.interval)
