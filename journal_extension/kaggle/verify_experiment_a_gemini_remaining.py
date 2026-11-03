"""Stage Gemini Experiment A shards 05--29 after an attested quota reset."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math

import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_gemini_batch00 as cell_stage
import verify_experiment_a_gemini_batch03_collection as previous_collection
import verify_experiment_a_qwen_batch00_collection as evidence_base


GENERATED = cell_stage.GENERATED
MANIFEST = GENERATED / "experiment_a_gemini_remaining_tasks_v1.json"
SHARDS = tuple(range(5, 30))
WAVES = (tuple(range(5, 13)), tuple(range(13, 21)), tuple(range(21, 30)))
INCREMENTAL_CEILING_USD = cell_stage.INCREMENTAL_CEILING_USD

QUOTA_ATTESTATION = (
    cell_stage.HERE
    / "round2_runs_20260920/experiment_a_gemini_batch03"
    / "quota_reset_before_gemini_remaining_20260921_v1.json"
)
QUOTA_EVIDENCE = (
    cell_stage.HERE
    / "round2_runs_20260920/experiment_a_gemini_batch03/s04"
    / "chronos-r2-water4-study-gemini-minimal-s04-v1/1"
    / "gemini-3.6-flash/2692525"
    / "round2_water4_study_gemini_minimal_s04_v1"
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
    return cell_stage._canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "batch_manifest_sha256"
        }
    )


def write_sources() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for shard in SHARDS:
        path = cell_stage._source(shard)
        path.write_text(
            cell_stage.cell_builder.build_source(**cell_stage._arguments(shard))
        )
        print(f"WROTE {path}")


def _wave_records(records: list[dict]) -> list[dict]:
    by_shard = {record["shard_index"]: record for record in records}
    return [
        {
            "wave": number,
            "shards": list(shards),
            "task_count": len(shards),
            "job_count": sum(by_shard[index]["job_count"] for index in shards),
            "planned_calls": sum(
                by_shard[index]["planned_calls"] for index in shards
            ),
            "aggregate_incremental_ceiling_usd": round(
                math.fsum(
                    by_shard[index]["incremental_ceiling_usd"]
                    for index in shards
                ),
                12,
            ),
        }
        for number, shards in enumerate(WAVES, start=1)
    ]


def build_manifest() -> dict:
    previous = _previous()
    quota = _quota()
    records = [cell_stage._record(shard) for shard in SHARDS]
    used = quota["response"]["daily_quota_used_usd"]
    allowed = quota["response"]["total_daily_quota_allowed_usd"]
    aggregate = round(
        math.fsum(
            record["incremental_ceiling_usd"] for record in records
        ),
        12,
    )
    manifest = {
        "schema": "chronos.experiment-a-full-batch-tasks.v1",
        "batch_manifest_sha256": None,
        "frozen_at": quota["queried_at_end_utc"],
        "status": "authorized_not_launched",
        "batch": "gemini_remaining_shards_05_29",
        "model": cell_stage.MODEL,
        "reasoning": cell_stage.REASONING,
        "role": cell_stage.ROLE,
        "study_id": cell_stage.STUDY_ID,
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
        "launch_policy": (
            "three_ordered_waves_05_12_then_13_20_then_21_29; "
            "waves_may_not_overlap"
        ),
        "shard_count_total": cell_stage.cell_builder.SHARD_COUNT,
        "batch_shards": list(SHARDS),
        "waves": _wave_records(records),
        "task_count": len(records),
        "job_count": sum(record["job_count"] for record in records),
        "planned_calls": sum(record["planned_calls"] for record in records),
        "tasks": records,
    }
    manifest["batch_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if manifest.get("batch_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Experiment A Gemini remaining self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Experiment A Gemini remaining differs from regeneration")
    if (
        manifest["status"] != "authorized_not_launched"
        or manifest["task_count"] != 25
        or manifest["job_count"] != 575
        or manifest["planned_calls"] != 1939
        or manifest["aggregate_incremental_ceiling_usd"] != 7.0
        or manifest["maximum_daily_exposure_usd"] > manifest["daily_limit_usd"]
        or [wave["planned_calls"] for wave in manifest["waves"]]
        != [616, 624, 699]
        or [wave["aggregate_incremental_ceiling_usd"] for wave in manifest["waves"]]
        != [2.24, 2.24, 2.52]
    ):
        raise ValueError("Experiment A Gemini remaining topology or budget changed")
    identities = {record["identity"] for record in manifest["tasks"]}
    job_ids = []
    for shard, record in zip(SHARDS, manifest["tasks"]):
        path = cell_stage._source(shard)
        raw = path.read_bytes()
        if (
            record["shard_index"] != shard
            or record["task"] != cell_stage._task(shard)
            or record["source"]["sha256"] != cell_stage._sha256(raw)
            or record["source"]["bytes"] != len(raw)
            or raw.decode()
            != cell_stage.cell_builder.build_source(**cell_stage._arguments(shard))
            or record["incremental_ceiling_usd"]
            != INCREMENTAL_CEILING_USD
            or record["effective_ceiling_usd"]
            != INCREMENTAL_CEILING_USD
        ):
            raise ValueError("Experiment A Gemini remaining source changed")
        values = cell_stage._assignments(raw.decode(), path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            contract["shard_index"] != shard
            or contract["shard_count"] != cell_stage.cell_builder.SHARD_COUNT
            or contract["parent_ledger_sha256"] is not None
            or contract["resume_ledger"]["events"] != 0
            or len(jobs) != 23
            or sum(job["calls"] for job in jobs) != record["planned_calls"]
            or contract["pilot_receipt_sha256"]
            != record["pilot_receipt_sha256"]
        ):
            raise ValueError("Experiment A Gemini remaining contract changed")
        compile(raw.decode(), str(path), "exec")
        job_ids.extend(job["id"] for job in jobs)
    if len(identities) != 1 or len(job_ids) != len(set(job_ids)):
        raise ValueError("Experiment A Gemini remaining shards collide")
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
    for wave in checked["waves"]:
        print(
            f"PASS wave {wave['wave']}: {wave['task_count']} tasks / "
            f"{wave['job_count']} jobs / {wave['planned_calls']} calls / "
            f"${wave['aggregate_incremental_ceiling_usd']:.2f} ceiling"
        )
    print(
        "GEMINI REMAINING STAGED: 25 tasks / 575 jobs / 1939 calls; "
        f"aggregate ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        f"maximum daily exposure ${checked['maximum_daily_exposure_usd']:.8f}"
    )


if __name__ == "__main__":
    main()
