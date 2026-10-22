"""Volledige functietest vanaf de laptop naar de game-pc.

Draai dit script op de **laptop** (het brein) terwijl de agent op de
game-pc draait. Het script test de echte LAN-verbinding en alle
game-pc-tools die JARVIS kan gebruiken: status, programma's, volume,
audio, vensters, bestanden, browser en (optioneel) de stroomacties.
Ook Home Assistant wordt getest als dat op de laptop is ingesteld.

Gebruik::

    python -m scripts.test_alle_functies_manual
    python -m scripts.test_alle_functies_manual --acties
    python -m scripts.test_alle_functies_manual --bestanden --browser --ui
    python -m scripts.test_alle_functies_manual --zinnen
    python -m scripts.test_alle_functies_manual --ha-actie light.slaapkamer

Zonder vlaggen test het script alleen *lezen*: status opvragen, een
screenshot maken en controleren of Discord draait. Met ``--acties``
komen daar zichtbare acties bij (volume, media, vensters). De
bestands-, browser- en UI-testen staan achter hun eigen vlag, omdat ze
bestanden of vensters op de game-pc aanpassen.

Let op: de agent heeft een **profiel**. Staat hij op ``basis`` (de
veilige standaard), dan weigert hij bestands-, browser-, UI- en
stroomacties. Dit script meldt die tools als "overgeslagen" met de
reden erbij. Zet op de game-pc ``REMOTE_SERVER_PROFILE=werkstation``
en herstart de agent om ze toch te testen.

Het script eindigt met een samenvatting en schrijft een JSON-rapport
naar ``logs/``. Exitcode 0 = alles geslaagd (overgeslagen telt niet
als fout), 1 = minstens één test mislukt, 2 = de client is niet goed
geconfigureerd.
"""

import argparse
import collections
import http.client
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Draai dit script vanuit de projectmap: de projectroot moet op het
# importpad staan, anders vindt Python `config`, `core` en `remote` niet.
PROJECTROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECTROOT))

import config
from remote import protocol, tools as remote_tools
from remote.client import RemoteClient

GESLAAGD = "GESLAAGD"
MISLUKT = "MISLUKT"
OVER = "OVERGESLAGEN"
LET_OP = "LET OP"

# Tools die nooit automatisch worden uitgevoerd (te riskant of te
# ingrijpend). Ze staan alleen in de afsluitende "niet getest"-lijst.
NOOIT_AUTOMATISCH = {
    "game_pc_ui_click_element": "klikt met de muis in een onbekend venster",
    "game_pc_ui_type_text": "typt tekst in een onbekend venster",
    "game_pc_ui_set_value": "wijzigt een veld in een onbekend venster",
    "game_pc_ui_launch_app": "start een willekeurig programma op een pad",
    "game_pc_empty_recycle_bin": "leegt de prullenbak van de game-pc",
    "game_pc_open_file": "opent een bestand in een willekeurig programma op de game-pc",
    "game_pc_audio_set_default_output": "verandert het standaard audio-apparaat van de game-pc",
}

# De agent laat standaard 60 opdrachten per minuut toe (per IP-adres).
# Deze teller blijft daar met een marge onder; bij status 429 probeert
# het script het opnieuw.
LIMIET_PER_MINUUT = 50
VENSTER_SECONDEN = 60.0
WACHT_BIJ_429 = (5, 10, 20)


# =============================================================
# Uitkomsten en afdrukken
# =============================================================

