"""
Executor (Fase 8, stap 2 + dependencies + wait/conditions + retry/risk + parallel)

De Executor voert een Action Plan uit dat door de Planner is gemaakt.

Architectuurregel:
    Planner   : "Wat moet er gebeuren?"
    Executor  : "Voer het plan uit."
    Actions   : "Hoe voer ik de actie uit?"

De Executor implementeert zelf GEEN Windows-acties. Hij gebruikt de
bestaande execute_tool() uit core/ai.py (late import om circulaire
imports te voorkomen) en houdt per stap de status bij:

    pending -> running -> done
                       -> failed
                       -> skipped (ongeldig, dependency niet geslaagd
                          of voorwaarde niet gehaald)
                       -> approval_required (risk level medium/high)

Dependencies (Fase 8):
    Een stap mag optioneel "depends_on" bevatten: een lijst met
    stapnummers (1-based) van EERDERE stappen in hetzelfde plan.
    Een afhankelijke stap wordt alleen uitgevoerd als alle benodigde
    stappen de status "done" hebben; anders wordt hij overgeslagen.

Wait (Fase 8, stap 5):
    - Losse wacht-stap: {"tool_name": "wait", "arguments": {"seconds": 2}}
    - Of op een actie-stap: "wait_seconds": 2 (wacht vóór de actie)
    De wachttijd is begrensd op MAX_WAIT_SECONDS seconden.

Conditions (Fase 8, stap 5):
    Een stap mag optioneel "condition" bevatten. De stap wordt alleen
    uitgevoerd als de voorwaarde klopt; anders -> skipped met reden:

        "condition": {
            "step": 1,                    # eerdere stap om te checken
            "status_is": "done",          # optioneel: verwachte status
            "result_contains": "tekst",   # optioneel: tekst in resultaat
        }

Retry (Fase 8, stap 6):
    Een mislukte actie wordt via core/retry.py maximaal
    DEFAULT_MAX_RETRIES keer opnieuw geprobeerd; per stap te
    overschrijven met optioneel "max_retries".

Risk levels & approvals (Fase 8, stap 6):
    Optioneel "risk" per stap. "low" wordt automatisch uitgevoerd;
    "medium"/"high" krijgen status "approval_required" en worden
    niet automatisch uitgevoerd. Echte gebruikersbevestiging kan
    later op dit punt worden toegevoegd.

Parallel execution (Fase 8, stap 7):
    Onafhankelijke acties (geen dependencies, low risk, geen wait)
    worden binnen een "wave" parallel uitgevoerd via de Python-
    standaardbibliotheek (concurrent.futures). Threads schrijven
    alleen in hun eigen record; gedeelde status/resultaten worden
    alleen door de hoofdraad bijgewerkt en zijn daarmee thread-safe.
    Eén fout in een parallelle actie raakt de andere acties niet.
"""
import time

import concurrent.futures

from core.retry import execute_with_retry, DEFAULT_MAX_RETRIES

from core.result_validation import classify_tool_result


# =============================================================
# Actie-journaal (Fase 4, "bewaar dit als routine")
#
# De Executor is het enige knooppunt waardoor elke gestructureerde
# tool-uitvoering gaat (Agent-plannen, routines én LLM-toolcalls).
# Hier houden we de laatst geslaagde acties bij, zodat de gebruiker
# ze kan opslaan als routine ("JARVIS, bewaar dit als routine X").
# =============================================================

_LAST_DONE_ACTIONS = []
_LAST_EXECUTION_TS = 0.0


def record_done_actions(records):
    """Bewaart de geslaagde acties van de laatst uitgevoerde plannen."""
    global _LAST_DONE_ACTIONS, _LAST_EXECUTION_TS

    actions = []
    for r in records or []:
        tool = r.get("used_tool_name") or r.get("tool_name")
        if not tool or r.get("status") != "done":
            continue
        actions.append({
            "tool_name": tool,
            "arguments": dict(r.get("arguments") or {}),
        })

    if not actions:
        return

    _LAST_DONE_ACTIONS = actions
    _LAST_EXECUTION_TS = time.time()


