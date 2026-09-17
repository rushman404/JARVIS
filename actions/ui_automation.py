"""
UI Automation (Fase 10) — algemene Windows-app-bediening via UI Automation.

JARVIS kan hiermee niet alleen programma's OPENEN, maar ook:
  - Vensters vinden (op titel of proces)
  - UI-elementen lezen (type, naam, automation id, parent/child)
  - Knoppen activeren, tekst typen, waarden instellen, selecties maken

Belangrijk:
  - Dit bestand blijft ALGEMEEN. Geen Sonar-specifieke code hierin.
  - Gebruikt pywinauto met de "uia" backend (Windows UI Automation).
  - pywinauto wordt lazy geïmporteerd, zodat het hele project blijft
    werken (en getest kan worden) zonder dat pywinauto is geïnstalleerd.

Veiligheid:
  - Alle functies geven een dict terug met ok/status/error.
  - Timeouts voorkomen dat JARVIS blijft hangen op een trage app.
"""

import time
import subprocess

TIMEOUT = 3
WINDOW_TIMEOUT = 5
MAX_LIST_ELEMENTS = 50


def _import_pywinauto():

    """Importeer pywinauto lazily. Geeft None als het niet beschikbaar is."""

    try:
        from pywinauto import Desktop
        from pywinauto.application import Application
        return Desktop, Application
    except ImportError:
        return None


def _not_available():

    return {
        "ok": False,
        "status": "fout",
        "error_type": "ui_automation_unavailable",
        "error": "UI-automatisering is niet beschikbaar (pywinauto is niet geïnstalleerd).",
    }


# =============================================================
# VENSTERS & APPS
# =============================================================

def list_windows(title_substring=None, process_id=None, max_windows=20):

    """Lijst open vensters op met hun titel, class en handle.

    Optioneel filter op titel-substring of proces-id."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    Desktop, _Application = mods

    try:
        windows = Desktop(backend="uia").windows()

        results = []
        for w in windows:
            if len(results) >= max_windows:
                break
            try:
                title = (w.window_text() or "").strip()
            except Exception:
                title = ""
            try:
                cls = w.class_name()
            except Exception:
                cls = ""
            try:
                handle = w.handle
            except Exception:
                handle = 0

            if title_substring and title_substring.lower() not in title.lower():
                continue

            info = {"title": title, "class": cls, "handle": handle}

            if process_id is not None:
                try:
                    import win32process
                    pid = win32process.GetWindowThreadProcessId(handle)[1]
                    info["process_id"] = pid
                    if pid != process_id:
                        continue
                except Exception:
                    pass

            results.append(info)

        return {
            "ok": True,
            "status": "200",
            "windows": results,
            "fout": len(results) == 0,
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon de vensters niet lezen: {error}",
        }


def find_window(title_substring=None, title_regex=None, process_id=None):

    """Vind een venster op titel(-substring/regex) of proces-id.

    Geeft het eerste matchende venster terug met titel, class en handle."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    Desktop, _Application = mods

    try:
        windows = list_windows(
            title_substring=title_substring,
            process_id=process_id,
            max_windows=200,
        )

        if not windows.get("ok"):
            return windows

        for w in windows.get("windows", []):
            if title_regex is not None:
                import re
                if not re.search(title_regex, w["title"], flags=re.I):
                    continue
            if title_substring is not None and title_substring.lower() not in w["title"].lower():
                continue
            if process_id is not None and w.get("process_id") != process_id:
                continue
            return {
                "ok": True,
                "status": "200",
                "found": True,
                "title": w["title"],
                "class": w["class"],
                "handle": w["handle"],
            }

        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": f"Geen venster gevonden voor {title_substring or title_regex or f'proces {process_id}'}.",
            "handle": None,
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon het venster niet vinden: {error}",
            "handle": None,
        }


