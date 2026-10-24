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

from core.result_validation import ToolResult
from actions.com_worker import is_com_thread, run_on_com_thread

TIMEOUT = 3
WINDOW_TIMEOUT = 5
MAX_LIST_ELEMENTS = 50


def _import_pywinauto():

    """Importeer pywinauto lazily. Geeft None als het niet beschikbaar is.

    De import gebeurt bewust op de COM-worker. Importeert de hoofdthread
    eerst pywinauto (of windowcom: win32com/pythoncom), dan hangen latere
    UIA-aanroepen op de worker. Op de worker zelf is COM netjes STA.
    """

    if not is_com_thread():
        try:
            return run_on_com_thread(_import_pywinauto)
        except Exception:
            return None

    try:
        from pywinauto import Desktop
        from pywinauto.application import Application
        return Desktop, Application
    except (ImportError, OSError):
        return None


def _not_available():

    return ToolResult(
        ok=False,
        message="UI-automatisering is niet beschikbaar (pywinauto is niet geïnstalleerd).",
        error_kind="ui_automation_unavailable",
    )


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
        def _get():
            return Desktop(backend="uia").windows()
        windows = run_on_com_thread(_get)

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

        return ToolResult(
            ok=True,
            message=(
                f"Ik heb {len(results)} venster(s) gevonden."
                if results else
                "Ik heb geen vensters gevonden."
            ),
            data={"windows": results},
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon de vensters niet lezen: {error}",
            error_kind="network_error",
        )


def find_window(title_substring=None, title_regex=None, process_id=None):

    """Vind een venster op titel(-substring/regex) of proces-id.

    Geeft het eerste matchende venster terug met titel, class en handle."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    Desktop, _Application = mods

    try:
        # list_windows() draait de COM-call al op de dedicated COM-thread.
        # Niet nóg eens omwikkelen met run_on_com_thread, want dat zou de
        # enige COM-thread blokkeren (nested call -> deadlock/timeout).
        windows = list_windows(
            title_substring=title_substring,
            process_id=process_id,
            max_windows=200,
        )

        if not windows.ok:
            return windows

        for w in windows.data.get("windows", []):
            if title_regex is not None:
                import re
                if not re.search(title_regex, w["title"], flags=re.I):
                    continue
            if title_substring is not None and title_substring.lower() not in w["title"].lower():
                continue
            if process_id is not None and w.get("process_id") != process_id:
                continue
            return ToolResult(
                ok=True,
                message=f"Venster gevonden: {w['title']}.",
                data={
                    "found": True,
                    "title": w["title"],
                    "class": w["class"],
                    "handle": w["handle"],
                },
            )

        return ToolResult(
            ok=False,
            message=f"Geen venster gevonden voor {title_substring or title_regex or f'proces {process_id}'}.",
            data={"handle": None},
            error_kind="window_not_found",
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon het venster niet vinden: {error}",
            data={"handle": None},
            error_kind="network_error",
        )


def activate_window(handle):

    """Breng een venster (handle) naar de voorgrond."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    Desktop, _Application = mods

    try:
        def _activate():
            window = Desktop(backend="uia").window(handle=handle)
            window.set_focus()
        run_on_com_thread(_activate)
        return ToolResult(
            ok=True,
            message="Venster naar voorgrond gebracht.",
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon het venster niet activeren: {error}",
            error_kind="network_error",
        )


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
        return ToolResult(
            ok=False,
            message="Geen venster-handle opgegeven.",
            error_kind="window_not_found",
        )

    try:
        def _get_descendants():
            window = _resolve_window(mods, handle)
            return list(window.descendants())
        descendants = run_on_com_thread(_get_descendants)

        results = []
        for desc in descendants:
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

        return ToolResult(
            ok=True,
            message=f"Ik heb {len(results)} element(en) gevonden.",
            data={"elements": results, "count": len(results)},
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon de elementen niet lezen: {error}",
            error_kind="network_error",
        )


def find_element(handle, name=None, control_type=None):

    """Vind een UI-element in een venster op naam of type.

    Geeft een beschrijving terug (type, naam, automation id, handle)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return ToolResult(
            ok=False,
            message="Geen venster-handle opgegeven.",
            error_kind="window_not_found",
        )

    try:
        # De UIA-boom moet op de COM-thread worden opgehaald. Een
        # pywinauto-aanroep vanuit een HTTP-workerthread laat de agent
        # anders vasthangen (de COM-thread is hier speciaal voor bedoeld).
        def _descendants():
            window = _resolve_window(mods, handle)
            return list(window.descendants())

        elementen = run_on_com_thread(_descendants)

        matches = []
        for desc in elementen:
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
            return ToolResult(
                ok=False,
                message=f"Geen element gevonden met naam '{name}'" +
                        (f" en type '{control_type}'" if control_type else "") + ".",
                data={"count": 0},
                error_kind="element_not_found",
            )

        return ToolResult(
            ok=True,
            message=f"Element gevonden: {matches[0]['name'] or matches[0]['type']}.",
            data={
                "found": True,
                "matches": matches,
                "count": len(matches),
                "first": matches[0],
            },
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon het element niet vinden: {error}",
            data={"count": 0},
            error_kind="network_error",
        )


# =============================================================
# ACTIES
# =============================================================

def type_text(handle, text, element_name=None, interval=0.01):

    """Type tekst in het actieve of het gevonden invoerveld."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return ToolResult(
            ok=False,
            message="Geen venster-handle opgegeven.",
            error_kind="window_not_found",
        )

    try:
        target = None
        if element_name:
            result = find_element(handle, name=element_name)
            if result.ok and result.data.get("matches"):
                target = result.data["matches"][0]
            else:
                return ToolResult(
                    ok=False,
                    message=f"Geen invoerveld '{element_name}' gevonden.",
                    error_kind="element_not_found",
                )

        def _type_window():
            _resolve_window(mods, handle).type_keys(
                text, with_spaces=True, pause=interval
            )

        if target is not None and target.get("handle"):
            def _type_element():
                from pywinauto.controls.uiawrapper import UIAWrapper
                UIAWrapper(target["handle"]).set_edit_text(text)

            try:
                run_on_com_thread(_type_element)
            except Exception:
                run_on_com_thread(_type_window)
        else:
            run_on_com_thread(_type_window)

        return ToolResult(
            ok=True,
            message=f"Tekst ingetypt ({len(text)} tekens).",
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon de tekst niet typen: {error}",
            error_kind="network_error",
        )


