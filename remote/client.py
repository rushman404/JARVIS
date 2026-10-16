"""Fase 15 — Game-PC Agent: de client (het JARVIS-brein).

De client stuurt ondertekende opdrachten naar de beveiligde agent op de
game-pc en ontvangt gestructureerde resultaten.

Beveiliging
-----------
* Verzoeken worden ondertekend met :mod:`remote.protocol` (HMAC-SHA256
  over methode, pad, tijdstempel, nonce en body-hash).
* TLS-verificatie staat **altijd** aan: het servercertificaat wordt
  expliciet gecontroleerd tegen het ingestelde vertrouwde certificaat
  (``REMOTE_CLIENT_CA_FILE``). Certificaatcontrole wordt nooit
  uitgeschakeld; ontbreekt het vertrouwde certificaat, dan weigert de
  client te starten.

Configuratie
------------
De client gebruikt de eigen ``REMOTE_CLIENT_*``-instellingen, los van de
server. Standaard is de host ``127.0.0.1`` (uitsluitend voor lokale
tests); in productie gebruik je het LAN-IP-adres of de hostnaam van de
game-pc.

Herhalen (retries)
------------------
Alleen **idempotente** acties worden bij een tijdelijke fout opnieuw
geprobeerd (beperkt aantal keren, met kleine backoff). Voor acties die
dubbele effecten kunnen veroorzaken (bijv. ``media_play_pause``,
``volume_up``) wordt nooit automatisch herhaald. De idempotentie komt uit
de vaste tabel in ``core.tool_registry`` (``get_tool_idempotent``).
"""

import http.client
import json
import logging
import os
import socket
import ssl
import time
from dataclasses import dataclass

import config
from core.tool_registry import get_tool_idempotent

from remote import allowlist, protocol

logger = logging.getLogger("jarvis.remote.client")

# Foutcodes aan de kant van de client.
FOUT_CONFIG = "config_fout"
FOUT_NIET_BEREIKBAAR = "niet_bereikbaar"
FOUT_TIMEOUT = "timeout"
FOUT_VERBROKEN = "verbinding_verbroken"
FOUT_TLS = "tls_fout"
FOUT_ONGELDIG_ANTWOORD = "ongeldig_antwoord"
FOUT_NIET_TOEGESTAAN = "niet_toegestaan"

DEFAULT_MAX_RETRIES = 1
DEFAULT_BACKOFF_SECONDS = 0.25

# HTTP-statuscodes die (voor idempotente acties) opnieuw mogen.
_RETRYABLE_STATUS = frozenset({408, 429, 502, 503, 504})

# Hosts die alleen voor lokaal testen bedoeld zijn.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_MELDINGEN = {
    FOUT_CONFIG: "De client is niet goed geconfigureerd.",
    FOUT_NIET_BEREIKBAAR: "De game-pc is niet bereikbaar.",
    FOUT_TIMEOUT: "De game-pc reageerde niet op tijd.",
    FOUT_VERBROKEN: "De verbinding met de game-pc werd verbroken.",
    FOUT_TLS: "De beveiligde verbinding met de game-pc is niet vertrouwd.",
    FOUT_ONGELDIG_ANTWOORD: "De game-pc gaf een onverwacht antwoord.",
}


@dataclass
class RemoteResult:
    """Gestructureerd resultaat van één remote-aanvraag."""

    ok: bool
    status: int = 0
    resultaat: object = None
    fout_code: str = ""
    fout_melding: str = ""
    pogingen: int = 1
    # True als het verzoek de server niet (aantoonbaar) bereikt heeft.
    lokaal: bool = False

    def __bool__(self):
        return self.ok

    def samenvatting(self):
        """Korte, Nederlandse omschrijving voor spraak/tekst."""

        if self.ok:
            if isinstance(self.resultaat, str) and self.resultaat.strip():
                return self.resultaat.strip()
            return "De opdracht is uitgevoerd."

        if self.fout_melding:
            return self.fout_melding

        return _MELDINGEN.get(
            self.fout_code, "Er ging iets mis bij het bereiken van de game-pc."
        )


