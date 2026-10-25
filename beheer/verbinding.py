"""Verbindingen bewaken (Fase 19, M6).

De proactieve engine kent statusregels (``statuswijziging``); dit bestand
levert er drie bronnen bij:

* ``game_pc``  — de game-pc-agent (alleen als die gebruikt wordt);
* ``ollama``   — het AI-model;
* ``internet`` — een TCP-verbinding naar een vast adres (geen DNS, er
  wordt niets verstuurd).

Valt een verbinding weg, dan meldt de regel dat één keer, en weer één keer
als hij terug is. Tussendoor probeert :class:`Wachter` het opnieuw met een
oplopende wachttijd, zodat een uitgeschakelde game-pc niet elke minuut een
time-out kost.
"""

import socket
import time

# Na een mislukte controle: zo lang wachten voor de volgende echte poging.
WACHTTIJDEN = (30, 60, 120, 300)

# Vaste adressen voor de internetcontrole (Cloudflare en Google DNS, poort
# 443). Een IP-adres, zodat er geen DNS nodig is.
INTERNET_ADRESSEN = (("1.1.1.1", 443), ("8.8.8.8", 443))
INTERNET_TIMEOUT = 3.0


class Wachter:
    """Roept ``probe`` aan; is die offline, dan pas na een oplopende pauze opnieuw.

    ``probe()`` geeft True (online), False (offline) of None (niet van
    toepassing). Tussen de pogingen geeft de wachter het laatste antwoord
    terug, zodat de engine geen verandering ziet die er niet is.
    """

    def __init__(self, probe, klok=time.time, wachttijden=WACHTTIJDEN):
        self.probe = probe
        self.klok = klok
        self.wachttijden = wachttijden
        self.laatste = None
        self._mislukt = 0
        self._volgende = 0.0

    def __call__(self):
        nu = self.klok()
        if self.laatste is False and nu < self._volgende:
            return False
        try:
            uitkomst = self.probe()
        except Exception:
            uitkomst = False
        if uitkomst is False:
            stap = self.wachttijden[min(self._mislukt, len(self.wachttijden) - 1)]
            self._mislukt += 1
            self._volgende = nu + stap
        else:
            self._mislukt = 0
            self._volgende = 0.0
        self.laatste = uitkomst
        return uitkomst


def game_pc_online():
    """True/False voor de game-pc-agent; None als hij niet gebruikt wordt."""

    import config
    from core import pc_target

    if not config.REMOTE_CLIENT_ENABLED or pc_target.get_pc_target() != pc_target.GAME_PC:
        return None
    if pc_target.remote_client_configuratie_fout():
        return None  # dat meldt JARVIS al bij het opstarten
    from remote import tools as remote_tools

    try:
        client = remote_tools._get_client()
    except ValueError:
        return None
    return bool(client.is_online())


def ollama_online(lijst_fn=None):
    if lijst_fn is None:
        import ollama

        lijst_fn = ollama.list
    lijst_fn()
    return True


def internet_online(adressen=INTERNET_ADRESSEN, timeout=INTERNET_TIMEOUT, verbind=socket.create_connection):
    for adres in adressen:
        try:
            with verbind(adres, timeout=timeout):
                return True
        except OSError:
            continue
    return False


def maak_checks():
    """De statusbronnen voor de engine: ``{bron: Wachter}``."""

    return {
        "game_pc": Wachter(game_pc_online),
        "ollama": Wachter(ollama_online),
        "internet": Wachter(internet_online),
    }
