"""Generate and verify the first Claude-none Experiment A shard wave."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

import build_experiment_a_cell_v1 as cell_builder
import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_gemini_batch00 as stage_base
import verify_experiment_a_gemini_remaining_wave03_collection as previous_collection
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch00"
MANIFEST = GENERATED / "experiment_a_claude_none_batch00_tasks_v1.json"
FROZEN_AT = "2026-09-21T19:08:59.002937+00:00"
MODEL = "anthropic/claude-sonnet-4-6@default"
REASONING = "none"
ROLE = "reasoning_off_sensitivity"
STUDY_ID = "chronos_round2_water4_study_claude_none_v1"
SHARDS = tuple(range(7))
INCREMENTAL_CEILING_USD = 1.09

QUOTA_ATTESTATION = RUNS / "quota_before_claude_none_batch00_20260921_v1.json"
QUOTA_EVIDENCE = (
    HERE
    / "round2_runs_20260920/experiment_a_gemini_remaining_wave03/s29"
    / "chronos-r2-water4-study-gemini-minimal-s29-repair-v1/1"
    / "gemini-3.6-flash/2719337"
    / "round2_water4_study_gemini_minimal_s29_v1"
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


def _task(shard: int) -> str:
    return f"chronos-r2-water4-study-claude-none-s{shard:02d}-v1"


def _folder(shard: int) -> str:
    return f"round2_water4_study_claude_none_s{shard:02d}_v1"


def _source(shard: int) -> Path:
    return GENERATED / f"water4_study_claude_none_s{shard:02d}_v1.py"


def _arguments(shard: int) -> dict:
    return {
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "shard_index": shard,
        "shard_count": cell_builder.SHARD_COUNT,
        "task_name": _task(shard),
        "output_folder": _folder(shard),
    }


def _record(shard: int) -> dict:
    path = _source(shard)
    raw = path.read_bytes()
    values = stage_base._assignments(raw.decode(), path)
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    return {
        "shard_index": shard,
        "shard_count": cell_builder.SHARD_COUNT,
        "task": _task(shard),
        "output_folder": _folder(shard),
        "source_status": "frozen_prelaunch",
        "source": {
            "path": str(path.relative_to(ROOT)),
            "sha256": stage_base._sha256(raw),
            "bytes": len(raw),
        },
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": contract["manifest_sha256"],
        "identity": contract["identity"],
        "pilot_receipt_sha256": contract["pilot_receipt_sha256"],
        "incremental_ceiling_usd": contract["incremental_ceiling_usd"],
        "effective_ceiling_usd": contract["effective_ceiling_usd"],
    }


def write_sources() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for shard in SHARDS:
        path = _source(shard)
        path.write_text(cell_builder.build_source(**_arguments(shard)))
        print(f"WROTE {path}")


def build_manifest() -> dict:
    previous = _previous()
    quota = _quota()
    records = [_record(shard) for shard in SHARDS]
    used = quota["response"]["daily_quota_used_usd"]
    allowed = quota["response"]["total_daily_quota_allowed_usd"]
    aggregate = round(
        math.fsum(record["incremental_ceiling_usd"] for record in records),
        12,
    )
    manifest = {
        "schema": "chronos.experiment-a-full-batch-tasks.v1",
        "batch_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "batch": "claude_none_batch00_shards_00_06",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
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
            "exactly_shards_00_06_may_run; no_later_claude_shard_may_launch_"
            "before_batch00_is_sealed_and_fresh_quota_is_attested"
        ),
        "shard_count_total": cell_builder.SHARD_COUNT,
        "batch_shards": list(SHARDS),
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
        raise ValueError("Experiment A Claude-none batch00 self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError(
            "Experiment A Claude-none batch00 differs from regeneration"
        )
    previous = _previous()
    quota = _quota()
    if (
        manifest["frozen_at"] != quota["queried_at_end_utc"]
        or previous["remaining_jobs"] != 0
        or not math.isclose(
            previous["post_batch_known_daily_cost_usd"],
            manifest["pre_launch_known_daily_cost_usd"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or manifest["status"] != "authorized_not_launched"
        or manifest["task_count"] != 7
        or manifest["job_count"] != 161
        or manifest["planned_calls"] != 513
        or manifest["aggregate_incremental_ceiling_usd"] != 7.63
        or manifest["maximum_daily_exposure_usd"] > manifest["daily_limit_usd"]
    ):
        raise ValueError(
            "Experiment A Claude-none batch00 topology or budget changed"
        )

    identities = {record["identity"] for record in manifest["tasks"]}
    job_ids = []
    for shard, record in zip(SHARDS, manifest["tasks"]):
        path = _source(shard)
        raw = path.read_bytes()
        regenerated = cell_builder.build_source(**_arguments(shard))
        values = stage_base._assignments(raw.decode(), path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            record["shard_index"] != shard
            or record["task"] != _task(shard)
            or record["source"]["sha256"] != stage_base._sha256(raw)
            or record["source"]["bytes"] != len(raw)
            or raw.decode() != regenerated
            or record["incremental_ceiling_usd"]
            != INCREMENTAL_CEILING_USD
            or record["effective_ceiling_usd"]
            != INCREMENTAL_CEILING_USD
            or contract["shard_index"] != shard
            or contract["shard_count"] != cell_builder.SHARD_COUNT
            or contract["parent_ledger_sha256"] is not None
            or contract["resume_ledger"]["events"] != 0
            or len(jobs) != 23
            or sum(job["calls"] for job in jobs) != record["planned_calls"]
            or contract["pilot_receipt_sha256"]
            != record["pilot_receipt_sha256"]
        ):
            raise ValueError("Experiment A Claude-none batch00 source changed")
        compile(raw.decode(), str(path), "exec")
        job_ids.extend(job["id"] for job in jobs)
    if (
        len(identities) != 1
        or len(job_ids) != 161
        or len(job_ids) != len(set(job_ids))
    ):
        raise ValueError("Experiment A Claude-none batch00 shards collide")
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
        "CLAUDE-NONE BATCH00 STAGED: 7 tasks / 161 jobs / 513 calls; "
        "aggregate ceiling "
        f"${checked['aggregate_incremental_ceiling_usd']:.2f}; maximum daily "
        f"exposure ${checked['maximum_daily_exposure_usd']:.8f}"
    )


if __name__ == "__main__":
    main()
