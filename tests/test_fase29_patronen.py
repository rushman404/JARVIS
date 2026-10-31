"""Fase 29 — leren van u: gebruikslog, voorstellen, focus-muziek en beheer.

Alles met een nep-klok, een tijdelijk patronen.json en nep-acties: er gaat
nooit echt een lamp aan of muziek spelen.
"""

from datetime import datetime, timedelta

import pytest

from core import confirmation, patronen as p


@pytest.fixture(autouse=True)
def schoon():
    confirmation.clear_pending()
    yield
    confirmation.clear_pending()


ZA = datetime(2026, 10, 31, 19, 0)       # zaterdag
VR = datetime(2026, 10, 30, 19, 0)       # vrijdag


def _ts(dt):
    return dt.timestamp()


def lamp(dt, h=30, entity="light.bed_lamp"):
    return p.noteer_lamp(entity, "bedlamp", "turn_on", h, t=_ts(dt))


def werkdagen_terug(vanaf, n):
    """De n werkdagen vóór ``vanaf`` (zelfde tijd)."""

    uit, dag = [], vanaf
    while len(uit) < n:
        dag -= timedelta(days=1)
        if dag.weekday() < 5:
            uit.append(dag)
    return uit


# ---------------------------------------------------------------------
# M1 — noteren
# ---------------------------------------------------------------------

def test_noteer_lamp():
    g = p.noteer_lamp("light.bed_lamp", "Bed lamp ", "turn_on", 33.3)
    assert g["label"] == "de Bed lamp op 30 procent"
    assert g["sleutel"] == "lamp|light.bed_lamp|turn_on|30"
    assert p.noteer_lamp("light.x", "x", "turn_off")["label"] == "de x uit"
    assert p.noteer_lamp("switch.tv", "tv", "turn_on") is None
    assert p.noteer_lamp("light.x", "x", "toggle") is None
    assert len(p.lees()["gebeurtenissen"]) == 2


def test_oude_gebeurtenissen_verdwijnen():
    oud = datetime.now() - timedelta(days=p.BEWAAR_DAGEN + 1)
    lamp(oud)
    lamp(datetime.now())
    assert len(p.lees()["gebeurtenissen"]) == 1


def test_uit_te_zetten(monkeypatch):
    import config

    monkeypatch.setattr(config, "PATRONEN_LEREN", False)
    assert lamp(datetime.now()) is None
    assert p.lees()["gebeurtenissen"] == []


def test_home_assistant_noteert_gelukte_lampactie(monkeypatch):
    from core import home_assistant as ha

    staat = {"state": "off"}

    def get(pad):
        return True, {"entity_id": "light.bed_lamp", "state": staat["state"],
                      "attributes": {"friendly_name": "Bed lamp", "brightness": 77,
                                     "supported_color_modes": ["brightness"]}}

    def post(pad, payload):
        staat["state"] = "on"
        return True, []

    monkeypatch.setattr(ha, "_config_ok", lambda: True)
    monkeypatch.setattr(ha, "_ha_get", get)
    monkeypatch.setattr(ha, "_ha_post", post)
    monkeypatch.setattr(ha, "is_control_allowed", lambda e: (True, ""))
    monkeypatch.setattr(ha, "_domain_supports_service", lambda *a: (True, ""))
    monkeypatch.setattr(ha, "_entity_fits_service", lambda *a: (True, ""))
    monkeypatch.setattr(ha, "_check_service_data", lambda *a: (True, ""))
    monkeypatch.setattr(ha.time, "sleep", lambda s: None)
    antwoord = ha.control_home_assistant_tool("light", "turn_on", "light.bed_lamp", {"brightness_pct": 30})
    assert "is nu aan" in antwoord
    g = p.lees()["gebeurtenissen"]
    assert [x["sleutel"] for x in g] == ["lamp|light.bed_lamp|turn_on|30"]


class NepSpotify:
    def __init__(self, items, namen=None):
        self.items = items
        self.namen = namen or {}
        self.gevraagd = []

    def is_gekoppeld(self):
        return True

    def get(self, pad, params=None):
        self.gevraagd.append(pad)
        if pad == "/me/player/recently-played":
            return {"items": self.items}
        return {"name": self.namen.get(pad, "")}


def _item(dt, uri="spotify:playlist:abc", soort="playlist"):
    return {"played_at": dt.astimezone().isoformat(), "context": {"type": soort, "uri": uri}}


