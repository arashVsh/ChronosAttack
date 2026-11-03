"""Freeze and verify the four staged Terra-low defense tasks before upload."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
from pathlib import Path

from build_hosted_cell_v2 import build_source, plan_cell
import verify_round2_terra_study_collection as study_verifier


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "terra_defense_tasks_v1.json"
MODEL = "openai/gpt-5.6-terra"
REASONING = "low"
STUDY_ID = "chronos_round2_terra_reasoning_defense_low_v1"
FROZEN_AT = "2026-09-20T20:35:15+03:30"
CEILING_USD = 0.70
PRE_LAUNCH_COST = 6.968902
REMAINING_CREDIT = 3.031098
COLLECTION_HASH = "99fb3f5d22d48bfcaa4d151702494c2e1ff78178c8b30011dbcb5fab37d4f253"
RECEIPT_HASH = "77d2b0eee32b20e66d2bd203c00a011d40184c482b0b2bf1d11aea436f5f7467"
MINIMAL_HASH = "4e6e9f30bc1803e087ba434b0ce049723567530be10ade9c1569199138d01b2a"

MINIMAL = (
    HERE / "round2_runs_20260920/terra_minimal"
    / "chronos-r2-terra-preflight-minimal-v1/1/gpt-5.6-terra/2644337"
    / "round2_terra_reasoning_preflight_minimal_v1"
)
LOW = (
    HERE / "round2_runs_20260920/terra_low"
    / "chronos-r2-terra-preflight-low-v1/1/gpt-5.6-terra/2646426"
    / "round2_terra_reasoning_preflight_low_v1"
)

TASKS = (
    ("undefended_natural", "natural"),
    ("undefended_attack", "attack"),
    ("randomized", "randomized"),
    ("invariant", "invariant"),
)


def _task(arm: str, label: str) -> str:
    return f"chronos-r2-terra-defense-low-{label}-v1"


def _source(label: str) -> Path:
    return GENERATED / f"terra_defense_low_{label}_v1.py"


def _folder(arm: str) -> str:
    return f"round2_terra_reasoning_defense_low_{arm}_v1"


def _arguments(arm: str, label: str) -> dict:
    return {
        "kind": "defense",
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "ceiling_usd": CEILING_USD,
        "task_name": _task(arm, label),
        "output_folder": _folder(arm),
        "arm": arm,
        "preflight_receipt": LOW / "reasoning_receipt.json",
        "preflight_evidence": LOW / "openai_gpt-5.6-terra.jsonl",
        "preflight_terminal": LOW / "reasoning_terminal.json",
        "minimal_unsupported_receipt": MINIMAL / "reasoning_receipt.json",
        "minimal_unsupported_evidence": MINIMAL / "openai_gpt-5.6-terra.jsonl",
        "minimal_unsupported_terminal": MINIMAL / "reasoning_terminal.json",
        "minimal_unsupported_quota_attestation": MINIMAL / "quota_attestation_1.json",
    }


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(raw)


def _manifest_hash(manifest: dict) -> str:
    return _canonical_hash({
        key: value for key, value in manifest.items()
        if key != "defense_tasks_manifest_sha256"
    })


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


def _record(arm: str, label: str) -> dict:
    path = _source(label)
    raw = path.read_bytes()
    values = _assignments(raw.decode(), path)
    jobs = values["EXPECTED_JOBS"]
    return {
        "arm": arm,
        "task": _task(arm, label),
        "output_folder": _folder(arm),
        "source_status": "frozen_prelaunch",
        "source": {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(raw),
            "bytes": len(raw),
        },
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": values["CONTRACT"]["manifest_sha256"],
        "incremental_ceiling_usd": CEILING_USD,
    }


def build_manifest() -> dict:
    manifest = {
        "schema": "chronos.round2.terra-defense-tasks.v1",
        "defense_tasks_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "model": MODEL,
        "reasoning": REASONING,
        "study_id": STUDY_ID,
        "pre_launch_collection_manifest_sha256": COLLECTION_HASH,
        "pre_launch_known_daily_cost_usd": PRE_LAUNCH_COST,
        "remaining_daily_credit_usd": REMAINING_CREDIT,
        "incremental_ceiling_per_task_usd": CEILING_USD,
        "aggregate_incremental_ceiling_usd": CEILING_USD * len(TASKS),
        "task_count": 4,
        "job_count": 120,
        "planned_calls": 600,
        "tasks": [_record(*item) for item in TASKS],
    }
    manifest["defense_tasks_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None) -> dict:
    manifest = json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    if _manifest_hash(manifest) != manifest.get("defense_tasks_manifest_sha256"):
        raise ValueError("Terra defense-task manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    study = study_verifier.verify()
    expected_keys = {
        "schema", "defense_tasks_manifest_sha256", "frozen_at", "model",
        "reasoning", "study_id", "pre_launch_collection_manifest_sha256",
        "pre_launch_known_daily_cost_usd", "remaining_daily_credit_usd",
        "incremental_ceiling_per_task_usd",
        "aggregate_incremental_ceiling_usd", "task_count", "job_count",
        "planned_calls", "tasks",
    }
    if set(manifest) != expected_keys:
        raise ValueError("invalid Terra defense-task manifest schema")
    if (
        manifest["schema"] != "chronos.round2.terra-defense-tasks.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["study_id"] != STUDY_ID
        or manifest["pre_launch_collection_manifest_sha256"] != COLLECTION_HASH
        or manifest["pre_launch_collection_manifest_sha256"]
        != study["collection_manifest_sha256"]
        or not math.isclose(
            manifest["pre_launch_known_daily_cost_usd"],
            study["known_daily_cost_usd"], rel_tol=0.0, abs_tol=1e-12,
        )
        or manifest["remaining_daily_credit_usd"] != REMAINING_CREDIT
        or manifest["incremental_ceiling_per_task_usd"] != CEILING_USD
        or manifest["aggregate_incremental_ceiling_usd"] != 2.8
        or manifest["aggregate_incremental_ceiling_usd"] > REMAINING_CREDIT
        or (manifest["task_count"], manifest["job_count"], manifest["planned_calls"])
        != (4, 120, 600)
    ):
        raise ValueError("Terra defense-task budget or parent contract changed")
    if not isinstance(manifest["tasks"], list) or len(manifest["tasks"]) != 4:
        raise ValueError("Terra defense-task count changed")

    full = plan_cell(
        kind="defense", model=MODEL, reasoning=REASONING, study_id=STUDY_ID
    )["jobs"]
    expected_ids = {job["id"] for job in full}
    observed_ids = []
    checked = []
    task_keys = {
        "arm", "task", "output_folder", "source_status", "source",
        "job_count", "planned_calls", "jobs_sha256",
        "incremental_ceiling_usd",
    }
    for (arm, label), record in zip(TASKS, manifest["tasks"]):
        if set(record) != task_keys:
            raise ValueError("invalid Terra defense-task record")
        if (
            record["arm"] != arm
            or record["task"] != _task(arm, label)
            or record["output_folder"] != _folder(arm)
            or record["source_status"] != "frozen_prelaunch"
            or (record["job_count"], record["planned_calls"]) != (30, 150)
            or record["incremental_ceiling_usd"] != CEILING_USD
        ):
            raise ValueError("Terra defense-task identity changed")
        source_record = record["source"]
        if set(source_record) != {"path", "sha256", "bytes"}:
            raise ValueError("invalid Terra defense source record")
        path = (ROOT / source_record["path"]).resolve()
        if path != _source(label).resolve():
            raise ValueError("Terra defense source path changed")
        raw = path.read_bytes()
        if len(raw) != source_record["bytes"] or _sha256(raw) != source_record["sha256"]:
            raise ValueError("Terra defense source hash/size mismatch")
        source = raw.decode()
        if source != build_source(**_arguments(arm, label)):
            raise ValueError("Terra defense source is not byte-exact regeneration")
        compile(source, str(path), "exec")
        values = _assignments(source, path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            values["MODEL"] != MODEL
            or values["REASONING"] != REASONING
            or values["STUDY_ID"] != STUDY_ID
            or values["KIND"] != "defense"
            or values["OUTPUT_FOLDER"] != record["output_folder"]
            or values["INCREMENTAL_CEILING_USD"] != CEILING_USD
            or values["RESUME_LEDGER"] != b""
            or contract["arm"] != arm
            or (contract["shard_index"], contract["shard_count"]) != (0, 1)
            or (contract["job_count"], contract["planned_calls"]) != (30, 150)
            or contract["manifest_sha256"] != record["jobs_sha256"]
            or contract["accepted_preflight_receipt_sha256"] != RECEIPT_HASH
            or contract["minimal_unsupported_receipt_sha256"] != MINIMAL_HASH
        ):
            raise ValueError("Terra defense embedded contract changed")
        observed_ids.extend(job["id"] for job in jobs)
        checked.append({
            "arm": arm, "task": record["task"],
            "source_sha256": source_record["sha256"],
            "jobs": len(jobs), "calls": sum(job["calls"] for job in jobs),
        })
    if (
        len(full) != 120 or sum(job["calls"] for job in full) != 600
        or len(observed_ids) != len(set(observed_ids))
        or set(observed_ids) != expected_ids
    ):
        raise ValueError("Terra defense arms are not disjoint and exhaustive")
    return {
        "defense_tasks_manifest_sha256": manifest["defense_tasks_manifest_sha256"],
        "tasks": checked, "task_count": 4, "job_count": 120,
        "planned_calls": 600, "aggregate_incremental_ceiling_usd": 2.8,
        "remaining_daily_credit_usd": REMAINING_CREDIT,
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
        print("PASS {arm}: {jobs} jobs / {calls} calls {source_sha256}".format(**task))
    print(
        "ROUND2 TERRA LOW DEFENSE STAGED: 4 tasks, 120 jobs, 600 calls, "
        "$2.800000 aggregate ceiling below $3.031098 remaining"
    )


if __name__ == "__main__":
    main()
