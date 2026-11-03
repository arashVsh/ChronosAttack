"""Generate and verify Terra Experiment A shards 20--21."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_terra_batch01 as base
import verify_experiment_a_terra_batch03_collection as previous_collection


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch03"
MANIFEST = GENERATED / "experiment_a_terra_batch04_tasks_v1.json"
FROZEN_AT = "2026-09-22T17:15:37.741761+00:00"
SHARDS = tuple(range(20, 22))
EXPECTED_JOB_COUNT = 46
EXPECTED_PLANNED_CALLS = 146
EXPECTED_AGGREGATE_CEILING_USD = 1.34

QUOTA_ATTESTATION = RUNS / "quota_after_terra_batch03_20260922_v1.json"
FINAL_EXECUTION = previous_collection.EXECUTIONS[-1]
QUOTA_EVIDENCE = (
    FINAL_EXECUTION["output_root"] / "openai_gpt-5.6-terra.jsonl"
)
QUOTA_TERMINAL = FINAL_EXECUTION["output_root"] / "terminal.json"

PATCHES = {
    "MANIFEST": MANIFEST,
    "FROZEN_AT": FROZEN_AT,
    "SHARDS": SHARDS,
    "EXPECTED_JOB_COUNT": EXPECTED_JOB_COUNT,
    "EXPECTED_PLANNED_CALLS": EXPECTED_PLANNED_CALLS,
    "EXPECTED_AGGREGATE_CEILING_USD": EXPECTED_AGGREGATE_CEILING_USD,
    "EXPECTED_PREVIOUS_REMAINING_JOBS": 230,
    "PREVIOUS_SHARDS": tuple(range(20)),
    "EXPECTED_CUMULATIVE_JOB_COUNT": 506,
    "BATCH_NAME": "terra_batch04_shards_20_21",
    "BATCH_DISPLAY": "TERRA BATCH04",
    "PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD": 8.0059591,
    "PRE_LAUNCH_OFFICIAL_MINUS_RAW_KNOWN_USD": 0.0,
    "EXPECTED_QUOTA_RUN_ID": 2786322,
    "EXPECTED_QUOTA_USED_USD": 8.0059591,
    "EXPECTED_QUOTA_ALLOWED_USD": 10.0,
    "LAUNCH_POLICY": (
        "exactly_shards_20_21_may_run; no_later_Terra_shard_may_launch_"
        "before_batch04_is_sealed_and_fresh_quota_is_attested"
    ),
    "QUOTA_ATTESTATION": QUOTA_ATTESTATION,
    "QUOTA_EVIDENCE": QUOTA_EVIDENCE,
    "QUOTA_TERMINAL": QUOTA_TERMINAL,
}


@lru_cache(maxsize=1)
def _sealed_previous() -> dict:
    return previous_collection.verify()


@contextmanager
def _batch04_base():
    sealed_previous = _sealed_previous()
    previous_function = base._previous
    previous_function.cache_clear()
    previous = {name: getattr(base, name) for name in PATCHES}
    for name, value in PATCHES.items():
        setattr(base, name, value)
    base._previous = lambda: sealed_previous
    base.build_source.cache_clear()
    base._quota.cache_clear()
    try:
        yield
    finally:
        base.build_source.cache_clear()
        base._quota.cache_clear()
        base._previous = previous_function
        previous_function.cache_clear()
        for name, value in previous.items():
            setattr(base, name, value)


def _task(shard: int) -> str:
    return base._task(shard)


def _folder(shard: int) -> str:
    return base._folder(shard)


def _source(shard: int) -> Path:
    return base._source(shard)


def _manifest_hash(value: dict) -> str:
    return base._manifest_hash(value)


def build_source(shard: int) -> str:
    with _batch04_base():
        return base.build_source(shard)


def write_sources() -> None:
    with _batch04_base():
        base.write_sources()


def build_manifest() -> dict:
    with _batch04_base():
        return base.build_manifest()


def _load(value: dict | None = None) -> dict:
    with _batch04_base():
        return base._load(value)


def verify(value: dict | None = None) -> dict:
    with _batch04_base():
        return base.verify(value)


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
            f"{record['planned_calls']} calls, source {record['source']['sha256']}"
        )
    print(
        f"TERRA BATCH04 STAGED: {len(SHARDS)} tasks / "
        f"{EXPECTED_JOB_COUNT} jobs / {EXPECTED_PLANNED_CALLS} calls; "
        f"aggregate ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        f"maximum daily exposure ${checked['maximum_daily_exposure_usd']:.7f}"
    )


if __name__ == "__main__":
    main()
