"""
Retry-systeem (Fase 8 + Fase 12)

Zelfstandige retry-logica voor één toolactie. Bewust LOS van de
Executor gebouwd zodat Dependencies en het bestaande gedrag
onaangetast blijven.

Architectuurregel:
    Executor  : "Voer het plan uit."
    Retry     : "Probeer één stap opnieuw als hij mislukt."
    Actions   : "Hoe voer ik de actie uit?"

Hoe het werkt:
    - Een mislukte actie wordt maximaal DEFAULT_MAX_RETRIES keer
      opnieuw geprobeerd (standaard 2, dus maximaal 3 pogingen).
    - Lukt een poging            -> status "done"
    - Lukt geen enkele poging    -> status "failed"
    - Per actie worden bijgehouden: aantal pogingen, de fouten
      en de resultaten van iedere poging.

Fase 12: Fallback Chains
    Naast het herhalen van dezelfde tool, kun je nu alternatieve
    tools configureren die geprobeerd worden als de primaire tool
    faalt. Dit wordt gedaan via de FALLBACK_MAP dictionary.

De tool-runner wordt als parameter meegegeven (meestal de bestaande
execute_tool() uit core/ai.py), waardoor dit bestand geen imports uit
core/ai.py nodig heeft en er geen circulaire import ontstaat.
"""

from core.result_validation import classify_tool_result

DEFAULT_MAX_RETRIES = 2

# =============================================================
# Resultaat-classificatie
# =============================================================

def _is_logical_failure(result):
    """
    Bepaalt of een tool-resultaat een MISLUKKING is, ook als er
    geen exception werd gegooid. Dit is de brug tussen Fase 9
    (resultaatvalidatie) en Fase 12 (fallback chains): een actie
    die terugkomt met {"ok": False} telt nu óók als falen, zodat
    de fallback-chain erop kan reageren.
    """
    if isinstance(result, dict):
        if result.get("ok") is False:
            return True
        if result.get("error_type"):
            return True

    # tools retourneren via execute_tool() een STRING van het dict;
    # parse die terug zodat {"ok": False} ook door de string heen telt
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                import json
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    if parsed.get("ok") is False:
                        return True
                    if parsed.get("error_type"):
                        return True
            except Exception:
                try:
                    import ast
                    parsed = ast.literal_eval(stripped)
                    if isinstance(parsed, dict):
                        if parsed.get("ok") is False:
                            return True
                        if parsed.get("error_type"):
                            return True
                except Exception:
                    pass

    try:
        return classify_tool_result(result) == "failed"
    except Exception:
        return False

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


def execute_with_retry(tool_runner, tool_name, arguments, question, max_retries=DEFAULT_MAX_RETRIES, use_fallbacks=True):

    """
    Voert ÉÉN toolactie uit met retries EN fallbacks.

    tool_runner : functie met signature (tool_name, arguments, question),
                  meestal execute_tool() uit core/ai.py.

    use_fallbacks : als True, worden alternatieve tools geprobeerd
                    na het mislukken van de primaire tool.

    Geeft een dict terug:

        {
            "status":   "done" | "failed",
            "result":   eindresultaat als string,
            "attempts": aantal pogingen gedaan,
            "errors":   lijst met foutmeldingen per mislukte poging,
            "results":  lijst met resultaat/fout-strings per poging,
            "fallback_used": naam van de fallback-tool die werkte (of None),
        }
    """

    total_tries = max(1, int(max_retries) + 1)

    attempts = 0
    errors = []
    results = []
    fallback_used = None

    # Stap 1: Probeer de primaire tool.
    while attempts < total_tries:

        attempts += 1

        try:

            result = tool_runner(tool_name, arguments, question)

            results.append(str(result))

            # Fase 12: een retour van {"ok": False} of een aantoonbare
            # foutmelding betekent dat DIT zelfde pad niet gaat werken.
            # Retry dezelfde tool is zinloos -> breek af, probeer fallback.
            if _is_logical_failure(result):
                msg = f"{tool_name} retourneerde een fout: {str(result)[:120]}"
                errors.append(msg)
                results.append(msg)
                print(f"[RETRY] Logische mislukking voor {tool_name}: {msg}")
                break

            return {
                "status": "done",
                "result": str(result),
                "attempts": attempts,
                "errors": errors,
                "results": results,
                "fallback_used": fallback_used,
            }

        except Exception as error:

            errors.append(str(error))
            results.append(f"Fout bij uitvoeren van {tool_name}: {error}")

            print(f"[RETRY] Poging {attempts}/{total_tries} mislukt voor {tool_name}: {error}")

    # Stap 2: Als de primaire tool faalt, probeer fallbacks
    if use_fallbacks and tool_name in FALLBACK_MAP:

        for fallback in FALLBACK_MAP[tool_name]:

            fallback_tool = fallback["tool_name"]
            transform = fallback.get("transform_args")
            fallback_args = transform(arguments) if transform else arguments

            print(f"[FALLBACK] Probeer alternatief: {fallback_tool}")

            try:

                result = tool_runner(fallback_tool, fallback_args, question)

                # Ook de fallback mag geen logische mislukking opleveren
                if _is_logical_failure(result):
                    fmsg = f"[fallback:{fallback_tool}] fout: {str(result)[:120]}"
                    errors.append(fmsg)
                    results.append(fmsg)
                    print(f"[FALLBACK] {fallback_tool} logische mislukking: {fmsg}")
                    continue

                results.append(f"[fallback:{fallback_tool}] {result}")
                fallback_used = fallback_tool

                return {
                    "status": "done",
                    "result": str(result),
                    "attempts": attempts,
                    "errors": errors,
                    "results": results,
                    "fallback_used": fallback_used,
                }

            except Exception as error:

                errors.append(f"[fallback:{fallback_tool}] {error}")
                results.append(f"Fout bij fallback {fallback_tool}: {error}")
                print(f"[FALLBACK] {fallback_tool} ook mislukt: {error}")

    return {
        "status": "failed",
        "result": f"Fout bij uitvoeren van {tool_name} na {total_tries} poging(en): {errors[-1]}",
        "attempts": attempts,
        "errors": errors,
        "results": results,
        "fallback_used": fallback_used,
    }