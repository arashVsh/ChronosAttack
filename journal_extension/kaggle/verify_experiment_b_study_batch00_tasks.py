"""Verify the first B study shard tasks after excluded pilot disposition.

Only the settings with independently passed raw pilots receive study sources.
Gemini and Qwen's failed pilots are retained as exclusions, not retried here.
"""

import hashlib
import json
from pathlib import Path

import build_experiment_b_hosted_v1 as builder
import experiment_b_protocol as protocol
import verify_experiment_b_collection as collection
import verify_experiment_b_pilot_tasks as pilot_tasks


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "round2_generated/experiment_b_study_batch00_tasks_v1.json"
PILOT_RUNS = {
    "openai/gpt-5.6-terra": (
        "terra-low/chronos-r2-tree4-rotation-pilot-terra-low-v1/1/"
        "gpt-5.6-terra/2840334"
    ),
    "anthropic/claude-sonnet-4-6@default": (
        "claude-none/chronos-r2-tree4-rotation-pilot-claude-none-v1/1/"
        "claude-sonnet-4-6-default/2840335"
    ),
}
FAILED_PILOTS = (
    {
        "model": "google/gemini-3.6-flash",
        "reasoning": "minimal",
        "role": "matched_non_off_primary",
        "status": "pilot_failed",
        "run_id": 2840332,
    },
    {
        "model": "qwen/qwen3-235b-a22b-instruct-2507",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "status": "pilot_failed",
        "run_id": 2840333,
    },
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _pilot(model):
    run_root = HERE / "round2_runs_20260920/experiment_b_pilot" / PILOT_RUNS[model]
    checked = collection.verify_downloaded_pilot(run_root=run_root, model=model)
    output_folder = next(
        task["output_folder"] for task in json.loads(pilot_tasks.MANIFEST.read_text())["tasks"]
        if task["model"] == model
    )
    output = run_root / output_folder
    return checked, {
        "evidence": (output / (model.replace("/", "_") + ".jsonl")).read_bytes(),
        "terminal": (output / "terminal.json").read_bytes(),
        "intended": (output / "intended_manifest.json").read_bytes(),
    }


def specs():
    result = []
    for model in PILOT_RUNS:
        _, _, tag = protocol.CELLS[model]
        result.append({
            "model": model,
            "phase": "study",
            "shard_index": 0,
            "task_name": f"chronos-r2-tree4-rotation-study-{tag.replace('_', '-')}-s00-v1",
            "output_folder": f"round2_tree4_rotation_study_{tag}_s00_v1",
            "source_path": f"kaggle/round2_generated/tree4_rotation_study_{tag}_s00_v1.py",
        })
    return result


def source_for(spec):
    checked, raw = _pilot(spec["model"])
    receipt = checked["receipt"]
    ceiling = builder.study_ceiling_from_pilot(receipt)
    source = builder.build_source(
        model=spec["model"],
        phase="study",
        shard_index=0,
        task_name=spec["task_name"],
        output_folder=spec["output_folder"],
        ceiling_usd=ceiling,
        pilot_receipt=receipt,
        pilot_evidence=raw["evidence"],
        pilot_terminal=raw["terminal"],
        pilot_intended=raw["intended"],
    )
    return source, checked, ceiling


def build_manifest():
    pilot_tasks.verify()
    tasks = []
    for spec in specs():
        source, pilot, ceiling = source_for(spec)
        path = ROOT / spec["source_path"]
        raw_source = path.read_bytes()
        if raw_source != source.encode():
            raise ValueError("B study s00 source differs from pilot-derived regeneration")
        plan = builder.plan_cell(model=spec["model"], phase="study", shard_index=0)
        tasks.append({
            **spec,
            "reasoning": plan["reasoning"],
            "role": plan["role"],
            "study_id": plan["study_id"],
            "identity": plan["identity"],
            "jobs_sha256": plan["jobs_sha256"],
            "jobs": plan["job_count"],
            "planned_calls": plan["planned_calls"],
            "source_sha256": hashlib.sha256(raw_source).hexdigest(),
            "source_bytes": len(raw_source),
            "pilot_receipt_sha256": pilot["receipt"]["receipt_sha256"],
            "pilot_evidence_sha256": pilot["evidence_sha256"],
            "pilot_terminal_sha256": pilot["terminal_sha256"],
            "pilot_intended_sha256": pilot["intended_manifest_sha256"],
            "incremental_ceiling_usd": ceiling,
        })
    body = {
        "schema": "chronos.experiment-b-study-batch.v1",
        "batch": 0,
        "status": "staged_after_excluded_pilots",
        "launch_authorized": False,
        "fixture_manifest_sha256": builder.freeze.verify()["manifest_sha256"],
        "pilot_tasks_manifest_sha256": json.loads(pilot_tasks.MANIFEST.read_text())[
            "pilot_tasks_manifest_sha256"
        ],
        "failed_pilots_excluded": list(FAILED_PILOTS),
        "task_count": len(tasks),
        "jobs": sum(task["jobs"] for task in tasks),
        "planned_calls": sum(task["planned_calls"] for task in tasks),
        "aggregate_ceiling_usd": sum(task["incremental_ceiling_usd"] for task in tasks),
        "tasks": tasks,
    }
    return {**body, "batch_manifest_sha256": digest(body)}


def verify():
    saved = json.loads(MANIFEST.read_text())
    body = {key: value for key, value in saved.items() if key != "batch_manifest_sha256"}
    if saved.get("batch_manifest_sha256") != digest(body) or saved != build_manifest():
        raise ValueError("B s00 study task manifest differs from passed pilots or sources")
    if (saved["task_count"], saved["jobs"], saved["planned_calls"]) != (2, 12, 60):
        raise ValueError("B s00 study task topology changed")
    if saved["failed_pilots_excluded"] != list(FAILED_PILOTS):
        raise ValueError("B failed pilot exclusion changed")
    all_ids = set()
    for task in saved["tasks"]:
        source = (ROOT / task["source_path"]).read_text()
        compile(source, task["source_path"], "exec")
        if pilot_tasks.discovered_task_names(source) != [task["task_name"]]:
            raise ValueError("B study task is not statically discoverable")
        jobs = pilot_tasks.assignments(source)["EXPECTED_JOBS"]
        ids = {job["id"] for job in jobs}
        if len(ids) != 6 or ids & all_ids:
            raise ValueError("B s00 study jobs overlap")
        all_ids.update(ids)
    return {
        "batch_manifest_sha256": saved["batch_manifest_sha256"],
        "task_count": 2,
        "jobs": 12,
        "planned_calls": 60,
        "aggregate_ceiling_usd": saved["aggregate_ceiling_usd"],
        "launch_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
