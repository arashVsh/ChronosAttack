"""Seal and independently verify Terra Experiment A shards 01--09."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from functools import lru_cache
import json
import math
from pathlib import Path

import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_qwen_batch00_collection as shard_base
import verify_experiment_a_terra_batch00_collection as previous_collection
import verify_experiment_a_terra_batch01 as staged_batch


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch01"
MANIFEST = GENERATED / "experiment_a_terra_batch01_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_terra_batch01_tasks_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_terra_batch01_20260922_v1.json"
)

MODEL = staged_batch.MODEL
MODEL_SLUG = "gpt-5.6-terra"
MODEL_FILE = "openai_gpt-5.6-terra.jsonl"
REASONING = staged_batch.REASONING
ROLE = staged_batch.ROLE
STUDY_ID = staged_batch.STUDY_ID
FROZEN_AT = "2026-09-22T16:01:15.950332+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {
    1: 2781139,
    2: 2781149,
    3: 2781141,
    4: 2781150,
    5: 2781140,
    6: 2781160,
    7: 2781162,
    8: 2781167,
    9: 2781163,
}

PRE_BATCH_RAW_KNOWN_DAILY_USD = 3.9647331
PRE_BATCH_OFFICIAL_DAILY_USD = 3.9647331
BATCH_KNOWN_COST_USD = 1.865456
POST_BATCH_RAW_KNOWN_DAILY_USD = 5.8301891
POST_BATCH_OFFICIAL_DAILY_USD = 5.8301891
OFFICIAL_QUOTA_DELTA_USD = 1.865456
POST_OFFICIAL_MINUS_RAW_KNOWN_USD = 0.0
PRELAUNCH_MANIFEST_SHA256 = (
    "1e5770533caaa5c98ce78f68a87aca964f4e065f5514891402a20c8559e8c798"
)
COLLECTION_SCHEMA = "chronos.experiment-a-terra-batch01-collection.v1"
VERIFICATION_SCHEMA = "chronos.experiment-a-terra-batch01-verification.v1"
BATCH_NAME = "terra_batch01_shards_01_09"
BATCH_DISPLAY = "Terra batch01"
FINAL_SHARD = 9
EXPECTED_SHARD_COUNT = 9
EXPECTED_JOB_COUNT = 207
EXPECTED_PLANNED_CALLS = 679
EXPECTED_ACCOUNTING = {
    "completed_jobs": 207,
    "planned_calls": 679,
    "observed_invocations": 679,
    "complete_calls": 679,
    "failed_calls": 0,
    "unknown_cost_calls": 0,
    "invalid_json_lines": 0,
    "events": 1093,
    "started_attempts": 207,
}


def _task(index: int) -> str:
    return f"chronos-r2-water4-study-terra-low-s{index:02d}-v1"


def _folder(index: int) -> str:
    return f"round2_water4_study_terra_low_s{index:02d}_v1"


def _execution(index: int) -> dict:
    task = _task(index)
    root = (
        RUNS
        / f"s{index:02d}"
        / task
        / "1"
        / MODEL_SLUG
        / str(RUN_IDS[index])
    )
    folder = _folder(index)
    return {
        "shard_index": index,
        "execution_kind": "baseline",
        "task": task,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": folder,
        "output_root": root / folder,
        "source": staged_batch._source(index),
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
    "post_batch_quota_attestation",
    "post_batch_quota_attestation_sha256",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


@contextmanager
def _terra_base():
    previous = (
        shard_base.MODEL,
        shard_base.MODEL_SLUG,
        shard_base.MODEL_FILE,
        shard_base.REASONING,
        shard_base.ROLE,
        shard_base.STUDY_ID,
    )
    shard_base.MODEL = MODEL
    shard_base.MODEL_SLUG = MODEL_SLUG
    shard_base.MODEL_FILE = MODEL_FILE
    shard_base.REASONING = REASONING
    shard_base.ROLE = ROLE
    shard_base.STUDY_ID = STUDY_ID
    shard_base._regenerated_source.cache_clear()
    try:
        yield
    finally:
        (
            shard_base.MODEL,
            shard_base.MODEL_SLUG,
            shard_base.MODEL_FILE,
            shard_base.REASONING,
            shard_base.ROLE,
            shard_base.STUDY_ID,
        ) = previous
        shard_base._regenerated_source.cache_clear()


def _manifest_hash(value: dict) -> str:
    return shard_base._canonical_hash(
        {
            key: item
            for key, item in value.items()
            if key != "collection_manifest_sha256"
        }
    )


@lru_cache(maxsize=1)
def _previous() -> dict:
    return previous_collection.verify()


def _verify_quota(record: dict) -> dict:
    raw = shard_base._read_pinned(
        record,
        POST_BATCH_QUOTA_ATTESTATION,
        f"{BATCH_DISPLAY} post-batch quota attestation",
    )
    attestation = json.loads(raw)
    with _terra_base():
        artifacts = shard_base._artifact_paths(EXECUTIONS[-1])
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task") != _task(FINAL_SHARD)
        or attestation.get("run_context", {}).get("run_id")
        != RUN_IDS[FINAL_SHARD]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_OFFICIAL_DAILY_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError(f"{BATCH_DISPLAY} quota evidence changed")
    return attestation


def _totals(shards: list[dict]) -> dict:
    accounts = [shard["accounting"] for shard in shards]
    batch_cost = round(
        math.fsum(item["known_cost_usd"] for item in accounts), 12
    )
    official_delta = round(
        POST_BATCH_OFFICIAL_DAILY_USD - PRE_BATCH_OFFICIAL_DAILY_USD, 12
    )
    return {
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
        "pre_batch_raw_known_daily_cost_usd": PRE_BATCH_RAW_KNOWN_DAILY_USD,
        "pre_batch_official_daily_quota_used_usd": PRE_BATCH_OFFICIAL_DAILY_USD,
        "post_batch_raw_known_daily_cost_usd": round(
            PRE_BATCH_RAW_KNOWN_DAILY_USD + batch_cost, 12
        ),
        "post_batch_official_daily_quota_used_usd": POST_BATCH_OFFICIAL_DAILY_USD,
        "official_quota_delta_usd": official_delta,
        "official_delta_minus_batch_known_usd": round(
            official_delta - batch_cost, 12
        ),
        "post_official_minus_raw_known_usd": round(
            POST_BATCH_OFFICIAL_DAILY_USD
            - (PRE_BATCH_RAW_KNOWN_DAILY_USD + batch_cost),
            12,
        ),
    }


def build_manifest() -> dict:
    previous = _previous()
    staged = staged_batch._load()
    quota = json.loads(POST_BATCH_QUOTA_ATTESTATION.read_text())
    with _terra_base():
        shards = [
            shard_base._build_shard_record(execution) for execution in EXECUTIONS
        ]
    if staged.get("batch_manifest_sha256") != PRELAUNCH_MANIFEST_SHA256:
        raise ValueError(f"{BATCH_DISPLAY} prelaunch manifest changed")
    manifest = {
        "schema": COLLECTION_SCHEMA,
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": BATCH_NAME,
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": shard_base._file_record(PRELAUNCH_MANIFEST),
        "post_batch_quota_attestation": shard_base._file_record(
            POST_BATCH_QUOTA_ATTESTATION
        ),
        "post_batch_quota_attestation_sha256": quota["attestation_sha256"],
        "shard_count": len(shards),
        "job_count": sum(shard["accounting"]["job_count"] for shard in shards),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "totals": _totals(shards),
        "shards": shards,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError(f"invalid {BATCH_DISPLAY} collection schema")
    if manifest.get("collection_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError(f"{BATCH_DISPLAY} collection self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous = _previous()
    staged = staged_batch._load()
    shard_base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        f"{BATCH_DISPLAY} prelaunch manifest",
    )
    quota = _verify_quota(manifest["post_batch_quota_attestation"])
    if (
        manifest["schema"] != COLLECTION_SCHEMA
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != BATCH_NAME
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
        or staged.get("batch_manifest_sha256") != PRELAUNCH_MANIFEST_SHA256
        or manifest["post_batch_quota_attestation_sha256"]
        != quota["attestation_sha256"]
        or manifest["shard_count"] != EXPECTED_SHARD_COUNT
        or manifest["job_count"] != EXPECTED_JOB_COUNT
        or manifest["planned_calls"] != EXPECTED_PLANNED_CALLS
    ):
        raise ValueError(f"{BATCH_DISPLAY} top-level contract changed")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError(f"{BATCH_DISPLAY} shard indexes changed")
    with _terra_base():
        verified = [
            shard_base._verify_shard(execution, record)
            for execution, record in zip(EXECUTIONS, records)
        ]
        all_ids = [job["id"] for item in verified for job in item["jobs"]]
        previous_runtime = shard_base._runtime()
        try:
            full_jobs = shard_base.protocol.jobs_for(MODEL, "study")
            expected = [
                job
                for index in SHARDS
                for job in shard_base.select_shard(
                    full_jobs,
                    shard_index=index,
                    shard_count=shard_base.cell_builder.SHARD_COUNT,
                )
            ]
        finally:
            shard_base._restore_runtime(previous_runtime)
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != EXPECTED_JOB_COUNT
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != EXPECTED_PLANNED_CALLS
    ):
        raise ValueError(f"{BATCH_DISPLAY} is not its deterministic disjoint subset")
    totals = _totals([{"accounting": item["accounting"]} for item in verified])
    shard_base._require_equal(manifest["totals"], totals, "collection totals")
    if any(
        totals[key] != expected_value
        for key, expected_value in EXPECTED_ACCOUNTING.items()
    ):
        raise ValueError(f"{BATCH_DISPLAY} accounting topology changed")
    for key, expected_value in (
        ("batch_known_cost_usd", BATCH_KNOWN_COST_USD),
        ("post_batch_raw_known_daily_cost_usd", POST_BATCH_RAW_KNOWN_DAILY_USD),
        ("official_quota_delta_usd", OFFICIAL_QUOTA_DELTA_USD),
        ("official_delta_minus_batch_known_usd", 0.0),
        ("post_official_minus_raw_known_usd", POST_OFFICIAL_MINUS_RAW_KNOWN_USD),
    ):
        if not math.isclose(
            totals[key], expected_value, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(f"{BATCH_DISPLAY} cost changed: {key}")
    return {
        "schema": VERIFICATION_SCHEMA,
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": EXPECTED_SHARD_COUNT,
        "completed_jobs": totals["completed_jobs"],
        "remaining_jobs": previous["remaining_jobs"] - totals["completed_jobs"],
        "planned_calls": totals["planned_calls"],
        "observed_invocations": totals["observed_invocations"],
        "failed_calls": totals["failed_calls"],
        "unknown_cost_calls": totals["unknown_cost_calls"],
        "batch_known_cost_usd": totals["batch_known_cost_usd"],
        "post_batch_official_daily_quota_used_usd": totals[
            "post_batch_official_daily_quota_used_usd"
        ],
        "post_official_minus_raw_known_usd": totals[
            "post_official_minus_raw_known_usd"
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
        "PASS Terra batch01: {completed_jobs}/207 jobs, {planned_calls} planned / "
        "{observed_invocations} measured calls, {failed_calls} failed calls, "
        "${batch_known_cost_usd:.6f} batch, "
        "${post_batch_official_daily_quota_used_usd:.7f} official daily used; "
        "nine shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
