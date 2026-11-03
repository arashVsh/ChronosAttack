"""Versioned ledger and execution rules for the frozen Terra attempt repair."""

from __future__ import annotations

import fcntl
import json
import math
from pathlib import Path

from round2_hosted import event_job_id, parse_jsonl_bytes, raw_event_summary


ORIGINAL_MAX_ATTEMPTS = 3
EXTENDED_MAX_ATTEMPTS = 6
ALLOWED_ERROR_TYPE = "LengthFinishReasonError"
MAX_COMPLETION_TOKENS = 256


def _attempt_limit(job_id: str, authorized_job_id: str) -> int:
    return EXTENDED_MAX_ATTEMPTS if job_id == authorized_job_id else ORIGINAL_MAX_ATTEMPTS


def _is_exact_costed_length_failure(state: dict, terminal: dict) -> bool:
    call = state.get("last_call") or {}
    raw = call.get("raw_completion") or {}
    choices = raw.get("choices") or []
    usage = call.get("usage") or {}
    raw_usage = raw.get("usage") or {}
    input_cost = usage.get("input_tokens_cost_nanodollars")
    output_cost = usage.get("output_tokens_cost_nanodollars")
    cost = call.get("cost_usd")
    return bool(
        state.get("failed_call")
        and call.get("event") == "call_failed"
        and call.get("error_type") == ALLOWED_ERROR_TYPE
        and terminal.get("error_type") == ALLOWED_ERROR_TYPE
        and isinstance(input_cost, (int, float))
        and not isinstance(input_cost, bool)
        and isinstance(output_cost, (int, float))
        and not isinstance(output_cost, bool)
        and isinstance(cost, (int, float))
        and not isinstance(cost, bool)
        and math.isfinite(cost)
        and cost >= 0
        and math.isclose(
            cost, (input_cost + output_cost) / 1e9, rel_tol=0, abs_tol=1e-12
        )
        and usage.get("output_tokens") == MAX_COMPLETION_TOKENS
        and raw_usage.get("completion_tokens") == MAX_COMPLETION_TOKENS
        and choices
        and choices[0].get("finish_reason") == "length"
    )


def _persisted_attempt_is_exact_length_failure(evidence, job: dict, attempt: int) -> bool:
    events = parse_jsonl_bytes(evidence.path.read_bytes(), label="runtime evidence")
    if len(events) < 2:
        return False
    call, terminal = events[-2:]
    execution_id = terminal.get("execution_id")
    state = {
        "failed_call": call.get("event") == "call_failed",
        "last_call": call,
    }
    return bool(
        terminal.get("event") == "job_error"
        and terminal.get("job") == job
        and terminal.get("attempt") == attempt
        and call.get("attempt") == attempt
        and event_job_id(call) == job["id"]
        and execution_id
        and call.get("execution_id") == execution_id
        and _is_exact_costed_length_failure(state, terminal)
    )


