"""Build the second evidence-preserving Claude-none shard-21 resume."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path

import build_experiment_a_claude_none_s21_resume_v1 as base


HERE = Path(__file__).resolve().parent
GENERATED = HERE / "round2_generated"
RUNS = HERE / "round2_runs_20260920/experiment_a_claude_none_batch06"

SHARD_INDEX = 21
ORIGINAL_TASK = "chronos-r2-water4-study-claude-none-s21-resume-v1"
RESUME_TASK = "chronos-r2-water4-study-claude-none-s21-resume2-v1"
OUTPUT_FOLDER = "round2_water4_study_claude_none_s21_v1"
RUN_ID = 2780203
FROZEN_AT = "2026-09-22T14:49:24+00:00"

RUN_ROOT = (
    RUNS
    / "s21_resume"
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

SEED = RUNS / "s21_completed_projection_seed_v2.jsonl"
SOURCE = GENERATED / "water4_study_claude_none_s21_resume2_v1.py"
WRAPPER = GENERATED / "water4_study_claude_none_s21_resume2_transport_v1.py"
ATTESTATION = RUNS / "s21_invalid_response_resume2_attestation_v1.json"

ARCHIVE_SHA256 = "d5846d7fc300ced4d83df5290b176d71d7fe07e299885da5d99d5f9f720bfe47"
ARCHIVE_SUMMARY = {
    "events": 42,
    "invalid_json_lines": 0,
    "accounting_complete": True,
    "started_attempts": 8,
    "completed_jobs": 7,
    "observed_invocations": 26,
    "complete_calls": 26,
    "failed_calls": 0,
    "known_cost_usd": 0.1180959,
    "unknown_cost_calls": 0,
}
SEED_SUMMARY = {
    "events": 37,
    "completed_jobs": 7,
    "observed_invocations": 23,
    "known_cost_usd": 0.1064799,
}
TAIL_SUMMARY = {
    "events": 5,
    "observed_invocations": 3,
    "known_cost_usd": 0.011616,
}
TAIL_STEPS = (1, 2, 3)
EXPECTED_PARENT_LEDGER_SHA256 = (
    "dcbd13ee4fc6c610c5ad125f0b3b1765a914149f084a6fd6006ade90653b7bcd"
)

PATCHES = {
    "SHARD_INDEX": SHARD_INDEX,
    "ORIGINAL_TASK": ORIGINAL_TASK,
    "RESUME_TASK": RESUME_TASK,
    "OUTPUT_FOLDER": OUTPUT_FOLDER,
    "RUN_ID": RUN_ID,
    "FROZEN_AT": FROZEN_AT,
    "RUN_ROOT": RUN_ROOT,
    "OUTPUT_ROOT": OUTPUT_ROOT,
    "ARCHIVE": ARCHIVE,
    "AUDIT": AUDIT,
    "TERMINAL": TERMINAL,
    "RESULT": RESULT,
    "SEED": SEED,
    "SOURCE": SOURCE,
    "WRAPPER": WRAPPER,
    "ATTESTATION": ATTESTATION,
    "ARCHIVE_SHA256": ARCHIVE_SHA256,
    "ARCHIVE_SUMMARY": ARCHIVE_SUMMARY,
    "SEED_SUMMARY": SEED_SUMMARY,
    "TAIL_SUMMARY": TAIL_SUMMARY,
    "TAIL_STEPS": TAIL_STEPS,
    "EXPECTED_PARENT_LEDGER_SHA256": EXPECTED_PARENT_LEDGER_SHA256,
}


@contextmanager
def _resume2_base():
    previous = {name: getattr(base, name) for name in PATCHES}
    base.build_source.cache_clear()
    for name, value in PATCHES.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        base.build_source.cache_clear()
        for name, value in previous.items():
            setattr(base, name, value)


def _validate_original() -> dict:
    with _resume2_base():
        return base._validate_original()


@lru_cache(maxsize=1)
def build_source() -> str:
    with _resume2_base():
        return base.build_source()


def build_wrapper() -> str:
    with _resume2_base():
        return base.build_wrapper()


def _literal_assignments(source: str, path: Path) -> dict:
    return base._literal_assignments(source, path)


def _attestation_hash(value: dict) -> str:
    return base._attestation_hash(value)


def build_attestation() -> dict:
    with _resume2_base():
        return base.build_attestation()


def verify(value: dict | None = None) -> dict:
    with _resume2_base():
        return base.verify(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    with _resume2_base():
        checked = base._validate_original()
        if args.write:
            outputs = (
                (SEED, checked["seed_raw"]),
                (SOURCE, None),
                (WRAPPER, None),
            )
            for path, raw in outputs:
                if raw is None:
                    raw = (
                        base.build_source().encode()
                        if path == SOURCE
                        else base.build_wrapper().encode()
                    )
                if path.exists() and path.read_bytes() != raw:
                    raise ValueError(
                        f"refusing to overwrite different file: {path}"
                    )
                path.write_bytes(raw)
                print(f"WROTE {path} {base.stage_base._sha256(raw)}")
            attestation = base.build_attestation()
            ATTESTATION.write_text(
                json.dumps(attestation, indent=2, sort_keys=True) + "\n"
            )
            print(f"WROTE {ATTESTATION} {attestation['attestation_sha256']}")
        checked_attestation = base.verify()
    print(
        "PASS Claude s21 resume2: 7 completed jobs preserved; 3-call invalid "
        f"tail accounted; attestation "
        f"{checked_attestation['attestation_sha256']}"
    )


if __name__ == "__main__":
    main()
