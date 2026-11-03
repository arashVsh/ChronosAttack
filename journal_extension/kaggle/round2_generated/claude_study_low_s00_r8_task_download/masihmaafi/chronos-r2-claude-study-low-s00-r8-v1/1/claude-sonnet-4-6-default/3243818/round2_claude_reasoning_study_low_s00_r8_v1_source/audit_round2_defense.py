"""Strict defense auditor with prompt linkage and charged-failure accounting.

The historical defense module is source-hashed and cannot be repaired in place.
This derived auditor validates its evidence more deeply and includes known cost
from both successful and failed provider invocations.
"""

from __future__ import annotations

from collections import defaultdict
import json
import math

import four_observation_defenses as defenses
import four_observation_protocol as base


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _expected_call(job: dict, fixture: dict, calls: dict[int, dict], step: int):
    if job["mode"] == "invariant":
        if step < 5:
            tool = job["order"][step - 1]
            prompt = defenses.SUMMARY_PROMPT.format(
                tool=tool, payload=fixture["payloads"][tool]
            )
            return defenses.engine.State, prompt
        states = [
            {
                "tool": tool,
                "state": calls[index]["response"],
            }
            for index, tool in enumerate(job["order"], 1)
        ]
        canonical = sorted(states, key=lambda state: state["tool"])
        lines = "\n".join(
            f'- {state["tool"]}: {state["state"]["state_summary"]} (favours '
            f'{state["state"]["current_choice"]}, confidence '
            f'{state["state"]["confidence"]})'
            for state in canonical
        )
        prompt = (
            f"{defenses.SYNTHESIS_PREAMBLE}\n\n{lines}\n\n"
            f"{fixture['final_prompt']}"
        )
        return defenses.engine.Decision, prompt
    if step < 5:
        return (
            defenses.engine.State,
            base.step_prompt(fixture, job["order"][step - 1], step),
        )
    return defenses.engine.Decision, fixture["final_prompt"]


def audit(events, model: str, expected_jobs=None, require_complete: bool = True) -> dict:
    jobs_list = (
        list(expected_jobs)
        if expected_jobs is not None
        else defenses.jobs_for(model, "defense")
    )
    jobs = {job["id"]: job for job in jobs_list}
    _require(len(jobs) == len(jobs_list), "Duplicate expected job ID")
    fixtures = defenses.fixtures()
    identity = defenses.engine.digest(
        json.dumps(
            {
                "study": defenses.STUDY_ID,
                "model": model,
                "fixtures": fixtures,
                "settings": defenses.engine.CALL_SETTINGS,
            },
            sort_keys=True,
        )
    )

    started = set()
    completed = set()
    calls = defaultdict(dict)
    seen_calls = set()
    known_cost = 0.0
    unknown_cost = 0
    failed_calls = 0

    for event in events:
        _require(
            event.get("identity") == identity and event.get("model") == model,
            "Protocol/model mismatch",
        )
        kind = event.get("event")
        _require(
            kind
            in ("job_started", "call_complete", "call_failed", "job_complete", "job_error"),
            "Unknown event",
        )
        job_id = event.get("job_id", event.get("job", {}).get("id"))
        _require(job_id in jobs, "Unexpected job")
        job = jobs[job_id]
        fixture = fixtures[job["scenario"]]
        attempt = event.get("attempt")
        _require(type(attempt) is int and 1 <= attempt <= 3, "Invalid attempt")
        key = (event.get("execution_id"), job_id, attempt)
        _require(bool(key[0]), "Missing execution")

        if kind == "job_started":
            _require(key not in started and job_id not in completed, "Duplicate start")
            started.add(key)
            continue
        _require(key in started, "Missing start")

        if kind in ("call_complete", "call_failed"):
            step = event.get("step")
            _require(type(step) is int and 1 <= step <= job["calls"], "Unexpected step")
            call_key = (*key, step)
            _require(call_key not in seen_calls, "Duplicate call")
            _require(step == len(calls[key]) + 1, "Nonsequential calls")
            schema, prompt = _expected_call(job, fixture, calls[key], step)
            _require(
                event.get("schema") == schema.__name__
                and event.get("user_prompt") == prompt,
                "Prompt/schema mismatch",
            )
            calculated = defenses.engine.usage_cost(event["usage"])
            _require(calculated == event.get("cost_usd"), "Cost mismatch")
            if calculated is None:
                unknown_cost += 1
            else:
                _require(
                    math.isfinite(calculated) and calculated >= 0,
                    "Invalid cost",
                )
                known_cost += calculated
            if kind == "call_complete":
                response = schema(**event["response"])
                defenses.engine.validate_response(response, schema)
            else:
                failed_calls += 1
            calls[key][step] = event
            seen_calls.add(call_key)
            continue

        if kind == "job_error":
            _require(event.get("job") == job, "Changed failed trial")
            continue

        _require(job_id not in completed and event.get("job") == job, "Duplicate/changed trial")
        _require(
            len(calls[key]) == job["calls"]
            and all(call["event"] == "call_complete" for call in calls[key].values()),
            "Incomplete trial",
        )
        _require(
            event.get("final") == calls[key][job["calls"]]["response"],
            "Final mismatch",
        )
        expected_states = [
            {
                "tool": tool,
                "step": step,
                "state": calls[key][step]["response"],
                "payload_sha256": fixture["hashes"][tool],
            }
            for step, tool in enumerate(job["order"], 1)
        ]
        _require(event.get("states") == expected_states, "History mismatch")
        _require(
            event.get("payload_hashes") == fixture["hashes"]
            and event.get("target") == fixture["target"],
            "Fixture mismatch",
        )
        _require(event.get("delivered_order") == job["order"], "Delivered order mismatch")
        _require(
            event.get("planned_calls") == job["calls"] and event.get("schedule") == [],
            "Count/schedule mismatch",
        )
        completed.add(job_id)

    missing = sorted(set(jobs) - completed)
    if require_complete:
        _require(not missing and not unknown_cost, "Incomplete evidence or unknown costs")
    return {
        "study": defenses.STUDY_ID,
        "model": model,
        "phase": "defense",
        "complete": not missing and not unknown_cost,
        "completed_jobs": len(completed),
        "missing_jobs": missing,
        "observed_invocations": len(seen_calls),
        "failed_calls": failed_calls,
        "complete_trial_calls": sum(jobs[job_id]["calls"] for job_id in completed),
        "known_cost_usd": known_cost,
        "unknown_cost_calls": unknown_cost,
    }
