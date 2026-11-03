"""Capture Kaggle's authenticated daily benchmark quota as pinned evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "chronos.kaggle-benchmark-quota-attestation.v1"
ENDPOINT = "/api/v1/benchmarks/tasks/quota"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _last_event_time(evidence: bytes) -> str:
    if not evidence or not evidence.endswith(b"\n"):
        raise ValueError("evidence must be non-empty and newline terminated")
    timestamps = []
    for number, raw_line in enumerate(evidence.splitlines(), start=1):
        try:
            event = json.loads(raw_line)
            timestamps.append(_parse_time(event["timestamp"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid evidence event at line {number}") from exc
    return max(timestamps).isoformat()


def build_attestation(
    *,
    response: dict,
    queried_at_start: str,
    queried_at_end: str,
    task: str,
    run_id: int,
    evidence: bytes,
    terminal: bytes,
) -> dict:
    """Build and self-hash one quota observation tied to completed evidence."""
    if set(response) != {"dailyQuotaUsed", "totalDailyQuotaAllowed"}:
        raise ValueError("unexpected quota response schema")
    used = response["dailyQuotaUsed"]
    allowed = response["totalDailyQuotaAllowed"]
    if (
        isinstance(used, bool)
        or isinstance(allowed, bool)
        or not isinstance(used, (int, float))
        or not isinstance(allowed, (int, float))
        or used < 0
        or allowed <= 0
        or used > allowed
    ):
        raise ValueError("invalid quota values")
    start = _parse_time(queried_at_start)
    end = _parse_time(queried_at_end)
    if end < start:
        raise ValueError("quota query end precedes its start")
    last_event = _parse_time(_last_event_time(evidence))
    if start < last_event:
        raise ValueError("quota was queried before the pinned run evidence ended")
    try:
        terminal_value = json.loads(terminal)
    except json.JSONDecodeError as exc:
        raise ValueError("terminal artifact is not valid JSON") from exc
    if not isinstance(terminal_value, dict):
        raise ValueError("terminal artifact must be a JSON object")

    body = {
        "schema": SCHEMA,
        "endpoint": ENDPOINT,
        "queried_at_start_utc": start.isoformat(),
        "queried_at_end_utc": end.isoformat(),
        "response": {
            "daily_quota_used_usd": float(used),
            "total_daily_quota_allowed_usd": float(allowed),
        },
        "run_context": {
            "task": task,
            "run_id": run_id,
            "model": terminal_value.get("model"),
            "reasoning": terminal_value.get("reasoning"),
            "study_id": terminal_value.get("study_id"),
            "last_evidence_event_utc": last_event.isoformat(),
            "evidence_sha256": _sha256(evidence),
            "terminal_sha256": _sha256(terminal),
        },
    }
    return {**body, "attestation_sha256": _sha256(_canonical(body))}


def verify_attestation(attestation: dict, evidence: bytes, terminal: bytes) -> None:
    digest = attestation.get("attestation_sha256")
    body = {key: value for key, value in attestation.items() if key != "attestation_sha256"}
    if digest != _sha256(_canonical(body)):
        raise ValueError("quota attestation self-hash mismatch")
    context = attestation.get("run_context") or {}
    if (
        attestation.get("schema") != SCHEMA
        or attestation.get("endpoint") != ENDPOINT
        or context.get("evidence_sha256") != _sha256(evidence)
        or context.get("terminal_sha256") != _sha256(terminal)
    ):
        raise ValueError("quota attestation does not match the run artifacts")
    rebuilt = build_attestation(
        response={
            "dailyQuotaUsed": attestation["response"]["daily_quota_used_usd"],
            "totalDailyQuotaAllowed": attestation["response"][
                "total_daily_quota_allowed_usd"
            ],
        },
        queried_at_start=attestation["queried_at_start_utc"],
        queried_at_end=attestation["queried_at_end_utc"],
        task=context["task"],
        run_id=context["run_id"],
        evidence=evidence,
        terminal=terminal,
    )
    if rebuilt != attestation:
        raise ValueError("quota attestation differs from rebuilt evidence")


def fetch_quota() -> tuple[dict, str, str]:
    """Query the official SDK endpoint without exposing credentials."""
    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.benchmarks.types.benchmark_tasks_api_service import (
        ApiGetBenchmarkTaskQuotaRequest,
    )

    start = datetime.now(timezone.utc).isoformat()
    api = KaggleApi()
    api.authenticate()
    with api.build_kaggle_client() as client:
        response = (
            client.benchmarks.benchmark_tasks_api_client.get_benchmark_task_quota(
                ApiGetBenchmarkTaskQuotaRequest()
            )
        )
    end = datetime.now(timezone.utc).isoformat()
    return response.to_dict(ignore_defaults=False), start, end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--terminal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    evidence = args.evidence.read_bytes()
    terminal = args.terminal.read_bytes()
    response, start, end = fetch_quota()
    attestation = build_attestation(
        response=response,
        queried_at_start=start,
        queried_at_end=end,
        task=args.task,
        run_id=args.run_id,
        evidence=evidence,
        terminal=terminal,
    )
    verify_attestation(attestation, evidence, terminal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(attestation, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(attestation, sort_keys=True))


if __name__ == "__main__":
    main()
