"""Seal and independently verify the complete Terra reasoning-on study.

The collection is ten logical shards.  Shard 00 is the cumulative, amended
attempt-extension ledger; shards 01--05 are the original staged tasks; shards
06--09 are scientifically identical relaunches whose only source change is the
outer Kaggle task label.  Kaggle's PASS flag is necessary but not sufficient:
this verifier pins every downloaded artifact, rebuilds every source, replays the
strict ledger and structural audits, and proves that the ten manifests are a
disjoint, exhaustive 690-job / 2,310-call partition.
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

import audit_four_observation
import build_attempt_extension_v1 as repair_builder
from build_hosted_cell_v2 import build_source
import four_observation_protocol as protocol
from round2_hosted import (
    raw_event_summary,
    subset_summary,
    validate_resume_ledger,
)
import verify_round2_attempt_extension_result as repair_verifier
import verify_round2_generated as preflight_verifier
from verify_round2_study_shards import _arguments as baseline_arguments


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "round2_generated/terra_study_collection_v1.json"
MODEL = "openai/gpt-5.6-terra"
MODEL_SLUG = "gpt-5.6-terra"
REASONING = "low"
STUDY_ID = "chronos_round2_terra_reasoning_study_low_v1"
FROZEN_AT = "2026-09-20T20:21:27+03:30"
PREFLIGHT_COST_USD = 0.030434
PREFLIGHT_RECEIPT_SHA256 = (
    "77d2b0eee32b20e66d2bd203c00a011d40184c482b0b2bf1d11aea436f5f7467"
)

PREFLIGHT_ROOT = (
    HERE
    / "round2_runs_20260920/terra_low"
    / "chronos-r2-terra-preflight-low-v1/1"
    / "gpt-5.6-terra/2646426"
    / "round2_terra_reasoning_preflight_low_v1"
)
PREFLIGHT_PATHS = {
    "receipt": PREFLIGHT_ROOT / "reasoning_receipt.json",
    "terminal": PREFLIGHT_ROOT / "reasoning_terminal.json",
    "evidence": PREFLIGHT_ROOT / "openai_gpt-5.6-terra.jsonl",
}


def _execution(
    index: int,
    *,
    task: str,
    run_id: int,
    run_folder: str,
    source: str,
    output_folder: str,
    kind: str,
) -> dict:
    run_root = (
        HERE
        / "round2_runs_20260920"
        / run_folder
        / task
        / "1"
        / MODEL_SLUG
        / str(run_id)
    )
    return {
        "shard_index": index,
        "task": task,
        "run_id": run_id,
        "run_root": run_root,
        "output_root": run_root / output_folder,
        "source": ROOT / source,
        "execution_kind": kind,
    }


EXECUTIONS = (
    _execution(
        0,
        task="chronos-r2-terra-study-low-s00-repair-v1",
        run_id=2659315,
        run_folder="terra_study_s00_repair",
        source="kaggle/round2_generated/terra_attempt_extension_s00_v1.py",
        output_folder="round2_terra_reasoning_study_low_s00_repair_v1",
        kind="attempt_extension",
    ),
    _execution(
        1,
        task="chronos-r2-terra-study-low-s01-v1",
        run_id=2664491,
        run_folder="terra_study_s01",
        source="kaggle/round2_generated/terra_study_low_s01_v1.py",
        output_folder="round2_terra_reasoning_study_low_s01_v1",
        kind="baseline",
    ),
    _execution(
        2,
        task="chronos-r2-terra-study-low-s02-v1",
        run_id=2664547,
        run_folder="terra_study_s02",
        source="kaggle/round2_generated/terra_study_low_s02_v1.py",
        output_folder="round2_terra_reasoning_study_low_s02_v1",
        kind="baseline",
    ),
    _execution(
        3,
        task="chronos-r2-terra-study-low-s03-v1",
        run_id=2664548,
        run_folder="terra_study_s03",
        source="kaggle/round2_generated/terra_study_low_s03_v1.py",
        output_folder="round2_terra_reasoning_study_low_s03_v1",
        kind="baseline",
    ),
    _execution(
        4,
        task="chronos-r2-terra-study-low-s04-v1",
        run_id=2664816,
        run_folder="terra_study_s04",
        source="kaggle/round2_generated/terra_study_low_s04_v1.py",
        output_folder="round2_terra_reasoning_study_low_s04_v1",
        kind="baseline",
    ),
    _execution(
        5,
        task="chronos-r2-terra-study-low-s05-v1",
        run_id=2664856,
        run_folder="terra_study_s05",
        source="kaggle/round2_generated/terra_study_low_s05_v1.py",
        output_folder="round2_terra_reasoning_study_low_s05_v1",
        kind="baseline",
    ),
    _execution(
        6,
        task="chronos-r2-terra-study-low-s06-relaunch-v1",
        run_id=2666584,
        run_folder="terra_study_s06_relaunch",
        source="kaggle/round2_generated/terra_study_low_s06_relaunch_v1.py",
        output_folder="round2_terra_reasoning_study_low_s06_v1",
        kind="task_relaunch_same_scientific_source",
    ),
    _execution(
        7,
        task="chronos-r2-terra-study-low-s07-relaunch-v1",
        run_id=2666770,
        run_folder="terra_study_s07_relaunch",
        source="kaggle/round2_generated/terra_study_low_s07_relaunch_v1.py",
        output_folder="round2_terra_reasoning_study_low_s07_v1",
        kind="task_relaunch_same_scientific_source",
    ),
    _execution(
        8,
        task="chronos-r2-terra-study-low-s08-relaunch-v1",
        run_id=2666662,
        run_folder="terra_study_s08_relaunch",
        source="kaggle/round2_generated/terra_study_low_s08_relaunch_v1.py",
        output_folder="round2_terra_reasoning_study_low_s08_v1",
        kind="task_relaunch_same_scientific_source",
    ),
    _execution(
        9,
        task="chronos-r2-terra-study-low-s09-relaunch-v1",
        run_id=2666740,
        run_folder="terra_study_s09_relaunch",
        source="kaggle/round2_generated/terra_study_low_s09_relaunch_v1.py",
        output_folder="round2_terra_reasoning_study_low_s09_v1",
        kind="task_relaunch_same_scientific_source",
    ),
)

TOP_LEVEL_KEYS = {
    "schema",
    "collection_manifest_sha256",
    "frozen_at",
    "model",
    "reasoning",
    "study_id",
    "shard_count",
    "job_count",
    "planned_calls",
    "preflight",
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
    "observed_invocations",
    "failed_calls",
    "unknown_cost_calls",
    "known_cost_usd",
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


def _artifact_paths(execution: dict) -> dict[str, Path]:
    task = execution["task"]
    root = execution["run_root"]
    output = execution["output_root"]
    prefix = f"{task}-run_id_Run_1_openai_gpt-5.6-terra"
    return {
        "task": root / f"{task}.task.json",
        "run": root / f"{prefix}.run.json",
        "result": root / f"{prefix}.result.json",
        "atif": root / f"{prefix}.atif.json",
        "intended_manifest": output / "intended_manifest.json",
        "audit": output / "audit.json",
        "evidence": output / "openai_gpt-5.6-terra.jsonl",
    }


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


@lru_cache(maxsize=None)
def _regenerated_source(index: int, task: str) -> str:
    arguments = dict(baseline_arguments(index))
    arguments["task_name"] = task
    return build_source(**arguments)


def _regular_jobs_from_source(raw: bytes, path: Path) -> tuple[dict, list[dict]]:
    values = _assignments(raw.decode("utf-8"), path)
    required = {
        "CONTRACT",
        "EXPECTED_JOBS",
        "MODEL",
        "REASONING",
        "STUDY_ID",
        "KIND",
        "OUTPUT_FOLDER",
        "INCREMENTAL_CEILING_USD",
        "MAX_WAIT_SECONDS",
        "RESUME_LEDGER",
    }
    if not required <= set(values):
        raise ValueError("generated source assignments are incomplete")
    return values, values["EXPECTED_JOBS"]


def _build_preflight_record() -> dict:
    receipt = json.loads(PREFLIGHT_PATHS["receipt"].read_text())
    return {
        "task": "chronos-r2-terra-preflight-low-v1",
        "run_id": 2646426,
        "status": "passed",
        "receipt_sha256": receipt["receipt_sha256"],
        "known_cost_usd": round(receipt["evidence"]["known_cost_usd"], 12),
        "artifacts": {
            label: _file_record(path)
            for label, path in PREFLIGHT_PATHS.items()
        },
    }


def _build_shard_record(execution: dict) -> dict:
    source_raw = execution["source"].read_bytes()
    artifacts = _artifact_paths(execution)
    evidence = artifacts["evidence"].read_bytes()
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    result = json.loads(artifacts["result"].read_text())
    audit = json.loads(artifacts["audit"].read_text())
    if execution["shard_index"] == 0:
        jobs = repair_builder.plan_repair()["jobs"]
    else:
        _, jobs = _regular_jobs_from_source(source_raw, execution["source"])
    accounting = {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "observed_invocations": summary["observed_invocations"],
        "failed_calls": summary["failed_calls"],
        "unknown_cost_calls": summary["unknown_cost_calls"],
        "known_cost_usd": round(summary["known_cost_usd"], 12),
    }
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
        "accounting": accounting,
        "hosted_audit_passed": audit.get("passed"),
    }


def build_manifest() -> dict:
    """Build the proposed immutable manifest from the exact downloaded files."""
    shards = [_build_shard_record(execution) for execution in EXECUTIONS]
    study_cost = round(
        math.fsum(shard["accounting"]["known_cost_usd"] for shard in shards),
        12,
    )
    preflight = _build_preflight_record()
    totals = {
        "completed_jobs": sum(
            shard["accounting"]["job_count"] for shard in shards
        ),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "observed_invocations": sum(
            shard["accounting"]["observed_invocations"] for shard in shards
        ),
        "failed_calls": sum(
            shard["accounting"]["failed_calls"] for shard in shards
        ),
        "unknown_cost_calls": sum(
            shard["accounting"]["unknown_cost_calls"] for shard in shards
        ),
        "study_known_cost_usd": study_cost,
        "preflight_known_cost_usd": preflight["known_cost_usd"],
        "known_daily_cost_usd": round(
            study_cost + preflight["known_cost_usd"], 12
        ),
    }
    manifest = {
        "schema": "chronos.round2.terra-study-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "shard_count": 10,
        "job_count": 690,
        "planned_calls": 2310,
        "preflight": preflight,
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
        raise ValueError("invalid Terra collection manifest schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Terra collection manifest self-hash mismatch")
    if (
        manifest["schema"] != "chronos.round2.terra-study-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["study_id"] != STUDY_ID
        or manifest["shard_count"] != 10
        or manifest["job_count"] != 690
        or manifest["planned_calls"] != 2310
    ):
        raise ValueError("Terra collection top-level contract changed")
    return manifest


def _verify_preflight(record: dict) -> float:
    expected_keys = {
        "task",
        "run_id",
        "status",
        "receipt_sha256",
        "known_cost_usd",
        "artifacts",
    }
    if set(record) != expected_keys or set(record["artifacts"]) != set(
        PREFLIGHT_PATHS
    ):
        raise ValueError("invalid Terra low-preflight record")
    blobs = {
        label: _read_pinned(
            record["artifacts"][label], path, f"preflight {label}"
        )
        for label, path in PREFLIGHT_PATHS.items()
    }
    receipt = _json(blobs["receipt"], "preflight receipt")
    terminal = _json(blobs["terminal"], "preflight terminal")
    evidence = blobs["evidence"]
    if not evidence.endswith(b"\n"):
        raise ValueError("preflight evidence is not newline terminated")
    summary = raw_event_summary([json.loads(line) for line in evidence.splitlines()])
    receipt_body = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    if (
        record["task"] != "chronos-r2-terra-preflight-low-v1"
        or record["run_id"] != 2646426
        or record["status"] != "passed"
        or record["receipt_sha256"] != PREFLIGHT_RECEIPT_SHA256
        or receipt.get("receipt_sha256") != PREFLIGHT_RECEIPT_SHA256
        or _canonical_hash(receipt_body) != PREFLIGHT_RECEIPT_SHA256
        or receipt.get("disposition") != "passed"
        or receipt.get("model") != MODEL
        or receipt.get("reasoning") != REASONING
        or receipt.get("planned_calls") != 10
        or terminal.get("error") is not None
        or terminal.get("evidence_sha256") != _sha256(evidence)
        or receipt.get("evidence", {}).get("raw_sha256") != _sha256(evidence)
    ):
        raise ValueError("Terra low-preflight authorization changed")
    receipt_accounting = {
        key: value
        for key, value in receipt["evidence"].items()
        if key != "raw_sha256"
    }
    _require_equal(receipt_accounting, summary, "preflight raw accounting")
    _require_equal(record["known_cost_usd"], PREFLIGHT_COST_USD, "preflight cost")
    verified = preflight_verifier.verify()
    low = next(
        item
        for item in verified
        if item["path"].endswith("terra_reasoning_preflight_low_v1.py")
    )
    if low["execution_status"] != "passed":
        raise ValueError("Terra low preflight no longer independently passes")
    return summary["known_cost_usd"]


def _uploaded_definition(source: str, task: str) -> str:
    marker = f"@kbench.task(name={task!r})"
    start = source.rindex(marker)
    end = source.index("\nhosted_cell.run", start)
    return source[start:end].rstrip("\n") + "\n"


def _verify_metadata(record: dict, source: str, blobs: dict[str, bytes]) -> None:
    task = _json(blobs["task"], "task metadata")
    run = _json(blobs["run"], "run metadata")
    result = _json(blobs["result"], "result metadata")
    atif = _json(blobs["atif"], "ATIF metadata")
    name = record["task"]
    definition = _uploaded_definition(source, name)
    expected_task = {"versionNumber": 1, "name": name, "definition": definition}
    if task != expected_task:
        raise ValueError("downloaded task differs from regenerated source")
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


def _configure_engine(contract: dict):
    previous = (
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
        protocol.engine.MODELS,
    )
    protocol.engine.STUDY_ID = contract["study_id"]
    protocol.engine.CALL_SETTINGS = {
        key: value
        for key, value in contract["call_settings"].items()
        if key != "sdk_max_retries"
    }
    protocol.engine.MODELS = (MODEL,)
    return previous


def _restore_engine(previous) -> None:
    (
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
        protocol.engine.MODELS,
    ) = previous


def _verify_regular(
    execution: dict,
    record: dict,
    source_raw: bytes,
    blobs: dict[str, bytes],
) -> dict:
    index = execution["shard_index"]
    source = source_raw.decode("utf-8")
    regenerated = _regenerated_source(index, record["task"])
    if source != regenerated:
        raise ValueError(f"shard {index:02d} is not a byte-exact regeneration")
    if index >= 6:
        original_task = f"chronos-r2-terra-study-low-s{index:02d}-v1"
        canonical = _regenerated_source(index, original_task)
        old = f"@kbench.task(name={original_task!r})"
        new = f"@kbench.task(name={record['task']!r})"
        if canonical.count(old) != 1 or source != canonical.replace(old, new, 1):
            raise ValueError(
                f"shard {index:02d} relaunch changed more than the task label"
            )
    compile(source, str(execution["source"]), "exec")
    values, jobs = _regular_jobs_from_source(source_raw, execution["source"])
    contract = values["CONTRACT"]
    if (
        values["MODEL"] != MODEL
        or values["REASONING"] != REASONING
        or values["STUDY_ID"] != STUDY_ID
        or values["KIND"] != "study"
        or values["INCREMENTAL_CEILING_USD"] != 0.95
        or values["MAX_WAIT_SECONDS"] != 7200
        or values["RESUME_LEDGER"] != b""
        or contract["shard_index"] != index
        or contract["shard_count"] != 10
        or contract["job_count"] != 69
        or contract["model"] != MODEL
        or contract["reasoning"] != REASONING
        or contract["study_id"] != STUDY_ID
        or contract["accepted_preflight_receipt_sha256"]
        != PREFLIGHT_RECEIPT_SHA256
    ):
        raise ValueError(f"shard {index:02d} source contract changed")
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
    previous = _configure_engine(contract)
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")

        def structural(candidate: list[dict]) -> dict:
            return audit_four_observation.audit(
                candidate, MODEL, "study", require_complete=False
            )

        ledger = validate_resume_ledger(
            events,
            model=MODEL,
            identity=contract["identity"],
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=structural,
        )
        strict = structural(events)
        subset = subset_summary(events, {job["id"] for job in jobs})
    finally:
        _restore_engine(previous)

    shard_ids = {job["id"] for job in jobs}
    full_ids = {job["id"] for job in full_jobs}
    if (
        ledger["completed_jobs"] != 69
        or ledger["incomplete_jobs"]
        or subset["complete"] is not True
        or subset["completed_jobs"] != 69
        or subset["missing_job_ids"]
        or subset["unknown_cost_calls"] != 0
        or strict["completed_jobs"] != 69
        or strict["unknown_cost_calls"] != 0
        or strict["complete"] is not False
        or set(strict["missing_jobs"]) != full_ids - shard_ids
        or len(strict["missing_jobs"]) != 621
        or summary["completed_jobs"] != 69
        or summary["unknown_cost_calls"] != 0
        or strict["attempted_calls"] != summary["observed_invocations"]
    ):
        raise ValueError(f"shard {index:02d} strict completion audit failed")
    _require_equal(
        strict["known_cost_usd"], summary["known_cost_usd"], "strict cost"
    )

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
    _verify_metadata(record, source, blobs)

    actual_accounting = {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "observed_invocations": summary["observed_invocations"],
        "failed_calls": summary["failed_calls"],
        "unknown_cost_calls": summary["unknown_cost_calls"],
        "known_cost_usd": summary["known_cost_usd"],
    }
    _require_equal(record["accounting"], actual_accounting, "shard accounting")
    return {"jobs": jobs, "accounting": actual_accounting}


def _verify_repair(record: dict) -> dict:
    checked = repair_verifier.verify()
    jobs = repair_builder.plan_repair()["jobs"]
    actual = {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "observed_invocations": checked["observed_invocations"],
        "failed_calls": checked["failed_calls"],
        "unknown_cost_calls": 0,
        "known_cost_usd": checked["known_cost_usd"],
    }
    if (
        checked["status"] != "complete_strictly_verified"
        or checked["task"] != record["task"]
        or checked["run_id"] != record["run_id"]
        or checked["completed_jobs"] != 69
        or checked["job_count"] != 69
        or checked["local_strict_disposition"] != "pass_complete_shard"
        or checked["hosted_reported_passed"] is not False
    ):
        raise ValueError("shard 00 repair no longer strictly verifies")
    _require_equal(record["accounting"], actual, "shard 00 accounting")
    return {"jobs": jobs, "accounting": actual}


def _verify_shard(execution: dict, record: dict) -> dict:
    if set(record) != SHARD_KEYS:
        raise ValueError("invalid Terra shard record schema")
    index = execution["shard_index"]
    expected_identity = {
        "shard_index": index,
        "execution_kind": execution["execution_kind"],
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "status": "complete_strictly_verified",
        "hosted_audit_passed": index != 0,
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise ValueError(f"shard {index:02d} execution identity changed")
    if set(record["accounting"]) != ACCOUNTING_KEYS:
        raise ValueError(f"shard {index:02d} accounting schema changed")
    source_raw = _read_pinned(
        record["source"], execution["source"], f"shard {index:02d} source"
    )
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
        raise ValueError(f"shard {index:02d} recorded timestamps changed")
    if index == 0:
        return _verify_repair(record)
    return _verify_regular(execution, record, source_raw, blobs)


def verify(manifest_value: dict | None = None) -> dict:
    """Verify every pinned file, execution, and cross-shard invariant."""
    manifest = _load_manifest(manifest_value)
    preflight_cost = _verify_preflight(manifest["preflight"])
    if not isinstance(manifest["shards"], list) or len(manifest["shards"]) != 10:
        raise ValueError("Terra collection must contain exactly ten shards")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(range(10)):
        raise ValueError("Terra collection shard indexes are not exactly 0--9")

    verified = [
        _verify_shard(execution, record)
        for execution, record in zip(EXECUTIONS, records)
    ]
    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous = (
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
        protocol.engine.MODELS,
    )
    protocol.engine.STUDY_ID = STUDY_ID
    protocol.engine.CALL_SETTINGS = dict(
        temperature=1,
        reasoning=REASONING,
        max_completion_tokens=256,
        timeout=30,
    )
    protocol.engine.MODELS = (MODEL,)
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")
    finally:
        _restore_engine(previous)
    expected_ids = {job["id"] for job in full_jobs}
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != expected_ids
    ):
        raise ValueError("Terra shards are not a disjoint exhaustive partition")

    accounts = [item["accounting"] for item in verified]
    study_cost = math.fsum(item["known_cost_usd"] for item in accounts)
    actual_totals = {
        "completed_jobs": sum(item["job_count"] for item in accounts),
        "planned_calls": sum(item["planned_calls"] for item in accounts),
        "observed_invocations": sum(
            item["observed_invocations"] for item in accounts
        ),
        "failed_calls": sum(item["failed_calls"] for item in accounts),
        "unknown_cost_calls": sum(
            item["unknown_cost_calls"] for item in accounts
        ),
        "study_known_cost_usd": study_cost,
        "preflight_known_cost_usd": preflight_cost,
        "known_daily_cost_usd": study_cost + preflight_cost,
    }
    _require_equal(manifest["totals"], actual_totals, "collection totals")
    if (
        actual_totals["completed_jobs"] != 690
        or actual_totals["planned_calls"] != 2310
        or actual_totals["observed_invocations"] != 2511
        or actual_totals["failed_calls"] != 53
        or actual_totals["unknown_cost_calls"] != 0
    ):
        raise ValueError("Terra collection accounting topology changed")
    _require_equal(study_cost, 6.938468, "study known cost")
    _require_equal(
        actual_totals["known_daily_cost_usd"], 6.968902, "daily known cost"
    )
    return {
        "schema": "chronos.round2.terra-study-collection-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 10,
        "completed_jobs": actual_totals["completed_jobs"],
        "planned_calls": actual_totals["planned_calls"],
        "observed_invocations": actual_totals["observed_invocations"],
        "failed_calls": actual_totals["failed_calls"],
        "unknown_cost_calls": actual_totals["unknown_cost_calls"],
        "study_known_cost_usd": study_cost,
        "preflight_known_cost_usd": preflight_cost,
        "known_daily_cost_usd": actual_totals["known_daily_cost_usd"],
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
        print(f"WROTE {MANIFEST}")
    checked = verify()
    print(
        "PASS Terra low study: {completed_jobs}/690 jobs, {planned_calls} planned "
        "calls, {observed_invocations} measured invocations, {failed_calls} "
        "failed calls, ${study_known_cost_usd:.6f} study / "
        "${known_daily_cost_usd:.6f} including preflight; 10 shards disjoint "
        "and exhaustive".format(**checked)
    )


if __name__ == "__main__":
    main()