def test_muziek_verzamelaar_een_keer_per_uur():
    t0 = datetime(2026, 10, 30, 19, 0)
    items = [_item(t0 + timedelta(minutes=m)) for m in (0, 3, 7, 50, 75)] + [
        _item(t0, "spotify:album:x", "album")]
    v = p.MuziekVerzamelaar(klant=NepSpotify(items, {"/playlists/abc": "Chill"}), namen_fn=lambda: {})
    assert v.stap() == 2  # 19:00 en 20:15 (19:50 valt binnen het uur na 19:00)
    g = p.lees()["gebeurtenissen"]
    assert g[0]["label"] == "uw playlist 'Chill'"
    assert v.stap() == 0  # dezelfde items niet opnieuw


# ---------------------------------------------------------------------
# M2 — patronen vinden
# ---------------------------------------------------------------------

def test_drie_dagen_is_een_patroon():
    for dag in werkdagen_terug(datetime(2026, 11, 2, 19, 10), 3):
        lamp(dag)
    patr = p.vind_patronen(p.lees()["gebeurtenissen"], datetime(2026, 11, 2, 18, 0))
    assert len(patr) == 1
    assert patr[0]["dagtype"] == "werkdag" and p.tijd_tekst(patr[0]["minuut"]) == "19:10"


def test_twee_dagen_nog_niet():
    for dag in werkdagen_terug(datetime(2026, 11, 2, 19, 0), 2):
        lamp(dag)
    assert p.vind_patronen(p.lees()["gebeurtenissen"], datetime(2026, 11, 2, 18, 0)) == []


def test_tijdstip_marge_en_weekend_apart():
    nu = datetime(2026, 11, 2, 18, 0)  # maandag
    dagen = werkdagen_terug(nu, 3)
    lamp(dagen[0].replace(hour=19, minute=0))
    lamp(dagen[1].replace(hour=19, minute=25))
    lamp(dagen[2].replace(hour=20, minute=30))   # te laat
    lamp(datetime(2026, 11, 1, 19, 0))           # zondag: weekend
    assert p.vind_patronen(p.lees()["gebeurtenissen"], nu) == []


def test_ouder_dan_twee_weken_telt_niet():
    nu = datetime(2026, 11, 20, 18, 0)
    for dag in werkdagen_terug(datetime(2026, 11, 2), 3):
        lamp(dag.replace(hour=19))
    assert p.vind_patronen(p.lees()["gebeurtenissen"], nu) == []


def test_ochtend_en_avond_twee_patronen():
    nu = datetime(2026, 11, 2, 6, 0)
    for dag in werkdagen_terug(nu, 3):
        lamp(dag.replace(hour=7, minute=30), h=100)
        lamp(dag.replace(hour=7, minute=30) + timedelta(hours=14), h=100)
    patr = p.vind_patronen(p.lees()["gebeurtenissen"], nu)
    assert sorted(p.tijd_tekst(x["minuut"]) for x in patr) == ["07:30", "21:30"]


# ---------------------------------------------------------------------
# M2 — voorstellen
# ---------------------------------------------------------------------

class Klok:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt


def _planner(dt, stil=False):
    meldingen = []
    klok = Klok(dt)
    planner = p.PatroonPlanner(meld_fn=lambda t, bron: meldingen.append((t, bron)), klok=klok,
                               stil_fn=lambda: stil)
    return planner, klok, meldingen


@pytest.fixture
def avondlamp():
    maandag = datetime(2026, 11, 2, 19, 0)
    for dag in werkdagen_terug(maandag, 3):
        lamp(dag)
    return maandag


def test_vijf_minuten_vooraf_vragen(avondlamp):
    planner, klok, meldingen = _planner(avondlamp - timedelta(minutes=10))
    assert planner.stap() is None
    klok.dt = avondlamp - timedelta(minutes=5)
    vraag = planner.stap()
    assert vraag == "Sir, rond deze tijd zet u meestal de bedlamp op 30 procent. Zal ik dat doen?"
    assert meldingen == [(vraag, "patroon")]
    pending = confirmation.get_pending()
    assert pending["kind"] == p.KIND and pending["actie_info"]["helderheid"] == 30
    confirmation.clear_pending()
    assert planner.stap() is None  # één keer per dag


def test_niet_in_het_weekend_voor_een_werkdagpatroon(avondlamp):
    planner, _, _ = _planner(datetime(2026, 11, 7, 18, 56))  # zaterdag
    assert planner.stap() is None


def test_niet_als_het_stil_moet(avondlamp):
    planner, _, meldingen = _planner(avondlamp - timedelta(minutes=4), stil=True)
    assert planner.stap() is None and meldingen == []


