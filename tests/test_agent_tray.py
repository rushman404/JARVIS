"""Taakbalk-icoon van de Game-PC Agent: starten, stoppen en bewaken."""

import threading

import pytest

from remote import tray, zelf_update


class NepProces:
    def __init__(self, pid):
        self.pid = pid
        self.code = None
        self.gestopt = False

    def poll(self):
        return self.code

    def terminate(self):
        self.gestopt = True
        self.code = 1

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.code


class Klok:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def beheer(tmp_path):
    gestart = []

    def popen(commando, **kwargs):
        gestart.append(kwargs)
        return NepProces(len(gestart))

    toestanden, meldingen = [], []
    b = tray.AgentBeheer(commando=["python", "-m", "remote.server"], popen=popen, klok=Klok(),
                         log_pad=str(tmp_path / "agent.log"), bij_wijziging=toestanden.append,
                         melder=meldingen.append)
    b.gestart, b.toestanden, b.meldingen = gestart, toestanden, meldingen
    return b


def test_start_zet_tray_vlag_en_schrijft_naar_log(beheer, tmp_path):
    beheer.start()
    assert beheer.toestand == tray.TOESTAND_DRAAIT
    kwargs = beheer.gestart[0]
    assert kwargs["env"][tray.ENV_TRAY] == "1"
    assert kwargs["stdout"].name == str(tmp_path / "agent.log")


def test_tweede_start_start_geen_tweede_agent(beheer):
    beheer.start()
    beheer.start()
    assert len(beheer.gestart) == 1


def test_stoppen_en_niet_vanzelf_herstarten(beheer):
    beheer.start()
    proces = beheer.proces
    beheer.stop()
    assert proces.gestopt
    assert beheer.toestand == tray.TOESTAND_GESTOPT
    beheer.klok.t += 3600
    beheer.controleer()
    assert len(beheer.gestart) == 1


def test_herstarten_start_een_nieuwe_agent(beheer):
    beheer.start()
    oud = beheer.proces
    beheer.herstart()
    assert oud.gestopt
    assert len(beheer.gestart) == 2
    assert beheer.toestand == tray.TOESTAND_DRAAIT


def test_na_update_meteen_herstarten(beheer):
    beheer.start()
    beheer.proces.code = tray.EXIT_HERSTART
    beheer.controleer()
    assert len(beheer.gestart) == 2
    assert beheer.herstarts == []


def test_na_crash_herstarten_na_wachttijd(beheer):
    beheer.start()
    beheer.proces.code = 1
    beheer.controleer()
    assert beheer.toestand == tray.TOESTAND_HERSTART
    assert len(beheer.gestart) == 1
    beheer.klok.t += tray.WACHTTIJDEN[0]
    beheer.controleer()
    assert len(beheer.gestart) == 2
    assert beheer.toestand == tray.TOESTAND_DRAAIT


def test_te_vaak_gecrasht_geeft_op_met_melding(beheer):
    beheer.start()
    for _ in range(tray.MAX_HERSTARTS):
        beheer.proces.code = 1
        beheer.controleer()
        beheer.klok.t = beheer._volgende_start
        beheer.controleer()
    beheer.proces.code = 1
    beheer.controleer()
    assert beheer.toestand == tray.TOESTAND_OPGEGEVEN
    assert beheer.meldingen
    # Zelf weer starten mag altijd en begint de teller opnieuw.
    beheer.start()
    assert beheer.toestand == tray.TOESTAND_DRAAIT
    assert beheer.herstarts == []


def test_log_wordt_geroteerd(tmp_path):
    pad = tmp_path / "agent.log"
    pad.write_bytes(b"x" * 20)
    tray._roteer_log(str(pad), max_bytes=10)
    assert not pad.exists()
    assert (tmp_path / "agent.log.1").exists()


def test_elke_toestand_heeft_kleur_en_tekst():
    # PIL is in de tests nagebootst (conftest); de afbeelding zelf niet testen.
    assert set(tray.KLEUREN) == set(tray.TEKSTEN)


def _herstart_codes(monkeypatch, tray_vlag):
    if tray_vlag:
        monkeypatch.setenv("JARVIS_AGENT_TRAY", "1")
    else:
        monkeypatch.delenv("JARVIS_AGENT_TRAY", raising=False)
    codes, gestart, klaar = [], [], threading.Event()
    zelf_update.plan_herstart(vertraging=0, exit_fn=lambda c: (codes.append(c), klaar.set()),
                              popen=lambda *a, **k: gestart.append(a))
    assert klaar.wait(5)
    return codes, gestart


def test_zelf_update_onder_icoon_laat_het_icoon_herstarten(monkeypatch):
    codes, gestart = _herstart_codes(monkeypatch, tray_vlag=True)
    assert codes == [tray.EXIT_HERSTART]
    assert gestart == []


def test_zelf_update_zonder_icoon_start_zelf_een_nieuwe_agent(monkeypatch):
    codes, gestart = _herstart_codes(monkeypatch, tray_vlag=False)
    assert codes == [0]
    assert len(gestart) == 1
