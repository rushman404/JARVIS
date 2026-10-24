"""Tests voor Fase 18 M2: de dashboard-server zonder sockets.

``DashboardServer.process()`` wordt direct aangeroepen. Dekt het
beveiligingstestplan uit docs/fase18_dashboard_design.md §12.1:
authenticatie en rollen, verkeerde tokens + lockout, rate-limit,
koppelcode, Host en Origin, geen CORS, security-headers, tokenrotatie,
statische bestanden (geen pad-uitbraak) en geen geheimen in het auditlog.
"""

import json

import pytest

from core.confirmation import ID_KEY, NONCE_KEY, clear_pending, set_pending
from core.timers import TimerStore
from dashboard import auth
from dashboard.api import DashboardAPI
from dashboard.server import CSP, DashboardServer, standaard_hosts, standaard_origins
from remote.server import AuthLockout, RateLimiter

VIEW = "kijk-token-0123456789abcdef"
CONTROL = "bedien-token-0123456789abcdef"
IPAD = "192.168.1.20"
HOST = "192.168.1.5:8780"
ORIGIN = "https://192.168.1.5:8780"
EPOCH = 1_000_000.0


class Klok:
    def __init__(self, nu=EPOCH):
        self.nu = nu

    def __call__(self):
        return self.nu


@pytest.fixture(autouse=True)
def schoon():
    clear_pending()
    yield
    clear_pending()


@pytest.fixture
def klok():
    return Klok()


@pytest.fixture
def audit_regels():
    return []


@pytest.fixture
def maak(tmp_path, klok, audit_regels):
    def _maak(**kwargs):
        api = DashboardAPI(
            timer_store=TimerStore(pad=str(tmp_path / "timers.json"), clock=klok),
            widgets_pad=str(tmp_path / "dashboard.json"),
            clock=klok,
            spreekt_fn=lambda: False,
            fase_fn=lambda: "rust",
            pc_target_fn=lambda: "local",
            uitvoerder=kwargs.pop("uitvoerder", lambda p, ok: "gedaan"),
            audit_fn=lambda **v: audit_regels.append(v),
        )
        register = auth.ApparaatRegister(str(tmp_path / "devices.json"), clock=klok)
        hosts = standaard_hosts(8780, "192.168.1.5")
        static = tmp_path / "static"
        static.mkdir(exist_ok=True)
        (static / "index.html").write_text("<!doctype html><title>JARVIS</title>", encoding="utf-8")
        (static / "app.js").write_text("console.log('ok')", encoding="utf-8")
        (tmp_path / "geheim.txt").write_text("geheim", encoding="utf-8")
        opties = dict(
            api=api,
            authenticator=auth.Authenticator(VIEW, CONTROL, register),
            koppelcode=auth.Koppelcode(300, clock=klok),
            allowed_hosts=hosts,
            allowed_origins=standaard_origins(hosts),
            rate_limiter=RateLimiter(1000, 60),
            static_dir=str(static),
            audit_fn=lambda **v: audit_regels.append(v),
        )
        opties.update(kwargs)
        return DashboardServer(**opties)

    return _maak


@pytest.fixture
def srv(maak):
    return maak()


def req(server, method, path, token=None, body=None, ip=IPAD, host=HOST, origin=ORIGIN,
        cookie=None, headers=None, now=None, content_type="application/json"):
    h = {"Host": host}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    if origin is not None and method in ("POST", "PUT", "DELETE"):
        h["Origin"] = origin
    if cookie is not None:
        h["Cookie"] = cookie
    data = b""
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        if content_type:
            h["Content-Type"] = content_type
    h.update(headers or {})
    return server.process(method, path, h, data, client_ip=ip, now=now)


def koppel(server, rol="bedien", ip=IPAD):
    code = server.koppelcode.nieuw()
    antwoord = req(server, "POST", "/api/pair", body={"code": code, "rol": rol, "naam": "iPad"}, ip=ip)
    assert antwoord.status == 201, antwoord.json()
    return antwoord


