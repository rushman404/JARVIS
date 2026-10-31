"""Self-Evolution: JARVIS verbetert zijn eigen herkenning (Fase 30).

JARVIS past **alleen** ``config/commando_voorbeelden.json`` aan: de
voorbeeldzinnen, opvulwoorden, korte spraakvormen, werkwoorden en namen
waarmee de commando-correctie (Fase 24) een verkeerd gezegd commando
herkent. Nooit Python-code, nooit beveiliging. En altijd pas na uw ja.

* **M1 — voorstel maken:** de missers die vaker misgingen
  (:func:`verzamel_missers`), zonder persoonlijke zinnen (privacy-poort).
  Gemini (hooguit drie verzoeken per ronde) mag alleen *aanvullen*;
  :func:`valideer` kijkt dat streng na en :func:`effect` controleert dat
  minstens één misser er echt beter van wordt.
* **M2 — branch en tests:** :func:`maak_branch` zet de wijziging in een
  eigen git-worktree op een branch ``jarvis/verbetering-…`` en draait de
  volledige test-suite vóór en na. Alleen bij geen nieuwe fouten blijft
  het een voorstel.
* **M3 — goedkeuren:** "installeer de verbetering" (met een strikte ja) of
  Installeren op de iPad: samenvoegen (alleen fast-forward), pushen, de
  voorbeelden opnieuw laden. "Draai de laatste verbetering terug" maakt een
  revert.
* **M4 — wanneer:** zondagnacht vanzelf (:class:`ZelfverbeterPlanner`) en
  "verbeter jezelf". Lukt het niet, dan blijft er een verbeterlijstje voor
  Claude Code op de iPad.
"""

import copy
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time as _time
from datetime import datetime, timedelta

logger = logging.getLogger("jarvis.zelfverbetering")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOORBEELDEN_PAD = os.path.join("config", "commando_voorbeelden.json")
STATUS_FILE = os.path.join(PROJECT, "memory", "zelfverbetering.json")

MIN_KEER = 2                # zo vaak moet een zin misgaan
MIN_WOORDEN = 2             # een los woord ("sluit") valt niet te verbeteren
RECENT_DAGEN = 30           # oudere missers zijn vaak al opgelost
WACHT_NA_FOUT = (5, 20)     # seconden wachten na een serverfout of leeg antwoord
MAX_MISSERS = 15            # zoveel zinnen hooguit naar Gemini
MAX_VERZOEKEN = 3           # Gemini-verzoeken per ronde
MAX_TOEVOEGINGEN = 25
MAX_LENGTE = 60
TEST_TIMEOUT = 1800         # seconden voor één volledige test-run
GIT_TIMEOUT = 120

KIND = "zelfverbetering"
BRANCH_PREFIX = "jarvis/verbetering-"
_GIT_ID = ("-c", "user.name=JARVIS", "-c", "user.email=jarvis@localhost")

LIJSTVELDEN = ("opvulwoorden", "werkwoorden", "basiswoorden", "namen")
_WOORD = re.compile(r"^[a-z0-9à-ÿ'\-]+$")
_ZIN = re.compile(r"^[a-z0-9à-ÿ %'\-{}]+$")

_lock = threading.RLock()


class VerbeterFout(Exception):
    pass


# -----------------------------------------------------------------
# Status
# -----------------------------------------------------------------

