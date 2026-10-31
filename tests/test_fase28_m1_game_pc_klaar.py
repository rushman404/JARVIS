"""Fase 28, M1 — laat het weten als de game-pc klaar is met updaten/downloaden.

Alles met een nep-game-pc: er wordt nooit echt iets gelezen of herstart.
"""

import pytest

from actions import achtergrond
from core import game_pc_klaar as k
from core.result_validation import ToolResult


@pytest.fixture(autouse=True)
def schoon():
    k._actief["wachter"] = None
    k._meld["fn"] = None
    yield
    w = k._actief["wachter"]
    if w is not None:
        w.stop()
    k._actief["wachter"] = None
    from core.confirmation import clear_pending
    clear_pending()


def status(windows=False, herstart=False, steam=(), riot=False):
    return {
        "windows": {"bezig": windows, "herstart": herstart},
        "steam": {"bezig": bool(steam), "games": [{"naam": n, "procent": p} for n, p in steam]},
        "riot": {"bezig": riot, "draait": True},
    }


class NepPc:
    def __init__(self, *standen):
        self.standen = list(standen)
        self.vragen = []

    def __call__(self, tool, args):
        self.vragen.append(tool)
        stand = self.standen.pop(0) if len(self.standen) > 1 else self.standen[0]
        if stand is None:
            return ToolResult(ok=False, message="weg", data={})
        return ToolResult(ok=True, message="", data={"resultaat": {"ok": True, "data": stand}})


class NepWachter(k.Wachter):
    gestart = []

    def start(self):
        NepWachter.gestart.append(self)
        return self


# ---------------------------------------------------------------------
# Herkennen
# ---------------------------------------------------------------------

@pytest.mark.parametrize("zin,soort,bronnen", [
    ("laat het me weten als de game-pc klaar is met updaten", "melden", k.BRONNEN),
    ("laat me weten wanneer steam klaar is met downloaden", "melden", ("steam",)),
    ("zeg het als valorant klaar is met updaten", "melden", ("riot",)),
    ("meld het zodra windows update klaar is", "melden", ("windows",)),
    ("laat het weten als de download klaar is", "melden", ("steam", "riot")),
    ("laat het me weten als de game pc klaar is", "melden", k.BRONNEN),
    ("is de game-pc al klaar met updaten?", "vraag", k.BRONNEN),
    ("is steam klaar met downloaden", "vraag", ("steam",)),
    ("is de game-pc nog aan het updaten", "vraag", k.BRONNEN),
    ("stop met wachten op de game-pc", "stop", k.BRONNEN),
])
def test_herken(zin, soort, bronnen):
    assert k.herken(zin) == (soort, bronnen)


@pytest.mark.parametrize("zin", [
    "laat het weten als de timer klaar is",
    "zijn er updates voor jarvis",
    "open steam op de game-pc",
    "herstart de game-pc",
    "zet een timer van tien minuten",
    "update jezelf",
])
def test_niet_voor_ons(zin):
    assert k.herken(zin) is None


# ---------------------------------------------------------------------
# Melden en vragen
# ---------------------------------------------------------------------

def test_melden_start_wachter():
    NepWachter.gestart = []
    pc = NepPc(status(steam=[("Valorant", 40)]))
    antwoord = k.melden(k.BRONNEN, pc_fn=pc, online_fn=lambda: True, maak_wachter=NepWachter)
    assert "Steam downloadt Valorant (40 procent)" in antwoord
    assert "laat het weten" in antwoord
    assert len(NepWachter.gestart) == 1
    assert NepWachter.gestart[0].gezien == ["Valorant"]


def test_niets_bezig():
    pc = NepPc(status())
    assert k.melden(k.BRONNEN, pc_fn=pc, online_fn=lambda: True) == k.NIETS_BEZIG
    assert k._actief["wachter"] is None


def test_game_pc_uit():
    pc = NepPc(status())
    assert k.melden(k.BRONNEN, pc_fn=pc, online_fn=lambda: False) == k.GAME_PC_UIT
    assert pc.vragen == []


def test_niet_te_lezen():
    assert k.melden(k.BRONNEN, pc_fn=NepPc(None), online_fn=lambda: True) == k.NIET_TE_LEZEN


def test_alleen_steam_ziet_windows_niet():
    pc = NepPc(status(windows=True))
    assert k.melden(("steam",), pc_fn=pc, online_fn=lambda: True) == k.NIETS_BEZIG


def test_vraag_geeft_stand():
    pc = NepPc(status(windows=True, steam=[("Euro Truck Simulator 2", None)]))
    antwoord = k.vraag(k.BRONNEN, pc_fn=pc, online_fn=lambda: True)
    assert antwoord == "Nee, sir: Windows installeert updates en Steam downloadt Euro Truck Simulator 2."


def test_vraag_klaar_met_herstart_vraagt_ja():
    from core.confirmation import get_pending

    pc = NepPc(status(herstart=True))
    antwoord = k.vraag(k.BRONNEN, pc_fn=pc, online_fn=lambda: True, stil_fn=lambda: False)
    assert antwoord.startswith("Ja, sir")
    assert "Zal ik dat doen?" in antwoord
    p = get_pending()
    assert p["kind"] == "power_confirm" and p["action"] == "restart" and p["target"] == "game-pc"