class Tester:
    """Verzamelt uitslagen, drukt ze af en schrijft het rapport."""

    def __init__(self, rapport_pad):
        self.rapport_pad = Path(rapport_pad)
        self.uitkomsten = []
        self._verzoeken = collections.deque()

    # -- tempo -----------------------------------------------------

    def wacht(self):
        """Houd het aantal opdrachten binnen de limiet van de agent.

        De agent laat standaard 60 opdrachten per minuut toe (per
        IP-adres). Deze teller houdt een veilige marge aan: pas als het
        venster van een minuut vol is, wordt er gewacht tot de oudste
        opdracht buiten het venster valt.
        """

        nu = time.perf_counter()
        grens = nu - VENSTER_SECONDEN

        while self._verzoeken and self._verzoeken[0] <= grens:
            self._verzoeken.popleft()

        if len(self._verzoeken) >= LIMIET_PER_MINUUT:
            slaap = self._verzoeken[0] + VENSTER_SECONDEN - nu

            if slaap > 0:
                print(
                    f"  (even wachten: {slaap:.0f}s; de agent staat "
                    f"{LIMIET_PER_MINUUT} opdrachten per minuut toe)"
                )
                time.sleep(slaap)

            grens = time.perf_counter() - VENSTER_SECONDEN

            while self._verzoeken and self._verzoeken[0] <= grens:
                self._verzoeken.popleft()

        self._verzoeken.append(time.perf_counter())

    def _met_herhaling(self, tool, argumenten):
        """Voert een tool uit en probeert het bij 429 opnieuw."""

        resultaat = None

        for wacht in (0, *WACHT_BIJ_429):

            if wacht:
                print(f"  (te veel verzoeken; {wacht}s wachten en opnieuw proberen)")
                time.sleep(wacht)

            self.wacht()
            resultaat = remote_tools.execute_remote_tool(tool, argumenten)

            if str(_statuscode(resultaat)) != "429":
                return resultaat

        return resultaat

    # -- afdrukken -------------------------------------------------

    def kop(self, titel):
        print()
        print("=" * 74)
        print(titel)
        print("=" * 74)

    def _bewaar(self, groep, naam, status, detail="", duur=0.0):
        self.uitkomsten.append({
            "groep": groep,
            "naam": naam,
            "status": status,
            "detail": str(detail or ""),
            "duur_seconden": round(float(duur), 3),
            "tijd": datetime.now().isoformat(timespec="seconds"),
        })

        regel = f"  [{status:<11}] {naam}"

        if duur:
            regel += f"  ({duur:.2f}s)"

        print(regel)

        if detail:
            print(f"                {str(detail)[:170]}")

    def geslaagd(self, groep, naam, detail="", duur=0.0):
        self._bewaar(groep, naam, GESLAAGD, detail, duur)

    def mislukt(self, groep, naam, detail="", duur=0.0):
        self._bewaar(groep, naam, MISLUKT, detail, duur)

    def over(self, groep, naam, reden):
        self._bewaar(groep, naam, OVER, reden)

    def let_op(self, groep, naam, detail="", duur=0.0):
        """Uitgevoerd, maar met een kanttekening (telt niet als fout)."""

        self._bewaar(groep, naam, LET_OP, detail, duur)

    # -- één remote tool ------------------------------------------

    def tool(self, groep, naam, tool, argumenten=None, verwacht=None,
             verwacht_fout=False, zacht=False):
        """Voert één game-pc-tool uit en beoordeelt het resultaat.

        ``verwacht`` is een functie die het ToolResult krijgt en
        ``(geslaagd, detail)`` teruggeeft. ``verwacht_fout`` draait de
        beoordeling om: dan hoort de tool netjes te weigeren.
        ``zacht`` maakt van een mislukking een "LET OP" in plaats van
        een fout (voor dingen die van de situatie afhangen).
        """

        begin = time.perf_counter()

        try:
            resultaat = self._met_herhaling(tool, argumenten or {})
        except Exception as fout:  # noqa: BLE001 - handmatig testscript
            self.mislukt(groep, naam, f"uitzondering: {fout}", time.perf_counter() - begin)
            return None

        duur = time.perf_counter() - begin

        if _profiel_blokkeert(resultaat):
            self.over(
                groep,
                naam,
                "profiel 'basis' staat dit niet toe; zet op de game-pc "
                "REMOTE_SERVER_PROFILE=werkstation en herstart de agent.",
            )
            return resultaat

        if verwacht_fout:
            if not resultaat.ok:
                self.geslaagd(groep, naam, f"netjes geweigerd: {resultaat.message}", duur)
            else:
                self.mislukt(groep, naam, "hoorde te mislukken, maar slaagde", duur)

            return resultaat

        if not resultaat.ok:
            detail = f"status {_statuscode(resultaat)}: {resultaat.message}"
            (self.let_op if zacht else self.mislukt)(groep, naam, detail, duur)
            return resultaat

        if verwacht is not None:
            try:
                goed, detail = verwacht(resultaat)
            except Exception as fout:  # noqa: BLE001
                self.mislukt(groep, naam, f"controle mislukt: {fout}", duur)
                return resultaat

            if goed:
                self.geslaagd(groep, naam, detail, duur)
            elif zacht:
                self.let_op(groep, naam, detail, duur)
            else:
                self.mislukt(groep, naam, detail, duur)

            return resultaat

        self.geslaagd(groep, naam, resultaat.message, duur)
        return resultaat

    # -- samenvatting ---------------------------------------------

    def tel(self, status):
        return sum(1 for rij in self.uitkomsten if rij["status"] == status)

    def samenvatting(self):
        print()
        print("=" * 74)
        print("SAMENVATTING")
        print("=" * 74)
        print(f"  geslaagd      : {self.tel(GESLAAGD)}")
        print(f"  mislukt       : {self.tel(MISLUKT)}")
        print(f"  let op        : {self.tel(LET_OP)}")
        print(f"  overgeslagen  : {self.tel(OVER)}")

        fouten = [rij for rij in self.uitkomsten if rij["status"] == MISLUKT]

        if fouten:
            print()
            print("  Mislukte testen:")

            for rij in fouten:
                print(f"   - {rij['naam']}: {rij['detail'][:120]}")

        return len(fouten)

    def schrijf_rapport(self, extra):
        self.rapport_pad.parent.mkdir(parents=True, exist_ok=True)

        inhoud = {
            "tijd": datetime.now().isoformat(timespec="seconds"),
            "host": extra.get("host", ""),
            "poort": extra.get("poort", ""),
            "pc_target": extra.get("pc_target", ""),
            "vlaggen": extra.get("vlaggen", {}),
            "samenvatting": {
                "geslaagd": self.tel(GESLAAGD),
                "mislukt": self.tel(MISLUKT),
                "let_op": self.tel(LET_OP),
                "overgeslagen": self.tel(OVER),
            },
            "resultaten": self.uitkomsten,
        }

        with open(self.rapport_pad, "w", encoding="utf-8") as bestand:
            json.dump(inhoud, bestand, ensure_ascii=False, indent=2)

        print()
        print(f"  Rapport: {self.rapport_pad}")


# =============================================================
# Helpers
# =============================================================

def _statuscode(resultaat):
    data = getattr(resultaat, "data", None) or {}

    if isinstance(data, dict):
        return data.get("status_code", "?")

    return "?"


