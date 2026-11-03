"""Freeze and verify the four Experiment A pilot tasks before upload."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
from pathlib import Path

from build_experiment_a_pilot_v1 import build_source, plan_pilot
import verify_experiment_a_availability as availability_verifier


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "experiment_a_pilot_tasks_v1.json"
FROZEN_AT = "2026-09-20T21:38:15+03:30"
PRE_LAUNCH_COST = 8.555856
REMAINING_CREDIT = 1.444144
CEILING_USD = 0.25
AVAILABILITY_HASH = (
    "9f4e975c7083ba39adba45dcb76034f526b99cfd32bba36a9aa5563e763355e4"
)

CELLS = (
    {
        "label": "terra_low",
        "model": "openai/gpt-5.6-terra",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "study_id": "chronos_round2_water4_pilot_terra_low_v1",
        "task": "chronos-r2-water4-pilot-terra-low-v1",
        "output_folder": "round2_water4_pilot_terra_low_v1",
    },
    {
        "label": "gemini_minimal",
        "model": "google/gemini-3.6-flash",
        "reasoning": "minimal",
        "role": "matched_non_off_primary",
        "study_id": "chronos_round2_water4_pilot_gemini_minimal_v1",
        "task": "chronos-r2-water4-pilot-gemini-minimal-v1",
        "output_folder": "round2_water4_pilot_gemini_minimal_v1",
    },
    {
        "label": "qwen_low",
        "model": "qwen/qwen3-235b-a22b-instruct-2507",
        "reasoning": "low",
        "role": "matched_non_off_primary",
        "study_id": "chronos_round2_water4_pilot_qwen_low_v1",
        "task": "chronos-r2-water4-pilot-qwen-low-v1",
        "output_folder": "round2_water4_pilot_qwen_low_v1",
    },
    {
        "label": "claude_none",
        "model": "anthropic/claude-sonnet-4-6@default",
        "reasoning": "none",
        "role": "reasoning_off_sensitivity",
        "study_id": "chronos_round2_water4_pilot_claude_none_v1",
        "task": "chronos-r2-water4-pilot-claude-none-v1",
        "output_folder": "round2_water4_pilot_claude_none_v1",
    },
)


def _source(cell: dict) -> Path:
    return GENERATED / f"water4_pilot_{cell['label']}_v1.py"


def _arguments(cell: dict) -> dict:
    return {
        "model": cell["model"],
        "reasoning": cell["reasoning"],
        "study_id": cell["study_id"],
        "task_name": cell["task"],
        "output_folder": cell["output_folder"],
        "ceiling_usd": CEILING_USD,
    }


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _manifest_hash(manifest: dict) -> str:
    return _canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "pilot_tasks_manifest_sha256"
        }
    )


def _assignments(source: str, path: Path) -> dict:
    values = {}
    for node in ast.parse(source, str(path)).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    pass
    return values


def _record(cell: dict) -> dict:
    path = _source(cell)
    raw = path.read_bytes()
    values = _assignments(raw.decode(), path)
    jobs = values["EXPECTED_JOBS"]
    return {
        **cell,
        "source_status": "frozen_prelaunch",
        "source": {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(raw),
            "bytes": len(raw),
        },
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": values["CONTRACT"]["manifest_sha256"],
        "identity": values["CONTRACT"]["identity"],
        "incremental_ceiling_usd": CEILING_USD,
    }


def build_manifest() -> dict:
    manifest = {
        "schema": "chronos.experiment-a-pilot-tasks.v1",
        "pilot_tasks_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "availability_manifest_sha256": AVAILABILITY_HASH,
        "pre_launch_known_daily_cost_usd": PRE_LAUNCH_COST,
        "remaining_daily_credit_usd": REMAINING_CREDIT,
        "incremental_ceiling_per_task_usd": CEILING_USD,
        "aggregate_incremental_ceiling_usd": CEILING_USD * len(CELLS),
        "maximum_daily_exposure_usd": PRE_LAUNCH_COST + CEILING_USD * len(CELLS),
        "daily_credit_limit_usd": 10.0,
        "task_count": 4,
        "job_count": 8,
        "planned_calls": 40,
        "tasks": [_record(cell) for cell in CELLS],
    }
    manifest["pilot_tasks_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if _manifest_hash(manifest) != manifest.get("pilot_tasks_manifest_sha256"):
        raise ValueError("Experiment A pilot-task manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    availability = availability_verifier.verify()
    expected_keys = {
        "schema",
        "pilot_tasks_manifest_sha256",
        "frozen_at",
        "status",
        "availability_manifest_sha256",
        "pre_launch_known_daily_cost_usd",
        "remaining_daily_credit_usd",
        "incremental_ceiling_per_task_usd",
        "aggregate_incremental_ceiling_usd",
        "maximum_daily_exposure_usd",
        "daily_credit_limit_usd",
        "task_count",
        "job_count",
        "planned_calls",
        "tasks",
    }
    if set(manifest) != expected_keys:
        raise ValueError("invalid Experiment A pilot-task manifest schema")
    if (
        manifest["schema"] != "chronos.experiment-a-pilot-tasks.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["status"] != "authorized_not_launched"
        or manifest["availability_manifest_sha256"] != AVAILABILITY_HASH
        or manifest["availability_manifest_sha256"]
        != availability["manifest_sha256"]
        or manifest["pre_launch_known_daily_cost_usd"] != PRE_LAUNCH_COST
        or manifest["remaining_daily_credit_usd"] != REMAINING_CREDIT
        or manifest["incremental_ceiling_per_task_usd"] != CEILING_USD
        or manifest["aggregate_incremental_ceiling_usd"] != 1.0
        or manifest["maximum_daily_exposure_usd"] != 9.555856
        or manifest["daily_credit_limit_usd"] != 10.0
        or manifest["maximum_daily_exposure_usd"]
        > manifest["daily_credit_limit_usd"]
        or (manifest["task_count"], manifest["job_count"], manifest["planned_calls"])
        != (4, 8, 40)
    ):
        raise ValueError("Experiment A pilot-task budget or parent contract changed")
    if not isinstance(manifest["tasks"], list) or len(manifest["tasks"]) != 4:
        raise ValueError("Experiment A pilot-task count changed")

    checked = []
    identities = set()
    job_ids = []
    task_keys = {
        "label",
        "model",
        "reasoning",
        "role",
        "study_id",
        "task",
        "output_folder",
        "source_status",
        "source",
        "job_count",
        "planned_calls",
        "jobs_sha256",
        "identity",
        "incremental_ceiling_usd",
    }
    for expected, record in zip(CELLS, manifest["tasks"]):
        if set(record) != task_keys:
            raise ValueError("invalid Experiment A pilot-task record")
        if (
            any(record[key] != expected[key] for key in expected)
            or record["source_status"] != "frozen_prelaunch"
            or (record["job_count"], record["planned_calls"]) != (2, 10)
            or record["incremental_ceiling_usd"] != CEILING_USD
        ):
            raise ValueError("Experiment A pilot-task identity changed")
        source_record = record["source"]
        if set(source_record) != {"path", "sha256", "bytes"}:
            raise ValueError("invalid Experiment A pilot source record")
        path = (ROOT / source_record["path"]).resolve()
        if path != _source(expected).resolve():
            raise ValueError("Experiment A pilot source path changed")
        raw = path.read_bytes()
        if len(raw) != source_record["bytes"] or _sha256(raw) != source_record["sha256"]:
            raise ValueError("Experiment A pilot source hash/size mismatch")
        source = raw.decode()
        if source != build_source(**_arguments(expected)):
            raise ValueError("Experiment A pilot source is not byte-exact regeneration")
        compile(source, str(path), "exec")
        values = _assignments(source, path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        plan = plan_pilot(
            model=expected["model"],
            reasoning=expected["reasoning"],
            study_id=expected["study_id"],
        )
        if (
            values["MODEL"] != expected["model"]
            or values["REASONING"] != expected["reasoning"]
            or values["ROLE"] != expected["role"]
            or values["STUDY_ID"] != expected["study_id"]
            or values["OUTPUT_FOLDER"] != expected["output_folder"]
            or values["CEILING_USD"] != CEILING_USD
            or jobs != plan["jobs"]
            or contract["job_count"] != 2
            or contract["planned_calls"] != 10
            or contract["manifest_sha256"] != record["jobs_sha256"]
            or contract["identity"] != record["identity"]
            or contract["availability_manifest_sha256"] != AVAILABILITY_HASH
            or contract["resume_ledger"]["events"] != 0
            or contract["call_settings"]["sdk_max_retries"] != 0
        ):
            raise ValueError("Experiment A pilot embedded contract changed")
        identities.add(record["identity"])
        job_ids.extend(job["id"] for job in jobs)
        checked.append(
            {
                "label": record["label"],
                "model": record["model"],
                "task": record["task"],
                "source_sha256": source_record["sha256"],
                "jobs": len(jobs),
                "calls": sum(job["calls"] for job in jobs),
            }
        )
    if (
        len(identities) != 4
        or len(job_ids) != len(set(job_ids))
        or not math.isclose(
            sum(record["incremental_ceiling_usd"] for record in manifest["tasks"]),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Experiment A pilot tasks collide or exceed allocation")
    return {
        "pilot_tasks_manifest_sha256": manifest["pilot_tasks_manifest_sha256"],
        "status": manifest["status"],
        "tasks": checked,
        "task_count": 4,
        "job_count": 8,
        "planned_calls": 40,
        "aggregate_incremental_ceiling_usd": 1.0,
        "maximum_daily_exposure_usd": 9.555856,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST}")
    checked = verify()
    for task in checked["tasks"]:
        print(
            "PASS {label}: {model}, {jobs} jobs / {calls} calls, "
            "source {source_sha256}".format(**task)
        )
    print(
        "EXPERIMENT A PILOTS STAGED: 4 tasks, 8 jobs, 40 calls, $1.000000 "
        "aggregate ceiling; maximum daily exposure $9.555856"
    )


if __name__ == "__main__":
    main()
