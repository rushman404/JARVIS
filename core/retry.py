"""
Retry-systeem (Fase 8)

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

De tool-runner wordt als parameter meegegeven (meestal de bestaande
execute_tool() uit core/ai.py), waardoor dit bestand geen imports uit
core/ai.py nodig heeft en er geen circulaire import ontstaat.
"""

DEFAULT_MAX_RETRIES = 2


def execute_with_retry(tool_runner, tool_name, arguments, question, max_retries=DEFAULT_MAX_RETRIES):

    """
    Voert ÉÉN toolactie uit met retries.

    tool_runner : functie met signature (tool_name, arguments, question),
                  meestal execute_tool() uit core/ai.py.

    Geeft een dict terug:

        {
            "status":   "done" | "failed",
            "result":   eindresultaat als string,
            "attempts": aantal pogingen gedaan,
            "errors":   lijst met foutmeldingen per mislukte poging,
            "results":  lijst met resultaat/fout-strings per poging,
        }
    """

    total_tries = max(1, int(max_retries) + 1)

    attempts = 0
    errors = []
    results = []

    while attempts < total_tries:

        attempts += 1

        try:

            result = tool_runner(tool_name, arguments, question)

            results.append(str(result))

            return {
                "status": "done",
                "result": str(result),
                "attempts": attempts,
                "errors": errors,
                "results": results,
            }

        except Exception as error:

            errors.append(str(error))
            results.append(f"Fout bij uitvoeren van {tool_name}: {error}")

            print(f"[RETRY] Poging {attempts}/{total_tries} mislukt voor {tool_name}: {error}")

    return {
        "status": "failed",
        "result": f"Fout bij uitvoeren van {tool_name} na {total_tries} poging(en): {errors[-1]}",
        "attempts": attempts,
        "errors": errors,
        "results": results,
    }