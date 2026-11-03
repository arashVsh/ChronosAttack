"""Capture official no-run evidence for the Claude-none shard-24 repair."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

import build_experiment_a_claude_none_s24_task_slug_repair_v1 as repair_builder
import verify_experiment_a_claude_none_batch06 as staged_batch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch06"
OUTPUT = RUNS / "s24_version1_no_run_attestation_v1.json"
SCHEMA = "chronos.kaggle-task-version-repair-batch-attestation.v1"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _file_record(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": str(path.resolve().relative_to(ROOT.resolve())),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _fetch_original() -> tuple[dict, list]:
    api = KaggleApi()
    api.authenticate()
    with api.build_kaggle_client() as client:
        task = api._get_benchmark_task(repair_builder.ORIGINAL_TASK, client)
        runs = api._fetch_task_runs(client, repair_builder.ORIGINAL_TASK)
    return (
        task.to_dict(ignore_defaults=False),
        [run.to_dict(ignore_defaults=False) for run in runs],
    )


def build() -> dict:
    staged = staged_batch.verify()
    repaired, wrapper = repair_builder.verify_sources()
    task, runs = _fetch_original()
    slug = task.get("slug") or {}
    if (
        task.get("creationState")
        != "BENCHMARK_TASK_VERSION_CREATION_STATE_UNSPECIFIED"
        or task.get("source")
        != "BENCHMARK_TASK_VERSION_SOURCE_UNSPECIFIED"
        or task.get("sourceKernelId") is not None
        or slug.get("ownerSlug") != "masihmaafi"
        or slug.get("taskSlug") != repair_builder.ORIGINAL_TASK
        or slug.get("versionNumber") != 1
        or runs
    ):
        raise ValueError("Claude shard-24 original is not a source-less no-run version")
    original = repair_builder.ORIGINAL.read_bytes()
    old = f"@kbench.task(name={repair_builder.ORIGINAL_TASK!r})".encode()
    new = f"@kbench.task(name={repair_builder.REPAIR_TASK!r})".encode()
    if repaired.replace(new, old) != original:
        raise ValueError("Claude shard-24 repair is not reversible")
    record = {
        "shard_index": 24,
        "original_task": repair_builder.ORIGINAL_TASK,
        "task_version_before_repair": {**task, "runs": runs},
        "model_run_observed": False,
        "same_slug_repush_attempt": {
            "error": (
                f"Task 'masihmaafi/{repair_builder.ORIGINAL_TASK}' exists but "
                "has no source kernel."
            ),
            "run_created": False,
        },
        "repair_task": repair_builder.REPAIR_TASK,
        "repair_source": {
            **_file_record(repair_builder.REPAIR),
            "derived_from_sha256": _sha256(original),
            "transformation": (
                "replace the sole kbench task decorator slug "
                f"{repair_builder.ORIGINAL_TASK} with "
                f"{repair_builder.REPAIR_TASK}; reverse substitution "
                "reproduces derived_from_sha256"
            ),
        },
        "transport_wrapper": {
            **_file_record(repair_builder.WRAPPER),
            "decompressed_payload_sha256": _sha256(repaired),
            "wrapper_sha256": _sha256(wrapper),
        },
        "scientific_changes": [],
        "unaccounted_quota_usd": 0.0,
    }
    body = {
        "schema": SCHEMA,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "conclusion": (
            "original_version_created_without_source_kernel_or_run; frozen "
            "contract relaunched with only task slug rewritten"
        ),
        "prelaunch_manifest_sha256": staged["batch_manifest_sha256"],
        "repairs": [record],
    }
    return {**body, "attestation_sha256": _sha256(_canonical(body))}


def main() -> None:
    if OUTPUT.exists():
        raise ValueError(f"refusing to overwrite {OUTPUT}")
    attestation = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    print(f"WROTE {OUTPUT} {attestation['attestation_sha256']}")


if __name__ == "__main__":
    main()