def _foutcode(resultaat):
    data = getattr(resultaat, "data", None) or {}

    if isinstance(data, dict):
        return str(data.get("fout_code", ""))

    return ""


def _profiel_blokkeert(resultaat):
    """True als de agent weigerde omdat het profiel de actie niet toestaat."""

    if resultaat is None or resultaat.ok:
        return False

    if _foutcode(resultaat) != "niet_toegestaan":
        return False

    return "profiel" in str(resultaat.message).lower()


def _zoek_volume(data, app_deel):
    """Zoekt in een (geneste) audiolijst het volume van één app."""

    if isinstance(data, dict):
        naam = str(data.get("name", "")).lower()
        volume = data.get("volume")

        if app_deel in naam and isinstance(volume, (int, float)):
            return int(volume)

        for waarde in data.values():
            gevonden = _zoek_volume(waarde, app_deel)

            if gevonden is not None:
                return gevonden

    elif isinstance(data, (list, tuple)):
        for waarde in data:
            gevonden = _zoek_volume(waarde, app_deel)

            if gevonden is not None:
                return gevonden

    elif isinstance(data, str) and data.strip().startswith("{"):

        try:
            return _zoek_volume(json.loads(data.replace("'", '"')), app_deel)
        except (ValueError, TypeError):
            return None

    return None


def _ruw_verzoek(client, method, pad, body=b"", timestamp=None):
    """Doet een rauw ondertekend HTTPS-verzoek en geeft (status, body)."""

    verbinding = http.client.HTTPSConnection(
        client.host,
        client.port,
        context=client._ssl_context(),
        timeout=client.timeout,
    )

    try:
        headers = protocol.signed_headers(
            client.token, method, pad, body, timestamp=timestamp
        )
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
        verbinding.request(method, pad, body=body or None, headers=headers)
        antwoord = verbinding.getresponse()

        return antwoord.status, antwoord.read()
    finally:
        try:
            verbinding.close()
        except Exception:  # noqa: BLE001
            pass


def _tekst_bevat(resultaat, *woorden):
    bericht = str(resultaat.message).lower()

    return all(woord.lower() in bericht for woord in woorden)


# =============================================================
# Sectie 1 - verbinding en beveiliging
# =============================================================

def sectie_verbinding(tester, client, groep="verbinding"):
    tester.kop("1. Verbinding en beveiliging")

    begin = time.perf_counter()

    try:
        resultaat = client.health()
        duur = time.perf_counter() - begin

        if resultaat.ok:
            tester.geslaagd(groep, "ondertekende health", "agent is online", duur)
        else:
            tester.mislukt(
                groep,
                "ondertekende health",
                f"status {resultaat.status}: {resultaat.samenvatting()}",
                duur,
            )
    except Exception as fout:  # noqa: BLE001
        tester.mislukt(
            groep,
            "ondertekende health",
            f"uitzondering: {fout}",
            time.perf_counter() - begin,
        )
        return

    begin = time.perf_counter()
    fout = RemoteClient(token="x" * 32).health()
    duur = time.perf_counter() - begin

    if fout.status == 401:
        tester.geslaagd(groep, "verkeerd token geweigerd", "netjes 401", duur)
    else:
        tester.mislukt(
            groep,
            "verkeerd token geweigerd",
            f"verwachtte 401, kreeg {fout.status}",
            duur,
        )

    begin = time.perf_counter()

    try:
        status, _ = _ruw_verzoek(
            client, "GET", protocol.ROUTE_HEALTH, timestamp=int(time.time()) - 3600
        )
        fout_melding = ""
    except OSError as fout_object:
        status, fout_melding = 0, str(fout_object)

    duur = time.perf_counter() - begin

    if status == 401:
        tester.geslaagd(groep, "oude handtekening geweigerd", "netjes 401", duur)
    else:
        tester.mislukt(
            groep,
            "oude handtekening geweigerd",
            fout_melding or f"verwachtte 401, kreeg {status}",
            duur,
        )


# =============================================================
# Sectie 2 - status en systeem
# =============================================================

def sectie_status(tester):
    groep = "status"
    tester.kop("2. Status en systeem (lezen)")

    tester.tool(groep, "pc-status", "game_pc_status")
    tester.tool(groep, "systeeminfo", "game_pc_system_info")
    tester.tool(groep, "telemetrie", "game_pc_telemetry")
    tester.tool(
        groep,
        "programma-status (discord)",
        "game_pc_program_status",
        {"program": "discord"},
    )
    tester.tool(
        groep,
        "programma-locatie (discord)",
        "game_pc_find_program_location",
        {"program": "discord"},
    )
    tester.tool(
        groep,
        "screenshot",
        "game_pc_screenshot",
        verwacht=lambda r: (
            _tekst_bevat(r, "screenshot"),
            r.message,
        ),
    )


# =============================================================
# Sectie 3 - programma's
# =============================================================

