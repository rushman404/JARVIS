"""Leren van u: gebruikspatronen en voorstellen (Fase 29).

* **M1 — gebruikslog:** JARVIS noteert lokaal wanneer u een lamp bedient
  (:func:`noteer_lamp`, vanuit Home Assistant), welke Spotify-playlist u
  draait (:class:`MuziekVerzamelaar`, uit "recent afgespeeld") en wanneer u
  de focus aanzet (:func:`noteer_focus`). Dertig dagen bewaard in
  ``memory/patronen.json``; niets hiervan gaat naar de cloud.
* **M2 — voorstellen op tijdstip:** :func:`vind_patronen` zoekt wat u minstens
  drie keer in twee weken rond hetzelfde tijdstip (±30 min) deed, apart voor
  doordeweeks en het weekend. :class:`PatroonPlanner` vraagt het een paar
  minuten vooraf ("Zal ik dat doen?"); ja voert uit, twee keer nee = twee
  weken stil, "stel dat nooit meer voor" = voorgoed uit.
* **M3 — muziek bij focus:** :func:`voorstel_bij_focus` stelt de playlist voor
  die u vaker kort na het aanzetten van de focus draaide.
* **M4 — beheer:** "wat heb je van mij geleerd?", "vergeet dat patroon" en
  een lijst op de iPad (:func:`overzicht`, :func:`beheer`).

Altijd een voorstel, nooit vanzelf doen.
"""

import hashlib
import logging
import os
import re
import threading
import time as _time
from datetime import datetime, timedelta

from core import koppelingen

logger = logging.getLogger("jarvis.patronen")

PATRONEN_FILE = os.path.join(os.path.dirname(koppelingen.MAP), "patronen.json")

BEWAAR_DAGEN = 30
VENSTER_DAGEN = 14
MIN_DAGEN = 3
MARGE_MIN = 30          # ±30 minuten telt als "hetzelfde tijdstip"
VOORAF_MIN = 5          # zoveel minuten vóór het gewone tijdstip vragen
LAAT_MIN = 10           # tot zoveel minuten erna mag het voorstel nog
STIL_DAGEN = 14         # na twee keer nee
NEE_DREMPEL = 2
VOORSTEL_TTL = 600      # seconden geldig: "Zal ik dat doen?"
SESSIE_MIN = 60         # dezelfde playlist binnen een uur = één keer draaien
FOCUS_MUZIEK_MIN = 20   # playlist tot zoveel minuten na "focus aan" telt mee
MAX_GEBEURTENISSEN = 3000

KIND = "patroon_voorstel"
SOORTEN = ("lamp", "muziek")

_lock = threading.RLock()


# -----------------------------------------------------------------
# Opslag
# -----------------------------------------------------------------

def _leeg():
    return {"gebeurtenissen": [], "instellingen": {}, "gevraagd": {}, "laatste": None, "spotify_tot": 0}


def lees(pad=None):
    data = koppelingen.lees_json(pad or PATRONEN_FILE) or {}
    staat = _leeg()
    for sleutel in staat:
        if sleutel in data:
            staat[sleutel] = data[sleutel]
    if not isinstance(staat["gebeurtenissen"], list):
        staat["gebeurtenissen"] = []
    for sleutel in ("instellingen", "gevraagd"):
        if not isinstance(staat[sleutel], dict):
            staat[sleutel] = {}
    return staat


def schrijf(staat, pad=None, nu=None):
    grens = (nu if nu is not None else _time.time()) - BEWAAR_DAGEN * 86400
    staat["gebeurtenissen"] = [g for g in staat["gebeurtenissen"]
                               if isinstance(g, dict) and g.get("t", 0) >= grens][-MAX_GEBEURTENISSEN:]
    koppelingen.schrijf_json(pad or PATRONEN_FILE, staat)


def _aan():
    import config

    return getattr(config, "PATRONEN_LEREN", True)


# -----------------------------------------------------------------
# M1 — noteren
# -----------------------------------------------------------------

