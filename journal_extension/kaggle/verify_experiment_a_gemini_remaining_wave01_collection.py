"""Seal and independently verify Gemini Experiment A shards 05--12."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from functools import lru_cache
import json
import math
from pathlib import Path

import build_experiment_a_task_slug_repair_v1 as repair_builder
import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_gemini_remaining as staged_batch
import verify_experiment_a_qwen_batch00_collection as base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_gemini_remaining_wave01"
MANIFEST = GENERATED / "experiment_a_gemini_remaining_wave01_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_gemini_remaining_tasks_v1.json"
REPAIR_ATTESTATION = RUNS / "s11_version1_no_run_attestation_v1.json"
POST_WAVE_QUOTA_ATTESTATION = (
    RUNS / "quota_after_gemini_remaining_wave01_20260921_v1.json"
)

MODEL = staged_batch.cell_stage.MODEL
MODEL_SLUG = "gemini-3.6-flash"
MODEL_FILE = "google_gemini-3.6-flash.jsonl"
REASONING = staged_batch.cell_stage.REASONING
ROLE = staged_batch.cell_stage.ROLE
STUDY_ID = staged_batch.cell_stage.STUDY_ID
FROZEN_AT = "2026-09-21T15:37:51.523852+00:00"
SHARDS = tuple(range(5, 13))
PRE_BATCH_KNOWN_DAILY_COST_USD = 0.0
BATCH_KNOWN_COST_USD = 0.54653175
POST_BATCH_KNOWN_DAILY_COST_USD = 0.54653175
RUN_IDS = {
    5: 2699609,
    6: 2699717,
    7: 2699744,
    8: 2699835,
    9: 2699834,
    10: 2699833,
    11: 2712143,
    12: 2700036,
}


def _canonical_task(index: int) -> str:
    return f"chronos-r2-water4-study-gemini-minimal-s{index:02d}-v1"


def _output_folder(index: int) -> str:
    return f"round2_water4_study_gemini_minimal_s{index:02d}_v1"


def _execution(index: int) -> dict:
    canonical_task = _canonical_task(index)
    output = _output_folder(index)
    is_repair = index == 11
    task = repair_builder.REPAIR_TASK if is_repair else canonical_task
    source = (
        repair_builder.REPAIR
        if is_repair
        else GENERATED / f"water4_study_gemini_minimal_s{index:02d}_v1.py"
    )
    root = (
        RUNS
        / f"s{index:02d}"
        / task
        / "1"
        / MODEL_SLUG
        / str(RUN_IDS[index])
    )
    execution = {
        "shard_index": index,
        "execution_kind": "task_slug_repair" if is_repair else "baseline",
        "task": task,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": output,
        "output_root": root / output,
        "source": source,
    }
    if is_repair:
        execution.update(
            canonical_task=canonical_task,
            canonical_output_folder=output,
        )
    return execution


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
    "repair_attestation",
    "post_wave_quota_attestation",
    "post_wave_quota_attestation_sha256",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}


@contextmanager
def _gemini_base():
    previous = (
        base.MODEL,
        base.MODEL_SLUG,
        base.MODEL_FILE,
        base.REASONING,
        base.ROLE,
        base.STUDY_ID,
    )
    base.MODEL = MODEL
    base.MODEL_SLUG = MODEL_SLUG
    base.MODEL_FILE = MODEL_FILE
    base.REASONING = REASONING
    base.ROLE = ROLE
    base.STUDY_ID = STUDY_ID
    base._regenerated_source.cache_clear()
    try:
        yield
    finally:
        (
            base.MODEL,
            base.MODEL_SLUG,
            base.MODEL_FILE,
            base.REASONING,
            base.ROLE,
            base.STUDY_ID,
        ) = previous
        base._regenerated_source.cache_clear()


@lru_cache(maxsize=1)
def _sealed_inputs() -> tuple[dict, dict]:
    # Revalidating the full 25-source staging builder here would duplicate the
    # launch-time gate and can exceed bounded verifier runtimes.  Pin its
    # self-hashed manifest and authenticated reset attestation, then regenerate
    # and audit every source actually present in this wave below.
    staged = staged_batch._load()
    previous = staged_batch._previous()
    quota = staged_batch._quota()
    if (
        staged.get("batch_manifest_sha256")
        != "d982c7cb1242383cf5eb54c525ea1b2fa6b66fd50f15e2ab28e9d008a3a53211"
        or staged.get("status") != "authorized_not_launched"
        or staged.get("previous_collection_manifest_sha256")
        != previous["collection_manifest_sha256"]
        or staged.get("quota_attestation_sha256")
        != quota["attestation_sha256"]
        or staged.get("pre_launch_known_daily_cost_usd") != 0.0
        or staged.get("task_count") != 25
        or staged.get("job_count") != 575
        or staged.get("planned_calls") != 1939
    ):
        raise ValueError("Gemini remaining launch authorization changed")
    return previous, staged


def _manifest_hash(manifest: dict) -> str:
    return base._canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "collection_manifest_sha256"
        }
    )


def _totals(shards: list[dict], pre_batch_cost: float) -> dict:
    batch_cost = round(
        math.fsum(shard["accounting"]["known_cost_usd"] for shard in shards),
        12,
    )
    return {
        "completed_jobs": sum(
            shard["accounting"]["completed_jobs"] for shard in shards
        ),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "observed_invocations": sum(
            shard["accounting"]["observed_invocations"] for shard in shards
        ),
        "complete_calls": sum(
            shard["accounting"]["complete_calls"] for shard in shards
        ),
        "failed_calls": sum(
            shard["accounting"]["failed_calls"] for shard in shards
        ),
        "unknown_cost_calls": sum(
            shard["accounting"]["unknown_cost_calls"] for shard in shards
        ),
        "invalid_json_lines": sum(
            shard["accounting"]["invalid_json_lines"] for shard in shards
        ),
        "events": sum(shard["accounting"]["events"] for shard in shards),
        "started_attempts": sum(
            shard["accounting"]["started_attempts"] for shard in shards
        ),
        "batch_known_cost_usd": batch_cost,
        "pre_batch_known_daily_cost_usd": pre_batch_cost,
        "post_batch_known_daily_cost_usd": round(
            pre_batch_cost + batch_cost, 12
        ),
    }


def build_manifest() -> dict:
    previous, staged = _sealed_inputs()
    repair_builder.verify()
    quota = json.loads(POST_WAVE_QUOTA_ATTESTATION.read_text())
    with _gemini_base():
        shards = [base._build_shard_record(execution) for execution in EXECUTIONS]
    pre_batch_cost = round(staged["pre_launch_known_daily_cost_usd"], 12)
    manifest = {
        "schema": "chronos.experiment-a-gemini-remaining-wave01-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "gemini_remaining_wave01_shards_05_12",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": base._file_record(PRELAUNCH_MANIFEST),
        "repair_attestation": base._file_record(REPAIR_ATTESTATION),
        "post_wave_quota_attestation": base._file_record(
            POST_WAVE_QUOTA_ATTESTATION
        ),
        "post_wave_quota_attestation_sha256": quota["attestation_sha256"],
        "shard_count": len(shards),
        "job_count": sum(shard["accounting"]["job_count"] for shard in shards),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "totals": _totals(shards, pre_batch_cost),
        "shards": shards,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Gemini remaining wave01 collection schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Gemini remaining wave01 self-hash mismatch")
    return manifest


def _verify_repair_attestation(record: dict) -> dict:
    raw = base._read_pinned(
        record, REPAIR_ATTESTATION, "Gemini s11 no-run repair attestation"
    )
    attestation = json.loads(raw)
    body = {
        key: value
        for key, value in attestation.items()
        if key != "attestation_sha256"
    }
    if base._canonical_hash(body) != attestation.get("attestation_sha256"):
        raise ValueError("Gemini s11 repair attestation self-hash mismatch")
    repair = repair_builder.verify()
    original = repair_builder.ORIGINAL.read_bytes()
    before = attestation.get("task_version_before_repair") or {}
    quota = attestation.get("official_quota_query", {}).get("response", {})
    accounted = attestation.get("accounted_completed_shards") or []
    if (
        attestation.get("schema")
        != "chronos.kaggle-task-version-repair-attestation.v1"
        or before.get("creationState")
        != "BENCHMARK_TASK_VERSION_CREATION_STATE_UNSPECIFIED"
        or before.get("slug", {}).get("versionNumber") != 1
        or before.get("runs") != []
        or attestation.get("repair_task") != repair_builder.REPAIR_TASK
        or attestation.get("repair_source", {}).get("sha256")
        != base._sha256(repair)
        or attestation.get("repair_source", {}).get("derived_from_sha256")
        != base._sha256(original)
        or attestation.get("unaccounted_quota_usd") != 0.0
        or [item.get("shard_index") for item in accounted]
        != [5, 6, 7, 8, 9, 10, 12]
        or not math.isclose(
            math.fsum(item["known_cost_usd"] for item in accounted),
            attestation["accounted_total_known_cost_usd"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or not math.isclose(
            quota.get("dailyQuotaUsed"),
            attestation["accounted_total_known_cost_usd"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Gemini s11 no-run repair attestation changed")
    return attestation


def _verify_post_wave_quota(record: dict) -> dict:
    raw = base._read_pinned(
        record,
        POST_WAVE_QUOTA_ATTESTATION,
        "Gemini remaining wave01 post-wave quota attestation",
    )
    attestation = json.loads(raw)
    repair = EXECUTIONS[6]
    with _gemini_base():
        artifacts = base._artifact_paths(repair)
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task")
        != repair_builder.REPAIR_TASK
        or attestation.get("run_context", {}).get("run_id") != RUN_IDS[11]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_KNOWN_DAILY_COST_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Gemini remaining wave01 quota evidence changed")
    return attestation


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous, staged = _sealed_inputs()
    base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Gemini remaining prelaunch manifest",
    )
    repair_attestation = _verify_repair_attestation(
        manifest["repair_attestation"]
    )
    quota = _verify_post_wave_quota(manifest["post_wave_quota_attestation"])
    if (
        manifest["schema"]
        != "chronos.experiment-a-gemini-remaining-wave01-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "gemini_remaining_wave01_shards_05_12"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
        or manifest["post_wave_quota_attestation_sha256"]
        != quota["attestation_sha256"]
        or staged["batch_manifest_sha256"]
        != json.loads(PRELAUNCH_MANIFEST.read_text())["batch_manifest_sha256"]
        or staged["pre_launch_known_daily_cost_usd"] != 0.0
        or manifest["shard_count"] != 8
        or manifest["job_count"] != 184
        or manifest["planned_calls"] != 616
        or repair_attestation["repair_task"] != repair_builder.REPAIR_TASK
    ):
        raise ValueError("Gemini remaining wave01 top-level contract changed")

    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Gemini remaining wave01 shard indexes changed")
    with _gemini_base():
        verified = [
            base._verify_shard(execution, record)
            for execution, record in zip(EXECUTIONS, records)
        ]
        previous_runtime = base._runtime()
        try:
            full_jobs = base.protocol.jobs_for(MODEL, "study")
            expected = [
                job
                for index in SHARDS
                for job in base.select_shard(
                    full_jobs,
                    shard_index=index,
                    shard_count=base.cell_builder.SHARD_COUNT,
                )
            ]
        finally:
            base._restore_runtime(previous_runtime)
    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != 184
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 616
    ):
        raise ValueError("Gemini remaining wave01 is not its frozen subset")

    accounts = [item["accounting"] for item in verified]
    actual_totals = _totals(
        [{"accounting": item} for item in accounts],
        PRE_BATCH_KNOWN_DAILY_COST_USD,
    )
    base._require_equal(manifest["totals"], actual_totals, "collection totals")
    if (
        actual_totals["completed_jobs"] != 184
        or actual_totals["planned_calls"] != 616
        or actual_totals["observed_invocations"] != 616
        or actual_totals["complete_calls"] != 616
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 984
        or actual_totals["started_attempts"] != 184
    ):
        raise ValueError("Gemini remaining wave01 accounting topology changed")
    base._require_equal(
        actual_totals["batch_known_cost_usd"],
        BATCH_KNOWN_COST_USD,
        "Gemini remaining wave01 known cost",
    )
    base._require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "Gemini remaining wave01 post-wave known cost",
    )
    return {
        "schema": "chronos.experiment-a-gemini-remaining-wave01-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 8,
        "completed_jobs": actual_totals["completed_jobs"],
        "remaining_jobs": 391,
        "planned_calls": actual_totals["planned_calls"],
        "observed_invocations": actual_totals["observed_invocations"],
        "failed_calls": actual_totals["failed_calls"],
        "unknown_cost_calls": actual_totals["unknown_cost_calls"],
        "batch_known_cost_usd": actual_totals["batch_known_cost_usd"],
        "post_batch_known_daily_cost_usd": actual_totals[
            "post_batch_known_daily_cost_usd"
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
        "PASS Gemini remaining wave01: {completed_jobs}/184 jobs, "
        "{planned_calls} planned calls, {observed_invocations} measured "
        "invocations, {failed_calls} failed calls, ${batch_known_cost_usd:.8f} "
        "batch / ${post_batch_known_daily_cost_usd:.8f} official daily total; "
        "eight shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
