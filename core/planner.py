"""
Planner (Fase 8, stap 1)

De Planner zet de ruwe AI-toolcalls om in een genormaliseerd Action Plan.

Architectuurregel:
    Planner   : "Wat moet er gebeuren?"
    Executor  : "Voer het plan uit."          (komt later)
    Actions   : "Hoe voer ik de actie uit?"

De Planner voert NIETS uit. Hij kent alleen:
    - tool_name
    - arguments
    - status

De daadwerkelijke uitvoering blijft bij execute_tool() in core/ai.py.
"""


def _extract_function(call):

    # Ollama geeft objecten: call.function.name / call.function.arguments
    function = getattr(call, "function", None)

    # Fallback: soms komt een tool call als gewone dict binnen
    if function is None and isinstance(call, dict):
        function = call.get("function")

    return function


def make_action_plan(tool_calls):

    """
    Maakt een genormaliseerd Action Plan van de ruwe AI-toolcalls.

    Geeft een lijst terug met stappen:

        {
            "tool_name": "open_program",
            "arguments": {"program": "Discord"},
            "status": "pending",
        }

    Een ongeldige stap krijgt status "invalid" en crasht niet.
    """

    plan = []

    if not tool_calls:
        return plan

    for index, call in enumerate(tool_calls):

        function = _extract_function(call)

        tool_name = getattr(function, "name", None)
        if tool_name is None and isinstance(function, dict):
            tool_name = function.get("name")

        arguments = getattr(function, "arguments", None)
        if arguments is None and isinstance(function, dict):
            arguments = function.get("arguments")

        # Validatie: minimaal een geldige toolnaam
        if not isinstance(tool_name, str) or not tool_name.strip():

            plan.append({
                "tool_name": None,
                "arguments": {},
                "status": "invalid",
                "error": f"Stap {index + 1} heeft geen geldige toolnaam.",
            })

            print(f"[PLANNER] ⚠️ Stap {index + 1} is ongeldig: geen geldige toolnaam.")

            continue

        if not isinstance(arguments, dict):
            arguments = {}

        plan.append({
            "tool_name": tool_name.strip(),
            "arguments": dict(arguments),
            "status": "pending",
        })

    return plan


def describe_plan(plan):

    """Debug-weergave van het Action Plan."""

    lines = [
        f"[PLANNER] Action plan gemaakt ({len(plan)} stap{'pen' if len(plan) != 1 else ''}):"
    ]

    for number, step in enumerate(plan, start=1):

        lines.append(f"[PLANNER] Step {number}: {step['tool_name']}")
        lines.append(f"[PLANNER] Arguments: {step['arguments']}")
        lines.append(f"[PLANNER] Status: {step['status']}")

    return "\n".join(lines)