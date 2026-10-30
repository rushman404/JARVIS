"""Routines maken en aanpassen vanaf het dashboard (Fase 27, M1).

Het dashboard (⚙ → Routines) werkt met een eenvoudige vorm van een routine:
naam, protocolnamen, start- en eindzin, "vertrouwd" en een lijst stappen.
Deze module zet die vorm om naar ``config/routines.json`` en terug, en
controleert alles streng: het dashboard mag nooit zomaar een willekeurige
tool in een routine zetten.

Soorten stappen (besluit 2026-10-30: vaste lijst + vrije opdracht):

* ``open`` / ``sluit``: een programma (``open_program`` / ``close_program``)
* ``volume``: het volume op een percentage (``set_volume``)
* ``opdracht``: een zin die JARVIS uitvoert alsof u hem zei
  (``jarvis_opdracht``); daarmee ook lamp, tv, Spotify en scènes
* ``bestaand``: een stap uit een bestaande routine die het dashboard niet
  zelf kan maken (bijv. een slim-huis-tool); die blijft precies zoals hij
  was en mag alleen verplaatst of weggehaald worden.

Bij elke wijziging maakt ``core/routines.py`` eerst ``routines.json.bak``.
"""

import re

MAX_STAPPEN = 20
MAX_PROTOCOLLEN = 5
MAX_ZIN = 120
MAX_TEKST = 120
MAX_PROGRAMMA = 40

_NAAM = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,29}$")
OPDRACHT_TOOL = "jarvis_opdracht"


class RoutineFout(ValueError):
    """Ongeldige invoer; de tekst is geschikt voor het dashboard."""


def _manager():
    from core.routines import _manager as manager

    return manager


def _beschrijf(stap):
    try:
        from core.tool_registry import describe_tool_action

        return describe_tool_action(stap.get("tool_name", ""), dict(stap.get("arguments") or {}))
    except Exception:
        return stap.get("tool_name", "")


def naar_dashboard(stap):
    """Een opgeslagen stap in de vorm van het dashboard."""

    tool = stap.get("tool_name")
    args = stap.get("arguments") or {}
    if tool == "open_program" and set(args) == {"program"}:
        return {"soort": "open", "programma": str(args["program"])}
    if tool == "close_program" and set(args) == {"program"}:
        return {"soort": "sluit", "programma": str(args["program"])}
    if tool == "set_volume" and set(args) == {"percent"}:
        return {"soort": "volume", "procent": args["percent"]}
    if tool == OPDRACHT_TOOL and set(args) == {"tekst"}:
        return {"soort": "opdracht", "tekst": str(args["tekst"])}
    return {"soort": "bestaand", "tool_name": tool, "arguments": args, "omschrijving": _beschrijf(stap)}


def routine_naar_dashboard(naam, routine):
    return {
        "naam": naam,
        "beschrijving": routine.get("description") or "",
        "protocollen": [str(p) for p in routine.get("protocollen") or []],
        "start_zin": routine.get("start_zin") or "",
        "eind_zin": routine.get("eind_zin") or "",
        "vertrouwd": bool(routine.get("vertrouwd", False)),
        "stappen": [naar_dashboard(s) for s in routine.get("steps") or [] if isinstance(s, dict)],
        # Een film-routine (Fase 21) heeft geen stappen; die kan het
        # dashboard niet aanpassen.
        "bewerkbaar": routine.get("soort") != "film",
    }


def lijst():
    """Alle routines voor de editor, op naam."""

    manager = _manager()
    manager.reload()
    return [routine_naar_dashboard(naam, r) for naam, r in sorted(manager.list_routines().items())]


# -----------------------------------------------------------------
# Controleren
# -----------------------------------------------------------------

def _tekst(waarde, veld, maximaal, verplicht=False):
    if waarde is None:
        waarde = ""
    if not isinstance(waarde, str):
        raise RoutineFout(f"{veld} moet tekst zijn.")
    waarde = " ".join(waarde.split())
    if verplicht and not waarde:
        raise RoutineFout(f"{veld} ontbreekt.")
    if len(waarde) > maximaal:
        raise RoutineFout(f"{veld} is te lang (hooguit {maximaal} tekens).")
    return waarde


