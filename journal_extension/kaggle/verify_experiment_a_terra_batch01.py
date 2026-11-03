"""Generate and verify quota-bounded Terra Experiment A shards 01--09."""

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
import verify_experiment_a_claude_none_batch07_collection as quota_collection
import verify_experiment_a_qwen_batch00_collection as evidence_base
import verify_experiment_a_terra_batch00_collection as previous_collection


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
MANIFEST = GENERATED / "experiment_a_terra_batch01_tasks_v1.json"
FROZEN_AT = "2026-09-22T15:29:34.794479+00:00"

MODEL = "openai/gpt-5.6-terra"
REASONING = "low"
ROLE = "matched_non_off_primary"
STUDY_ID = "chronos_round2_water4_study_terra_low_v1"
SHARDS = tuple(range(1, 10))
INCREMENTAL_CEILING_USD = 0.67
EXPECTED_JOB_COUNT = 207
EXPECTED_PLANNED_CALLS = 679
EXPECTED_AGGREGATE_CEILING_USD = 6.03
EXPECTED_PREVIOUS_REMAINING_JOBS = 667
PREVIOUS_SHARDS = (0,)
EXPECTED_CUMULATIVE_JOB_COUNT = 230
BATCH_NAME = "terra_batch01_shards_01_09"
BATCH_DISPLAY = "TERRA BATCH01"
PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD = 3.9647331
PRE_LAUNCH_OFFICIAL_MINUS_RAW_KNOWN_USD = 0.0
EXPECTED_QUOTA_RUN_ID = 2780849
EXPECTED_QUOTA_USED_USD = 3.9647331
EXPECTED_QUOTA_ALLOWED_USD = 10.0
LAUNCH_POLICY = (
    "exactly_shards_01_09_may_run; no_later_Terra_shard_may_launch_before_"
    "batch01_is_sealed_and_fresh_quota_is_attested"
)

