"""Games starten met de stem (Fase 21, M6).

"Start Valorant", "ik wil BeamNG spelen", "open Assetto Corsa":

1. JARVIS kent de games op de game-pc (Steam + Riot) uit een lijst die hij
   bewaart (``memory/games.json``, hooguit een dag oud); alleen als de naam
   echt een game is, neemt deze module de opdracht over. "Open Spotify"
   blijft dus gewoon een programma.
2. Staat de game-pc uit, dan drukt JARVIS op de Wake-on-LAN-knop in Home
   Assistant, zegt "De game-pc wordt opgestart" en wacht op de achtergrond
   tot de agent er is (max. ``GAME_PC_OPSTART_SECONDEN``). Daarna start hij
   de game en meldt hij het (stem + dashboard).
3. Anders start hij de game meteen.

Een game starten is laag risico (net als een programma openen): geen
ja/nee-vraag, wel een auditregel.
"""

import json
import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(PROJECT, "memory", "games.json")
CACHE_GELDIG = 24 * 3600
VERNIEUW_PAUZE = 600   # na een mislukte/nutteloze verversing niet meteen opnieuw
WACHT_STAP = 5.0

_START = (
    re.compile(r"^(?:start|speel|open|launch)\s+(?:het\s+spel\s+|de\s+game\s+|het\s+spelletje\s+|een\s+potje\s+)?"
               r"(.+?)(?:\s+op\s+(?:de\s+)?game\s*pc)?$"),
    re.compile(r"^ik\s+(?:wil|ga)\s+(?:een\s+potje\s+)?(.+?)\s+spelen$"),
    re.compile(r"^laten\s+we\s+(?:een\s+potje\s+)?(.+?)\s+spelen$"),
)
_LIJST = re.compile(
    r"^welke\s+(?:games|spellen)\s+(?:heb\s+ik|staan\s+er\s+op\s+(?:de\s+|mijn\s+)?game\s*pc|kan\s+ik\s+spelen)$"
)


def _schoon(tekst):
    from core.filmmodus import _schoon as schoon

    return schoon(tekst)


