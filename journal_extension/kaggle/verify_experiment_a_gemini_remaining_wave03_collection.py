"""Seal and independently verify Gemini Experiment A shards 21--29."""

from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import json
import math
from pathlib import Path

import build_experiment_a_gemini_wave03_task_slug_repairs_v1 as repair_builder
import capture_benchmark_quota_v1 as quota_capture
import verify_experiment_a_gemini_remaining as staged_batch
import verify_experiment_a_gemini_remaining_wave01_collection as gemini_base
import verify_experiment_a_gemini_remaining_wave02_collection as previous_wave
import verify_experiment_a_qwen_batch00_collection as base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_gemini_remaining_wave03"
MANIFEST = GENERATED / "experiment_a_gemini_remaining_wave03_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_gemini_remaining_tasks_v1.json"
REPAIR_ATTESTATION = RUNS / "s26_s29_version1_no_run_attestation_v1.json"
POST_WAVE_QUOTA_ATTESTATION = (
    RUNS / "quota_after_gemini_remaining_wave03_20260921_v1.json"
)

MODEL = previous_wave.MODEL
MODEL_SLUG = previous_wave.MODEL_SLUG
MODEL_FILE = previous_wave.MODEL_FILE
REASONING = previous_wave.REASONING
ROLE = previous_wave.ROLE
STUDY_ID = previous_wave.STUDY_ID
FROZEN_AT = "2026-09-21T18:15:54.398505+00:00"
SHARDS = tuple(range(21, 30))
PRE_BATCH_KNOWN_DAILY_COST_USD = 1.10377575
BATCH_KNOWN_COST_USD = 0.61902975
POST_BATCH_KNOWN_DAILY_COST_USD = 1.7228055
RUN_IDS = {
    21: 2716217,
    22: 2716246,
    23: 2716243,
    24: 2716245,
    25: 2716244,
    26: 2719165,
    27: 2719389,
    28: 2719272,
    29: 2719337,
}
REPAIRS_BY_SHARD = {repair.shard: repair for repair in repair_builder.REPAIRS}


def _canonical_task(index: int) -> str:
    return f"chronos-r2-water4-study-gemini-minimal-s{index:02d}-v1"


def _output_folder(index: int) -> str:
    return f"round2_water4_study_gemini_minimal_s{index:02d}_v1"


def _execution(index: int) -> dict:
    canonical_task = _canonical_task(index)
    output = _output_folder(index)
    repair = REPAIRS_BY_SHARD.get(index)
    task = repair.repair_task if repair else canonical_task
    source = (
        repair.repair_path
        if repair
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
        "execution_kind": "task_slug_repair" if repair else "baseline",
        "task": task,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": output,
        "output_root": root / output,
        "source": source,
    }
    if repair:
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


@lru_cache(maxsize=1)
def _sealed_inputs() -> tuple[dict, dict]:
    previous = previous_wave.verify()
    staged = staged_batch._load()
    quota = staged_batch._quota()
    if (
        staged.get("batch_manifest_sha256")
        != "d982c7cb1242383cf5eb54c525ea1b2fa6b66fd50f15e2ab28e9d008a3a53211"
        or staged.get("status") != "authorized_not_launched"
        or staged.get("quota_attestation_sha256") != quota["attestation_sha256"]
        or staged.get("pre_launch_known_daily_cost_usd") != 0.0
        or staged.get("task_count") != 25
        or staged.get("job_count") != 575
        or staged.get("planned_calls") != 1939
        or previous.get("post_batch_known_daily_cost_usd")
        != PRE_BATCH_KNOWN_DAILY_COST_USD
    ):
        raise ValueError("Gemini wave03 launch inputs changed")
    return previous, staged


def _manifest_hash(manifest: dict) -> str:
    return base._canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "collection_manifest_sha256"
        }
    )


