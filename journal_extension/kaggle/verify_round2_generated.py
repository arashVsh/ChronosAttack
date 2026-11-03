"""Verify staged reasoning-preflight sources and any pinned execution evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from build_hosted_cell_v2 import build_preflight_receipt
from capture_benchmark_quota_v1 import verify_attestation


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "round2_generated" / "manifest_v1.json"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pinned_file(record: dict, label: str) -> tuple[Path, bytes]:
    if set(record) != {"path", "sha256"}:
        raise ValueError(f"invalid pinned {label} record")
    path = (HERE / record["path"]).resolve()
    if HERE.resolve() not in path.parents:
        raise ValueError(f"pinned {label} escapes the kaggle directory")
    raw = path.read_bytes()
    if _sha256(raw) != record["sha256"]:
        raise ValueError(f"pinned {label} hash mismatch")
    return path, raw


def _verify_passed_execution(artifact: dict, execution: dict) -> dict:
    expected_keys = {
        "launched",
        "status",
        "task_version",
        "run_id",
        "kaggle_model_slug",
        "completed_at",
        "compatibility_observation",
        "observed_invocations",
        "known_cost_usd",
        "unknown_cost_invocations",
        "receipt_issued",
        "receipt_sha256",
        "artifacts",
    }
    if set(execution) != expected_keys or (
        execution["status"] != "passed"
        or execution["compatibility_observation"]
        != f"{artifact['reasoning']}_supported"
        or execution["observed_invocations"] != 10
        or execution["known_cost_usd"] <= 0
        or execution["unknown_cost_invocations"] != 0
        or execution["receipt_issued"] is not True
    ):
        raise ValueError(f"invalid passed execution state: {artifact['path']}")
    records = execution["artifacts"]
    if set(records) != {
        "evidence",
        "terminal",
        "intended_manifest",
        "audit",
        "receipt",
    }:
        raise ValueError(f"incomplete passed evidence: {artifact['path']}")
    _, evidence_raw = _pinned_file(records["evidence"], "evidence")
    _, terminal_raw = _pinned_file(records["terminal"], "terminal")
    _, intended_raw = _pinned_file(records["intended_manifest"], "intended manifest")
    _, audit_raw = _pinned_file(records["audit"], "audit")
    _, receipt_raw = _pinned_file(records["receipt"], "receipt")
    if not evidence_raw.endswith(b"\n"):
        raise ValueError("passed preflight evidence is not newline terminated")
    events = [json.loads(line) for line in evidence_raw.splitlines()]
    kinds = [event.get("event") for event in events]
    calls = [event for event in events if event.get("event") == "call_complete"]
    if (
        len(events) != 14
        or kinds.count("job_started") != 2
        or kinds.count("call_complete") != 10
        or kinds.count("job_complete") != 2
        or any(event.get("attempt") != 1 for event in events)
        or any(call.get("cost_usd") is None for call in calls)
        or any(kind in {"call_failed", "job_error"} for kind in kinds)
    ):
        raise ValueError("passed preflight does not have the exact 2-job/10-call topology")

    terminal = json.loads(terminal_raw)
    intended = json.loads(intended_raw)
    audit = json.loads(audit_raw)
    receipt = json.loads(receipt_raw)
    predecessor = artifact.get("predecessor_receipt_sha256")
    if (
        terminal.get("model") != artifact["model"]
        or terminal.get("reasoning") != artifact["reasoning"]
        or terminal.get("study_id") != artifact["study_id"]
        or terminal.get("evidence_sha256") != _sha256(evidence_raw)
        or terminal.get("error") is not None
        or terminal.get("transient_waits") != {"count": 0, "seconds": 0}
        or terminal.get("minimal_unsupported_receipt_sha256") != predecessor
    ):
        raise ValueError("passed terminal differs from the staged compatibility chain")
    if (
        intended.get("kind") != "preflight"
        or intended.get("model") != artifact["model"]
        or intended.get("reasoning") != artifact["reasoning"]
        or intended.get("study_id") != artifact["study_id"]
        or intended.get("planned_calls") != 10
        or intended.get("job_count") != 2
        or intended.get("incremental_ceiling_usd") != 0.25
        or intended.get("effective_ceiling_usd") != 0.25
        or intended.get("minimal_unsupported_receipt_sha256") != predecessor
    ):
        raise ValueError("passed intended manifest differs from the staged contract")
    accounting = audit.get("raw_accounting") or {}
    if (
        audit.get("passed") is not True
        or (audit.get("preflight") or {}).get("passed") is not True
        or audit.get("model") != artifact["model"]
        or audit.get("reasoning") != artifact["reasoning"]
        or audit.get("evidence_sha256") != _sha256(evidence_raw)
        or audit.get("minimal_unsupported_receipt_sha256") != predecessor
        or accounting.get("observed_invocations") != 10
        or accounting.get("unknown_cost_calls") != 0
        or accounting.get("known_cost_usd") != execution["known_cost_usd"]
    ):
        raise ValueError("passed audit does not match raw accounting")
    rebuilt_receipt = build_preflight_receipt(
        evidence_raw,
        terminal,
        terminal_raw=terminal_raw,
    )
    if (
        receipt != rebuilt_receipt
        or receipt.get("disposition") != "passed"
        or receipt.get("receipt_sha256") != execution["receipt_sha256"]
        or receipt.get("minimal_unsupported_receipt_sha256") != predecessor
    ):
        raise ValueError("passed receipt does not revalidate the compatibility chain")
    return {"launched": True, "status": "passed"}


def _verify_transient_execution(artifact: dict, execution: dict) -> dict:
    expected_keys = {
        "launched",
        "status",
        "task_version",
        "run_id",
        "kaggle_model_slug",
        "completed_at",
        "compatibility_observation",
        "observed_invocations",
        "raw_unknown_cost_invocations",
        "resolved_incremental_cost_usd",
        "prior_known_daily_quota_usd",
        "observed_daily_quota_usd",
        "receipt_issued",
        "artifacts",
    }
    if set(execution) != expected_keys or (
        execution["status"] != "transient_error_stopped"
        or execution["compatibility_observation"]
        != "unresolved_internal_server_error"
        or execution["observed_invocations"] != 1
        or execution["raw_unknown_cost_invocations"] != 1
        or execution["resolved_incremental_cost_usd"] != 0.0
        or not math.isclose(
            execution["prior_known_daily_quota_usd"],
            execution["observed_daily_quota_usd"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or execution["receipt_issued"] is not False
    ):
        raise ValueError(f"invalid transient execution state: {artifact['path']}")
    records = execution["artifacts"]
    if set(records) != {
        "evidence",
        "terminal",
        "intended_manifest",
        "audit",
        "quota_attestation",
    }:
        raise ValueError(f"incomplete transient evidence: {artifact['path']}")
    _, evidence_raw = _pinned_file(records["evidence"], "evidence")
    _, terminal_raw = _pinned_file(records["terminal"], "terminal")
    _, intended_raw = _pinned_file(records["intended_manifest"], "intended manifest")
    _, audit_raw = _pinned_file(records["audit"], "audit")
    _, quota_raw = _pinned_file(records["quota_attestation"], "quota attestation")
    if not evidence_raw.endswith(b"\n"):
        raise ValueError("transient preflight evidence is not newline terminated")
    events = [json.loads(line) for line in evidence_raw.splitlines()]
    if (
        [event.get("event") for event in events]
        != ["job_started", "call_failed", "job_error"]
        or any(event.get("attempt") != 1 for event in events)
        or events[1].get("step") != 1
        or events[1].get("raw_completion") is not None
        or events[1].get("cost_usd") is not None
        or events[1].get("error_type") != "InternalServerError"
        or events[2].get("error_type") != "InternalServerError"
    ):
        raise ValueError("transient preflight does not have the exact stopped topology")
    terminal = json.loads(terminal_raw)
    intended = json.loads(intended_raw)
    audit = json.loads(audit_raw)
    quota = json.loads(quota_raw)
    error = terminal.get("error") or {}
    if (
        terminal.get("model") != artifact["model"]
        or terminal.get("reasoning") != artifact["reasoning"]
        or terminal.get("study_id") != artifact["study_id"]
        or terminal.get("evidence_sha256") != _sha256(evidence_raw)
        or terminal.get("transient_waits") != {"count": 0, "seconds": 0}
        or error.get("status_code") != 500
        or error.get("type") != "InternalServerError"
        or "internal server error" not in str(error.get("message") or "").lower()
    ):
        raise ValueError("transient terminal does not prove the observed server error")
    if (
        intended.get("kind") != "preflight"
        or intended.get("model") != artifact["model"]
        or intended.get("reasoning") != artifact["reasoning"]
        or intended.get("study_id") != artifact["study_id"]
        or intended.get("planned_calls") != 10
        or intended.get("job_count") != 2
        or intended.get("incremental_ceiling_usd") != 0.25
        or intended.get("effective_ceiling_usd") != 0.25
    ):
        raise ValueError("transient intended manifest differs from the staged contract")
    accounting = audit.get("raw_accounting") or {}
    if (
        audit.get("passed") is not False
        or audit.get("model") != artifact["model"]
        or audit.get("reasoning") != artifact["reasoning"]
        or audit.get("evidence_sha256") != _sha256(evidence_raw)
        or accounting.get("observed_invocations") != 1
        or accounting.get("unknown_cost_calls") != 1
        or accounting.get("known_cost_usd") != 0.0
    ):
        raise ValueError("transient audit does not preserve raw unknown-cost accounting")
    verify_attestation(quota, evidence_raw, terminal_raw)
    observed = quota["response"]["daily_quota_used_usd"]
    query_time = datetime.fromisoformat(quota["queried_at_start_utc"])
    last_event = max(
        datetime.fromisoformat(event["timestamp"]) for event in events
    )
    if (
        not math.isclose(
            observed, execution["observed_daily_quota_usd"], rel_tol=0.0, abs_tol=1e-12
        )
        or (query_time - last_event).total_seconds() < 300
    ):
        raise ValueError("transient quota balance is not settled or does not match")
    try:
        build_preflight_receipt(
            evidence_raw,
            terminal,
            quota_attestation=quota,
            terminal_raw=terminal_raw,
        )
    except ValueError:
        pass
    else:
        raise ValueError("generic server error incorrectly authorized a receipt")
    return {"launched": True, "status": "transient_error_stopped"}


def _verify_execution(artifact: dict) -> dict:
    execution = artifact.get("execution")
    if not isinstance(execution, dict):
        raise ValueError(f"missing execution state: {artifact['path']}")
    if not execution.get("launched"):
        if execution != {"launched": False, "status": "not_launched"}:
            raise ValueError(f"invalid unlaunched state: {artifact['path']}")
        return {"launched": False, "status": "not_launched"}
    if execution.get("status") == "passed":
        return _verify_passed_execution(artifact, execution)
    if execution.get("status") == "transient_error_stopped":
        return _verify_transient_execution(artifact, execution)

    expected_keys = {
        "launched",
        "status",
        "task_version",
        "run_id",
        "kaggle_model_slug",
        "completed_at",
        "compatibility_observation",
        "observed_invocations",
        "known_cost_usd",
        "unknown_cost_invocations",
        "cost_resolution",
        "receipt_issued",
        "receipt_sha256",
        "artifacts",
    }
    if set(execution) != expected_keys:
        raise ValueError(f"invalid launched execution schema: {artifact['path']}")
    if (
        execution["status"] != "minimal_unsupported_verified"
        or execution["compatibility_observation"]
        != "minimal_explicitly_unsupported"
        or execution["observed_invocations"] != 1
        or execution["known_cost_usd"] != 0.0
        or execution["unknown_cost_invocations"] != 1
        or execution["cost_resolution"] != "kaggle_daily_quota_attestation"
        or execution["receipt_issued"] is not True
    ):
        raise ValueError(f"invalid stopped execution state: {artifact['path']}")

    records = execution["artifacts"]
    if set(records) != {
        "evidence",
        "terminal",
        "intended_manifest",
        "audit",
        "quota_attestation",
        "receipt",
    }:
        raise ValueError(f"incomplete execution evidence: {artifact['path']}")
    _, evidence_raw = _pinned_file(records["evidence"], "evidence")
    _, terminal_raw = _pinned_file(records["terminal"], "terminal")
    _, intended_raw = _pinned_file(records["intended_manifest"], "intended manifest")
    _, audit_raw = _pinned_file(records["audit"], "audit")
    _, quota_raw = _pinned_file(records["quota_attestation"], "quota attestation")
    _, receipt_raw = _pinned_file(records["receipt"], "receipt")
    if not evidence_raw.endswith(b"\n"):
        raise ValueError("pinned preflight evidence is not newline terminated")
    events = [json.loads(line) for line in evidence_raw.splitlines()]
    if (
        [event.get("event") for event in events]
        != ["job_started", "call_failed", "job_error"]
        or any(event.get("attempt") != 1 for event in events)
        or events[1].get("step") != 1
        or events[1].get("raw_completion") is not None
        or events[1].get("cost_usd") is not None
    ):
        raise ValueError("pinned preflight evidence is not the stopped first-call topology")

    terminal = json.loads(terminal_raw)
    intended = json.loads(intended_raw)
    audit = json.loads(audit_raw)
    quota = json.loads(quota_raw)
    receipt = json.loads(receipt_raw)
    error = terminal.get("error") or {}
    error_text = str(error.get("message") or "").lower()
    if (
        terminal.get("model") != artifact["model"]
        or terminal.get("reasoning") != artifact["reasoning"]
        or terminal.get("study_id") != artifact["study_id"]
        or terminal.get("evidence_sha256") != _sha256(evidence_raw)
        or terminal.get("transient_waits") != {"count": 0, "seconds": 0}
        or error.get("status_code") != 400
        or error.get("type") != events[1].get("error_type")
        or "reasoning_effort" not in error_text
        or "minimal" not in error_text
        or "unsupported" not in error_text
    ):
        raise ValueError("pinned terminal does not prove the observed rejection")
    if (
        intended.get("kind") != "preflight"
        or intended.get("model") != artifact["model"]
        or intended.get("reasoning") != artifact["reasoning"]
        or intended.get("study_id") != artifact["study_id"]
        or intended.get("planned_calls") != 10
        or intended.get("job_count") != 2
        or intended.get("incremental_ceiling_usd") != 0.25
        or intended.get("effective_ceiling_usd") != 0.25
    ):
        raise ValueError("pinned intended manifest differs from the staged contract")
    accounting = audit.get("raw_accounting") or {}
    if (
        audit.get("passed") is not False
        or audit.get("model") != artifact["model"]
        or audit.get("reasoning") != artifact["reasoning"]
        or audit.get("evidence_sha256") != _sha256(evidence_raw)
        or accounting.get("observed_invocations") != 1
        or accounting.get("unknown_cost_calls") != 1
        or accounting.get("known_cost_usd") != 0.0
    ):
        raise ValueError("pinned audit does not preserve unknown-cost accounting")
    verify_attestation(quota, evidence_raw, terminal_raw)
    rebuilt_receipt = build_preflight_receipt(
        evidence_raw,
        terminal,
        quota_attestation=quota,
        terminal_raw=terminal_raw,
    )
    if (
        receipt != rebuilt_receipt
        or receipt.get("disposition") != "minimal_unsupported"
        or receipt.get("receipt_sha256") != execution["receipt_sha256"]
        or receipt.get("cost_resolution", {}).get("source")
        != "kaggle_daily_quota_attestation"
    ):
        raise ValueError("pinned receipt does not revalidate the compatibility chain")
    return {"launched": True, "status": execution["status"]}


def _literal_assignments(tree: ast.Module) -> dict:
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def _task_name(tree: ast.Module) -> str:
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "hosted_cell"
    )
    decorator = function.decorator_list[0]
    if not isinstance(decorator, ast.Call):
        raise ValueError("hosted_cell lacks the expected task decorator")
    keyword = next(item for item in decorator.keywords if item.arg == "name")
    value = ast.literal_eval(keyword.value)
    if not isinstance(value, str):
        raise ValueError("hosted task name is not literal")
    return value


def verify() -> list[dict]:
    manifest = json.loads(MANIFEST.read_text())
    if (
        set(manifest) != {"schema_version", "generated_offline", "artifacts"}
        or manifest["schema_version"] != 2
        or manifest["generated_offline"] is not True
        or len(manifest["artifacts"]) != 3
    ):
        raise ValueError("generated manifest is not the expected v2 schema")
    checked = []
    for artifact in manifest["artifacts"]:
        path = MANIFEST.parent / artifact["path"]
        raw = path.read_bytes()
        if len(raw) != artifact["bytes"]:
            raise ValueError(f"generated artifact size mismatch: {path.name}")
        if _sha256(raw) != artifact["sha256"]:
            raise ValueError(f"generated artifact hash mismatch: {path.name}")
        source = raw.decode("utf-8")
        compile(source, str(path), "exec")
        tree = ast.parse(source, str(path))
        values = _literal_assignments(tree)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            values["MODEL"] != artifact["model"]
            or values["REASONING"] != artifact["reasoning"]
            or values["STUDY_ID"] != artifact["study_id"]
            or values["KIND"] != "preflight"
            or values["OUTPUT_FOLDER"] != artifact["output_folder"]
            or _task_name(tree) != artifact["task"]
        ):
            raise ValueError(f"generated artifact identity mismatch: {path.name}")
        if (
            len(jobs) != 2
            or [job["condition"] for job in jobs] != ["natural", "attack"]
            or any(job["mode"] != "stateful" or job["rep"] != 1 for job in jobs)
            or sum(job["calls"] for job in jobs) != 10
        ):
            raise ValueError(f"generated preflight topology mismatch: {path.name}")
        if (
            contract["call_settings"]
            != {
                "temperature": 1,
                "reasoning": artifact["reasoning"],
                "max_completion_tokens": 256,
                "timeout": 30,
                "sdk_max_retries": 0,
            }
            or contract["incremental_ceiling_usd"] != 0.25
            or contract["effective_ceiling_usd"] != 0.25
            or values["MAX_WAIT_SECONDS"] != 0
            or contract["accepted_preflight_receipt_sha256"] is not None
            or contract["minimal_unsupported_receipt_sha256"]
            != artifact.get("predecessor_receipt_sha256")
            or (
                artifact["reasoning"] == "minimal"
                and artifact.get("predecessor_receipt_sha256") is not None
            )
            or (
                artifact["reasoning"] == "low"
                and artifact.get("predecessor_receipt_sha256") is None
            )
        ):
            raise ValueError(f"generated preflight gate mismatch: {path.name}")
        for name, content in values["SOURCES"].items():
            current = (HERE / name).read_text()
            digest = _sha256(current.encode("utf-8"))
            if content != current or values["SOURCE_SHA256"][name] != digest:
                raise ValueError(f"embedded source drift: {path.name}: {name}")
        if "reasoning_preflight.run_once(" not in source:
            raise ValueError(f"generated preflight bypasses exact runner: {path.name}")
        execution = _verify_execution(artifact)
        checked.append(
            {
                "path": str(path.relative_to(HERE.parent)),
                "sha256": artifact["sha256"],
                "model": artifact["model"],
                "planned_calls": 10,
                "launched": execution["launched"],
                "execution_status": execution["status"],
            }
        )
    return checked


def main() -> None:
    checked = verify()
    for artifact in checked:
        print(
            f"PASS {artifact['model']} preflight source: "
            f"{artifact['planned_calls']} calls {artifact['sha256']} "
            f"execution={artifact['execution_status']}"
        )
    launched = sum(item["launched"] for item in checked)
    print(
        f"ROUND2 GENERATED VERIFIED: {len(checked)} offline-generated "
        "preflight artifacts; "
        f"{launched} launched"
    )


if __name__ == "__main__":
    main()