class GameStarter:
    def __init__(self, pc_tool=None, ha=None, online_fn=None, meld_fn=None,
                 cache_pad=None, klok=time.time, slaap=time.sleep, achtergrond=True):
        self.pc_tool = pc_tool
        self.ha = ha
        self.online_fn = online_fn
        self.meld_fn = meld_fn
        self.cache_pad = cache_pad
        self.klok = klok
        self.slaap = slaap
        self.achtergrond = achtergrond
        self._laatst_vernieuwd = 0.0
        self._wekken = threading.Lock()

    # ----- hulpjes (los te vervangen in tests) -----

    def _pc(self, tool, args):
        if self.pc_tool is not None:
            return self.pc_tool(tool, args)
        from core.filmmodus import _pc_tool

        return _pc_tool(tool, args)

    def _ha(self):
        if self.ha is not None:
            return self.ha
        from core.filmmodus import HaKlant

        return HaKlant()

    def _online(self):
        if self.online_fn is not None:
            return self.online_fn()
        from beheer import verbinding

        try:
            return verbinding.game_pc_online()
        except Exception:
            return False

    def _meld(self, tekst):
        if self.meld_fn is not None:
            return self.meld_fn(tekst)
        try:
            from core import proactive

            proactive.get_engine().meld(tekst, bron="games")
        except Exception:
            logger.warning("Kon de gamemelding niet geven: %s", tekst)

    # ----- de lijst met games -----

    def _pad(self):
        return self.cache_pad or CACHE_FILE

    def _lees_cache(self):
        try:
            with open(self._pad(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) and isinstance(data.get("games"), list) else None
        except (OSError, ValueError):
            return None

    def vernieuw(self):
        """Haalt de lijst op van de (game-)pc. Geeft de games, of None."""

        self._laatst_vernieuwd = self.klok()
        from core.filmmodus import _gegeven

        r = self._pc("game_lijst", {})
        games = _gegeven(r, "games") if getattr(r, "ok", False) else None
        if not isinstance(games, list):
            return None
        try:
            os.makedirs(os.path.dirname(self._pad()), exist_ok=True)
            with open(self._pad(), "w", encoding="utf-8") as f:
                json.dump({"games": games, "bijgewerkt": self.klok()}, f, ensure_ascii=False, indent=2)
        except OSError:
            logger.debug("Kon de gamelijst niet bewaren", exc_info=True)
        return games

    def games(self, mag_vernieuwen=True):
        cache = self._lees_cache()
        vers = cache and self.klok() - cache.get("bijgewerkt", 0) < CACHE_GELDIG
        if vers:
            return cache["games"]
        if mag_vernieuwen and self.klok() - self._laatst_vernieuwd >= VERNIEUW_PAUZE \
                and self._online() is not False:
            nieuw = self.vernieuw()
            if nieuw is not None:
                return nieuw
        return cache["games"] if cache else []

    def zoek(self, naam):
        from actions.games import zoek_game

        game = zoek_game(naam, self.games())
        if game is None and self._lees_cache() and self.klok() - self._laatst_vernieuwd >= VERNIEUW_PAUZE \
                and self._online() is not False:
            # Misschien net geïnstalleerd: één keer verversen.
            nieuw = self.vernieuw()
            if nieuw:
                game = zoek_game(naam, nieuw)
        return game

    # ----- starten -----

    def _start_nu(self, game):
        r = self._pc("game_start", {"game_id": game["id"]})
        if getattr(r, "ok", False):
            return f"{game['naam']} wordt gestart, sir."
        return f"{game['naam']} kon ik niet starten, sir."

    def _wek_knop(self):
        from config import GAME_PC_AAN_KNOP

        if GAME_PC_AAN_KNOP:
            return GAME_PC_AAN_KNOP
        for s in self._ha().staten():
            eid = str(s.get("entity_id", ""))
            naam = re.sub(r"[^a-z]", "", str((s.get("attributes") or {}).get("friendly_name") or "").lower())
            if eid.startswith("button.") and ("gamepc" in naam or "gamepc" in eid.replace("_", "")):
                return eid
        return None

    def _wacht_en_start(self, game):
        from config import GAME_PC_OPSTART_SECONDEN

        einde = self.klok() + GAME_PC_OPSTART_SECONDEN
        try:
            while self.klok() < einde:
                if self._online():
                    self.slaap(WACHT_STAP)  # de agent net online: even laten opstarten
                    self._meld(self._start_nu(game).replace(" wordt gestart, sir.",
                                                             " wordt gestart, sir. De game-pc is er."))
                    return
                self.slaap(WACHT_STAP)
            self._meld(f"De game-pc kwam niet online, sir. {game['naam']} heb ik niet gestart.")
        finally:
            self._wekken.release()

    def start(self, naam):
        """Antwoord, of None als ``naam`` geen game is."""

        game = self.zoek(naam)
        if game is None:
            return None
        online = self._online()
        if online is not False:  # True, of None (geen aparte game-pc)
            return self._start_nu(game)
        knop = self._wek_knop()
        if not knop:
            return "De game-pc staat uit en ik vind geen knop om hem aan te zetten, sir."
        if not self._wekken.acquire(blocking=False):
            return f"De game-pc is al aan het opstarten, sir. Ik start {game['naam']} zodra hij er is."
        if not self._ha().dienst("button", "press", {"entity_id": knop}):
            self._wekken.release()
            return "De game-pc kon ik niet aanzetten, sir."
        if self.achtergrond:
            threading.Thread(target=self._wacht_en_start, args=(game,), daemon=True,
                             name="jarvis-game-pc-wekken").start()
        else:
            self._wacht_en_start(game)
        return f"De game-pc wordt opgestart, sir. Ik start {game['naam']} zodra hij er is."

    def lijst(self):
        games = self.games()
        if not games:
            return "Ik ken nog geen games op de game-pc, sir."
        namen = [g["naam"] for g in games]
        if len(namen) == 1:
            return f"Op de game-pc staat {namen[0]}."
        return f"Op de game-pc staan {len(namen)} games: " + ", ".join(namen[:-1]) + f" en {namen[-1]}."


_starter = None


def get_starter():
    global _starter
    if _starter is None:
        _starter = GameStarter()
    return _starter


def voer_uit(tekst):
    t = _schoon(tekst)
    if not t:
        return None
    if _LIJST.match(t):
        return get_starter().lijst()
    for patroon in _START:
        m = patroon.match(t)
        if m:
            naam = m.group(1).strip()
            if len(naam) < 3:
                return None
            return get_starter().start(naam)
    return None
