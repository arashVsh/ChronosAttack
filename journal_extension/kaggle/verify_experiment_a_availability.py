"""Verify Experiment A's pre-outcome endpoint-availability amendment."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

import verify_experiment_a_freeze as fixture_verifier
import verify_round2_claude_preflight_retry_result as claude_verifier
import verify_round2_terra_study_collection as terra_verifier
import water_supply_protocol as protocol


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "experiment_a_availability_v1.json"
AMENDMENT = (
    ROOT
    / "specs/journal-extension-sep14/"
    "round2-experiment-a-availability-amendment-2026-09-20.md"
)
FIXTURE_MANIFEST = HERE / "experiment_a_manifest_v1.json"
ROUND2_MANIFEST = HERE / "round2_manifest_v1.json"
CLAUDE_RESULT = (
    HERE / "round2_generated/claude_preflight_retry_result_v1.json"
)
TERRA_COLLECTION = HERE / "round2_generated/terra_study_collection_v1.json"
FROZEN_AT = "2026-09-20T21:28:15+03:30"

EXPECTED_FILE_HASHES = {
    "amendment": "16b473be87357c7f0a181c0b4a3d7d227e87ad30d42a6db58ad982469758c895",
    "fixture_manifest": "81a78601f994c32348b3716749904206da39f11ab0decd14e0fa7ab0e250f92d",
    "round2_manifest": "ed050bc39274cabd4f15545bf6078b36aeb0a40930458f12d11bc5e0cfeeb9b2",
    "claude_result": "184aef90ac6f466fd6d0e66dbc9364600708eab5dd67abe81d00ed0c6c1b85d7",
    "terra_collection": "30d3af176306eec2256bcb33177f6aa6b4e5bde8f65bf5d6480dc2b301b38747",
}
ARTIFACT_PATHS = {
    "amendment": AMENDMENT,
    "fixture_manifest": FIXTURE_MANIFEST,
    "round2_manifest": ROUND2_MANIFEST,
    "claude_result": CLAUDE_RESULT,
    "terra_collection": TERRA_COLLECTION,
}
FILE_RECORD_KEYS = {"path", "sha256", "bytes"}
TOP_LEVEL_KEYS = {
    "schema",
    "manifest_sha256",
    "frozen_at",
    "status",
    "artifacts",
    "trigger",
    "roles",
    "pilots",
    "collection",
    "multiplicity",
    "guardrails",
    "collection_status",
}

TERRA = "openai/gpt-5.6-terra"
CLAUDE = "anthropic/claude-sonnet-4-6@default"
GEMINI = "google/gemini-3.6-flash"
QWEN = "qwen/qwen3-235b-a22b-instruct-2507"
PRIMARY = (
    (TERRA, "low"),
    (GEMINI, "minimal"),
    (QWEN, "low"),
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def _manifest_hash(manifest: dict) -> str:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return _canonical_hash(body)


def _repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _file_record(path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": _repo_relative(path),
        "sha256": _sha256(raw),
        "bytes": len(raw),
    }


def _primary_roles() -> list[dict]:
    return [
        {
            "model": model,
            "reasoning": reasoning,
            "role": "matched_non_off_primary",
            "pilot_required": True,
            "study_jobs": 690,
            "study_calls": 2310,
        }
        for model, reasoning in PRIMARY
    ]


def _pilot_cells() -> list[dict]:
    cells = [
        {
            "model": model,
            "reasoning": reasoning,
            "role": "matched_non_off_primary",
        }
        for model, reasoning in PRIMARY
    ]
    cells.append(
        {
            "model": CLAUDE,
            "reasoning": "none",
            "role": "reasoning_off_sensitivity",
        }
    )
    return [dict(cell, jobs=2, calls=10, ceiling_usd=0.25) for cell in cells]


def build_manifest() -> dict:
    manifest = {
        "schema": "chronos.experiment-a-availability.v1",
        "manifest_sha256": None,
        "frozen_at": FROZEN_AT,
        "status": "availability_frozen_no_calls",
        "artifacts": {
            label: _file_record(path) for label, path in ARTIFACT_PATHS.items()
        },
        "trigger": {
            "claude_status": "operationally_unavailable_after_bounded_retry",
            "claude_retry_run_id": 2671436,
            "claude_result_manifest_sha256": (
                "f9700806f3009520628aa818114aeaf09b7688ad1054f3e33d14bcef8264cdf9"
            ),
            "resolved_incremental_cost_usd": 0.0,
            "receipt_issued": False,
            "low_authorized": False,
            "further_retry_authorized": False,
            "experiment_a_outcomes_observed": 0,
        },
        "roles": {
            "matched_primary": _primary_roles(),
            "unavailable_primary": {
                "model": CLAUDE,
                "required_policy": "lowest_supported_non_off",
                "status": "operationally_unavailable_after_bounded_retry",
                "study_jobs": 0,
                "study_calls": 0,
            },
            "sensitivity": {
                "model": CLAUDE,
                "reasoning": "none",
                "role": "reasoning_off_sensitivity",
                "authorization": "full_cell_requires_passed_excluded_pilot",
                "study_jobs": 690,
                "study_calls": 2310,
            },
        },
        "pilots": {
            "status": "not_started",
            "selection": "stateful_natural_rep1_and_stateful_attack_rep1",
            "attempts_per_job": 1,
            "sdk_max_retries": 0,
            "transport_wait_seconds": 0,
            "outcome_bearing": False,
            "confirmation_exclusion": "always_excluded",
            "cells": _pilot_cells(),
            "total_jobs": 8,
            "total_calls": 40,
            "per_cell_ceiling_usd": 0.25,
            "aggregate_ceiling_usd": 1.0,
            "prior_daily_cost_usd": 8.555856,
            "maximum_daily_exposure_usd": 9.555856,
            "daily_credit_limit_usd": 10.0,
        },
        "collection": {
            "matched_primary_models": [model for model, _ in PRIMARY],
            "matched_primary_jobs": 2070,
            "matched_primary_calls": 6930,
            "unavailable_matched_models": [CLAUDE],
            "sensitivity_models": [CLAUDE],
            "sensitivity_jobs": 690,
            "sensitivity_calls": 2310,
            "maximum_executable_jobs": 2760,
            "maximum_executable_calls": 9240,
            "full_cell_status": "not_started",
        },
        "multiplicity": {
            "method": "holm",
            "planned_family_size": 8,
            "evaluable_matched_hypotheses": 6,
            "unavailable_matched_hypotheses": 2,
            "structural_p_one_for_adjustment_only": 2,
            "claude_none_in_primary_family": False,
            "model_pooling": "none_for_primary_tests",
        },
        "guardrails": {
            "fixture_manifest_sha256": (
                "92b855e78fd338d0f56063b44508d7c45b9d296035094b2b6c6be53fbcfe3af7"
            ),
            "fixture_changes_authorized": False,
            "setting_fallback_authorized": False,
            "claude_matched_retry_authorized": False,
            "completed_job_replay_authorized": False,
            "unknown_cost_stops": True,
            "outcome_dependent_stopping": False,
            "task_sources_must_be_pinned_before_upload": True,
        },
        "collection_status": "not_started",
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _read_pinned(record: dict, expected_path: Path, label: str) -> bytes:
    if set(record) != FILE_RECORD_KEYS:
        raise ValueError(f"invalid artifact record: {label}")
    path = (ROOT / record["path"]).resolve()
    if path != expected_path.resolve():
        raise ValueError(f"artifact path changed: {label}")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
        raise ValueError(f"artifact hash/size mismatch: {label}")
    if record["sha256"] != EXPECTED_FILE_HASHES[label]:
        raise ValueError(f"frozen artifact hash changed: {label}")
    return raw


def _load_manifest(value: dict | None) -> dict:
    manifest = (
        json.loads(MANIFEST.read_text()) if value is None else copy.deepcopy(value)
    )
    if set(manifest) != TOP_LEVEL_KEYS:
        raise ValueError("invalid experiment-A availability schema")
    if _manifest_hash(manifest) != manifest["manifest_sha256"]:
        raise ValueError("experiment-A availability self-hash mismatch")
    if (
        manifest["schema"] != "chronos.experiment-a-availability.v1"
        or manifest["frozen_at"] != FROZEN_AT
        or manifest["status"] != "availability_frozen_no_calls"
        or manifest["collection_status"] != "not_started"
    ):
        raise ValueError("experiment-A availability top-level contract changed")
    return manifest


def _verify_dependencies(blobs: dict[str, bytes]) -> None:
    fixture = fixture_verifier.verify()
    if (
        fixture["status"] != "fixture_frozen_no_calls"
        or fixture["total_jobs"] != 2760
        or fixture["total_calls"] != 9240
    ):
        raise ValueError("experiment-A fixture verification changed")
    claude = claude_verifier.verify()
    if (
        claude["status"] != "operationally_unavailable_after_bounded_retry"
        or claude["run_id"] != 2671436
        or claude["resolved_incremental_cost_usd"] != 0.0
        or claude["receipt_issued"]
        or claude["further_retry_authorized"]
    ):
        raise ValueError("Claude terminal availability trigger changed")
    terra = terra_verifier.verify()
    if (
        terra["model"] != TERRA
        or terra["reasoning"] != "low"
        or terra["completed_jobs"] != 690
    ):
        raise ValueError("Terra matched-setting evidence changed")

    round2 = json.loads(blobs["round2_manifest"])
    rows = {row["model"]: row for row in round2["primary_matrix"]}
    if (
        rows[GEMINI]
        != {"model": GEMINI, "reasoning": "minimal", "status": "complete"}
        or rows[QWEN]
        != {"model": QWEN, "reasoning": "low", "status": "complete"}
    ):
        raise ValueError("retained Gemini/Qwen reasoning settings changed")


def _verify_pilot_topology(cells: list[dict]) -> None:
    old_models = protocol.engine.MODELS
    old_settings = protocol.engine.CALL_SETTINGS
    old_study_id = protocol.engine.STUDY_ID
    try:
        protocol.engine.MODELS = tuple(cell["model"] for cell in cells)
        for cell in cells:
            protocol.engine.STUDY_ID = (
                "chronos_round2_water4_compatibility_"
                + cell["role"]
                + "_v1"
            )
            protocol.engine.CALL_SETTINGS = dict(
                old_settings, reasoning=cell["reasoning"]
            )
            selected = [
                job
                for job in protocol.jobs_for(cell["model"], "study")
                if job["mode"] == "stateful"
                and job["condition"] in {"natural", "attack"}
                and job["rep"] == 1
            ]
            if (
                len(selected) != 2
                or sum(job["calls"] for job in selected) != 10
                or {job["condition"] for job in selected}
                != {"natural", "attack"}
                or any(job["calls"] != 5 for job in selected)
            ):
                raise ValueError("experiment-A pilot topology changed")
    finally:
        protocol.engine.MODELS = old_models
        protocol.engine.CALL_SETTINGS = old_settings
        protocol.engine.STUDY_ID = old_study_id


def verify(value: dict | None = None) -> dict:
    manifest = _load_manifest(value)
    if set(manifest["artifacts"]) != set(ARTIFACT_PATHS):
        raise ValueError("experiment-A availability artifact set changed")
    blobs = {
        label: _read_pinned(manifest["artifacts"][label], path, label)
        for label, path in ARTIFACT_PATHS.items()
    }
    _verify_dependencies(blobs)

    expected_trigger = build_manifest()["trigger"]
    expected_roles = build_manifest()["roles"]
    expected_pilots = build_manifest()["pilots"]
    expected_collection = build_manifest()["collection"]
    expected_multiplicity = build_manifest()["multiplicity"]
    expected_guardrails = build_manifest()["guardrails"]
    for label, expected in (
        ("trigger", expected_trigger),
        ("roles", expected_roles),
        ("pilots", expected_pilots),
        ("collection", expected_collection),
        ("multiplicity", expected_multiplicity),
        ("guardrails", expected_guardrails),
    ):
        if manifest[label] != expected:
            raise ValueError(f"experiment-A availability {label} changed")

    cells = manifest["pilots"]["cells"]
    _verify_pilot_topology(cells)
    if (
        sum(cell["jobs"] for cell in cells) != 8
        or sum(cell["calls"] for cell in cells) != 40
        or not math.isclose(
            sum(cell["ceiling_usd"] for cell in cells),
            manifest["pilots"]["aggregate_ceiling_usd"],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or manifest["pilots"]["maximum_daily_exposure_usd"]
        > manifest["pilots"]["daily_credit_limit_usd"]
    ):
        raise ValueError("experiment-A pilot allocation changed")
    return {
        "schema": "chronos.experiment-a-availability-verification.v1",
        "manifest_sha256": manifest["manifest_sha256"],
        "status": manifest["status"],
        "pilot_cells": len(cells),
        "pilot_jobs": manifest["pilots"]["total_jobs"],
        "pilot_calls": manifest["pilots"]["total_calls"],
        "matched_primary_models": len(
            manifest["collection"]["matched_primary_models"]
        ),
        "matched_primary_jobs": manifest["collection"]["matched_primary_jobs"],
        "matched_primary_calls": manifest["collection"]["matched_primary_calls"],
        "sensitivity_jobs": manifest["collection"]["sensitivity_jobs"],
        "sensitivity_calls": manifest["collection"]["sensitivity_calls"],
        "maximum_daily_exposure_usd": manifest["pilots"]
        ["maximum_daily_exposure_usd"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        manifest = build_manifest()
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"WROTE {MANIFEST}")
    checked = verify()
    print(
        "EXPERIMENT A AVAILABILITY FROZEN: {matched_primary_models} matched "
        "non-off primary models ({matched_primary_jobs} jobs / "
        "{matched_primary_calls} calls), Claude matched cell unavailable, "
        "Claude none sensitivity {sensitivity_jobs} jobs / {sensitivity_calls} "
        "calls contingent on pilot; {pilot_cells} excluded pilots / "
        "{pilot_calls} calls; maximum current-day exposure "
        "${maximum_daily_exposure_usd:.6f}".format(**checked)
    )


if __name__ == "__main__":
    main()
