"""Stage Terra Experiment A shards 27--29 after the daily quota reset."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_terra_batch01 as base
import verify_experiment_a_terra_batch08_collection as previous_collection


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch09"
MANIFEST = GENERATED / "experiment_a_terra_batch10_tasks_v1.json"
FROZEN_AT = "2026-09-23T15:00:33.127489+00:00"
SHARDS = (27, 28, 29)
QUOTA_ATTESTATION = RUNS / "quota_before_terra_batch09_20260923_v1.json"
FINAL_EXECUTION = previous_collection.EXECUTIONS[-1]

PATCHES = {
    "MANIFEST": MANIFEST,
    "FROZEN_AT": FROZEN_AT,
    "SHARDS": SHARDS,
    "EXPECTED_JOB_COUNT": 69,
    "EXPECTED_PLANNED_CALLS": 237,
    "EXPECTED_AGGREGATE_CEILING_USD": 2.01,
    "EXPECTED_PREVIOUS_REMAINING_JOBS": 69,
    "PREVIOUS_SHARDS": tuple(range(27)),
    "EXPECTED_CUMULATIVE_JOB_COUNT": 690,
    "BATCH_NAME": "terra_batch10_shards_27_29",
    "BATCH_DISPLAY": "TERRA BATCH10",
    "PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD": 0.0,
    "PRE_LAUNCH_OFFICIAL_MINUS_RAW_KNOWN_USD": 0.0,
    "EXPECTED_QUOTA_RUN_ID": 2792886,
    "EXPECTED_QUOTA_USED_USD": 0.0,
    "EXPECTED_QUOTA_ALLOWED_USD": 10.0,
    "LAUNCH_POLICY": (
        "exactly_shards_27_29_may_run; no_experiment_B_model_call_may_launch_"
        "before_batch10_is_sealed"
    ),
    "QUOTA_ATTESTATION": QUOTA_ATTESTATION,
    "QUOTA_EVIDENCE": (
        FINAL_EXECUTION["output_root"] / "openai_gpt-5.6-terra.jsonl"
    ),
    "QUOTA_TERMINAL": FINAL_EXECUTION["output_root"] / "terminal.json",
}


@lru_cache(maxsize=1)
def _sealed_previous() -> dict:
    return previous_collection.verify()


@contextmanager
def _batch10_base():
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


def _load(value: dict | None = None) -> dict:
    with _batch10_base():
        return base._load(value)


def build_manifest() -> dict:
    with _batch10_base():
        return base.build_manifest()


def verify(value: dict | None = None) -> dict:
    with _batch10_base():
        return base.verify(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        with _batch10_base():
            base.write_sources()
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['batch_manifest_sha256']}")
    checked = verify()
    print(
        "PASS Terra batch10: {job_count}/69 jobs, {planned_calls}/237 "
        "planned calls, ${aggregate_incremental_ceiling_usd:.2f} reserved; "
        "maximum daily exposure ${maximum_daily_exposure_usd:.2f}".format(
            **checked
        )
    )


if __name__ == "__main__":
    main()
