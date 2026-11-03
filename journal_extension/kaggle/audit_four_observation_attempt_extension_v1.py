"""Strict tree-study audit with one frozen attempts-4-to-6 exception."""

from collections import defaultdict
import json
import math

import four_observation_protocol as protocol
from round2_attempt_extension_v1 import (
    ALLOWED_ERROR_TYPE,
    EXTENDED_MAX_ATTEMPTS,
    MAX_COMPLETION_TOKENS,
    ORIGINAL_MAX_ATTEMPTS,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(events, model, phase, *, authorized_job_id, require_complete=True):
    jobs = {job["id"]: job for job in protocol.jobs_for(model, phase)}
    require(authorized_job_id in jobs, "Authorized repair job is outside the manifest")
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
    terminal = {}
    attempts_by_job = defaultdict(set)
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
        job, fixture = jobs[job_id], fixtures["tree4"]
        attempt = event["attempt"]
        limit = EXTENDED_MAX_ATTEMPTS if job_id == authorized_job_id else ORIGINAL_MAX_ATTEMPTS
        require(type(attempt) is int and 1 <= attempt <= limit, "Invalid attempt")
        require(
            attempt <= ORIGINAL_MAX_ATTEMPTS or job_id == authorized_job_id,
            "Attempt extension used for a different job",
        )
        key = (event["execution_id"], job_id, attempt)
        require(bool(key[0]), "Missing execution")
        if kind == "job_started":
            require(key not in started and job_id not in completed, "Duplicate start")
            require(attempt not in attempts_by_job[job_id], "Duplicate attempt")
            require(
                attempt == len(attempts_by_job[job_id]) + 1,
                "Noncontiguous attempt",
            )
            started.add(key)
            attempts_by_job[job_id].add(attempt)
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
            terminal[(job_id, attempt)] = event
            completed.add(job_id)
        else:
            require(event["job"] == job, "Changed failed trial")
            terminal[(job_id, attempt)] = event

    def exact_length_failure(job_id, attempt):
        event = terminal.get((job_id, attempt)) or {}
        attempt_calls = calls[(event.get("execution_id"), job_id, attempt)]
        call = attempt_calls.get(max(attempt_calls, default=0))
        raw = (call or {}).get("raw_completion") or {}
        choices = raw.get("choices") or []
        return bool(
            event.get("event") == "job_error"
            and event.get("error_type") == ALLOWED_ERROR_TYPE
            and (call or {}).get("event") == "call_failed"
            and (call or {}).get("error_type") == ALLOWED_ERROR_TYPE
            and ((call or {}).get("usage") or {}).get("output_tokens")
            == MAX_COMPLETION_TOKENS
            and choices
            and choices[0].get("finish_reason") == "length"
        )
    for attempt in sorted(attempts_by_job[authorized_job_id]):
        if attempt <= ORIGINAL_MAX_ATTEMPTS:
            continue
        require(
            exact_length_failure(authorized_job_id, attempt - 1),
            "Extended attempt lacks an exact costed length predecessor",
        )
        current = terminal.get((authorized_job_id, attempt)) or {}
        require(
            current.get("event") == "job_complete"
            or exact_length_failure(authorized_job_id, attempt),
            "Extended attempt is neither complete nor an exact costed length failure",
        )
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
        authorized_job_id=authorized_job_id,
        extended_attempts=sorted(
            attempt
            for job_id, attempts in attempts_by_job.items()
            if job_id == authorized_job_id
            for attempt in attempts
            if attempt > ORIGINAL_MAX_ATTEMPTS
        ),
    )
