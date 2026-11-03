"""Generate and verify authorized Qwen Experiment A shards 21--25."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math

import verify_experiment_a_qwen_batch01 as stage_base
import verify_experiment_a_qwen_batch02_collection as previous_collection


GENERATED = stage_base.GENERATED
MANIFEST = GENERATED / "experiment_a_qwen_batch03_tasks_v1.json"
FROZEN_AT = "2026-09-20T23:45:58+03:30"
SHARDS = tuple(range(21, 26))
INCREMENTAL_CEILING_USD = stage_base.INCREMENTAL_CEILING_USD
DAILY_LIMIT_USD = stage_base.DAILY_LIMIT_USD


@lru_cache(maxsize=1)
def _previous() -> dict:
    return previous_collection.verify()


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
    records = [stage_base._record(shard) for shard in SHARDS]
    current = previous["post_batch_known_daily_cost_usd"]
    aggregate = math.fsum(
        record["incremental_ceiling_usd"] for record in records
    )
    manifest = {
        "schema": "chronos.experiment-a-full-batch-tasks.v1",
        "batch_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "batch": "qwen_batch03_shards_21_25",
        "model": stage_base.MODEL,
        "reasoning": stage_base.REASONING,
        "role": stage_base.ROLE,
        "study_id": stage_base.STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "pre_launch_known_daily_cost_usd": current,
        "daily_limit_usd": DAILY_LIMIT_USD,
        "incremental_ceiling_per_task_usd": INCREMENTAL_CEILING_USD,
        "aggregate_incremental_ceiling_usd": aggregate,
        "maximum_daily_exposure_usd": current + aggregate,
        "launch_policy": (
            "all_five_may_run_concurrently_within_sealed_exposure"
        ),
        "shard_count_total": stage_base.cell_builder.SHARD_COUNT,
        "batch_shards": list(SHARDS),
        "task_count": len(records),
        "job_count": sum(record["job_count"] for record in records),
        "planned_calls": sum(record["planned_calls"] for record in records),
        "tasks": records,
    }
    manifest["batch_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if manifest.get("batch_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Experiment A Qwen batch03 self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Experiment A Qwen batch03 differs from regeneration")
    if (
        manifest["status"] != "authorized_not_launched"
        or manifest["task_count"] != 5
        or manifest["job_count"] != 115
        or manifest["planned_calls"] != 391
        or manifest["aggregate_incremental_ceiling_usd"] != 0.8
        or manifest["maximum_daily_exposure_usd"] > DAILY_LIMIT_USD
    ):
        raise ValueError("Experiment A Qwen batch03 topology or budget changed")
    identities = {record["identity"] for record in manifest["tasks"]}
    job_ids = []
    for shard, record in zip(SHARDS, manifest["tasks"]):
        path = stage_base._source(shard)
        raw = path.read_bytes()
        if (
            record["shard_index"] != shard
            or record["task"] != stage_base._task(shard)
            or record["source"]["sha256"] != stage_base._sha256(raw)
            or record["source"]["bytes"] != len(raw)
            or raw.decode()
            != stage_base.cell_builder.build_source(
                **stage_base._arguments(shard)
            )
            or record["incremental_ceiling_usd"]
            != INCREMENTAL_CEILING_USD
            or record["effective_ceiling_usd"]
            != INCREMENTAL_CEILING_USD
        ):
            raise ValueError("Experiment A Qwen batch03 source changed")
        values = stage_base._assignments(raw.decode(), path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            contract["shard_index"] != shard
            or contract["shard_count"]
            != stage_base.cell_builder.SHARD_COUNT
            or contract["parent_ledger_sha256"] is not None
            or contract["resume_ledger"]["events"] != 0
            or len(jobs) != 23
            or sum(job["calls"] for job in jobs) != record["planned_calls"]
            or contract["pilot_receipt_sha256"]
            != record["pilot_receipt_sha256"]
        ):
            raise ValueError("Experiment A Qwen batch03 contract changed")
        compile(raw.decode(), str(path), "exec")
        job_ids.extend(job["id"] for job in jobs)
    if len(identities) != 1 or len(job_ids) != len(set(job_ids)):
        raise ValueError("Experiment A Qwen batch03 shards collide")
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
    for record in checked["tasks"]:
        print(
            f"PASS s{record['shard_index']:02d}: {record['job_count']} jobs / "
            f"{record['planned_calls']} calls, source "
            f"{record['source']['sha256']}"
        )
    print(
        "QWEN BATCH03 STAGED: 5 tasks / 115 jobs / "
        f"{checked['planned_calls']} calls; aggregate ceiling "
        f"${checked['aggregate_incremental_ceiling_usd']:.2f}; maximum daily "
        f"exposure ${checked['maximum_daily_exposure_usd']:.8f}"
    )


if __name__ == "__main__":
    main()