def test_niet_als_er_al_een_vraag_loopt(avondlamp):
    confirmation.set_pending("muziek_voorstel", {"question": "x"})
    planner, _, _ = _planner(avondlamp - timedelta(minutes=4))
    assert planner.stap() is None


def test_niet_als_u_het_al_deed(avondlamp):
    lamp(avondlamp - timedelta(minutes=8))
    planner, _, meldingen = _planner(avondlamp - timedelta(minutes=4))
    assert planner.stap() is None and meldingen == []


def test_ja_voert_uit(monkeypatch, avondlamp):
    from core import home_assistant as ha

    gedaan = []
    monkeypatch.setattr(ha, "control_home_assistant_tool",
                        lambda *a: gedaan.append(a) or "Bed lamp is nu aan.")
    planner, _, _ = _planner(avondlamp - timedelta(minutes=4))
    planner.stap()
    assert p.na_ja(confirmation.get_pending()) == "Bed lamp is nu aan."
    assert gedaan == [("light", "turn_on", "light.bed_lamp", {"brightness_pct": 30})]


def test_ja_via_het_brein(monkeypatch, avondlamp):
    from core import brain, home_assistant as ha

    gedaan = []
    monkeypatch.setattr(ha, "control_home_assistant_tool",
                        lambda *a: gedaan.append(a) or "Bed lamp is nu aan.")
    planner, _, _ = _planner(avondlamp - timedelta(minutes=4))
    planner.stap()
    assert brain.process_command("ja") == "Bed lamp is nu aan."
    assert len(gedaan) == 1


def test_twee_keer_nee_twee_weken_stil(avondlamp):
    planner, klok, _ = _planner(avondlamp - timedelta(minutes=4))
    planner.stap()
    assert p.na_nee(confirmation.get_pending()) == "Goed, sir; vandaag niet."
    confirmation.clear_pending()
    klok.dt += timedelta(days=1)   # dinsdag
    assert planner.stap()
    nu = klok.dt.timestamp()
    assert "twee weken" in p.na_nee(confirmation.get_pending(), nu=nu)
    confirmation.clear_pending()
    klok.dt += timedelta(days=1)
    assert planner.stap() is None


def test_nooit_meer_via_het_brein(avondlamp):
    from core import brain

    planner, klok, _ = _planner(avondlamp - timedelta(minutes=4))
    planner.stap()
    assert brain.process_command("stel dat nooit meer voor") == "Goed, sir; dat stel ik nooit meer voor."
    assert confirmation.get_pending() is None
    klok.dt += timedelta(days=1)
    assert planner.stap() is None


def test_ander_commando_laat_het_voorstel_vallen(monkeypatch, avondlamp):
    planner, _, _ = _planner(avondlamp - timedelta(minutes=4))
    planner.stap()
    assert confirmation.evaluate_answer("hoe laat is het", p.KIND) == "cancel"


def test_muziek_voorstel_speelt_playlist(monkeypatch):
    from core import spotify_smaak

    gespeeld = []
    monkeypatch.setattr(spotify_smaak, "speel", lambda keuze, *a, **k: gespeeld.append(keuze) or "Speelt nu.")
    actie = {"type": "muziek", "uri": "spotify:playlist:abc", "naam": "Chill"}
    assert p.na_ja({"patroon": "x", "actie_info": actie}) == "Speelt nu."
    assert gespeeld[0]["uri"] == "spotify:playlist:abc" and gespeeld[0]["playlist"] is True


# ---------------------------------------------------------------------
# M3 — muziek bij focus
# ---------------------------------------------------------------------

def _focus_met_muziek(dagen, uri="spotify:playlist:fff", naam="Lofi"):
    for i in range(dagen):
        f = datetime(2026, 10, 25, 14, 0) + timedelta(days=i)
        p.noteer_focus(t=_ts(f))
        p.noteer_muziek(uri, naam, t=_ts(f + timedelta(minutes=3)))


def test_focus_playlist_na_drie_keer():
    nu = datetime(2026, 10, 31, 12, 0)
    _focus_met_muziek(2)
    assert p.focus_playlist(p.lees()["gebeurtenissen"], nu) is None
    _focus_met_muziek(3)
    assert p.focus_playlist(p.lees()["gebeurtenissen"], nu)["label"] == "uw playlist 'Lofi'"


