"""Frozen selection and pass gate for reasoning-alignment compatibility runs."""

from __future__ import annotations

from round2_hosted import subset_summary


UNSUPPORTED_ERROR_TYPES = {
    "BadRequestError",
    "InvalidRequestError",
    "UnprocessableEntityError",
    "APIStatusError",
}
UNSUPPORTED_MARKERS = (
    "unsupported",
    "not supported",
    "does not support",
    "isn't supported",
    "invalid reasoning",
)


def jobs(full_study_jobs: list[dict]) -> list[dict]:
    selected = [
        job
        for job in full_study_jobs
        if job["mode"] == "stateful"
        and job["condition"] in ("natural", "attack")
        and job["rep"] == 1
    ]
    selected.sort(key=lambda job: (job["condition"] != "natural", job["id"]))
    if (
        len(selected) != 2
        or [job["condition"] for job in selected] != ["natural", "attack"]
        or sum(job["calls"] for job in selected) != 10
    ):
        raise ValueError("preflight must be one natural and one attacked stateful job")
    return selected


def run_once(engine, execute_job, kbench, llm, fixtures, expected_jobs, output, ceiling):
    """Execute each compatibility job at most once; every error stops the phase."""
    evidence = engine.Evidence(output, llm.model, fixtures, ceiling)
    for job in expected_jobs:
        if job["id"] in evidence.completed:
            continue
        if evidence.attempts.get(job["id"], 0):
            raise RuntimeError("Stopped preflight cannot retry an attempted job")
        evidence.append(dict(event="job_started", job_id=job["id"], attempt=1))
        try:
            execute_job(kbench, llm, fixtures, job, evidence, 1)
        except Exception as error:
            evidence.append(
                dict(
                    event="job_error",
                    job=job,
                    error_type=type(error).__name__,
                    attempt=1,
                )
            )
            raise


def pass_gate(events: list[dict], expected_jobs: list[dict]) -> dict:
    expected_ids = {job["id"] for job in expected_jobs}
    result = subset_summary(events, expected_ids)
    result["planned_calls"] = sum(job["calls"] for job in expected_jobs)
    relevant = [
        event
        for event in events
        if (event.get("job_id") or event.get("job", {}).get("id")) in expected_ids
    ]
    started = [event for event in relevant if event.get("event") == "job_started"]
    completed = [event for event in relevant if event.get("event") == "job_complete"]
    complete_calls = [event for event in relevant if event.get("event") == "call_complete"]
    result["passed"] = (
        result["complete"]
        and result["planned_calls"] == 10
        and result["observed_invocations"] == 10
        and len(complete_calls) == 10
        and result["failed_calls"] == 0
        and result["unknown_cost_calls"] == 0
        and len(started) == len(completed) == len(expected_jobs) == 2
        and all(event.get("attempt") == 1 for event in relevant)
        and not any(event.get("event") == "job_error" for event in relevant)
    )
    result["outcomes_ignored_for_pass"] = True
    return result


def unsupported_reasoning(error_type: str | None, error_text: str | None) -> bool:
    """Conservatively classify an endpoint-level reasoning-setting rejection."""
    text = (error_text or "").lower()
    return bool(
        error_type in UNSUPPORTED_ERROR_TYPES
        and "reason" in text
        and any(marker in text for marker in UNSUPPORTED_MARKERS)
    )
