"""Generate and verify Claude-none Experiment A shards 07--11."""

from __future__ import annotations

import argparse
import ast
import base64
import copy
from functools import lru_cache
import json
import math
from pathlib import Path
import zlib

import build_experiment_a_cell_v1 as cell_builder
import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_claude_none_batch00_collection as previous_collection
import verify_experiment_a_gemini_batch00 as stage_base
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch00"
MANIFEST = GENERATED / "experiment_a_claude_none_batch01_tasks_v1.json"
FROZEN_AT = "2026-09-21T20:27:39.808217+00:00"

MODEL = "anthropic/claude-sonnet-4-6@default"
REASONING = "none"
ROLE = "reasoning_off_sensitivity"
STUDY_ID = "chronos_round2_water4_study_claude_none_v1"
SHARDS = tuple(range(7, 12))
INCREMENTAL_CEILING_USD = 1.09
EXPECTED_JOB_COUNT = 115
EXPECTED_PLANNED_CALLS = 391
EXPECTED_AGGREGATE_CEILING_USD = 5.45
BATCH_NAME = "claude_none_batch01_shards_07_11"
BATCH_DISPLAY = "CLAUDE-NONE BATCH01"
EXPECTED_PREVIOUS_REMAINING_JOBS = 529
PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD = 4.1205888
PRE_LAUNCH_OFFICIAL_MINUS_RAW_KNOWN_USD = 0.3335013
EXPECTED_QUOTA_RUN_ID = 2731442
EXPECTED_QUOTA_USED_USD = 4.4540901
EXPECTED_QUOTA_ALLOWED_USD = 10.0
LAUNCH_POLICY = (
    "exactly_shards_07_11_may_run; no_later_claude_shard_may_launch_"
    "before_batch01_is_sealed_and_fresh_quota_is_attested"
)

QUOTA_ATTESTATION = (
    RUNS / "quota_after_claude_none_batch00_20260921_v1.json"
)
QUOTA_EVIDENCE = previous_collection._artifact_paths(
    previous_collection.EXECUTIONS[3]
)["evidence"]
QUOTA_TERMINAL = previous_collection._artifact_paths(
    previous_collection.EXECUTIONS[3]
)["terminal"]


def _task(shard: int) -> str:
    return f"chronos-r2-water4-study-claude-none-s{shard:02d}-v1"


def _folder(shard: int) -> str:
    return f"round2_water4_study_claude_none_s{shard:02d}_v1"


def _source(shard: int) -> Path:
    return GENERATED / f"water4_study_claude_none_s{shard:02d}_v1.py"


def _wrapper(shard: int) -> Path:
    return GENERATED / f"water4_study_claude_none_s{shard:02d}_transport_v1.py"


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
        or attestation.get("response", {}).get("daily_quota_used_usd")
        != EXPECTED_QUOTA_USED_USD
        or attestation.get("response", {}).get("total_daily_quota_allowed_usd")
        != EXPECTED_QUOTA_ALLOWED_USD
    ):
        raise ValueError("Claude batch01 quota attestation changed")
    return attestation


def _manifest_hash(value: dict) -> str:
    return stage_base._canonical_hash(
        {key: item for key, item in value.items() if key != "batch_manifest_sha256"}
    )


@lru_cache(maxsize=None)
def build_source(shard: int) -> str:
    if shard not in SHARDS:
        raise ValueError("shard is outside Claude batch01")
    return cell_builder.build_source(**_arguments(shard))


