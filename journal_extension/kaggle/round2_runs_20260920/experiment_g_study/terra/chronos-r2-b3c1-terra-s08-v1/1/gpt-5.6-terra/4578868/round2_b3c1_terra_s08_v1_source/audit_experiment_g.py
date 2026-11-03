"""Audit Experiment G raw calls: B3/C1 on the three-tool engine. Stateful and budget trials
make four calls (three observations, final at step 4); stateless, control, barrier and
consistency trials make one joint call. Adapted from audit_experiment_df.py."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

import experiment_g_protocol as protocol

SEQUENTIAL = ("stateful", "budget")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_prompt(fixture, job, step):
    engine = protocol.engine
    if step < job["calls"]:
        return engine.step_prompt(fixture, job["order"][step - 1], step)
    return fixture["final_prompt"] if job["mode"] in SEQUENTIAL else engine.joint_prompt(fixture, job)


def audit(events, model, phase="study", require_complete=True):
    expected = {job["id"]: job for job in protocol.jobs_for(model, phase)}
    fixtures = protocol.fixtures()
    identity = protocol.identity(model, phase)
    engine = protocol.engine
    started, terminals, seen_calls, completed = set(), set(), set(), set()
    attempts = defaultdict(list)
    calls = defaultdict(dict)
    trials = []
    cost, failures, job_errors, unknown = 0.0, 0, 0, 0

    for event in events:
        require(event.get("identity") == identity and event.get("model") == model, "Protocol/model mismatch")
        kind = event.get("event")
        require(kind in ("job_started", "call_complete", "call_failed", "job_complete", "job_error"), "Unknown event")
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
            require(type(step) is int and 1 <= step <= job["calls"], "Unexpected step")
            require((*key, step) not in seen_calls, "Duplicate call")
            require(step == len(calls[key]) + 1, "Nonsequential calls")
            require(not any(call["event"] == "call_failed" for call in calls[key].values()), "Call after failure")
            seen_calls.add((*key, step))
            schema = engine.State if step < job["calls"] else engine.Decision
            require(event.get("schema") == schema.__name__ and event.get("user_prompt") == expected_prompt(fixture, job, step),
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

        n = job["calls"]
        require(len(calls[key]) == n and all(c["event"] == "call_complete" for c in calls[key].values()), "Incomplete trial")
        require(event.get("final") == calls[key][n]["response"], "Final mismatch")
        states = [{"tool": tool, "step": step, "state": calls[key][step]["response"],
                   "payload_sha256": fixture["hashes"][tool]}
                  for step, tool in enumerate(job["order"], 1)] if job["mode"] in SEQUENTIAL else []
        require(event.get("states") == states, "History mismatch")
        require(event.get("payload_hashes") == fixture["hashes"] and event.get("target") == fixture["target"],
                "Fixture/target mismatch")
        require(event.get("schedule") == (engine.schedule(fixture, job["order"]) if job["mode"] in SEQUENTIAL else []),
                "Schedule mismatch")
        require(event.get("planned_calls") == n, "Count mismatch")
        # Row shape of audit_completion_evidence.py, so analyze_completion_study.py applies unchanged.
        trials.append({"model": model, "scenario": job["scenario"], "mode": job["mode"],
                       "condition": job["condition"], "rep": job["rep"], "calls": n,
                       "final": event["final"], "job_id": job_id})
        terminals.add(key)
        completed.add(job_id)

    missing = sorted(set(expected) - completed)
    if require_complete:
        require(not missing and not unknown, "Incomplete evidence or unknown costs")
    return {
        **protocol.cell(model, phase),
        "complete": not missing and not unknown,
        "completed_jobs": len(completed),
        "planned_jobs": len(expected),
        "missing_jobs": missing,
        "planned_calls": sum(job["calls"] for job in expected.values()),
        "complete_trial_calls": sum(t["calls"] for t in trials),
        "observed_invocations": len(seen_calls),
        "failed_calls": failures,
        "job_errors": job_errors,
        "known_cost_usd": cost,
        "unknown_cost_calls": unknown,
        "completed_by_cell": dict(Counter(f"{t['scenario']}|{t['mode']}|{t['condition']}" for t in trials)),
        "trials": sorted(trials, key=lambda t: t["job_id"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit([json.loads(line) for line in args.path.read_text().splitlines()],
                           args.model, require_complete=not args.allow_partial), indent=2))
