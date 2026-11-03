"""Seal and independently verify Terra Experiment A shard 00."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from functools import lru_cache
import json
import math
from pathlib import Path

import verify_experiment_a_qwen_batch00_collection as base
import verify_experiment_a_terra_batch00 as staged_batch


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch00"
MANIFEST = GENERATED / "experiment_a_terra_batch00_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_terra_batch00_tasks_v1.json"

MODEL = staged_batch.MODEL
MODEL_SLUG = "gpt-5.6-terra"
MODEL_FILE = "openai_gpt-5.6-terra.jsonl"
REASONING = staged_batch.REASONING
ROLE = staged_batch.ROLE
STUDY_ID = staged_batch.STUDY_ID
FROZEN_AT = "2026-09-21T00:34:40+03:30"
PRE_BATCH_KNOWN_DAILY_COST_USD = 9.22574675
BATCH_KNOWN_COST_USD = 0.20922
POST_BATCH_KNOWN_DAILY_COST_USD = 9.43496675
RUN_ID = 2688450

TASK = "chronos-r2-water4-study-terra-low-s00-v1"
OUTPUT_FOLDER = "round2_water4_study_terra_low_s00_v1"
RUN_ROOT = RUNS / "s00" / TASK / "1" / MODEL_SLUG / str(RUN_ID)
EXECUTION = {
    "shard_index": 0,
    "execution_kind": "baseline",
    "task": TASK,
    "run_id": RUN_ID,
    "run_root": RUN_ROOT,
    "output_folder": OUTPUT_FOLDER,
    "output_root": RUN_ROOT / OUTPUT_FOLDER,
    "source": GENERATED / "water4_study_terra_low_s00_v1.py",
}

TOP_LEVEL_KEYS = {
    "schema",
    "collection_manifest_sha256",
    "frozen_at",
    "batch",
    "model",
    "reasoning",
    "role",
    "study_id",
    "previous_cell_collection_manifest_sha256",
    "quota_attestation_sha256",
    "prelaunch_manifest",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


@contextmanager
def _terra_base():
    previous = (
        base.MODEL,
        base.MODEL_SLUG,
        base.MODEL_FILE,
        base.REASONING,
        base.ROLE,
        base.STUDY_ID,
    )
    base.MODEL = MODEL
    base.MODEL_SLUG = MODEL_SLUG
    base.MODEL_FILE = MODEL_FILE
    base.REASONING = REASONING
    base.ROLE = ROLE
    base.STUDY_ID = STUDY_ID
    base._regenerated_source.cache_clear()
    try:
        yield
    finally:
        (
            base.MODEL,
            base.MODEL_SLUG,
            base.MODEL_FILE,
            base.REASONING,
            base.ROLE,
            base.STUDY_ID,
        ) = previous
        base._regenerated_source.cache_clear()


@lru_cache(maxsize=1)
def _sealed_inputs() -> tuple[dict, dict]:
    staged = staged_batch.verify()
    return staged_batch._previous(), staged


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
    with _terra_base():
        shard = base._build_shard_record(EXECUTION)
    accounting = shard["accounting"]
    batch_cost = round(accounting["known_cost_usd"], 12)
    pre_batch_cost = round(staged["pre_launch_known_daily_cost_usd"], 12)
    totals = {
        "completed_jobs": accounting["completed_jobs"],
        "planned_calls": accounting["planned_calls"],
        "observed_invocations": accounting["observed_invocations"],
        "complete_calls": accounting["complete_calls"],
        "failed_calls": accounting["failed_calls"],
        "unknown_cost_calls": accounting["unknown_cost_calls"],
        "invalid_json_lines": accounting["invalid_json_lines"],
        "events": accounting["events"],
        "started_attempts": accounting["started_attempts"],
        "batch_known_cost_usd": batch_cost,
        "pre_batch_known_daily_cost_usd": pre_batch_cost,
        "post_batch_known_daily_cost_usd": round(
            pre_batch_cost + batch_cost, 12
        ),
    }
    manifest = {
        "schema": "chronos.experiment-a-terra-batch00-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "terra_batch00_shard_00",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_cell_collection_manifest_sha256": previous[
            "cell_collection_manifest_sha256"
        ],
        "quota_attestation_sha256": staged["quota_attestation_sha256"],
        "prelaunch_manifest": base._file_record(PRELAUNCH_MANIFEST),
        "shard_count": 1,
        "job_count": accounting["job_count"],
        "planned_calls": accounting["planned_calls"],
        "totals": totals,
        "shards": [shard],
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Terra batch00 collection manifest schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Terra batch00 collection manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous, staged = _sealed_inputs()
    base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Terra batch00 prelaunch manifest",
    )
    if (
        manifest["schema"]
        != "chronos.experiment-a-terra-batch00-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "terra_batch00_shard_00"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_cell_collection_manifest_sha256"]
        != previous["cell_collection_manifest_sha256"]
        or manifest["quota_attestation_sha256"]
        != staged["quota_attestation_sha256"]
        or manifest["shard_count"] != 1
        or manifest["job_count"] != 23
        or manifest["planned_calls"] != 75
    ):
        raise ValueError("Terra batch00 collection top-level contract changed")

    record = manifest["shards"][0]
    with _terra_base():
        verified = base._verify_shard(EXECUTION, record)
    accounting = verified["accounting"]
    actual_totals = {
        "completed_jobs": accounting["completed_jobs"],
        "planned_calls": accounting["planned_calls"],
        "observed_invocations": accounting["observed_invocations"],
        "complete_calls": accounting["complete_calls"],
        "failed_calls": accounting["failed_calls"],
        "unknown_cost_calls": accounting["unknown_cost_calls"],
        "invalid_json_lines": accounting["invalid_json_lines"],
        "events": accounting["events"],
        "started_attempts": accounting["started_attempts"],
        "batch_known_cost_usd": accounting["known_cost_usd"],
        "pre_batch_known_daily_cost_usd": PRE_BATCH_KNOWN_DAILY_COST_USD,
        "post_batch_known_daily_cost_usd": (
            PRE_BATCH_KNOWN_DAILY_COST_USD + accounting["known_cost_usd"]
        ),
    }
    base._require_equal(manifest["totals"], actual_totals, "collection totals")
    if (
        actual_totals["completed_jobs"] != 23
        or actual_totals["planned_calls"] != 75
        or actual_totals["observed_invocations"] != 75
        or actual_totals["complete_calls"] != 75
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 121
        or actual_totals["started_attempts"] != 23
    ):
        raise ValueError("Terra batch00 accounting topology changed")
    base._require_equal(
        actual_totals["batch_known_cost_usd"],
        BATCH_KNOWN_COST_USD,
        "Terra batch00 known cost",
    )
    base._require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "Terra post-batch known daily cost",
    )
    return {
        "schema": "chronos.experiment-a-terra-batch00-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 1,
        "completed_jobs": actual_totals["completed_jobs"],
        "remaining_jobs": 667,
        "planned_calls": actual_totals["planned_calls"],
        "observed_invocations": actual_totals["observed_invocations"],
        "failed_calls": actual_totals["failed_calls"],
        "unknown_cost_calls": actual_totals["unknown_cost_calls"],
        "batch_known_cost_usd": actual_totals["batch_known_cost_usd"],
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
        "PASS Terra batch00: {completed_jobs}/23 jobs, {planned_calls} planned "
        "calls, {observed_invocations} measured invocations, {failed_calls} "
        "failed calls, ${batch_known_cost_usd:.8f} batch / "
        "${post_batch_known_daily_cost_usd:.8f} known daily total; shard 00 "
        "raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
