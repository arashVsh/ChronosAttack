"""Verify and seal the bounded Claude replacement-preflight result."""

from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from build_hosted_cell_v2 import build_preflight_receipt
from capture_benchmark_quota_v1 import verify_attestation
import four_observation_protocol as protocol
from round2_hosted import raw_event_summary
import verify_round2_claude_preflight_retry as prelaunch_verifier


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "round2_generated/claude_preflight_retry_result_v1.json"
FROZEN_AT = "2026-09-20T21:19:19+03:30"
TASK = prelaunch_verifier.TASK
MODEL = prelaunch_verifier.MODEL
REASONING = prelaunch_verifier.REASONING
STUDY_ID = prelaunch_verifier.STUDY_ID
RUN_ID = 2671436
PRELAUNCH_HASH = (
    "08d9874958ba8a826527dcf3672a46124eb0ee52e13e6a5e9262692b5edcd765"
)
PRIOR_DAILY_COST_USD = 8.555856

RUN_ROOT = (
    HERE
    / "round2_runs_20260920/claude_minimal_retry"
    / f"{TASK}/1/claude-sonnet-4-6-default/{RUN_ID}"
)
OUTPUT_ROOT = RUN_ROOT / prelaunch_verifier.OUTPUT_FOLDER
PREFIX = f"{TASK}-run_id_Run_1_anthropic_claude-sonnet-4-6default"
ARTIFACT_PATHS = {
    "amendment": prelaunch_verifier.AMENDMENT,
    "prelaunch_manifest": prelaunch_verifier.MANIFEST,
    "source": prelaunch_verifier.SOURCE,
    "task": RUN_ROOT / f"{TASK}.task.json",
    "run": RUN_ROOT / f"{PREFIX}.run.json",
    "result": RUN_ROOT / f"{PREFIX}.result.json",
    "atif": RUN_ROOT / f"{PREFIX}.atif.json",
    "intended_manifest": OUTPUT_ROOT / "intended_manifest.json",
    "audit": OUTPUT_ROOT / "audit.json",
    "evidence": OUTPUT_ROOT / f"{MODEL.replace('/', '_')}.jsonl",
    "terminal": OUTPUT_ROOT / "reasoning_terminal.json",
    "quota_attestation": OUTPUT_ROOT / "quota_attestation_1.json",
}

TOP_LEVEL_KEYS = {
    "schema",
    "result_manifest_sha256",
    "frozen_at",
    "status",
    "prelaunch_retry_manifest_sha256",
    "task",
    "run",
    "outcome",
    "artifacts",
    "accounting",
    "quota",
}
FILE_RECORD_KEYS = {"path", "sha256", "bytes"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(raw)


def _manifest_hash(manifest: dict) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key != "result_manifest_sha256"
    }
    return _canonical_hash(body)


