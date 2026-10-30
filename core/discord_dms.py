"""Discord-DM's lezen en beantwoorden via de game-pc (Fase 23, M6).

Het brein vraagt de game-pc-agent om de Discord-meldingen uit Windows
(:mod:`actions.discord_meldingen`). Geen selfbot, geen account-token.

* "heb ik nieuwe DM's?" leest de DM's voor die u nog niet kent.
* "wat stuurde Sem?" / "lees de DM van Sem voor" geeft de laatste van Sem.
* "antwoord Sem: ik kom zo" leest voor aan wie en wat, en verstuurt pas na
  een strikte ja: JARVIS typt het dan in de Discord-app op de game-pc.
  Alleen aan iemand die u een DM stuurde (die naam staat in de melding),
  zodat het snel-wisselen van Discord nooit bij een vreemde uitkomt.
* :class:`DiscordPlanner` leest nieuwe DM's bij binnenkomst voor, maar niet
  's nachts, in de stille modus, tijdens de film-modus of als er op de
  game-pc iets op volledig scherm draait (gamen). Die blijven "nieuw" tot u
  ernaar vraagt.

De tekst van een DM is data, geen opdracht: JARVIS leest hem alleen voor.
"""

import logging
import os
import re
import threading

from core import koppelingen

logger = logging.getLogger("jarvis.discord")

GEZIEN_FILE = os.path.join(koppelingen.MAP, "discord_gezien.json")
MAX_GEZIEN = 300
MAX_NOEMEN = 3
MAX_VOORLEZEN = 200       # tekens per DM in een melding of overzicht
MAX_ANTWOORD = 500
VERSTUUR_KIND = "discord_versturen"
VERSTUUR_TTL = 120

GAME_PC_UIT = ("De game-pc staat uit of is niet bereikbaar, sir; Discord-DM's lees ik "
               "via de meldingen op die pc.")


def _config():
    import config

    return config


# -----------------------------------------------------------------
# Game-pc
# -----------------------------------------------------------------

def _std_pc(tool, args):
    from remote import tools as remote_tools

    return remote_tools.execute_remote_tool(tool, args, question="discord")


def _gegeven(resultaat, sleutel):
    from core.filmmodus import _gegeven as gegeven

    return gegeven(resultaat, sleutel)


def _gelukt(resultaat):
    """De agent antwoordt altijd "ok"; of de actie zelf lukte staat erbinnen."""

    if not getattr(resultaat, "ok", False):
        return False
    binnen = (getattr(resultaat, "data", None) or {}).get("resultaat")
    return not (isinstance(binnen, dict) and binnen.get("ok") is False)


def _binnen_melding(resultaat):
    binnen = (getattr(resultaat, "data", None) or {}).get("resultaat")
    if isinstance(binnen, dict) and binnen.get("message"):
        return str(binnen["message"])
    return getattr(resultaat, "message", "") or ""


class DiscordKlant:
    """Dunne laag om de twee game-pc-acties."""

    def __init__(self, pc_fn=None):
        self.pc_fn = pc_fn or _std_pc
        self.volledig_scherm = False

    def dms(self):
        """De DM's (nieuwste eerst), of ``None`` als de game-pc niet antwoordt."""

        r = self.pc_fn("game_pc_discord_dms", {})
        if not _gelukt(r):
            return None
        dms = _gegeven(r, "dms")
        self.volledig_scherm = bool(_gegeven(r, "volledig_scherm"))
        if not isinstance(dms, list):
            return None
        return [d for d in dms if isinstance(d, dict) and d.get("id") and d.get("van")]

    def stuur(self, naam, tekst):
        """``(status, melding)``; status is geslaagd, mislukt of onzeker."""

        r = self.pc_fn("game_pc_discord_antwoord", {"naam": naam, "tekst": tekst})
        if _gelukt(r):
            return "geslaagd", None
        data = getattr(r, "data", None) or {}
        return "onzeker" if data.get("status") == "onzeker" else "mislukt", _binnen_melding(r)


# -----------------------------------------------------------------
# Wat al gelezen of gemeld is
# -----------------------------------------------------------------

def _lees_staat(pad):
    data = koppelingen.lees_json(pad) or {}
    return [str(i) for i in data.get("gelezen") or []], [str(i) for i in data.get("gemeld") or []]


