"""Generate and verify the quota-bounded first Terra Experiment A shard."""

from __future__ import annotations

import argparse
import ast
import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import build_experiment_a_cell_v1 as cell_builder
import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_qwen_batch00_collection as evidence_base
import verify_experiment_a_qwen_cell_collection as previous_collection


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "experiment_a_terra_batch00_tasks_v1.json"
FROZEN_AT = "2026-09-21T00:24:30+03:30"
MODEL = "openai/gpt-5.6-terra"
REASONING = "low"
ROLE = "matched_non_off_primary"
STUDY_ID = "chronos_round2_water4_study_terra_low_v1"
SHARDS = (0,)
INCREMENTAL_CEILING_USD = 0.67

QUOTA_ATTESTATION = (
    HERE
    / "round2_runs_20260920/experiment_a_qwen_batch04"
    / "quota_after_qwen_cell_20260921_v1.json"
)
QUOTA_EVIDENCE = (
    HERE
    / "round2_runs_20260920/experiment_a_qwen_batch04/s29"
    / "chronos-r2-water4-study-qwen-low-s29-v1/1"
    / "qwen3-235b-a22b-instruct-2507/2685586"
    / "round2_water4_study_qwen_low_s29_v1"
    / "qwen_qwen3-235b-a22b-instruct-2507.jsonl"
)
QUOTA_TERMINAL = QUOTA_EVIDENCE.with_name("terminal.json")


@lru_cache(maxsize=1)
def _previous() -> dict:
    return previous_collection.verify()


@lru_cache(maxsize=1)
def _quota() -> dict:
    attestation = json.loads(QUOTA_ATTESTATION.read_text())
    quota_capture.verify_attestation(
        attestation,
        QUOTA_EVIDENCE.read_bytes(),
        QUOTA_TERMINAL.read_bytes(),
    )
    return attestation


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
            if key != "batch_manifest_sha256"
        }
    )


def _task(shard: int) -> str:
    return f"chronos-r2-water4-study-terra-low-s{shard:02d}-v1"


def _folder(shard: int) -> str:
    return f"round2_water4_study_terra_low_s{shard:02d}_v1"


def _source(shard: int) -> Path:
    return GENERATED / f"water4_study_terra_low_s{shard:02d}_v1.py"


def _arguments(shard: int) -> dict:
    return {
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "shard_index": shard,
        "shard_count": cell_builder.SHARD_COUNT,
        "task_name": _task(shard),
        "output_folder": _folder(shard),
    }


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


def _record(shard: int) -> dict:
    path = _source(shard)
    raw = path.read_bytes()
    values = _assignments(raw.decode(), path)
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    return {
        "shard_index": shard,
        "shard_count": cell_builder.SHARD_COUNT,
        "task": _task(shard),
        "output_folder": _folder(shard),
        "source_status": "frozen_prelaunch",
        "source": {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(raw),
            "bytes": len(raw),
        },
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": contract["manifest_sha256"],
        "identity": contract["identity"],
        "pilot_receipt_sha256": contract["pilot_receipt_sha256"],
        "incremental_ceiling_usd": contract["incremental_ceiling_usd"],
        "effective_ceiling_usd": contract["effective_ceiling_usd"],
    }


def write_sources() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for shard in SHARDS:
        path = _source(shard)
        path.write_text(cell_builder.build_source(**_arguments(shard)))
        print(f"WROTE {path}")


def build_manifest() -> dict:
    previous = _previous()
    quota = _quota()
    records = [_record(shard) for shard in SHARDS]
    used = quota["response"]["daily_quota_used_usd"]
    allowed = quota["response"]["total_daily_quota_allowed_usd"]
    aggregate = math.fsum(
        record["incremental_ceiling_usd"] for record in records
    )
    manifest = {
        "schema": "chronos.experiment-a-full-batch-tasks.v1",
        "batch_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "batch": "terra_batch00_shard_00",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_cell_collection_manifest_sha256": previous[
            "cell_collection_manifest_sha256"
        ],
        "quota_attestation": evidence_base._file_record(QUOTA_ATTESTATION),
        "quota_attestation_sha256": quota["attestation_sha256"],
        "pre_launch_known_daily_cost_usd": used,
        "daily_limit_usd": allowed,
        "incremental_ceiling_per_task_usd": INCREMENTAL_CEILING_USD,
        "aggregate_incremental_ceiling_usd": aggregate,
        "maximum_daily_exposure_usd": used + aggregate,
        "launch_policy": "exactly_one_shard_may_run_within_sealed_exposure",
        "shard_count_total": cell_builder.SHARD_COUNT,
        "batch_shards": list(SHARDS),
        "task_count": len(records),
        "job_count": sum(record["job_count"] for record in records),
        "planned_calls": sum(record["planned_calls"] for record in records),
        "tasks": records,
    }
    manifest["batch_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if manifest.get("batch_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Experiment A Terra batch00 self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Experiment A Terra batch00 differs from regeneration")
    if (
        manifest["status"] != "authorized_not_launched"
        or manifest["task_count"] != 1
        or manifest["job_count"] != 23
        or manifest["planned_calls"] != 75
        or manifest["aggregate_incremental_ceiling_usd"] != 0.67
        or manifest["maximum_daily_exposure_usd"] > manifest["daily_limit_usd"]
    ):
        raise ValueError("Experiment A Terra batch00 topology or budget changed")
    record = manifest["tasks"][0]
    path = _source(0)
    raw = path.read_bytes()
    if (
        record["shard_index"] != 0
        or record["task"] != _task(0)
        or record["source"]["sha256"] != _sha256(raw)
        or record["source"]["bytes"] != len(raw)
        or raw.decode() != cell_builder.build_source(**_arguments(0))
        or record["incremental_ceiling_usd"] != INCREMENTAL_CEILING_USD
        or record["effective_ceiling_usd"] != INCREMENTAL_CEILING_USD
    ):
        raise ValueError("Experiment A Terra batch00 source changed")
    values = _assignments(raw.decode(), path)
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    if (
        contract["shard_index"] != 0
        or contract["shard_count"] != cell_builder.SHARD_COUNT
        or contract["parent_ledger_sha256"] is not None
        or contract["resume_ledger"]["events"] != 0
        or len(jobs) != 23
        or sum(job["calls"] for job in jobs) != 75
        or contract["pilot_receipt_sha256"]
        != record["pilot_receipt_sha256"]
    ):
        raise ValueError("Experiment A Terra batch00 contract changed")
    compile(raw.decode(), str(path), "exec")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        write_sources()
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['batch_manifest_sha256']}")
    checked = verify()
    record = checked["tasks"][0]
    print(
        f"PASS s00: {record['job_count']} jobs / "
        f"{record['planned_calls']} calls, source "
        f"{record['source']['sha256']}"
    )
    print(
        "TERRA BATCH00 STAGED: 1 task / 23 jobs / 75 calls; aggregate "
        f"ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        "maximum daily exposure "
        f"${checked['maximum_daily_exposure_usd']:.8f}"
    )


if __name__ == "__main__":
    main()
