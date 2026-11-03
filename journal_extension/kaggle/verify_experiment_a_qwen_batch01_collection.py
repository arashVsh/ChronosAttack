"""Seal and independently verify Qwen Experiment A shards 08--14."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

from round2_hosted import select_shard
import verify_experiment_a_qwen_batch00_collection as base
import verify_experiment_a_qwen_batch01 as staged_batch
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_qwen_batch01"
MANIFEST = GENERATED / "experiment_a_qwen_batch01_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_qwen_batch01_tasks_v1.json"
SUPERSEDED_RECORDS = {
    10: RUNS / "s10_original_no_run_record_v1.json",
    13: RUNS / "s13_original_no_run_record_v1.json",
}

MODEL = base.MODEL
REASONING = base.REASONING
ROLE = base.ROLE
STUDY_ID = base.STUDY_ID
FROZEN_AT = "2026-09-20T23:22:49+03:30"
SHARDS = tuple(range(8, 15))
PRE_BATCH_KNOWN_DAILY_COST_USD = 8.79140383
BATCH_KNOWN_COST_USD = 0.14147408
POST_BATCH_KNOWN_DAILY_COST_USD = 8.93287791


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
    resolved_output = output_folder or canonical_output
    run_root = (
        RUNS
        / run_folder
        / resolved_task
        / "1"
        / base.MODEL_SLUG
        / str(run_id)
    )
    return {
        "shard_index": index,
        "execution_kind": kind,
        "task": resolved_task,
        "run_id": run_id,
        "run_root": run_root,
        "output_folder": resolved_output,
        "output_root": run_root / resolved_output,
        "source": GENERATED / (source or canonical_source),
    }


EXECUTIONS = (
    _execution(8, run_id=2684985, run_folder="s08"),
    _execution(9, run_id=2684970, run_folder="s09"),
    _execution(
        10,
        run_id=2685316,
        run_folder="s10_relaunch",
        task="chronos-r2-water4-study-qwen-low-s10-relaunch-v1",
        source="water4_study_qwen_low_s10_relaunch_v1.py",
        output_folder="round2_water4_study_qwen_low_s10_relaunch_v1",
        kind="task_relaunch_after_no_run_build_stall",
    ),
    _execution(11, run_id=2684984, run_folder="s11"),
    _execution(12, run_id=2684957, run_folder="s12"),
    _execution(
        13,
        run_id=2685302,
        run_folder="s13_relaunch",
        task="chronos-r2-water4-study-qwen-low-s13-relaunch-v1",
        source="water4_study_qwen_low_s13_relaunch_v1.py",
        output_folder="round2_water4_study_qwen_low_s13_relaunch_v1",
        kind="task_relaunch_after_no_run_build_stall",
    ),
    _execution(14, run_id=2684969, run_folder="s14"),
)
EXECUTION_BY_INDEX = {item["shard_index"]: item for item in EXECUTIONS}

TOP_LEVEL_KEYS = {
    "schema",
    "collection_manifest_sha256",
    "frozen_at",
    "batch",
    "model",
    "reasoning",
    "role",
    "study_id",
    "previous_collection_manifest_sha256",
    "prelaunch_manifest",
    "superseded_no_runs",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


@lru_cache(maxsize=1)
def _sealed_inputs() -> tuple[dict, dict]:
    previous = base.verify()
    original_previous = staged_batch._previous
    staged_batch._previous = lambda: previous
    try:
        staged = staged_batch.verify()
    finally:
        staged_batch._previous = original_previous
    return previous, staged


def _manifest_hash(manifest: dict) -> str:
    body = {
        key: value
        for key, value in manifest.items()
        if key != "collection_manifest_sha256"
    }
    return base._canonical_hash(body)


def _build_superseded_record(index: int) -> dict:
    return {
        "shard_index": index,
        "status": "superseded_before_any_model_run",
        "record": base._file_record(SUPERSEDED_RECORDS[index]),
    }


def build_manifest() -> dict:
    previous, staged = _sealed_inputs()
    shards = [base._build_shard_record(execution) for execution in EXECUTIONS]
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
        "schema": "chronos.experiment-a-qwen-batch01-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "qwen_batch01_shards_08_14",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": base._file_record(PRELAUNCH_MANIFEST),
        "superseded_no_runs": [
            _build_superseded_record(index)
            for index in sorted(SUPERSEDED_RECORDS)
        ],
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
        raise ValueError("invalid Qwen batch01 collection manifest schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Qwen batch01 collection manifest self-hash mismatch")
    if (
        manifest["schema"]
        != "chronos.experiment-a-qwen-batch01-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "qwen_batch01_shards_08_14"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["shard_count"] != 7
        or manifest["job_count"] != 161
        or manifest["planned_calls"] != 565
    ):
        raise ValueError("Qwen batch01 collection top-level contract changed")
    return manifest


def _verify_prelaunch(manifest: dict) -> None:
    base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Qwen batch01 prelaunch manifest",
    )
    previous, staged = _sealed_inputs()
    if (
        staged["task_count"] != 7
        or staged["job_count"] != 161
        or staged["planned_calls"] != 565
        or staged["batch_shards"] != list(SHARDS)
        or round(staged["pre_launch_known_daily_cost_usd"], 12)
        != PRE_BATCH_KNOWN_DAILY_COST_USD
        or staged["maximum_daily_exposure_usd"] > 10.0
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
    ):
        raise ValueError("Qwen batch01 launch authorization changed")


def _verify_superseded_records(records: list[dict]) -> None:
    if not isinstance(records, list) or len(records) != 2:
        raise ValueError("Qwen batch01 supersession count changed")
    for expected_index, record in zip(sorted(SUPERSEDED_RECORDS), records):
        if (
            set(record) != {"shard_index", "status", "record"}
            or record["shard_index"] != expected_index
            or record["status"] != "superseded_before_any_model_run"
        ):
            raise ValueError("Qwen batch01 supersession identity changed")
        raw = base._read_pinned(
            record["record"],
            SUPERSEDED_RECORDS[expected_index],
            f"superseded shard {expected_index:02d} record",
        )
        observed = base._json(raw, f"superseded shard {expected_index:02d}")
        execution = EXECUTION_BY_INDEX[expected_index]
        if (
            observed.get("schema")
            != "chronos.kaggle-task-no-run-supersession.v1"
            or observed.get("original_task")
            != f"chronos-r2-water4-study-qwen-low-s{expected_index:02d}-v1"
            or observed.get("original_task_version") != 1
            or observed.get("original_status") != "UNSPECIFIED"
            or observed.get("model_run_observed") is not False
            or observed.get("scientific_changes") != []
            or observed.get("relaunch_task") != execution["task"]
            or observed.get("relaunch_task_version") != 1
            or observed.get("relaunch_run_id") != execution["run_id"]
            or observed.get("relaunch_source_sha256")
            != base._sha256(execution["source"].read_bytes())
        ):
            raise ValueError(
                f"superseded shard {expected_index:02d} record changed"
            )


def verify(manifest_value: dict | None = None) -> dict:
    manifest = _load_manifest(manifest_value)
    _verify_prelaunch(manifest)
    _verify_superseded_records(manifest["superseded_no_runs"])
    if not isinstance(manifest["shards"], list) or len(manifest["shards"]) != 7:
        raise ValueError("Qwen batch01 must contain exactly seven shards")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Qwen batch01 shard indexes are not exactly 08--14")
    verified = [
        base._verify_shard(execution, record)
        for execution, record in zip(EXECUTIONS, records)
    ]

    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous = base._runtime()
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")
        expected = [
            job
            for index in SHARDS
            for job in select_shard(
                full_jobs,
                shard_index=index,
                shard_count=30,
            )
        ]
    finally:
        base._restore_runtime(previous)
    if (
        len(all_ids) != 161
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 565
    ):
        raise ValueError("Qwen batch01 is not its deterministic disjoint subset")

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
    base._require_equal(manifest["totals"], actual_totals, "collection totals")
    if (
        actual_totals["completed_jobs"] != 161
        or actual_totals["planned_calls"] != 565
        or actual_totals["observed_invocations"] != 565
        or actual_totals["complete_calls"] != 565
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 887
        or actual_totals["started_attempts"] != 161
    ):
        raise ValueError("Qwen batch01 accounting topology changed")
    base._require_equal(batch_cost, BATCH_KNOWN_COST_USD, "batch known cost")
    base._require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "post-batch daily known cost",
    )
    return {
        "schema": "chronos.experiment-a-qwen-batch01-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 7,
        "completed_jobs": actual_totals["completed_jobs"],
        "cumulative_completed_jobs": 345,
        "remaining_jobs": 345,
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
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['collection_manifest_sha256']}")
    checked = verify()
    print(
        "PASS Qwen batch01: {completed_jobs}/161 jobs, {planned_calls} planned "
        "calls, {observed_invocations} measured invocations, {failed_calls} "
        "failed calls, ${batch_known_cost_usd:.8f} batch / "
        "${post_batch_known_daily_cost_usd:.8f} known daily total; seven "
        "shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
