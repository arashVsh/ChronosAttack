"""Independently revalidate downloaded Experiment B pilot and study evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import audit_experiment_b as auditor
import build_experiment_b_hosted_v1 as builder
import experiment_b_protocol as protocol
import issue_experiment_b_pilot_receipt_v1 as receipts
from round2_hosted import (
    parse_jsonl_bytes,
    raw_event_summary,
    subset_summary,
    validate_resume_ledger,
)
import verify_experiment_a_pilot_collection as platform_checks
import verify_experiment_b_pilot_tasks as pilot_tasks


ROOT = Path(__file__).resolve().parent.parent
COLLECTION_MANIFEST = ROOT / "kaggle/round2_generated/experiment_b_collection_v1.json"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _one(directory: Path, pattern: str) -> Path:
    matches = list(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {pattern} in {directory}")
    return matches[0]


def _json(raw: bytes, label: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _same_costed_summary(actual: dict, expected: dict) -> bool:
    """Compare raw-replayed counts exactly and only tolerate float-sum noise."""
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    cost = actual.get("known_cost_usd")
    reference = expected.get("known_cost_usd")
    if not (
        isinstance(cost, (int, float))
        and not isinstance(cost, bool)
        and isinstance(reference, (int, float))
        and not isinstance(reference, bool)
        and math.isclose(cost, reference, rel_tol=0, abs_tol=1e-12)
    ):
        return False
    return {key: value for key, value in actual.items() if key != "known_cost_usd"} == {
        key: value for key, value in expected.items() if key != "known_cost_usd"
    }


def verify_raw_pilot(
    *,
    model: str,
    evidence: bytes,
    terminal: bytes,
    intended: bytes,
    hosted_audit: bytes,
) -> dict:
    receipt = receipts.issue_receipt(
        evidence=evidence,
        terminal=terminal,
        intended=intended,
        model=model,
    )
    events = parse_jsonl_bytes(evidence, label="B pilot ledger")
    plan = builder.plan_cell(model=model, phase="pilot")
    structural = auditor.audit(events, model, "pilot")
    ledger = validate_resume_ledger(
        events,
        model=model,
        identity=plan["identity"],
        expected_jobs={job["id"]: job for job in plan["jobs"]},
        structural_audit=lambda rows: auditor.audit(rows, model, "pilot", require_complete=False),
    )
    raw_accounting = raw_event_summary(events)
    subset = subset_summary(events, {job["id"] for job in plan["jobs"]})
    intended_value = _json(intended, "B intended manifest")
    checked = _json(hosted_audit, "B hosted audit")
    if (
        checked.get("schema") != "chronos.experiment-b-hosted-audit.v1"
        or checked.get("passed") is not True
        or checked.get("contract") != {key: value for key, value in intended_value.items() if key != "jobs"}
        or not _same_costed_summary(checked.get("ledger_audit"), ledger)
        or not _same_costed_summary(checked.get("structural_audit"), structural)
        or not _same_costed_summary(checked.get("subset"), subset)
        or not _same_costed_summary(checked.get("raw_accounting"), raw_accounting)
        or checked.get("parent_prefix_preserved") is not True
        or checked.get("evidence_sha256") != _sha256(evidence)
        or checked.get("terminal_error") is not None
    ):
        raise ValueError("B hosted pilot audit disagrees with independent raw replay")
    return {
        "model": model,
        "reasoning": receipt["reasoning"],
        "role": receipt["role"],
        "jobs": 2,
        "planned_calls": 10,
        "observed_invocations": 10,
        "known_cost_usd": receipt["known_cost_usd"],
        "evidence_sha256": _sha256(evidence),
        "terminal_sha256": _sha256(terminal),
        "intended_manifest_sha256": _sha256(intended),
        "hosted_audit_sha256": _sha256(hosted_audit),
        "receipt": receipt,
    }


def verify_downloaded_pilot(*, run_root: Path, model: str) -> dict:
    pilot_tasks.verify()
    manifest = json.loads(pilot_tasks.MANIFEST.read_text())
    records = [task for task in manifest["tasks"] if task["model"] == model]
    if len(records) != 1:
        raise ValueError("B pilot model has no frozen staged task")
    record = records[0]
    source_path = pilot_tasks.ROOT / record["source_path"]
    source = source_path.read_bytes()
    if _sha256(source) != record["source_sha256"]:
        raise ValueError("B staged pilot source changed")
    output = run_root / record["output_folder"]
    metadata = {
        "frozen_source": source_path,
        "notebook": run_root / "__notebook__.ipynb",
        "task_metadata": _one(run_root, "*.task.json"),
        "run_metadata": _one(run_root, "*.run.json"),
        "result_metadata": _one(run_root, "*.result.json"),
        "atif_metadata": _one(run_root, "*.atif.json"),
    }
    platform = platform_checks._verify_platform_metadata(
        {"task": record["task_name"], "model": model}, metadata
    )
    evidence = (output / (model.replace("/", "_") + ".jsonl")).read_bytes()
    terminal = (output / "terminal.json").read_bytes()
    intended = (output / "intended_manifest.json").read_bytes()
    hosted_audit = (output / "audit.json").read_bytes()
    source_hashes = _json(intended, "B intended manifest")["source_sha256"]
    for name, expected in source_hashes.items():
        embedded = (run_root / (record["output_folder"] + "_source") / name).read_bytes()
        local = (builder.HERE / name).read_bytes()
        if embedded != local or _sha256(embedded) != expected:
            raise ValueError(f"B downloaded embedded source changed: {name}")
    checked = verify_raw_pilot(
        model=model,
        evidence=evidence,
        terminal=terminal,
        intended=intended,
        hosted_audit=hosted_audit,
    )
    return {
        **checked,
        "task": record["task_name"],
        "source_sha256": record["source_sha256"],
        "platform": platform,
    }


def verify_raw_study_shard(
    *,
    model: str,
    shard_index: int,
    evidence: bytes,
    terminal: bytes,
    intended: bytes,
    hosted_audit: bytes,
    parent_ledger: bytes,
    pilot_receipt: dict,
    pilot_evidence: bytes,
    pilot_terminal: bytes,
    pilot_intended: bytes,
) -> dict:
    receipts.validate_receipt(
        pilot_receipt,
        evidence=pilot_evidence,
        terminal=pilot_terminal,
        intended=pilot_intended,
    )
    if not evidence.startswith(parent_ledger):
        raise ValueError("B study shard did not preserve parent ledger bytes")
    plan = builder.plan_cell(
        model=model,
        phase="study",
        shard_index=shard_index,
        resume_seed=parent_ledger,
    )
    intended_value = _json(intended, "B study intended manifest")
    contract = {key: value for key, value in intended_value.items() if key != "jobs"}
    terminal_value = _json(terminal, "B study terminal")
    _, source_hashes = builder._sources()
    if (
        intended_value.get("jobs") != plan["jobs"]
        or any(contract.get(key) != value for key, value in plan.items() if key != "jobs")
        or set(contract) != (set(plan) - {"jobs"}) | {
            "pilot_receipt_sha256", "parent_ledger_sha256", "incremental_ceiling_usd",
            "effective_ceiling_usd", "source_sha256", "sdk_max_retries",
        }
        or contract.get("pilot_receipt_sha256") != pilot_receipt["receipt_sha256"]
        or contract.get("parent_ledger_sha256") != (_sha256(parent_ledger) if parent_ledger else None)
        or contract.get("incremental_ceiling_usd") != builder.study_ceiling_from_pilot(pilot_receipt)
        or contract.get("effective_ceiling_usd") != round(
            plan["resume_ledger"]["known_cost_usd"]
            + builder.study_ceiling_from_pilot(pilot_receipt), 9
        )
        or contract.get("source_sha256") != source_hashes
        or contract.get("sdk_max_retries") != 0
        or terminal_value.get("schema") != "chronos.experiment-b-terminal.v1"
        or terminal_value.get("phase") != "study"
        or terminal_value.get("model") != model
        or terminal_value.get("reasoning") != protocol.cell(model)["reasoning"]
        or terminal_value.get("role") != protocol.cell(model)["role"]
        or terminal_value.get("study_id") != protocol.cell(model)["study_id"]
        or terminal_value.get("identity") != plan["identity"]
        or terminal_value.get("fixture_manifest_sha256") != plan["fixture_manifest_sha256"]
        or terminal_value.get("jobs_sha256") != plan["jobs_sha256"]
        or terminal_value.get("job_ids") != [job["id"] for job in plan["jobs"]]
        or terminal_value.get("planned_calls") != plan["planned_calls"]
        or terminal_value.get("call_settings") != {
            **protocol.call_settings(model), "sdk_max_retries": 0
        }
        or terminal_value.get("source_sha256") != source_hashes
        or terminal_value.get("evidence_sha256") != _sha256(evidence)
        or terminal_value.get("parent_ledger_sha256") != contract.get("parent_ledger_sha256")
        or terminal_value.get("pilot_receipt_sha256") != pilot_receipt["receipt_sha256"]
        or terminal_value.get("error") is not None
    ):
        raise ValueError("B study terminal or intended contract changed")
    events = parse_jsonl_bytes(evidence, label="B study ledger")
    ledger = validate_resume_ledger(
        events,
        model=model,
        identity=plan["identity"],
        expected_jobs={job["id"]: job for job in plan["jobs"]},
        structural_audit=lambda rows: auditor.audit(rows, model, "study", require_complete=False),
    )
    structural = auditor.audit(events, model, "study", require_complete=False)
    subset = subset_summary(events, {job["id"] for job in plan["jobs"]})
    accounting = raw_event_summary(events)
    hosted = _json(hosted_audit, "B study hosted audit")
    if (
        not subset["complete"]
        or not accounting["accounting_complete"]
        or hosted.get("schema") != "chronos.experiment-b-hosted-audit.v1"
        or hosted.get("passed") is not True
        or hosted.get("contract") != contract
        or not _same_costed_summary(hosted.get("ledger_audit"), ledger)
        or not _same_costed_summary(hosted.get("structural_audit"), structural)
        or not _same_costed_summary(hosted.get("subset"), subset)
        or not _same_costed_summary(hosted.get("raw_accounting"), accounting)
        or hosted.get("parent_prefix_preserved") is not True
        or hosted.get("evidence_sha256") != _sha256(evidence)
        or hosted.get("terminal_error") is not None
    ):
        raise ValueError("B hosted study audit disagrees with independent raw replay")
    suffix = evidence[len(parent_ledger):]
    suffix_events = parse_jsonl_bytes(suffix, label="B new study suffix")
    suffix_cost = raw_event_summary(suffix_events)
    return {
        "model": model,
        "shard_index": shard_index,
        "jobs": 6,
        "planned_calls": 30,
        "known_cost_usd": accounting["known_cost_usd"],
        "new_suffix_known_cost_usd": suffix_cost["known_cost_usd"],
        "observed_invocations": accounting["observed_invocations"],
        "failed_calls": accounting["failed_calls"],
        "evidence_sha256": _sha256(evidence),
        "terminal_sha256": _sha256(terminal),
        "intended_manifest_sha256": _sha256(intended),
        "hosted_audit_sha256": _sha256(hosted_audit),
        "completed_job_ids": sorted(
            event["job"]["id"] for event in events if event["event"] == "job_complete"
        ),
    }


def verify_study_cell(records: list[dict], model: str) -> dict:
    if len(records) != builder.SHARD_COUNT:
        raise ValueError("B study cell requires all 30 distinct shards")
    if {record["shard_index"] for record in records} != set(range(builder.SHARD_COUNT)):
        raise ValueError("B study shard index partition changed")
    if any(record["model"] != model or record["jobs"] != 6 or record["planned_calls"] != 30 for record in records):
        raise ValueError("B study shard model/topology mismatch")
    job_ids = [job_id for record in records for job_id in record["completed_job_ids"]]
    expected = {job["id"] for job in protocol.jobs_for(model)}
    if len(job_ids) != 180 or set(job_ids) != expected:
        raise ValueError("B study cell has missing or duplicate completed jobs")
    return {
        "model": model,
        "role": protocol.cell(model)["role"],
        "shards": 30,
        "completed_jobs": 180,
        "planned_calls": 900,
        "observed_invocations": sum(record["observed_invocations"] for record in records),
        "known_cost_usd": math.fsum(record["known_cost_usd"] for record in records),
        "failed_calls": sum(record["failed_calls"] for record in records),
    }


def verify_downloaded_study_s00(*, run_root: Path, pilot_run_root: Path, model: str) -> dict:
    """Authenticate and replay one downloaded first-batch study shard."""
    import verify_experiment_b_study_batch00_tasks as tasks

    tasks.verify()
    manifest = json.loads(tasks.MANIFEST.read_text())
    matches = [task for task in manifest["tasks"] if task["model"] == model]
    if len(matches) != 1:
        raise ValueError("B model has no pilot-authorized s00 study task")
    task = matches[0]
    if task["shard_index"] != 0:
        raise ValueError("B first study shard index changed")
    pilot = verify_downloaded_pilot(run_root=pilot_run_root, model=model)
    _, pilot_raw = tasks._pilot(model)
    source_path = ROOT / task["source_path"]
    source = source_path.read_bytes()
    if _sha256(source) != task["source_sha256"] or len(source) != task["source_bytes"]:
        raise ValueError("B study s00 staged source changed")
    metadata = {
        "frozen_source": source_path,
        "notebook": run_root / "__notebook__.ipynb",
        "task_metadata": run_root / f"{task['task_name']}.task.json",
        "run_metadata": _one(run_root, "*.run.json"),
        "result_metadata": _one(run_root, "*.result.json"),
        "atif_metadata": _one(run_root, "*.atif.json"),
    }
    platform = platform_checks._verify_platform_metadata(
        {"task": task["task_name"], "model": model}, metadata
    )
    output = run_root / task["output_folder"]
    evidence = (output / (model.replace("/", "_") + ".jsonl")).read_bytes()
    terminal = (output / "terminal.json").read_bytes()
    intended = (output / "intended_manifest.json").read_bytes()
    hosted_audit = (output / "audit.json").read_bytes()
    embedded_root = run_root / (task["output_folder"] + "_source")
    for name, expected in _json(intended, "B study intended manifest")["source_sha256"].items():
        embedded = (embedded_root / name).read_bytes()
        if embedded != (builder.HERE / name).read_bytes() or _sha256(embedded) != expected:
            raise ValueError(f"B downloaded study embedded source changed: {name}")
    checked = verify_raw_study_shard(
        model=model, shard_index=0, evidence=evidence, terminal=terminal,
        intended=intended, hosted_audit=hosted_audit, parent_ledger=b"",
        pilot_receipt=pilot["receipt"], pilot_evidence=pilot_raw["evidence"],
        pilot_terminal=pilot_raw["terminal"], pilot_intended=pilot_raw["intended"],
    )
    return {
        **checked,
        "task": task["task_name"],
        "source_sha256": task["source_sha256"],
        "platform": platform,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-run-root", type=Path, required=True)
    parser.add_argument("--model", choices=tuple(protocol.CELLS), required=True)
    parser.add_argument("--study-s00-run-root", type=Path)
    args = parser.parse_args()
    result = (
        verify_downloaded_study_s00(
            run_root=args.study_s00_run_root,
            pilot_run_root=args.pilot_run_root,
            model=args.model,
        )
        if args.study_s00_run_root else
        verify_downloaded_pilot(run_root=args.pilot_run_root, model=args.model)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