def _bewaar_staat(pad, gelezen, gemeld):
    koppelingen.schrijf_json(pad, {"gelezen": gelezen[-MAX_GEZIEN:], "gemeld": gemeld[-MAX_GEZIEN:]})


def markeer_gelezen(dms, pad=None):
    pad = pad or GEZIEN_FILE
    gelezen, gemeld = _lees_staat(pad)
    nieuw = [d["id"] for d in dms if d["id"] not in gelezen]
    if nieuw:
        _bewaar_staat(pad, gelezen + nieuw, gemeld + [i for i in nieuw if i not in gemeld])


def ongelezen(dms, pad=None):
    gelezen, _ = _lees_staat(pad or GEZIEN_FILE)
    return [d for d in dms if d["id"] not in gelezen]


# -----------------------------------------------------------------
# Teksten
# -----------------------------------------------------------------

def _kort(tekst, maximaal=MAX_VOORLEZEN):
    tekst = re.sub(r"\s+", " ", str(tekst or "")).strip()
    if len(tekst) > maximaal:
        tekst = tekst[:maximaal].rsplit(" ", 1)[0] + "…"
    return tekst


def _regel(dm):
    tekst = _kort(dm.get("tekst")) or "(geen tekst)"
    if tekst[-1] not in ".!?…":
        tekst += "."
    return f"{dm['van']}: {tekst}"


def overzicht(dms, kop_een, kop_meer):
    """Eén DM op één regel, meer DM's als lijstje (oudste eerst)."""

    dms = list(reversed(dms))
    if len(dms) == 1:
        return f"{kop_een} {_regel(dms[0])}"
    regels = [kop_meer.format(n=len(dms))]
    regels += [_regel(d) for d in dms[-MAX_NOEMEN:]]
    if len(dms) > MAX_NOEMEN:
        regels.append(f"En nog {len(dms) - MAX_NOEMEN} eerder.")
    return "\n".join(regels)


def _vergelijk(tekst):
    return re.sub(r"[^\w]+", "", (tekst or "").casefold())


def zoek_afzender(naam, dms):
    """De afzendernaam(en) uit de DM's die bij ``naam`` passen."""

    gezocht = _vergelijk(naam)
    if not gezocht:
        return []
    namen = []
    for d in dms:
        if d["van"] not in namen:
            namen.append(d["van"])
    exact = [n for n in namen if _vergelijk(n) == gezocht]
    if exact:
        return exact[:1]
    return [n for n in namen if _vergelijk(n).startswith(gezocht) or gezocht in _vergelijk(n)]


# -----------------------------------------------------------------
# Commando's
# -----------------------------------------------------------------

_DM = r"(?:dm'?s|dm|dm-?jes?|discord-?berichten|discord\s+berichten|berichten\s+(?:op|in)\s+discord)"

_NIEUW = re.compile(
    r"^(?:heb\s+ik|zijn\s+er|is\s+er)\s+(?:nog\s+)?(?:nieuwe\s+|ongelezen\s+)?(?:een\s+)?" + _DM +
    r"(?:\s+(?:binnen|gekregen|ontvangen))?$"
    r"|^(?:heb\s+ik|zijn\s+er)\s+(?:nog\s+)?(?:nieuwe\s+)?berichten\s+(?:op|in)\s+discord$"
    r"|^(?:lees|check|bekijk)\s+(?:mijn|de)\s+(?:nieuwe\s+)?" + _DM + r"(?:\s+voor)?$"
    r"|^nieuwe\s+" + _DM + r"$"
)

_LEES_VAN = re.compile(
    r"^(?:lees|vertel)\s+(?:de|het|mijn|me|mij)?\s*(?:laatste\s+)?(?:dm|discord-?bericht|bericht\s+op\s+discord)"
    r"\s+van\s+(?P<van>.+?)\s+(?:voor|op)$"
    r"|^wat\s+(?:stuurde|schreef)\s+(?P<van2>.+?)(?:\s+(?:me|mij))?(?:\s+(?:op|in|via)\s+discord)?$"
)

