"""Seal and independently verify Claude-none Experiment A shards 07--11."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

import build_experiment_a_claude_none_s08_resume_v1 as resume_builder
import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_claude_none_batch00_collection as previous_collection
import verify_experiment_a_claude_none_batch01 as staged_batch
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch01"
MANIFEST = GENERATED / "experiment_a_claude_none_batch01_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_claude_none_batch01_tasks_v1.json"
RESUME_ATTESTATION = RUNS / "s08_invalid_response_resume_attestation_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_claude_none_batch01_20260922_v1.json"
)

MODEL = staged_batch.MODEL
REASONING = staged_batch.REASONING
ROLE = staged_batch.ROLE
STUDY_ID = staged_batch.STUDY_ID
FROZEN_AT = "2026-09-21T21:29:45.486538+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {
    7: 2736419,
    8: 2737771,
    9: 2736496,
    10: 2736544,
    11: 2736558,
}

PRE_BATCH_OFFICIAL_DAILY_USD = 4.4540901
POST_BATCH_OFFICIAL_DAILY_USD = 6.3010788
SCIENTIFIC_KNOWN_COST_USD = 1.8348477
EXCLUDED_TAIL_KNOWN_COST_USD = 0.007104
BATCH_KNOWN_COST_USD = 1.8419517
POST_BATCH_KNOWN_DAILY_USD = 6.2960418
OFFICIAL_QUOTA_DELTA_USD = 1.8469887
UNATTRIBUTED_OFFICIAL_DELTA_USD = 0.005037


def _task(index: int) -> str:
    return f"chronos-r2-water4-study-claude-none-s{index:02d}-v1"


def _folder(index: int) -> str:
    return f"round2_water4_study_claude_none_s{index:02d}_v1"


def _execution(index: int) -> dict:
    if index == 8:
        task = resume_builder.RESUME_TASK
        source = resume_builder.SOURCE
        wrapper = resume_builder.WRAPPER
        run_folder = "s08_resume"
        kind = "completed_projection_resume_after_invalid_response"
        recovery = resume_builder
    else:
        task = _task(index)
        source = staged_batch._source(index)
        wrapper = staged_batch._wrapper(index)
        run_folder = f"s{index:02d}"
        kind = "baseline"
        recovery = None
    root = (
        RUNS
        / run_folder
        / task
        / "1"
        / previous_collection.MODEL_SLUG
        / str(RUN_IDS[index])
    )
    return {
        "shard_index": index,
        "execution_kind": kind,
        "task": task,
        "canonical_task": _task(index),
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": _folder(index),
        "output_root": root / _folder(index),
        "source": source,
        "transport_source": wrapper,
        "recovery_builder": recovery,
    }


EXECUTIONS = tuple(_execution(index) for index in SHARDS)
TOP_LEVEL_KEYS = {
    "schema",
    "collection_manifest_sha256",
    "frozen_at",
    "batch",
    "model",
    "reasoning",
    "role",
    "study_id",
    "previous_collection_manifest_sha256",
    "prelaunch_manifest",
    "s08_resume_attestation",
    "post_batch_quota_attestation",
    "post_batch_quota_attestation_sha256",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


def _manifest_hash(value: dict) -> str:
    return evidence_base._canonical_hash(
        {
            key: item
            for key, item in value.items()
            if key != "collection_manifest_sha256"
        }
    )


@lru_cache(maxsize=1)
def _previous() -> dict:
    return previous_collection.verify()


def _verify_resume_attestation(record: dict) -> dict:
    raw = evidence_base._read_pinned(
        record,
        RESUME_ATTESTATION,
        "Claude s08 resume attestation",
    )
    attestation = json.loads(raw)
    if (
        attestation.get("attestation_sha256")
        != resume_builder._attestation_hash(attestation)
        or attestation.get("original_execution", {}).get("run_id") != 2736418
        or attestation.get("original_execution", {}).get("scientific_status")
        != "incomplete_rejected"
        or attestation.get("resume_projection", {})
        .get("excluded_incomplete_tail", {})
        .get("observed_invocations")
        != 2
        or attestation.get("resume_execution", {}).get(
            "scientific_parameter_changes"
        )
        != []
    ):
        raise ValueError("Claude s08 resume attestation changed")
    resume_builder.verify(attestation)
    return attestation


def _verify_quota(record: dict) -> dict:
    raw = evidence_base._read_pinned(
        record,
        POST_BATCH_QUOTA_ATTESTATION,
        "Claude batch01 post-batch quota attestation",
    )
    attestation = json.loads(raw)
    artifacts = previous_collection._artifact_paths(EXECUTIONS[1])
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task")
        != resume_builder.RESUME_TASK
        or attestation.get("run_context", {}).get("run_id") != RUN_IDS[8]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_OFFICIAL_DAILY_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Claude batch01 quota evidence changed")
    return attestation


def _totals(shards: list[dict]) -> dict:
    accounts = [shard["accounting"] for shard in shards]
    scientific_cost = round(
        math.fsum(item["known_cost_usd"] for item in accounts), 12
    )
    raw_cost = round(scientific_cost + EXCLUDED_TAIL_KNOWN_COST_USD, 12)
    official_delta = round(
        POST_BATCH_OFFICIAL_DAILY_USD - PRE_BATCH_OFFICIAL_DAILY_USD, 12
    )
    return {
        "completed_jobs": sum(item["completed_jobs"] for item in accounts),
        "planned_calls": sum(item["planned_calls"] for item in accounts),
        "scientific_observed_invocations": sum(
            item["observed_invocations"] for item in accounts
        ),
        "raw_observed_invocations": sum(
            item["observed_invocations"] for item in accounts
        )
        + 2,
        "scientific_complete_calls": sum(
            item["complete_calls"] for item in accounts
        ),
        "raw_call_complete_events": sum(
            item["complete_calls"] for item in accounts
        )
        + 2,
        "failed_calls": sum(item["failed_calls"] for item in accounts),
        "unknown_cost_calls": sum(
            item["unknown_cost_calls"] for item in accounts
        ),
        "invalid_json_lines": sum(
            item["invalid_json_lines"] for item in accounts
        ),
        "scientific_ledger_events": sum(item["events"] for item in accounts),
        "raw_accounted_events": sum(item["events"] for item in accounts) + 4,
        "scientific_started_attempts": sum(
            item["started_attempts"] for item in accounts
        ),
        "raw_started_attempts": sum(
            item["started_attempts"] for item in accounts
        )
        + 1,
        "excluded_incomplete_tail_invocations": 2,
        "structurally_invalid_call_complete_events": 1,
        "scientific_known_cost_usd": scientific_cost,
        "excluded_tail_known_cost_usd": EXCLUDED_TAIL_KNOWN_COST_USD,
        "batch_known_cost_usd": raw_cost,
        "pre_batch_official_daily_quota_used_usd": PRE_BATCH_OFFICIAL_DAILY_USD,
        "post_batch_known_daily_cost_usd": round(
            PRE_BATCH_OFFICIAL_DAILY_USD + raw_cost, 12
        ),
        "post_batch_official_daily_quota_used_usd": POST_BATCH_OFFICIAL_DAILY_USD,
        "official_quota_delta_usd": official_delta,
        "unattributed_official_minus_raw_known_usd": round(
            official_delta - raw_cost, 12
        ),
    }


def build_manifest() -> dict:
    previous = _previous()
    staged = staged_batch._load()
    quota = json.loads(POST_BATCH_QUOTA_ATTESTATION.read_text())
    shards = [
        previous_collection._build_shard_record(execution)
        for execution in EXECUTIONS
    ]
    if staged.get("batch_manifest_sha256") != (
        "b87ae6746573394df6dc0f8f44da65f6ce397857747408d8f020e1ab2f653f44"
    ):
        raise ValueError("Claude batch01 prelaunch manifest changed")
    manifest = {
        "schema": "chronos.experiment-a-claude-none-batch01-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "claude_none_batch01_shards_07_11",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": evidence_base._file_record(PRELAUNCH_MANIFEST),
        "s08_resume_attestation": evidence_base._file_record(
            RESUME_ATTESTATION
        ),
        "post_batch_quota_attestation": evidence_base._file_record(
            POST_BATCH_QUOTA_ATTESTATION
        ),
        "post_batch_quota_attestation_sha256": quota["attestation_sha256"],
        "shard_count": len(shards),
        "job_count": sum(shard["accounting"]["job_count"] for shard in shards),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "totals": _totals(shards),
        "shards": shards,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Claude batch01 collection schema")
    if manifest.get("collection_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Claude batch01 collection self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous = _previous()
    staged = staged_batch._load()
    evidence_base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Claude batch01 prelaunch manifest",
    )
    _verify_resume_attestation(manifest["s08_resume_attestation"])
    quota = _verify_quota(manifest["post_batch_quota_attestation"])
    if (
        manifest["schema"]
        != "chronos.experiment-a-claude-none-batch01-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "claude_none_batch01_shards_07_11"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
        or staged["batch_manifest_sha256"]
        != json.loads(PRELAUNCH_MANIFEST.read_text())["batch_manifest_sha256"]
        or manifest["post_batch_quota_attestation_sha256"]
        != quota["attestation_sha256"]
        or manifest["shard_count"] != 5
        or manifest["job_count"] != 115
        or manifest["planned_calls"] != 391
    ):
        raise ValueError("Claude batch01 top-level contract changed")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Claude batch01 shard indexes changed")
    verified = [
        previous_collection._verify_shard(execution, record)
        for execution, record in zip(EXECUTIONS, records)
    ]
    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous_runtime = previous_collection._runtime()
    try:
        full_jobs = previous_collection.protocol.jobs_for(MODEL, "study")
        expected = [
            job
            for index in SHARDS
            for job in previous_collection.select_shard(
                full_jobs,
                shard_index=index,
                shard_count=previous_collection.cell_builder.SHARD_COUNT,
            )
        ]
    finally:
        previous_collection._restore_runtime(previous_runtime)
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != 115
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 391
    ):
        raise ValueError("Claude batch01 is not its deterministic disjoint subset")
    shards = [{"accounting": item["accounting"]} for item in verified]
    totals = _totals(shards)
    evidence_base._require_equal(manifest["totals"], totals, "collection totals")
    fixed = {
        "completed_jobs": 115,
        "planned_calls": 391,
        "scientific_observed_invocations": 398,
        "raw_observed_invocations": 400,
        "scientific_complete_calls": 396,
        "raw_call_complete_events": 398,
        "failed_calls": 2,
        "unknown_cost_calls": 0,
        "invalid_json_lines": 0,
        "scientific_ledger_events": 632,
        "raw_accounted_events": 636,
        "scientific_started_attempts": 117,
        "raw_started_attempts": 118,
        "excluded_incomplete_tail_invocations": 2,
        "structurally_invalid_call_complete_events": 1,
    }
    if any(totals[key] != expected for key, expected in fixed.items()):
        raise ValueError("Claude batch01 accounting topology changed")
    for key, expected in (
        ("scientific_known_cost_usd", SCIENTIFIC_KNOWN_COST_USD),
        ("excluded_tail_known_cost_usd", EXCLUDED_TAIL_KNOWN_COST_USD),
        ("batch_known_cost_usd", BATCH_KNOWN_COST_USD),
        ("post_batch_known_daily_cost_usd", POST_BATCH_KNOWN_DAILY_USD),
        ("official_quota_delta_usd", OFFICIAL_QUOTA_DELTA_USD),
        (
            "unattributed_official_minus_raw_known_usd",
            UNATTRIBUTED_OFFICIAL_DELTA_USD,
        ),
    ):
        if not math.isclose(totals[key], expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"Claude batch01 cost changed: {key}")
    return {
        "schema": "chronos.experiment-a-claude-none-batch01-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 5,
        "completed_jobs": totals["completed_jobs"],
        "remaining_jobs": previous["remaining_jobs"] - totals["completed_jobs"],
        "planned_calls": totals["planned_calls"],
        "raw_observed_invocations": totals["raw_observed_invocations"],
        "failed_calls": totals["failed_calls"],
        "unknown_cost_calls": totals["unknown_cost_calls"],
        "batch_known_cost_usd": totals["batch_known_cost_usd"],
        "post_batch_official_daily_quota_used_usd": totals[
            "post_batch_official_daily_quota_used_usd"
        ],
        "unattributed_official_minus_raw_known_usd": totals[
            "unattributed_official_minus_raw_known_usd"
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST} {manifest['collection_manifest_sha256']}")
    checked = verify()
    print(
        "PASS Claude-none batch01: {completed_jobs}/115 jobs, "
        "{planned_calls} planned / {raw_observed_invocations} raw observed "
        "calls, {failed_calls} failed calls, ${batch_known_cost_usd:.7f} "
        "raw-known batch cost, ${post_batch_official_daily_quota_used_usd:.7f} "
        "official daily used, ${unattributed_official_minus_raw_known_usd:.7f} "
        "official-minus-known delta; five shards disjoint and raw-revalidated"
        .format(**checked)
    )


if __name__ == "__main__":
    main()
