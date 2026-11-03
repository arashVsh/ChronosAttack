"""Seal and independently verify Claude-none Experiment A shards 19--27.

Shard 21 required two completed-job projection resumes after structurally
invalid provider responses.  Those rejected tails remain pinned and charged
in raw spend, but are excluded from scientific evidence.  Shard 24 uses a
reversible task-slug repair after Kaggle created a source-less task version.
"""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from functools import lru_cache
import json
import math
from pathlib import Path

import build_experiment_a_claude_none_s21_resume_v1 as s21_resume1
import build_experiment_a_claude_none_s21_resume2_v1 as s21_resume2
import build_experiment_a_claude_none_s24_task_slug_repair_v1 as s24_builder
import capture_benchmark_quota_v1 as quota_capture
import capture_experiment_a_claude_none_s24_task_repair_v1 as s24_capture
import verify_experiment_a_claude_none_batch00_collection as shard_base
import verify_experiment_a_claude_none_batch05_collection as previous_collection
import verify_experiment_a_claude_none_batch06 as staged_batch
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch06"
MANIFEST = GENERATED / "experiment_a_claude_none_batch06_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_claude_none_batch06_tasks_v1.json"
S24_REPAIR_ATTESTATION = RUNS / "s24_version1_no_run_attestation_v1.json"
S21_RESUME_ATTESTATIONS = (
    RUNS / "s21_invalid_response_resume_attestation_v1.json",
    RUNS / "s21_invalid_response_resume2_attestation_v1.json",
)
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_claude_none_batch06_20260922_v1.json"
)

MODEL = staged_batch.base.MODEL
REASONING = staged_batch.base.REASONING
ROLE = staged_batch.base.ROLE
STUDY_ID = staged_batch.base.STUDY_ID
FROZEN_AT = "2026-09-22T15:03:46.346592+00:00"
SHARDS = staged_batch.SHARDS
RUN_IDS = {
    19: 2779922,
    20: 2779923,
    21: 2780402,
    22: 2779932,
    23: 2779933,
    24: 2780153,
    25: 2779985,
    26: 2779984,
    27: 2779983,
}

PRE_BATCH_RAW_KNOWN_DAILY_USD = 0.0
PRE_BATCH_OFFICIAL_DAILY_USD = 0.0
SCIENTIFIC_KNOWN_COST_USD = 3.1788444
EXCLUDED_TAIL_KNOWN_COST_USD = 0.030006
BATCH_KNOWN_COST_USD = 3.2088504
POST_BATCH_RAW_KNOWN_DAILY_USD = 3.2088504
POST_BATCH_OFFICIAL_DAILY_USD = 3.2088504
OFFICIAL_QUOTA_DELTA_USD = 3.2088504
POST_OFFICIAL_MINUS_RAW_KNOWN_USD = 0.0

PRELAUNCH_MANIFEST_SHA256 = (
    "8a233ab26f9833514c72f94289eb8bdd85283d984396a35060bf6ec35fe113ba"
)
S24_REPAIR_ATTESTATION_SHA256 = (
    "52a6acbcd87fdffc16b4388233dd2262751a667ca2492884de2ea5dfe3ee057f"
)
S21_RESUME_ATTESTATION_SHA256 = (
    "67cf7eddae5ed60a5d1b1c49362eac64ac7ef39ff5089ce90617d3ede0abac9d",
    "cbdb6eaf6d13b3951103e7d502027a7dcdd9030b21d795afbad06b7469850a34",
)


def _canonical_task(index: int) -> str:
    return f"chronos-r2-water4-study-claude-none-s{index:02d}-v1"


def _output_folder(index: int) -> str:
    return f"round2_water4_study_claude_none_s{index:02d}_v1"


