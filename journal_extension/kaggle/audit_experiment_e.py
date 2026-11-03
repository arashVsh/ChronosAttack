"""Audit Experiment E raw calls. Generated from audit_experiment_b.py by replacing the protocol;
``rotation`` here is the wording index (letters are never remapped)."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

import experiment_e_protocol as protocol


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(events, model, phase="study", require_complete=True):
    expected = {job["id"]: job for job in protocol.jobs_for(model, phase)}
    fixtures = protocol.fixtures()
    identity = protocol.identity(model, phase)
    started, terminals, seen_calls, completed = set(), set(), set(), set()
    attempts = defaultdict(list)
    calls = defaultdict(dict)
    decisions = []
    cost, failures, job_errors, unknown = 0.0, 0, 0, 0

    for event in events:
        require(
            event.get("identity") == identity and event.get("model") == model,
            "Protocol/model mismatch",
        )
        kind = event.get("event")
        require(
            kind in ("job_started", "call_complete", "call_failed", "job_complete", "job_error"),
            "Unknown event",
        )
        job_id = event.get("job_id", (event.get("job") or {}).get("id"))
        require(job_id in expected, "Unexpected job")
        job = expected[job_id]
        fixture = fixtures[job["scenario"]]
        attempt = event.get("attempt")
        max_attempt = 1 if phase == "pilot" else 3
        require(type(attempt) is int and 1 <= attempt <= max_attempt, "Invalid attempt")
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

        require(
            key in started and key not in terminals and job_id not in completed,
            "Missing start or late event",
        )
        if kind in ("call_complete", "call_failed"):
            step = event.get("step")
            require(type(step) is int and 1 <= step <= 5, "Unexpected step")
            require((*key, step) not in seen_calls, "Duplicate call")
            require(step == len(calls[key]) + 1, "Nonsequential calls")
            require(
                not any(call["event"] == "call_failed" for call in calls[key].values()),
                "Call after failure",
            )
            seen_calls.add((*key, step))
            schema = protocol.engine.State if step < 5 else protocol.engine.Decision
            prompt = (
                protocol.tree.step_prompt(fixture, job["order"][step - 1], step)
                if step < 5
                else fixture["final_prompt"]
            )
            require(
                event.get("schema") == schema.__name__
                and event.get("user_prompt") == prompt,
                "Prompt/schema mismatch",
            )
            measured = protocol.engine.usage_cost(event["usage"])
            require(measured == event.get("cost_usd"), "Cost mismatch")
            if measured is None:
                unknown += 1
            else:
                require(math.isfinite(measured) and measured >= 0, "Invalid cost")
                cost += measured
            if kind == "call_complete":
                protocol.engine.validate_response(schema(**event["response"]), schema)
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

        require(
            len(calls[key]) == 5
            and all(call["event"] == "call_complete" for call in calls[key].values()),
            "Incomplete trial",
        )
        require(event.get("final") == calls[key][5]["response"], "Final mismatch")
        expected_states = [
            {
                "tool": tool,
                "step": step,
                "state": calls[key][step]["response"],
                "payload_sha256": fixture["hashes"][tool],
            }
            for step, tool in enumerate(job["order"], 1)
        ]
        require(event.get("states") == expected_states, "History mismatch")
        require(
            event.get("payload_hashes") == fixture["hashes"]
            and event.get("target") == fixture["target"],
            "Fixture/target mismatch",
        )
        require(
            event.get("schedule") == protocol.tree.schedule(fixture, job["order"]),
            "Schedule mismatch",
        )
        require(event.get("planned_calls") == 5, "Count mismatch")
        literal = event["final"]["final_choice"]
        rotation = fixture["rotation"]
        decisions.append(
            {
                "job_id": job_id,
                "rotation": rotation,
                "condition": job["condition"],
                "rep": job["rep"],
                "literal_choice": literal,
                "semantic_choice": protocol.semantic_choice(rotation, literal),
                "literal_target": fixture["target"],
                "semantic_target": protocol.SEMANTIC_TARGET,
            }
        )
        terminals.add(key)
        completed.add(job_id)

    missing = sorted(set(expected) - completed)
    if require_complete:
        require(not missing and not unknown, "Incomplete evidence or unknown costs")
        if phase == "pilot":
            require(
                not failures and not job_errors and len(seen_calls) == 10,
                "Pilot call failure or retry",
            )
    by_rotation_condition = {}
    for rotation in protocol.ROTATIONS:
        for condition in ("natural", "attack"):
            selected = [
                decision for decision in decisions
                if decision["rotation"] == rotation
                and decision["condition"] == condition
            ]
            by_rotation_condition[f"w{rotation}_{condition}"] = {
                "completed_jobs": len(selected),
                "literal_choices": dict(Counter(d["literal_choice"] for d in selected)),
                "semantic_choices": dict(Counter(d["semantic_choice"] for d in selected)),
            }
    return {
        **protocol.cell(model, phase),
        "classification": "exploratory_descriptive",
        "complete": not missing and not unknown,
        "pilot_passed": (
            phase == "pilot"
            and not missing
            and not unknown
            and not failures
            and not job_errors
            and len(seen_calls) == 10
            and len(started) == 2
        ),
        "completed_jobs": len(completed),
        "planned_jobs": len(expected),
        "missing_jobs": missing,
        "planned_calls": sum(job["calls"] for job in expected.values()),
        "complete_trial_calls": 5 * len(completed),
        "observed_invocations": len(seen_calls),
        "failed_calls": failures,
        "job_errors": job_errors,
        "known_cost_usd": cost,
        "unknown_cost_calls": unknown,
        "by_rotation_condition": by_rotation_condition,
        "decisions": sorted(decisions, key=lambda d: d["job_id"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--phase", choices=("pilot", "study"), default="study")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            audit(
                [json.loads(line) for line in args.path.read_text().splitlines()],
                args.model,
                phase=args.phase,
                require_complete=not args.allow_partial,
            ),
            indent=2,
        )
    )