def get_last_done_actions():
    """Geeft de laatst geslaagde acties (tool + argumenten) terug."""
    return list(_LAST_DONE_ACTIONS)
MAX_WAIT_SECONDS = 60

# Risk levels (Fase 8, stap 6):
RISK_LEVELS = ("low", "medium", "high")
DEFAULT_RISK = "low"
APPROVAL_REQUIRED_RISKS = ("medium", "high")


def _evaluate_condition(condition, records_by_number):

    """
    Beoordeelt een simpele voorwaarde tegen een eerdere stap.

    Geeft terug: (ok, reden) — reden is leeg als ok True is.
    """

    if not isinstance(condition, dict):
        return False, "ongeldige conditie"

    ref = condition.get("step")

    target = records_by_number.get(ref)

    if not isinstance(target, dict):
        return False, f"conditie verwijst naar niet-bestaande stap {ref}"

    expected_status = condition.get("status_is")

    if expected_status and target.get("status") != expected_status:
        return False, f"stap {ref} heeft status '{target.get('status')}' i.p.v. '{expected_status}'"

    needle = condition.get("result_contains")

    if needle is not None and str(needle) not in str(target.get("result", "")):
        return False, f"resultaat van stap {ref} bevat '{needle}' niet"

    return True, ""


def _new_record(step):

    """Maakt het basis-record voor één stap (parse + defaults)."""

    tool_name = step.get("tool_name")
    arguments = step.get("arguments") or {}

    # Risk level: onbekende waarden zijn fail-safe en vragen om
    # goedkeuring ("high")
    risk = str(step.get("risk") or DEFAULT_RISK).lower()

    if risk not in RISK_LEVELS:
        risk = "high"

    return {
        "tool_name": tool_name,
        "used_tool_name": tool_name,
        "arguments": arguments,
        "risk": risk,
        "status": step.get("status", "pending"),
        "result": "",
        "verdict": None,
        "attempts": 0,
        "errors": [],
        "results": [],
        "needs_approval": False,
    }


def _mark_skipped(number, step, record, result_text):

    record["result"] = result_text
    record["status"] = "skipped"
    step["status"] = "skipped"

    print(f"[EXECUTOR] Status: skipped")

    return record


def _gate_check(number, step, record, statuses_by_number, records_by_number):

    """
    Goedkope checks vóór uitvoering (invalid / dependency /
    condition / risk). Geeft True als de stap mag uitvoeren;
    anders is de stap al definitief afgehandeld in record.
    """

    status = record["status"]

    if status == "invalid":

        _mark_skipped(number, step, record, f"Overgeslagen: {step.get('error') or 'ongeldige stap.'}")
        return False

    if status != "pending":

        _mark_skipped(number, step, record, f"Overgeslagen: onverwachte status '{status}'.")
        return False

    depends_on = step.get("depends_on")

    if depends_on:

        problem = None

        for dep_number in depends_on:

            # Dependencies verwijzen altijd naar EERDERE stappen;
            # een latere stap is net zo min geldig als een die niet bestaat
            if dep_number >= number or dep_number < 1:
                problem = f"dependency stap {dep_number} bestaat niet of komt later in het plan"
                break

            dep_status = statuses_by_number.get(dep_number)

            if dep_status is None:
                problem = f"dependency stap {dep_number} bestaat niet of komt later in het plan"
                break

            if dep_status != "done":
                problem = f"dependency stap {dep_number} is '{dep_status}' i.p.v. 'done'"
                break

        if problem:

            _mark_skipped(number, step, record, f"Overgeslagen: {problem}.")
            return False

    condition = step.get("condition")

    if condition:

        condition_ok, condition_reason = _evaluate_condition(condition, records_by_number)

        if not condition_ok:

            _mark_skipped(
                number, step, record,
                f"Overgeslagen: voorwaarde niet gehaald ({condition_reason})."
            )
            return False

    # Risk levels & approvals (stap 6): echte gebruikersbevestiging
    # kan hier later worden toegevoegd (dan status alsnog naar
    # "pending" zetten en de stap opnieuw uitvoeren).
    if record["risk"] in APPROVAL_REQUIRED_RISKS:

        record["result"] = (
            f"Wacht op goedkeuring: risk level '{record['risk']}' wordt niet "
            f"automatisch uitgevoerd."
        )
        record["status"] = "approval_required"
        record["needs_approval"] = True
        step["status"] = "approval_required"

        print(f"[EXECUTOR] Status: approval_required (risk={record['risk']})")
        print(f"[EXECUTOR] Result: {record['result']}")

        return False

    return True


