"""Regenerate exploratory Experiment B results from sealed raw study ledgers.

The collection verifier authenticates hosted outputs and resume chains. This
module independently checks all pinned study bytes and replays the structural
auditor. Complete-cell effects require 180 distinct jobs and 900 trial calls;
sealed failed pilots and stopped studies remain explicit partial dispositions.
Excluded pilot outcomes never enter the analysis; their cost is shown separately.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import audit_experiment_b as auditor
import experiment_b_protocol as protocol
from round2_hosted import parse_jsonl_bytes, raw_event_summary, select_shard
import verify_experiment_b_final_collection_v1 as collection_verifier
import verify_experiment_b_freeze as freeze


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_COLLECTION = HERE / "round2_generated/experiment_b_collection_v1.json"
DEFAULT_OUTPUT = HERE / "round2_analysis/experiment_b_analysis_v1.json"
CHOICES = ("A", "B", "C")
CONDITIONS = ("natural", "attack")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: dict) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _require_money(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite nonnegative amount")
    return float(value)


def _same_money(left: object, right: object, label: str) -> None:
    if not math.isclose(
        _require_money(left, label), _require_money(right, label),
        rel_tol=0, abs_tol=1e-8,
    ):
        raise ValueError(f"{label} disagrees with pinned raw calls")


def _pinned_raw(record: dict) -> bytes:
    relative = Path(record["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("B raw ledger path is not repository-relative")
    path = (ROOT / relative).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError("B raw ledger path escapes the repository")
    raw = path.read_bytes()
    if _sha256(raw) != record["sha256"] or not raw.endswith(b"\n"):
        raise ValueError(f"B raw ledger hash or JSONL termination changed: {relative}")
    return raw


def _choice_counts(rows: list[dict], field: str) -> dict[str, int]:
    counts = Counter(row[field] for row in rows)
    if set(counts) - set(CHOICES):
        raise ValueError("Experiment B contains a choice outside A/B/C")
    return {choice: counts[choice] for choice in CHOICES}


def _summarize_decisions(decisions: list[dict]) -> dict:
    """Require the full 3 x 2 x 30 fresh matrix before describing outcomes."""
    expected_keys = {
        (rotation, condition, rep)
        for rotation in protocol.ROTATIONS
        for condition in CONDITIONS
        for rep in range(1, protocol.REPETITIONS + 1)
    }
    indexed = {}
    for decision in decisions:
        key = (decision["rotation"], decision["condition"], decision["rep"])
        if key not in expected_keys or key in indexed:
            raise ValueError("B decision is unexpected or duplicates a rotation pair")
        literal = decision["literal_choice"]
        if (
            literal not in CHOICES
            or decision["semantic_choice"] != protocol.semantic_choice(key[0], literal)
            or decision["literal_target"] != protocol.ROTATIONS[key[0]][protocol.SEMANTIC_TARGET]
            or decision["semantic_target"] != protocol.SEMANTIC_TARGET
        ):
            raise ValueError("B decision label remapping changed")
        indexed[key] = decision
    if set(indexed) != expected_keys or len(decisions) != 180:
        raise ValueError("B requires exactly 180 complete, unique study decisions")

    by_rotation_condition = {}
    paired_effects = {}
    for rotation in protocol.ROTATIONS:
        mapping = protocol.ROTATIONS[rotation]
        literal_target = mapping[protocol.SEMANTIC_TARGET]
        for condition in CONDITIONS:
            rows = [indexed[rotation, condition, rep] for rep in range(1, 31)]
            literal = _choice_counts(rows, "literal_choice")
            semantic = _choice_counts(rows, "semantic_choice")
            by_rotation_condition[f"rot{rotation}|{condition}"] = {
                "n": 30,
                "semantic_to_literal": mapping,
                "literal_target_letter": literal_target,
                "semantic_choice_counts": semantic,
                "literal_choice_counts": literal,
                "semantic_target_rate": semantic[protocol.SEMANTIC_TARGET] / 30,
                "literal_target_letter_rate": literal[literal_target] / 30,
                "literal_C_rate": literal["C"] / 30,
            }

        natural = [indexed[rotation, "natural", rep] for rep in range(1, 31)]
        attack = [indexed[rotation, "attack", rep] for rep in range(1, 31)]
        gains = sum(
            n["semantic_choice"] != protocol.SEMANTIC_TARGET
            and a["semantic_choice"] == protocol.SEMANTIC_TARGET
            for n, a in zip(natural, attack)
        )
        losses = sum(
            n["semantic_choice"] == protocol.SEMANTIC_TARGET
            and a["semantic_choice"] != protocol.SEMANTIC_TARGET
            for n, a in zip(natural, attack)
        )
        both = sum(
            n["semantic_choice"] == a["semantic_choice"] == protocol.SEMANTIC_TARGET
            for n, a in zip(natural, attack)
        )
        transitions = {
            semantic_n: {
                semantic_a: sum(
                    n["semantic_choice"] == semantic_n
                    and a["semantic_choice"] == semantic_a
                    for n, a in zip(natural, attack)
                )
                for semantic_a in CHOICES
            }
            for semantic_n in CHOICES
        }
        literal_transitions = {
            literal_n: {
                literal_a: sum(
                    n["literal_choice"] == literal_n and a["literal_choice"] == literal_a
                    for n, a in zip(natural, attack)
                )
                for literal_a in CHOICES
            }
            for literal_n in CHOICES
        }
        if gains + losses + both > 30 or sum(map(sum, (row.values() for row in transitions.values()))) != 30:
            raise ValueError("B semantic pair accounting changed")
        if sum(map(sum, (row.values() for row in literal_transitions.values()))) != 30:
            raise ValueError("B literal pair accounting changed")
        literal_C_natural = sum(row["literal_choice"] == "C" for row in natural)
        literal_C_attack = sum(row["literal_choice"] == "C" for row in attack)
        paired_effects[f"rot{rotation}"] = {
            "fresh_pairs": 30,
            "natural_semantic_target_rate": (losses + both) / 30,
            "attack_semantic_target_rate": (gains + both) / 30,
            "attack_minus_natural_semantic_target_rate": (gains - losses) / 30,
            "gains": gains,
            "losses": losses,
            "both_target": both,
            "neither_target": 30 - gains - losses - both,
            "semantic_choice_transition_counts": transitions,
            "literal_choice_transition_counts": literal_transitions,
            "literal_C_natural_rate": literal_C_natural / 30,
            "literal_C_attack_rate": literal_C_attack / 30,
            "literal_C_attack_minus_natural_rate": (literal_C_attack - literal_C_natural) / 30,
            "classification": "exploratory_descriptive_no_hypothesis_test",
        }

    label_susceptibility = {}
    for condition in CONDITIONS:
        semantic_rates = {
            choice: [
                by_rotation_condition[f"rot{rotation}|{condition}"]["semantic_choice_counts"][choice] / 30
                for rotation in protocol.ROTATIONS
            ]
            for choice in CHOICES
        }
        literal_rates = {
            choice: [
                by_rotation_condition[f"rot{rotation}|{condition}"]["literal_choice_counts"][choice] / 30
                for rotation in protocol.ROTATIONS
            ]
            for choice in CHOICES
        }
        label_susceptibility[condition] = {
            "semantic_choice_rates_by_rotation": semantic_rates,
            "literal_letter_rates_by_rotation": literal_rates,
            "semantic_target_rate_range_across_rotations": (
                max(semantic_rates[protocol.SEMANTIC_TARGET])
                - min(semantic_rates[protocol.SEMANTIC_TARGET])
            ),
            "literal_C_rate_range_across_rotations": (
                max(literal_rates["C"]) - min(literal_rates["C"])
            ),
            "semantic_distribution_max_pairwise_total_variation": max(
                sum(abs(semantic_rates[choice][i] - semantic_rates[choice][j]) for choice in CHOICES) / 2
                for i, j in ((0, 1), (0, 2), (1, 2))
            ),
            "interpretation": "Independent rotations; between-rotation ranges include sampling variation.",
        }
    return {
        "by_rotation_condition": by_rotation_condition,
        "fresh_paired_semantic_target_effects": paired_effects,
        "label_susceptibility": label_susceptibility,
    }


def _read_study_shard(
    ledger: dict, expected_jobs: list[dict], *, complete: bool
) -> tuple[list[dict], list[str], dict]:
    """Check a pinned shard against its deterministic job partition and calls."""
    index = ledger["shard_index"]
    expected_ids = {
        job["id"] for job in select_shard(
            expected_jobs, shard_index=index, shard_count=30
        )
    }
    raw = _pinned_raw(ledger)
    events = parse_jsonl_bytes(raw, label=f"B shard {index} raw ledger")
    ids = [event["job"]["id"] for event in events if event.get("event") == "job_complete"]
    if (
        len(ids) != len(set(ids))
        or not set(ids) <= expected_ids
        or sorted(ids) != ledger["completed_job_ids"]
        or (complete and (len(ids) != 6 or set(ids) != expected_ids))
    ):
        raise ValueError(f"B shard {index} is missing or duplicating trial IDs")
    account = raw_event_summary(events)
    unknown = ledger.get("unknown_cost_calls", 0)
    if (
        account["completed_jobs"] != len(ids)
        or account["observed_invocations"] != ledger["observed_invocations"]
        or account["failed_calls"] != ledger["failed_calls"]
        or account["unknown_cost_calls"] != unknown
        or (complete and not account["accounting_complete"])
    ):
        raise ValueError(f"B shard {index} raw accounting changed")
    _same_money(account["known_cost_usd"], ledger["known_cost_usd"], "B shard cost")
    return events, ids, account


def _read_cell(record: dict) -> tuple[dict, dict]:
    model = record["model_id"]
    expected_cell = protocol.cell(model, "study")
    if (
        record["reasoning_id"] != expected_cell["reasoning"]
        or record["cohort_role"] != expected_cell["role"]
        or record["status"] != "complete"
        or record["completed_jobs"] != 180
        or record["planned_calls"] != 900
        or record["partial_study"] is not None
        or record["study_unknown_cost_calls"] != 0
        or record["pilot_unknown_cost_calls"] != 0
        or record["pilot_failed_calls"] != 0
        or record["pilot_failure_type"] is not None
        or not isinstance(record["pilot_receipt_sha256"], str)
    ):
        raise ValueError(f"{model}: B collection cell is not complete at its frozen setting")
    expected_jobs = protocol.jobs_for(model, "study")
    expected_ids = {job["id"] for job in expected_jobs}
    if len(expected_jobs) != 180 or len(expected_ids) != 180 or sum(job["calls"] for job in expected_jobs) != 900:
        raise ValueError(f"{model}: frozen Experiment B job topology changed")
    ledgers = record["raw_ledgers"]
    if len(ledgers) != 30 or {item["shard_index"] for item in ledgers} != set(range(30)):
        raise ValueError(f"{model}: B collection needs exactly 30 distinct raw ledgers")

    events = []
    all_ids = []
    all_costs = []
    all_invocations = 0
    all_failures = 0
    for ledger in sorted(ledgers, key=lambda item: item["shard_index"]):
        shard_events, shard_ids, account = _read_study_shard(
            ledger, expected_jobs, complete=True
        )
        events.extend(shard_events)
        all_ids.extend(shard_ids)
        all_costs.append(account["known_cost_usd"])
        all_invocations += account["observed_invocations"]
        all_failures += account["failed_calls"]

    if len(all_ids) != 180 or len(set(all_ids)) != 180 or set(all_ids) != expected_ids:
        raise ValueError(f"{model}: B full cell has missing or duplicate trial IDs")
    checked = auditor.audit(events, model, "study", require_complete=True)
    if (
        checked["completed_jobs"] != 180
        or checked["planned_calls"] != 900
        or checked["complete_trial_calls"] != 900
        or checked["unknown_cost_calls"] != 0
        or checked["observed_invocations"] != all_invocations
        or checked["failed_calls"] != all_failures
        or record["observed_invocations"] != all_invocations
        or record["failed_calls"] != all_failures
    ):
        raise ValueError(f"{model}: B complete raw audit differs from the collection seal")
    study_cost = math.fsum(all_costs)
    _same_money(study_cost, checked["known_cost_usd"], "B cell auditor cost")
    _same_money(study_cost, record["known_cost_usd"], "B cell collection cost")
    pilot_cost = _require_money(record["pilot_known_cost_usd"], "B excluded pilot cost")
    compact_audit = {
        key: checked[key]
        for key in (
            "completed_jobs", "planned_jobs", "planned_calls", "complete_trial_calls",
            "observed_invocations", "failed_calls", "job_errors", "unknown_cost_calls",
        )
    }
    return checked, {
        "model": model,
        "reasoning": expected_cell["reasoning"],
        "role": expected_cell["role"],
        "status": "complete",
        "raw_audit": compact_audit,
        "cost": {
            "study_known_usd_including_failed_attempts": round(study_cost, 12),
            "excluded_pilot_known_usd_lower_bound": round(pilot_cost, 12),
            "excluded_pilot_unknown_cost_calls": 0,
            "excluded_pilot_observed_invocations": record["pilot_observed_invocations"],
            "excluded_pilot_failed_invocations": 0,
            "all_known_usd_lower_bound": round(study_cost + pilot_cost, 12),
            "all_cost_exact_usd": round(study_cost + pilot_cost, 12),
            "study_observed_invocations": all_invocations,
            "study_failed_invocations": all_failures,
            "study_job_errors": checked["job_errors"],
            "study_unknown_cost_calls": 0,
            "amortized_study_usd_per_completed_decision": study_cost / 180,
        },
        "provenance": {
            "study_id": expected_cell["study_id"],
            "identity": protocol.identity(model, "study"),
            "excluded_pilot_receipt_sha256": record["pilot_receipt_sha256"],
            "raw_ledgers": [
                {
                    "shard_index": ledger["shard_index"],
                    "path": ledger["path"],
                    "sha256": ledger["sha256"],
                }
                for ledger in sorted(ledgers, key=lambda item: item["shard_index"])
            ],
        },
    }


def _failed_pilot_cell(record: dict) -> dict:
    """Keep a sealed failed pilot as unavailable study evidence, never a zero effect."""
    model = record["model_id"]
    expected = protocol.cell(model, "study")
    if (
        record["reasoning_id"] != expected["reasoning"]
        or record["cohort_role"] != expected["role"]
        or record["status"] != "pilot_failed"
        or record["raw_ledgers"] != []
        or record["partial_study"] is not None
        or record["study_unknown_cost_calls"] != 0
        or any(record[key] != 0 for key in (
            "completed_jobs", "planned_calls", "observed_invocations",
            "failed_calls", "known_cost_usd",
        ))
        or record["pilot_unknown_cost_calls"] != 1
        or record["pilot_failed_calls"] != 1
        or not isinstance(record["pilot_observed_invocations"], int)
        or record["pilot_observed_invocations"] < 1
        or not isinstance(record["pilot_failure_type"], str)
        or not record["pilot_failure_type"]
        or record["pilot_receipt_sha256"] is not None
    ):
        raise ValueError(f"{model}: failed B pilot is not an explicit sealed study stop")
    pilot_known = _require_money(record["pilot_known_cost_usd"], "B failed pilot cost")
    return {
        "model": model,
        "reasoning": expected["reasoning"],
        "role": expected["role"],
        "status": "pilot_failed",
        "study_outcomes": None,
        "fresh_paired_semantic_target_effects": None,
        "by_rotation_condition": None,
        "label_susceptibility": None,
        "failure_type": record["pilot_failure_type"],
        "cost": {
            "study_known_usd_including_failed_attempts": 0.0,
            "excluded_pilot_known_usd_lower_bound": round(pilot_known, 12),
            "excluded_pilot_unknown_cost_calls": 1,
            "excluded_pilot_observed_invocations": record["pilot_observed_invocations"],
            "excluded_pilot_failed_invocations": 1,
            "all_known_usd_lower_bound": round(pilot_known, 12),
            "all_cost_exact_usd": None,
            "study_observed_invocations": 0,
            "study_failed_invocations": 0,
            "study_job_errors": 0,
            "study_unknown_cost_calls": 0,
            "amortized_study_usd_per_completed_decision": None,
        },
        "provenance": {
            "study_id": expected["study_id"],
            "identity": protocol.identity(model, "study"),
            "excluded_pilot_receipt_sha256": None,
            "raw_ledgers": [],
        },
    }


def _partial_choice_counts(decisions: list[dict]) -> dict:
    """Show observed counts only; stopped collection cannot support full-panel rates."""
    grouped = {
        (rotation, condition): []
        for rotation in protocol.ROTATIONS for condition in CONDITIONS
    }
    for decision in decisions:
        key = (decision["rotation"], decision["condition"])
        if key not in grouped:
            raise ValueError("B partial study contains an unexpected decision")
        if decision["semantic_choice"] != protocol.semantic_choice(
            decision["rotation"], decision["literal_choice"]
        ):
            raise ValueError("B partial study label remapping changed")
        grouped[key].append(decision)
    result = {}
    for (rotation, condition), rows in grouped.items():
        if len(rows) > 30:
            raise ValueError("B partial study exceeds a frozen rotation cell")
        result[f"rot{rotation}|{condition}"] = {
            "observed_decisions": len(rows),
            "missing_from_frozen_30": 30 - len(rows),
            "semantic_choice_counts": _choice_counts(rows, "semantic_choice"),
            "literal_choice_counts": _choice_counts(rows, "literal_choice"),
        }
    return result


def _partial_study_cell(record: dict) -> dict:
    """Replay observed partial raw evidence without imputing a 30-pair effect."""
    model = record["model_id"]
    expected = protocol.cell(model, "study")
    complete_ledgers = record["raw_ledgers"]
    stopped = record["partial_study"]
    if (
        record["reasoning_id"] != expected["reasoning"]
        or record["cohort_role"] != expected["role"]
        or record["status"] != "study_partial"
        or not isinstance(complete_ledgers, list)
        or len(complete_ledgers) >= 30
        or (stopped is not None and not isinstance(stopped, dict))
        or record["pilot_unknown_cost_calls"] != 0
        or record["pilot_failed_calls"] != 0
        or record["pilot_failure_type"] is not None
        or not isinstance(record["pilot_receipt_sha256"], str)
    ):
        raise ValueError(f"{model}: B partial study has no verified passed-pilot disposition")
    indices = [ledger["shard_index"] for ledger in complete_ledgers]
    if (
        len(indices) != len(set(indices))
        or any(type(index) is not int or not 0 <= index < 30 for index in indices)
        or (stopped is not None and (
            type(stopped.get("shard_index")) is not int
            or not 0 <= stopped["shard_index"] < 30
            or stopped["shard_index"] in indices
        ))
        or record["planned_calls"] != 30 * (len(indices) + (stopped is not None))
    ):
        raise ValueError(f"{model}: B partial study shard partition changed")
    expected_jobs = protocol.jobs_for(model, "study")
    events, all_ids, all_costs = [], [], []
    invocations = failures = unknown = 0
    for ledger in [*complete_ledgers, *([stopped] if stopped is not None else [])]:
        shard_events, ids, account = _read_study_shard(
            ledger, expected_jobs, complete=ledger is not stopped
        )
        events.extend(shard_events)
        all_ids.extend(ids)
        all_costs.append(account["known_cost_usd"])
        invocations += account["observed_invocations"]
        failures += account["failed_calls"]
        unknown += account["unknown_cost_calls"]
    if (
        len(all_ids) != len(set(all_ids))
        or record["completed_jobs"] != len(all_ids)
        or record["observed_invocations"] != invocations
        or record["failed_calls"] != failures
        or record["study_unknown_cost_calls"] != unknown
    ):
        raise ValueError(f"{model}: B partial study raw trial/accounting totals changed")
    checked = auditor.audit(events, model, "study", require_complete=False)
    if (
        checked["completed_jobs"] != len(all_ids)
        or checked["complete_trial_calls"] != 5 * len(all_ids)
        or checked["observed_invocations"] != invocations
        or checked["failed_calls"] != failures
        or checked["unknown_cost_calls"] != unknown
    ):
        raise ValueError(f"{model}: B partial study structural replay differs from raw")
    known_study = math.fsum(all_costs)
    _same_money(known_study, checked["known_cost_usd"], "B partial auditor cost")
    _same_money(known_study, record["known_cost_usd"], "B partial collection cost")
    known_pilot = _require_money(record["pilot_known_cost_usd"], "B partial pilot cost")
    known_total = known_study + known_pilot
    return {
        "model": model,
        "reasoning": expected["reasoning"],
        "role": expected["role"],
        "status": "study_partial",
        "study_outcomes": "incomplete_observed_counts_only",
        "fresh_paired_semantic_target_effects": None,
        "by_rotation_condition": None,
        "label_susceptibility": None,
        "observed_partial_choice_counts_by_rotation_condition": _partial_choice_counts(
            checked["decisions"]
        ),
        "raw_audit": {
            key: checked[key]
            for key in (
                "completed_jobs", "planned_jobs", "complete_trial_calls",
                "observed_invocations", "failed_calls", "job_errors",
                "unknown_cost_calls",
            )
        },
        "cost": {
            "study_known_usd_including_failed_attempts": round(known_study, 12),
            "study_unknown_cost_calls": unknown,
            "study_observed_invocations": invocations,
            "study_failed_invocations": failures,
            "study_job_errors": checked["job_errors"],
            "excluded_pilot_known_usd_lower_bound": round(known_pilot, 12),
            "excluded_pilot_unknown_cost_calls": 0,
            "excluded_pilot_observed_invocations": record["pilot_observed_invocations"],
            "excluded_pilot_failed_invocations": 0,
            "all_known_usd_lower_bound": round(known_total, 12),
            "all_cost_exact_usd": round(known_total, 12) if unknown == 0 else None,
            "amortized_study_usd_per_completed_decision": None,
        },
        "provenance": {
            "study_id": expected["study_id"],
            "identity": protocol.identity(model, "study"),
            "excluded_pilot_receipt_sha256": record["pilot_receipt_sha256"],
            "raw_ledgers": [
                {"shard_index": ledger["shard_index"], "path": ledger["path"],
                 "sha256": ledger["sha256"]}
                for ledger in complete_ledgers
            ],
            "stopped_shard": (
                {"shard_index": stopped["shard_index"], "path": stopped["path"],
                 "sha256": stopped["sha256"]}
                if stopped is not None else None
            ),
        },
    }


def build_analysis(collection_path: Path = DEFAULT_COLLECTION) -> dict:
    frozen = freeze.verify()
    collection_path = Path(collection_path)
    if not collection_path.is_file():
        raise FileNotFoundError(f"Experiment B collection seal is absent: {collection_path}")
    collection = collection_verifier.verify_collection_manifest(collection_path)
    records = collection["cells"]
    if not isinstance(records, list) or len(records) != 4:
        raise ValueError("B canonical analysis requires four explicitly sealed cell dispositions")
    by_model = {record["model_id"]: record for record in records}
    if len(by_model) != 4 or set(by_model) != set(protocol.CELLS):
        raise ValueError("B collection roster differs from the frozen four settings")
    if collection["status"] not in ("complete_raw_revalidated", "partial_raw_revalidated"):
        raise ValueError("B collection has no final raw-revalidated disposition")
    cells = {}
    for model in protocol.CELLS:
        record = by_model[model]
        if record["status"] == "complete":
            checked, evidence = _read_cell(record)
            cells[model] = {**evidence, **_summarize_decisions(checked["decisions"])}
        elif record["status"] == "pilot_failed":
            cells[model] = _failed_pilot_cell(record)
        elif record["status"] == "study_partial":
            cells[model] = _partial_study_cell(record)
        else:
            raise ValueError(f"{model}: B cell has no final verified disposition")

    complete_count = sum(cell["status"] == "complete" for cell in cells.values())
    pilot_failed_count = sum(cell["status"] == "pilot_failed" for cell in cells.values())
    study_partial_count = sum(cell["status"] == "study_partial" for cell in cells.values())
    expected_collection_status = (
        "complete_raw_revalidated" if complete_count == 4 else "partial_raw_revalidated"
    )
    if collection["status"] != expected_collection_status:
        raise ValueError("B analysis and collection completion status disagree")

    primary = {
        model: cells[model]
        for model in protocol.CELLS
        if protocol.cell(model)["role"] == "matched_non_off_primary"
    }
    sensitivity = next(
        cells[model]
        for model in protocol.CELLS
        if protocol.cell(model)["role"] == "reasoning_off_sensitivity"
    )
    study_costs = [cell["cost"]["study_known_usd_including_failed_attempts"] for cell in cells.values()]
    pilot_costs = [cell["cost"]["excluded_pilot_known_usd_lower_bound"] for cell in cells.values()]
    unknown_pilot_calls = sum(
        cell["cost"]["excluded_pilot_unknown_cost_calls"] for cell in cells.values()
    )
    unknown_study_calls = sum(
        cell["cost"]["study_unknown_cost_calls"] for cell in cells.values()
    )
    known_total = math.fsum((*study_costs, *pilot_costs))
    result = {
        "schema": "chronos.experiment-b-analysis.v1",
        "analysis_sha256": None,
        "status": collection["status"],
        "classification": "exploratory_descriptive",
        "source": "sealed_raw_experiment_b_collection",
        "frozen_manifest_sha256": frozen["manifest_sha256"],
        "collection_manifest": {
            "path": str(collection_path.resolve().relative_to(ROOT.resolve())),
            "sha256": _sha256(collection_path.read_bytes()),
        },
        "semantic_target": protocol.SEMANTIC_TARGET,
        "matched_non_off_primary": primary,
        "unavailable_matched_primary": {
            **protocol.UNAVAILABLE_PRIMARY,
            "effect": None,
            "reason": "No approved matched non-off Claude setting; Claude-none is not a substitute.",
        },
        "claude_none_sensitivity": sensitivity,
        "aggregate_accounting": {
            "frozen_executable_study_jobs": 720,
            "frozen_executable_planned_calls": 3600,
            "completed_study_cells": complete_count,
            "pilot_failed_study_cells": pilot_failed_count,
            "study_partial_cells": study_partial_count,
            "completed_study_jobs": sum(record["completed_jobs"] for record in records),
            "completed_study_trial_calls": 5 * sum(record["completed_jobs"] for record in records),
            "attempted_shard_planned_calls": sum(record["planned_calls"] for record in records),
            "study_observed_invocations": sum(cell["cost"]["study_observed_invocations"] for cell in cells.values()),
            "study_failed_invocations": sum(cell["cost"]["study_failed_invocations"] for cell in cells.values()),
            "study_known_usd_including_failed_attempts": round(math.fsum(study_costs), 12),
            "study_unknown_cost_calls": unknown_study_calls,
            "excluded_pilot_known_usd_lower_bound": round(math.fsum(pilot_costs), 12),
            "excluded_pilot_unknown_cost_calls": unknown_pilot_calls,
            "excluded_pilot_observed_invocations": sum(
                cell["cost"]["excluded_pilot_observed_invocations"] for cell in cells.values()
            ),
            "excluded_pilot_failed_invocations": sum(
                cell["cost"]["excluded_pilot_failed_invocations"] for cell in cells.values()
            ),
            "all_known_usd_lower_bound": round(known_total, 12),
            "all_cost_exact_usd": (
                round(known_total, 12)
                if unknown_pilot_calls + unknown_study_calls == 0 else None
            ),
        },
        "qualifications": [
            "All B outcome comparisons are exploratory-descriptive; no confirmatory p-values are assigned.",
            "The 30 natural/attack pairs are fresh within each rotation; repetition indices do not pair different rotations.",
            "Semantic and literal-letter distributions are both reported because a fixed literal-letter preference can mimic semantic stability or change.",
            "Claude-none is a reasoning-off sensitivity outside the matched non-off primary roster.",
            "Failed pilots have no study outcomes or zero-effect imputation; their verified known charges are a lower bound when failed-call cost is unknown.",
            "Stopped study cells report observed choice counts and raw accounting only; no incomplete-cell rates, pair effects, or label-susceptibility contrasts are estimated.",
            "Pilot outcomes are excluded; known pilot charges and charged study failures are included in cost accounting.",
            "The tree fixture has no objective correctness key.",
        ],
    }
    result["analysis_sha256"] = _canonical_hash(
        {key: value for key, value in result.items() if key != "analysis_sha256"}
    )
    return result


def verify_analysis_file(path: Path = DEFAULT_OUTPUT) -> dict:
    saved = json.loads(Path(path).read_text())
    body = {key: value for key, value in saved.items() if key != "analysis_sha256"}
    if saved.get("analysis_sha256") != _canonical_hash(body):
        raise ValueError("Experiment B analysis self-hash changed")
    actual = build_analysis()
    if saved != actual:
        raise ValueError("Experiment B analysis differs from fresh sealed raw regeneration")
    return actual


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.output and args.verify:
        parser.error("choose --output or --verify")
    if args.verify:
        result = verify_analysis_file(args.verify)
        print(f"PASS Experiment B analysis {result['analysis_sha256']}")
        return
    result = build_analysis()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
        print(f"WROTE {args.output} {result['analysis_sha256']}")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