def lees_status(pad=None):
    try:
        with open(pad or STATUS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("voorstel", None)
    data.setdefault("lijstje", None)
    data.setdefault("behandeld", [])
    data.setdefault("geschiedenis", [])
    data.setdefault("laatste_ronde", None)
    data.setdefault("bezig", False)
    return data


def schrijf_status(status, pad=None):
    pad = pad or STATUS_FILE
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    status["behandeld"] = status["behandeld"][-300:]
    status["geschiedenis"] = status["geschiedenis"][-20:]
    tijdelijk = pad + ".tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    os.replace(tijdelijk, pad)


# -----------------------------------------------------------------
# M1 — missers verzamelen
# -----------------------------------------------------------------

def _privacy_ok(zin):
    from core import privacy_poort

    try:
        return privacy_poort.beslis(zin).cloud
    except Exception:
        return False


def verzamel_missers(behandeld=(), lees_fn=None, privacy_fn=None, nu=None):
    """De zinnen die minstens twee keer misgingen en nog niet opgelost zijn.

    ``[{"zin", "keer", "bedoeld"}]``, vaakst eerst. Zinnen die de
    privacy-poort niet naar de cloud laat, vallen weg.
    """

    from core import commando_correctie as cc

    data = (lees_fn or cc._lees)()
    geleerd = data.get("geleerd") or {}
    behandeld = set(behandeld)
    privacy_fn = privacy_fn or _privacy_ok
    grens = ((nu or datetime.now()) - timedelta(days=RECENT_DAGEN)).isoformat(timespec="seconds")
    uit = []
    for zin, regel in (data.get("missers") or {}).items():
        if not isinstance(regel, dict) or zin in geleerd or zin in behandeld:
            continue
        if len(zin.split()) < MIN_WOORDEN or str(regel.get("laatst") or "") < grens:
            continue
        keer = int(regel.get("keer") or 0)
        uitkomsten = regel.get("uitkomsten") or {}
        opgelost = sum(int(uitkomsten.get(u, 0)) for u in (cc.UIT_DIRECT, cc.UIT_GELEERD, cc.UIT_JA))
        if keer < MIN_KEER or opgelost >= keer:
            continue
        if not privacy_fn(zin):
            continue
        uit.append({"zin": zin, "keer": keer, "bedoeld": regel.get("bedoeld")})
    uit.sort(key=lambda m: (-m["keer"], m["zin"]))
    return uit[:MAX_MISSERS]


# -----------------------------------------------------------------
# M1 — Gemini om aanvullingen vragen
# -----------------------------------------------------------------

INSTRUCTIE = """Je verbetert de spraakherkenning van JARVIS, een Nederlandse spraakassistent.
JARVIS verbetert een verkeerd gezegd commando woord voor woord, met het JSON-bestand hieronder,
tot een zin die lijkt op de voorbeeldzinnen bij "herkenners" (die commando's kent hij al):
- "korte_vormen": een woord dat JARVIS niet kent en het woord dat hij wel kent; ook spreektaal
  en synoniemen (bijv. "an": "aan", "knal": "zet", "zachtjes": "zachter"). Dit helpt het meest.
- "opvulwoorden": woorden die weg mogen (bijv. "even", "toch").
- "werkwoorden": woorden waarmee een commando begint.
- "basiswoorden" en "namen": bekende woorden en namen (programma's, games, sites).
- "herkenners": per soort commando voorbeeldzinnen; {naam} staat voor een programma, apparaat, game of site.

Hieronder ook zinnen die JARVIS vaker NIET begreep (met soms wat er bedoeld was).
Stel ALLEEN AANVULLINGEN voor waardoor die zinnen na de verbetering een bekend commando worden.
Niets verwijderen of wijzigen.

Antwoord met precies één JSON-object, zonder uitleg eromheen, met alleen deze velden (laat weg wat je niet nodig hebt):
{"herkenners": {"<bestaande soort>": ["nieuwe voorbeeldzin", ...]},
 "werkwoorden": [...], "opvulwoorden": [...], "basiswoorden": [...], "namen": [...],
 "korte_vormen": {"fout": "goed"},
 "uitleg": "één of twee korte zinnen in het Nederlands, in de u-vorm, wat er beter wordt"}
Regels: kleine letters, korte zinnen (max 60 tekens), alleen bestaande soorten bij "herkenners",
hooguit 25 aanvullingen samen, geen persoonsgegevens."""


def bouw_berichten(data, missers, fout=None):
    zinnen = []
    for m in missers:
        regel = f"- \"{m['zin']}\" ({m['keer']} keer"
        if m.get("bedoeld"):
            regel += f", bedoeld: \"{m['bedoeld']}\""
        zinnen.append(regel + ")")
    bestand = {k: v for k, v in data.items() if not k.startswith("_")}
    gebruiker = ("HUIDIG BESTAND:\n" + json.dumps(bestand, ensure_ascii=False, indent=1)
                 + "\n\nZINNEN DIE MISGINGEN:\n" + "\n".join(zinnen))
    berichten = [{"role": "system", "content": INSTRUCTIE}, {"role": "user", "content": gebruiker}]
    if fout:
        berichten.append({"role": "user", "content": f"Je vorige antwoord was niet bruikbaar: {fout}. Probeer het opnieuw."})
    return berichten


def _std_chat(berichten, json_mode=True):
    from core import gemini

    return gemini.chat(berichten, json_mode=json_mode, temperature=0.2)


def _gemini_beschikbaar():
    try:
        from core import llm

        return llm.gemini_beschikbaar()
    except Exception:
        return False


def _norm(tekst):
    return " ".join(str(tekst or "").lower().split())


def valideer(toevoeging, data):
    """(schone aanvulling, None) of (None, reden). Alleen nieuwe, nette items."""

    if not isinstance(toevoeging, dict):
        return None, "geen JSON-object"
    onbekend = set(toevoeging) - set(LIJSTVELDEN) - {"herkenners", "korte_vormen", "uitleg"}
    if onbekend:
        return None, f"onbekende velden: {', '.join(sorted(onbekend))}"
    schoon, aantal = {}, 0
    for veld in LIJSTVELDEN:
        waarden = toevoeging.get(veld) or []
        if not isinstance(waarden, list):
            return None, f"{veld} is geen lijst"
        bestaand = set(data.get(veld) or [])
        nieuw = []
        for w in waarden:
            w = _norm(w)
            patroon = _ZIN if veld == "namen" else _WOORD
            if not isinstance(w, str) or not w or len(w) > MAX_LENGTE or not patroon.match(w) or "{" in w:
                return None, f"ongeldig item in {veld}: {w!r}"
            if w not in bestaand and w not in nieuw:
                nieuw.append(w)
        if nieuw:
            schoon[veld] = nieuw
            aantal += len(nieuw)
    korte = toevoeging.get("korte_vormen") or {}
    if not isinstance(korte, dict):
        return None, "korte_vormen is geen object"
    bestaand = data.get("korte_vormen") or {}
    nieuw = {}
    for fout, goed in korte.items():
        fout, goed = _norm(fout), _norm(goed)
        if not (_WOORD.match(fout) and _WOORD.match(goed)) or len(fout) > 12 or len(goed) > 20 or fout == goed:
            return None, f"ongeldige korte vorm: {fout!r} → {goed!r}"
        if fout not in bestaand:
            nieuw[fout] = goed
    if nieuw:
        schoon["korte_vormen"] = nieuw
        aantal += len(nieuw)
    herk = toevoeging.get("herkenners") or {}
    if not isinstance(herk, dict):
        return None, "herkenners is geen object"
    bekend = data.get("herkenners") or {}
    schoon_h = {}
    for soort, zinnen in herk.items():
        if soort not in bekend:
            return None, f"onbekende soort: {soort!r}"
        if not isinstance(zinnen, list):
            return None, f"herkenners.{soort} is geen lijst"
        bestaande = set(_norm(z) for z in bekend[soort])
        nieuw = []
        for z in zinnen:
            z = _norm(z)
            if not z or len(z) > MAX_LENGTE or not _ZIN.match(z) or re.sub(r"\{naam\}", "", z).count("{") \
                    or re.sub(r"\{naam\}", "", z).count("}"):
                return None, f"ongeldige voorbeeldzin: {z!r}"
            if z not in bestaande and z not in nieuw:
                nieuw.append(z)
        if nieuw:
            schoon_h[soort] = nieuw
            aantal += len(nieuw)
    if schoon_h:
        schoon["herkenners"] = schoon_h
    if aantal == 0:
        return None, "geen nieuwe aanvullingen"
    if aantal > MAX_TOEVOEGINGEN:
        return None, f"te veel aanvullingen ({aantal})"
    uitleg = " ".join(str(toevoeging.get("uitleg") or "").split())[:300]
    schoon["uitleg"] = uitleg or "Een paar zinnen die ik niet begreep, herken ik voortaan."
    return schoon, None


def pas_toe(data, aanvulling):
    """Een nieuwe kopie van de voorbeelden met de aanvulling erbij."""

    nieuw = copy.deepcopy(data)
    for veld in LIJSTVELDEN:
        if aanvulling.get(veld):
            nieuw[veld] = list(nieuw.get(veld) or []) + aanvulling[veld]
    if aanvulling.get("korte_vormen"):
        nieuw["korte_vormen"] = dict(nieuw.get("korte_vormen") or {}, **aanvulling["korte_vormen"])
    for soort, zinnen in (aanvulling.get("herkenners") or {}).items():
        nieuw.setdefault("herkenners", {})[soort] = list(nieuw["herkenners"].get(soort) or []) + zinnen
    return nieuw


def beschrijf_aanvulling(aanvulling):
    """Leesbare regels voor de iPad: wat erbij komt."""

    regels = []
    namen = {"opvulwoorden": "Opvulwoorden", "werkwoorden": "Werkwoorden",
             "basiswoorden": "Woorden", "namen": "Namen"}
    for soort, zinnen in (aanvulling.get("herkenners") or {}).items():
        regels.append(f"Voorbeelden ({soort.replace('_', ' ')}): " + ", ".join(f"“{z}”" for z in zinnen))
    for veld in LIJSTVELDEN:
        if aanvulling.get(veld):
            regels.append(f"{namen[veld]}: " + ", ".join(aanvulling[veld]))
    if aanvulling.get("korte_vormen"):
        regels.append("Spraakfoutjes: " + ", ".join(f"{a} → {b}" for a, b in aanvulling["korte_vormen"].items()))
    return regels


def _beste(zin, data, namen):
    from core import commando_correctie as cc

    try:
        kandidaten = cc.zoek_kandidaten(zin, namen=namen, data=data)
    except Exception:
        return None
    if not kandidaten or kandidaten[0].score < cc.DREMPEL_VRAGEN:
        return None
    return kandidaten[0].commando


def effect(missers, oud, nieuw, namen=None):
    """(verbeterd, slechter): welke misser-zinnen het voorstel helpt of schaadt."""

    from core import commando_correctie as cc

    if namen is None:
        try:
            namen = cc.bekende_namen()
        except Exception:
            namen = frozenset()
    verbeterd, slechter = [], []
    for m in missers:
        voor, na = _beste(m["zin"], oud, namen), _beste(m["zin"], nieuw, namen)
        doel = cc._norm(m["bedoeld"]) if m.get("bedoeld") else None
        if doel:
            if na == doel and voor != doel:
                verbeterd.append(m["zin"])
            elif voor == doel and na != doel:
                slechter.append(m["zin"])
        elif na and not voor:
            verbeterd.append(m["zin"])
    return verbeterd, slechter


_SOORT_TEKST = {"server": "server te druk", "netwerk": "geen verbinding", "leeg": "leeg antwoord"}


def _fout_tekst(e):
    soort = _SOORT_TEKST.get(getattr(e, "soort", ""), getattr(e, "soort", "fout"))
    status = getattr(e, "status", None)
    return f"{soort}, HTTP {status}" if status else soort


def maak_voorstel(missers, data, chat_fn=None, beschikbaar_fn=None, namen=None, slaap=_time.sleep):
    """Vraagt Gemini om een aanvulling. ``(voorstel | None, reden)``.

    Hooguit :data:`MAX_VERZOEKEN` verzoeken; bij een limiet, sleutel- of
    privacyfout meteen stoppen.
    """

    from core import gemini, privacy_poort

    if not (beschikbaar_fn or _gemini_beschikbaar)():
        return None, "Gemini is niet beschikbaar"
    chat_fn = chat_fn or _std_chat
    fout = None
    json_mode = True
    storingen = []
    for poging in range(MAX_VERZOEKEN):
        berichten = bouw_berichten(data, missers, fout)
        mag, reden = privacy_poort.controleer(berichten)
        if not mag:
            return None, f"privacy: {reden}"
        try:
            antwoord = chat_fn(berichten) if json_mode else chat_fn(berichten, json_mode=False)
        except gemini.GeminiFout as e:
            if getattr(e, "soort", None) in (gemini.SERVER, gemini.NETWERK, gemini.LEEG):
                # Even wachten en opnieuw; na een leeg antwoord zonder JSON-modus.
                storingen.append(_fout_tekst(e))
                logger.info("Zelfverbetering: Gemini gaf geen antwoord (%s).", storingen[-1])
                if getattr(e, "soort", None) == gemini.LEEG:
                    json_mode = False
                if poging < MAX_VERZOEKEN - 1:
                    slaap(WACHT_NA_FOUT[min(poging, len(WACHT_NA_FOUT) - 1)])
                continue
            return None, f"Gemini: {e}"
        inhoud = antwoord.get("message", {}).get("content") if isinstance(antwoord, dict) else None
        tekst = str(inhoud or "")
        begin, eind = tekst.find("{"), tekst.rfind("}")
        try:
            ruw = json.loads(tekst[begin:eind + 1]) if 0 <= begin < eind else None
            if ruw is None:
                raise ValueError("geen JSON")
        except ValueError:
            fout = "geen geldige JSON"
            continue
        aanvulling, fout = valideer(ruw, data)
        if aanvulling is None:
            continue
        nieuw = pas_toe(data, aanvulling)
        verbeterd, slechter = effect(missers, data, nieuw, namen)
        if slechter:
            fout = "deze zinnen werden slechter herkend: " + ", ".join(slechter[:3])
            continue
        if not verbeterd:
            fout = "geen enkele misser wordt hiermee herkend"
            continue
        return {"aanvulling": aanvulling, "data": nieuw, "verbeterd": verbeterd}, None
    if fout:
        return None, fout
    if storingen:
        return None, f"Gemini gaf {len(storingen)}× geen antwoord ({storingen[-1]})"
    return None, "geen bruikbaar voorstel"


# -----------------------------------------------------------------
# M2 — branch en tests
# -----------------------------------------------------------------

def _git(*args, cwd=PROJECT, timeout=GIT_TIMEOUT):
    git = shutil.which("git")
    if not git:
        raise VerbeterFout("Git is niet geïnstalleerd.")
    try:
        uit = subprocess.run([git, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise VerbeterFout(f"git {args[0]} duurde te lang.") from None
    if uit.returncode != 0:
        melding = (uit.stderr or uit.stdout or "").strip().splitlines()
        raise VerbeterFout(f"git {args[0]} mislukt: {melding[-1] if melding else uit.returncode}")
    return uit.stdout.strip()


_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


def draai_tests(map_):
    """``(gelukt, fouten)``: de volledige suite in ``map_``.

    ``gelukt`` is False als pytest niet eens kon draaien (bijv. een
    importfout); ``fouten`` is de set mislukte tests.
    """

    env = dict(os.environ, JARVIS_OLLAMA_DISABLED="1", PYTHONDONTWRITEBYTECODE="1")
    try:
        uit = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", "--no-header"],
            cwd=map_, capture_output=True, text=True, timeout=TEST_TIMEOUT, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, {"(time-out)"}
    fouten = set(_FAILED.findall(uit.stdout or ""))
    return uit.returncode in (0, 1), fouten


def schrijf_voorbeelden(map_, data):
    pad = os.path.join(map_, VOORBEELDEN_PAD)
    with open(pad, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def maak_branch(data, uitleg, git=None, tests_fn=None, nu=None):
    """De wijziging op een eigen branch, getest. Geeft een info-dict.

    ``{"branch", "commit", "nieuw_fout", "basis"}``; bij nieuwe fouten wordt
    de branch weer weggegooid (``commit`` is dan None).
    """

    git = git or _git
    tests_fn = tests_fn or draai_tests
    nu = nu or datetime.now()
    branch = BRANCH_PREFIX + nu.strftime("%Y%m%d-%H%M")
    map_ = tempfile.mkdtemp(prefix="jarvis-verbetering-")
    os.rmdir(map_)
    basis = git("rev-parse", "HEAD")
    git("worktree", "add", "-b", branch, map_, basis)
    commit = None
    try:
        gelukt_voor, fout_voor = tests_fn(map_)
        if not gelukt_voor:
            raise VerbeterFout("de tests draaien niet eens op de huidige versie")
        schrijf_voorbeelden(map_, data)
        gelukt_na, fout_na = tests_fn(map_)
        nieuw_fout = sorted(fout_na - fout_voor) if gelukt_na else ["(de tests draaien niet meer)"]
        if not nieuw_fout:
            git("add", VOORBEELDEN_PAD, cwd=map_)
            git(*_GIT_ID, "commit", "-q", "-m",
                f"feat(zelfverbetering): herkenning aangevuld\n\n{uitleg}", cwd=map_)
            commit = git("rev-parse", "HEAD", cwd=map_)
    finally:
        try:
            git("worktree", "remove", "--force", map_)
        except VerbeterFout:
            shutil.rmtree(map_, ignore_errors=True)
            try:
                git("worktree", "prune")
            except VerbeterFout:
                pass
        if commit is None:
            try:
                git("branch", "-D", branch)
            except VerbeterFout:
                pass
    return {"branch": branch, "commit": commit, "basis": basis, "nieuw_fout": nieuw_fout}


# -----------------------------------------------------------------
# Een ronde (M1 + M2)
# -----------------------------------------------------------------

def _lees_voorbeelden():
    with open(os.path.join(PROJECT, VOORBEELDEN_PAD), encoding="utf-8") as f:
        return json.load(f)


def lijstje_tekst(missers, reden):
    regels = ["JARVIS begreep deze zinnen vaker niet (config/commando_voorbeelden.json aanvullen):"]
    for m in missers:
        regel = f"- \"{m['zin']}\" ({m['keer']}x"
        if m.get("bedoeld"):
            regel += f", bedoeld: \"{m['bedoeld']}\""
        regels.append(regel + ")")
    regels.append(f"Zelf oplossen lukte niet: {reden}.")
    return "\n".join(regels)


def ronde(pad=None, missers_fn=None, voorstel_fn=None, branch_fn=None, data_fn=None, nu=None):
    """Eén volledige ronde. Geeft de uitkomst als korte zin terug."""

    nu = nu or datetime.now()
    with _lock:
        status = lees_status(pad)
        if status.get("voorstel"):
            return "wacht"
        status["laatste_ronde"] = nu.date().isoformat()
        schrijf_status(status, pad)
    missers = (missers_fn or verzamel_missers)(status["behandeld"])
    if not missers:
        with _lock:
            status = lees_status(pad)
            status["lijstje"] = None  # een oud lijstje klopt niet meer
            schrijf_status(status, pad)
        return "niets"
    data = (data_fn or _lees_voorbeelden)()
    voorstel, reden = (voorstel_fn or maak_voorstel)(missers, data)
    if voorstel is not None:
        try:
            info = (branch_fn or maak_branch)(voorstel["data"], voorstel["aanvulling"]["uitleg"], nu=nu)
        except VerbeterFout as fout:
            info, reden = None, str(fout)
        if info and info.get("commit"):
            with _lock:
                status = lees_status(pad)
                status["voorstel"] = {
                    "id": info["commit"][:10], "branch": info["branch"], "commit": info["commit"],
                    "basis": info["basis"], "uitleg": voorstel["aanvulling"]["uitleg"],
                    "wijzigingen": beschrijf_aanvulling(voorstel["aanvulling"]),
                    "verbeterd": voorstel["verbeterd"], "missers": [m["zin"] for m in missers],
                    "gemaakt": nu.isoformat(timespec="minutes"),
                }
                status["lijstje"] = None
                schrijf_status(status, pad)
            return "voorstel"
        if info:
            reden = "de tests faalden daarna: " + ", ".join(info["nieuw_fout"][:3])
    with _lock:
        status = lees_status(pad)
        status["lijstje"] = {"tekst": lijstje_tekst(missers, reden), "reden": reden,
                             "gemaakt": nu.isoformat(timespec="minutes")}
        schrijf_status(status, pad)
    return "lijstje"


UITKOMST_ZIN = {
    "niets": "Er gaat de laatste tijd niets vaak mis, sir; ik hoef niets te verbeteren.",
    "lijstje": "Ik kon het niet zelf oplossen, sir. Op de iPad, bij Instellingen, staat een verbeterlijstje voor Claude Code.",
    "wacht": "Er wacht al een verbetering op uw ja, sir.",
}


def melding_voor(uitkomst, pad=None):
    if uitkomst == "voorstel":
        v = lees_status(pad)["voorstel"]
        return (f"Sir, ik heb een verbetering klaar en alle tests slaagden. {v['uitleg']} "
                "Zeg \"installeer de verbetering\", of bekijk hem op de iPad bij Instellingen.")
    return UITKOMST_ZIN.get(uitkomst, "")


# -----------------------------------------------------------------
# M3 — installeren, weigeren, terugdraaien
# -----------------------------------------------------------------

def _herlaad():
    from core import commando_correctie as cc

    cc.laad_voorbeelden(vernieuw=True)
    cc.bekende_namen(vernieuw=True)


def installeer(pad=None, git=None, herlaad_fn=None):
    """Voegt de verbetering samen en pusht. Geeft de zin voor de gebruiker."""

    git = git or _git
    with _lock:
        status = lees_status(pad)
        v = status.get("voorstel")
        if not v:
            return "Er wacht geen verbetering, sir."
        if git("status", "--porcelain", "--untracked-files=no"):
            return "Er zijn lokale wijzigingen in de code, sir; daarom installeer ik nu niets."
        if git("rev-parse", "HEAD") != v["basis"]:
            _ruim_op(status, v, git, "verlopen")
            schrijf_status(status, pad)
            return ("JARVIS is intussen bijgewerkt, sir, dus deze verbetering past niet meer. "
                    "Zeg \"verbeter jezelf\", dan maak ik hem opnieuw.")
        git("merge", "--ff-only", "--quiet", v["branch"])
        try:
            git("push", "--quiet")
        except VerbeterFout as fout:
            git("reset", "--keep", v["basis"])
            logger.warning("Pushen van de verbetering mislukte: %s", fout)
            return "Pushen naar GitHub lukte niet, sir, dus ik heb niets geïnstalleerd. De verbetering wacht nog."
        (herlaad_fn or _herlaad)()
        status["geschiedenis"].append({"commit": v["commit"], "uitleg": v["uitleg"], "stand": "geïnstalleerd",
                                       "tijd": datetime.now().isoformat(timespec="minutes")})
        _ruim_op(status, v, git, None)
        schrijf_status(status, pad)
    return "Geïnstalleerd, sir. " + v["uitleg"]


def _ruim_op(status, v, git, stand):
    status["behandeld"].extend(z for z in v.get("missers") or [] if z not in status["behandeld"])
    status["voorstel"] = None
    if stand:
        status["geschiedenis"].append({"commit": v["commit"], "uitleg": v["uitleg"], "stand": stand,
                                       "tijd": datetime.now().isoformat(timespec="minutes")})
    try:
        git("branch", "-D", v["branch"])
    except VerbeterFout:
        pass


def weiger(pad=None, git=None):
    git = git or _git
    with _lock:
        status = lees_status(pad)
        v = status.get("voorstel")
        if not v:
            return "Er wacht geen verbetering, sir."
        _ruim_op(status, v, git, "geweigerd")
        schrijf_status(status, pad)
    return "Goed, sir; die verbetering gooi ik weg."


def draai_terug(pad=None, git=None, herlaad_fn=None):
    git = git or _git
    with _lock:
        status = lees_status(pad)
        laatste = next((h for h in reversed(status["geschiedenis"]) if h.get("stand") == "geïnstalleerd"), None)
        if laatste is None:
            return "Ik heb nog geen verbetering geïnstalleerd, sir."
        if git("status", "--porcelain", "--untracked-files=no"):
            return "Er zijn lokale wijzigingen in de code, sir; daarom draai ik nu niets terug."
        voor = git("rev-parse", "HEAD")
        git(*_GIT_ID, "revert", "--no-edit", laatste["commit"])
        try:
            git("push", "--quiet")
        except VerbeterFout:
            git("reset", "--keep", voor)
            return "Pushen naar GitHub lukte niet, sir, dus ik heb niets teruggedraaid."
        (herlaad_fn or _herlaad)()
        laatste["stand"] = "teruggedraaid"
        schrijf_status(status, pad)
    return "Teruggedraaid, sir; de herkenning is weer zoals vóór die verbetering."


# -----------------------------------------------------------------
# M4 — wanneer: op verzoek en wekelijks
# -----------------------------------------------------------------

_meld = {"fn": None}


def zet_meld(meld_fn):
    _meld["fn"] = meld_fn


def _melden(tekst):
    fn = _meld["fn"]
    if fn is None or not tekst:
        return
    try:
        fn(tekst, bron="zelfverbetering")
    except Exception:
        logger.debug("Kon de verbetering niet melden.", exc_info=True)


def _aan():
    import config

    return getattr(config, "ZELFVERBETERING", True)


def start_ronde(pad=None, ronde_fn=None, achtergrond=True):
    """Start een ronde in de achtergrond; meldt de uitkomst."""

    with _lock:
        status = lees_status(pad)
        if status.get("bezig"):
            return False
        status["bezig"] = True
        schrijf_status(status, pad)

    def _werk():
        uitkomst = "lijstje"
        try:
            uitkomst = (ronde_fn or ronde)(pad)
        except Exception:
            logger.exception("Zelfverbetering mislukte.")
        finally:
            with _lock:
                status = lees_status(pad)
                status["bezig"] = False
                schrijf_status(status, pad)
        _melden(melding_voor(uitkomst, pad))

    if achtergrond:
        threading.Thread(target=_werk, name="jarvis-zelfverbetering", daemon=True).start()
    else:
        _werk()
    return True


class ZelfverbeterPlanner:
    """Eén keer per week, zondagnacht tussen 3 en 4 uur."""

    DAG = 6   # zondag
    UUR = 3

    def __init__(self, klok=None, pad=None, start_fn=None, interval=600):
        self.klok = klok or datetime.now
        self.pad = pad
        self.start_fn = start_fn or start_ronde
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def stap(self):
        if not _aan():
            return False
        nu = self.klok()
        if nu.weekday() != self.DAG or nu.hour != self.UUR:
            return False
        status = lees_status(self.pad)
        if status.get("laatste_ronde") == nu.date().isoformat() or status.get("voorstel"):
            return False
        return self.start_fn(self.pad)

    def _lus(self):
        while not self._stop.wait(self.interval):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout in de zelfverbetering-planner.")

    def start(self):
        if self._thread is None:
            # Na een herstart loopt er geen ronde meer, ook al staat "bezig" nog.
            with _lock:
                status = lees_status(self.pad)
                if status.get("bezig"):
                    status["bezig"] = False
                    schrijf_status(status, self.pad)
            self._thread = threading.Thread(target=self._lus, name="jarvis-zelfverbetering-plan", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()


# -----------------------------------------------------------------
# Stemcommando's
# -----------------------------------------------------------------

_VERBETER = re.compile(r"^(verbeter|upgrade)\s+je(zelf)?(\s+maar)?$|^ga\s+jezelf\s+verbeteren$", re.IGNORECASE)
_INSTALLEER = re.compile(r"^(installeer|installeren)\s+(de|die|deze)\s+verbetering$|^verbetering\s+installeren$", re.IGNORECASE)
_WEIGER = re.compile(r"^(weiger|verwijder|gooi)\s+(de|die|deze)\s+verbetering(\s+weg)?$", re.IGNORECASE)
_TERUG = re.compile(r"^draai\s+(de\s+)?laatste\s+verbetering\s+terug$|^maak\s+(de\s+)?laatste\s+verbetering\s+ongedaan$", re.IGNORECASE)
_WAT = re.compile(r"^(wat|welke)\s+(is|was)\s+(de|je|jouw)\s+(laatste\s+)?verbetering$|^welke\s+verbetering\s+heb\s+je$", re.IGNORECASE)


def vraag_installeren(pad=None):
    from core import confirmation

    v = lees_status(pad).get("voorstel")
    if not v:
        return "Er wacht geen verbetering, sir."
    vraag = f"{v['uitleg']} Alle tests slaagden. Zal ik hem installeren?"
    confirmation.set_pending(KIND, {"question": vraag, "action": "De verbetering installeren",
                                    "commit": v["commit"]}, ttl=120)
    return vraag


def na_ja(pending, pad=None):
    v = lees_status(pad).get("voorstel")
    commit = pending.get("commit") or (pending.get("payload") or {}).get("commit")
    if not v or v["commit"] != commit:
        return "Die verbetering wacht niet meer, sir."
    return installeer(pad)


def beschrijf(pad=None):
    status = lees_status(pad)
    v = status.get("voorstel")
    if v:
        return f"Er wacht een verbetering, sir: {v['uitleg']} Zeg \"installeer de verbetering\" of \"weiger de verbetering\"."
    if status.get("bezig"):
        return "Ik ben nog bezig met een verbetering, sir."
    if status.get("lijstje"):
        return "Er wacht geen verbetering, sir; wel een verbeterlijstje op de iPad."
    laatste = status["geschiedenis"][-1] if status["geschiedenis"] else None
    if laatste:
        return f"Mijn laatste verbetering is {laatste['stand']}, sir: {laatste['uitleg']}"
    return "Ik heb mezelf nog niet verbeterd, sir."


def probeer_commando(command, pad=None, start_fn=None):
    tekst = " ".join(str(command or "").strip().rstrip("?.!").split())
    if not tekst:
        return None
    if _VERBETER.match(tekst):
        status = lees_status(pad)
        if status.get("voorstel"):
            return UITKOMST_ZIN["wacht"] + " " + vraag_installeren(pad)
        if not (start_fn or start_ronde)(pad):
            return "Ik ben er al mee bezig, sir."
        return "Ik ga aan de slag, sir. Dat duurt een paar minuten; ik meld het als ik klaar ben."
    if _INSTALLEER.match(tekst):
        return vraag_installeren(pad)
    if _WEIGER.match(tekst):
        return weiger(pad)
    if _TERUG.match(tekst):
        return draai_terug(pad)
    if _WAT.match(tekst):
        return beschrijf(pad)
    return None


# -----------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------

def overzicht(pad=None):
    status = lees_status(pad)
    return {
        "voorstel": status.get("voorstel"),
        "lijstje": status.get("lijstje"),
        "bezig": bool(status.get("bezig")),
        "geschiedenis": list(reversed(status["geschiedenis"][-5:])),
    }