def click_element(handle, name=None, control_type=None):

    """Klik op een UI-element in een venster op naam of type."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return ToolResult(
            ok=False,
            message="Geen venster-handle opgegeven.",
            error_kind="window_not_found",
        )

    try:
        result = find_element(handle, name=name, control_type=control_type)
        if not result.ok:
            return result

        target = result.data["first"]
        clicked = False

        if target.get("handle"):
            try:
                def _click_input():
                    from pywinauto.controls.uiawrapper import UIAWrapper
                    UIAWrapper(target["handle"]).click_input()

                run_on_com_thread(_click_input)
                clicked = True
            except Exception as click_error:
                print(f"(ui_automation) klik-input mislukt: {click_error}")

        if not clicked:
            # Fallback: klik het naam-gebaseerde element via de window-wrapper
            try:
                def _click():
                    window = _resolve_window(mods, handle)
                    child_window = getattr(window, "child_window", None)
                    if child_window is None:
                        raise RuntimeError("element niet klikbaar")
                    child_window(title=name, control_type=control_type).click_input()

                run_on_com_thread(_click)
                clicked = True
            except Exception as click_error:
                return ToolResult(
                    ok=False,
                    message=f"Kon het element niet klikken: {click_error}",
                    error_kind="network_error",
                )

        return ToolResult(
            ok=True,
            message=f"Geklikt op {name or control_type or 'element'}.",
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon het element niet klikken: {error}",
            error_kind="network_error",
        )


def get_value(handle, name=None, control_type=None):

    """Lees de waarde van een UI-element (bijv. een slider of tekstveld)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return ToolResult(
            ok=False,
            message="Geen venster-handle opgegeven.",
            error_kind="window_not_found",
        )

    try:
        result = find_element(handle, name=name, control_type=control_type)
        if not result.ok:
            return result

        target = result.data["first"]
        value = ""
        if target.get("handle"):
            def _lees():
                from pywinauto.controls.uiawrapper import UIAWrapper
                wrapper = UIAWrapper(target["handle"])
                waarde = wrapper.get_value()
                if not waarde:
                    waarde = wrapper.window_text()
                if not waarde and hasattr(wrapper, "legacy_properties"):
                    waarde = wrapper.legacy_properties().get("Value", "") or ""
                return waarde

            try:
                value = run_on_com_thread(_lees)
            except Exception as read_error:
                print(f"(ui_automation) waarde lezen mislukt: {read_error}")

        value = str(value).strip()
        return ToolResult(
            ok=True,
            message=f"Waarde gelezen: {value}.",
            data={"value": value, "element": target},
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon de waarde niet lezen: {error}",
            error_kind="network_error",
        )


def set_value(handle, value, name=None, control_type=None):

    """Stel de waarde van een UI-element in (bijv. een slider of tekstveld)."""

    mods = _import_pywinauto()
    if mods is None:
        return _not_available()

    if not handle:
        return ToolResult(
            ok=False,
            message="Geen venster-handle opgegeven.",
            error_kind="window_not_found",
        )

    try:
        result = find_element(handle, name=name, control_type=control_type)
        if not result.ok:
            return result

        target = result.data["first"]
        changed = False
        if target.get("handle"):
            def _set():
                from pywinauto.controls.uiawrapper import UIAWrapper
                UIAWrapper(target["handle"]).set_value(str(value))

            try:
                run_on_com_thread(_set)
                changed = True
            except Exception as write_error:
                print(f"(ui_automation) set_value mislukt: {write_error}")

        if not changed:
            return ToolResult(
                ok=False,
                message="Kon de waarde niet instellen (element is niet schrijfbaar).",
                error_kind="network_error",
            )

        return ToolResult(
            ok=True,
            message="Waarde ingesteld.",
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon de waarde niet instellen: {error}",
            error_kind="network_error",
        )


# =============================================================
# HELPERS
# =============================================================

def launch_app(path, args=None):

    """Start een applicatie en wacht kort tot deze een venster heeft."""

    try:
        cmd = [path] + (args or [])
        subprocess.Popen(cmd)
        time.sleep(1)
        return ToolResult(
            ok=True,
            message=f"App gestart: {path}.",
        )

    except Exception as error:
        return ToolResult(
            ok=False,
            message=f"Kon de applicatie niet starten: {error}",
            error_kind="network_error",
        )
