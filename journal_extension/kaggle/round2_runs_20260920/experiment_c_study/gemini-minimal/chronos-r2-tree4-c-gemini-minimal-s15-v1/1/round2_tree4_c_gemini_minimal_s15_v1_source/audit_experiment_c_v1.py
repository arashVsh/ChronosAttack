"""Strict prompt, vote, summary-reuse and cost audit for Experiment C JSONL."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import experiment_c_protocol_v1 as protocol
import experiment_c_selection_v1 as selection_rules
import four_observation_defenses as defenses
import four_observation_protocol as tree


def require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _states(f: dict, job: dict, calls: dict[int, dict]) -> list[dict]:
    if job["mode"] in ("barrier", "order_consistency_24"):
        return []
    return [
        {
            "tool": tool,
            "step": step,
            "state": calls[step]["response"],
            "payload_sha256": f["hashes"][tool],
        }
        for step, tool in enumerate(job["order"], 1)
    ]


def _prompt_schema(f: dict, job: dict, step: int, prior: dict[int, dict]) -> tuple[str, type]:
    arm = job["mode"]
    if arm == "order_consistency_24":
        return protocol.consistency_prompt(f, step - 1), protocol.engine.Decision
    if arm == "barrier":
        return tree.joint_prompt(f, {"mode": "barrier", "order": job["order"]}), protocol.engine.Decision
    if arm == "invariant":
        if step <= 4:
            tool = job["order"][step - 1]
            return defenses.SUMMARY_PROMPT.format(tool=tool, payload=f["payloads"][tool]), protocol.engine.State
        require(all(index in prior for index in range(1, 5)), "synthesis preceded its four summaries")
        states = _states(f, job, prior)
        return protocol.synthesis_prompt(f, states, reverse=step == 6), protocol.engine.Decision
    if step < 5:
        tool = job["order"][step - 1]
        return tree.step_prompt(f, tool, step), protocol.engine.State
    return f["final_prompt"], protocol.engine.Decision


def audit(
    events: list[dict],
    model: str,
    selection: dict,
    *,
    require_complete: bool = True,
    expected_job_ids: set[str] | None = None,
) -> dict:
    selection_rules.validate_selection(selection, model=model)
    protocol.configure(model, selection["reasoning"])
    full_jobs = {job["id"]: job for job in protocol.jobs_for(model, selection)}
    if expected_job_ids is None:
        jobs = full_jobs
    else:
        require(bool(expected_job_ids) and expected_job_ids <= set(full_jobs), "invalid shard job IDs")
        jobs = {job_id: full_jobs[job_id] for job_id in expected_job_ids}
    fixtures = protocol.fixtures(selection)
    f = fixtures["tree4"]
    identity = protocol.engine.digest(
        json.dumps({"study": protocol.STUDY_ID, "model": model, "fixtures": fixtures, "settings": protocol.engine.CALL_SETTINGS}, sort_keys=True)
    )
    started, seen_calls, completed = set(), set(), set()
    calls: dict[tuple[str, str, int], dict[int, dict]] = defaultdict(dict)
    max_attempt: dict[str, int] = {}
    failed_attempts: set[tuple[str, str, int]] = set()
    active: tuple[str, str, int] | None = None
    pending_job: str | None = None
    cost, failed, unknown = 0.0, 0, 0
    for event in events:
        require(event.get("identity") == identity and event.get("model") == model, "protocol/model/setting identity mismatch")
        kind = event.get("event")
        require(kind in {"job_started", "call_complete", "call_failed", "job_complete", "job_error"}, "unknown event")
        job_id = event.get("job_id", (event.get("job") or {}).get("id"))
        require(job_id in jobs, "unexpected job")
        job = jobs[job_id]
        attempt = event.get("attempt")
        require(type(attempt) is int and 1 <= attempt <= 3, "invalid attempt")
        key = (event.get("execution_id"), job_id, attempt)
        require(bool(key[0]), "missing execution ID")
        if kind == "job_started":
            require(key not in started and job_id not in completed, "duplicate or post-completion start")
            require(active is None, "interleaved active attempts")
            require(pending_job in (None, job_id), "advanced past an incomplete job")
            require(attempt == max_attempt.get(job_id, 0) + 1, "noncontiguous attempt number")
            started.add(key)
            max_attempt[job_id] = attempt
            active = key
            continue
        require(key in started and active == key, "event outside its active attempt")
        if kind in ("call_complete", "call_failed"):
            step = event.get("step")
            require(type(step) is int and 1 <= step <= job["calls"], "unexpected call step")
            require(key not in failed_attempts, "call after a failed invocation")
            require((*key, step) not in seen_calls, "duplicate provider invocation")
            seen_calls.add((*key, step))
            require(step == len(calls[key]) + 1, "nonsequential provider invocations")
            expected_prompt, schema = _prompt_schema(f, job, step, calls[key])
            require(event.get("schema") == schema.__name__ and event.get("user_prompt") == expected_prompt, "prompt/schema mismatch")
            calculated = protocol.engine.usage_cost(event.get("usage") or {})
            require(calculated == event.get("cost_usd"), "call cost does not match usage")
            if calculated is None:
                unknown += 1
            else:
                require(math.isfinite(calculated) and calculated >= 0, "invalid call cost")
                cost += calculated
            if kind == "call_complete":
                response = event.get("response")
                require(isinstance(response, dict), "missing parsed response")
                protocol.engine.validate_response(schema(**response), schema)
            else:
                failed += 1
                failed_attempts.add(key)
            calls[key][step] = event
            continue
        require(event.get("job") == job, "terminal event changed the frozen job")
        if kind == "job_error":
            pending_job = job_id
            active = None
            continue
        require(job_id not in completed, "duplicated completed decision")
        trial_calls = calls[key]
        require(len(trial_calls) == job["calls"] and all(call["event"] == "call_complete" for call in trial_calls.values()), "decision lacks its complete valid call set")
        arm = job["mode"]
        expected_states = _states(f, job, trial_calls)
        if arm == "order_consistency_24":
            decisions = [
                {"condition": index, "order": protocol.consistency_order(index, f), "decision": trial_calls[index + 1]["response"]}
                for index in range(24)
            ]
            final = protocol.consistency_vote([row["decision"]["final_choice"] for row in decisions])
            reverse = None
        else:
            decisions = []
            final = trial_calls[5 if job["calls"] >= 5 else 1]["response"]
            reverse = trial_calls[6]["response"] if arm == "invariant" and job["calls"] == 6 else None
        require(event.get("states") == expected_states, "state history differs from raw calls")
        require(event.get("consistency_decisions") == decisions, "24-order decisions/vote inputs changed")
        require(event.get("final") == final and event.get("reverse_final") == reverse, "final or reverse synthesis differs from raw calls")
        require(event.get("payload_hashes") == f["hashes"] and event.get("target") == f["target"], "fixture payload/target changed")
        require(event.get("delivered_order") == job["order"] and event.get("arrival_order") == job["arrival_order"], "delivered or arrival order changed")
        require(event.get("planned_calls") == job["calls"] and event.get("selection_manifest_sha256") == f["selection_manifest_sha256"], "count or selection seal changed")
        expected_schedule = tree.schedule(f, job["order"]) if arm in ("undefended_natural", "undefended_selected_order", "randomized") else []
        require(event.get("schedule") == expected_schedule, "schedule changed")
        completed.add(job_id)
        pending_job = None
        active = None
    missing = sorted(set(jobs) - completed)
    require(active is None, "unterminated active attempt")
    if require_complete:
        require(not missing and unknown == 0, "incomplete evidence or unknown charged cost")
    return {
        "schema": "chronos.experiment-c-audit.v1",
        "model": model,
        "reasoning": selection["reasoning"],
        "role": selection["role"],
        "selection_manifest_sha256": selection["selection_manifest_sha256"],
        "complete": not missing and unknown == 0,
        "completed_jobs": len(completed),
        "missing_jobs": missing,
        "observed_invocations": len(seen_calls),
        "failed_calls": failed,
        "complete_trial_calls": sum(jobs[job_id]["calls"] for job_id in completed),
        "known_cost_usd": cost,
        "unknown_cost_calls": unknown,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    events = [json.loads(line) for line in args.evidence.read_text().splitlines()]
    print(json.dumps(audit(events, args.model, selection, require_complete=not args.allow_partial), indent=2))
