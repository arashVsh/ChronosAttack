"""Reject incomplete or inconsistent four-tool evidence before analysis.

Checks log consistency, not independent proof of a provider's execution.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import four_observation_protocol as p


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(events, model, phase, require_complete=True):
    jobs = {j["id"]: j for j in p.jobs_for(model, phase)}
    fs = p.fixtures()
    identity = p.engine.digest(json.dumps(dict(study=p.engine.STUDY_ID, model=model,
                                               fixtures=fs, settings=p.engine.CALL_SETTINGS), sort_keys=True))
    started, seen_calls, completed = set(), set(), set()
    calls = defaultdict(dict)
    cost, failed, unknown = 0.0, 0, 0
    for event in events:
        require(event.get("identity") == identity and event.get("model") == model, "Protocol/model mismatch")
        kind = event["event"]
        require(kind in ("job_started", "call_complete", "call_failed", "job_complete", "job_error"), "Unknown event")
        jid = event.get("job_id", event.get("job", {}).get("id"))
        require(jid in jobs, "Unexpected job")
        job, f = jobs[jid], fs["tree4"]
        attempt = event["attempt"]
        require(type(attempt) is int and 1 <= attempt <= 3, "Invalid attempt")
        key = (event["execution_id"], jid, attempt)
        require(bool(key[0]), "Missing execution")
        if kind == "job_started":
            require(key not in started and jid not in completed, "Duplicate start")
            started.add(key)
            continue
        require(key in started, "Missing start")
        if kind in ("call_complete", "call_failed"):
            step = event["step"]
            require(type(step) is int and 1 <= step <= job["calls"], "Unexpected step")
            require((*key, step) not in seen_calls, "Duplicate call")
            seen_calls.add((*key, step))
            require(step == len(calls[key]) + 1, "Nonsequential calls")
            schema = p.engine.State if job["calls"] == 5 and step < 5 else p.engine.Decision
            prompt = (p.step_prompt(f, job["order"][step-1], step) if schema is p.engine.State
                      else f["final_prompt"] if job["calls"] == 5 else p.joint_prompt(f, job))
            require(event["schema"] == schema.__name__ and event["user_prompt"] == prompt, "Prompt/schema mismatch")
            calculated = p.engine.usage_cost(event["usage"])
            require(calculated == event["cost_usd"], "Cost mismatch")
            if calculated is None:
                unknown += 1
            else:
                require(math.isfinite(calculated) and calculated >= 0, "Invalid cost")
                cost += calculated
            if kind == "call_complete":
                p.engine.validate_response(schema(**event["response"]), schema)
            else:
                failed += 1
            calls[key][step] = event
        elif kind == "job_complete":
            require(jid not in completed and event["job"] == job, "Duplicate/changed trial")
            require(len(calls[key]) == job["calls"] and
                    all(c["event"] == "call_complete" for c in calls[key].values()), "Incomplete trial")
            require(event["final"] == calls[key][job["calls"]]["response"], "Final mismatch")
            expected_states = [dict(tool=t, step=i, state=calls[key][i]["response"],
                                    payload_sha256=f["hashes"][t])
                               for i, t in enumerate(job["order"], 1)] if job["calls"] == 5 else []
            require(event["states"] == expected_states, "History mismatch")
            require(event["payload_hashes"] == f["hashes"] and event["target"] == f["target"], "Fixture mismatch")
            require(event["schedule"] == (p.schedule(f, job["order"]) if job["calls"] == 5 else []), "Schedule mismatch")
            require(event["planned_calls"] == job["calls"], "Count mismatch")
            completed.add(jid)
        else:
            require(event["job"] == job, "Changed failed trial")
    missing = sorted(set(jobs) - completed)
    if require_complete:
        require(not missing and not unknown, "Incomplete evidence or unknown costs")
    return dict(model=model, phase=phase, complete=not missing and not unknown,
                completed_jobs=len(completed), missing_jobs=missing,
                attempted_calls=len(seen_calls), failed_calls=failed,
                complete_trial_calls=sum(jobs[j]["calls"] for j in completed),
                known_cost_usd=cost, unknown_cost_calls=unknown)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True, choices=p.engine.MODELS)
    parser.add_argument("--phase", required=True, choices=("pilot", "study"))
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit([json.loads(x) for x in args.path.read_text().splitlines()],
                           args.model, args.phase, not args.allow_partial), indent=2))
