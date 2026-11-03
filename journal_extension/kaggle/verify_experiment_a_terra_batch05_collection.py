"""Seal and independently verify Terra Experiment A shards 22--23."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import verify_experiment_a_terra_batch01_collection as base
import verify_experiment_a_terra_batch05 as staged_batch


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_terra_batch05"
MANIFEST = GENERATED / "experiment_a_terra_batch05_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_terra_batch05_tasks_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_terra_batch05_20260922_v1.json"
)
FROZEN_AT = "2026-09-22T17:54:31.268239+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {22: 2788713, 23: 2788727}


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
    "completed_jobs": 46,
    "planned_calls": 154,
    "observed_invocations": 154,
    "complete_calls": 154,
    "failed_calls": 0,
    "unknown_cost_calls": 0,
    "invalid_json_lines": 0,
    "events": 246,
    "started_attempts": 46,
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
    "PRE_BATCH_RAW_KNOWN_DAILY_USD": 8.4115211,
    "PRE_BATCH_OFFICIAL_DAILY_USD": 8.4115211,
    "BATCH_KNOWN_COST_USD": 0.421268,
    "POST_BATCH_RAW_KNOWN_DAILY_USD": 8.8327891,
    "POST_BATCH_OFFICIAL_DAILY_USD": 8.8327891,
    "OFFICIAL_QUOTA_DELTA_USD": 0.421268,
    "POST_OFFICIAL_MINUS_RAW_KNOWN_USD": 0.0,
    "PRELAUNCH_MANIFEST_SHA256": (
        "53bdf7e8362b20b649b60747ee311d39a12b355d29f7f8c8604f9c1026fb30b2"
    ),
    "COLLECTION_SCHEMA": "chronos.experiment-a-terra-batch05-collection.v1",
    "VERIFICATION_SCHEMA": (
        "chronos.experiment-a-terra-batch05-verification.v1"
    ),
    "BATCH_NAME": "terra_batch05_shards_22_23",
    "BATCH_DISPLAY": "Terra batch05",
    "FINAL_SHARD": 23,
    "EXPECTED_SHARD_COUNT": 2,
    "EXPECTED_JOB_COUNT": 46,
    "EXPECTED_PLANNED_CALLS": 154,
    "EXPECTED_ACCOUNTING": EXPECTED_ACCOUNTING,
}


@lru_cache(maxsize=1)
def _sealed_previous() -> dict:
    return staged_batch._sealed_previous()


@contextmanager
def _batch05_base():
    staged = staged_batch._load()
    sealed_previous = _sealed_previous()
    previous_function = base._previous
    previous_function.cache_clear()
    previous = {name: getattr(base, name) for name in PATCHES}
    previous_staged_batch = base.staged_batch
    for name, value in PATCHES.items():
        setattr(base, name, value)
    base.staged_batch = type(
        "FrozenTerraBatch05Stage",
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
    with _batch05_base():
        return base.build_manifest()


def _load_manifest(value: dict | None = None) -> dict:
    with _batch05_base():
        return base._load_manifest(value)


def verify(value: dict | None = None) -> dict:
    with _batch05_base():
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
        "PASS Terra batch05: {completed_jobs}/46 jobs, {planned_calls} planned / "
        "{observed_invocations} measured calls, {failed_calls} failed calls, "
        "${batch_known_cost_usd:.6f} batch, "
        "${post_batch_official_daily_quota_used_usd:.7f} official daily used; "
        "two shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
