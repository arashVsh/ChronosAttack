"""Seal and independently verify Claude-none Experiment A shards 00--06.

The collection distinguishes scientific ledgers from complete spend evidence.
Shard 03 resumed from an exact completed-job projection after one incomplete
attempt contained a paid but structurally invalid response.  That six-event
tail is excluded from scientific evidence but retained in raw accounting.
Several oversized sources used hash-checking transport wrappers; the verifier
checks both the downloaded wrapper notebook and its byte-exact payload.
"""

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

import audit_water_supply as water_audit
import build_experiment_a_cell_v1 as cell_builder
import build_experiment_a_claude_none_s03_resume_v1 as resume_builder
import build_experiment_a_claude_none_s06_task_slug_repair_v1 as s06_builder
import build_experiment_a_claude_none_transport_wrappers_v1 as transport_builder
import capture_benchmark_quota_v1 as quota_capture
from round2_hosted import (
    raw_event_summary,
    select_shard,
    subset_summary,
    validate_resume_ledger,
)
import verify_experiment_a_claude_none_batch00 as staged_batch
import verify_experiment_a_qwen_batch00_collection as base
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch00"
MANIFEST = GENERATED / "experiment_a_claude_none_batch00_collection_v1.json"
PRELAUNCH_MANIFEST = GENERATED / "experiment_a_claude_none_batch00_tasks_v1.json"
TRANSPORT_ATTESTATION = RUNS / "transport_wrappers_s00_s01_s03_s06_v1.json"
S06_REPAIR_ATTESTATION = RUNS / "s06_version1_no_run_attestation_v1.json"
S03_RESUME_ATTESTATION = RUNS / "s03_invalid_response_resume_attestation_v1.json"
POST_BATCH_QUOTA_ATTESTATION = (
    RUNS / "quota_after_claude_none_batch00_20260921_v1.json"
)

MODEL = "anthropic/claude-sonnet-4-6@default"
MODEL_SLUG = "claude-sonnet-4-6-default"
MODEL_METADATA_FILE_SLUG = "anthropic_claude-sonnet-4-6default"
MODEL_FILE = "anthropic_claude-sonnet-4-6@default.jsonl"
REASONING = "none"
ROLE = "reasoning_off_sensitivity"
STUDY_ID = "chronos_round2_water4_study_claude_none_v1"
FROZEN_AT = "2026-09-21T20:27:39.808217+00:00"
SHARDS = tuple(range(7))
RUN_IDS = {
    0: 2728696,
    1: 2728627,
    2: 2725014,
    3: 2731442,
    4: 2728861,
    5: 2728797,
    6: 2730220,
}

PRE_BATCH_OFFICIAL_DAILY_USD = 1.7228055
POST_BATCH_OFFICIAL_DAILY_USD = 4.4540901
SCIENTIFIC_KNOWN_COST_USD = 2.3839599
EXCLUDED_TAIL_KNOWN_COST_USD = 0.0138234
BATCH_KNOWN_COST_USD = 2.3977833
POST_BATCH_KNOWN_DAILY_USD = 4.1205888
OFFICIAL_QUOTA_DELTA_USD = 2.7312846
UNATTRIBUTED_OFFICIAL_DELTA_USD = 0.3335013


def _canonical_task(index: int) -> str:
    return f"chronos-r2-water4-study-claude-none-s{index:02d}-v1"


def _output_folder(index: int) -> str:
    return f"round2_water4_study_claude_none_s{index:02d}_v1"


def _canonical_source(index: int) -> Path:
    return GENERATED / f"water4_study_claude_none_s{index:02d}_v1.py"


