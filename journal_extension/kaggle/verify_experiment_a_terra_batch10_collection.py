"""Seal and independently verify the final Terra Experiment A shards."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_terra_batch01_collection as base
import verify_experiment_a_terra_batch10 as staged_batch


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch10"
MANIFEST = GENERATED / "experiment_a_terra_batch10_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_terra_batch10_tasks_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_terra_batch10_20260923_v1.json"
)
FROZEN_AT = "2026-09-23T15:14:16.987076+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {27: 2839052, 28: 2839012, 29: 2839071}


def _execution(index: int) -> dict:
    task = staged_batch._task(index)
    folder = staged_batch._folder(index)
    root = RUNS / f"s{index:02d}" / task / "1" / base.MODEL_SLUG / str(RUN_IDS[index])
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
    "completed_jobs": 69,
    "planned_calls": 237,
    "observed_invocations": 237,
    "complete_calls": 237,
    "failed_calls": 0,
    "unknown_cost_calls": 0,
    "invalid_json_lines": 0,
    "events": 375,
    "started_attempts": 69,
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
    "PRE_BATCH_RAW_KNOWN_DAILY_USD": 0.0,
    "PRE_BATCH_OFFICIAL_DAILY_USD": 0.0,
    "BATCH_KNOWN_COST_USD": 0.666242,
    "POST_BATCH_RAW_KNOWN_DAILY_USD": 0.666242,
    "POST_BATCH_OFFICIAL_DAILY_USD": 0.666242,
    "OFFICIAL_QUOTA_DELTA_USD": 0.666242,
    "POST_OFFICIAL_MINUS_RAW_KNOWN_USD": 0.0,
    "PRELAUNCH_MANIFEST_SHA256": (
        "f80d8faa910383862ac63be072ebdaaa3aec68147df308515307d6b9cc37c0a8"
    ),
    "COLLECTION_SCHEMA": "chronos.experiment-a-terra-batch10-collection.v1",
    "VERIFICATION_SCHEMA": "chronos.experiment-a-terra-batch10-verification.v1",
    "BATCH_NAME": "terra_batch10_shards_27_29",
    "BATCH_DISPLAY": "Terra batch10",
    "FINAL_SHARD": 29,
    "EXPECTED_SHARD_COUNT": 3,
    "EXPECTED_JOB_COUNT": 69,
    "EXPECTED_PLANNED_CALLS": 237,
    "EXPECTED_ACCOUNTING": EXPECTED_ACCOUNTING,
}


@lru_cache(maxsize=1)
def _sealed_previous() -> dict:
    return staged_batch._sealed_previous()


@contextmanager
def _batch10_base():
    staged = staged_batch._load()
    sealed_previous = _sealed_previous()
    previous_function = base._previous
    previous_function.cache_clear()
    previous = {name: getattr(base, name) for name in PATCHES}
    previous_staged_batch = base.staged_batch
    for name, value in PATCHES.items():
        setattr(base, name, value)
    base.staged_batch = type(
        "FrozenTerraBatch10Stage",
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


def build_manifest() -> dict:
    with _batch10_base():
        return base.build_manifest()


def verify(value: dict | None = None) -> dict:
    with _batch10_base():
        checked = base.verify(value)
    if checked["remaining_jobs"] != 0:
        raise ValueError("Terra Experiment A cell is not exhaustive")
    return checked


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
        "PASS Terra batch10: {completed_jobs}/69 jobs, {planned_calls}/237 calls, "
        "{failed_calls} failures, ${batch_known_cost_usd:.6f} batch; "
        "{remaining_jobs} Experiment A jobs remain".format(**checked)
    )


if __name__ == "__main__":
    main()