def build_manifest() -> dict:
    previous, _ = _sealed_inputs()
    for repair in repair_builder.REPAIRS:
        repair_builder.verify(repair)
    quota = json.loads(POST_WAVE_QUOTA_ATTESTATION.read_text())
    with gemini_base._gemini_base():
        shards = [base._build_shard_record(execution) for execution in EXECUTIONS]
    manifest = {
        "schema": "chronos.experiment-a-gemini-remaining-wave03-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "gemini_remaining_wave03_shards_21_29",
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
        "totals": gemini_base._totals(
            shards, PRE_BATCH_KNOWN_DAILY_COST_USD
        ),
        "shards": shards,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Gemini remaining wave03 collection schema")
    if _manifest_hash(manifest) != manifest["collection_manifest_sha256"]:
        raise ValueError("Gemini remaining wave03 self-hash mismatch")
    return manifest


def _verify_repair_attestation(record: dict) -> dict:
    raw = base._read_pinned(
        record, REPAIR_ATTESTATION, "Gemini s26--s29 no-run repair attestation"
    )
    attestation = json.loads(raw)
    body = {
        key: value
        for key, value in attestation.items()
        if key != "attestation_sha256"
    }
    if base._canonical_hash(body) != attestation.get("attestation_sha256"):
        raise ValueError("Gemini wave03 repair attestation self-hash mismatch")
    repairs = attestation.get("repairs") or []
    if (
        attestation.get("schema")
        != "chronos.kaggle-task-version-repair-batch-attestation.v1"
        or [item.get("shard_index") for item in repairs] != [26, 27, 28, 29]
    ):
        raise ValueError("Gemini wave03 repair attestation schema changed")
    for item, repair in zip(repairs, repair_builder.REPAIRS):
        repaired = repair_builder.verify(repair)
        original = repair.original_path.read_bytes()
        before = item.get("task_version_before_repair") or {}
        source = item.get("repair_source") or {}
        expected_error = (
            f"Task 'masihmaafi/{repair.original_task}' exists but has no source kernel."
        )
        if (
            item.get("original_task") != repair.original_task
            or before.get("creationState")
            != "BENCHMARK_TASK_VERSION_CREATION_STATE_UNSPECIFIED"
            or before.get("source")
            != "BENCHMARK_TASK_VERSION_SOURCE_UNSPECIFIED"
            or before.get("sourceKernelId") is not None
            or before.get("runs") != []
            or item.get("model_run_observed") is not False
            or item.get("repair_task") != repair.repair_task
            or source.get("sha256") != base._sha256(repaired)
            or source.get("derived_from_sha256") != base._sha256(original)
            or item.get("scientific_changes") != []
            or item.get("unaccounted_quota_usd") != 0.0
            or item.get("same_slug_repush_attempt", {}).get("error")
            != expected_error
            or item.get("same_slug_repush_attempt", {}).get("run_created")
            is not False
        ):
            raise ValueError(
                f"Gemini s{repair.shard} no-run repair attestation changed"
            )
    return attestation


def _verify_post_wave_quota(record: dict) -> dict:
    raw = base._read_pinned(
        record,
        POST_WAVE_QUOTA_ATTESTATION,
        "Gemini remaining wave03 post-wave quota attestation",
    )
    attestation = json.loads(raw)
    final_execution = EXECUTIONS[-1]
    with gemini_base._gemini_base():
        artifacts = base._artifact_paths(final_execution)
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task")
        != REPAIRS_BY_SHARD[29].repair_task
        or attestation.get("run_context", {}).get("run_id") != RUN_IDS[29]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_KNOWN_DAILY_COST_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Gemini remaining wave03 quota evidence changed")
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
        != "chronos.experiment-a-gemini-remaining-wave03-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "gemini_remaining_wave03_shards_21_29"
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
        or manifest["shard_count"] != 9
        or manifest["job_count"] != 207
        or manifest["planned_calls"] != 699
        or len(repair_attestation["repairs"]) != 4
    ):
        raise ValueError("Gemini remaining wave03 top-level contract changed")

    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Gemini remaining wave03 shard indexes changed")
    with gemini_base._gemini_base():
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
        or len(all_ids) != 207
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 699
    ):
        raise ValueError("Gemini remaining wave03 is not its frozen subset")

    accounts = [item["accounting"] for item in verified]
    actual_totals = gemini_base._totals(
        [{"accounting": item} for item in accounts],
        PRE_BATCH_KNOWN_DAILY_COST_USD,
    )
    base._require_equal(manifest["totals"], actual_totals, "collection totals")
    if (
        actual_totals["completed_jobs"] != 207
        or actual_totals["planned_calls"] != 699
        or actual_totals["observed_invocations"] != 699
        or actual_totals["complete_calls"] != 699
        or actual_totals["failed_calls"] != 0
        or actual_totals["unknown_cost_calls"] != 0
        or actual_totals["invalid_json_lines"] != 0
        or actual_totals["events"] != 1113
        or actual_totals["started_attempts"] != 207
    ):
        raise ValueError("Gemini remaining wave03 accounting topology changed")
    base._require_equal(
        actual_totals["batch_known_cost_usd"],
        BATCH_KNOWN_COST_USD,
        "Gemini remaining wave03 known cost",
    )
    base._require_equal(
        actual_totals["post_batch_known_daily_cost_usd"],
        POST_BATCH_KNOWN_DAILY_COST_USD,
        "Gemini remaining wave03 post-wave known cost",
    )
    return {
        "schema": "chronos.experiment-a-gemini-remaining-wave03-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 9,
        "completed_jobs": actual_totals["completed_jobs"],
        "remaining_jobs": 0,
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
        "PASS Gemini remaining wave03: {completed_jobs}/207 jobs, "
        "{planned_calls} planned calls, {observed_invocations} measured "
        "invocations, {failed_calls} failed calls, ${batch_known_cost_usd:.8f} "
        "batch / ${post_batch_known_daily_cost_usd:.8f} official daily total; "
        "nine shards disjoint and raw-revalidated".format(**checked)
    )


if __name__ == "__main__":
    main()
