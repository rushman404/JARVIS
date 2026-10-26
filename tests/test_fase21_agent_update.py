"""Fase 21 — bij "update JARVIS" werkt de game-pc-agent zichzelf ook bij."""

import pytest

from beheer import updates
from remote import protocol, server, zelf_update
from remote.client import RemoteResult

TOKEN = "s" * 32


def _agent():
    return server.RemoteAgent(TOKEN, rate_limiter=server.RateLimiter(max_requests=0), audit=False,
                              allowed_ips=("127.0.0.1",))


def _update(agent, token=TOKEN, methode="POST"):
    headers = protocol.signed_headers(token, methode, server.ROUTE_UPDATE, b"")
    return agent.process(methode, server.ROUTE_UPDATE, headers, b"", client_ip="127.0.0.1")


# -----------------------------------------------------------------
# De agent: ondertekende route /update
# -----------------------------------------------------------------

def test_update_route_werkt_bij(monkeypatch):
    monkeypatch.setattr(zelf_update, "voer_uit", lambda: {"ok": True, "status": "bijgewerkt", "aantal": 2})
    status, data = _update(_agent())
    assert status == 200 and data == {"ok": True, "status": "bijgewerkt", "aantal": 2}


def test_update_route_vereist_handtekening_en_post(monkeypatch):
    gedaan = []
    monkeypatch.setattr(zelf_update, "voer_uit", lambda: gedaan.append(1) or {"ok": True})
    assert _update(_agent(), token="x" * 32)[0] == 401
    assert _update(_agent(), methode="GET")[0] == 405
    assert gedaan == []


def test_update_fout_laat_de_server_staan(monkeypatch):
    def kapot():
        raise RuntimeError("boem")

    monkeypatch.setattr(zelf_update, "voer_uit", kapot)
    status, data = _update(_agent())
    assert status == 200 and data["ok"] is False and data["fout"]["code"] == "update_fout"


def test_zelf_update_al_actueel():
    herstart = []
    uit = zelf_update.voer_uit(zoek_fn=lambda: {"aantal": 0}, installeer_fn=None, herstart_fn=herstart.append)
    assert uit == {"ok": True, "status": "actueel", "aantal": 0} and herstart == []


def test_zelf_update_installeert_zonder_backup_en_herstart():
    gezien, herstart = {}, []

    def installeer(backup_fn, pip_fn):
        gezien["backup"] = backup_fn()
        pip_fn("C:/JARVIS")  # requirements.txt veranderde
        return 3

    uit = zelf_update.voer_uit(zoek_fn=lambda: {"aantal": 3}, installeer_fn=installeer,
                               herstart_fn=herstart.append)
    assert uit == {"ok": True, "status": "bijgewerkt", "aantal": 3}
    assert gezien["backup"][0] is True and herstart == [True]


def test_zelf_update_weigert_lokale_wijzigingen():
    def installeer(**kw):
        raise updates.UpdateFout("er zijn lokale wijzigingen in de code (x.py); die overschrijf ik niet.")

    uit = zelf_update.voer_uit(zoek_fn=lambda: {"aantal": 1}, installeer_fn=installeer,
                               herstart_fn=lambda p: pytest.fail("niet herstarten"))
    assert uit["ok"] is False and "lokale wijzigingen" in uit["fout"]["melding"]


def test_herstart_start_een_nieuwe_agent(monkeypatch):
    monkeypatch.setattr(zelf_update.threading, "Thread",
                        lambda target, **kw: type("T", (), {"start": lambda self: target()})())
    gestart, gestopt = [], []
    zelf_update.plan_herstart(vertraging=0, exit_fn=gestopt.append,
                              popen=lambda cmd, **kw: gestart.append(cmd))
    assert gestart and gestart[0][1:] == ["-m", "remote.server"] and gestopt == [0]


# -----------------------------------------------------------------
# Het brein: na de eigen update ook de game-pc
# -----------------------------------------------------------------

class NepClient:
    def __init__(self, resultaat):
        self.resultaat = resultaat

    def update(self):
        return self.resultaat


@pytest.mark.parametrize("resultaat,stukje", [
    (RemoteResult(True, 200, resultaat={"ok": True, "status": "bijgewerkt"}), "ook bijgewerkt"),
    (RemoteResult(True, 200, resultaat={"ok": True, "status": "actueel"}), "al bij"),
    (RemoteResult(False, 404, fout_code="onbekende_route"), "git pull"),
    (RemoteResult(False, 200, fout_code="update_fout", fout_melding="er zijn lokale wijzigingen"),
     "lokale wijzigingen"),
    (RemoteResult(False, 0, fout_code="niet_bereikbaar", lokaal=True), "niet bereikbaar"),
])
def test_werk_game_pc_bij_teksten(resultaat, stukje):
    assert stukje in updates.werk_game_pc_bij(client_fn=lambda: NepClient(resultaat))


def test_zonder_game_pc_niets(monkeypatch):
    import config

    monkeypatch.setattr(config, "REMOTE_CLIENT_ENABLED", False)
    assert updates.werk_game_pc_bij() == ""


def test_na_ja_ook_de_game_pc(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_WAAKHOND", "1")
    herstart = []
    tekst = updates.voer_uit_na_goedkeuring(
        installeer_fn=lambda: 2, herstart_fn=lambda: herstart.append(1),
        status_pad=str(tmp_path / "u.json"), game_pc_fn=lambda: "De game-pc is ook bijgewerkt.")
    assert tekst == ("De update is geïnstalleerd (2 wijzigingen). De game-pc is ook bijgewerkt. "
                     "Ik start zo opnieuw op, sir.")
    assert herstart == [1]


def test_mislukte_update_raakt_de_game_pc_niet(tmp_path):
    def kapot():
        raise updates.UpdateFout("geen nieuwe versie")

    tekst = updates.voer_uit_na_goedkeuring(installeer_fn=kapot, status_pad=str(tmp_path / "u.json"),
                                            game_pc_fn=lambda: pytest.fail("niet naar de game-pc"))
    assert tekst.startswith("De update is niet geïnstalleerd")


@pytest.mark.parametrize("zin", ["werk de game-pc bij", "update de game pc", "game-pc bijwerken",
                                 "update de agent op de game-pc"])
def test_stemcommando(zin):
    assert updates.probeer_commando(zin, game_pc_fn=lambda: "De game-pc was al bij.") == "De game-pc was al bij."


def test_brein_routeert_het_stemcommando(monkeypatch):
    from core import brain

    monkeypatch.setattr(updates, "werk_game_pc_bij", lambda: "De game-pc was al bij.")
    assert brain.process_command("werk de game-pc bij") == "De game-pc was al bij."
