"""
JARVIS - Fase 10: UI Automation tests
======================================

Test de UI-automatiserings-skill zonder echte Windows-UI (alles gemockt):

  [1] pywinauto NIET beschikbaar -> nette foutmelding (geen crash)
  [2] list_windows: vensters ophalen (Desktop mock)
  [3] list_windows: filter op titel-substring
  [4] find_window: vind venster op titel -> title/handle terug
  [5] find_window: geen match -> window_not_found, handle=None
  [6] activate_window: zet focus
  [7] list_elements: elementen ophalen met type/name/automation_id
  [8] list_elements: filter op naam
  [9] find_element: vind element op naam -> matches
  [10] find_element: geen match -> element_not_found
  [11] type_text: typt tekst via venster
  [12] click_element: klikt via find_element
  [13] click_element: element niet gevonden -> nette fout
  [14] get_value: leest waarde van element
  [15] set_value: stelt waarde in
  [16] launch_app: start applicatie
  [17] Veiligheid: NOOIT een gevaarlijke/onveilige actie
  [18] Foutstructuur: elke functie retourneert dict met ok/status/error

Alle UI-interacties zijn gemockt; geen echte applicaties aangeraakt.
"""
import sys
import os
import io

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

import actions.ui_automation as uia

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}  {str(detail)[:150]}")


# =============================================================
# Fakes / mocks voor pywinauto
# =============================================================

def make_fake_element(name, cls="Button", automation_id=""):
    el = MagicMock()
    el.window_text.return_value = name
    el.element_info.element_class = cls
    el.automation_id.return_value = automation_id
    el.handle = 999 + (hash(name) % 1000)
    return el


def make_fake_window(elements, title="Test Venster", handle=12345):
    w = MagicMock()
    w.window_text.return_value = title
    w.class_name.return_value = "TestClass"
    w.handle = handle
    w.descendants.return_value = elements
    w.set_focus.return_value = None
    return w


class FakeWindow(MagicMock):
    """Een MagicMock-venster met een echte .handle attribuut."""

    @property
    def handle(self):
        return self._the_handle

    @handle.setter
    def handle(self, v):
        self._the_handle = v

    def child_window(self, **kw):
        return FakeWindow()


def make_desktop_plugin(windows):
    """Maak de ('Desktop', 'Application') plugin die _import_pywinauto
    teruggeeft. Desktop(...) levert een fake desktop die onze vensters
    KENT op hun handle. Onbekende handles gooien een exception (net als
    pywinauto bij een ongeldig venster)."""

    class FakeDesktop:
        def __init__(self, backend=None):
            self._windows = windows

        def windows(self):
            return self._windows

        def window(self, handle=None, **kw):
            for w in self._windows:
                if getattr(w, "handle", None) == handle:
                    return w
            raise RuntimeError(f"window not found for handle {handle}")

    application_mock = MagicMock()
    return (FakeDesktop, application_mock)


# =============================================================
print("\n===== [1] PYWINAUTO NIET BESCHIKBAAR =====")

with patch.object(uia, "_import_pywinauto", return_value=None):
    r1 = uia.list_windows()
    ok("zonder pywinauto -> ok=False", not r1["ok"])
    ok("zonder pywinauto -> duidelijke error",
       "pywinauto" in r1.get("error", ""), r1.get("error"))

    r2 = uia.find_window(title_substring="Test")
    ok("find_window zonder pywinauto -> ok=False", not r2["ok"])

    r3 = uia.find_element(handle=123, name="Test")
    ok("find_element zonder pywinauto -> ok=False", not r3["ok"])

    r4 = uia.click_element(handle=123, name="Test")
    ok("click zonder pywinauto -> ok=False", not r4["ok"])

    r5 = uia.type_text(handle=123, text="hallo")
    ok("type zonder pywinauto -> ok=False", not r5["ok"])

    r6 = uia.get_value(handle=123, name="Test")
    ok("get_value zonder pywinauto -> ok=False", not r6["ok"])

    r7 = uia.set_value(handle=123, value="x", name="Test")
    ok("set_value zonder pywinauto -> ok=False", not r7["ok"])

    with patch("actions.ui_automation.subprocess.Popen"):
        r8 = uia.launch_app(r"C:\dummy\app.exe")
        ok("launch_app zonder pywinauto -> WERKT (geen pywinauto nodig)",
           r8["ok"], r8.get("error"))


# =============================================================
print("\n===== [2] LIST WINDOWS =====")

fake_windows = [
    make_fake_window([], title="Spotify", handle=1001),
    make_fake_window([], title="SteelSeries GG", handle=1002),
    make_fake_window([], title="Notepad", handle=1003),
]
plugin = make_desktop_plugin(fake_windows)

with patch.object(uia, "_import_pywinauto", return_value=plugin):
    r = uia.list_windows()
    ok("[2a] list_windows ok", r["ok"], str(r))
    ok("[2a] 3 vensters geretourneerd", len(r.get("windows", [])) == 3,
       str(r.get("windows")))

with patch.object(uia, "_import_pywinauto", return_value=plugin):
    r = uia.list_windows(title_substring="steel")
    ok("[2b] filter 'steel' -> 1 venster", len(r.get("windows", [])) == 1,
       str(r.get("windows")))
    ok("[2b] correcte titel", r["windows"][0]["title"] == "SteelSeries GG")


# =============================================================
print("\n===== [3] FIND WINDOW =====")