def _is_standalone_wait(step):

    """Losse wait-stap -> altijd sequentieel en voert geen tool uit."""

    return step.get("tool_name") == "wait"


def _has_pre_wait(step):

    """Actie-stap met wachttijd vóór de actie -> sequentieel."""

    wait_seconds = step.get("wait_seconds")

    try:
        return bool(wait_seconds) and float(wait_seconds) > 0
    except (TypeError, ValueError):
        return False


def _run_wait_step(number, total, step, record):

    """Voert een losse wait-stap sequentieel uit."""

    raw_seconds = record["arguments"].get("seconds", step.get("wait_seconds", 0))

    try:
        wait_time = max(0.0, min(float(raw_seconds), MAX_WAIT_SECONDS))
    except (TypeError, ValueError):
        wait_time = 0.0

    print(f"[EXECUTOR] Wacht {wait_time} seconde(n)...")

    time.sleep(wait_time)

    record["result"] = f"{wait_time} seconde(n) gewacht."
    record["status"] = "done"
    step["status"] = "done"

    print(f"[EXECUTOR] Result: {record['result']}")
    print(f"[EXECUTOR] Status: done")

    return record


def _run_action(number, total, step, record, execute_tool, correct_opposite_tool, question):

    """
    Voert één uitvoerbare stap uit (met retry).

    Thread-safe: schrijft alleen in het eigen record, nooit in
    gedeelde status/resultaat-structuren.
    """

    try:

        # AI koos soms het tegenovergestelde van wat de gebruiker wil
        corrected = correct_opposite_tool(record["tool_name"], question)

        if corrected:
            print(f"[EXECUTOR] ⚠️ AI koos {record['tool_name']}, maar gebruiker wil het tegenovergestelde. Gebruik {corrected}.")
            record["used_tool_name"] = corrected
        else:
            record["used_tool_name"] = record["tool_name"]

        step["status"] = "running"

        print(f"[EXECUTOR] Arguments: {record['arguments']}")

        wait_seconds = step.get("wait_seconds")

        if wait_seconds:

            try:
                pre_wait = max(0.0, min(float(wait_seconds), MAX_WAIT_SECONDS))
            except (TypeError, ValueError):
                pre_wait = 0.0

            if pre_wait > 0:
                print(f"[EXECUTOR] Wacht {pre_wait} seconde(n) voor {record['tool_name']}...")
                time.sleep(pre_wait)

        retry_result = execute_with_retry(
            execute_tool,
            record["used_tool_name"],
            record["arguments"],
            question,
            max_retries=step.get("max_retries", DEFAULT_MAX_RETRIES),
        )

        record["result"] = retry_result["result"]
        record["status"] = retry_result["status"]
        record["attempts"] = retry_result["attempts"]
        record["errors"] = retry_result["errors"]
        record["results"] = retry_result["results"]

        # Fase 12: markeer als een fallback-tool gebruikt is, zodat de
        # Agent-herplanning dit kan meenemen in zijn volgende keuze.
        if retry_result.get("fallback_used"):
            record["fallback_used"] = retry_result["fallback_used"]
            print(f"[EXECUTOR] ⚠️ Fallback gebruikt: {retry_result['fallback_used']}")

    except Exception as error:

        # Fallback: één fout mag de stap (en parallelle buren) niet laten crashen
        record["result"] = f"Fout bij uitvoeren van {record['tool_name']}: {error}"
        record["status"] = "failed"

    # =====================================================
    # RESULTAATVALIDATIE (Fase 9, stap 4): een "done"-resultaat
    # dat aantoonbaar een fout meldt, wordt alsnog "failed".
    # Onzekere resultaten blijven "done" maar krijgen verdict
    # "uncertain" zodat JARVIS niet blind "succes" claimt.
    # =====================================================

    if record["status"] == "done":

        verdict = classify_tool_result(record["result"])

        record["verdict"] = verdict

        if verdict == "failed":

            record["status"] = "failed"
            record["errors"].append(str(record["result"]))

            print(f"[EXECUTOR] Resultaatvalidatie: aangetoonde mislukking -> failed")

    elif record["status"] == "failed":
        record["verdict"] = "failed"

    step["status"] = record["status"]

    print(f"[EXECUTOR] Result: {record['result']}")
    print(f"[EXECUTOR] Status: {record['status']}")

    return record