def _execution(index: int) -> dict:
    canonical = _canonical_task(index)
    if index == 21:
        task = s21_resume2.RESUME_TASK
        source = s21_resume2.SOURCE
        wrapper = s21_resume2.WRAPPER
        run_folder = "s21_resume2"
        kind = "completed_projection_resume_after_two_invalid_responses"
        recovery = s21_resume2
    elif index == 24:
        task = s24_builder.REPAIR_TASK
        source = s24_builder.REPAIR
        wrapper = s24_builder.WRAPPER
        run_folder = "s24_repair"
        kind = "task_slug_repair_after_no_source_kernel"
        recovery = None
    else:
        task = canonical
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
        / shard_base.MODEL_SLUG
        / str(RUN_IDS[index])
    )
    output = _output_folder(index)
    return {
        "shard_index": index,
        "execution_kind": kind,
        "task": task,
        "canonical_task": canonical,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": output,
        "output_root": root / output,
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
    "s24_repair_attestation",
    "s21_resume_attestations",
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


@contextmanager
def _s24_regeneration():
    """Teach the frozen generic verifier about the reversible s24 slug repair."""
    original = shard_base._regenerated_source

    def regenerated(index: int) -> str:
        if index == 24:
            return s24_builder.build_source()
        return original(index)

    shard_base._regenerated_source = regenerated
    try:
        yield
    finally:
        shard_base._regenerated_source = original


def _verify_s24_attestation(record: dict) -> dict:
    raw = evidence_base._read_pinned(
        record,
        S24_REPAIR_ATTESTATION,
        "Claude batch06 s24 repair attestation",
    )
    attestation = json.loads(raw)
    body = {
        key: value
        for key, value in attestation.items()
        if key != "attestation_sha256"
    }
    repairs = attestation.get("repairs") or []
    if (
        attestation.get("attestation_sha256")
        != s24_capture._sha256(s24_capture._canonical(body))
        or attestation.get("attestation_sha256")
        != S24_REPAIR_ATTESTATION_SHA256
        or attestation.get("prelaunch_manifest_sha256")
        != PRELAUNCH_MANIFEST_SHA256
        or len(repairs) != 1
    ):
        raise ValueError("Claude batch06 s24 repair attestation changed")
    repair = repairs[0]
    version = repair.get("task_version_before_repair") or {}
    repaired, wrapper = s24_builder.verify_sources()
    source_record = evidence_base._file_record(s24_builder.REPAIR)
    wrapper_record = evidence_base._file_record(s24_builder.WRAPPER)
    if (
        repair.get("shard_index") != 24
        or repair.get("original_task") != s24_builder.ORIGINAL_TASK
        or repair.get("repair_task") != s24_builder.REPAIR_TASK
        or repair.get("model_run_observed") is not False
        or repair.get("scientific_changes") != []
        or repair.get("unaccounted_quota_usd") != 0.0
        or repair.get("same_slug_repush_attempt", {}).get("run_created")
        is not False
        or version.get("creationState")
        != "BENCHMARK_TASK_VERSION_CREATION_STATE_UNSPECIFIED"
        or version.get("source")
        != "BENCHMARK_TASK_VERSION_SOURCE_UNSPECIFIED"
        or version.get("sourceKernelId") is not None
        or version.get("runs") != []
        or any(
            repair.get("repair_source", {}).get(key) != value
            for key, value in source_record.items()
        )
        or any(
            repair.get("transport_wrapper", {}).get(key) != value
            for key, value in wrapper_record.items()
        )
        or repair.get("repair_source", {}).get("derived_from_sha256")
        != s24_builder.ORIGINAL_SHA256
        or repair.get("transport_wrapper", {}).get(
            "decompressed_payload_sha256"
        )
        != s24_builder.REPAIR_SHA256
        or s24_builder._sha256(repaired) != s24_builder.REPAIR_SHA256
        or s24_builder._sha256(wrapper) != wrapper_record["sha256"]
    ):
        raise ValueError("Claude batch06 s24 no-run repair changed")
    return attestation


def _verify_s21_attestations(records: list[dict]) -> list[dict]:
    if len(records) != 2:
        raise ValueError("Claude batch06 requires exactly two s21 resumes")
    builders = (s21_resume1, s21_resume2)
    values = []
    for number, (record, path, builder, expected_hash) in enumerate(
        zip(
            records,
            S21_RESUME_ATTESTATIONS,
            builders,
            S21_RESUME_ATTESTATION_SHA256,
        ),
        start=1,
    ):
        raw = evidence_base._read_pinned(
            record, path, f"Claude batch06 s21 resume{number} attestation"
        )
        value = builder.verify(json.loads(raw))
        tail = value.get("resume_projection", {}).get(
            "excluded_incomplete_tail", {}
        )
        if (
            value.get("attestation_sha256") != expected_hash
            or tail.get("counted_in_total_accounting") is not True
            or tail.get("retained_in_raw_archive") is not True
            or tail.get("treated_as_valid_scientific_evidence") is not False
            or tail.get("failure") != "ValueError: Missing explanation"
            or value.get("resume_execution", {}).get(
                "scientific_parameter_changes"
            )
            != []
        ):
            raise ValueError(f"Claude batch06 s21 resume{number} changed")
        values.append(value)
    first_seed = values[0]["resume_projection"]["seed"]["sha256"]
    second_original_parent = s21_resume2.EXPECTED_PARENT_LEDGER_SHA256
    if (
        first_seed != second_original_parent
        or values[1]["original_execution"]["task"]
        != values[0]["resume_execution"]["task"]
        or values[1]["original_execution"]["run_id"] != s21_resume2.RUN_ID
        or values[0]["resume_projection"]["excluded_incomplete_tail"]["job_id"]
        == values[1]["resume_projection"]["excluded_incomplete_tail"]["job_id"]
    ):
        raise ValueError("Claude batch06 s21 resume chain changed")
    return values


def _verify_quota(record: dict) -> dict:
    raw = evidence_base._read_pinned(
        record,
        POST_BATCH_QUOTA_ATTESTATION,
        "Claude batch06 post-batch quota attestation",
    )
    attestation = json.loads(raw)
    execution = next(item for item in EXECUTIONS if item["shard_index"] == 21)
    artifacts = shard_base._artifact_paths(execution)
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task")
        != s21_resume2.RESUME_TASK
        or attestation.get("run_context", {}).get("run_id") != RUN_IDS[21]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_OFFICIAL_DAILY_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Claude batch06 quota evidence changed")
    return attestation


def _totals(shards: list[dict], resumes: list[dict]) -> dict:
    accounts = [shard["accounting"] for shard in shards]
    tails = [
        value["resume_projection"]["excluded_incomplete_tail"]
        for value in resumes
    ]
    scientific_cost = round(
        math.fsum(item["known_cost_usd"] for item in accounts), 12
    )
    tail_cost = round(math.fsum(item["known_cost_usd"] for item in tails), 12)
    batch_cost = round(scientific_cost + tail_cost, 12)
    scientific = {
        "completed_jobs": sum(item["completed_jobs"] for item in accounts),
        "planned_calls": sum(item["planned_calls"] for item in accounts),
        "observed_invocations": sum(
            item["observed_invocations"] for item in accounts
        ),
        "complete_calls": sum(item["complete_calls"] for item in accounts),
        "failed_calls": sum(item["failed_calls"] for item in accounts),
        "unknown_cost_calls": sum(
            item["unknown_cost_calls"] for item in accounts
        ),
        "invalid_json_lines": sum(
            item["invalid_json_lines"] for item in accounts
        ),
        "events": sum(item["events"] for item in accounts),
        "started_attempts": sum(item["started_attempts"] for item in accounts),
    }
    tail_events = sum(item["events"] for item in tails)
    tail_invocations = sum(item["observed_invocations"] for item in tails)
    official_delta = round(
        POST_BATCH_OFFICIAL_DAILY_USD - PRE_BATCH_OFFICIAL_DAILY_USD, 12
    )
    return {
        **scientific,
        "scientific_known_cost_usd": scientific_cost,
        "excluded_tail_count": len(tails),
        "excluded_tail_events": tail_events,
        "excluded_tail_started_attempts": len(tails),
        "excluded_tail_observed_invocations": tail_invocations,
        "excluded_tail_complete_calls": tail_invocations,
        "excluded_tail_failed_calls": 0,
        "excluded_tail_known_cost_usd": tail_cost,
        "raw_events_including_excluded_tails": scientific["events"] + tail_events,
        "raw_started_attempts_including_excluded_tails": (
            scientific["started_attempts"] + len(tails)
        ),
        "raw_observed_invocations_including_excluded_tails": (
            scientific["observed_invocations"] + tail_invocations
        ),
        "raw_complete_calls_including_excluded_tails": (
            scientific["complete_calls"] + tail_invocations
        ),
        "raw_failed_calls_including_excluded_tails": scientific["failed_calls"],
        "batch_known_cost_usd": batch_cost,
        "pre_batch_raw_known_daily_cost_usd": PRE_BATCH_RAW_KNOWN_DAILY_USD,
        "pre_batch_official_daily_quota_used_usd": PRE_BATCH_OFFICIAL_DAILY_USD,
        "post_batch_raw_known_daily_cost_usd": round(
            PRE_BATCH_RAW_KNOWN_DAILY_USD + batch_cost, 12
        ),
        "post_batch_official_daily_quota_used_usd": POST_BATCH_OFFICIAL_DAILY_USD,
        "official_quota_delta_usd": official_delta,
        "official_delta_minus_batch_known_usd": round(
            official_delta - batch_cost, 12
        ),
        "post_official_minus_raw_known_usd": round(
            POST_BATCH_OFFICIAL_DAILY_USD
            - (PRE_BATCH_RAW_KNOWN_DAILY_USD + batch_cost),
            12,
        ),
    }


def build_manifest() -> dict:
    previous = _previous()
    staged = staged_batch._load()
    s24_record = evidence_base._file_record(S24_REPAIR_ATTESTATION)
    resume_records = [
        evidence_base._file_record(path) for path in S21_RESUME_ATTESTATIONS
    ]
    _verify_s24_attestation(s24_record)
    resumes = _verify_s21_attestations(resume_records)
    quota = json.loads(POST_BATCH_QUOTA_ATTESTATION.read_text())
    shards = [shard_base._build_shard_record(execution) for execution in EXECUTIONS]
    if staged.get("batch_manifest_sha256") != PRELAUNCH_MANIFEST_SHA256:
        raise ValueError("Claude batch06 prelaunch manifest changed")
    manifest = {
        "schema": "chronos.experiment-a-claude-none-batch06-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "claude_none_batch06_shards_19_27",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "previous_collection_manifest_sha256": previous[
            "collection_manifest_sha256"
        ],
        "prelaunch_manifest": evidence_base._file_record(PRELAUNCH_MANIFEST),
        "s24_repair_attestation": s24_record,
        "s21_resume_attestations": resume_records,
        "post_batch_quota_attestation": evidence_base._file_record(
            POST_BATCH_QUOTA_ATTESTATION
        ),
        "post_batch_quota_attestation_sha256": quota["attestation_sha256"],
        "shard_count": len(shards),
        "job_count": sum(shard["accounting"]["job_count"] for shard in shards),
        "planned_calls": sum(
            shard["accounting"]["planned_calls"] for shard in shards
        ),
        "totals": _totals(shards, resumes),
        "shards": shards,
    }
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Claude batch06 collection schema")
    if manifest.get("collection_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Claude batch06 collection self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    previous = _previous()
    staged = staged_batch._load()
    evidence_base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Claude batch06 prelaunch manifest",
    )
    _verify_s24_attestation(manifest["s24_repair_attestation"])
    resumes = _verify_s21_attestations(manifest["s21_resume_attestations"])
    quota = _verify_quota(manifest["post_batch_quota_attestation"])
    if (
        manifest["schema"]
        != "chronos.experiment-a-claude-none-batch06-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "claude_none_batch06_shards_19_27"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or manifest["previous_collection_manifest_sha256"]
        != previous["collection_manifest_sha256"]
        or staged.get("batch_manifest_sha256") != PRELAUNCH_MANIFEST_SHA256
        or manifest["post_batch_quota_attestation_sha256"]
        != quota["attestation_sha256"]
        or manifest["shard_count"] != 9
        or manifest["job_count"] != 207
        or manifest["planned_calls"] != 679
    ):
        raise ValueError("Claude batch06 top-level contract changed")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Claude batch06 shard indexes changed")
    with _s24_regeneration():
        verified = [
            shard_base._verify_shard(execution, record)
            for execution, record in zip(EXECUTIONS, records)
        ]
    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous_runtime = shard_base._runtime()
    try:
        full_jobs = shard_base.protocol.jobs_for(MODEL, "study")
        expected = [
            job
            for index in SHARDS
            for job in shard_base.select_shard(
                full_jobs,
                shard_index=index,
                shard_count=shard_base.cell_builder.SHARD_COUNT,
            )
        ]
    finally:
        shard_base._restore_runtime(previous_runtime)
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != 207
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 679
    ):
        raise ValueError("Claude batch06 is not its deterministic disjoint subset")
    totals = _totals(
        [{"accounting": item["accounting"]} for item in verified], resumes
    )
    evidence_base._require_equal(manifest["totals"], totals, "collection totals")
    fixed = {
        "completed_jobs": 207,
        "planned_calls": 679,
        "observed_invocations": 692,
        "complete_calls": 688,
        "failed_calls": 4,
        "unknown_cost_calls": 0,
        "invalid_json_lines": 0,
        "events": 1114,
        "started_attempts": 211,
        "excluded_tail_count": 2,
        "excluded_tail_events": 11,
        "excluded_tail_started_attempts": 2,
        "excluded_tail_observed_invocations": 7,
        "excluded_tail_complete_calls": 7,
        "excluded_tail_failed_calls": 0,
        "raw_events_including_excluded_tails": 1125,
        "raw_started_attempts_including_excluded_tails": 213,
        "raw_observed_invocations_including_excluded_tails": 699,
        "raw_complete_calls_including_excluded_tails": 695,
        "raw_failed_calls_including_excluded_tails": 4,
    }
    if any(totals[key] != expected_value for key, expected_value in fixed.items()):
        raise ValueError("Claude batch06 accounting topology changed")
    for key, expected_value in (
        ("scientific_known_cost_usd", SCIENTIFIC_KNOWN_COST_USD),
        ("excluded_tail_known_cost_usd", EXCLUDED_TAIL_KNOWN_COST_USD),
        ("batch_known_cost_usd", BATCH_KNOWN_COST_USD),
        ("post_batch_raw_known_daily_cost_usd", POST_BATCH_RAW_KNOWN_DAILY_USD),
        ("official_quota_delta_usd", OFFICIAL_QUOTA_DELTA_USD),
        ("official_delta_minus_batch_known_usd", 0.0),
        ("post_official_minus_raw_known_usd", POST_OFFICIAL_MINUS_RAW_KNOWN_USD),
    ):
        if not math.isclose(
            totals[key], expected_value, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(f"Claude batch06 cost changed: {key}")
    return {
        "schema": "chronos.experiment-a-claude-none-batch06-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 9,
        "completed_jobs": totals["completed_jobs"],
        "remaining_jobs": previous["remaining_jobs"] - totals["completed_jobs"],
        "planned_calls": totals["planned_calls"],
        "observed_invocations": totals["observed_invocations"],
        "raw_observed_invocations": totals[
            "raw_observed_invocations_including_excluded_tails"
        ],
        "failed_calls": totals["failed_calls"],
        "unknown_cost_calls": totals["unknown_cost_calls"],
        "scientific_known_cost_usd": totals["scientific_known_cost_usd"],
        "excluded_tail_known_cost_usd": totals["excluded_tail_known_cost_usd"],
        "batch_known_cost_usd": totals["batch_known_cost_usd"],
        "post_batch_official_daily_quota_used_usd": totals[
            "post_batch_official_daily_quota_used_usd"
        ],
        "post_official_minus_raw_known_usd": totals[
            "post_official_minus_raw_known_usd"
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
        "PASS Claude-none batch06: {completed_jobs}/207 jobs, "
        "{planned_calls} planned / {observed_invocations} scientific / "
        "{raw_observed_invocations} raw calls, {failed_calls} failed calls, "
        "${scientific_known_cost_usd:.7f} scientific + "
        "${excluded_tail_known_cost_usd:.7f} rejected tails = "
        "${batch_known_cost_usd:.7f}; ${post_batch_official_daily_quota_used_usd:.7f} "
        "official daily used; nine shards disjoint and raw-revalidated".format(
            **checked
        )
    )


if __name__ == "__main__":
    main()