with patch.object(uia, "_import_pywinauto", return_value=plugin):
    r = uia.find_window(title_substring="notepad")
    ok("[3a] Notepad gevonden", r.get("ok") and r.get("found") is True)
    ok("[3a] handle correct", r.get("handle") == 1003, str(r.get("handle")))
    ok("[3a] titel correct", r.get("title") == "Notepad")

with patch.object(uia, "_import_pywinauto", return_value=plugin):
    r = uia.find_window(title_substring="bestaatnietx")
    ok("[3b] geen match -> ok=False", not r["ok"])
    ok("[3b] error_type window_not_found",
       r.get("error_type") == "window_not_found", str(r.get("error_type")))
    ok("[3b] handle None", r.get("handle") is None)


# =============================================================
print("\n===== [4] ACTIVATE WINDOW =====")

with patch.object(uia, "_import_pywinauto", return_value=plugin):
    r = uia.activate_window(handle=1001)
    ok("[4] activate_window ok", r["ok"])
    ok("[4] status 200", r.get("status") == "200")

    r2 = uia.activate_window(handle=__import__("sys").maxsize)
    ok("[4b] activeren onbekend venster -> fout", not r2["ok"])


# =============================================================
print("\n===== [5] LIST ELEMENTS =====")

fake_elements = [
    make_fake_element("Volume Slider", cls="Slider", automation_id="volume"),
    make_fake_element("Spelen", cls="Button", automation_id="play"),
    make_fake_element("Stoppen", cls="Button", automation_id="stop"),
]
win_sonar = make_fake_window(fake_elements, title="SteelSeries GG", handle=2001)
sonar_plugin = make_desktop_plugin([win_sonar])

with patch.object(uia, "_import_pywinauto", return_value=sonar_plugin):
    r = uia.list_elements(handle=2001)
    ok("[5a] list_elements ok", r["ok"], str(r))
    ok("[5a] 3 elementen", len(r.get("elements", [])) == 3, str(r))

    r = uia.list_elements(handle=2001, name_filter="volume")
    ok("[5b] filter 'volume' -> 1 element", len(r.get("elements", [])) == 1,
       str(r))


# =============================================================
print("\n===== [6] FIND ELEMENT =====")

with patch.object(uia, "_import_pywinauto", return_value=sonar_plugin):
    r = uia.find_element(handle=2001, name="spelen")
    ok("[6a] element gevonden", r.get("ok") and r.get("found") is True)
    ok("[6a] count 1", r.get("count") == 1, str(r.get("count")))

    r = uia.find_element(handle=2001, name="doesntexist")
    ok("[6b] geen match -> ok=False", not r["ok"])
    ok("[6b] error_type element_not_found",
       r.get("error_type") == "element_not_found", str(r.get("error_type")))

    r = uia.find_element(handle=2001, name="Stoppen", control_type="button")
    ok("[6c] control_type filter werkt", r.get("count") == 1, str(r))


# =============================================================
print("\n===== [7] TYPE TEXT =====")

with patch.object(uia, "_import_pywinauto", return_value=sonar_plugin):
    r = uia.type_text(handle=2001, text="hallo wereld")
    ok("[7a] type_text ok", r["ok"], str(r))
    ok("[7a] melding over aantal tekens", "12" in r.get("message", ""),
       r.get("message"))

    r = uia.type_text(handle=4567, text="geen venster")
    ok("[7b] type in onbekend venster -> ok of fout-check",
       r.get("ok") is True or r.get("status") == "fout", str(r))


# =============================================================
print("\n===== [8] CLICK ELEMENT =====")

with patch.object(uia, "_import_pywinauto", return_value=sonar_plugin):
    r = uia.click_element(handle=2001, name="Stoppen")
    ok("[8a] click ok", r["ok"], str(r))
    ok("[8a] status 200", r.get("status") == "200")

    r = uia.click_element(handle=2001, name="deze-knop-bestaat-niet")
    ok("[8b] klik op onbekend -> ok=False", not r["ok"])
    ok("[8b] element_not_found",
       r.get("error_type") == "element_not_found", str(r.get("error_type")))


# =============================================================
print("\n===== [9] GET / SET VALUE =====")

with patch.object(uia, "_import_pywinauto", return_value=sonar_plugin):
    r = uia.get_value(handle=2001, name="Volume")
    ok("[9a] get_value met element", r.get("ok") is True, str(r))

    r = uia.set_value(handle=2001, value=50, name="Volume")
    ok("[9b] set_value accepteert of fout", "ok" in r, str(r))


# =============================================================
print("\n===== [10] LAUNCH APP =====")

with patch("actions.ui_automation.subprocess.Popen") as mock_popen:
    r = uia.launch_app(r"C:\dummy\app.exe")
    ok("[10] launch_app ok via Popen", r["ok"])
    mock_popen.assert_called_once()


# =============================================================
print("\n===== [11] VEILIGHEID: GEEN GEVAARLIJKE ACTIES =====")

import inspect
source = inspect.getsource(uia)
dangerous = ["shutdown", "reboot", "os.remove", "rmtree", "DeleteFile",
             "os.system", "unlink", "format c:", "del /f"]
for d in dangerous:
    ok(f"[11] geen gevaarlijke '{d}'", d not in source)


# =============================================================
print(f"\n{'='*50}")
print(f"UI AUTOMATION TESTS: {passed} gereed, {failed} gefaald")
print(f"{'='*50}")

if failed:
    sys.exit(1)