# "antwoord Sem: ik kom zo", "antwoord Sem op discord: ik kom zo",
# "stuur Sem op discord: ik kom zo", "beantwoord de dm van Sem met ik kom zo"
_ANTWOORD = re.compile(
    r"^(?:antwoord|reageer\s+op)\s+(?P<van>[^:]{1,40}?)(?:\s+(?:op|in|via)\s+discord)?\s*:\s*(?P<tekst>\S.*)$"
    r"|^stuur\s+(?P<van2>[^:]{1,40}?)\s+(?:op|via)\s+discord\s*:?\s*(?P<tekst2>\S.*)$"
    r"|^(?:beantwoord|antwoord\s+op|reageer\s+op)\s+(?:de|het|mijn)\s+(?:laatste\s+)?(?:dm|discord-?bericht)"
    r"\s+van\s+(?P<van3>.+?)\s*(?:\s+met|:)\s*:?\s*(?P<tekst3>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Gesproken, dus zonder dubbele punt: "antwoord Sem ik kom zo",
# "antwoord Sem, ik kom zo", "stuur Sem terug dat ik zo kom".
_ANTWOORD_VRIJ = re.compile(
    r"^(?:antwoord|beantwoord|reageer\s+op|stuur)\s+(?P<rest>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Wat er tussen de naam en het bericht kan staan.
_TUSSEN = re.compile(
    r"^(?:[,:;.!-]+\s*|(?:op|in|via)\s+discord\b\s*|(?:met|dat|terug)\b\s*)",
    re.IGNORECASE,
)

_AANLOOP = r"^(?:jarvis[, ]+)?(?:kun\s+je|kan\s+je|wil\s+je)\s+"

# "antwoord Sem: ..." waarbij "Sem" eigenlijk een mail- of agendawoord is,
# of een zin ("antwoord op de vraag: ...").
_GEEN_NAAM = re.compile(
    r"\b(?:mail|e-?mail|mailtje|agenda|afspraak|vraag)\b|^(?:op|de|het|een|mijn|je|jij|u|me|mij)\b"
    r"|^\S+(?:\s+\S+){3,}$",
    re.IGNORECASE,
)


def herken(command):
    """``(soort, naam, tekst)`` of ``None``; soort is nieuw, lees of antwoord."""

    origineel = re.sub(r"\s+", " ", (command or "").strip())
    origineel = re.sub(_AANLOOP, "", origineel, flags=re.IGNORECASE)
    m = _ANTWOORD.match(origineel)
    if m:
        naam = (m.group("van") or m.group("van2") or m.group("van3") or "").strip()
        tekst = (m.group("tekst") or m.group("tekst2") or m.group("tekst3") or "").strip()
        if naam and not _GEEN_NAAM.search(naam):
            return "antwoord", naam, tekst
        return None
    m = _ANTWOORD_VRIJ.match(origineel)
    if m and not _GEEN_NAAM.search(" ".join(m.group("rest").replace(",", " ").split()[:2])):
        # Zonder dubbele punt weet alleen de DM-lijst waar de naam ophoudt.
        return "antwoord_vrij", None, m.group("rest").strip()
    tekst = origineel.lower().rstrip(" ?.!")
    if _NIEUW.match(tekst):
        return "nieuw", None, None
    m = _LEES_VAN.match(tekst)
    if m:
        naam = (m.group("van") or m.group("van2") or "").strip()
        if naam and not _GEEN_NAAM.search(naam):
            return "lees", naam, None
    return None


def nieuwe_dms(klant, pad=None):
    dms = klant.dms()
    if dms is None:
        return GAME_PC_UIT
    nieuw = ongelezen(dms, pad)
    if not nieuw:
        return "Geen nieuwe DM's, sir."
    markeer_gelezen(nieuw, pad)
    return overzicht(nieuw, "Eén nieuwe DM, van", "{n} nieuwe DM's:")


def lees_van(klant, naam, dms=None, pad=None):
    dms = klant.dms() if dms is None else dms
    if dms is None:
        return GAME_PC_UIT
    namen = zoek_afzender(naam, dms)
    if not namen:
        return f"Ik zie geen recente DM van {naam}, sir."
    if len(namen) > 1:
        return f"Bedoelt u {' of '.join(namen)}, sir?"
    van = [d for d in dms if d["van"] == namen[0]][:MAX_NOEMEN]
    markeer_gelezen(van, pad)
    return overzicht(van, "De laatste DM van", f"De laatste {{n}} DM's van {namen[0]}:")


def vraag_tekst(naam, tekst):
    return f"Aan {naam} op Discord:\n\"{tekst}\"\nZal ik het versturen?"


def vraag_versturen(naam, tekst):
    from core import confirmation

    vraag = vraag_tekst(naam, tekst)
    confirmation.set_pending(VERSTUUR_KIND, {
        "naam": naam,
        "tekst": tekst,
        "question": vraag,
        "action": "Discord-DM versturen",
        "target": naam,
    }, ttl=VERSTUUR_TTL)
    return vraag


def antwoord(klant, naam, tekst, dms=None):
    tekst = re.sub(r"\s+", " ", tekst or "").strip()
    if not tekst:
        return f"Wat wilt u {naam} terugsturen, sir? Zeg bijvoorbeeld: antwoord {naam} ik kom zo."
    if len(tekst) > MAX_ANTWOORD:
        return f"Dat is te lang voor één DM, sir (hooguit {MAX_ANTWOORD} tekens)."
    dms = klant.dms() if dms is None else dms
    if dms is None:
        return GAME_PC_UIT
    namen = zoek_afzender(naam, dms)
    if not namen:
        return (f"Ik zie geen recente DM van {naam}, sir. Ik antwoord alleen aan wie u "
                "een DM stuurde.")
    if len(namen) > 1:
        return f"Bedoelt u {' of '.join(namen)}, sir? Zeg de naam zoals in Discord."
    return vraag_versturen(namen[0], tekst)


def splits_naam(rest, dms):
    """``(naam, tekst)`` uit "Sem ik kom zo", of ``None`` als er geen afzender voorop staat.

    Eerst de langste exacte afzendernaam (tot 3 woorden, "Sem de Vries"),
    anders een begin van een naam ("sem" voor "Sem_04"). Zo weet JARVIS
    zonder dubbele punt waar de naam ophoudt en het bericht begint.
    """

    woorden = rest.replace(",", " , ").split()
    namen = []
    for d in dms:
        if d["van"] not in namen:
            namen.append(d["van"])

    def tekst_na(n):
        tekst = " ".join(woorden[n:]).replace(" , ", ", ").strip()
        while True:
            korter = _TUSSEN.sub("", tekst, count=1).strip()
            if korter == tekst:
                return tekst
            tekst = korter

    for n in range(min(3, len(woorden)), 0, -1):
        gezocht = _vergelijk(" ".join(woorden[:n]))
        if gezocht and any(_vergelijk(naam) == gezocht for naam in namen):
            return " ".join(woorden[:n]), tekst_na(n)
    eerste = _vergelijk(woorden[0]) if woorden else ""
    if len(eerste) >= 3 and any(_vergelijk(naam).startswith(eerste) for naam in namen):
        return woorden[0], tekst_na(1)
    return None


def probeer_commando(command, klant_fn=None, pad=None, online_fn=None):
    """``None`` als het geen Discord-vraag is, anders het antwoord."""

    soort = herken(command)
    if soort is None:
        return None
    soort, naam, tekst = soort
    if soort == "antwoord_vrij":
        # "antwoord ..." is vaak geen DM; vraag de game-pc niet als hij uit staat.
        noemt_discord = "discord" in tekst.lower()
        if (online_fn or _std_online)() is False:
            return GAME_PC_UIT if noemt_discord else None
        klant = (klant_fn or DiscordKlant)()
        dms = klant.dms()
        if dms is None:
            return GAME_PC_UIT if noemt_discord else None
        gesplitst = splits_naam(tekst, dms)
        if gesplitst is None:
            return None
        return antwoord(klant, gesplitst[0], gesplitst[1], dms=dms)
    klant = (klant_fn or DiscordKlant)()
    if soort == "nieuw":
        return nieuwe_dms(klant, pad)
    if soort == "antwoord":
        return antwoord(klant, naam, tekst)
    return lees_van(klant, naam, pad=pad)


# -----------------------------------------------------------------
# Versturen na ja
# -----------------------------------------------------------------

def _audit(pending, resultaat, goedgekeurd, reden=None):
    try:
        from core.audit import log_audit

        log_audit(
            gehoord=pending.get("question", ""),
            handler="discord",
            tool="discord_versturen",
            argumenten={"aan": pending.get("naam", ""), "tekens": len(pending.get("tekst", ""))},
            risico="high",
            resultaat=resultaat,
            goedgekeurd=goedgekeurd,
            reden=reden,
            herkomst=pending.get("herkomst"),
        )
    except Exception:
        logger.debug("Auditregel voor Discord mislukte.", exc_info=True)


def _uit_pending(pending):
    bron = pending if pending.get("naam") else (pending.get("payload") or {})
    return dict(pending, naam=bron.get("naam", ""), tekst=bron.get("tekst", ""))


def na_ja(pending, klant=None):
    pending = _uit_pending(pending)
    if not pending["naam"] or not pending["tekst"]:
        return "Ik weet niet meer wat ik moest versturen, sir."
    status, melding = (klant or DiscordKlant()).stuur(pending["naam"], pending["tekst"])
    if status == "geslaagd":
        _audit(pending, "verstuurd", True)
        return f"Verstuurd aan {pending['naam']}, sir."
    if status == "onzeker":
        _audit(pending, "onzeker", True, melding)
        return "Ik weet niet zeker of het is verstuurd, sir; kijk even in Discord."
    _audit(pending, "mislukt", True, melding)
    return f"Versturen lukte niet: {melding or 'onbekende fout.'}"


def na_nee(pending):
    _audit(_uit_pending(pending), "niet verstuurd", False, "geweigerd door de gebruiker")
    return "Oké, ik verstuur het niet."


# -----------------------------------------------------------------
# Voorlezen bij binnenkomst
# -----------------------------------------------------------------

def _std_stil():
    from core import filmmodus, focusmodus, proactive

    # Fase 26, M2: ook tijdens de focusmodus geen DM's voorlezen.
    return (proactive.is_nachtmodus() or proactive.is_quiet() or filmmodus.lees_toestand() is not None
            or focusmodus.is_aan())


def _std_online():
    from beheer import verbinding

    try:
        return verbinding.game_pc_online()
    except Exception:
        return None


class DiscordPlanner:
    """Kijkt elke minuut naar nieuwe DM's en leest ze voor.

    De eerste ronde meldt niets (die DM's kent u al). Als het niet gelegen
    komt, worden nieuwe DM's alleen als *gemeld* onthouden; ze blijven
    ongelezen voor "heb ik nieuwe DM's?".
    """

    def __init__(self, meld_fn=None, klant_fn=None, interval=None, pad=None, stil_fn=None,
                 online_fn=None):
        self.meld_fn = meld_fn
        self.klant_fn = klant_fn or DiscordKlant
        self.interval = interval if interval is not None else _config().DISCORD_CHECK_SECONDEN
        self.pad = pad or GEZIEN_FILE
        self.stil_fn = stil_fn or _std_stil
        self.online_fn = online_fn or _std_online
        self._eerste = not os.path.exists(self.pad)
        self._stop = threading.Event()
        self._thread = None

    def stap(self):
        """Eén controle; geeft de voorgelezen DM's terug."""

        if self.online_fn() is not True:
            return []
        klant = self.klant_fn()
        dms = klant.dms()
        if not dms:
            return []
        gelezen, gemeld = _lees_staat(self.pad)
        nieuw = [d for d in dms if d["id"] not in gelezen and d["id"] not in gemeld]
        if not nieuw:
            return []
        ids = [d["id"] for d in nieuw]
        if self._eerste:
            self._eerste = False
            _bewaar_staat(self.pad, gelezen, gemeld + ids)
            return []
        if self.stil_fn() or klant.volledig_scherm:
            logger.info("Discord: %d nieuwe DM('s), niet voorgelezen (nacht, stil, film of game).", len(nieuw))
            _bewaar_staat(self.pad, gelezen, gemeld + ids)
            return []
        _bewaar_staat(self.pad, gelezen + ids, gemeld + ids)
        if self.meld_fn is not None:
            try:
                self.meld_fn("Sir, " + overzicht(nieuw, "DM van", "{n} nieuwe DM's:"), bron="discord")
            except Exception:
                logger.debug("Kon de Discord-melding niet versturen.", exc_info=True)
        return nieuw

    def _lus(self):
        while not self._stop.wait(self.interval):
            try:
                self.stap()
            except Exception:
                logger.exception("Onverwachte fout bij het controleren van Discord.")

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._lus, name="jarvis-discord", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
