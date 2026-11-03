"""Audit Experiments D/F raw calls. Adapted from audit_experiment_e.py for the
three-tool engine: four calls per trial (three observations, final at step 4)."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

import experiment_df_protocol as protocol

STEPS = protocol.CALLS


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(events, model, phase="study", require_complete=True):
    expected = {job["id"]: job for job in protocol.jobs_for(model, phase)}
    fixtures = protocol.fixtures()
    identity = protocol.identity(model, phase)
    engine = protocol.engine
    started, terminals, seen_calls, completed = set(), set(), set(), set()
    attempts = defaultdict(list)
    calls = defaultdict(dict)
    decisions = []
    cost, failures, job_errors, unknown = 0.0, 0, 0, 0

    for event in events:
        require(event.get("identity") == identity and event.get("model") == model, "Protocol/model mismatch")
        kind = event.get("event")
        require(kind in ("job_started", "call_complete", "call_failed", "job_complete", "job_error"),
                "Unknown event")
        job_id = event.get("job_id", (event.get("job") or {}).get("id"))
        require(job_id in expected, "Unexpected job")
        job = expected[job_id]
        fixture = fixtures[job["scenario"]]
        attempt = event.get("attempt")
        require(type(attempt) is int and 1 <= attempt <= 3, "Invalid attempt")
        execution = event.get("execution_id")
        require(isinstance(execution, str) and execution, "Missing execution")
        key = (execution, job_id, attempt)

        if kind == "job_started":
            require(job_id not in completed and key not in started, "Duplicate start")
            require(attempt == len(attempts[job_id]) + 1, "Nonsequential attempt")
            if attempt > 1:
                require(attempts[job_id][-1] in terminals, "Unfinished prior attempt")
            started.add(key)
            attempts[job_id].append(key)
            continue

        require(key in started and key not in terminals and job_id not in completed, "Missing start or late event")
        if kind in ("call_complete", "call_failed"):
            step = event.get("step")
            require(type(step) is int and 1 <= step <= STEPS, "Unexpected step")
            require((*key, step) not in seen_calls, "Duplicate call")
            require(step == len(calls[key]) + 1, "Nonsequential calls")
            require(not any(call["event"] == "call_failed" for call in calls[key].values()), "Call after failure")
            seen_calls.add((*key, step))
            schema = engine.State if step < STEPS else engine.Decision
            prompt = (engine.step_prompt(fixture, job["order"][step - 1], step)
                      if step < STEPS else fixture["final_prompt"])
            require(event.get("schema") == schema.__name__ and event.get("user_prompt") == prompt,
                    "Prompt/schema mismatch")
            measured = engine.usage_cost(event["usage"])
            require(measured == event.get("cost_usd"), "Cost mismatch")
            if measured is None:
                unknown += 1
            else:
                require(math.isfinite(measured) and measured >= 0, "Invalid cost")
                cost += measured
            if kind == "call_complete":
                engine.validate_response(schema(**event["response"]), schema)
            else:
                require(bool(event.get("error_type")), "Missing failed-call error")
                failures += 1
            calls[key][step] = event
            continue

        require(event.get("job") == job, "Changed trial")
        if kind == "job_error":
            require(bool(event.get("error_type")), "Missing job error")
            terminals.add(key)
            job_errors += 1
            continue

        require(len(calls[key]) == STEPS and all(c["event"] == "call_complete" for c in calls[key].values()),
                "Incomplete trial")
        require(event.get("final") == calls[key][STEPS]["response"], "Final mismatch")
        expected_states = [{"tool": tool, "step": step, "state": calls[key][step]["response"],
                            "payload_sha256": fixture["hashes"][tool]}
                           for step, tool in enumerate(job["order"], 1)]
        require(event.get("states") == expected_states, "History mismatch")
        require(event.get("payload_hashes") == fixture["hashes"] and event.get("target") == fixture["target"],
                "Fixture/target mismatch")
        require(event.get("schedule") == engine.schedule(fixture, job["order"]), "Schedule mismatch")
        require(event.get("planned_calls") == STEPS, "Count mismatch")
        decisions.append({"job_id": job_id, "scenario": job["scenario"], "condition": job["condition"],
                          "rep": job["rep"], "order": job["order"],
                          "order_role": protocol.order_role(fixture, job["order"]),
                          "choice": event["final"]["final_choice"], "target": fixture["target"],
                          "states": [s["state"]["current_choice"] for s in expected_states]})
        terminals.add(key)
        completed.add(job_id)

    missing = sorted(set(expected) - completed)
    if require_complete:
        require(not missing and not unknown, "Incomplete evidence or unknown costs")
    by_scenario_order = {}
    for scenario in fixtures:
        for index in range(6):
            selected = [d for d in decisions if d["scenario"] == scenario and d["condition"] == str(index)]
            by_scenario_order[f"{scenario}|{index}"] = {"completed_jobs": len(selected),
                                                        "choices": dict(Counter(d["choice"] for d in selected))}
    return {
        **protocol.cell(model, phase),
        "classification": "exploratory_descriptive",
        "complete": not missing and not unknown,
        "completed_jobs": len(completed),
        "planned_jobs": len(expected),
        "missing_jobs": missing,
        "planned_calls": sum(job["calls"] for job in expected.values()),
        "complete_trial_calls": STEPS * len(completed),
        "observed_invocations": len(seen_calls),
        "failed_calls": failures,
        "job_errors": job_errors,
        "known_cost_usd": cost,
        "unknown_cost_calls": unknown,
        "by_scenario_order": by_scenario_order,
        "decisions": sorted(decisions, key=lambda d: d["job_id"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit([json.loads(line) for line in args.path.read_text().splitlines()],
                           args.model, require_complete=not args.allow_partial), indent=2))