def build_wrapper(shard: int) -> str:
    canonical = build_source(shard).encode()
    encoded = base64.b85encode(zlib.compress(canonical, level=9))
    digest = stage_base._sha256(canonical)
    task = _task(shard)
    return f'''# Deterministic transport wrapper; scientific payload is byte-pinned.
import base64 as _transport_base64
import hashlib as _transport_hashlib
import zlib as _transport_zlib

if False:
    @task(name={task!r})
    def _transport_task_marker(llm):
        pass

_TRANSPORT_PAYLOAD_B85 = {encoded!r}
_TRANSPORT_PAYLOAD_SHA256 = {digest!r}
_transport_payload = _transport_zlib.decompress(
    _transport_base64.b85decode(_TRANSPORT_PAYLOAD_B85)
)
if _transport_hashlib.sha256(_transport_payload).hexdigest() != (
    _TRANSPORT_PAYLOAD_SHA256
):
    raise ValueError("Canonical Experiment A payload hash mismatch")
exec(
    compile(
        _transport_payload,
        {f'water4_study_claude_none_s{shard:02d}_v1.py'!r},
        "exec",
    ),
    globals(),
    globals(),
)
'''


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
    source = _source(shard)
    wrapper = _wrapper(shard)
    raw = source.read_bytes()
    values = stage_base._assignments(raw.decode(), source)
    contract = values["CONTRACT"]
    jobs = values["EXPECTED_JOBS"]
    return {
        "shard_index": shard,
        "shard_count": cell_builder.SHARD_COUNT,
        "task": _task(shard),
        "output_folder": _folder(shard),
        "source_status": "frozen_prelaunch",
        "source": evidence_base._file_record(source),
        "transport_wrapper": evidence_base._file_record(wrapper),
        "transport_payload_sha256": stage_base._sha256(raw),
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        "jobs_sha256": contract["manifest_sha256"],
        "identity": contract["identity"],
        "pilot_receipt_sha256": contract["pilot_receipt_sha256"],
        "incremental_ceiling_usd": contract["incremental_ceiling_usd"],
        "effective_ceiling_usd": contract["effective_ceiling_usd"],
        "scientific_changes_from_frozen_cell": [],
        "transport_change": "zlib_level9_base85_with_pre_execution_sha256_check",
    }


def write_sources() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for shard in SHARDS:
        source = _source(shard)
        wrapper = _wrapper(shard)
        source.write_text(build_source(shard))
        wrapper.write_text(build_wrapper(shard))
        print(f"WROTE {source} {stage_base._sha256(source.read_bytes())}")
        print(f"WROTE {wrapper} {stage_base._sha256(wrapper.read_bytes())}")


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
        "pre_launch_raw_known_daily_cost_usd": PRE_LAUNCH_RAW_KNOWN_DAILY_COST_USD,
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
        raise ValueError("Claude batch01 manifest self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load(value)
    expected = build_manifest()
    if manifest != expected:
        raise ValueError("Claude batch01 differs from deterministic regeneration")
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
        raise ValueError("Claude batch01 topology or budget changed")

    identities, job_ids = set(), []
    for shard, record in zip(SHARDS, manifest["tasks"]):
        source = _source(shard)
        wrapper = _wrapper(shard)
        raw = source.read_bytes()
        wrapper_raw = wrapper.read_bytes()
        values = stage_base._assignments(raw.decode(), source)
        wrapper_values = _assignments(wrapper_raw.decode(), wrapper)
        contract = values["CONTRACT"]
        jobs = values["EXPECTED_JOBS"]
        payload = zlib.decompress(
            base64.b85decode(wrapper_values["_TRANSPORT_PAYLOAD_B85"])
        )
        if (
            record["shard_index"] != shard
            or record["task"] != _task(shard)
            or record["source"]["sha256"] != stage_base._sha256(raw)
            or record["transport_wrapper"]["sha256"]
            != stage_base._sha256(wrapper_raw)
            or raw.decode() != build_source(shard)
            or wrapper_raw.decode() != build_wrapper(shard)
            or payload != raw
            or wrapper_values["_TRANSPORT_PAYLOAD_SHA256"]
            != stage_base._sha256(raw)
            or record["transport_payload_sha256"] != stage_base._sha256(raw)
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
            raise ValueError(f"Claude batch01 s{shard:02d} source changed")
        compile(raw.decode(), str(source), "exec")
        compile(wrapper_raw.decode(), str(wrapper), "exec")
        identities.add(record["identity"])
        job_ids.extend(job["id"] for job in jobs)
    if (
        len(identities) != 1
        or len(job_ids) != EXPECTED_JOB_COUNT
        or len(job_ids) != len(set(job_ids))
    ):
        raise ValueError("Claude batch01 shards collide")
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
            f"{record['planned_calls']} calls, source "
            f"{record['source']['sha256']}, wrapper "
            f"{record['transport_wrapper']['sha256']}"
        )
    print(
        f"{BATCH_DISPLAY} STAGED: {len(SHARDS)} tasks / "
        f"{EXPECTED_JOB_COUNT} jobs / {EXPECTED_PLANNED_CALLS} calls; "
        f"aggregate ceiling ${checked['aggregate_incremental_ceiling_usd']:.2f}; "
        f"maximum daily exposure ${checked['maximum_daily_exposure_usd']:.7f}"
    )


if __name__ == "__main__":
    main()
