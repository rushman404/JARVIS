"""Narratie bij routines (Fase 21, M3).

JARVIS vertelt kort wat hij doet terwijl een routine loopt, film-achtig:

    "Gamemodus wordt geactiveerd. Discord geopend. Spotify geopend.
     Volume op 40. Bed lamp op 30 procent. Alles staat klaar, sir."

Per stap komt er één zin zodra die stap klaar is (de executor roept
``Verteller.stap`` aan). Een mislukte stap krijgt een korte melding
("Spotify openen mislukt."). Met ``on_tekst`` klinkt elke zin meteen;
het volledige antwoord is alle zinnen samen.

Uitzetten: ``ROUTINE_NARRATIE=0`` in .env, of ``"narratie": false`` bij
één routine in config/routines.json. Dan geeft JARVIS weer alleen de
omschrijving van de routine als antwoord.
"""

import logging

logger = logging.getLogger(__name__)


def _ha_naam(entity_id):
    """"light.bed_lamp" -> "Bed lamp"."""

    naam = str(entity_id or "").split(".", 1)[-1].replace("_", " ").strip()
    return naam[:1].upper() + naam[1:] if naam else "het apparaat"


def _ha_zin(args):
    domein = args.get("domain", "")
    dienst = args.get("service", "")
    naam = _ha_naam(args.get("entity_id"))
    data = args.get("service_data") or {}
    if domein == "scene":
        return f"Scène {naam.lower()} actief."
    if dienst == "turn_on" and "brightness_pct" in data:
        return f"{naam} op {data['brightness_pct']} procent."
    if dienst == "turn_on":
        return f"{naam} aan."
    if dienst == "turn_off":
        return f"{naam} uit."
    if dienst == "toggle":
        return f"{naam} omgezet."
    if domein == "cover":
        return f"{naam} {'open' if 'open' in dienst else 'dicht' if 'close' in dienst else 'bijgesteld'}."
    return f"{naam} bijgewerkt."


# toolnaam (zonder game_pc_) -> zin in de voltooide tijd
_ZINNEN = {
    "open_program": lambda a: f"{a.get('program', 'Het programma')} geopend.",
    "close_program": lambda a: f"{a.get('program', 'Het programma')} gesloten.",
    "restart_program": lambda a: f"{a.get('program', 'Het programma')} herstart.",
    "open_website": lambda a: "Website geopend.",
    "set_volume": lambda a: f"Volume op {a.get('percent')}.",
    "volume_up": lambda a: "Volume omhoog.",
    "volume_down": lambda a: "Volume omlaag.",
    "media_play_pause": lambda a: "Muziek omgezet.",
    "media_stop": lambda a: "Muziek gestopt.",
    "media_next": lambda a: "Volgend nummer.",
    "media_mute": lambda a: "Geluid omgezet.",
    "media_pause_app": lambda a: f"{a.get('app_name', 'De app')} gepauzeerd.",
    "audio_set_session_volume": lambda a: f"{a.get('app_name', 'De app')} op {a.get('volume')} procent.",
    "audio_set_session_mute": lambda a: (
        f"{a.get('app_name', 'De app')} gedempt." if a.get("muted", True)
        else f"{a.get('app_name', 'De app')} weer hoorbaar."),
    "control_home_assistant": _ha_zin,
    "show_notification": lambda a: "Melding getoond.",
}


def zin_voor_stap(record):
    """Eén korte zin voor een afgeronde stap, of None (overgeslagen e.d.)."""

    status = record.get("status")
    tool = str(record.get("used_tool_name") or record.get("tool_name") or "")
    args = record.get("arguments") or {}
    basis = tool[len("game_pc_"):] if tool.startswith("game_pc_") else tool
    if status == "done":
        maker = _ZINNEN.get(basis)
        if maker is not None:
            try:
                return maker(args)
            except Exception:
                pass
        return _omschrijving(tool, args, voltooid=True)
    if status == "failed":
        return f"{_omschrijving(tool, args)} mislukt."
    return None


def _omschrijving(tool, args, voltooid=False):
    try:
        from core.tool_registry import beschrijf_taak

        tekst = beschrijf_taak(tool, args)
    except Exception:
        tekst = tool
    tekst = str(tekst or tool).strip()
    tekst = tekst[:1].upper() + tekst[1:]
    return f"{tekst}: gedaan." if voltooid else tekst


class Verteller:
    """Verzamelt de zinnen en spreekt ze (met ``on_tekst``) meteen uit."""

    def __init__(self, on_tekst=None):
        self.on_tekst = on_tekst
        self.zinnen = []
        self.gelukt = 0
        self.mislukt = 0
        self.wacht_op_goedkeuring = False
        self._gezien = set()

    def zeg(self, zin):
        if not zin:
            return
        self.zinnen.append(zin)
        if self.on_tekst is not None:
            try:
                self.on_tekst(zin + " ")
            except Exception:
                logger.debug("Vertellen mislukt", exc_info=True)

    def stap(self, record):
        """Callback van de executor: één stap is klaar."""

        if id(record) in self._gezien:
            return
        self._gezien.add(id(record))
        if record.get("needs_approval"):
            self.wacht_op_goedkeuring = True
            return
        if record.get("status") == "done":
            self.gelukt += 1
        elif record.get("status") == "failed":
            self.mislukt += 1
        self.zeg(zin_voor_stap(record))

    def na_afloop(self, resultaten):
        """Stappen die de callback niet zag alsnog vertellen, zodat het
        slot ("Alles staat klaar") altijd klopt met de echte uitkomst."""

        for record in resultaten or []:
            if isinstance(record, dict):
                self.stap(record)

    def slot(self, eind_zin=None):
        """De laatste zin, afhankelijk van hoe het ging."""

        if self.wacht_op_goedkeuring:
            self.zeg("Voor de volgende stap wacht ik op uw goedkeuring.")
        elif self.mislukt and not self.gelukt:
            self.zeg("Het is helaas niet gelukt, sir.")
        elif self.mislukt:
            self.zeg("De rest staat klaar, sir.")
        else:
            self.zeg(eind_zin or "Alles staat klaar, sir.")

    def tekst(self):
        return " ".join(self.zinnen)


def staat_aan(routine):
    """Narratie voor deze routine? (config + per routine uit te zetten)."""

    from config import ROUTINE_NARRATIE

    return bool(ROUTINE_NARRATIE) and routine.get("narratie", True) is not False
