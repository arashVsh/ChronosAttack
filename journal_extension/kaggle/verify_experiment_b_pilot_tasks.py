"""Verify byte-pinned, excluded Experiment B pilot task sources."""

import ast
import hashlib
import json
from pathlib import Path

import build_experiment_b_hosted_v1 as builder
import experiment_b_protocol as protocol


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "experiment_b_pilot_tasks_v1.json"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def specs():
    result = []
    for model, (_, _, tag) in protocol.CELLS.items():
        hyphen_tag = tag.replace("_", "-")
        result.append({
            "model": model,
            "phase": "pilot",
            "task_name": f"chronos-r2-tree4-rotation-pilot-{hyphen_tag}-v1",
            "output_folder": f"round2_tree4_rotation_pilot_{tag}_v1",
            "ceiling_usd": builder.PILOT_CEILING_USD,
            "source_path": f"kaggle/round2_generated/tree4_rotation_pilot_{tag}_v1.py",
        })
    return result


def assignments(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return result


def discovered_task_names(source):
    """Mirror the CLI's static requirement for literal task decorator names."""
    names = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            if not (
                isinstance(target, ast.Attribute)
                and target.attr == "task"
                and isinstance(target.value, ast.Name)
                and target.value.id == "kbench"
            ):
                continue
            matches = [keyword.value for keyword in decorator.keywords if keyword.arg == "name"]
            if len(matches) != 1 or not isinstance(matches[0], ast.Constant) or not isinstance(matches[0].value, str):
                raise ValueError("B task decorator name must be a literal string")
            names.append(matches[0].value)
    return names


def build_manifest():
    tasks = []
    for spec in specs():
        path = ROOT / spec["source_path"]
        raw = path.read_bytes()
        plan = builder.plan_cell(model=spec["model"], phase="pilot")
        tasks.append({
            **spec,
            "reasoning": plan["reasoning"],
            "role": plan["role"],
            "study_id": plan["study_id"],
            "identity": plan["identity"],
            "jobs_sha256": plan["jobs_sha256"],
            "jobs": plan["job_count"],
            "planned_calls": plan["planned_calls"],
            "source_sha256": sha256(raw),
            "source_bytes": len(raw),
        })
    body = {
        "schema": "chronos.experiment-b-pilot-tasks.v1",
        "status": "staged_prerequisites_not_verified",
        "launch_authorized": False,
        "fixture_manifest_sha256": builder.freeze.verify()["manifest_sha256"],
        "experiment_a_analysis_seal_sha256": None,
        "fresh_quota_attestation_sha256": None,
        "task_count": len(tasks),
        "jobs": sum(task["jobs"] for task in tasks),
        "planned_calls": sum(task["planned_calls"] for task in tasks),
        "ceiling_per_task_usd": builder.PILOT_CEILING_USD,
        "aggregate_ceiling_usd": sum(task["ceiling_usd"] for task in tasks),
        "tasks": tasks,
    }
    return {**body, "pilot_tasks_manifest_sha256": digest(body)}


def verify():
    manifest = json.loads(MANIFEST.read_text())
    body = {key: value for key, value in manifest.items() if key != "pilot_tasks_manifest_sha256"}
    if manifest["pilot_tasks_manifest_sha256"] != digest(body):
        raise ValueError("B pilot task manifest self-hash mismatch")
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("B pilot task manifest differs from generated sources")
    if (
        manifest["task_count"] != 4
        or manifest["jobs"] != 8
        or manifest["planned_calls"] != 40
        or manifest["aggregate_ceiling_usd"] != 1.0
        or manifest["launch_authorized"] is not False
    ):
        raise ValueError("B pilot topology or launch state changed")
    all_ids = set()
    for spec, task in zip(specs(), manifest["tasks"]):
        path = ROOT / spec["source_path"]
        source = path.read_text()
        rebuilt = builder.build_source(**{
            key: spec[key]
            for key in ("model", "phase", "task_name", "output_folder", "ceiling_usd")
        })
        if source != rebuilt:
            raise ValueError(f"B pilot source differs from byte-exact regeneration: {path}")
        compile(source, str(path), "exec")
        if discovered_task_names(source) != [task["task_name"]]:
            raise ValueError("B pilot source is not statically discoverable by Kaggle CLI")
        values = assignments(source)
        plan = builder.plan_cell(model=spec["model"], phase="pilot")
        if (
            values["CONTRACT"]["identity"] != task["identity"]
            or values["CONTRACT"]["jobs_sha256"] != task["jobs_sha256"]
            or values["EXPECTED_JOBS"] != plan["jobs"]
            or values["RESUME_LEDGER"] != b""
            or values["PILOT_RECEIPT"] is not None
            or values["CEILING_USD"] != builder.PILOT_CEILING_USD
            or values["CALL_SETTINGS"] != protocol.call_settings(spec["model"])
        ):
            raise ValueError("B pilot source embedded contract changed")
        ids = {job["id"] for job in values["EXPECTED_JOBS"]}
        if len(ids) != 2 or ids & all_ids:
            raise ValueError("B pilot task IDs collide")
        all_ids.update(ids)
    return {
        "pilot_tasks_manifest_sha256": manifest["pilot_tasks_manifest_sha256"],
        "task_count": 4,
        "jobs": 8,
        "planned_calls": 40,
        "aggregate_ceiling_usd": 1.0,
        "launch_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
