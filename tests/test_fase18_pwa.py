"""Tests voor Fase 18 M3: de PWA-bestanden in dashboard/static/.

Controleert de regels uit docs/fase18_dashboard_design.md §10.8 en §13.1
statisch, zonder browser:
  - geen inline <script>, <style> of style="..." (strikte CSP);
  - geen innerHTML / insertAdjacentHTML / outerHTML / document.write / eval;
  - geen enkele verwijzing naar een externe host (geen Google Fonts, geen CDN);
  - alle lokale verwijzingen bestaan en worden door de server geserveerd;
  - lettertypen zijn echte woff2-bestanden; manifest en service worker kloppen;
  - de service worker cachet nooit /api/.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from dashboard.server import MIME_TYPES, STATIC_DIR

STATIC = Path(STATIC_DIR)
HTML_BESTANDEN = sorted(STATIC.glob("*.html"))
JS_BESTANDEN = sorted(STATIC.glob("*.js"))
CSS_BESTANDEN = sorted(STATIC.glob("*.css"))


class _Verzamelaar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []        # (attrs, heeft_inhoud)
        self.styles = 0
        self.style_attrs = []
        self.event_attrs = []
        self.verwijzingen = []
        self._in_script = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "style" in a:
            self.style_attrs.append(tag)
        self.event_attrs.extend(k for k in a if k.lower().startswith("on"))
        if tag == "script":
            self._in_script = a
            self.scripts.append([a, False])
        if tag == "style":
            self.styles += 1
        for sleutel in ("src", "href"):
            if a.get(sleutel):
                self.verwijzingen.append(a[sleutel])

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = None

    def handle_data(self, data):
        if self._in_script is not None and data.strip():
            self.scripts[-1][1] = True


def _parse(pad):
    v = _Verzamelaar()
    v.feed(pad.read_text(encoding="utf-8"))
    return v


def test_er_zijn_productiebestanden():
    namen = {p.name for p in STATIC.iterdir()}
    for nodig in ("index.html", "styles.css", "app.js", "sw.js", "manifest.webmanifest", "koppel.html", "koppel.js"):
        assert nodig in namen


@pytest.mark.parametrize("pad", HTML_BESTANDEN, ids=lambda p: p.name)
def test_html_zonder_inline_code_of_styles(pad):
    v = _parse(pad)
    assert v.styles == 0, "geen <style>-blok"
    assert v.style_attrs == [], f"style-attributen op: {v.style_attrs}"
    assert v.event_attrs == [], f"inline event-handlers: {v.event_attrs}"
    for attrs, inhoud in v.scripts:
        assert attrs.get("src"), "elk <script> moet een src hebben"
        assert not inhoud, "geen inline script-inhoud"


@pytest.mark.parametrize("pad", HTML_BESTANDEN, ids=lambda p: p.name)
def test_html_verwijst_alleen_naar_bestaande_lokale_bestanden(pad):
    for ref in _parse(pad).verwijzingen:
        assert not re.match(r"^[a-z][a-z0-9+.-]*:|^//", ref, re.I), f"externe verwijzing: {ref}"
        if ref.startswith("/profiel.mobileconfig"):
            continue
        doel = STATIC / ref.lstrip("/")
        assert doel.is_file(), f"{pad.name}: {ref} bestaat niet"
        assert doel.suffix in MIME_TYPES, f"{ref} wordt niet geserveerd (MIME)"


VERBODEN_JS = re.compile(
    r"\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function\s*\("
    r"|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"]"
)


@pytest.mark.parametrize("pad", JS_BESTANDEN, ids=lambda p: p.name)
def test_js_zonder_html_injectie_of_eval(pad):
    code = pad.read_text(encoding="utf-8")
    # Commentaar weghalen: daar mogen de verboden woorden in de uitleg staan.
    zonder_commentaar = re.sub(r"/\*.*?\*/|(?<![:'\"])//[^\n]*", "", code, flags=re.S)
    treffers = VERBODEN_JS.findall(zonder_commentaar)
    assert treffers == [], f"{pad.name}: {treffers}"


@pytest.mark.parametrize("pad", JS_BESTANDEN + CSS_BESTANDEN + [STATIC / "manifest.webmanifest"], ids=lambda p: p.name)
def test_geen_externe_hosts(pad):
    # De SVG-namespace is een vaste naam, geen verzoek naar een host.
    tekst = pad.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
    assert not re.search(r"https?://", tekst), f"{pad.name} verwijst naar een externe host"
    assert "@import" not in tekst


def test_css_lettertypen_bestaan_en_zijn_woff2():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\(\"?([^\")]+)\"?\)", css)
    assert len(urls) == 5
    for url in urls:
        bestand = STATIC / url
        assert bestand.is_file(), url
        assert bestand.read_bytes()[:4] == b"wOF2", f"{url} is geen woff2"
    assert {"Orbitron", "Rajdhani"} <= set(re.findall(r"font-family:\s*(\w+);\s*font-weight", css))


def test_lettertype_licenties_aanwezig():
    for naam in ("OFL-Orbitron.txt", "OFL-Rajdhani.txt"):
        assert "Open Font License" in (STATIC / "fonts" / naam).read_text(encoding="utf-8")


def test_manifest_klopt():
    m = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["start_url"] == "/" and m["display"] == "standalone"
    assert m["background_color"] == "#04090e"
    maten = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= maten
    for icoon in m["icons"]:
        bestand = STATIC / icoon["src"]
        assert bestand.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_service_worker_shell_bestaat_en_cachet_geen_api():
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S).group(1)
    for pad in re.findall(r"'([^']+)'", shell):
        if pad == "/":
            continue
        assert (STATIC / pad.lstrip("/")).is_file(), pad
        assert not pad.startswith("/api/")
    assert "indexOf('/api/') === 0" in sw


def test_app_gebruikt_alleen_eigen_origin_en_cookie():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "credentials: 'same-origin'" in app
    assert "localStorage" not in app and "sessionStorage" not in app
    assert "Authorization" not in app, "de PWA gebruikt de HttpOnly-cookie, geen token in JS"


def test_index_wordt_geserveerd_met_csp(tmp_path):
    from core.timers import TimerStore
    from dashboard import auth
    from dashboard.api import DashboardAPI
    from dashboard.server import CSP, DashboardServer, standaard_hosts, standaard_origins

    hosts = standaard_hosts(8780, "192.168.1.5")
    srv = DashboardServer(
        api=DashboardAPI(timer_store=TimerStore(pad=str(tmp_path / "t.json")), audit_fn=lambda **v: None),
        authenticator=auth.Authenticator("a" * 20, "b" * 20, auth.ApparaatRegister(str(tmp_path / "d.json"))),
        koppelcode=auth.Koppelcode(300),
        allowed_hosts=hosts,
        allowed_origins=standaard_origins(hosts),
        audit_fn=lambda **v: None,
    )
    for pad in ("/", "/app.js", "/styles.css", "/sw.js", "/manifest.webmanifest", "/koppel.html",
                "/fonts/orbitron-latin-500-normal.woff2", "/icons/icon-192.png"):
        a = srv.process("GET", pad, {"Host": "192.168.1.5:8780"}, b"", client_ip="192.168.1.20")
        assert a.status == 200, pad
    # De licentieteksten zijn geen webbestand en worden niet geserveerd.
    a = srv.process("GET", "/fonts/OFL-Orbitron.txt", {"Host": "192.168.1.5:8780"}, b"", client_ip="192.168.1.20")
    assert a.status == 404
    assert "unsafe-inline" not in CSP


def test_elk_paneel_heeft_een_bekende_widget_id():
    from dashboard.api import BEKENDE_WIDGETS, STANDAARD_WIDGETS

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    ids = re.findall(r'data-widget="([a-z_]+)"', html)
    assert len(ids) == len(set(ids)) == 9
    assert set(ids) <= BEKENDE_WIDGETS
    # De standaardindeling noemt precies de panelen die bestaan.
    standaard = [w for kolom in STANDAARD_WIDGETS["kolommen"].values() for w in kolom]
    assert sorted(standaard) == sorted(ids)
    # En app.js kent dezelfde panelen (de lijst voor het instellingenscherm).
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    for widget_id in ids:
        assert f"['{widget_id}'," in app
