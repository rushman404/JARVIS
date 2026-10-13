"""
Retry-systeem (Fase 8 + Fase 12 — betrouwbaar & veilig)

Zelfstandige retry-logica voor één toolactie. Bewust LOS van de
Executor gebouwd zodat Dependencies en het bestaande gedrag
onaangetast blijven.

Architectuurregel:
    Executor  : "Voer het plan uit."
    Retry     : "Probeer één stap opnieuw als hij veilig te herhalen is."
    Actions   : "Hoe voer ik de actie uit?"

WAAROM géén blind herhalen:
    - media_play_pause is een toggle: een tweede keer doet net het
      tegenovergestelde.
    - ui_type_text typt dubbel, ui_click_element klikt dubbel,
      move_file verplaatst tweemaal.
    Daarom wordt alleen HERHAALD als de tool idempotent is (vastgelegd
    in core/tool_registry.py) EN de fout tijdelijk was (exception/
    timeout). Een definitieve mislukking (ok=False) wordt nooit
    herhaald; die gaat naar de fallback-chain of is gewoon mislukt.

Fase 12: Fallback Chains
    Naast het herhalen van een veilige tool, kun je alternatieve tools
    configureren die geprobeerd worden als de primaire tool faalt.
    Dit gebeurt via de FALLBACK_MAP dictionary. Een fallback die een
    ANDERE actie uitvoert (bijv. ui_find_element i.p.v. klikken) levert
    een PARTIEEL resultaat op (partial=True) en JARVIS zegt eerlijk wat
    er wel en niet is gedaan.

De tool-runner wordt als parameter meegegeven (meestal execute_tool()
uit core/ai.py), waardoor dit bestand geen imports uit core/ai.py
nodig heeft en er geen circulaire import ontstaat.
"""

from core.result_validation import to_tool_result
from core.tool_registry import get_tool_idempotent

DEFAULT_MAX_RETRIES = 2

# =============================================================
# FALLBACK MAP (Fase 12)
# Per tool: lijst van alternatieven die geprobeerd worden als de
# primaire tool faalt. Elke entry is een dict met:
#   - tool_name: de alternatieve tool
#   - transform_args: functie om argumenten om te zetten (optioneel)
# =============================================================

FALLBACK_MAP = {
    "ui_click_element": [
        {
            "tool_name": "ui_find_element",
            "description": "Zoek het element eerst, dan klik",
        },
    ],
    "ui_type_text": [
        {
            "tool_name": "ui_find_element",
            "description": "Zoek het veld eerst, dan type",
        },
    ],
    "browser_search": [
        {
            "tool_name": "web_search",
            "description": "Val terug op DuckDuckGo als browser niet werkt",
            "transform_args": lambda args: {"query": args.get("query", "")},
        },
    ],
}


def _is_logical_failure(result):
    """Backwards-compatibele mislukking-check (Fase 8-tests).

    Moderne tools geven een ToolResult terug; de adapter beslist dan
    aan de hand van de ok-vlag. Legacy-dicts met een error_type tellen
    óók als mislukking (oud contract: error_type = aantoonbare fout).
    """

    if isinstance(result, dict) and (result.get("error_type") or result.get("error_kind")):
        return True

    try:
        return not to_tool_result(result).ok
    except Exception:
        return False


def _bepaal_retries(tool_name, max_retries):
    """
    Alleen IDEMPOTENTE tools mogen opnieuw aangeboden worden.
    Niet-idempotente tools (toggle, typen, klikken, verplaatsen)
    krijgen precies EÉN poging.
    """

    if get_tool_idempotent(tool_name):
        return max(1, int(max_retries) + 1)

    return 1


