"""Build and attest the evidence-preserving Claude s03 resume task.

Kaggle marked the first s03 execution complete, but the scientific audit
stopped after a paid response whose State payload had an empty
``state_summary``.  The raw archive is immutable accounting evidence.  The
resume seed is the byte-preserving projection of the 15 fully completed jobs;
the six-event incomplete tail remains pinned and is never treated as valid
scientific evidence.
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

import build_experiment_a_cell_v1 as cell_builder
import completion_protocol as engine
import verify_experiment_a_claude_none_batch00 as staged_batch
import verify_experiment_a_gemini_batch00 as stage_base
import verify_experiment_a_qwen_batch00_collection as evidence_base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch00"

MODEL = "anthropic/claude-sonnet-4-6@default"
REASONING = "none"
ROLE = "reasoning_off_sensitivity"
STUDY_ID = "chronos_round2_water4_study_claude_none_v1"
SHARD_INDEX = 3
ORIGINAL_TASK = "chronos-r2-water4-study-claude-none-s03-v1"
RESUME_TASK = "chronos-r2-water4-study-claude-none-s03-resume-v1"
OUTPUT_FOLDER = "round2_water4_study_claude_none_s03_v1"
RUN_ID = 2728602
FROZEN_AT = "2026-09-21T20:18:13+00:00"

RUN_ROOT = (
    RUNS
    / "s03"
    / ORIGINAL_TASK
    / "1"
    / "claude-sonnet-4-6-default"
    / str(RUN_ID)
)
OUTPUT_ROOT = RUN_ROOT / OUTPUT_FOLDER
ARCHIVE = OUTPUT_ROOT / "anthropic_claude-sonnet-4-6@default.jsonl"
AUDIT = OUTPUT_ROOT / "audit.json"
TERMINAL = OUTPUT_ROOT / "terminal.json"
RESULT = RUN_ROOT / (
    ORIGINAL_TASK
    + "-run_id_Run_1_anthropic_claude-sonnet-4-6default.result.json"
)

SEED = RUNS / "s03_completed_projection_seed_v1.jsonl"
SOURCE = GENERATED / "water4_study_claude_none_s03_resume_v1.py"
WRAPPER = GENERATED / "water4_study_claude_none_s03_resume_transport_v1.py"
ATTESTATION = RUNS / "s03_invalid_response_resume_attestation_v1.json"

ARCHIVE_SHA256 = "22c167b66477495077af3bfcfabd14387556712e7f4c71f0e7ded42975b10d69"
ARCHIVE_SUMMARY = {
    "events": 83,
    "invalid_json_lines": 0,
    "accounting_complete": True,
    "started_attempts": 16,
    "completed_jobs": 15,
    "observed_invocations": 51,
    "complete_calls": 51,
    "failed_calls": 0,
    "known_cost_usd": 0.231222,
    "unknown_cost_calls": 0,
}
SEED_SUMMARY = {
    "events": 77,
    "completed_jobs": 15,
    "observed_invocations": 47,
    "known_cost_usd": 0.2173986,
}
TAIL_SUMMARY = {
    "events": 6,
    "observed_invocations": 4,
    "known_cost_usd": 0.0138234,
}


def _event_job_id(event: dict) -> str | None:
    return event.get("job_id") or event.get("job", {}).get("id")


def _parse_lines(raw: bytes) -> tuple[list[bytes], list[dict]]:
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("s03 raw archive must be nonempty newline-terminated JSONL")
    lines = raw.splitlines(keepends=True)
    if any(not line.endswith(b"\n") for line in lines):
        raise ValueError("s03 raw archive contains a nonterminated record")
    events = [json.loads(line) for line in lines]
    if any(not isinstance(event, dict) for event in events):
        raise ValueError("s03 raw archive contains a non-object record")
    return lines, events


def _equal_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)


def project_completed_seed(raw: bytes) -> tuple[bytes, list[dict], list[dict]]:
    """Return exact original lines for completed jobs and the rejected tail."""
    lines, events = _parse_lines(raw)
    completed = {
        event["job"]["id"]
        for event in events
        if event.get("event") == "job_complete"
    }
    seed_lines, seed_events, tail_events = [], [], []
    for line, event in zip(lines, events):
        if _event_job_id(event) in completed:
            seed_lines.append(line)
            seed_events.append(event)
        else:
            tail_events.append(event)
    return b"".join(seed_lines), seed_events, tail_events


def _validate_original() -> dict:
    raw = ARCHIVE.read_bytes()
    if stage_base._sha256(raw) != ARCHIVE_SHA256:
        raise ValueError("Claude s03 raw archive changed")
    _, events = _parse_lines(raw)
    summary = evidence_base.raw_event_summary(events)
    if set(summary) != set(ARCHIVE_SUMMARY):
        raise ValueError("Claude s03 raw-accounting schema changed")
    for key, expected in ARCHIVE_SUMMARY.items():
        observed = summary[key]
        if isinstance(expected, float):
            if not _equal_number(observed, expected):
                raise ValueError(f"Claude s03 raw accounting changed: {key}")
        elif observed != expected:
            raise ValueError(f"Claude s03 raw accounting changed: {key}")

    seed_raw, seed_events, tail = project_completed_seed(raw)
    seed_summary = evidence_base.raw_event_summary(seed_events)
    if (
        len(seed_events) != SEED_SUMMARY["events"]
        or seed_summary["completed_jobs"] != SEED_SUMMARY["completed_jobs"]
        or seed_summary["observed_invocations"]
        != SEED_SUMMARY["observed_invocations"]
        or not _equal_number(
            seed_summary["known_cost_usd"], SEED_SUMMARY["known_cost_usd"]
        )
    ):
        raise ValueError("Claude s03 completed projection changed")
    if [event.get("event") for event in tail] != [
        "job_started",
        "call_complete",
        "call_complete",
        "call_complete",
        "call_complete",
        "job_error",
    ]:
        raise ValueError("Claude s03 rejected tail topology changed")
    tail_ids = {_event_job_id(event) for event in tail}
    if len(tail_ids) != 1 or None in tail_ids:
        raise ValueError("Claude s03 rejected tail spans multiple jobs")
    if any(event.get("attempt") != 1 for event in tail):
        raise ValueError("Claude s03 rejected tail attempt changed")
    calls = tail[1:5]
    if [event.get("step") for event in calls] != [1, 2, 3, 4]:
        raise ValueError("Claude s03 rejected tail call sequence changed")
    for event in calls[:3]:
        engine.validate_response(engine.State(**event["response"]), engine.State)
    try:
        engine.validate_response(engine.State(**calls[3]["response"]), engine.State)
    except ValueError as error:
        if str(error) != "Missing explanation":
            raise ValueError("Claude s03 rejected response failure changed") from error
    else:
        raise ValueError("Claude s03 rejected response unexpectedly validates")
    tail_cost = sum(event["cost_usd"] for event in calls)
    if (
        len(tail) != TAIL_SUMMARY["events"]
        or not _equal_number(tail_cost, TAIL_SUMMARY["known_cost_usd"])
        or tail[-1].get("error_type") != "ValueError"
    ):
        raise ValueError("Claude s03 rejected tail accounting changed")

    audit = json.loads(AUDIT.read_text())
    terminal = json.loads(TERMINAL.read_text())
    result = json.loads(RESULT.read_text())
    expected_error = {
        "code": None,
        "message": "Missing explanation",
        "param": None,
        "status_code": None,
        "type": "ValueError",
    }
    if (
        audit.get("passed") is not False
        or audit.get("stopped_early") != "ValueError('Missing explanation')"
        or audit.get("terminal_error") != expected_error
        or audit.get("evidence_sha256") != ARCHIVE_SHA256
        or audit.get("raw_accounting") != summary
        or terminal.get("error") != expected_error
        or terminal.get("evidence_sha256") != ARCHIVE_SHA256
        or terminal.get("parent_ledger_sha256") is not None
        or result.get("task_name") != ORIGINAL_TASK
        or result.get("verifier_result", {}).get("rewards", {}).get("score")
        != 1.0
    ):
        raise ValueError("Claude s03 failure metadata changed")

    contract = cell_builder.plan_cell(
        model=MODEL,
        reasoning=REASONING,
        role=ROLE,
        study_id=STUDY_ID,
        shard_index=SHARD_INDEX,
        resume_seed=seed_raw,
    )
    seed_audit = contract["resume_ledger"]
    if (
        seed_audit["events"] != SEED_SUMMARY["events"]
        or seed_audit["completed_jobs"] != SEED_SUMMARY["completed_jobs"]
        or seed_audit["observed_invocations"]
        != SEED_SUMMARY["observed_invocations"]
        or seed_audit["failed_calls"] != 0
        or seed_audit["incomplete_jobs"]
        or not _equal_number(
            seed_audit["known_cost_usd"], SEED_SUMMARY["known_cost_usd"]
        )
    ):
        raise ValueError("Claude s03 completed seed failed strict validation")
    return {
        "archive_raw": raw,
        "archive_events": events,
        "archive_summary": summary,
        "seed_raw": seed_raw,
        "seed_events": seed_events,
        "seed_audit": seed_audit,
        "tail": tail,
        "tail_job_id": next(iter(tail_ids)),
    }


@lru_cache(maxsize=1)
def build_source() -> str:
    checked = _validate_original()
    if not SEED.exists() or SEED.read_bytes() != checked["seed_raw"]:
        raise ValueError("write and verify the completed projection seed first")
    return cell_builder.build_source(
        model=MODEL,
        reasoning=REASONING,
        role=ROLE,
        study_id=STUDY_ID,
        shard_index=SHARD_INDEX,
        task_name=RESUME_TASK,
        output_folder=OUTPUT_FOLDER,
        resume_from=SEED,
    )


def build_wrapper() -> str:
    canonical = build_source().encode()
    encoded = base64.b85encode(zlib.compress(canonical, level=9))
    digest = stage_base._sha256(canonical)
    return f'''# Deterministic transport wrapper; resume payload is byte-pinned.
import base64 as _transport_base64
import hashlib as _transport_hashlib
import zlib as _transport_zlib

if False:
    @task(name={RESUME_TASK!r})
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
    raise ValueError("Claude s03 resume payload hash mismatch")
exec(
    compile(
        _transport_payload,
        "water4_study_claude_none_s03_resume_v1.py",
        "exec",
    ),
    globals(),
    globals(),
)
'''


def _literal_assignments(source: str, path: Path) -> dict:
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


def _attestation_hash(value: dict) -> str:
    return stage_base._canonical_hash(
        {key: item for key, item in value.items() if key != "attestation_sha256"}
    )


def build_attestation() -> dict:
    checked = _validate_original()
    source = build_source()
    wrapper = build_wrapper()
    source_values = _literal_assignments(source, SOURCE)
    wrapper_values = _literal_assignments(wrapper, WRAPPER)
    if (
        source_values.get("RESUME_LEDGER") != checked["seed_raw"]
        or source_values.get("MODEL") != MODEL
        or source_values.get("REASONING") != REASONING
        or source_values.get("ROLE") != ROLE
        or source_values.get("STUDY_ID") != STUDY_ID
        or source_values.get("OUTPUT_FOLDER") != OUTPUT_FOLDER
        or not _equal_number(
            source_values.get("CEILING_USD", float("nan")),
            SEED_SUMMARY["known_cost_usd"]
            + cell_builder.INCREMENTAL_CEILINGS_USD[(MODEL, REASONING)],
        )
        or zlib.decompress(
            base64.b85decode(wrapper_values["_TRANSPORT_PAYLOAD_B85"])
        )
        != source.encode()
        or wrapper_values["_TRANSPORT_PAYLOAD_SHA256"]
        != stage_base._sha256(source.encode())
    ):
        raise ValueError("Claude s03 resume source or wrapper contract changed")
    attestation = {
        "schema": "chronos.experiment-a-invalid-response-resume.v1",
        "attestation_sha256": None,
        "frozen_at": FROZEN_AT,
        "prelaunch_manifest": evidence_base._file_record(staged_batch.MANIFEST),
        "original_execution": {
            "task": ORIGINAL_TASK,
            "task_version": 1,
            "run_id": RUN_ID,
            "platform_status": "completed",
            "scientific_status": "incomplete_rejected",
            "raw_archive": evidence_base._file_record(ARCHIVE),
            "audit": evidence_base._file_record(AUDIT),
            "terminal": evidence_base._file_record(TERMINAL),
            "result": evidence_base._file_record(RESULT),
            "raw_accounting": checked["archive_summary"],
        },
        "resume_projection": {
            "rule": "retain exact original JSONL lines only for job IDs with job_complete",
            "seed": evidence_base._file_record(SEED),
            "strict_seed_audit": checked["seed_audit"],
            "excluded_incomplete_tail": {
                "job_id": checked["tail_job_id"],
                "events": TAIL_SUMMARY["events"],
                "observed_invocations": TAIL_SUMMARY["observed_invocations"],
                "known_cost_usd": TAIL_SUMMARY["known_cost_usd"],
                "retained_in_raw_archive": True,
                "counted_in_total_accounting": True,
                "treated_as_valid_scientific_evidence": False,
                "failure": "ValueError: Missing explanation",
            },
        },
        "resume_execution": {
            "task": RESUME_TASK,
            "output_folder": OUTPUT_FOLDER,
            "canonical_source": evidence_base._file_record(SOURCE),
            "transport_wrapper": evidence_base._file_record(WRAPPER),
            "parent_seed_sha256": stage_base._sha256(checked["seed_raw"]),
            "effective_ceiling_usd": source_values["CEILING_USD"],
            "scientific_parameter_changes": [],
            "technical_changes": [
                "new_task_slug",
                "completed_job_projection_embedded_as_resume_seed",
                "zlib_level9_base85_transport_wrapper",
            ],
        },
    }
    attestation["attestation_sha256"] = _attestation_hash(attestation)
    return attestation


def verify(value: dict | None = None) -> dict:
    checked = _validate_original()
    if SEED.read_bytes() != checked["seed_raw"]:
        raise ValueError("Claude s03 completed projection seed changed")
    if SOURCE.read_text() != build_source():
        raise ValueError("Claude s03 resume source changed")
    if WRAPPER.read_text() != build_wrapper():
        raise ValueError("Claude s03 resume transport wrapper changed")
    compile(SOURCE.read_text(), str(SOURCE), "exec")
    compile(WRAPPER.read_text(), str(WRAPPER), "exec")
    attestation = (
        json.loads(ATTESTATION.read_text())
        if value is None
        else copy.deepcopy(value)
    )
    if attestation.get("attestation_sha256") != _attestation_hash(attestation):
        raise ValueError("Claude s03 resume attestation self-hash mismatch")
    expected = build_attestation()
    if attestation != expected:
        raise ValueError("Claude s03 resume attestation changed")
    return attestation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        checked = _validate_original()
        SEED.write_bytes(checked["seed_raw"])
        SOURCE.write_text(build_source())
        WRAPPER.write_text(build_wrapper())
        attestation = build_attestation()
        ATTESTATION.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n"
        )
        print(f"WROTE {SEED} {stage_base._sha256(SEED.read_bytes())}")
        print(f"WROTE {SOURCE} {stage_base._sha256(SOURCE.read_bytes())}")
        print(f"WROTE {WRAPPER} {stage_base._sha256(WRAPPER.read_bytes())}")
        print(f"WROTE {ATTESTATION} {attestation['attestation_sha256']}")
    sealed = verify()
    print(
        "PASS Claude s03 resume: 15 completed jobs projected byte-for-byte; "
        "4 paid invalid-tail calls retained in accounting; attestation "
        + sealed["attestation_sha256"]
    )


if __name__ == "__main__":
    main()
