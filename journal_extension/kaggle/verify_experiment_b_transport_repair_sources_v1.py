"""Byte-exact, source-only B repairs for three source-less Kaggle task records.

The replacement changes only the statically discovered task decorator slug.
Study identity, job IDs, prompts, settings, output folder, and budget are frozen.
This module makes no Kaggle calls and does not authorize a launch.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import verify_experiment_b_pilot_tasks as pilot_tasks
import verify_experiment_b_study_wave_v1 as wave


ROOT = Path(__file__).resolve().parent.parent
REPAIR_SUFFIX = "-transport-repair-v1"
REPAIRS = (
    ("openai/gpt-5.6-terra", 6, "terra_low"),
    ("anthropic/claude-sonnet-4-6@default", 6, "claude_none"),
    ("openai/gpt-5.6-terra", 7, "terra_low"),
)


def _task(model: str, shard_index: int) -> dict:
    if (model, shard_index) not in {(model, index) for model, index, _ in REPAIRS}:
        raise ValueError("B task is not in the three-source transport repair")
    wave.verify_wave(wave.manifest_path(6, 10))
    import json
    manifest = json.loads(wave.manifest_path(6, 10).read_text())
    tasks = [
        task for task in manifest["tasks"]
        if task["model"] == model and task["shard_index"] == shard_index
    ]
    if len(tasks) != 1:
        raise ValueError("B canonical wave task is not unique")
    return tasks[0]


def repair_source_path(model: str, shard_index: int) -> Path:
    matches = [tag for task_model, index, tag in REPAIRS
               if task_model == model and index == shard_index]
    if len(matches) != 1:
        raise ValueError("B source is not in the three-source transport repair")
    return ROOT / "kaggle/round2_generated" / (
        f"tree4_rotation_study_{matches[0]}_s{shard_index:02d}_transport_repair_v1.py"
    )


def build_repaired_source(model: str, shard_index: int) -> tuple[bytes, dict]:
    task = _task(model, shard_index)
    original_path = ROOT / task["source_path"]
    original = original_path.read_bytes()
    if hashlib.sha256(original).hexdigest() != task["source_sha256"]:
        raise ValueError("B canonical wave source hash changed")
    original_slug = task["task_name"]
    repair_slug = original_slug.removesuffix("-v1") + REPAIR_SUFFIX
    old = f"@kbench.task(name={original_slug!r})".encode()
    new = f"@kbench.task(name={repair_slug!r})".encode()
    if original.count(old) != 1 or new in original:
        raise ValueError("B canonical task decorator is not unique")
    repaired = original.replace(old, new)
    if repaired.replace(new, old) != original:
        raise ValueError("B transport repair is not exactly reversible")
    compile(repaired, str(repair_source_path(model, shard_index)), "exec")
    if pilot_tasks.discovered_task_names(repaired.decode()) != [repair_slug]:
        raise ValueError("B replacement task is not statically discoverable")
    record = {
        "model": model,
        "shard_index": shard_index,
        "original_task_name": original_slug,
        "replacement_task_name": repair_slug,
        "original_source_path": task["source_path"],
        "original_source_sha256": task["source_sha256"],
        "replacement_source_path": str(repair_source_path(model, shard_index).relative_to(ROOT)),
        "replacement_source_sha256": hashlib.sha256(repaired).hexdigest(),
        "source_bytes": len(repaired),
        "output_folder": task["output_folder"],
        "job_count": task["job_count"],
        "planned_calls": task["planned_calls"],
        "incremental_ceiling_usd": task["incremental_ceiling_usd"],
        "transformation": "replace_only_static_kbench_task_decorator_slug",
    }
    return repaired, record


def verify_sources() -> dict:
    records = []
    for model, index, _ in REPAIRS:
        repaired, record = build_repaired_source(model, index)
        if repair_source_path(model, index).read_bytes() != repaired:
            raise ValueError("B written transport repair source differs from byte regeneration")
        records.append(record)
    return {
        "schema": "chronos.experiment-b-transport-repair-sources.v1",
        "status": "prepared_not_launched",
        "canonical_wave_manifest_sha256": wave.verify_wave(
            wave.manifest_path(6, 10)
        )["batch_manifest_sha256"],
        "tasks": records,
        "task_count": 3,
        "jobs": sum(task["job_count"] for task in records),
        "planned_calls": sum(task["planned_calls"] for task in records),
        "aggregate_ceiling_usd": round(sum(
            task["incremental_ceiling_usd"] for task in records
        ), 9),
        "launch_authorized": False,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(verify_sources(), indent=2, sort_keys=True))