def test_herstart_s_nachts_alleen_hint():
    from core.confirmation import get_pending

    pc = NepPc(status(herstart=True))
    antwoord = k.vraag(("windows",), pc_fn=pc, online_fn=lambda: True, stil_fn=lambda: True)
    assert "herstart de game-pc" in antwoord
    assert get_pending() is None


def test_riot_onbekend_eerlijk():
    s = status()
    s["riot"] = {"bezig": None, "draait": True}
    antwoord = k.melden(("riot",), pc_fn=NepPc(s), online_fn=lambda: True)
    assert "kan ik nu niet zien" in antwoord


def test_stop():
    assert k.stop() == k.GEEN_WACHTER
    w = k.Wachter(pc_fn=NepPc(status(windows=True)), interval=999)
    k._actief["wachter"] = w
    assert k.stop() == k.GESTOPT
    assert w._stop.is_set() and k._actief["wachter"] is None


# ---------------------------------------------------------------------
# De wachter
# ---------------------------------------------------------------------

class Klok:
    def __init__(self):
        self.nu = 0.0

    def __call__(self):
        return self.nu


def _wachter(pc, bronnen=k.BRONNEN, stil=False):
    klok = Klok()
    meldingen = []
    w = k.Wachter(bronnen, pc_fn=pc, meld_fn=lambda t, bron: meldingen.append((t, bron)), klok=klok,
                  interval=60, stil_fn=lambda: stil)
    return w, klok, meldingen


def test_wachter_meldt_na_twee_rustige_controles():
    pc = NepPc(status(steam=[("Valorant", 50)]), status(steam=[("Valorant", 90)]), status(), status())
    w, klok, meldingen = _wachter(pc)
    for _ in range(3):
        klok.nu += 60
        assert w.stap() is None
    klok.nu += 60
    tekst = w.stap()
    assert tekst == "Sir, de game-pc is klaar: Valorant is klaar."
    assert meldingen == [(tekst, "game-pc")]
    assert w.stap() is None  # één keer


def test_wachter_windows_pauze_is_nog_niet_klaar():
    pc = NepPc(status(windows=True), status(), status(windows=True), status(), status())
    w, klok, meldingen = _wachter(pc)
    uitkomsten = []
    for _ in range(5):
        klok.nu += 60
        uitkomsten.append(w.stap())
    assert uitkomsten[:4] == [None] * 4
    assert uitkomsten[4].startswith("Sir, de game-pc is klaar: Windows Update is klaar.")


def test_wachter_biedt_herstart_aan():
    from core.confirmation import get_pending

    pc = NepPc(status(windows=True), status(herstart=True))
    w, klok, _ = _wachter(pc)
    for _ in range(3):
        klok.nu += 60
        tekst = w.stap() or ""
    assert tekst.endswith(k.HERSTART_VRAAG)
    assert get_pending()["kind"] == "power_confirm"


def test_wachter_geen_herstart_als_alleen_steam_liep():
    pc = NepPc(status(steam=[("Valorant", 10)]), status(herstart=True))
    w, klok, _ = _wachter(pc)
    for _ in range(3):
        klok.nu += 60
        tekst = w.stap() or ""
    assert tekst == "Sir, de game-pc is klaar: Valorant is klaar."


def test_wachter_meerdere_dingen():
    pc = NepPc(status(windows=True, steam=[("Valorant", 10)], riot=True), status())
    w, klok, _ = _wachter(pc)
    uitkomsten = []
    for _ in range(3):
        klok.nu += 60
        uitkomsten.append(w.stap())
    assert uitkomsten[:2] == [None, None]
    assert "Windows Update, Valorant en de Riot-update zijn klaar" in uitkomsten[2]


def test_wachter_overleeft_herstart_van_de_game_pc():
    pc = NepPc(status(windows=True), None, None, status(), status())
    w, klok, meldingen = _wachter(pc)
    for _ in range(4):
        klok.nu += 60
        assert w.stap() is None
    klok.nu += 60
    assert w.stap().startswith("Sir, de game-pc is klaar")


def test_wachter_stopt_na_een_uur_offline():
    pc = NepPc(status(windows=True), None)
    w, klok, meldingen = _wachter(pc)
    klok.nu += 60
    w.stap()
    klok.nu += k.MAX_OFFLINE + 1
    assert "niet bereikbaar" in w.stap()
    assert w.klaar


def test_wachter_stopt_na_zes_uur():
    pc = NepPc(status(windows=True))
    w, klok, _ = _wachter(pc)
    klok.nu = k.MAX_WACHT + 1
    assert "zes uur" in w.stap()


def test_nieuwe_vraag_voegt_bronnen_samen():
    NepWachter.gestart = []
    k.melden(("steam",), pc_fn=NepPc(status(steam=[("A", 1)])), online_fn=lambda: True, maak_wachter=NepWachter)
    k.melden(("windows",), pc_fn=NepPc(status(windows=True)), online_fn=lambda: True, maak_wachter=NepWachter)
    assert NepWachter.gestart[0]._stop.is_set()
    assert NepWachter.gestart[1].bronnen == ("windows", "steam")


