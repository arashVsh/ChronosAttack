"""Seal and independently verify Gemini Experiment A shard 03."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_gemini_batch00_collection as gemini_base
import verify_experiment_a_gemini_batch02 as staged_batch
import verify_experiment_a_qwen_batch00_collection as base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_gemini_batch02"
MANIFEST = GENERATED / "experiment_a_gemini_batch02_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_gemini_batch02_tasks_v1.json"

MODEL = staged_batch.cell_stage.MODEL
REASONING = staged_batch.cell_stage.REASONING
ROLE = staged_batch.cell_stage.ROLE
STUDY_ID = staged_batch.cell_stage.STUDY_ID
FROZEN_AT = "2026-09-21T01:13:12+03:30"
PRE_BATCH_KNOWN_DAILY_COST_USD = 9.6243605
BATCH_KNOWN_COST_USD = 0.062982
POST_BATCH_KNOWN_DAILY_COST_USD = 9.6873425
RUN_ID = 2691391

TASK = "chronos-r2-water4-study-gemini-minimal-s03-v1"
OUTPUT_FOLDER = "round2_water4_study_gemini_minimal_s03_v1"
RUN_ROOT = RUNS / "s03" / TASK / "1" / "gemini-3.6-flash" / str(RUN_ID)
EXECUTION = {
    "shard_index": 3,
    "execution_kind": "baseline",
    "task": TASK,
    "run_id": RUN_ID,
    "run_root": RUN_ROOT,
    "output_folder": OUTPUT_FOLDER,
    "output_root": RUN_ROOT / OUTPUT_FOLDER,
    "source": GENERATED / "water4_study_gemini_minimal_s03_v1.py",
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
    "previous_collection_manifest_sha256",
    "quota_attestation_sha256",
    "prelaunch_manifest",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


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
    with gemini_base._gemini_base():
        shard = base._build_shard_record(EXECUTION)
    accounting = shard["accounting"]
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
        "batch_known_cost_usd": round(accounting["known_cost_usd"], 12),
        "pre_batch_known_daily_cost_usd": round(
            staged["pre_launch_known_daily_cost_usd"], 12
        ),
        "post_batch_known_daily_cost_usd": round(
            staged["pre_launch_known_daily_cost_usd"]
            + accounting["known_cost_usd"],
            12,
        ),
    }
    manifest = {
        "schema": "chronos.experiment-a-gemini-batch02-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "gemini_batch02_shard_03",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
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
        raise ValueError("invalid Gemini batch02 collection manifest schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Gemini batch02 collection manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous, staged = _sealed_inputs()
    base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Gemini batch02 prelaunch manifest",
    )
    if (
        manifest["schema"]
        != "chronos.experiment-a-gemini-batch02-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "gemini_batch02_shard_03"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
        or manifest["quota_attestation_sha256"]
        != staged["quota_attestation_sha256"]
        or manifest["shard_count"] != 1
        or manifest["job_count"] != 23
        or manifest["planned_calls"] != 71
    ):
        raise ValueError("Gemini batch02 collection top-level contract changed")
    with gemini_base._gemini_base():
        verified = base._verify_shard(EXECUTION, manifest["shards"][0])
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
        or actual_totals["planned_calls"] != 71
        or actual_totals["observed_invocations"] != 71
        or actual_totals["complete_calls"] != 71
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 117
        or actual_totals["started_attempts"] != 23
    ):
        raise ValueError("Gemini batch02 accounting topology changed")
    base._require_equal(
        actual_totals["batch_known_cost_usd"],
        BATCH_KNOWN_COST_USD,
        "Gemini batch02 known cost",
    )
    base._require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "Gemini batch02 post-batch cost",
    )
    return {
        "schema": "chronos.experiment-a-gemini-batch02-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 1,
        "completed_jobs": actual_totals["completed_jobs"],
        "cumulative_completed_jobs": 92,
        "remaining_jobs": 598,
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
        "PASS Gemini batch02: {completed_jobs}/23 jobs, {planned_calls} "
        "planned calls, {observed_invocations} measured invocations, "
        "{failed_calls} failed calls, ${batch_known_cost_usd:.8f} batch / "
        "${post_batch_known_daily_cost_usd:.8f} known daily total; shard 03 "
        "raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
