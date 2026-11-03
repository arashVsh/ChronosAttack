"""Pure safety helpers shared by generated round-two hosted tasks."""

from __future__ import annotations

import hashlib
import json
import math


def manifest_digest(jobs: list[dict]) -> str:
    encoded = json.dumps(jobs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def event_job_id(event: dict) -> str | None:
    return event.get("job_id") or event.get("job", {}).get("id")


def normalize_jsonl_bytes(data: bytes) -> bytes:
    """Return append-safe JSONL bytes without changing any existing record."""
    return data if not data or data.endswith(b"\n") else data + b"\n"


def parse_jsonl_bytes(data: bytes, *, label: str = "JSONL") -> list[dict]:
    events = []
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{label} line {line_number} is blank")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} line {line_number} is invalid JSON") from exc
        if not isinstance(event, dict):
            raise ValueError(f"{label} line {line_number} is not an object")
        events.append(event)
    return events


def parse_jsonl_best_effort(data: bytes) -> tuple[list[dict], list[dict]]:
    """Recover intact records for emergency accounting after an audit failure."""
    events, failures = [], []
    for line_number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            failures.append({"line": line_number, "error": "blank line"})
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("record is not an object")
            events.append(event)
        except (json.JSONDecodeError, ValueError) as exc:
            failures.append({"line": line_number, "error": str(exc)})
    return events, failures


def completed_only_events(events: list[dict]) -> list[dict]:
    completed = {
        event["job"]["id"]
        for event in events
        if event.get("event") == "job_complete"
    }
    return [event for event in events if event_job_id(event) in completed]


def raw_event_summary(events: list[dict], *, invalid_json_lines: int = 0) -> dict:
    """Best-effort accounting that does not depend on a structural audit."""
    calls = [
        event
        for event in events
        if event.get("event") in ("call_complete", "call_failed")
    ]
    known_cost, unknown_cost = 0.0, 0
    for event in calls:
        value = event.get("cost_usd")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            known_cost += value
        else:
            unknown_cost += 1
    completed = {
        event.get("job", {}).get("id")
        for event in events
        if event.get("event") == "job_complete"
    }
    completed.discard(None)
    return {
        "events": len(events),
        "invalid_json_lines": invalid_json_lines,
        "accounting_complete": invalid_json_lines == 0 and unknown_cost == 0,
        "started_attempts": sum(event.get("event") == "job_started" for event in events),
        "completed_jobs": len(completed),
        "observed_invocations": len(calls),
        "complete_calls": sum(event.get("event") == "call_complete" for event in calls),
        "failed_calls": sum(event.get("event") == "call_failed" for event in calls),
        "known_cost_usd": known_cost,
        "unknown_cost_calls": unknown_cost,
    }


def select_shard(
    jobs: list[dict], *, shard_index: int = 0, shard_count: int = 1
) -> list[dict]:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid deterministic shard")
    selected = jobs[shard_index::shard_count]
    if not selected:
        raise ValueError("deterministic shard is empty")
    return selected


def validate_resume_seed(
    events: list[dict],
    *,
    model: str,
    identity: str,
    expected_job_ids: set[str],
    structural_audit,
) -> dict:
    """Accept only complete trials from the exact intended cell/subset."""
    if not events:
        return {"events": 0, "completed_jobs": 0, "known_cost_usd": 0.0}
    for event in events:
        if event.get("model") != model or event.get("identity") != identity:
            raise ValueError("resume seed identity/model mismatch")
        job_id = event_job_id(event)
        if job_id not in expected_job_ids:
            raise ValueError("resume seed contains a job outside the intended manifest")
    completed = [
        event["job"]["id"] for event in events if event.get("event") == "job_complete"
    ]
    if len(completed) != len(set(completed)):
        raise ValueError("resume seed duplicates a completed job")
    if {event_job_id(event) for event in events} != set(completed):
        raise ValueError("resume seed must contain completed-trial histories only")
    if any(
        event.get("event") in ("call_complete", "call_failed")
        and event.get("cost_usd") is None
        for event in events
    ):
        raise ValueError("resume seed contains unknown call cost")
    checked = structural_audit(events)
    if checked.get("completed_jobs") != len(completed):
        raise ValueError("resume seed audit/completion count mismatch")
    known_cost = sum(
        event["cost_usd"]
        for event in events
        if event.get("event") in ("call_complete", "call_failed")
        and event.get("cost_usd") is not None
    )
    return {
        "events": len(events),
        "completed_jobs": len(completed),
        "known_cost_usd": known_cost,
    }


