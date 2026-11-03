"""Seal and independently verify Qwen Experiment A shards 00--07.

The hosted ``passed`` badge is not the authority.  This verifier pins every
downloaded artifact, reconstructs the uploaded notebook from the frozen local
source, replays the raw JSONL ledger and water-supply structural audit, checks
Kaggle task/run/result/ATIF metadata, and proves that the eight shards are a
disjoint deterministic subset of the 690-job cell.

Shard 07 is a technical relaunch.  Kaggle created the original task shell but
left it in ``UNSPECIFIED`` with no run.  The relaunch changes only the outer
task label and output-folder label; prompts, jobs, model settings, receipt gate,
identity, and cost ceiling are unchanged.
"""

from __future__ import annotations

import argparse
import ast
import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import audit_water_supply as water_audit
import build_experiment_a_cell_v1 as cell_builder
from round2_hosted import (
    raw_event_summary,
    select_shard,
    subset_summary,
    validate_resume_ledger,
)
import verify_experiment_a_pilot_collection as pilot_collection
import verify_experiment_a_qwen_batch00 as staged_batch
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_qwen_batch00"
MANIFEST = GENERATED / "experiment_a_qwen_batch00_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_qwen_batch00_tasks_v1.json"
SUPERSEDED_RECORD = RUNS / "s07_original_no_run_record_v1.json"

MODEL = "qwen/qwen3-235b-a22b-instruct-2507"
MODEL_SLUG = "qwen3-235b-a22b-instruct-2507"
MODEL_FILE = "qwen_qwen3-235b-a22b-instruct-2507.jsonl"
REASONING = "low"
ROLE = "matched_non_off_primary"
STUDY_ID = "chronos_round2_water4_study_qwen_low_v1"
FROZEN_AT = "2026-09-20T22:52:18+03:30"
PRE_BATCH_KNOWN_DAILY_COST_USD = 8.64577417
BATCH_KNOWN_COST_USD = 0.14562966
POST_BATCH_KNOWN_DAILY_COST_USD = 8.79140383


def _execution(
    index: int,
    *,
    run_id: int,
    run_folder: str,
    task: str | None = None,
    source: str | None = None,
    output_folder: str | None = None,
    kind: str = "baseline",
) -> dict:
    canonical_task = f"chronos-r2-water4-study-qwen-low-s{index:02d}-v1"
    canonical_source = f"water4_study_qwen_low_s{index:02d}_v1.py"
    canonical_output = f"round2_water4_study_qwen_low_s{index:02d}_v1"
    resolved_task = task or canonical_task
    run_root = (
        RUNS
        / run_folder
        / resolved_task
        / "1"
        / MODEL_SLUG
        / str(run_id)
    )
    return {
        "shard_index": index,
        "execution_kind": kind,
        "task": resolved_task,
        "run_id": run_id,
        "run_root": run_root,
        "output_folder": output_folder or canonical_output,
        "output_root": run_root / (output_folder or canonical_output),
        "source": GENERATED / (source or canonical_source),
    }


EXECUTIONS = (
    _execution(0, run_id=2678260, run_folder="s00"),
    _execution(1, run_id=2678364, run_folder="s01"),
    _execution(2, run_id=2679486, run_folder="s02"),
    _execution(3, run_id=2678366, run_folder="s03"),
    _execution(4, run_id=2679722, run_folder="s04"),
    _execution(5, run_id=2678365, run_folder="s05"),
    _execution(6, run_id=2678389, run_folder="s06"),
    _execution(
        7,
        run_id=2680779,
        run_folder="s07_relaunch",
        task="chronos-r2-water4-study-qwen-low-s07-relaunch-v1",
        source="water4_study_qwen_low_s07_relaunch_v1.py",
        output_folder="round2_water4_study_qwen_low_s07_relaunch_v1",
        kind="task_relaunch_after_no_run_build_stall",
    ),
)

TOP_LEVEL_KEYS = {
    "schema",
    "collection_manifest_sha256",
    "frozen_at",
    "batch",
    "model",
    "reasoning",
    "role",
    "study_id",
    "pilot_collection_manifest_sha256",
    "prelaunch_manifest",
    "superseded_no_run",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}
