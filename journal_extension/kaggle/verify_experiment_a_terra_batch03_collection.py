"""Seal and independently verify Terra Experiment A shards 16--19."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_terra_batch01_collection as base
import verify_experiment_a_terra_batch03 as staged_batch


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch03"
MANIFEST = GENERATED / "experiment_a_terra_batch03_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_terra_batch03_tasks_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_terra_batch03_20260922_v1.json"
)
FROZEN_AT = "2026-09-22T17:15:37.741761+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {16: 2786331, 17: 2786332, 18: 2786323, 19: 2786322}


def _execution(index: int) -> dict:
    task = staged_batch._task(index)
    folder = staged_batch._folder(index)
    root = (
        RUNS
        / f"s{index:02d}"
        / task
        / "1"
        / base.MODEL_SLUG
        / str(RUN_IDS[index])
    )
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
EXPECTED_ACCOUNTING = {
    "completed_jobs": 92,
    "planned_calls": 320,
    "observed_invocations": 320,
    "complete_calls": 320,
    "failed_calls": 0,
    "unknown_cost_calls": 0,
    "invalid_json_lines": 0,
    "events": 504,
    "started_attempts": 92,
}

PATCHES = {
    "RUNS": RUNS,
    "MANIFEST": MANIFEST,
    "PRELAUNCH_MANIFEST": PRELAUNCH_MANIFEST,
    "POST_BATCH_QUOTA_ATTESTATION": POST_BATCH_QUOTA_ATTESTATION,
    "FROZEN_AT": FROZEN_AT,
    "SHARDS": SHARDS,
    "RUN_IDS": RUN_IDS,
    "EXECUTIONS": EXECUTIONS,
    "PRE_BATCH_RAW_KNOWN_DAILY_USD": 7.1235331,
    "PRE_BATCH_OFFICIAL_DAILY_USD": 7.1235331,
    "BATCH_KNOWN_COST_USD": 0.882426,
    "POST_BATCH_RAW_KNOWN_DAILY_USD": 8.0059591,
    "POST_BATCH_OFFICIAL_DAILY_USD": 8.0059591,
    "OFFICIAL_QUOTA_DELTA_USD": 0.882426,
    "POST_OFFICIAL_MINUS_RAW_KNOWN_USD": 0.0,
    "PRELAUNCH_MANIFEST_SHA256": (
        "7f9d8891235d830f24477ecda9af4299f4d4cca2e7d957a6064198427377dfad"
    ),
    "COLLECTION_SCHEMA": "chronos.experiment-a-terra-batch03-collection.v1",
    "VERIFICATION_SCHEMA": (
        "chronos.experiment-a-terra-batch03-verification.v1"
    ),
    "BATCH_NAME": "terra_batch03_shards_16_19",
    "BATCH_DISPLAY": "Terra batch03",
    "FINAL_SHARD": 19,
    "EXPECTED_SHARD_COUNT": 4,
    "EXPECTED_JOB_COUNT": 92,
    "EXPECTED_PLANNED_CALLS": 320,
    "EXPECTED_ACCOUNTING": EXPECTED_ACCOUNTING,
}


@lru_cache(maxsize=1)
def _sealed_previous() -> dict:
    return staged_batch._sealed_previous()


@contextmanager
def _batch03_base():
    staged = staged_batch._load()
    sealed_previous = _sealed_previous()
    previous_function = base._previous
    previous_function.cache_clear()
    previous = {name: getattr(base, name) for name in PATCHES}
    previous_staged_batch = base.staged_batch
    for name, value in PATCHES.items():
        setattr(base, name, value)
    base.staged_batch = type(
        "FrozenTerraBatch03Stage",
        (),
        {"_load": staticmethod(lambda value=None: staged)},
    )
    base._previous = lambda: sealed_previous
    try:
        yield
    finally:
        base._previous = previous_function
        previous_function.cache_clear()
        base.staged_batch = previous_staged_batch
        for name, value in previous.items():
            setattr(base, name, value)


def _manifest_hash(value: dict) -> str:
    return base._manifest_hash(value)


def build_manifest() -> dict:
    with _batch03_base():
        return base.build_manifest()


def _load_manifest(value: dict | None = None) -> dict:
    with _batch03_base():
        return base._load_manifest(value)


def verify(value: dict | None = None) -> dict:
    with _batch03_base():
        return base.verify(value)


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
        "PASS Terra batch03: {completed_jobs}/92 jobs, {planned_calls} planned / "
        "{observed_invocations} measured calls, {failed_calls} failed calls, "
        "${batch_known_cost_usd:.6f} batch, "
        "${post_batch_official_daily_quota_used_usd:.7f} official daily used; "
        "four shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
