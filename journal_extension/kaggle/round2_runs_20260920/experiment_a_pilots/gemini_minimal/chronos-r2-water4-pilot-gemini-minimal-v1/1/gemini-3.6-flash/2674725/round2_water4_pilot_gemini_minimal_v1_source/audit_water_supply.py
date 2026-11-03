"""Strict structural audit for frozen water-supply experiment-A evidence."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import water_supply_protocol as protocol


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(events, model, phase, require_complete=True):
    jobs = {job["id"]: job for job in protocol.jobs_for(model, phase)}
    fixtures = protocol.fixtures()
    identity = protocol.engine.digest(
        json.dumps(
            dict(
                study=protocol.engine.STUDY_ID,
                model=model,
                fixtures=fixtures,
                settings=protocol.engine.CALL_SETTINGS,
            ),
            sort_keys=True,
        )
    )
    started, seen_calls, completed = set(), set(), set()
    calls = defaultdict(dict)
    cost, failed, unknown = 0.0, 0, 0
    for event in events:
        require(
            event.get("identity") == identity and event.get("model") == model,
            "Protocol/model mismatch",
        )
        kind = event["event"]
        require(
            kind
            in ("job_started", "call_complete", "call_failed", "job_complete", "job_error"),
            "Unknown event",
        )
        job_id = event.get("job_id", (event.get("job") or {}).get("id"))
        require(job_id in jobs, "Unexpected job")
        job, fixture = jobs[job_id], fixtures["water4"]
        attempt = event["attempt"]
        require(type(attempt) is int and 1 <= attempt <= 3, "Invalid attempt")
        key = (event["execution_id"], job_id, attempt)
        require(bool(key[0]), "Missing execution")
        if kind == "job_started":
            require(key not in started and job_id not in completed, "Duplicate start")
            started.add(key)
            continue
        require(key in started, "Missing start")
        if kind in ("call_complete", "call_failed"):
            step = event["step"]
            require(type(step) is int and 1 <= step <= job["calls"], "Unexpected step")
            require((*key, step) not in seen_calls, "Duplicate call")
            seen_calls.add((*key, step))
            require(step == len(calls[key]) + 1, "Nonsequential calls")
            schema = (
                protocol.engine.State
                if job["calls"] == 5 and step < 5
                else protocol.engine.Decision
            )
            prompt = (
                protocol.step_prompt(fixture, job["order"][step - 1], step)
                if schema is protocol.engine.State
                else fixture["final_prompt"]
                if job["calls"] == 5
                else protocol.joint_prompt(fixture, job)
            )
            require(
                event["schema"] == schema.__name__ and event["user_prompt"] == prompt,
                "Prompt/schema mismatch",
            )
            calculated = protocol.engine.usage_cost(event["usage"])
            require(calculated == event["cost_usd"], "Cost mismatch")
            if calculated is None:
                unknown += 1
            else:
                require(math.isfinite(calculated) and calculated >= 0, "Invalid cost")
                cost += calculated
            if kind == "call_complete":
                protocol.engine.validate_response(schema(**event["response"]), schema)
            else:
                failed += 1
            calls[key][step] = event
        elif kind == "job_complete":
            require(job_id not in completed and event["job"] == job, "Duplicate/changed trial")
            require(
                len(calls[key]) == job["calls"]
                and all(call["event"] == "call_complete" for call in calls[key].values()),
                "Incomplete trial",
            )
            require(event["final"] == calls[key][job["calls"]]["response"], "Final mismatch")
            expected_states = (
                [
                    dict(
                        tool=tool,
                        step=index,
                        state=calls[key][index]["response"],
                        payload_sha256=fixture["hashes"][tool],
                    )
                    for index, tool in enumerate(job["order"], 1)
                ]
                if job["calls"] == 5
                else []
            )
            require(event["states"] == expected_states, "History mismatch")
            require(
                event["payload_hashes"] == fixture["hashes"]
                and event["target"] == fixture["target"],
                "Fixture mismatch",
            )
            require(
                event["schedule"]
                == (protocol.schedule(fixture, job["order"]) if job["calls"] == 5 else []),
                "Schedule mismatch",
            )
            require(event["planned_calls"] == job["calls"], "Count mismatch")
            completed.add(job_id)
        else:
            require(event["job"] == job, "Changed failed trial")
    missing = sorted(set(jobs) - completed)
    if require_complete:
        require(not missing and not unknown, "Incomplete evidence or unknown costs")
    return dict(
        model=model,
        phase=phase,
        complete=not missing and not unknown,
        completed_jobs=len(completed),
        missing_jobs=missing,
        attempted_calls=len(seen_calls),
        failed_calls=failed,
        complete_trial_calls=sum(jobs[job_id]["calls"] for job_id in completed),
        known_cost_usd=cost,
        unknown_cost_calls=unknown,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--phase", required=True, choices=("pilot", "study"))
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            audit(
                [json.loads(line) for line in args.path.read_text().splitlines()],
                args.model,
                args.phase,
                not args.allow_partial,
            ),
            indent=2,
        )
    )