def execute_action_plan(action_plan, question):

    """
    Voert alle stappen uit het Action Plan uit.

    Scheduling gebeurt in "waves": een stap is klaar om te draaien
    zodra al zijn dependencies verwerkt zijn. Onafhankelijke acties
    binnen dezelfde wave worden parallel uitgevoerd (stap 7);
    waits, approvals en dependency-gebonden stappen lopen sequentieel.

    Geeft per stap een dict terug (zie module-docstring), in
    planvolgorde zodat het bestaande Ollama/tool-message protocol
    intact blijft.
    """

    # Late import: voorkomt circulaire import (ai.py importeert executor.py)
    from core.ai import execute_tool, correct_opposite_tool

    steps = [step for step in action_plan if isinstance(step, dict)]

    total = len(steps)

    print(f"[EXECUTOR] Starting action plan: {total} step{'s' if total != 1 else ''}")

    statuses_by_number = {}   # stapnummer -> eindstatus, voor dependency-checks
    records_by_number = {}    # stapnummer -> volledig record, voor conditions

    def finish(number, record):

        # Alleen de hoofdraad schrijft gedeelde state (thread-safe).
        # De uiteindelijke resultatenlijst wordt aan het einde in
        # planvolgorde opgebouwd.
        statuses_by_number[number] = record["status"]
        records_by_number[number] = record

    def waiting_for(number):

        """
        Alle stapnummers waar deze stap op moet wachten: expliciete
        dependencies PLUS de stap waar een eventuele condition naar
        verwijst (die moet eerst een resultaat hebben).
        """

        step = steps[number - 1]

        waiting = set(step.get("depends_on") or [])

        condition = step.get("condition")

        if isinstance(condition, dict) and condition.get("step") is not None:
            waiting.add(condition.get("step"))

        return waiting

    pending_numbers = set(range(1, total + 1))

    while pending_numbers:

        ready = []          # alles waarop gewacht wordt is al verwerkt
        unreachable = []    # er wordt gewacht op iets dat niet bestaat

        for number in sorted(pending_numbers):

            deps = waiting_for(number)

            if all(dep in statuses_by_number for dep in deps):
                ready.append(number)

            elif any(dep not in statuses_by_number and dep not in pending_numbers for dep in deps):
                unreachable.append(number)

        if not ready and not unreachable:

            # Alleen nog onderling afhankelijke stappen over
            # (cyclische dependencies) -> niets kan ooit uitvoeren
            for number in sorted(pending_numbers):

                step = steps[number - 1]
                record = _new_record(step)

                print(f"[EXECUTOR] Step {number}/{total}")
                print(f"[EXECUTOR] Tool: {record['tool_name']}")

                _mark_skipped(
                    number, step, record,
                    "Overgeslagen: dependency-kring (cycle) kan nooit uitgevoerd worden."
                )

                finish(number, record)

            pending_numbers.clear()
            continue

        handled = []

        # Stappen met niet-bestaande dependencies: overgeslagen
        for number in unreachable:

            step = steps[number - 1]
            record = _new_record(step)

            print(f"[EXECUTOR] Step {number}/{total}")
            print(f"[EXECUTOR] Tool: {record['tool_name']}")

            missing = [
                dep for dep in (step.get("depends_on") or [])
                if dep not in statuses_by_number and dep not in pending_numbers
            ]

            _mark_skipped(
                number, step, record,
                f"Overgeslagen: dependency stap {missing[0]} bestaat niet of komt later in het plan."
            )

            finish(number, record)
            handled.append(number)

        # Gates voor de ready-stappen
        runnable = []          # mag parallel uitgevoerd worden
        sequential = []        # losse wait-stappen: sequentieel
        sequential_actions = []  # acties met wachttijd: sequentieel

        for number in ready:

            step = steps[number - 1]
            record = _new_record(step)

            print(f"[EXECUTOR] Step {number}/{total}")
            print(f"[EXECUTOR] Tool: {record['tool_name']}")

            if not _gate_check(number, step, record, statuses_by_number, records_by_number):
                finish(number, record)
                handled.append(number)
                continue

            if _is_standalone_wait(step):
                sequential.append((number, record))
            elif _has_pre_wait(step):
                sequential_actions.append((number, record))
            else:
                runnable.append((number, record))

        # =====================================================
        # PARALLEL (Fase 8, stap 7): meerdere onafhankelijke,
        # goedgekeurde acties draaien tegelijk. Threads werken
        # elk in hun eigen record; finish() doet alle gedeelde
        # updates achteraf in de hoofdraad.
        # =====================================================

        if len(runnable) > 1:

            print(f"[EXECUTOR] Voert {len(runnable)} onafhankelijke actie(s) parallel uit...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(runnable)) as pool:

                future_map = {
                    pool.submit(
                        _run_action,
                        number,
                        total,
                        steps[number - 1],
                        record,
                        execute_tool,
                        correct_opposite_tool,
                        question,
                    ): (number, record)
                    for number, record in runnable
                }

                for future, (number, record) in future_map.items():

                    try:
                        record = future.result()

                    except Exception as error:

                        # Defensief: mocht een thread zelf crashen,
                        # dan alleen die stap failed
                        record["result"] = (
                            f"Fout bij parallelle uitvoering van {record['tool_name']}: {error}"
                        )
                        record["status"] = "failed"
                        steps[number - 1]["status"] = "failed"

                    finish(number, record)
                    handled.append(number)

        else:

            for number, record in runnable:

                finished = _run_action(
                    number, total, steps[number - 1], record,
                    execute_tool, correct_opposite_tool, question
                )

                finish(number, finished)
                handled.append(number)

        # Waits altijd sequentieel (ook als er parallel gedraaid is)
        for number, record in sequential:

            finished = _run_wait_step(number, total, steps[number - 1], record)

            finish(number, finished)
            handled.append(number)

        # Acties met wachttijd ook sequentieel (wacht vóór de actie)
        for number, record in sequential_actions:

            finished = _run_action(
                number, total, steps[number - 1], record,
                execute_tool, correct_opposite_tool, question
            )

            finish(number, finished)
            handled.append(number)

        pending_numbers.difference_update(handled)

    # =========================================================
    # SAMENVATTING (Fase 8, stap 3)
    # =========================================================

    # Resultaten altijd in planvolgorde (ook bij parallelle uitvoering)
    executed = [records_by_number[number] for number in sorted(records_by_number)]

    # Fase 4: onthoud de geslaagde acties voor "bewaar dit als routine".
    record_done_actions(executed)

    done_count = sum(1 for item in executed if item["status"] == "done")
    failed_count = sum(1 for item in executed if item["status"] == "failed")
    skipped_count = sum(1 for item in executed if item["status"] == "skipped")
    approval_count = sum(1 for item in executed if item["status"] == "approval_required")

    print("[EXECUTOR] Action plan finished")
    print(
        f"[EXECUTOR] Samenvatting: {total} actie(s) | "
        f"geslaagd: {done_count} | mislukt: {failed_count} | "
        f"overgeslagen: {skipped_count} | wacht op goedkeuring: {approval_count}"
    )

    return executed