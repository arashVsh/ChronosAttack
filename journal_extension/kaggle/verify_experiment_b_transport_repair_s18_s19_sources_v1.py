"""Byte-exact, source-only B transport repairs for three source-less task records.

Only the statically discovered decorator slug changes. Internal task identity,
jobs, prompts, settings, output folders, and ceilings remain pinned. This
module makes no Kaggle calls and does not authorize a launch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import verify_experiment_b_pilot_tasks as pilot_tasks
import verify_experiment_b_study_wave_v1 as wave


ROOT = Path(__file__).resolve().parent.parent
WAVE_PATH = wave.manifest_path(16, 20)
WAVE_SHA256 = "a688e6f31d7654679b0b954ceb7f8bbc9ba138d9fa0fa99e5c86fb206a38c1c8"
REPAIR_SUFFIX = "-transport-repair-v1"
REPAIRS = (
    ("anthropic/claude-sonnet-4-6@default", 18, "claude_none"),
    ("openai/gpt-5.6-terra", 19, "terra_low"),
    ("anthropic/claude-sonnet-4-6@default", 19, "claude_none"),
)


def repair_source_path(model: str, shard_index: int) -> Path:
    tags = [
        tag for task_model, index, tag in REPAIRS
        if task_model == model and index == shard_index
    ]
    if len(tags) != 1:
        raise ValueError("B task is not in the three-source s18–s19 transport repair")
    return ROOT / "kaggle/round2_generated" / (
        f"tree4_rotation_study_{tags[0]}_s{shard_index:02d}_transport_repair_v1.py"
    )


def _canonical_wave() -> dict:
    checked = wave.verify_wave(WAVE_PATH)
    if checked["batch_manifest_sha256"] != WAVE_SHA256:
        raise ValueError("B canonical s16–s20 wave identity changed")
    return json.loads(WAVE_PATH.read_text())


def _repaired_source(task: dict) -> tuple[bytes, dict]:
    model, shard_index = task["model"], task["shard_index"]
    replacement_path = repair_source_path(model, shard_index)
    original = (ROOT / task["source_path"]).read_bytes()
    if hashlib.sha256(original).hexdigest() != task["source_sha256"]:
        raise ValueError("B canonical wave source hash changed")
    original_slug = task["task_name"]
    if not original_slug.endswith("-v1"):
        raise ValueError("B canonical task slug is not versioned")
    repair_slug = original_slug.removesuffix("-v1") + REPAIR_SUFFIX
    old = f"@kbench.task(name={original_slug!r})".encode()
    new = f"@kbench.task(name={repair_slug!r})".encode()
    if original.count(old) != 1 or new in original:
        raise ValueError("B canonical task decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError("B transport repair is not exactly reversible")
    compile(repaired, str(replacement_path), "exec")
    if pilot_tasks.discovered_task_names(repaired.decode()) != [repair_slug]:
        raise ValueError("B replacement task is not statically discoverable")
    record = {
        "model": model,
        "shard_index": shard_index,
        "original_task_name": original_slug,
        "replacement_task_name": repair_slug,
        "original_source_path": task["source_path"],
        "original_source_sha256": task["source_sha256"],
        "replacement_source_path": str(replacement_path.relative_to(ROOT)),
        "replacement_source_sha256": hashlib.sha256(repaired).hexdigest(),
        "source_bytes": len(repaired),
        "output_folder": task["output_folder"],
        "job_count": task["job_count"],
        "planned_calls": task["planned_calls"],
        "incremental_ceiling_usd": task["incremental_ceiling_usd"],
        "transformation": "replace_only_static_kbench_task_decorator_slug",
    }
    return repaired, record


def build_repaired_source(model: str, shard_index: int) -> tuple[bytes, dict]:
    repair_source_path(model, shard_index)
    tasks = [
        task for task in _canonical_wave()["tasks"]
        if task["model"] == model and task["shard_index"] == shard_index
    ]
    if len(tasks) != 1:
        raise ValueError("B canonical wave task is not unique")
    return _repaired_source(tasks[0])


def verify_sources() -> dict:
    manifest = _canonical_wave()
    tasks = {(task["model"], task["shard_index"]): task for task in manifest["tasks"]}
    records = []
    for model, shard_index, _ in REPAIRS:
        repaired, record = _repaired_source(tasks[(model, shard_index)])
        if repair_source_path(model, shard_index).read_bytes() != repaired:
            raise ValueError("B written transport repair source differs from byte regeneration")
        records.append(record)
    return {
        "schema": "chronos.experiment-b-transport-repair-s18-s19-sources.v1",
        "status": "prepared_not_launched",
        "canonical_wave_manifest_sha256": WAVE_SHA256,
        "tasks": records,
        "task_count": len(records),
        "jobs": sum(task["job_count"] for task in records),
        "planned_calls": sum(task["planned_calls"] for task in records),
        "aggregate_ceiling_usd": round(sum(
            task["incremental_ceiling_usd"] for task in records
        ), 9),
        "launch_authorized": False,
    }


def stage_sources() -> dict:
    """Create only missing replacement files after canonical byte verification."""
    manifest = _canonical_wave()
    tasks = {(task["model"], task["shard_index"]): task for task in manifest["tasks"]}
    generated = []
    for model, shard_index, _ in REPAIRS:
        repaired, _ = _repaired_source(tasks[(model, shard_index)])
        path = repair_source_path(model, shard_index)
        if path.exists() and path.read_bytes() != repaired:
            raise ValueError("B pre-existing transport repair source differs from byte regeneration")
        generated.append((path, repaired))
    for path, repaired in generated:
        if not path.exists():
            with path.open("xb") as file:
                file.write(repaired)
    return verify_sources()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true", help="Create missing exact source files")
    args = parser.parse_args()
    result = stage_sources() if args.stage else verify_sources()
    print(json.dumps(result, indent=2, sort_keys=True))