def _repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _file_record(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": _repo_relative(path),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _read_pinned(record: dict, expected: Path, label: str) -> bytes:
    if set(record) != FILE_RECORD_KEYS:
        raise ValueError(f"invalid pinned file record: {label}")
    path = (ROOT / record["path"]).resolve()
    if path != expected.resolve():
        raise ValueError(f"pinned path changed: {label}")
    if path != ROOT.resolve() and ROOT.resolve() not in path.parents:
        raise ValueError(f"pinned path escapes repository: {label}")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
        raise ValueError(f"pinned hash/size mismatch: {label}")
    return raw


def _json(raw: bytes, label: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _assignments(source: str) -> dict:
    values = {}
    for node in ast.parse(source, str(prelaunch_verifier.SOURCE)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def build_manifest() -> dict:
    result = json.loads(ARTIFACT_PATHS["result"].read_text())
    evidence = ARTIFACT_PATHS["evidence"].read_bytes()
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    quota = json.loads(ARTIFACT_PATHS["quota_attestation"].read_text())
    manifest = {
        "schema": "chronos.round2.claude-preflight-retry-result.v1",
        "result_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "operationally_unavailable_after_bounded_retry",
        "prelaunch_retry_manifest_sha256": PRELAUNCH_HASH,
        "task": {
            "owner": "masihmaafi",
            "name": TASK,
            "version": 1,
            "url": f"https://www.kaggle.com/benchmarks/tasks/masihmaafi/{TASK}/1",
        },
        "run": {
            "id": RUN_ID,
            "number": 1,
            "model": MODEL,
            "state": "BENCHMARK_TASK_RUN_STATE_COMPLETED",
            "started_at": result["started_at"],
            "finished_at": result["finished_at"],
        },
        "outcome": {
            "reasoning_setting_resolved": False,
            "minimal_supported": None,
            "low_authorized": False,
            "further_retry_authorized": False,
            "receipt_issued": False,
            "error_type": "InternalServerError",
            "status_code": 500,
            "raw_completion": None,
            "decision_rule": "second_generic_failure_stops_claude_branch",
        },
        "artifacts": {
            label: _file_record(path) for label, path in ARTIFACT_PATHS.items()
        },
        "accounting": {
            "raw": summary,
            "resolved_incremental_cost_usd": 0.0,
        },
        "quota": {
            "prior_known_daily_cost_usd": PRIOR_DAILY_COST_USD,
            "observed_daily_cost_usd": quota["response"][
                "daily_quota_used_usd"
            ],
            "resolved_incremental_cost_usd": (
                quota["response"]["daily_quota_used_usd"]
                - PRIOR_DAILY_COST_USD
            ),
            "attestation_sha256": quota["attestation_sha256"],
        },
    }
    manifest["result_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Claude retry-result manifest schema")
    if _manifest_hash(manifest) != manifest["result_manifest_sha256"]:
        raise ValueError("Claude retry-result manifest self-hash mismatch")
    if (
        manifest["schema"]
        != "chronos.round2.claude-preflight-retry-result.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["status"]
        != "operationally_unavailable_after_bounded_retry"
        or manifest["prelaunch_retry_manifest_sha256"] != PRELAUNCH_HASH
    ):
        raise ValueError("Claude retry-result top-level contract changed")
    return manifest


def _uploaded_definition(source: str) -> str:
    marker = f"@kbench.task(name={TASK!r})"
    start = source.rindex(marker)
    end = source.index("\nhosted_cell.run", start)
    return source[start:end].rstrip("\n") + "\n"


def _verify_metadata(manifest: dict, blobs: dict[str, bytes], source: str) -> None:
    task = _json(blobs["task"], "task metadata")
    run = _json(blobs["run"], "run metadata")
    result = _json(blobs["result"], "result metadata")
    atif = _json(blobs["atif"], "ATIF metadata")
    definition = _uploaded_definition(source)
    if task != {"versionNumber": 1, "name": TASK, "definition": definition}:
        raise ValueError("downloaded Claude task differs from staged source")
    expected_run = manifest["run"]
    run_task = run.get("taskVersion") or {}
    if (
        run_task.get("versionNumber") != 1
        or run_task.get("name") != TASK
        or run_task.get("definition") != definition
        or run.get("modelVersion", {}).get("slug") != MODEL
        or run.get("pyRunId") != f"{TASK}-Run #1"
        or run.get("state") != expected_run["state"]
        or run.get("startTime") != expected_run["started_at"]
        or run.get("endTime") != expected_run["finished_at"]
    ):
        raise ValueError("downloaded Claude run metadata changed")
    if (
        result.get("task_name") != TASK
        or result.get("trial_name") != f"{TASK}-Run #1"
        or result.get("started_at") != expected_run["started_at"]
        or result.get("finished_at") != expected_run["finished_at"]
        or result.get("agent_info", {}).get("model_info", {}).get("name")
        != MODEL
        or result.get("verifier_result", {}).get("rewards", {}).get("score")
        != 1.0
    ):
        raise ValueError("downloaded Claude result metadata changed")
    kbench = atif.get("extra", {}).get("kbench", {})
    atif_task = kbench.get("task_version", {})
    if (
        atif.get("schema_version") != "ATIF-v1.7"
        or atif.get("session_id") != f"{TASK}-Run #1"
        or atif.get("trajectory_id") != f"{TASK}-Run #1"
        or atif.get("agent", {}).get("model_name") != MODEL
        or atif_task.get("version_number") != 1
        or atif_task.get("name") != TASK
        or atif_task.get("definition") != definition
        or kbench.get("state") != expected_run["state"]
        or kbench.get("end_time") != expected_run["finished_at"]
    ):
        raise ValueError("downloaded Claude ATIF metadata changed")


def _verify_execution(
    manifest: dict, blobs: dict[str, bytes], source_values: dict
) -> dict:
    contract = source_values["CONTRACT"]
    jobs = source_values["EXPECTED_JOBS"]
    intended = _json(blobs["intended_manifest"], "intended manifest")
    expected_intended = dict(
        contract, jobs=jobs, seed_audit=contract["resume_ledger"]
    )
    if intended != expected_intended:
        raise ValueError("downloaded Claude intended manifest changed")
    evidence = blobs["evidence"]
    if not evidence.endswith(b"\n"):
        raise ValueError("Claude retry evidence is not newline terminated")
    events = [json.loads(line) for line in evidence.splitlines()]
    if len(events) != 3:
        raise ValueError("Claude retry did not stop on exactly one invocation")
    started, failed, errored = events
    first_job = jobs[0]
    fixture = protocol.fixtures()[first_job["scenario"]]
    expected_prompt = protocol.step_prompt(fixture, first_job["order"][0], 1)
    if (
        [event.get("event") for event in events]
        != ["job_started", "call_failed", "job_error"]
        or any(event.get("attempt") != 1 for event in events)
        or any(event.get("identity") != contract["identity"] for event in events)
        or any(event.get("model") != MODEL for event in events)
        or started.get("job_id") != first_job["id"]
        or failed.get("job_id") != first_job["id"]
        or failed.get("step") != 1
        or failed.get("schema") != "State"
        or failed.get("user_prompt") != expected_prompt
        or failed.get("error_type") != "InternalServerError"
        or failed.get("raw_completion") is not None
        or failed.get("cost_usd") is not None
        or errored.get("job") != first_job
        or errored.get("error_type") != "InternalServerError"
    ):
        raise ValueError("Claude retry evidence topology or prompt changed")
    usage = failed.get("usage") or {}
    if any(value is not None for value in usage.values()):
        raise ValueError("Claude retry unexpectedly contains completion telemetry")

    summary = raw_event_summary(events)
    if (
        summary["events"] != 3
        or summary["started_attempts"] != 1
        or summary["observed_invocations"] != 1
        or summary["complete_calls"] != 0
        or summary["failed_calls"] != 1
        or summary["completed_jobs"] != 0
        or summary["known_cost_usd"] != 0.0
        or summary["unknown_cost_calls"] != 1
        or summary["accounting_complete"] is not False
    ):
        raise ValueError("Claude retry raw accounting changed")
    if manifest["accounting"] != {
        "raw": summary,
        "resolved_incremental_cost_usd": 0.0,
    }:
        raise ValueError("Claude retry manifest accounting differs")

    terminal = _json(blobs["terminal"], "reasoning terminal")
    error = terminal.get("error") or {}
    if (
        terminal.get("model") != MODEL
        or terminal.get("reasoning") != REASONING
        or terminal.get("study_id") != STUDY_ID
        or terminal.get("identity") != contract["identity"]
        or terminal.get("manifest_sha256") != contract["manifest_sha256"]
        or terminal.get("evidence_sha256") != _sha256(evidence)
        or terminal.get("planned_calls") != 10
        or terminal.get("transient_waits") != {"count": 0, "seconds": 0}
        or terminal.get("minimal_unsupported_receipt_sha256") is not None
        or error.get("type") != "InternalServerError"
        or error.get("status_code") != 500
        or "internal server error" not in str(error.get("message") or "").lower()
    ):
        raise ValueError("Claude retry terminal changed")

    audit = _json(blobs["audit"], "hosted audit")
    if (
        audit.get("passed") is not False
        or audit.get("allocation_exhausted") is not False
        or audit.get("parent_prefix_preserved") is not True
        or audit.get("terminal_error") != error
        or audit.get("evidence_sha256") != _sha256(evidence)
        or audit.get("raw_accounting") != summary
        or audit.get("new_suffix_accounting") != summary
        or audit.get("transient_waits") != {"count": 0, "seconds": 0}
        or "unknown or invalid call cost" not in audit.get("audit_failed", "")
    ):
        raise ValueError("Claude retry hosted audit changed")
    for key, value in contract.items():
        if audit.get(key) != value:
            raise ValueError(f"Claude retry hosted contract differs: {key}")

    quota = _json(blobs["quota_attestation"], "quota attestation")
    verify_attestation(quota, evidence, blobs["terminal"])
    query_time = datetime.fromisoformat(quota["queried_at_start_utc"])
    last_event = max(datetime.fromisoformat(event["timestamp"]) for event in events)
    observed = quota["response"]["daily_quota_used_usd"]
    if (
        (query_time - last_event).total_seconds() < 300
        or not math.isclose(
            observed, PRIOR_DAILY_COST_USD, rel_tol=0.0, abs_tol=1e-12
        )
        or quota["run_context"]["task"] != TASK
        or quota["run_context"]["run_id"] != RUN_ID
    ):
        raise ValueError("Claude retry quota did not settle at zero increment")
    expected_quota = {
        "prior_known_daily_cost_usd": PRIOR_DAILY_COST_USD,
        "observed_daily_cost_usd": observed,
        "resolved_incremental_cost_usd": 0.0,
        "attestation_sha256": quota["attestation_sha256"],
    }
    if manifest["quota"] != expected_quota:
        raise ValueError("Claude retry quota record differs")
    try:
        build_preflight_receipt(
            evidence,
            terminal,
            quota_attestation=quota,
            terminal_raw=blobs["terminal"],
        )
    except ValueError:
        pass
    else:
        raise ValueError("generic Claude failure incorrectly issued a receipt")
    return {
        "summary": summary,
        "evidence_sha256": _sha256(evidence),
        "attestation_sha256": quota["attestation_sha256"],
    }


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    prelaunch = prelaunch_verifier.verify()
    if prelaunch["retry_manifest_sha256"] != PRELAUNCH_HASH:
        raise ValueError("Claude retry prelaunch seal changed")
    if set(manifest["artifacts"]) != set(ARTIFACT_PATHS):
        raise ValueError("Claude retry-result artifact set changed")
    blobs = {
        label: _read_pinned(
            manifest["artifacts"][label], path, f"Claude result {label}"
        )
        for label, path in ARTIFACT_PATHS.items()
    }
    if _sha256(blobs["prelaunch_manifest"]) != _sha256(
        prelaunch_verifier.MANIFEST.read_bytes()
    ):
        raise ValueError("Claude retry prelaunch artifact changed")
    source = blobs["source"].decode("utf-8")
    source_values = _assignments(source)
    expected_task = {
        "owner": "masihmaafi",
        "name": TASK,
        "version": 1,
        "url": f"https://www.kaggle.com/benchmarks/tasks/masihmaafi/{TASK}/1",
    }
    expected_run_prefix = {
        "id": RUN_ID,
        "number": 1,
        "model": MODEL,
        "state": "BENCHMARK_TASK_RUN_STATE_COMPLETED",
    }
    if manifest["task"] != expected_task or any(
        manifest["run"].get(key) != value
        for key, value in expected_run_prefix.items()
    ):
        raise ValueError("Claude retry task or run identity changed")
    result = _json(blobs["result"], "result metadata")
    if (
        manifest["run"].get("started_at") != result.get("started_at")
        or manifest["run"].get("finished_at") != result.get("finished_at")
    ):
        raise ValueError("Claude retry recorded timestamps changed")
    expected_outcome = {
        "reasoning_setting_resolved": False,
        "minimal_supported": None,
        "low_authorized": False,
        "further_retry_authorized": False,
        "receipt_issued": False,
        "error_type": "InternalServerError",
        "status_code": 500,
        "raw_completion": None,
        "decision_rule": "second_generic_failure_stops_claude_branch",
    }
    if manifest["outcome"] != expected_outcome:
        raise ValueError("Claude retry outcome disposition changed")
    _verify_metadata(manifest, blobs, source)
    checked = _verify_execution(manifest, blobs, source_values)
    return {
        "schema": "chronos.round2.claude-preflight-retry-result-verification.v1",
        "result_manifest_sha256": manifest["result_manifest_sha256"],
        "status": manifest["status"],
        "task": TASK,
        "run_id": RUN_ID,
        "observed_invocations": checked["summary"]["observed_invocations"],
        "unknown_cost_invocations": checked["summary"]["unknown_cost_calls"],
        "resolved_incremental_cost_usd": manifest["accounting"][
            "resolved_incremental_cost_usd"
        ],
        "known_daily_cost_usd": manifest["quota"]["observed_daily_cost_usd"],
        "evidence_sha256": checked["evidence_sha256"],
        "attestation_sha256": checked["attestation_sha256"],
        "receipt_issued": manifest["outcome"]["receipt_issued"],
        "further_retry_authorized": manifest["outcome"][
            "further_retry_authorized"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST}")
    checked = verify()
    print(
        "CLAUDE MATCHED REASONING UNAVAILABLE: run {run_id} repeated the generic "
        "HTTP 500 on its first request; {observed_invocations} raw invocation, "
        "${resolved_incremental_cost_usd:.6f} settled increment, no receipt and "
        "no further retry authorized; daily total ${known_daily_cost_usd:.6f}".format(
            **checked
        )
    )


if __name__ == "__main__":
    main()