def noteer(soort, sleutel, label, actie, t=None, pad=None):
    """Voegt één gebeurtenis toe. Faalt stil: leren mag nooit iets breken."""

    if not _aan():
        return None
    gebeurtenis = {"t": float(t if t is not None else _time.time()), "soort": soort,
                   "sleutel": sleutel, "label": label, "actie": actie}
    try:
        with _lock:
            staat = lees(pad)
            staat["gebeurtenissen"].append(gebeurtenis)
            schrijf(staat, pad)
    except Exception:
        logger.debug("Kon de gebeurtenis niet noteren.", exc_info=True)
        return None
    return gebeurtenis


def _helderheid(waarde):
    try:
        h = int(round(float(waarde) / 10.0)) * 10
    except (TypeError, ValueError):
        return None
    return max(10, min(100, h))


def noteer_lamp(entity_id, naam, service, helderheid=None, t=None, pad=None):
    """Een lamp ging aan of uit (vanuit :mod:`core.home_assistant`)."""

    if service not in ("turn_on", "turn_off") or not str(entity_id).startswith("light."):
        return None
    naam = " ".join(str(naam or entity_id).split()) or entity_id
    h = _helderheid(helderheid) if service == "turn_on" else None
    if service == "turn_off":
        label = f"de {naam} uit"
    elif h:
        label = f"de {naam} op {h} procent"
    else:
        label = f"de {naam} aan"
    actie = {"type": "lamp", "entity": entity_id, "service": service, "helderheid": h, "naam": naam}
    return noteer("lamp", f"lamp|{entity_id}|{service}|{h or ''}", label, actie, t, pad)


def noteer_muziek(uri, naam, t=None, pad=None):
    if not str(uri).startswith("spotify:playlist:"):
        return None
    naam = " ".join(str(naam or "").split()) or "uw playlist"
    actie = {"type": "muziek", "uri": uri, "naam": naam}
    return noteer("muziek", f"muziek|{uri}", f"uw playlist '{naam}'", actie, t, pad)


def noteer_focus(t=None, pad=None):
    return noteer("focus", "focus", "de focus", {"type": "focus"}, t, pad)


class MuziekVerzamelaar:
    """Leest "recent afgespeeld" uit Spotify en noteert de playlists.

    Eén keer draaien = de eerste keer in een uur dat die playlist speelde.
    """

    def __init__(self, klant=None, pad=None, namen_fn=None):
        self.klant = klant
        self.pad = pad
        self.namen_fn = namen_fn

    def _klant(self):
        if self.klant is None:
            from core.spotify_smaak import SpotifyKlant

            self.klant = SpotifyKlant()
        return self.klant

    def _namen(self):
        if self.namen_fn is not None:
            return self.namen_fn()
        try:
            from core.spotify_smaak import SMAAK_FILE, _lees

            return {p["uri"]: p["naam"] for p in (_lees(SMAAK_FILE) or {}).get("playlists") or []
                    if isinstance(p, dict) and p.get("uri")}
        except Exception:
            return {}

    def _naam(self, uri, namen):
        if uri in namen:
            return namen[uri]
        try:
            info = self._klant().get("/playlists/" + uri.rsplit(":", 1)[-1], {"fields": "name"}) or {}
            namen[uri] = info.get("name") or ""
        except Exception:
            namen[uri] = ""
        return namen[uri]

    def stap(self):
        """Haalt de nieuwe items op; geeft het aantal genoteerde playlists terug."""

        if not _aan():
            return 0
        klant = self._klant()
        if not klant.is_gekoppeld():
            return 0
        items = (klant.get("/me/player/recently-played", {"limit": 50}) or {}).get("items") or []
        with _lock:
            staat = lees(self.pad)
            tot = float(staat.get("spotify_tot") or 0)
            nieuw = []
            for item in items:
                t = _iso_naar_ts(item.get("played_at"))
                context = item.get("context") or {}
                if t is None or t <= tot or context.get("type") != "playlist" or not context.get("uri"):
                    continue
                nieuw.append((t, context["uri"]))
            nieuw.sort()
            if items:
                tijden = [x for x in (_iso_naar_ts(i.get("played_at")) for i in items) if x is not None]
                if tijden:
                    staat["spotify_tot"] = max([tot] + tijden)
            laatst = {}
            for g in staat["gebeurtenissen"]:
                if g.get("soort") == "muziek":
                    laatst[g["actie"]["uri"]] = max(laatst.get(g["actie"]["uri"], 0), g["t"])
            namen = self._namen()
            geteld = 0
            for t, uri in nieuw:
                if t - laatst.get(uri, 0) < SESSIE_MIN * 60:
                    continue
                laatst[uri] = t
                naam = self._naam(uri, namen) or "uw playlist"
                staat["gebeurtenissen"].append({
                    "t": t, "soort": "muziek", "sleutel": f"muziek|{uri}",
                    "label": f"uw playlist '{naam}'", "actie": {"type": "muziek", "uri": uri, "naam": naam}})
                geteld += 1
            schrijf(staat, self.pad)
        return geteld