def _execution(index: int) -> dict:
    canonical_task = _canonical_task(index)
    output = _output_folder(index)
    if index == 3:
        task = resume_builder.RESUME_TASK
        source = resume_builder.SOURCE
        wrapper = resume_builder.WRAPPER
        run_folder = "s03_resume"
        kind = "completed_projection_resume_after_invalid_response"
        recovery_builder = resume_builder
    elif index == 6:
        task = s06_builder.REPAIR_TASK
        source = s06_builder.REPAIR
        wrapper = s06_builder.WRAPPER
        run_folder = "s06"
        kind = "task_slug_repair_after_no_source_kernel"
        recovery_builder = None
    else:
        task = canonical_task
        source = _canonical_source(index)
        wrapper = (
            None
            if index == 2
            else GENERATED
            / f"water4_study_claude_none_s{index:02d}_transport_v1.py"
        )
        run_folder = f"s{index:02d}"
        kind = "baseline"
        recovery_builder = None
    root = (
        RUNS
        / run_folder
        / task
        / "1"
        / MODEL_SLUG
        / str(RUN_IDS[index])
    )
    return {
        "shard_index": index,
        "execution_kind": kind,
        "task": task,
        "canonical_task": canonical_task,
        "run_id": RUN_IDS[index],
        "run_root": root,
        "output_folder": output,
        "output_root": root / output,
        "source": source,
        "transport_source": wrapper,
        "recovery_builder": recovery_builder,
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
    "prelaunch_manifest",
    "transport_attestation",
    "s06_repair_attestation",
    "s03_resume_attestation",
    "post_batch_quota_attestation",
    "post_batch_quota_attestation_sha256",
    "shard_count",
    "job_count",
    "planned_calls",
    "totals",
    "shards",
}
SHARD_KEYS = {
    "shard_index",
    "execution_kind",
    "task",
    "task_version",
    "run_id",
    "model",
    "started_at",
    "finished_at",
    "status",
    "source",
    "transport_source",
    "artifacts",
    "accounting",
    "hosted_audit_passed",
}