def _stap_uit_dashboard(stap, bestaande):
    if not isinstance(stap, dict):
        raise RoutineFout("Een stap is ongeldig.")
    soort = stap.get("soort")
    if soort in ("open", "sluit"):
        programma = _tekst(stap.get("programma"), "Het programma", MAX_PROGRAMMA, verplicht=True)
        tool = "open_program" if soort == "open" else "close_program"
        return {"tool_name": tool, "arguments": {"program": programma}}
    if soort == "volume":
        procent = stap.get("procent")
        if isinstance(procent, bool) or not isinstance(procent, int) or not 0 <= procent <= 100:
            raise RoutineFout("Het volume moet een getal van 0 tot 100 zijn.")
        return {"tool_name": "set_volume", "arguments": {"percent": procent}}
    if soort == "opdracht":
        tekst = _tekst(stap.get("tekst"), "De opdracht", MAX_TEKST, verplicht=True)
        return {"tool_name": OPDRACHT_TOOL, "arguments": {"tekst": tekst}}
    if soort == "bestaand":
        # Alleen een stap die al in deze routine stond: het dashboard kan
        # zo nooit een willekeurige tool toevoegen.
        kandidaat = {"tool_name": stap.get("tool_name"), "arguments": stap.get("arguments")}
        for oud in bestaande:
            if oud.get("tool_name") == kandidaat["tool_name"] and (oud.get("arguments") or {}) == (
                    kandidaat["arguments"] or {}):
                return {"tool_name": oud["tool_name"], "arguments": dict(oud.get("arguments") or {})}
        raise RoutineFout("Een bestaande stap is gewijzigd; die kan alleen verplaatst of verwijderd worden.")
    raise RoutineFout("Onbekende soort stap.")


def _naam(waarde):
    naam = _tekst(waarde, "De naam", 30, verplicht=True).lower()
    if not _NAAM.match(naam):
        raise RoutineFout("De naam mag alleen letters, cijfers, spaties, - en _ bevatten.")
    return naam


# -----------------------------------------------------------------
# Opslaan en verwijderen
# -----------------------------------------------------------------

def opslaan(gegevens):
    """Een routine opslaan (nieuw of bijwerken). Geeft de dashboardvorm terug.

    ``gegevens``: naam, oude_naam (bij bewerken, ook bij hernoemen),
    beschrijving, protocollen, start_zin, eind_zin, vertrouwd, stappen.
    Andere velden van een bestaande routine (triggers, gebruik,
    muziekvoorstel, …) blijven bewaard.
    """

    if not isinstance(gegevens, dict):
        raise RoutineFout("Stuur een routine.")
    manager = _manager()
    manager.reload()
    routines = manager.list_routines()

    naam = _naam(gegevens.get("naam"))
    oude_naam = gegevens.get("oude_naam")
    if oude_naam is not None:
        if not isinstance(oude_naam, str) or oude_naam not in routines:
            raise RoutineFout("Deze routine bestaat niet meer.")
        if routines[oude_naam].get("soort") == "film":
            raise RoutineFout("De film-routine kunt u niet op het dashboard aanpassen.")
    if naam in routines and naam != oude_naam:
        raise RoutineFout(f"Er is al een routine '{naam}'.")

    protocollen = gegevens.get("protocollen") or []
    if not isinstance(protocollen, list) or len(protocollen) > MAX_PROTOCOLLEN:
        raise RoutineFout(f"Hooguit {MAX_PROTOCOLLEN} protocolnamen.")
    protocollen = [p for p in (_tekst(p, "Een protocolnaam", 30).lower() for p in protocollen) if p]

    stappen_in = gegevens.get("stappen")
    if not isinstance(stappen_in, list) or not stappen_in:
        raise RoutineFout("Een routine heeft minstens één stap nodig.")
    if len(stappen_in) > MAX_STAPPEN:
        raise RoutineFout(f"Hooguit {MAX_STAPPEN} stappen.")
    bestaande = list((routines.get(oude_naam) or {}).get("steps") or []) if oude_naam else []
    stappen = [_stap_uit_dashboard(s, bestaande) for s in stappen_in]

    vertrouwd = gegevens.get("vertrouwd", False)
    if not isinstance(vertrouwd, bool):
        raise RoutineFout("vertrouwd moet ja of nee zijn.")

    routine = dict(routines.get(oude_naam) or {}) if oude_naam else {"triggers": [], "aliases": []}
    routine.update({
        "name": naam,
        "description": _tekst(gegevens.get("beschrijving"), "De beschrijving", MAX_ZIN),
        "protocollen": protocollen,
        "start_zin": _tekst(gegevens.get("start_zin"), "De startzin", MAX_ZIN),
        "eind_zin": _tekst(gegevens.get("eind_zin"), "De eindzin", MAX_ZIN),
        "vertrouwd": vertrouwd,
        "steps": stappen,
    })
    if not routine["description"]:
        routine["description"] = f"Routine {naam} ({len(stappen)} stappen)."

    nieuw = dict(routines)
    if oude_naam and oude_naam != naam:
        nieuw.pop(oude_naam, None)
    nieuw[naam] = routine
    _bewaar(manager, nieuw)
    return routine_naar_dashboard(naam, routine)


def verwijder(naam):
    """Verwijdert een routine; True als hij bestond."""

    if not isinstance(naam, str) or not naam:
        raise RoutineFout("naam ontbreekt.")
    manager = _manager()
    manager.reload()
    if naam not in manager.list_routines():
        return False
    return manager.delete_routine(naam)


def _bewaar(manager, routines):
    from core import routines as routines_mod

    routines_mod._save_routines(routines)  # maakt eerst routines.json.bak
    manager.reload()