SHARD_KEYS = {
    "shard_index",
    "execution_kind",
    "task",
    "task_version",
    "run_id",
    "model",
    "started_at",
    "finished_at",
    "status",
    "source",
    "artifacts",
    "accounting",
    "hosted_audit_passed",
}
ACCOUNTING_KEYS = {
    "job_count",
    "planned_calls",
    "accounting_complete",
    "complete_calls",
    "completed_jobs",
    "events",
    "failed_calls",
    "invalid_json_lines",
    "known_cost_usd",
    "observed_invocations",
    "started_attempts",
    "unknown_cost_calls",
}
FILE_RECORD_KEYS = {"path", "sha256", "bytes"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _manifest_hash(manifest: dict) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key != "collection_manifest_sha256"
    }
    return _canonical_hash(body)


def _equal(left, right) -> bool:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _require_equal(left, right, label: str) -> None:
    if not _equal(left, right):
        raise ValueError(f"{label} differs")


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


def _assignments(source: str, path: Path) -> dict:
    values = {}
    for node in ast.parse(source, str(path)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def _source_arguments(execution: dict) -> dict:
    return {
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "shard_index": execution["shard_index"],
        "shard_count": cell_builder.SHARD_COUNT,
        "task_name": execution["task"],
        "output_folder": execution["output_folder"],
    }


@lru_cache(maxsize=None)
def _regenerated_source(index: int, task: str, output_folder: str) -> str:
    return cell_builder.build_source(
        model=MODEL,
        reasoning=REASONING,
        role=ROLE,
        study_id=STUDY_ID,
        shard_index=index,
        shard_count=cell_builder.SHARD_COUNT,
        task_name=task,
        output_folder=output_folder,
    )


@lru_cache(maxsize=1)
def _sealed_launch_inputs() -> tuple[dict, dict]:
    return pilot_collection.verify(), staged_batch.verify()


def _artifact_paths(execution: dict) -> dict[str, Path]:
    task = execution["task"]
    root = execution["run_root"]
    output = execution["output_root"]
    prefix = f"{task}-run_id_Run_1_{MODEL.replace('/', '_')}"
    return {
        "notebook": root / "__notebook__.ipynb",
        "task": root / f"{task}.task.json",
        "run": root / f"{prefix}.run.json",
        "result": root / f"{prefix}.result.json",
        "atif": root / f"{prefix}.atif.json",
        "intended_manifest": output / "intended_manifest.json",
        "terminal": output / "terminal.json",
        "audit": output / "audit.json",
        "evidence": output / MODEL_FILE,
    }


def _uploaded_definition(source: str, task: str) -> str:
    marker = f"@kbench.task(name={task!r})"
    start = source.rindex(marker)
    end = source.index("\nhosted_cell.run", start)
    return source[start:end].rstrip("\n") + "\n"


def _runtime():
    previous = (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    )
    protocol.engine.MODELS = tuple(
        dict.fromkeys((*protocol.engine.MODELS, MODEL))
    )
    protocol.engine.STUDY_ID = STUDY_ID
    protocol.engine.CALL_SETTINGS = {
        "temperature": 1,
        "reasoning": REASONING,
        "max_completion_tokens": 256,
        "timeout": 30,
    }
    return previous


def _restore_runtime(previous) -> None:
    (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    ) = previous


def _jobs_for_shard(index: int) -> tuple[list[dict], list[dict]]:
    previous = _runtime()
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")
        jobs = select_shard(
            full_jobs,
            shard_index=index,
            shard_count=cell_builder.SHARD_COUNT,
        )
    finally:
        _restore_runtime(previous)
    return full_jobs, jobs


def _accounting(jobs: list[dict], summary: dict) -> dict:
    return {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        **{
            key: round(value, 12) if key == "known_cost_usd" else value
            for key, value in summary.items()
        },
    }


def _build_shard_record(execution: dict) -> dict:
    source = execution["source"].read_text()
    values = _assignments(source, execution["source"])
    jobs = values["EXPECTED_JOBS"]
    artifacts = _artifact_paths(execution)
    evidence = artifacts["evidence"].read_bytes()
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    result = json.loads(artifacts["result"].read_text())
    audit = json.loads(artifacts["audit"].read_text())
    return {
        "shard_index": execution["shard_index"],
        "execution_kind": execution["execution_kind"],
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "started_at": result["started_at"],
        "finished_at": result["finished_at"],
        "status": "complete_strictly_verified",
        "source": _file_record(execution["source"]),
        "artifacts": {
            label: _file_record(path) for label, path in artifacts.items()
        },
        "accounting": _accounting(jobs, summary),
        "hosted_audit_passed": audit.get("passed"),
    }


def _verify_superseded_record(record: dict) -> None:
    raw = _read_pinned(
        record["record"], SUPERSEDED_RECORD, "superseded shard 07 record"
    )
    observed = _json(raw, "superseded shard 07 record")
    expected_keys = {
        "browser_heading",
        "browser_pipeline_steps",
        "checked_at",
        "cli_status_conclusion",
        "model_run_observed",
        "original_created_at",
        "original_status",
        "original_task",
        "original_task_url",
        "original_task_version",
        "recovery_reason",
        "relaunch_run_id",
        "relaunch_source_sha256",
        "relaunch_task",
        "relaunch_task_version",
        "schema",
        "scientific_changes",
        "technical_changes",
    }
    relaunch = EXECUTIONS[-1]
    if (
        set(record) != {"status", "record"}
        or record["status"] != "superseded_before_any_model_run"
        or set(observed) != expected_keys
        or observed["schema"]
        != "chronos.kaggle-task-no-run-supersession.v1"
        or observed["original_task"]
        != "chronos-r2-water4-study-qwen-low-s07-v1"
        or observed["original_task_version"] != 1
        or observed["original_status"] != "UNSPECIFIED"
        or observed["model_run_observed"] is not False
        or observed["scientific_changes"] != []
        or observed["relaunch_task"] != relaunch["task"]
        or observed["relaunch_task_version"] != 1
        or observed["relaunch_run_id"] != relaunch["run_id"]
        or observed["relaunch_source_sha256"]
        != _sha256(relaunch["source"].read_bytes())
    ):
        raise ValueError("superseded shard 07 record changed")


def build_manifest() -> dict:
    """Build the proposed immutable manifest from exact local artifacts."""
    pilots, staged = _sealed_launch_inputs()
    shards = [_build_shard_record(execution) for execution in EXECUTIONS]
    batch_cost = round(
        math.fsum(shard["accounting"]["known_cost_usd"] for shard in shards),
        12,
    )
    pre_batch_cost = round(staged["pre_launch_known_daily_cost_usd"], 12)
    totals = {
        "completed_jobs": sum(
            shard["accounting"]["completed_jobs"] for shard in shards
        ),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "observed_invocations": sum(
            shard["accounting"]["observed_invocations"] for shard in shards
        ),
        "complete_calls": sum(
            shard["accounting"]["complete_calls"] for shard in shards
        ),
        "failed_calls": sum(
            shard["accounting"]["failed_calls"] for shard in shards
        ),
        "unknown_cost_calls": sum(
            shard["accounting"]["unknown_cost_calls"] for shard in shards
        ),
        "invalid_json_lines": sum(
            shard["accounting"]["invalid_json_lines"] for shard in shards
        ),
        "events": sum(shard["accounting"]["events"] for shard in shards),
        "started_attempts": sum(
            shard["accounting"]["started_attempts"] for shard in shards
        ),
        "batch_known_cost_usd": batch_cost,
        "pre_batch_known_daily_cost_usd": pre_batch_cost,
        "post_batch_known_daily_cost_usd": round(
            pre_batch_cost + batch_cost, 12
        ),
    }
    manifest = {
        "schema": "chronos.experiment-a-qwen-batch00-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "qwen_batch00_shards_00_07",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "pilot_collection_manifest_sha256": pilots[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": _file_record(PRELAUNCH_MANIFEST),
        "superseded_no_run": {
            "status": "superseded_before_any_model_run",
            "record": _file_record(SUPERSEDED_RECORD),
        },
        "shard_count": len(shards),
        "job_count": sum(shard["accounting"]["job_count"] for shard in shards),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "totals": totals,
        "shards": shards,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Qwen batch00 collection manifest schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Qwen batch00 collection manifest self-hash mismatch")
    if (
        manifest["schema"]
        != "chronos.experiment-a-qwen-batch00-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "qwen_batch00_shards_00_07"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["shard_count"] != 8
        or manifest["job_count"] != 184
        or manifest["planned_calls"] != 580
    ):
        raise ValueError("Qwen batch00 collection top-level contract changed")
    return manifest


def _verify_prelaunch(manifest: dict) -> None:
    _read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Qwen batch00 prelaunch manifest",
    )
    pilots, staged = _sealed_launch_inputs()
    if (
        staged["batch_manifest_sha256"]
        != json.loads(PRELAUNCH_MANIFEST.read_text())["batch_manifest_sha256"]
        or staged["task_count"] != 8
        or staged["job_count"] != 184
        or staged["planned_calls"] != 580
        or round(staged["pre_launch_known_daily_cost_usd"], 12)
        != PRE_BATCH_KNOWN_DAILY_COST_USD
        or manifest["pilot_collection_manifest_sha256"]
        != pilots["collection_manifest_sha256"]
    ):
        raise ValueError("Qwen batch00 launch authorization changed")


def _verify_metadata(
    execution: dict,
    record: dict,
    source: str,
    blobs: dict[str, bytes],
) -> None:
    task = _json(blobs["task"], "task metadata")
    run = _json(blobs["run"], "run metadata")
    result = _json(blobs["result"], "result metadata")
    atif = _json(blobs["atif"], "ATIF metadata")
    notebook = _json(blobs["notebook"], "downloaded notebook")
    name = execution["task"]
    definition = _uploaded_definition(source, name)
    expected_task = {"versionNumber": 1, "name": name, "definition": definition}
    if task != expected_task:
        raise ValueError("downloaded task differs from regenerated source")
    cells = notebook.get("cells")
    notebook_source = (
        "".join(cells[0].get("source", []))
        if isinstance(cells, list) and len(cells) == 1
        else None
    )
    # Kaggle serializes the single code cell without the source file's final
    # newline.  Accept exactly that one-byte normalization and nothing else.
    normalized_source = source[:-1] if source.endswith("\n") else source
    if (
        not isinstance(cells, list)
        or len(cells) != 1
        or cells[0].get("cell_type") != "code"
        or notebook_source != normalized_source
    ):
        raise ValueError("downloaded notebook source changed")
    run_task = run.get("taskVersion") or {}
    if (
        run_task.get("versionNumber") != 1
        or run_task.get("name") != name
        or run_task.get("definition") != definition
        or run.get("modelVersion", {}).get("slug") != MODEL
        or run.get("pyRunId") != f"{name}-Run #1"
        or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or run.get("startTime") != record["started_at"]
        or run.get("endTime") != record["finished_at"]
    ):
        raise ValueError("downloaded run metadata changed")
    if (
        result.get("task_name") != name
        or result.get("trial_name") != f"{name}-Run #1"
        or result.get("started_at") != record["started_at"]
        or result.get("finished_at") != record["finished_at"]
        or result.get("agent_info", {}).get("model_info", {}).get("name")
        != MODEL
        or result.get("verifier_result", {}).get("rewards", {}).get("score")
        != 1.0
    ):
        raise ValueError("downloaded result metadata changed")
    kbench = atif.get("extra", {}).get("kbench", {})
    atif_task = kbench.get("task_version", {})
    if (
        atif.get("schema_version") != "ATIF-v1.7"
        or atif.get("session_id") != f"{name}-Run #1"
        or atif.get("trajectory_id") != f"{name}-Run #1"
        or atif.get("agent", {}).get("model_name") != MODEL
        or atif_task.get("version_number") != 1
        or atif_task.get("name") != name
        or atif_task.get("definition") != definition
        or kbench.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or kbench.get("end_time") != record["finished_at"]
    ):
        raise ValueError("downloaded ATIF metadata changed")


def _verify_shard(execution: dict, record: dict) -> dict:
    index = execution["shard_index"]
    if set(record) != SHARD_KEYS or set(record["accounting"]) != ACCOUNTING_KEYS:
        raise ValueError(f"invalid Qwen shard {index:02d} record schema")
    expected_identity = {
        "shard_index": index,
        "execution_kind": execution["execution_kind"],
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "status": "complete_strictly_verified",
        "hosted_audit_passed": True,
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise ValueError(f"shard {index:02d} execution identity changed")

    source_raw = _read_pinned(
        record["source"], execution["source"], f"shard {index:02d} source"
    )
    source = source_raw.decode("utf-8")
    regenerated = _regenerated_source(
        index, execution["task"], execution["output_folder"]
    )
    if source != regenerated:
        raise ValueError(f"shard {index:02d} is not a byte-exact regeneration")
    if execution["execution_kind"] != "baseline":
        canonical_execution = dict(execution)
        canonical_task = execution.get(
            "canonical_task",
            f"chronos-r2-water4-study-qwen-low-s{index:02d}-v1",
        )
        canonical_output = execution.get(
            "canonical_output_folder",
            f"round2_water4_study_qwen_low_s{index:02d}_v1",
        )
        canonical_execution["task"] = canonical_task
        canonical_execution["output_folder"] = canonical_output
        canonical = _regenerated_source(
            index,
            canonical_execution["task"],
            canonical_execution["output_folder"],
        )
        expected_relaunch = canonical.replace(
            canonical_output,
            execution["output_folder"],
            1,
        ).replace(
            canonical_task,
            execution["task"],
            1,
        )
        if source != expected_relaunch:
            raise ValueError(
                f"shard {index:02d} relaunch changed scientific source"
            )
    compile(source, str(execution["source"]), "exec")

    values = _assignments(source, execution["source"])
    required = {
        "CONTRACT",
        "EXPECTED_JOBS",
        "RESUME_LEDGER",
        "MODEL",
        "REASONING",
        "ROLE",
        "STUDY_ID",
        "OUTPUT_FOLDER",
        "CEILING_USD",
        "MAX_WAIT_SECONDS",
    }
    if not required <= set(values):
        raise ValueError(f"shard {index:02d} source assignments are incomplete")
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    full_jobs, expected_jobs = _jobs_for_shard(index)
    if (
        values["MODEL"] != MODEL
        or values["REASONING"] != REASONING
        or values["ROLE"] != ROLE
        or values["STUDY_ID"] != STUDY_ID
        or values["OUTPUT_FOLDER"] != execution["output_folder"]
        or values["CEILING_USD"]
        != cell_builder.INCREMENTAL_CEILINGS_USD[(MODEL, REASONING)]
        or values["MAX_WAIT_SECONDS"] != 7200
        or values["RESUME_LEDGER"] != b""
        or contract["model"] != MODEL
        or contract["reasoning"] != REASONING
        or contract["role"] != ROLE
        or contract["study_id"] != STUDY_ID
        or contract["shard_index"] != index
        or contract["shard_count"] != 30
        or contract["job_count"] != 23
        or contract["parent_ledger_sha256"] is not None
        or contract["resume_ledger"]["events"] != 0
        or jobs != expected_jobs
    ):
        raise ValueError(f"shard {index:02d} source contract changed")

    expected_artifacts = _artifact_paths(execution)
    if set(record["artifacts"]) != set(expected_artifacts):
        raise ValueError(f"shard {index:02d} artifact set changed")
    blobs = {
        label: _read_pinned(
            record["artifacts"][label],
            path,
            f"shard {index:02d} {label}",
        )
        for label, path in expected_artifacts.items()
    }
    result = _json(blobs["result"], "result metadata")
    if (
        record["started_at"] != result.get("started_at")
        or record["finished_at"] != result.get("finished_at")
    ):
        raise ValueError(f"shard {index:02d} timestamps changed")

    intended = _json(blobs["intended_manifest"], "intended manifest")
    expected_intended = dict(
        contract, jobs=jobs, seed_audit=contract["resume_ledger"]
    )
    _require_equal(intended, expected_intended, "downloaded intended manifest")

    evidence = blobs["evidence"]
    if not evidence.endswith(b"\n"):
        raise ValueError(f"shard {index:02d} evidence is not newline terminated")
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    previous = _runtime()
    try:
        identity = cell_builder._identity(
            STUDY_ID, MODEL, protocol.fixtures()
        )

        def structural(candidate: list[dict]) -> dict:
            return water_audit.audit(
                candidate, MODEL, "study", require_complete=False
            )

        ledger = validate_resume_ledger(
            events,
            model=MODEL,
            identity=identity,
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=structural,
        )
        strict = structural(events)
        subset = subset_summary(events, {job["id"] for job in jobs})
    finally:
        _restore_runtime(previous)
    shard_ids = {job["id"] for job in jobs}
    full_ids = {job["id"] for job in full_jobs}
    if (
        ledger["completed_jobs"] != 23
        or ledger["incomplete_jobs"]
        or subset["complete"] is not True
        or subset["completed_jobs"] != 23
        or subset["missing_job_ids"]
        or subset["unknown_cost_calls"] != 0
        or strict["complete"] is not False
        or strict["completed_jobs"] != 23
        or strict["unknown_cost_calls"] != 0
        or set(strict["missing_jobs"]) != full_ids - shard_ids
        or len(strict["missing_jobs"]) != 667
        or strict["attempted_calls"] != summary["observed_invocations"]
        or summary["accounting_complete"] is not True
        or summary["completed_jobs"] != 23
        or summary["failed_calls"] != 0
        or summary["unknown_cost_calls"] != 0
        or summary["invalid_json_lines"] != 0
        or summary["observed_invocations"]
        != sum(job["calls"] for job in jobs)
    ):
        raise ValueError(f"shard {index:02d} strict raw-ledger audit failed")
    _require_equal(
        strict["known_cost_usd"], summary["known_cost_usd"], "strict cost"
    )

    terminal = _json(blobs["terminal"], "terminal record")
    if (
        terminal.get("schema")
        != "chronos.experiment-a-full-shard-terminal.v1"
        or terminal.get("model") != MODEL
        or terminal.get("reasoning") != REASONING
        or terminal.get("role") != ROLE
        or terminal.get("study_id") != STUDY_ID
        or terminal.get("identity") != contract["identity"]
        or terminal.get("manifest_sha256") != contract["manifest_sha256"]
        or terminal.get("shard_index") != index
        or terminal.get("shard_count") != 30
        or terminal.get("job_ids") != [job["id"] for job in jobs]
        or terminal.get("planned_calls") != sum(
            job["calls"] for job in jobs
        )
        or terminal.get("evidence_sha256") != _sha256(evidence)
        or terminal.get("parent_ledger_sha256") is not None
        or terminal.get("error") is not None
    ):
        raise ValueError(f"shard {index:02d} terminal record changed")

    audit = _json(blobs["audit"], "hosted audit")
    if (
        audit.get("passed") is not True
        or "audit_failed" in audit
        or audit.get("allocation_exhausted") is not False
        or audit.get("stopped_early") is not None
        or audit.get("terminal_error") is not None
        or audit.get("parent_prefix_preserved") is not True
        or audit.get("evidence_sha256") != _sha256(evidence)
    ):
        raise ValueError(f"shard {index:02d} hosted audit did not pass cleanly")
    for key, value in contract.items():
        _require_equal(audit.get(key), value, f"hosted contract field {key}")
    _require_equal(audit["ledger_audit"], ledger, "hosted ledger audit")
    _require_equal(audit["structural_audit"], strict, "hosted structural audit")
    _require_equal(audit["subset"], subset, "hosted subset audit")
    _require_equal(audit["raw_accounting"], summary, "hosted raw accounting")
    _require_equal(
        audit["new_suffix_accounting"], summary, "hosted suffix accounting"
    )
    _verify_metadata(execution, record, source, blobs)

    actual_accounting = _accounting(jobs, summary)
    _require_equal(record["accounting"], actual_accounting, "shard accounting")
    return {"jobs": jobs, "accounting": actual_accounting}


def verify(manifest_value: dict | None = None) -> dict:
    """Verify every pinned file, execution, raw event, and batch invariant."""
    manifest = _load_manifest(manifest_value)
    _verify_prelaunch(manifest)
    _verify_superseded_record(manifest["superseded_no_run"])
    if not isinstance(manifest["shards"], list) or len(manifest["shards"]) != 8:
        raise ValueError("Qwen batch00 must contain exactly eight shards")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(range(8)):
        raise ValueError("Qwen batch00 shard indexes are not exactly 0--7")
    verified = [
        _verify_shard(execution, record)
        for execution, record in zip(EXECUTIONS, records)
    ]

    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous = _runtime()
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")
        expected = [
            job
            for index in range(8)
            for job in select_shard(
                full_jobs,
                shard_index=index,
                shard_count=cell_builder.SHARD_COUNT,
            )
        ]
    finally:
        _restore_runtime(previous)
    expected_ids = {job["id"] for job in expected}
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != 184
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != expected_ids
        or sum(job["calls"] for job in expected) != 580
    ):
        raise ValueError("Qwen batch00 is not its deterministic disjoint subset")

    accounts = [item["accounting"] for item in verified]
    batch_cost = math.fsum(item["known_cost_usd"] for item in accounts)
    actual_totals = {
        "completed_jobs": sum(item["completed_jobs"] for item in accounts),
        "planned_calls": sum(item["planned_calls"] for item in accounts),
        "observed_invocations": sum(
            item["observed_invocations"] for item in accounts
        ),
        "complete_calls": sum(item["complete_calls"] for item in accounts),
        "failed_calls": sum(item["failed_calls"] for item in accounts),
        "unknown_cost_calls": sum(
            item["unknown_cost_calls"] for item in accounts
        ),
        "invalid_json_lines": sum(
            item["invalid_json_lines"] for item in accounts
        ),
        "events": sum(item["events"] for item in accounts),
        "started_attempts": sum(item["started_attempts"] for item in accounts),
        "batch_known_cost_usd": batch_cost,
        "pre_batch_known_daily_cost_usd": PRE_BATCH_KNOWN_DAILY_COST_USD,
        "post_batch_known_daily_cost_usd": (
            PRE_BATCH_KNOWN_DAILY_COST_USD + batch_cost
        ),
    }
    _require_equal(manifest["totals"], actual_totals, "collection totals")
    if (
        actual_totals["completed_jobs"] != 184
        or actual_totals["planned_calls"] != 580
        or actual_totals["observed_invocations"] != 580
        or actual_totals["complete_calls"] != 580
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 948
        or actual_totals["started_attempts"] != 184
    ):
        raise ValueError("Qwen batch00 accounting topology changed")
    _require_equal(batch_cost, BATCH_KNOWN_COST_USD, "batch known cost")
    _require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "post-batch daily known cost",
    )
    return {
        "schema": "chronos.experiment-a-qwen-batch00-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 8,
        "completed_jobs": actual_totals["completed_jobs"],
        "remaining_jobs": len(full_jobs) - actual_totals["completed_jobs"],
        "planned_calls": actual_totals["planned_calls"],
        "observed_invocations": actual_totals["observed_invocations"],
        "failed_calls": actual_totals["failed_calls"],
        "unknown_cost_calls": actual_totals["unknown_cost_calls"],
        "batch_known_cost_usd": batch_cost,
        "pre_batch_known_daily_cost_usd": PRE_BATCH_KNOWN_DAILY_COST_USD,
        "post_batch_known_daily_cost_usd": actual_totals[
            "post_batch_known_daily_cost_usd"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="write the self-hashed manifest before verifying it",
    )
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['collection_manifest_sha256']}")
    checked = verify()
    print(
        "PASS Qwen batch00: {completed_jobs}/184 jobs, {planned_calls} planned "
        "calls, {observed_invocations} measured invocations, {failed_calls} "
        "failed calls, ${batch_known_cost_usd:.8f} batch / "
        "${post_batch_known_daily_cost_usd:.8f} known daily total; eight "
        "shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
