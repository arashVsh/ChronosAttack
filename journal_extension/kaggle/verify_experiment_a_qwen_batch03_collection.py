"""Seal and independently verify Qwen Experiment A shards 21--25."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

from round2_hosted import select_shard
import verify_experiment_a_qwen_batch00_collection as base
import verify_experiment_a_qwen_batch02_collection as previous_collection
import verify_experiment_a_qwen_batch03 as staged_batch
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_qwen_batch03"
MANIFEST = GENERATED / "experiment_a_qwen_batch03_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_qwen_batch03_tasks_v1.json"

MODEL = base.MODEL
REASONING = base.REASONING
ROLE = base.ROLE
STUDY_ID = base.STUDY_ID
FROZEN_AT = "2026-09-20T23:54:26+03:30"
SHARDS = tuple(range(21, 26))
PRE_BATCH_KNOWN_DAILY_COST_USD = 9.05006047
BATCH_KNOWN_COST_USD = 0.09811538
POST_BATCH_KNOWN_DAILY_COST_USD = 9.14817585
RUN_IDS = {
    21: 2685493,
    22: 2685496,
    23: 2685492,
    24: 2685491,
    25: 2685497,
}


def _execution(index: int) -> dict:
    task = f"chronos-r2-water4-study-qwen-low-s{index:02d}-v1"
    output = f"round2_water4_study_qwen_low_s{index:02d}_v1"
    root = (
        RUNS
        / f"s{index:02d}"
        / task
        / "1"
        / base.MODEL_SLUG
        / str(RUN_IDS[index])
    )
    return {
        "shard_index": index,
        "execution_kind": "baseline",
        "task": task,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": output,
        "output_root": root / output,
        "source": GENERATED / f"water4_study_qwen_low_s{index:02d}_v1.py",
    }


EXECUTIONS = tuple(_execution(index) for index in SHARDS)
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
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


@lru_cache(maxsize=1)
def _sealed_inputs() -> tuple[dict, dict]:
    previous = previous_collection.verify()
    original_previous = staged_batch._previous
    staged_batch._previous = lambda: previous
    try:
        staged = staged_batch.verify()
    finally:
        staged_batch._previous = original_previous
    return previous, staged


def _manifest_hash(manifest: dict) -> str:
    return base._canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "collection_manifest_sha256"
        }
    )


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
        "schema": "chronos.experiment-a-qwen-batch03-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "qwen_batch03_shards_21_25",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": base._file_record(PRELAUNCH_MANIFEST),
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
        raise ValueError("invalid Qwen batch03 collection manifest schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Qwen batch03 collection manifest self-hash mismatch")
    if (
        manifest["schema"]
        != "chronos.experiment-a-qwen-batch03-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "qwen_batch03_shards_21_25"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["shard_count"] != 5
        or manifest["job_count"] != 115
        or manifest["planned_calls"] != 391
    ):
        raise ValueError("Qwen batch03 collection top-level contract changed")
    return manifest


def _verify_prelaunch(manifest: dict) -> None:
    base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Qwen batch03 prelaunch manifest",
    )
    previous, staged = _sealed_inputs()
    if (
        staged["task_count"] != 5
        or staged["job_count"] != 115
        or staged["planned_calls"] != 391
        or staged["batch_shards"] != list(SHARDS)
        or round(staged["pre_launch_known_daily_cost_usd"], 12)
        != PRE_BATCH_KNOWN_DAILY_COST_USD
        or staged["maximum_daily_exposure_usd"] > 10.0
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
    ):
        raise ValueError("Qwen batch03 launch authorization changed")


def verify(manifest_value: dict | None = None) -> dict:
    manifest = _load_manifest(manifest_value)
    _verify_prelaunch(manifest)
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Qwen batch03 shard indexes are not exactly 21--25")
    verified = [
        base._verify_shard(execution, record)
        for execution, record in zip(EXECUTIONS, records)
    ]
    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous_runtime = base._runtime()
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")
        expected = [
            job
            for index in SHARDS
            for job in select_shard(
                full_jobs, shard_index=index, shard_count=30
            )
        ]
    finally:
        base._restore_runtime(previous_runtime)
    if (
        len(all_ids) != 115
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 391
    ):
        raise ValueError("Qwen batch03 is not its deterministic disjoint subset")

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
        actual_totals["completed_jobs"] != 115
        or actual_totals["planned_calls"] != 391
        or actual_totals["observed_invocations"] != 391
        or actual_totals["complete_calls"] != 391
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 621
        or actual_totals["started_attempts"] != 115
    ):
        raise ValueError("Qwen batch03 accounting topology changed")
    base._require_equal(batch_cost, BATCH_KNOWN_COST_USD, "batch known cost")
    base._require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "post-batch daily known cost",
    )
    return {
        "schema": "chronos.experiment-a-qwen-batch03-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 5,
        "completed_jobs": actual_totals["completed_jobs"],
        "cumulative_completed_jobs": 598,
        "remaining_jobs": 92,
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
        "PASS Qwen batch03: {completed_jobs}/115 jobs, {planned_calls} planned "
        "calls, {observed_invocations} measured invocations, {failed_calls} "
        "failed calls, ${batch_known_cost_usd:.8f} batch / "
        "${post_batch_known_daily_cost_usd:.8f} known daily total; five shards "
        "disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
