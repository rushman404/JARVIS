"""Handmatige LAN-test voor de Game-PC Agent (Fase 15).

Draai dit script op de **mini-pc** (het brein) terwijl de agent op de
game-pc draait. Het script controleert stap voor stap de echte
LAN-verbinding en drukt per stap "geslaagd" of "mislukt" af, in het
Nederlands.

Gebruik::

    python scripts/test_remote_lan_manual.py

Het leest de client-instellingen uit ``.env`` (``REMOTE_CLIENT_HOST``,
``REMOTE_CLIENT_PORT``, ``REMOTE_CLIENT_TOKEN`` en
``REMOTE_CLIENT_CA_FILE``). Zorg dat die naar de game-pc wijzen, niet
naar ``127.0.0.1``.

De stappen:

1. Online-check      — is de poort van de agent bereikbaar?
2. Ondertekende health — klopt het token en het certificaat?
3. Verkeerd token    — hoort een *verkeerd* token netjes 401 te geven?
4. Verouderde tijd   — hoort een *oude* handtekening geweigerd te worden?
5. Volume-opdracht   — stuurt een echte (goedgekeurde) opdracht.
6. Screenshot        — maakt een echte schermafbeelding op de game-pc.

Stap 5 en 6 hebben echt effect op de game-pc. Zorg dat dat mag.
"""

import http.client
import socket
import sys
import time

import config
from remote import protocol
from remote.client import RemoteClient


def _meld(naam, geslaagd, detail=""):
    """Drukt één stap af in het Nederlands en geeft de uitslag terug."""

    uitslag = "geslaagd" if geslaagd else "mislukt"
    regel = f"[JARVIS] {naam}: {uitslag}"

    if detail:
        regel += f" ({detail})"

    print(regel)

    return geslaagd


def _ruw_verzoek(client, method, path, body=b"", timestamp=None):
    """Doet een rauw ondertekend HTTPS-verzoek en geeft (status, body)."""

    verbinding = http.client.HTTPSConnection(
        client.host,
        client.port,
        context=client._ssl_context(),
        timeout=client.timeout,
    )

    try:
        headers = protocol.signed_headers(
            client.token, method, path, body, timestamp=timestamp
        )
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
        verbinding.request(method, path, body=body or None, headers=headers)
        antwoord = verbinding.getresponse()
        return antwoord.status, antwoord.read()
    finally:
        try:
            verbinding.close()
        except Exception:
            pass


def stap_online(client):
    """Stap 1 — is de agent-poort bereikbaar op het netwerk?"""

    try:
        with socket.create_connection((client.host, client.port), timeout=client.timeout):
            return _meld("Stap 1 — online-check", True, f"{client.host}:{client.port}")
    except OSError as error:
        return _meld("Stap 1 — online-check", False, str(error))


def stap_health(client):
    """Stap 2 — ondertekende health (token + certificaat correct?)."""

    resultaat = client.health()

    if resultaat.ok:
        return _meld("Stap 2 — ondertekende health", True, "agent is online")

    return _meld(
        "Stap 2 — ondertekende health",
        False,
        f"status {resultaat.status}: {resultaat.samenvatting()}",
    )


def stap_verkeerd_token():
    """Stap 3 — een verkeerd token hoort 401 te geven."""

    fout = RemoteClient(token="x" * 32)
    resultaat = fout.health()

    if resultaat.status == 401:
        return _meld("Stap 3 — verkeerd token", True, "netjes geweigerd met 401")

    return _meld(
        "Stap 3 — verkeerd token",
        False,
        f"verwachtte 401, kreeg {resultaat.status}",
    )


def stap_verouderde_tijd(client):
    """Stap 4 — een oude handtekening hoort geweigerd te worden."""

    oud = int(time.time()) - 3600

    try:
        status, _ = _ruw_verzoek(
            client, "GET", protocol.ROUTE_HEALTH, timestamp=oud
        )
    except OSError as error:
        return _meld("Stap 4 — verouderde tijd", False, str(error))

    if status == 401:
        return _meld("Stap 4 — verouderde tijd", True, "netjes geweigerd met 401")

    return _meld(
        "Stap 4 — verouderde tijd",
        False,
        f"verwachtte 401, kreeg {status}",
    )


def stap_volume(client):
    """Stap 5 — een echte volume-opdracht op de game-pc."""

    resultaat = client.send_command("set_volume", {"percent": 20})

    if resultaat.ok:
        return _meld("Stap 5 — volume-opdracht", True, resultaat.samenvatting())

    return _meld(
        "Stap 5 — volume-opdracht",
        False,
        f"status {resultaat.status}: {resultaat.samenvatting()}",
    )


def stap_screenshot(client):
    """Stap 6 — een echte schermafbeelding op de game-pc."""

    resultaat = client.send_command("screenshot", {})

    if resultaat.ok:
        return _meld("Stap 6 — screenshot", True, resultaat.samenvatting())

    return _meld(
        "Stap 6 — screenshot",
        False,
        f"status {resultaat.status}: {resultaat.samenvatting()}",
    )


def main():
    print("[JARVIS] LAN-test voor de Game-PC Agent.")
    print(
        f"[JARVIS] Doel: {config.REMOTE_CLIENT_HOST}:{config.REMOTE_CLIENT_PORT}"
    )
    print()

    try:
        client = RemoteClient()
    except ValueError as error:
        print(f"[JARVIS] Configuratie onjuist: {error}")
        print("[JARVIS] Vul REMOTE_CLIENT_* in .env in en probeer opnieuw.")
        return 1

    uitslagen = [
        stap_online(client),
        stap_health(client),
        stap_verkeerd_token(),
        stap_verouderde_tijd(client),
        stap_volume(client),
        stap_screenshot(client),
    ]

    gelukt = sum(1 for u in uitslagen if u)

    print()
    print(f"[JARVIS] Klaar: {gelukt} van {len(uitslagen)} stappen geslaagd.")

    return 0 if gelukt == len(uitslagen) else 1


if __name__ == "__main__":
    sys.exit(main())
