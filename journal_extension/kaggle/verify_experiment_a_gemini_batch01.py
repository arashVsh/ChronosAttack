"""Generate and verify quota-bounded Gemini Experiment A shard 02."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json

import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_gemini_batch00 as stage_base
import verify_experiment_a_gemini_batch00_collection as previous_collection
import verify_experiment_a_qwen_batch00_collection as evidence_base


GENERATED = stage_base.GENERATED
MANIFEST = GENERATED / "experiment_a_gemini_batch01_tasks_v1.json"
FROZEN_AT = "2026-09-21T00:52:42+03:30"
SHARDS = (2,)
INCREMENTAL_CEILING_USD = stage_base.INCREMENTAL_CEILING_USD

QUOTA_ATTESTATION = (
    stage_base.HERE
    / "round2_runs_20260920/experiment_a_gemini_batch00"
    / "quota_after_gemini_batch00_20260921_v1.json"
)
QUOTA_EVIDENCE = (
    stage_base.HERE
    / "round2_runs_20260920/experiment_a_gemini_batch00/s01"
    / "chronos-r2-water4-study-gemini-minimal-s01-v1/1"
    / "gemini-3.6-flash/2689029"
    / "round2_water4_study_gemini_minimal_s01_v1"
    / "google_gemini-3.6-flash.jsonl"
)
QUOTA_TERMINAL = QUOTA_EVIDENCE.with_name("terminal.json")


@lru_cache(maxsize=1)
def _previous() -> dict:
    return previous_collection.verify()


@lru_cache(maxsize=1)
def _quota() -> dict:
    attestation = json.loads(QUOTA_ATTESTATION.read_text())
    quota_capture.verify_attestation(
        attestation,
        QUOTA_EVIDENCE.read_bytes(),
        QUOTA_TERMINAL.read_bytes(),
    )
    return attestation


def _manifest_hash(manifest: dict) -> str:
    return stage_base._canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "batch_manifest_sha256"
        }
    )


def write_sources() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for shard in SHARDS:
        path = stage_base._source(shard)
        path.write_text(
            stage_base.cell_builder.build_source(**stage_base._arguments(shard))
        )
        print(f"WROTE {path}")


def build_manifest() -> dict:
    previous = _previous()
    quota = _quota()
    records = [stage_base._record(shard) for shard in SHARDS]
    used = quota["response"]["daily_quota_used_usd"]
    allowed = quota["response"]["total_daily_quota_allowed_usd"]
    aggregate = sum(record["incremental_ceiling_usd"] for record in records)
    manifest = {
        "schema": "chronos.experiment-a-full-batch-tasks.v1",
        "batch_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "batch": "gemini_batch01_shard_02",
        "model": stage_base.MODEL,
        "reasoning": stage_base.REASONING,
        "role": stage_base.ROLE,
        "study_id": stage_base.STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "quota_attestation": evidence_base._file_record(QUOTA_ATTESTATION),
        "quota_attestation_sha256": quota["attestation_sha256"],
        "pre_launch_known_daily_cost_usd": used,
        "daily_limit_usd": allowed,
        "incremental_ceiling_per_task_usd": INCREMENTAL_CEILING_USD,
        "aggregate_incremental_ceiling_usd": aggregate,
        "maximum_daily_exposure_usd": used + aggregate,
        "launch_policy": "exactly_one_shard_may_run_within_sealed_exposure",
        "shard_count_total": stage_base.cell_builder.SHARD_COUNT,
        "batch_shards": list(SHARDS),
        "task_count": 1,
        "job_count": records[0]["job_count"],
        "planned_calls": records[0]["planned_calls"],
        "tasks": records,
    }
    manifest["batch_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if manifest.get("batch_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Experiment A Gemini batch01 self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Experiment A Gemini batch01 differs from regeneration")
    if (
        manifest["status"] != "authorized_not_launched"
        or manifest["task_count"] != 1
        or manifest["job_count"] != 23
        or manifest["planned_calls"] != 79
        or manifest["aggregate_incremental_ceiling_usd"] != 0.28
        or manifest["maximum_daily_exposure_usd"] > manifest["daily_limit_usd"]
    ):
        raise ValueError("Experiment A Gemini batch01 topology or budget changed")
    record = manifest["tasks"][0]
    path = stage_base._source(2)
    raw = path.read_bytes()
    if (
        record["shard_index"] != 2
        or record["task"] != stage_base._task(2)
        or record["source"]["sha256"] != stage_base._sha256(raw)
        or record["source"]["bytes"] != len(raw)
        or raw.decode()
        != stage_base.cell_builder.build_source(**stage_base._arguments(2))
        or record["incremental_ceiling_usd"] != INCREMENTAL_CEILING_USD
        or record["effective_ceiling_usd"] != INCREMENTAL_CEILING_USD
    ):
        raise ValueError("Experiment A Gemini batch01 source changed")
    values = stage_base._assignments(raw.decode(), path)
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    if (
        contract["shard_index"] != 2
        or contract["shard_count"] != stage_base.cell_builder.SHARD_COUNT
        or contract["parent_ledger_sha256"] is not None
        or contract["resume_ledger"]["events"] != 0
        or len(jobs) != 23
        or sum(job["calls"] for job in jobs) != 79
        or contract["pilot_receipt_sha256"]
        != record["pilot_receipt_sha256"]
    ):
        raise ValueError("Experiment A Gemini batch01 contract changed")
    compile(raw.decode(), str(path), "exec")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        write_sources()
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['batch_manifest_sha256']}")
    checked = verify()
    record = checked["tasks"][0]
    print(
        f"PASS s02: {record['job_count']} jobs / {record['planned_calls']} calls, "
        f"source {record['source']['sha256']}"
    )
    print(
        "GEMINI BATCH01 STAGED: 1 task / 23 jobs / 79 calls; aggregate "
        f"ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        f"maximum daily exposure ${checked['maximum_daily_exposure_usd']:.8f}"
    )


if __name__ == "__main__":
    main()
