"""Generate and verify final Claude-none Experiment A shards 28--29."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_claude_none_batch01 as base
import verify_experiment_a_claude_none_batch06_collection as previous_collection


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch06"
MANIFEST = GENERATED / "experiment_a_claude_none_batch07_tasks_v1.json"
FROZEN_AT = "2026-09-22T15:03:46.346592+00:00"
SHARDS = tuple(range(28, 30))
EXPECTED_JOB_COUNT = 46
EXPECTED_PLANNED_CALLS = 158
EXPECTED_AGGREGATE_CEILING_USD = 2.18

QUOTA_ATTESTATION = (
    RUNS / "quota_after_claude_none_batch06_20260922_v1.json"
)
FINAL_EXECUTION = next(
    item for item in previous_collection.EXECUTIONS if item["shard_index"] == 21
)
QUOTA_EVIDENCE = previous_collection.shard_base._artifact_paths(FINAL_EXECUTION)[
    "evidence"
]
QUOTA_TERMINAL = previous_collection.shard_base._artifact_paths(FINAL_EXECUTION)[
    "terminal"
]

PATCHES = {
    "MANIFEST": MANIFEST,
    "FROZEN_AT": FROZEN_AT,
    "SHARDS": SHARDS,
    "EXPECTED_JOB_COUNT": EXPECTED_JOB_COUNT,
    "EXPECTED_PLANNED_CALLS": EXPECTED_PLANNED_CALLS,
    "EXPECTED_AGGREGATE_CEILING_USD": EXPECTED_AGGREGATE_CEILING_USD,
    "BATCH_NAME": "claude_none_batch07_shards_28_29",
    "BATCH_DISPLAY": "CLAUDE-NONE BATCH07",
    "EXPECTED_PREVIOUS_REMAINING_JOBS": 46,
    "PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD": 3.2088504,
    "PRE_LAUNCH_OFFICIAL_MINUS_RAW_KNOWN_USD": 0.0,
    "EXPECTED_QUOTA_RUN_ID": 2780402,
    "EXPECTED_QUOTA_USED_USD": 3.2088504,
    "EXPECTED_QUOTA_ALLOWED_USD": 10.0,
    "LAUNCH_POLICY": (
        "exactly_final_shards_28_29_may_run; Claude-none Experiment A is "
        "complete only after batch07 is sealed and fresh quota is attested"
    ),
    "QUOTA_ATTESTATION": QUOTA_ATTESTATION,
    "QUOTA_EVIDENCE": QUOTA_EVIDENCE,
    "QUOTA_TERMINAL": QUOTA_TERMINAL,
}


@lru_cache(maxsize=1)
def _sealed_previous() -> dict:
    return previous_collection.verify()


@contextmanager
def _batch07_base():
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


def _wrapper(shard: int) -> Path:
    return base._wrapper(shard)


def _manifest_hash(value: dict) -> str:
    return base._manifest_hash(value)


def build_source(shard: int) -> str:
    with _batch07_base():
        return base.build_source(shard)


def build_wrapper(shard: int) -> str:
    with _batch07_base():
        return base.build_wrapper(shard)


def write_sources() -> None:
    with _batch07_base():
        base.write_sources()


def build_manifest() -> dict:
    with _batch07_base():
        return base.build_manifest()


def _load(value: dict | None = None) -> dict:
    with _batch07_base():
        return base._load(value)


def verify(value: dict | None = None) -> dict:
    with _batch07_base():
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
            f"{record['planned_calls']} calls, source "
            f"{record['source']['sha256']}, wrapper "
            f"{record['transport_wrapper']['sha256']}"
        )
    print(
        f"CLAUDE-NONE BATCH07 STAGED: {len(SHARDS)} tasks / "
        f"{EXPECTED_JOB_COUNT} jobs / {EXPECTED_PLANNED_CALLS} calls; "
        f"aggregate ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        f"maximum daily exposure ${checked['maximum_daily_exposure_usd']:.7f}"
    )


if __name__ == "__main__":
    main()