def test_voorstel_bij_focus_zet_vraag_klaar():
    _focus_met_muziek(3)
    vraag = p.voorstel_bij_focus(nu=datetime(2026, 10, 31, 12, 0))
    assert vraag == " Zal ik uw playlist 'Lofi' opzetten, sir?"
    assert confirmation.get_pending()["actie_info"]["uri"] == "spotify:playlist:fff"


def test_focus_aan_noteert_en_stelt_voor(monkeypatch, tmp_path):
    from core import focusmodus
    from core.result_validation import ToolResult

    monkeypatch.setattr(p, "voorstel_bij_focus", lambda: " Zal ik uw playlist 'Lofi' opzetten, sir?")
    modus = focusmodus.FocusModus(pc_tool=lambda *a: ToolResult(ok=False, message="", data={}),
                                  toestand_pad=str(tmp_path / "focus.json"))
    tekst = modus.aan()
    assert tekst.endswith("Zal ik uw playlist 'Lofi' opzetten, sir?")
    assert [g["soort"] for g in p.lees()["gebeurtenissen"]] == ["focus"]


# ---------------------------------------------------------------------
# M4 — beheer
# ---------------------------------------------------------------------

def test_wat_heb_je_geleerd(avondlamp, monkeypatch):
    from core import brain

    monkeypatch.setattr(p, "datetime", type("D", (datetime,), {"now": staticmethod(lambda: avondlamp)}))
    antwoord = brain.process_command("wat heb je van mij geleerd?")
    assert antwoord == "Dit heb ik geleerd, sir: doordeweeks rond 19:00 zet u de bedlamp op 30 procent."


def test_nog_niets_geleerd():
    assert p.probeer_commando("wat heb je van mij geleerd").startswith("Ik heb nog geen vaste gewoontes")


def test_beheer_uit_aan_en_wissen(avondlamp):
    lijst = p.overzicht(nu=avondlamp)
    assert len(lijst) == 1 and lijst[0]["aan"] and lijst[0]["tijd"] == "19:00"
    pid = lijst[0]["id"]
    assert p.beheer(pid, "uit", nu=avondlamp)
    assert p.overzicht(nu=avondlamp)[0]["aan"] is False
    planner, _, _ = _planner(avondlamp - timedelta(minutes=4))
    assert planner.stap() is None
    assert p.beheer(pid, "aan", nu=avondlamp)
    assert p.beheer(pid, "wissen", nu=avondlamp)
    assert p.overzicht(nu=avondlamp) == []
    assert p.beheer(pid, "wissen", nu=avondlamp) is False


@pytest.mark.parametrize("zin", ["wat heb je van mij geleerd", "welke gewoontes heb je geleerd",
                                 "wat weet je over mijn gewoontes", "welke patronen ken je van mij", "wat zijn mijn gewoontes"])
def test_herkent_geleerd(zin):
    assert p.probeer_commando(zin) is not None


@pytest.mark.parametrize("zin", ["wat heb je geleerd op school", "vergeet mijn verjaardag", "zet de bedlamp aan"])
def test_niet_voor_ons(zin):
    assert p.probeer_commando(zin) is None


def test_opstart():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert "PatroonPlanner(meld_fn=" in (root / "main.py").read_text(encoding="utf-8")
    assert "PATRONEN_LEREN=1" in (root / ".env.example").read_text(encoding="utf-8")
    assert "memory/patronen.json" in (root / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# M4 — de iPad
# ---------------------------------------------------------------------

def test_dashboard_api(avondlamp, monkeypatch):
    from dashboard.api import DashboardAPI

    monkeypatch.setattr(p, "datetime", type("D", (datetime,), {"now": staticmethod(lambda: avondlamp)}))
    api = DashboardAPI(audit_fn=lambda **k: None)
    status, data = api.patronen()
    assert status == 200 and len(data["patronen"]) == 1
    pid = data["patronen"][0]["id"]
    status, data = api.patroon_beheer({"id": pid, "actie": "uit"})
    assert status == 200 and data["patronen"][0]["aan"] is False
    assert api.patroon_beheer({"id": pid, "actie": "weg"})[0] == 400
    assert api.patroon_beheer({"id": "../x", "actie": "uit"})[0] == 400
    assert api.patroon_beheer({"id": "0123456789", "actie": "uit"})[0] == 404
    assert api.patroon_beheer({"id": pid, "actie": "wissen"})[0] == 200
    assert api.patronen()[1]["patronen"] == []


def test_dashboard_routes_en_rollen():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    server = (root / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '("GET", "/api/patronen"): (k,' in server
    assert '("POST", "/api/patronen"): (b,' in server
    html = (root / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="instPatronen"' in html
