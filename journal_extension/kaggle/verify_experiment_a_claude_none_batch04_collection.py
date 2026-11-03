"""Seal and independently verify Claude-none Experiment A shard 17."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_claude_none_batch00_collection as shard_base
import verify_experiment_a_claude_none_batch03_collection as previous_collection
import verify_experiment_a_claude_none_batch04 as staged_batch
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch04"
MANIFEST = GENERATED / "experiment_a_claude_none_batch04_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_claude_none_batch04_tasks_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_claude_none_batch04_20260922_v1.json"
)

MODEL = staged_batch.base.MODEL
REASONING = staged_batch.base.REASONING
ROLE = staged_batch.base.ROLE
STUDY_ID = staged_batch.base.STUDY_ID
FROZEN_AT = "2026-09-21T22:32:39.973761+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {17: 2743753}

PRE_BATCH_RAW_KNOWN_DAILY_USD = 8.2324605
PRE_BATCH_OFFICIAL_DAILY_USD = 8.2374975
BATCH_KNOWN_COST_USD = 0.4198119
POST_BATCH_RAW_KNOWN_DAILY_USD = 8.6522724
POST_BATCH_OFFICIAL_DAILY_USD = 8.6573094
OFFICIAL_QUOTA_DELTA_USD = 0.4198119
POST_OFFICIAL_MINUS_RAW_KNOWN_USD = 0.005037


def _task(index: int) -> str:
    return f"chronos-r2-water4-study-claude-none-s{index:02d}-v1"


def _folder(index: int) -> str:
    return f"round2_water4_study_claude_none_s{index:02d}_v1"


def _execution(index: int) -> dict:
    task = _task(index)
    root = (
        RUNS
        / f"s{index:02d}"
        / task
        / "1"
        / shard_base.MODEL_SLUG
        / str(RUN_IDS[index])
    )
    return {
        "shard_index": index,
        "execution_kind": "baseline",
        "task": task,
        "canonical_task": task,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": _folder(index),
        "output_root": root / _folder(index),
        "source": staged_batch._source(index),
        "transport_source": staged_batch._wrapper(index),
        "recovery_builder": None,
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


def _manifest_hash(value: dict) -> str:
    return evidence_base._canonical_hash(
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
    raw = evidence_base._read_pinned(
        record,
        POST_BATCH_QUOTA_ATTESTATION,
        "Claude batch04 post-batch quota attestation",
    )
    attestation = json.loads(raw)
    artifacts = shard_base._artifact_paths(EXECUTIONS[0])
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task") != _task(17)
        or attestation.get("run_context", {}).get("run_id") != RUN_IDS[17]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_OFFICIAL_DAILY_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Claude batch04 quota evidence changed")
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
    shards = [shard_base._build_shard_record(execution) for execution in EXECUTIONS]
    if staged.get("batch_manifest_sha256") != (
        "cc021c075fa64294605933c8456324bce4c1a03f3204bf17fd73c5865c7b95c9"
    ):
        raise ValueError("Claude batch04 prelaunch manifest changed")
    manifest = {
        "schema": "chronos.experiment-a-claude-none-batch04-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "claude_none_batch04_shard_17",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": evidence_base._file_record(PRELAUNCH_MANIFEST),
        "post_batch_quota_attestation": evidence_base._file_record(
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
        raise ValueError("invalid Claude batch04 collection schema")
    if manifest.get("collection_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Claude batch04 collection self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous = _previous()
    staged = staged_batch._load()
    evidence_base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Claude batch04 prelaunch manifest",
    )
    quota = _verify_quota(manifest["post_batch_quota_attestation"])
    if (
        manifest["schema"]
        != "chronos.experiment-a-claude-none-batch04-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "claude_none_batch04_shard_17"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
        or staged["batch_manifest_sha256"]
        != json.loads(PRELAUNCH_MANIFEST.read_text())["batch_manifest_sha256"]
        or manifest["post_batch_quota_attestation_sha256"]
        != quota["attestation_sha256"]
        or manifest["shard_count"] != 1
        or manifest["job_count"] != 23
        or manifest["planned_calls"] != 91
    ):
        raise ValueError("Claude batch04 top-level contract changed")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Claude batch04 shard indexes changed")
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
        or len(all_ids) != 23
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 91
    ):
        raise ValueError("Claude batch04 is not its deterministic disjoint subset")
    totals = _totals([{"accounting": item["accounting"]} for item in verified])
    evidence_base._require_equal(manifest["totals"], totals, "collection totals")
    fixed = {
        "completed_jobs": 23,
        "planned_calls": 91,
        "observed_invocations": 91,
        "complete_calls": 91,
        "failed_calls": 0,
        "unknown_cost_calls": 0,
        "invalid_json_lines": 0,
        "events": 137,
        "started_attempts": 23,
    }
    if any(totals[key] != expected for key, expected in fixed.items()):
        raise ValueError("Claude batch04 accounting topology changed")
    for key, expected in (
        ("batch_known_cost_usd", BATCH_KNOWN_COST_USD),
        ("post_batch_raw_known_daily_cost_usd", POST_BATCH_RAW_KNOWN_DAILY_USD),
        ("official_quota_delta_usd", OFFICIAL_QUOTA_DELTA_USD),
        ("official_delta_minus_batch_known_usd", 0.0),
        (
            "post_official_minus_raw_known_usd",
            POST_OFFICIAL_MINUS_RAW_KNOWN_USD,
        ),
    ):
        if not math.isclose(totals[key], expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"Claude batch04 cost changed: {key}")
    return {
        "schema": "chronos.experiment-a-claude-none-batch04-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 1,
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
        "PASS Claude-none batch04: {completed_jobs}/23 jobs, "
        "{planned_calls} planned / {observed_invocations} measured calls, "
        "{failed_calls} failed calls, ${batch_known_cost_usd:.7f} batch, "
        "${post_batch_official_daily_quota_used_usd:.7f} official daily used; "
        "one shard disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
