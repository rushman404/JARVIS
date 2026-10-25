"""De hartslag van JARVIS (Fase 19, M2).

``main.py`` schrijft elke ``INTERVAL`` seconden ``logs/hartslag.json`` met
het tijdstip, zijn pid, de fase (rust/luistert/denkt/spreekt) en het
laatste *teken van leven* van de hoofdlus (zie ``status.tik``). De
waakhond (:mod:`beheer.waakhond`) leest dat bestand en herstart JARVIS
als het stilvalt.

Twee soorten vastlopen:

* **het hele proces staat stil** — de hartslag zelf wordt niet meer
  geschreven (``MAX_STIL_SECONDEN``);
* **de hoofdlus hangt** — het proces leeft nog, maar de lus geeft geen
  teken meer. In rust komt er elke 80 ms een microfoonframe binnen; valt
  dat ``MAX_RUST_ZONDER_TEKEN`` seconden weg, dan is de audio dood. In
  andere fasen (een lange AI-vraag) mag het veel langer duren.
"""

import json
import os
import threading
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARTSLAG_FILE = os.path.join(PROJECT, "logs", "hartslag.json")

INTERVAL = 15
MAX_STIL_SECONDEN = 90
MAX_RUST_ZONDER_TEKEN = 300
MAX_BEZIG_ZONDER_TEKEN = 900
# Zo lang mag JARVIS na het starten over zijn eerste hartslag doen
# (AI-model, wake word en stem laden).
OPSTART_GRATIE = 240


def schrijf_atomair(pad, gegevens):
    """Schrijft JSON zo dat een lezer nooit een half bestand ziet."""

    os.makedirs(os.path.dirname(pad), exist_ok=True)
    tijdelijk = f"{pad}.{os.getpid()}.tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump(gegevens, f, ensure_ascii=False)
    os.replace(tijdelijk, pad)


def lees_json(pad):
    """De inhoud als dict, of ``None`` als het bestand ontbreekt of stuk is."""

    try:
        with open(pad, encoding="utf-8") as f:
            gegevens = json.load(f)
    except (OSError, ValueError):
        return None
    return gegevens if isinstance(gegevens, dict) else None


def schrijf(pad=HARTSLAG_FILE, nu=None, fase="rust", laatste_teken=None, pid=None):
    nu = time.time() if nu is None else nu
    schrijf_atomair(pad, {
        "tijd": nu,
        "pid": os.getpid() if pid is None else pid,
        "fase": fase,
        "laatste_teken": nu if laatste_teken is None else laatste_teken,
    })


def vastgelopen(hartslag, nu, pid, gestart_op):
    """De reden waarom JARVIS vastzit, of ``None`` als alles leeft.

    ``pid`` en ``gestart_op`` zijn van het proces dat de waakhond zelf
    startte; een hartslag van een vorig proces telt niet.
    """

    if not hartslag or hartslag.get("pid") != pid:
        if nu - gestart_op > OPSTART_GRATIE:
            return f"geen hartslag binnen {OPSTART_GRATIE} s na het starten"
        return None

    try:
        tijd = float(hartslag.get("tijd"))
        teken = float(hartslag.get("laatste_teken"))
    except (TypeError, ValueError):
        return "ongeldige hartslag"

    if nu - tijd > MAX_STIL_SECONDEN:
        return f"geen hartslag meer sinds {int(nu - tijd)} s"

    fase = hartslag.get("fase") or "rust"
    grens = MAX_RUST_ZONDER_TEKEN if fase == "rust" else MAX_BEZIG_ZONDER_TEKEN
    if nu - teken > grens:
        if fase == "rust":
            return f"de wake-word-lus krijgt al {int(nu - teken)} s geen audio"
        return f"hangt al {int(nu - teken)} s in fase '{fase}'"
    return None


class HartslagSchrijver:
    """Achtergrondthread die de hartslag bijhoudt (alleen onder de waakhond)."""

    def __init__(self, pad=HARTSLAG_FILE, interval=INTERVAL, fase_fn=None, teken_fn=None):
        self.pad = pad
        self.interval = interval
        self.fase_fn = fase_fn
        self.teken_fn = teken_fn
        self._stop = threading.Event()
        self._thread = None

    def _een_slag(self):
        fase = self.fase_fn() if self.fase_fn else "rust"
        teken = self.teken_fn() if self.teken_fn else None
        try:
            schrijf(self.pad, fase=fase, laatste_teken=teken)
        except OSError:
            pass

    def _lus(self):
        while not self._stop.is_set():
            self._een_slag()
            self._stop.wait(self.interval)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-hartslag", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