def execute_with_retry(tool_runner, tool_name, arguments, question, max_retries=DEFAULT_MAX_RETRIES, use_fallbacks=True):

    """
    Voert ÉÉN toolactie uit met veilige retries én fallbacks.

    tool_runner   : functie met signature (tool_name, arguments, question),
                    meestal execute_tool() uit core/ai.py.
    use_fallbacks : als True, worden alternatieve tools geprobeerd
                    na het mislukken van de primaire tool.

    Geeft een dict terug:

        {
            "status":   "done" | "failed",
            "result":   eindresultaat als string (of ToolResult),
            "attempts": aantal werkelijk gedane pogingen,
            "errors":   lijst met foutmeldingen per mislukte poging,
            "results":  lijst met resultaat/fout-strings per poging,
            "fallback_used": naam van de fallback-tool die werkte (of None),
            "partial":  True als een fallback een ANDERE actie deed,
        }
    """

    total_tries = _bepaal_retries(tool_name, max_retries)

    attempts = 0
    errors = []
    results = []
    fallback_used = None
    partial = False

    laatste_error_kind = None

    # Stap 1: Probeer de primaire tool.
    while attempts < total_tries:

        attempts += 1

        try:

            raw_result = tool_runner(tool_name, arguments, question)
            tr = to_tool_result(raw_result)

            results.append(str(tr))

            # Een definitieve mislukking (ok=False / "failed"-classificatie)
            # is niet tijdelijk: RETRY heeft geen zin, ga naar fallback.
            if not tr.ok:

                msg = f"{tool_name} retourneerde een fout: {tr.message[:120]}"
                errors.append(msg)
                results.append(msg)

                laatste_error_kind = tr.error_kind

                print(f"[RETRY] Logische mislukking voor {tool_name}: {msg}")

                break

            return {
                "status": "done",
                "result": tr,
                "attempts": attempts,
                "errors": errors,
                "results": results,
                "fallback_used": fallback_used,
                "partial": tr.partial,
            }

        except Exception as error:

            errors.append(str(error))
            results.append(f"Fout bij uitvoeren van {tool_name}: {error}")

            print(f"[RETRY] Poging {attempts}/{total_tries} mislukt voor {tool_name}: {error}")

            # Niet-idempotent: één fout is definitief, ga direct naar
            # de fallback (of falen). Nooit dubbel typen/klikken/togglen.
            if attempts >= total_tries:
                break

    # Stap 2: Fallbacks
    if use_fallbacks and tool_name in FALLBACK_MAP:

        for fallback in FALLBACK_MAP[tool_name]:

            fallback_tool = fallback["tool_name"]
            transform = fallback.get("transform_args")
            fallback_args = transform(arguments) if transform else arguments

            print(f"[FALLBACK] Probeer alternatief: {fallback_tool}")

            try:

                fallback_raw = tool_runner(fallback_tool, fallback_args, question)
                fallback_tr = to_tool_result(fallback_raw)

                if not fallback_tr.ok:

                    fmsg = f"[fallback:{fallback_tool}] fout: {str(fallback_tr)[:120]}"
                    errors.append(fmsg)
                    results.append(fmsg)
                    print(f"[FALLBACK] {fallback_tool} logische mislukking: {fmsg}")
                    continue

                fallback_used = fallback_tool

                # Een fallback die een ANDERE actie uitvoert (bijv. alleen
                # vinden i.p.v. klikken) is partiëel: JARVIS zegt eerlijk
                # wat er wél en niet is gelukt.
                if fallback_tool != tool_name:
                    partial = True
                    eerlijk = (
                        f"{str(fallback_tr)} (de actie '{tool_name}' is "
                        f"niet uitgevoerd)"
                    )
                    eind_resultaat = eerlijk
                else:
                    eind_resultaat = fallback_tr

                results.append(f"[fallback:{fallback_tool}] {str(fallback_tr)}")

                return {
                    "status": "done",
                    "result": eind_resultaat,
                    "attempts": attempts,
                    "errors": errors,
                    "results": results,
                    "fallback_used": fallback_used,
                    "partial": partial,
                }

            except Exception as error:

                errors.append(f"[fallback:{fallback_tool}] {error}")
                results.append(f"Fout bij fallback {fallback_tool}: {error}")
                print(f"[FALLBACK] {fallback_tool} ook mislukt: {error}")

    # Eerlijk aantal werkelijk gedane pogingen in de melding.
    laatste_fout = errors[-1] if errors else "onbekende fout"

    return {
        "status": "failed",
        "result": f"Fout bij uitvoeren van {tool_name} na {attempts} poging(en): {laatste_fout}",
        "attempts": attempts,
        "errors": errors,
        "results": results,
        "fallback_used": fallback_used,
        "partial": partial,
        "error_kind": laatste_error_kind,
    }