def validate_extended_resume_ledger(
    events: list[dict],
    *,
    model: str,
    identity: str,
    expected_jobs: dict[str, dict],
    authorized_job_id: str,
    structural_audit,
) -> dict:
    """Validate a cumulative ledger with one exact attempts-4-to-6 exception."""
    if authorized_job_id not in expected_jobs:
        raise ValueError("authorized repair job is outside the intended manifest")
    if not events:
        raise ValueError("attempt-extension ledger requires the immutable parent")
    allowed_kinds = {
        "job_started",
        "call_complete",
        "call_failed",
        "job_complete",
        "job_error",
    }
    attempts: dict[tuple[str, int], dict] = {}
    max_attempt: dict[str, int] = {}
    completed: set[str] = set()
    active: tuple[str, int] | None = None
    pending_job: str | None = None

    for position, event in enumerate(events, 1):
        if event.get("identity") != identity or event.get("model") != model:
            raise ValueError("extended ledger identity/model mismatch")
        kind = event.get("event")
        if kind not in allowed_kinds:
            raise ValueError("extended ledger contains an unknown event")
        job_id = event_job_id(event)
        if job_id not in expected_jobs:
            raise ValueError("extended ledger contains a job outside the intended manifest")
        attempt = event.get("attempt")
        limit = _attempt_limit(job_id, authorized_job_id)
        if type(attempt) is not int or not 1 <= attempt <= limit:
            raise ValueError("extended ledger contains an unauthorized attempt")
        if attempt > ORIGINAL_MAX_ATTEMPTS and job_id != authorized_job_id:
            raise ValueError("attempt extension was used for a different job")
        key = (job_id, attempt)

        if kind == "job_started":
            if job_id in completed:
                raise ValueError("extended ledger starts an attempt after completion")
            if active is not None:
                raise ValueError("extended ledger interleaves active attempts")
            if pending_job is not None and pending_job != job_id:
                raise ValueError("extended ledger advances past an incomplete job")
            if attempt != max_attempt.get(job_id, 0) + 1 or key in attempts:
                raise ValueError("extended ledger attempts are repeated or noncontiguous")
            if attempt > ORIGINAL_MAX_ATTEMPTS:
                previous = attempts.get((job_id, attempt - 1))
                if previous is None or not _is_exact_costed_length_failure(
                    previous, previous.get("terminal_event") or {}
                ):
                    raise ValueError("extended attempt lacks an exact costed length predecessor")
            execution_id = event.get("execution_id")
            if not execution_id:
                raise ValueError("extended ledger event is missing execution identity")
            attempts[key] = {
                "execution_id": execution_id,
                "next_step": 1,
                "terminal": False,
                "failed_call": False,
                "last_call": None,
                "terminal_event": None,
                "position": position,
            }
            max_attempt[job_id] = attempt
            active = key
            continue

        state = attempts.get(key)
        if state is None or event.get("execution_id") != state["execution_id"]:
            raise ValueError("extended ledger event is not linked to its unique attempt")
        if active != key or state["terminal"]:
            raise ValueError("extended ledger contains an event after an attempt terminal")

        if kind in ("call_complete", "call_failed"):
            step = event.get("step")
            if state["failed_call"] or step != state["next_step"]:
                raise ValueError("extended ledger calls are duplicated or nonsequential")
            value = event.get("cost_usd")
            if not (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                raise ValueError("extended ledger contains unknown or invalid call cost")
            state["next_step"] += 1
            state["failed_call"] = kind == "call_failed"
            state["last_call"] = event
            continue

        if event.get("job") != expected_jobs[job_id]:
            raise ValueError("extended ledger terminal event changed the intended job")
        state["terminal"] = True
        state["terminal_event"] = event
        active = None
        if kind == "job_complete":
            if state["failed_call"]:
                raise ValueError("extended ledger completed an attempt after a failed call")
            completed.add(job_id)
            if pending_job == job_id:
                pending_job = None
        else:
            if attempt > ORIGINAL_MAX_ATTEMPTS and not _is_exact_costed_length_failure(
                state, event
            ):
                raise ValueError("extended attempt ended without the authorized length failure")
            pending_job = job_id

    if active is not None:
        raise ValueError("extended ledger has an unterminated active attempt")
    checked = structural_audit(events)
    summary = raw_event_summary(events)
    audit_invocations = checked.get(
        "observed_invocations", checked.get("attempted_calls")
    )
    if (
        checked.get("completed_jobs") != summary["completed_jobs"]
        or audit_invocations != summary["observed_invocations"]
        or checked.get("failed_calls") != summary["failed_calls"]
        or not math.isclose(
            checked.get("known_cost_usd", float("nan")),
            summary["known_cost_usd"],
            rel_tol=0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("extended ledger accounting disagrees with the strict audit")
    incomplete = sorted(set(max_attempt) - completed)
    if len(incomplete) > 1:
        raise ValueError("extended ledger contains multiple incomplete jobs")
    exhausted = [
        job_id
        for job_id in incomplete
        if max_attempt[job_id] >= _attempt_limit(job_id, authorized_job_id)
    ]
    if exhausted:
        raise ValueError("extended ledger has an incomplete job at its amended attempt limit")
    return {
        "events": len(events),
        "completed_jobs": len(completed),
        "known_cost_usd": summary["known_cost_usd"],
        "observed_invocations": summary["observed_invocations"],
        "failed_calls": summary["failed_calls"],
        "incomplete_jobs": incomplete,
        "max_attempt_by_job": {
            job_id: max_attempt[job_id] for job_id in sorted(max_attempt)
        },
        "authorized_job_id": authorized_job_id,
        "authorized_next_attempt": (
            max_attempt.get(authorized_job_id, 0) + 1
            if authorized_job_id in incomplete
            else None
        ),
    }


def run_jobs(
    engine,
    kbench,
    llm,
    fixtures,
    jobs,
    directory,
    ceiling_usd,
    *,
    authorized_job_id: str,
):
    """Run frozen jobs with the exact single-job attempt extension."""
    Path(directory).mkdir(parents=True, exist_ok=True)
    model = getattr(llm, "model", None)
    if model not in engine.MODELS:
        raise ValueError("Unexpected model; no calls made")
    if authorized_job_id not in {job["id"] for job in jobs}:
        raise ValueError("Authorized repair job is outside the runtime manifest")
    lock_path = Path(directory) / (model.replace("/", "_") + ".lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run_locked(
            engine,
            kbench,
            llm,
            fixtures,
            jobs,
            directory,
            ceiling_usd,
            authorized_job_id=authorized_job_id,
        )


def _run_locked(
    engine,
    kbench,
    llm,
    fixtures,
    jobs,
    directory,
    ceiling_usd,
    *,
    authorized_job_id: str,
):
    model = getattr(llm, "model", None)
    if model not in engine.MODELS:
        raise ValueError("Unexpected model; no calls made")
    evidence = engine.Evidence(directory, model, fixtures, ceiling_usd)
    for job in jobs:
        if job["id"] in evidence.completed:
            continue
        while job["id"] not in evidence.completed:
            attempt = evidence.attempts.get(job["id"], 0) + 1
            limit = _attempt_limit(job["id"], authorized_job_id)
            if attempt > limit:
                raise RuntimeError(
                    "Amended attempt limit reached; repair evidence is preserved"
                )
            evidence.append(
                dict(event="job_started", job_id=job["id"], attempt=attempt)
            )
            try:
                engine.execute_job(
                    kbench, llm, fixtures, job, evidence, attempt
                )
            except Exception as error:
                evidence.append(
                    dict(
                        event="job_error",
                        job=job,
                        error_type=type(error).__name__,
                        attempt=attempt,
                    )
                )
                if (
                    type(error).__name__ == ALLOWED_ERROR_TYPE
                    and not evidence.unknown_cost
                    and _persisted_attempt_is_exact_length_failure(
                        evidence, job, attempt
                    )
                    and attempt < limit
                ):
                    continue
                raise
    result = dict(
        event="run_complete",
        study=engine.STUDY_ID,
        model=model,
        completed_jobs=len(evidence.completed),
        accepted_response_count=evidence.calls,
        failed_call_count=evidence.failed_calls,
        complete_trial_calls=sum(
            event["planned_calls"] for event in evidence.completed.values()
        ),
        measured_cost_usd=evidence.spent,
        unknown_cost=evidence.unknown_cost,
        expected_calls=sum(job["calls"] for job in jobs),
        attempt_extension={
            "job_id": authorized_job_id,
            "original_max": ORIGINAL_MAX_ATTEMPTS,
            "amended_max": EXTENDED_MAX_ATTEMPTS,
        },
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return result