def validate_resume_ledger(
    events: list[dict],
    *,
    model: str,
    identity: str,
    expected_jobs: dict[str, dict],
    structural_audit,
) -> dict:
    """Validate a cumulative, byte-preserving ledger before it can resume.

    Unlike ``validate_resume_seed``, this accepts the one paid partial tail that
    a gracefully stopped sequential runner can leave.  It never discards that
    tail: the same full ledger is loaded by the execution engine.
    """
    if not events:
        return {
            "events": 0,
            "completed_jobs": 0,
            "known_cost_usd": 0.0,
            "observed_invocations": 0,
            "failed_calls": 0,
            "incomplete_jobs": [],
            "max_attempt_by_job": {},
        }
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
            raise ValueError("resume ledger identity/model mismatch")
        kind = event.get("event")
        if kind not in allowed_kinds:
            raise ValueError("resume ledger contains an unknown event")
        job_id = event_job_id(event)
        if job_id not in expected_jobs:
            raise ValueError("resume ledger contains a job outside the intended manifest")
        attempt = event.get("attempt")
        if type(attempt) is not int or not 1 <= attempt <= 3:
            raise ValueError("resume ledger contains an invalid attempt")
        key = (job_id, attempt)

        if kind == "job_started":
            if job_id in completed:
                raise ValueError("resume ledger starts an attempt after completion")
            if active is not None:
                raise ValueError("resume ledger interleaves active attempts")
            if pending_job is not None and pending_job != job_id:
                raise ValueError("resume ledger advances past an incomplete job")
            if attempt != max_attempt.get(job_id, 0) + 1 or key in attempts:
                raise ValueError("resume ledger attempts are repeated or noncontiguous")
            execution_id = event.get("execution_id")
            if not execution_id:
                raise ValueError("resume ledger event is missing execution identity")
            attempts[key] = {
                "execution_id": execution_id,
                "next_step": 1,
                "terminal": False,
                "failed_call": False,
                "position": position,
            }
            max_attempt[job_id] = attempt
            active = key
            continue

        state = attempts.get(key)
        if state is None or event.get("execution_id") != state["execution_id"]:
            raise ValueError("resume ledger event is not linked to its unique attempt")
        if active != key or state["terminal"]:
            raise ValueError("resume ledger contains an event after an attempt terminal")

        if kind in ("call_complete", "call_failed"):
            step = event.get("step")
            if state["failed_call"] or step != state["next_step"]:
                raise ValueError("resume ledger calls are duplicated or nonsequential")
            value = event.get("cost_usd")
            if not (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                raise ValueError("resume ledger contains unknown or invalid call cost")
            state["next_step"] += 1
            state["failed_call"] = kind == "call_failed"
            continue

        if event.get("job") != expected_jobs[job_id]:
            raise ValueError("resume ledger terminal event changed the intended job")
        state["terminal"] = True
        active = None
        if kind == "job_complete":
            completed.add(job_id)
            if pending_job == job_id:
                pending_job = None
        else:
            pending_job = job_id

    if active is not None:
        raise ValueError("resume ledger has an unterminated active attempt")
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
        raise ValueError("resume ledger accounting disagrees with the strict audit")
    incomplete = sorted(set(max_attempt) - completed)
    if len(incomplete) > 1:
        raise ValueError("resume ledger contains multiple incomplete jobs")
    exhausted = [job_id for job_id in incomplete if max_attempt[job_id] >= 3]
    if exhausted:
        raise ValueError("resume ledger has an incomplete job at the attempt limit")
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
    }


def validate_archive_seed(
    archive_events: list[dict],
    seed_events: list[dict],
    *,
    model: str,
    identity: str,
    expected_job_ids: set[str],
    structural_audit,
) -> dict:
    """Validate a complete raw archive and its completed-trial resume view.

    The archive remains the accounting record.  The seed is deliberately only
    the completed-trial projection loaded into the frozen execution engine.
    """
    if bool(archive_events) != bool(seed_events):
        raise ValueError("resume seed and raw archive must be supplied together")
    if not archive_events:
        return {
            "archive_events": 0,
            "seed_events": 0,
            "completed_jobs": 0,
            "known_cost_usd": 0.0,
            "archive_extra_known_cost_usd": 0.0,
        }
    for event in archive_events:
        if event.get("model") != model or event.get("identity") != identity:
            raise ValueError("raw archive identity/model mismatch")
        if event_job_id(event) not in expected_job_ids:
            raise ValueError("raw archive contains a job outside the intended manifest")
    if any(
        event.get("event") in ("call_complete", "call_failed")
        and event.get("cost_usd") is None
        for event in archive_events
    ):
        raise ValueError("raw archive contains unknown call cost")
    archive_audit = structural_audit(archive_events)
    expected_seed = completed_only_events(archive_events)
    if seed_events != expected_seed:
        raise ValueError("resume seed is not the exact completed-trial projection of the raw archive")
    seed_audit = validate_resume_seed(
        seed_events,
        model=model,
        identity=identity,
        expected_job_ids=expected_job_ids,
        structural_audit=structural_audit,
    )
    if archive_audit.get("completed_jobs") != seed_audit["completed_jobs"]:
        raise ValueError("raw archive and resume seed completion counts differ")
    archive_summary = raw_event_summary(archive_events)
    extra = archive_summary["known_cost_usd"] - seed_audit["known_cost_usd"]
    if extra < -1e-12:
        raise ValueError("raw archive cost cannot be below resume seed cost")
    return {
        "archive_events": len(archive_events),
        "seed_events": len(seed_events),
        "completed_jobs": seed_audit["completed_jobs"],
        "known_cost_usd": archive_summary["known_cost_usd"],
        "archive_extra_known_cost_usd": max(0.0, extra),
    }


def subset_summary(events: list[dict], expected_job_ids: set[str]) -> dict:
    completed = {
        event["job"]["id"] for event in events if event.get("event") == "job_complete"
    }
    calls = [
        event
        for event in events
        if event.get("event") in ("call_complete", "call_failed")
        and event_job_id(event) in expected_job_ids
    ]
    unknown = sum(event.get("cost_usd") is None for event in calls)
    known = sum(
        event["cost_usd"] for event in calls if event.get("cost_usd") is not None
    )
    return {
        "complete": completed == expected_job_ids and not unknown,
        "completed_jobs": len(completed & expected_job_ids),
        "missing_job_ids": sorted(expected_job_ids - completed),
        "planned_job_ids": len(expected_job_ids),
        "observed_invocations": len(calls),
        "failed_calls": sum(event["event"] == "call_failed" for event in calls),
        "known_cost_usd": known,
        "unknown_cost_calls": unknown,
    }
