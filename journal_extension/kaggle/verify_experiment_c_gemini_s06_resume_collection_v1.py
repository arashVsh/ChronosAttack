"""Replay Gemini s06's one-event reconciled resume atop the s03 platform bridge.

Only s06 task v2 may use the in-memory zero-cost view; all downloaded raw
bytes, including the v1 null-cost 429, remain pinned and costed by raw suffix.
The existing s03 platform-version bridge retains its exact original scope.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
from unittest import mock

import build_experiment_c_gemini_s06_resume_v1 as repair
import experiment_c_gemini_s06_reconciled_view_v1 as view
import round2_hosted as hosted
import verify_experiment_c_collection_v1 as v1
import verify_experiment_c_gemini_s03_platform_bridge_v1 as bridge


SCHEMA = "chronos.experiment-c-collection-gemini-s06-reconciled-platform-bridge.v1"
_ORDINARY_VERIFY = v1._verify_run
RUN_ID = 2939189
RAW_SHA256 = "2c6994c12a0707f5aaad26a8345643caf56167caf722560572c7c3c8c64620b2"
SOURCE = "kaggle/round2_generated/tree4_c_gemini_minimal_s06_v1_resume_c9c9115e3d36a23f.py"
SOURCE_SHA256 = "7519e10b431cbb5015007901d766d617ae324c02512749b8390b31d935ffdfb8"
API_PATH = "kaggle/round2_generated/experiment_c_gemini_s06_v2_browser_list_runs_raw_20260924_v1.json"
API_SHA256 = "06efe56f3900a964f26d0b890fb4da29711f37052a241c405d3b4e51704c5874"
CANONICAL = ("kaggle/round2_runs_20260920/experiment_c_study/"
             f"gemini-minimal/{repair.TASK}/2")
ORIGINAL = f"{CANONICAL}/{repair.TASK}/2/gemini-3.6-flash/{RUN_ID}"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _browser_run() -> dict:
    raw = (bridge.ROOT / API_PATH).read_bytes()
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if _sha(raw) != API_SHA256:
        raise ValueError("C s06 browser run response bytes changed")
    response = json.loads(raw)
    if (set(response) != {"benchmarkTaskRuns", "totalResults"}
            or response["totalResults"] != 1
            or len(response["benchmarkTaskRuns"]) != 1):
        raise ValueError("C s06 browser run roster changed")
    run = response["benchmarkTaskRuns"][0]
    version = run.get("taskVersion") or {}
    model = run.get("modelVersion") or {}
    source = (bridge.ROOT / SOURCE).read_bytes()
    if (_sha(source) != SOURCE_SHA256
            or run.get("id") != RUN_ID
            or version.get("id") != 791207
            or version.get("taskId") != 306776
            or version.get("versionNumber") != 2
            or version.get("name") != repair.TASK
            or version.get("definition") != v1._hosted_definition(source.decode())
            or version.get("sourceKernelId") != 135679569
            or version.get("sourceKernelSessionId") != 352441527
            or run.get("outputKernelSessionId") != 352441527
            or model.get("modelProxySlug") != view.MODEL
            or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
            or len(run.get("results", [])) != 1
            or run["results"][0].get("booleanResult") is not True):
        raise ValueError("C s06 browser run is not the authorized v2 run")
    return run


def _download_digest() -> str:
    original = bridge.ROOT / ORIGINAL
    canonical = bridge.ROOT / CANONICAL
    files = sorted(path for path in original.rglob("*") if path.is_file())
    if len(files) < 10:
        raise ValueError("C s06 original run-ID download is incomplete")
    manifest = []
    for path in files:
        relative = path.relative_to(original)
        copied = canonical / relative
        if not copied.is_file() or copied.read_bytes() != path.read_bytes():
            raise ValueError("C s06 canonical run differs from original download")
        manifest.append((relative.as_posix(), _sha(path.read_bytes())))
    return v1._digest(manifest)


@contextmanager
def _s06_platform_bridge():
    run = _browser_run()
    download_digest = _download_digest()
    original_pin, original_platform = v1._pin_run, v1._platform

    def pin(run_root, source_path, task, parent_ledger_path=None):
        record = original_pin(run_root, source_path, task, parent_ledger_path)
        if record["run_root"] == CANONICAL:
            if (record["task_name"] != repair.TASK
                    or record["shard_index"] != 6
                    or record["artifacts"]["frozen_source"]["path"] != SOURCE
                    or record["task_version"] != 1):
                raise ValueError("C s06 platform bridge target differs")
            record["task_version"] = 2
        return record

    def platform(record, paths, source, model):
        if record.get("run_root") != CANONICAL:
            return original_platform(record, paths, source, model)
        if (record.get("task_version") != 2
                or record.get("task_name") != repair.TASK
                or model != view.MODEL or _sha(source.encode()) != SOURCE_SHA256):
            raise ValueError("C s06 platform bridge scope differs")
        locally_checked = original_platform(
            {**record, "task_version": 1}, paths, source, model)
        if (locally_checked["task_version"] != 1
                or locally_checked["start_time"] != run["startTime"]
                or locally_checked["end_time"] != run["endTime"]):
            raise ValueError("C s06 browser and downloaded execution disagree")
        return {**locally_checked, "task_version": 2}

    with mock.patch.object(v1, "_pin_run", side_effect=pin), mock.patch.object(
            v1, "_platform", side_effect=platform):
        yield download_digest


def _special(run: dict, task: dict) -> bool:
    return (task.get("task_name") == repair.TASK
            and run.get("task_name") == repair.TASK
            and run.get("task_version") == 2
            and run.get("parent_ledger") is not None)


def _verify_reconciled_run(run: dict, task: dict, staged: dict,
                           *, require_claims: bool = True) -> dict:
    if not _special(run, task) or set(run) != v1.RUN_KEYS:
        raise ValueError("C reconciled run is not exact Gemini s06 task v2")
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
    expected.update({key: v1._one(run_root, pattern)
                     for key, pattern in v1.METADATA_PATTERNS.items()})
    if (not isinstance(run.get("artifacts"), dict)
            or set(run["artifacts"]) != v1.ARTIFACT_KEYS):
        raise ValueError("C reconciled run artifact set is incomplete")
    paths, raws = {}, {}
    for key, record in run["artifacts"].items():
        paths[key], raws[key] = v1._artifact(record, expected=expected[key])
    parent = v1._artifact(run["parent_ledger"])[1]
    if parent != repair.reconciliation.RAW.read_bytes():
        raise ValueError("C reconciled parent differs from Gemini s06 v1 raw")

    original_builder = v1.builder.build_source

    def variant_builder(*, contract, selection, task_name, output_folder,
                        resume_seed):
        if task_name != repair.TASK or output_folder != repair.FOLDER:
            raise ValueError("C reconciled source changed its frozen task")
        return repair.build_source(
            contract, selection, resume_seed,
            standard_builder=original_builder)

    with mock.patch.object(v1.builder, "build_source", side_effect=variant_builder):
        contract, selection, seed = v1._source_and_receipt(
            run, task, staged, paths, raws)
    if (seed != parent or contract.get("cost_reconciliation")
            != repair.reconciliation_record()):
        raise ValueError("C Gemini s06 reconciliation differs from quota proof")
    platform = v1._platform(
        run, paths, raws["frozen_source"].decode("utf-8"), task["model"])
    jobs = {job["id"]: job for job in v1.protocol.jobs_for(task["model"], selection)
            if job["id"] in set(task["expected_job_ids"])}

    def structural(rows):
        return v1.auditor.audit(
            v1._normalize_consistency_transport(rows), task["model"], selection,
            require_complete=False,
            expected_job_ids=set(task["expected_job_ids"]))

    checked_seed = hosted.validate_resume_ledger(
        view.normalized_cumulative(parent, parent), model=task["model"],
        identity=task["identity"], expected_jobs=jobs,
        structural_audit=structural)
    if checked_seed != contract["resume_ledger"]:
        raise ValueError("C Gemini s06 normalized parent differs from contract")
    evidence = raws["evidence"]
    events = hosted.parse_jsonl_bytes(
        evidence, label="C Gemini s06 cumulative raw ledger")
    raw_accounting = hosted.raw_event_summary(events)
    repeated_429 = _sha(evidence) == RAW_SHA256
    if repeated_429:
        if (len(events) != 6
                or [event.get("event") for event in events[3:]]
                != ["job_started", "call_failed", "job_error"]
                or events[3].get("attempt") != 2
                or events[4].get("attempt") != 2
                or events[4].get("step") != 1
                or events[4].get("error_type") != "RateLimitError"
                or events[4].get("job_id") != view.JOB_ID
                or events[4].get("cost_usd") is not None
                or events[4].get("raw_completion") is not None
                or not isinstance(events[4].get("usage"), dict)
                or any(value is not None for value in events[4]["usage"].values())
                or events[5].get("attempt") != 2
                or events[5].get("error_type") != "RateLimitError"):
            raise ValueError("C Gemini s06 v2 is not the exact repeated 429")
        audit = structural(events)
        normalized_accounting = None
    else:
        normalized = view.normalized_cumulative(evidence, parent)
        audit = structural(normalized)
        normalized_accounting = hosted.raw_event_summary(normalized)
    completed_ids = [event["job"]["id"] for event in events
                     if event["event"] == "job_complete"]
    if (len(completed_ids) != len(set(completed_ids))
            or audit["completed_jobs"] != len(completed_ids)
            or audit["observed_invocations"] != raw_accounting["observed_invocations"]
            or audit["failed_calls"] != raw_accounting["failed_calls"]
            or (repeated_429 and audit["unknown_cost_calls"]
                != raw_accounting["unknown_cost_calls"])
            or not math.isclose(audit["known_cost_usd"], raw_accounting["known_cost_usd"],
                                rel_tol=0, abs_tol=1e-12)):
        raise ValueError("C Gemini s06 raw and reconciled replay disagree")
    if repeated_429:
        if (raw_accounting["unknown_cost_calls"] != 2
                or raw_accounting["failed_calls"] != 2
                or raw_accounting["observed_invocations"] != 2
                or completed_ids):
            raise ValueError("C Gemini s06 repeated 429 accounting differs")
    elif (audit["unknown_cost_calls"] != 0
          or normalized_accounting["unknown_cost_calls"] != 0
          or raw_accounting["unknown_cost_calls"] != 1
          or not math.isclose(normalized_accounting["known_cost_usd"],
                              raw_accounting["known_cost_usd"],
                              rel_tol=0, abs_tol=1e-12)):
        raise ValueError("C Gemini s06 normal resumed accounting differs")
    terminal = v1._json(raws["terminal"], "Gemini s06 hosted terminal")
    stopped = terminal.get("stopped_early")
    complete = bool(audit["complete"] and stopped is None and not repeated_429)
    transport_bug = "ValueError('24-order decisions/vote inputs changed')"
    hosted_bug = (terminal.get("status") == "stopped"
                  and terminal.get("audit_error") == transport_bug
                  and terminal.get("audit") is None)
    expected_terminal = {
        "schema": "chronos.experiment-c-hosted-terminal.v1",
        "task": task["task_name"],
        "contract_sha256": contract["contract_sha256"],
        "status": "stopped" if hosted_bug or repeated_429 else "complete" if complete else "stopped",
        "stopped_early": stopped,
        "audit_error": ("ValueError('another unknown-cost call remains')"
                        if repeated_429 else transport_bug if hosted_bug else None),
        "audit": None if hosted_bug or repeated_429 else audit,
        "raw_accounting": raw_accounting,
        "cost_reconciliation": contract["cost_reconciliation"],
    }
    if terminal != expected_terminal:
        differing = sorted(key for key in set(terminal) | set(expected_terminal)
                           if terminal.get(key) != expected_terminal.get(key))
        raise ValueError(f"C Gemini s06 terminal differs: {differing}")
    if (repeated_429 and run["artifacts"]["terminal"]["sha256"]
            != "bdbfaf541ea8591a24c4552f3f4da91b6a4a114215e74f8b83e6959c3c7ded83"):
        raise ValueError("C Gemini s06 repeated-429 terminal bytes changed")
    if stopped is not None and (not isinstance(stopped, str) or not stopped):
        raise ValueError("C Gemini s06 stopped reason is malformed")
    claims = {
        "complete": complete,
        "completed_job_ids": sorted(completed_ids),
        "observed_invocations": raw_accounting["observed_invocations"],
        "failed_calls": raw_accounting["failed_calls"],
        "known_cost_usd": raw_accounting["known_cost_usd"],
        "unknown_cost_calls": raw_accounting["unknown_cost_calls"],
    }
    if require_claims and any(run[key] != value for key, value in claims.items()):
        raise ValueError("C Gemini s06 run claims differ from raw replay")
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


def _dispatch(run: dict, task: dict, staged: dict,
              *, require_claims: bool = True) -> dict:
    if _special(run, task):
        return _verify_reconciled_run(run, task, staged,
                                      require_claims=require_claims)
    return _ORDINARY_VERIFY(run, task, staged,
                            require_claims=require_claims)


def build(run_specs_path: Path) -> dict:
    proof = repair.reconciliation_record()
    with _s06_platform_bridge() as download_digest:
        with mock.patch.object(repair, "reconciliation_record", return_value=proof):
            with mock.patch.object(v1, "_verify_run", side_effect=_dispatch):
                bridged = bridge.build(run_specs_path)
    body = {key: value for key, value in bridged.items()
            if key != "collection_sha256"}
    body["schema"] = SCHEMA
    body["reconciled_resume"] = {
        "schema": "chronos.experiment-c-gemini-s06-reconciled-resume.v1",
        "task": repair.TASK,
        "parent_raw_sha256": view.PARENT_SHA256,
        "failed_event_line_sha256": view.FAILED_LINE_SHA256,
        "cost_reconciliation": proof,
    }
    body["s06_platform_bridge"] = {
        "schema": "chronos.experiment-c-gemini-s06-platform-bridge.v1",
        "task": repair.TASK,
        "run_id": RUN_ID,
        "downloaded_task_version": 1,
        "browser_task_version": 2,
        "source_path": SOURCE,
        "source_sha256": SOURCE_SHA256,
        "browser_response_path": API_PATH,
        "browser_response_sha256": API_SHA256,
        "original_download_root": ORIGINAL,
        "original_download_digest": download_digest,
    }
    return {**body, "collection_sha256": v1._digest(body)}


def verify(path: Path) -> dict:
    saved = json.loads(path.read_text())
    provenance = saved.get("provenance_bridge") or {}
    specs_path = bridge.ROOT / provenance.get("run_specs_path", "")
    if not specs_path.is_file():
        raise ValueError("C resumed bridge run specs are missing")
    rebuilt = build(specs_path)
    if saved != rebuilt:
        raise ValueError("C resumed bridge collection differs from raw replay")
    return rebuilt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-specs", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.run_specs is None:
        result = verify(args.output)
    else:
        result = build(args.run_specs)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(args.output, result["collection_sha256"])


if __name__ == "__main__":
    main()
