"""Freeze outcome-independent B study shards s01--s29 for pilot-passed cells."""

import hashlib
import json
from pathlib import Path

import build_experiment_b_hosted_v1 as builder
import experiment_b_protocol as protocol
import verify_experiment_b_study_batch00_tasks as batch00


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "round2_generated/experiment_b_remaining_study_plan_v1.json"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_plan():
    staged = batch00.verify()
    prior = json.loads(batch00.MANIFEST.read_text())
    passed = {task["model"]: task for task in prior["tasks"]}
    entries = []
    all_ids = set()
    for index in range(1, builder.SHARD_COUNT):
        for model in batch00.PILOT_RUNS:
            _, _, tag = protocol.CELLS[model]
            plan = builder.plan_cell(model=model, phase="study", shard_index=index)
            ids = {job["id"] for job in plan["jobs"]}
            if len(ids) != 6 or ids & all_ids:
                raise ValueError("B remaining study shard jobs overlap")
            all_ids.update(ids)
            entries.append({
                "model": model,
                "reasoning": plan["reasoning"],
                "role": plan["role"],
                "study_id": plan["study_id"],
                "shard_index": index,
                "shard_count": builder.SHARD_COUNT,
                "task_name": f"chronos-r2-tree4-rotation-study-{tag.replace('_', '-')}-s{index:02d}-v1",
                "output_folder": f"round2_tree4_rotation_study_{tag}_s{index:02d}_v1",
                "source_path": f"kaggle/round2_generated/tree4_rotation_study_{tag}_s{index:02d}_v1.py",
                "job_count": plan["job_count"],
                "planned_calls": plan["planned_calls"],
                "jobs_sha256": plan["jobs_sha256"],
                "identity": plan["identity"],
                "pilot_receipt_sha256": passed[model]["pilot_receipt_sha256"],
                "incremental_ceiling_usd": passed[model]["incremental_ceiling_usd"],
                "source_sha256": None,
            })
    body = {
        "schema": "chronos.experiment-b-remaining-study-plan.v1",
        "status": "planned_after_excluded_pilot_disposition",
        "launch_authorized": False,
        "fixture_manifest_sha256": builder.freeze.verify()["manifest_sha256"],
        "pilot_tasks_manifest_sha256": prior["pilot_tasks_manifest_sha256"],
        "batch00_manifest_sha256": staged["batch_manifest_sha256"],
        "failed_pilots_excluded": prior["failed_pilots_excluded"],
        "shards": entries,
        "shard_count": len(entries),
        "jobs": sum(entry["job_count"] for entry in entries),
        "planned_calls": sum(entry["planned_calls"] for entry in entries),
    }
    return {**body, "remaining_plan_sha256": digest(body)}


def verify():
    saved = json.loads(MANIFEST.read_text())
    body = {key: value for key, value in saved.items() if key != "remaining_plan_sha256"}
    if saved.get("remaining_plan_sha256") != digest(body) or saved != build_plan():
        raise ValueError("B remaining study plan differs from deterministic shards")
    if (saved["shard_count"], saved["jobs"], saved["planned_calls"]) != (58, 348, 1740):
        raise ValueError("B remaining study plan topology changed")
    return {
        "remaining_plan_sha256": saved["remaining_plan_sha256"],
        "shards": 58,
        "jobs": 348,
        "planned_calls": 1740,
        "launch_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