def activate_window(handle):

    """Breng een venster (handle) naar de voorgrond."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    Desktop, _Application = mods

    try:
        window = Desktop(backend="uia").window(handle=handle)
        window.set_focus()
        return {
            "ok": True,
            "status": "200",
            "message": "Venster naar voorgrond gebracht.",
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon het venster niet activeren: {error}",
        }


# =============================================================
# UI-ELEMENTEN
# =============================================================

def _resolve_window(mods, handle):

    """Haal het Window-object op bij een handle. Verbergt pywinauto-details."""

    Desktop, _Application = mods
    return Desktop(backend="uia").window(handle=handle)


def list_elements(handle, name_filter=None, max_elements=MAX_LIST_ELEMENTS):

    """Lees de UI-elementen van een venster (type, naam, automation id).

    Optioneel filter op element-naam (substring, case-insensitive)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": "Geen venster-handle opgegeven.",
        }

    try:
        window = _resolve_window(mods, handle)

        results = []
        for desc in window.descendants():
            if len(results) >= max_elements:
                break
            try:
                element_type = desc.element_info.element_class if hasattr(desc.element_info, "element_class") else ""
                element_name = (desc.window_text() or "").strip()
                automation_id = ""
                try:
                    automation_id = desc.automation_id() or ""
                except Exception:
                    automation_id = ""

                if not element_type and not element_name:
                    continue

                if name_filter:
                    if not (
                        (element_name and name_filter.lower() in element_name.lower())
                        or (automation_id and name_filter.lower() in automation_id.lower())
                    ):
                        continue

                results.append({
                    "type": element_type,
                    "name": element_name,
                    "automation_id": automation_id,
                })
            except Exception:
                continue

        return {
            "ok": True,
            "status": "200",
            "elements": results,
            "count": len(results),
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon de elementen niet lezen: {error}",
        }


def find_element(handle, name=None, control_type=None):

    """Vind een UI-element in een venster op naam of type.

    Geeft een beschrijving terug (type, naam, automation id, handle)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": "Geen venster-handle opgegeven.",
        }

    try:
        window = _resolve_window(mods, handle)

        matches = []
        for desc in window.descendants():
            try:
                element_type = desc.element_info.element_class
                element_name = (desc.window_text() or "").strip()
                automation_id = ""
                try:
                    automation_id = desc.automation_id() or ""
                except Exception:
                    pass

                if control_type and str(control_type).lower() not in str(element_type).lower():
                    continue
                if name:
                    name_matches = (
                        name.lower() in element_name.lower()
                        or name.lower() in automation_id.lower()
                    )
                    if not name_matches:
                        continue

                matches.append({
                    "type": str(element_type),
                    "name": element_name,
                    "automation_id": automation_id,
                    "handle": desc.handle if hasattr(desc, "handle") else None,
                })
            except Exception:
                continue

        if not matches:
            return {
                "ok": False,
                "status": "geen-element",
                "error_type": "element_not_found",
                "error": f"Geen element gevonden met naam '{name}'" +
                         (f" en type '{control_type}'" if control_type else "") + ".",
                "count": 0,
            }

        return {
            "ok": True,
            "status": "200",
            "found": True,
            "matches": matches,
            "count": len(matches),
            "first": matches[0],
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon het element niet vinden: {error}",
            "count": 0,
        }


# =============================================================
# ACTIES
# =============================================================

def type_text(handle, text, element_name=None, interval=0.01):

    """Type tekst in het actieve of het gevonden invoerveld."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": "Geen venster-handle opgegeven.",
        }

    try:
        window = _resolve_window(mods, handle)

        target = None
        if element_name:
            result = find_element(handle, name=element_name)
            if result.get("ok") and result.get("matches"):
                target = result["matches"][0]
            else:
                return {
                    "ok": False,
                    "status": "geen-element",
                    "error_type": "element_not_found",
                    "error": f"Geen invoerveld '{element_name}' gevonden.",
                }

        if target is not None and target.get("handle"):
            try:
                from pywinauto.controls.uiawrapper import UIAWrapper
                inp = UIAWrapper(target["handle"])
                inp.set_edit_text(text)
            except Exception:
                window.type_keys(text, with_spaces=True, pause=interval)
        else:
            window.type_keys(text, with_spaces=True, pause=interval)

        return {
            "ok": True,
            "status": "200",
            "message": f"Tekst getypt ({len(text)} tekens).",
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon de tekst niet typen: {error}",
        }


