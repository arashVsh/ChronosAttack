"""Verify the immutable Kaggle result of the Terra shard-00 repair."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import audit_four_observation_attempt_extension_v1 as amended_audit
import build_attempt_extension_v1 as builder
import four_observation_protocol as protocol
import round2_hosted as hosted
import verify_round2_attempt_extension as source_verifier
from round2_attempt_extension_v1 import validate_extended_resume_ledger


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "round2_generated/attempt_extension_result_v1.json"
RUN_ROOT = (
    HERE
    / "round2_runs_20260920/terra_study_s00_repair"
    / "chronos-r2-terra-study-low-s00-repair-v1/1"
    / "gpt-5.6-terra/2659315"
)
OUTPUT_ROOT = RUN_ROOT / "round2_terra_reasoning_study_low_s00_repair_v1"

TOP_LEVEL_KEYS = {
    "schema",
    "result_manifest_sha256",
    "frozen_at",
    "status",
    "task",
    "run",
    "contract",
    "artifacts",
    "accounting",
    "quota",
    "hosted_audit_disposition",
}
ARTIFACT_PATHS = {
    "staged_source": source_verifier.GENERATED,
    "task": RUN_ROOT / "chronos-r2-terra-study-low-s00-repair-v1.task.json",
    "run": RUN_ROOT
    / "chronos-r2-terra-study-low-s00-repair-v1-run_id_Run_1_openai_gpt-5.6-terra.run.json",
    "result": RUN_ROOT
    / "chronos-r2-terra-study-low-s00-repair-v1-run_id_Run_1_openai_gpt-5.6-terra.result.json",
    "atif": RUN_ROOT
    / "chronos-r2-terra-study-low-s00-repair-v1-run_id_Run_1_openai_gpt-5.6-terra.atif.json",
    "intended_manifest": OUTPUT_ROOT / "intended_manifest.json",
    "audit": OUTPUT_ROOT / "audit.json",
    "evidence": OUTPUT_ROOT / "openai_gpt-5.6-terra.jsonl",
}
ACCOUNTING_KEYS = {
    "events",
    "started_attempts",
    "observed_invocations",
    "complete_calls",
    "failed_calls",
    "completed_jobs",
    "known_cost_usd",
    "unknown_cost_calls",
    "invalid_json_lines",
    "accounting_complete",
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(body: dict) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(raw)


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text())
        if value is None
        else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid attempt-extension result manifest schema")
    body = {
        key: item
        for key, item in manifest.items()
        if key != "result_manifest_sha256"
    }
    if _canonical_hash(body) != manifest["result_manifest_sha256"]:
        raise ValueError("attempt-extension result manifest self-hash mismatch")
    return manifest


def _read_artifacts(manifest: dict) -> dict[str, bytes]:
    records = manifest["artifacts"]
    if set(records) != set(ARTIFACT_PATHS):
        raise ValueError("attempt-extension result artifact set changed")
    blobs = {}
    for label, expected_path in ARTIFACT_PATHS.items():
        record = records[label]
        if set(record) != {"path", "sha256", "bytes"}:
            raise ValueError(f"invalid pinned artifact record: {label}")
        path = (ROOT / record["path"]).resolve()
        if path != expected_path.resolve():
            raise ValueError(f"pinned artifact path changed: {label}")
        if path != ROOT.resolve() and ROOT.resolve() not in path.parents:
            raise ValueError(f"pinned artifact escapes the repository: {label}")
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
            raise ValueError(f"pinned artifact hash/size mismatch: {label}")
        blobs[label] = raw
    return blobs


def _json_object(raw: bytes, label: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _assert_close(left: float, right: float, label: str) -> None:
    if not math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{label} differs")


def _assert_accounting(actual: dict, expected: dict, label: str) -> None:
    if set(actual) != ACCOUNTING_KEYS or set(expected) != ACCOUNTING_KEYS:
        raise ValueError(f"{label} accounting schema changed")
    actual_cost = actual["known_cost_usd"]
    expected_cost = expected["known_cost_usd"]
    _assert_close(actual_cost, expected_cost, f"{label} cost")
    without_cost = ACCOUNTING_KEYS - {"known_cost_usd"}
    if any(actual[key] != expected[key] for key in without_cost):
        raise ValueError(f"{label} accounting differs")


def _verify_manifest_contract(manifest: dict, planned: dict) -> None:
    contract = planned["contract"]
    expected_task = {
        "owner": "masihmaafi",
        "name": builder.TASK_NAME,
        "version": 1,
        "url": (
            "https://www.kaggle.com/benchmarks/tasks/masihmaafi/"
            "chronos-r2-terra-study-low-s00-repair-v1/1"
        ),
    }
    expected_run = {
        "id": 2659315,
        "number": 1,
        "model": builder.MODEL,
        "state": "BENCHMARK_TASK_RUN_STATE_COMPLETED",
        "started_at": "2026-09-20T15:28:30.632141Z",
        "finished_at": "2026-09-20T15:32:45.610851Z",
    }
    expected_contract = {
        "study_id": builder.STUDY_ID,
        "reasoning": builder.REASONING,
        "shard_index": builder.SHARD_INDEX,
        "shard_count": builder.SHARD_COUNT,
        "job_count": 69,
        "planned_calls": 217,
        "authorized_job_id": builder.AUTHORIZED_JOB_ID,
        "completed_attempt": 4,
        "parent_path": str(builder.PARENT_PATH.relative_to(ROOT)),
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "parent_ledger_bytes": contract["parent_ledger_bytes"],
        "attempt_extension_manifest_sha256": contract[
            "attempt_extension_manifest_sha256"
        ],
    }
    if (
        manifest["schema"] != "chronos.attempt-extension-result.v1"
        or manifest["status"] != "complete_strictly_verified"
        or manifest["task"] != expected_task
        or manifest["run"] != expected_run
        or manifest["contract"] != expected_contract
    ):
        raise ValueError("attempt-extension result contract changed")
    try:
        frozen = datetime.fromisoformat(manifest["frozen_at"])
    except (TypeError, ValueError) as error:
        raise ValueError("invalid result freeze timestamp") from error
    if frozen.tzinfo is None:
        raise ValueError("result freeze timestamp is not timezone aware")


def _verify_kaggle_metadata(manifest: dict, blobs: dict[str, bytes]) -> None:
    task = _json_object(blobs["task"], "task metadata")
    run = _json_object(blobs["run"], "run metadata")
    result = _json_object(blobs["result"], "result metadata")
    atif = _json_object(blobs["atif"], "ATIF metadata")
    task_name = manifest["task"]["name"]
    model = manifest["run"]["model"]
    started = manifest["run"]["started_at"]
    finished = manifest["run"]["finished_at"]

    source = blobs["staged_source"].decode("utf-8")
    marker = f'@kbench.task(name="{task_name}")'
    start = source.rindex(marker)
    end = source.index("\nhosted_cell.run", start)
    uploaded_definition = source[start:end].rstrip("\n") + "\n"
    if task != {
        "versionNumber": 1,
        "name": task_name,
        "definition": uploaded_definition,
    }:
        raise ValueError("downloaded Kaggle task differs from the staged source")
    run_task = run.get("taskVersion") or {}
    if (
        run_task.get("versionNumber") != task["versionNumber"]
        or run_task.get("name") != task["name"]
        or run_task.get("definition") != task["definition"]
        or run_task.get("description") != ""
        or (run.get("modelVersion") or {}).get("slug") != model
        or run.get("pyRunId") != f"{task_name}-Run #1"
        or run.get("state") != manifest["run"]["state"]
        or run.get("startTime") != started
        or run.get("endTime") != finished
    ):
        raise ValueError("downloaded Kaggle run metadata changed")
    if (
        result.get("task_name") != task_name
        or result.get("trial_name") != f"{task_name}-Run #1"
        or result.get("started_at") != started
        or result.get("finished_at") != finished
        or ((result.get("agent_info") or {}).get("model_info") or {}).get("name")
        != model
        or (((result.get("verifier_result") or {}).get("rewards") or {}).get("score"))
        != 1.0
    ):
        raise ValueError("downloaded Kaggle result metadata changed")
    kbench = ((atif.get("extra") or {}).get("kbench") or {})
    atif_task = kbench.get("task_version") or {}
    if (
        atif.get("schema_version") != "ATIF-v1.7"
        or atif.get("session_id") != f"{task_name}-Run #1"
        or atif.get("trajectory_id") != f"{task_name}-Run #1"
        or (atif.get("agent") or {}).get("model_name") != model
        or atif_task.get("version_number") != 1
        or atif_task.get("name") != task_name
        or atif_task.get("definition") != uploaded_definition
        or kbench.get("state") != manifest["run"]["state"]
        or kbench.get("end_time") != finished
    ):
        raise ValueError("downloaded ATIF metadata changed")


def _strict_result_audit(
    manifest: dict, planned: dict, blobs: dict[str, bytes]
) -> dict:
    contract = planned["contract"]
    jobs = planned["jobs"]
    parent = planned["parent"]
    evidence = blobs["evidence"]
    if not evidence.startswith(parent):
        raise ValueError("repair evidence does not preserve the exact parent prefix")
    if len(parent) != manifest["contract"]["parent_ledger_bytes"]:
        raise ValueError("repair parent byte count differs")
    suffix = evidence[len(parent) :]
    events = hosted.parse_jsonl_bytes(evidence, label="repair evidence")
    suffix_events = hosted.parse_jsonl_bytes(suffix, label="repair suffix")

    full_accounting = hosted.raw_event_summary(events)
    suffix_accounting = hosted.raw_event_summary(suffix_events)
    _assert_accounting(
        full_accounting, manifest["accounting"]["full"], "full repair"
    )
    _assert_accounting(
        suffix_accounting,
        manifest["accounting"]["new_suffix"],
        "new repair suffix",
    )

    previous = (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    )
    protocol.engine.MODELS = (builder.MODEL,)
    protocol.engine.STUDY_ID = builder.STUDY_ID
    protocol.engine.CALL_SETTINGS = {
        key: value
        for key, value in contract["call_settings"].items()
        if key != "sdk_max_retries"
    }
    try:
        full_jobs = protocol.jobs_for(builder.MODEL, "study")

        def structural_audit(candidate: list[dict]) -> dict:
            return amended_audit.audit(
                candidate,
                builder.MODEL,
                "study",
                authorized_job_id=builder.AUTHORIZED_JOB_ID,
                require_complete=False,
            )

        ledger = validate_extended_resume_ledger(
            events,
            model=builder.MODEL,
            identity=contract["identity"],
            expected_jobs={job["id"]: job for job in jobs},
            authorized_job_id=builder.AUTHORIZED_JOB_ID,
            structural_audit=structural_audit,
        )
        structural = structural_audit(events)
        subset = hosted.subset_summary(events, {job["id"] for job in jobs})
    finally:
        (
            protocol.engine.MODELS,
            protocol.engine.STUDY_ID,
            protocol.engine.CALL_SETTINGS,
        ) = previous

    if (
        ledger["completed_jobs"] != 69
        or ledger["incomplete_jobs"]
        or ledger["authorized_next_attempt"] is not None
        or ledger["observed_invocations"] != 241
        or ledger["failed_calls"] != 6
    ):
        raise ValueError("strict extended-ledger disposition is not complete")
    _assert_close(ledger["known_cost_usd"], 0.669912, "extended-ledger cost")
    if (
        subset["complete"] is not True
        or subset["completed_jobs"] != 69
        or subset["missing_job_ids"]
        or subset["unknown_cost_calls"] != 0
    ):
        raise ValueError("strict shard-subset audit is not complete")

    shard_ids = {job["id"] for job in jobs}
    full_ids = {job["id"] for job in full_jobs}
    missing = set(structural["missing_jobs"])
    if (
        len(full_jobs) != 690
        or len(shard_ids) != 69
        or structural["complete"] is not False
        or structural["completed_jobs"] != 69
        or structural["unknown_cost_calls"] != 0
        or len(missing) != 621
        or missing != full_ids - shard_ids
    ):
        raise ValueError("full-study structural scope explanation is not exact")

    terminal_starts = [
        event["attempt"]
        for event in events
        if hosted.event_job_id(event) == builder.AUTHORIZED_JOB_ID
        and event["event"] == "job_started"
    ]
    terminal_completions = [
        event["attempt"]
        for event in events
        if hosted.event_job_id(event) == builder.AUTHORIZED_JOB_ID
        and event["event"] == "job_complete"
    ]
    other_max_attempt = max(
        attempt
        for job_id, attempt in ledger["max_attempt_by_job"].items()
        if job_id != builder.AUTHORIZED_JOB_ID
    )
    if (
        terminal_starts != [1, 2, 3, 4]
        or terminal_completions != [4]
        or ledger["max_attempt_by_job"][builder.AUTHORIZED_JOB_ID] != 4
        or other_max_attempt > 3
    ):
        raise ValueError("authorized attempt-extension topology changed")

    audit = _json_object(blobs["audit"], "hosted audit")
    expected_audit_keys = set(contract) | {
        "passed",
        "ledger_audit",
        "structural_audit",
        "subset",
        "allocation_exhausted",
        "stopped_early",
        "terminal_error",
        "transient_waits",
        "evidence_sha256",
        "raw_accounting",
        "new_suffix_accounting",
        "parent_prefix_preserved",
    }
    if set(audit) != expected_audit_keys:
        raise ValueError("hosted audit success-path schema changed")
    if any(audit[key] != value for key, value in contract.items()):
        raise ValueError("hosted audit contract differs from the frozen repair")
    hosted_subset = dict(audit["subset"])
    rebuilt_subset = dict(subset)
    hosted_subset_cost = hosted_subset.pop("known_cost_usd", None)
    rebuilt_subset_cost = rebuilt_subset.pop("known_cost_usd", None)
    subset_matches = hosted_subset == rebuilt_subset
    try:
        _assert_close(
            hosted_subset_cost,
            rebuilt_subset_cost,
            "hosted/rebuilt subset cost",
        )
    except (TypeError, ValueError):
        subset_matches = False
    if (
        audit["ledger_audit"] != ledger
        or audit["structural_audit"] != structural
        or not subset_matches
        or audit["evidence_sha256"] != _sha256(evidence)
    ):
        raise ValueError("hosted audit differs from independent reconstruction")
    _assert_accounting(audit["raw_accounting"], full_accounting, "hosted full")
    _assert_accounting(
        audit["new_suffix_accounting"], suffix_accounting, "hosted suffix"
    )

    pass_components = {
        "ledger_complete": ledger["completed_jobs"] == contract["job_count"],
        "subset_complete": subset["complete"],
        "structural_complete": structural["complete"],
        "allocation_available": not audit["allocation_exhausted"],
        "not_stopped": audit["stopped_early"] is None,
    }
    false_components = {
        label for label, passed in pass_components.items() if not passed
    }
    if (
        audit["passed"] is not False
        or "audit_failed" in audit
        or audit["allocation_exhausted"] is not False
        or audit["stopped_early"] is not None
        or audit["terminal_error"] is not None
        or audit["parent_prefix_preserved"] is not True
        or false_components != {"structural_complete"}
    ):
        raise ValueError("hosted false pass flag has a cause beyond shard scope")

    intended = _json_object(blobs["intended_manifest"], "intended manifest")
    expected_intended = dict(
        contract,
        jobs=jobs,
        parent_audit=contract["parent_ledger_audit"],
    )
    if intended != expected_intended:
        raise ValueError("downloaded intended manifest differs from the exact plan")

    return {
        "ledger": ledger,
        "structural": structural,
        "subset": subset,
        "full_accounting": full_accounting,
        "suffix_accounting": suffix_accounting,
        "other_max_attempt": other_max_attempt,
        "false_components": sorted(false_components),
    }


def _verify_quota_and_disposition(manifest: dict, audited: dict) -> None:
    quota = manifest["quota"]
    if set(quota) != {
        "currency",
        "pre_run",
        "post_run",
        "observed_delta",
        "matches_new_suffix_accounting",
    }:
        raise ValueError("quota record schema changed")
    if (
        quota["currency"] != "USD"
        or quota["pre_run"]
        != {
            "used": 0.3693179999999998,
            "total_allowed": 10,
            "queried_at": None,
            "timestamp_recorded": False,
        }
        or quota["post_run"]
        != {
            "used": 0.7003459999999997,
            "total_allowed": 10,
            "query_started_at": "2026-09-20T15:34:49.871381+00:00",
            "query_finished_at": "2026-09-20T15:34:51.546762+00:00",
        }
        or quota["matches_new_suffix_accounting"] is not True
    ):
        raise ValueError("quota attestation record changed")
    delta = quota["post_run"]["used"] - quota["pre_run"]["used"]
    _assert_close(delta, quota["observed_delta"], "quota delta")
    _assert_close(
        quota["observed_delta"],
        audited["suffix_accounting"]["known_cost_usd"],
        "quota/suffix cost",
    )

    expected_disposition = {
        "reported_passed": False,
        "audit_failed_present": False,
        "allocation_exhausted": False,
        "stopped_early": None,
        "terminal_error": None,
        "parent_prefix_preserved": True,
        "false_component": "structural_audit.complete",
        "full_study_missing_jobs_outside_shard": 621,
        "scope_explanation": (
            "The amended structural auditor reports completeness against all 690 "
            "study jobs, while this execution intentionally contains only shard "
            "00's 69 jobs."
        ),
        "local_strict_disposition": "pass_complete_shard",
    }
    if manifest["hosted_audit_disposition"] != expected_disposition:
        raise ValueError("hosted audit disposition record changed")


def verify(manifest_value: dict | None = None) -> dict:
    """Rebuild the task, pin every artifact, and independently audit the result."""
    manifest = _load_manifest(manifest_value)
    blobs = _read_artifacts(manifest)
    source = source_verifier.verify(blobs["staged_source"])
    planned = builder.plan_repair()
    _verify_manifest_contract(manifest, planned)
    _verify_kaggle_metadata(manifest, blobs)
    audited = _strict_result_audit(manifest, planned, blobs)
    _verify_quota_and_disposition(manifest, audited)
    return {
        "schema": "chronos.attempt-extension-result-verification.v1",
        "result_manifest_sha256": manifest["result_manifest_sha256"],
        "source_sha256": source["generated_sha256"],
        "evidence_sha256": manifest["artifacts"]["evidence"]["sha256"],
        "task": manifest["task"]["name"],
        "run_id": manifest["run"]["id"],
        "status": manifest["status"],
        "completed_jobs": audited["ledger"]["completed_jobs"],
        "job_count": manifest["contract"]["job_count"],
        "authorized_completed_attempt": manifest["contract"]["completed_attempt"],
        "observed_invocations": audited["full_accounting"][
            "observed_invocations"
        ],
        "failed_calls": audited["full_accounting"]["failed_calls"],
        "known_cost_usd": audited["full_accounting"]["known_cost_usd"],
        "new_invocations": audited["suffix_accounting"][
            "observed_invocations"
        ],
        "new_failed_calls": audited["suffix_accounting"]["failed_calls"],
        "new_cost_usd": audited["suffix_accounting"]["known_cost_usd"],
        "hosted_reported_passed": False,
        "hosted_false_component": audited["false_components"][0],
        "local_strict_disposition": "pass_complete_shard",
    }


def main() -> None:
    checked = verify()
    print(
        "PASS {task}: {completed_jobs}/{job_count} jobs, attempt {attempt}, "
        "{calls} invocations (${cost:.6f}); new suffix {new_calls} "
        "invocations (${new_cost:.6f}); hosted false flag isolated to "
        "full-study scope".format(
            task=checked["task"],
            completed_jobs=checked["completed_jobs"],
            job_count=checked["job_count"],
            attempt=checked["authorized_completed_attempt"],
            calls=checked["observed_invocations"],
            cost=checked["known_cost_usd"],
            new_calls=checked["new_invocations"],
            new_cost=checked["new_cost_usd"],
        )
    )


if __name__ == "__main__":
    main()
