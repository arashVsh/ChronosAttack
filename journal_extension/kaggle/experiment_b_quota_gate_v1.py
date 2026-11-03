"""Costed prelaunch gate against a fresh authenticated Kaggle daily meter."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import capture_benchmark_quota_v1 as quota

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS = ROOT / "kaggle/round2_analysis/experiment_a_analysis_v1.json"


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Quota time requires timezone")
    return parsed.astimezone(timezone.utc)


def evaluate(
    *,
    task_manifest: dict,
    attestation: dict,
    evidence: bytes,
    terminal: bytes,
    now: datetime | None = None,
    max_age_seconds: int = 3600,
) -> dict:
    """Assess only quota; scientific prerequisites are a separate launch gate."""
    quota.verify_attestation(attestation, evidence, terminal)
    schema = task_manifest.get("schema")
    manifest_hash_field = {
        "chronos.experiment-b-pilot-tasks.v1": "pilot_tasks_manifest_sha256",
        "chronos.experiment-b-study-batch.v1": "batch_manifest_sha256",
        "chronos.experiment-b-transport-repair-tasks.v1": "repair_manifest_sha256",
        "chronos.experiment-b-transport-repair-s18-s19-tasks.v1": "repair_manifest_sha256",
    }.get(schema)
    if manifest_hash_field is None or manifest_hash_field not in task_manifest:
        raise ValueError("B task manifest has no schema-matched self-hash")
    body = {key: value for key, value in task_manifest.items() if key != manifest_hash_field}
    if _hash(body) != task_manifest[manifest_hash_field]:
        raise ValueError("B task manifest self-hash mismatch")
    if task_manifest.get("launch_authorized") is not False:
        raise ValueError("B task manifest must remain staged until all launch gates pass")
    start = _time(attestation["queried_at_start_utc"])
    end = _time(attestation["queried_at_end_utc"])
    current = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    if not 0 <= (current - end).total_seconds() <= max_age_seconds:
        raise ValueError("Official Kaggle quota observation is stale or in the future")
    used = attestation["response"]["daily_quota_used_usd"]
    allowed = attestation["response"]["total_daily_quota_allowed_usd"]
    if allowed != 10.0:
        raise ValueError("Official daily quota differs from the approved $10 cap")
    ceiling = task_manifest["aggregate_ceiling_usd"]
    if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) or ceiling <= 0:
        raise ValueError("B task ceiling is invalid")
    remaining = allowed - used
    if remaining + 1e-9 < ceiling:
        raise ValueError("Insufficient fresh daily quota for B task ceilings")
    result = {
        "schema": "chronos.experiment-b-quota-gate.v1",
        "task_manifest_sha256": task_manifest[manifest_hash_field],
        "quota_attestation_sha256": attestation["attestation_sha256"],
        "quota_evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "quota_terminal_sha256": hashlib.sha256(terminal).hexdigest(),
        "checked_at_utc": current.isoformat(),
        "quota_query_started_at_utc": start.isoformat(),
        "quota_query_ended_at_utc": end.isoformat(),
        "daily_used_usd": used,
        "daily_allowed_usd": allowed,
        "remaining_usd": remaining,
        "aggregate_ceiling_usd": ceiling,
        "remaining_after_reservation_usd": remaining - ceiling,
        "quota_passed": True,
        "scientific_prerequisites_checked": False,
    }
    return {**result, "gate_sha256": _hash(result)}


def evaluate_launch(*, analysis_path: Path, **quota_arguments) -> dict:
    """Join the fresh quota check to A's exact regenerated analysis seal."""
    quota_result = evaluate(**quota_arguments)
    if analysis_path.resolve() != ANALYSIS.resolve():
        raise ValueError("Unexpected Experiment A analysis artifact path")
    analysis = json.loads(analysis_path.read_text())
    body = {key: value for key, value in analysis.items() if key != "analysis_sha256"}
    if _hash(body) != analysis.get("analysis_sha256"):
        raise ValueError("Experiment A analysis self-hash mismatch")
    from analyze_experiment_a import verify_analysis_file

    verify_analysis_file(analysis_path)
    joined = {
        **{key: value for key, value in quota_result.items() if key != "gate_sha256"},
        "experiment_a_analysis_sha256": analysis["analysis_sha256"],
        "scientific_prerequisites_checked": True,
        "launch_authorized": True,
    }
    return {**joined, "gate_sha256": _hash(joined)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-manifest", required=True, type=Path)
    parser.add_argument("--quota-attestation", required=True, type=Path)
    parser.add_argument("--quota-evidence", required=True, type=Path)
    parser.add_argument("--quota-terminal", required=True, type=Path)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args()
    arguments = dict(
        task_manifest=json.loads(args.task_manifest.read_text()),
        attestation=json.loads(args.quota_attestation.read_text()),
        evidence=args.quota_evidence.read_bytes(),
        terminal=args.quota_terminal.read_bytes(),
    )
    result = (
        evaluate_launch(analysis_path=args.analysis, **arguments)
        if args.analysis else evaluate(**arguments)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