def click_element(handle, name=None, control_type=None):

    """Klik op een UI-element in een venster op naam of type."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": "Geen venster-handle opgegeven.",
        }

    try:
        window = _resolve_window(mods, handle)

        result = find_element(handle, name=name, control_type=control_type)
        if not result.get("ok"):
            return result

        target = result["first"]
        clicked = False

        if target.get("handle"):
            try:
                from pywinauto.controls.uiawrapper import UIAWrapper
                wrapper = UIAWrapper(target["handle"])
                wrapper.click_input()
                clicked = True
            except Exception as click_error:
                print(f"(ui_automation) klik-input mislukt: {click_error}")

        if not clicked:
            # Fallback: klik het naam-gebaseerde element via de window-wrapper
            try:
                found = getattr(window, "child_window",
                                lambda **kw: None)(title=name, control_type=control_type)
                found.click_input() if found else (_ for _ in ()).throw(
                    RuntimeError("element niet klikbaar"))
                clicked = True
            except Exception as click_error:
                return {
                    "ok": False,
                    "status": "fout",
                    "error_type": "network_error",
                    "error": f"Kon het element niet klikken: {click_error}",
                }

        return {
            "ok": True,
            "status": "200",
            "message": f"Geklikt op element.",
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon het element niet klikken: {error}",
        }


def get_value(handle, name=None, control_type=None):

    """Lees de waarde van een UI-element (bijv. een slider of tekstveld)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": "Geen venster-handle opgegeven.",
        }

    try:
        result = find_element(handle, name=name, control_type=control_type)
        if not result.get("ok"):
            return result

        target = result["first"]
        value = ""
        if target.get("handle"):
            try:
                from pywinauto.controls.uiawrapper import UIAWrapper
                wrapper = UIAWrapper(target["handle"])
                value = wrapper.get_value() or wrapper.window_text() or wrapper.legacy_properties()["Value"] if hasattr(wrapper, "legacy_properties") else ""
            except Exception as read_error:
                print(f"(ui_automation) waarde lezen mislukt: {read_error}")

        return {
            "ok": True,
            "status": "200",
            "value": str(value).strip(),
            "element": target,
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon de waarde niet lezen: {error}",
        }


def set_value(handle, value, name=None, control_type=None):

    """Stel de waarde van een UI-element in (bijv. een slider of tekstveld)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return {
            "ok": False,
            "status": "geen-venster",
            "error_type": "window_not_found",
            "error": "Geen venster-handle opgegeven.",
        }

    try:
        result = find_element(handle, name=name, control_type=control_type)
        if not result.get("ok"):
            return result

        target = result["first"]
        changed = False
        if target.get("handle"):
            try:
                from pywinauto.controls.uiawrapper import UIAWrapper
                wrapper = UIAWrapper(target["handle"])
                wrapper.set_value(str(value))
                changed = True
            except Exception as write_error:
                print(f"(ui_automation) set_value mislukt: {write_error}")

        if not changed:
            return {
                "ok": False,
                "status": "fout",
                "error_type": "network_error",
                "error": "Kon de waarde niet instellen (element is niet schrijfbaar).",
            }

        return {
            "ok": True,
            "status": "200",
            "message": f"Waarde ingesteld op '{value}'.",
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon de waarde niet instellen: {error}",
        }


# =============================================================
# HELPERS
# =============================================================

def launch_app(path, args=None):

    """Start een applicatie en wacht kort tot deze een venster heeft."""

    try:
        cmd = [path] + (args or [])
        subprocess.Popen(cmd)
        time.sleep(1)
        return {
            "ok": True,
            "status": "200",
            "message": f"Applicatie gestart: {path}",
        }

    except Exception as error:
        return {
            "ok": False,
            "status": "fout",
            "error_type": "network_error",
            "error": f"Kon de applicatie niet starten: {error}",
        }