class RemoteClient:
    """Client voor de Game-PC Agent."""

    def __init__(
        self,
        host=None,
        port=None,
        token=None,
        ca_file=None,
        timeout=None,
        max_retries=DEFAULT_MAX_RETRIES,
        backoff=DEFAULT_BACKOFF_SECONDS,
        enabled=None,
    ):
        self.enabled = config.REMOTE_CLIENT_ENABLED if enabled is None else bool(enabled)
        self.host = config.REMOTE_CLIENT_HOST if host is None else host
        self.port = int(config.REMOTE_CLIENT_PORT if port is None else port)
        self.token = config.REMOTE_CLIENT_TOKEN if token is None else token
        self.ca_file = config.REMOTE_CLIENT_CA_FILE if ca_file is None else ca_file
        self.timeout = float(config.REMOTE_CLIENT_TIMEOUT if timeout is None else timeout)
        self.max_retries = max(0, int(max_retries))
        self.backoff = max(0.0, float(backoff))
        self._context = None

        self._controleer_config()

    # -- configuratie -------------------------------------------------

    def _controleer_config(self):
        """Fail-closed: zonder token of vertrouwd certificaat geen client."""

        fouten = []

        if not self.host or not str(self.host).strip():
            fouten.append("REMOTE_CLIENT_HOST ontbreekt.")

        if not (0 < self.port < 65536):
            fouten.append("REMOTE_CLIENT_PORT is ongeldig.")

        if not self.token or not str(self.token).strip():
            fouten.append("REMOTE_CLIENT_TOKEN ontbreekt: zonder geheim geen opdracht.")
        elif len(str(self.token)) < config.REMOTE_MIN_TOKEN_LENGTH:
            fouten.append(
                f"REMOTE_CLIENT_TOKEN is te kort (minimaal "
                f"{config.REMOTE_MIN_TOKEN_LENGTH} tekens)."
            )

        if not self.ca_file:
            fouten.append(
                "REMOTE_CLIENT_CA_FILE ontbreekt: TLS-verificatie is verplicht."
            )
        elif not os.path.isfile(self.ca_file):
            fouten.append(f"Vertrouwd certificaat niet gevonden: {self.ca_file}")

        if fouten:
            raise ValueError(
                "Onveilige client-configuratie; client start niet: " + " ".join(fouten)
            )

        if self.is_loopback():
            logger.warning(
                "REMOTE_CLIENT_HOST staat op %s (alleen voor lokale tests); "
                "gebruik het LAN-IP-adres of de hostnaam van de game-pc.",
                self.host,
            )

        # Laad het vertrouwde certificaat meteen: is het ongeldig, dan
        # start de client niet (in plaats van pas bij het eerste verzoek).
        self._ssl_context()

    def is_loopback(self):
        """True als de host alleen voor lokaal testen is."""

        return str(self.host or "").strip().lower() in LOOPBACK_HOSTS

    def _ssl_context(self):
        """TLS-context die het servercertificaat expliciet verifieert."""

        if self._context is None:
            try:
                context = ssl.create_default_context(cafile=self.ca_file)
            except (ssl.SSLError, OSError, ValueError) as error:
                raise ValueError(
                    f"Vertrouwd certificaat is ongeldig; client start niet: {error}"
                ) from error

            # Expliciet: nooit uitzetten.
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._context = context

        return self._context

    # -- transport ----------------------------------------------------

    def _do_request(self, method, path, body=b""):
        """Doet één daadwerkelijk HTTPS-verzoek.

        Geeft ``(status, ruwe_body-bytes)`` terug. Exceptions (TLS,
        time-out, verbroken verbinding) worden door de aanroeper
        afgehandeld.
        """

        verbinding = http.client.HTTPSConnection(
            self.host,
            self.port,
            context=self._ssl_context(),
            timeout=self.timeout,
        )

        try:
            headers = protocol.signed_headers(self.token, method, path, body)
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))

            verbinding.request(
                method, path, body=body if body else None, headers=headers
            )
            antwoord = verbinding.getresponse()
            return antwoord.status, antwoord.read()
        finally:
            try:
                verbinding.close()
            except Exception:
                pass

    # -- verwerking ---------------------------------------------------

    def _parse_antwoord(self, status, data, poging):
        if not data:
            return RemoteResult(
                False,
                status,
                fout_code=FOUT_ONGELDIG_ANTWOORD,
                fout_melding="De game-pc stuurde een leeg antwoord.",
                pogingen=poging,
            )

        try:
            payload = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return RemoteResult(
                False,
                status,
                fout_code=FOUT_ONGELDIG_ANTWOORD,
                fout_melding="Het antwoord van de game-pc was geen geldige JSON.",
                pogingen=poging,
            )

        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            return RemoteResult(
                False,
                status,
                fout_code=FOUT_ONGELDIG_ANTWOORD,
                fout_melding="Het antwoord van de game-pc had een onverwachte vorm.",
                pogingen=poging,
            )

        if payload["ok"]:
            return RemoteResult(
                True, status, resultaat=payload.get("resultaat"), pogingen=poging
            )

        fout = payload.get("fout")
        code = fout.get("code") if isinstance(fout, dict) else ""
        melding = fout.get("melding") if isinstance(fout, dict) else ""

        return RemoteResult(
            False,
            status,
            fout_code=code or "fout",
            fout_melding=melding or "De game-pc gaf een fout terug.",
            pogingen=poging,
        )

    def _request(self, method, path, body=b"", idempotent=True):
        """Verstuurt een ondertekend verzoek, met beperkte retries.

        Retries gebeuren alleen als ``idempotent`` waar is.
        """

        max_pogingen = (self.max_retries + 1) if idempotent else 1
        laatste = None

        for poging in range(1, max_pogingen + 1):

            try:
                status, data = self._do_request(method, path, body)

            except ssl.SSLError as error:
                # TLS-fout (bijv. certificaat niet vertrouwd): nooit herhalen.
                return RemoteResult(
                    False,
                    0,
                    fout_code=FOUT_TLS,
                    fout_melding=f"{_MELDINGEN[FOUT_TLS]} ({error})",
                    pogingen=poging,
                    lokaal=True,
                )

            except TimeoutError:
                laatste = RemoteResult(
                    False,
                    0,
                    fout_code=FOUT_TIMEOUT,
                    fout_melding=_MELDINGEN[FOUT_TIMEOUT],
                    pogingen=poging,
                    lokaal=True,
                )

            except http.client.HTTPException as error:
                laatste = RemoteResult(
                    False,
                    0,
                    fout_code=FOUT_VERBROKEN,
                    fout_melding=f"{_MELDINGEN[FOUT_VERBROKEN]} ({error})",
                    pogingen=poging,
                    lokaal=poging == 1,
                )

            except (ConnectionError, socket.gaierror, OSError) as error:
                laatste = RemoteResult(
                    False,
                    0,
                    fout_code=FOUT_NIET_BEREIKBAAR,
                    fout_melding=f"{_MELDINGEN[FOUT_NIET_BEREIKBAAR]} ({error})",
                    pogingen=poging,
                    lokaal=True,
                )

            else:
                resultaat = self._parse_antwoord(status, data, poging)

                if resultaat.ok or status not in _RETRYABLE_STATUS:
                    return resultaat

                laatste = resultaat

            if poging < max_pogingen and self.backoff:
                time.sleep(self.backoff * poging)

        # Let op: RemoteResult is falsy wanneer ok=False, dus geen `or`.
        if laatste is not None:
            return laatste

        return RemoteResult(
            False,
            0,
            fout_code=FOUT_NIET_BEREIKBAAR,
            fout_melding=_MELDINGEN[FOUT_NIET_BEREIKBAAR],
            pogingen=max_pogingen,
            lokaal=True,
        )

    # -- publieke API -------------------------------------------------

    def health(self):
        """Vraagt of de agent online is (idempotent, mag herhaald worden)."""

        return self._request("GET", protocol.ROUTE_HEALTH, b"", idempotent=True)

    def is_online(self):
        """True als de agent bereikbaar en geautoriseerd is."""

        return self.health().ok

    def telemetry(self):
        """Vraagt status/telemetrie op (CPU/RAM/schijf/uptime/GPU).

        Read-only en idempotent, dus veilig om opnieuw te proberen. Het
        resultaat zit in ``RemoteResult.resultaat`` (de telemetrie-dict).
        """

        return self._request("GET", protocol.ROUTE_TELEMETRY, b"", idempotent=True)

    def send_command(self, tool, arguments=None, question=None, idempotent=None):
        """Valideert en verstuurt een toegestane actie.

        De actie wordt eerst tegen de allowlist gecontroleerd (vroeg
        weigeren, zonder het netwerk op te gaan). Daarna wordt de
        idempotentie uit de vaste tabel bepaald en een ondertekend
        verzoek verstuurd.
        """

        schoon, reden = allowlist.validate_call(tool, arguments)

        if schoon is None:
            return RemoteResult(
                False,
                0,
                fout_code=FOUT_NIET_TOEGESTAAN,
                fout_melding=reden,
                pogingen=0,
                lokaal=True,
            )

        if idempotent is None:
            idempotent = get_tool_idempotent(tool)

        bericht = {"tool": str(tool).strip()}
        if schoon:
            bericht["arguments"] = schoon
        if question:
            bericht["question"] = str(question)

        body = protocol.encode_body(bericht)

        return self._request(
            "POST", protocol.ROUTE_COMMAND, body, idempotent=bool(idempotent)
        )
