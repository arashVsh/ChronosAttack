"""C collection replay with one explicit, account-reconciled Qwen s02 resume.

All ordinary shards delegate unchanged to the frozen v1 verifier. Only a
version-2 run of the pinned Qwen s02 task may use the derived zero-cost view;
the raw v1 null-cost event and cumulative byte prefix remain mandatory.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from unittest import mock

import build_experiment_c_qwen_s02_resume_v1 as repair
import experiment_c_qwen_s02_reconciled_view_v1 as view
import round2_hosted as hosted
import verify_experiment_c_collection_v1 as v1


def _special(run: dict, task: dict) -> bool:
    return (
        task.get("task_name") == repair.TASK
        and run.get("task_name") == repair.TASK
        and run.get("task_version") == 2
        and run.get("parent_ledger") is not None
    )


def _verify_reconciled_run(run: dict, task: dict, staged: dict,
                           *, require_claims: bool = True) -> dict:
    if not _special(run, task) or set(run) != v1.RUN_KEYS:
        raise ValueError("C reconciled run is not exact Qwen s02 task v2")
    run_root = v1._path(run["run_root"])
    output = run_root / task["output_folder"]
    source_path = v1._path(run["artifacts"]["frozen_source"]["path"])
    expected = {
        "frozen_source": source_path,
        "contract": source_path.with_suffix(".contract.json"),
        "prelaunch_receipt": source_path.with_suffix(".prelaunch.json"),
        "notebook": run_root / "__notebook__.ipynb",
        "task_metadata": run_root / f"{task['task_name']}.task.json",
        "evidence": output / (task["model"].replace("/", "_") + ".jsonl"),
        "terminal": output / "terminal.json",
    }
    expected.update({key: v1._one(run_root, pattern) for key, pattern in v1.METADATA_PATTERNS.items()})
    if (not isinstance(run.get("artifacts"), dict)
            or set(run["artifacts"]) != v1.ARTIFACT_KEYS):
        raise ValueError("C reconciled run artifact set is incomplete")
    paths, raws = {}, {}
    for key, record in run["artifacts"].items():
        paths[key], raws[key] = v1._artifact(record, expected=expected[key])
    parent = v1._artifact(run["parent_ledger"])[1]
    if parent != repair.reconciliation.QWEN_RAW.read_bytes():
        raise ValueError("C reconciled resume parent differs from Qwen v1 raw")

    original_builder = v1.builder.build_source

    def variant_builder(*, contract, selection, task_name, output_folder, resume_seed):
        if task_name != repair.TASK or output_folder != repair.FOLDER:
            raise ValueError("C reconciled source changed its frozen task")
        return repair.build_source(
            contract, selection, resume_seed, standard_builder=original_builder,
        )

    with mock.patch.object(v1.builder, "build_source", side_effect=variant_builder):
        contract, selection, seed = v1._source_and_receipt(run, task, staged, paths, raws)
    if (seed != parent
            or contract.get("cost_reconciliation") != repair.reconciliation_record()):
        raise ValueError("C Qwen s02 cost reconciliation differs from official quota proof")
    platform = v1._platform(run, paths, raws["frozen_source"].decode("utf-8"), task["model"])
    jobs = {job["id"]: job for job in v1.protocol.jobs_for(task["model"], selection)
            if job["id"] in set(task["expected_job_ids"])}

    def structural(rows):
        return v1.auditor.audit(
            v1._normalize_consistency_transport(rows), task["model"], selection,
            require_complete=False, expected_job_ids=set(task["expected_job_ids"]),
        )

    checked_seed = hosted.validate_resume_ledger(
        view.normalized_cumulative(parent, parent), model=task["model"],
        identity=task["identity"], expected_jobs=jobs, structural_audit=structural,
    )
    if checked_seed != contract["resume_ledger"]:
        raise ValueError("C Qwen s02 normalized parent differs from prelaunch contract")
    evidence = raws["evidence"]
    normalized = view.normalized_cumulative(evidence, parent)
    events = hosted.parse_jsonl_bytes(evidence, label="C Qwen s02 cumulative raw ledger")
    audit = structural(normalized)
    raw_accounting = hosted.raw_event_summary(events)
    normalized_accounting = hosted.raw_event_summary(normalized)
    completed_ids = [event["job"]["id"] for event in events if event["event"] == "job_complete"]
    if (len(completed_ids) != len(set(completed_ids))
            or audit["completed_jobs"] != len(completed_ids)
            or audit["observed_invocations"] != normalized_accounting["observed_invocations"]
            or audit["failed_calls"] != normalized_accounting["failed_calls"]
            or audit["unknown_cost_calls"] != 0
            or normalized_accounting["unknown_cost_calls"] != 0
            or raw_accounting["unknown_cost_calls"] != 1
            or not math.isclose(audit["known_cost_usd"], raw_accounting["known_cost_usd"], rel_tol=0, abs_tol=1e-12)
            or not math.isclose(normalized_accounting["known_cost_usd"], raw_accounting["known_cost_usd"], rel_tol=0, abs_tol=1e-12)):
        raise ValueError("C Qwen s02 raw and reconciled replay disagree")
    terminal = v1._json(raws["terminal"], "Qwen s02 hosted terminal")
    stopped = terminal.get("stopped_early")
    complete = bool(audit["complete"] and stopped is None)
    transport_bug = "ValueError('24-order decisions/vote inputs changed')"
    hosted_bug = (terminal.get("status") == "stopped"
                  and terminal.get("audit_error") == transport_bug
                  and terminal.get("audit") is None)
    expected_terminal = {
        "schema": "chronos.experiment-c-hosted-terminal.v1",
        "task": task["task_name"],
        "contract_sha256": contract["contract_sha256"],
        "status": "stopped" if hosted_bug else "complete" if complete else "stopped",
        "stopped_early": stopped,
        "audit_error": transport_bug if hosted_bug else None,
        "audit": None if hosted_bug else audit,
        "raw_accounting": raw_accounting,
        "cost_reconciliation": contract["cost_reconciliation"],
    }
    if (terminal != expected_terminal
            or stopped is not None and (not isinstance(stopped, str) or not stopped)):
        raise ValueError("C Qwen s02 hosted terminal differs from exact reconciled replay")
    claims = {
        "complete": complete,
        "completed_job_ids": sorted(completed_ids),
        "observed_invocations": raw_accounting["observed_invocations"],
        "failed_calls": raw_accounting["failed_calls"],
        "known_cost_usd": raw_accounting["known_cost_usd"],
        "unknown_cost_calls": raw_accounting["unknown_cost_calls"],
    }
    if require_claims and any(run[key] != value for key, value in claims.items()):
        raise ValueError("C Qwen s02 run claims differ from raw replay")
    return {
        "shard_index": task["shard_index"], "task_name": task["task_name"],
        "run_id": platform["run_id"], "task_version": platform["task_version"],
        "complete": complete, "completed_job_ids": claims["completed_job_ids"],
        "planned_calls": task["planned_calls"],
        "observed_invocations": claims["observed_invocations"],
        "failed_calls": claims["failed_calls"],
        "known_cost_usd": claims["known_cost_usd"],
        "unknown_cost_calls": claims["unknown_cost_calls"],
        "stop_reason": stopped if not complete else None,
        "path": run["artifacts"]["evidence"]["path"],
        "sha256": run["artifacts"]["evidence"]["sha256"],
        "terminal_path": run["artifacts"]["terminal"]["path"],
        "terminal_sha256": run["artifacts"]["terminal"]["sha256"],
        "source_path": run["artifacts"]["frozen_source"]["path"],
        "source_sha256": run["artifacts"]["frozen_source"]["sha256"],
        "contract_sha256": contract["contract_sha256"],
        "prelaunch_receipt_sha256": run["artifacts"]["prelaunch_receipt"]["sha256"],
        "parent_ledger_sha256": contract["parent_ledger_sha256"],
        "platform": platform,
    }


_ORDINARY_VERIFY = v1._verify_run


def _dispatch(run: dict, task: dict, staged: dict, *, require_claims: bool = True) -> dict:
    if _special(run, task):
        return _verify_reconciled_run(run, task, staged, require_claims=require_claims)
    return _ORDINARY_VERIFY(run, task, staged, require_claims=require_claims)


def build_manifest_from_runs(specs: dict) -> dict:
    with mock.patch.object(v1, "_verify_run", side_effect=_dispatch):
        return v1.build_manifest_from_runs(specs)


def verify_collection_manifest(path: Path) -> dict:
    with mock.patch.object(v1, "_verify_run", side_effect=_dispatch):
        return v1.verify_collection_manifest(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-specs", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.run_specs is None:
        print(json.dumps(verify_collection_manifest(args.output), indent=2, sort_keys=True))
        return
    specs = json.loads(args.run_specs.read_text())
    result = build_manifest_from_runs(specs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(args.output, result["collection_sha256"])


if __name__ == "__main__":
    main()