def _manifest_hash(value: dict) -> str:
    return base._canonical_hash(
        {
            key: item
            for key, item in value.items()
            if key != "collection_manifest_sha256"
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


def _runtime():
    previous = (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    )
    protocol.engine.MODELS = tuple(dict.fromkeys((*protocol.engine.MODELS, MODEL)))
    protocol.engine.STUDY_ID = STUDY_ID
    protocol.engine.CALL_SETTINGS = {
        "temperature": 1,
        "reasoning": REASONING,
        "max_completion_tokens": 256,
        "timeout": 30,
    }
    return previous


def _restore_runtime(previous) -> None:
    (
        protocol.engine.MODELS,
        protocol.engine.STUDY_ID,
        protocol.engine.CALL_SETTINGS,
    ) = previous


def _jobs_for_shard(index: int) -> tuple[list[dict], list[dict]]:
    previous = _runtime()
    try:
        full = protocol.jobs_for(MODEL, "study")
        jobs = select_shard(
            full,
            shard_index=index,
            shard_count=cell_builder.SHARD_COUNT,
        )
    finally:
        _restore_runtime(previous)
    return full, jobs


def _artifact_paths(execution: dict) -> dict[str, Path]:
    task = execution["task"]
    root = execution["run_root"]
    output = execution["output_root"]
    prefix = f"{task}-run_id_Run_1_{MODEL_METADATA_FILE_SLUG}"
    return {
        "notebook": root / "__notebook__.ipynb",
        "task": root / f"{task}.task.json",
        "run": root / f"{prefix}.run.json",
        "result": root / f"{prefix}.result.json",
        "atif": root / f"{prefix}.atif.json",
        "intended_manifest": output / "intended_manifest.json",
        "terminal": output / "terminal.json",
        "audit": output / "audit.json",
        "evidence": output / MODEL_FILE,
    }


def _accounting(jobs: list[dict], summary: dict) -> dict:
    return {
        "job_count": len(jobs),
        "planned_calls": sum(job["calls"] for job in jobs),
        **{
            key: round(value, 12) if key == "known_cost_usd" else value
            for key, value in summary.items()
        },
    }


def _build_shard_record(execution: dict) -> dict:
    source = execution["source"].read_text()
    jobs = _assignments(source, execution["source"])["EXPECTED_JOBS"]
    artifacts = _artifact_paths(execution)
    events = [json.loads(line) for line in artifacts["evidence"].read_bytes().splitlines()]
    summary = raw_event_summary(events)
    result = json.loads(artifacts["result"].read_text())
    audit = json.loads(artifacts["audit"].read_text())
    transport = execution["transport_source"]
    return {
        "shard_index": execution["shard_index"],
        "execution_kind": execution["execution_kind"],
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "started_at": result["started_at"],
        "finished_at": result["finished_at"],
        "status": "complete_strictly_verified",
        "source": base._file_record(execution["source"]),
        "transport_source": (
            base._file_record(transport) if transport is not None else None
        ),
        "artifacts": {
            label: base._file_record(path) for label, path in artifacts.items()
        },
        "accounting": _accounting(jobs, summary),
        "hosted_audit_passed": audit.get("passed"),
    }


def _verify_transport(execution: dict, source: str) -> str:
    transport = execution["transport_source"]
    if transport is None:
        return source
    wrapper = transport.read_text()
    values = _assignments(wrapper, transport)
    payload = zlib.decompress(
        base64.b85decode(values["_TRANSPORT_PAYLOAD_B85"])
    )
    if (
        payload != source.encode()
        or values["_TRANSPORT_PAYLOAD_SHA256"] != base._sha256(payload)
    ):
        raise ValueError(
            f"Claude s{execution['shard_index']:02d} transport payload changed"
        )
    compile(wrapper, str(transport), "exec")
    return wrapper


@lru_cache(maxsize=None)
def _regenerated_source(index: int) -> str:
    task = _canonical_task(index)
    return cell_builder.build_source(
        model=MODEL,
        reasoning=REASONING,
        role=ROLE,
        study_id=STUDY_ID,
        shard_index=index,
        task_name=task,
        output_folder=_output_folder(index),
    )


def _verify_source(execution: dict, source: str, values: dict) -> None:
    index = execution["shard_index"]
    recovery = execution.get("recovery_builder")
    if recovery is not None:
        recovery.verify()
        if source != recovery.build_source():
            raise ValueError(f"Claude s{index:02d} resume source changed")
    else:
        canonical = _regenerated_source(index)
        if index == 6:
            expected = canonical.replace(
                _canonical_task(index), execution["task"], 1
            )
            if source != expected or expected.replace(
                execution["task"], _canonical_task(index), 1
            ) != canonical:
                raise ValueError("Claude s06 repair changed scientific source")
        elif source != canonical:
            raise ValueError(f"Claude s{index:02d} source is not regenerated")

    required = {
        "CONTRACT",
        "EXPECTED_JOBS",
        "RESUME_LEDGER",
        "MODEL",
        "REASONING",
        "ROLE",
        "STUDY_ID",
        "OUTPUT_FOLDER",
        "CEILING_USD",
        "MAX_WAIT_SECONDS",
    }
    if not required <= set(values):
        raise ValueError(f"Claude s{index:02d} source assignments incomplete")
    contract = values["CONTRACT"]
    _, jobs = _jobs_for_shard(index)
    if (
        values["MODEL"] != MODEL
        or values["REASONING"] != REASONING
        or values["ROLE"] != ROLE
        or values["STUDY_ID"] != STUDY_ID
        or values["OUTPUT_FOLDER"] != _output_folder(index)
        or values["MAX_WAIT_SECONDS"] != 7200
        or contract["model"] != MODEL
        or contract["reasoning"] != REASONING
        or contract["role"] != ROLE
        or contract["study_id"] != STUDY_ID
        or contract["shard_index"] != index
        or contract["shard_count"] != 30
        or contract["job_count"] != 23
        or values["EXPECTED_JOBS"] != jobs
    ):
        raise ValueError(f"Claude s{index:02d} source contract changed")
    if recovery is not None:
        seed = recovery.SEED.read_bytes()
        expected_seed = recovery.SEED_SUMMARY
        expected_ceiling = (
            expected_seed["known_cost_usd"]
            + cell_builder.INCREMENTAL_CEILINGS_USD[(MODEL, REASONING)]
        )
        if (
            values["RESUME_LEDGER"] != seed
            or contract["parent_ledger_sha256"] != base._sha256(seed)
            or contract["resume_ledger"]["completed_jobs"]
            != expected_seed["completed_jobs"]
            or contract["resume_ledger"]["events"] != expected_seed["events"]
            or not math.isclose(
                contract["resume_ledger"]["known_cost_usd"],
                expected_seed["known_cost_usd"],
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                values["CEILING_USD"],
                expected_ceiling,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(f"Claude s{index:02d} resume contract changed")
    elif (
        values["RESUME_LEDGER"] != b""
        or contract["parent_ledger_sha256"] is not None
        or contract["resume_ledger"]["events"] != 0
        or values["CEILING_USD"] != 1.09
    ):
        raise ValueError(f"Claude s{index:02d} baseline resume contract changed")
    compile(source, str(execution["source"]), "exec")


def _verify_metadata(
    execution: dict,
    record: dict,
    source: str,
    notebook_source: str,
    blobs: dict[str, bytes],
) -> None:
    task = base._json(blobs["task"], "task metadata")
    run = base._json(blobs["run"], "run metadata")
    result = base._json(blobs["result"], "result metadata")
    atif = base._json(blobs["atif"], "ATIF metadata")
    notebook = base._json(blobs["notebook"], "downloaded notebook")
    name = execution["task"]
    definition = base._uploaded_definition(source, name)
    wrapped = execution["transport_source"] is not None
    expected_task = {"versionNumber": 1, "name": name}
    if not wrapped:
        expected_task["definition"] = definition
    if task != expected_task:
        raise ValueError("downloaded task metadata changed")
    cells = notebook.get("cells")
    observed_notebook = (
        "".join(cells[0].get("source", []))
        if isinstance(cells, list) and len(cells) == 1
        else None
    )
    normalized = (
        notebook_source[:-1] if notebook_source.endswith("\n") else notebook_source
    )
    if (
        not isinstance(cells, list)
        or len(cells) != 1
        or cells[0].get("cell_type") != "code"
        or observed_notebook != normalized
    ):
        raise ValueError("downloaded notebook transport source changed")

    run_task = run.get("taskVersion") or {}
    expected_run_task = {"versionNumber", "name", "description"}
    expected_atif_task = {"version_number", "name", "description"}
    if not wrapped:
        expected_run_task.add("definition")
        expected_atif_task.add("definition")
    if (
        set(run_task) != expected_run_task
        or run_task.get("versionNumber") != 1
        or run_task.get("name") != name
        or run_task.get("description") != ""
        or (not wrapped and run_task.get("definition") != definition)
        or run.get("modelVersion", {}).get("slug") != MODEL
        or run.get("pyRunId") != f"{name}-Run #1"
        or run.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or run.get("startTime") != record["started_at"]
        or run.get("endTime") != record["finished_at"]
    ):
        raise ValueError("downloaded run metadata changed")
    if (
        result.get("task_name") != name
        or result.get("trial_name") != f"{name}-Run #1"
        or result.get("started_at") != record["started_at"]
        or result.get("finished_at") != record["finished_at"]
        or result.get("agent_info", {}).get("model_info", {}).get("name")
        != MODEL
        or result.get("verifier_result", {}).get("rewards", {}).get("score")
        != 1.0
    ):
        raise ValueError("downloaded result metadata changed")
    kbench = atif.get("extra", {}).get("kbench", {})
    atif_task = kbench.get("task_version", {})
    if (
        set(atif_task) != expected_atif_task
        or atif.get("schema_version") != "ATIF-v1.7"
        or atif.get("session_id") != f"{name}-Run #1"
        or atif.get("trajectory_id") != f"{name}-Run #1"
        or atif.get("agent", {}).get("model_name") != MODEL
        or atif_task.get("version_number") != 1
        or atif_task.get("name") != name
        or atif_task.get("description") != ""
        or (not wrapped and atif_task.get("definition") != definition)
        or kbench.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED"
        or kbench.get("end_time") != record["finished_at"]
    ):
        raise ValueError("downloaded ATIF metadata changed")


def _verify_shard(execution: dict, record: dict) -> dict:
    index = execution["shard_index"]
    if set(record) != SHARD_KEYS or set(record["accounting"]) != base.ACCOUNTING_KEYS:
        raise ValueError(f"invalid Claude s{index:02d} record schema")
    expected_identity = {
        "shard_index": index,
        "execution_kind": execution["execution_kind"],
        "task": execution["task"],
        "task_version": 1,
        "run_id": execution["run_id"],
        "model": MODEL,
        "status": "complete_strictly_verified",
        "hosted_audit_passed": True,
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise ValueError(f"Claude s{index:02d} execution identity changed")
    source_raw = base._read_pinned(
        record["source"], execution["source"], f"Claude s{index:02d} source"
    )
    source = source_raw.decode()
    values = _assignments(source, execution["source"])
    _verify_source(execution, source, values)
    notebook_source = _verify_transport(execution, source)
    transport = execution["transport_source"]
    if transport is None:
        if record["transport_source"] is not None:
            raise ValueError(f"Claude s{index:02d} unexpected transport record")
    else:
        base._read_pinned(
            record["transport_source"],
            transport,
            f"Claude s{index:02d} transport source",
        )

    jobs = values["EXPECTED_JOBS"]
    contract = values["CONTRACT"]
    artifacts = _artifact_paths(execution)
    if set(record["artifacts"]) != set(artifacts):
        raise ValueError(f"Claude s{index:02d} artifact set changed")
    blobs = {
        label: base._read_pinned(
            record["artifacts"][label], path, f"Claude s{index:02d} {label}"
        )
        for label, path in artifacts.items()
    }
    result = base._json(blobs["result"], "result metadata")
    if (
        record["started_at"] != result.get("started_at")
        or record["finished_at"] != result.get("finished_at")
    ):
        raise ValueError(f"Claude s{index:02d} timestamps changed")
    intended = base._json(blobs["intended_manifest"], "intended manifest")
    base._require_equal(
        intended,
        dict(contract, jobs=jobs, seed_audit=contract["resume_ledger"]),
        "downloaded intended manifest",
    )

    evidence = blobs["evidence"]
    if not evidence.endswith(b"\n"):
        raise ValueError(f"Claude s{index:02d} evidence is not newline terminated")
    events = [json.loads(line) for line in evidence.splitlines()]
    summary = raw_event_summary(events)
    previous = _runtime()
    try:
        identity = cell_builder._identity(STUDY_ID, MODEL, protocol.fixtures())

        def structural(candidate: list[dict]) -> dict:
            return water_audit.audit(candidate, MODEL, "study", require_complete=False)

        ledger = validate_resume_ledger(
            events,
            model=MODEL,
            identity=identity,
            expected_jobs={job["id"]: job for job in jobs},
            structural_audit=structural,
        )
        strict = structural(events)
        subset = subset_summary(events, {job["id"] for job in jobs})
        full_jobs = protocol.jobs_for(MODEL, "study")
    finally:
        _restore_runtime(previous)
    shard_ids = {job["id"] for job in jobs}
    full_ids = {job["id"] for job in full_jobs}
    if (
        ledger["completed_jobs"] != 23
        or ledger["incomplete_jobs"]
        or subset["complete"] is not True
        or subset["completed_jobs"] != 23
        or subset["missing_job_ids"]
        or subset["unknown_cost_calls"] != 0
        or strict["complete"] is not False
        or strict["completed_jobs"] != 23
        or strict["unknown_cost_calls"] != 0
        or set(strict["missing_jobs"]) != full_ids - shard_ids
        or len(strict["missing_jobs"]) != 667
        or strict["attempted_calls"] != summary["observed_invocations"]
        or summary["accounting_complete"] is not True
        or summary["completed_jobs"] != 23
        or summary["unknown_cost_calls"] != 0
        or summary["invalid_json_lines"] != 0
    ):
        raise ValueError(f"Claude s{index:02d} strict raw-ledger audit failed")
    base._require_equal(strict["known_cost_usd"], summary["known_cost_usd"], "strict cost")

    terminal = base._json(blobs["terminal"], "terminal record")
    expected_parent = contract["parent_ledger_sha256"]
    if (
        terminal.get("schema") != "chronos.experiment-a-full-shard-terminal.v1"
        or terminal.get("model") != MODEL
        or terminal.get("reasoning") != REASONING
        or terminal.get("role") != ROLE
        or terminal.get("study_id") != STUDY_ID
        or terminal.get("identity") != contract["identity"]
        or terminal.get("manifest_sha256") != contract["manifest_sha256"]
        or terminal.get("shard_index") != index
        or terminal.get("shard_count") != 30
        or terminal.get("job_ids") != [job["id"] for job in jobs]
        or terminal.get("planned_calls") != sum(job["calls"] for job in jobs)
        or terminal.get("evidence_sha256") != base._sha256(evidence)
        or terminal.get("parent_ledger_sha256") != expected_parent
        or terminal.get("error") is not None
    ):
        raise ValueError(f"Claude s{index:02d} terminal record changed")
    audit = base._json(blobs["audit"], "hosted audit")
    if (
        audit.get("passed") is not True
        or "audit_failed" in audit
        or audit.get("allocation_exhausted") is not False
        or audit.get("stopped_early") is not None
        or audit.get("terminal_error") is not None
        or audit.get("parent_prefix_preserved") is not True
        or audit.get("evidence_sha256") != base._sha256(evidence)
    ):
        raise ValueError(f"Claude s{index:02d} hosted audit did not pass")
    for key, value in contract.items():
        base._require_equal(audit.get(key), value, f"hosted contract field {key}")
    base._require_equal(audit["ledger_audit"], ledger, "hosted ledger audit")
    base._require_equal(audit["structural_audit"], strict, "hosted structural audit")
    base._require_equal(audit["subset"], subset, "hosted subset audit")
    base._require_equal(audit["raw_accounting"], summary, "hosted raw accounting")
    recovery = execution.get("recovery_builder")
    if recovery is not None:
        seed = recovery.SEED.read_bytes()
        if not evidence.startswith(seed):
            raise ValueError(
                f"Claude s{index:02d} final ledger lost its parent seed prefix"
            )
        suffix = [json.loads(line) for line in evidence[len(seed) :].splitlines()]
        base._require_equal(
            audit["new_suffix_accounting"],
            raw_event_summary(suffix),
            f"Claude s{index:02d} hosted suffix accounting",
        )
    else:
        base._require_equal(
            audit["new_suffix_accounting"], summary, "hosted suffix accounting"
        )
    _verify_metadata(execution, record, source, notebook_source, blobs)
    actual = _accounting(jobs, summary)
    base._require_equal(record["accounting"], actual, "shard accounting")
    return {"jobs": jobs, "accounting": actual}


def _verify_static_attestations(manifest: dict) -> None:
    transport_raw = base._read_pinned(
        manifest["transport_attestation"],
        TRANSPORT_ATTESTATION,
        "Claude transport attestation",
    )
    transport = json.loads(transport_raw)
    if (
        transport.get("attestation_sha256")
        != transport_builder._attestation_hash(transport)
        or transport.get("wrapper_count") != 6
        or [item.get("shard_index") for item in transport.get("wrappers", [])]
        != [0, 1, 3, 4, 5, 6]
        or any(item.get("scientific_changes") for item in transport["wrappers"])
    ):
        raise ValueError("Claude transport attestation changed")
    s06_raw = base._read_pinned(
        manifest["s06_repair_attestation"],
        S06_REPAIR_ATTESTATION,
        "Claude s06 repair attestation",
    )
    s06 = json.loads(s06_raw)
    repairs = s06.get("repairs") or []
    if (
        s06.get("attestation_sha256") != s06_builder._attestation_hash(s06)
        or len(repairs) != 1
        or repairs[0].get("shard_index") != 6
        or repairs[0].get("model_run_observed") is not False
        or repairs[0].get("scientific_changes") != []
        or repairs[0].get("unaccounted_quota_usd") != 0.0
        or repairs[0].get("repair_task") != s06_builder.REPAIR_TASK
    ):
        raise ValueError("Claude s06 repair attestation changed")
    resume_raw = base._read_pinned(
        manifest["s03_resume_attestation"],
        S03_RESUME_ATTESTATION,
        "Claude s03 resume attestation",
    )
    resume = json.loads(resume_raw)
    if (
        resume.get("attestation_sha256") != resume_builder._attestation_hash(resume)
        or resume.get("original_execution", {}).get("run_id") != 2728602
        or resume.get("original_execution", {}).get("scientific_status")
        != "incomplete_rejected"
        or resume.get("resume_projection", {})
        .get("excluded_incomplete_tail", {})
        .get("observed_invocations")
        != 4
        or resume.get("resume_execution", {}).get("scientific_parameter_changes")
        != []
    ):
        raise ValueError("Claude s03 resume attestation changed")
    resume_builder.verify(resume)


def _verify_quota(record: dict) -> dict:
    raw = base._read_pinned(
        record,
        POST_BATCH_QUOTA_ATTESTATION,
        "Claude post-batch quota attestation",
    )
    attestation = json.loads(raw)
    artifacts = _artifact_paths(EXECUTIONS[3])
    quota_capture.verify_attestation(
        attestation,
        artifacts["evidence"].read_bytes(),
        artifacts["terminal"].read_bytes(),
    )
    if (
        attestation.get("queried_at_end_utc") != FROZEN_AT
        or attestation.get("run_context", {}).get("task")
        != resume_builder.RESUME_TASK
        or attestation.get("run_context", {}).get("run_id") != RUN_IDS[3]
        or not math.isclose(
            attestation.get("response", {}).get("daily_quota_used_usd"),
            POST_BATCH_OFFICIAL_DAILY_USD,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError("Claude post-batch quota evidence changed")
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
        + 4,
        "scientific_complete_calls": sum(
            item["complete_calls"] for item in accounts
        ),
        "raw_call_complete_events": sum(
            item["complete_calls"] for item in accounts
        )
        + 4,
        "failed_calls": sum(item["failed_calls"] for item in accounts),
        "unknown_cost_calls": sum(
            item["unknown_cost_calls"] for item in accounts
        ),
        "invalid_json_lines": sum(
            item["invalid_json_lines"] for item in accounts
        ),
        "scientific_ledger_events": sum(item["events"] for item in accounts),
        "raw_accounted_events": sum(item["events"] for item in accounts) + 6,
        "scientific_started_attempts": sum(
            item["started_attempts"] for item in accounts
        ),
        "raw_started_attempts": sum(
            item["started_attempts"] for item in accounts
        )
        + 1,
        "excluded_incomplete_tail_invocations": 4,
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
    staged = staged_batch._load()
    quota = json.loads(POST_BATCH_QUOTA_ATTESTATION.read_text())
    shards = [_build_shard_record(execution) for execution in EXECUTIONS]
    manifest = {
        "schema": "chronos.experiment-a-claude-none-batch00-collection.v1",
        "collection_manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "batch": "claude_none_batch00_shards_00_06",
        "model": MODEL,
        "reasoning": REASONING,
        "role": ROLE,
        "study_id": STUDY_ID,
        "prelaunch_manifest": base._file_record(PRELAUNCH_MANIFEST),
        "transport_attestation": base._file_record(TRANSPORT_ATTESTATION),
        "s06_repair_attestation": base._file_record(S06_REPAIR_ATTESTATION),
        "s03_resume_attestation": base._file_record(S03_RESUME_ATTESTATION),
        "post_batch_quota_attestation": base._file_record(
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
    if staged.get("batch_manifest_sha256") != "0342e3716f41867df5a46716b5a49bd6d3929d7b38cd7778a48ea1114f38ef81":
        raise ValueError("Claude prelaunch manifest changed")
    manifest["collection_manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _load_manifest(value: dict | None = None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid Claude batch00 collection schema")
    if manifest.get("collection_manifest_sha256") != _manifest_hash(manifest):
        raise ValueError("Claude batch00 collection self-hash mismatch")
    return manifest


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    staged = staged_batch._load()
    base._read_pinned(
        manifest["prelaunch_manifest"],
        PRELAUNCH_MANIFEST,
        "Claude batch00 prelaunch manifest",
    )
    _verify_static_attestations(manifest)
    quota = _verify_quota(manifest["post_batch_quota_attestation"])
    if (
        manifest["schema"]
        != "chronos.experiment-a-claude-none-batch00-collection.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["batch"] != "claude_none_batch00_shards_00_06"
        or manifest["model"] != MODEL
        or manifest["reasoning"] != REASONING
        or manifest["role"] != ROLE
        or manifest["study_id"] != STUDY_ID
        or staged.get("batch_manifest_sha256")
        != json.loads(PRELAUNCH_MANIFEST.read_text())["batch_manifest_sha256"]
        or manifest["post_batch_quota_attestation_sha256"]
        != quota["attestation_sha256"]
        or manifest["shard_count"] != 7
        or manifest["job_count"] != 161
        or manifest["planned_calls"] != 513
    ):
        raise ValueError("Claude batch00 top-level contract changed")
    records = sorted(manifest["shards"], key=lambda item: item["shard_index"])
    if [record["shard_index"] for record in records] != list(SHARDS):
        raise ValueError("Claude batch00 shard indexes changed")
    verified = [
        _verify_shard(execution, record)
        for execution, record in zip(EXECUTIONS, records)
    ]
    all_ids = [job["id"] for item in verified for job in item["jobs"]]
    previous = _runtime()
    try:
        full_jobs = protocol.jobs_for(MODEL, "study")
        expected = [
            job
            for index in SHARDS
            for job in select_shard(
                full_jobs,
                shard_index=index,
                shard_count=cell_builder.SHARD_COUNT,
            )
        ]
    finally:
        _restore_runtime(previous)
    if (
        len(full_jobs) != 690
        or sum(job["calls"] for job in full_jobs) != 2310
        or len(all_ids) != 161
        or len(all_ids) != len(set(all_ids))
        or set(all_ids) != {job["id"] for job in expected}
        or sum(job["calls"] for job in expected) != 513
    ):
        raise ValueError("Claude batch00 is not its deterministic disjoint subset")
    shards = [
        {"accounting": item["accounting"]}
        for item in verified
    ]
    actual_totals = _totals(shards)
    base._require_equal(manifest["totals"], actual_totals, "collection totals")
    fixed = {
        "completed_jobs": 161,
        "planned_calls": 513,
        "scientific_observed_invocations": 521,
        "raw_observed_invocations": 525,
        "scientific_complete_calls": 519,
        "raw_call_complete_events": 523,
        "failed_calls": 2,
        "unknown_cost_calls": 0,
        "invalid_json_lines": 0,
        "scientific_ledger_events": 847,
        "raw_accounted_events": 853,
        "scientific_started_attempts": 163,
        "raw_started_attempts": 164,
        "excluded_incomplete_tail_invocations": 4,
        "structurally_invalid_call_complete_events": 1,
    }
    if any(actual_totals[key] != expected for key, expected in fixed.items()):
        raise ValueError("Claude batch00 accounting topology changed")
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
        if not math.isclose(
            actual_totals[key], expected, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(f"Claude batch00 cost changed: {key}")
    return {
        "schema": "chronos.experiment-a-claude-none-batch00-verification.v1",
        "collection_manifest_sha256": manifest["collection_manifest_sha256"],
        "model": MODEL,
        "reasoning": REASONING,
        "shards": 7,
        "completed_jobs": actual_totals["completed_jobs"],
        "remaining_jobs": len(full_jobs) - actual_totals["completed_jobs"],
        "planned_calls": actual_totals["planned_calls"],
        "raw_observed_invocations": actual_totals["raw_observed_invocations"],
        "failed_calls": actual_totals["failed_calls"],
        "unknown_cost_calls": actual_totals["unknown_cost_calls"],
        "batch_known_cost_usd": actual_totals["batch_known_cost_usd"],
        "post_batch_official_daily_quota_used_usd": actual_totals[
            "post_batch_official_daily_quota_used_usd"
        ],
        "unattributed_official_minus_raw_known_usd": actual_totals[
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
        "PASS Claude-none batch00: {completed_jobs}/161 jobs, "
        "{planned_calls} planned / {raw_observed_invocations} raw observed "
        "calls, {failed_calls} failed calls, ${batch_known_cost_usd:.7f} "
        "raw-known batch cost, ${post_batch_official_daily_quota_used_usd:.7f} "
        "official daily used, ${unattributed_official_minus_raw_known_usd:.7f} "
        "official-minus-known delta; seven shards disjoint and raw-revalidated"
        .format(**checked)
    )


if __name__ == "__main__":
    main()