def sectie_programmas(tester, opties):
    groep = "programma's"
    tester.kop("3. Programma's")

    tester.tool(
        groep,
        "open_program (discord)",
        "game_pc_open_program",
        {"program": "discord"},
        verwacht=lambda r: (
            _tekst_bevat(r, "discord"),
            r.message,
        ),
    )

    if not opties.acties:
        tester.over(groep, "close_program",
                    "niet getest: kan werk van de gebruiker sluiten; "
                    "gebruik --acties (opent en sluit dan Notepad).")
        return

    # Openen en meteen weer sluiten van Notepad: zo testen we
    # close_program zonder iets van de gebruiker te raken.
    print("  (Notepad openen en sluiten om close_program te testen)")

    tester.tool(
        groep,
        "open_program (kladblok)",
        "game_pc_open_program",
        {"program": "notepad"},
        verwacht=lambda r: ("niet vinden" not in r.message.lower(), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "programma-status (kladblok)",
        "game_pc_program_status",
        {"program": "notepad"},
        verwacht=lambda r: ("niet gevonden" not in r.message.lower(), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "close_program (kladblok)",
        "game_pc_close_program",
        {"program": "notepad"},
        verwacht=lambda r: (
            "was niet geopend" not in r.message.lower(),
            r.message,
        ),
        zacht=True,
    )


# =============================================================
# Sectie 4 - volume, media en audio
# =============================================================

def sectie_audio(tester, opties):
    groep = "audio"
    tester.kop("4. Volume, media en audio")

    sessies = tester.tool(
        groep,
        "audio_list_sessions",
        "game_pc_audio_list_sessions",
    )

    tester.tool(
        groep,
        "audio_get_session_volume (discord)",
        "game_pc_audio_get_session_volume",
        {"app_name": "discord"},
        verwacht=lambda r: (
            "geen actieve audio-session" not in r.message.lower(),
            r.message,
        ),
        zacht=True,
    )

    huidig = _zoek_volume(sessies.data if sessies is not None else {}, "discord")

    if huidig is None:
        tester.over(
            groep,
            "audio_set_session_volume (discord)",
            "niet getest: geen Discord-audiosessie gevonden (start Discord eerst).",
        )
    else:
        tester.tool(
            groep,
            "audio_set_session_volume (discord)",
            "game_pc_audio_set_session_volume",
            {"app_name": "discord", "volume": huidig},
            zacht=True,
        )

    tester.tool(groep, "audio_list_outputs", "game_pc_audio_list_outputs")
    tester.tool(
        groep,
        "audio_get_default_output",
        "game_pc_audio_get_default_output",
    )

    # Negatieve test: een onbekende media-actie hoort netjes te weigeren.
    tester.tool(
        groep,
        "media weigert onbekende actie",
        "game_pc_media",
        {"action": "onzin"},
        verwacht_fout=True,
    )

    if not opties.acties:
        tester.over(
            groep,
            "media (play/pause, volgende, vorige, stop, mute, volume op/neer)",
            "niet getest: beinvloedt wat er op de game-pc speelt; gebruik --acties.",
        )
        tester.over(
            groep,
            "set_volume (master)",
            "niet getest: zet het mastervolume van de game-pc; gebruik --acties.",
        )
        tester.over(
            groep,
            "audio_toggle_session_mute / audio_set_session_mute (discord)",
            "niet getest: hoorbaar; gebruik --acties.",
        )
        return

    for actie in ("play_pause", "next", "previous", "stop"):
        tester.tool(
            groep,
            f"media {actie}",
            "game_pc_media",
            {"action": actie},
            zacht=True,
        )

    tester.tool(
        groep,
        "set_volume (master, 50%)",
        "game_pc_set_volume",
        {"percent": 50},
        verwacht=lambda r: (_tekst_bevat(r, "50"), r.message + " (volume staat nu op 50%)"),
        zacht=True,
    )

    if huidig is None:
        tester.over(
            groep,
            "audio_toggle_session_mute (discord)",
            "niet getest: geen Discord-audiosessie gevonden "
            "(laat Discord geluid maken en run opnieuw).",
        )
        return

    tester.tool(
        groep,
        "audio_toggle_session_mute (discord)",
        "game_pc_audio_toggle_session_mute",
        {"app_name": "discord"},
        verwacht=lambda r: (
            "geen actieve audio-session" not in r.message.lower(),
            r.message,
        ),
        zacht=True,
    )
    tester.tool(
        groep,
        "audio_toggle_session_mute (discord, terug)",
        "game_pc_audio_toggle_session_mute",
        {"app_name": "discord"},
        verwacht=lambda r: (
            "geen actieve audio-session" not in r.message.lower(),
            r.message,
        ),
        zacht=True,
    )

    # Mute via de expliciete setter (mutex) in plaats van de toggle.
    for muted, uitleg in (
        (True, "audio_set_session_mute (discord, gedempt)"),
        (False, "audio_set_session_mute (discord, geluid terug)"),
    ):
        tester.tool(
            groep,
            uitleg,
            "game_pc_audio_set_session_mute",
            {"app_name": "discord", "muted": muted},
            verwacht=lambda r: (
                "geen actieve audio-session" not in r.message.lower(),
                r.message,
            ),
            zacht=True,
        )

    # Mediasleutels: mute twee keer (netto ongemoeid) en volume op/neer.
    tester.tool(groep, "media mute (aan)", "game_pc_media",
                {"action": "mute"}, zacht=True)
    tester.tool(groep, "media mute (uit)", "game_pc_media",
                {"action": "mute"}, zacht=True)
    tester.tool(groep, "media volume_up", "game_pc_media",
                {"action": "volume_up"}, zacht=True)
    tester.tool(groep, "media volume_down", "game_pc_media",
                {"action": "volume_down"}, zacht=True)


# =============================================================
# Sectie 5 - vensters
# =============================================================

def sectie_vensters(tester, opties):
    groep = "vensters"
    tester.kop("5. Vensters")

    if not opties.acties:
        tester.over(groep, "minimize_window (discord)",
                    "niet getest: verandert het scherm van de game-pc; gebruik --acties.")
        tester.over(groep, "maximize_window (discord)",
                    "niet getest: verandert het scherm van de game-pc; gebruik --acties.")
        tester.over(groep, "restore_window (discord)",
                    "niet getest: verandert het scherm van de game-pc; gebruik --acties.")
        return

    tester.tool(
        groep,
        "minimize_window (discord)",
        "game_pc_minimize_window",
        {"program": "discord"},
        verwacht=lambda r: ("geen venster" not in r.message.lower(), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "restore_window (discord)",
        "game_pc_restore_window",
        {"program": "discord"},
        verwacht=lambda r: ("geen venster" not in r.message.lower(), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "maximize_window (discord)",
        "game_pc_maximize_window",
        {"program": "discord"},
        verwacht=lambda r: ("geen venster" not in r.message.lower(), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "restore_window (discord, terug)",
        "game_pc_restore_window",
        {"program": "discord"},
        verwacht=lambda r: ("geen venster" not in r.message.lower(), r.message),
        zacht=True,
    )


# =============================================================
# Sectie 6 - UI-automatisering (alleen lezen en naar voren halen)
# =============================================================

def sectie_ui(tester, opties):
    groep = "ui"
    tester.kop("6. UI-automatisering (vensters van de game-pc)")

    if not opties.ui:
        tester.over(
            groep,
            "ui_list_windows / ui_find_window / ui_list_elements",
            "niet getest: vraagt profiel 'werkstation'; gebruik --ui.",
        )
        return

    vensters = tester.tool(groep, "ui_list_windows", "game_pc_ui_list_windows")

    if vensters is None or not vensters.ok:
        return

    gevonden = tester.tool(
        groep,
        "ui_find_window (discord)",
        "game_pc_ui_find_window",
        {"title": "discord"},
        zacht=True,
    )

    handle = _zoek_handle(gevonden)

    if not handle:
        tester.over(
            groep,
            "ui_list_elements / ui_activate_window",
            "niet getest: geen Discord-venster gevonden om op te richten.",
        )
        return

    elementen = tester.tool(
        groep,
        "ui_list_elements (discord)",
        "game_pc_ui_list_elements",
        {"handle": handle},
        zacht=True,
    )

    element = _elementnaam(elementen)

    if element:
        tester.tool(
            groep,
            "ui_find_element (eerste element)",
            "game_pc_ui_find_element",
            {"handle": handle, "name": element},
            zacht=True,
        )
        tester.tool(
            groep,
            "ui_get_value (eerste element)",
            "game_pc_ui_get_value",
            {"handle": handle, "name": element},
            zacht=True,
        )
    else:
        tester.over(
            groep,
            "ui_find_element / ui_get_value",
            "niet getest: geen elementnaam gevonden in dit venster.",
        )

    tester.tool(
        groep,
        "ui_activate_window (discord)",
        "game_pc_ui_activate_window",
        {"handle": handle},
        zacht=True,
    )


def _elementnaam(resultaat):
    """Haalt een elementnaam uit het antwoord van ui_list_elements."""

    if resultaat is None or not resultaat.ok:
        return None

    data = getattr(resultaat, "data", None) or {}

    return _naam_uit(data)


def _naam_uit(waarde, diepte=0):
    if diepte > 6:
        return None

    if isinstance(waarde, dict):
        naam = waarde.get("name") or waarde.get("naam")

        if isinstance(naam, str) and naam.strip():
            return naam.strip()

        for binnen in waarde.values():
            gevonden = _naam_uit(binnen, diepte + 1)

            if gevonden:
                return gevonden

    elif isinstance(waarde, (list, tuple)):
        for binnen in waarde:
            gevonden = _naam_uit(binnen, diepte + 1)

            if gevonden:
                return gevonden

    elif isinstance(waarde, str):
        inhoud = waarde.strip()

        if inhoud.startswith(("{", "[")):
            try:
                return _naam_uit(json.loads(inhoud.replace("'", '"')), diepte + 1)
            except (ValueError, TypeError):
                return None

    return None


def _zoek_handle(resultaat):
    """Haalt een vensterhandle uit het antwoord van ui_find_window."""

    if resultaat is None or not resultaat.ok:
        return None

    data = getattr(resultaat, "data", None) or {}

    if not isinstance(data, dict):
        return None

    for waarde in (data.get("resultaat"), data.get("data"), data):
        handle = _handle_uit(waarde)

        if handle:
            return handle

    return None


def _handle_uit(waarde):
    if isinstance(waarde, dict):
        for sleutel in ("handle", "hwnd", "venster"):
            if waarde.get(sleutel):
                return waarde[sleutel]

        for binnen in waarde.values():
            handle = _handle_uit(binnen)

            if handle:
                return handle

    elif isinstance(waarde, str):
        inhoud = waarde.strip()

        if inhoud.startswith("{"):
            try:
                return _handle_uit(json.loads(inhoud.replace("'", '"')))
            except (ValueError, TypeError):
                return None

    return None


# =============================================================
# Sectie 7 - bestanden (alleen met --bestanden)
# =============================================================

def sectie_bestanden(tester, opties):
    groep = "bestanden"
    tester.kop("7. Bestanden")

    if not opties.bestanden:
        tester.over(
            groep,
            "list_files / recent_files / search_files",
            "niet getest: alleen lezen, maar vraagt profiel 'werkstation'; gebruik --bestanden.",
        )
        tester.over(
            groep,
            "create_file / rename_file / move_file / recycle_file",
            "niet getest: maakt testbestanden aan; gebruik --bestanden.",
        )
        return

    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    naam = f"jarvis-test-{stempel}.txt"
    hernoemd = f"jarvis-hernoemd-{stempel}.txt"
    map_naam = f"JARVIS-Test-{stempel}"

    tester.tool(groep, "list_files (downloads)", "game_pc_list_files",
                {"location": "downloads"})
    tester.tool(groep, "recent_files", "game_pc_recent_files")
    tester.tool(groep, "search_files (jarvis)", "game_pc_search_files",
                {"query": "jarvis"}, zacht=True)

    tester.tool(
        groep,
        "create_file (documenten)",
        "game_pc_create_file",
        {"name": naam, "location": "documenten"},
        verwacht=lambda r: (_tekst_bevat(r, "aangemaakt"), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "list_files (documenten)",
        "game_pc_list_files",
        {"location": "documenten"},
    )
    tester.tool(
        groep,
        "rename_file (documenten)",
        "game_pc_rename_file",
        {"old_name": naam, "new_name": hernoemd},
        verwacht=lambda r: (_tekst_bevat(r, "hernoemd"), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "move_file (documenten -> bureaublad)",
        "game_pc_move_file",
        {"filename": hernoemd, "location": "bureaublad"},
        verwacht=lambda r: (_tekst_bevat(r, "verplaatst"), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "create_folder (documenten)",
        "game_pc_create_folder",
        {"name": map_naam, "location": "documenten"},
        zacht=True,
    )
    tester.tool(
        groep,
        "open_folder (downloads)",
        "game_pc_open_folder",
        {"location": "downloads"},
        zacht=True,
    )

    # copy_file: alleen de foutmelding testen. Een echte kopie laat twee
    # bestanden met dezelfde naam achter, en de agent kan daarna niet
    # meer kiezen welk bestand hij moet opruimen.
    tester.tool(
        groep,
        "copy_file weigert onbekend bestand",
        "game_pc_copy_file",
        {"filename": f"bestaat-niet-{stempel}", "location": "downloads"},
        verwacht=lambda r: (_tekst_bevat(r, "niet vinden"), r.message),
        zacht=True,
    )

    tester.tool(
        groep,
        "recycle_file (testbestand)",
        "game_pc_recycle_file",
        {"filename": hernoemd},
        verwacht=lambda r: (_tekst_bevat(r, "prullenbak"), r.message),
        zacht=True,
    )
    tester.tool(
        groep,
        "recycle_file (testmap)",
        "game_pc_recycle_file",
        {"filename": map_naam},
        verwacht=lambda r: (_tekst_bevat(r, "prullenbak"), r.message),
        zacht=True,
    )

    print(f"  (testbestand: {naam} -> {hernoemd}; testmap: {map_naam} - opgeruimd via de prullenbak)")


# =============================================================
# Sectie 8 - browser (alleen met --browser)
# =============================================================

def sectie_browser(tester, opties):
    groep = "browser"
    tester.kop("8. Browser en websites")

    if not opties.browser:
        tester.over(
            groep,
            "open_website / browser_*",
            "niet getest: opent tabbladen op de game-pc; gebruik --browser.",
        )
        return

    tester.tool(groep, "open_website (example.com)", "game_pc_open_website",
                {"url": "https://example.com"}, zacht=True)
    tester.tool(groep, "browser_new_tab", "game_pc_browser_new_tab", zacht=True)
    tester.tool(groep, "browser_refresh", "game_pc_browser_refresh", zacht=True)
    tester.tool(groep, "browser_back", "game_pc_browser_back", zacht=True)
    tester.tool(groep, "browser_forward", "game_pc_browser_forward", zacht=True)
    tester.tool(groep, "browser_search (jarvis)", "game_pc_browser_search",
                {"query": "jarvis"}, zacht=True)
    tester.tool(groep, "browser_close_tab", "game_pc_browser_close_tab", zacht=True)


# =============================================================
# Sectie 9 - stroomacties (alleen expliciet)
# =============================================================

def sectie_power(tester, opties):
    groep = "stroom"
    tester.kop("9. Stroomacties")

    if not opties.power:
        tester.over(
            groep,
            "game_pc_power",
            "niet getest: kan de game-pc uitzetten of laten slapen; "
            "gebruik --power lock|sleep|restart|shutdown (vraagt bevestiging).",
        )
        return

    print()
    print(f"  LET OP: de game-pc gaat nu '{opties.power}' uitvoeren.")

    if input("  Typ JA om door te gaan: ").strip().upper() != "JA":
        tester.over(groep, f"game_pc_power ({opties.power})", "geannuleerd door gebruiker.")
        return

    tester.tool(
        groep,
        f"game_pc_power ({opties.power})",
        "game_pc_power",
        {"action": opties.power},
        zacht=True,
    )


# =============================================================
# Sectie 10 - Home Assistant (draait op de laptop zelf)
# =============================================================

def sectie_home_assistant(tester, opties):
    groep = "home assistant"
    tester.kop("10. Home Assistant (vanaf deze laptop)")

    try:
        from core import home_assistant
    except Exception as fout:  # noqa: BLE001
        tester.mislukt(groep, "module laden", f"import mislukt: {fout}")
        return

    begin = time.perf_counter()
    melding = home_assistant.ha_health_check()
    duur = time.perf_counter() - begin

    if "niet geconfigureerd" in melding.lower():
        tester.over(groep, "configuratie", melding)
        return

    if "bereikbaar" in melding.lower():
        tester.geslaagd(groep, "health check", melding, duur)
    else:
        tester.mislukt(groep, "health check", melding, duur)
        return

    begin = time.perf_counter()

    try:
        entiteiten = home_assistant.get_home_assistant_entities_tool()
        duur = time.perf_counter() - begin
        tester.geslaagd(groep, "entiteiten ophalen",
                        str(entiteiten)[:170], duur)
    except Exception as fout:  # noqa: BLE001
        tester.mislukt(groep, "entiteiten ophalen", str(fout),
                       time.perf_counter() - begin)
        return

    if not opties.ha_actie:
        tester.over(
            groep,
            "apparaat schakelen",
            "niet getest: dat verandert een echt apparaat; "
            "gebruik --ha-actie light.slaapkamer (of een andere entiteit).",
        )
        return

    entiteit = opties.ha_actie
    domein = entiteit.split(".", 1)[0] if "." in entiteit else "light"

    begin = time.perf_counter()

    try:
        antwoord = home_assistant.control_home_assistant_tool(
            domein, "toggle", entiteit
        )
        duur = time.perf_counter() - begin
        tester.geslaagd(groep, f"toggle {entiteit}", str(antwoord)[:170], duur)
    except Exception as fout:  # noqa: BLE001
        tester.mislukt(groep, f"toggle {entiteit}", str(fout),
                       time.perf_counter() - begin)


# =============================================================
# Sectie 11 - Nederlandse zinnen (alleen met --zinnen)
# =============================================================

ZINNEN = [
    ("is discord open", {"game_pc_program_status"}, ""),
    ("waar staat discord", {"game_pc_find_program_location"}, ""),
    ("hoeveel geheugen gebruik ik",
     {"game_pc_telemetry", "game_pc_status", "game_pc_system_info",
      "system_info"}, ""),
    ("open discord", {"game_pc_open_program"}, ""),
    ("open spotify en discord", {"game_pc_open_program"},
     "verwacht twee keer open_program (spotify en discord)"),
    ("zet het volume op 50", {"game_pc_set_volume"},
     "let op: het mastervolume van de game-pc wordt 50%"),
]


def sectie_zinnen(tester, opties):
    groep = "zinnen"
    tester.kop("11. Nederlandse zinnen via het brein")

    if not opties.zinnen:
        tester.over(
            groep,
            "spraakzinnen",
            "niet getest: voert echte acties uit op de game-pc; gebruik --zinnen.",
        )
        return

    try:
        from core import brain
    except Exception as fout:  # noqa: BLE001
        tester.mislukt(groep, "brein laden", f"import mislukt: {fout}")
        return

    origineel = brain.execute_tool
    opnames = []

    def _opname(*argumenten, **sleutels):
        if argumenten:
            opnames.append((str(argumenten[0]), argumenten[1] if len(argumenten) > 1 else {}))
        else:
            opnames.append((str(sleutels.get("tool_name", "")), sleutels.get("arguments", {})))

        return origineel(*argumenten, **sleutels)

    brain.execute_tool = _opname

    try:
        for zin, verwacht, opmerking in ZINNEN:
            opnames.clear()
            begin = time.perf_counter()
            tester.wacht()

            try:
                antwoord = brain.process_command(zin)
                duur = time.perf_counter() - begin
            except Exception as fout:  # noqa: BLE001
                tester.mislukt(groep, f"zin: {zin}", str(fout),
                               time.perf_counter() - begin)
                continue

            gebruikt = {naam for naam, _ in opnames}
            geraakt = gebruikt & verwacht

            detail = f"antwoord: {str(antwoord)[:90]}"

            if opmerking:
                detail += f" | {opmerking}"

            if geraakt:
                tester.geslaagd(groep, f"zin: {zin}", detail, duur)
            else:
                tester.mislukt(
                    groep,
                    f"zin: {zin}",
                    f"geen {sorted(verwacht)} gebruikt; wel: {sorted(gebruikt) or 'niets'}. "
                    + detail,
                    duur,
                )

        # Extra controle: de meervoudige open-zin doet twee losse calls.
        opnames.clear()
        tester.wacht()
        brain.process_command("open spotify en discord")
        namen = [
            str((argumenten or {}).get("program", "")).lower()
            for tool, argumenten in opnames
            if tool == "game_pc_open_program"
        ]

        if "spotify" in namen and "discord" in namen:
            tester.geslaagd(
                groep,
                "meervoudige open: twee aparte opdrachten",
                f"programma's: {namen}",
            )
        else:
            tester.mislukt(
                groep,
                "meervoudige open: twee aparte opdrachten",
                f"programma's: {namen or 'geen'}",
            )
    finally:
        brain.execute_tool = origineel


def sectie_herstart(tester, opties):
    """Discord herstarten als allerlaatste stap.

    Bewust achteraan: een herstart maakt de Discord-audiosessie leeg,
    waardoor de volume- en mutetests daarna niets meer vinden.
    """

    groep = "programma's"
    tester.kop("12. Discord herstarten (laatste stap)")

    if not opties.acties:
        tester.over(
            groep,
            "herstart_program (discord)",
            "niet getest: kan een lopend Discord-gesprek verbreken; "
            "gebruik --acties als dat mag.",
        )
        return

    tester.tool(
        groep,
        "herstart_program (discord)",
        "game_pc_restart_program",
        {"program": "discord"},
        verwacht=lambda r: (
            "niet vinden" not in r.message.lower(),
            r.message,
        ),
        zacht=True,
    )


# =============================================================
# Afsluitende dekking
# =============================================================

def dekking(opties):
    print()
    print("=" * 74)
    print("NIET AUTOMATISCH GETEST")
    print("=" * 74)

    for tool, reden in NOOIT_AUTOMATISCH.items():
        print(f"  {tool:<32} {reden}")

    if not opties.power:
        print(f"  {'game_pc_power':<32} vraagt --power en een getypte bevestiging")

    if not (opties.bestanden and opties.browser and opties.ui):
        print()
        print("  Tip: zet op de game-pc REMOTE_SERVER_PROFILE=werkstation en")
        print("  herstart de agent om bestands-, browser- en UI-tools te testen.")


# =============================================================
# Main
# =============================================================

def _argumenten():
    parser = argparse.ArgumentParser(
        description=(
            "Test alle JARVIS-functies vanaf de laptop tegen de game-pc. "
            "Zonder vlaggen worden alleen leesacties uitgevoerd."
        )
    )
    parser.add_argument("--acties", action="store_true",
                        help="ook zichtbare acties: volume, media, vensters, herstart.")
    parser.add_argument("--bestanden", action="store_true",
                        help="bestandstesten (maakt en ruimt testbestanden op).")
    parser.add_argument("--browser", action="store_true",
                        help="browser- en websitetesten op de game-pc.")
    parser.add_argument("--ui", action="store_true",
                        help="UI-venstertesten (alleen lezen en naar voren halen).")
    parser.add_argument("--zinnen", action="store_true",
                        help="Nederlandse zinnen via het brein (voert echte acties uit).")
    parser.add_argument("--power", choices=("lock", "sleep", "restart", "shutdown"),
                        help="test een stroomactie (vraagt bevestiging).")
    parser.add_argument("--ha-actie", dest="ha_actie", metavar="ENTITEIT",
                        help="test een Home Assistant-toggle, bijv. light.slaapkamer.")
    parser.add_argument("--rapport", default="",
                        help="pad voor het JSON-rapport (standaard: logs/).")
    return parser.parse_args()


def _rapport_pad(gekozen):
    if gekozen:
        return Path(gekozen)

    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")

    return PROJECTROOT / "logs" / f"test-alle-functies-{stempel}.json"


def main():
    opties = _argumenten()

    print("=" * 74)
    print("JARVIS - volledige functietest vanaf de laptop")
    print("=" * 74)
    print(f"  Doel       : {config.REMOTE_CLIENT_HOST}:{config.REMOTE_CLIENT_PORT}")
    print(f"  PC_TARGET  : {config.PC_TARGET or '(leeg)'}")

    if str(config.PC_TARGET).strip().lower() != "game-pc":
        print("  LET OP: PC_TARGET staat niet op 'game-pc'; opdrachten gaan dan")
        print("          mogelijk naar deze laptop in plaats van de game-pc.")

    print()
    print("  Wat dit script doet:")

    if opties.acties:
        print("   - status lezen, screenshot, volume/media/vensters aanpassen")
    else:
        print("   - status lezen, screenshot maken, Discord naar voren halen")

    if opties.bestanden:
        print("   - testbestanden aanmaken en via de prullenbak opruimen")

    if opties.browser:
        print("   - tabbladen openen en sluiten op de game-pc")

    if opties.ui:
        print("   - vensters van de game-pc uitlezen (er wordt niet geklikt)")

    if opties.zinnen:
        print("   - Nederlandse zinnen uitvoeren (opent Spotify en zet volume op 50%)")

    if opties.power:
        print(f"   - stroomactie '{opties.power}' (vraagt bevestiging)")

    try:
        client = remote_tools._get_client()
    except Exception as fout:  # noqa: BLE001
        print()
        print(f"[FOUT] De remote-client is niet goed geconfigureerd: {fout}")
        print("       Controleer REMOTE_CLIENT_* in .env op deze laptop.")
        return 2

    tester = Tester(_rapport_pad(opties.rapport))

    try:
        sectie_verbinding(tester, client)
        sectie_status(tester)
        sectie_programmas(tester, opties)
        sectie_audio(tester, opties)
        sectie_vensters(tester, opties)
        sectie_ui(tester, opties)
        sectie_bestanden(tester, opties)
        sectie_browser(tester, opties)
        sectie_power(tester, opties)
        sectie_home_assistant(tester, opties)
        sectie_zinnen(tester, opties)
        sectie_herstart(tester, opties)
        dekking(opties)
    except KeyboardInterrupt:
        print()
        print("  Afgebroken door de gebruiker.")
        return 130

    fouten = tester.samenvatting()

    tester.schrijf_rapport({
        "host": getattr(client, "host", ""),
        "poort": getattr(client, "port", ""),
        "pc_target": getattr(config, "PC_TARGET", ""),
        "vlaggen": {
            "acties": opties.acties,
            "bestanden": opties.bestanden,
            "browser": opties.browser,
            "ui": opties.ui,
            "zinnen": opties.zinnen,
            "power": opties.power or "",
            "ha_actie": opties.ha_actie or "",
        },
    })

    print()
    print("  Klaar." if not fouten else f"  Klaar met {fouten} mislukte test(en).")

    return 0 if not fouten else 1


if __name__ == "__main__":
    sys.exit(main())