def test_meld_fout_breekt_niets():
    def kapot(*a, **kw):
        raise RuntimeError("stuk")

    pc = NepPc(status())
    w = k.Wachter(pc_fn=pc, meld_fn=kapot, klok=Klok(), interval=60)
    w.rust = 1
    assert w.stap().startswith("Sir")


# ---------------------------------------------------------------------
# De game-pc-kant (actions/achtergrond.py)
# ---------------------------------------------------------------------

MANIFEST = '''"AppState"
{
	"appid"		"1172470"
	"name"		"Apex Legends"
	"StateFlags"		"%s"
	"BytesToDownload"		"%s"
	"BytesDownloaded"		"%s"
}'''


def test_steam_manifest_download_loopt():
    assert achtergrond.steam_download(MANIFEST % (1026, 1000, 250)) == {"naam": "Apex Legends", "procent": 25}


def test_steam_manifest_klaar_of_gepauzeerd():
    assert achtergrond.steam_download(MANIFEST % (4, 1000, 1000)) is None
    assert achtergrond.steam_download(MANIFEST % (4, 0, 0)) is None
    assert achtergrond.steam_download(MANIFEST % (4 | 512, 1000, 300)) is None


def test_steam_map(tmp_path):
    apps = tmp_path / "steamapps"
    apps.mkdir()
    (apps / "appmanifest_1.acf").write_text(MANIFEST % (1026, 100, 10), encoding="utf-8")
    (apps / "appmanifest_2.acf").write_text((MANIFEST % (4, 0, 0)).replace("1172470", "2"), encoding="utf-8")
    uit = achtergrond.steam(str(tmp_path))
    assert uit == {"bezig": True, "games": [{"naam": "Apex Legends", "procent": 10}]}


def test_windows_update():
    assert achtergrond.windows_update(lambda: True, lambda: False) == {"bezig": True, "herstart": False}
    assert achtergrond.windows_update(lambda: None, lambda: True) == {"bezig": None, "herstart": True}


def test_riot_api_en_schijf():
    assert achtergrond.riot(get_fn=lambda p: {"action": "Patching"})["bezig"] is True
    assert achtergrond.riot(get_fn=lambda p: [{"action": "Idle"}])["bezig"] is False

    def geen_api(p):
        raise OSError("404")

    assert achtergrond.riot(get_fn=geen_api, schrijft_fn=lambda: True)["bezig"] is True
    assert achtergrond.riot(get_fn=geen_api, schrijft_fn=lambda: None)["bezig"] is None


def test_riot_niet_geinstalleerd(tmp_path):
    assert achtergrond.riot(lockfile=str(tmp_path / "geen")) == {"bezig": False, "draait": False}


def test_riot_schrijft():
    class Proc:
        def __init__(self):
            self.n = 0

        def io_counters(self):
            self.n += 1
            return type("io", (), {"write_bytes": self.n * 5 * 1024 * 1024})()

    assert achtergrond._riot_schrijft(lambda: [Proc()], slaap=lambda s: None) is True
    assert achtergrond._riot_schrijft(lambda: [], slaap=lambda s: None) is False


def test_status_valt_niet_om(monkeypatch):
    monkeypatch.setattr(achtergrond, "windows_update", lambda: 1 / 0)
    monkeypatch.setattr(achtergrond, "steam", lambda: {"bezig": False, "games": []})
    monkeypatch.setattr(achtergrond, "riot", lambda: {"bezig": False, "draait": False})
    data = achtergrond.achtergrond_status().data
    assert data["windows"] == {"bezig": None}


# ---------------------------------------------------------------------
# Aansluiting
# ---------------------------------------------------------------------

def test_tool_overal_geregistreerd():
    from core import pc_target, tool_registry, tool_select
    from remote import allowlist, tools as remote_tools

    assert allowlist.validate_call("achtergrond_status", {})[0] == {}
    assert allowlist.is_allowed_in_profiel("achtergrond_status", allowlist.PROFIEL_BASIS)
    assert remote_tools.is_remote_tool("game_pc_achtergrond_status")
    assert pc_target.LOCAL_TO_REMOTE["achtergrond_status"] == "game_pc_achtergrond_status"
    assert "achtergrond_status" in tool_select.ALLEEN_INTERN
    assert "achtergrond_status" in tool_registry.get_schema_tool_names()


def test_brein_route(monkeypatch):
    from core import brain

    monkeypatch.setattr(k, "_std_online", lambda: False)
    assert brain.process_command("laat het me weten als de game-pc klaar is met updaten") == k.GAME_PC_UIT


def test_opstart():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert "game_pc_klaar.zet_meld(" in (root / "main.py").read_text(encoding="utf-8")
    assert "GAMEPC_KLAAR_CHECK_SECONDEN=60" in (root / ".env.example").read_text(encoding="utf-8")