def _iso_naar_ts(tekst):
    if not tekst:
        return None
    try:
        return datetime.fromisoformat(str(tekst).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# -----------------------------------------------------------------
# M2 — patronen vinden
# -----------------------------------------------------------------

def dagtype(dt):
    return "weekend" if dt.weekday() >= 5 else "werkdag"


def _minuut(dt):
    return dt.hour * 60 + dt.minute


def _patroon_id(sleutel, dtype, minuut):
    return hashlib.sha1(f"{sleutel}|{dtype}|{round(minuut / 60)}".encode("utf-8")).hexdigest()[:10]


def vind_patronen(gebeurtenissen, nu=None):
    """De patronen in de laatste twee weken, nieuwste eerst niet van belang.

    Per (actie, doordeweeks/weekend): het tijdstip waar de meeste
    verschillende dagen binnen ±30 minuten vallen; minstens drie dagen.
    Daarna opnieuw met wat overblijft (bijv. 's ochtends én 's avonds).
    """

    nu = nu or datetime.now()
    grens = (nu - timedelta(days=VENSTER_DAGEN)).timestamp()
    groepen = {}
    for g in gebeurtenissen:
        if not isinstance(g, dict) or g.get("soort") not in SOORTEN or g.get("t", 0) < grens:
            continue
        dt = datetime.fromtimestamp(g["t"])
        groepen.setdefault((g["sleutel"], dagtype(dt)), []).append((dt.date(), _minuut(dt), g))

    patronen = []
    for (sleutel, dtype), items in groepen.items():
        over = list(items)
        while over:
            beste = None
            for _, m, _g in over:
                rond = [x for x in over if abs(x[1] - m) <= MARGE_MIN]
                dagen = len({x[0] for x in rond})
                if beste is None or dagen > beste[0]:
                    beste = (dagen, rond)
            dagen, rond = beste
            if dagen < MIN_DAGEN:
                break
            minuten = sorted(x[1] for x in rond)
            minuut = minuten[len(minuten) // 2]
            laatste = max(rond, key=lambda x: x[2]["t"])[2]
            patronen.append({
                "id": _patroon_id(sleutel, dtype, minuut),
                "sleutel": sleutel, "soort": laatste["soort"], "dagtype": dtype,
                "minuut": minuut, "dagen": dagen, "label": laatste["label"], "actie": laatste["actie"],
            })
            over = [x for x in over if x not in rond]
    patronen.sort(key=lambda p: (p["dagtype"], p["minuut"]))
    return patronen


def tijd_tekst(minuut):
    return f"{minuut // 60:02d}:{minuut % 60:02d}"


def vraag_voor(patroon):
    if patroon["soort"] == "muziek":
        return f"Sir, rond deze tijd draait u vaak {patroon['label']}. Zal ik hem opzetten?"
    return f"Sir, rond deze tijd zet u meestal {patroon['label']}. Zal ik dat doen?"


def _is_stil_ingesteld(inst, nu_ts):
    return bool(inst.get("uit")) or float(inst.get("stil_tot") or 0) > nu_ts


def _std_stil():
    from core import welzijn

    try:
        return welzijn._std_stil()
    except Exception:
        return True


class PatroonPlanner:
    """Kijkt elke minuut of er een patroon aan de beurt is en vraagt het."""

    def __init__(self, meld_fn=None, klok=None, stil_fn=None, pad=None, interval=60,
                 verzamelaar=None, muziek_interval=1800):
        self.meld_fn = meld_fn
        self.klok = klok or datetime.now
        self.stil_fn = stil_fn or _std_stil
        self.pad = pad
        self.interval = interval
        self.verzamelaar = verzamelaar
        self.muziek_interval = muziek_interval
        self._muziek_laatst = 0.0
        self._stop = threading.Event()
        self._thread = None

    def stap(self):
        """Eén controle; geeft het gestelde voorstel terug (of None)."""

        if not _aan():
            return None
        nu = self.klok()
        nu_ts = nu.timestamp()
        try:
            if self.stil_fn():
                return None
        except Exception:
            return None
        from core import confirmation

        if confirmation.get_pending():
            return None  # er loopt al een vraag
        with _lock:
            staat = lees(self.pad)
            vandaag = nu.date().isoformat()
            m = _minuut(nu)
            for p in vind_patronen(staat["gebeurtenissen"], nu):
                if p["dagtype"] != dagtype(nu):
                    continue
                if not (p["minuut"] - VOORAF_MIN <= m <= p["minuut"] + LAAT_MIN):
                    continue
                if staat["gevraagd"].get(p["id"]) == vandaag:
                    continue
                if _is_stil_ingesteld(staat["instellingen"].get(p["id"]) or {}, nu_ts):
                    continue
                staat["gevraagd"][p["id"]] = vandaag
                al_gedaan = any(
                    g.get("sleutel") == p["sleutel"] and abs(g["t"] - nu_ts) <= MARGE_MIN * 60
                    for g in staat["gebeurtenissen"])
                if al_gedaan:
                    schrijf(staat, self.pad)
                    continue
                staat["laatste"] = p["id"]
                schrijf(staat, self.pad)
                return self._vraag(p)
        return None

    def _vraag(self, p):
        from core import confirmation

        vraag = vraag_voor(p)
        confirmation.set_pending(KIND, {
            "patroon": p["id"], "actie_info": p["actie"], "label": p["label"], "question": vraag,
            "action": p["label"][0].upper() + p["label"][1:] if p["soort"] == "lamp" else f"{p['label']} opzetten",
        }, ttl=VOORSTEL_TTL)
        if self.meld_fn is not None:
            try:
                self.meld_fn(vraag, bron="patroon")
            except Exception:
                logger.debug("Kon het voorstel niet melden.", exc_info=True)
        return vraag

    def _verzamel(self):
        if _time.monotonic() - self._muziek_laatst < self.muziek_interval:
            return
        self._muziek_laatst = _time.monotonic()
        try:
            (self.verzamelaar or MuziekVerzamelaar()).stap()
        except Exception:
            logger.debug("Kon de Spotify-geschiedenis niet lezen.", exc_info=True)

    def _lus(self):
        while not self._stop.wait(self.interval):
            self._verzamel()
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout bij de patronen.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-patronen", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()


# -----------------------------------------------------------------
# Ja / nee / nooit meer
# -----------------------------------------------------------------

def _info(pending):
    bron = pending if pending.get("actie_info") else (pending.get("payload") or {})
    return bron.get("patroon"), bron.get("actie_info") or {}


def voer_actie_uit(actie):
    if actie.get("type") == "lamp":
        from core.home_assistant import control_home_assistant_tool

        data = {"brightness_pct": actie["helderheid"]} if actie.get("helderheid") and actie.get("service") == "turn_on" else None
        return control_home_assistant_tool("light", actie.get("service"), actie.get("entity"), data)
    if actie.get("type") == "muziek":
        from core import spotify_smaak

        return spotify_smaak.speel({"naam": actie.get("naam", ""), "artiest": "", "uri": actie.get("uri"),
                                    "playlist": True})
    return "Ik weet niet meer wat ik voorstelde, sir."


def na_ja(pending, pad=None):
    pid, actie = _info(pending)
    if pid:
        with _lock:
            staat = lees(pad)
            inst = staat["instellingen"].setdefault(pid, {})
            inst["nee"] = 0
            schrijf(staat, pad)
    if not actie:
        return "Ik weet niet meer wat ik voorstelde, sir."
    return voer_actie_uit(actie)


def na_nee(pending, pad=None, nu=None):
    pid, _ = _info(pending)
    if not pid:
        return "Goed, sir."
    with _lock:
        staat = lees(pad)
        inst = staat["instellingen"].setdefault(pid, {})
        inst["nee"] = int(inst.get("nee") or 0) + 1
        if inst["nee"] >= NEE_DREMPEL:
            inst["nee"] = 0
            inst["stil_tot"] = (nu or _time.time()) + STIL_DAGEN * 86400
            schrijf(staat, pad)
            return "Goed, sir; dat stel ik de komende twee weken niet meer voor."
        schrijf(staat, pad)
    return "Goed, sir; vandaag niet."


_NOOIT_MEER = re.compile(
    r"\b(stel\s+(dat|dit|het)\s+nooit\s+meer\s+voor|nooit\s+meer\s+voorstellen|"
    r"vraag\s+(dat|dit|het)\s+nooit\s+meer|vergeet\s+(dat|dit|het)\s+patroon)\b", re.IGNORECASE)


def is_nooit_meer(tekst):
    return bool(_NOOIT_MEER.search(str(tekst or "")))


def nooit_meer(pid=None, pad=None):
    """Zet het (laatst voorgestelde) patroon voorgoed uit."""

    with _lock:
        staat = lees(pad)
        pid = pid or staat.get("laatste")
        if not pid:
            return "Ik heb nog niets voorgesteld om te vergeten, sir."
        staat["instellingen"].setdefault(pid, {})["uit"] = True
        schrijf(staat, pad)
    return "Goed, sir; dat stel ik nooit meer voor."


# -----------------------------------------------------------------
# M3 — muziek bij focus
# -----------------------------------------------------------------

def focus_playlist(gebeurtenissen, nu=None):
    """De playlist die u minstens drie keer in twee weken kort na "focus aan" draaide."""

    nu = nu or datetime.now()
    grens = (nu - timedelta(days=VENSTER_DAGEN)).timestamp()
    focus = [g["t"] for g in gebeurtenissen if isinstance(g, dict) and g.get("soort") == "focus" and g["t"] >= grens]
    muziek = [g for g in gebeurtenissen if isinstance(g, dict) and g.get("soort") == "muziek" and g["t"] >= grens - 600]
    tellingen = {}
    for f in focus:
        gezien = set()
        for g in muziek:
            if -5 * 60 <= g["t"] - f <= FOCUS_MUZIEK_MIN * 60 and g["sleutel"] not in gezien:
                gezien.add(g["sleutel"])
                dag = datetime.fromtimestamp(f).date()
                tellingen.setdefault(g["sleutel"], {"dagen": set(), "g": g})["dagen"].add(dag)
                tellingen[g["sleutel"]]["g"] = g
    beste = None
    for sleutel, info in tellingen.items():
        if len(info["dagen"]) >= MIN_DAGEN and (beste is None or len(info["dagen"]) > len(beste["dagen"])):
            beste = info
    if beste is None:
        return None
    g = beste["g"]
    return {"id": _patroon_id(g["sleutel"], "focus", 0), "sleutel": g["sleutel"], "soort": "muziek",
            "dagtype": "focus", "minuut": None, "dagen": len(beste["dagen"]), "label": g["label"], "actie": g["actie"]}


def voorstel_bij_focus(pad=None, nu=None):
    """Na "focus aan": de vraag om de focus-playlist op te zetten, of ''."""

    if not _aan():
        return ""
    try:
        with _lock:
            staat = lees(pad)
            p = focus_playlist(staat["gebeurtenissen"], nu)
            if p is None or _is_stil_ingesteld(staat["instellingen"].get(p["id"]) or {}, _time.time()):
                return ""
            staat["laatste"] = p["id"]
            schrijf(staat, pad)
        from core import confirmation

        vraag = f"Zal ik {p['label']} opzetten, sir?"
        confirmation.set_pending(KIND, {"patroon": p["id"], "actie_info": p["actie"], "label": p["label"],
                                        "question": vraag, "action": f"{p['label']} opzetten"}, ttl=VOORSTEL_TTL)
        return " " + vraag
    except Exception:
        logger.debug("Geen focus-voorstel.", exc_info=True)
        return ""


# -----------------------------------------------------------------
# M4 — beheer
# -----------------------------------------------------------------

def overzicht(pad=None, nu=None):
    """Alle patronen met hun stand, voor de stem en de iPad."""

    nu = nu or datetime.now()
    staat = lees(pad)
    lijst = vind_patronen(staat["gebeurtenissen"], nu)
    focus = focus_playlist(staat["gebeurtenissen"], nu)
    if focus:
        lijst.append(focus)
    uit = []
    for p in lijst:
        inst = staat["instellingen"].get(p["id"]) or {}
        stil_tot = float(inst.get("stil_tot") or 0)
        uit.append({
            "id": p["id"], "soort": p["soort"], "label": p["label"], "dagtype": p["dagtype"],
            "tijd": tijd_tekst(p["minuut"]) if p["minuut"] is not None else None, "dagen": p["dagen"],
            "aan": not inst.get("uit"),
            "stil_tot": datetime.fromtimestamp(stil_tot).date().isoformat() if stil_tot > nu.timestamp() else None,
        })
    return uit


_DAGTYPE = {"werkdag": "doordeweeks", "weekend": "in het weekend"}


def beschrijf(pad=None, nu=None):
    lijst = [p for p in overzicht(pad, nu) if p["aan"]]
    if not lijst:
        return "Ik heb nog geen vaste gewoontes van u geleerd, sir. Daarvoor moet ik iets minstens drie keer in twee weken rond hetzelfde tijdstip zien."
    zinnen = []
    for p in lijst[:5]:
        werkwoord = "draait u" if p["soort"] == "muziek" else "zet u"
        if p["dagtype"] == "focus":
            zinnen.append(f"bij de focus draait u vaak {p['label']}")
        else:
            zinnen.append(f"{_DAGTYPE[p['dagtype']]} rond {p['tijd']} {werkwoord} {p['label']}")
    tekst = "Dit heb ik geleerd, sir: " + "; ".join(zinnen) + "."
    if len(lijst) > 5:
        tekst += f" En nog {len(lijst) - 5} meer; die staan op de iPad."
    return tekst


def beheer(pid, actie, pad=None, nu=None):
    """``actie``: "aan", "uit" of "wissen". Geeft True als het patroon bestond."""

    with _lock:
        staat = lees(pad)
        nu = nu or datetime.now()
        lijst = vind_patronen(staat["gebeurtenissen"], nu)
        focus = focus_playlist(staat["gebeurtenissen"], nu)
        if focus:
            lijst.append(focus)
        p = next((x for x in lijst if x["id"] == pid), None)
        if p is None:
            return False
        if actie in ("aan", "uit"):
            inst = staat["instellingen"].setdefault(pid, {})
            inst["uit"] = actie == "uit"
            if actie == "aan":
                inst.pop("stil_tot", None)
                inst["nee"] = 0
        elif actie == "wissen":
            if p["dagtype"] == "focus":
                weg = lambda g: g.get("sleutel") == p["sleutel"]  # noqa: E731
            else:
                def weg(g):
                    if g.get("sleutel") != p["sleutel"]:
                        return False
                    dt = datetime.fromtimestamp(g["t"])
                    return dagtype(dt) == p["dagtype"] and abs(_minuut(dt) - p["minuut"]) <= MARGE_MIN
            staat["gebeurtenissen"] = [g for g in staat["gebeurtenissen"] if not weg(g)]
            staat["instellingen"].pop(pid, None)
        else:
            return False
        schrijf(staat, pad)
    return True


_GELEERD = re.compile(
    r"^wat\s+(heb\s+je|weet\s+je)\s+(van|over)\s+mij\s+(geleerd|gezien|ontdekt)$"
    r"|^welke\s+(gewoontes|gewoonten|patronen)\s+(heb|ken|weet)\s+je(\s+(van|over)\s+mij)?(\s+(geleerd|gezien|ontdekt))?$"
    r"|^wat\s+(heb\s+je|weet\s+je)\s+(van|over)\s+mijn\s+(gewoontes|gewoonten|patronen)(\s+geleerd)?$"
    r"|^wat\s+zijn\s+mijn\s+(gewoontes|gewoonten|patronen)$", re.IGNORECASE)


def probeer_commando(command, pad=None):
    tekst = " ".join(str(command or "").strip().rstrip("?.!").split())
    if not tekst:
        return None
    if is_nooit_meer(tekst):
        return nooit_meer(pad=pad)
    if _GELEERD.search(tekst):
        return beschrijf(pad)
    return None