def cookie_uit(antwoord):
    return antwoord.header("Set-Cookie").split(";")[0]


# ----- authenticatie en autorisatie -----

def test_zonder_token_en_zonder_cookie_401(srv):
    a = req(srv, "GET", "/api/status")
    assert a.status == 401
    assert "fase" not in a.body.decode()


def test_kijk_token_mag_lezen(srv):
    a = req(srv, "GET", "/api/status", token=VIEW)
    assert a.status == 200
    assert a.json()["fase"] == "rust"


def test_kijk_token_op_schrijf_endpoint_403(srv):
    a = req(srv, "POST", "/api/timers", token=VIEW, body={"naam": "x", "seconden": 60})
    assert a.status == 403
    assert req(srv, "GET", "/api/timers", token=VIEW).json() == []


def test_bedien_token_op_schrijf_endpoint_werkt_en_audit(srv, audit_regels):
    a = req(srv, "POST", "/api/timers", token=CONTROL, body={"naam": "thee", "seconden": 60})
    assert a.status == 201
    assert audit_regels[-1]["handler"] == "dashboard"
    assert audit_regels[-1]["tool"] == "timer_zet"


def test_kijk_token_kan_niet_goedkeuren(srv):
    p = set_pending("power_confirm", {"action": "shutdown"})
    a = req(srv, "POST", "/api/goedkeuring", token=VIEW,
            body={"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert a.status == 403


def test_bedien_token_kan_goedkeuren(srv):
    p = set_pending("power_confirm", {"action": "shutdown"})
    a = req(srv, "POST", "/api/goedkeuring", token=CONTROL,
            body={"id": p[ID_KEY], "nonce": p[NONCE_KEY], "besluit": "ja"})
    assert a.status == 200
    assert a.json()["uitgevoerd"] is True


def test_gekoppeld_kijk_apparaat_mag_niet_schrijven(srv):
    c = cookie_uit(koppel(srv, rol="kijk"))
    assert req(srv, "GET", "/api/timers", cookie=c).status == 200
    assert req(srv, "POST", "/api/timers", cookie=c, body={"naam": "x", "seconden": 5}).status == 403


def test_gekoppeld_bedien_apparaat_mag_schrijven(srv):
    c = cookie_uit(koppel(srv, rol="bedien"))
    assert req(srv, "POST", "/api/timers", cookie=c, body={"naam": "x", "seconden": 5}).status == 201


def test_apparaattoken_werkt_ook_als_bearer(srv):
    token = koppel(srv, rol="kijk").json()["token"]
    assert req(srv, "GET", "/api/status", token=token).status == 200


def test_token_in_de_url_wordt_genegeerd(srv):
    assert req(srv, "GET", f"/api/status?token={CONTROL}").status == 401
    assert req(srv, "GET", f"/api/status?access_token={CONTROL}").status == 401


def test_foute_authorization_valt_niet_terug_op_cookie(srv):
    c = cookie_uit(koppel(srv))
    assert req(srv, "GET", "/api/status", token="fout", cookie=c).status == 401


@pytest.mark.parametrize("waarde", ["Basic abc", "Bearer", "Bearer ", CONTROL])
def test_ongeldige_authorization_header(srv, waarde):
    a = srv.process("GET", "/api/status", {"Host": HOST, "Authorization": waarde}, b"", client_ip=IPAD)
    assert a.status == 401


def test_settings_bevat_geen_token(srv):
    koppel(srv, rol="kijk")
    a = req(srv, "GET", "/api/settings", token=VIEW)
    assert a.status == 200
    tekst = a.body.decode()
    assert VIEW not in tekst and CONTROL not in tekst
    data = a.json()
    assert data["token_ingesteld"] is True
    assert data["rollen"] == ["bedien", "kijk"]


def test_settings_opslaan(srv):
    a = req(srv, "PUT", "/api/settings", token=CONTROL,
            body={"instellingen": {"thema": "donker", "taal": "en", "meldingen": False}})
    assert a.status == 200
    assert req(srv, "GET", "/api/settings", token=VIEW).json()["instellingen"]["taal"] == "en"
    assert req(srv, "PUT", "/api/settings", token=CONTROL, body={"kolommen": {}}).status == 400


def test_sessie_zonder_gegevens(srv):
    a = req(srv, "GET", "/api/sessie")
    assert a.status == 200
    assert a.json() == {"gekoppeld": False, "rol": None, "token_ingesteld": True}


def test_sessie_na_koppelen_toont_geen_token(srv):
    k = koppel(srv, rol="kijk")
    a = req(srv, "GET", "/api/sessie", cookie=cookie_uit(k))
    assert a.json() == {"gekoppeld": True, "rol": "kijk", "token_ingesteld": True}
    assert k.json()["token"] not in a.body.decode()


def test_sessie_met_oude_cookie_wist_de_cookie(srv):
    a = req(srv, "GET", "/api/sessie", cookie=f"{auth.COOKIE_NAAM}=oud")
    assert a.json()["gekoppeld"] is False
    assert "Max-Age=0" in a.header("Set-Cookie")


def test_onbekend_endpoint_404_en_verkeerde_methode_405(srv):
    assert req(srv, "GET", "/api/bestaat-niet", token=VIEW).status == 404
    a = req(srv, "DELETE", "/api/status", token=CONTROL)
    assert a.status == 405
    assert a.header("Allow") == "GET"


def test_health_zonder_token(srv):
    a = req(srv, "GET", "/api/health")
    assert a.status == 200 and a.json()["ok"] is True


# ----- verkeerd token, rate-limit en lockout -----

def test_vijf_keer_fout_token_blokkeert_ip(srv):
    for _ in range(5):
        assert req(srv, "GET", "/api/status", token="fout", now=EPOCH).status == 401
    # Nu geblokkeerd: zelfs het juiste token krijgt 403 zonder uitleg.
    assert req(srv, "GET", "/api/status", token=VIEW, now=EPOCH + 1).status == 403
    # Een ander IP heeft er geen last van.
    assert req(srv, "GET", "/api/status", token=VIEW, ip="192.168.1.21").status == 200


def test_na_de_lockout_mag_het_ip_weer(srv):
    for _ in range(5):
        req(srv, "GET", "/api/status", token="fout", now=EPOCH)
    assert req(srv, "GET", "/api/status", token=VIEW, now=EPOCH + 301).status == 200


def test_geslaagde_authenticatie_reset_de_teller(srv):
    for _ in range(4):
        req(srv, "GET", "/api/status", token="fout", now=EPOCH)
    assert req(srv, "GET", "/api/status", token=VIEW, now=EPOCH).status == 200
    for _ in range(4):
        assert req(srv, "GET", "/api/status", token="fout", now=EPOCH).status == 401
    assert req(srv, "GET", "/api/status", token=VIEW, now=EPOCH).status == 200


def test_zonder_gegevens_telt_niet_voor_lockout(srv):
    for _ in range(10):
        assert req(srv, "GET", "/api/status").status == 401
    assert req(srv, "GET", "/api/status", token=VIEW).status == 200


def test_rate_limit_429(maak):
    srv = maak(rate_limiter=RateLimiter(3, 60))
    for _ in range(3):
        assert req(srv, "GET", "/api/health", now=EPOCH).status == 200
    assert req(srv, "GET", "/api/health", now=EPOCH).status == 429


def test_niet_toegestaan_of_publiek_ip_403(maak):
    srv = maak(allowed_ips=("192.168.1.20",))
    assert req(srv, "GET", "/api/health", ip="192.168.1.20").status == 200
    assert req(srv, "GET", "/api/health", ip="192.168.1.99").status == 403
    assert req(maak(), "GET", "/api/health", ip="8.8.8.8").status == 403


# ----- koppelcode -----

def test_koppelen_geeft_token_eenmalig_en_veilige_cookie(srv, tmp_path):
    a = koppel(srv)
    data = a.json()
    assert data["rol"] == "bedien" and len(data["token"]) >= 32
    cookie = a.header("Set-Cookie")
    for deel in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
        assert deel in cookie
    # Op schijf staat alleen de hash.
    op_schijf = (tmp_path / "devices.json").read_text(encoding="utf-8")
    assert data["token"] not in op_schijf
    assert auth.token_hash(data["token"]) in op_schijf


def test_koppelcode_is_eenmalig(srv):
    code = srv.koppelcode.nieuw()
    assert req(srv, "POST", "/api/pair", body={"code": code, "rol": "kijk"}).status == 201
    assert req(srv, "POST", "/api/pair", body={"code": code, "rol": "kijk"}, ip="192.168.1.21").status == 401


def test_verlopen_koppelcode(srv, klok):
    code = srv.koppelcode.nieuw()
    klok.nu += 301
    a = req(srv, "POST", "/api/pair", body={"code": code, "rol": "kijk"})
    assert a.status == 401
    assert "token" not in a.json()


def test_verkeerde_koppelcode_401_zonder_token(srv):
    srv.koppelcode.nieuw()
    a = req(srv, "POST", "/api/pair", body={"code": "00000000", "rol": "bedien"})
    assert a.status == 401
    assert "token" not in a.json()
    assert a.header("Set-Cookie") is None


def test_koppelcode_vervalt_na_drie_fouten(srv):
    code = srv.koppelcode.nieuw()
    for i in range(3):
        req(srv, "POST", "/api/pair", body={"code": "1234567" + str(i), "rol": "kijk"}, ip=f"192.168.1.{30 + i}")
    assert req(srv, "POST", "/api/pair", body={"code": code, "rol": "kijk"}, ip="192.168.1.40").status == 401


def test_koppelen_heeft_strengere_limiet(srv):
    srv.koppelcode.nieuw()
    for _ in range(5):
        req(srv, "POST", "/api/pair", body={"code": "0", "rol": "kijk"}, now=EPOCH)
    # Na vijf pogingen: geblokkeerd (lockout) of afgeremd (429).
    assert req(srv, "POST", "/api/pair", body={"code": "0", "rol": "kijk"}, now=EPOCH).status in (403, 429)


@pytest.mark.parametrize("body", [None, [], {"code": "12345678"}, {"code": "12345678", "rol": "admin"}])
def test_koppelen_met_ongeldige_invoer_400(srv, body):
    srv.koppelcode.nieuw()
    assert req(srv, "POST", "/api/pair", body=body if body is not None else b"").status in (400, 401)


def test_koppelen_mag_zonder_origin(srv):
    code = srv.koppelcode.nieuw()
    assert req(srv, "POST", "/api/pair", origin=None, body={"code": code, "rol": "kijk"}).status == 201


def test_nieuwe_koppelcode_alleen_vanaf_deze_pc(srv):
    assert req(srv, "POST", "/api/koppelcode", ip=IPAD).status == 404
    a = req(srv, "POST", "/api/koppelcode", ip="127.0.0.1", host="localhost:8780",
            origin="https://localhost:8780")
    assert a.status == 200
    code = a.json()["code"]
    assert len(code) == 8 and code.isdigit()
    assert req(srv, "POST", "/api/pair", body={"code": code, "rol": "kijk"}).status == 201


# ----- Host en Origin -----

@pytest.mark.parametrize("host", ["evil.example", "192.168.1.5:9999", "", "192.168.1.5"])
def test_verkeerde_host_403(srv, host):
    assert req(srv, "GET", "/api/health", host=host).status == 403


def test_localhost_host_is_toegestaan(srv):
    assert req(srv, "GET", "/api/health", host="localhost:8780", ip="127.0.0.1").status == 200


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://192.168.1.5:8780", "null"])
def test_schrijfactie_zonder_of_met_vreemde_origin_403(srv, origin):
    a = req(srv, "POST", "/api/timers", token=CONTROL, origin=origin, body={"naam": "x", "seconden": 5})
    assert a.status == 403
    assert req(srv, "GET", "/api/timers", token=VIEW).json() == []


def test_schrijfactie_met_eigen_origin(srv):
    assert req(srv, "POST", "/api/timers", token=CONTROL, body={"naam": "x", "seconden": 5}).status == 201


def test_schrijfactie_zonder_json_content_type_415(srv):
    a = req(srv, "POST", "/api/timers", token=CONTROL, body={"naam": "x", "seconden": 5},
            content_type="text/plain")
    assert a.status == 415


def test_ongeldige_json_400(srv):
    assert req(srv, "POST", "/api/timers", token=CONTROL, body=b"{kapot").status == 400


def test_te_grote_body_413(srv):
    assert req(srv, "POST", "/api/timers", token=CONTROL, body=b"x" * (17 * 1024)).status == 413


def test_geen_cors_headers(srv):
    for a in (
        req(srv, "GET", "/api/status", token=VIEW, headers={"Origin": "https://evil.example"}),
        req(srv, "GET", "/"),
        req(srv, "OPTIONS", "/api/status", token=VIEW),
    ):
        assert not any(k.lower().startswith("access-control-") for k, _ in a.headers)


def test_options_405(srv):
    assert req(srv, "OPTIONS", "/api/status").status == 405


def test_api_responses_niet_cachen(srv):
    a = req(srv, "GET", "/api/status", token=VIEW)
    assert a.header("Cache-Control") == "no-store"


# ----- tokenrotatie -----

def test_rotatie_met_huidig_token(srv):
    oud = koppel(srv).json()["token"]
    a = req(srv, "POST", "/api/tokens/rotatie", token=oud, body={"huidig": oud})
    assert a.status == 200
    nieuw = a.json()["token"]
    assert nieuw != oud
    assert nieuw in a.header("Set-Cookie")
    assert req(srv, "GET", "/api/status", token=oud).status == 401
    assert req(srv, "GET", "/api/status", cookie=f"{auth.COOKIE_NAAM}={oud}").status == 401
    assert req(srv, "GET", "/api/status", token=nieuw).status == 200


def test_rotatie_zonder_kloppend_huidig_token(srv):
    token = koppel(srv).json()["token"]
    a = req(srv, "POST", "/api/tokens/rotatie", token=token, body={"huidig": "iets anders"})
    assert a.status == 401
    assert req(srv, "GET", "/api/status", token=token).status == 200


def test_rotatie_van_ander_apparaat_kan_niet(srv):
    a = koppel(srv).json()["token"]
    b = koppel(srv, ip="192.168.1.21").json()["token"]
    assert req(srv, "POST", "/api/tokens/rotatie", token=a, body={"huidig": b}).status == 401
    assert req(srv, "GET", "/api/status", token=b, ip="192.168.1.21").status == 200


def test_rotatie_van_vast_token_409(srv):
    a = req(srv, "POST", "/api/tokens/rotatie", token=CONTROL, body={"huidig": CONTROL})
    assert a.status == 409


def test_ingetrokken_apparaat_werkt_niet_meer(srv):
    k = koppel(srv)
    srv.auth.register.trek_in(k.json()["apparaat_id"])
    assert req(srv, "GET", "/api/status", cookie=cookie_uit(k)).status == 401


# ----- goedkeuring via de server -----

def test_goedkeuring_met_verkeerde_nonce_403(srv):
    p = set_pending("power_confirm", {"action": "shutdown"})
    a = req(srv, "POST", "/api/goedkeuring", token=CONTROL,
            body={"id": p[ID_KEY], "nonce": "oud", "besluit": "ja"})
    assert a.status == 403


def test_pending_endpoint_toont_volledige_actie(srv):
    set_pending("power_confirm", {"action": "shutdown", "question": "sluit af"})
    data = req(srv, "GET", "/api/pending", token=VIEW).json()
    assert data["soort"] == "power_confirm"
    assert data["vraag"] == "sluit af"
    assert data["risico"] == "high"


def test_timer_annuleren_via_pad(srv):
    t = req(srv, "POST", "/api/timers", token=CONTROL, body={"naam": "x", "seconden": 60}).json()
    assert req(srv, "DELETE", f"/api/timers/{t['id']}", token=VIEW).status == 403
    assert req(srv, "DELETE", f"/api/timers/{t['id']}", token=CONTROL).status == 200
    assert req(srv, "DELETE", "/api/timers/../../etc", token=CONTROL).status == 404


# ----- statische bestanden en headers -----

def test_index_en_security_headers(srv):
    a = req(srv, "GET", "/")
    assert a.status == 200
    assert a.header("Content-Type").startswith("text/html")
    assert b"JARVIS" in a.body


def test_csp_is_strikt():
    assert "default-src 'self'" in CSP
    assert "unsafe-inline" not in CSP and "unsafe-eval" not in CSP
    assert "frame-ancestors 'none'" in CSP and "object-src 'none'" in CSP


@pytest.mark.parametrize("pad", [
    "/../geheim.txt", "/..%2Fgeheim.txt", "/static/../geheim.txt", "/.env",
    "/app.py", "/sub/../../geheim.txt", "/C:/Windows/win.ini", "//etc/passwd",
])
def test_geen_pad_uitbraak(srv, pad):
    a = req(srv, "GET", pad)
    assert a.status == 404
    assert b"geheim" not in a.body


def test_statisch_alleen_get(srv):
    assert req(srv, "POST", "/app.js", body={}).status == 405


def test_javascript_mime(srv):
    a = req(srv, "GET", "/app.js")
    assert a.status == 200
    assert a.header("Content-Type").startswith("text/javascript")


def test_profiel_alleen_als_het_bestaat(maak, tmp_path):
    assert req(maak(), "GET", "/profiel.mobileconfig").status == 404
    profiel = tmp_path / "p.mobileconfig"
    profiel.write_bytes(b"<plist/>")
    a = req(maak(profiel_file=str(profiel)), "GET", "/profiel.mobileconfig")
    assert a.status == 200
    assert a.header("Content-Type") == "application/x-apple-aspen-config"


# ----- SSE -----

def test_events_vraagt_authenticatie(srv):
    assert req(srv, "GET", "/api/events").status == 401
    a = req(srv, "GET", "/api/events", token=VIEW)
    assert a.status == 200
    assert a.abonnement is not None
    assert a.header("Content-Type").startswith("text/event-stream")
    srv.bus.zeg_op(a.abonnement)


def test_events_maximaal_aantal_streams(srv):
    open_ = [req(srv, "GET", "/api/events", token=VIEW) for _ in range(4)]
    assert all(a.status == 200 for a in open_)
    assert req(srv, "GET", "/api/events", token=VIEW).status == 503


# ----- audit en geheimen -----

def test_mislukte_authenticatie_komt_in_audit_zonder_token(srv, audit_regels):
    req(srv, "GET", "/api/status", token="dit-is-een-fout-token")
    regel = audit_regels[-1]
    assert regel["tool"] == "dashboard_auth"
    assert regel["goedgekeurd"] is False
    assert regel["herkomst"] == "dashboard"
    assert "dit-is-een-fout-token" not in json.dumps(audit_regels)


def test_geen_token_of_koppelcode_in_audit(srv, audit_regels):
    k = koppel(srv)
    token = k.json()["token"]
    req(srv, "POST", "/api/tokens/rotatie", token=token, body={"huidig": token})
    code = srv.koppelcode.nieuw()
    req(srv, "POST", "/api/pair", body={"code": code, "rol": "kijk"})
    tekst = json.dumps(audit_regels)
    for geheim in (token, code, VIEW, CONTROL):
        assert geheim not in tekst


def test_lockout_object_wordt_gedeeld_met_de_tls_server(maak):
    lockout = AuthLockout()
    srv = maak(lockout=lockout)
    assert srv._lockout is lockout