QUOTA_ATTESTATION = (
    HERE
    / "round2_runs_20260920/experiment_a_claude_none_batch07"
    / "quota_after_claude_none_batch07_20260922_v1.json"
)
QUOTA_EXECUTION = quota_collection.EXECUTIONS[-1]
QUOTA_EVIDENCE = quota_collection.shard_base._artifact_paths(QUOTA_EXECUTION)[
    "evidence"
]
QUOTA_TERMINAL = quota_collection.shard_base._artifact_paths(QUOTA_EXECUTION)[
    "terminal"
]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _manifest_hash(value: dict) -> str:
    return _canonical_hash(
        {
            key: item
            for key, item in value.items()
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


@lru_cache(maxsize=None)
def _prior_job_ids(
    shards: tuple[int, ...],
    model: str,
    reasoning: str,
    role: str,
    study_id: str,
) -> frozenset[str]:
    ids = set()
    for shard in shards:
        source = cell_builder.build_source(
            model=model,
            reasoning=reasoning,
            role=role,
            study_id=study_id,
            shard_index=shard,
            shard_count=cell_builder.SHARD_COUNT,
            task_name=_task(shard),
            output_folder=_folder(shard),
        )
        values = _assignments(source, _source(shard))
        ids.update(job["id"] for job in values["EXPECTED_JOBS"])
    return frozenset(ids)


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
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("run_id")
        != EXPECTED_QUOTA_RUN_ID
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            EXPECTED_QUOTA_USED_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            attestation.get("response", {}).get(
                "total_daily_quota_allowed_usd"
            ),
            EXPECTED_QUOTA_ALLOWED_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError(f"{BATCH_DISPLAY} quota attestation changed")
    return attestation


@lru_cache(maxsize=None)
def build_source(shard: int) -> str:
    if shard not in SHARDS:
        raise ValueError(f"shard is outside {BATCH_DISPLAY}")
    return cell_builder.build_source(**_arguments(shard))


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
        "source": evidence_base._file_record(path),
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": contract["manifest_sha256"],
        "identity": contract["identity"],
        "pilot_receipt_sha256": contract["pilot_receipt_sha256"],
        "incremental_ceiling_usd": contract["incremental_ceiling_usd"],
        "effective_ceiling_usd": contract["effective_ceiling_usd"],
        "scientific_changes_from_frozen_cell": [],
    }


def write_sources() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for shard in SHARDS:
        path = _source(shard)
        raw = build_source(shard).encode()
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(f"refusing to overwrite different source: {path}")
        if not path.exists():
            path.write_bytes(raw)
        print(f"WROTE {path} {_sha256(raw)}")


def build_manifest() -> dict:
    previous = _previous()
    quota = _quota()
    records = [_record(shard) for shard in SHARDS]
    used = quota["response"]["daily_quota_used_usd"]
    allowed = quota["response"]["total_daily_quota_allowed_usd"]
    aggregate = round(
        math.fsum(record["incremental_ceiling_usd"] for record in records), 12
    )
    manifest = {
        "schema": "chronos.experiment-a-full-batch-tasks.v1",
        "batch_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "authorized_not_launched",
        "batch": BATCH_NAME,
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "quota_attestation": evidence_base._file_record(QUOTA_ATTESTATION),
        "quota_attestation_sha256": quota["attestation_sha256"],
        "pre_launch_official_daily_quota_used_usd": used,
        "pre_launch_raw_known_daily_cost_usd": (
            PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD
        ),
        "pre_launch_official_minus_raw_known_usd": (
            PRE_LAUNCH_OFFICIAL_MINUS_RAW_KNOWN_USD
        ),
        "daily_limit_usd": allowed,
        "incremental_ceiling_per_task_usd": INCREMENTAL_CEILING_USD,
        "aggregate_incremental_ceiling_usd": aggregate,
        "maximum_daily_exposure_usd": round(used + aggregate, 12),
        "remaining_official_quota_before_launch_usd": round(allowed - used, 12),
        "launch_policy": LAUNCH_POLICY,
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
        raise ValueError(f"{BATCH_DISPLAY} manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError(f"{BATCH_DISPLAY} differs from deterministic regeneration")
    previous = _previous()
    quota = _quota()
    if (
        manifest["frozen_at"] != quota["queried_at_end_utc"]
        or previous["remaining_jobs"] != EXPECTED_PREVIOUS_REMAINING_JOBS
        or manifest["status"] != "authorized_not_launched"
        or manifest["task_count"] != len(SHARDS)
        or manifest["job_count"] != EXPECTED_JOB_COUNT
        or manifest["planned_calls"] != EXPECTED_PLANNED_CALLS
        or manifest["aggregate_incremental_ceiling_usd"]
        != EXPECTED_AGGREGATE_CEILING_USD
        or manifest["maximum_daily_exposure_usd"] > manifest["daily_limit_usd"]
        or manifest["remaining_official_quota_before_launch_usd"]
        < manifest["aggregate_incremental_ceiling_usd"]
    ):
        raise ValueError(f"{BATCH_DISPLAY} topology or budget changed")

    identities, job_ids = set(), []
    for shard, record in zip(SHARDS, manifest["tasks"]):
        path = _source(shard)
        raw = path.read_bytes()
        values = _assignments(raw.decode(), path)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        if (
            record["shard_index"] != shard
            or record["task"] != _task(shard)
            or record["source"]["sha256"] != _sha256(raw)
            or record["source"]["bytes"] != len(raw)
            or raw.decode() != build_source(shard)
            or record["scientific_changes_from_frozen_cell"] != []
            or record["incremental_ceiling_usd"] != INCREMENTAL_CEILING_USD
            or record["effective_ceiling_usd"] != INCREMENTAL_CEILING_USD
            or contract["shard_index"] != shard
            or contract["shard_count"] != cell_builder.SHARD_COUNT
            or contract["parent_ledger_sha256"] is not None
            or contract["resume_ledger"]["events"] != 0
            or len(jobs) != 23
            or sum(job["calls"] for job in jobs) != record["planned_calls"]
        ):
            raise ValueError(f"{BATCH_DISPLAY} s{shard:02d} source changed")
        compile(raw.decode(), str(path), "exec")
        identities.add(record["identity"])
        job_ids.extend(job["id"] for job in jobs)
    prior_ids = _prior_job_ids(
        tuple(PREVIOUS_SHARDS), MODEL, REASONING, ROLE, STUDY_ID
    )
    if (
        len(identities) != 1
        or len(job_ids) != EXPECTED_JOB_COUNT
        or len(job_ids) != len(set(job_ids))
        or prior_ids.intersection(job_ids)
        or len(prior_ids.union(job_ids)) != EXPECTED_CUMULATIVE_JOB_COUNT
    ):
        raise ValueError(f"{BATCH_DISPLAY} shards collide")
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
    for record in checked["tasks"]:
        print(
            f"PASS s{record['shard_index']:02d}: {record['job_count']} jobs / "
            f"{record['planned_calls']} calls, source {record['source']['sha256']}"
        )
    print(
        f"{BATCH_DISPLAY} STAGED: {len(SHARDS)} tasks / "
        f"{EXPECTED_JOB_COUNT} jobs / {EXPECTED_PLANNED_CALLS} calls; "
        f"aggregate ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        f"maximum daily exposure ${checked['maximum_daily_exposure_usd']:.7f}"
    )


if __name__ == "__main__":
    main()
